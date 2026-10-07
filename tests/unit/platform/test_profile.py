"""``05-1`` stage 1: pure profiling algorithms (no database).

These cover the decisions that are expensive to get wrong in production:
sampling rate per table size, histogram bin count on heavy-tailed columns,
per-dialect quantile spelling, and the identifier contract that stands between
catalog data and string-interpolated SQL.
"""
from __future__ import annotations

import math

import pytest

from local_ingestion.platform.dialect import MySQLDialect, PostgresDialect
from local_ingestion.platform.profile import (
    DEFAULT_PROFILE_CONFIG,
    METHOD_APPROX,
    METHOD_EXACT,
    METHOD_WINDOW,
    ColumnSelectorSpec,
    ProfileConfig,
    SampleTier,
    UnsafeRelationError,
    bin_edges,
    bin_labels,
    bin_width,
    decide_sample_rate,
    is_safe_relation,
    quantile_expr,
    resolve_bin_count,
    resolve_selector,
    sample_from_clause,
    select_columns,
    window_quantile_sql,
)

# --------------------------------------------------------------------------
# sampling: rate decision (FR-M1.1)
# --------------------------------------------------------------------------


def test_default_tiers_are_ascending():
    rows = [t.max_rows for t in DEFAULT_PROFILE_CONFIG.sample_tiers]
    assert rows == sorted(rows)
    rates = [t.rate for t in DEFAULT_PROFILE_CONFIG.sample_tiers]
    assert rates == sorted(rates, reverse=True)


@pytest.mark.parametrize(
    ("row_count", "expected"),
    [
        (0, 1.0),
        (1, 1.0),
        (100_000, 1.0),  # tier boundary is inclusive
        (100_001, 0.5),
        (1_000_000, 0.5),
        (1_000_001, 0.1),
        (10_000_000, 0.1),
        (10_000_001, 0.05),
        (100_000_000, 0.05),
        (100_000_001, 0.01),
        (1_000_000_000, 0.01),
        (1_000_000_001, DEFAULT_PROFILE_CONFIG.fallback_rate),
        (50_000_000_000, DEFAULT_PROFILE_CONFIG.fallback_rate),
    ],
)
def test_decide_sample_rate_tiers(row_count, expected):
    assert decide_sample_rate(row_count, DEFAULT_PROFILE_CONFIG) == expected


def test_unknown_row_count_gets_fallback_rate():
    # An unknown-size table is the one we must never scan in full.
    assert (
        decide_sample_rate(None, DEFAULT_PROFILE_CONFIG)
        == DEFAULT_PROFILE_CONFIG.fallback_rate
    )


def test_custom_tiers_are_honoured():
    config = ProfileConfig(sample_tiers=(SampleTier(max_rows=10, rate=0.25),))
    assert decide_sample_rate(5, config) == 0.25
    assert decide_sample_rate(11, config) == config.fallback_rate


# --------------------------------------------------------------------------
# sampling: FROM clause (D2 / D3 / D13)
# --------------------------------------------------------------------------


def test_full_rate_returns_bare_relation():
    # D3: no pointless subquery when we are reading everything anyway.
    assert (
        sample_from_clause(PostgresDialect(), "public.orders", 1.0) == "public.orders"
    )


def test_sampled_rate_wraps_dialect_sample_sql():
    clause = sample_from_clause(PostgresDialect(), "public.orders", 0.1)
    assert clause.startswith("(SELECT * FROM public.orders TABLESAMPLE")
    assert clause.endswith(") AS _profile_sample")


def test_mysql_sample_uses_rand_filter():
    clause = sample_from_clause(MySQLDialect(), "orders", 0.5)
    assert "RAND()" in clause


def test_unsafe_relation_is_rejected():
    for bad in ("orders; DROP TABLE x", "public.orders --", "", "a b", "o" * 600):
        assert not is_safe_relation(bad)
        with pytest.raises(UnsafeRelationError):
            sample_from_clause(PostgresDialect(), bad, 0.5)


def test_quoted_relation_is_accepted():
    assert is_safe_relation('"My Schema"."Order Table"')


# --------------------------------------------------------------------------
# histogram (FR-M1.6, edge E3 / E5)
# --------------------------------------------------------------------------


def test_bin_width_zero_iqr_returns_one():
    # Otherwise the FD rule yields a zero-width bin and an infinite count.
    assert bin_width(0.0, 1000) == 1.0


def test_bin_width_matches_freedman_diaconis():
    assert bin_width(2.0, 1000) == pytest.approx(2.0 * 2.0 * 1000 ** (-1.0 / 3.0))


def test_constant_column_gets_single_bin():
    # E3: a column whose values are all identical has no distribution to show.
    bins, width = resolve_bin_count(
        minimum=5.0, maximum=5.0, iqr=0.0, row_count=1000, config=DEFAULT_PROFILE_CONFIG
    )
    assert bins == 1
    assert width == 0.0


def test_zero_rows_gets_single_bin():
    bins, _ = resolve_bin_count(
        minimum=0.0, maximum=10.0, iqr=1.0, row_count=0, config=DEFAULT_PROFILE_CONFIG
    )
    assert bins == 1


def test_heavy_tail_falls_back_to_sturges():
    # E5: tiny IQR -> tiny FD width -> absurd bin count -> Sturges rescues it.
    config = DEFAULT_PROFILE_CONFIG
    bins, width = resolve_bin_count(
        minimum=0.0, maximum=1_000_000.0, iqr=0.001, row_count=1_000_000, config=config
    )
    assert bins <= config.max_bins
    assert width > 0
    assert bins == int(math.ceil(math.log2(1_000_000) + 1))


def test_bin_count_is_clamped_to_max_bins():
    config = ProfileConfig(max_bins=7)
    bins, _ = resolve_bin_count(
        minimum=0.0, maximum=1000.0, iqr=0.0001, row_count=10_000_000, config=config
    )
    assert bins == 7


def test_missing_iqr_uses_sturges():
    bins, width = resolve_bin_count(
        minimum=0.0,
        maximum=100.0,
        iqr=None,
        row_count=1024,
        config=DEFAULT_PROFILE_CONFIG,
    )
    assert bins == int(math.ceil(math.log2(1024) + 1)) == 11
    assert width == pytest.approx(100.0 / 11)


def test_bin_edges_span_min_to_max_inclusive():
    edges = bin_edges(
        minimum=0.0,
        maximum=100.0,
        iqr=10.0,
        row_count=1000,
        config=DEFAULT_PROFILE_CONFIG,
    )
    assert edges[0] == 0.0
    # Pinned so floating-point drift cannot drop the maximum itself.
    assert edges[-1] == 100.0
    assert edges == sorted(edges)


def test_bin_edges_single_bin_when_constant():
    edges = bin_edges(
        minimum=7.0, maximum=7.0, iqr=0.0, row_count=10, config=DEFAULT_PROFILE_CONFIG
    )
    assert edges == [7.0, 7.0]


def test_bin_labels_last_bin_is_inclusive():
    labels = bin_labels([0.0, 10.0, 20.0])
    assert labels == ["0 to 10", "10 and up"]


def test_bin_labels_empty_when_no_bins():
    assert bin_labels([]) == []
    assert bin_labels([1.0]) == []


# --------------------------------------------------------------------------
# quantiles (FR-M1.5, AC-1.6)
# --------------------------------------------------------------------------


def test_postgres_uses_percentile_cont():
    expr = quantile_expr("postgres", "amount", 0.5)
    assert expr.method == METHOD_EXACT
    assert "percentile_cont(0.5) WITHIN GROUP (ORDER BY amount)" in expr.expression


def test_snowflake_uses_approx_percentile():
    expr = quantile_expr("snowflake", "amount", 0.25)
    assert expr.method == METHOD_APPROX
    assert "APPROX_PERCENTILE(amount, 0.25)" == expr.expression


def test_mysql_falls_back_to_window_method():
    expr = quantile_expr("mysql", "amount", 0.5)
    assert expr.method == METHOD_WINDOW
    assert expr.expression == ""


@pytest.mark.parametrize("q", [0.0, 1.0, -0.1, 1.5])
def test_quantile_fraction_must_be_in_range(q):
    with pytest.raises(ValueError):
        quantile_expr("postgres", "amount", q)


def test_quantile_literal_never_uses_scientific_notation():
    # `5e-01` is not valid SQL.
    expr = quantile_expr("postgres", "amount", 0.000001)
    assert "e-" not in expr.expression.lower()


def test_window_quantile_sql_ranks_non_null_values():
    sql = window_quantile_sql("public.orders", "amount", 100, 0.5)
    assert "ROW_NUMBER() OVER (ORDER BY amount)" in sql
    assert "WHERE amount IS NOT NULL" in sql
    assert "_rn = 50" in sql


def test_window_quantile_requires_positive_row_count():
    with pytest.raises(ValueError):
        window_quantile_sql("t", "c", 0, 0.5)


# --------------------------------------------------------------------------
# column selection (FR-M1.7)
# --------------------------------------------------------------------------


def test_no_selector_profiles_everything():
    result = select_columns(["a", "b"], None, max_columns=100)
    assert result.selected == ("a", "b")
    assert result.excluded == ()


def test_exclude_wins_over_include():
    spec = ColumnSelectorSpec(include=("a", "b"), exclude=("b",))
    result = select_columns(["a", "b", "c"], spec, max_columns=100)
    assert result.selected == ("a",)
    assert result.excluded == ("b", "c")


def test_column_matching_is_case_insensitive():
    spec = ColumnSelectorSpec(exclude=("blob",))
    result = select_columns(["ID", "BLOB"], spec, max_columns=100)
    assert result.selected == ("ID",)


def test_max_columns_truncates_and_reports():
    result = select_columns(["a", "b", "c"], None, max_columns=2)
    assert result.selected == ("a", "b")
    assert result.truncated == ("c",)
    assert result.excluded == ()


def test_selector_resolution_prefers_most_specific():
    db = ColumnSelectorSpec(exclude=("db_only",))
    schema = ColumnSelectorSpec(exclude=("schema_only",))
    table = ColumnSelectorSpec(exclude=("table_only",))
    assert resolve_selector(database=db, schema=schema, table=table) is table
    assert resolve_selector(database=db, schema=schema) is schema
    assert resolve_selector(database=db) is db


def test_empty_declarations_are_skipped():
    empty = ColumnSelectorSpec()
    specific = ColumnSelectorSpec(exclude=("x",))
    assert resolve_selector(database=specific, table=empty) is specific
    assert resolve_selector(database=empty, schema=empty) is None
