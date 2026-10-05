"""Presentation routes: parameter mapping and response shape (main flow C).

The services behind these routes already existed; what was missing was the HTTP
surface. These tests pin the contract (query params -> query object, camelCase
body, 404 for unknown assets) without needing a database.
"""
from __future__ import annotations

import os

os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "presentation-test-key-00000000")

import pytest
from fastapi.testclient import TestClient

from local_ingestion.api.app import app
from local_ingestion.platform.api.routers.assets import get_asset_service
from local_ingestion.platform.api.routers.search import get_search_service
from local_ingestion.platform.asset.models import AssetDetail, ColumnBrief
from local_ingestion.platform.search.models import SearchHit, SearchResult


def _bind(dependency, fake):
    app.dependency_overrides[dependency] = lambda: fake
    return TestClient(app)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_search_service, None)
    app.dependency_overrides.pop(get_asset_service, None)


def test_search_maps_query_params_and_camelizes():
    captured = {}

    class FakeSearch:
        def search(self, query):
            captured["query"] = query
            return SearchResult(
                items=[SearchHit(entity_type="table", fqn="db.s.t",
                                 name="t", datasource_id=1, is_pii=True)],
                total=1, limit=query.limit, offset=query.offset,
            )

    client = _bind(get_search_service, FakeSearch())
    resp = client.get(
        "/api/v1/search",
        params={"term": "t", "datasourceId": 3, "sensitiveOnly": "true", "limit": 5},
    )

    assert resp.status_code == 200, resp.text
    q = captured["query"]
    assert (q.term, q.datasource_id, q.sensitive_only, q.limit) == ("t", 3, True, 5)
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["isPii"] is True
    assert body["items"][0]["fqn"] == "db.s.t"


def test_asset_detail_returns_card():
    class FakeAsset:
        async def aggregate(self, fqn):
            return AssetDetail(
                fqn=fqn, entity_type="table", name="customers",
                columns=[ColumnBrief(name="email", data_type="varchar",
                                     nullable=True, is_pii=True, importance=3)],
            )

    client = _bind(get_asset_service, FakeAsset())
    resp = client.get("/api/v1/assets/db.public.customers")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "customers"
    assert body["columns"][0]["dataType"] == "varchar"
    assert body["columns"][0]["isPii"] is True


def test_asset_detail_404_when_unknown():
    class FakeAsset:
        async def aggregate(self, fqn):
            return AssetDetail(fqn=fqn)  # no entity_type, no columns

    client = _bind(get_asset_service, FakeAsset())
    resp = client.get("/api/v1/assets/db.public.missing")

    assert resp.status_code == 404
