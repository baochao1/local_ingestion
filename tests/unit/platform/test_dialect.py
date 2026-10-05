"""T-114 dialect tests.

The critical guarantee is that ``Dialect.normalize_type`` returns exactly the
same :class:`DataType` as the L1 connector mappers it replaces, so switching
the scanning pipeline over later is behaviour-preserving.
"""
from __future__ import annotations

import pytest

from local_ingestion.core.connectors.mysql import MySQLSourceConnector
from local_ingestion.core.connectors.postgres import PostgresSourceConnector
from local_ingestion.core.connectors.snowflake import SnowflakeSourceConnector
from local_ingestion.platform.dialect import (
    MySQLDialect,
    PostgresDialect,
    SnowflakeDialect,
    UnknownDialectError,
    available_dialects,
    get_dialect,
)
from local_ingestion.schema.base import DataType

# (raw_type, expected DataType) — covers parametric, multi-word and unknown types.
_POSTGRES_CASES = [
    ("character varying(255)", DataType.STRING),
    ("varchar", DataType.STRING),
    ("text", DataType.TEXT),
    ("numeric(10,2)", DataType.DECIMAL),
    ("double precision", DataType.DOUBLE),
    ("timestamp with time zone", DataType.TIMESTAMP),
    ("timestamptz", DataType.TIMESTAMP),
    ("int4", DataType.INTEGER),
    ("int8", DataType.BIGINT),
    ("jsonb", DataType.JSON),
    ("uuid", DataType.UUID),
    ("bytea", DataType.BYTES),
    ("ARRAY", DataType.ARRAY),
    ("money", DataType.DECIMAL),
    ("totally_unknown", DataType.UNKNOWN),
    ("", DataType.UNKNOWN),
]
_MYSQL_CASES = [
    ("varchar(255)", DataType.STRING),
    ("int", DataType.INTEGER),
    ("tinyint(1)", DataType.TINYINT),
    ("mediumint", DataType.INTEGER),
    ("datetime", DataType.TIMESTAMP),
    ("blob", DataType.BINARY),
    ("longtext", DataType.TEXT),
    ("year", DataType.INTEGER),
    ("geometry", DataType.BINARY),
    ("decimal(12,4)", DataType.DECIMAL),
    ("double", DataType.DOUBLE),
    ("weird_type", DataType.UNKNOWN),
    ("", DataType.UNKNOWN),
]
_SNOWFLAKE_CASES = [
    ("VARCHAR(100)", DataType.STRING),
    ("NUMBER(38,0)", DataType.DECIMAL),
    ("TIMESTAMP_NTZ", DataType.TIMESTAMP),
    ("TIMESTAMP_TZ", DataType.TIMESTAMP),
    ("VARIANT", DataType.JSON),
    ("ARRAY", DataType.ARRAY),
    ("MAP", DataType.MAP),
    ("GEOGRAPHY", DataType.STRING),
    ("FLOAT4", DataType.FLOAT),
    ("OBJECT", DataType.JSON),
    ("nope", DataType.UNKNOWN),
    ("", DataType.UNKNOWN),
]


@pytest.mark.parametrize("raw,expected", _POSTGRES_CASES)
def test_postgres_normalize_matches_l1(raw, expected):
    assert PostgresDialect().normalize_type(raw) == expected
    assert PostgresDialect().normalize_type(raw) == PostgresSourceConnector()._map_postgres_type(raw)


@pytest.mark.parametrize("raw,expected", _MYSQL_CASES)
def test_mysql_normalize_matches_l1(raw, expected):
    assert MySQLDialect().normalize_type(raw) == expected
    assert MySQLDialect().normalize_type(raw) == MySQLSourceConnector()._map_mysql_type(raw)


@pytest.mark.parametrize("raw,expected", _SNOWFLAKE_CASES)
def test_snowflake_normalize_matches_l1(raw, expected):
    assert SnowflakeDialect().normalize_type(raw) == expected
    assert SnowflakeDialect().normalize_type(raw) == SnowflakeSourceConnector()._map_snowflake_type(raw)


def _assert_sql(sql: str, *tokens: str) -> None:
    assert sql and sql.strip()
    lowered = " ".join(sql.lower().split())
    for tok in tokens:
        assert tok.lower() in lowered


def test_postgres_sql_sanity():
    d = PostgresDialect()
    _assert_sql(d.list_databases_sql(), "pg_database")
    _assert_sql(d.list_schemas_sql(), "pg_namespace")
    _assert_sql(d.list_tables_sql(), "pg_class", ":schema")
    _assert_sql(d.list_columns_sql(), "pg_attribute", ":schema", ":table")
    _assert_sql(d.list_accounts_sql(), "pg_roles")
    _assert_sql(d.list_grants_sql(), "role_table_grants")


def test_mysql_sql_sanity():
    d = MySQLDialect()
    _assert_sql(d.list_databases_sql(), "show databases")
    _assert_sql(d.list_schemas_sql(), "information_schema.schemata", ":db")
    _assert_sql(d.list_tables_sql(), "information_schema.tables", ":schema")
    _assert_sql(d.list_columns_sql(), "information_schema.columns", ":schema", ":table")
    _assert_sql(d.list_accounts_sql(), "mysql.user", "super_priv")
    # MOD-08: uniform (grantee, object_type, object_fqn, privilege, grantable)
    # contract; "SHOW GRANTS" only ever returned CURRENT_USER's own grants.
    _assert_sql(d.list_grants_sql(), "information_schema.table_privileges", "grantee")


def test_snowflake_sql_sanity():
    d = SnowflakeDialect()
    _assert_sql(d.list_databases_sql(), "show databases")
    _assert_sql(d.list_schemas_sql(), "show schemas", ":database")
    _assert_sql(d.list_tables_sql(), "information_schema.tables", ":schema")
    _assert_sql(d.list_columns_sql(), "information_schema.columns", ":schema", ":table")
    # MOD-08: permission listing is deliberately *unsupported* rather than
    # silently mis-parseable — SHOW output cannot satisfy the uniform contract.
    with pytest.raises(NotImplementedError):
        d.list_accounts_sql()
    with pytest.raises(NotImplementedError):
        d.list_grants_sql()


def test_sampling_capability():
    for d in (PostgresDialect(), MySQLDialect(), SnowflakeDialect()):
        assert d.supports_sampling is True
        sql = d.sample_sql("db.schema.t", 0.05)
        assert "db.schema.t" in sql
        assert "5" in sql  # 0.05 * 100


def test_registry_aliases_and_unknown():
    assert isinstance(get_dialect("postgres"), PostgresDialect)
    assert isinstance(get_dialect("PostgreSQL"), PostgresDialect)
    assert isinstance(get_dialect("mysql"), MySQLDialect)
    assert isinstance(get_dialect("mariadb"), MySQLDialect)
    assert isinstance(get_dialect("snowflake"), SnowflakeDialect)
    assert "postgres" in available_dialects()

    with pytest.raises(UnknownDialectError):
        get_dialect("sqlserver")
    with pytest.raises(UnknownDialectError):
        get_dialect("")
