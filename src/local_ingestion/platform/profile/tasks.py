"""Wire profiling into the MOD-10 orchestration (``05-1`` close-out).

Why this module exists
----------------------
Until now a profile could only be produced by calling
:func:`platform.profile.runner.profile_table` directly — which is what the
integration tests do. There was no way for a user to ask for one: the UI button
was disabled because nothing could resolve a connection to the business
database. This module supplies the missing handler for ``JobType.PROFILE``
(that enum value already existed, unused).

It mirrors :mod:`platform.lineage.tasks`: resolve the datasource, acquire a
connection through :class:`platform.connections.ConnectionProvider`, then run
the collector.

Read-only guarantee
-------------------
Profiling only issues ``SELECT`` against the business database. The handler
acquires an ADMIN-purpose connection because ADMIN skips the *read-only
verification probe* — not because it is allowed to write; the statements are
still read-only (``05-1`` PC2, verified by
``test_business_table_is_never_written``).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from ..connections import ADMIN, ConnectionProvider
from ..dialect import get_dialect
from ..storage.models_core import CatalogColumn, CatalogSchema, CatalogTable
from .config import ProfileConfig
from .runner import profile_table

#: ``JobType.PROFILE`` already exists in the orchestration models; reuse it
#: rather than inventing a parallel job type.
JOB_PROFILE = "profile"


def _load_table(session_factory, table_id: int) -> dict[str, Any]:
    """Resolve a table to what profiling needs: schema name, name, datasource."""
    with session_factory() as session:
        table = session.get(CatalogTable, table_id)
        if table is None:
            raise ValueError(f"catalog_table {table_id} not found")
        schema = session.get(CatalogSchema, table.schema_id)
        schema_name = schema.name if schema is not None else "public"
        columns = (
            session.execute(
                select(CatalogColumn)
                .where(CatalogColumn.table_id == table_id)
                .order_by(CatalogColumn.ordinal_position)
            )
            .scalars()
            .all()
        )
        return {
            "datasource_id": int(table.datasource_id),
            "schema_name": schema_name,
            "table_name": table.name,
            "columns": [
                (column.name, column.data_type or "UNKNOWN") for column in columns
            ],
        }


def _scope_of(ctx: Any) -> dict[str, Any]:
    """Task scope, tolerant of both context shapes seen in this repo.

    ``TaskContext`` exposes ``run.scope``; some handlers were written against a
    ``ctx.scope`` attribute that does not exist on it. Accept either so the
    handler works whichever shape the orchestrator passes.
    """
    run = getattr(ctx, "run", None)
    if run is not None and getattr(run, "scope", None):
        return dict(run.scope)
    return dict(getattr(ctx, "scope", None) or {})


def _relation(schema_name: str, table_name: str) -> str:
    """Always-quoted relation.

    Quoting unconditionally (rather than validating and passing bare
    identifiers through) means names with spaces or mixed case work, and it
    keeps a single code path — ``is_safe_relation`` accepts the quoted form.
    """
    quote = lambda value: '"' + value.replace('"', '""') + '"'  # noqa: E731
    return f"{quote(schema_name)}.{quote(table_name)}"


def make_profile_handler(
    session_factory,
    connection_provider: ConnectionProvider | None = None,
    config: ProfileConfig | None = None,
) -> Callable[[Any], dict[str, Any]]:
    """Build the ``JobType.PROFILE`` handler.

    ``connection_provider`` is injectable so tests can hand in a fake; when
    omitted one is built per run, because it binds a ``Session`` and must not
    be cached across requests.
    """

    def run_profile(ctx: Any) -> dict[str, Any]:
        scope = _scope_of(ctx)
        table_id = int(scope.get("table_id") or 0)
        if not table_id:
            raise ValueError("scope.table_id is required for the profile job")

        meta = _load_table(session_factory, table_id)
        ds_id = meta["datasource_id"]
        relation = _relation(meta["schema_name"], meta["table_name"])

        provider = connection_provider
        if provider is None:
            provider = ConnectionProvider(session_factory())

        with provider.acquire(ds_id, ADMIN) as ds_conn:
            # ``engine``, not a Connection: the runner opens a connection per
            # phase and must not hold one across the whole run.
            outcome = profile_table(
                engine=ds_conn.engine,
                dialect=get_dialect(ds_conn.ds_type),
                relation=relation,
                columns=meta["columns"],
                table_id=table_id,
                datasource_id=ds_id,
                config=config or ProfileConfig(),
                session_factory=session_factory,
            )

        return {
            "status": outcome.status,
            "tableId": table_id,
            "rowCount": outcome.row_count,
            "sampleRate": outcome.sample_rate,
            "durationMs": outcome.duration_ms,
            "errorMessage": outcome.error_message,
        }

    return run_profile


def register_profile_tasks(
    task_service,
    session_factory,
    connection_provider: ConnectionProvider | None = None,
    config: ProfileConfig | None = None,
) -> None:
    """Register the profile handler against ``JobType.PROFILE``."""
    task_service.register_handler(
        JOB_PROFILE,
        make_profile_handler(
            session_factory, connection_provider=connection_provider, config=config
        ),
    )
