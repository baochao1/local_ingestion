"""Column include/exclude resolution (FR-M1.7) — ``05-1`` stage 1.

Why this module exists
----------------------
Profiling every column of a 500-column table is wasted work: most of those
columns are uninteresting, and the ``stats`` payload grows with each one
(NFR-M3). Operators need to say "skip everything matching ``%_blob`` in this
schema" once, not per table.

Resolution follows upstream's three-level inheritance: a table-level
declaration wins, otherwise the schema's, otherwise the database's. An absent
``include`` means "everything", which keeps the default behaviour unchanged.

Provenance
----------
Ported from OpenMetadata
``ingestion/src/metadata/sampler/config.py`` ``get_include_columns`` /
``get_exclude_columns`` (baseline: ``openmetadata-ingestion`` 2.0.0.0.dev0).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .config import ColumnSelectorSpec

__all__ = ["ColumnSelection", "resolve_selector", "select_columns"]


@dataclass(frozen=True)
class ColumnSelection:
    """Outcome of applying a selector to a table's columns."""

    #: Columns to profile, in input order.
    selected: tuple[str, ...]
    #: Columns deliberately not profiled; reported so the UI can say why.
    excluded: tuple[str, ...]
    #: Columns dropped because :attr:`ProfileConfig.max_columns` was hit.
    truncated: tuple[str, ...]


def resolve_selector(
    database: ColumnSelectorSpec | None = None,
    schema: ColumnSelectorSpec | None = None,
    table: ColumnSelectorSpec | None = None,
) -> ColumnSelectorSpec | None:
    """Pick the most specific declared selector (table > schema > database).

    Returns ``None`` when nothing was declared anywhere, which callers treat as
    "profile every column".
    """
    for candidate in (table, schema, database):
        if candidate is None:
            continue
        if candidate.include or candidate.exclude:
            return candidate
    return None


def select_columns(
    columns: Sequence[str],
    selector: ColumnSelectorSpec | None,
    *,
    max_columns: int,
) -> ColumnSelection:
    """Apply ``selector`` then the ``max_columns`` cap.

    Matching is case-insensitive on the exact column name — ``col_a`` in config
    matches ``COL_A`` in the catalog, because several supported engines fold
    identifiers differently.
    """
    exclude = {name.lower() for name in (selector.exclude if selector else ())}
    include = (
        {name.lower() for name in selector.include}
        if selector and selector.include is not None
        else None
    )

    kept: list[str] = []
    excluded: list[str] = []
    for column in columns:
        folded = column.lower()
        if folded in exclude:
            excluded.append(column)
            continue
        if include is not None and folded not in include:
            excluded.append(column)
            continue
        kept.append(column)

    truncated: tuple[str, ...] = ()
    if max_columns > 0 and len(kept) > max_columns:
        truncated = tuple(kept[max_columns:])
        kept = kept[:max_columns]

    return ColumnSelection(
        selected=tuple(kept), excluded=tuple(excluded), truncated=truncated
    )
