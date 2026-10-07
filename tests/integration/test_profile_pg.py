"""PG integration tests for profiling (``05-1`` stage 2) — needs ``PG_TEST=1``.

The point of these is not that the SQL runs, but that the numbers are *right*
and that every failure mode lands as a queryable row instead of an exception:
AC-1.2 (exact agreement with a direct query), AC-1.5 (two snapshots), the skip
path, the failure path, and read-only execution (PC2).
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from local_ingestion.platform.dialect import PostgresDialect
from local_ingestion.platform.profile import (
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    ProfileConfig,
    delete_profile,
    get_profile,
    list_history,
    profile_table,
)
from local_ingestion.platform.storage.schema import reset_schema
from local_ingestion.schema.base import DataType

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)

DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"

#: Fixed ids so the FK chain (datasource -> database -> schema -> table) is
#: explicit and cleanup is trivial.
DS_ID = 9101
DB_ID = 9101
SCHEMA_ID = 9101
TABLE_ID = 9101

FIXTURE_SCHEMA = "profiling_fixture"
RELATION = f"{FIXTURE_SCHEMA}.profile_demo"

COLUMNS = [
    ("id", DataType.INTEGER),
    ("amount", DataType.DECIMAL),
    ("customer_name", DataType.TEXT),
    ("created_at", DataType.TIMESTAMP),
    ("score", DataType.INTEGER),  # deliberately contains NULLs
]

ROW_COUNT = 100


@pytest.fixture(scope="module")
def engine() -> Engine:
    eng = create_engine(os.getenv("DATABASE_URL", DEFAULT_URL), future=True)
    reset_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(scope="module")
def seeded(engine, session_factory):
    """Create the FK chain, the business table, and deterministic rows."""
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {FIXTURE_SCHEMA}"))
        conn.execute(
            text(
                "INSERT INTO datasource (id, code, name, ds_type) "
                "VALUES (:i,'pg_prof','PG Profiling','postgres')"
            ),
            {"i": DS_ID},
        )
        conn.execute(
            text(
                "INSERT INTO catalog_database (id, datasource_id, name, fqn) "
                "VALUES (:i,:d,'local_ingestion','pg_prof.local_ingestion')"
            ),
            {"i": DB_ID, "d": DS_ID},
        )
        conn.execute(
            text(
                "INSERT INTO catalog_schema "
                "(id, datasource_id, database_id, name, fqn) "
                "VALUES (:i,:d,:db,'public','pg_prof.local_ingestion.public')"
            ),
            {"i": SCHEMA_ID, "d": DS_ID, "db": DB_ID},
        )
        conn.execute(
            text(
                "INSERT INTO catalog_table (id, datasource_id, schema_id, name, fqn) "
                "VALUES (:i,:d,:s,'profile_demo',"
                "'pg_prof.local_ingestion.public.profile_demo')"
            ),
            {"i": TABLE_ID, "d": DS_ID, "s": SCHEMA_ID},
        )

        conn.execute(text(f"DROP TABLE IF EXISTS {RELATION}"))
        conn.execute(
            text(
                f"CREATE TABLE {RELATION} ("
                "id INTEGER PRIMARY KEY, "
                "amount NUMERIC(10,2), "
                "customer_name TEXT, "
                "created_at TIMESTAMP, "
                "score INTEGER)"
            )
        )
        rows = []
        for index in range(ROW_COUNT):
            rows.append(
                {
                    "id": index,
                    "amount": float(index) * 1.5,
                    "customer_name": f"customer_{index % 7}",  # 7 distinct values
                    "created_at": f"2026-01-{(index % 28) + 1:02d} 00:00:00",
                    # every 5th row is NULL -> 20 nulls
                    "score": None if index % 5 == 0 else index,
                }
            )
        conn.execute(
            text(
                f"INSERT INTO {RELATION} "
                "(id, amount, customer_name, created_at, score) "
                "VALUES (:id, :amount, :customer_name, :created_at, :score)"
            ),
            rows,
        )

    yield

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {RELATION}"))
    with session_factory() as session:
        delete_profile(session, TABLE_ID)


def _run(seeded, engine, session_factory, **overrides):
    config = overrides.pop("config", ProfileConfig())
    return profile_table(
        engine=engine,
        dialect=PostgresDialect(),
        relation=overrides.pop("relation", RELATION),
        columns=overrides.pop("columns", COLUMNS),
        table_id=TABLE_ID,
        datasource_id=DS_ID,
        config=config,
        session_factory=session_factory,
        **overrides,
    )


# --------------------------------------------------------------------------
# AC-1.2 / AC-1.1: correctness against a direct query
# --------------------------------------------------------------------------


def test_full_table_profile_matches_direct_query(seeded, engine, session_factory):
    outcome = _run(seeded, engine, session_factory)

    assert outcome.status == STATUS_SUCCESS, outcome.error_message
    assert outcome.row_count == ROW_COUNT
    # 100 rows is under the first tier, so nothing was sampled (AC-1.1).
    assert outcome.sample_rate == 1.0
    assert outcome.stats["_row_count"] == ROW_COUNT

    with engine.connect() as conn:
        direct = conn.execute(
            text(
                f"SELECT COUNT(*) - COUNT(score) AS nulls, "
                f"COUNT(DISTINCT customer_name) AS distinct_names "
                f"FROM {RELATION}"
            )
        ).mappings().one()

    assert outcome.stats["score"]["null_count"] == direct["nulls"] == 20
    assert outcome.stats["customer_name"]["distinct_count"] == direct["distinct_names"]
    assert direct["distinct_names"] == 7


def test_numeric_metrics_and_quantiles(seeded, engine, session_factory):
    outcome = _run(seeded, engine, session_factory)
    amount = outcome.stats["amount"]

    assert amount["min"] is not None and float(amount["min"]) == 0.0
    assert float(amount["max"]) == float(ROW_COUNT - 1) * 1.5
    # Q1 <= median <= Q3, and the median sits mid-range for uniform data.
    assert float(amount["q1"]) <= float(amount["median"]) <= float(amount["q3"])


def test_histogram_counts_sum_to_non_null_rows(seeded, engine, session_factory):
    outcome = _run(seeded, engine, session_factory)
    histogram = outcome.stats["amount"]["histogram"]

    assert histogram["counts"], "expected at least one bin"
    assert sum(histogram["counts"]) == ROW_COUNT
    assert len(histogram["counts"]) == len(histogram["labels"])
    assert len(histogram["counts"]) <= ProfileConfig().max_bins


def test_string_length_histogram_is_available(seeded, engine, session_factory):
    # FR-M2.2 needs a length distribution for textual columns.
    outcome = _run(seeded, engine, session_factory)
    histogram = outcome.stats["customer_name"]["histogram"]
    assert histogram["by_length"] is True
    assert sum(histogram["counts"]) == ROW_COUNT


def test_temporal_columns_get_min_max_only(seeded, engine, session_factory):
    outcome = _run(seeded, engine, session_factory)
    created = outcome.stats["created_at"]
    assert created["min"] is not None and created["max"] is not None
    # AVG/STDDEV are meaningless for timestamps — they must not be emitted.
    assert "mean" not in created and "stddev" not in created


# --------------------------------------------------------------------------
# AC-1.5: history snapshots
# --------------------------------------------------------------------------


def test_two_profiled_dates_produce_two_snapshots(seeded, engine, session_factory):
    first_day = date(2026, 1, 1)
    second_day = first_day + timedelta(days=1)

    _run(seeded, engine, session_factory, profiled_date=first_day)
    _run(seeded, engine, session_factory, profiled_date=second_day)

    with session_factory() as session:
        history = list_history(session, TABLE_ID)
    assert {row.profiled_date for row in history} >= {first_day, second_day}


def test_reprofiling_same_day_updates_instead_of_appending(
    seeded, engine, session_factory
):
    # History is partitioned by DATE: one snapshot per table per day.
    day = date(2026, 2, 1)
    _run(seeded, engine, session_factory, profiled_date=day)
    _run(seeded, engine, session_factory, profiled_date=day)

    with session_factory() as session:
        rows = [
            row for row in list_history(session, TABLE_ID) if row.profiled_date == day
        ]
    assert len(rows) == 1


def test_current_profile_is_single_row(seeded, engine, session_factory):
    _run(seeded, engine, session_factory)
    _run(seeded, engine, session_factory)

    with session_factory() as session:
        profile = get_profile(session, TABLE_ID)
    assert profile is not None
    assert profile.status == STATUS_SUCCESS
    assert profile.column_count == len(COLUMNS)


# --------------------------------------------------------------------------
# failure / skip paths must be durable, not exceptions
# --------------------------------------------------------------------------


def test_missing_table_fails_with_reason(seeded, engine, session_factory):
    outcome = _run(
        seeded, engine, session_factory, relation=f"{FIXTURE_SCHEMA}.does_not_exist"
    )
    assert outcome.status == STATUS_FAILED
    assert outcome.error_message

    with session_factory() as session:
        assert get_profile(session, TABLE_ID).status == STATUS_FAILED


def test_oversized_table_is_skipped(seeded, engine, session_factory):
    outcome = _run(
        seeded, engine, session_factory, config=ProfileConfig(skip_rows_above=10)
    )
    assert outcome.status == STATUS_SKIPPED
    assert "skip_rows_above" in (outcome.error_message or "")


def test_unsafe_relation_raises(seeded, engine, session_factory):
    from local_ingestion.platform.profile import UnsafeRelationError

    with pytest.raises(UnsafeRelationError):
        _run(seeded, engine, session_factory, relation="demo; DROP TABLE x")


# --------------------------------------------------------------------------
# PC2 / AC-1.4: read-only execution
# --------------------------------------------------------------------------


def test_profiling_runs_under_a_read_only_account(seeded, engine, session_factory):
    """The whole point of PC2: a read-only account suffices."""
    role = "profile_ro_test"
    password = "profile_ro_test"
    with engine.begin() as conn:
        conn.execute(
            text(
                "DO $$ BEGIN "
                f"CREATE ROLE {role} LOGIN PASSWORD '{password}'; "
                "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
        )
        conn.execute(text(f"GRANT USAGE ON SCHEMA {FIXTURE_SCHEMA} TO {role}"))
        conn.execute(
            text(f"GRANT SELECT ON ALL TABLES IN SCHEMA {FIXTURE_SCHEMA} TO {role}")
        )

    url = os.getenv("DATABASE_URL", DEFAULT_URL)
    read_only_url = url.replace("postgres:postgres", f"{role}:{password}")
    ro_engine = create_engine(read_only_url, future=True)
    try:
        outcome = _run(seeded, ro_engine, session_factory)
        assert outcome.status == STATUS_SUCCESS, outcome.error_message
        assert outcome.row_count == ROW_COUNT
    finally:
        ro_engine.dispose()
        # Reassign before dropping; the role may own nothing, but be safe.
        with engine.begin() as conn:
            conn.execute(text(f"REASSIGN OWNED BY {role} TO postgres"))
            conn.execute(text(f"DROP OWNED BY {role}"))
            conn.execute(text(f"DROP ROLE IF EXISTS {role}"))


def test_business_table_is_never_written(seeded, engine, session_factory):
    with engine.connect() as conn:
        before = conn.execute(text(f"SELECT COUNT(*) FROM {RELATION}")).scalar()
        tables_before = {
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = :s"),
                {"s": FIXTURE_SCHEMA},
            )
        }

    _run(seeded, engine, session_factory)

    with engine.connect() as conn:
        after = conn.execute(text(f"SELECT COUNT(*) FROM {RELATION}")).scalar()
        tables_after = {
            row[0]
            for row in conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = :s"),
                {"s": FIXTURE_SCHEMA},
            )
        }

    assert before == after
    assert tables_before == tables_after, "profiling created an object in the source"
