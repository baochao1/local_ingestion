"""Unit tests for the global search service (MOD-09 / T-211).

Uses the in-memory repository + injected catalog records; verifies scoring,
filtering and pagination without a database.
"""
from __future__ import annotations

from local_ingestion.platform.search import (
    CatalogRecord,
    InMemoryCatalogRepository,
    SearchQuery,
    SearchService,
)

RECORDS = [
    CatalogRecord(
        fqn="ds1.sales.orders", name="orders", entity_type="table", datasource_id=1,
        schema="sales", description="customer orders", tags=["pii", "core"],
        owner="alice", is_pii=True,
    ),
    CatalogRecord(
        fqn="ds1.sales.order_items", name="order_items", entity_type="table",
        datasource_id=1, schema="sales", description="line items", tags=["core"],
    ),
    CatalogRecord(
        fqn="ds1.sales.orders.customer_id", name="customer_id", entity_type="column",
        datasource_id=1, parent_fqn="ds1.sales.orders", tags=["pii"], is_pii=True,
    ),
    CatalogRecord(
        fqn="ds2.hr.employees", name="employees", entity_type="table", datasource_id=2,
        schema="hr", description="staff", tags=["pii"], is_pii=True,
    ),
]


def _svc():
    return SearchService(InMemoryCatalogRepository(RECORDS))


def test_name_match_ranks_highest():
    res = _svc().search(SearchQuery(term="orders"))
    assert res.total >= 1
    top = res.items[0]
    assert top.name == "orders" and top.score >= 10


def test_prefix_beats_substring():
    res = _svc().search(SearchQuery(term="order"))
    names = [i.name for i in res.items]
    assert "orders" in names and "order_items" in names
    # exact/prefix 'order' should rank order_items (startswith) well
    assert res.items[0].name in ("orders", "order_items")


def test_filter_by_datasource():
    res = _svc().search(SearchQuery(term="", datasource_id=2))
    assert res.total == 1
    assert res.items[0].datasource_id == 2


def test_filter_by_tag():
    res = _svc().search(SearchQuery(term="", tags=["pii"]))
    # orders(table), orders.customer_id(column), employees(table) carry pii
    assert all(i.is_pii for i in res.items)
    assert res.total == 3


def test_sensitive_only():
    res = _svc().search(SearchQuery(term="", sensitive_only=True))
    assert all(i.is_pii for i in res.items)


def test_filter_by_type_column():
    res = _svc().search(SearchQuery(term="customer", type="column"))
    assert res.total == 1
    assert res.items[0].entity_type == "column"


def test_owner_filter():
    res = _svc().search(SearchQuery(term="", owner="alice"))
    assert res.total == 1
    assert res.items[0].owner == "alice"


def test_pagination_limit_offset():
    res = _svc().search(SearchQuery(term="", limit=2, offset=0))
    assert len(res.items) == 2
    assert res.total == 4
    page2 = _svc().search(SearchQuery(term="", limit=2, offset=2))
    assert len(page2.items) == 2
    # pages are disjoint
    assert {i.fqn for i in res.items} & {i.fqn for i in page2.items} == set()


def test_multi_token_or_match():
    res = _svc().search(SearchQuery(term="orders customer"))
    # at least the orders table should match on 'orders'
    assert any(i.name == "orders" for i in res.items)
