"""API integration tests for the data-source router (MOD-01 / T-109).

Uses FastAPI ``TestClient`` with a dependency override that swaps the production
SQL-backed service for an in-memory one, so no database is required. An autouse
fixture gives each test its own isolated service instance that is nonetheless
shared across the multiple requests a single test makes.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from local_ingestion.api.app import app
from local_ingestion.platform.api.routers.datasources import get_datasource_service
from local_ingestion.platform.credentials import CredentialCipher
from local_ingestion.platform.datasource.repository import InMemoryDatasourceRepository
from local_ingestion.platform.datasource.service import (
    ConnectivityResult,
    DataSourceService,
)
from local_ingestion.platform.orchestration import (
    AuditService,
    InMemoryAuditSink,
    build_in_memory_orchestration,
)

PAYLOAD = {
    "code": "ds1",
    "name": "DS One",
    "dsType": "postgres",
    "host": "h",
    "port": 5432,
    "username": "u",
    "password": "p",
    "scanConfig": {"database": "db"},
}


def _fake_checker(connected=True, readonly=True):
    def _fn(*a, **k):
        return ConnectivityResult(connected, readonly, "")
    return _fn


def _build_svc():
    repo = InMemoryDatasourceRepository()
    cipher = CredentialCipher(key=os.urandom(32))
    audit = AuditService(InMemoryAuditSink())
    tasks = build_in_memory_orchestration()
    return DataSourceService(
        repo, cipher=cipher, audit=audit, task_service=tasks,
        connectivity_checker=_fake_checker(), allow_write=True,
    )


@pytest.fixture(autouse=True)
def isolated_service():
    svc = _build_svc()
    app.dependency_overrides[get_datasource_service] = lambda: svc
    yield
    app.dependency_overrides.clear()


def test_register_returns_camel_case_and_no_secret():
    client = TestClient(app)
    r = client.post("/api/v1/datasources", json=PAYLOAD)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["code"] == "ds1"
    assert data["dsType"] == "postgres"  # camelCase serialization
    assert data["activeCredentialVersion"] == 1
    assert "password" not in data
    assert "credentialEnc" not in data


def test_list_and_get():
    client = TestClient(app)
    client.post("/api/v1/datasources", json=PAYLOAD)
    lst = client.get("/api/v1/datasources")
    assert lst.status_code == 200
    assert lst.json()["items"][0]["code"] == "ds1"
    ds_id = lst.json()["items"][0]["id"]
    get = client.get(f"/api/v1/datasources/{ds_id}")
    assert get.status_code == 200 and get.json()["id"] == ds_id


def test_test_connection_endpoint():
    client = TestClient(app)
    r = client.post(
        "/api/v1/datasources/test",
        json={"dsType": "postgres", "host": "h", "username": "u", "password": "p"},
    )
    assert r.status_code == 200
    assert r.json()["connected"] is True


def test_duplicate_code_returns_409():
    client = TestClient(app)
    client.post("/api/v1/datasources", json=PAYLOAD)
    r = client.post("/api/v1/datasources", json=PAYLOAD)
    assert r.status_code == 409


def test_delete_returns_204():
    client = TestClient(app)
    ds_id = client.post("/api/v1/datasources", json=PAYLOAD).json()["id"]
    r = client.delete(f"/api/v1/datasources/{ds_id}")
    assert r.status_code == 204
    assert client.get(f"/api/v1/datasources/{ds_id}").status_code == 404


def test_enable_disable_and_health():
    client = TestClient(app)
    ds_id = client.post("/api/v1/datasources", json=PAYLOAD).json()["id"]
    client.post(f"/api/v1/datasources/{ds_id}/disable")
    assert client.get(f"/api/v1/datasources/{ds_id}").json()["enabled"] is False
    client.post(f"/api/v1/datasources/{ds_id}/enable")
    assert client.get(f"/api/v1/datasources/{ds_id}").json()["enabled"] is True
    h = client.get(f"/api/v1/datasources/{ds_id}/health").json()
    assert h["credentialPresent"] is True
