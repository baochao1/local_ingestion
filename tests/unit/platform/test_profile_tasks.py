"""``05-1`` close-out: the ``JobType.PROFILE`` handler.

These deliberately do **not** touch a database. The handler's job is to turn a
task scope into the right arguments for the runner; whether the runner works is
covered by the integration tests. So ``profile_table`` is patched and we assert
on what the handler hands it.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import create_engine

from local_ingestion.platform.orchestration.audit import AuditService, InMemoryAuditSink
from local_ingestion.platform.orchestration.service import TaskService
from local_ingestion.platform.orchestration.store import InMemoryTaskRunStore
from local_ingestion.platform.profile import tasks as profile_tasks
from local_ingestion.platform.storage.models_core import (
    CatalogColumn,
    CatalogSchema,
    CatalogTable,
)

DSN = "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"


@dataclass
class _FakeRun:
    scope: dict[str, Any]


@dataclass
class _FakeContext:
    """Mirrors ``TaskContext``: the scope lives on ``run``."""

    run: _FakeRun
    attempt: int = 1

    def cancelled(self) -> bool:
        return False


class _FakeConnection:
    def __init__(self, engine, ds_type: str = "postgres") -> None:
        self.engine = engine
        self.ds_type = ds_type


class _FakeProvider:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    @contextmanager
    def acquire(
        self, ds_id: int, purpose: Any, **kwargs: Any
    ) -> Iterator[_FakeConnection]:
        yield self._connection


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._rows


class _FakeSession:
    def __init__(
        self,
        table: CatalogTable,
        schema: CatalogSchema,
        columns: list[CatalogColumn],
    ) -> None:
        self._table = table
        self._schema = schema
        self._columns = columns

    def get(self, model: Any, pk: Any) -> Any:
        if model is CatalogTable:
            return self._table
        if model is CatalogSchema:
            return self._schema
        return None

    def execute(self, statement: Any) -> _FakeResult:
        return _FakeResult(self._columns)

    def __enter__(self) -> _FakeSession:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


def _session_factory():
    table = CatalogTable(id=77, datasource_id=5, schema_id=9, name="orders")
    schema = CatalogSchema(id=9, name="sales")
    columns = [
        CatalogColumn(
            id=1, table_id=77, name="id", data_type="INTEGER", ordinal_position=1
        ),
        CatalogColumn(
            id=2, table_id=77, name="amount", data_type="DECIMAL", ordinal_position=2
        ),
    ]
    return _FakeSession(table, schema, columns)


@pytest.fixture
def task_service() -> TaskService:
    return TaskService(
        store=InMemoryTaskRunStore(), audit=AuditService(InMemoryAuditSink())
    )


def test_profile_handler_is_registered(task_service):
    profile_tasks.register_profile_tasks(task_service, _session_factory)
    assert profile_tasks.JOB_PROFILE in task_service.registered_handlers()


def test_relation_is_always_quoted():
    # Quoting unconditionally keeps names with spaces or mixed case working.
    assert profile_tasks._relation("sales", "orders") == '"sales"."orders"'
    assert (
        profile_tasks._relation("My Schema", "Order Table")
        == '"My Schema"."Order Table"'
    )


def test_embedded_quote_is_escaped():
    assert profile_tasks._relation('sa"les', "orders") == '"sa""les"."orders"'


def test_scope_is_read_from_run_attribute():
    ctx = _FakeContext(run=_FakeRun(scope={"table_id": 42}))
    assert profile_tasks._scope_of(ctx) == {"table_id": 42}


def test_scope_falls_back_to_ctx_attribute():
    class _Legacy:
        scope = {"table_id": 7}

    assert profile_tasks._scope_of(_Legacy()) == {"table_id": 7}


def test_handler_assembles_runner_arguments(monkeypatch, task_service):
    captured: dict[str, Any] = {}

    def fake_profile_table(**kwargs: Any):
        captured.update(kwargs)

        class _Outcome:
            status = "success"
            row_count = 10
            sample_rate = 1.0
            duration_ms = 3
            error_message = None

        return _Outcome()

    monkeypatch.setattr(profile_tasks, "profile_table", fake_profile_table)

    provider = _FakeProvider(_FakeConnection(create_engine(DSN)))
    profile_tasks.register_profile_tasks(task_service, _session_factory, provider)
    handler = task_service._handlers.get(profile_tasks.JOB_PROFILE)

    result = handler(_FakeContext(run=_FakeRun(scope={"table_id": 77})))

    assert result["status"] == "success"
    assert result["tableId"] == 77
    # Resolved from catalog, not blindly trusted from the scope.
    assert captured["table_id"] == 77
    assert captured["datasource_id"] == 5
    assert captured["relation"] == '"sales"."orders"'
    assert captured["columns"] == [("id", "INTEGER"), ("amount", "DECIMAL")]


def test_missing_table_id_is_rejected(task_service):
    provider = _FakeProvider(_FakeConnection(create_engine(DSN)))
    profile_tasks.register_profile_tasks(task_service, _session_factory, provider)
    handler = task_service._handlers.get(profile_tasks.JOB_PROFILE)

    with pytest.raises(ValueError, match="table_id"):
        handler(_FakeContext(run=_FakeRun(scope={})))
