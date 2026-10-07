"""Profiles REST API integration (``05-1`` stage 3) — needs ``PG_TEST=1``.

Stage 3 is where the profile becomes visible; these tests assert the contract
the UI relies on: camelCase keys, ``columns`` reshaped for rendering,
``null_ratio`` derived, 404 for "never profiled" (distinct from "failed"), and
history/snapshot endpoints that make FR-M2.3 comparison possible.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from local_ingestion.api.app import app
from local_ingestion.platform.dialect import PostgresDialect
from local_ingestion.platform.profile import ProfileConfig, profile_table
from local_ingestion.platform.storage.schema import reset_schema
from local_ingestion.schema.base import DataType

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)

DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"

DS_ID = 9201
DB_ID = 9201
SCHEMA_ID = 9201
TABLE_ID = 9201
NEVER_PROFILED_ID = 9202

FIXTURE_SCHEMA = "profiling_api"
RELATION = f"{FIXTURE_SCHEMA}.demo"

COLUMNS = [("id", DataType.INTEGER), ("amount", DataType.DECIMAL)]
ROWS = 40


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(os.getenv("DATABASE_URL", DEFAULT_URL), future=True)
    reset_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(scope="module")
def profiled(engine, session_factory):
    """FK chain + business table + one completed profile run."""
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {FIXTURE_SCHEMA}"))
        conn.execute(
            text(
                "INSERT INTO datasource (id, code, name, ds_type) "
                "VALUES (:i,'pg_api','PG API','postgres')"
            ),
            {"i": DS_ID},
        )
        conn.execute(
            text(
                "INSERT INTO catalog_database (id, datasource_id, name, fqn) "
                "VALUES (:i,:d,'local_ingestion','pg_api.local_ingestion')"
            ),
            {"i": DB_ID, "d": DS_ID},
        )
        conn.execute(
            text(
                "INSERT INTO catalog_schema "
                "(id, datasource_id, database_id, name, fqn) "
                "VALUES (:i,:d,:db,'public','pg_api.local_ingestion.public')"
            ),
            {"i": SCHEMA_ID, "d": DS_ID, "db": DB_ID},
        )
        conn.execute(
            text(
                "INSERT INTO catalog_table (id, datasource_id, schema_id, name, fqn) "
                "VALUES (:i,:d,:s,'demo','pg_api.local_ingestion.public.demo')"
            ),
            {"i": TABLE_ID, "d": DS_ID, "s": SCHEMA_ID},
        )

        conn.execute(text(f"DROP TABLE IF EXISTS {RELATION}"))
        conn.execute(
            text(
                f"CREATE TABLE {RELATION} "
                "(id INTEGER PRIMARY KEY, amount NUMERIC(10,2))"
            )
        )
        conn.execute(
            text(f"INSERT INTO {RELATION} (id, amount) VALUES (:id, :amount)"),
            [{"id": index, "amount": float(index)} for index in range(ROWS)],
        )

    outcome = profile_table(
        engine=engine,
        dialect=PostgresDialect(),
        relation=RELATION,
        columns=COLUMNS,
        table_id=TABLE_ID,
        datasource_id=DS_ID,
        config=ProfileConfig(),
        session_factory=session_factory,
        profiled_date=date(2026, 3, 1),
    )
    assert outcome.status == "success", outcome.error_message

    yield TABLE_ID

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {RELATION}"))


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# --------------------------------------------------------------------------
# current profile
# --------------------------------------------------------------------------


def test_read_profile_returns_camel_case_payload(profiled, client):
    response = client.get(f"/api/v1/profiles/tables/{profiled}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["tableId"] == profiled
    assert body["status"] == "success"
    assert body["rowCount"] == ROWS
    # snake_case must not leak into the API boundary (ADR-8 §4).
    assert "row_count" not in body


def test_columns_are_reshaped_for_rendering(profiled, client):
    body = client.get(f"/api/v1/profiles/tables/{profiled}").json()
    names = {column["name"] for column in body["columns"]}
    assert names == {"id", "amount"}

    amount = next(column for column in body["columns"] if column["name"] == "amount")
    assert amount["distinctCount"] == ROWS
    # null_ratio is derived, not stored — the UI needs the ratio, not the count.
    assert amount["nullRatio"] == 0
    assert amount["histogram"]["counts"], "expected a histogram for a numeric column"
    assert len(amount["histogram"]["counts"]) == len(amount["histogram"]["labels"])


def test_table_level_marker_is_not_exposed_as_a_column(profiled, client):
    # ``_row_count`` lives in stats but is table-level metadata.
    body = client.get(f"/api/v1/profiles/tables/{profiled}").json()
    assert all(not column["name"].startswith("_") for column in body["columns"])


def test_never_profiled_table_returns_404(profiled, client):
    response = client.get(f"/api/v1/profiles/tables/{NEVER_PROFILED_ID}")
    assert response.status_code == 404


# --------------------------------------------------------------------------
# history (FR-M2.3)
# --------------------------------------------------------------------------


def test_history_lists_snapshot_dates(profiled, client):
    body = client.get(f"/api/v1/profiles/tables/{profiled}/history").json()
    dates = [item["profiledDate"] for item in body["items"]]
    assert "2026-03-01" in dates
    # stats are deliberately omitted from the list — otherwise it is enormous.
    assert "columns" not in body["items"][0]


def test_snapshot_returns_full_column_stats(profiled, client):
    body = client.get(f"/api/v1/profiles/tables/{profiled}/history/2026-03-01").json()
    assert body["profiledDate"] == "2026-03-01"
    names = {column["name"] for column in body["columns"]}
    assert names == {"id", "amount"}


def test_unknown_snapshot_date_returns_404(profiled, client):
    missing = (date(2026, 3, 1) + timedelta(days=9)).isoformat()
    response = client.get(f"/api/v1/profiles/tables/{profiled}/history/{missing}")
    assert response.status_code == 404
