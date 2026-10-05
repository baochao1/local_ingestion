"""Change-confirmation closure, statistics and escalation (MOD-06 / T-204).

* **Closure (FR-7.9)** — a responsible person acknowledges a change
  (acknowledged / rejected / ignored); the event then closes and the action is
  written through the shared ``AuditService`` (T-107), so the loop is auditable.
* **Statistics** — rollup over a time window: totals, severity & datasource
  distribution, acknowledgement rate, and the most "unstable" entities.
* **Escalation (FR-7.8)** — breaking changes that stay unacknowledged past a
  deadline are escalated. This reuses the T-203 ``NotificationAggregator``
  (same scope/severity/dedup/multi-channel machinery) by mapping the persisted
  ``severity`` onto the graded ``level`` scale.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

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
from .repository import ChangeRepository
from ..notify.models import NotificationOutcome
from ..notify.service import NotificationAggregator
from ..orchestration.audit import AuditService
from ..versioning.models import GradedChange

SEVERITY_TO_LEVEL = {
    "breaking": "P0",
    "structural": "P2",
    "descriptive": "P3",
}


class ChangeNotFoundError(Exception):
    def __init__(self, change_id: int) -> None:
        super().__init__(f"change event {change_id} not found")
        self.change_id = change_id


class ChangeAlreadyClosedError(Exception):
    def __init__(self, change_id: int) -> None:
        super().__init__(f"change event {change_id} already closed")
        self.change_id = change_id


class InvalidAckActionError(Exception):
    def __init__(self, action: str) -> None:
        super().__init__(f"invalid ack action: {action!r}")
        self.action = action


class ChangeConfirmService:
    def __init__(self, repo: ChangeRepository, audit: Optional[AuditService] = None,
                 on_after_ack=None) -> None:
        self._repo = repo
        self._audit = audit
        # Optional hook invoked after a change is acknowledged/rejected. Used to
        # raise a follow-up ticket for breaking changes (MOD-12 linkage) without
        # the changes module depending on the governance module.
        self._on_after_ack = on_after_ack

    def ack(self, change_id: int, actor: str, action: str) -> ChangeEventView:
        if action not in VALID_ACK_ACTIONS:
            raise InvalidAckActionError(action)
        ev = self._repo.get(change_id)
        if ev is None:
            raise ChangeNotFoundError(change_id)
        if ev.ack_status == ACK_CLOSED:
            raise ChangeAlreadyClosedError(change_id)
        self._repo.set_ack(change_id, action, actor, datetime.now(timezone.utc))
        if self._audit:
            self._audit.record(
                actor, "change.ack", entity_type="change_event",
                entity_fqn=str(change_id), detail={"action": action},
            )
        if self._on_after_ack is not None:
            self._on_after_ack(ev, action)
        return self._repo.get(change_id)


class ChangeStatsService:
    def __init__(self, repo: ChangeRepository) -> None:
        self._repo = repo

    def statistics(self, since: datetime, until: datetime, top_n: int = 5) -> ChangeStats:
        evs = self._repo.windowed(since, until)
        total = len(evs)
        by_severity: dict = {}
        by_datasource: dict = {}
        closed = 0
        counter: dict = {}
        for e in evs:
            by_severity[e.severity] = by_severity.get(e.severity, 0) + 1
            ds = str(e.datasource_id if e.datasource_id is not None else "unknown")
            by_datasource[ds] = by_datasource.get(ds, 0) + 1
            if e.ack_status == ACK_CLOSED:
                closed += 1
            if e.entity_fqn:
                counter[e.entity_fqn] = counter.get(e.entity_fqn, 0) + 1
        ack_rate = round(closed / total, 4) if total else 0.0
        top = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
        return ChangeStats(
            total=total, by_severity=by_severity, by_datasource=by_datasource,
            ack_rate=ack_rate, top_unstable=top, window=(since, until),
        )


class ChangeEscalationService:
    def __init__(self, repo: ChangeRepository, aggregator: NotificationAggregator,
                 deadline: timedelta) -> None:
        self._repo = repo
        self._agg = aggregator
        self._deadline = deadline

    def find_overdue_breaking(self, now: Optional[datetime] = None) -> List[ChangeEventView]:
        now = now or datetime.now(timezone.utc)
        cutoff = now - self._deadline
        rows = self._repo.list(severity="breaking", ack_status=ACK_PENDING, limit=100_000)
        return [e for e in rows if e.detected_at <= cutoff]

    async def escalate(self, sender) -> NotificationOutcome:
        over = self.find_overdue_breaking()
        if not over:
            return NotificationOutcome()
        graded = [
            GradedChange(
                change_type=e.change_type, fqn=e.entity_fqn or "",
                level=SEVERITY_TO_LEVEL.get(e.severity, "P3"),
                datasource_id=e.datasource_id or 0,
            )
            for e in over
        ]
        return await self._agg.dispatch(graded, sender)
