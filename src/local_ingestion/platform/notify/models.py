"""Subscription + notification domain models (MOD-06 / T-203).

Severity uses the same P0..P3 scale produced by the change grader (T-202) so a
subscription's ``min_severity`` maps directly onto graded changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def severity_rank(level: str) -> int:
    return SEVERITY_RANK.get(level, 9)


@dataclass
class SubscriptionSpec:
    subscriber: str
    scope_type: str  # global | datasource | schema | table
    scope_fqn: Optional[str] = None
    datasource_id: Optional[int] = None
    min_severity: str = "P2"
    channel: str = "email"
    channel_conf: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class SubscriptionView:
    id: int
    subscriber: str
    scope_type: str
    scope_fqn: Optional[str]
    datasource_id: Optional[int]
    min_severity: str
    channel: str
    enabled: bool
    created_at: Optional[datetime] = None


@dataclass
class ChangeDetail:
    fqn: str
    change_type: str
    level: str
    column: Optional[str] = None
    detail: Dict[str, Any] = field(default_factory=dict)
    cid: int = 0  # stable change id used for dedup logging


@dataclass
class AggregatedNotification:
    subscription_id: int
    subscriber: str
    channel: str
    severity_summary: str
    message: str
    details: List[ChangeDetail] = field(default_factory=list)


@dataclass
class NotificationOutcome:
    notifications: int = 0
    sent: int = 0
    failed: int = 0
    dedup_skipped: int = 0
    errors: List[str] = field(default_factory=list)
