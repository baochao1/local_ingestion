"""Asset detail providers (MOD-09 / T-212).

Each provider contributes one slice of the asset card. Providers run concurrently
(see ``AssetDetailService``); a provider that returns ``None`` or raises is
treated as a degraded (unavailable) source so the aggregate call never fails.

* ``InMemoryCatalogProvider`` / ``SqlCatalogProvider`` — the real catalog slice.
* ``PlaceholderProvider`` — stands in for modules not yet implemented
  (business metadata, quality, lineage, grants, recent changes); returns ``None``
  so the source is reported as degraded rather than erroring.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from .models import ColumnBrief, SOURCE_CATALOG


class AssetDetailProvider(Protocol):
    source: str

    async def provide(self, fqn: str) -> Optional[Dict[str, Any]]: ...


class InMemoryCatalogProvider:
    source = SOURCE_CATALOG

    def __init__(self, tables: Dict[str, Dict[str, Any]]) -> None:
        self._tables = tables

    async def provide(self, fqn: str) -> Optional[Dict[str, Any]]:
        t = self._tables.get(fqn)
        if not t:
            return None
        cols = [ColumnBrief(**c) for c in t.get("columns", [])]
        out = {k: v for k, v in t.items() if k != "columns"}
        out["columns"] = cols
        return out


class SqlCatalogProvider:
    """Real catalog slice; fetches table + all its columns in bulk (no N+1).

    既支持表 FQN，也支持字段 FQN：前端资产详情链路统一按 FQN 取（不含数字 id），
    否则「找到一张表 → 看它的字段」这条主旅程在字段这一环会断
    （见 doc/design/ux-audit-full.md S0#1 / B1）。
    """

    source = SOURCE_CATALOG

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    async def provide(self, fqn: str) -> Optional[Dict[str, Any]]:
        from ..storage.models_core import CatalogColumn, CatalogTable

        with self._sf() as s:
            t = (
                s.query(CatalogTable)
                .filter(CatalogTable.fqn == fqn, CatalogTable.deleted_at.is_(None))
                .first()
            )
            if not t:
                return self._column_slice(s, fqn)
            cols = (
                s.query(CatalogColumn)
                .filter(CatalogColumn.table_id == t.id, CatalogColumn.deleted_at.is_(None))
                .all()
            )
            return {
                "entity_type": "table",
                "name": t.name,
                "schema": t.fqn.rsplit(".", 1)[0] if "." in t.fqn else None,
                "description": t.description,
                "tags": list(t.tags or []),
                "owner": t.owner,
                "is_pii": "PII" in (t.tags or []),
                "importance": t.grade_level or 0,
                "datasource_id": t.datasource_id,
                "grade_level": t.grade_level,
                "columns": [
                    ColumnBrief(
                        name=c.name, data_type=c.data_type or "", nullable=bool(c.nullable),
                        comment=c.description, is_pii="PII" in (c.tags or []),
                        importance=c.grade_level or 0,
                    )
                    for c in cols
                ],
            }

    def _column_slice(self, s, fqn: str) -> Optional[Dict[str, Any]]:
        """按字段 FQN 取一条列（连带父表，供前端展示「所属表」）。"""
        from ..storage.models_core import CatalogColumn, CatalogTable

        row = (
            s.query(CatalogColumn, CatalogTable)
            .join(CatalogTable, CatalogTable.id == CatalogColumn.table_id)
            .filter(
                CatalogColumn.fqn == fqn,
                CatalogColumn.deleted_at.is_(None),
                CatalogTable.deleted_at.is_(None),
            )
            .first()
        )
        if not row:
            return None
        c, parent = row
        return {
            "entity_type": "column",
            "name": c.name,
            "schema": parent.fqn.rsplit(".", 1)[0] if "." in parent.fqn else None,
            "description": c.description,
            "tags": list(c.tags or []),
            "owner": parent.owner,
            "is_pii": "PII" in (c.tags or []),
            "importance": c.grade_level or 0,
            "datasource_id": c.datasource_id,
            "grade_level": c.grade_level,
            "parent_fqn": parent.fqn,
            "data_type": c.data_type,
            "nullable": bool(c.nullable),
            "columns": [],
        }


class PlaceholderProvider:
    """Stand-in for a not-yet-implemented module slice."""

    def __init__(self, source: str) -> None:
        self.source = source

    async def provide(self, fqn: str) -> Optional[Dict[str, Any]]:
        return None
