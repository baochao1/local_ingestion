"""Production lineage service (MOD-07). Replaces the T-205 placeholder.

Upstream/downstream traversal is answered from the precomputed ``lineage_closure``
table (design D4); ``impact_scope`` aggregates affected data sources (and, when
MOD-09 ownership is wired, owners). The service is never degraded once edges
exist — the placeholder's ``degraded`` flag is gone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Protocol

from .models import ImpactNode, ImpactReport
from .repository import LineageRepository


class LineageImpactService(Protocol):
    def impact_scope(self, fqn: str, entity_type: str = "table",
                     max_depth: int = 5) -> ImpactReport: ...


class LineageService:
    def __init__(self, session_factory):
        self.repo = LineageRepository(session_factory)

    def upstream(self, fqn: str, max_depth: int = 5) -> List[ImpactNode]:
        return [ImpactNode(fqn=r["fqn"], depth=r["depth"], entity_type="table")
                for r in self.repo.walk_closure(fqn, "up", max_depth)]

    def downstream(self, fqn: str, max_depth: int = 5) -> List[ImpactNode]:
        return [ImpactNode(fqn=r["fqn"], depth=r["depth"], entity_type="table")
                for r in self.repo.walk_closure(fqn, "down", max_depth)]

    def impact_scope(self, fqn: str, entity_type: str = "table",
                     max_depth: int = 5) -> ImpactReport:
        nodes = self.downstream(fqn, max_depth)
        data_sources = sorted({n.fqn.split(".", 1)[0] for n in nodes})
        return ImpactReport(
            root_fqn=fqn, max_depth=max_depth, downstream=nodes, total=len(nodes),
            data_sources=data_sources, owners=[], degraded=False, note="",
            computed_at=datetime.now(timezone.utc),
        )


def get_default_lineage_service(session_factory=None) -> LineageImpactService:
    """Production default — real impact scope (replaces the T-205 placeholder)."""
    if session_factory is None:
        from ..storage.session import session_scope
        session_factory = session_scope
    return LineageService(session_factory)
