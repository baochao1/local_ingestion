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
        # Uniform MOD-08 contract: (name, host, is_super, is_locked).
        # MySQL 8 exposes the flag as Super_priv / account_locked (no is_super column).
        return (
            "SELECT user, host, Super_priv = 'Y' AS is_super, "
            "account_locked = 'Y' AS is_locked "
            "FROM mysql.user ORDER BY user, host"
        )

    def list_grants_sql(self) -> str:
        # Uniform contract via information_schema (MySQL 8). grantee is 'user'@'host'.
        return """
        SELECT grantee,
               'table' AS object_type,
               CONCAT(table_schema, '.', table_name) AS object_fqn,
               privilege_type AS privilege,
               IS_GRANTABLE = 'YES' AS grantable
        FROM information_schema.table_privileges
        UNION ALL
        SELECT grantee,
               'column' AS object_type,
               CONCAT(table_schema, '.', table_name, '.', column_name) AS object_fqn,
               privilege_type AS privilege,
               IS_GRANTABLE = 'YES' AS grantable
        FROM information_schema.column_privileges
        ORDER BY grantee, object_fqn
        """

    def view_definition_sql(self) -> str:
        return (
            "SELECT table_name AS view_name, view_definition "
            "FROM information_schema.views "
            "WHERE table_schema = :schema ORDER BY table_name"
        )
