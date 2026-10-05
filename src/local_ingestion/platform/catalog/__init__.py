"""Catalog overview (MOD-09 / T-213)."""
from __future__ import annotations

from .models import (
    SENSITIVE_GRADE_THRESHOLD,
    UNGRADED_KEY,
    CatalogOverview,
)
from .source import (
    CatalogStatsSource,
    InMemoryCatalogStatsSource,
    SqlCatalogStatsSource,
)
from .service import OverviewService, TtlCache


def build_in_memory_overview_service(table_grades=None, column_grades=None,
                                     change_source=None, ttl: float = 60.0):
    """Wire an in-memory overview service (no database required)."""
    src = InMemoryCatalogStatsSource(table_grades, column_grades)
    return OverviewService(src, change_source=change_source, ttl=ttl)


__all__ = [
    "SENSITIVE_GRADE_THRESHOLD",
    "UNGRADED_KEY",
    "CatalogOverview",
    "CatalogStatsSource",
    "InMemoryCatalogStatsSource",
    "SqlCatalogStatsSource",
    "OverviewService",
    "TtlCache",
    "build_in_memory_overview_service",
]
