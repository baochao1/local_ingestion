"""REST API for catalog overview statistics (MOD-09 / T-213).

Serves the **real** catalog by default: the in-memory source was the only wiring
before, which meant the dashboard always showed an empty catalog no matter how
much had been scanned. When no database answers, it falls back to the in-memory
source so the endpoint still works locally (and in tests) instead of 500ing.
"""
from __future__ import annotations

from dataclasses import asdict

import structlog
from fastapi import APIRouter, Depends

from local_ingestion.platform.catalog import build_in_memory_overview_service
from local_ingestion.platform.catalog.service import OverviewService

# structlog, like the rest of the platform: stdlib logging silently drops
# `logger.info(..., key=...)` kwargs (root level is WARNING, so the call is a
# no-op) and *raises* on `warning`/`error` — neither is acceptable here.
logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/catalog", tags=["Catalog"])

_state: dict = {}


def _build_overview_service() -> OverviewService:
    """SQL-backed when the platform DB answers, in-memory otherwise."""
    from local_ingestion.platform.catalog.source import SqlCatalogStatsSource
    from local_ingestion.platform.storage.session import session_scope

    try:
        source = SqlCatalogStatsSource(session_scope)
        source.count_tables()  # cheap probe: fails fast when there is no DB
    except Exception as exc:  # noqa: BLE001 - degradation is the contract here
        logger.warning(
            "overview_degraded_to_memory",
            error=str(exc),
            note="平台库不可用，总览退回内存数据源",
        )
        return build_in_memory_overview_service()
    return OverviewService(source)


def get_overview_service() -> OverviewService:
    if "ov" not in _state:
        _state["ov"] = _build_overview_service()
    return _state["ov"]


@router.get("/overview")
def overview(
    trend_days: int = 30,
    svc: OverviewService = Depends(get_overview_service),
):
    return asdict(svc.get_overview(trend_days=trend_days))
