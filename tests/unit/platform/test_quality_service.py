"""FR-M5: rule compilation.

Compilation is pure, so the important guarantees are testable without a
database: each rule becomes one read-only SELECT, and the read-only promise is
enforced at compile time rather than trusted.
"""
from __future__ import annotations

import pytest

from local_ingestion.platform.quality.service import (
    SUPPORTED_RULE_TYPES,
    CaseResult,
    compile_rule,
)

RELATION = '"sales"."orders"'


def test_not_null_counts_null_rows():
    sql = compile_rule("not_null", {"column": "email"}, RELATION)
    assert sql.startswith("SELECT")
    assert 'WHERE "email" IS NULL' in sql


def test_unique_counts_duplicate_groups():
    sql = compile_rule("unique", {"column": "code"}, RELATION)
    assert "GROUP BY" in sql and "HAVING COUNT(*) > 1" in sql


def test_range_compiles_bounds():
    sql = compile_rule("range", {"column": "amount", "min": 0, "max": 100}, RELATION)
    assert '"amount" < 0.0' in sql and '"amount" > 100.0' in sql


def test_range_accepts_a_single_bound():
    sql = compile_rule("range", {"column": "amount", "min": 1}, RELATION)
    assert "< 1.0" in sql and ">" not in sql.split("WHERE")[1]


def test_pattern_compiles_regex():
    sql = compile_rule(
        "pattern", {"column": "phone", "pattern": "^1[3-9]\\d{9}$"}, RELATION
    )
    assert "~ '^1[3-9]\\d{9}$'" in sql


def test_pattern_can_be_inverted():
    sql = compile_rule(
        "pattern", {"column": "phone", "pattern": "x", "must_match": False}, RELATION
    )
    assert "NOT (" in sql


def test_row_count_compiles_bounds():
    sql = compile_rule("row_count", {"min": 10, "max": 1000}, RELATION)
    assert "_n < 10" in sql and "_n > 1000" in sql


def test_custom_sql_is_accepted_when_read_only():
    sql = compile_rule("custom_sql", {"sql": "SELECT COUNT(*) FROM t"}, RELATION)
    assert sql == "SELECT COUNT(*) FROM t"


def test_custom_sql_rejects_writes():
    """The read-only guarantee must be enforced, not assumed (PC2)."""
    for bad in ("DELETE FROM t", "UPDATE t SET x=1", "INSERT INTO t VALUES (1)"):
        with pytest.raises(ValueError, match="SELECT"):
            compile_rule("custom_sql", {"sql": bad}, RELATION)


def test_unsupported_rule_type_is_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        compile_rule("referential_integrity", {}, RELATION)


@pytest.mark.parametrize(
    "rule_type,definition",
    [
        ("not_null", {}),
        ("unique", {}),
        ("range", {"column": "a"}),
        ("pattern", {"column": "a"}),
        ("row_count", {}),
        ("custom_sql", {}),
    ],
)
def test_missing_definition_fields_are_rejected(rule_type, definition):
    with pytest.raises(ValueError):
        compile_rule(rule_type, definition, RELATION)


def test_identifiers_are_quoted():
    sql = compile_rule("not_null", {"column": 'we"ird'}, RELATION)
    assert '"we""ird"' in sql


def test_all_supported_types_compile():
    """Every advertised type must actually be compilable."""
    for rule_type in SUPPORTED_RULE_TYPES:
        definition = {"column": "c", "pattern": "p", "sql": "SELECT 1", "min": 0}
        assert compile_rule(rule_type, definition, RELATION).startswith("SELECT")


def test_case_result_serialises():
    result = CaseResult(rule_code="r1", passed=False, metric_value=3.0)
    payload = result.as_dict()
    assert payload["passed"] is False
    assert payload["metric_value"] == 3.0
    assert payload["rule_code"] == "r1"
