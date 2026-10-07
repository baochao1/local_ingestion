"""Catalog search endpoint (MOD-09 / T-211).

:class:`SearchService` and :class:`SqlCatalogRepository` were fully implemented
(trigram/ILIKE queries + relevance scoring) but had **no HTTP route**, so the
search capability was invisible to any client. This mounts it against the real
catalog tables.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from ...api.serialization import camelize
from ...search.facets import DEFAULT_TOP_N, FACET_DIMENSIONS, compute_facets
from ...search.models import SearchQuery, SearchResult
from ...search.service import SearchService
from ...storage.session import session_scope

router = APIRouter(prefix="/api/v1/search", tags=["Search"])


def get_search_service() -> SearchService:
    """Production wiring: SQL repository over ``catalog_*``."""
    from ...search.repository import SqlCatalogRepository
    from ...storage.session import session_scope

    return SearchService(SqlCatalogRepository(session_scope))


@router.get("/facets")
def search_facets(
    term: Optional[str] = None,
    type: Optional[str] = Query(None, description="table | column"),
    datasourceId: Optional[int] = None,
    tags: Optional[List[str]] = Query(None),
    owner: Optional[str] = None,
    sensitiveOnly: bool = False,
    gradeMin: Optional[int] = None,
    topN: int = Query(DEFAULT_TOP_N, ge=1, le=100, description="buckets per dimension"),
) -> Dict[str, Any]:
    """Hit counts per dimension, for narrowing a search (FR-M3).

    Separate from ``GET /search`` on purpose: results and facets have different
    cost profiles, and keeping them apart means a slow facet computation can
    never delay the result list (NFR-M2).
    """
    facets = compute_facets(
        session_scope,
        term=term,
        datasource_id=datasourceId,
        type=type,
        tags=tags,
        owner=owner,
        grade_min=gradeMin,
        sensitive_only=sensitiveOnly,
        top_n=topN,
    )
    return camelize({"dimensions": list(FACET_DIMENSIONS), "facets": facets})


@router.get("")
def search(
    term: Optional[str] = None,
    type: Optional[str] = Query(None, description="table | column"),
    datasourceId: Optional[int] = None,
    tags: Optional[List[str]] = Query(None),
    owner: Optional[str] = None,
    sensitiveOnly: bool = False,
    gradeMin: Optional[int] = Query(None, description="filter by grade_level >= N (1-9)"),
    limit: int = 20,
    offset: int = 0,
    svc: SearchService = Depends(get_search_service),
) -> Dict[str, Any]:
    """Search tables and columns of the catalog."""
    result: SearchResult = svc.search(
        SearchQuery(
            term=term,
            type=type,
            datasource_id=datasourceId,
            tags=tags or [],
            owner=owner,
            sensitive_only=sensitiveOnly,
            grade_min=gradeMin,
            limit=limit,
            offset=offset,
        )
    )
    return camelize(asdict(result))
