"""Schema versioning & change analysis (MOD-06 / T-201, T-202)."""
from __future__ import annotations

from .adapter import build_catalog_state
from .classify import ImpactClassifier
from .diff import SchemaDiffer
from .models import (
    CatalogState,
    Change,
    ColumnSpec,
    DiffResult,
    GradedChange,
    TableSpec,
)

__all__ = [
    "build_catalog_state",
    "ImpactClassifier",
    "SchemaDiffer",
    "CatalogState",
    "Change",
    "ColumnSpec",
    "DiffResult",
    "GradedChange",
    "TableSpec",
]
