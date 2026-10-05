"""MOD-07 T7: lineage REST API (PG-backed)."""
import os

import pytest
from fastapi.testclient import TestClient

from local_ingestion.api.app import app
from local_ingestion.platform.lineage.repository import LineageRepository
from local_ingestion.platform.storage.models_ops import (
    LineageClosure,
    LineageColumnEdge,
    LineageTableEdge,
)
from local_ingestion.platform.storage.session import session_scope
from sqlalchemy import delete

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)


@pytest.fixture(autouse=True)
def _clean():
    yield
    with session_scope() as s:
        s.execute(delete(LineageClosure))
        s.execute(delete(LineageColumnEdge))
        s.execute(delete(LineageTableEdge))
        s.commit()


def _seed():
    repo = LineageRepository(session_scope)
    repo.upsert_table_edge("ds.db.s.A", "ds.db.s.B")
    repo.upsert_table_edge("ds.db.s.B", "ds.db.s.C")
    repo.rebuild_closure()


def test_upstream_downstream_endpoints():
    _seed()
    client = TestClient(app)
    up = client.get("/api/v1/lineage/tables/ds.db.s.C/upstream").json()
    assert any(n["fqn"] == "ds.db.s.A" for n in up["nodes"])
    down = client.get("/api/v1/lineage/tables/ds.db.s.A/downstream").json()
    assert {n["fqn"] for n in down["nodes"]} == {"ds.db.s.B", "ds.db.s.C"}


def test_parse_endpoint_is_pure():
    client = TestClient(app)
    r = client.post("/api/v1/lineage/parse", json={
        "sql": "SELECT a.id FROM db.s.t1 a", "ds_code": "ds", "db": "db", "schema": "s",
    })
    assert r.status_code == 200
    body = r.json()
    assert ["ds.db.s.t1", "ds.db.s._sub"] in body["table_edges"]


def test_edges_crud_and_rebuild():
    client = TestClient(app)
    add = client.post("/api/v1/lineage/edges", json={
        "src_fqn": "ds.db.s.X", "tgt_fqn": "ds.db.s.Y", "level": "table",
    })
    assert add.status_code == 200 and add.json()["ok"] is True
    listed = client.get("/api/v1/lineage/edges", params={"src_fqn": "ds.db.s.X"}).json()
    assert any(e["tgt_fqn"] == "ds.db.s.Y" for e in listed)

    deleted = client.delete("/api/v1/lineage/edges/ds.db.s.X/ds.db.s.Y").json()
    assert deleted["deleted"] == 1
    listed2 = client.get("/api/v1/lineage/edges", params={"src_fqn": "ds.db.s.X"}).json()
    assert listed2 == []

    rb = client.post("/api/v1/lineage/closure/rebuild").json()
    assert rb["ok"] is True


def test_import_endpoint():
    client = TestClient(app)
    r = client.post("/api/v1/lineage/import", json={
        "edges": [{"src_fqn": "ds.db.s.P", "tgt_fqn": "ds.db.s.Q", "level": "table"}],
    })
    assert r.status_code == 200 and r.json()["imported"] == 1
    listed = client.get("/api/v1/lineage/edges", params={"tgt_fqn": "ds.db.s.Q"}).json()
    assert any(e["src_fqn"] == "ds.db.s.P" for e in listed)
