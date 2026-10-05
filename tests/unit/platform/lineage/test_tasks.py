"""MOD-07 T6: lineage task registration + dependency chain."""
import pytest

from local_ingestion.platform.lineage.tasks import (
    JOB_CLOSURE,
    JOB_COLLECT,
    JOB_SCAN,
    register_lineage_tasks,
)
from local_ingestion.platform.orchestration.audit import AuditService, InMemoryAuditSink
from local_ingestion.platform.orchestration.service import TaskService
from local_ingestion.platform.orchestration.store import InMemoryTaskRunStore


@pytest.fixture
def task_service():
    return TaskService(store=InMemoryTaskRunStore(), audit=AuditService(InMemoryAuditSink()))


def test_register_lineage_handler(task_service):
    register_lineage_tasks(task_service, None, None)
    assert JOB_COLLECT in task_service.registered_handlers()
    assert JOB_CLOSURE in task_service.registered_handlers()


def test_dependency_chain_registered(task_service):
    register_lineage_tasks(task_service, None, None)
    # metadata (scan) -> lineage.collect -> lineage.closure.rebuild
    downstream_of_scan = [d for (u, d, _b) in task_service._deps._rules if u == JOB_SCAN]
    assert JOB_COLLECT in downstream_of_scan
    downstream_of_collect = [d for (u, d, _b) in task_service._deps._rules if u == JOB_COLLECT]
    assert JOB_CLOSURE in downstream_of_collect
