"""FastAPI Application for Local Ingestion"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from local_ingestion.api.service import MetadataService, WorkflowService
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager"""
    logger.info("Starting Local Ingestion API")
    yield
    logger.info("Shutting down Local Ingestion API")


app = FastAPI(
    title="Local Ingestion API",
    description="Lightweight metadata ingestion API for local development",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
