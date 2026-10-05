"""Asset detail aggregation (MOD-09 / T-212)."""
from __future__ import annotations

from typing import Dict

from .models import (
    SOURCE_BUSINESS,
    SOURCE_CATALOG,
    SOURCE_CHANGES,
    SOURCE_GRANTS,
    SOURCE_LINEAGE,
    SOURCE_QUALITY,
    AssetDetail,
    ColumnBrief,
)
from .providers import (
    AssetDetailProvider,
    InMemoryCatalogProvider,
    PlaceholderProvider,
    SqlCatalogProvider,
)
from .service import AssetDetailService


def build_in_memory_asset_service(tables: Dict[str, Dict]) -> AssetDetailService:
    """Fully wired in-process asset detail service with placeholder slices."""
    providers = [
        InMemoryCatalogProvider(tables),
        PlaceholderProvider(SOURCE_BUSINESS),
        PlaceholderProvider(SOURCE_QUALITY),
        PlaceholderProvider(SOURCE_LINEAGE),
        PlaceholderProvider(SOURCE_GRANTS),
        PlaceholderProvider(SOURCE_CHANGES),
    ]
    return AssetDetailService(providers)


__all__ = [
    "SOURCE_BUSINESS",
    "SOURCE_CATALOG",
    "SOURCE_CHANGES",
    "SOURCE_GRANTS",
    "SOURCE_LINEAGE",
    "SOURCE_QUALITY",
    "AssetDetail",
    "ColumnBrief",
    "AssetDetailProvider",
    "InMemoryCatalogProvider",
    "PlaceholderProvider",
    "SqlCatalogProvider",
    "AssetDetailService",
    "build_in_memory_asset_service",
]
