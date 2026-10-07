"""FR-M5 close-out: the quality handler wires into orchestration."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from local_ingestion.platform.orchestration.models import JobType
from local_ingestion.platform.quality.tasks import JOB_QUALITY, make_quality_handler


class _FakeConn:
    def __init__(self, ds_type: str = "postgres") -> None:
        self.ds_type = ds_type
        self.engine = object()  # handler only needs ``.engine``


class _FakeProvider:
    @contextmanager
    def acquire(self, ds_id: int, purpose: Any, **kwargs: Any) -> Iterator[_FakeConn]:
        yield _FakeConn()


def _result(with_error: bool):
    return type("R", (), {"detail": {"error": "boom"} if with_error else {}})()


def _make_handler(monkeypatch, results):
    """Handler whose QualityService.run + _load_table are stubbed."""
    captured: dict[str, Any] = {}

    def fake_run(self, *, engine, relation, table_id, column_ids=None, rules=None, persist=True):
        captured.update(relation=relation, table_id=table_id, persist=persist)
        return results

    import local_ingestion.platform.quality.tasks as qt

    monkeypatch.setattr(qt.QualityService, "run", fake_run)
    monkeypatch.setattr(
        qt,
        "_load_table",
        lambda sf, tid: {
            "datasource_id": 1,
            "schema_name": "public",
            "table_name": "orders",
        },
    )

    handler = make_quality_handler(lambda: None, connection_provider=_FakeProvider())
    ctx = type("Ctx", (), {"run": type("Run", (), {"scope": {"table_id": 42}})})()
    return handler(ctx), captured


def test_handler_wires_relation_and_persists(monkeypatch):
    outcome, captured = _make_handler(monkeypatch, [_result(False), _result(False)])
    assert outcome["succeeded"] == 2
    assert outcome["failed"] == 0
    assert captured["relation"] == '"public"."orders"'
    assert captured["persist"] is True
    assert captured["table_id"] == 42


def test_errored_rules_count_as_failed(monkeypatch):
    # A rule that flagged rows is a *successful execution* (passed=False with no
    # error); only unrunnable rules count toward task failure (FR-M9/FR-M5.3).
    outcome, _ = _make_handler(monkeypatch, [_result(False), _result(False), _result(True)])
    assert outcome["succeeded"] == 2
    assert outcome["failed"] == 1
    assert outcome["rulesTotal"] == 3


def test_handler_requires_table_id(monkeypatch):
    handler = make_quality_handler(lambda: None, connection_provider=_FakeProvider())
    ctx = type("Ctx", (), {"run": type("Run", (), {"scope": {}})})()
    try:
        handler(ctx)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "table_id" in str(exc)


def test_job_type_constant_matches_enum():
    assert JOB_QUALITY == "quality"
    assert JobType.QUALITY.value == "quality"
