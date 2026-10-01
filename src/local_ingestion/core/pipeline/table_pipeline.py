"""Table pipeline for extracting table metadata"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import structlog

from local_ingestion.core.connectors.base import SourceConnector, SinkConnector
from local_ingestion.core.pipeline.base import Pipeline, PipelineContext, PipelineStatus
from local_ingestion.schema.data.table import Table

logger = structlog.get_logger()


@dataclass
class TablePipelineConfig:
    """Configuration for table pipeline"""

    include_tables: bool = True
    include_views: bool = True
    mark_deleted_tables: bool = False
    database_filter: Optional[Set[str]] = None
    schema_filter: Optional[Set[str]] = None
    table_filter: Optional[Set[str]] = None
    parallel_extraction: bool = False
    max_workers: int = 4
    retry_attempts: int = 3

    def should_process_table(
        self,
        database: str,
        schema: str,
        table_name: str,
        table_type: Optional[str] = None,
    ) -> bool:
        """Check if table should be processed based on filters

        Args:
            database: Database name
            schema: Schema name
            table_name: Table name
            table_type: Optional table type (TABLE or VIEW)

        Returns:
            True if table should be processed
        """
        if self.database_filter and database not in self.database_filter:
            return False

        if self.schema_filter and schema not in self.schema_filter:
            return False

        if self.table_filter and table_name not in self.table_filter:
            return False

        if table_type:
            if table_type.upper() == "VIEW" and not self.include_views:
                return False
            if table_type.upper() in ("TABLE", "BASE TABLE") and not self.include_tables:
                return False

        return True


class TablePipeline(Pipeline):
    """Pipeline for extracting table metadata from a source to a sink"""

    def __init__(
        self,
        source: SourceConnector,
        sink: SinkConnector,
        config: Optional[TablePipelineConfig] = None,
        name: Optional[str] = None,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        table: Optional[str] = None,
    ):
        super().__init__(source=source, sink=sink, name=name)
        self.config = config or TablePipelineConfig()
        self.target_database = database
        self.target_schema = schema
        self.target_table = table

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
            "pipeline_validation_passed",
            pipeline=self.name,
            database=self.target_database,
            schema=self.target_schema,
        )
        return True

    def extract(self) -> List[Table]:
        """Extract tables from source

        Returns:
            List of Table objects
        """
        tables: List[Table] = []

        if self.target_table:
            return self._extract_single_table()
        elif self.target_schema:
            return self._extract_schema_tables()
        elif self.target_database:
            return self._extract_database_tables()
        else:
            return self._extract_all_tables()

    def _extract_single_table(self) -> List[Table]:
        """Extract a single table"""
        tables = []
        if self.target_database and self.target_schema and self.target_table:
            table_list = self.source.fetch_tables(
                self.target_database,
                self.target_schema,
            )
            for tbl in table_list:
                if tbl.name == self.target_table:
                    tbl.columns = self.source.fetch_columns(tbl)
                    tables.append(tbl)
        return tables

    def _extract_schema_tables(self) -> List[Table]:
        """Extract all tables from a schema"""
        tables = []
        if self.target_database and self.target_schema:
            table_list = self.source.fetch_tables(
                self.target_database,
                self.target_schema,
            )
            for tbl in table_list:
                if self.config.should_process_table(
                    self.target_database,
                    self.target_schema,
                    tbl.name,
                    tbl.tableType,
                ):
                    tbl.columns = self.source.fetch_columns(tbl)
                    tables.append(tbl)
        return tables

    def _extract_database_tables(self) -> List[Table]:
        """Extract all tables from a database"""
        tables = []
        if self.target_database:
            schemas = self.source.fetch_schemas(self.target_database)
            for schema in schemas:
                schema_tables = self.source.fetch_tables(
                    self.target_database,
                    schema.name,
                )
                for tbl in schema_tables:
                    if self.config.should_process_table(
                        self.target_database,
                        schema.name,
                        tbl.name,
                        tbl.tableType,
                    ):
                        tbl.columns = self.source.fetch_columns(tbl)
                        tables.append(tbl)
        return tables

    def _extract_all_tables(self) -> List[Table]:
        """Extract all tables from all databases"""
        tables = []
        databases = self.source.fetch_databases()
        for db in databases:
            schemas = self.source.fetch_schemas(db.name)
            for schema in schemas:
                schema_tables = self.source.fetch_tables(db.name, schema.name)
                for tbl in schema_tables:
                    if self.config.should_process_table(
                        db.name,
                        schema.name,
                        tbl.name,
                        tbl.tableType,
                    ):
                        try:
                            tbl.columns = self.source.fetch_columns(tbl)
                            tables.append(tbl)
                        except Exception as e:
                            logger.warning(
                                "failed_to_fetch_columns",
                                table=tbl.name,
                                error=str(e),
                            )
        return tables

    def transform(self, tables: List[Table]) -> List[Table]:
        """Transform extracted tables (default implementation - can be overridden)

        Args:
            tables: List of extracted tables

        Returns:
            Transformed list of tables
        """
        return tables

    def load(self, tables: List[Table]) -> int:
        """Load tables to sink

        Args:
            tables: List of tables to write

        Returns:
            Number of tables successfully written
        """
        written_count = 0
        for table in tables:
            try:
                self.sink.write_table(table)
                written_count += 1
            except Exception as e:
                logger.error(
                    "failed_to_write_table",
                    table=table.name,
                    error=str(e),
                )
                raise
        return written_count

    def run(self) -> PipelineContext:
        """Execute the table extraction pipeline

        Returns:
            PipelineContext with execution results
        """
        if not self._validate_called:
            if not self.validate():
                raise RuntimeError("Pipeline validation failed")

        with self.execution_context() as context:
            tables = self.extract()
            transformed_tables = self.transform(tables)
            written_count = self.load(transformed_tables)

            context.tables_processed = written_count
            context.tables_failed = len(tables) - written_count

        return context

    def run_with_checkpoint(self) -> PipelineContext:
        """Execute pipeline with checkpoint support for resume capability

        Returns:
            PipelineContext with execution results
        """
        if not self._validate_called:
            if not self.validate():
                raise RuntimeError("Pipeline validation failed")

        with self.execution_context() as context:
            last_processed = context.get_checkpoint("last_processed_table")

            tables = self.extract()

            if last_processed:
                tables = self._resume_from_checkpoint(tables, last_processed)

            for table in tables:
                try:
                    self.sink.write_table(table)
                    context.increment_tables_processed()
                    context.set_checkpoint("last_processed_table", table.fullyQualifiedName)
                except Exception as e:
                    context.add_error(
                        name=type(e).__name__,
                        error=str(e),
                        entity_name=table.name,
                        entity_type="Table",
                        recoverable=True,
                    )
                    context.increment_tables_failed()

            self.sink.flush()

        return context

    def _resume_from_checkpoint(
        self,
        tables: List[Table],
        last_processed: str,
    ) -> List[Table]:
        """Filter tables to resume from checkpoint

        Args:
            tables: All tables
            last_processed: FQN of last successfully processed table

        Returns:
            Filtered list of tables to process
        """
        found_last = False
        filtered_tables = []

        for table in tables:
            if found_last:
                filtered_tables.append(table)
            elif table.fullyQualifiedName == last_processed:
                found_last = True

        logger.info(
            "resuming_from_checkpoint",
            last_processed=last_processed,
            tables_to_process=len(filtered_tables),
        )
        return filtered_tables
