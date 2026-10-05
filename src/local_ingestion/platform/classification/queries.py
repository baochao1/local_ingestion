"""分类分级结果查询（MOD-05 界面侧）。

为什么单独一个模块
------------------
``service.py`` 负责**写**（扫完给 catalog 行打级），这里的查询面向**界面**：
覆盖率、敏感资产清单、分级标准、识别规则。两者职责不同，读写分离。

分级阶梯以 :mod:`platform.classification.rules` 为准（**1–5 级**）::

    1 INTERNAL      一般业务数据，不含个人信息
    2 SENSITIVE     业务敏感但非个人身份（金额、余额、价格…）
    3 PII           可识别到自然人（姓名、手机、邮箱、地址…）
    4 PII_HIGH      强标识 / 高敏个人信息（证件号、银行卡…）
    5 CONFIDENTIAL  机密（工资、征信、密钥、口令…）

!!! 已知不一致（须修，见 doc/design/product-benchmark-roadmap.md P1-1）
------------------------------------------------------------------------
``classification_tag`` 表里 seed 的是 **L1–L4** 四档（``L1_PUBLIC`` … ``L4_CORE``），
而引擎写进 ``catalog_column.grade_level`` 的是 **1–5**。两套语义并存会让界面
自相矛盾（同一个字段，标签说 L2、级别说 3）。本模块**一律以引擎的 1–5 为准**，
因为那是实际参与变更影响判定与概览统计的值；标签库的 ``grade_level``
按标签自身语义展示。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from ..api.pagination import KeysetPage, encode_cursor, decode_cursor


#: GB/T 43697-2024 的三级框架（核心 / 重要 / 一般）。
#: 自建 1–5 级是其业务化细化，导出与合规口径按此归并（对标 S0-2）。
GB_LEVELS = ("核心", "重要", "一般")

#: 引擎的级别阶梯。界面文案与之对齐；`gb_level` 为该级别对应的 GB/T 43697 级别。
GRADE_LADDER: Dict[int, Dict[str, str]] = {
    1: {"code": "INTERNAL", "label": "内部", "gb_level": "一般",
        "description": "一般业务数据，不含个人信息"},
    2: {"code": "SENSITIVE", "label": "业务敏感", "gb_level": "一般",
        "description": "金额、余额、价格等业务敏感数据"},
    3: {"code": "PII", "label": "个人信息", "gb_level": "重要",
        "description": "可识别到自然人（姓名、手机、邮箱、地址）"},
    4: {"code": "PII_HIGH", "label": "高敏个人信息", "gb_level": "重要",
        "description": "证件号、银行卡、医疗、生物特征"},
    5: {"code": "CONFIDENTIAL", "label": "机密", "gb_level": "核心",
        "description": "工资、征信、密钥、口令"},
}


def gb_level_of(grade: Optional[int]) -> str:
    """业务级别 → GB/T 43697 级别；未分级/未知一律归为「一般」。"""
    if grade is None:
        return "一般"
    return GRADE_LADDER.get(int(grade), {}).get("gb_level", "一般")

#: 达到该级别即计入"敏感资产"（与 ``catalog.source`` 的阈值一致）。
SENSITIVE_THRESHOLD = 2


@dataclass
class DatasourceCoverage:
    """单个数据源的分级覆盖情况。"""

    datasource_id: int
    name: Optional[str] = None
    total_columns: int = 0
    graded_columns: int = 0
    sensitive_columns: int = 0
    total_tables: int = 0
    graded_tables: int = 0

    @property
    def coverage_ratio(self) -> float:
        if not self.total_columns:
            return 0.0
        return round(self.graded_columns / self.total_columns, 4)


@dataclass
class CoverageSummary:
    """分级覆盖率（FR-9.11）。"""

    total_columns: int = 0
    graded_columns: int = 0
    sensitive_columns: int = 0
    total_tables: int = 0
    graded_tables: int = 0
    #: 级别 → 字段数，含 ``"ungraded"`` 键（未分级字段单列，不算作 L1）。
    grade_distribution: Dict[str, int] = field(default_factory=dict)
    by_datasource: List[DatasourceCoverage] = field(default_factory=list)

    @property
    def coverage_ratio(self) -> float:
        if not self.total_columns:
            return 0.0
        return round(self.graded_columns / self.total_columns, 4)

    @property
    def sensitive_ratio(self) -> float:
        if not self.graded_columns:
            return 0.0
        return round(self.sensitive_columns / self.graded_columns, 4)


@dataclass
class SensitiveAsset:
    """敏感资产清单条目（FR-9.8）。默认字段级。"""

    id: int
    entity_type: str  # column | table
    name: str
    fqn: str
    datasource_id: int
    grade_level: int
    table_id: Optional[int] = None
    table_name: Optional[str] = None
    table_fqn: Optional[str] = None
    data_type: Optional[str] = None
    grade_code: Optional[str] = None
    grade_reason: Optional[str] = None
    is_pii: bool = False
    tags: List[str] = field(default_factory=list)


@dataclass
class TagDef:
    """分级标准（``classification_tag``）。"""

    id: int
    tag_key: str
    tag_name: str
    category: Optional[str] = None
    grade_level: Optional[int] = None
    grade_code: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True


@dataclass
class RuleDef:
    """识别规则（``classification_rule``）。"""

    id: int
    tag_key: str
    rule_kind: str
    pattern: Optional[str] = None
    confidence: float = 0.0
    priority: int = 100
    enabled: bool = True


# --------------------------------------------------------------------- 边界


class ClassificationQueryRepository(Protocol):
    def coverage(self, *, datasource_id: Optional[int]) -> CoverageSummary: ...

    def sensitive_assets(
        self,
        *,
        grade_min: int,
        datasource_id: Optional[int],
        entity_type: str,
        keyword: Optional[str],
        cursor: Optional[str],
        limit: int,
    ) -> List[SensitiveAsset]: ...

    def list_tags(self) -> List[TagDef]: ...

    def list_rules(self) -> List[RuleDef]: ...


class InMemoryClassificationQueryRepository:
    """内存实现：单元测试用，语义与 SQL 实现一致。"""

    def __init__(
        self,
        *,
        columns: Optional[List[Dict[str, Any]]] = None,
        tables: Optional[List[Dict[str, Any]]] = None,
        tags: Optional[List[TagDef]] = None,
        rules: Optional[List[RuleDef]] = None,
        datasource_names: Optional[Dict[int, str]] = None,
    ) -> None:
        self._columns = list(columns or [])
        self._tables = list(tables or [])
        self._tags = list(tags or [])
        self._rules = list(rules or [])
        self._names = dict(datasource_names or {})

    def coverage(self, *, datasource_id: Optional[int]) -> CoverageSummary:
        cols = [c for c in self._columns
                if datasource_id is None or c["datasource_id"] == datasource_id]
        tabs = [t for t in self._tables
                if datasource_id is None or t["datasource_id"] == datasource_id]

        summary = CoverageSummary()
        dist: Dict[str, int] = {}
        for c in cols:
            summary.total_columns += 1
            lvl = c.get("grade_level")
            if lvl is None:
                dist["ungraded"] = dist.get("ungraded", 0) + 1
                continue
            summary.graded_columns += 1
            if int(lvl) >= SENSITIVE_THRESHOLD:
                summary.sensitive_columns += 1
            dist[str(int(lvl))] = dist.get(str(int(lvl)), 0) + 1
        for t in tabs:
            summary.total_tables += 1
            if t.get("grade_level") is not None:
                summary.graded_tables += 1
        summary.grade_distribution = dist

        # 按数据源分组
        by_ds: Dict[int, DatasourceCoverage] = {}
        for c in cols:
            ds = by_ds.setdefault(
                c["datasource_id"],
                DatasourceCoverage(
                    datasource_id=c["datasource_id"],
                    name=self._names.get(c["datasource_id"]),
                ),
            )
            ds.total_columns += 1
            lvl = c.get("grade_level")
            if lvl is not None:
                ds.graded_columns += 1
                if int(lvl) >= SENSITIVE_THRESHOLD:
                    ds.sensitive_columns += 1
        for t in tabs:
            ds = by_ds.setdefault(
                t["datasource_id"],
                DatasourceCoverage(
                    datasource_id=t["datasource_id"],
                    name=self._names.get(t["datasource_id"]),
                ),
            )
            ds.total_tables += 1
            if t.get("grade_level") is not None:
                ds.graded_tables += 1
        summary.by_datasource = sorted(by_ds.values(), key=lambda d: d.datasource_id)
        return summary

    def sensitive_assets(
        self,
        *,
        grade_min: int,
        datasource_id: Optional[int],
        entity_type: str,
        keyword: Optional[str],
        cursor: Optional[str],
        limit: int,
    ) -> List[SensitiveAsset]:
        if entity_type == "table":
            rows = [
                SensitiveAsset(
                    id=t["id"], entity_type="table", name=t["name"], fqn=t["fqn"],
                    datasource_id=t["datasource_id"],
                    grade_level=int(t["grade_level"]),
                    grade_code=t.get("grade_code"),
                )
                for t in self._tables
                if t.get("grade_level") is not None
                and int(t["grade_level"]) >= grade_min
                and (datasource_id is None or t["datasource_id"] == datasource_id)
                and (not keyword or keyword.lower() in t["name"].lower())
            ]
        else:
            rows = [
                SensitiveAsset(
                    id=c["id"], entity_type="column", name=c["name"], fqn=c["fqn"],
                    datasource_id=c["datasource_id"],
                    grade_level=int(c["grade_level"]),
                    grade_code=c.get("grade_code"),
                    table_id=c.get("table_id"),
                    table_name=c.get("table_name"),
                    table_fqn=c.get("table_fqn"),
                    data_type=c.get("data_type"),
                    grade_reason=c.get("grade_reason"),
                    is_pii=int(c["grade_level"]) >= 3,
                    tags=list(c.get("tags") or []),
                )
                for c in self._columns
                if c.get("grade_level") is not None
                and int(c["grade_level"]) >= grade_min
                and (datasource_id is None or c["datasource_id"] == datasource_id)
                and (not keyword or keyword.lower() in c["name"].lower())
            ]
        rows.sort(key=lambda a: (a.fqn, a.id))
        if cursor:
            last_fqn, last_id = decode_cursor(cursor)
            rows = [r for r in rows if (r.fqn, r.id) > (last_fqn, last_id)]
        return rows[:limit]

    def list_tags(self) -> List[TagDef]:
        return sorted(self._tags, key=lambda t: (t.grade_level or 0, t.tag_key))

    def list_rules(self) -> List[RuleDef]:
        return sorted(self._rules, key=lambda r: (r.priority, r.tag_key))


class SqlClassificationQueryRepository:
    """PostgreSQL 实现：读 ``catalog_column`` / ``catalog_table`` 与标准、规则表。"""

    def __init__(self, session_factory: Any) -> None:
        self._sf = session_factory

    def coverage(self, *, datasource_id: Optional[int]) -> CoverageSummary:
        from sqlalchemy import func, select

        from ..storage.models_core import CatalogColumn, CatalogTable

        summary = CoverageSummary()
        with self._sf() as s:
            col_q = select(CatalogColumn.datasource_id, CatalogColumn.grade_level,
                           func.count()).where(CatalogColumn.deleted_at.is_(None))
            tab_q = select(CatalogTable.datasource_id, CatalogTable.grade_level,
                           func.count()).where(CatalogTable.deleted_at.is_(None))
            if datasource_id is not None:
                col_q = col_q.where(CatalogColumn.datasource_id == datasource_id)
                tab_q = tab_q.where(CatalogTable.datasource_id == datasource_id)
            col_rows = s.execute(col_q.group_by(
                CatalogColumn.datasource_id, CatalogColumn.grade_level)).all()
            tab_rows = s.execute(tab_q.group_by(
                CatalogTable.datasource_id, CatalogTable.grade_level)).all()

        by_ds: Dict[int, DatasourceCoverage] = {}
        dist: Dict[str, int] = {}
        for ds_id, level, n in col_rows:
            ds = by_ds.setdefault(ds_id, DatasourceCoverage(datasource_id=ds_id))
            ds.total_columns += n
            summary.total_columns += n
            if level is None:
                dist["ungraded"] = dist.get("ungraded", 0) + n
                continue
            summary.graded_columns += n
            ds.graded_columns += n
            dist[str(int(level))] = dist.get(str(int(level)), 0) + n
            if int(level) >= SENSITIVE_THRESHOLD:
                summary.sensitive_columns += n
                ds.sensitive_columns += n
        for ds_id, level, n in tab_rows:
            ds = by_ds.setdefault(ds_id, DatasourceCoverage(datasource_id=ds_id))
            ds.total_tables += n
            summary.total_tables += n
            if level is not None:
                ds.graded_tables += n
                summary.graded_tables += n

        summary.grade_distribution = dist
        names = self._datasource_names(sorted(by_ds))
        for ds_id, cov in by_ds.items():
            cov.name = names.get(ds_id)
        summary.by_datasource = [by_ds[k] for k in sorted(by_ds)]
        return summary

    def _datasource_names(self, ids: List[int]) -> Dict[int, str]:
        """一次取回数据源名称，用于分组列表展示（避免界面出现裸 ID）。"""
        if not ids:
            return {}
        from sqlalchemy import select

        from ..storage.models_core import Datasource

        with self._sf() as s:
            rows = s.execute(
                select(Datasource.id, Datasource.name).where(Datasource.id.in_(ids))
            ).all()
        return {r[0]: r[1] for r in rows}

    def sensitive_assets(
        self,
        *,
        grade_min: int,
        datasource_id: Optional[int],
        entity_type: str,
        keyword: Optional[str],
        cursor: Optional[str],
        limit: int,
    ) -> List[SensitiveAsset]:
        from sqlalchemy import select, tuple_

        from ..storage.models_core import CatalogColumn, CatalogTable

        if entity_type == "table":
            stmt = select(CatalogTable).where(
                CatalogTable.deleted_at.is_(None),
                CatalogTable.grade_level.is_not(None),
                CatalogTable.grade_level >= grade_min,
            )
            if datasource_id is not None:
                stmt = stmt.where(CatalogTable.datasource_id == datasource_id)
            if keyword:
                stmt = stmt.where(CatalogTable.name.ilike(f"%{keyword}%"))
            if cursor:
                last_fqn, last_id = decode_cursor(cursor)
                stmt = stmt.where(tuple_(CatalogTable.fqn, CatalogTable.id) > tuple_(last_fqn, last_id))
            stmt = stmt.order_by(CatalogTable.fqn, CatalogTable.id).limit(limit)
            with self._sf() as s:
                rows = s.execute(stmt).scalars().all()
            return [
                SensitiveAsset(
                    id=r.id, entity_type="table", name=r.name, fqn=r.fqn,
                    datasource_id=r.datasource_id, grade_level=int(r.grade_level),
                    grade_code=r.grade_code, tags=list(r.tags or []),
                )
                for r in rows
            ]

        # 字段级：join 所属表，让清单里能看到「哪个库的哪张表的哪个字段」
        stmt = (
            select(CatalogColumn, CatalogTable)
            .join(CatalogTable, CatalogColumn.table_id == CatalogTable.id)
            .where(
                CatalogColumn.deleted_at.is_(None),
                CatalogColumn.grade_level.is_not(None),
                CatalogColumn.grade_level >= grade_min,
            )
        )
        if datasource_id is not None:
            stmt = stmt.where(CatalogColumn.datasource_id == datasource_id)
        if keyword:
            stmt = stmt.where(CatalogColumn.name.ilike(f"%{keyword}%"))
        if cursor:
            last_fqn, last_id = decode_cursor(cursor)
            stmt = stmt.where(tuple_(CatalogColumn.fqn, CatalogColumn.id) > tuple_(last_fqn, last_id))
        stmt = stmt.order_by(CatalogColumn.fqn, CatalogColumn.id).limit(limit)

        with self._sf() as s:
            rows = s.execute(stmt).all()

        out: List[SensitiveAsset] = []
        for col, tab in rows:
            props = col.properties or {}
            out.append(
                SensitiveAsset(
                    id=col.id,
                    entity_type="column",
                    name=col.name,
                    fqn=col.fqn,
                    datasource_id=col.datasource_id,
                    grade_level=int(col.grade_level),
                    grade_code=col.grade_code,
                    table_id=col.table_id,
                    table_name=tab.name,
                    table_fqn=tab.fqn,
                    data_type=col.data_type_display or col.data_type,
                    grade_reason=props.get("grade_reason"),
                    is_pii=int(col.grade_level) >= 3,
                    tags=list(col.tags or []),
                )
            )
        return out

    def list_tags(self) -> List[TagDef]:
        from sqlalchemy import select

        from ..storage.models_governance import ClassificationTag as M

        with self._sf() as s:
            rows = s.execute(
                select(M).order_by(M.grade_level, M.tag_key)
            ).scalars().all()
        return [
            TagDef(
                id=r.id, tag_key=r.tag_key, tag_name=r.tag_name, category=r.category,
                grade_level=r.grade_level, grade_code=r.grade_code, color=r.color,
                description=r.description, enabled=bool(r.enabled),
            )
            for r in rows
        ]

    def list_rules(self) -> List[RuleDef]:
        from sqlalchemy import select

        from ..storage.models_governance import ClassificationRule as M

        with self._sf() as s:
            rows = s.execute(
                select(M).order_by(M.priority, M.tag_key, M.id)
            ).scalars().all()
        return [
            RuleDef(
                id=r.id, tag_key=r.tag_key, rule_kind=r.rule_kind, pattern=r.pattern,
                confidence=float(r.confidence or 0), priority=int(r.priority or 100),
                enabled=bool(r.enabled),
            )
            for r in rows
        ]


class ClassificationQueryService:
    """面向界面的分类分级查询。"""

    def __init__(self, repo: ClassificationQueryRepository) -> None:
        self._repo = repo

    def coverage(self, *, datasource_id: Optional[int] = None) -> CoverageSummary:
        return self._repo.coverage(datasource_id=datasource_id)

    def sensitive_assets(
        self,
        *,
        grade_min: int = SENSITIVE_THRESHOLD,
        datasource_id: Optional[int] = None,
        entity_type: str = "column",
        keyword: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> KeysetPage[SensitiveAsset]:
        rows = self._repo.sensitive_assets(
            grade_min=grade_min,
            datasource_id=datasource_id,
            entity_type=entity_type,
            keyword=keyword,
            cursor=cursor,
            limit=limit + 1,
        )
        return KeysetPage.build(rows, limit, cursor_builder=encode_cursor)

    def tags(self) -> List[TagDef]:
        return self._repo.list_tags()

    def rules(self) -> List[RuleDef]:
        return self._repo.list_rules()
