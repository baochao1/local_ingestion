"""MySQL dialect (T-114).

SQL and type mapping are verbatim reproductions of
``local_ingestion.core.connectors.mysql``.
"""
from __future__ import annotations

from typing import Dict

from local_ingestion.schema.base import DataType

from .base import Dialect, _longest_match

_TYPE_MAP: Dict[str, DataType] = {
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


class MySQLDialect(Dialect):
    @property
    def name(self) -> str:
        return "mysql"

    def list_databases_sql(self) -> str:
        # The L1 connector fetches all then filters system schemas in Python;
        # the SQL is exactly ``SHOW DATABASES``.
        return "SHOW DATABASES"

    def list_schemas_sql(self) -> str:
        return (
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name = :db"
        )

    def list_tables_sql(self) -> str:
        return """
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
        """

    def list_columns_sql(self) -> str:
        return """
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
        """

    def normalize_type(self, raw_type: str, **meta: object) -> DataType:
        if not raw_type:
            return DataType.UNKNOWN
        return _longest_match(raw_type.upper(), _TYPE_MAP)

    @property
    def supports_sampling(self) -> bool:
        return True

    def sample_sql(self, table: str, rate: float) -> str:
        # MySQL has no TABLESAMPLE; approximate with a WHERE filter on RAND().
        return f"SELECT * FROM {table} WHERE RAND() < {float(rate):g}"

    def list_accounts_sql(self) -> str:
        return "SELECT user, host FROM mysql.user ORDER BY user, host"

    def list_grants_sql(self) -> str:
        return "SHOW GRANTS FOR CURRENT_USER"
