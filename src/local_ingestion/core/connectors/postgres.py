"""PostgreSQL source connector for metadata extraction"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING
from datetime import datetime

import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from local_ingestion.core.connectors.base import SourceConnector
from local_ingestion.schema.data.database import Database, DatabaseSchema
from local_ingestion.schema.data.table import Table, Column
from local_ingestion.schema.service.connection import PostgresConnection
from local_ingestion.schema.base import DataType

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

logger = structlog.get_logger()


class PostgresSourceConnector(SourceConnector):
    """PostgreSQL source connector using SQLAlchemy for metadata extraction"""

    def __init__(self) -> None:
        super().__init__()
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._retry_attempts: int = 3
        self._retry_delay: float = 1.0

    def connect(self, config: PostgresConnection) -> None:
        """Connect to PostgreSQL database

        Args:
            config: PostgreSQL connection configuration
        """
        self._config = config
        try:
            connection_string = config.get_connection_string()
            logger.info(
                "connecting_to_postgres",
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
            )
            self._session_factory = sessionmaker(bind=self._engine)
            self._connected = True
            logger.info("postgres_connection_success", database=config.database)

        except Exception as e:
            self._log_connection_error(e)
            self._connected = False
            raise

    def disconnect(self) -> None:
        """Disconnect from PostgreSQL database"""
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._connected = False
            logger.info("postgres_disconnected")

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
        """Fetch all databases from PostgreSQL

        Returns:
            List of Database objects
        """
        databases = []
        try:
            result = self._execute_with_retry(
                """
                SELECT datname
                FROM pg_database
                WHERE datistemplate = false
                AND datallowconn = true
                ORDER BY datname
                """
            )
            for row in result:
                db_name = row[0]
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
        """Fetch all schemas from a PostgreSQL database

        Args:
            database: Database name

        Returns:
            List of DatabaseSchema objects
        """
        schemas = []
        try:
            result = self._execute_with_retry(
                """
                SELECT
                    n.nspname,
                    COALESCE(d.description, '')
                FROM pg_namespace n
                LEFT JOIN pg_description d ON d.objoid = n.oid AND d.classoid = 'pg_namespace'::regclass
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
                AND n.nspname NOT LIKE 'pg_toast%'
                AND n.nspname NOT LIKE 'pg_temp%'
                AND n.nspname NOT LIKE 'pg_toast_temp%'
                ORDER BY n.nspname
                """
            )
            for row in result:
                schema_name = row[0]
                description = row[1]
                schemas.append(
                    DatabaseSchema(
                        name=schema_name,
                        fullyQualifiedName=f"{database}.{schema_name}",
                        database=database,
                        description=description or None,
                    )
                )
            logger.info("fetched_schemas", database=database, count=len(schemas))
        except Exception as e:
            logger.error("fetch_schemas_error", database=database, error=str(e))
            raise
        return schemas

    def fetch_tables(self, database: str, schema: str) -> List[Table]:
        """Fetch all tables from a PostgreSQL schema

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
                    c.relname,
                    c.relkind,
                    COALESCE(d.description, ''),
                    pg_size_pretty(pg_relation_size(c.oid)),
                    COALESCE(to_char(c.relpages * 8192, '9999999999'), '0')::bigint,
                    COALESCE(s.n_live_tup, 0),
                    COALESCE(to_char(s.last_analyze, 'YYYY-MM-DD HH24:MI:SS'), NULL),
                    COALESCE(to_char(s.last_autoanalyze, 'YYYY-MM-DD HH24:MI:SS'), NULL)
                FROM pg_class c
                LEFT JOIN pg_description d ON d.objoid = c.oid AND d.classoid = 'pg_class'::regclass
                LEFT JOIN pg_stat_user_tables s ON s.schemaname = :schema AND s.relname = c.relname
                WHERE c.relnamespace = (
                    SELECT oid FROM pg_namespace WHERE nspname = :schema
                )
                AND c.relkind IN ('r', 'v', 'm')
                ORDER BY c.relname
                """,
                {"schema": schema},
            )

            for row in result:
                table_name = row[0]
                table_type = row[1]
                description = row[2]
                size_pretty = row[3]
                size_bytes = row[4]
                row_count = row[5]
                last_analyze = row[6]
                last_autoanalyze = row[7]

                table_kind = "VIEW" if table_type in ("v", "m") else "TABLE"

                table = Table(
                    name=table_name,
                    fullyQualifiedName=f"{database}.{schema}.{table_name}",
                    database=database,
                    databaseSchema=schema,
                    tableType=table_kind,
                    description=description or None,
                )
                tables.append(table)

            logger.info("fetched_tables", schema=schema, count=len(tables))
        except Exception as e:
            logger.error("fetch_tables_error", schema=schema, error=str(e))
            raise
        return tables

    def fetch_columns(self, table: Table) -> List[Column]:
        """Fetch columns for a PostgreSQL table

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
                    a.attname,
                    pg_catalog.format_type(a.atttypid, a.atttypmod),
                    COALESCE(d.description, ''),
                    a.attnotnull,
                    COALESCE(pg_get_expr(ad.adbin, ad.adrelid), ''),
                    a.attnum,
                    CASE
                        WHEN a.atttypid IN (pg_catalog.oidvectortypid(), pg_catalog.oidarraytypmodtyp())
                        THEN NULL
                        ELSE COALESCE(bt.typtypmod, a.atttypmod)
                    END,
                    CASE
                        WHEN a.atttypid IN (pg_catalog.oidvectortypid(), pg_catalog.oidarraytypmodtyp())
                        THEN NULL
                        WHEN a.atttypid IN (21, 23, 20)
                        THEN NULL
                        ELSE COALESCE(bt.typprecision, NULL)
                    END,
                    CASE
                        WHEN a.atttypid IN (pg_catalog.oidvectortypid(), pg_catalog.oidarraytypmodtyp())
                        THEN NULL
                        ELSE COALESCE(bt.typscale, NULL)
                    END,
                    COALESCE(col_default, ''),
                    ai.adsrc
                FROM pg_attribute a
                JOIN pg_class pc ON pc.oid = a.attrelid
                LEFT JOIN pg_description d ON d.objoid = a.attrelid AND d.objsubid = a.attnum
                LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
                LEFT JOIN pg_type bt ON bt.oid = a.atttypid
                LEFT JOIN pg_attribute ai ON ai.attrelid = ad.adrelid AND ai.attname = 'attnum' AND ai.attnum = 1
                WHERE a.attrelid = (
                    SELECT oid FROM pg_class WHERE relname = :table
                    AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = :schema)
                )
                AND a.attnum > 0
                AND NOT a.attisdropped
                ORDER BY a.attnum
                """,
                {"schema": table.databaseSchema, "table": table.name},
            )

            for row in result:
                column_name = row[0]
                data_type_display = row[1]
                description = row[2]
                is_nullable = not row[3]
                default_value = row[4]
                ordinal_position = row[5]
                precision_val = row[7]
                scale_val = row[8]
                column_default = row[9]

                data_type_enum = self._map_postgres_type(data_type_display)

                column = Column(
                    name=column_name,
                    dataType=data_type_enum,
                    dataTypeDisplay=data_type_display,
                    precision=int(precision_val) if precision_val else None,
                    scale=int(scale_val) if scale_val else None,
                    nullable=is_nullable,
                    ordinalPosition=ordinal_position,
                    default=str(column_default) if column_default else None,
                    description=description or None,
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

    def _map_postgres_type(self, pg_type: str) -> DataType:
        """Map PostgreSQL data type to OpenMetadata DataType

        Args:
            pg_type: PostgreSQL data type string

        Returns:
            Corresponding DataType enum value
        """
        pg_type_upper = pg_type.upper().split("(")[0].strip()

        type_mapping = {
            "CHAR": DataType.STRING,
            "CHARACTER": DataType.STRING,
            "VARCHAR": DataType.STRING,
            "CHARACTER VARYING": DataType.STRING,
            "TEXT": DataType.TEXT,
            "NAME": DataType.STRING,
            "BOOLEAN": DataType.BOOLEAN,
            "BOOL": DataType.BOOLEAN,
            "SMALLINT": DataType.SMALLINT,
            "INT2": DataType.SMALLINT,
            "INTEGER": DataType.INTEGER,
            "INT4": DataType.INTEGER,
            "BIGINT": DataType.BIGINT,
            "INT8": DataType.BIGINT,
            "REAL": DataType.FLOAT,
            "FLOAT4": DataType.FLOAT,
            "DOUBLE PRECISION": DataType.DOUBLE,
            "FLOAT8": DataType.DOUBLE,
            "NUMERIC": DataType.DECIMAL,
            "DECIMAL": DataType.DECIMAL,
            "MONEY": DataType.DECIMAL,
            "DATE": DataType.DATE,
            "TIME": DataType.TIME,
            "TIME WITHOUT TIME ZONE": DataType.TIME,
            "TIME WITH TIME ZONE": DataType.TIME,
            "TIMESTAMP": DataType.TIMESTAMP,
            "TIMESTAMP WITHOUT TIME ZONE": DataType.TIMESTAMP,
            "TIMESTAMP WITH TIME ZONE": DataType.TIMESTAMP,
            "TIMESTAMPTZ": DataType.TIMESTAMP,
            "INTERVAL": DataType.STRING,
            "BYTEA": DataType.BYTES,
            "UUID": DataType.UUID,
            "JSON": DataType.JSON,
            "JSONB": DataType.JSON,
            "XML": DataType.STRING,
            "POINT": DataType.STRING,
            "LINE": DataType.STRING,
            "CIRCLE": DataType.STRING,
            "BOX": DataType.STRING,
            "PATH": DataType.STRING,
            "POLYGON": DataType.STRING,
            "INET": DataType.STRING,
            "CIDR": DataType.STRING,
            "MACADDR": DataType.STRING,
            "ARRAY": DataType.ARRAY,
        }

        # Sort by key length descending to match longer types first
        for key in sorted(type_mapping.keys(), key=len, reverse=True):
            if key in pg_type_upper:
                return type_mapping[key]

        return DataType.UNKNOWN
