"""资产层级浏览接口（MOD-09 §182-183）。

MOD-09 规定的 ``GET /api/v1/catalog/tables`` 与 ``/catalog/columns`` 此前
**从未实现**，HTTP 层只有 ``/api/v1/search``（限 1000 条的模糊匹配）——
资产目录因此退化为「一条搜索框」，用户必须先知道表名才能找到表。

本 router 补齐四层只读浏览接口（库 → schema → 表 → 字段），
分页走 keyset（``{items, nextCursor, hasMore, approxTotal}``），
与前端 ``DataTable`` 的 fetcher 契约一致。

服务通过 :func:`get_browse_service` 注入，测试可用
``app.dependency_overrides`` 换成内存实现，无需数据库。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...api.pagination import InvalidCursorError, clamp_limit
from ...catalog.browse import CatalogBrowseService

router = APIRouter(prefix="/api/v1/catalog", tags=["Catalog"])


def get_browse_service() -> CatalogBrowseService:
    """生产接线：``SqlCatalogBrowseRepository`` 走平台库。"""
    from ...catalog.browse import SqlCatalogBrowseRepository
    from ...storage.session import session_scope

    return CatalogBrowseService(SqlCatalogBrowseRepository(session_scope))


def _page(fn: Any) -> Dict[str, Any]:
    """统一处理游标错误 → 400（游标对客户端不透明，解不开就是非法输入）。"""
    try:
        return fn().to_dict()
    except InvalidCursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="游标无效或已过期，请重新发起查询"
        ) from exc


@router.get("/databases")
def list_databases(
    datasourceId: Optional[int] = Query(None, description="按数据源过滤"),
    cursor: Optional[str] = Query(None, description="keyset 游标，原样回传上一页的 nextCursor"),
    limit: Optional[int] = Query(None, description="每页条数，默认 50，上限 200"),
    svc: CatalogBrowseService = Depends(get_browse_service),
) -> Dict[str, Any]:
    """库列表（层级浏览第一层）。"""
    return _page(
        lambda: svc.databases(
            datasource_id=datasourceId, cursor=cursor, limit=clamp_limit(limit)
        )
    )


@router.get("/schemas")
def list_schemas(
    datasourceId: Optional[int] = None,
    databaseId: Optional[int] = Query(None, description="按所属库过滤"),
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
    svc: CatalogBrowseService = Depends(get_browse_service),
) -> Dict[str, Any]:
    """Schema 列表（层级浏览第二层）。"""
    return _page(
        lambda: svc.schemas(
            datasource_id=datasourceId,
            database_id=databaseId,
            cursor=cursor,
            limit=clamp_limit(limit),
        )
    )


@router.get("/tables")
def list_tables(
    datasourceId: Optional[int] = None,
    schemaId: Optional[int] = Query(None, description="按所属 schema 过滤"),
    tableType: Optional[str] = Query(
        None, description="TABLE | VIEW | MATERIALIZED_VIEW | EXTERNAL（大小写不敏感）"
    ),
    keyword: Optional[str] = Query(None, description="表名模糊匹配"),
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
    svc: CatalogBrowseService = Depends(get_browse_service),
) -> Dict[str, Any]:
    """表/视图列表（层级浏览第三层）。"""
    return _page(
        lambda: svc.tables(
            datasource_id=datasourceId,
            schema_id=schemaId,
            table_type=tableType,
            keyword=keyword,
            cursor=cursor,
            limit=clamp_limit(limit),
        )
    )


@router.get("/columns")
def list_columns(
    datasourceId: Optional[int] = None,
    tableId: Optional[int] = Query(None, description="按所属表过滤"),
    keyword: Optional[str] = Query(None, description="字段名模糊匹配"),
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
    svc: CatalogBrowseService = Depends(get_browse_service),
) -> Dict[str, Any]:
    """字段列表（层级浏览第四层）。"""
    return _page(
        lambda: svc.columns(
            datasource_id=datasourceId,
            table_id=tableId,
            keyword=keyword,
            cursor=cursor,
            limit=clamp_limit(limit, default=100),
        )
    )
