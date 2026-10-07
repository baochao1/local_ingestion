"""Profiling execution (FR-M1) — ``05-1`` stage 2.

Why this module exists
----------------------
Stage 1 decided *what* to compute; this module owns the order in which it
happens against a live database, and — more importantly — every way it can
fail. A profile run can be skipped (too large), fail midway (table dropped),
or degrade (no catalog estimate). Each of those must land as a durable row
with an actionable reason rather than an exception that only shows up in logs,
because the UI promises to explain *why* a table has no profile (FR-M2.4).

Read-only guarantee
-------------------
Every statement issued against the target database is a ``SELECT``. Profiling
never creates temp tables, never writes, and never holds a transaction open —
which is what makes a read-only account sufficient (PC2 / AC-1.4).

Ordering rationale
------------------
Row count first, because both the sampling rate and the skip decision depend
on it, and because ``COUNT(*)`` on a huge table is the single most expensive
thing here — so it is only paid when the catalog estimate is unavailable.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..dialect.base import Dialect
from .config import ProfileConfig
from .histogram import bin_edges, bin_labels
from .metrics import (
    build_aggregate_sql,
    build_histogram_sql,
    estimate_row_count_sql,
    parse_aggregate_row,
    quote_column,
)
from .quantile import METHOD_WINDOW, window_quantile_sql
from .sampling import (
    UnsafeRelationError,
    decide_sample_rate,
    is_safe_relation,
    sample_from_clause,
)
from .selector import ColumnSelectorSpec, resolve_selector, select_columns
from .store import (
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    append_history,
    upsert_profile,
)

log = logging.getLogger(__name__)

__all__ = ["ProfileOutcome", "profile_table"]


@dataclass
class ProfileOutcome:
    """Result of one profiling attempt — always returned, never raised."""

    status: str
    row_count: int | None = None
    column_count: int | None = None
    sample_rate: float | None = None
    sampled_rows: int | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    error_message: str | None = None
    #: How the row count was obtained — surfaced so ops can spot a table whose
    #: statistics are stale and which is therefore paying for COUNT(*).
    row_count_source: str = ""
    #: Columns left unprofiled, with the reason (excluded / truncated).
    skipped_columns: dict[str, str] = field(default_factory=dict)


def profile_table(
    *,
    engine: Engine,
    dialect: Dialect,
    relation: str,
    columns: Sequence[tuple[str, Any]],
    table_id: int,
    datasource_id: int,
    config: ProfileConfig,
    session_factory,
    database_selector: ColumnSelectorSpec | None = None,
    schema_selector: ColumnSelectorSpec | None = None,
    table_selector: ColumnSelectorSpec | None = None,
    profiled_date: date | None = None,
    profiled_at: datetime | None = None,
) -> ProfileOutcome:
    """Profile one table and persist the result.

    ``columns`` is ``[(column_name, data_type), ...]`` where ``data_type`` is a
    :class:`~local_ingestion.schema.base.DataType` or its string value.

    Never raises for data-source problems: they are captured as
    :data:`STATUS_FAILED` / :data:`STATUS_SKIPPED` with a reason. The only
    exception that escapes is :class:`UnsafeRelationError`, which signals a
    programming error (bad relation name) rather than a runtime condition.
    """
    started = time.monotonic()
    started_at = profiled_at or datetime.now()
    day = profiled_date or started_at.date()

    # Validated before *any* statement is issued. This must stay ahead of
    # row-count resolution: that step interpolates the relation directly and
    # would otherwise be the first thing to reach the database with
    # unchecked input.
    if not is_safe_relation(relation):
        raise UnsafeRelationError(f"refusing to profile unsafe relation: {relation!r}")

    try:
        row_count, row_count_source = _resolve_row_count(engine, dialect, relation)

        if config.skip_rows_above is not None and row_count > config.skip_rows_above:
            outcome = ProfileOutcome(
                status=STATUS_SKIPPED,
                row_count=row_count,
                error_message=(
                    f"table exceeds skip_rows_above={config.skip_rows_above}"
                ),
                row_count_source=row_count_source,
            )
            return _persist(
                outcome,
                table_id,
                datasource_id,
                session_factory,
                started_at,
                day,
                started,
            )

        rate = decide_sample_rate(row_count, config)
        from_clause = sample_from_clause(dialect, relation, rate)

        selector = resolve_selector(
            database=database_selector, schema=schema_selector, table=table_selector
        )
        selection = select_columns(
            [name for name, _ in columns], selector, max_columns=config.max_columns
        )

        stats = _collect_column_stats(
            engine=engine,
            dialect=dialect,
            from_clause=from_clause,
            columns=columns,
            selection=selection.selected,
            config=config,
        )

        if config.enable_histogram:
            _attach_histograms(
                engine=engine, from_clause=from_clause, stats=stats, config=config
            )

        # FR-M6 sourcing: pull a few real values per column so value-pattern PII
        # verification has input. One extra read-only SELECT per batch; capped by
        # ``max_columns`` and ``sample_value_cap`` so it cannot blow up memory or
        # query time (PC2 — still only SELECTs against the business database).
        if config.enable_sample_values and selection.selected:
            samples = _collect_samples(
                engine=engine,
                from_clause=from_clause,
                columns=list(selection.selected),
                config=config,
            )
            for name, values in samples.items():
                stats.setdefault(name, {})["samples"] = values

        for name in (*selection.excluded, *selection.truncated):
            stats.setdefault(name, {})["skipped_reason"] = (
                "excluded by selector" if name in selection.excluded else "max_columns"
            )

        sampled_rows = stats.get("_row_count")
        outcome = ProfileOutcome(
            status=STATUS_SUCCESS,
            row_count=row_count,
            column_count=len(selection.selected),
            sample_rate=rate,
            sampled_rows=sampled_rows,
            stats=stats,
            row_count_source=row_count_source,
            skipped_columns={
                name: "excluded" for name in selection.excluded
            }
            | {name: "truncated" for name in selection.truncated},
        )
        return _persist(
            outcome, table_id, datasource_id, session_factory, started_at, day, started
        )

    except UnsafeRelationError:
        raise
    except Exception as exc:  # noqa: BLE001 - failure must become a durable row
        log.warning("profiling failed for %s: %s", relation, exc)
        outcome = ProfileOutcome(
            status=STATUS_FAILED, error_message=str(exc)[:500]
        )
        return _persist(
            outcome, table_id, datasource_id, session_factory, started_at, day, started
        )


def _resolve_row_count(
    engine: Engine, dialect: Dialect, relation: str
) -> tuple[int, str]:
    """Row count from the catalog if possible, ``COUNT(*)`` otherwise (E2)."""
    # Defence in depth: this helper interpolates the relation into a bare
    # COUNT(*), so it must not depend on the caller having validated first.
    if not is_safe_relation(relation):
        raise UnsafeRelationError(f"refusing to profile unsafe relation: {relation!r}")
    estimate_sql = estimate_row_count_sql(dialect, relation)
    if estimate_sql:
        with engine.connect() as conn:
            value = conn.execute(text(estimate_sql)).scalar()
        if value is not None and value >= 0:
            return int(value), "estimate"
    with engine.connect() as conn:
        value = conn.execute(text(f"SELECT COUNT(*) FROM {relation}")).scalar()
    return int(value or 0), "count"


def _collect_column_stats(
    *,
    engine: Engine,
    dialect: Dialect,
    from_clause: str,
    columns: Sequence[tuple[str, Any]],
    selection: Sequence[str],
    config: ProfileConfig,
) -> dict[str, Any]:
    """Run the phase-one aggregates in batches (D4)."""
    by_name = {name: data_type for name, data_type in columns}
    targets = [(name, by_name[name]) for name in selection if name in by_name]
    stats: dict[str, Any] = {}

    for start in range(0, len(targets), config.metric_batch_size):
        batch = targets[start : start + config.metric_batch_size]
        sql, aggs = build_aggregate_sql(
            from_clause, batch, dialect_name=dialect.name, config=config
        )
        with engine.connect() as conn:
            row = conn.execute(text(sql)).mappings().one()
        stats.update(parse_aggregate_row(row, aggs))
        if "_row_count" not in stats:
            stats["_row_count"] = row["_row_count"]

    _fill_window_quantiles(engine, dialect, from_clause, targets, stats)
    return stats


def _fill_window_quantiles(
    engine: Engine,
    dialect: Dialect,
    from_clause: str,
    targets: Sequence[tuple[str, Any]],
    stats: dict[str, Any],
) -> None:
    """Backfill quantiles on dialects with no inline aggregate (MySQL).

    One statement per column, and only for numeric columns — which is exactly
    the case :mod:`platform.profile.metrics` had to skip.
    """
    for column, data_type in targets:
        if str(getattr(data_type, "value", data_type)).upper() not in (
            "INTEGER", "BIGINT", "SMALLINT", "TINYINT", "FLOAT", "DOUBLE", "DECIMAL",
        ):
            continue
        bucket = stats.setdefault(column, {})
        if "median" in bucket:
            continue
        row_count = stats.get("_row_count") or 0
        if not row_count:
            continue
        for label, fraction in (("q1", 0.25), ("median", 0.5), ("q3", 0.75)):
            sql = window_quantile_sql(from_clause, f'"{column}"', row_count, fraction)
            with engine.connect() as conn:
                bucket[label] = conn.execute(text(sql)).scalar()
            bucket.setdefault("quantile_method", METHOD_WINDOW)


def _attach_histograms(
    *, engine: Engine, from_clause: str, stats: dict[str, Any], config: ProfileConfig
) -> None:
    """Phase two: bin edges from phase-one stats, then count per bin (D5/D6)."""
    row_count = int(stats.get("_row_count") or 0)
    for column, metrics in list(stats.items()):
        if column.startswith("_"):
            continue
        by_length = "min_length" in metrics
        low = metrics.get("min_length" if by_length else "min")
        high = metrics.get("max_length" if by_length else "max")
        if low is None or high is None:
            continue
        try:
            low_f, high_f = float(low), float(high)
        except (TypeError, ValueError):
            continue  # temporal min/max — no numeric distribution to bin

        q1, q3 = metrics.get("q1"), metrics.get("q3")
        iqr = None
        if q1 is not None and q3 is not None:
            try:
                iqr = float(q3) - float(q1)
            except (TypeError, ValueError):
                iqr = None

        edges = bin_edges(
            minimum=low_f,
            maximum=high_f,
            iqr=iqr,
            row_count=row_count,
            config=config,
        )
        if len(edges) < 2:
            continue
        sql = build_histogram_sql(from_clause, column, edges, by_length=by_length)
        with engine.connect() as conn:
            row = conn.execute(text(sql)).mappings().one()
        metrics["histogram"] = {
            "by_length": by_length,
            "edges": edges,
            "labels": bin_labels(edges),
            "counts": [int(row[f"b{index}"]) for index in range(len(edges) - 1)],
            "method": "freedman_diaconis" if iqr else "sturges",
        }


def _collect_samples(
    *, engine: Engine, from_clause: str, columns: Sequence[str], config: ProfileConfig
) -> dict[str, list[str]]:
    """Pull a bounded sample of real values per column (FR-M6 source).

    One ``SELECT col1, col2, ... FROM <from_clause> LIMIT k`` per batch; for each
    returned row we keep the first ``sample_value_cap`` non-null string values of
    every column. This is the *only* place samples originate — ``evaluate_column``
    (FR-M6.7 / QC1) deliberately takes them as an argument and never queries, so
    the "no new data is fetched during grading" guarantee holds at the call sites.
    """
    out: dict[str, list[str]] = {}
    if not columns:
        return out
    batch = max(1, config.metric_batch_size)
    for start in range(0, len(columns), batch):
        names = list(columns[start : start + batch])
        quoted = ", ".join(quote_column(name) for name in names)
        sql = f"SELECT {quoted} FROM {from_clause} LIMIT {int(config.sample_row_fetch)}"
        with engine.connect() as conn:
            rows = conn.execute(text(sql)).mappings().all()
        for name in names:
            collected: list[str] = []
            for row in rows:
                value = row[name]
                if value is None:
                    continue
                as_text = str(value)
                if as_text == "":
                    continue
                collected.append(as_text)
                if len(collected) >= config.sample_value_cap:
                    break
            if collected:
                out[name] = collected
    return out


def _persist(
    outcome: ProfileOutcome,
    table_id: int,
    datasource_id: int,
    session_factory,
    started_at: datetime,
    day: date,
    started: float,
) -> ProfileOutcome:
    """Write the outcome and return it with ``duration_ms`` filled in."""
    outcome.duration_ms = int((time.monotonic() - started) * 1000)
    with session_factory() as session:
        upsert_profile(
            session,
            table_id=table_id,
            datasource_id=datasource_id,
            row_count=outcome.row_count,
            column_count=outcome.column_count,
            stats=outcome.stats,
            sample_rate=outcome.sample_rate,
            sampled_rows=outcome.sampled_rows,
            profiled_at=started_at,
            duration_ms=outcome.duration_ms,
            status=outcome.status,
            error_message=outcome.error_message,
        )
        if outcome.status == STATUS_SUCCESS:
            append_history(
                session,
                table_id=table_id,
                datasource_id=datasource_id,
                profiled_date=day,
                row_count=outcome.row_count,
                stats=outcome.stats,
            )
    return outcome
