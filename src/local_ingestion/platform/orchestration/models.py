"""Task orchestration domain models (MOD-10 / T-107).

These are plain dataclasses/enums so the orchestration core stays free of any
business semantics (design decision D3: the orchestrator must not know what a
scan, a sample or a classification *is*). Persistence is delegated to a
``TaskRunStore`` implementation (in-memory for tests, SQLAlchemy for prod).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    #: Handler ran, but part of the work failed (FR-M9). Distinguishing this
    #: from a total failure matters: a profile run over 200 tables where 3
    #: errored still produced 197 usable results, and reporting "failed" hides
    #: them.
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TriggerType(str, Enum):
    MANUAL = "manual"
    CRON = "cron"
    EVENT = "event"


class JobType(str, Enum):
    METADATA = "metadata"
    SAMPLE = "sample"
    PROFILE = "profile"
    CLASSIFY = "classify"
    LINEAGE = "lineage"
    PERMISSION = "permission"
    QUALITY = "quality"


def _norm(value: Any) -> str:
    """Normalise a job-type (enum or raw string) to its canonical string."""
    if isinstance(value, JobType):
        return value.value
    return str(value)


def scope_key_of(scope: Dict[str, Any]) -> str:
    """Canonical, stable key for a scope, used for re-entry protection."""
    items = sorted((str(k), str(v)) for k, v in scope.items())
    return "|".join(f"{k}={v}" for k, v in items)


@dataclass
class RetryPolicy:
    max_attempts: int = 1
    base_delay_sec: float = 1.0
    max_delay_sec: float = 60.0
    jitter: bool = True


@dataclass
class TaskSpec:
    job_type: JobType | str
    scope: Dict[str, Any]
    trigger: TriggerType | str = TriggerType.MANUAL
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_sec: float | None = None
    concurrency_key: str | None = None
    priority: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def datasource_id(self) -> int | None:
        ds = self.scope.get("datasource_id")
        return int(ds) if ds is not None else None

    def scope_key(self) -> str:
        return scope_key_of(self.scope)

    def concurrency_key_resolved(self) -> str:
        if self.concurrency_key:
            return self.concurrency_key
        if self.datasource_id is not None:
            return f"ds:{self.datasource_id}"
        return f"job:{_norm(self.job_type)}"


@dataclass
class TaskRun:
    id: int
    job_type: str
    scope: Dict[str, Any]
    trigger: str
    status: TaskStatus
    retry: RetryPolicy
    timeout_sec: float | None
    concurrency_key: str
    priority: int
    payload: Dict[str, Any]
    submitted_by: str | None = None
    attempts: int = 0
    stats: Dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime | None = None

    def scope_key(self) -> str:
        return scope_key_of(self.scope)


@dataclass
class TaskContext:
    """Passed to a task handler. Carries identity + a cancellation probe."""

    run: TaskRun
    attempt: int
    cancelled: Callable[[], bool]
