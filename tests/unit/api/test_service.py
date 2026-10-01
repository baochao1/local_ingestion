"""Service layer unit tests"""
import pytest
from unittest.mock import MagicMock, patch
from local_ingestion.api.service import (
    MetadataService,
    WorkflowService,
    AsyncMetadataService,
    AsyncWorkflowService,
)
from local_ingestion.api.exceptions import (
    ServiceError,
    NotFoundError,
    ValidationError,
    ConflictError,
)
from local_ingestion.schema.data.table import Table, Column
from local_ingestion.schema.data.database import Database
from local_ingestion.schema.metadata.workflow import LocalWorkflowConfig, WorkflowConfig


class MockDatabase:
    """Mock database for testing"""

    def __init__(self):
        self._store: dict[str, list[dict]] = {
            "metadata_tables": [],
            "metadata_databases": [],
            "workflows": [],
        }

    def insert(self, table_name: str, data: dict) -> str:
        self._store[table_name].append(data)
        return data.get("id", "")

    def find_one(self, table_name: str, query: dict) -> dict | None:
        for item in self._store.get(table_name, []):
            if all(item.get(k) == v for k, v in query.items()):
                return item
        return None

    def find_many(self, table_name: str, query: dict) -> list[dict]:
        results = self._store.get(table_name, [])
        if not query:
            return list(results)
        return [
            item
            for item in results
            if all(item.get(k) == v for k, v in query.items())
        ]

    def delete_one(self, table_name: str, query: dict) -> bool:
        for i, item in enumerate(self._store.get(table_name, [])):
            if all(item.get(k) == v for k, v in query.items()):
                self._store[table_name].pop(i)
                return True
        return False

    def clear(self):
        for key in self._store:
            self._store[key] = []


class TestMetadataService:
    """Tests for MetadataService"""

    def setup_method(self):
        self.db = MockDatabase()
        self.service = MetadataService(self.db)

    def test_ingest_table_success(self):
        table = Table(
            name="users",
            fullyQualifiedName="prod.mysql.db1.schema1.users",
            columns=[Column(name="id", dataType="INTEGER")],
        )
        table_id = self.service.ingest_table(table)
        assert table_id is not None
        assert len(table_id) == 36

        stored = self.db.find_one("metadata_tables", {"fullyQualifiedName": table.fullyQualifiedName})
        assert stored is not None
        assert stored["name"] == "users"

    def test_ingest_table_duplicate_raises_conflict(self):
        table = Table(name="users", fullyQualifiedName="db.schema.users")
        self.service.ingest_table(table)

        with pytest.raises(ConflictError) as exc_info:
            self.service.ingest_table(table)
        assert "already exists" in str(exc_info.value)

    def test_ingest_table_empty_name_raises_validation(self):
        table = Table(name="", fullyQualifiedName="db.schema.users")
        with pytest.raises(ValidationError) as exc_info:
            self.service.ingest_table(table)
        assert "name is required" in str(exc_info.value)

    def test_ingest_table_empty_fqn_raises_validation(self):
        table = Table(name="users", fullyQualifiedName="")
        with pytest.raises(ValidationError) as exc_info:
            self.service.ingest_table(table)
        assert "fullyQualifiedName is required" in str(exc_info.value)

    def test_ingest_table_invalid_fqn_format(self):
        table = Table(name="users", fullyQualifiedName="invalid")
        with pytest.raises(ValidationError) as exc_info:
            self.service.ingest_table(table)
        assert "at least root.child" in str(exc_info.value)

    def test_ingest_database_success(self):
        database = Database(
            name="db1",
            fullyQualifiedName="prod.mysql.db1",
        )
        db_id = self.service.ingest_database(database)
        assert db_id is not None

        stored = self.db.find_one("metadata_databases", {"fullyQualifiedName": database.fullyQualifiedName})
        assert stored is not None
        assert stored["name"] == "db1"

    def test_ingest_database_duplicate_raises_conflict(self):
        database = Database(name="db1", fullyQualifiedName="prod.db1")
        self.service.ingest_database(database)

        with pytest.raises(ConflictError):
            self.service.ingest_database(database)

    def test_get_table_success(self):
        table = Table(name="users", fullyQualifiedName="db.schema.users")
        self.service.ingest_table(table)

        result = self.service.get_table("db.schema.users")
        assert result.name == "users"

    def test_get_table_not_found(self):
        with pytest.raises(NotFoundError) as exc_info:
            self.service.get_table("nonexistent.schema.table")
        assert "not found" in str(exc_info.value)

    def test_get_database_success(self):
        database = Database(name="db1", fullyQualifiedName="prod.db1")
        self.service.ingest_database(database)

        result = self.service.get_database("prod.db1")
        assert result.name == "db1"

    def test_get_database_not_found(self):
        with pytest.raises(NotFoundError):
            self.service.get_database("nonexistent.db")

    def test_list_tables_empty(self):
        results = self.service.list_tables()
        assert results == []

    def test_list_tables_with_data(self):
        table1 = Table(name="users", fullyQualifiedName="db.schema.users")
        table2 = Table(name="orders", fullyQualifiedName="db.schema.orders")
        self.service.ingest_table(table1)
        self.service.ingest_table(table2)

        results = self.service.list_tables()
        assert len(results) == 2

    def test_list_tables_with_filters(self):
        table1 = Table(name="users", fullyQualifiedName="db.schema.users", database="db")
        table2 = Table(name="orders", fullyQualifiedName="db.schema.orders", database="db")
        self.service.ingest_table(table1)
        self.service.ingest_table(table2)

        results = self.service.list_tables({"database": "db"})
        assert len(results) == 2

    def test_list_tables_invalid_filter_key(self):
        with pytest.raises(ValidationError) as exc_info:
            self.service.list_tables({"invalid_key": "value"})
        assert "Invalid filter key" in str(exc_info.value)

    def test_list_databases_empty(self):
        results = self.service.list_databases()
        assert results == []

    def test_list_databases_with_data(self):
        db1 = Database(name="db1", fullyQualifiedName="prod.db1")
        db2 = Database(name="db2", fullyQualifiedName="prod.db2")
        self.service.ingest_database(db1)
        self.service.ingest_database(db2)

        results = self.service.list_databases()
        assert len(results) == 2


class TestWorkflowService:
    """Tests for WorkflowService"""

    def setup_method(self):
        self.db = MockDatabase()
        self.service = WorkflowService(self.db)

    def test_create_workflow_success(self):
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test-workflow"),
            source={"type": "mysql", "serviceName": "prod"},
            sink={"type": "file", "config": {"outputPath": "./output"}},
        )
        workflow_id = self.service.create_workflow(config)
        assert workflow_id is not None
        assert len(workflow_id) == 36

    def test_create_workflow_missing_source(self):
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={},
            sink={"type": "file"},
        )
        with pytest.raises(ValidationError) as exc_info:
            self.service.create_workflow(config)
        assert "source" in str(exc_info.value).lower()

    def test_create_workflow_missing_sink(self):
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={},
        )
        with pytest.raises(ValidationError) as exc_info:
            self.service.create_workflow(config)
        assert "sink" in str(exc_info.value).lower()

    def test_get_workflow_success(self):
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        workflow_id = self.service.create_workflow(config)

        result = self.service.get_workflow(workflow_id)
        assert result.workflowConfig.pipelineName == "test"

    def test_get_workflow_not_found(self):
        fake_id = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(NotFoundError):
            self.service.get_workflow(fake_id)

    def test_get_workflow_invalid_id_format(self):
        with pytest.raises(ValidationError) as exc_info:
            self.service.get_workflow("not-a-uuid")
        assert "Invalid workflow ID format" in str(exc_info.value)

    def test_list_workflows_empty(self):
        results = self.service.list_workflows()
        assert results == []

    def test_list_workflows_with_data(self):
        config1 = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="workflow1"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        config2 = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="workflow2"),
            source={"type": "postgres"},
            sink={"type": "file"},
        )
        self.service.create_workflow(config1)
        self.service.create_workflow(config2)

        results = self.service.list_workflows()
        assert len(results) == 2

    def test_delete_workflow_success(self):
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        workflow_id = self.service.create_workflow(config)

        result = self.service.delete_workflow(workflow_id)
        assert result is True

        with pytest.raises(NotFoundError):
            self.service.get_workflow(workflow_id)

    def test_delete_workflow_not_found(self):
        fake_id = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(NotFoundError):
            self.service.delete_workflow(fake_id)


class TestExceptions:
    """Tests for exception classes"""

    def test_service_error_to_dict(self):
        error = ServiceError("Test error", {"key": "value"})
        result = error.to_dict()
        assert result["error"] == "ServiceError"
        assert result["message"] == "Test error"
        assert result["details"] == {"key": "value"}

    def test_not_found_error(self):
        error = NotFoundError("Table", "db.schema.users")
        assert "not found" in str(error.message).lower()
        assert error.details["resource_type"] == "Table"
        assert error.details["resource_id"] == "db.schema.users"

    def test_validation_error_with_field(self):
        error = ValidationError("Invalid input", field="name")
        assert error.details["field"] == "name"

    def test_conflict_error(self):
        error = ConflictError("Table", "db.schema.users")
        assert "already exists" in str(error.message).lower()


class TestAsyncServices:
    """Tests for async service wrappers"""

    @pytest.mark.asyncio
    async def test_async_metadata_service_ingest_table(self):
        db = MockDatabase()
        service = AsyncMetadataService(db)
        table = Table(name="users", fullyQualifiedName="db.schema.users")

        result = await service.ingest_table(table)
        assert result is not None

    @pytest.mark.asyncio
    async def test_async_workflow_service_create(self):
        db = MockDatabase()
        service = AsyncWorkflowService(db)
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )

        result = await service.create_workflow(config)
        assert result is not None

    @pytest.mark.asyncio
    async def test_async_list_tables(self):
        db = MockDatabase()
        service = AsyncMetadataService(db)
        table = Table(name="users", fullyQualifiedName="db.schema.users")
        await service.ingest_table(table)

        results = await service.list_tables()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_async_get_workflow(self):
        db = MockDatabase()
        service = AsyncWorkflowService(db)
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        workflow_id = await service.create_workflow(config)

        result = await service.get_workflow(workflow_id)
        assert result.workflowConfig.pipelineName == "test"
