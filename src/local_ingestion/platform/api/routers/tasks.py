"""Task orchestration REST API (MOD-10 / T-107).

Exposes the ``TaskService`` (``platform/orchestration``) over HTTP so the
frontend "任务运维" page (FE-01 §11) can list task runs, inspect details, and
cancel/retry them end-to-end.

Task runs are persisted to PostgreSQL via ``SqlTaskRunStore(session_scope)``
(``scan_run`` table) — they survive across requests and process restarts. The
service is a module-level singleton holding only the executor/lock; all run state
lives in the database.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ...api.serialization import camelize, to_camel
from ...storage.session import session_scope
from ...classification.service import ClassificationService
from ...orchestration.audit import AuditService, GLOBAL_AUDIT_SINK
from ...orchestration.errors import OrchestrationError, TaskNotFoundError
from ...orchestration.models import JobType, TaskContext, TaskSpec, TaskStatus, TriggerType
from ...orchestration.registry import HandlerRegistry
from ...orchestration.service import TaskService
from ...orchestration.store import SqlTaskRunStore, TaskRunStore
from ...scan.service import ScanService

router = APIRouter(prefix="/api/v1/tasks", tags=["Tasks"])


def _datasource_id_from(ctx: TaskContext) -> int:
    ds = ctx.run.scope.get("datasource_id")
    if ds is None:
        raise ValueError("scope.datasource_id is required for this job type")
    return int(ds)


def _build_handlers() -> HandlerRegistry:
    """Wire real business operations to orchestration job types.

    Only job types with a backing service are registered; the rest resolve to
    "no handler registered" and fail honestly when dispatched.
    """
    reg = HandlerRegistry()

    def scan_handler(ctx: TaskContext) -> Dict[str, Any]:
        ds_id = _datasource_id_from(ctx)
        result = ScanService(session_scope).run_scan(ds_id, allow_write=False)
        return result.as_dict()

    def classify_handler(ctx: TaskContext) -> Dict[str, Any]:
        ds_id = _datasource_id_from(ctx)
        result = ClassificationService(session_scope).classify_datasource(ds_id)
        return result.as_dict()

    reg.register(JobType.METADATA, scan_handler)
    reg.register(JobType.CLASSIFY, classify_handler)
    return reg


#: Worker pool behind background execution. Kept well under the orchestrator's
#: global concurrency cap (8) so a burst of submitted tasks queues instead of
#: exhausting the pool.
_EXECUTOR_WORKERS = 4
_EXECUTOR = ThreadPoolExecutor(max_workers=_EXECUTOR_WORKERS, thread_name_prefix="task-exec")

# 任务运行持久化到 ``scan_run`` 表（跨进程/重启保留）；
# 审计仍走 GLOBAL_AUDIT_SINK，保持审计页现有行为不变。
_STORE: TaskRunStore = SqlTaskRunStore(session_scope)
_SERVICE: TaskService = TaskService(
    store=_STORE,
    audit=AuditService(GLOBAL_AUDIT_SINK),
    handlers=_build_handlers(),
    executor=_EXECUTOR,
)


def get_task_service() -> TaskService:
    return _SERVICE


def _run_to_dict(run) -> Dict[str, Any]:
    status = run.status.value if isinstance(run.status, TaskStatus) else run.status
    return {
        "id": run.id,
        "job_type": run.job_type,
        "scope": dict(run.scope),
        "trigger": run.trigger,
        "status": status,
        "retry": {
            "max_attempts": run.retry.max_attempts,
            "base_delay_sec": run.retry.base_delay_sec,
            "max_delay_sec": run.retry.max_delay_sec,
            "jitter": run.retry.jitter,
        },
        "timeout_sec": run.timeout_sec,
        "concurrency_key": run.concurrency_key,
        "priority": run.priority,
        "payload": dict(run.payload),
        "submitted_by": run.submitted_by,
        "attempts": run.attempts,
        "stats": dict(run.stats),
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


class TaskSubmitRequest(BaseModel):
    # 入参与出参一致走 camelCase（见 serialization.to_camel）：前端发
    # ``jobType`` 等，populate_by_name 同时兼容 snake_case，便于 CLI/测试。
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    job_type: str = Field(..., description="metadata|sample|profile|classify|lineage|permission")
    scope: Dict[str, Any] = Field(default_factory=dict, description="job scope, e.g. {datasource_id: 1}")
    trigger: str = "manual"
    concurrency_key: Optional[str] = None
    priority: int = 0
    payload: Dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_tasks(
    jobType: Optional[str] = Query(None, description="filter by job type"),
    status: Optional[str] = Query(None, description="filter by status (pending|running|success|failed|cancelled|timeout)"),
    datasourceId: Optional[int] = Query(None, description="filter by datasource_id in scope"),
    svc: TaskService = Depends(get_task_service),
) -> Dict[str, Any]:
    """List task runs, optionally filtered."""
    st = None
    if status is not None:
        try:
            st = TaskStatus(status)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"invalid status: {status}")
    runs = svc.list(job_type=jobType, status=st, datasource_id=datasourceId)
    return camelize({"items": [_run_to_dict(r) for r in runs], "total": len(runs)})


@router.post("")
def submit_task(
    body: TaskSubmitRequest,
    svc: TaskService = Depends(get_task_service),
) -> Dict[str, Any]:
    """Submit and start a task run in the background.

    Returns immediately with ``status=pending``; poll ``GET /api/v1/tasks/{id}``
    to follow pending -> running -> success/failed/cancelled. Re-entry
    protection applies per job_type+scope (409 on a duplicate active run).
    """
    try:
        trigger = TriggerType(body.trigger)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid trigger: {body.trigger}")
    spec = TaskSpec(
        job_type=body.job_type,
        scope=dict(body.scope),
        trigger=trigger,
        concurrency_key=body.concurrency_key,
        priority=body.priority,
        payload=dict(body.payload),
    )
    try:
        run = svc.dispatch(spec, background=True)
    except OrchestrationError as e:  # DuplicateTaskError / ConcurrencyLimitError 等
        raise HTTPException(status_code=409, detail=str(e))
    return camelize(_run_to_dict(run))


@router.get("/{task_id}")
def get_task(task_id: int, svc: TaskService = Depends(get_task_service)) -> Dict[str, Any]:
    """Task run detail (incl. stats/log payload)."""
    run = svc.get(task_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    return camelize(_run_to_dict(run))


@router.post("/{task_id}/cancel")
def cancel_task(task_id: int, svc: TaskService = Depends(get_task_service)) -> Dict[str, Any]:
    """Cancel a pending/running task."""
    try:
        ok = svc.cancel(task_id)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    run = svc.get(task_id)
    return camelize({"cancelled": ok, "task": _run_to_dict(run)})


@router.post("/{task_id}/retry")
def retry_task(task_id: int, svc: TaskService = Depends(get_task_service)) -> Dict[str, Any]:
    """Retry a failed/cancelled task (submits a fresh run in the background)."""
    try:
        run = svc.retry(task_id, background=True)
    except TaskNotFoundError:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    except OrchestrationError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return camelize(_run_to_dict(run))
