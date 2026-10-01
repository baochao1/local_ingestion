"""Request/Response schemas for API routes"""

from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

from local_ingestion.schema.base import StackTraceError
from local_ingestion.schema.data.database import Database
from local_ingestion.schema.data.table import Table

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """Error response schema"""
    status: str = "error"
    message: str
    code: int = 500
    details: Optional[StackTraceError] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "error",
                "message": "Resource not found",
                "code": 404,
            }
        }
    }


class HealthResponse(BaseModel):
    """Health check response schema"""
    status: str = "healthy"
    version: str = "1.0.0"
    timestamp: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "healthy",
                "version": "1.0.0",
                "timestamp": "2024-01-01T00:00:00Z",
            }
        }
    }


class TableIngestRequest(BaseModel):
    """Request schema for table ingestion"""
    table: Table
    generateSampleData: bool = False
    includeColumns: bool = True
    includeProfile: bool = True
    includeLineage: bool = False

    model_config = {
        "json_schema_extra": {
            "example": {
                "table": {
                    "name": "users",
                    "fullyQualifiedName": "db.schema.users",
                    "database": "db",
                    "databaseSchema": "schema",
                    "columns": [],
                },
                "generateSampleData": False,
                "includeColumns": True,
                "includeProfile": True,
                "includeLineage": False,
            }
        }
    }


class TableIngestResponse(BaseModel):
    """Response schema for table ingestion"""
    status: str = "success"
    table: Table
    message: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "success",
                "table": {
                    "name": "users",
                    "fullyQualifiedName": "db.schema.users",
                },
                "message": "Table ingested successfully",
            }
        }
    }


class DatabaseIngestRequest(BaseModel):
    """Request schema for database ingestion"""
    database: Database
    includeSchemas: bool = True
    includeTables: bool = True
    includeViews: bool = True

    model_config = {
        "json_schema_extra": {
            "example": {
                "database": {
                    "name": "mydb",
                    "fullyQualifiedName": "mydb",
                    "description": "My database",
                },
                "includeSchemas": True,
                "includeTables": True,
                "includeViews": True,
            }
        }
    }


class DatabaseIngestResponse(BaseModel):
    """Response schema for database ingestion"""
    status: str = "success"
    database: Database
    message: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "status": "success",
                "database": {
                    "name": "mydb",
                    "fullyQualifiedName": "mydb",
                },
                "message": "Database ingested successfully",
            }
        }
    }


class PaginationParams(BaseModel):
    """Pagination query parameters"""
    page: int = Field(default=1, ge=1, description="Page number (1-indexed)")
    page_size: int = Field(default=10, ge=1, le=100, description="Items per page")

    model_config = {
        "json_schema_extra": {
            "example": {
                "page": 1,
                "page_size": 10,
            }
        }
    }


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response schema"""
    data: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def create(
        cls,
        items: List[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        """Create a paginated response with calculated total_pages"""
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(
            data=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    model_config = {
        "json_schema_extra": {
            "example": {
                "data": [],
                "total": 0,
                "page": 1,
                "page_size": 10,
                "total_pages": 0,
            }
        }
    }


class TableListResponse(PaginatedResponse[Table]):
    """Paginated response for table list"""
    pass


class DatabaseListResponse(PaginatedResponse[Database]):
    """Paginated response for database list"""
    pass
