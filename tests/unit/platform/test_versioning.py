"""Unit tests for the schema diff engine + impact grading (MOD-06 / T-201, T-202).

Pure-logic: builds normalized CatalogStates directly and asserts the diff +
grading output. Rename detection exercises the shared identity resolver (FR-13.4).
"""
from __future__ import annotations

from local_ingestion.platform.versioning import (
    CatalogState,
    ColumnSpec,
    ImpactClassifier,
    SchemaDiffer,
    TableSpec,
)


def _col(name, dtype="varchar", nullable=True, comment=None, pii=False, importance=0):
    return ColumnSpec(name=name, data_type=dtype, nullable=nullable, comment=comment, is_pii=pii, importance=importance)


def _tbl(fqn, *cols, **kw):
    return TableSpec(fqn=fqn, name=fqn.split(".")[-1], columns=list(cols), **kw)


def _state(*tables):
    return CatalogState(tables=list(tables))


def test_no_change_when_identical():
    base = _state(_tbl("db.schema.users", _col("id"), _col("name")))
    cur = _state(_tbl("db.schema.users", _col("id"), _col("name")))
    diff = SchemaDiffer().diff(base, cur, datasource_id=1)
    assert diff.is_empty


def test_table_added_and_removed():
    base = _state(_tbl("db.s.a", _col("id")))
    cur = _state(_tbl("db.s.b", _col("id")))
    diff = SchemaDiffer().diff(base, cur, datasource_id=1)
    assert diff.tables_added == ["db.s.b"]
    assert diff.tables_removed == ["db.s.a"]
    assert any(c.change_type == "table_added" for c in diff.table_changes)
    assert any(c.change_type == "table_removed" for c in diff.table_changes)


def test_column_added_and_removed():
    base = _state(_tbl("db.s.t", _col("id"), _col("old")))
    cur = _state(_tbl("db.s.t", _col("id"), _col("new")))
    diff = SchemaDiffer().diff(base, cur, datasource_id=1)
    assert diff.tables_changed == ["db.s.t"]
    types = {c.change_type for c in diff.column_changes}
    assert "column_added" in types and "column_removed" in types
    removed = [c for c in diff.column_changes if c.change_type == "column_removed"][0]
    assert removed.column == "old"


def test_type_and_nullable_and_comment_change():
    base = _state(_tbl("db.s.t", _col("id", "int", nullable=False, comment="pk")))
    cur = _state(_tbl("db.s.t", _col("id", "bigint", nullable=True, comment="primary key")))
    diff = SchemaDiffer().diff(base, cur, datasource_id=1)
    types = {c.change_type for c in diff.column_changes}
    assert "type_changed" in types
    assert "nullable_changed" in types
    assert "comment_changed" in types


def test_table_rename_detected_via_structural_similarity():
    # Same columns, only the table name changed -> rename, not drop+create.
    base = _state(_tbl("db.s.orders", _col("id"), _col("amt", "numeric")))
    cur = _state(_tbl("db.s.orders_v2", _col("id"), _col("amt", "numeric")))
    diff = SchemaDiffer().diff(base, cur, datasource_id=1)
    assert diff.tables_renamed == [("db.s.orders_v2", "db.s.orders")]
    assert "db.s.orders" not in diff.tables_removed
    assert "db.s.orders_v2" not in diff.tables_added


def test_column_rename_detected():
    base = _state(_tbl("db.s.t", _col("user_id", "int"), _col("name")))
    cur = _state(_tbl("db.s.t", _col("uid", "int"), _col("name")))
    diff = SchemaDiffer().diff(base, cur, datasource_id=1)
    renamed = [c for c in diff.column_changes if c.change_type == "column_renamed"]
    assert renamed, diff.column_changes
    assert renamed[0].column == "uid"
    assert renamed[0].old_column == "user_id"


def test_impact_grading_levels():
    base = _state(
        _tbl("db.s.t", _col("plain", pii=False), _col("ssn", pii=True))
    )
    cur = _state(
        _tbl("db.s.t", _col("plain", pii=False), _col("ssn", pii=True), _col("email", pii=True))
    )
    # Also drop the sensitive column by rebuilding base/cur differently:
    base2 = _state(_tbl("db.s.t", _col("plain", pii=False), _col("ssn", pii=True)))
    cur2 = _state(_tbl("db.s.t", _col("plain", pii=False)))
    diff = SchemaDiffer().diff(base2, cur2, datasource_id=1)
    graded = ImpactClassifier().classify(diff)
    levels = {g.column: g.level for g in graded if g.column}
    assert levels.get("ssn") == "P0"  # sensitive column drop


def test_sensitive_column_type_change_is_p0():
    base = _state(_tbl("db.s.t", _col("ssn", "varchar", pii=True)))
    cur = _state(_tbl("db.s.t", _col("ssn", "text", pii=True)))
    diff = SchemaDiffer().diff(base, cur, datasource_id=1)
    graded = ImpactClassifier().classify(diff)
    ssn = [g for g in graded if g.column == "ssn"][0]
    assert ssn.change_type == "type_changed"
    assert ssn.level == "P0"


def test_importance_boosts_level():
    base = _state(_tbl("db.s.t", _col("c", pii=False, importance=9)))
    cur = _state(_tbl("db.s.t", _col("c", "int", pii=False, importance=9)))
    diff = SchemaDiffer().diff(base, cur, datasource_id=1)
    graded = ImpactClassifier().classify(diff)
    c = [g for g in graded if g.column == "c"][0]
    assert c.level == "P0"  # P2 type change promoted by importance>=7


def test_comment_change_is_p3_only():
    base = _state(_tbl("db.s.t", _col("c", comment="old")))
    cur = _state(_tbl("db.s.t", _col("c", comment="new")))
    diff = SchemaDiffer().diff(base, cur, datasource_id=1)
    graded = ImpactClassifier().classify(diff)
    assert len(graded) == 1
    assert graded[0].level == "P3"
