"""API Service layer for metadata and workflow operations"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Protocol, Callable

from local_ingestion.api.exceptions import (
    ServiceError,
    NotFoundError,
    ValidationError,
    ConflictError,
)
from local_ingestion.schema.data.table import Table
from local_ingestion.schema.data.database import Database
from local_ingestion.schema.metadata.workflow import LocalWorkflowConfig

logger = logging.getLogger(__name__)


class DatabaseConnection(Protocol):
    """Protocol for database connection"""

    def insert(self, table_name: str, data: dict) -> str: ...
    def find_one(self, table_name: str, query: dict) -> dict | None: ...
    def find_many(self, table_name: str, query: dict) -> list[dict]: ...
    def delete_one(self, table_name: str, query: dict) -> bool: ...


class MetadataService:
    """Service for metadata operations"""

    def __init__(self, db: DatabaseConnection):
        self._db = db
        self._table_name = "metadata_tables"
        self._db_table_name = "metadata_databases"

    def ingest_table(self, table: Table) -> str:
        """Ingest table metadata"""
        self._validate_table(table)
        self._validate_fully_qualified_name(table.fullyQualifiedName)

        existing = self._db.find_one(
            self._table_name, {"fullyQualifiedName": table.fullyQualifiedName}
        )
        if existing:
            raise ConflictError("Table", table.fullyQualifiedName)

        table_id = str(uuid.uuid4())
        data = table.model_dump()
        data["id"] = table_id

        logger.info("Ingesting table", table_fqn=table.fullyQualifiedName)
        self._db.insert(self._table_name, data)

        return table_id

    def ingest_database(self, database: Database) -> str:
        """Ingest database metadata"""
        self._validate_database(database)
        self._validate_fully_qualified_name(database.fullyQualifiedName)

        existing = self._db.find_one(
            self._db_table_name, {"fullyQualifiedName": database.fullyQualifiedName}
        )
        if existing:
            raise ConflictError("Database", database.fullyQualifiedName)

        database_id = str(uuid.uuid4())
        data = database.model_dump()
        data["id"] = database_id

        logger.info("Ingesting database", db_fqn=database.fullyQualifiedName)
        self._db.insert(self._db_table_name, data)

        return database_id

    def get_table(self, qualified_name: str) -> Table:
        """Get table by qualified name"""
        self._validate_fully_qualified_name(qualified_name)

        logger.debug("Getting table", table_fqn=qualified_name)
        result = self._db.find_one(self._table_name, {"fullyQualifiedName": qualified_name})

        if not result:
            raise NotFoundError("Table", qualified_name)

        return Table.model_validate(result)

    def get_database(self, qualified_name: str) -> Database:
        """Get database by qualified name"""
        self._validate_fully_qualified_name(qualified_name)

        logger.debug("Getting database", db_fqn=qualified_name)
        result = self._db.find_one(
            self._db_table_name, {"fullyQualifiedName": qualified_name}
        )

        if not result:
            raise NotFoundError("Database", qualified_name)

        return Database.model_validate(result)

    def list_tables(self, filters: dict | None = None) -> list[Table]:
        """List tables with filtering"""
        filters = filters or {}

        self._validate_filters(filters)

        logger.debug("Listing tables", filters=filters)
        results = self._db.find_many(self._table_name, filters)

        return [Table.model_validate(r) for r in results]

    def list_databases(self, filters: dict | None = None) -> list[Database]:
        """List databases with filtering"""
        filters = filters or {}

        self._validate_filters(filters)

        logger.debug("Listing databases", filters=filters)
        results = self._db.find_many(self._db_table_name, filters)

        return [Database.model_validate(r) for r in results]

    def _validate_table(self, table: Table) -> None:
        """Validate table input"""
        if not table.name:
            raise ValidationError("Table name is required", field="name")
        if not table.fullyQualifiedName:
            raise ValidationError("Table fullyQualifiedName is required", field="fullyQualifiedName")

    def _validate_database(self, database: Database) -> None:
        """Validate database input"""
        if not database.name:
            raise ValidationError("Database name is required", field="name")
        if not database.fullyQualifiedName:
            raise ValidationError(
                "Database fullyQualifiedName is required", field="fullyQualifiedName"
            )

    def _validate_fully_qualified_name(self, fqn: str) -> None:
        """Validate fully qualified name format"""
        if not fqn or not isinstance(fqn, str):
            raise ValidationError(
                "Fully qualified name must be a non-empty string",
                field="fullyQualifiedName",
            )
        if len(fqn.split(".")) < 2:
            raise ValidationError(
                "Fully qualified name must contain at least root.child",
                field="fullyQualifiedName",
            )

    def _validate_filters(self, filters: dict) -> None:
        """Validate filter parameters"""
        allowed_keys = {"name", "database", "databaseSchema", "tags", "owner"}
        for key in filters:
            if key not in allowed_keys:
                raise ValidationError(
                    f"Invalid filter key: {key}",
                    field="filters",
                )


class WorkflowService:
    """Service for workflow operations"""

    def __init__(self, db: DatabaseConnection):
        self._db = db
        self._table_name = "workflows"

    def create_workflow(self, config: LocalWorkflowConfig) -> str:
        """Create a new workflow"""
        self._validate_workflow_config(config)

        workflow_id = str(uuid.uuid4())
        data = config.model_dump()
        data["id"] = workflow_id
        data["status"] = "created"

        logger.info("Creating workflow", pipeline=config.workflowConfig.pipelineName)
        self._db.insert(self._table_name, data)

        return workflow_id

    def get_workflow(self, workflow_id: str) -> LocalWorkflowConfig:
        """Get workflow by ID"""
        self._validate_workflow_id(workflow_id)

        logger.debug("Getting workflow", workflow_id=workflow_id)
        result = self._db.find_one(self._table_name, {"id": workflow_id})

        if not result:
            raise NotFoundError("Workflow", workflow_id)

        return LocalWorkflowConfig.model_validate(result)

    def list_workflows(self) -> list[LocalWorkflowConfig]:
        """List all workflows"""
        logger.debug("Listing workflows")
        results = self._db.find_many(self._table_name, {})

        return [LocalWorkflowConfig.model_validate(r) for r in results]

    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete workflow"""
        self._validate_workflow_id(workflow_id)

        logger.info("Deleting workflow", workflow_id=workflow_id)
        result = self._db.delete_one(self._table_name, {"id": workflow_id})

        if not result:
            raise NotFoundError("Workflow", workflow_id)

        return True

    def _validate_workflow_config(self, config: LocalWorkflowConfig) -> None:
        """Validate workflow configuration"""
        if not config.source:
            raise ValidationError("Workflow source configuration is required", field="source")
        if not config.sink:
            raise ValidationError("Workflow sink configuration is required", field="sink")

    def _validate_workflow_id(self, workflow_id: str) -> None:
        """Validate workflow ID format"""
        if not workflow_id or not isinstance(workflow_id, str):
            raise ValidationError(
                "Workflow ID must be a non-empty string",
                field="workflow_id",
            )
        try:
            uuid.UUID(workflow_id)
        except ValueError:
            raise ValidationError(
                "Invalid workflow ID format",
                field="workflow_id",
            )


class AsyncMetadataService:
    """Async version of MetadataService for future async operations"""

    def __init__(self, db: DatabaseConnection):
        self._sync_service = MetadataService(db)

    async def ingest_table(self, table: Table) -> str:
        """Async ingest table metadata"""
        return self._sync_service.ingest_table(table)

    async def ingest_database(self, database: Database) -> str:
        """Async ingest database metadata"""
        return self._sync_service.ingest_database(database)

    async def get_table(self, qualified_name: str) -> Table:
        """Async get table by qualified name"""
        return self._sync_service.get_table(qualified_name)

    async def get_database(self, qualified_name: str) -> Database:
        """Async get database by qualified name"""
        return self._sync_service.get_database(qualified_name)

    async def list_tables(self, filters: dict | None = None) -> list[Table]:
        """Async list tables with filtering"""
        return self._sync_service.list_tables(filters)

    async def list_databases(self, filters: dict | None = None) -> list[Database]:
        """Async list databases with filtering"""
        return self._sync_service.list_databases(filters)


class AsyncWorkflowService:
    """Async version of WorkflowService for future async operations"""

    def __init__(self, db: DatabaseConnection):
        self._sync_service = WorkflowService(db)

    async def create_workflow(self, config: LocalWorkflowConfig) -> str:
        """Async create a new workflow"""
        return self._sync_service.create_workflow(config)

    async def get_workflow(self, workflow_id: str) -> LocalWorkflowConfig:
        """Async get workflow by ID"""
        return self._sync_service.get_workflow(workflow_id)

    async def list_workflows(self) -> list[LocalWorkflowConfig]:
        """Async list all workflows"""
        return self._sync_service.list_workflows()

    async def delete_workflow(self, workflow_id: str) -> bool:
        """Async delete workflow"""
        return self._sync_service.delete_workflow(workflow_id)
