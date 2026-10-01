"""Unit tests for pipeline module"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from local_ingestion.core.pipeline.base import (
    Pipeline,
    PipelineContext,
    PipelineStatus,
    ErrorRecord,
    PipelineChainer,
)
from local_ingestion.core.pipeline.table_pipeline import (
    TablePipeline,
    TablePipelineConfig,
)
from local_ingestion.core.pipeline.database_pipeline import (
    DatabasePipeline,
    DatabasePipelineConfig,
)
from local_ingestion.core.pipeline.parallel import (
    ParallelPipeline,
    WorkerPool,
    PipelineExecutor,
    WorkerPoolConfig,
    PipelineExecutorConfig,
)
from local_ingestion.schema.data.table import Table, Column
from local_ingestion.schema.data.database import Database, DatabaseSchema
from local_ingestion.schema.base import DataType


class MockSourceConnector:
    """Mock source connector for testing"""

    def __init__(self):
        self._connected = False
        self._databases = []
        self._schemas = []
        self._tables = []

    def connect(self, config: Any) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def fetch_databases(self) -> List[Database]:
        return self._databases

    def fetch_schemas(self, database: str) -> List[DatabaseSchema]:
        return [s for s in self._schemas if s.database == database]

    def fetch_tables(self, database: str, schema: str) -> List[Table]:
        return [
            t for t in self._tables
            if t.database == database and t.databaseSchema == schema
        ]

    def fetch_columns(self, table: Table) -> List[Column]:
        return table.columns if table.columns else []


class MockSinkConnector:
    """Mock sink connector for testing"""

    def __init__(self):
        self._connected = False
        self._written_tables: List[Table] = []
        self._written_databases: List[Database] = []

    def connect(self, config: Any) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def write_table(self, table: Table) -> None:
        self._written_tables.append(table)

    def write_database(self, database: Database) -> None:
        self._written_databases.append(database)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class TestPipelineContext:
    """Tests for PipelineContext class"""

    def test_context_creation(self):
        context = PipelineContext()
        assert context.pipeline_id is not None
        assert context.status == PipelineStatus.PENDING
        assert context.tables_processed == 0
        assert context.tables_failed == 0

    def test_context_with_custom_id(self):
        custom_id = "test-pipeline-123"
        context = PipelineContext(pipeline_id=custom_id)
        assert context.pipeline_id == custom_id

    def test_start(self):
        context = PipelineContext()
        context.start()
        assert context.status == PipelineStatus.RUNNING
        assert context.start_time is not None

    def test_complete(self):
        context = PipelineContext()
        context.start()
        context.complete()
        assert context.status == PipelineStatus.COMPLETED
        assert context.end_time is not None

    def test_fail(self):
        context = PipelineContext()
        context.start()
        context.fail(ValueError("Test error"))
        assert context.status == PipelineStatus.FAILED
        assert len(context.errors) == 1
        assert context.errors[0].error == "Test error"

    def test_increment_counters(self):
        context = PipelineContext()
        context.increment_tables_processed()
        context.increment_tables_processed()
        context.increment_tables_failed()
        assert context.tables_processed == 2
        assert context.tables_failed == 1

    def test_checkpoint(self):
        context = PipelineContext()
        context.set_checkpoint("last_table", "test_table")
        assert context.get_checkpoint("last_table") == "test_table"
        assert context.get_checkpoint("nonexistent", "default") == "default"

    def test_duration_seconds(self):
        context = PipelineContext()
        context.start()
        context.end_time = datetime.now(timezone.utc)
        assert context.duration_seconds is not None
        assert context.duration_seconds >= 0

    def test_success_rate(self):
        context = PipelineContext()
        context.tables_processed = 8
        context.tables_failed = 2
        assert context.success_rate == 80.0

    def test_success_rate_zero_total(self):
        context = PipelineContext()
        assert context.success_rate == 100.0

    def test_to_dict(self):
        context = PipelineContext(pipeline_name="test_pipeline")
        context.start()
        data = context.to_dict()
        assert data["pipeline_name"] == "test_pipeline"
        assert data["status"] == "running"
        assert "start_time" in data


class TestErrorRecord:
    """Tests for ErrorRecord class"""

    def test_error_record_creation(self):
        error = ErrorRecord(
            name="TestError",
            error="Something went wrong",
            entity_name="test_table",
            entity_type="Table",
            recoverable=True,
        )
        assert error.name == "TestError"
        assert error.error == "Something went wrong"
        assert error.entity_name == "test_table"
        assert error.entity_type == "Table"
        assert error.recoverable is True


class TestTablePipelineConfig:
    """Tests for TablePipelineConfig class"""

    def test_config_defaults(self):
        config = TablePipelineConfig()
        assert config.include_tables is True
        assert config.include_views is True
        assert config.mark_deleted_tables is False
        assert config.parallel_extraction is False

    def test_should_process_table_no_filters(self):
        config = TablePipelineConfig()
        assert config.should_process_table("db", "schema", "table") is True

    def test_should_process_table_with_filter(self):
        config = TablePipelineConfig(
            database_filter={"allowed_db"},
            schema_filter={"allowed_schema"},
            table_filter={"allowed_table"},
        )
        assert config.should_process_table("allowed_db", "allowed_schema", "allowed_table") is True
        assert config.should_process_table("other_db", "allowed_schema", "allowed_table") is False
        assert config.should_process_table("allowed_db", "other_schema", "allowed_table") is False
        assert config.should_process_table("allowed_db", "allowed_schema", "other_table") is False

    def test_should_process_table_by_type(self):
        config = TablePipelineConfig(include_tables=True, include_views=False)
        assert config.should_process_table("db", "schema", "table", "VIEW") is False
        assert config.should_process_table("db", "schema", "table", "TABLE") is True


class TestTablePipeline:
    """Tests for TablePipeline class"""

    def test_table_pipeline_creation(self):
        source = MockSourceConnector()
        sink = MockSinkConnector()
        pipeline = TablePipeline(source=source, sink=sink)
        assert pipeline.source is source
        assert pipeline.sink is sink
        assert pipeline.config is not None

    def test_validate_success(self):
        source = MockSourceConnector()
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)
        pipeline = TablePipeline(source=source, sink=sink)
        assert pipeline.validate() is True

    def test_validate_source_not_connected(self):
        source = MockSourceConnector()
        sink = MockSinkConnector()
        sink.connect(None)
        pipeline = TablePipeline(source=source, sink=sink)
        assert pipeline.validate() is False

    def test_validate_sink_not_connected(self):
        source = MockSourceConnector()
        source.connect(None)
        sink = MockSinkConnector()
        pipeline = TablePipeline(source=source, sink=sink)
        assert pipeline.validate() is False

    def test_extract_no_target(self):
        source = MockSourceConnector()
        source._databases = [
            Database(name="test_db", fullyQualifiedName="test_db"),
        ]
        source._schemas = [
            DatabaseSchema(name="test_schema", fullyQualifiedName="test_db.test_schema", database="test_db"),
        ]
        source._tables = [
            Table(name="test_table", fullyQualifiedName="test_db.test_schema.test_table", database="test_db", databaseSchema="test_schema"),
        ]
        sink = MockSinkConnector()
        source.connect(None)
        sink.connect(None)

        pipeline = TablePipeline(source=source, sink=sink)
        pipeline.validate()
        tables = pipeline.extract()
        assert len(tables) == 1

    def test_run(self):
        source = MockSourceConnector()
        source._tables = [
            Table(
                name="users",
                fullyQualifiedName="db.schema.users",
                database="db",
                databaseSchema="schema",
                columns=[
                    Column(name="id", dataType=DataType.INTEGER),
                    Column(name="name", dataType=DataType.STRING),
                ],
            ),
        ]
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)

        pipeline = TablePipeline(source=source, sink=sink, database="db", schema="schema")
        context = pipeline.run()

        assert context.status == PipelineStatus.COMPLETED
        assert context.tables_processed == 1
        assert len(sink._written_tables) == 1

    def test_run_with_checkpoint(self):
        source = MockSourceConnector()
        source._tables = [
            Table(name="table1", fullyQualifiedName="db.schema.table1", database="db", databaseSchema="schema"),
            Table(name="table2", fullyQualifiedName="db.schema.table2", database="db", databaseSchema="schema"),
        ]
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)

        pipeline = TablePipeline(source=source, sink=sink, database="db", schema="schema")
        context = pipeline.run_with_checkpoint()

        assert context.status == PipelineStatus.COMPLETED
        assert context.tables_processed == 2


class TestDatabasePipelineConfig:
    """Tests for DatabasePipelineConfig class"""

    def test_config_defaults(self):
        config = DatabasePipelineConfig()
        assert config.include_tables is True
        assert config.include_views is True
        assert config.include_schemas is True
        assert config.include_databases is True
        assert config.recursive_extraction is True

    def test_should_process_database(self):
        config = DatabasePipelineConfig(database_filter={"allowed_db"})
        assert config.should_process_database("allowed_db") is True
        assert config.should_process_database("other_db") is False

    def test_should_process_schema(self):
        config = DatabasePipelineConfig(schema_filter={"allowed_schema"})
        assert config.should_process_schema("db", "allowed_schema") is True
        assert config.should_process_schema("db", "other_schema") is False


class TestDatabasePipeline:
    """Tests for DatabasePipeline class"""

    def test_database_pipeline_creation(self):
        source = MockSourceConnector()
        sink = MockSinkConnector()
        pipeline = DatabasePipeline(source=source, sink=sink)
        assert pipeline.source is source
        assert pipeline.sink is sink
        assert pipeline.config is not None

    def test_validate(self):
        source = MockSourceConnector()
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)
        pipeline = DatabasePipeline(source=source, sink=sink)
        assert pipeline.validate() is True

    def test_extract_databases(self):
        source = MockSourceConnector()
        source._databases = [
            Database(name="db1", fullyQualifiedName="db1"),
            Database(name="db2", fullyQualifiedName="db2"),
        ]
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)

        pipeline = DatabasePipeline(source=source, sink=sink)
        pipeline.validate()
        databases = pipeline.extract_databases()
        assert len(databases) == 2

    def test_extract_databases_with_filter(self):
        source = MockSourceConnector()
        source._databases = [
            Database(name="db1", fullyQualifiedName="db1"),
            Database(name="db2", fullyQualifiedName="db2"),
        ]
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)

        config = DatabasePipelineConfig(database_filter={"db1"})
        pipeline = DatabasePipeline(source=source, sink=sink, config=config)
        databases = pipeline.extract_databases()
        assert len(databases) == 1
        assert databases[0].name == "db1"

    def test_run(self):
        source = MockSourceConnector()
        source._databases = [
            Database(name="test_db", fullyQualifiedName="test_db"),
        ]
        source._schemas = [
            DatabaseSchema(name="public", fullyQualifiedName="test_db.public", database="test_db"),
        ]
        source._tables = [
            Table(
                name="users",
                fullyQualifiedName="test_db.public.users",
                database="test_db",
                databaseSchema="public",
            ),
        ]
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)

        pipeline = DatabasePipeline(source=source, sink=sink)
        context = pipeline.run()

        assert context.status == PipelineStatus.COMPLETED
        assert context.databases_processed == 1
        assert context.schemas_processed == 1
        assert context.tables_processed == 1


class TestWorkerPool:
    """Tests for WorkerPool class"""

    def test_worker_pool_creation(self):
        pool = WorkerPool()
        assert pool.config is not None
        assert pool.get_active_count() == 0

    def test_worker_pool_context_manager(self):
        with WorkerPool() as pool:
            assert pool._executor is not None
        assert pool._executor is None

    def test_submit_task(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=2))
        with pool:
            future = pool.submit("task1", lambda: 42)
            result = future.result(timeout=5)
            assert result == 42

    def test_task_completion(self):
        pool = WorkerPool(WorkerPoolConfig(max_workers=2))
        with pool:
            task_id = "task1"
            pool.submit(task_id, lambda: "done")
            assert pool.is_task_complete(task_id) is True


class TestPipelineExecutor:
    """Tests for PipelineExecutor class"""

    def test_executor_creation(self):
        executor = PipelineExecutor()
        assert executor.config is not None
        assert executor.worker_pool is not None

    def test_execute_success(self):
        source = MockSourceConnector()
        source._tables = [
            Table(name="table1", fullyQualifiedName="db.schema.table1"),
        ]
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)

        pipeline = TablePipeline(source=source, sink=sink, database="db", schema="schema")
        pipeline.validate()

        executor = PipelineExecutor()
        context = executor.execute(pipeline, use_retry=False)

        assert context.status == PipelineStatus.COMPLETED

    def test_execute_with_retry(self):
        source = MockSourceConnector()
        call_count = 0

        class FailingSourceConnector(MockSourceConnector):
            def fetch_tables(self, database: str, schema: str) -> List[Table]:
                nonlocal call_count
                call_count += 1
                if call_count < 2:
                    raise ValueError("Temporary error")
                return []

        source = FailingSourceConnector()
        source._tables = []
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)

        pipeline = TablePipeline(source=source, sink=sink, database="db", schema="schema")
        pipeline.validate()

        executor = PipelineExecutor(
            config=PipelineExecutorConfig(max_retries=3, retry_delay_seconds=0.01),
        )
        context = executor.execute(pipeline, use_retry=True)

        assert context.status == PipelineStatus.COMPLETED
        assert call_count == 2

    def test_execution_history(self):
        source = MockSourceConnector()
        source._tables = []
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)

        pipeline = TablePipeline(source=source, sink=sink, database="db", schema="schema")
        pipeline.validate()

        executor = PipelineExecutor()
        executor.execute(pipeline, use_retry=False)

        history = executor.get_execution_history()
        assert len(history) == 1
        assert history[0]["success"] is True


class TestParallelPipeline:
    """Tests for ParallelPipeline class"""

    def test_parallel_pipeline_creation(self):
        pipeline = ParallelPipeline()
        assert pipeline.name is not None
        assert len(pipeline) == 0

    def test_add_pipeline(self):
        source = MockSourceConnector()
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)

        pipeline1 = TablePipeline(source=source, sink=sink, name="pipeline1")
        pipeline2 = TablePipeline(source=source, sink=sink, name="pipeline2")

        parallel = ParallelPipeline()
        parallel.add_pipeline(pipeline1)
        parallel.add_pipeline(pipeline2)

        assert len(parallel) == 2

    def test_run_empty(self):
        parallel = ParallelPipeline()
        with pytest.raises(ValueError, match="No pipelines to execute"):
            parallel.run()


class TestPipelineChainer:
    """Tests for PipelineChainer class"""

    def test_chainer_creation(self):
        chainer = PipelineChainer()
        assert len(chainer) == 0

    def test_add_pipeline(self):
        chainer = PipelineChainer()
        source = MockSourceConnector()
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)

        pipeline = TablePipeline(source=source, sink=sink)
        chainer.add(pipeline)
        assert len(chainer) == 1

    def test_run_all(self):
        source = MockSourceConnector()
        source._tables = [
            Table(name="table1", fullyQualifiedName="db.schema.table1"),
        ]
        source.connect(None)
        sink = MockSinkConnector()
        sink.connect(None)

        pipeline1 = TablePipeline(source=source, sink=sink, database="db", schema="schema")
        chainer = PipelineChainer()
        chainer.add(pipeline1)

        contexts = chainer.run_all()
        assert len(contexts) == 1
        assert contexts[0].status == PipelineStatus.COMPLETED
