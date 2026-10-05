"""Subscription REST API (MOD-06 / T-203).

订阅持久化在 ``notification_subscription`` 表（``SqlSubscriptionRepository``），
供前端"数据变更 → 订阅管理"页使用。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...api.serialization import camelize
from ...notify import SubscriptionService, SubscriptionSpec
from ...notify import build_sql_notify_stack
from ...storage.session import session_scope

router = APIRouter(prefix="/api/v1/subscriptions", tags=["Subscriptions"])

_state: dict = {}


def get_subscription_service() -> SubscriptionService:
    if "svc" not in _state:
        sub_svc, _agg, _repo, _logs = build_sql_notify_stack(session_factory=session_scope)
        _state["svc"] = sub_svc
    return _state["svc"]


class SubscriptionCreate(BaseModel):
    subscriber: str
    scopeType: str = Field("global", description="global | datasource | schema | table")
    scopeFqn: Optional[str] = None
    datasourceId: Optional[int] = None
    minSeverity: str = "P2"
    channel: str = "email"
    channelConf: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


def _sub_to_dict(s) -> Dict[str, Any]:
    return {
        "id": s.id,
        "subscriber": s.subscriber,
        "scope_type": s.scope_type,
        "scope_fqn": s.scope_fqn,
        "datasource_id": s.datasource_id,
        "min_severity": s.min_severity,
        "channel": s.channel,
        "enabled": s.enabled,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.get("")
def list_subscriptions(
    subscriber: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
) -> Dict[str, Any]:
    svc = get_subscription_service()
    rows = svc.list()
    if subscriber:
        rows = [r for r in rows if r.subscriber == subscriber]
    if enabled is not None:
        rows = [r for r in rows if bool(r.enabled) is enabled]
    return camelize({"items": [_sub_to_dict(r) for r in rows], "total": len(rows)})


@router.post("", status_code=status.HTTP_201_CREATED)
def create_subscription(body: SubscriptionCreate) -> Dict[str, Any]:
    svc = get_subscription_service()
    spec = SubscriptionSpec(
        subscriber=body.subscriber,
        scope_type=body.scopeType,
        scope_fqn=body.scopeFqn,
        datasource_id=body.datasourceId,
        min_severity=body.minSeverity,
        channel=body.channel,
        channel_conf=dict(body.channelConf),
        enabled=body.enabled,
    )
    return camelize(_sub_to_dict(svc.create(spec)))


@router.get("/{sub_id}")
def get_subscription(sub_id: int) -> Dict[str, Any]:
    svc = get_subscription_service()
    s = svc.get(sub_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"subscription {sub_id} not found")
    return camelize(_sub_to_dict(s))


@router.post("/{sub_id}/mute")
def mute_subscription(sub_id: int) -> Dict[str, Any]:
    svc = get_subscription_service()
    try:
        svc.mute(sub_id)
    except Exception as exc:  # noqa: BLE001 - 统一出口，区分语义且不外泄原始异常
        detail = str(exc)
        if "not found" in detail.lower() or "不存在" in detail:
            raise HTTPException(status_code=404, detail="订阅不存在") from exc
        raise HTTPException(status_code=500, detail="订阅停用失败，请稍后重试") from exc
    return camelize({"id": sub_id, "enabled": False})


@router.post("/{sub_id}/unmute")
def unmute_subscription(sub_id: int) -> Dict[str, Any]:
    svc = get_subscription_service()
    try:
        svc.unmute(sub_id)
    except Exception as exc:  # noqa: BLE001 - 同上
        detail = str(exc)
        if "not found" in detail.lower() or "不存在" in detail:
            raise HTTPException(status_code=404, detail="订阅不存在") from exc
        raise HTTPException(status_code=500, detail="订阅启用失败，请稍后重试") from exc
    return camelize({"id": sub_id, "enabled": True})


@router.delete("/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(sub_id: int) -> None:
    svc = get_subscription_service()
    if not svc.delete(sub_id):
        raise HTTPException(status_code=404, detail=f"subscription {sub_id} not found")
