"""Unit + API tests for the change-confirmation closure (MOD-06 / T-204).

Covers: acknowledgement closure + audit, statistics rollup, escalation of overdue
breaking changes (reusing the T-203 aggregator), and the REST surface. No
Postgres required — everything runs against the in-memory stacks.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from local_ingestion.api.app import app
from local_ingestion.api.routers.changes import get_change_stack
from local_ingestion.platform.changes import (
    ChangeAlreadyClosedError,
    ChangeConfirmService,
    ChangeNotFoundError,
    InvalidAckActionError,
    build_in_memory_change_stack,
)
from local_ingestion.platform.changes.models import ChangeEventInput
from local_ingestion.platform.notify import SubscriptionSpec
from local_ingestion.platform.orchestration.audit import AuditService, InMemoryAuditSink


class FakeSender:
    def __init__(self):
        self.calls = []

    async def send(self, title, message, level, context):
        self.calls.append((title, context))
        return True


def _stack(audit=None):
    return build_in_memory_change_stack(audit=audit)


def _ev(repo, **kw):
    base = dict(entity_type="table", change_type="column_added", severity="descriptive",
                entity_fqn="db.s.t", datasource_id=1)
    base.update(kw)
    return repo.add(ChangeEventInput(**base))


# ----------------------------------------------------------- confirmation closure
def test_ack_closes_and_audits():
    sink = InMemoryAuditSink()
    confirm, stats, esc, repo, agg, sub = _stack(audit=AuditService(sink))
    ev = _ev(repo, severity="breaking")
    out = confirm.ack(ev.id, "alice", "acknowledged")
    assert out.ack_status == "closed"
    assert out.ack_action == "acknowledged" and out.ack_by == "alice"
    assert sink.entries and sink.entries[0].action == "change.ack"
    assert sink.entries[0].detail == {"action": "acknowledged"}


def test_reject_and_ignore_also_close():
    confirm, _, _, repo, _, _ = _stack()
    ev = _ev(repo)
    confirm.ack(ev.id, "bob", "rejected")
    assert repo.get(ev.id).ack_status == "closed"
    ev2 = _ev(repo)
    confirm.ack(ev2.id, "bob", "ignored")
    assert repo.get(ev2.id).ack_status == "closed"


def test_double_ack_raises():
    confirm, _, _, repo, _, _ = _stack()
    ev = _ev(repo)
    confirm.ack(ev.id, "a", "acknowledged")
    with pytest.raises(ChangeAlreadyClosedError):
        confirm.ack(ev.id, "a", "acknowledged")


def test_ack_missing_raises():
    confirm, _, _, _, _, _ = _stack()
    with pytest.raises(ChangeNotFoundError):
        confirm.ack(999, "a", "acknowledged")


def test_invalid_action_raises():
    confirm, _, _, repo, _, _ = _stack()
    ev = _ev(repo)
    with pytest.raises(InvalidAckActionError):
        confirm.ack(ev.id, "a", "bogus")


# --------------------------------------------------------------------- statistics
def test_statistics_rollup():
    confirm, stats, _, repo, _, _ = _stack()
    now = datetime.now()
    a = repo.add(ChangeEventInput(entity_type="table", change_type="c", severity="breaking", entity_fqn="db.s.a", datasource_id=1, detected_at=now))
    repo.add(ChangeEventInput(entity_type="table", change_type="c", severity="descriptive", entity_fqn="db.s.a", datasource_id=1, detected_at=now))  # same -> unstable
    repo.add(ChangeEventInput(entity_type="table", change_type="c", severity="structural", entity_fqn="db.s.b", datasource_id=2, detected_at=now))
    confirm.ack(a.id, "x", "acknowledged")

    s = stats.statistics(since=now - timedelta(hours=1), until=now + timedelta(hours=1))
    assert s.total == 3
    assert s.by_severity == {"breaking": 1, "descriptive": 1, "structural": 1}
    assert s.by_datasource == {"1": 2, "2": 1}
    assert abs(s.ack_rate - (1 / 3)) < 1e-2
    assert s.top_unstable[0][0] == "db.s.a" and s.top_unstable[0][1] == 2


# -------------------------------------------------------------------- escalation
async def test_escalate_overdue_breaking_via_aggregator():
    confirm, stats, esc, repo, agg, sub = _stack()
    sub.create(SubscriptionSpec(subscriber="oncall", scope_type="global", min_severity="P0", channel="email"))

    ev = _ev(repo, severity="breaking", entity_fqn="db.s.critical", detected_at=datetime.now() - timedelta(days=2))

    sender = FakeSender()
    outcome = await esc.escalate(sender)
    assert outcome.sent == 1
    assert sender.calls  # went through the T-203 aggregator

    # acknowledged breaking is no longer escalated
    confirm.ack(ev.id, "x", "acknowledged")
    assert (await esc.escalate(FakeSender())).sent == 0


async def test_escalate_ignores_non_breaking():
    _, _, esc, repo, agg, sub = _stack()
    sub.create(SubscriptionSpec(subscriber="oncall", scope_type="global", min_severity="P0", channel="email"))
    _ev(repo, severity="descriptive", entity_fqn="db.s.low", detected_at=datetime.now() - timedelta(days=2))
    assert (await esc.escalate(FakeSender())).sent == 0


# -------------------------------------------------------------------------- REST
def test_changes_rest_flow():
    client = TestClient(app)
    confirm, stats, esc, repo, agg, sub = get_change_stack()
    sub.create(SubscriptionSpec(subscriber="oncall", scope_type="global", min_severity="P0", channel="email"))
    ev = _ev(repo, severity="breaking", entity_fqn="db.s.x", detected_at=datetime.now() - timedelta(days=1))

    # list
    r = client.get("/api/v1/changes")
    assert r.status_code == 200 and r.json()["count"] == 1
    # get
    r = client.get(f"/api/v1/changes/{ev.id}")
    assert r.status_code == 200 and r.json()["id"] == ev.id
    # history
    r = client.get(f"/api/v1/changes/entities/table/db.s.x/history")
    assert r.status_code == 200 and r.json()["count"] == 1
    # ack
    r = client.post(f"/api/v1/changes/{ev.id}/ack", json={"actor": "alice", "action": "acknowledged"})
    assert r.status_code == 200 and r.json()["ack_status"] == "closed"
    # double ack -> 409
    r = client.post(f"/api/v1/changes/{ev.id}/ack", json={"actor": "alice", "action": "acknowledged"})
    assert r.status_code == 409
    # invalid action -> 422
    ev2 = _ev(repo)
    r = client.post(f"/api/v1/changes/{ev2.id}/ack", json={"actor": "a", "action": "nope"})
    assert r.status_code == 422
    # statistics
    r = client.get("/api/v1/changes/statistics")
    assert r.status_code == 200 and r.json()["total"] >= 2
