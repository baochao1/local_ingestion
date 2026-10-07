"""Column-metric SQL construction (FR-M1.4/1.5) — ``05-1`` stage 2.

Why this module exists
----------------------
Two things make "just aggregate every column the same way" wrong:

1. ``AVG(description)`` is a type error, not a NULL. Numeric, temporal and
   textual columns each support a different metric set, so the metric set is
   derived per column from its :class:`~local_ingestion.schema.base.DataType`.
2. A histogram needs the IQR, and the IQR needs Q1/Q3 — which are themselves
   aggregates. Rather than a separate "get me the IQR" round trip, phase one
   already selects Q1/Q3 alongside min/max/count, and the histogram reuses
   them (decision D5).

Row-count estimation also lives here because its fallback chain (system
catalog first, ``COUNT(*)`` only as a last resort, edge E2) is pure SQL shape.

Provenance
----------
Metric set follows OpenMetadata ``profiler/processor/default.py``
(row/column count, null, distinct, unique, min/max, mean/stddev, quartiles);
quantile spellings come from :mod:`platform.profile.quantile`.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..dialect.base import Dialect
from .config import ProfileConfig
from .quantile import METHOD_WINDOW, quantile_expr

__all__ = [
    "ColumnAgg",
    "ColumnMetric",
    "quote_column",
    "metrics_for",
    "build_aggregate_sql",
    "parse_aggregate_row",
    "estimate_row_count_sql",
]

_NUMERIC = frozenset(
    {"INTEGER", "BIGINT", "SMALLINT", "TINYINT", "FLOAT", "DOUBLE", "DECIMAL"}
)
_TEMPORAL = frozenset({"DATE", "TIME", "TIMESTAMP"})
_TEXTUAL = frozenset({"STRING", "TEXT", "UUID", "BYTES", "BINARY", "JSON"})


#: ``(SELECT alias, column name, metric name)`` for one emitted aggregate.
ColumnAgg = tuple[str, str, str]


def _is_numeric(data_type: Any) -> bool:
    """Whether quantile/numeric metrics apply, tolerant of enum or raw string."""
    return str(getattr(data_type, "value", data_type)).upper() in _NUMERIC


def quote_column(name: str) -> str:
    """Quote ``name`` as a double-quoted identifier.

    Column names arrive from catalog data and may legitimately contain spaces
    or non-ASCII characters, so unlike relations (which are validated by
    :func:`platform.profile.sampling.is_safe_relation`) we quote rather than
    reject — the only escaping needed is doubling an embedded quote.
    """
    return '"' + name.replace('"', '""') + '"'


@dataclass(frozen=True)
class ColumnMetric:
    """One aggregate to compute for one column."""

    #: Key used in the returned ``stats`` payload.
    name: str
    #: SELECT-list expression template; ``{col}`` is the quoted identifier.
    template: str
    #: Only emitted when the dialect supports it (quantiles on MySQL do not).
    dialect_specific: bool = False


#: Metrics every column gets, regardless of type.
_COMMON_METRICS = (
    ColumnMetric("null_count", "COUNT(*) - COUNT({col})"),
    ColumnMetric("distinct_count", "COUNT(DISTINCT {col})"),
)

_NUMERIC_METRICS = (
    ColumnMetric("min", "MIN({col})"),
    ColumnMetric("max", "MAX({col})"),
    ColumnMetric("mean", "AVG({col})"),
    ColumnMetric("stddev", "STDDEV_SAMP({col})"),
)

_TEMPORAL_METRICS = (
    ColumnMetric("min", "MIN({col})"),
    ColumnMetric("max", "MAX({col})"),
)

_TEXTUAL_METRICS = (
    ColumnMetric("min", "MIN({col})"),
    ColumnMetric("max", "MAX({col})"),
    # Feeds FR-M2.2's "string length distribution" histogram.
    ColumnMetric("min_length", "MIN(LENGTH({col}))"),
    ColumnMetric("max_length", "MAX(LENGTH({col}))"),
)


def metrics_for(data_type: Any) -> tuple[ColumnMetric, ...]:
    """Metric set appropriate for ``data_type``.

    ``data_type`` is compared by its string value so this works for both the
    :class:`~local_ingestion.schema.base.DataType` enum and a raw catalog
    string.
    """
    name = str(getattr(data_type, "value", data_type)).upper()
    if name in _NUMERIC:
        return _COMMON_METRICS + _NUMERIC_METRICS
    if name in _TEMPORAL:
        return _COMMON_METRICS + _TEMPORAL_METRICS
    if name in _TEXTUAL:
        return _COMMON_METRICS + _TEXTUAL_METRICS
    # ARRAY / MAP / STRUCT / UNKNOWN: presence is the only safe claim.
    return _COMMON_METRICS


def build_aggregate_sql(
    from_clause: str,
    columns: Sequence[tuple[str, Any]],
    *,
    dialect_name: str,
    config: ProfileConfig,
) -> tuple[str, list[ColumnAgg]]:
    """Build one aggregate statement for ``columns``.

    Returns ``(sql, aggs)`` where ``aggs`` is ``(alias, column, metric)`` per
    emitted aggregate, so the caller can walk a result row without re-parsing
    SQL. Aliases are numbered by column position rather than derived from the
    column name: two columns named ``a b`` and ``a_b`` must not collide.

    Quantiles are emitted only when the dialect can express them inline; on
    dialects that need the window fallback (MySQL) they are skipped here and
    :func:`platform.profile.quantile.window_quantile_sql` is used instead.
    """
    del config  # reserved for future per-batch tuning
    selects = ["COUNT(*) AS _row_count"]
    aggs: list[ColumnAgg] = []

    for index, (column, data_type) in enumerate(columns):
        quoted = quote_column(column)
        for metric in metrics_for(data_type):
            alias = f"m{index}_{metric.name}"
            selects.append(metric.template.format(col=quoted) + f" AS {alias}")
            aggs.append((alias, column, metric.name))

        if _is_numeric(data_type):
            for label, fraction in (("q1", 0.25), ("median", 0.5), ("q3", 0.75)):
                expr = quantile_expr(dialect_name, quoted, fraction)
                if expr.method == METHOD_WINDOW:
                    continue
                alias = f"m{index}_{label}"
                selects.append(expr.expression + f" AS {alias}")
                aggs.append((alias, column, label))

    sql = "SELECT " + ", ".join(selects) + f" FROM {from_clause}"
    return sql, aggs


def parse_aggregate_row(
    row: Any, aggs: Sequence[ColumnAgg]
) -> dict[str, dict[str, Any]]:
    """Turn one aggregate result row into ``{column: {metric: value}}``.

    ``None`` values are kept (a column with no non-null rows has no mean), and
    ``Decimal`` / ``datetime`` are left untouched — serialising them is the
    store's job, not ours.
    """
    result: dict[str, dict[str, Any]] = {}
    for alias, column, metric in aggs:
        if hasattr(row, "_mapping"):
            value = row._mapping[alias]
        else:
            value = row[alias]
        result.setdefault(column, {})[metric] = value
    return result


def estimate_row_count_sql(dialect: Dialect, relation: str) -> str | None:
    """Cheap row-count estimate from system catalogs, if the dialect has one.

    Returns ``None`` when the dialect exposes no estimate, in which case the
    caller falls back to ``COUNT(*)`` and records the degradation (edge E2).
    """
    # A negative result (or no row) means "no estimate available", which the
    # caller distinguishes from "the table is empty" — collapsing both to 0
    # would silently turn an un-ANALYZEd table into a full COUNT(*) scan.
    name = dialect.name.lower()
    if name in ("postgres", "postgresql", "greenplum"):
        return (
            "SELECT COALESCE(c.reltuples, -1)::bigint "
            "FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE c.relname = {table} AND n.nspname = {schema}"
        ).format(**_split_relation(relation))
    if name == "mysql":
        return (
            "SELECT COALESCE(TABLE_ROWS, -1) "
            "FROM information_schema.TABLES "
            "WHERE TABLE_NAME = {table} AND TABLE_SCHEMA = {schema}"
        ).format(**_split_relation(relation))
    return None


def build_histogram_sql(
    from_clause: str, column: str, edges: Sequence[float], *, by_length: bool = False
) -> str:
    """Count rows per bin using portable ``CASE WHEN`` (decision D6).

    ``width_bucket`` would be shorter on PostgreSQL but does not exist on
    MySQL, and a portable statement avoids maintaining two code paths.
    ``by_length`` switches the input to ``LENGTH(col)`` for the string-length
    distribution required by FR-M2.2.
    """
    if len(edges) < 2:
        raise ValueError("need at least two edges")
    target = f"LENGTH({quote_column(column)})" if by_length else quote_column(column)
    cases = []
    for index in range(len(edges) - 1):
        lower = _literal(edges[index])
        upper = _literal(edges[index + 1])
        if index == len(edges) - 2:
            # Last bin is inclusive of the maximum (see bin_edges).
            predicate = f"{target} >= {lower} AND {target} <= {upper}"
        else:
            predicate = f"{target} >= {lower} AND {target} < {upper}"
        cases.append(f"SUM(CASE WHEN {predicate} THEN 1 ELSE 0 END) AS b{index}")
    return "SELECT " + ", ".join(cases) + f" FROM {from_clause}"


def _literal(value: float) -> str:
    """Render a float literal without scientific notation."""
    return f"{float(value):.10f}".rstrip("0").rstrip(".")


def _split_relation(relation: str) -> dict[str, str]:
    """Split ``schema.table`` into quoted literals for catalog lookups."""
    parts = [p.strip().strip('"') for p in relation.split(".")]
    if len(parts) >= 2:
        schema, table = parts[-2], parts[-1]
    else:
        schema, table = "public", parts[-1]
    quote = lambda value: "'" + value.replace("'", "''") + "'"  # noqa: E731
    return {"schema": quote(schema), "table": quote(table)}
