"""Change confirmation closure, statistics & escalation (MOD-06 / T-204)."""
from __future__ import annotations

from datetime import timedelta

from .models import (
    ACK_ACTION_ACKNOWLEDGED,
    ACK_ACTION_IGNORED,
    ACK_ACTION_REJECTED,
    ACK_CLOSED,
    ACK_PENDING,
    ChangeEventInput,
    ChangeEventView,
    ChangeStats,
    VALID_ACK_ACTIONS,
)
from .repository import (
    ChangeRepository,
    InMemoryChangeRepository,
    SqlChangeRepository,
)
from .service import (
    ChangeAlreadyClosedError,
    ChangeConfirmService,
    ChangeEscalationService,
    ChangeNotFoundError,
    ChangeStatsService,
    InvalidAckActionError,
)
from ..notify import build_in_memory_notify_stack


def build_in_memory_change_stack(deadline: timedelta = timedelta(hours=24), audit=None,
                                 on_after_ack=None):
    """Fully wired in-process change stack (no database).

    Returns ``(confirm, stats, escalation, repo, aggregator, sub_service)``.
    """
    repo = InMemoryChangeRepository()
    confirm = ChangeConfirmService(repo, audit=audit, on_after_ack=on_after_ack)
    stats = ChangeStatsService(repo)
    sub_svc, agg, _, _ = build_in_memory_notify_stack()
    escalation = ChangeEscalationService(repo, agg, deadline)
    return confirm, stats, escalation, repo, agg, sub_svc


__all__ = [
    "ACK_ACTION_ACKNOWLEDGED",
    "ACK_ACTION_IGNORED",
    "ACK_ACTION_REJECTED",
    "ACK_CLOSED",
    "ACK_PENDING",
    "ChangeEventInput",
    "ChangeEventView",
    "ChangeStats",
    "VALID_ACK_ACTIONS",
    "ChangeRepository",
    "InMemoryChangeRepository",
    "SqlChangeRepository",
    "ChangeAlreadyClosedError",
    "ChangeConfirmService",
    "ChangeEscalationService",
    "ChangeNotFoundError",
    "ChangeStatsService",
    "InvalidAckActionError",
    "build_in_memory_change_stack",
]
