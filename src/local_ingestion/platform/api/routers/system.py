"""Platform health & runtime metrics endpoints (MOD-10 / FR-15).

Exposes ``GET /api/v1/system/health`` and ``GET /api/v1/system/metrics`` so the
frontend (FE-01 §2 dashboard health strip, §11.3/§11.4) and external monitors
have a stable, documented contract. The database probe is best-effort: the
default in-memory stack has no Postgres, in which case the DB component reports
``degraded`` rather than failing the whole health call.
"""
from __future__ import annotations

import logging
import os
import platform
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter

from ...api.serialization import camelize

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/system", tags=["System"])

_STARTED_AT = time.time()


def _app_version() -> str:
    try:
        from ... import __version__ as v  # type: ignore

        return str(v)
    except Exception:
        return "dev"


def _db_status() -> Dict[str, Any]:
    try:
        from sqlalchemy import text

        from ...storage.session import session_scope

        with session_scope() as s:
            s.execute(text("SELECT 1"))
        return {"component": "database", "status": "healthy", "message": "ok"}
    except Exception:  # pragma: no cover - environment dependent
        # 不要把驱动/DB 原始异常放进响应体：前端会直接渲染 c.message（ux-audit E 组）
        return {
            "component": "database",
            "status": "degraded",
            "message": "数据库不可用，请检查数据库服务与连接配置",
        }


@router.get("/health")
def system_health() -> Dict[str, Any]:
    """Overall system health, with per-component checks."""
    components = [_db_status(), {"component": "api", "status": "healthy", "message": "running"}]
    status = "healthy"
    if any(c["status"] != "healthy" for c in components):
        status = "degraded"
    return camelize(
        {
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "components": components,
        }
    )


@router.get("/metrics")
def system_metrics() -> Dict[str, Any]:
    """Basic runtime metrics (uptime, version, environment)."""
    return camelize(
        {
            "uptime_seconds": round(time.time() - _STARTED_AT, 2),
            "app_version": _app_version(),
            "python_version": platform.python_version(),
            "environment": os.getenv("APP_ENV", "dev"),
            "started_at": datetime.fromtimestamp(_STARTED_AT, tz=timezone.utc).isoformat(),
        }
    )
