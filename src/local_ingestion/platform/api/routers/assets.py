"""Asset detail endpoint (MOD-09 / T-212).

:class:`AssetDetailService` + :class:`SqlCatalogProvider` were implemented (real
bulk fetch of a table with its columns, tags, owner, grade and PII flags) but
were only reachable from tests. This mounts the detail card over the catalog.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status

from ...api.serialization import camelize
from ...asset.service import AssetDetailService

router = APIRouter(prefix="/api/v1/assets", tags=["Assets"])


def get_asset_service() -> AssetDetailService:
    """Production wiring: the catalog slice is real, the rest degrade to None."""
    from ...asset.providers import SqlCatalogProvider
    from ...storage.session import session_scope

    return AssetDetailService(providers=[SqlCatalogProvider(session_scope)])


@router.get("/{fqn}")
async def asset_detail(
    fqn: str,
    svc: AssetDetailService = Depends(get_asset_service),
) -> Dict[str, Any]:
    """Detail card for one asset (table fqn)."""
    detail = await svc.aggregate(fqn)
    if detail.entity_type is None and not detail.columns:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"资产不存在：{fqn}"
        )
    return camelize(asdict(detail))
