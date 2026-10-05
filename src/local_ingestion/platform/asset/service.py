"""Asset detail aggregation service (MOD-09 / T-212).

Runs every registered provider concurrently (``asyncio.gather``) so the detail
card is assembled in one parallel fan-out instead of a serial N+1 walk. A source
that errors or returns ``None`` is recorded in ``degraded_sources`` and the
overall aggregation still succeeds (graceful degradation, per MOD-09 design).
"""
from __future__ import annotations

import asyncio
from typing import List

from .models import AssetDetail, SOURCE_CATALOG
from .providers import AssetDetailProvider


class AssetDetailService:
    def __init__(
        self,
        providers: List[AssetDetailProvider],
        catalog_source: str = SOURCE_CATALOG,
    ) -> None:
        self._providers = providers
        self._catalog_source = catalog_source

    async def aggregate(self, fqn: str) -> AssetDetail:
        results = await asyncio.gather(
            *(p.provide(fqn) for p in self._providers), return_exceptions=True
        )
        degraded: List[str] = []
        data: dict = {}
        for prov, res in zip(self._providers, results):
            if isinstance(res, Exception):
                degraded.append(prov.source)
            elif res is None:
                degraded.append(prov.source)
            else:
                data[prov.source] = res

        cat = data.get(self._catalog_source, {})
        return AssetDetail(
            fqn=fqn,
            entity_type=cat.get("entity_type"),
            name=cat.get("name"),
            schema=cat.get("schema"),
            description=cat.get("description"),
            tags=list(cat.get("tags", []) or []),
            owner=cat.get("owner"),
            is_pii=cat.get("is_pii", False),
            importance=cat.get("importance", 0),
            columns=cat.get("columns") or [],
            business=data.get("business"),
            quality=data.get("quality"),
            lineage=data.get("lineage"),
            grants=data.get("grants"),
            recent_changes=data.get("changes"),
            degraded_sources=degraded,
            # 字段级切片 + 归属信息（无则返回 None，前端按缺失渲染，不显示 0）
            parent_fqn=cat.get("parent_fqn"),
            data_type=cat.get("data_type"),
            nullable=cat.get("nullable"),
            datasource_id=cat.get("datasource_id"),
            grade_level=cat.get("grade_level"),
        )
