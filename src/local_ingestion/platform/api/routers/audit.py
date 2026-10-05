"""Audit log REST API (MOD-10 / FR-15.5).

Exposes the process-wide ``GLOBAL_AUDIT_SINK`` (in-memory default stack) as a
queryable feed so the frontend "任务运维 → 审计" tab (FE-01 §11.5) can render
critical actions (task submit/cancel/retry/success/failure, etc.).

In the default in-memory stack every audit entry is written by services that opt
into ``GLOBAL_AUDIT_SINK`` (the orchestration ``TaskService`` does). Services
still using their own per-call sink won't appear here until they are pointed at
the shared sink — see ``platform/orchestration/audit.py``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from ...api.serialization import camelize
from ...orchestration.audit import GLOBAL_AUDIT_SINK

router = APIRouter(prefix="/api/v1/audit-logs", tags=["Audit"])


def _entry_to_dict(entry) -> Dict[str, Any]:
    return {
        "actor": entry.actor,
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_fqn": entry.entity_fqn,
        "detail": dict(entry.detail or {}),
        "client_ip": entry.client_ip,
        "result": entry.result,
        "occurred_at": entry.occurred_at.isoformat() if entry.occurred_at else None,
    }


def _query_from_db(action: Optional[str], actor: Optional[str],
                   entity_type: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """从 ``audit_log`` 表读取（持久化，重启后仍可见）。"""
    from ...storage.models_ops import AuditLog
    from ...storage.session import session_scope

    with session_scope() as s:
        q = s.query(AuditLog)
        if action is not None:
            q = q.filter(AuditLog.action == action)
        if actor is not None:
            q = q.filter(AuditLog.actor == actor)
        if entity_type is not None:
            q = q.filter(AuditLog.entity_type == entity_type)
        rows = q.order_by(AuditLog.occurred_at.desc()).limit(limit).all()
        return [
            {
                "actor": r.actor,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_fqn": r.entity_fqn,
                "detail": dict(r.detail or {}),
                "client_ip": str(r.client_ip) if r.client_ip else None,
                "result": r.result,
                "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
            }
            for r in rows
        ]


@router.get("")
def list_audit_logs(
    action: Optional[str] = Query(None, description="filter by action, e.g. task.cancel"),
    actor: Optional[str] = Query(None, description="filter by actor"),
    entityType: Optional[str] = Query(None, description="filter by entity_type"),
    limit: int = Query(100, ge=1, le=1000, description="max rows returned"),
) -> Dict[str, Any]:
    """Query audit entries newest-first（优先读库，失败退回内存 sink）。"""
    try:
        items = _query_from_db(action, actor, entityType, limit)
    except Exception:  # noqa: BLE001 - 无库环境退回内存缓冲
        items = [
            _entry_to_dict(e)
            for e in GLOBAL_AUDIT_SINK.query(
                action=action, actor=actor, entity_type=entityType, limit=limit
            )
        ]
    return camelize({"items": items, "total": len(items)})
