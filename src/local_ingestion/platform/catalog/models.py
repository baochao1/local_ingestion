"""Catalog overview domain models (MOD-09 / T-213).

A pre-computed, cacheable rollup of the governed estate: asset volume, grade
distribution, sensitive-asset ratio, quality distribution and recent change
trend. Real counts come from ``catalog_table`` / ``catalog_column``; quality is
degraded (unavailable) until its module lands, and is reported as such rather
than failing the request.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

# grade_level >= this is treated as "sensitive / high" for the sensitive ratio.
SENSITIVE_GRADE_THRESHOLD = 2

UNGRADED_KEY = "ungraded"

# 分级桶：对外只用 L1..L4 + ungraded。历史上这里直接吐 `grade_level` 原值
# （"1"/"2"… 甚至超出定义的 "5"），前端按 "L1" 取值永远拿不到，
# 首页分级分布因此恒为 0（doc/design/ux-audit-full.md S1#5 / B3）。
GRADE_KEYS = ("L1", "L2", "L3", "L4")


def grade_key(level: Optional[int]) -> str:
    """`grade_level` → 对外分级键；1..4 → L1..L4，其余（含 None / 越界）归为未分级。"""
    if level is None:
        return UNGRADED_KEY
    try:
        n = int(level)
    except (TypeError, ValueError):
        return UNGRADED_KEY
    if 1 <= n <= len(GRADE_KEYS):
        return GRADE_KEYS[n - 1]
    return UNGRADED_KEY


@dataclass
class CatalogOverview:
    tables_count: int
    columns_count: int
    grade_distribution: Dict[str, int]
    sensitive_count: int
    sensitive_ratio: float
    quality_distribution: Dict[str, int]
    change_trend: Dict[str, int]
    degraded_sources: List[str]
    computed_at: datetime
    # 数据源数量：首页「数据源」指标此前永远显示 0，因为响应里根本没有这个字段
    datasources_count: int = 0
