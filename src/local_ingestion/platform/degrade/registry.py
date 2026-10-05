"""Degradation registry aggregating deferred-module placeholders (T-215).

Consumers (e.g. catalog detail / search) query ``degraded_sources()`` to mark
unavailable sections instead of erroring, fulfilling MOD-09 §4.4 and FR-7.6.
"""
from __future__ import annotations

from typing import List

from ..resilience.feature import FeatureAvailability, default_availability
from .providers import (
    AuthorizationProvider,
    DegradedDependency,
    DependencyStatus,
    LineageSummaryProvider,
    VisibilityProvider,
)


class DegradationRegistry:
    def __init__(self, providers: List[DegradedDependency] | None = None,
                 availability: FeatureAvailability | None = None) -> None:
        self._providers: List[DegradedDependency] = list(providers or [
            LineageSummaryProvider(),
            AuthorizationProvider(),
            VisibilityProvider(),
        ])
        self._avail: FeatureAvailability = availability or default_availability()

    def statuses(self) -> List[DependencyStatus]:
        return [p.status(self._avail) for p in self._providers]

    def degraded_sources(self) -> List[str]:
        return [s.name for s in self.statuses() if not s.available]

    def describe(self) -> dict:
        return {
            "degraded_sources": self.degraded_sources(),
            "dependencies": [
                {"name": s.name, "module": s.module, "available": s.available, "reason": s.reason}
                for s in self.statuses()
            ],
        }


def build_default_registry() -> DegradationRegistry:
    return DegradationRegistry()
