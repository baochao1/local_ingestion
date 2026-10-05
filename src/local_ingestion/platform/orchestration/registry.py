"""Handler and dependency registries (FR-12.7 / T-107, design D2/D3).

The orchestrator is deliberately business-agnostic. Business modules *register*
a callable for a job type and declare dependency rules; the orchestrator only
knows how to invoke and chain them.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from .models import JobType, TaskContext, TaskRun, TaskSpec, _norm


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[[TaskContext], object]] = {}

    def register(
        self, job_type: JobType | str, handler: Callable[[TaskContext], object]
    ) -> None:
        self._handlers[_norm(job_type)] = handler

    def get(self, job_type: str) -> Optional[Callable[[TaskContext], object]]:
        return self._handlers.get(_norm(job_type))

    def has(self, job_type: str) -> bool:
        return _norm(job_type) in self._handlers


class DependencyRegistry:
    """Declarative dependency rules: on success of an upstream job, submit/run
    downstream tasks. ``build_spec`` optionally derives the downstream spec from
    the finished upstream run."""

    def __init__(self) -> None:
        # (upstream_job_type, downstream_job_type, optional build_spec(run)->TaskSpec)
        self._rules: List[Tuple[str, str, Optional[Callable[[TaskRun], TaskSpec]]]] = []

    def on_success(
        self,
        upstream: JobType | str,
        downstream: JobType | str,
        build_spec: Optional[Callable[[TaskRun], TaskSpec]] = None,
    ) -> None:
        self._rules.append((_norm(upstream), _norm(downstream), build_spec))

    def downstreams_for(
        self, upstream_job_type: str
    ) -> List[Tuple[str, Optional[Callable[[TaskRun], TaskSpec]]]]:
        return [
            (ds, build) for (up, ds, build) in self._rules if up == _norm(upstream_job_type)
        ]
