"""Task run persistence (FR-12.5 / T-107).

A small abstraction so the orchestration core is storage-agnostic:

* ``InMemoryTaskRunStore`` — used for unit tests and the single-instance MVP
  runtime (task runs live in-process; history is also mirrored to Postgres via
  ``SqlTaskRunStore`` when a DB session factory is provided).
* ``SqlTaskRunStore`` — persists to the ``scan_run`` table (ORM already landed
  in T-106), satisfying "must ship with persistence".

The full ``scope`` dict and retry policy are stashed inside ``scan_run.stats``
under private keys so the row stays queryable and re-entry checks stay exact.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .errors import TaskNotFoundError
from .models import RetryPolicy, TaskRun, TaskStatus, scope_key_of

# Private keys inside scan_run.stats — must not collide with business stats.
_SCOPE_KEY = "_scope"
_RETRY_KEY = "_retry"


def _retry_dict(r: RetryPolicy) -> dict:
    return {
        "max_attempts": r.max_attempts,
        "base_delay_sec": r.base_delay_sec,
        "max_delay_sec": r.max_delay_sec,
        "jitter": r.jitter,
    }


def _retry_from(d: dict) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=d.get("max_attempts", 1),
        base_delay_sec=d.get("base_delay_sec", 1.0),
        max_delay_sec=d.get("max_delay_sec", 60.0),
        jitter=d.get("jitter", True),
    )


class TaskRunStore:
    def create(self, run: TaskRun) -> TaskRun:  # pragma: no cover - interface
        raise NotImplementedError

    def get(self, run_id: int) -> Optional[TaskRun]:  # pragma: no cover
        raise NotImplementedError

    def update(self, run: TaskRun) -> None:  # pragma: no cover
        raise NotImplementedError

    def list(
        self,
        *,
        job_type: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        datasource_id: Optional[int] = None,
    ) -> List[TaskRun]:  # pragma: no cover
        raise NotImplementedError

    def exists_active(self, job_type: str, scope_key: str) -> bool:  # pragma: no cover
        raise NotImplementedError


class InMemoryTaskRunStore(TaskRunStore):
    """Thread-safe in-memory store.

    Background execution (``TaskService.run_async``) mutates runs from worker
    threads while HTTP requests read them, so every access is serialised here.
    """

    def __init__(
        self, clock: Optional[Callable[[], datetime]] = None
    ) -> None:
        self._runs: dict[int, TaskRun] = {}
        self._seq = 0
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._gate = threading.Lock()

    def create(self, run: TaskRun) -> TaskRun:
        with self._gate:
            self._seq += 1
            run.id = self._seq
            run.created_at = self._clock()
            self._runs[run.id] = run
            return run

    def get(self, run_id: int) -> Optional[TaskRun]:
        with self._gate:
            return self._runs.get(run_id)

    def update(self, run: TaskRun) -> None:
        with self._gate:
            if run.id not in self._runs:
                raise TaskNotFoundError(run.id)
            self._runs[run.id] = run

    def list(
        self,
        *,
        job_type: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        datasource_id: Optional[int] = None,
    ) -> List[TaskRun]:
        with self._gate:
            res = list(self._runs.values())
        if job_type is not None:
            res = [r for r in res if r.job_type == job_type]
        if status is not None:
            res = [r for r in res if r.status == status]
        if datasource_id is not None:
            res = [r for r in res if r.scope.get("datasource_id") == datasource_id]
        return sorted(res, key=lambda r: r.id)

    def exists_active(self, job_type: str, scope_key: str) -> bool:
        with self._gate:
            runs = list(self._runs.values())
        for r in runs:
            if r.job_type == job_type and scope_key_of(r.scope) == scope_key:
                if r.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    return True
        return False


class SqlTaskRunStore(TaskRunStore):
    """Persists task runs to the ``scan_run`` table (ORM landed in T-106)."""

    def __init__(self, session_factory: Callable[[], object]) -> None:
        self._sf = session_factory

    @staticmethod
    def _build_stats(run: TaskRun) -> dict:
        stats = dict(run.stats)
        stats[_SCOPE_KEY] = run.scope
        stats[_RETRY_KEY] = _retry_dict(run.retry)
        return stats

    def _to_run(self, m) -> TaskRun:
        stats = dict(m.stats or {})
        scope = stats.pop(_SCOPE_KEY, {})
        retry = _retry_from(stats.pop(_RETRY_KEY, {}))
        return TaskRun(
            id=m.id,
            job_type=m.job_type,
            scope=scope,
            trigger=m.trigger_type or "manual",
            status=TaskStatus(m.status),
            retry=retry,
            timeout_sec=getattr(m, "timeout_sec", None),
            concurrency_key=stats.pop("_concurrency_key", None) or (
                f"ds:{m.datasource_id}" if m.datasource_id is not None else f"job:{m.job_type}"
            ),
            priority=int(stats.pop("_priority", 0)),
            payload=stats.pop("_payload", {}),
            submitted_by=m.stats.get("_submitted_by") if isinstance(m.stats, dict) else None,
            attempts=m.stats.get("_attempts", 0) if isinstance(m.stats, dict) else 0,
            stats=stats,
            error_message=m.error_message,
            started_at=m.started_at,
            finished_at=m.finished_at,
            duration_ms=m.duration_ms,
            created_at=m.created_at,
        )

    def create(self, run: TaskRun) -> TaskRun:
        from ..storage.models_ops import ScanRun

        with self._sf() as s:
            stats = self._build_stats(run)
            stats["_submitted_by"] = run.submitted_by
            stats["_attempts"] = run.attempts
            stats["_concurrency_key"] = run.concurrency_key
            stats["_priority"] = run.priority
            stats["_payload"] = run.payload
            m = ScanRun(
                datasource_id=run.scope.get("datasource_id"),
                job_type=run.job_type,
                trigger_type=run.trigger,
                status=run.status.value,
                stats=stats,
                error_message=run.error_message,
                started_at=run.started_at,
                finished_at=run.finished_at,
                duration_ms=run.duration_ms,
            )
            s.add(m)
            s.flush()
            run.id = m.id
            s.commit()
        return run

    def get(self, run_id: int) -> Optional[TaskRun]:
        from ..storage.models_ops import ScanRun

        with self._sf() as s:
            m = s.get(ScanRun, run_id)
            return self._to_run(m) if m is not None else None

    def update(self, run: TaskRun) -> None:
        from ..storage.models_ops import ScanRun

        with self._sf() as s:
            m = s.get(ScanRun, run.id)
            if m is None:
                raise TaskNotFoundError(run.id)
            m.status = run.status.value
            m.error_message = run.error_message
            m.started_at = run.started_at
            m.finished_at = run.finished_at
            m.duration_ms = run.duration_ms
            stats = self._build_stats(run)
            stats["_submitted_by"] = run.submitted_by
            stats["_attempts"] = run.attempts
            stats["_concurrency_key"] = run.concurrency_key
            stats["_priority"] = run.priority
            stats["_payload"] = run.payload
            m.stats = stats
            s.commit()

    def list(
        self,
        *,
        job_type: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        datasource_id: Optional[int] = None,
    ) -> List[TaskRun]:
        from ..storage.models_ops import ScanRun
        from sqlalchemy import select

        with self._sf() as s:
            q = select(ScanRun)
            if job_type is not None:
                q = q.where(ScanRun.job_type == job_type)
            if status is not None:
                q = q.where(ScanRun.status == status.value)
            if datasource_id is not None:
                q = q.where(ScanRun.datasource_id == datasource_id)
            rows = s.scalars(q.order_by(ScanRun.id)).all()
        return [self._to_run(m) for m in rows]

    def exists_active(self, job_type: str, scope_key: str) -> bool:
        from ..storage.models_ops import ScanRun
        from sqlalchemy import select

        with self._sf() as s:
            q = select(ScanRun).where(
                ScanRun.job_type == job_type,
                ScanRun.status.in_(["pending", "running"]),
            )
            rows = s.scalars(q).all()
        for m in rows:
            scope = (m.stats or {}).get(_SCOPE_KEY, {})
            if scope_key_of(scope) == scope_key:
                return True
        return False
