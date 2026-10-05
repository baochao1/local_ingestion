"""Degradation placeholders & registry for deferred modules (T-215 / MOD-09 D7)."""
from __future__ import annotations

from .providers import (
    AuthorizationProvider,
    DegradedDependency,
    DependencyStatus,
    LineageSummaryProvider,
    VisibilityProvider,
)
from .registry import DegradationRegistry, build_default_registry

__all__ = [
    "AuthorizationProvider",
    "DegradedDependency",
    "DependencyStatus",
    "LineageSummaryProvider",
    "VisibilityProvider",
    "DegradationRegistry",
    "build_default_registry",
]
