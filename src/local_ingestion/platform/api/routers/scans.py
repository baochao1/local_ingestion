"""Manual scan trigger: registered datasource -> real ingestion -> ``catalog_*``.

``POST /api/v1/datasources/{datasource_id}/scan`` runs the ingestion pipeline on
demand. It is deliberately **synchronous** — a large source database can hold the
request open for minutes — while *scheduled* execution goes through
:mod:`local_ingestion.platform.scan.scheduler`, which runs the same service in a
background thread.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ...api.serialization import camelize, snakify
from ...classification import ClassificationService
from ...connections import WriteAccessError
from ...scan import (
    DatasourceNotFoundError,
    ScanError,
    ScanService,
    UnsupportedDatasourceError,
)

router = APIRouter(prefix="/api/v1/datasources", tags=["Scans"])


class ScanRequest(BaseModel):
    """Per-run overrides. Every field is optional."""

    database: Optional[str] = None
    schemas: Optional[List[str]] = None
    allowWrite: bool = Field(False, alias="allowWrite")
    markDeleted: bool = Field(True, alias="markDeleted")

    model_config = {"populate_by_name": True}


class ClassifyRequest(BaseModel):
    """``all`` re-derives grades for already-graded rows too."""

    all: bool = Field(False, alias="all")

    model_config = {"populate_by_name": True}


def get_classification_service() -> ClassificationService:
    """Production wiring for MOD-05 grading (overridable in tests)."""
    from ...storage.session import session_scope

    return ClassificationService(session_scope)


def get_scan_service() -> ScanService:
    """Production wiring.

    Built per request so it honours the platform DB configuration loaded from
    the environment at call time; tests override this dependency to inject a
    fake instead of needing a live PostgreSQL.
    """
    from ...storage.session import session_scope

    return ScanService(session_scope)


@router.post("/{datasource_id}/classify")
def classify_datasource(
    datasource_id: int,
    body: Optional[ClassifyRequest] = None,
    svc: ClassificationService = Depends(get_classification_service),
) -> Dict[str, Any]:
    """(Re-)grade the datasource's catalog rows without rescanning."""
    opts = snakify((body or ClassifyRequest()).model_dump(by_alias=True))
    return camelize(
        svc.classify_datasource(
            datasource_id, only_ungraded=not bool(opts.get("all", False))
        ).as_dict()
    )


@router.post("/{datasource_id}/scan")
def run_scan(
    datasource_id: int,
    body: Optional[ScanRequest] = None,
    svc: ScanService = Depends(get_scan_service),
) -> Dict[str, Any]:
    opts = snakify((body or ScanRequest()).model_dump(by_alias=True))
    try:
        result = svc.run_scan(
            datasource_id,
            database=opts.get("database"),
            schemas=opts.get("schemas"),
            allow_write=bool(opts.get("allow_write", False)),
            mark_deleted=bool(opts.get("mark_deleted", True)),
        )
    except DatasourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except (UnsupportedDatasourceError, ScanError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except WriteAccessError as exc:
        # FR-1.5 只读策略拒绝：属于用户可操作的状况（勾选"允许写权限"即可放行），
        # 必须回 4xx + 可行动文案，而不是让它冒泡成 500 "Internal Server Error"。
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return camelize(result.as_dict())
