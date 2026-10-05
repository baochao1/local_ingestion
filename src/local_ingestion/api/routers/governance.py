"""REST API for governance collaboration: approvals + tickets (MOD-12).

持久化到 PostgreSQL（``approval_request`` / ``governance_ticket`` /
``governance_comment``），审计写 ``audit_log``。测试可通过覆写
``get_governance_stack`` 的依赖注入换回内存实现。
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, model_validator

from local_ingestion.platform.governance import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    ApprovalService,
    InvalidApprovalActionError,
    InvalidTicketTransitionError,
    InvalidTicketTypeError,
    TicketNotFoundError,
    TicketService,
)
from local_ingestion.platform.governance.models import (
    ApprovalInput,
    TicketInput,
)
from local_ingestion.platform.orchestration.audit import AuditService

router = APIRouter(prefix="/api/v1/governance", tags=["Governance"])

_state: dict = {}


def get_governance_stack():
    """SQL-backed governance stack（MOD-12 持久化）。

    审批/工单/评论落在 ``approval_request`` / ``governance_ticket`` /
    ``governance_comment`` 表，审计写 ``audit_log``。
    """
    if "stack" not in _state:
        from local_ingestion.platform.governance.repository import SqlGovernanceRepository
        from local_ingestion.platform.orchestration.audit import SqlAuditSink
        from local_ingestion.platform.storage.session import session_scope

        repo = SqlGovernanceRepository(session_scope)
        audit = AuditService(SqlAuditSink(session_scope))
        approval_svc = ApprovalService(repo, audit=audit)
        ticket_svc = TicketService(repo, audit=audit)
        _state["stack"] = (approval_svc, ticket_svc, repo)
    return _state["stack"]


def get_approval_service() -> ApprovalService:
    return get_governance_stack()[0]


def get_ticket_service() -> TicketService:
    return get_governance_stack()[1]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class ApprovalCreate(BaseModel):
    resource_type: str
    resource_fqn: str
    action_type: str
    title: str
    requested_by: str
    approver: Optional[str] = None
    priority: str = "P2"
    reason: Optional[str] = None
    actor: Optional[str] = None


class DecisionRequest(BaseModel):
    actor: str
    comment: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_names(cls, data):
        """兼容旧的 `decided_by` / `decision_note`（前端曾因此 422 白屏）。

        规范字段名以本 model 为准；别名仅在缺失时兜底，不改变对外响应契约。
        """
        if isinstance(data, dict):
            data = dict(data)
            if "actor" not in data and data.get("decided_by"):
                data["actor"] = data["decided_by"]
            if "comment" not in data and data.get("decision_note"):
                data["comment"] = data["decision_note"]
        return data


class TicketCreate(BaseModel):
    title: str
    description: Optional[str] = None
    ticket_type: str = "data_issue"
    priority: str = "P2"
    reporter: str = "system"
    assignee: Optional[str] = None
    related_fqn: Optional[str] = None
    source: str = "manual"
    sla_hours: Optional[int] = None
    actor: Optional[str] = None


class AssignRequest(BaseModel):
    assignee: str
    actor: Optional[str] = None


class TransitionRequest(BaseModel):
    to_status: str
    actor: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_names(cls, data):
        """兼容旧的 `status`（前端曾把目标状态放在 `status` 上导致 422）。"""
        if isinstance(data, dict):
            data = dict(data)
            if "to_status" not in data and data.get("status"):
                data["to_status"] = data["status"]
        return data


class CommentRequest(BaseModel):
    author: str
    body: str


def _or_404(exc):
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------
@router.post("/approvals", status_code=status.HTTP_201_CREATED)
def create_approval(body: ApprovalCreate, svc: ApprovalService = Depends(get_approval_service)):
    try:
        a = svc.create(ApprovalInput(**body.model_dump(exclude={"actor"})), actor=body.actor)
    except InvalidApprovalActionError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return asdict(a)


@router.get("/approvals")
def list_approvals(
    svc: ApprovalService = Depends(get_approval_service),
    status_filter: Optional[str] = None,
    resource_type: Optional[str] = None,
    approver: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    rows = svc.list(status=status_filter, resource_type=resource_type, approver=approver,
                    limit=limit, offset=offset)
    return {"approvals": [asdict(r) for r in rows], "count": len(rows)}


@router.get("/approvals/{approval_id}")
def get_approval(approval_id: int, svc: ApprovalService = Depends(get_approval_service)):
    try:
        return asdict(svc.get(approval_id))
    except ApprovalNotFoundError as e:
        _or_404(e)


def _apply_approved_side_effects(approval) -> None:
    """审批通过后的下游动作（目前仅 MOD-05 分级修正）。

    分级与审批分属两个模块：这里由审批侧在通过后调用分级提供的
    ``apply_approved_annotation``，避免 governance 反向依赖 classification 内部实现。

    下游失败**不能**让审批接口报错——审批已经生效，用日志留痕即可，
    否则用户会重复点「通过」。
    """
    if getattr(approval, "resource_type", None) != "classification":
        return
    try:
        from local_ingestion.platform.classification.annotation import (
            apply_approved_annotation,
        )
        from local_ingestion.platform.storage.session import session_scope

        apply_approved_annotation(getattr(approval, "reason", None), session_scope)
    except Exception:  # noqa: BLE001 - 下游失败不应回滚审批
        logging.getLogger(__name__).exception(
            "classification_approval_apply_failed", extra={"approval_id": approval.id}
        )


@router.post("/approvals/{approval_id}/approve")
def approve_approval(approval_id: int, body: DecisionRequest,
                    svc: ApprovalService = Depends(get_approval_service)):
    try:
        decided = svc.approve(approval_id, body.actor, body.comment)
    except ApprovalNotFoundError as e:
        _or_404(e)
    except ApprovalAlreadyDecidedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except InvalidApprovalActionError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    _apply_approved_side_effects(decided)
    return asdict(decided)


@router.post("/approvals/{approval_id}/reject")
def reject_approval(approval_id: int, body: DecisionRequest,
                   svc: ApprovalService = Depends(get_approval_service)):
    try:
        return asdict(svc.reject(approval_id, body.actor, body.comment))
    except ApprovalNotFoundError as e:
        _or_404(e)
    except ApprovalAlreadyDecidedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except InvalidApprovalActionError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.get("/approvals/{approval_id}/comments")
def list_approval_comments(approval_id: int, svc: ApprovalService = Depends(get_approval_service)):
    try:
        rows = svc.comments(approval_id)
    except ApprovalNotFoundError as e:
        _or_404(e)
    return {"comments": [asdict(c) for c in rows], "count": len(rows)}


@router.post("/approvals/{approval_id}/comments", status_code=status.HTTP_201_CREATED)
def add_approval_comment(approval_id: int, body: CommentRequest,
                        svc: ApprovalService = Depends(get_approval_service)):
    try:
        c = svc.comment(approval_id, body.author, body.body)
    except ApprovalNotFoundError as e:
        _or_404(e)
    return asdict(c)


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
@router.post("/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(body: TicketCreate, svc: TicketService = Depends(get_ticket_service)):
    try:
        t = svc.create(TicketInput(**body.model_dump(exclude={"actor"})), actor=body.actor)
    except InvalidTicketTypeError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return asdict(t)


@router.get("/tickets")
def list_tickets(
    svc: TicketService = Depends(get_ticket_service),
    status_filter: Optional[str] = None,
    ticket_type: Optional[str] = None,
    assignee: Optional[str] = None,
    reporter: Optional[str] = None,
    related_fqn: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    rows = svc.list(status=status_filter, ticket_type=ticket_type, assignee=assignee,
                    reporter=reporter, related_fqn=related_fqn, limit=limit, offset=offset)
    return {"tickets": [asdict(r) for r in rows], "count": len(rows)}


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, svc: TicketService = Depends(get_ticket_service)):
    try:
        return asdict(svc.get(ticket_id))
    except TicketNotFoundError as e:
        _or_404(e)


@router.post("/tickets/{ticket_id}/assign")
def assign_ticket(ticket_id: int, body: AssignRequest,
                 svc: TicketService = Depends(get_ticket_service)):
    try:
        return asdict(svc.assign(ticket_id, body.assignee, body.actor))
    except TicketNotFoundError as e:
        _or_404(e)


@router.post("/tickets/{ticket_id}/transition")
def transition_ticket(ticket_id: int, body: TransitionRequest,
                     svc: TicketService = Depends(get_ticket_service)):
    try:
        return asdict(svc.transition(ticket_id, body.to_status, body.actor))
    except TicketNotFoundError as e:
        _or_404(e)
    except InvalidTicketTransitionError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.get("/tickets/{ticket_id}/comments")
def list_ticket_comments(ticket_id: int, svc: TicketService = Depends(get_ticket_service)):
    try:
        rows = svc.comments(ticket_id)
    except TicketNotFoundError as e:
        _or_404(e)
    return {"comments": [asdict(c) for c in rows], "count": len(rows)}


@router.post("/tickets/{ticket_id}/comments", status_code=status.HTTP_201_CREATED)
def add_ticket_comment(ticket_id: int, body: CommentRequest,
                      svc: TicketService = Depends(get_ticket_service)):
    try:
        c = svc.comment(ticket_id, body.author, body.body)
    except TicketNotFoundError as e:
        _or_404(e)
    return asdict(c)
