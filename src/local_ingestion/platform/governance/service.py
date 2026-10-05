"""Governance services: approvals + tickets (MOD-12).

* ``ApprovalService`` — submit/approve/reject approval requests; every decision is
  written through the shared ``AuditService`` (contract C10).
* ``TicketService`` — create/assign/transition tickets with a comment thread and
  SLA; supports auto-creation from a breaking change (the MOD-06 linkage).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .models import (
    COMMENT_TARGET_APPROVAL,
    COMMENT_TARGET_TICKET,
    TICKET_CLOSED,
    TICKET_IN_PROGRESS,
    TICKET_OPEN,
    TICKET_RESOLVED,
    TICKET_TRANSITIONS,
    ApprovalInput,
    ApprovalRequest,
    Comment,
    Ticket,
    TicketInput,
    VALID_APPROVAL_ACTIONS,
    VALID_APPROVAL_STATUS,
    VALID_TICKET_STATUS,
    VALID_TICKET_TYPES,
)
from .repository import GovernanceRepository, InMemoryGovernanceRepository
from ..orchestration.audit import AuditService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalNotFoundError(Exception):
    def __init__(self, approval_id: int) -> None:
        super().__init__(f"approval {approval_id} not found")
        self.approval_id = approval_id


class InvalidApprovalActionError(Exception):
    def __init__(self, action: str) -> None:
        super().__init__(f"invalid approval action: {action!r}")
        self.action = action


class ApprovalAlreadyDecidedError(Exception):
    def __init__(self, approval_id: int) -> None:
        super().__init__(f"approval {approval_id} already decided")
        self.approval_id = approval_id


class TicketNotFoundError(Exception):
    def __init__(self, ticket_id: int) -> None:
        super().__init__(f"ticket {ticket_id} not found")
        self.ticket_id = ticket_id


class InvalidTicketTransitionError(Exception):
    def __init__(self, frm: str, to: str) -> None:
        super().__init__(f"invalid ticket transition: {frm} -> {to}")
        self.frm = frm
        self.to = to


class InvalidTicketTypeError(Exception):
    def __init__(self, ticket_type: str) -> None:
        super().__init__(f"invalid ticket type: {ticket_type!r}")
        self.ticket_type = ticket_type


class ApprovalService:
    def __init__(self, repo: GovernanceRepository, audit: Optional[AuditService] = None) -> None:
        self._repo = repo
        self._audit = audit

    def create(self, inp: ApprovalInput, actor: Optional[str] = None,
               tenant_id: int = 0) -> ApprovalRequest:
        if inp.action_type not in VALID_APPROVAL_ACTIONS:
            raise InvalidApprovalActionError(inp.action_type)
        a = self._repo.add_approval(inp, tenant_id=tenant_id)
        if self._audit:
            self._audit.record(actor, "approval.create", entity_type="approval",
                               entity_fqn=str(a.id), detail={"resource_fqn": a.resource_fqn,
                                                            "action_type": a.action_type})
        return a

    def get(self, approval_id: int) -> ApprovalRequest:
        a = self._repo.get_approval(approval_id)
        if a is None:
            raise ApprovalNotFoundError(approval_id)
        return a

    def list(self, *, status=None, resource_type=None, approver=None,
             tenant_id: int = 0, limit: int = 50, offset: int = 0) -> list[ApprovalRequest]:
        return self._repo.list_approvals(status=status, resource_type=resource_type,
                                         approver=approver, tenant_id=tenant_id,
                                         limit=limit, offset=offset)

    def _decide(self, approval_id: int, status: str, actor: str, comment: Optional[str]) -> ApprovalRequest:
        if status not in VALID_APPROVAL_STATUS:
            raise InvalidApprovalActionError(status)
        a = self.get(approval_id)
        if a.status != "pending":
            raise ApprovalAlreadyDecidedError(approval_id)
        at = _utcnow()
        self._repo.set_approval_decision(approval_id, status, actor, comment, at)
        if self._audit:
            self._audit.record(actor, f"approval.{status}", entity_type="approval",
                               entity_fqn=str(approval_id),
                               detail={"comment": comment})
        return self.get(approval_id)

    def approve(self, approval_id: int, actor: str, comment: Optional[str] = None) -> ApprovalRequest:
        return self._decide(approval_id, "approved", actor, comment)

    def reject(self, approval_id: int, actor: str, comment: Optional[str] = None) -> ApprovalRequest:
        return self._decide(approval_id, "rejected", actor, comment)

    def comment(self, approval_id: int, author: str, body: str,
                tenant_id: int = 0) -> Comment:
        # existence check
        self.get(approval_id)
        c = self._repo.add_comment(COMMENT_TARGET_APPROVAL, approval_id, author, body, tenant_id=tenant_id)
        if self._audit:
            self._audit.record(author, "approval.comment", entity_type="approval",
                               entity_fqn=str(approval_id))
        return c

    def comments(self, approval_id: int) -> list[Comment]:
        return self._repo.list_comments(COMMENT_TARGET_APPROVAL, approval_id)


class TicketService:
    def __init__(self, repo: GovernanceRepository, audit: Optional[AuditService] = None) -> None:
        self._repo = repo
        self._audit = audit

    def create(self, inp: TicketInput, actor: Optional[str] = None,
               tenant_id: int = 0) -> Ticket:
        if inp.ticket_type not in VALID_TICKET_TYPES:
            raise InvalidTicketTypeError(inp.ticket_type)
        t = self._repo.add_ticket(inp, tenant_id=tenant_id)
        if self._audit:
            self._audit.record(actor, "ticket.create", entity_type="ticket",
                               entity_fqn=str(t.id),
                               detail={"ticket_type": t.ticket_type, "related_fqn": t.related_fqn})
        return t

    def get(self, ticket_id: int) -> Ticket:
        t = self._repo.get_ticket(ticket_id)
        if t is None:
            raise TicketNotFoundError(ticket_id)
        return t

    def list(self, *, status=None, ticket_type=None, assignee=None, reporter=None,
             related_fqn=None, tenant_id: int = 0, limit: int = 50, offset: int = 0) -> list[Ticket]:
        return self._repo.list_tickets(status=status, ticket_type=ticket_type, assignee=assignee,
                                       reporter=reporter, related_fqn=related_fqn,
                                       tenant_id=tenant_id, limit=limit, offset=offset)

    def assign(self, ticket_id: int, assignee: str, actor: Optional[str] = None) -> Ticket:
        t = self.get(ticket_id)
        self._repo.update_ticket(ticket_id, assignee=assignee, updated_at=_utcnow())
        if self._audit:
            self._audit.record(actor, "ticket.assign", entity_type="ticket",
                               entity_fqn=str(ticket_id), detail={"assignee": assignee})
        return self.get(ticket_id)

    def transition(self, ticket_id: int, to_status: str, actor: Optional[str] = None) -> Ticket:
        if to_status not in VALID_TICKET_STATUS:
            raise InvalidTicketTransitionError("?", to_status)
        t = self.get(ticket_id)
        if to_status not in TICKET_TRANSITIONS.get(t.status, []):
            raise InvalidTicketTransitionError(t.status, to_status)
        kw: dict = {"status": to_status, "updated_at": _utcnow()}
        if to_status == TICKET_RESOLVED:
            kw["resolved_at"] = _utcnow()
        if to_status == TICKET_CLOSED:
            kw["closed_at"] = _utcnow()
        self._repo.update_ticket(ticket_id, **kw)
        if self._audit:
            self._audit.record(actor, f"ticket.{to_status}", entity_type="ticket",
                               entity_fqn=str(ticket_id))
        return self.get(ticket_id)

    def comment(self, ticket_id: int, author: str, body: str,
                tenant_id: int = 0) -> Comment:
        self.get(ticket_id)
        c = self._repo.add_comment(COMMENT_TARGET_TICKET, ticket_id, author, body, tenant_id=tenant_id)
        if self._audit:
            self._audit.record(author, "ticket.comment", entity_type="ticket",
                               entity_fqn=str(ticket_id))
        return c

    def comments(self, ticket_id: int) -> list[Comment]:
        return self._repo.list_comments(COMMENT_TARGET_TICKET, ticket_id)

    # ---- MOD-06 linkage: auto-raise a ticket from a breaking change ----
    def create_from_change(self, change, action: str, actor: str = "system",
                           tenant_id: int = 0) -> Ticket:
        fqn = getattr(change, "entity_fqn", None) or f"change#{getattr(change, 'id', '?')}"
        title = f"[自动工单] 破坏性变更待处理: {fqn}"
        desc = (
            f"变更 #{getattr(change, 'id', '?')}（{getattr(change, 'change_type', '')}）"
            f"被判定为破坏性变更，责任人已 {action}。请跟进影响面与下游依赖。"
        )
        inp = TicketInput(
            title=title, description=desc, ticket_type="change_auto",
            priority="P0", reporter=actor, related_fqn=fqn, source="change_auto",
            sla_hours=24,
        )
        return self.create(inp, actor=actor, tenant_id=tenant_id)


def build_in_memory_governance_stack(audit=None):
    """Fully wired in-process governance stack (no database).

    Returns ``(approval_svc, ticket_svc, repo)``.
    """
    repo = InMemoryGovernanceRepository()
    approval = ApprovalService(repo, audit=audit)
    ticket = TicketService(repo, audit=audit)
    return approval, ticket, repo
