"""PostgreSQL dialect (T-114).

SQL and type mapping are verbatim reproductions of
``local_ingestion.core.connectors.postgres`` so the scanning pipeline can
switch over with zero behaviour change.
"""
from __future__ import annotations

from typing import Dict

from local_ingestion.schema.base import DataType

from .base import Dialect, _longest_match

_TYPE_MAP: Dict[str, DataType] = {
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


class PostgresDialect(Dialect):
    @property
    def name(self) -> str:
        return "postgres"

    def list_databases_sql(self) -> str:
        return """
        SELECT datname
        FROM pg_database
        WHERE datistemplate = false
        AND datallowconn = true
        ORDER BY datname
        """

    def list_schemas_sql(self) -> str:
        return """
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

    def list_tables_sql(self) -> str:
        return """
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
        """

    def list_columns_sql(self) -> str:
        return """
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
        """

    def normalize_type(self, raw_type: str, **meta: object) -> DataType:
        if not raw_type:
            return DataType.UNKNOWN
        # Postgres reports types like "character varying(255)" / "numeric(10,2)".
        normalised = raw_type.upper().split("(")[0].strip()
        return _longest_match(normalised, _TYPE_MAP)

    @property
    def supports_sampling(self) -> bool:
        return True

    def sample_sql(self, table: str, rate: float) -> str:
        pct = max(0.0, min(100.0, float(rate) * 100.0))
        return f"SELECT * FROM {table} TABLESAMPLE BERNOULLI({pct:g})"

    def list_accounts_sql(self) -> str:
        # rolsuper / rolcanlogin drive risk detection (super / locked accounts)
        return (
            "SELECT rolname, rolsuper, rolcanlogin "
            "FROM pg_roles WHERE rolcanlogin ORDER BY rolname"
        )

    def list_grants_sql(self) -> str:
        # Uniform contract: (grantee, object_type, object_fqn, privilege, grantable).
        # Table + column grants merged; object_fqn = schema.table[.column].
        return """
        SELECT grantee,
               'table'  AS object_type,
               table_schema || '.' || table_name AS object_fqn,
               privilege_type AS privilege,
               is_grantable = 'YES' AS grantable
        FROM information_schema.role_table_grants
        UNION ALL
        SELECT rg.grantee,
               'column' AS object_type,
               rg.table_schema || '.' || rg.table_name || '.' || rg.column_name AS object_fqn,
               rg.privilege_type AS privilege,
               rg.is_grantable = 'YES' AS grantable
        FROM information_schema.role_column_grants rg
        ORDER BY grantee, object_fqn
        """

    def view_definition_sql(self) -> str:
        return """
        SELECT c.relname AS view_name,
               pg_get_viewdef(c.oid, true) AS view_definition
        FROM pg_class c
        WHERE c.relkind IN ('v', 'm')
          AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = :schema)
        ORDER BY c.relname
        """
