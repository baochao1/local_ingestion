"""Quality case execution against real PostgreSQL (FR-M5) — needs ``PG_TEST=1``.

Compilation is covered by unit tests; what needs a database is that the pushed
down SQL actually returns the right counts and that results land in
``quality_result`` — the part that was missing entirely before.
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from local_ingestion.platform.quality.service import QualityService
from local_ingestion.platform.storage.models_governance import QualityRule
from local_ingestion.platform.storage.schema import reset_schema

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)

DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"

FIXTURE_SCHEMA = "quality_fixture"
RELATION = f"{FIXTURE_SCHEMA}.orders"
TABLE_ID = 9501
DS_ID = 9501
DB_ID = 9501
SCHEMA_ID = 9501


@pytest.fixture(scope="module")
def ready():
    engine = create_engine(os.getenv("DATABASE_URL", DEFAULT_URL), future=True)
    reset_schema(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {FIXTURE_SCHEMA}"))
        # quality_result.table_id has an FK to catalog_table, so the chain the
        # platform expects must exist even though this test only runs rules.
        conn.execute(
            text(
                "INSERT INTO datasource (id, code, name, ds_type) "
                "VALUES (:i,'q_ds','Q DS','postgres')"
            ),
            {"i": DS_ID},
        )
        conn.execute(
            text(
                "INSERT INTO catalog_database (id, datasource_id, name, fqn) "
                "VALUES (:i,:d,'db','q_ds.db')"
            ),
            {"i": DB_ID, "d": DS_ID},
        )
        conn.execute(
            text(
                "INSERT INTO catalog_schema (id, datasource_id, database_id, name, fqn) "
                "VALUES (:i,:d,:db,'public','q_ds.db.public')"
            ),
            {"i": SCHEMA_ID, "d": DS_ID, "db": DB_ID},
        )
        conn.execute(
            text(
                "INSERT INTO catalog_table (id, datasource_id, schema_id, name, fqn) "
                "VALUES (:i,:d,:s,'orders','q_ds.db.public.orders')"
            ),
            {"i": TABLE_ID, "d": DS_ID, "s": SCHEMA_ID},
        )
        conn.execute(text(f"DROP TABLE IF EXISTS {RELATION}"))
        conn.execute(
            text(f"CREATE TABLE {RELATION} (id INTEGER PRIMARY KEY, email TEXT, amount NUMERIC(10,2))")
        )
        # id 3 has a NULL email; amount 200 exceeds the declared max of 100.
        conn.execute(
            text(f"INSERT INTO {RELATION} (id, email, amount) VALUES (:id, :email, :amount)"),
            [
                {"id": 1, "email": "a@x.com", "amount": 10.0},
                {"id": 2, "email": "b@x.com", "amount": 20.0},
                {"id": 3, "email": None, "amount": 200.0},
            ],
        )

    with factory() as session:
        session.add(
            QualityRule(
                code="q_email_not_null",
                name="email 非空",
                rule_type="not_null",
                target_type="column",
                definition={"column": "email"},
            )
        )
        session.add(
            QualityRule(
                code="q_amount_range",
                name="amount 区间",
                rule_type="range",
                target_type="column",
                definition={"column": "amount", "min": 0, "max": 100},
            )
        )
        session.add(
            QualityRule(
                code="q_id_unique",
                name="id 唯一",
                rule_type="unique",
                target_type="column",
                definition={"column": "id"},
            )
        )
        session.commit()

    yield engine, factory

    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {RELATION}"))
    engine.dispose()


def test_rules_execute_and_persist(ready):
    engine, factory = ready
    service = QualityService(factory)

    results = service.run(engine=engine, relation=RELATION, table_id=TABLE_ID)
    by_code = {result.rule_code: result for result in results}

    # one NULL email -> offending_rows == 1 -> fails the default threshold of 0
    assert by_code["q_email_not_null"].metric_value == 1
    assert by_code["q_email_not_null"].passed is False
    # amount 200 is out of range -> 1 offending row
    assert by_code["q_amount_range"].metric_value == 1
    assert by_code["q_amount_range"].passed is False
    # ids are unique -> 0 offending rows
    assert by_code["q_id_unique"].metric_value == 0
    assert by_code["q_id_unique"].passed is True

    rows = service.history(TABLE_ID)
    assert len(rows) == 3, "results must be persisted, not just returned"


def test_success_rate_reflects_outcomes(ready):
    engine, factory = ready
    service = QualityService(factory)
    results = service.run(engine=engine, relation=RELATION, table_id=TABLE_ID)
    expected = sum(1 for result in results if result.passed) / len(results)
    assert service.success_rate(TABLE_ID) == pytest.approx(expected)


def test_unrunnable_rule_becomes_a_failed_result(ready):
    """A rule that cannot run is a result, not a crash (FR-M5.3)."""
    engine, factory = ready
    service = QualityService(factory)

    class _Bad:
        code = "q_broken"
        rule_type = "not_null"
        definition = {}  # missing column -> compile raises

    results = service.run(
        engine=engine, relation=RELATION, table_id=TABLE_ID, rules=[_Bad()]
    )
    assert results[0].passed is False
    assert "error" in results[0].detail
