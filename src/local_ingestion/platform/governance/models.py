"""Governance process domain models (MOD-12 / collaborative workflow).

Defines the two collaborative capabilities that the original scope had
explicitly excluded (见 ``01-product-requirements.md`` §5.1「审批流」「协作能力」):

* **Approval (审批流)** — a responsible person approves/rejects a governed
  action (asset go-live, classification result, sensitive-tag change …).
* **Ticket (工单)** — a trackable work item (data issue, access request,
  auto-raised breaking-change follow-up) with assignee / status / SLA and a
  comment thread.

Both reuse the shared ``AuditService`` (contract C10) so every decision and
state transition is auditable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
VALID_APPROVAL_STATUS = frozenset({APPROVAL_PENDING, APPROVAL_APPROVED, APPROVAL_REJECTED})

APPROVAL_ACTION_PUBLISH = "publish"          # 资产上线/发布
APPROVAL_ACTION_CLASSIFY = "classify"        # 分类分级结果审批
APPROVAL_ACTION_SENSITIVE = "sensitive_tag"  # 敏感标注审批
APPROVAL_ACTION_DELETE = "delete"            # 删除资产审批
VALID_APPROVAL_ACTIONS = frozenset(
    {APPROVAL_ACTION_PUBLISH, APPROVAL_ACTION_CLASSIFY,
     APPROVAL_ACTION_SENSITIVE, APPROVAL_ACTION_DELETE}
)


@dataclass
class ApprovalInput:
    resource_type: str            # asset | classification | sensitive_tag | datasource
    resource_fqn: str
    action_type: str             # see VALID_APPROVAL_ACTIONS
    title: str
    requested_by: str
    approver: Optional[str] = None
    priority: str = "P2"
    reason: Optional[str] = None


@dataclass
class ApprovalRequest:
    id: int
    tenant_id: int
    resource_type: str
    resource_fqn: str
    action_type: str
    title: str
    requested_by: str
    approver: Optional[str]
    status: str
    priority: str
    reason: Optional[str]
    created_at: datetime
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    decided_comment: Optional[str] = None


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
TICKET_OPEN = "open"
TICKET_IN_PROGRESS = "in_progress"
TICKET_RESOLVED = "resolved"
TICKET_CLOSED = "closed"
VALID_TICKET_STATUS = frozenset(
    {TICKET_OPEN, TICKET_IN_PROGRESS, TICKET_RESOLVED, TICKET_CLOSED}
)

# Allowed forward/backward transitions (closed is terminal unless reopened).
# FR-17.5 mandates the strict chain open -> in_progress -> resolved -> closed,
# plus closed -> in_progress (reopen). Intermediate states may not be skipped:
# jumping open -> resolved would claim work that never started, and skipping
# in_progress -> resolved would bypass handling. Only `resolved` may also go
# back to in_progress (work turned out to be incomplete).
TICKET_TRANSITIONS: Dict[str, List[str]] = {
    TICKET_OPEN: [TICKET_IN_PROGRESS],
    TICKET_IN_PROGRESS: [TICKET_RESOLVED],
    TICKET_RESOLVED: [TICKET_IN_PROGRESS, TICKET_CLOSED],
    TICKET_CLOSED: [TICKET_IN_PROGRESS],  # reopen
}

TICKET_TYPE_DATA_ISSUE = "data_issue"
TICKET_TYPE_ACCESS = "access_request"
TICKET_TYPE_CHANGE_AUTO = "change_auto"
TICKET_TYPE_OTHER = "other"
VALID_TICKET_TYPES = frozenset(
    {TICKET_TYPE_DATA_ISSUE, TICKET_TYPE_ACCESS,
     TICKET_TYPE_CHANGE_AUTO, TICKET_TYPE_OTHER}
)


@dataclass
class TicketInput:
    title: str
    description: Optional[str] = None
    ticket_type: str = TICKET_TYPE_DATA_ISSUE
    priority: str = "P2"
    reporter: str = "system"
    assignee: Optional[str] = None
    related_fqn: Optional[str] = None
    source: str = "manual"           # manual | change_auto
    sla_hours: Optional[int] = None


@dataclass
class Ticket:
    id: int
    tenant_id: int
    title: str
    description: Optional[str]
    ticket_type: str
    priority: str
    status: str
    reporter: str
    assignee: Optional[str]
    related_fqn: Optional[str]
    source: str
    sla_due_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Comments (shared by approvals and tickets)
# ---------------------------------------------------------------------------
COMMENT_TARGET_APPROVAL = "approval"
COMMENT_TARGET_TICKET = "ticket"


@dataclass
class Comment:
    id: int
    tenant_id: int
    target_type: str     # approval | ticket
    target_id: int
    author: str
    body: str
    created_at: datetime
