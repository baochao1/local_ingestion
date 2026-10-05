"""FastAPI router for data-source management (MOD-01 / T-109).

Mounted onto the main app via ``app.include_router(router)``. The service is
injected through :func:`get_datasource_service` so tests can swap in an
in-memory stack via ``app.dependency_overrides`` without a database.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from ...datasource.schemas import (
    CredentialCreate,
    DatasourceCreate,
    DatasourceUpdate,
    TestConnectionRequest,
)
from ...datasource.service import (
    ConnectionFailedError,
    ConflictError,
    DataSourceService,
    DataSourceServiceError,
    NotFoundError,
    WriteAccessDeniedError,
)
from ...api.serialization import camelize, snakify

router = APIRouter(prefix="/api/v1/datasources", tags=["DataSources"])


def get_datasource_service() -> DataSourceService:
    """Production wiring: SQLAlchemy repo + persistent audit + real orchestrator.

    Constructed per request so it honours the platform DB configuration loaded
    from the environment at call time.
    """
    from ...datasource.repository import SqlDatasourceRepository
    from ...orchestration import (
        AuditService,
        SqlAuditSink,
        build_sql_orchestration,
    )
    from ...storage.session import session_scope

    repo = SqlDatasourceRepository(session_scope)
    audit = AuditService(SqlAuditSink(session_scope))
    tasks = build_sql_orchestration()
    return DataSourceService(repo, audit=audit, task_service=tasks)


def _handle_errors(fn):
    try:
        return fn()
    except ConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (ConnectionFailedError, WriteAccessDeniedError, DataSourceServiceError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("", status_code=status.HTTP_201_CREATED)
def register_datasource(
    body: DatasourceCreate,
    svc: DataSourceService = Depends(get_datasource_service),
) -> Dict[str, Any]:
    spec = snakify(body.model_dump(by_alias=True))
    # allowWrite is passed only via the explicit kwarg; drop the spec copy to
    # avoid implying the body field drives registration on its own.
    spec.pop("allow_write", None)
    return _handle_errors(
        lambda: camelize(svc.register(spec, allow_write=body.allowWrite))
    )


@router.post("/test")
def test_connection(
    body: TestConnectionRequest,
    svc: DataSourceService = Depends(get_datasource_service),
) -> Dict[str, Any]:
    spec = snakify(body.model_dump(by_alias=True))
    return _handle_errors(lambda: camelize(svc.test_connection(spec)))


@router.get("")
def list_datasources(
    enabled: Optional[bool] = None,
    environment: Optional[str] = None,
    group: Optional[str] = None,
    type: Optional[str] = None,
    keyword: Optional[str] = None,
    svc: DataSourceService = Depends(get_datasource_service),
) -> Dict[str, Any]:
    rows = svc.list_datasources(
        enabled=enabled, environment=environment, group_name=group,
        ds_type=type, keyword=keyword,
    )
    return camelize({"items": rows, "hasMore": False, "approxTotal": len(rows)})


@router.get("/{datasource_id}")
def get_datasource(
    datasource_id: int,
    svc: DataSourceService = Depends(get_datasource_service),
) -> Dict[str, Any]:
    return _handle_errors(lambda: camelize(svc.get_datasource(datasource_id)))


@router.put("/{datasource_id}")
def update_datasource(
    datasource_id: int,
    body: DatasourceUpdate,
    svc: DataSourceService = Depends(get_datasource_service),
) -> Dict[str, Any]:
    changes = snakify({k: v for k, v in body.model_dump(by_alias=True, exclude_unset=True).items()})
    return _handle_errors(lambda: camelize(svc.update_datasource(datasource_id, changes)))


@router.delete("/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_datasource(
    datasource_id: int,
    svc: DataSourceService = Depends(get_datasource_service),
) -> None:
    _handle_errors(lambda: svc.delete_datasource(datasource_id))


@router.post("/{datasource_id}/enable")
def enable_datasource(
    datasource_id: int,
    svc: DataSourceService = Depends(get_datasource_service),
) -> Dict[str, Any]:
    return _handle_errors(lambda: camelize(svc.enable(datasource_id)))


@router.post("/{datasource_id}/disable")
def disable_datasource(
    datasource_id: int,
    svc: DataSourceService = Depends(get_datasource_service),
) -> Dict[str, Any]:
    return _handle_errors(lambda: camelize(svc.disable(datasource_id)))


@router.post("/{datasource_id}/credentials")
def add_credential(
    datasource_id: int,
    body: CredentialCreate,
    svc: DataSourceService = Depends(get_datasource_service),
) -> Dict[str, Any]:
    version = _handle_errors(
        lambda: svc.add_credential_version(datasource_id, body.username, body.password)
    )
    return {"version": version}


@router.post("/{datasource_id}/credentials/{version}/activate")
def activate_credential(
    datasource_id: int,
    version: int,
    svc: DataSourceService = Depends(get_datasource_service),
) -> Dict[str, Any]:
    activated = _handle_errors(lambda: svc.activate_credential(datasource_id, version))
    return {"version": activated}


@router.get("/{datasource_id}/health")
def datasource_health(
    datasource_id: int,
    svc: DataSourceService = Depends(get_datasource_service),
) -> Dict[str, Any]:
    return _handle_errors(lambda: camelize(svc.health(datasource_id)))
