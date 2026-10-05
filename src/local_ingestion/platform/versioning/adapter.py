"""Adapter: build a :class:`CatalogState` from catalog ORM rows (MOD-06).

Keeps the diff engine storage-agnostic; the caller passes already-loaded
``catalog_table`` / ``catalog_column`` rows (or snapshot projections) and this
maps them into the normalized :class:`ColumnSpec` / :class:`TableSpec`.
"""
from __future__ import annotations

from typing import Dict, Iterable, List

from .models import CatalogState, ColumnSpec, TableSpec


def _schema_of(fqn: str) -> str:
    parts = fqn.split(".")
    return ".".join(parts[:-1]) if len(parts) > 1 else ""


def _is_sensitive(tags, props) -> tuple[bool, bool]:
    tags = set(tags or [])
    props = props or {}
    is_pii = bool(props.get("pii")) or "PII" in tags or "pii" in tags
    high = bool(props.get("high_sensitivity")) or "HIGH" in tags
    return is_pii, high


def build_catalog_state(
    tables: Iterable,
    columns_by_table: Dict[int, List],
) -> CatalogState:
    """``columns_by_table`` maps ``catalog_table.id`` -> list of column rows."""
    state = CatalogState()
    for t in tables:
        cols: List[ColumnSpec] = []
        for c in columns_by_table.get(t.id, []):
            is_pii, high = _is_sensitive(getattr(c, "tags", None), getattr(c, "properties", None))
            cols.append(
                ColumnSpec(
                    name=c.name,
                    data_type=c.data_type or "",
                    nullable=bool(c.nullable),
                    comment=getattr(c, "description", None),
                    is_pii=is_pii,
                    high_sensitivity=high,
                    importance=getattr(c, "grade_level", None) or 0,
                )
            )
        # Filter soft-deleted rows defensively.
        if getattr(t, "deleted_at", None) is not None:
            continue
        state.tables.append(
            TableSpec(
                fqn=t.fqn,
                name=t.name,
                schema=_schema_of(t.fqn),
                columns=cols,
                struct_hash=getattr(t, "struct_hash", None),
                importance=getattr(t, "grade_level", None) or 0,
            )
        )
    return state
