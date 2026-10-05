"""Degraded dependency placeholders for deferred modules (T-215, MOD-09 D7).

Each placeholder represents an upstream module MOD-09/MOD-06 depends on but which
may be undeployed. Its availability is driven by :class:`FeatureAvailability`, so
when a module is later deployed, flipping the flag makes the dependency "available"
with no code change in the consumer.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..resilience.feature import (
    MOD_AUTHORIZATION,
    MOD_LINEAGE,
    MOD_VISIBILITY,
    FeatureAvailability,
)


@dataclass
class DependencyStatus:
    name: str
    module: str
    available: bool
    reason: str


class DegradedDependency:
    name: str = ""
    module: str = ""
    unavailable_reason: str = "not deployed"

    def status(self, avail: FeatureAvailability) -> DependencyStatus:
        available = avail.is_available(self.module)
        return DependencyStatus(
            name=self.name,
            module=self.module,
            available=available,
            reason="" if available else self.unavailable_reason,
        )


class LineageSummaryProvider(DegradedDependency):
    name = "lineage"
    module = MOD_LINEAGE
    unavailable_reason = "MOD-07 lineage not deployed"


class AuthorizationProvider(DegradedDependency):
    name = "authorization"
    module = MOD_AUTHORIZATION
    unavailable_reason = "MOD-08 authorization analysis not deployed"


class VisibilityProvider(DegradedDependency):
    name = "visibility"
    module = MOD_VISIBILITY
    unavailable_reason = "MOD-11 data visibility not deployed"
