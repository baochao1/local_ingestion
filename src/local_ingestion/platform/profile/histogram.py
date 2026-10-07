"""Histogram binning (FR-M1.6) — ``05-1`` stage 1.

Why this module exists
----------------------
A histogram needs its bin edges *before* the counts can be queried, and the
number of bins depends on statistics (IQR, row count) that themselves come from
a query. That two-phase shape (decision D5) is why binning is a pure function
here: phase one produces ``count/min/max/IQR``, this module turns them into
edges, phase two counts rows per edge.

Provenance
----------
Ported from OpenMetadata
``ingestion/src/metadata/profiler/metrics/hybrid/histogram.py``
(baseline: ``openmetadata-ingestion`` 2.0.0.0.dev0):

* bin width via the Freedman-Diaconis rule ``2 * IQR * n ** (-1/3)``;
* if that yields more than ``max_bins`` bins, fall back to Sturges'
  ``ceil(log2(n) + 1)``;
* if Sturges also exceeds ``max_bins``, clamp to ``max_bins``.

The fallbacks matter: a heavy-tailed column produces a tiny FD bin width and
therefore an absurd bin count, which is exactly the case that would otherwise
blow up the ``stats`` JSONB payload.
"""
from __future__ import annotations

import math

from .config import ProfileConfig

__all__ = [
    "bin_width",
    "resolve_bin_count",
    "bin_edges",
    "bin_labels",
    "format_number",
]


def bin_width(iqr: float, row_count: int) -> float:
    """Freedman-Diaconis bin width.

    ``iqr == 0`` means the middle 50% of values are identical; the rule would
    then produce a zero-width bin, so upstream returns 1.
    """
    if iqr == 0:
        return 1.0
    return 2.0 * iqr * (row_count ** (-1.0 / 3.0))


def resolve_bin_count(
    *,
    minimum: float,
    maximum: float,
    iqr: float | None,
    row_count: int,
    config: ProfileConfig,
) -> tuple[int, float]:
    """Return ``(num_bins, width)`` for the histogram.

    Resolved in three steps: Freedman-Diaconis, then Sturges, then a hard clamp.
    """
    max_bins = max(1, config.max_bins)
    span = maximum - minimum
    if span <= 0:
        # Constant column: a single bin is the only honest answer.
        return 1, 0.0
    if row_count <= 0:
        return 1, span

    num_bins = 0
    width = span
    if iqr is not None:
        width = bin_width(iqr, row_count)
        if width > 0:
            num_bins = math.ceil(span / width)

    if iqr is None or num_bins > max_bins or num_bins <= 0:
        # Sturges' rule — also the path taken when IQR is unavailable.
        num_bins = int(math.ceil(math.log2(row_count) + 1))
        num_bins = max(1, num_bins)
        width = span / num_bins

    if num_bins > max_bins:
        num_bins = max_bins
        width = span / num_bins

    return num_bins, width


def bin_edges(
    *,
    minimum: float,
    maximum: float,
    iqr: float | None,
    row_count: int,
    config: ProfileConfig,
) -> list[float]:
    """Return the closed-open bin boundaries, including both endpoints.

    The final edge is pinned to ``maximum`` so the last bin is inclusive;
    without that, floating point drift would drop the maximum value itself.
    """
    num_bins, width = resolve_bin_count(
        minimum=minimum, maximum=maximum, iqr=iqr, row_count=row_count, config=config
    )
    if num_bins <= 1:
        return [float(minimum), float(maximum)]

    edges = [float(minimum) + (i * width) for i in range(num_bins)]
    edges.append(float(maximum))
    return edges


def bin_labels(edges: list[float]) -> list[str]:
    """Human-readable label per bin, matching upstream's ``_format_bin_labels``.

    The last bin reads ``"X and up"`` because it is inclusive of the maximum.
    """
    if len(edges) < 2:
        return []
    labels: list[str] = []
    for index in range(len(edges) - 1):
        lower = edges[index]
        upper = edges[index + 1]
        if index == len(edges) - 2:
            labels.append(f"{format_number(lower)} and up")
        else:
            labels.append(f"{format_number(lower)} to {format_number(upper)}")
    return labels


def format_number(value: float) -> str:
    """Compact rendering for bin labels (``1234567`` -> ``1.23457e+06``)."""
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:g}"
