"""REST API for change confirmation / statistics (MOD-06 / T-204).

Defaults to a fully in-memory stack so the endpoints work without a Postgres
backend; the dependency can be overridden to wire a SQL-backed stack in production.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from local_ingestion.platform.changes import (
    ChangeAlreadyClosedError,
    ChangeConfirmService,
    ChangeNotFoundError,
    ChangeStatsService,
    InvalidAckActionError,
    build_in_memory_change_stack,
)
from local_ingestion.platform.orchestration.audit import AuditService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/changes", tags=["Changes"])

_state: dict = {}


def _auto_ticket_from_change(change, action):
    """MOD-12 linkage: raise a ticket when a *breaking* change is acknowledged."""
    if getattr(change, "severity", None) != "breaking":
        return
    try:
        from local_ingestion.api.routers.governance import get_ticket_service

        svc = get_ticket_service()
        svc.create_from_change(change, action, actor=getattr(change, "ack_by", None) or "system")
    except Exception:  # pragma: no cover - best-effort linkage, never break ack
        logger.warning("auto ticket from breaking change failed", exc_info=True)


def get_change_stack():
    """SQL-backed change stack（MOD-06 持久化）。

    变更事件落在 ``change_event`` 表，审计写 ``audit_log``。仅在需要通过
    ``_state`` 覆盖依赖做单测时才改这里。
    """
    if "stack" not in _state:
        from local_ingestion.platform.changes import (
            ChangeConfirmService,
            ChangeEscalationService,
            ChangeStatsService,
            SqlChangeRepository,
        )
        from local_ingestion.platform.notify import build_sql_notify_stack
        from local_ingestion.platform.orchestration.audit import SqlAuditSink
        from local_ingestion.platform.storage.session import session_scope

        repo = SqlChangeRepository(session_scope)
        audit = AuditService(SqlAuditSink(session_scope))
        confirm = ChangeConfirmService(repo, audit=audit, on_after_ack=_auto_ticket_from_change)
        stats = ChangeStatsService(repo)
        # 订阅/通知落库（notification_subscription / notification_log）
        sub_svc, agg, _, _ = build_sql_notify_stack()
        escalation = ChangeEscalationService(repo, agg, timedelta(hours=24))
        _state["stack"] = (confirm, stats, escalation, repo, agg, sub_svc)
    return _state["stack"]


def get_repo():
    return get_change_stack()[3]


def get_confirm():
    return get_change_stack()[0]


def get_stats():
    return get_change_stack()[1]


class AckRequest(BaseModel):
    actor: str
    action: str  # acknowledged | rejected | ignored


@router.get("/statistics")
def get_statistics(
    since: Optional[str] = None,
    until: Optional[str] = None,
    stats: ChangeStatsService = Depends(get_stats),
):
    u = datetime.fromisoformat(until) if until else datetime.now()
    s = datetime.fromisoformat(since) if since else u - timedelta(days=30)
    return asdict(stats.statistics(s, u))


@router.get("")
def list_changes(
    repo=Depends(get_repo),
    severity: Optional[str] = None,
    datasource_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_fqn: Optional[str] = None,
    ack_status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    rows = repo.list(
        severity=severity, datasource_id=datasource_id, entity_type=entity_type,
        entity_fqn=entity_fqn, ack_status=ack_status, limit=limit, offset=offset,
    )
    return {"changes": [asdict(r) for r in rows], "count": len(rows)}


@router.get("/entities/{entity_type}/{entity_fqn:path}/history")
def entity_history(entity_type: str, entity_fqn: str, limit: int = 50, repo=Depends(get_repo)):
    rows = repo.get_history(entity_type, entity_fqn, limit=limit)
    return {"history": [asdict(r) for r in rows], "count": len(rows)}


@router.get("/{change_id}")
def get_change(change_id: int, repo=Depends(get_repo)):
    c = repo.get(change_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="change not found")
    return asdict(c)


@router.post("/{change_id}/ack", status_code=status.HTTP_200_OK)
def ack_change(change_id: int, body: AckRequest, confirm: ChangeConfirmService = Depends(get_confirm)):
    try:
        ev = confirm.ack(change_id, body.actor, body.action)
    except ChangeNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="change not found")
    except ChangeAlreadyClosedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="change already closed")
    except InvalidAckActionError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid ack action")
    return asdict(ev)
