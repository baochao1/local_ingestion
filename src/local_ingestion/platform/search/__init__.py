"""Global search (MOD-09 / T-211)."""
from __future__ import annotations

from .models import CatalogRecord, SearchHit, SearchQuery, SearchResult
from .repository import (
    CatalogRepository,
    InMemoryCatalogRepository,
    SqlCatalogRepository,
)
from .service import SearchService, tokenize

__all__ = [
    "CatalogRecord",
    "SearchHit",
    "SearchQuery",
    "SearchResult",
    "CatalogRepository",
    "InMemoryCatalogRepository",
    "SqlCatalogRepository",
    "SearchService",
    "tokenize",
]
