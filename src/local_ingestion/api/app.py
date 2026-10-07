"""FastAPI Application for Local Ingestion"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from local_ingestion.api.service import MetadataService, WorkflowService
from local_ingestion.platform.api.routers.datasources import router as _datasource_router
from local_ingestion.platform.api.routers.scans import router as _scans_router
from local_ingestion.platform.api.routers.search import router as _search_router
from local_ingestion.platform.api.routers.catalog_browse import router as _catalog_browse_router
from local_ingestion.platform.api.routers.classification import router as _classification_router
from local_ingestion.platform.api.routers.profiles import router as _profiles_router
from local_ingestion.platform.api.routers.assets import router as _assets_router
from local_ingestion.platform.api.routers.tasks import router as _tasks_router
from local_ingestion.platform.api.routers.audit import router as _audit_router
from local_ingestion.platform.api.routers.partitions import router as _partitions_router
from local_ingestion.api.routers.changes import router as _changes_router
from local_ingestion.api.routers.governance import router as _governance_router
from local_ingestion.api.routers.permissions import router as _permissions_router
from local_ingestion.platform.api.routers.system import router as _system_router
from local_ingestion.platform.api.routers.subscriptions import router as _subscriptions_router
from local_ingestion.api.routers.catalog_overview import router as _catalog_overview_router
from local_ingestion.api.routers.lineage import router as _lineage_router
from local_ingestion.api.routers.business import router as _business_router
from local_ingestion.api.routers.meta import router as _meta_router
from local_ingestion.api.exceptions import NotFoundError, ValidationError, ConflictError
from local_ingestion.schema.data.table import Table
from local_ingestion.schema.data.database import Database
from local_ingestion.schema.metadata.workflow import LocalWorkflowConfig

logger = logging.getLogger(__name__)

# In-memory database for development
class InMemoryDB:
    """Simple in-memory database for development"""
    
    def __init__(self):
        self._data: Dict[str, List[Dict]] = {}
    
    def insert(self, table_name: str, data: dict) -> str:
        if table_name not in self._data:
            self._data[table_name] = []
        self._data[table_name].append(data)
        return data.get("id", "")
    
    def find_one(self, table_name: str, query: dict) -> dict | None:
        if table_name not in self._data:
            return None
        for item in self._data[table_name]:
            if all(item.get(k) == v for k, v in query.items()):
                return item
        return None
    
    def find_many(self, table_name: str, query: dict) -> list[dict]:
        if table_name not in self._data:
            return []
        if not query:
            return self._data[table_name]
        return [
            item for item in self._data[table_name]
            if all(item.get(k) == v for k, v in query.items())
        ]
    
    def delete_one(self, table_name: str, query: dict) -> bool:
        if table_name not in self._data:
            return False
        for i, item in enumerate(self._data[table_name]):
            if all(item.get(k) == v for k, v in query.items()):
                self._data[table_name].pop(i)
                return True
        return False


# Global database instance
_db = InMemoryDB()
_metadata_service = MetadataService(_db)
_workflow_service = WorkflowService(_db)


# Pydantic models for API
class TableCreate(BaseModel):
    name: str
    fullyQualifiedName: str
    description: Optional[str] = None
    columns: List[Dict[str, Any]] = []
    database: Optional[str] = None
    databaseSchema: Optional[str] = None


class DatabaseCreate(BaseModel):
    name: str
    fullyQualifiedName: str
    description: Optional[str] = None
    owner: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    version: str = "0.1.0"


def _start_scan_scheduler():
    """Opt-in periodic scanning (off unless ``SCAN_SCHEDULER=1``).

    Kept disabled by default so importing/starting the app never opens surprise
    background connections — notably in tests.
    """
    if os.getenv("SCAN_SCHEDULER", "").strip().lower() not in {"1", "true", "yes", "on"}:
        return None

    from local_ingestion.platform.scan.scheduler import ScanScheduler
    from local_ingestion.storage.session import session_scope

    interval = int(os.getenv("SCAN_INTERVAL_MINUTES", "60") or 60)
    scheduler = ScanScheduler(session_scope, default_interval_minutes=interval)
    if scheduler.start():
        logger.info("scan scheduler started (interval=%s min)", interval)
        return scheduler
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager"""
    logger.info("Starting Local Ingestion API")
    scheduler = _start_scan_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.stop()
        logger.info("Shutting down Local Ingestion API")


app = FastAPI(
    title="Local Ingestion API",
    description="Lightweight metadata ingestion API for local development",
    version="0.1.0",
    lifespan=lifespan,
)

# --- 错误归一 ---------------------------------------------------------------
# 契约约定：所有 4xx/5xx 的 `detail` 必须是**字符串**（不可为对象数组）。
# FastAPI 默认把 RequestValidationError 序列化成 `[{type, loc, msg, input}]`，
# 前端一旦把它整体渲染就会抛 "Objects are not valid as a React child" 并整站白屏
# （见 doc/design/ux-audit-full.md S0#2/S0#3），故在出口统一拍平成可读文案。
_VALIDATION_TYPE_TEXT = {
    "missing": "缺少必填字段",
    "string_type": "应为字符串",
    "int_type": "应为整数",
    "int_parsing": "应为整数",
    "float_parsing": "应为数值",
    "bool_parsing": "应为布尔值",
    "enum": "取值不在允许范围内",
    "value_error": "取值不合法",
    "string_too_short": "内容过短",
    "greater_than_equal": "小于允许的最小值",
    "less_than_equal": "超出允许的最大值",
}

# loc 里的 body/query/path 描述参数所在位置，不是字段含义，不展示给终端用户。
_LOC_NOISE = {"body", "query", "path", "header", "cookie"}


def _describe_validation_error(exc: RequestValidationError) -> str:
    parts: List[str] = []
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if str(p) not in _LOC_NOISE]
        field = ".".join(loc) or "请求体"
        reason = _VALIDATION_TYPE_TEXT.get(str(err.get("type", "")), str(err.get("msg", "取值不合法")))
        parts.append(f"{field}：{reason}")
    if not parts:
        return "请求参数有误"
    return "请求参数有误：" + "；".join(parts)


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": _describe_validation_error(exc)},
    )


def _cors_origins() -> list:
    """CORS 白名单（对标 S0-3）。

    原先是 `allow_origins=["*"]` + `allow_credentials=True`：该组合在浏览器侧
    本就非法，且等于对任意站点开放跨域请求。现在默认只放本地 dev 前端，
    生产必须由 `CORS_ORIGINS` 显式配置（未配置则不放行任何来源）。
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    if os.getenv("APP_ENV", "dev").lower() in ("prod", "production"):
        return []
    return ["http://localhost:5173", "http://127.0.0.1:5173"]


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint"""
    return HealthResponse(status="healthy", version="0.1.0")


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "service": "Local Ingestion API",
        "version": "0.1.0",
        "docs": "/docs",
    }


# ============== Table Endpoints ==============

@app.post("/api/v1/tables", status_code=status.HTTP_201_CREATED, tags=["Tables"])
async def create_table(table: TableCreate):
    """Create a new table"""
    try:
        table_data = Table(
            name=table.name,
            fullyQualifiedName=table.fullyQualifiedName,
            description=table.description,
            columns=[],
            database=table.database,
            databaseSchema=table.databaseSchema,
        )
        table_id = _metadata_service.ingest_table(table_data)
        return {"id": table_id, "message": "Table created successfully"}
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@app.get("/api/v1/tables", tags=["Tables"])
async def list_tables(database: Optional[str] = None, databaseSchema: Optional[str] = None):
    """List all tables"""
    filters = {}
    if database:
        filters["database"] = database
    if databaseSchema:
        filters["databaseSchema"] = databaseSchema
    
    tables = _metadata_service.list_tables(filters if filters else None)
    return {"tables": [t.model_dump() for t in tables], "count": len(tables)}


@app.get("/api/v1/tables/{qualified_name}", tags=["Tables"])
async def get_table(qualified_name: str):
    """Get table by qualified name"""
    try:
        table = _metadata_service.get_table(qualified_name)
        return table.model_dump()
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationError as e:
        # FQN 格式非法（如不含 root.child）应返回 422，否则会漏成 500
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


# ============== Database Endpoints ==============

@app.post("/api/v1/databases", status_code=status.HTTP_201_CREATED, tags=["Databases"])
async def create_database(database: DatabaseCreate):
    """Create a new database"""
    try:
        db_data = Database(
            name=database.name,
            fullyQualifiedName=database.fullyQualifiedName,
            description=database.description,
            owner=database.owner,
        )
        db_id = _metadata_service.ingest_database(db_data)
        return {"id": db_id, "message": "Database created successfully"}
    except ConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@app.get("/api/v1/databases", tags=["Databases"])
async def list_databases(owner: Optional[str] = None):
    """List all databases"""
    filters = {"owner": owner} if owner else None
    databases = _metadata_service.list_databases(filters)
    return {"databases": [d.model_dump() for d in databases], "count": len(databases)}


@app.get("/api/v1/databases/{qualified_name}", tags=["Databases"])
async def get_database(qualified_name: str):
    """Get database by qualified name"""
    try:
        database = _metadata_service.get_database(qualified_name)
        return database.model_dump()
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


# ============== Workflow Endpoints ==============

@app.post("/api/v1/workflows", status_code=status.HTTP_201_CREATED, tags=["Workflows"])
async def create_workflow(config: Dict[str, Any]):
    """Create a new workflow"""
    try:
        workflow_config = LocalWorkflowConfig.model_validate(config)
        workflow_id = _workflow_service.create_workflow(workflow_config)
        return {"id": workflow_id, "message": "Workflow created successfully"}
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@app.get("/api/v1/workflows", tags=["Workflows"])
async def list_workflows():
    """List all workflows"""
    workflows = _workflow_service.list_workflows()
    return {"workflows": [w.model_dump() for w in workflows], "count": len(workflows)}


@app.get("/api/v1/workflows/{workflow_id}", tags=["Workflows"])
async def get_workflow(workflow_id: str):
    """Get workflow by ID"""
    try:
        workflow = _workflow_service.get_workflow(workflow_id)
        return workflow.model_dump()
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@app.delete("/api/v1/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Workflows"])
async def delete_workflow(workflow_id: str):
    """Delete workflow"""
    try:
        _workflow_service.delete_workflow(workflow_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


# L3 platform routers (MOD-01 data-source management, etc.)
app.include_router(_datasource_router)
app.include_router(_scans_router)
app.include_router(_search_router)
app.include_router(_assets_router)
app.include_router(_changes_router)
app.include_router(_subscriptions_router)
app.include_router(_governance_router)
app.include_router(_permissions_router)
app.include_router(_system_router)
# ``/api/v1/tasks/partitions`` must be registered *before* the tasks router, or
# the literal path would be swallowed by ``/api/v1/tasks/{task_id}`` (422).
app.include_router(_partitions_router)
app.include_router(_tasks_router)
app.include_router(_audit_router)
app.include_router(_catalog_overview_router)
# 资产层级浏览（MOD-09 §182-183）：库 → schema → 表 → 字段。
# 与 ``_catalog_overview_router`` 共用 ``/api/v1/catalog`` 前缀但路径不重叠
# （``/overview`` vs ``/databases|/schemas|/tables|/columns``），顺序无关。
app.include_router(_catalog_browse_router)
# 分类分级（MOD-05）：分级结果此前只被 search 的 gradeMin 间接消费，
# 用户能触发分级任务却看不到结果。这组只读接口供「分级结果界面」使用。
app.include_router(_classification_router)
app.include_router(_lineage_router)
# 画像只读接口（MOD-04 / FR-M2）。只暴露查询：触发需要业务库连接与
# JobType.PROFILE 任务处理器，两者尚未接线，留待 profile/tasks.py。
app.include_router(_profiles_router)
app.include_router(_business_router)
# 降级清单（GET /api/v1/meta/degradation）会对外自曝"本产品有多少功能是占位的"，
# 仅非生产环境注册（对标 S1-9）。
if os.getenv("APP_ENV", "dev").lower() not in ("prod", "production"):
    app.include_router(_meta_router)
