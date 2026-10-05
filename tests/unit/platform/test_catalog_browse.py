"""资产层级浏览的单元测试（MOD-09 §182-183）。

用内存 repository + 手工构造的四层节点，验证逐层过滤、keyset 分页、
类型大小写不敏感与游标错误处理，不依赖数据库。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from local_ingestion.platform.api.pagination import decode_cursor
from local_ingestion.platform.api.routers.catalog_browse import get_browse_service
from local_ingestion.platform.catalog.browse import (
    CatalogBrowseService,
    CatalogNode,
    InMemoryCatalogBrowseRepository,
)

# 两层数据源，用于验证「按数据源过滤」不会串台。
NODES = [
    CatalogNode(id=1, name="analytics", fqn="ds1.analytics", entity_type="database", datasource_id=1),
    CatalogNode(id=2, name="warehouse", fqn="ds1.warehouse", entity_type="database", datasource_id=1),
    CatalogNode(id=3, name="hr", fqn="ds2.hr", entity_type="database", datasource_id=2),
    # schemas：1、2 属 analytics，3 属 hr
    CatalogNode(id=10, name="public", fqn="ds1.analytics.public", entity_type="schema",
                datasource_id=1, parent_id=1),
    CatalogNode(id=11, name="sales", fqn="ds1.analytics.sales", entity_type="schema",
                datasource_id=1, parent_id=1),
    CatalogNode(id=12, name="staff", fqn="ds2.hr.staff", entity_type="schema",
                datasource_id=2, parent_id=3),
    # tables：10 下两张表、11 下一张
    CatalogNode(id=20, name="orders", fqn="ds1.analytics.public.orders", entity_type="table",
                datasource_id=1, parent_id=10, table_type="TABLE", column_count=4, grade_level=3),
    CatalogNode(id=21, name="order_view", fqn="ds1.analytics.public.order_view",
                entity_type="table", datasource_id=1, parent_id=10, table_type="VIEW",
                column_count=2),
    CatalogNode(id=22, name="customers", fqn="ds1.analytics.sales.customers",
                entity_type="table", datasource_id=1, parent_id=11, table_type="TABLE"),
    # columns：20 下三个字段
    CatalogNode(id=30, name="id", fqn="ds1.analytics.public.orders.id", entity_type="column",
                datasource_id=1, parent_id=20, data_type="bigint", ordinal_position=1),
    CatalogNode(id=31, name="customer_id", fqn="ds1.analytics.public.orders.customer_id",
                entity_type="column", datasource_id=1, parent_id=20, data_type="bigint",
                ordinal_position=2, grade_level=3),
    CatalogNode(id=32, name="amount", fqn="ds1.analytics.public.orders.amount",
                entity_type="column", datasource_id=1, parent_id=20, data_type="numeric",
                ordinal_position=3),
]


def _svc() -> CatalogBrowseService:
    return CatalogBrowseService(InMemoryCatalogBrowseRepository(NODES))


# --------------------------------------------------------------- 四层过滤


def test_databases_filtered_by_datasource():
    page = _svc().databases(datasource_id=1)
    assert [n.name for n in page.items] == ["analytics", "warehouse"]


def test_schemas_filtered_by_database():
    page = _svc().schemas(database_id=1)
    assert [n.name for n in page.items] == ["public", "sales"]


def test_schemas_filtered_by_datasource_spans_databases():
    page = _svc().schemas(datasource_id=1)
    assert {n.name for n in page.items} == {"public", "sales"}


def test_tables_filtered_by_schema():
    page = _svc().tables(schema_id=10)
    assert [n.name for n in page.items] == ["order_view", "orders"]


def test_tables_carry_hierarchy_metadata():
    page = _svc().tables(schema_id=10)
    orders = next(n for n in page.items if n.name == "orders")
    assert orders.parent_id == 10          # 归属 schema，供前端做面包屑
    assert orders.table_type == "TABLE"
    assert orders.column_count == 4
    assert orders.grade_level == 3


def test_columns_filtered_by_table():
    """字段数量少且需按表内位置展示，但分页顺序固定为 ``(fqn, id)`` 以保证游标稳定。

    展示顺序（``ordinalPosition``）由前端负责——一次取全后自行排序，
    避免为单表字段引入第二套游标格式。
    """
    page = _svc().columns(table_id=20)
    assert {n.name for n in page.items} == {"id", "customer_id", "amount"}
    assert sorted(n.ordinal_position for n in page.items) == [1, 2, 3]


def test_columns_carry_type_and_grade():
    page = _svc().columns(table_id=20)
    cid = next(n for n in page.items if n.name == "customer_id")
    assert cid.data_type == "bigint"
    assert cid.grade_level == 3


# --------------------------------------------------------------- 类型筛选


def test_table_type_filter_is_case_insensitive():
    """``VIEW`` / ``view`` 都要能筛出视图——大小写不该成为用户的坑。"""
    upper = _svc().tables(table_type="VIEW")
    lower = _svc().tables(table_type="view")
    assert [n.name for n in upper.items] == ["order_view"]
    assert [n.name for n in lower.items] == ["order_view"]


def test_table_type_filter_distinguishes_view_from_table():
    """视图与表必须能分开筛——这正是「视图混装进表」要解决的问题。"""
    tables = _svc().tables(table_type="TABLE")
    assert {n.name for n in tables.items} == {"orders", "customers"}


def test_keyword_filter():
    page = _svc().tables(keyword="order")
    assert {n.name for n in page.items} == {"orders", "order_view"}


# --------------------------------------------------------------- keyset 分页


def test_pagination_reports_more_and_returns_cursor():
    page = _svc().databases(limit=1)
    assert len(page.items) == 1
    assert page.has_more is True
    assert page.next_cursor is not None
    assert decode_cursor(page.next_cursor) == (page.items[-1].fqn, page.items[-1].id)


def test_pagination_second_page_continues_without_overlap():
    svc = _svc()
    first = svc.databases(limit=1)
    second = svc.databases(limit=1, cursor=first.next_cursor)
    assert [n.name for n in first.items] == ["analytics"]
    assert [n.name for n in second.items] == ["warehouse"]
    # 仍有一个库（ds2 的 hr）未取，故第二页还应报告 has_more
    assert second.has_more is True

    third = svc.databases(limit=1, cursor=second.next_cursor)
    assert [n.name for n in third.items] == ["hr"]
    assert third.has_more is False
    assert third.next_cursor is None


def test_pagination_walks_all_rows_exactly_once():
    """逐页翻到底，行数与顺序都应与全量一致，不重不漏。"""
    svc = _svc()
    seen, cursor, guard = [], None, 0
    while guard < 20:
        page = svc.tables(cursor=cursor, limit=2)
        seen.extend(n.name for n in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor
        guard += 1
    assert seen == ["order_view", "orders", "customers"]


def test_pagination_with_filter_still_paginates_that_subset():
    page = _svc().tables(schema_id=10, limit=1)
    assert [n.name for n in page.items] == ["order_view"]
    assert page.has_more is True


# --------------------------------------------------------------- HTTP 层


@pytest.fixture()
def client() -> TestClient:
    from local_ingestion.api.app import app

    app.dependency_overrides[get_browse_service] = _svc
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_databases_returns_keyset_envelope(client: TestClient):
    res = client.get("/api/v1/catalog/databases", params={"datasourceId": 1})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == {"items", "nextCursor", "hasMore", "approxTotal"}
    assert [i["name"] for i in body["items"]] == ["analytics", "warehouse"]


def test_api_serializes_camel_case(client: TestClient):
    res = client.get("/api/v1/catalog/tables", params={"schemaId": 10})
    item = res.json()["items"][0]
    assert "tableType" in item and "datasourceId" in item
    assert "table_type" not in item


def test_api_rejects_invalid_cursor(client: TestClient):
    res = client.get("/api/v1/catalog/tables", params={"cursor": "not-base64!!"})
    assert res.status_code == 400
    assert "游标" in res.json()["detail"]


def test_api_clamps_limit(client: TestClient):
    """limit 超过上限时收敛而不是报错（clamp_limit 契约）。"""
    res = client.get("/api/v1/catalog/databases", params={"limit": 99999})
    assert res.status_code == 200
    assert len(res.json()["items"]) == 3
