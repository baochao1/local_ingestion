"""Change-confirmation domain models (MOD-06 / T-204).

Extends the persisted ``change_event`` (severity = breaking/structural/descriptive)
with the acknowledgement state needed for the confirmation closure (FR-7.9) and
the statistics rollup.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

ACK_PENDING = "pending"
ACK_CLOSED = "closed"

ACK_ACTION_ACKNOWLEDGED = "acknowledged"
ACK_ACTION_REJECTED = "rejected"
ACK_ACTION_IGNORED = "ignored"

VALID_ACK_ACTIONS = frozenset(
    {ACK_ACTION_ACKNOWLEDGED, ACK_ACTION_REJECTED, ACK_ACTION_IGNORED}
)


@dataclass
class ChangeEventInput:
    entity_type: str
    change_type: str
    severity: str
    entity_fqn: Optional[str] = None
    datasource_id: Optional[int] = None
    entity_id: Optional[int] = None
    scan_run_id: Optional[int] = None
    before_json: Optional[dict] = None
    after_json: Optional[dict] = None
    detected_at: Optional[datetime] = None


@dataclass
class ChangeEventView:
    id: int
    detected_at: datetime
    scan_run_id: Optional[int]
    datasource_id: Optional[int]
    entity_type: str
    entity_id: Optional[int]
    entity_fqn: Optional[str]
    change_type: str
    severity: str
    before_json: Optional[dict]
    after_json: Optional[dict]
    notified: bool
    ack_status: str
    ack_action: Optional[str]
    ack_by: Optional[str]
    ack_at: Optional[datetime]


@dataclass
class ChangeStats:
    total: int
    by_severity: Dict[str, int]
    by_datasource: Dict[str, int]
    ack_rate: float
    top_unstable: List[Tuple[str, int]]
    window: Tuple[datetime, datetime]
