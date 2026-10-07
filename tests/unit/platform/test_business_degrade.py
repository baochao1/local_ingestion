"""Unit + API tests for T-214 business metadata and T-215 degradation (MOD-09).

Both run against the in-memory stacks — no Postgres required.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from local_ingestion.api.app import app
from local_ingestion.platform.business import (
    BusinessMetadataInput,
    BusinessTermInput,
    build_in_memory_business_stack,
)
from local_ingestion.platform.degrade import (
    AuthorizationProvider,
    DegradationRegistry,
    LineageSummaryProvider,
    VisibilityProvider,
    build_default_registry,
)
from local_ingestion.platform.resilience.feature import (
    MOD_AUTHORIZATION,
    MOD_LINEAGE,
    MOD_VISIBILITY,
    FeatureAvailability,
    default_availability,
)


# ----------------------------------------------------------------- T-214 business
def test_business_term_crud_and_lookup():
    svc, _ = build_in_memory_business_stack()
    svc.upsert_term(BusinessTermInput(term_code="order", term_name="订单", domain="trade"))
    assert svc.get_term("order").term_name == "订单"
    assert [t.term_code for t in svc.list_terms(domain="trade")] == ["order"]
    # upsert updates in place
    svc.upsert_term(BusinessTermInput(term_code="order", term_name="订单(更新)"))
    assert svc.get_term("order").term_name == "订单(更新)"


def test_business_metadata_and_tags():
    svc, _ = build_in_memory_business_stack()
    svc.set_metadata("table", 7, BusinessMetadataInput(
        alias="orders_view", business_desc="订单明细", domain="trade",
        owner_business="data-team", term_codes=["order"], tags={"priority": "high"},
    ))
    m = svc.get_metadata("table", 7)
    assert m.alias == "orders_view" and m.owner_business == "data-team"
    assert m.term_codes == ["order"] and m.tags == {"priority": "high"}
    # tag overwrite
    svc.set_tags("table", 7, {"critical": "true"})
    assert svc.get_metadata("table", 7).tags == {"critical": "true"}
    # alias lookup
    assert [x.entity_id for x in svc.find_by_alias("orders_view")] == [7]


# ----------------------------------------------------------------- T-215 degrade
def test_placeholders_degrade_by_default():
    """血缘已随 MOD-07 落地，不再默认降级（FR-M4.5）。

    血缘的采集器、闭包表与 REST 接口均已实现，把它报为不可用等于隐藏一个
    可用模块。其余两个模块仍属未部署，必须降级。
    """
    lineage = LineageSummaryProvider().status(default_availability())
    assert lineage.available is True

    for prov in (AuthorizationProvider(), VisibilityProvider()):
        st = prov.status(default_availability())
        assert st.available is False
        assert st.reason


def test_availability_flip_makes_dependency_available():
    avail = FeatureAvailability({MOD_LINEAGE: True, MOD_AUTHORIZATION: True, MOD_VISIBILITY: True})
    for prov in (LineageSummaryProvider(), AuthorizationProvider(), VisibilityProvider()):
        st = prov.status(avail)
        assert st.available is True
        assert st.reason == ""


def test_registry_reports_degraded_sources():
    reg = build_default_registry()
    assert set(reg.degraded_sources()) == {"authorization", "visibility"}
    # flip the remaining two available
    reg._avail.declare(MOD_AUTHORIZATION, True)
    reg._avail.declare(MOD_VISIBILITY, True)
    assert reg.degraded_sources() == []


# ------------------------------------------------------------------------- REST
def test_business_rest_flow():
    client = TestClient(app)
    r = client.post("/api/v1/business/terms", json={"term_code": "cust", "term_name": "客户"})
    assert r.status_code == 201 and r.json()["term_code"] == "cust"
    r = client.get("/api/v1/business/terms")
    assert r.status_code == 200 and len(r.json()["terms"]) == 1
    r = client.put("/api/v1/business/entities/table/3", json={"alias": "t", "business_desc": "d", "tags": {"k": "v"}})
    assert r.status_code == 200 and r.json()["tags"] == {"k": "v"}
    r = client.get("/api/v1/business/entities/table/3")
    assert r.status_code == 200 and r.json()["alias"] == "t"
    r = client.post("/api/v1/business/entities/table/3/tags", json={"tags": {"x": "y"}})
    assert r.status_code == 200 and r.json()["tags"] == {"x": "y"}


def test_degradation_rest():
    client = TestClient(app)
    r = client.get("/api/v1/meta/degradation")
    assert r.status_code == 200
    body = r.json()
    assert set(body["degraded_sources"]) == {"authorization", "visibility"}
    assert len(body["dependencies"]) == 3
