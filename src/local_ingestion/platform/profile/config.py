"""Profiling configuration (FR-M1) — ``05-1`` stage 1.

Why this module exists
----------------------
Profiling needs a dozen magic numbers: how much to sample, how many histogram
bins, when to give up on a table. They are referenced from four other modules,
so they live here once instead of being re-derived (and drifting) per call site.

Provenance
----------
The sampling tiers are ported from OpenMetadata
``ingestion/src/metadata/sampler/config.py`` ``get_tiered_sample``
(baseline: ``openmetadata-ingestion`` 2.0.0.0.dev0). The histogram caps come
from ``profiler/metrics/hybrid/histogram.py``. Values are exposed as
configuration rather than baked into call sites so they can be retuned per
deployment (see ``05-1`` PQ-1 / PQ-3).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SampleTier:
    """One rung of the sampling ladder: tables up to ``max_rows`` use ``rate``.

    ``rate`` is a fraction (0 < rate <= 1). Tiers are evaluated in order and
    the first matching one wins, so they must be declared ascending.
    """

    max_rows: int
    rate: float


#: Ported from upstream ``get_tiered_sample``. Small tables are profiled in
#: full; the rate collapses by roughly 5x per decade of rows so that the
#: absolute sample size stays in the same ballpark.
DEFAULT_SAMPLE_TIERS: tuple[SampleTier, ...] = (
    SampleTier(max_rows=100_000, rate=1.0),
    SampleTier(max_rows=1_000_000, rate=0.5),
    SampleTier(max_rows=10_000_000, rate=0.1),
    SampleTier(max_rows=100_000_000, rate=0.05),
    SampleTier(max_rows=1_000_000_000, rate=0.01),
)

#: Used when ``row_count`` exceeds every tier (upstream falls back to 0.1%).
DEFAULT_FALLBACK_RATE = 0.001


@dataclass(frozen=True)
class ProfileConfig:
    """Tunables for one profiling run.

    Every field has a conservative default so a deployment can start without
    configuration and tighten later.
    """

    sample_tiers: tuple[SampleTier, ...] = DEFAULT_SAMPLE_TIERS
    fallback_rate: float = DEFAULT_FALLBACK_RATE

    #: Hard cap on histogram bins (upstream ``max_bin_count``).
    max_bins: int = 100

    #: Columns profiled per statement. Wider tables are split into batches so a
    #: single aggregate SQL does not grow without bound (decision D4).
    metric_batch_size: int = 40

    #: Columns beyond this are left unprofiled and marked as such (edge E7).
    max_columns: int = 500

    #: Tables with more rows than this are skipped outright with
    #: ``status='skipped'`` (NFR-M1 / edge E10). ``None`` disables skipping.
    skip_rows_above: int | None = 5_000_000_000

    #: Rows pulled into memory when a dialect can do neither ``width_bucket``
    #: nor ``CASE WHEN`` binning. Last resort only (decision D6) and capped so
    #: a pathological table cannot exhaust memory.
    in_memory_histogram_max_rows: int = 50_000

    #: Upper bound on the serialised ``stats`` payload (NFR-M3, PQ-3).
    stats_max_bytes: int = 1_000_000

    enable_histogram: bool = True

    #: FR-M6: collect a few real values per column so value-pattern PII
    #: verification has something to chew on. Off by default? No — it is what
    #: makes FR-M6 usable, and it is a bounded, read-only ``SELECT`` (one extra
    #: statement per batch of columns, capped by ``max_columns``).
    enable_sample_values: bool = True

    #: Max non-null values stored per column (fed to ``evaluate_column``).
    sample_value_cap: int = 20

    #: Rows pulled back when collecting samples; more rows means fuller per-column
    #: sample lists before the per-column cap kicks in.
    sample_row_fetch: int = 50


DEFAULT_PROFILE_CONFIG = ProfileConfig()


@dataclass(frozen=True)
class ColumnSelectorSpec:
    """Include/exclude declaration for one scope (table / schema / database)."""

    include: tuple[str, ...] | None = None
    exclude: tuple[str, ...] = field(default_factory=tuple)
