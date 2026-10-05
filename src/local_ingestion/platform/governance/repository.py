"""Governance repositories (MOD-12).

Two implementations share the interface: an in-memory one for unit tests / the
MVP (the API stack defaults to this so it runs without Postgres), plus a
SQLAlchemy one backed by the ``approval_request`` / ``governance_ticket`` /
``governance_comment`` tables (DDL + ORM landed alongside MOD-12).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Protocol

from .models import (
    APPROVAL_PENDING,
    TICKET_CLOSED,
    TICKET_OPEN,
    TICKET_RESOLVED,
    ApprovalInput,
    ApprovalRequest,
    Comment,
    Ticket,
    TicketInput,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GovernanceRepository(Protocol):
    # approvals
    def add_approval(self, inp: ApprovalInput, tenant_id: int = 0) -> ApprovalRequest: ...
    def get_approval(self, approval_id: int) -> Optional[ApprovalRequest]: ...
    def list_approvals(self, *, status=None, resource_type=None, approver=None,
                       tenant_id: int = 0, limit: int = 50, offset: int = 0) -> List[ApprovalRequest]: ...
    def set_approval_decision(self, approval_id: int, status: str, decided_by: str,
                              comment: Optional[str], at: datetime) -> None: ...

    # tickets
    def add_ticket(self, inp: TicketInput, tenant_id: int = 0) -> Ticket: ...
    def get_ticket(self, ticket_id: int) -> Optional[Ticket]: ...
    def list_tickets(self, *, status=None, ticket_type=None, assignee=None,
                     reporter=None, related_fqn=None, tenant_id: int = 0,
                     limit: int = 50, offset: int = 0) -> List[Ticket]: ...
    def update_ticket(self, ticket_id: int, *, status: Optional[str] = None,
                      assignee: Optional[str] = None, resolved_at: Optional[datetime] = None,
                      closed_at: Optional[datetime] = None, updated_at: datetime = None) -> None: ...

    # comments
    def add_comment(self, target_type: str, target_id: int, author: str, body: str,
                    tenant_id: int = 0) -> Comment: ...
    def list_comments(self, target_type: str, target_id: int) -> List[Comment]: ...


class InMemoryGovernanceRepository:
    def __init__(self) -> None:
        self._approvals: List[ApprovalRequest] = []
        self._tickets: List[Ticket] = []
        self._comments: List[Comment] = []
        self._seq_a = 1
        self._seq_t = 1
        self._seq_c = 1

    # ---- approvals ----
    def add_approval(self, inp: ApprovalInput, tenant_id: int = 0) -> ApprovalRequest:
        a = ApprovalRequest(
            id=self._seq_a, tenant_id=tenant_id, resource_type=inp.resource_type,
            resource_fqn=inp.resource_fqn, action_type=inp.action_type, title=inp.title,
            requested_by=inp.requested_by, approver=inp.approver, status=APPROVAL_PENDING,
            priority=inp.priority, reason=inp.reason, created_at=_now(),
        )
        self._seq_a += 1
        self._approvals.append(a)
        return a

    def get_approval(self, approval_id: int) -> Optional[ApprovalRequest]:
        return next((a for a in self._approvals if a.id == approval_id), None)

    def list_approvals(self, *, status=None, resource_type=None, approver=None,
                       tenant_id: int = 0, limit: int = 50, offset: int = 0) -> List[ApprovalRequest]:
        f = [a for a in self._approvals if a.tenant_id == tenant_id]
        if status:
            f = [a for a in f if a.status == status]
        if resource_type:
            f = [a for a in f if a.resource_type == resource_type]
        if approver:
            f = [a for a in f if a.approver == approver]
        f.sort(key=lambda x: x.created_at, reverse=True)
        return f[offset:offset + limit]

    def set_approval_decision(self, approval_id: int, status: str, decided_by: str,
                              comment: Optional[str], at: datetime) -> None:
        a = self.get_approval(approval_id)
        if a:
            a.status = status
            a.decided_by = decided_by
            a.decided_comment = comment
            a.decided_at = at

    # ---- tickets ----
    def add_ticket(self, inp: TicketInput, tenant_id: int = 0) -> Ticket:
        now = _now()
        sla = now + timedelta(hours=inp.sla_hours) if inp.sla_hours else None
        t = Ticket(
            id=self._seq_t, tenant_id=tenant_id, title=inp.title, description=inp.description,
            ticket_type=inp.ticket_type, priority=inp.priority, status=TICKET_OPEN,
            reporter=inp.reporter, assignee=inp.assignee, related_fqn=inp.related_fqn,
            source=inp.source, sla_due_at=sla, created_at=now, updated_at=now,
        )
        self._seq_t += 1
        self._tickets.append(t)
        return t

    def get_ticket(self, ticket_id: int) -> Optional[Ticket]:
        return next((t for t in self._tickets if t.id == ticket_id), None)

    def list_tickets(self, *, status=None, ticket_type=None, assignee=None,
                     reporter=None, related_fqn=None, tenant_id: int = 0,
                     limit: int = 50, offset: int = 0) -> List[Ticket]:
        f = [t for t in self._tickets if t.tenant_id == tenant_id]
        if status:
            f = [t for t in f if t.status == status]
        if ticket_type:
            f = [t for t in f if t.ticket_type == ticket_type]
        if assignee:
            f = [t for t in f if t.assignee == assignee]
        if reporter:
            f = [t for t in f if t.reporter == reporter]
        if related_fqn:
            f = [t for t in f if t.related_fqn == related_fqn]
        f.sort(key=lambda x: x.created_at, reverse=True)
        return f[offset:offset + limit]

    def update_ticket(self, ticket_id: int, *, status: Optional[str] = None,
                      assignee: Optional[str] = None, resolved_at: Optional[datetime] = None,
                      closed_at: Optional[datetime] = None, updated_at: datetime = None) -> None:
        t = self.get_ticket(ticket_id)
        if t:
            if status is not None:
                t.status = status
            if assignee is not None:
                t.assignee = assignee
            if resolved_at is not None:
                t.resolved_at = resolved_at
            if closed_at is not None:
                t.closed_at = closed_at
            t.updated_at = updated_at or _now()

    # ---- comments ----
    def add_comment(self, target_type: str, target_id: int, author: str, body: str,
                    tenant_id: int = 0) -> Comment:
        c = Comment(id=self._seq_c, tenant_id=tenant_id, target_type=target_type,
                    target_id=target_id, author=author, body=body, created_at=_now())
        self._seq_c += 1
        self._comments.append(c)
        return c

    def list_comments(self, target_type: str, target_id: int) -> List[Comment]:
        f = [c for c in self._comments if c.target_type == target_type and c.target_id == target_id]
        f.sort(key=lambda x: x.created_at)
        return f


class SqlGovernanceRepository:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    # ---- approvals ----
    def add_approval(self, inp: ApprovalInput, tenant_id: int = 0) -> ApprovalRequest:
        from ..storage.models_ops import ApprovalRequest as ORMApproval

        with self._sf() as s:
            m = ORMApproval(
                tenant_id=tenant_id, resource_type=inp.resource_type, resource_fqn=inp.resource_fqn,
                action_type=inp.action_type, title=inp.title, requested_by=inp.requested_by,
                approver=inp.approver, priority=inp.priority, reason=inp.reason,
            )
            s.add(m)
            s.commit()
            s.refresh(m)
            return self._approval_view(m)

    def get_approval(self, approval_id: int) -> Optional[ApprovalRequest]:
        from ..storage.models_ops import ApprovalRequest as ORMApproval

        with self._sf() as s:
            m = s.query(ORMApproval).filter(ORMApproval.id == approval_id).first()
            return self._approval_view(m) if m else None

    def list_approvals(self, *, status=None, resource_type=None, approver=None,
                       tenant_id: int = 0, limit: int = 50, offset: int = 0) -> List[ApprovalRequest]:
        from ..storage.models_ops import ApprovalRequest as ORMApproval

        with self._sf() as s:
            q = s.query(ORMApproval).filter(ORMApproval.tenant_id == tenant_id)
            if status:
                q = q.filter(ORMApproval.status == status)
            if resource_type:
                q = q.filter(ORMApproval.resource_type == resource_type)
            if approver:
                q = q.filter(ORMApproval.approver == approver)
            rows = q.order_by(ORMApproval.created_at.desc()).offset(offset).limit(limit).all()
            return [self._approval_view(m) for m in rows]

    def set_approval_decision(self, approval_id: int, status: str, decided_by: str,
                              comment: Optional[str], at: datetime) -> None:
        from ..storage.models_ops import ApprovalRequest as ORMApproval

        with self._sf() as s:
            m = s.query(ORMApproval).filter(ORMApproval.id == approval_id).first()
            if m:
                m.status = status
                m.decided_by = decided_by
                m.decided_comment = comment
                m.decided_at = at
                s.commit()

    # ---- tickets ----
    def add_ticket(self, inp: TicketInput, tenant_id: int = 0) -> Ticket:
        from ..storage.models_ops import GovernanceTicket

        with self._sf() as s:
            sla = None
            if inp.sla_hours:
                from datetime import timedelta
                sla = _now() + timedelta(hours=inp.sla_hours)
            m = GovernanceTicket(
                tenant_id=tenant_id, title=inp.title, description=inp.description,
                ticket_type=inp.ticket_type, priority=inp.priority, reporter=inp.reporter,
                assignee=inp.assignee, related_fqn=inp.related_fqn, source=inp.source,
                sla_due_at=sla,
            )
            s.add(m)
            s.commit()
            s.refresh(m)
            return self._ticket_view(m)

    def get_ticket(self, ticket_id: int) -> Optional[Ticket]:
        from ..storage.models_ops import GovernanceTicket

        with self._sf() as s:
            m = s.query(GovernanceTicket).filter(GovernanceTicket.id == ticket_id).first()
            return self._ticket_view(m) if m else None

    def list_tickets(self, *, status=None, ticket_type=None, assignee=None,
                     reporter=None, related_fqn=None, tenant_id: int = 0,
                     limit: int = 50, offset: int = 0) -> List[Ticket]:
        from ..storage.models_ops import GovernanceTicket

        with self._sf() as s:
            q = s.query(GovernanceTicket).filter(GovernanceTicket.tenant_id == tenant_id)
            if status:
                q = q.filter(GovernanceTicket.status == status)
            if ticket_type:
                q = q.filter(GovernanceTicket.ticket_type == ticket_type)
            if assignee:
                q = q.filter(GovernanceTicket.assignee == assignee)
            if reporter:
                q = q.filter(GovernanceTicket.reporter == reporter)
            if related_fqn:
                q = q.filter(GovernanceTicket.related_fqn == related_fqn)
            rows = q.order_by(GovernanceTicket.created_at.desc()).offset(offset).limit(limit).all()
            return [self._ticket_view(m) for m in rows]

    def update_ticket(self, ticket_id: int, *, status: Optional[str] = None,
                      assignee: Optional[str] = None, resolved_at: Optional[datetime] = None,
                      closed_at: Optional[datetime] = None, updated_at: datetime = None) -> None:
        from ..storage.models_ops import GovernanceTicket

        with self._sf() as s:
            m = s.query(GovernanceTicket).filter(GovernanceTicket.id == ticket_id).first()
            if m:
                if status is not None:
                    m.status = status
                if assignee is not None:
                    m.assignee = assignee
                if resolved_at is not None:
                    m.resolved_at = resolved_at
                if closed_at is not None:
                    m.closed_at = closed_at
                m.updated_at = updated_at or _now()
                s.commit()

    # ---- comments ----
    def add_comment(self, target_type: str, target_id: int, author: str, body: str,
                    tenant_id: int = 0) -> Comment:
        from ..storage.models_ops import GovernanceComment

        with self._sf() as s:
            m = GovernanceComment(tenant_id=tenant_id, target_type=target_type,
                                  target_id=target_id, author=author, body=body)
            s.add(m)
            s.commit()
            s.refresh(m)
            return Comment(id=m.id, tenant_id=m.tenant_id, target_type=m.target_type,
                           target_id=m.target_id, author=m.author, body=m.body,
                           created_at=m.created_at)

    def list_comments(self, target_type: str, target_id: int) -> List[Comment]:
        from ..storage.models_ops import GovernanceComment

        with self._sf() as s:
            rows = (
                s.query(GovernanceComment)
                .filter(GovernanceComment.target_type == target_type,
                        GovernanceComment.target_id == target_id)
                .order_by(GovernanceComment.created_at.asc()).all()
            )
            return [Comment(id=m.id, tenant_id=m.tenant_id, target_type=m.target_type,
                           target_id=m.target_id, author=m.author, body=m.body,
                           created_at=m.created_at) for m in rows]

    # ---- views ----
    @staticmethod
    def _approval_view(m) -> ApprovalRequest:
        return ApprovalRequest(
            id=m.id, tenant_id=m.tenant_id, resource_type=m.resource_type,
            resource_fqn=m.resource_fqn, action_type=m.action_type, title=m.title,
            requested_by=m.requested_by, approver=m.approver, status=m.status,
            priority=m.priority, reason=m.reason, created_at=m.created_at,
            decided_at=m.decided_at, decided_by=m.decided_by, decided_comment=m.decided_comment,
        )

    @staticmethod
    def _ticket_view(m) -> Ticket:
        return Ticket(
            id=m.id, tenant_id=m.tenant_id, title=m.title, description=m.description,
            ticket_type=m.ticket_type, priority=m.priority, status=m.status,
            reporter=m.reporter, assignee=m.assignee, related_fqn=m.related_fqn,
            source=m.source, sla_due_at=m.sla_due_at, created_at=m.created_at,
            updated_at=m.updated_at, resolved_at=m.resolved_at, closed_at=m.closed_at,
        )
