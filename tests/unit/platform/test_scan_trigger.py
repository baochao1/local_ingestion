"""Triggering ingestion — the REST endpoint and the scheduler (main flow B).

Before this, nothing in the production code ever called ``ScanService``: the CLI
only printed a connectivity preview and no HTTP route existed, so ingestion was
only reachable from tests. These tests pin the two new entry points.

No database is needed: the scan service is injected through the FastAPI
dependency override, and the scheduler runs against a fake session factory.
"""
from __future__ import annotations

import os

os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "scan-trigger-test-key-000000")

import pytest
from fastapi.testclient import TestClient

from local_ingestion.api.app import app
from local_ingestion.platform.api.routers.scans import get_scan_service
from local_ingestion.platform.scan import (
    DatasourceNotFoundError,
    ScanError,
    ScanResult,
)
from local_ingestion.platform.scan.scheduler import ScanScheduler


class _FakeScanService:
    """Records how it was called instead of touching a database."""

    def __init__(self, result: ScanResult | None = None, error: Exception | None = None):
        self.calls: list = []
        self._result = result or ScanResult(
            datasource_id=7, datasource_code="pg1", database="db", tables_processed=3
        )
        self._error = error

    def run_scan(self, ds_id, *, database=None, schemas=None,
                 allow_write=False, mark_deleted=True):
        self.calls.append((ds_id, database, schemas, allow_write, mark_deleted))
        if self._error is not None:
            raise self._error
        return self._result


@pytest.fixture
def scan_client():
    """Yields a factory binding a fake scan service to the app."""
    def _bind(fake):
        app.dependency_overrides[get_scan_service] = lambda: fake
        return TestClient(app)

    yield _bind
    app.dependency_overrides.pop(get_scan_service, None)


def test_scan_endpoint_runs_ingestion(scan_client):
    fake = _FakeScanService()
    client = scan_client(fake)

    resp = client.post(
        "/api/v1/datasources/7/scan",
        json={"schemas": ["public"], "markDeleted": False},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["datasourceId"] == 7
    assert body["tablesProcessed"] == 3
    assert body["ok"] is True
    # camelCase body forwarded, and the no-body default (markDeleted=True) overridden.
    assert fake.calls == [(7, None, ["public"], False, False)]


def test_scan_endpoint_accepts_no_body(scan_client):
    fake = _FakeScanService()
    client = scan_client(fake)

    resp = client.post("/api/v1/datasources/7/scan")
    assert resp.status_code == 200, resp.text
    assert fake.calls == [(7, None, None, False, True)]


def test_scan_endpoint_maps_missing_datasource_to_404(scan_client):
    fake = _FakeScanService(error=DatasourceNotFoundError("数据源 9 不存在或已删除。"))
    client = scan_client(fake)

    resp = client.post("/api/v1/datasources/9/scan")
    assert resp.status_code == 404


def test_scan_endpoint_maps_scan_error_to_400(scan_client):
    fake = _FakeScanService(error=ScanError("未指定目标数据库"))
    client = scan_client(fake)

    resp = client.post("/api/v1/datasources/7/scan")
    assert resp.status_code == 400


# -- scheduler -----------------------------------------------------------


class _FakeDS:
    def __init__(self, ds_id: int, code: str, scan_config: dict | None = None):
        self.id = ds_id
        self.code = code
        self.scan_config = scan_config or {}


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _model):
        return _FakeQuery(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _scheduler(rows, **kw):
    return ScanScheduler(
        lambda: _FakeSession(rows),
        scan_service_factory=lambda: _FakeScanService(),
        **kw,
    )


def test_scheduler_schedules_every_target_with_its_cadence():
    rows = [_FakeDS(1, "default"), _FakeDS(2, "fast", {"interval_minutes": 5})]
    sched = _scheduler(rows)

    assert sched.start() is True
    jobs = {j.datasource_code: j.interval_minutes for j in sched.list_jobs()}
    assert jobs == {"default": 60, "fast": 5}

    sched.stop()
    assert sched.is_running() is False
    assert sched.list_jobs() == []


def test_scheduler_interval_never_falls_below_one_minute():
    sched = _scheduler([])
    assert sched._interval_for(_FakeDS(1, "x", {"interval_minutes": 0})) == 1
    assert sched._interval_for(_FakeDS(1, "x", {"interval_minutes": "abc"})) == 60
    assert sched._interval_for(_FakeDS(1, "x")) == 60


def test_scheduler_without_targets_does_not_start():
    sched = _scheduler([])
    assert sched.start() is False
    assert sched.is_running() is False
