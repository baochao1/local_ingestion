"""Unit tests for API routes"""

import pytest
from datetime import datetime

from local_ingestion.api.routes.handlers import (
    BaseAPI,
    HealthHandler,
    IngestionHandler,
    MetadataHandler,
)
from local_ingestion.api.routes.schemas import (
    DatabaseIngestRequest,
    DatabaseIngestResponse,
    ErrorResponse,
    HealthResponse,
    PaginationParams,
    PaginatedResponse,
    TableIngestRequest,
    TableIngestResponse,
    TableListResponse,
)
from local_ingestion.schema.data.table import Table, Column
from local_ingestion.schema.data.database import Database
from local_ingestion.schema.base import DataType


class TestHealthHandler:
    """Tests for HealthHandler"""

    def test_get_health_returns_healthy_status(self):
        """Test health endpoint returns healthy status"""
        handler = HealthHandler()
        result = handler.get_health()

        assert result["status"] == "healthy"
        assert "version" in result
        assert "timestamp" in result

    def test_get_health_has_timestamp(self):
        """Test health response includes timestamp"""
        handler = HealthHandler()
        result = handler.get_health()

        assert result["timestamp"] is not None
        assert "T" in result["timestamp"]
        assert result["timestamp"].endswith("Z")


class TestIngestionHandler:
    """Tests for IngestionHandler"""

    def test_ingest_table_success(self):
        """Test successful table ingestion"""
        handler = IngestionHandler()
        request_data = {
            "table": {
                "name": "users",
                "fullyQualifiedName": "db.schema.users",
                "database": "db",
                "databaseSchema": "schema",
            },
            "includeColumns": True,
        }

        response, status_code = handler.ingest_table(request_data)

        assert status_code == 200
        assert response["status"] == "success"
        assert response["table"]["name"] == "users"
        assert "message" in response

    def test_ingest_table_with_columns(self):
        """Test table ingestion with columns"""
        handler = IngestionHandler()
        request_data = {
            "table": {
                "name": "users",
                "fullyQualifiedName": "db.schema.users",
                "columns": [
                    {"name": "id", "dataType": "INTEGER"},
                    {"name": "name", "dataType": "STRING"},
                ],
            },
        }

        response, status_code = handler.ingest_table(request_data)

        assert status_code == 200
        assert response["table"]["columns"][0]["name"] == "id"

    def test_ingest_table_validation_error(self):
        """Test table ingestion with invalid data"""
        handler = IngestionHandler()
        request_data = {
            "table": {
                "name": "users",
                # missing required fullyQualifiedName
            },
        }

        response, status_code = handler.ingest_table(request_data)

        assert status_code == 400
        assert response["status"] == "error"
        assert response["code"] == 400

    def test_ingest_table_empty_request(self):
        """Test table ingestion with empty request"""
        handler = IngestionHandler()
        response, status_code = handler.ingest_table(None)

        assert status_code == 400
        assert response["status"] == "error"

    def test_ingest_database_success(self):
        """Test successful database ingestion"""
        handler = IngestionHandler()
        request_data = {
            "database": {
                "name": "mydb",
                "fullyQualifiedName": "mydb",
                "description": "My database",
            },
            "includeSchemas": True,
        }

        response, status_code = handler.ingest_database(request_data)

        assert status_code == 200
        assert response["status"] == "success"
        assert response["database"]["name"] == "mydb"
        assert "message" in response

    def test_ingest_database_validation_error(self):
        """Test database ingestion with invalid data"""
        handler = IngestionHandler()
        request_data = {
            "database": {
                "name": "mydb",
                # missing required fullyQualifiedName
            },
        }

        response, status_code = handler.ingest_database(request_data)

        assert status_code == 400
        assert response["status"] == "error"

    def test_get_ingested_tables(self):
        """Test retrieving ingested tables"""
        handler = IngestionHandler()
        request_data = {
            "table": {
                "name": "users",
                "fullyQualifiedName": "db.schema.users",
            },
        }
        handler.ingest_table(request_data)

        tables = handler.get_ingested_tables()
        assert len(tables) == 1
        assert tables[0].name == "users"

    def test_get_ingested_databases(self):
        """Test retrieving ingested databases"""
        handler = IngestionHandler()
        request_data = {
            "database": {
                "name": "mydb",
                "fullyQualifiedName": "mydb",
            },
        }
        handler.ingest_database(request_data)

        databases = handler.get_ingested_databases()
        assert len(databases) == 1
        assert databases[0].name == "mydb"


class TestMetadataHandler:
    """Tests for MetadataHandler"""

    def test_list_tables_empty(self):
        """Test listing tables when empty"""
        handler = MetadataHandler()
        result = handler.list_tables()

        assert result["data"] == []
        assert result["total"] == 0
        assert result["page"] == 1
        assert result["page_size"] == 10
        assert result["total_pages"] == 0

    def test_list_tables_with_pagination(self):
        """Test listing tables with pagination"""
        handler = MetadataHandler()
        for i in range(15):
            handler.add_table(
                Table(
                    name=f"table_{i}",
                    fullyQualifiedName=f"db.schema.table_{i}",
                )
            )

        result = handler.list_tables(page=1, page_size=5)

        assert len(result["data"]) == 5
        assert result["total"] == 15
        assert result["page"] == 1
        assert result["page_size"] == 5
        assert result["total_pages"] == 3

    def test_list_tables_page_2(self):
        """Test listing tables on page 2"""
        handler = MetadataHandler()
        for i in range(15):
            handler.add_table(
                Table(
                    name=f"table_{i}",
                    fullyQualifiedName=f"db.schema.table_{i}",
                )
            )

        result = handler.list_tables(page=2, page_size=5)

        assert len(result["data"]) == 5
        assert result["page"] == 2
        assert result["data"][0]["name"] == "table_5"

    def test_get_table_by_qualified_name_success(self):
        """Test getting table by qualified name"""
        handler = MetadataHandler()
        handler.add_table(
            Table(
                name="users",
                fullyQualifiedName="db.schema.users",
                database="db",
            )
        )

        response, status_code = handler.get_table_by_qualified_name("db.schema.users")

        assert status_code == 200
        assert response["name"] == "users"
        assert response["fullyQualifiedName"] == "db.schema.users"

    def test_get_table_by_qualified_name_not_found(self):
        """Test getting non-existent table"""
        handler = MetadataHandler()

        response, status_code = handler.get_table_by_qualified_name("nonexistent")

        assert status_code == 404
        assert response["status"] == "error"
        assert response["code"] == 404
        assert "not found" in response["message"].lower()

    def test_list_databases_empty(self):
        """Test listing databases when empty"""
        handler = MetadataHandler()
        result = handler.list_databases()

        assert result["data"] == []
        assert result["total"] == 0
        assert result["page"] == 1

    def test_list_databases_with_data(self):
        """Test listing databases with data"""
        handler = MetadataHandler()
        handler.add_database(
            Database(name="db1", fullyQualifiedName="db1")
        )
        handler.add_database(
            Database(name="db2", fullyQualifiedName="db2")
        )

        result = handler.list_databases()

        assert len(result["data"]) == 2
        assert result["total"] == 2

    def test_get_database_by_qualified_name_success(self):
        """Test getting database by qualified name"""
        handler = MetadataHandler()
        handler.add_database(
            Database(name="mydb", fullyQualifiedName="mydb", description="Test")
        )

        response, status_code = handler.get_database_by_qualified_name("mydb")

        assert status_code == 200
        assert response["name"] == "mydb"
        assert response["description"] == "Test"

    def test_get_database_by_qualified_name_not_found(self):
        """Test getting non-existent database"""
        handler = MetadataHandler()

        response, status_code = handler.get_database_by_qualified_name("nonexistent")

        assert status_code == 404
        assert response["status"] == "error"


class TestPaginationParams:
    """Tests for pagination validation"""

    def test_default_pagination(self):
        """Test default pagination values"""
        params = PaginationParams()
        assert params.page == 1
        assert params.page_size == 10

    def test_custom_pagination(self):
        """Test custom pagination values"""
        params = PaginationParams(page=5, page_size=25)
        assert params.page == 5
        assert params.page_size == 25

    def test_pagination_min_values(self):
        """Test minimum pagination values"""
        params = PaginationParams(page=1, page_size=1)
        assert params.page == 1
        assert params.page_size == 1

    def test_pagination_max_page_size(self):
        """Test max page_size validation"""
        params = PaginationParams(page=1, page_size=100)
        assert params.page_size == 100


class TestPaginatedResponse:
    """Tests for PaginatedResponse"""

    def test_create_paginated_response(self):
        """Test creating paginated response"""
        items = [Table(name="t1", fullyQualifiedName="t1")]
        response = PaginatedResponse.create(
            items=items,
            total=1,
            page=1,
            page_size=10,
        )

        assert response.data == items
        assert response.total == 1
        assert response.page == 1
        assert response.page_size == 10
        assert response.total_pages == 1

    def test_total_pages_calculation(self):
        """Test total pages calculation"""
        response = PaginatedResponse.create(
            items=[],
            total=25,
            page=1,
            page_size=10,
        )

        assert response.total_pages == 3

    def test_total_pages_with_exact_division(self):
        """Test total pages with exact division"""
        response = PaginatedResponse.create(
            items=[],
            total=20,
            page=1,
            page_size=10,
        )

        assert response.total_pages == 2

    def test_total_pages_empty(self):
        """Test total pages with no items"""
        response = PaginatedResponse.create(
            items=[],
            total=0,
            page=1,
            page_size=10,
        )

        assert response.total_pages == 0


class TestBaseAPI:
    """Tests for BaseAPI"""

    def test_serialize_response(self):
        """Test response serialization"""
        api = BaseAPI()
        response = HealthResponse(
            status="healthy",
            version="1.0.0",
            timestamp="2024-01-01T00:00:00Z",
        )

        result = api._serialize_response(response)

        assert result["status"] == "healthy"
        assert result["version"] == "1.0.0"

    def test_validate_pagination_defaults(self):
        """Test pagination validation with defaults"""
        api = BaseAPI()
        page, page_size = api._validate_pagination()

        assert page == 1
        assert page_size == 10

    def test_validate_pagination_custom(self):
        """Test pagination validation with custom values"""
        api = BaseAPI()
        page, page_size = api._validate_pagination(page=3, page_size=20)

        assert page == 3
        assert page_size == 20


class TestErrorResponse:
    """Tests for ErrorResponse"""

    def test_error_response_creation(self):
        """Test error response creation"""
        error = ErrorResponse(
            message="Not found",
            code=404,
        )

        assert error.status == "error"
        assert error.message == "Not found"
        assert error.code == 404
        assert error.details is None

    def test_error_response_serialization(self):
        """Test error response serialization"""
        error = ErrorResponse(
            message="Server error",
            code=500,
        )

        result = error.model_dump(mode="json")

        assert result["status"] == "error"
        assert result["message"] == "Server error"
        assert result["code"] == 500
