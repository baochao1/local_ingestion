"""Task orchestration service (FR-12 / T-107).

Owns the lifecycle of every task in the platform. Implements the acceptance
criteria for T-107:

* re-entry protection (no duplicate job_type+scope)            -> :meth:`submit`
* manual trigger / cancel / retry                              -> :meth:`dispatch`, :meth:`cancel`, :meth:`retry`
* global + per-datasource concurrency caps                    -> :class:`ConcurrencyLimiter`
* retry with exponential back-off + jitter                    -> :mod:`retries`
* dependency chaining (scan -> diff -> notify)                -> :class:`DependencyRegistry`
* audit trail on every key action                             -> :class:`AuditService`
* queryable history / stats                                   -> :meth:`get`, :meth:`list`

The service is deliberately business-agnostic: it only knows job *types* as
opaque strings and invokes handlers registered by business modules.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from concurrent.futures import Executor
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .audit import AuditService, AuditSink, InMemoryAuditSink
from .concurrency import ConcurrencyLimiter
from .errors import DuplicateTaskError, OrchestrationError, TaskNotFoundError
from .lock import LockProvider, ProcessLockProvider
from .models import (
    JobType,
    TaskContext,
    TaskRun,
    TaskSpec,
    TaskStatus,
    TriggerType,
    _norm,
)
from .registry import DependencyRegistry, HandlerRegistry
from .retries import backoff_seconds, is_retryable, sleep_with_cancel
from .store import InMemoryTaskRunStore, TaskRunStore


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


logger = logging.getLogger(__name__)


class TaskService:
    def __init__(
        self,
        *,
        store: TaskRunStore,
        audit: Optional[AuditService] = None,
        audit_sink: Optional[AuditSink] = None,
        locks: Optional[LockProvider] = None,
        concurrency: Optional[ConcurrencyLimiter] = None,
        handlers: Optional[HandlerRegistry] = None,
        deps: Optional[DependencyRegistry] = None,
        clock: Optional[Callable[[], datetime]] = None,
        sleeper: Optional[Callable[[float], None]] = None,
        executor: Optional[Executor] = None,
    ) -> None:
        self._store = store
        #: Worker pool for background execution (:meth:`run_async`). ``None``
        #: means synchronous-only: ``dispatch(..., background=True)`` then raises.
        self._executor = executor
        if audit is not None:
            self._audit = audit
        else:
            self._audit = AuditService(audit_sink or InMemoryAuditSink())
        self._locks = locks or ProcessLockProvider()
        self._concurrency = concurrency or ConcurrencyLimiter()
        self._handlers = handlers or HandlerRegistry()
        self._deps = deps or DependencyRegistry()
        self._clock = clock or _default_clock
        self._sleeper = sleeper or __import__("time").sleep
        self._cancel_tokens: dict[int, bool] = {}

    # -- handler / dependency registration (business modules) ----------------
    def register_handler(
        self, job_type: "JobType | str", handler: Callable[[TaskContext], object]
    ) -> None:
        """Register the callable invoked for ``job_type`` (design D2/D3)."""
        self._handlers.register(job_type, handler)

    def add_dependency(
        self,
        upstream: "JobType | str",
        downstream: "JobType | str",
        build_spec: Optional[Callable[["TaskRun"], "TaskSpec"]] = None,
    ) -> None:
        """On success of ``upstream``, submit ``downstream`` (optionally deriving its spec)."""
        self._deps.on_success(upstream, downstream, build_spec)

    def registered_handlers(self) -> list[str]:
        """Names of all registered job types (for inspection/tests)."""
        return list(self._handlers._handlers.keys())

    # ------------------------------------------------------------------ submit
    def submit(self, spec: TaskSpec, *, actor: Optional[str] = None) -> TaskRun:
        """Create a task run. Rejects duplicates for an active job_type+scope."""
        scope_key = spec.scope_key()
        lock_key = f"reentry:{_norm(spec.job_type)}:{scope_key}"
        with self._locks.lock(lock_key):
            if self._store.exists_active(_norm(spec.job_type), scope_key):
                raise DuplicateTaskError(_norm(spec.job_type), scope_key)
            run = TaskRun(
                id=0,
                job_type=_norm(spec.job_type),
                scope=dict(spec.scope),
                trigger=str(spec.trigger),
                status=TaskStatus.PENDING,
                retry=spec.retry,
                timeout_sec=spec.timeout_sec,
                concurrency_key=spec.concurrency_key_resolved(),
                priority=spec.priority,
                payload=dict(spec.payload),
                submitted_by=actor,
            )
            self._store.create(run)
        self._audit.record(
            actor,
            "task.submit",
            entity_type="task",
            entity_fqn=f"{run.job_type}:{scope_key}",
            detail={"run_id": run.id, "trigger": run.trigger},
            result="accepted",
        )
        return run

    def dispatch(
        self, spec: TaskSpec, *, actor: Optional[str] = None, background: bool = False
    ) -> TaskRun:
        """Submit and execute a task.

        ``background=False`` (default) runs it inline and returns the *finished*
        run — convenient for tests and CLI. ``background=True`` hands it to the
        executor and returns immediately, so an HTTP request never blocks on a
        long scan; poll :meth:`get` to observe
        pending -> running -> success/failed/cancelled.

        The returned run is the *live* object the worker mutates, so its status
        may already have advanced to ``running`` (or even a terminal state for a
        very fast handler) by the time the caller inspects it — that is expected,
        not a synchronisation bug.
        """
        run = self.submit(spec, actor=actor)
        if background:
            self._schedule(run.id)
            # Return the run as submitted: the worker may already have advanced
            # it, and callers only need the identity/status at submit time.
            return run
        return self.run_now(run.id)

    # ------------------------------------------------------------- background
    def run_async(self, run_id: int) -> TaskRun:
        """Schedule :meth:`run_now` on the executor and return immediately."""
        self._schedule(run_id)
        run = self._store.get(run_id)
        if run is None:  # pragma: no cover - defensive
            raise TaskNotFoundError(run_id)
        return run

    def _schedule(self, run_id: int) -> None:
        """Hand a run to the executor, validating it exists and is runnable."""
        if self._executor is None:
            raise OrchestrationError("no executor configured for background execution")
        if self._store.get(run_id) is None:
            raise TaskNotFoundError(run_id)
        self._executor.submit(self._run_guarded, run_id)

    def _run_guarded(self, run_id: int) -> None:
        """Worker entrypoint: never let an exception escape into the executor.

        :meth:`run_now` already records handler failures, but it can itself raise
        (e.g. the run vanished). Mark the run failed so it is not left dangling
        in ``pending``/``running`` forever.
        """
        try:
            self.run_now(run_id)
        except Exception as exc:  # noqa: BLE001 - last-resort worker guard
            logger.exception("background task %s crashed", run_id)
            try:
                run = self._store.get(run_id)
                if run is not None and run.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    run.status = TaskStatus.FAILED
                    run.error_message = f"executor failure: {exc}"[:2000]
                    run.finished_at = self._clock()
                    self._store.update(run)
            except Exception:  # noqa: BLE001 - store unavailable too
                logger.exception("could not mark task %s as failed", run_id)

    # ------------------------------------------------------------------- execute
    def run_now(self, run_id: int) -> TaskRun:
        run = self._store.get(run_id)
        if run is None:
            raise TaskNotFoundError(run_id)

        handler = self._handlers.get(run.job_type)
        if handler is None:
            run.status = TaskStatus.FAILED
            run.error_message = f"no handler registered for job_type={run.job_type!r}"
            run.finished_at = self._clock()
            self._store.update(run)
            self._audit.record(
                run.submitted_by, "task.failure", entity_type="task",
                entity_fqn=f"{run.job_type}:{run.scope_key()}",
                detail={"run_id": run.id, "error": run.error_message}, result="failed",
            )
            return run

        self._concurrency.acquire(run.concurrency_key)
        try:
            is_cancelled = lambda: self._cancel_tokens.get(run.id, False)
            ctx = TaskContext(run=run, attempt=0, cancelled=is_cancelled)
            run.status = TaskStatus.RUNNING
            run.started_at = self._clock()
            self._store.update(run)

            success = False
            last_exc: Optional[BaseException] = None
            for attempt in range(1, run.retry.max_attempts + 1):
                run.attempts = attempt
                ctx.attempt = attempt
                try:
                    result = handler(ctx) if not inspect.iscoroutinefunction(handler) \
                        else asyncio.run(handler(ctx))
                    run.stats = result if isinstance(result, dict) else {"result": repr(result)}
                    success = True
                    break
                except Exception as exc:  # noqa: BLE001 - orchestrator catches all
                    last_exc = exc
                    if not is_retryable(exc) or attempt >= run.retry.max_attempts:
                        break
                    if sleep_with_cancel(
                        backoff_seconds(attempt, run.retry), is_cancelled, self._sleeper
                    ):
                        break  # cancelled during back-off

            finished = self._clock()
            run.finished_at = finished
            if run.started_at:
                run.duration_ms = int((finished - run.started_at).total_seconds() * 1000)

            if is_cancelled():
                run.status = TaskStatus.CANCELLED
                run.error_message = "cancelled"
            elif success:
                run.status = TaskStatus.SUCCESS
            else:
                run.status = TaskStatus.FAILED
                run.error_message = (str(last_exc) or repr(last_exc))[:2000]

            self._store.update(run)
            action = {
                TaskStatus.SUCCESS: "task.success",
                TaskStatus.CANCELLED: "task.cancel",
                TaskStatus.FAILED: "task.failure",
            }.get(run.status, "task.failure")
            self._audit.record(
                run.submitted_by, action, entity_type="task",
                entity_fqn=f"{run.job_type}:{run.scope_key()}",
                detail={"run_id": run.id, "attempts": run.attempts, "stats": run.stats},
                result=run.status.value,
            )

            if run.status == TaskStatus.SUCCESS:
                self._trigger_downstream(run)

            return run
        finally:
            self._concurrency.release(run.concurrency_key)
            self._cancel_tokens.pop(run.id, None)

    # ------------------------------------------------------------------ control
    def cancel(self, run_id: int, *, actor: Optional[str] = None) -> bool:
        run = self._store.get(run_id)
        if run is None:
            raise TaskNotFoundError(run_id)
        if run.status == TaskStatus.PENDING:
            run.status = TaskStatus.CANCELLED
            run.finished_at = self._clock()
            self._store.update(run)
            self._audit.record(
                actor, "task.cancel", entity_type="task",
                entity_fqn=f"{run.job_type}:{run.scope_key()}",
                detail={"run_id": run.id}, result="cancelled",
            )
            return True
        if run.status == TaskStatus.RUNNING:
            self._cancel_tokens[run_id] = True
            self._audit.record(
                actor, "task.cancel", entity_type="task",
                entity_fqn=f"{run.job_type}:{run.scope_key()}",
                detail={"run_id": run.id, "note": "signal sent to running task"},
                result="cancel-signal",
            )
            return True
        return False

    def retry(
        self, run_id: int, *, actor: Optional[str] = None, background: bool = False
    ) -> TaskRun:
        run = self._store.get(run_id)
        if run is None:
            raise TaskNotFoundError(run_id)
        if run.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise OrchestrationError(
                f"only FAILED/CANCELLED tasks can be retried (got {run.status.value})"
            )
        spec = TaskSpec(
            job_type=run.job_type,
            scope=dict(run.scope),
            trigger=TriggerType.MANUAL,
            retry=run.retry,
            timeout_sec=run.timeout_sec,
            concurrency_key=run.concurrency_key,
            priority=run.priority,
            payload=dict(run.payload),
        )
        return self.dispatch(spec, actor=actor or run.submitted_by, background=background)

    # ------------------------------------------------------------------ queries
    def get(self, run_id: int) -> Optional[TaskRun]:
        return self._store.get(run_id)

    def list(
        self,
        *,
        job_type: Optional[JobType | str] = None,
        status: Optional[TaskStatus] = None,
        datasource_id: Optional[int] = None,
    ) -> List[TaskRun]:
        jt = _norm(job_type) if job_type is not None else None
        return self._store.list(job_type=jt, status=status, datasource_id=datasource_id)

    # -------------------------------------------------------------- dependencies
    def _trigger_downstream(self, finished: TaskRun) -> None:
        for ds_job, build in self._deps.downstreams_for(finished.job_type):
            spec = (
                build(finished)
                if build is not None
                else TaskSpec(
                    job_type=ds_job,
                    scope=dict(finished.scope),
                    trigger=TriggerType.EVENT,
                    payload={"upstream_run_id": finished.id},
                )
            )
            try:
                child = self.submit(spec, actor="orchestrator")
            except DuplicateTaskError:
                # upstream replay must not spawn duplicate downstreams
                continue
            self.run_now(child.id)
