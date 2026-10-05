"""分类分级查询的单元测试（MOD-05 界面侧）。

用内存 repository 验证覆盖率统计、敏感资产清单、分级标准与识别规则，
不依赖数据库。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from local_ingestion.platform.api.routers.classification import get_query_service
from local_ingestion.platform.classification.queries import (
    SENSITIVE_THRESHOLD,
    ClassificationQueryService,
    InMemoryClassificationQueryRepository,
    RuleDef,
    TagDef,
)

COLUMNS = [
    # ds1: 2 个已分级（1 敏感），2 个未分级
    {"id": 1, "name": "user_name", "fqn": "ds1.public.users.user_name", "datasource_id": 1,
     "grade_level": 3, "grade_code": "PII", "table_id": 10, "table_name": "users",
     "table_fqn": "ds1.public.users", "data_type": "text", "grade_reason": "personal",
     "tags": ["PII"]},
    {"id": 2, "name": "salary", "fqn": "ds1.public.users.salary", "datasource_id": 1,
     "grade_level": 5, "grade_code": "CONFIDENTIAL", "table_id": 10, "table_name": "users",
     "table_fqn": "ds1.public.users", "data_type": "numeric", "grade_reason": "credential",
     "tags": ["PII", "HIGH"]},
    {"id": 3, "name": "id", "fqn": "ds1.public.users.id", "datasource_id": 1,
     "grade_level": None, "table_id": 10, "table_name": "users"},
    {"id": 4, "name": "note", "fqn": "ds1.public.users.note", "datasource_id": 1,
     "grade_level": None, "table_id": 10, "table_name": "users"},
    # ds2: 1 个已分级（非敏感）
    {"id": 5, "name": "qty", "fqn": "ds2.public.orders.qty", "datasource_id": 2,
     "grade_level": 1, "grade_code": "INTERNAL", "table_id": 20, "table_name": "orders",
     "table_fqn": "ds2.public.orders"},
]

TABLES = [
    {"id": 10, "name": "users", "fqn": "ds1.public.users", "datasource_id": 1,
     "grade_level": 5, "grade_code": "CONFIDENTIAL"},
    {"id": 20, "name": "orders", "fqn": "ds2.public.orders", "datasource_id": 2,
     "grade_level": 1, "grade_code": "INTERNAL"},
    {"id": 30, "name": "raw_staging", "fqn": "ds1.public.raw_staging", "datasource_id": 1,
     "grade_level": None},
]

TAGS = [
    TagDef(id=1, tag_key="L1_PUBLIC", tag_name="公开", category="SECURITY", grade_level=1, grade_code="L1"),
    TagDef(id=2, tag_key="PII_PHONE", tag_name="手机号", category="PII", grade_level=3, grade_code="L3"),
    TagDef(id=3, tag_key="L2_INTERNAL", tag_name="内部", category="SECURITY", grade_level=2, grade_code="L2"),
]

RULES = [
    RuleDef(id=1, tag_key="PII_PHONE", rule_kind="regex", pattern=r"^1[3-9]\d{9}$",
            confidence=0.9, priority=50),
    RuleDef(id=2, tag_key="PII_EMAIL", rule_kind="column_name", pattern="email",
            confidence=0.7, priority=100),
]


def _svc() -> ClassificationQueryService:
    return ClassificationQueryService(
        InMemoryClassificationQueryRepository(
            columns=COLUMNS, tables=TABLES, tags=TAGS, rules=RULES,
            datasource_names={1: "pg_local", 2: "mysql_ods"},
        )
    )


# ------------------------------------------------------------------ 覆盖率


def test_coverage_counts_total_and_graded():
    cov = _svc().coverage()
    assert cov.total_columns == 5
    assert cov.graded_columns == 3
    assert cov.total_tables == 3
    assert cov.graded_tables == 2


def test_coverage_ratio_is_derived_not_stored():
    cov = _svc().coverage()
    assert cov.coverage_ratio == pytest.approx(3 / 5)


def test_ungraded_columns_are_not_counted_as_level_1():
    """未分级必须单列，不能混进 L1——否则「覆盖率」永远显示 100%。"""
    cov = _svc().coverage()
    assert cov.grade_distribution.get("ungraded") == 2
    assert cov.grade_distribution.get("1") == 1


def test_sensitive_count_uses_threshold():
    cov = _svc().coverage()
    # 级别 >= 2 才算敏感：L3 + L5 两个
    assert cov.sensitive_columns == 2
    assert SENSITIVE_THRESHOLD == 2


def test_coverage_grouped_by_datasource_with_names():
    cov = _svc().coverage()
    by_id = {d.datasource_id: d for d in cov.by_datasource}
    assert by_id[1].name == "pg_local"
    assert by_id[1].total_columns == 4
    assert by_id[1].graded_columns == 2
    assert by_id[1].sensitive_columns == 2
    assert by_id[2].sensitive_columns == 0


def test_coverage_filtered_by_datasource():
    cov = _svc().coverage(datasource_id=2)
    assert cov.total_columns == 1
    assert cov.graded_columns == 1
    assert [d.datasource_id for d in cov.by_datasource] == [2]


# -------------------------------------------------------------- 敏感资产清单


def test_sensitive_assets_defaults_to_columns_above_threshold():
    page = _svc().sensitive_assets()
    assert {a.name for a in page.items} == {"user_name", "salary"}


def test_sensitive_assets_carries_parent_table_and_reason():
    """清单必须能回答「哪个库的哪张表的哪个字段、为什么被判敏感」。"""
    page = _svc().sensitive_assets()
    salary = next(a for a in page.items if a.name == "salary")
    assert salary.table_name == "users"
    assert salary.table_fqn == "ds1.public.users"
    assert salary.grade_reason == "credential"
    assert salary.is_pii is True


def test_sensitive_assets_grade_min_filters():
    page = _svc().sensitive_assets(grade_min=5)
    assert [a.name for a in page.items] == ["salary"]


def test_sensitive_assets_grade_min_1_high_grade_includes_internal():
    page = _svc().sensitive_assets(grade_min=1)
    assert "qty" in {a.name for a in page.items}


def test_sensitive_assets_entity_type_table():
    page = _svc().sensitive_assets(entity_type="table", grade_min=2)
    assert [a.name for a in page.items] == ["users"]


def test_sensitive_assets_keyword():
    page = _svc().sensitive_assets(keyword="sal")
    assert [a.name for a in page.items] == ["salary"]


def test_sensitive_assets_paginates():
    svc = _svc()
    first = svc.sensitive_assets(limit=1)
    assert [a.name for a in first.items] == ["salary"]  # 按 fqn 排序
    assert first.has_more is True
    second = svc.sensitive_assets(limit=1, cursor=first.next_cursor)
    assert [a.name for a in second.items] == ["user_name"]
    assert second.has_more is False


def test_ungraded_columns_never_appear_in_sensitive_list():
    page = _svc().sensitive_assets(grade_min=1)
    assert "note" not in {a.name for a in page.items}


# ------------------------------------------------------------ 标准与规则


def test_tags_sorted_by_grade():
    tags = _svc().tags()
    assert [t.grade_level for t in tags] == [1, 2, 3]


def test_rules_sorted_by_priority():
    rules = _svc().rules()
    assert [r.priority for r in rules] == [50, 100]


# ------------------------------------------------------------------ HTTP 层


@pytest.fixture()
def client() -> TestClient:
    from local_ingestion.api.app import app

    app.dependency_overrides[get_query_service] = _svc
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_ladder_exposes_all_five_levels(client: TestClient):
    """级别定义由后端单点提供，前端不再自己硬编码一套。"""
    body = client.get("/api/v1/classification/ladder").json()
    assert body["threshold"] == 2
    assert [lv["level"] for lv in body["levels"]] == [1, 2, 3, 4, 5]
    assert body["levels"][2]["code"] == "PII"


def test_api_coverage_serializes_camel_case(client: TestClient):
    body = client.get("/api/v1/classification/coverage").json()
    assert body["coverageRatio"] == pytest.approx(0.6)
    assert "byDatasource" in body
    assert body["byDatasource"][0]["coverageRatio"] == pytest.approx(0.5)
    assert "coverage_ratio" not in body


def test_api_sensitive_assets_envelope(client: TestClient):
    body = client.get("/api/v1/classification/sensitive-assets").json()
    assert set(body) == {"items", "nextCursor", "hasMore", "approxTotal"}
    assert "tableName" in body["items"][0]


def test_api_rejects_unknown_entity_type(client: TestClient):
    res = client.get(
        "/api/v1/classification/sensitive-assets", params={"entityType": "schema"}
    )
    assert res.status_code == 400
    assert "column" in res.json()["detail"]


def test_api_tags_and_rules(client: TestClient):
    assert client.get("/api/v1/classification/tags").json()["total"] == 3
    assert client.get("/api/v1/classification/rules").json()["total"] == 2
