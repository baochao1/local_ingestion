"""API Route Handlers

HTTP route handlers that expose the service layer through REST endpoints.
These handlers validate requests, call the appropriate services, and format responses.
"""

from abc import ABC
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from pydantic import ValidationError

from local_ingestion.api.routes.schemas import (
    DatabaseIngestRequest,
    DatabaseIngestResponse,
    DatabaseListResponse,
    ErrorResponse,
    HealthResponse,
    PaginatedResponse,
    PaginationParams,
    TableIngestRequest,
    TableIngestResponse,
    TableListResponse,
)
from local_ingestion.schema.data.database import Database
from local_ingestion.schema.data.table import Table


class BaseAPI(ABC):
    """Base class for all API handlers

    Provides common functionality for request validation, response serialization,
    and error handling.
    """

    def __init__(self):
        self._storage: Dict[str, Any] = {}

    def _serialize_response(self, response: Any) -> Dict[str, Any]:
        """Serialize response to dict for JSON output"""
        if hasattr(response, "model_dump"):
            return response.model_dump(mode="json")
        return response

    def _serialize_error(self, error: ErrorResponse) -> Dict[str, Any]:
        """Serialize error response to dict"""
        return error.model_dump(mode="json")

    def _validate_request(
        self,
        request_data: Optional[Dict[str, Any]],
        schema: Type[Any],
    ) -> tuple[Optional[Any], Optional[ErrorResponse]]:
        """Validate request data against schema

        Args:
            request_data: The request payload to validate
            schema: Pydantic model class to validate against

        Returns:
            Tuple of (validated_data, error_response)
            If validation succeeds, error_response is None
            If validation fails, validated_data is None
        """
        if request_data is None:
            request_data = {}

        try:
            validated = schema.model_validate(request_data)
            return validated, None
        except ValidationError as e:
            error = ErrorResponse(
                status="error",
                message="Validation error",
                code=400,
            )
            return None, error

    def _validate_pagination(
        self,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> tuple[int, int]:
        """Validate and normalize pagination parameters

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page

        Returns:
            Tuple of (page, page_size) with validated values
        """
        params = PaginationParams(
            page=page if page is not None else 1,
            page_size=page_size if page_size is not None else 10,
        )
        return params.page, params.page_size


class HealthHandler(BaseAPI):
    """Handler for health check endpoints

    Provides basic health status information about the service.
    """

    VERSION = "1.0.0"

    def __init__(self):
        super().__init__()

    def get_health(self) -> Dict[str, Any]:
        """Handle GET /health request

        Returns:
            Health status response with version and timestamp
        """
        response = HealthResponse(
            status="healthy",
            version=self.VERSION,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )
        return self._serialize_response(response)


class IngestionHandler(BaseAPI):
    """Handler for data ingestion endpoints

    Processes incoming metadata for tables and databases.
    """

    def __init__(self):
        super().__init__()
        self._ingested_tables: List[Table] = []
        self._ingested_databases: List[Database] = []

    def ingest_table(
        self,
        request_data: Optional[Dict[str, Any]] = None,
    ) -> tuple[Dict[str, Any], int]:
        """Handle POST /api/v1/tables/ingest request

        Args:
            request_data: Table ingestion request data containing table metadata

        Returns:
            Tuple of (response_data, status_code)
        """
        validated_request, error = self._validate_request(
            request_data, TableIngestRequest
        )

        if error:
            return self._serialize_error(error), 400

        table = validated_request.table
        self._ingested_tables.append(table)

        response = TableIngestResponse(
            status="success",
            table=table,
            message="Table ingested successfully",
        )

        return self._serialize_response(response), 200

    def ingest_database(
        self,
        request_data: Optional[Dict[str, Any]] = None,
    ) -> tuple[Dict[str, Any], int]:
        """Handle POST /api/v1/databases/ingest request

        Args:
            request_data: Database ingestion request data containing database metadata

        Returns:
            Tuple of (response_data, status_code)
        """
        validated_request, error = self._validate_request(
            request_data, DatabaseIngestRequest
        )

        if error:
            return self._serialize_error(error), 400

        database = validated_request.database
        self._ingested_databases.append(database)

        response = DatabaseIngestResponse(
            status="success",
            database=database,
            message="Database ingested successfully",
        )

        return self._serialize_response(response), 200

    def get_ingested_tables(self) -> List[Table]:
        """Get list of ingested tables

        Returns:
            List of Table objects that have been ingested
        """
        return self._ingested_tables.copy()

    def get_ingested_databases(self) -> List[Database]:
        """Get list of ingested databases

        Returns:
            List of Database objects that have been ingested
        """
        return self._ingested_databases.copy()


class MetadataHandler(BaseAPI):
    """Handler for metadata query endpoints

    Provides read access to ingested table and database metadata.
    """

    def __init__(self):
        super().__init__()
        self._tables: List[Table] = []
        self._databases: List[Database] = []

    def list_tables(
        self,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Handle GET /api/v1/tables request

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page

        Returns:
            Paginated list of tables
        """
        page, page_size = self._validate_pagination(page, page_size)

        total = len(self._tables)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = self._tables[start:end]

        response = TableListResponse.create(
            items=page_items,
            total=total,
            page=page,
            page_size=page_size,
        )

        return self._serialize_response(response)

    def get_table_by_qualified_name(
        self,
        qualified_name: str,
    ) -> tuple[Dict[str, Any], int]:
        """Handle GET /api/v1/tables/{qualified_name} request

        Args:
            qualified_name: Table's fully qualified name

        Returns:
            Tuple of (response_data, status_code)
        """
        for table in self._tables:
            if table.fullyQualifiedName == qualified_name:
                return self._serialize_response(table), 200

        error = ErrorResponse(
            status="error",
            message=f"Table not found: {qualified_name}",
            code=404,
        )
        return self._serialize_error(error), 404

    def list_databases(
        self,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Handle GET /api/v1/databases request

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page

        Returns:
            Paginated list of databases
        """
        page, page_size = self._validate_pagination(page, page_size)

        total = len(self._databases)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = self._databases[start:end]

        response = DatabaseListResponse.create(
            items=page_items,
            total=total,
            page=page,
            page_size=page_size,
        )

        return self._serialize_response(response)

    def get_database_by_qualified_name(
        self,
        qualified_name: str,
    ) -> tuple[Dict[str, Any], int]:
        """Handle GET /api/v1/databases/{qualified_name} request

        Args:
            qualified_name: Database's fully qualified name

        Returns:
            Tuple of (response_data, status_code)
        """
        for database in self._databases:
            if database.fullyQualifiedName == qualified_name:
                return self._serialize_response(database), 200

        error = ErrorResponse(
            status="error",
            message=f"Database not found: {qualified_name}",
            code=404,
        )
        return self._serialize_error(error), 404

    def add_table(self, table: Table) -> None:
        """Add a table to the metadata store

        Args:
            table: Table object to add
        """
        self._tables.append(table)

    def add_database(self, database: Database) -> None:
        """Add a database to the metadata store

        Args:
            database: Database object to add
        """
        self._databases.append(database)

    def get_tables(self) -> List[Table]:
        """Get all tables

        Returns:
            Copy of all tables in the store
        """
        return self._tables.copy()

    def get_databases(self) -> List[Database]:
        """Get all databases

        Returns:
            Copy of all databases in the store
        """
        return self._databases.copy()
