"""Lineage persistence (MOD-07). One writer per table (total 概览 §4).

All writes go through a SQLAlchemy ``sessionmaker`` (``session_factory``). Edges
are upserted idempotently via the unique ``(src_fqn, tgt_fqn)`` index
(``deleted_at IS NULL``); closure is rebuilt with a cycle-safe recursive CTE.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text

from ..storage.models_ops import LineageClosure, LineageColumnEdge, LineageTableEdge

_DEFAULT_TENANT = 0


class LineageRepository:
    def __init__(self, session_factory):
        self._sf = session_factory

    # -- table edges -------------------------------------------------------
    def upsert_table_edge(self, src_fqn: str, tgt_fqn: str, *, src_table_id=None,
                          tgt_table_id=None, edge_source: str = "view",
                          confidence: float = 1.0, properties: dict | None = None,
                          tenant_id: int = _DEFAULT_TENANT) -> LineageTableEdge:
        with self._sf() as s:
            row = s.execute(
                select(LineageTableEdge).where(
                    LineageTableEdge.src_fqn == src_fqn,
                    LineageTableEdge.tgt_fqn == tgt_fqn,
                    LineageTableEdge.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if row is None:
                row = LineageTableEdge(tenant_id=tenant_id, src_fqn=src_fqn, tgt_fqn=tgt_fqn)
                s.add(row)
            row.src_table_id = src_table_id
            row.tgt_table_id = tgt_table_id
            row.edge_source = edge_source
            row.confidence = confidence
            if properties is not None:
                row.properties = properties
            s.commit()
            s.refresh(row)
            return row

    def upsert_column_edge(self, src_fqn: str, tgt_fqn: str, *, src_column_id=None,
                          tgt_column_id=None, edge_source: str = "view",
                          confidence: float = 0.9, transform_expr: str | None = None,
                          tenant_id: int = _DEFAULT_TENANT) -> LineageColumnEdge:
        with self._sf() as s:
            row = s.execute(
                select(LineageColumnEdge).where(
                    LineageColumnEdge.src_fqn == src_fqn,
                    LineageColumnEdge.tgt_fqn == tgt_fqn,
                    LineageColumnEdge.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if row is None:
                row = LineageColumnEdge(tenant_id=tenant_id, src_fqn=src_fqn, tgt_fqn=tgt_fqn)
                s.add(row)
            row.src_column_id = src_column_id
            row.tgt_column_id = tgt_column_id
            row.edge_source = edge_source
            row.confidence = confidence
            if transform_expr is not None:
                row.transform_expr = transform_expr
            s.commit()
            s.refresh(row)
            return row

    def soft_delete_edge(self, src_fqn: str, tgt_fqn: str, *, column: bool = False) -> int:
        model = LineageColumnEdge if column else LineageTableEdge
        now = datetime.now(timezone.utc)
        with self._sf() as s:
            rows = s.execute(
                select(model).where(
                    model.src_fqn == src_fqn, model.tgt_fqn == tgt_fqn,
                    model.deleted_at.is_(None),
                )
            ).scalars().all()
            for r in rows:
                r.deleted_at = now
            s.commit()
            return len(rows)

    def count_table_edges(self, tenant_id: int = _DEFAULT_TENANT) -> int:
        with self._sf() as s:
            return s.execute(
                select(func.count()).select_from(LineageTableEdge)
                .where(LineageTableEdge.deleted_at.is_(None),
                       LineageTableEdge.tenant_id == tenant_id)
            ).scalar_one()

    # -- closure (cycle-safe, depth-capped) --------------------------------
    def rebuild_closure(self, max_depth: int = 20, tenant_id: int = _DEFAULT_TENANT) -> int:
        """Recompute ``lineage_closure`` from current edges (design §4.3/4.4)."""
        with self._sf() as s:
            s.execute(sa_delete(LineageClosure))
            s.execute(text("""
            INSERT INTO lineage_closure (ancestor_fqn, descendant_fqn, depth, edge_count, rebuilt_at)
            WITH RECURSIVE walk(anc, desc_fqn, depth, path) AS (
                SELECT src_fqn, tgt_fqn, 1, ARRAY[src_fqn, tgt_fqn]
                FROM lineage_table_edge WHERE deleted_at IS NULL
              UNION ALL
                SELECT w.anc, e.tgt_fqn, w.depth + 1, w.path || e.tgt_fqn
                FROM walk w
                JOIN lineage_table_edge e
                  ON e.src_fqn = w.desc_fqn AND e.deleted_at IS NULL
                WHERE w.depth < :max_depth
                  AND NOT e.tgt_fqn = ANY(w.path)
            )
            SELECT anc, desc_fqn, MIN(depth), 1, now()
            FROM walk GROUP BY anc, desc_fqn
            """), {"max_depth": int(max_depth)})
            s.commit()
            return s.execute(select(func.count()).select_from(LineageClosure)).scalar_one()

    def all_closure(self) -> list[LineageClosure]:
        with self._sf() as s:
            return list(s.execute(select(LineageClosure)).scalars().all())

    def walk_closure(self, fqn: str, direction: str = "down",
                     max_depth: int = 20) -> list[dict]:
        """Return related FQNs from the precomputed closure.

        ``direction="down"`` -> descendants of ``fqn``; ``"up"`` -> ancestors.
        """
        col = LineageClosure.descendant_fqn if direction == "up" else LineageClosure.ancestor_fqn
        match = LineageClosure.ancestor_fqn if direction == "up" else LineageClosure.descendant_fqn
        with self._sf() as s:
            rows = s.execute(
                select(match, LineageClosure.depth)
                .where(col == fqn, LineageClosure.depth <= max_depth)
                .order_by(LineageClosure.depth)
            ).all()
        return [{"fqn": r[0], "depth": r[1]} for r in rows]
