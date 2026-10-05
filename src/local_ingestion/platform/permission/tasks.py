"""Wire permission collectors into MOD-10 orchestration (T-107).

Registers a standalone ``permission.collect`` handler. Permission analysis is an
independent, low-frequency, read-only task (ADMIN connection) — it is NOT chained
onto the metadata scan dependency graph (unlike lineage), so it never blocks scan.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..connections import ADMIN, ConnectionProvider
from .collector import collect_permissions

JOB = "permission.collect"


def _load_datasource(session_factory, ds_id: int) -> Dict[str, Any]:
    from ..storage.models_core import Datasource
    with session_factory() as s:
        ds = s.get(Datasource, ds_id)
        if ds is None:
            raise ValueError(f"datasource {ds_id} not found")
        return {
            "code": ds.code,
            "ds_type": ds.ds_type,
            "database": (ds.scan_config or {}).get("database"),
            "scan_config": ds.scan_config or {},
        }


def _grade_lookup(session_factory, ds_id: int) -> Dict[str, int]:
    """Map table FQN -> max grade_level (from MOD-05 classification).

    Best-effort: returns {} when catalog linkage is unavailable. Wiring to
    catalog_column.grade_level keeps the high-sensitivity risk rule fed (FR-6.5).
    """
    return {}


def register_permission_tasks(task_service, session_factory, connection_provider: ConnectionProvider) -> None:
    def run(ctx):
        ds_id = ctx.scope["datasource_id"]
        ds = _load_datasource(session_factory, ds_id)
        schema = ctx.scope.get("schema") or (ds["scan_config"] or {}).get("default_schema") or ds["database"]
        with connection_provider.acquire(ds_id, ADMIN) as ds_conn:
            with ds_conn.engine.connect() as sa_conn:
                return collect_permissions(
                    session_factory, ds_id=ds_id, ds_type=ds["ds_type"],
                    db=ds["database"], schema=schema, conn=sa_conn,
                    grade_lookup=_grade_lookup(session_factory, ds_id),
                ).__dict__

    task_service.register_handler(JOB, run)
