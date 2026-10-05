"""Wire lineage collectors into the MOD-10 orchestration (T-107).

Registers two handlers and a dependency chain so that a successful metadata scan
triggers lineage collection, which in turn rebuilds the closure table:

    metadata (scan) -> lineage.collect -> lineage.closure.rebuild

Both handlers run against an ``ADMIN``-purpose connection (read-only to the
business DB; see connections.py — ADMIN skips the read-only verification but the
collector still only issues SELECTs, never writes to the business database).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..connections import ADMIN, ConnectionProvider
from .collector import collect_lineage
from .repository import LineageRepository

JOB_COLLECT = "lineage.collect"
JOB_CLOSURE = "lineage.closure.rebuild"

# Upstream scan job type (JobType.METADATA).
JOB_SCAN = "metadata"


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


def _schemas_to_scan(ds: Dict[str, Any]) -> list[str]:
    cfg = ds.get("scan_config", {})
    schemas = cfg.get("schemas") or []
    if not schemas:
        schemas = [cfg.get("default_schema") or "public"]
    return schemas


def register_lineage_tasks(task_service, session_factory, connection_provider: ConnectionProvider) -> None:
    def run_collect(ctx):
        ds_id = ctx.scope["datasource_id"]
        ds = _load_datasource(session_factory, ds_id)
        for schema in _schemas_to_scan(ds):
            with connection_provider.acquire(ds_id, ADMIN) as ds_conn:
                with ds_conn.engine.connect() as sa_conn:
                    collect_lineage(
                        session_factory, datasource_id=ds_id, ds_code=ds["code"],
                        db=ds["database"], schema=schema, conn=sa_conn,
                        dialect_name=ds["ds_type"], with_columns=True,
                    )
        # closure already rebuilt per-schema inside collect_lineage; ensure once more
        LineageRepository(session_factory).rebuild_closure()
        return {"ok": True, "datasource_id": ds_id}

    def run_closure(ctx):
        LineageRepository(session_factory).rebuild_closure()
        return {"ok": True}

    task_service.register_handler(JOB_COLLECT, run_collect)
    task_service.register_handler(JOB_CLOSURE, run_closure)
    task_service.add_dependency(JOB_SCAN, JOB_COLLECT)
    task_service.add_dependency(JOB_COLLECT, JOB_CLOSURE)
