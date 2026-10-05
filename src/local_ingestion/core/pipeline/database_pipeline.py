"""Database pipeline for extracting database, schema, and table metadata"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import structlog

from local_ingestion.core.connectors.base import SourceConnector, SinkConnector
from local_ingestion.core.pipeline.base import Pipeline, PipelineContext, PipelineStatus
from local_ingestion.core.pipeline.table_pipeline import TablePipeline, TablePipelineConfig
from local_ingestion.platform.dialect import UnknownDialectError, get_dialect
from local_ingestion.schema.base import DataType
from local_ingestion.schema.data.database import Database, DatabaseSchema
from local_ingestion.schema.data.table import Table

logger = structlog.get_logger()


@dataclass
class DatabasePipelineConfig:
    """Configuration for database pipeline"""

    include_tables: bool = True
    include_views: bool = True
    include_schemas: bool = True
    include_databases: bool = True
    mark_deleted_tables: bool = False
    recursive_extraction: bool = True
    database_filter: Optional[Set[str]] = None
    schema_filter: Optional[Set[str]] = None
    parallel_schemas: bool = False
    max_workers: int = 4
    retry_attempts: int = 3
    # ds_type drives the T-114 dialect used by the default transform hook.
    ds_type: str = "postgres"

    def should_process_database(self, database: str) -> bool:
        """Check if database should be processed based on filters

        Args:
            database: Database name

        Returns:
            True if database should be processed
        """
        if self.database_filter and database not in self.database_filter:
            return False
        return True

    def should_process_schema(self, database: str, schema: str) -> bool:
        """Check if schema should be processed based on filters

        Args:
            database: Database name
            schema: Schema name

        Returns:
            True if schema should be processed
        """
        if self.schema_filter and schema not in self.schema_filter:
            return False
        return True


class DatabasePipeline(Pipeline):
    """Pipeline for extracting complete database metadata including schemas and tables"""

    def __init__(
        self,
        source: SourceConnector,
        sink: SinkConnector,
        config: Optional[DatabasePipelineConfig] = None,
        name: Optional[str] = None,
        database: Optional[str] = None,
        transformer: Optional[Any] = None,
    ):
        super().__init__(source=source, sink=sink, name=name)
        self.config = config or DatabasePipelineConfig()
        self.target_database = database
        self._dialect = self._resolve_dialect()
        # Hook applied to every table before it reaches the sink (MOD-02 §7.1-2).
        # Defaults to the dialect-based type normaliser; inject a callable for
        # other processing logic so it is never silently bypassed.
        self.transformer = transformer or self._default_transform
        self._table_pipeline: Optional[TablePipeline] = None

    def _resolve_dialect(self):
        try:
            return get_dialect(self.config.ds_type)
        except UnknownDialectError:
            logger.warning(
                "dialect_unknown_for_transform",
                ds_type=self.config.ds_type,
            )
            return None

    def _default_transform(self, table: Table) -> Table:
        """Default transform: recover UNKNOWN column types via the T-114 dialect.

        Mirrors the normalisation PostgresSink performs, applied centrally so the
        pipeline owns type canonicalisation rather than relying on the sink.
        """
        if self._dialect is None or not table.columns:
            return table
        for col in table.columns:
            dt = col.dataType
            if (
                dt == DataType.UNKNOWN or str(dt).upper() == "UNKNOWN"
            ) and col.dataTypeDisplay:
                try:
                    col.dataType = self._dialect.normalize_type(col.dataTypeDisplay)
                except Exception:  # noqa: BLE001
                    pass
        return table

    def validate(self) -> bool:
        """Validate pipeline configuration and connectivity

        Returns:
            True if pipeline is valid
        """
        if not self.source.is_connected():
            logger.error(
                "source_not_connected",
                pipeline=self.name,
            )
            return False

        if not self.sink.is_connected():
            logger.error(
                "sink_not_connected",
                pipeline=self.name,
            )
            return False

        self._validate_called = True
        logger.info(
            "database_pipeline_validation_passed",
            pipeline=self.name,
            database=self.target_database,
        )
        return True

    def _push_deletion_flag(self, enabled: bool) -> None:
        """Propagate ``mark_deleted_tables`` to the sink, if it understands it.

        The switch lives on :class:`DatabasePipelineConfig`, but the actual
        soft-delete is performed by the sink — which is injected and
        platform-specific. Instead of importing it here (L1 must not depend on
        the platform layer), any sink exposing ``set_mark_deleted_tables`` is
        driven through that; sinks without it are left untouched.
        """
        setter = getattr(self.sink, "set_mark_deleted_tables", None)
        if callable(setter):
            setter(enabled)

    def _get_table_pipeline(self) -> TablePipeline:
        """Get or create table pipeline instance

        Returns:
            TablePipeline instance
        """
        if self._table_pipeline is None:
            table_config = TablePipelineConfig(
                include_tables=self.config.include_tables,
                include_views=self.config.include_views,
                mark_deleted_tables=self.config.mark_deleted_tables,
                database_filter=self.config.database_filter,
                schema_filter=self.config.schema_filter,
                parallel_extraction=self.config.parallel_schemas,
                max_workers=self.config.max_workers,
                retry_attempts=self.config.retry_attempts,
            )
            self._table_pipeline = TablePipeline(
                source=self.source,
                sink=self.sink,
                config=table_config,
                database=self.target_database,
            )
        return self._table_pipeline

    def extract_databases(self) -> List[Database]:
        """Extract all databases from source

        Returns:
            List of Database objects
        """
        databases = []
        if self.target_database:
            databases.append(
                Database(
                    name=self.target_database,
                    fullyQualifiedName=self.target_database,
                )
            )
        else:
            databases = self.source.fetch_databases()

        filtered_databases = [
            db for db in databases
            if self.config.should_process_database(db.name)
        ]

        logger.info(
            "extracted_databases",
            total=len(databases),
            filtered=len(filtered_databases),
        )
        return filtered_databases

    def extract_schemas(self, database: str) -> List[DatabaseSchema]:
        """Extract all schemas from a database

        Args:
            database: Database name

        Returns:
            List of DatabaseSchema objects
        """
        schemas = self.source.fetch_schemas(database)

        filtered_schemas = [
            schema for schema in schemas
            if self.config.should_process_schema(database, schema.name)
        ]

        logger.info(
            "extracted_schemas",
            database=database,
            total=len(schemas),
            filtered=len(filtered_schemas),
        )
        return filtered_schemas

    def extract(self) -> Dict[str, Any]:
        """Extract complete database metadata

        Returns:
            Dictionary containing databases, schemas, and tables
        """
        result: Dict[str, Any] = {
            "databases": [],
            "schemas": [],
            "tables": [],
        }

        databases = self.extract_databases()
        for db in databases:
            result["databases"].append(db)
            if self.config.include_schemas and self.config.recursive_extraction:
                schemas = self.extract_schemas(db.name)
                for schema in schemas:
                    result["schemas"].append(schema)

        logger.info(
            "database_extraction_complete",
            databases=len(result["databases"]),
            schemas=len(result["schemas"]),
        )
        return result

    def run(self) -> PipelineContext:
        """Execute the database extraction pipeline

        Returns:
            PipelineContext with execution results
        """
        if not self._validate_called:
            if not self.validate():
                raise RuntimeError("Pipeline validation failed")

        with self.execution_context() as context:
            # Full scan: every in-scope entity was seen, so absence = deletion.
            self._push_deletion_flag(self.config.mark_deleted_tables)
            metadata = self.extract()

            for db in metadata["databases"]:
                try:
                    self.sink.write_database(db)
                    context.increment_databases_processed()
                except Exception as e:
                    context.add_error(
                        name=type(e).__name__,
                        error=str(e),
                        entity_name=db.name,
                        entity_type="Database",
                        recoverable=True,
                    )
                    context.increment_databases_failed()

            if self.config.recursive_extraction:
                self._extract_tables_with_context(context)

            self.sink.flush()

        return context

    def _extract_tables_with_context(self, context: PipelineContext) -> None:
        """Extract tables with context tracking

        Args:
            context: Pipeline context for tracking progress
        """
        databases = self.extract_databases()

        for db in databases:
            schemas = self.extract_schemas(db.name)

            for schema in schemas:
                try:
                    tables = self.source.fetch_tables(db.name, schema.name)
                    for table in tables:
                        try:
                            table.columns = self.source.fetch_columns(table)
                            table = self.transformer(table)
                            self.sink.write_table(table)
                            context.increment_tables_processed()
                        except Exception as e:
                            context.add_error(
                                name=type(e).__name__,
                                error=str(e),
                                entity_name=table.name,
                                entity_type="Table",
                                recoverable=True,
                            )
                            context.increment_tables_failed()
                    context.increment_schemas_processed()
                except Exception as e:
                    context.add_error(
                        name=type(e).__name__,
                        error=str(e),
                        entity_name=schema.name,
                        entity_type="Schema",
                        recoverable=True,
                    )
                    context.increment_schemas_failed()

    def run_incremental(
        self,
        previous_state: Optional[Dict[str, Any]] = None,
    ) -> PipelineContext:
        """Execute pipeline incrementally, processing only changes

        Args:
            previous_state: Previous pipeline state for comparison

        Returns:
            PipelineContext with execution results
        """
        if not self._validate_called:
            if not self.validate():
                raise RuntimeError("Pipeline validation failed")

        with self.execution_context() as context:
            current_metadata = self.extract()

            if previous_state:
                # Only the changed subset ever reaches the sink, so "absent"
                # here means "not part of this change set" — never "deleted".
                # Marking deletions would wipe everything untouched by the diff.
                self._push_deletion_flag(False)
                changes = self._detect_changes(current_metadata, previous_state)
                self._process_changes(context, changes)
            else:
                self._push_deletion_flag(self.config.mark_deleted_tables)
                self._extract_tables_with_context(context)

            self.sink.flush()

        return context

    def _detect_changes(
        self,
        current: Dict[str, Any],
        previous: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Detect changes between current and previous metadata states

        Args:
            current: Current metadata
            previous: Previous metadata state

        Returns:
            Dictionary of detected changes
        """
        changes: Dict[str, Any] = {
            "added_tables": [],
            "modified_tables": [],
            "deleted_tables": [],
        }

        prev_tables = {
            t["fullyQualifiedName"]: t for t in previous.get("tables", [])
        }
        curr_tables = {
            t.fullyQualifiedName: t for t in current.get("tables", [])
        }

        for fqn, table in curr_tables.items():
            if fqn not in prev_tables:
                changes["added_tables"].append(table)
            else:
                if self._table_changed(table, prev_tables[fqn]):
                    changes["modified_tables"].append(table)

        for fqn in prev_tables:
            if fqn not in curr_tables:
                changes["deleted_tables"].append(fqn)

        logger.info(
            "changes_detected",
            added=len(changes["added_tables"]),
            modified=len(changes["modified_tables"]),
            deleted=len(changes["deleted_tables"]),
        )
        return changes

    def _table_changed(
        self,
        current_table: Any,
        previous_table: Dict[str, Any],
    ) -> bool:
        """Check if table has changed

        Args:
            current_table: Current table object
            previous_table: Previous table state

        Returns:
            True if table has changed
        """
        if current_table.description != previous_table.get("description"):
            return True
        if len(current_table.columns) != len(previous_table.get("columns", [])):
            return True
        return False

    def _process_changes(
        self,
        context: PipelineContext,
        changes: Dict[str, Any],
    ) -> None:
        """Process detected changes

        Args:
            context: Pipeline context
            changes: Dictionary of changes
        """
        for table in changes.get("added_tables", []):
            try:
                table = self.transformer(table)
                self.sink.write_table(table)
                context.increment_tables_processed()
            except Exception as e:
                context.add_error(
                    name=type(e).__name__,
                    error=str(e),
                    entity_name=table.name,
                    entity_type="Table",
                    recoverable=True,
                )
                context.increment_tables_failed()

        for table in changes.get("modified_tables", []):
            try:
                table = self.transformer(table)
                self.sink.write_table(table)
                context.increment_tables_processed()
            except Exception as e:
                context.add_error(
                    name=type(e).__name__,
                    error=str(e),
                    entity_name=table.name,
                    entity_type="Table",
                    recoverable=True,
                )
                context.increment_tables_failed()

        logger.info(
            "changes_processed",
            processed=context.tables_processed,
            failed=context.tables_failed,
        )
