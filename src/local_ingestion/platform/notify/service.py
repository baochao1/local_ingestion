"""Subscription management + change-notification aggregation (MOD-06 / T-203).

The aggregator turns a list of graded changes (from T-202) into per-subscriber
digests:

* **scope match** — global / by datasource id / by fqn prefix (schema or table);
* **severity filter** — only changes at or above the subscription's ``min_severity``;
* **cooldown dedup** — the same object+change is not re-notified within the cooldown
  window (modelled per subscription in ``notification_log``);
* **mute** — a disabled subscription is skipped entirely (FR-7.7);
* **multi-channel** — the actual delivery is delegated to the injected ``Sender``
  (an adapter over ``integrations.notifications.NotificationService`` by default).
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import List, Optional, Protocol

from .models import (
    AggregatedNotification,
    ChangeDetail,
    NotificationOutcome,
    SubscriptionSpec,
    SubscriptionView,
    severity_rank,
)
from .repository import NotificationLogStore, SubscriptionRepository
from ..versioning.models import GradedChange


def _change_key(c: GradedChange) -> str:
    return f"{c.datasource_id}|{c.fqn}|{c.change_type}|{c.column or ''}"


def _hash(key: str) -> int:
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % (2 ** 63)


def _fqn_under_scope(change_fqn: str, scope_fqn: str) -> bool:
    """True when change_fqn lives under the (dot-separated) scope prefix.

    Segment-aware so ``db.sales.orders`` does NOT match ``db.sales.orders_v2``,
    while it does match ``db.sales.orders`` and its columns.
    """
    cs = change_fqn.split(".")
    ss = scope_fqn.split(".")
    if len(cs) < len(ss):
        return False
    return cs[: len(ss)] == ss


class Sender(Protocol):
    async def send(self, title: str, message: str, level: str, context: dict) -> bool: ...


class SubscriptionService:
    def __init__(self, repo: SubscriptionRepository) -> None:
        self._repo = repo

    def create(self, spec: SubscriptionSpec) -> SubscriptionView:
        return self._repo.create(spec)

    def list(self) -> List[SubscriptionView]:
        return self._repo.list()

    def get(self, sub_id: int) -> Optional[SubscriptionView]:
        return self._repo.get(sub_id)

    def delete(self, sub_id: int) -> bool:
        return self._repo.delete(sub_id)

    def mute(self, sub_id: int) -> None:
        self._repo.set_enabled(sub_id, False)

    def unmute(self, sub_id: int) -> None:
        self._repo.set_enabled(sub_id, True)


class NotificationAggregator:
    def __init__(
        self,
        repo: SubscriptionRepository,
        logs: NotificationLogStore,
        cooldown: timedelta = timedelta(hours=24),
        max_details: int = 20,
    ) -> None:
        self._repo = repo
        self._logs = logs
        self._cooldown = cooldown
        self._max_details = max_details

    # -------------------------------------------------------------- scope match
    def _matches(self, sub: SubscriptionView, c: GradedChange) -> bool:
        if severity_rank(c.level) > severity_rank(sub.min_severity):
            return False
        st = sub.scope_type
        if st == "global":
            return True
        if st == "datasource":
            return sub.datasource_id == c.datasource_id
        if st in ("schema", "table"):
            return bool(sub.scope_fqn) and _fqn_under_scope(c.fqn, sub.scope_fqn)
        return False

    # ----------------------------------------------------------------- aggregate
    def aggregate(self, changes: List[GradedChange]) -> List[AggregatedNotification]:
        out: List[AggregatedNotification] = []
        now = datetime.now()
        since = now - self._cooldown
        for sub in self._repo.list_enabled():
            matched = [c for c in changes if self._matches(sub, c)]
            if not matched:
                continue
            fresh: List[GradedChange] = []
            for c in matched:
                cid = _hash(_change_key(c))
                if self._logs.recent(sub.id, cid, since):
                    continue
                fresh.append(c)
            if not fresh:
                continue
            top = min(severity_rank(c.level) for c in fresh)
            top_level = next(k for k, v in {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.items() if v == top)
            details = [
                ChangeDetail(
                    fqn=c.fqn, change_type=c.change_type, level=c.level,
                    column=c.column, detail=c.detail, cid=_hash(_change_key(c)),
                )
                for c in fresh[: self._max_details]
            ]
            message = self._build_message(sub, fresh)
            out.append(AggregatedNotification(
                subscription_id=sub.id, subscriber=sub.subscriber, channel=sub.channel,
                severity_summary=top_level, message=message, details=details,
            ))
        return out

    @staticmethod
    def _build_message(sub: SubscriptionView, fresh: List[GradedChange]) -> str:
        lines = [f"数据源变更通知（订阅者 {sub.subscriber}）:"]
        for c in fresh[:20]:
            loc = c.fqn + (f".{c.column}" if c.column else "")
            lines.append(f"[{c.level}] {c.change_type} @ {loc}")
        if len(fresh) > 20:
            lines.append(f"... 其余 {len(fresh) - 20} 条变更请到平台查看")
        return "\n".join(lines)

    # ------------------------------------------------------------------- dispatch
    async def dispatch(self, changes: List[GradedChange], sender: Sender) -> NotificationOutcome:
        notifs = self.aggregate(changes)
        outcome = NotificationOutcome(notifications=len(notifs))
        for n in notifs:
            ok = await self._send_with_retry(n, sender, outcome)
            for d in n.details:
                self._logs.record(
                    n.subscription_id, d.cid, n.channel,
                    "sent" if ok else "failed",
                )
            if ok:
                outcome.sent += 1
            else:
                outcome.failed += 1
        return outcome

    async def _send_with_retry(self, n: AggregatedNotification, sender: Sender,
                               outcome: NotificationOutcome, max_retries: int = 3,
                               backoff: float = 0.01) -> bool:
        last_err: Optional[str] = None
        for _ in range(max_retries):
            try:
                ok = await sender.send(
                    title=f"变更通知 {n.severity_summary}",
                    message=n.message, level=n.severity_summary,
                    context={"subscriber": n.subscriber, "channel": n.channel},
                )
                if ok:
                    return True
                last_err = "sender returned False"
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
            await asyncio.sleep(backoff)
        outcome.errors.append(f"sub={n.subscription_id}: {last_err}")
        return False
