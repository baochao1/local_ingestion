"""Unit + API tests for T-213 overview statistics and T-205 lineage impact (degraded).

Both run against the in-memory stacks — no Postgres required.
"""
from __future__ import annotations

import os

# The production lineage service now hits the DB (the old placeholder did not),
# so app startup/DB access requires the credential-encryption key to be present.
os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY",
    "6bDIB9Fe9Wuxj51Hreoyxj8hEGZaeSbHGBlxl77er0s=",
)

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from local_ingestion.api.app import app
from local_ingestion.platform.catalog import build_in_memory_overview_service
from local_ingestion.platform.changes import ChangeEventInput, InMemoryChangeRepository
from local_ingestion.platform.lineage import (
    ImpactReport,
    LineageService,
    get_default_lineage_service,
)


# ----------------------------------------------------------------- T-213 overview
def test_overview_rollup_and_degraded_quality():
    svc = build_in_memory_overview_service(
        table_grades=[3, 1, None], column_grades=[2, 0])
    ov = svc.get_overview()
    assert ov.tables_count == 3 and ov.columns_count == 2
    # 分级桶对外统一为 L1..L4；None 与越界值（0）归入 "ungraded"
    # （旧契约直接吐 grade_level 原值，前端按 "L1" 取值永远拿不到 → 首页恒为 0）
    assert ov.grade_distribution == {"L1": 1, "L2": 1, "L3": 1, "ungraded": 2}
    # sensitive = grade_level >= 2 -> {3, 2}
    assert ov.sensitive_count == 2
    assert abs(ov.sensitive_ratio - (2 / 5)) < 1e-6
    # quality module not deployed -> reported degraded, empty dict
    assert ov.degraded_sources == ["quality"]
    assert ov.quality_distribution == {}
    # no change source wired -> empty trend
    assert ov.change_trend == {}


def test_overview_is_cached():
    svc = build_in_memory_overview_service(table_grades=[1])
    first = svc.get_overview()
    second = svc.get_overview()
    assert first.computed_at == second.computed_at  # served from cache
    # explicit refresh recomputes (new timestamp)
    third = svc.refresh()
    assert third.computed_at >= second.computed_at


def test_overview_change_trend_from_change_repo():
    repo = InMemoryChangeRepository()
    day = datetime.now() - timedelta(days=1)
    repo.add(ChangeEventInput(entity_type="table", change_type="c", severity="breaking", entity_fqn="db.s.a", detected_at=day))
    repo.add(ChangeEventInput(entity_type="table", change_type="c", severity="breaking", entity_fqn="db.s.b", detected_at=day))
    repo.add(ChangeEventInput(entity_type="table", change_type="c", severity="descriptive", entity_fqn="db.s.c", detected_at=datetime.now() - timedelta(days=10)))

    svc = build_in_memory_overview_service(table_grades=[], column_grades=[], change_source=repo)
    ov = svc.get_overview(trend_days=30)
    assert ov.change_trend.get(day.date().isoformat()) == 2
    assert len(ov.change_trend) == 2  # two distinct dates


# ----------------------------------------------------------------- T-205 lineage
def test_default_lineage_service_is_production():
    # MOD-07 deployed: the default is the real service, not the degraded placeholder
    assert isinstance(get_default_lineage_service(), LineageService)


# ------------------------------------------------------------------------- REST
def test_overview_rest():
    client = TestClient(app)
    r = client.get("/api/v1/catalog/overview")
    assert r.status_code == 200
    body = r.json()
    assert "tables_count" in body and "sensitive_ratio" in body
    assert body["degraded_sources"] == ["quality"]


def test_lineage_impact_rest():
    client = TestClient(app)
    r = client.get("/api/v1/lineage/tables/db.s.critical/impact")
    assert r.status_code == 200
    body = r.json()
    # production service is never degraded; with no edges the scope is simply empty
    assert body["degraded"] is False
    assert body["total"] == 0
