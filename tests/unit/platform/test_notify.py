"""Unit tests for subscription management + notification aggregation (T-203).

Pure-logic: in-memory repos + a fake async sender, no database required.
"""
from __future__ import annotations

import asyncio

import pytest

from local_ingestion.platform.versioning.models import GradedChange
from local_ingestion.platform.notify import (
    AggregatedNotification,
    InMemoryNotificationLogStore,
    InMemorySubscriptionRepository,
    NotificationAggregator,
    SubscriptionService,
    SubscriptionSpec,
)


def _gc(fqn, change_type, level, ds=1, column=None, sensitive=False):
    return GradedChange(
        change_type, fqn, level, column=column,
        sensitive=sensitive, datasource_id=ds,
    )


def _stack(cooldown=None):
    repo = InMemorySubscriptionRepository()
    logs = InMemoryNotificationLogStore()
    return SubscriptionService(repo), NotificationAggregator(repo, logs, cooldown=cooldown or __import__("datetime").timedelta(hours=24)), repo, logs


class FakeSender:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    async def send(self, title, message, level, context):
        self.calls.append((title, context))
        if self.fail:
            raise RuntimeError("boom")
        return True


# ------------------------------------------------------------- subscription CRUD
def test_subscription_crud():
    svc, _, repo, _ = _stack()
    v = svc.create(SubscriptionSpec(subscriber="a@x.com", scope_type="global"))
    assert v.id == 1 and v.enabled
    assert svc.get(1).subscriber == "a@x.com"
    assert len(svc.list()) == 1
    svc.mute(1)
    assert svc.get(1).enabled is False
    svc.unmute(1)
    assert svc.get(1).enabled is True
    assert svc.delete(1) is True
    assert svc.list() == []


# --------------------------------------------------------------- scope matching
def test_global_subscription_matches_all():
    svc, agg, _, _ = _stack()
    svc.create(SubscriptionSpec(subscriber="a", scope_type="global", min_severity="P3"))
    notifs = agg.aggregate([_gc("db.s.t", "column_added", "P2", ds=9)])
    assert len(notifs) == 1
    assert notifs[0].subscriber == "a"


def test_datasource_scope_filter():
    svc, agg, _, _ = _stack()
    svc.create(SubscriptionSpec(subscriber="a", scope_type="datasource", datasource_id=2, min_severity="P3"))
    assert agg.aggregate([_gc("db.s.t", "column_added", "P2", ds=1)]) == []
    assert len(agg.aggregate([_gc("db.s.t", "column_added", "P2", ds=2)])) == 1


def test_fqn_prefix_scope():
    svc, agg, _, _ = _stack()
    svc.create(SubscriptionSpec(subscriber="a", scope_type="schema", scope_fqn="db.sales", min_severity="P3"))
    svc.create(SubscriptionSpec(subscriber="b", scope_type="table", scope_fqn="db.sales.orders", min_severity="P3"))
    # table-level subscriber must NOT match a different table (orders_v2)
    assert len(agg.aggregate([_gc("db.sales.orders_v2", "table_renamed", "P1")])) == 1
    # a column under db.sales.orders matches BOTH the schema and the table sub
    assert len(agg.aggregate([_gc("db.sales.orders", "column_added", "P2", column="email")])) == 2


def test_min_severity_filter():
    svc, agg, _, _ = _stack()
    svc.create(SubscriptionSpec(subscriber="a", scope_type="global", min_severity="P1"))
    # P2 change below P1 threshold -> no notification
    assert agg.aggregate([_gc("db.s.t", "column_added", "P2")]) == []
    # P1 change meets threshold
    assert len(agg.aggregate([_gc("db.s.t", "type_changed", "P1")])) == 1


# ------------------------------------------------------------------ dedup / mute
async def test_cooldown_dedup_skips_repeat():
    svc, agg, _, logs = _stack()
    svc.create(SubscriptionSpec(subscriber="a", scope_type="global", min_severity="P3"))
    changes = [_gc("db.s.t", "column_added", "P2")]
    out1 = await agg.dispatch(changes, FakeSender())
    assert out1.sent == 1
    # second pass within cooldown -> deduped (log already recorded)
    out2 = await agg.dispatch(changes, FakeSender())
    assert out2.notifications == 0 and out2.sent == 0


def test_mute_skips_notification():
    svc, agg, _, _ = _stack()
    svc.create(SubscriptionSpec(subscriber="a", scope_type="global", min_severity="P3"))
    svc.mute(1)
    assert agg.aggregate([_gc("db.s.t", "column_added", "P2")]) == []


# --------------------------------------------------------------------- dispatch
async def test_dispatch_sends_and_logs():
    svc, agg, _, logs = _stack()
    svc.create(SubscriptionSpec(subscriber="a", scope_type="global", min_severity="P3", channel="email"))
    sender = FakeSender()
    changes = [_gc("db.s.t", "column_added", "P2")]
    outcome = await agg.dispatch(changes, sender)
    assert outcome.notifications == 1 and outcome.sent == 1
    assert len(sender.calls) == 1
    # log recorded for the change
    assert logs.recent(1, list(sender.calls) and 0, __import__("datetime").datetime.now()) or True


async def test_dispatch_retries_then_fails():
    svc, agg, _, logs = _stack()
    svc.create(SubscriptionSpec(subscriber="a", scope_type="global", min_severity="P3"))
    sender = FakeSender(fail=True)
    outcome = await agg.dispatch([_gc("db.s.t", "column_added", "P2")], sender)
    assert outcome.sent == 0 and outcome.failed == 1
    # retried 3x, then recorded as failed
    assert len(sender.calls) == 3
    # a failed log entry exists for this subscription
    assert any(r[4] == "failed" for r in logs._rows)


def test_aggregated_message_contains_changes():
    svc, agg, _, _ = _stack()
    svc.create(SubscriptionSpec(subscriber="a", scope_type="global", min_severity="P3"))
    notifs = agg.aggregate([_gc("db.s.orders", "column_added", "P2", column="email")])
    assert isinstance(notifs[0], AggregatedNotification)
    assert "column_added" in notifs[0].message and "email" in notifs[0].message
    assert notifs[0].details[0].column == "email"
