"""Wire quality-case execution into the orchestration (``05-4`` close-out).

Why this module exists
----------------------
``platform.quality.service.QualityService`` already compiles rules to read-only
SQL and persists results, but nothing triggers it — it could only be called
directly, which is what the integration test does. So quality had no trigger
path and the audit trail of "who ran which rule when" was empty. This supplies
the ``JobType.QUALITY`` handler, mirroring ``platform.profile.tasks``.

Read-only guarantee
-------------------
Quality only issues ``SELECT`` against the business database (every rule compiles
to a single read-only statement; ``custom_sql`` that is not a SELECT is rejected
at compile time). The connection is acquired ADMIN-purpose only to skip the
read-only probe, never to write (PC2).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from ..connections import ADMIN, ConnectionProvider
from ..dialect import get_dialect
from ..storage.models_core import CatalogSchema, CatalogTable
from .service import QualityService

#: ``JobType.QUALITY`` already exists in the orchestration models; reuse it.
JOB_QUALITY = "quality"


def _load_table(session_factory, table_id: int) -> dict[str, Any]:
    with session_factory() as session:
        table = session.get(CatalogTable, table_id)
        if table is None:
            raise ValueError(f"catalog_table {table_id} not found")
        schema = session.get(CatalogSchema, table.schema_id)
        return {
            "datasource_id": int(table.datasource_id),
            "schema_name": schema.name if schema is not None else "public",
            "table_name": table.name,
        }


def _scope_of(ctx: Any) -> dict[str, Any]:
    """Task scope, tolerant of both context shapes in this repo.

    ``TaskContext`` exposes ``run.scope``; some handlers were written against a
    ``ctx.scope`` that does not exist. Accept either.
    """
    run = getattr(ctx, "run", None)
    if run is not None and getattr(run, "scope", None):
        return dict(run.scope)
    return dict(getattr(ctx, "scope", None) or {})


def _relation(schema_name: str, table_name: str) -> str:
    quote = lambda value: '"' + value.replace('"', '""') + '"'  # noqa: E731
    return f"{quote(schema_name)}.{quote(table_name)}"


def make_quality_handler(
    session_factory,
    connection_provider: ConnectionProvider | None = None,
) -> Callable[[Any], dict[str, Any]]:
    """Build the ``JobType.QUALITY`` handler.

    ``connection_provider`` is injectable so tests can hand in a fake; when
    omitted one is built per run because it binds a ``Session`` and must not be
    cached across requests.
    """

    def run_quality(ctx: Any) -> dict[str, Any]:
        scope = _scope_of(ctx)
        table_id = int(scope.get("table_id") or 0)
        if not table_id:
            raise ValueError("scope.table_id is required for the quality job")

        meta = _load_table(session_factory, table_id)
        ds_id = meta["datasource_id"]
        relation = _relation(meta["schema_name"], meta["table_name"])

        provider = connection_provider
        if provider is None:
            provider = ConnectionProvider(session_factory())

        with provider.acquire(ds_id, ADMIN) as ds_conn:
            results = QualityService(session_factory).run(
                engine=ds_conn.engine,
                relation=relation,
                table_id=table_id,
                persist=True,
            )

        errored = sum(1 for result in results if "error" in result.detail)
        return {
            # Run-level success/failure, distinct from business pass/fail: a rule
            # that ran but flagged rows is a *successful* execution, not a task
            # failure. Only unrunnable rules count toward task failure, so the
            # partial-success state (FR-M9) reflects execution, not quality.
            "succeeded": len(results) - errored,
            "failed": errored,
            "rulesTotal": len(results),
        }

    return run_quality


def register_quality_tasks(
    task_service,
    session_factory,
    connection_provider: ConnectionProvider | None = None,
) -> None:
    """Register the quality handler against ``JobType.QUALITY``."""
    task_service.register_handler(
        JOB_QUALITY,
        make_quality_handler(session_factory, connection_provider=connection_provider),
    )
