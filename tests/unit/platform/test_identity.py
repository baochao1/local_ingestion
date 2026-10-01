"""Unit tests for platform/identity.py (FR-13 entity identity resolution).

These are pure-logic tests with no database dependency: ``existing_*`` inputs are
duck-typed fakes exposing the catalog attributes the resolver reads.
"""
from __future__ import annotations

from local_ingestion.platform.identity import (
    detect_orphans,
    resolve_columns,
    resolve_tables,
)


class FakeTable:
    def __init__(self, id, fqn, name, struct_hash=None, columns_json=None):
        self.id = id
        self.fqn = fqn
        self.name = name
        self.struct_hash = struct_hash
        self.columns_json = columns_json or []


class FakeColumn:
    def __init__(self, id, fqn, name, ordinal_position, data_type, nullable=True):
        self.id = id
        self.fqn = fqn
        self.name = name
        self.ordinal_position = ordinal_position
        self.data_type = data_type
        self.nullable = nullable


def _current_table(fqn, name, struct_hash, col_names):
    return {
        "fqn": fqn,
        "name": name,
        "struct_hash": struct_hash,
        "col_names": col_names,
    }


def test_resolve_tables_matched_by_fqn():
    existing = [FakeTable(1, "db.sch.orders", "orders", "H", [{"name": "a"}])]
    current = [_current_table("db.sch.orders", "orders", "H", ["a"])]
    res = resolve_tables(7, current, existing)
    assert len(res) == 1
    assert res[0].action == "matched"
    assert res[0].entity_id == 1
    assert res[0].confidence == 1.0


def test_resolve_tables_renamed_high_confidence():
    existing = [FakeTable(1, "db.sch.orders", "orders", "H", [{"name": "a"}, {"name": "b"}])]
    # same struct_hash (identical columns) + very similar name -> auto-adopted
    current = [_current_table("db.sch.orders2", "orders2", "H", ["a", "b"])]
    res = resolve_tables(7, current, existing)
    assert res[0].action == "renamed"
    assert res[0].entity_id == 1
    assert res[0].old_fqn == "db.sch.orders"
    assert res[0].alias_fqn == "db.sch.orders"
    assert res[0].pending is False  # high confidence -> auto-adopt


def test_resolve_tables_renamed_low_confidence_pending():
    # One column added (no removal) -> Jaccard 5/6 = 0.833, struct_hash mismatch
    # -> meets the rename minima but is NOT high-confidence (structure not identical)
    existing = [FakeTable(
        1, "db.sch.orders", "orders", "OLD",
        [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}, {"name": "e"}],
    )]
    current = [_current_table(
        "db.sch.orders2", "orders2", "NEW",
        ["a", "b", "c", "d", "e", "f"],  # one column added, all existing retained
    )]
    res = resolve_tables(7, current, existing)
    assert res[0].action == "renamed"
    assert res[0].pending is True  # medium confidence -> needs confirmation
    assert 0.8 <= res[0].confidence < 1.0


def test_resolve_tables_new_entity():
    existing = [FakeTable(1, "db.sch.orders", "orders", "H", [{"name": "a"}])]
    current = [_current_table("db.sch.customers", "customers", "X", ["id"])]
    res = resolve_tables(7, current, existing)
    assert res[0].action == "new"
    assert res[0].entity_id is None


def test_resolve_tables_only_considers_same_schema():
    # identical name/structure but different schema must NOT be a rename
    existing = [FakeTable(1, "db.sch_a.orders", "orders", "H", [{"name": "a"}])]
    current = [_current_table("db.sch_b.orders", "orders", "H", ["a"])]
    res = resolve_tables(7, current, existing)
    assert res[0].action == "new"


def test_resolve_columns_renamed():
    existing = [FakeColumn(10, "db.sch.t.user_id", "user_id", 0, "INTEGER")]
    current = [{
        "fqn": "db.sch.t.user_idd",
        "name": "user_idd",
        "ordinal_position": 0,
        "data_type": "INTEGER",
        "nullable": True,
    }]
    res = resolve_columns(7, current, existing, "db.sch.t", "db.sch.t")
    assert res[0].action == "renamed"
    assert res[0].entity_id == 10
    assert res[0].old_fqn == "db.sch.t.user_id"
    assert res[0].alias_fqn == "db.sch.t.user_id"
    assert res[0].fqn == "db.sch.t.user_idd"
    assert res[0].pending is False


def test_resolve_columns_matched_by_name():
    existing = [FakeColumn(10, "db.sch.t.user_id", "user_id", 0, "INTEGER")]
    current = [{
        "fqn": "db.sch.t.user_id",
        "name": "user_id",
        "ordinal_position": 0,
        "data_type": "INTEGER",
        "nullable": True,
    }]
    res = resolve_columns(7, current, existing, "db.sch.t", "db.sch.t")
    assert res[0].action == "matched"
    assert res[0].entity_id == 10
    assert res[0].alias_fqn is None


def test_resolve_columns_new():
    existing = [FakeColumn(10, "db.sch.t.user_id", "user_id", 0, "INTEGER")]
    current = [{
        "fqn": "db.sch.t.created_at",
        "name": "created_at",
        "ordinal_position": 1,
        "data_type": "TIMESTAMP",
        "nullable": True,
    }]
    res = resolve_columns(7, current, existing, "db.sch.t", "db.sch.t")
    assert res[0].action == "new"
    assert res[0].entity_id is None


def test_detect_orphans():
    t1 = FakeTable(1, "db.sch.a", "a", "H")
    t2 = FakeTable(2, "db.sch.b", "b", "H")
    orphans = detect_orphans([t1, t2], {"db.sch.a"})
    assert orphans == [t2]
