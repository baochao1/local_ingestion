"""资产层级浏览服务（MOD-09）。

为什么需要这个模块
------------------
``catalog_database`` / ``catalog_schema`` / ``catalog_table`` / ``catalog_column``
四层表结构与外键完整，扫描器也真的采集了库与 schema，但 MOD-09 §182-183 规定的
浏览接口（``GET /api/v1/catalog/tables``、``/catalog/columns``）**从未实现**：
HTTP 层只有 ``/api/v1/search``（限 1000 条的模糊匹配）。

结果是资产目录退化成「一条搜索框」——**用户必须先知道表名才能找到表**，
而「让用户发现自己有什么数据」恰恰是这个产品的核心价值。

本模块补齐四个只读浏览接口，让四层资产模型可以被逐层下钻：

    GET /api/v1/catalog/databases
    GET /api/v1/catalog/schemas?datasourceId&databaseId
    GET /api/v1/catalog/tables?datasourceId&schemaId&tableType&keyword
    GET /api/v1/catalog/columns?datasourceId&tableId&keyword

分页一律走 keyset（:class:`~local_ingestion.platform.api.pagination.KeysetPage`），
排序键固定为 ``(fqn, id)`` —— 这是 ``catalog_*`` 各表唯一都具备的稳定排序键，
与 ``idx_cattab_keyset`` / ``idx_catcol_keyset`` 等索引前缀一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol

from ..api.pagination import KeysetPage, encode_cursor


@dataclass
class CatalogNode:
    """层级浏览的统一节点。四层资产共用，按 ``entity_type`` 区分。"""

    id: int
    name: str
    fqn: str
    entity_type: str  # database | schema | table | column
    datasource_id: int

    # 层级归属
    parent_id: Optional[int] = None
    parent_fqn: Optional[str] = None

    # 通用治理属性
    owner: Optional[str] = None
    description: Optional[str] = None
    grade_level: Optional[int] = None
    grade_code: Optional[str] = None

    # table 专有
    table_type: Optional[str] = None
    column_count: Optional[int] = None

    # column 专有
    data_type: Optional[str] = None
    nullable: Optional[bool] = None
    ordinal_position: Optional[int] = None

    updated_at: Optional[str] = None
    tags: List[str] = field(default_factory=list)


class CatalogBrowseRepository(Protocol):
    """层级浏览的数据访问边界。"""

    def list_databases(
        self, *, datasource_id: Optional[int], cursor: Optional[str], limit: int
    ) -> List[CatalogNode]: ...

    def list_schemas(
        self,
        *,
        datasource_id: Optional[int],
        database_id: Optional[int],
        cursor: Optional[str],
        limit: int,
    ) -> List[CatalogNode]: ...

    def list_tables(
        self,
        *,
        datasource_id: Optional[int],
        schema_id: Optional[int],
        table_type: Optional[str],
        keyword: Optional[str],
        cursor: Optional[str],
        limit: int,
    ) -> List[CatalogNode]: ...

    def list_columns(
        self,
        *,
        datasource_id: Optional[int],
        table_id: Optional[int],
        keyword: Optional[str],
        cursor: Optional[str],
        limit: int,
    ) -> List[CatalogNode]: ...


def _keyset_filter(nodes: List[CatalogNode], cursor: Optional[str]) -> List[CatalogNode]:
    """内存实现的 keyset 过滤：保留 ``(fqn, id)`` 严格大于游标的节点。

    与 SQL 实现的行值比较语义保持一致（``(fqn, id) > (:fqn, :id)``）。
    """
    if not cursor:
        return nodes
    from ..api.pagination import decode_cursor

    last_fqn, last_id = decode_cursor(cursor)
    return [n for n in nodes if (n.fqn, n.id) > (last_fqn, last_id)]


class InMemoryCatalogBrowseRepository:
    """内存实现：单元测试与单实例 MVP 用，语义与 SQL 实现一致。"""

    def __init__(self, nodes: Optional[List[CatalogNode]] = None) -> None:
        self._nodes = list(nodes or [])

    def _sorted(self, nodes: List[CatalogNode]) -> List[CatalogNode]:
        return sorted(nodes, key=lambda n: (n.fqn, n.id))

    def list_databases(
        self, *, datasource_id: Optional[int], cursor: Optional[str], limit: int
    ) -> List[CatalogNode]:
        rows = [
            n
            for n in self._nodes
            if n.entity_type == "database"
            and (datasource_id is None or n.datasource_id == datasource_id)
        ]
        return self._sorted(_keyset_filter(rows, cursor))[:limit]

    def list_schemas(
        self,
        *,
        datasource_id: Optional[int],
        database_id: Optional[int],
        cursor: Optional[str],
        limit: int,
    ) -> List[CatalogNode]:
        rows = [
            n
            for n in self._nodes
            if n.entity_type == "schema"
            and (datasource_id is None or n.datasource_id == datasource_id)
            and (database_id is None or n.parent_id == database_id)
        ]
        return self._sorted(_keyset_filter(rows, cursor))[:limit]

    def list_tables(
        self,
        *,
        datasource_id: Optional[int],
        schema_id: Optional[int],
        table_type: Optional[str],
        keyword: Optional[str],
        cursor: Optional[str],
        limit: int,
    ) -> List[CatalogNode]:
        rows = [
            n
            for n in self._nodes
            if n.entity_type == "table"
            and (datasource_id is None or n.datasource_id == datasource_id)
            and (schema_id is None or n.parent_id == schema_id)
            and (table_type is None or (n.table_type or "").upper() == table_type.upper())
            and (keyword is None or keyword.lower() in n.name.lower())
        ]
        return self._sorted(_keyset_filter(rows, cursor))[:limit]

    def list_columns(
        self,
        *,
        datasource_id: Optional[int],
        table_id: Optional[int],
        keyword: Optional[str],
        cursor: Optional[str],
        limit: int,
    ) -> List[CatalogNode]:
        rows = [
            n
            for n in self._nodes
            if n.entity_type == "column"
            and (datasource_id is None or n.datasource_id == datasource_id)
            and (table_id is None or n.parent_id == table_id)
            and (keyword is None or keyword.lower() in n.name.lower())
        ]
        return self._sorted(_keyset_filter(rows, cursor))[:limit]


class SqlCatalogBrowseRepository:
    """PostgreSQL 实现：查询 ``catalog_*`` 四张表。

    排序键一律 ``(fqn, id)``，与 ``uq_cat*_fqn`` / ``idx_cat*_keyset`` 索引前缀一致，
    避免 keyset 退化为全表排序（见 ``api/pagination.py`` 的告警）。
    """

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    # -- 内部工具 ---------------------------------------------------------

    @staticmethod
    def _apply_keyset(stmt: Any, model: Any, cursor: Optional[str]) -> Any:
        """附加 ``(fqn, id) > (:fqn, :id)`` 并固定排序。"""
        from ..api.pagination import decode_cursor

        if cursor:
            last_fqn, last_id = decode_cursor(cursor)
            stmt = stmt.where(
                tuple_(model.fqn, model.id) > tuple_(last_fqn, last_id)
            )
        return stmt.order_by(model.fqn, model.id)

    def _fetch(self, build: Any) -> List[CatalogNode]:
        """在一个 session 内构造并执行查询，返回节点列表。"""
        with self._session_factory() as session:
            stmt = build(session)
            rows = session.execute(stmt).scalars().all()
            return [self._to_node(r) for r in rows]

    @staticmethod
    def _to_node(row: Any) -> CatalogNode:
        """把 ORM 行转成统一节点；按实体类型补齐父子信息。"""
        kind = {
            "catalog_database": "database",
            "catalog_schema": "schema",
            "catalog_table": "table",
            "catalog_column": "column",
        }[row.__tablename__]

        node = CatalogNode(
            id=row.id,
            name=row.name,
            fqn=row.fqn,
            entity_type=kind,
            datasource_id=row.datasource_id,
            owner=getattr(row, "owner", None),
            description=getattr(row, "description", None),
            grade_level=getattr(row, "grade_level", None),
            grade_code=getattr(row, "grade_code", None),
            updated_at=(
                row.updated_at.isoformat() if getattr(row, "updated_at", None) else None
            ),
        )

        if kind == "schema":
            node.parent_id = row.database_id
        elif kind == "table":
            node.parent_id = row.schema_id
            node.table_type = row.table_type
            node.column_count = row.column_count
        elif kind == "column":
            node.parent_id = row.table_id
            node.data_type = row.data_type_display or row.data_type
            node.nullable = row.nullable
            node.ordinal_position = row.ordinal_position

        tags = getattr(row, "tags", None)
        if isinstance(tags, list):
            node.tags = [str(t) for t in tags]
        return node

    # -- 四层查询 ---------------------------------------------------------

    def list_databases(
        self, *, datasource_id: Optional[int], cursor: Optional[str], limit: int
    ) -> List[CatalogNode]:
        from ..storage.models_core import CatalogDatabase as M

        def build(_session: Any) -> Any:
            stmt = _select(M)
            if datasource_id is not None:
                stmt = stmt.where(M.datasource_id == datasource_id)
            return self._apply_keyset(stmt, M, cursor).limit(limit)

        return self._fetch(build)

    def list_schemas(
        self,
        *,
        datasource_id: Optional[int],
        database_id: Optional[int],
        cursor: Optional[str],
        limit: int,
    ) -> List[CatalogNode]:
        from ..storage.models_core import CatalogSchema as M

        def build(_session: Any) -> Any:
            stmt = _select(M)
            if datasource_id is not None:
                stmt = stmt.where(M.datasource_id == datasource_id)
            if database_id is not None:
                stmt = stmt.where(M.database_id == database_id)
            return self._apply_keyset(stmt, M, cursor).limit(limit)

        return self._fetch(build)

    def list_tables(
        self,
        *,
        datasource_id: Optional[int],
        schema_id: Optional[int],
        table_type: Optional[str],
        keyword: Optional[str],
        cursor: Optional[str],
        limit: int,
    ) -> List[CatalogNode]:
        from ..storage.models_core import CatalogTable as M

        def build(_session: Any) -> Any:
            stmt = _select(M)
            if datasource_id is not None:
                stmt = stmt.where(M.datasource_id == datasource_id)
            if schema_id is not None:
                stmt = stmt.where(M.schema_id == schema_id)
            if table_type:
                stmt = stmt.where(func_upper(M.table_type) == table_type.upper())
            if keyword:
                stmt = stmt.where(M.name.ilike(f"%{keyword}%"))
            return self._apply_keyset(stmt, M, cursor).limit(limit)

        return self._fetch(build)

    def list_columns(
        self,
        *,
        datasource_id: Optional[int],
        table_id: Optional[int],
        keyword: Optional[str],
        cursor: Optional[str],
        limit: int,
    ) -> List[CatalogNode]:
        from ..storage.models_core import CatalogColumn as M

        def build(_session: Any) -> Any:
            stmt = _select(M)
            if datasource_id is not None:
                stmt = stmt.where(M.datasource_id == datasource_id)
            if table_id is not None:
                stmt = stmt.where(M.table_id == table_id)
            if keyword:
                stmt = stmt.where(M.name.ilike(f"%{keyword}%"))
            return self._apply_keyset(stmt, M, cursor).limit(limit)

        return self._fetch(build)


def _select(model: Any) -> Any:
    """``select(model).where(软删除过滤)`` —— 四层表都带 ``deleted_at``。"""
    from sqlalchemy import select

    return select(model).where(model.deleted_at.is_(None))


def func_upper(column: Any) -> Any:
    """``upper(column)``，用于大小写不敏感的类型比较（``VIEW`` / ``view`` 都可）。"""
    from sqlalchemy import func

    return func.upper(column)


class CatalogBrowseService:
    """层级浏览服务：把 repository 的结果包成 keyset 分页响应。

    ``limit`` 一律按「多取一行」约定处理（``LIMIT limit + 1``），
    由 :meth:`KeysetPage.build` 探测 ``has_more`` 并生成游标。
    """

    def __init__(self, repo: CatalogBrowseRepository) -> None:
        self._repo = repo

    def _page(
        self, rows: List[CatalogNode], limit: int
    ) -> KeysetPage[CatalogNode]:
        return KeysetPage.build(
            rows,
            limit,
            cursor_builder=encode_cursor,
        )

    def databases(
        self, *, datasource_id: Optional[int] = None, cursor: Optional[str] = None, limit: int = 50
    ) -> KeysetPage[CatalogNode]:
        rows = self._repo.list_databases(
            datasource_id=datasource_id, cursor=cursor, limit=limit + 1
        )
        return self._page(rows, limit)

    def schemas(
        self,
        *,
        datasource_id: Optional[int] = None,
        database_id: Optional[int] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> KeysetPage[CatalogNode]:
        rows = self._repo.list_schemas(
            datasource_id=datasource_id,
            database_id=database_id,
            cursor=cursor,
            limit=limit + 1,
        )
        return self._page(rows, limit)

    def tables(
        self,
        *,
        datasource_id: Optional[int] = None,
        schema_id: Optional[int] = None,
        table_type: Optional[str] = None,
        keyword: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> KeysetPage[CatalogNode]:
        rows = self._repo.list_tables(
            datasource_id=datasource_id,
            schema_id=schema_id,
            table_type=table_type,
            keyword=keyword,
            cursor=cursor,
            limit=limit + 1,
        )
        return self._page(rows, limit)

    def columns(
        self,
        *,
        datasource_id: Optional[int] = None,
        table_id: Optional[int] = None,
        keyword: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> KeysetPage[CatalogNode]:
        rows = self._repo.list_columns(
            datasource_id=datasource_id,
            table_id=table_id,
            keyword=keyword,
            cursor=cursor,
            limit=limit + 1,
        )
        return self._page(rows, limit)
