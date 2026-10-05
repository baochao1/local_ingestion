"""MOD-05 grading: rules and service (main-flow segment A).

The rules are pure functions, so the important behaviour — including the classic
``product_name`` false positive — is pinned without a database. The service tests
use a fake session because what matters is *what gets written*: grade_level,
``PII``/``HIGH`` tags and ``properties`` (the last two are what change-impact
grading actually reads).
"""
from __future__ import annotations

from local_ingestion.platform.classification import (
    ClassificationService,
    GRADE_CODES,
    classify_column,
)


# -- rules ---------------------------------------------------------------


def test_credentials_are_top_grade():
    assert classify_column("password").grade_level == 5
    assert classify_column("api_key").grade_level == 5
    assert classify_column("pwd", None, "登录口令").grade_level == 5


def test_strong_identifiers_are_high_pii():
    v = classify_column("id_card_no")
    assert (v.grade_level, v.is_pii, v.high_sensitivity) == (4, True, True)
    assert classify_column("passport_no").grade_level == 4
    assert classify_column("bankcard").grade_level == 4


def test_personal_data_is_pii_but_not_high():
    for name in ("email", "phone", "mobile", "address", "birthday"):
        v = classify_column(name)
        assert v.grade_level == 3, name
        assert v.is_pii and not v.high_sensitivity, name
    assert classify_column("customer_name").grade_level == 3


def test_product_name_is_not_pii():
    """``product_name`` / ``file_name`` are the classic false positive."""
    assert classify_column("product_name").grade_level == 1
    assert classify_column("file_name").grade_level == 1
    assert classify_column("table_name").grade_level == 1
    # ...but a bare or person-qualified name is.
    assert classify_column("name").grade_level == 3
    assert classify_column("user_name").grade_level == 3


def test_business_sensitive_is_grade_two():
    assert classify_column("amount").grade_level == 2
    assert classify_column("order_amount").grade_level == 2
    assert classify_column("total", "money").grade_level == 2


def test_plain_columns_stay_at_one():
    """The threshold is 2, so ordinary columns must not inflate the ratio."""
    for name in ("id", "created_at", "status", "customer_id", "sku", "qty"):
        assert classify_column(name).grade_level == 1, name


def test_chinese_names_and_comments():
    assert classify_column("c", None, "身份证号").grade_level == 4
    assert classify_column("c", None, "客户姓名").grade_level == 3
    assert classify_column("c", None, "订单金额").grade_level == 2


def test_verdict_tags():
    assert classify_column("email").tags == ("PII",)
    assert classify_column("id_card").tags == ("PII", "HIGH")
    assert classify_column("amount").tags == ()


def test_every_grade_has_a_code():
    for level, code in GRADE_CODES.items():
        assert 1 <= level <= 9


# -- service -------------------------------------------------------------


class _Col:
    def __init__(self, col_id, table_id, name, data_type=None, description=None,
                 grade_level=None, tags=None, properties=None):
        self.id = col_id
        self.table_id = table_id
        self.name = name
        self.data_type = data_type
        self.description = description
        self.grade_level = grade_level
        self.tags = list(tags or [])
        self.properties = dict(properties or {})


class _Table:
    def __init__(self, table_id, name, grade_level=None):
        self.id = table_id
        self.name = name
        self.grade_level = grade_level
        self.grade_code = None


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, tables, cols, manual_ids=()):
        self._tables = tables
        self._cols = cols
        #: 已人工标注的实体 ID（FR-9.5），测试由此注入
        self._manual_ids = list(manual_ids)
        self.committed = False

    def query(self, model):
        # 引擎会按「列」查询人工标注（``EntityTag.entity_id``），此时模型名在
        # ``.class_`` 上而不是 ``__name__``。两种形态都要认。
        owner = getattr(model, "class_", None)
        name = getattr(model, "__name__", None) or getattr(owner, "__name__", "")
        if name == "EntityTag":
            # ``_manual_ids`` 只取第一列，故返回行元组序列
            return _Query([(i,) for i in self._manual_ids])
        return _Query(self._tables if name == "CatalogTable" else self._cols)

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _service(tables, cols, manual_ids=()):
    session = _Session(tables, cols, manual_ids)
    return ClassificationService(lambda: session), session


def test_service_writes_grade_tags_and_properties():
    table = _Table(1, "customers")
    email = _Col(10, 1, "email")
    sku = _Col(11, 1, "sku")
    svc, session = _service([table], [email, sku])

    result = svc.classify_datasource(1)

    assert result.columns_graded == 2
    assert result.pii_columns == 1
    assert result.sensitive_columns == 1
    assert session.committed is True

    assert email.grade_level == 3
    assert email.grade_code == "PII"
    assert "PII" in email.tags
    assert email.properties["pii"] is True
    assert email.properties["high_sensitivity"] is False

    assert sku.grade_level == 1
    assert "PII" not in sku.tags

    # Table inherits the most severe column.
    assert table.grade_level == 3
    assert table.grade_code == "PII"


def test_service_preserves_manual_grading_by_default():
    table = _Table(1, "customers", grade_level=5)
    col = _Col(10, 1, "email", grade_level=5, tags=["PII"], properties={"pii": True})
    svc, _ = _service([table], [col])

    result = svc.classify_datasource(1)

    assert result.columns_graded == 0
    assert result.skipped == 2  # table + column both untouched
    assert col.grade_level == 5


def test_service_can_rederive_when_asked():
    table = _Table(1, "customers", grade_level=5)
    col = _Col(10, 1, "email", grade_level=5, tags=["PII"], properties={"pii": True})
    svc, _ = _service([table], [col])

    svc.classify_datasource(1, only_ungraded=False)

    assert col.grade_level == 3
    assert table.grade_level == 3


def test_service_clears_stale_pii_marks():
    table = _Table(1, "products")
    col = _Col(10, 1, "sku", tags=["PII"], properties={"pii": True})
    svc, _ = _service([table], [col])

    svc.classify_datasource(1)

    assert col.grade_level == 1
    assert "PII" not in col.tags
    assert col.properties["pii"] is False


def test_service_keeps_foreign_tags():
    table = _Table(1, "customers")
    col = _Col(10, 1, "email", tags=["manual-review"])
    svc, _ = _service([table], [col])

    svc.classify_datasource(1)

    assert "manual-review" in col.tags
    assert "PII" in col.tags


def test_service_never_overwrites_manual_annotation_even_on_full_recompute():
    """FR-9.5：人工标注过的字段，**全量重跑也不得覆盖**。

    没有这条，用户改正的误判会在下一次 ``only_ungraded=False`` 重跑时被改回去，
    复核工作台就白做了。
    """
    table = _Table(1, "customers")
    col = _Col(10, 1, "name", grade_level=1, tags=["PII"])  # 人工判定为「内部」
    svc, _ = _service([table], [col], manual_ids=[10])

    result = svc.classify_datasource(1, only_ungraded=False)

    assert result.manual_preserved == 1
    assert col.grade_level == 1  # 未被引擎改回 3
    assert col.properties == {}  # 引擎没有写回 PII 标记


def test_service_counts_manual_preservation_separately_from_skip():
    """跳过原因要能区分：人工保留 vs 已分级跳过（前者是治理动作，后者只是幂等）。"""
    table = _Table(1, "customers")
    col = _Col(10, 1, "email", grade_level=3)
    svc, _ = _service([table], [col])

    result = svc.classify_datasource(1)

    assert result.manual_preserved == 0
    assert result.skipped >= 1
