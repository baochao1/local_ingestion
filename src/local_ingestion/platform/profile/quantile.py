"""Per-dialect quantile expressions (FR-M1.5) — ``05-1`` stage 1.

Why this module exists
----------------------
Quantiles are the one column metric with no portable spelling. PostgreSQL and
Snowflake have ordered-set aggregates, Snowflake additionally ships a cheaper
approximate one, and MySQL has neither. Hard-coding ``percentile_cont`` would
fail at run time on MySQL rather than at import time, which is the failure mode
this table exists to prevent.

FR-M1.5 also requires the *method* to be recorded alongside the value: an
approximate median and an exact median are different claims, and a consumer
comparing two tables must be able to tell them apart (see ``05-1`` AC-1.6).

Provenance
----------
Ported from OpenMetadata
``ingestion/src/metadata/profiler/orm/functions/median.py``
(baseline: ``openmetadata-ingestion`` 2.0.0.0.dev0): ``percentile_cont`` by
default, ``approx_percentile`` on engines that provide it.
"""
from __future__ import annotations

from dataclasses import dataclass

#: How a quantile value was obtained. Stored verbatim in ``stats``.
METHOD_EXACT = "exact"  # ordered-set aggregate, exact
METHOD_APPROX = "approx"  # engine-provided approximation
METHOD_WINDOW = "window"  # row-number window query (fallback)


@dataclass(frozen=True)
class QuantileExpr:
    """A quantile aggregate plus how it should be labelled."""

    #: SQL expression usable inside a SELECT list, already column-qualified.
    expression: str
    method: str


def quantile_expr(dialect_name: str, column: str, q: float) -> QuantileExpr:
    """Return the quantile aggregate for ``dialect_name`` at fraction ``q``.

    ``column`` must already be a safe, caller-validated identifier — the same
    contract as :meth:`platform.dialect.base.Dialect.sample_sql` (decision D13).
    """
    if not 0.0 < q < 1.0:
        raise ValueError(f"q must be in (0, 1), got {q!r}")

    name = dialect_name.lower()
    literal = _render_literal(q)

    if name in ("snowflake", "databricks", "athena", "trino", "presto"):
        # Upstream overrides these to the cheaper approximate function.
        return QuantileExpr(
            expression=f"APPROX_PERCENTILE({column}, {literal})",
            method=METHOD_APPROX,
        )

    if name in ("postgres", "postgresql", "greenplum", "redshift", "cockroach"):
        return QuantileExpr(
            expression=(
                f"percentile_cont({literal}) WITHIN GROUP (ORDER BY {column})"
            ),
            method=METHOD_EXACT,
        )

    # MySQL (and anything unknown) has no ordered-set aggregate. Callers must
    # fall back to :func:`window_quantile_sql`.
    return QuantileExpr(expression="", method=METHOD_WINDOW)


def window_quantile_sql(source: str, column: str, row_count: int, q: float) -> str:
    """Fallback quantile query for dialects without ordered-set aggregates.

    ``source`` is a FROM clause (table name or inline sample view). Ranks the
    non-null values and picks the row at ``ceil(q * n)``.

    This is *not* an interpolation: it returns an observed value, which is why
    :data:`METHOD_WINDOW` is recorded rather than "exact".
    """
    if row_count <= 0:
        raise ValueError(f"row_count must be positive, got {row_count!r}")
    rank = max(1, int(-(-(q * row_count) // 1)))  # ceil without float drift
    return (
        f"SELECT {column} FROM ("
        f"SELECT {column}, ROW_NUMBER() OVER (ORDER BY {column}) AS _rn "
        f"FROM {source} WHERE {column} IS NOT NULL"
        f") AS _ranked WHERE _rn = {rank}"
    )


def _render_literal(q: float) -> str:
    """Render ``q`` without scientific notation (SQL rejects ``5e-01``)."""
    text = f"{q:.6f}".rstrip("0").rstrip(".")
    return text or "0"
