"""Lineage impact domain models (MOD-07 / T-205).

The impact scope (contract C7) answers: given a changed entity, which downstream
objects, data sources and owners are affected. Until MOD-07 is deployed this is a
*placeholder* that degrades gracefully — it reports no downstream impact and
flags ``degraded=True`` so callers (e.g. MOD-06 escalation) can fall back to
notifying only the direct owner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class ImpactNode:
    fqn: str
    depth: int
    entity_type: str = "table"


@dataclass
class ImpactReport:
    root_fqn: str
    max_depth: int
    downstream: List[ImpactNode]
    total: int
    data_sources: List[str]
    owners: List[str]
    degraded: bool
    note: str
    computed_at: datetime
