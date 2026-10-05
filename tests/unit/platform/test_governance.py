"""Unit + API tests for the governance collaboration module (MOD-12 / T-new).

Covers: approval workflow (submit/approve/reject + audit + comments) and the
ticket state machine (create/assign/transition/comment), plus the MOD-06 linkage
that auto-raises a ticket for breaking changes. No Postgres required — runs
against the in-memory stacks; REST surface validated via TestClient.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from local_ingestion.api.app import app
from local_ingestion.api.routers.governance import get_governance_stack
from local_ingestion.platform.governance import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    ApprovalService,
    InvalidApprovalActionError,
    InvalidTicketTransitionError,
    InvalidTicketTypeError,
    TicketNotFoundError,
    build_in_memory_governance_stack,
)
from local_ingestion.platform.governance.models import ApprovalInput, TicketInput
from local_ingestion.platform.orchestration.audit import AuditService, InMemoryAuditSink


def _stack(audit=None):
    return build_in_memory_governance_stack(audit=audit)


# --------------------------------------------------------------- approval flow
def test_approval_submit_and_decide():
    sink = InMemoryAuditSink()
    approval, _ticket, _repo = _stack(audit=AuditService(sink))
    a = approval.create(
        ApprovalInput(resource_type="asset", resource_fqn="db.s.t",
                      action_type="publish", title="资产发布", requested_by="alice"),
        actor="alice")
    assert a.status == "pending"
    decided = approval.approve(a.id, "bob", "looks good")
    assert decided.status == "approved" and decided.decided_by == "bob"
    assert sink.entries and any(e.action == "approval.approved" for e in sink.entries)


def test_approval_reject_and_signal():
    approval, _t, _r = _stack()
    a = approval.create(
        ApprovalInput(resource_type="sensitive_tag", resource_fqn="db.s.t.col",
                      action_type="sensitive_tag", title="敏感标注", requested_by="alice"),
        actor="alice")
    out = approval.reject(a.id, "bob", "not enough context")
    assert out.status == "rejected"


def test_double_decision_raises():
    approval, _t, _r = _stack()
    a = approval.create(
        ApprovalInput(resource_type="asset", resource_fqn="db.s.t",
                      action_type="delete", title="删除", requested_by="alice"),
        actor="alice")
    approval.approve(a.id, "bob")
    with pytest.raises(ApprovalAlreadyDecidedError):
        approval.approve(a.id, "bob")


def test_approval_invalid_action_and_missing():
    approval, _t, _r = _stack()
    with pytest.raises(InvalidApprovalActionError):
        approval.create(
            ApprovalInput(resource_type="asset", resource_fqn="db.s.t",
                          action_type="bogus", title="x", requested_by="alice"))
    with pytest.raises(ApprovalNotFoundError):
        approval.approve(9999, "bob")


def test_approval_filter_and_comment():
    approval, _t, _r = _stack()
    a = approval.create(
        ApprovalInput(resource_type="asset", resource_fqn="db.s.t",
                      action_type="publish", title="x", requested_by="alice"),
        actor="alice")
    approval.comment(a.id, "bob", "please add owner")
    listed = approval.list(status="pending")
    assert any(x.id == a.id for x in listed)
    comments = approval.comments(a.id)
    assert len(comments) == 1 and comments[0].body == "please add owner"


# ----------------------------------------------------------------- ticket flow
def test_ticket_state_machine():
    _a, ticket, _r = _stack()
    t = ticket.create(
        TicketInput(title="数据质量异常", ticket_type="data_issue",
                    reporter="carol", priority="P1"),
        actor="carol")
    assert t.status == "open"
    ticket.assign(t.id, "dave")
    assert ticket.get(t.id).assignee == "dave"
    assert ticket.transition(t.id, "in_progress").status == "in_progress"
    assert ticket.transition(t.id, "resolved").status == "resolved"
    assert ticket.transition(t.id, "closed").status == "closed"
    # closed -> reopen only to in_progress
    assert ticket.transition(t.id, "in_progress").status == "in_progress"


def test_ticket_invalid_transition_and_type():
    _a, ticket, _r = _stack()
    t = ticket.create(TicketInput(title="x", reporter="carol"), actor="carol")
    with pytest.raises(InvalidTicketTransitionError):
        ticket.transition(t.id, "resolved")  # open cannot jump to resolved
    with pytest.raises(InvalidTicketTypeError):
        ticket.create(TicketInput(title="x", ticket_type="bogus", reporter="carol"))


def test_ticket_missing_and_comment():
    _a, ticket, _r = _stack()
    with pytest.raises(TicketNotFoundError):
        ticket.get(9999)
    t = ticket.create(TicketInput(title="x", reporter="carol"), actor="carol")
    ticket.comment(t.id, "dave", "fixing now")
    assert len(ticket.comments(t.id)) == 1


# --------------------------------------------------- MOD-06 linkage (auto ticket)
def test_auto_ticket_from_breaking_change():
    approval, ticket, _r = _stack()
    class FakeChange:
        id = 42
        entity_fqn = "db.s.critical"
        change_type = "column_removed"
        severity = "breaking"
        ack_by = "bob"

    ticket.create_from_change(FakeChange(), "acknowledged", actor="bob")
    auto = ticket.list(ticket_type="change_auto")
    assert len(auto) == 1
    assert auto[0].related_fqn == "db.s.critical"
    assert auto[0].priority == "P0"


# ------------------------------------------------------------------------- REST
def test_governance_rest_flow():
    client = TestClient(app)
    approval, ticket, _r = get_governance_stack()

    # create approval
    r = client.post("/api/v1/governance/approvals", json={
        "resource_type": "asset", "resource_fqn": "db.s.t", "action_type": "publish",
        "title": "发布资产", "requested_by": "alice", "actor": "alice"})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    # approve
    r = client.post(f"/api/v1/governance/approvals/{aid}/approve",
                    json={"actor": "bob", "comment": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    # double approve -> 409
    r = client.post(f"/api/v1/governance/approvals/{aid}/approve", json={"actor": "bob"})
    assert r.status_code == 409
    # list
    r = client.get("/api/v1/governance/approvals")
    assert r.status_code == 200 and r.json()["count"] >= 1

    # create ticket
    r = client.post("/api/v1/governance/tickets", json={
        "title": "数据问题", "ticket_type": "data_issue", "reporter": "carol", "priority": "P1"})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    client.post(f"/api/v1/governance/tickets/{tid}/assign", json={"assignee": "dave"})
    r = client.post(f"/api/v1/governance/tickets/{tid}/transition", json={"to_status": "in_progress"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    # invalid transition -> 422
    r = client.post(f"/api/v1/governance/tickets/{tid}/transition", json={"to_status": "closed"})
    assert r.status_code == 422
    # comment
    r = client.post(f"/api/v1/governance/tickets/{tid}/comments",
                    json={"author": "dave", "body": "fixing"})
    assert r.status_code == 201
    r = client.get(f"/api/v1/governance/tickets/{tid}/comments")
    assert r.json()["count"] == 1
