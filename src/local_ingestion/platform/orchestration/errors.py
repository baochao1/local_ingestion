"""Exceptions raised by the orchestration layer (MOD-10 / T-107)."""
from __future__ import annotations


class OrchestrationError(Exception):
    """Base class for all orchestration errors."""


class DuplicateTaskError(OrchestrationError):
    """Raised when a task with the same job_type+scope is already active."""

    def __init__(self, job_type: str, scope_key: str):
        self.job_type = job_type
        self.scope_key = scope_key
        super().__init__(
            f"Active task already exists for job_type={job_type!r} scope={scope_key!r}"
        )


class TaskNotFoundError(OrchestrationError):
    def __init__(self, run_id: int):
        self.run_id = run_id
        super().__init__(f"Task run {run_id} not found")


class ConcurrencyLimitError(OrchestrationError):
    """Raised when a concurrency slot cannot be acquired in time."""
