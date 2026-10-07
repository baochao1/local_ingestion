"""Lineage collector: read view defs via an ADMIN (read-only) connection and
persist table/column edges (MOD-07).

This module NEVER writes to the business database. It only issues SELECTs
through the supplied connection (which is an ``ADMIN`` purpose connection from
``ConnectionProvider`` — see design D2) and writes edges into the platform
catalog via :class:`LineageRepository`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlalchemy import text

from ..dialect import get_dialect
from .parse import parse_definition
from .repository import LineageRepository

logger = structlog.get_logger()


@dataclass
class CollectResult:
    table_edges: int = 0
    column_edges: int = 0
    views: int = 0
    failed: int = 0
    per_view: list = field(default_factory=list)


def collect_lineage(
    session_factory,
    *,
    datasource_id: int,
    ds_code: str,
    db: str,
    schema: str,
    conn,
    dialect_name: str,
    with_columns: bool = True,
    max_col_depth: int = 20,
) -> CollectResult:
    """Pull view definitions from ``conn`` and persist lineage edges.

    ``conn`` must support ``conn.execute(sql_text, params)`` and yield rows of
    ``(view_name, view_definition)``. A failing view definition never aborts the
    whole collection (design §8 — resilience to partial parse failures).
    """
    repo = LineageRepository(session_factory)
    res = CollectResult()
    sql = text(get_dialect(dialect_name).view_definition_sql())
    try:
        rows = conn.execute(sql, {"schema": schema})
    except Exception as exc:  # connection-level failure
        logger.warning("lineage_view_query_failed", ds=datasource_id, error=str(exc))
        res.failed += 1
        return res

    for view_name, definition in rows:
        if not definition:
            continue
        res.views += 1
        # parse_definition (FR-M4) instead of the bare extract_* helpers: it
        # folds CTEs, applies a timeout, and — unlike the old call — tells us
        # *why* a view produced nothing instead of silently yielding no edges.
        outcome = parse_definition(
            ds_code, db, schema, view_name, definition, dialect_name
        )
        if not outcome.ok:
            res.failed += 1
            logger.warning(
                "lineage_view_parse_failed",
                view=view_name,
                parser=outcome.parser,
                timed_out=outcome.timed_out,
                error=outcome.error,
            )
            continue

        for src, tgt in outcome.table_edges:
            repo.upsert_table_edge(src, tgt, edge_source="view", confidence=1.0)
            res.table_edges += 1
        if with_columns:
            for src, tgt in outcome.column_edges:
                repo.upsert_column_edge(src, tgt, edge_source="view", confidence=0.9)
                res.column_edges += 1

    # keep closure fresh for fast multi-hop queries (design D4)
    repo.rebuild_closure(max_depth=max_col_depth)
    logger.info("lineage_collect_done", ds=datasource_id, **_counts(res))
    return res


def _counts(res: CollectResult) -> dict:
    return {
        "views": res.views,
        "table_edges": res.table_edges,
        "column_edges": res.column_edges,
        "failed": res.failed,
    }
