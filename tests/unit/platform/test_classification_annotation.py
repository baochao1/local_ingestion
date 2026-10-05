"""人工标注服务的单元测试（MOD-05 / FR-9.5）。

用轻量 fake session——这里关心的是*写了什么*：``entity_tag`` 的 source 必须是
``manual``（引擎据此跳过），``catalog_column`` 的 grade 必须同步回写（否则检索
筛选与变更影响判定看不到人工结论）。
"""
from __future__ import annotations

import pytest

from local_ingestion.platform.classification.annotation import (
    APPROVAL_REQUIRED_GRADE,
    MANUAL_TAG_KEY,
    AnnotationError,
    AnnotationService,
    EntityNotFound,
    PendingAnnotation,
    apply_approved_annotation,
)


class _Row:
    """catalog_column / catalog_table 的最小替身。"""

    def __init__(self, row_id, name, fqn="ds.public.t.name", grade_level=3, deleted_at=None):
        self.id = row_id
        self.name = name
        self.fqn = fqn
        self.grade_level = grade_level
        self.grade_code = "PII"
        self.deleted_at = deleted_at


class _Session:
    def __init__(self, rows=None, existing_tag=None):
        self._rows = rows or {}
        self._existing_tag = existing_tag
        self.added = []
        self.deleted = None
        self.committed = False

    def get(self, model, row_id):
        return self._rows.get(row_id)

    def query(self, model):
        return self

    def filter(self, *args, **kwargs):
        return self

    def one_or_none(self):
        return self._existing_tag

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted = obj

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _svc(session):
    return AnnotationService(lambda: session)


# ------------------------------------------------------------------ 写标注


def test_annotate_rewrites_catalog_row_so_downstream_sees_it():
    """只写 entity_tag 是不够的：检索的 gradeMin 筛选读的是 catalog 行。"""
    col = _Row(10, "name")
    session = _Session({10: col})

    ann = _svc(session).annotate(
        entity_type="column", entity_id=10, grade_level=1, actor="alice"
    )

    assert col.grade_level == 1
    assert col.grade_code == "INTERNAL"
    assert ann.grade_level == 1
    assert ann.grade_code == "INTERNAL"
    assert ann.applied_by == "alice"
    assert session.committed is True


def test_annotate_creates_manual_entity_tag():
    """source 必须是 manual——引擎正是按这个值决定「不得覆盖」。"""
    session = _Session({10: _Row(10, "name")})

    _svc(session).annotate(entity_type="column", entity_id=10, grade_level=4)

    assert len(session.added) == 1
    tag = session.added[0]
    assert tag.source == "manual"
    assert tag.tag_key == MANUAL_TAG_KEY
    assert tag.grade_level == 4
    assert tag.confidence == 1.0
    assert tag.entity_type == "column"
    assert tag.entity_fqn == "ds.public.t.name"


def test_annotate_reuses_existing_manual_tag():
    """重复修正同一条目不应产生第二条记录（唯一索引会拒绝）。"""
    existing = type("T", (), {"source": "rule", "grade_level": 3, "confidence": None,
                              "applied_by": None, "entity_fqn": None})()
    session = _Session({10: _Row(10, "name")}, existing_tag=existing)

    _svc(session).annotate(entity_type="column", entity_id=10, grade_level=5, actor="bob")

    assert session.added == []
    assert existing.grade_level == 5
    assert existing.source == "manual"
    assert existing.applied_by == "bob"


def test_annotate_table_is_supported():
    session = _Session({7: _Row(7, "orders")})
    ann = _svc(session).annotate(entity_type="table", entity_id=7, grade_level=2)
    assert ann.entity_type == "table"
    assert ann.grade_code == "SENSITIVE"


# ------------------------------------------------------------------ 入参校验


def test_rejects_unsupported_entity_type():
    with pytest.raises(AnnotationError, match="不支持"):
        _svc(_Session()).annotate(entity_type="database", entity_id=1, grade_level=1)


@pytest.mark.parametrize("level", [0, 10, -1])
def test_rejects_out_of_range_level(level):
    with pytest.raises(AnnotationError, match="1–9"):
        _svc(_Session({1: _Row(1, "c")})).annotate(
            entity_type="column", entity_id=1, grade_level=level
        )


def test_missing_entity_raises_not_found():
    with pytest.raises(EntityNotFound):
        _svc(_Session()).annotate(entity_type="column", entity_id=999, grade_level=1)


def test_soft_deleted_entity_is_not_annotatable():
    session = _Session({10: _Row(10, "name", deleted_at="2026-01-01")})
    with pytest.raises(EntityNotFound):
        _svc(session).annotate(entity_type="column", entity_id=10, grade_level=1)


# ------------------------------------------------------------------ 撤销


def test_clear_deletes_manual_tag():
    existing = object()
    session = _Session({10: _Row(10, "name")}, existing_tag=existing)

    _svc(session).clear(entity_type="column", entity_id=10)

    assert session.deleted is existing
    assert session.committed is True


def test_clear_is_noop_when_no_manual_tag():
    session = _Session({10: _Row(10, "name")})
    _svc(session).clear(entity_type="column", entity_id=10)
    assert session.deleted is None
    assert session.committed is False


def test_clear_rejects_unsupported_type():
    with pytest.raises(AnnotationError):
        _svc(_Session()).clear(entity_type="database", entity_id=1)


# ------------------------------------------------------- 高敏修正的审批接线


def test_high_grade_annotation_requires_approval():
    """L4/L5 的人工提升走审批；L1–L3 直接生效。

    一刀切全审批会让队列被日常降级淹没，最终沦为批量点「通过」。
    """
    assert APPROVAL_REQUIRED_GRADE == 4


def test_pending_payload_roundtrip():
    pending = PendingAnnotation(
        entity_type="column", entity_id=5759, grade_level=5, applied_by="alice"
    )
    restored = PendingAnnotation.from_reason(pending.to_reason())
    assert restored == pending


def test_pending_payload_ignores_foreign_reason():
    """审批表是共用的，别把别人的 reason 当成自己的载荷。"""
    assert PendingAnnotation.from_reason("这是一句普通的申请理由") is None
    assert PendingAnnotation.from_reason(None) is None
    assert PendingAnnotation.from_reason("{ not json") is None
    assert PendingAnnotation.from_reason('{"kind":"other.module"}') is None


def test_pending_payload_rejects_malformed_body():
    assert PendingAnnotation.from_reason('{"kind":"classification.annotate"}') is None
    assert (
        PendingAnnotation.from_reason(
            '{"kind":"classification.annotate","entity_type":"column"}'
        )
        is None
    )


def test_apply_approved_annotation_writes_grade():
    col = _Row(5759, "name")
    session = _Session({5759: col})
    pending = PendingAnnotation(entity_type="column", entity_id=5759, grade_level=5)

    applied = apply_approved_annotation(pending.to_reason(), lambda: session)

    assert applied is True
    assert col.grade_level == 5
    assert col.grade_code == "CONFIDENTIAL"


def test_apply_approved_annotation_skips_foreign_approval():
    col = _Row(10, "name")
    session = _Session({10: col})

    applied = apply_approved_annotation("普通审批理由", lambda: session)

    assert applied is False
    assert col.grade_level == 3  # 未被改动
    assert session.committed is False
