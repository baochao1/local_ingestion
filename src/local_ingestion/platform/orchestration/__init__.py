"""Orchestration package (MOD-10 / T-107): the platform task backbone.

Public surface used by business modules (contracts C9 / C10):

* ``TaskService`` — submit / dispatch / cancel / retry / query tasks.
* ``AuditService`` — record key actions (``AuditService.record``).
* ``HandlerRegistry`` / ``DependencyRegistry`` — wire business handlers & chains.
* ``build_in_memory_orchestration`` — a ready-to-use in-process stack (MVP).
"""
from __future__ import annotations

from .audit import AuditEntry, AuditService, AuditSink, InMemoryAuditSink, SqlAuditSink
from .concurrency import ConcurrencyLimiter
from .errors import (
    ConcurrencyLimitError,
    DuplicateTaskError,
    OrchestrationError,
    TaskNotFoundError,
)
from .lock import LockProvider, ProcessLockProvider
from .models import (
    JobType,
    RetryPolicy,
    TaskContext,
    TaskRun,
    TaskSpec,
    TaskStatus,
    TriggerType,
)
from .registry import DependencyRegistry, HandlerRegistry
from .retries import backoff_seconds, is_retryable, sleep_with_cancel
from .service import TaskService
from .store import (
    InMemoryTaskRunStore,
    SqlTaskRunStore,
    TaskRunStore,
)


def build_in_memory_orchestration(
    *,
    max_global: int = 8,
    per_key_limits: dict | None = None,
    clock=None,
    sleeper=None,
    audit: "AuditService | None" = None,
    concurrency: "ConcurrencyLimiter | None" = None,
):
    """Construct a fully wired in-process orchestration stack (no database).

    Use for the single-instance MVP runtime and for unit tests. Swap the store /
    audit sink for their ``Sql*`` counterparts when a Postgres backend is wired.
    Pass ``audit`` / ``concurrency`` to override the default in-memory instances.
    """
    store = InMemoryTaskRunStore(clock=clock)
    audit = audit or AuditService(InMemoryAuditSink(), clock=clock)
    concurrency = concurrency or ConcurrencyLimiter(
        max_global=max_global, per_key_limits=per_key_limits
    )
    return TaskService(
        store=store,
        audit=audit,
        concurrency=concurrency,
        locks=ProcessLockProvider(),
        handlers=HandlerRegistry(),
        deps=DependencyRegistry(),
        clock=clock,
        sleeper=sleeper,
    )


def build_sql_orchestration(
    *,
    session_factory=None,
    max_global: int = 8,
    per_key_limits: dict | None = None,
    clock=None,
    sleeper=None,
    audit: "AuditService | None" = None,
    concurrency: "ConcurrencyLimiter | None" = None,
):
    """Same wiring as :func:`build_in_memory_orchestration` but persists runs.

    Task runs land in the ``scan_run`` table via :class:`SqlTaskRunStore`, so they
    survive process restarts. 审计 sink 保持与内存版一致（默认 ``GLOBAL_AUDIT_SINK``
    的行为不变），避免影响审计页现有展示。
    """
    if session_factory is None:
        from ..storage.session import session_scope

        session_factory = session_scope
    store = SqlTaskRunStore(session_factory)
    audit = audit or AuditService(InMemoryAuditSink(), clock=clock)
    concurrency = concurrency or ConcurrencyLimiter(
        max_global=max_global, per_key_limits=per_key_limits
    )
    return TaskService(
        store=store,
        audit=audit,
        concurrency=concurrency,
        locks=ProcessLockProvider(),
        handlers=HandlerRegistry(),
        deps=DependencyRegistry(),
        clock=clock,
        sleeper=sleeper,
    )


__all__ = [
    "AuditEntry", "AuditService", "AuditSink", "InMemoryAuditSink", "SqlAuditSink",
    "ConcurrencyLimiter",
    "ConcurrencyLimitError", "DuplicateTaskError", "OrchestrationError", "TaskNotFoundError",
    "LockProvider", "ProcessLockProvider",
    "JobType", "RetryPolicy", "TaskContext", "TaskRun", "TaskSpec", "TaskStatus", "TriggerType",
    "DependencyRegistry", "HandlerRegistry",
    "backoff_seconds", "is_retryable", "sleep_with_cancel",
    "TaskService", "InMemoryTaskRunStore", "SqlTaskRunStore", "TaskRunStore",
    "build_in_memory_orchestration",
    "build_sql_orchestration",
]
