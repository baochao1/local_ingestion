"""MOD-08 T7: permission REST API (PG-backed)."""
import os

os.environ.setdefault(
    "CREDENTIAL_ENCRYPTION_KEY",
    "6bDIB9Fe9Wuxj51Hreoyxj8hEGZaeSbHGBlxl77er0s=",
)

import pytest
from fastapi.testclient import TestClient

from local_ingestion.api.app import app
from local_ingestion.platform.permission.repository import PermissionRepository
from local_ingestion.platform.storage.session import session_scope

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)


def _seed():
    repo = PermissionRepository(session_scope)
    repo.upsert_account(1, "alice", is_super=True)
    repo.upsert_account(1, "app", is_super=False)
    repo.upsert_grant(1, "app", "DELETE", "table", "db.s.orders")
    return repo


def _client():
    return TestClient(app)


def test_accounts_and_matrix_endpoints():
    _seed()
    c = _client()
    assert c.get("/api/v1/permissions/accounts", params={"datasource_id": 1}).status_code == 200
    assert c.get("/api/v1/permissions/matrix", params={"datasource_id": 1}).status_code == 200


def test_risks_endpoint():
    _seed()
    body = _client().get("/api/v1/permissions/risks", params={"datasource_id": 1}).json()
    types = {r["type"] for r in body}
    assert "super" in types and "excessive" in types
    # ack a risk
    rid = body[0]["id"]
    ack = _client().post(f"/api/v1/permissions/risks/{rid}/ack", params={"datasource_id": 1})
    assert ack.json()["ok"] is True


def test_entity_grants_and_changes():
    repo = _seed()
    repo.mark_baseline(1)
    repo.upsert_grant(1, "app", "DROP", "table", "db.s.orders")
    c = _client()
    assert c.get("/api/v1/permissions/entities/grants", params={"object_fqn": "db.s.orders"}).status_code == 200
    changes = c.get("/api/v1/permissions/changes", params={"datasource_id": 1}).json()
    assert any(ch["kind"] == "added" and ch["privilege"] == "DROP" for ch in changes)


def test_baseline_refresh_and_export():
    _seed()
    c = _client()
    assert c.post("/api/v1/permissions/baseline/refresh", json={"datasource_id": 1}).json()["ok"] is True
    rep = c.get("/api/v1/permissions/export", params={"datasource_id": 1}).json()
    assert rep["accounts"] >= 2 and "high_sensitivity_count" in rep


def test_trigger_task():
    _seed()
    r = _client().post("/api/v1/permissions/tasks", json={"datasource_id": 1})
    assert r.status_code == 200 and "task_id" in r.json()
