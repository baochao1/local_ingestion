"""Schema bootstrap for a local PostgreSQL instance (T-113 / integration tests).

The production schema is owned by Alembic (``migrations/0001_initial.py`` replays
``doc/design/02-schema-ddl.sql``). This helper lets the seed script and the PG
integration tests build the *same* schema directly from that DDL, and attach
explicit monthly partitions for the RANGE-partitioned tables.

The DDL deliberately omits a DEFAULT partition ("会阻塞后续 ATTACH"), so for tests
we create a bounded set of monthly partitions covering the test window. This is
test-only scaffolding and does not change the reviewed design.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Tuple

from sqlalchemy import Engine
from sqlalchemy import text as _text

# schema.py lives in src/local_ingestion/platform/storage/; the design DDL sits at
# the repository root under doc/design/. parents[4] is the repository root.
_DDL_PATH = Path(__file__).resolve().parents[4] / "doc" / "design" / "02-schema-ddl.sql"

# (table, partition_key, key_kind) for every RANGE-partitioned table in the DDL.
_PARTITIONED: List[Tuple[str, str, str]] = [
    ("table_snapshot", "snapshot_date", "date"),
    ("column_snapshot", "snapshot_date", "date"),
    ("change_event", "detected_at", "ts"),
    ("sample_value", "sampled_at", "ts"),
    ("audit_log", "occurred_at", "ts"),
    ("table_profile_history", "profiled_date", "date"),
]


def init_schema(engine: Engine, ddl_path: Path | None = None) -> None:
    """Create every table by replaying the reviewed DDL."""
    path = Path(ddl_path) if ddl_path else _DDL_PATH
    sql = path.read_text(encoding="utf-8").replace("BEGIN;", "").replace("COMMIT;", "")
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


def drop_schema(engine: Engine) -> None:
    """Drop the whole ``public`` schema (tables + partitions) and recreate it.

    ``Base.metadata.drop_all`` cannot be used because the partition child tables
    are not part of the ORM metadata, so a plain DROP SCHEMA CASCADE is the only
    clean reset.
    """
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS public")


def ensure_test_partitions(engine: Engine, years: Tuple[int, int] = (2025, 2027)) -> None:
    """Create explicit monthly partitions for the partitioned tables.

    Covers every month in ``[years[0], years[1]]`` inclusive. Idempotent.
    """
    stmts: List[str] = []
    for y in range(years[0], years[1] + 1):
        for m in range(1, 13):
            if m == 12:
                ny, nm = y + 1, 1
            else:
                ny, nm = y, m + 1
            start = date(y, m, 1).isoformat()
            end = date(ny, nm, 1).isoformat()
            for table, _key, kind in _PARTITIONED:
                pname = f"{table}_{y}{m:02d}"
                if kind == "ts":
                    lo = f"{start} 00:00:00+00"
                    hi = f"{end} 00:00:00+00"
                else:
                    lo, hi = start, end
                stmts.append(
                    f"CREATE TABLE IF NOT EXISTS {pname} PARTITION OF {table} "
                    f"FOR VALUES FROM ('{lo}') TO ('{hi}')"
                )
    with engine.begin() as conn:
        for st in stmts:
            conn.exec_driver_sql(st)


def reset_schema(engine: Engine) -> None:
    """Drop everything and rebuild a clean, partition-ready schema (test helper)."""
    drop_schema(engine)
    init_schema(engine)
    ensure_test_partitions(engine)
