"""Column/table profiling (FR-M1, FR-M2) — L3 local extension.

Lives under ``platform/`` per ADR-9: nothing here may modify the L1
``schema/`` or ``core/`` packages.

Only the pure, dependency-free layer exists so far (``05-1`` stage 1):
sampling-rate decision, histogram binning, quantile expressions and column
selection. The execution layer that issues SQL belongs to stage 2.

Everything ported from upstream carries its source path and the
``openmetadata-ingestion`` version it was taken from, in the module docstring.
"""
from __future__ import annotations

from .config import (
    DEFAULT_PROFILE_CONFIG,
    DEFAULT_SAMPLE_TIERS,
    ColumnSelectorSpec,
    ProfileConfig,
    SampleTier,
)
from .histogram import bin_edges, bin_labels, bin_width, resolve_bin_count
from .metrics import (
    ColumnAgg,
    build_aggregate_sql,
    build_histogram_sql,
    estimate_row_count_sql,
    metrics_for,
    parse_aggregate_row,
    quote_column,
)
from .quantile import (
    METHOD_APPROX,
    METHOD_EXACT,
    METHOD_WINDOW,
    QuantileExpr,
    quantile_expr,
    window_quantile_sql,
)
from .runner import ProfileOutcome, profile_table
from .sampling import (
    UnsafeRelationError,
    decide_sample_rate,
    is_safe_relation,
    sample_from_clause,
)
from .selector import ColumnSelection, resolve_selector, select_columns
from .store import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    append_history,
    delete_profile,
    get_profile,
    list_history,
    serialise_stats,
    upsert_profile,
)

__all__ = [
    "DEFAULT_PROFILE_CONFIG",
    "DEFAULT_SAMPLE_TIERS",
    "METHOD_APPROX",
    "METHOD_EXACT",
    "METHOD_WINDOW",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "STATUS_RUNNING",
    "STATUS_SKIPPED",
    "STATUS_SUCCESS",
    "ColumnAgg",
    "ColumnSelection",
    "ColumnSelectorSpec",
    "ProfileConfig",
    "ProfileOutcome",
    "QuantileExpr",
    "SampleTier",
    "UnsafeRelationError",
    "append_history",
    "bin_edges",
    "bin_labels",
    "bin_width",
    "build_aggregate_sql",
    "build_histogram_sql",
    "decide_sample_rate",
    "delete_profile",
    "estimate_row_count_sql",
    "get_profile",
    "is_safe_relation",
    "list_history",
    "metrics_for",
    "parse_aggregate_row",
    "profile_table",
    "quantile_expr",
    "quote_column",
    "resolve_bin_count",
    "resolve_selector",
    "sample_from_clause",
    "select_columns",
    "serialise_stats",
    "upsert_profile",
    "window_quantile_sql",
]
