"""FR-M9: partial-success task state.

The point of the new state is that "3 of 200 tables failed" and "the run
collapsed" are different facts, and only one of them should hide 197 usable
results.
"""
from __future__ import annotations

import pytest

from local_ingestion.platform.orchestration.audit import AuditService, InMemoryAuditSink
from local_ingestion.platform.orchestration.models import (
    JobType,
    TaskSpec,
    TaskStatus,
)
from local_ingestion.platform.orchestration.service import (
    TaskService,
    is_partial_result,
)
from local_ingestion.platform.orchestration.store import InMemoryTaskRunStore


@pytest.fixture
def service() -> TaskService:
    return TaskService(
        store=InMemoryTaskRunStore(), audit=AuditService(InMemoryAuditSink())
    )


# --------------------------------------------------------------------------
# the predicate
# --------------------------------------------------------------------------


def test_explicit_flag_is_honoured():
    assert is_partial_result({"partial": True}) is True


def test_counts_must_show_both_success_and_failure():
    assert is_partial_result({"succeeded": 3, "failed": 1}) is True
    assert is_partial_result({"succeeded": 5, "failed": 0}) is False
    assert is_partial_result({"succeeded": 0, "failed": 5}) is False


def test_non_dict_results_are_not_partial():
    assert is_partial_result(None) is False
    assert is_partial_result("ok") is False
    assert is_partial_result(["a"]) is False


# --------------------------------------------------------------------------
# end-to-end through the orchestrator
# --------------------------------------------------------------------------


def _run_with(service: TaskService, result):
    service.register_handler(JobType.PROFILE, lambda ctx: result)
    run = service.submit(TaskSpec(job_type=JobType.PROFILE, scope={"table_id": 1}))
    return service.run_now(run.id)


def test_handler_reporting_some_failures_is_partial(service):
    run = _run_with(service, {"succeeded": 197, "failed": 3})
    assert run.status == TaskStatus.PARTIAL_SUCCESS


def test_handler_reporting_full_success_is_success(service):
    run = _run_with(service, {"succeeded": 200, "failed": 0})
    assert run.status == TaskStatus.SUCCESS


def test_plain_dict_without_counters_stays_success(service):
    """Handlers that report nothing must not be reclassified (AC-9.2)."""
    run = _run_with(service, {"status": "success"})
    assert run.status == TaskStatus.SUCCESS


def test_raising_handler_is_still_a_plain_failure(service):
    def boom(ctx):
        raise ValueError("exploded")

    service.register_handler(JobType.PROFILE, boom)
    run = service.submit(TaskSpec(job_type=JobType.PROFILE, scope={"table_id": 2}))
    finished = service.run_now(run.id)
    assert finished.status == TaskStatus.FAILED
    assert "exploded" in (finished.error_message or "")


def test_partial_result_is_audited_as_its_own_action(service):
    sink = InMemoryAuditSink()
    svc = TaskService(store=InMemoryTaskRunStore(), audit=AuditService(sink))
    _run_with(svc, {"succeeded": 1, "failed": 1})
    actions = [entry.action for entry in sink.entries]
    assert "task.partial_success" in actions
    results = [entry.result for entry in sink.entries]
    assert TaskStatus.PARTIAL_SUCCESS.value in results
