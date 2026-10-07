"""Sampling rate decision and sample FROM-clause (FR-M1.1/1.2) — stage 1.

Why this module exists
----------------------
Profiling a 10-billion-row table in full is not a slow profile, it is an
incident. The rate decision therefore happens before any SQL is issued, and it
is a pure function of the row count so it can be unit-tested without a database.

The row count itself is deliberately *not* computed here: reading it from
system catalogs (falling back to ``COUNT(*)``) is phase-two work and belongs in
the runner, which owns the connection.

Provenance
----------
Tiers ported from OpenMetadata
``ingestion/src/metadata/sampler/config.py`` ``get_tiered_sample``
(baseline: ``openmetadata-ingestion`` 2.0.0.0.dev0).

Decisions
---------
* **D2** — reuse :meth:`platform.dialect.base.Dialect.sample_sql` rather than
  re-deriving per-engine sampling syntax.
* **D3** — when the rate is 1.0, return the bare relation instead of wrapping
  it in a subquery; ``TABLESAMPLE BERNOULLI(100)`` is correct but adds a scan.
* **D13** — ``sample_sql`` renders the table name as-is by contract ("must be a
  caller-validated identifier"). Since profiling builds table names from
  catalog data, we re-assert that contract here before it reaches SQL.
"""
from __future__ import annotations

import re

from ..dialect.base import Dialect
from .config import ProfileConfig

__all__ = [
    "decide_sample_rate",
    "sample_from_clause",
    "is_safe_relation",
    "UnsafeRelationError",
]

#: Characters allowed in a (possibly schema-qualified, possibly quoted)
#: relation name. Deliberately narrow: no whitespace, no statement separators,
#: no comment introducers.
_SAFE_RELATION = re.compile(r'^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*$')
_SAFE_QUOTED_RELATION = re.compile(r'^"[A-Za-z0-9_ ]+"(?:\."[A-Za-z0-9_ ]+")*$')


class UnsafeRelationError(ValueError):
    """Raised when a relation name cannot be safely interpolated into SQL."""


def is_safe_relation(name: str) -> bool:
    """Whether ``name`` is a bare or double-quoted relation we may interpolate."""
    if not name or len(name) > 512:
        return False
    return bool(_SAFE_RELATION.match(name) or _SAFE_QUOTED_RELATION.match(name))


def decide_sample_rate(row_count: int | None, config: ProfileConfig) -> float:
    """Fraction of rows to profile for a table of ``row_count`` rows.

    ``row_count is None`` (unknown) is treated as "assume the worst" and gets
    the fallback rate — an unknown-size table is exactly the one we must not
    scan in full.
    """
    if row_count is None:
        return config.fallback_rate
    if row_count <= 0:
        # Empty table: nothing to sample, but still "full" so callers can
        # distinguish it from a sampled run.
        return 1.0

    for tier in config.sample_tiers:
        if row_count <= tier.max_rows:
            return tier.rate
    return config.fallback_rate


def sample_from_clause(dialect: Dialect, relation: str, rate: float) -> str:
    """Return the FROM clause to profile against.

    Either the bare relation (rate 1.0, decision D3) or an inline view over
    ``dialect.sample_sql`` (D2). Callers compose ``SELECT <aggs> FROM <this>``.
    """
    if not is_safe_relation(relation):
        raise UnsafeRelationError(f"refusing to profile unsafe relation: {relation!r}")

    if rate >= 1.0:
        return relation

    sample_sql = dialect.sample_sql(relation, rate)
    return f"({sample_sql}) AS _profile_sample"
