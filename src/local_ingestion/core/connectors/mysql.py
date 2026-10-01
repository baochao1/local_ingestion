"""MySQL source connector for metadata extraction"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING
from contextlib import contextmanager
from datetime import datetime

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from local_ingestion.core.connectors.base import SourceConnector
from local_ingestion.schema.data.database import Database, DatabaseSchema
from local_ingestion.schema.data.table import Table, Column
from local_ingestion.schema.service.connection import MySQLConnection
from local_ingestion.schema.base import DataType

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

logger = structlog.get_logger()


class MySQLSourceConnector(SourceConnector):
    """MySQL source connector using SQLAlchemy for metadata extraction"""

    def __init__(self) -> None:
        super().__init__()
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._retry_attempts: int = 3
        self._retry_delay: float = 1.0

    def connect(self, config: MySQLConnection) -> None:
        """Connect to MySQL database

        Args:
            config: MySQL connection configuration
        """
        self._config = config
        try:
            connection_string = config.get_connection_string()
            logger.info(
                "connecting_to_mysql",
                host=config.hostPort,
                database=config.database,
            )

            self._engine = create_engine(
                connection_string,
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=3600,
                connect_args={"ssl_disabled": True},
            )
            self._session_factory = sessionmaker(bind=self._engine)
            self._connected = True
            logger.info("mysql_connection_success", database=config.database)

        except Exception as e:
            self._log_connection_error(e)
            self._connected = False
            raise

    def disconnect(self) -> None:
        """Disconnect from MySQL database"""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._connected = False
            logger.info("mysql_disconnected")

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
        """Fetch all databases from MySQL

        Returns:
            List of Database objects
        """
        databases = []
        try:
            result = self._execute_with_retry("SHOW DATABASES")
            for row in result:
                db_name = row[0]
                if db_name not in ("information_schema", "mysql", "performance_schema", "sys"):
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
        """Fetch all schemas from a MySQL database

        Args:
            database: Database name

        Returns:
            List of DatabaseSchema objects
        """
        schemas = []
        try:
            result = self._execute_with_retry(
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = :db",
                {"db": database},
            )
            for row in result:
                schema_name = row[0]
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
        """Fetch all tables from a MySQL schema

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
                    table_name,
                    table_type,
                    table_comment,
                    engine,
                    table_rows,
                    data_length,
                    index_length,
                    update_time
                FROM information_schema.tables
                WHERE table_schema = :schema
                ORDER BY table_name
                """,
                {"schema": schema},
            )

            for row in result:
                table_name = row[0]
                table_type = row[1]
                description = row[2]
                engine = row[3]
                row_count = row[4]
                data_length = row[5]
                index_length = row[6]
                update_time = row[7]

                table = Table(
                    name=table_name,
                    fullyQualifiedName=f"{database}.{schema}.{table_name}",
                    database=database,
                    databaseSchema=schema,
                    tableType=table_type,
                    description=description or None,
                )
                tables.append(table)

            logger.info("fetched_tables", schema=schema, count=len(tables))
        except Exception as e:
            logger.error("fetch_tables_error", schema=schema, error=str(e))
            raise
        return tables

    def fetch_columns(self, table: Table) -> List[Column]:
        """Fetch columns for a MySQL table

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
                    column_name,
                    data_type,
                    column_type,
                    is_nullable,
                    column_default,
                    column_comment,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale,
                    ordinal_position,
                    extra
                FROM information_schema.columns
                WHERE table_schema = :schema AND table_name = :table
                ORDER BY ordinal_position
                """,
                {"schema": table.databaseSchema, "table": table.name},
            )

            for row in result:
                column_name = row[0]
                data_type = row[1]
                column_type = row[2]
                is_nullable = row[3] == "YES"
                column_default = row[4]
                column_comment = row[5]
                char_max_length = row[6]
                numeric_precision = row[7]
                numeric_scale = row[8]
                ordinal_position = row[9]
                extra = row[10]

                data_type_enum = self._map_mysql_type(data_type)

                column = Column(
                    name=column_name,
                    dataType=data_type_enum,
                    dataTypeDisplay=column_type,
                    dataLength=int(char_max_length) if char_max_length else None,
                    precision=int(numeric_precision) if numeric_precision else None,
                    scale=int(numeric_scale) if numeric_scale else None,
                    nullable=is_nullable,
                    ordinalPosition=ordinal_position,
                    default=str(column_default) if column_default else None,
                    description=column_comment or None,
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

    def _map_mysql_type(self, mysql_type: str) -> DataType:
        """Map MySQL data type to OpenMetadata DataType

        Args:
            mysql_type: MySQL data type string

        Returns:
            Corresponding DataType enum value
        """
        mysql_type_upper = mysql_type.upper()

        type_mapping = {
            "CHAR": DataType.STRING,
            "VARCHAR": DataType.STRING,
            "TEXT": DataType.TEXT,
            "TINYTEXT": DataType.TEXT,
            "MEDIUMTEXT": DataType.TEXT,
            "LONGTEXT": DataType.TEXT,
            "ENUM": DataType.STRING,
            "SET": DataType.STRING,
            "BOOLEAN": DataType.BOOLEAN,
            "BOOL": DataType.BOOLEAN,
            "TINYINT": DataType.TINYINT,
            "SMALLINT": DataType.SMALLINT,
            "MEDIUMINT": DataType.INTEGER,
            "BIGINT": DataType.BIGINT,
            "INTEGER": DataType.INTEGER,
            "INT": DataType.INTEGER,
            "DECIMAL": DataType.DECIMAL,
            "NUMERIC": DataType.DECIMAL,
            "FLOAT": DataType.FLOAT,
            "DOUBLE": DataType.DOUBLE,
            "DATE": DataType.DATE,
            "TIME": DataType.TIME,
            "DATETIME": DataType.TIMESTAMP,
            "TIMESTAMP": DataType.TIMESTAMP,
            "YEAR": DataType.INTEGER,
            "BIT": DataType.INTEGER,
            "VARBINARY": DataType.BINARY,
            "BINARY": DataType.BINARY,
            "TINYBLOB": DataType.BINARY,
            "MEDIUMBLOB": DataType.BINARY,
            "LONGBLOB": DataType.BINARY,
            "BLOB": DataType.BINARY,
            "JSON": DataType.JSON,
            "GEOMETRY": DataType.BINARY,
        }

        # Sort by key length descending to match longer types first
        for key in sorted(type_mapping.keys(), key=len, reverse=True):
            if key in mysql_type_upper:
                return type_mapping[key]

        return DataType.UNKNOWN
