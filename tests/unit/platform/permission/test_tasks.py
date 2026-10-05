"""MOD-08 T6: permission task registration."""
import pytest

from local_ingestion.platform.orchestration.audit import AuditService, InMemoryAuditSink
from local_ingestion.platform.orchestration.service import TaskService
from local_ingestion.platform.orchestration.store import InMemoryTaskRunStore
from local_ingestion.platform.permission.tasks import JOB, register_permission_tasks


@pytest.fixture
def task_service():
    return TaskService(store=InMemoryTaskRunStore(), audit=AuditService(InMemoryAuditSink()))


def test_register_permission_handler(task_service):
    register_permission_tasks(task_service, None, None)
    assert JOB in task_service.registered_handlers()
