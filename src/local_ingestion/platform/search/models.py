"""Global search domain models (MOD-09 / T-211).

The search service is storage-agnostic: the repository hands back normalized
:class:`CatalogRecord` objects (built from the ``catalog_*`` tables or an
in-memory fixture), and the service applies scoring + filtering + pagination.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CatalogRecord:
    """Normalized catalog entry returned by a search repository."""

    fqn: str
    name: str
    entity_type: str  # "table" | "column"
    datasource_id: int
    schema: Optional[str] = None
    parent_fqn: Optional[str] = None  # set for columns (owning table fqn)
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    owner: Optional[str] = None
    is_pii: bool = False
    importance: int = 0
    # 资产主键：前端需要用它在目录列表里跳详情（/catalog/tables/{id}）
    id: Optional[int] = None


@dataclass
class SearchQuery:
    term: Optional[str] = None
    type: Optional[str] = None  # "table" | "column"
    datasource_id: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    owner: Optional[str] = None
    sensitive_only: bool = False
    grade_min: Optional[int] = None  # filter importance (grade_level) >= N
    limit: int = 20
    offset: int = 0


@dataclass
class SearchHit:
    entity_type: str
    fqn: str
    name: str
    datasource_id: int
    schema: Optional[str] = None
    parent_fqn: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    owner: Optional[str] = None
    is_pii: bool = False
    score: float = 0.0
    matched_in: List[str] = field(default_factory=list)
    # 透传 CatalogRecord.id，供前端跳详情
    id: Optional[int] = None


@dataclass
class SearchResult:
    items: List[SearchHit]
    total: int
    limit: int
    offset: int
