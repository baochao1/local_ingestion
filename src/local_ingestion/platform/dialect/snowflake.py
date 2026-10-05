"""Snowflake dialect (T-114).

SQL and type mapping are verbatim reproductions of
``local_ingestion.core.connectors.snowflake``.
"""
from __future__ import annotations

from typing import Dict

from local_ingestion.schema.base import DataType

from .base import Dialect, _longest_match

_TYPE_MAP: Dict[str, DataType] = {
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


class SnowflakeDialect(Dialect):
    @property
    def name(self) -> str:
        return "snowflake"

    def list_databases_sql(self) -> str:
        return "SHOW DATABASES"

    def list_schemas_sql(self) -> str:
        return "SHOW SCHEMAS IN DATABASE IDENTIFIER(:database)"

    def list_tables_sql(self) -> str:
        return """
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
        """

    def list_columns_sql(self) -> str:
        return """
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
        """

    def normalize_type(self, raw_type: str, **meta: object) -> DataType:
        if not raw_type:
            return DataType.UNKNOWN
        return _longest_match(raw_type.upper(), _TYPE_MAP)

    @property
    def supports_sampling(self) -> bool:
        return True

    def sample_sql(self, table: str, rate: float) -> str:
        pct = max(0.0, min(100.0, float(rate) * 100.0))
        return f"SELECT * FROM {table} TABLESAMPLE ({pct:g})"

    def list_accounts_sql(self) -> str:
        return "SHOW USERS"

    def list_grants_sql(self) -> str:
        return "SHOW GRANTS TO USER CURRENT_USER()"

    def view_definition_sql(self) -> str:
        return (
            "SELECT table_name AS view_name, view_definition "
            "FROM information_schema.views "
            "WHERE table_schema = :schema ORDER BY table_name"
        )
