"""Asset detail aggregation models (MOD-09 / T-212).

An asset detail card stitches together data owned by several modules. Only the
catalog (MOD-02) slice is populated today; the rest are placeholder/degraded
until their owning modules land.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SOURCE_CATALOG = "catalog"
SOURCE_BUSINESS = "business"
SOURCE_QUALITY = "quality"
SOURCE_LINEAGE = "lineage"
SOURCE_GRANTS = "grants"
SOURCE_CHANGES = "changes"


@dataclass
class ColumnBrief:
    name: str
    data_type: str
    nullable: bool
    comment: Optional[str] = None
    is_pii: bool = False
    importance: int = 0


@dataclass
class AssetDetail:
    fqn: str
    entity_type: Optional[str] = None
    name: Optional[str] = None
    schema: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    owner: Optional[str] = None
    is_pii: bool = False
    importance: int = 0
    columns: List[ColumnBrief] = field(default_factory=list)
    business: Optional[Dict[str, Any]] = None
    quality: Optional[Dict[str, Any]] = None
    lineage: Optional[Dict[str, Any]] = None
    grants: Optional[Dict[str, Any]] = None
    recent_changes: Optional[Dict[str, Any]] = None
    degraded_sources: List[str] = field(default_factory=list)
    # --- 字段详情（entity_type == "column"）使用的切片 ---
    parent_fqn: Optional[str] = None
    data_type: Optional[str] = None
    nullable: Optional[bool] = None
    # --- 归属信息：表/字段都带，前端据此渲染数据源与分级 ---
    datasource_id: Optional[int] = None
    grade_level: Optional[int] = None
