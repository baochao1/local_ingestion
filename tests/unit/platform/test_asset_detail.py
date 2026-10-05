"""Unit tests for asset detail aggregation (MOD-09 / T-212).

Verifies concurrent fan-out, the real catalog slice, graceful degradation of
not-yet-implemented modules, and resilience to provider exceptions — all without
a database.
"""
from __future__ import annotations

import asyncio

from local_ingestion.platform.asset import (
    AssetDetailService,
    AssetDetailProvider,
    ColumnBrief,
    SOURCE_BUSINESS,
    SOURCE_CATALOG,
    SOURCE_CHANGES,
    SOURCE_GRANTS,
    SOURCE_LINEAGE,
    SOURCE_QUALITY,
    build_in_memory_asset_service,
)

_TABLES = {
    "db.sales.orders": {
        "entity_type": "table",
        "name": "orders",
        "schema": "db.sales",
        "description": "customer orders",
        "tags": ["pii", "core"],
        "owner": "alice",
        "is_pii": True,
        "importance": 5,
        "columns": [
            {"name": "id", "data_type": "int", "nullable": False, "is_pii": False, "importance": 0},
            {"name": "customer_id", "data_type": "int", "nullable": False, "is_pii": True, "importance": 8},
        ],
    }
}


async def test_aggregate_catalog_and_degraded_placeholders():
    svc = build_in_memory_asset_service(_TABLES)
    detail = await svc.aggregate("db.sales.orders")
    assert isinstance(detail, __import__("local_ingestion.platform.asset.models", fromlist=["AssetDetail"]).AssetDetail)
    assert detail.name == "orders"
    assert detail.is_pii is True
    assert detail.owner == "alice"
    assert len(detail.columns) == 2
    assert detail.columns[1].name == "customer_id" and detail.columns[1].is_pii
    # placeholder modules report as degraded, not erroring
    assert set(detail.degraded_sources) == {
        SOURCE_BUSINESS, SOURCE_QUALITY, SOURCE_LINEAGE, SOURCE_GRANTS, SOURCE_CHANGES
    }


async def test_missing_asset_returns_empty_catalog_only():
    svc = build_in_memory_asset_service(_TABLES)
    detail = await svc.aggregate("db.sales.absent")
    assert detail.name is None
    # catalog is the only non-degraded slice, but it found nothing -> also degraded
    assert SOURCE_CATALOG in detail.degraded_sources


async def test_providers_run_concurrently_once_each():
    calls = []

    class Recorder(AssetDetailProvider):
        source = "rec"

        async def provide(self, fqn: str):
            calls.append(fqn)
            await asyncio.sleep(0.001)
            return {"x": 1}

    svc = AssetDetailService([Recorder(), Recorder()])
    await svc.aggregate("db.s.t")
    assert calls == ["db.s.t", "db.s.t"]


async def test_provider_exception_degrades_gracefully():
    class Boom(AssetDetailProvider):
        source = "boom"

        async def provide(self, fqn: str):
            raise RuntimeError("module down")

    svc = AssetDetailService([Boom()])
    detail = await svc.aggregate("db.s.t")
    assert detail.degraded_sources == ["boom"]
    assert detail.fqn == "db.s.t"
