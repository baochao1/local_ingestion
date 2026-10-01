"""Snowflake source connector for metadata extraction"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from local_ingestion.core.connectors.base import SourceConnector
from local_ingestion.schema.data.database import Database, DatabaseSchema
from local_ingestion.schema.data.table import Table, Column
from local_ingestion.schema.service.connection import SnowflakeConnection
from local_ingestion.schema.base import DataType

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

logger = structlog.get_logger()


class SnowflakeSourceConnector(SourceConnector):
    """Snowflake source connector for metadata extraction"""

    def __init__(self) -> None:
        super().__init__()
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._retry_attempts: int = 3
        self._retry_delay: float = 1.0

    def connect(self, config: SnowflakeConnection) -> None:
        """Connect to Snowflake database

        Args:
            config: Snowflake connection configuration
        """
        self._config = config
        try:
            connection_string = config.get_connection_string()
            logger.info(
                "connecting_to_snowflake",
                account=config.account,
                database=config.database,
                warehouse=config.warehouse,
            )

            connect_args = {}
            if config.privateKey:
                connect_args["private_key"] = config.privateKey

            self._engine = create_engine(
                connection_string,
                connect_args=connect_args,
            )
            self._session_factory = sessionmaker(bind=self._engine)
            self._connected = True
            logger.info(
                "snowflake_connection_success",
                database=config.database,
                warehouse=config.warehouse,
            )

        except Exception as e:
            self._log_connection_error(e)
            self._connected = False
            raise

    def disconnect(self) -> None:
        """Disconnect from Snowflake database"""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._connected = False
            logger.info("snowflake_disconnected")

    def _execute_with_retry(self, query: str, params: Optional[Dict] = None) -> Any:
        """Execute query with retry logic

        Args:
            query: SQL query to execute
            params: Query parameters

        Returns:
            Query result
        """
        for attempt in range(self._retry_attempts):
            try:
                with self._engine.connect() as conn:
                    result = conn.execute(text(query), params or {})
                    return result
            except Exception as e:
                if attempt == self._retry_attempts - 1:
                    raise
                logger.warning(
                    "query_retry",
                    attempt=attempt + 1,
                    max_attempts=self._retry_attempts,
                    error=str(e),
                )

    def fetch_databases(self) -> List[Database]:
        """Fetch all databases from Snowflake

        Returns:
            List of Database objects
        """
        databases = []
        try:
            result = self._execute_with_retry("SHOW DATABASES")
            for row in result:
                db_name = row[0] if len(row) > 0 else None
                if db_name:
                    databases.append(
                        Database(
                            name=db_name,
                            fullyQualifiedName=db_name,
                        )
                    )
            logger.info("fetched_databases", count=len(databases))
        except Exception as e:
            logger.error("fetch_databases_error", error=str(e))
            raise
        return databases

    def fetch_schemas(self, database: str) -> List[DatabaseSchema]:
        """Fetch all schemas from a Snowflake database

        Args:
            database: Database name

        Returns:
            List of DatabaseSchema objects
        """
        schemas = []
        try:
            result = self._execute_with_retry(
                "SHOW SCHEMAS IN DATABASE IDENTIFIER(:database)",
                {"database": database},
            )

            for row in result:
                schema_name = row[1] if len(row) > 1 else row[0]
                if schema_name:
                    schemas.append(
                        DatabaseSchema(
                            name=schema_name,
                            fullyQualifiedName=f"{database}.{schema_name}",
                            database=database,
                        )
                    )
            logger.info("fetched_schemas", database=database, count=len(schemas))
        except Exception as e:
            logger.error("fetch_schemas_error", database=database, error=str(e))
            raise
        return schemas

    def fetch_tables(self, database: str, schema: str) -> List[Table]:
        """Fetch all tables from a Snowflake schema

        Args:
            database: Database name
            schema: Schema name

        Returns:
            List of Table objects with columns
        """
        tables = []
        try:
            result = self._execute_with_retry(
                """
                SELECT
                    TABLE_NAME,
                    TABLE_TYPE,
                    COMMENT,
                    ROW_COUNT,
                    BYTES,
                    CREATED,
                    LAST_ALTERED
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = :schema
                ORDER BY TABLE_NAME
                """,
                {"schema": schema},
            )

            for row in result:
                table_name = row[0]
                table_type = row[1]
                comment = row[2]
                row_count = row[3]
                bytes_val = row[4]
                created_on = row[5]
                last_altered = row[6]

                table = Table(
                    name=table_name,
                    fullyQualifiedName=f"{database}.{schema}.{table_name}",
                    database=database,
                    databaseSchema=schema,
                    tableType=table_type,
                    description=comment or None,
                )
                tables.append(table)

            logger.info("fetched_tables", schema=schema, count=len(tables))
        except Exception as e:
            logger.error("fetch_tables_error", schema=schema, error=str(e))
            raise
        return tables

    def fetch_columns(self, table: Table) -> List[Column]:
        """Fetch columns for a Snowflake table

        Args:
            table: Table object

        Returns:
            List of Column objects
        """
        columns = []
        try:
            result = self._execute_with_retry(
                """
                SELECT
                    COLUMN_NAME,
                    DATA_TYPE,
                    IS_NULLABLE,
                    COLUMN_DEFAULT,
                    COMMENT,
                    ORDINAL_POSITION,
                    CHARACTER_MAX_LENGTH,
                    NUMERIC_PRECISION,
                    NUMERIC_SCALE,
                    COLUMN_ID
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = :schema
                AND TABLE_NAME = :table
                ORDER BY ORDINAL_POSITION
                """,
                {"schema": table.databaseSchema, "table": table.name},
            )

            for row in result:
                column_name = row[0]
                data_type = row[1]
                is_nullable = row[2] == "YES"
                column_default = row[3]
                comment = row[4]
                ordinal_position = row[5]
                char_max_length = row[6]
                numeric_precision = row[7]
                numeric_scale = row[8]
                column_id = row[9]

                data_type_enum = self._map_snowflake_type(data_type)

                column = Column(
                    name=column_name,
                    dataType=data_type_enum,
                    dataTypeDisplay=data_type,
                    dataLength=int(char_max_length) if char_max_length else None,
                    precision=int(numeric_precision) if numeric_precision else None,
                    scale=int(numeric_scale) if numeric_scale else None,
                    nullable=is_nullable,
                    ordinalPosition=ordinal_position,
                    default=str(column_default) if column_default else None,
                    description=comment or None,
                )
                columns.append(column)

            logger.info(
                "fetched_columns",
                table=table.name,
                count=len(columns),
            )
        except Exception as e:
            logger.error("fetch_columns_error", table=table.name, error=str(e))
            raise
        return columns

    def _map_snowflake_type(self, snowflake_type: str) -> DataType:
        """Map Snowflake data type to OpenMetadata DataType

        Args:
            snowflake_type: Snowflake data type string

        Returns:
            Corresponding DataType enum value
        """
        sf_type_upper = snowflake_type.upper()

        type_mapping = {
            "VARCHAR": DataType.STRING,
            "CHAR": DataType.STRING,
            "CHARACTER": DataType.STRING,
            "TEXT": DataType.TEXT,
            "STRING": DataType.STRING,
            "BOOLEAN": DataType.BOOLEAN,
            "BOOL": DataType.BOOLEAN,
            "BINARY": DataType.BINARY,
            "VARBINARY": DataType.BINARY,
            "BLOB": DataType.BINARY,
            "CLOB": DataType.TEXT,
            "NUMBER": DataType.DECIMAL,
            "NUMERIC": DataType.DECIMAL,
            "DECIMAL": DataType.DECIMAL,
            "INTEGER": DataType.INTEGER,
            "INT": DataType.INTEGER,
            "BIGINT": DataType.BIGINT,
            "SMALLINT": DataType.SMALLINT,
            "TINYINT": DataType.TINYINT,
            "BYTEINT": DataType.TINYINT,
            "FLOAT": DataType.FLOAT,
            "FLOAT4": DataType.FLOAT,
            "DOUBLE": DataType.DOUBLE,
            "DOUBLE PRECISION": DataType.DOUBLE,
            "REAL": DataType.FLOAT,
            "DATE": DataType.DATE,
            "DATETIME": DataType.TIMESTAMP,
            "TIME": DataType.TIME,
            "TIMESTAMP": DataType.TIMESTAMP,
            "TIMESTAMP_NTZ": DataType.TIMESTAMP,
            "TIMESTAMP_LTZ": DataType.TIMESTAMP,
            "TIMESTAMP_TZ": DataType.TIMESTAMP,
            "VARIANT": DataType.JSON,
            "OBJECT": DataType.JSON,
            "ARRAY": DataType.ARRAY,
            "MAP": DataType.MAP,
            "GEOGRAPHY": DataType.STRING,
            "GEOMETRY": DataType.STRING,
            "JSON": DataType.JSON,
            "XML": DataType.STRING,
        }

        # Sort by key length descending to match longer types first
        for key in sorted(type_mapping.keys(), key=len, reverse=True):
            if key in sf_type_upper:
                return type_mapping[key]

        return DataType.UNKNOWN
