"""REST API for permission analysis (MOD-08).

Exposes account/grant inventory, the bidirectional permission matrix, risk
detection (super / excessive / dormant / orphan / high-sensitivity), baseline
diff, and a standalone analysis trigger. All reads hit the platform catalog only;
the analysis itself ran read-only against the business DB via ADMIN connection.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, Query

from local_ingestion.platform.api.routers.tasks import get_task_service
from local_ingestion.platform.orchestration.models import TaskSpec
from local_ingestion.platform.permission.service import PermissionQueryService
from local_ingestion.platform.storage.session import session_scope

router = APIRouter(prefix="/api/v1/permissions", tags=["Permissions"])


def get_svc() -> PermissionQueryService:
    return PermissionQueryService(session_scope)


@router.get("/accounts")
def list_accounts(
    datasource_id: int = Query(...),
    account: Optional[str] = Query(None),
    svc: PermissionQueryService = Depends(get_svc),
):
    return svc.matrix(datasource_id, account=account)


@router.get("/accounts/{account}/grants")
def account_grants(
    account: str,
    datasource_id: int = Query(...),
    svc: PermissionQueryService = Depends(get_svc),
):
    return svc.grants_of_account(datasource_id, account)


@router.get("/matrix")
def matrix(
    datasource_id: int = Query(...),
    svc: PermissionQueryService = Depends(get_svc),
):
    return svc.matrix(datasource_id)


@router.get("/entities/grants")
def entity_grants(
    object_fqn: str = Query(...),
    svc: PermissionQueryService = Depends(get_svc),
):
    return svc.get_entity_grants(object_fqn)


@router.get("/risks")
def risks(
    datasource_id: int = Query(...),
    severity: Optional[str] = Query(None),
    svc: PermissionQueryService = Depends(get_svc),
):
    return svc.risks(datasource_id, severity=severity)


@router.post("/risks/{risk_id}/ack")
def ack_risk(
    risk_id: str,
    datasource_id: int = Query(...),
    svc: PermissionQueryService = Depends(get_svc),
):
    svc.ack_risk(datasource_id, risk_id)
    return {"ok": True}


@router.get("/changes")
def changes(
    datasource_id: int = Query(...),
    svc: PermissionQueryService = Depends(get_svc),
):
    return svc.changes(datasource_id)


@router.post("/baseline/refresh")
def refresh_baseline(
    datasource_id: int = Body(..., embed=True),
    svc: PermissionQueryService = Depends(get_svc),
):
    svc.mark_baseline(datasource_id)
    return {"ok": True}


@router.post("/tasks")
def trigger(
    datasource_id: int = Body(..., embed=True),
    target_schema: Optional[str] = Body(None, embed=True),
    svc: PermissionQueryService = Depends(get_svc),
):
    spec = TaskSpec(job_type="permission.collect", scope={"datasource_id": datasource_id, "schema": target_schema})
    run = get_task_service().submit(spec)
    return {"task_id": run.id}


@router.get("/export")
def export(
    datasource_id: int = Query(...),
    svc: PermissionQueryService = Depends(get_svc),
):
    return svc.export_report(datasource_id)
