"""End-to-end PostgreSQL integration test for MOD-07 lineage (T-205 -> production).

Creates a real table + view in a throwaway schema and runs the collector against a
live ``ADMIN``-style connection, proving the full parse -> edge -> query path works
against the actual PostgreSQL catalog (``pg_get_viewdef``).
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from local_ingestion.platform.lineage.collector import collect_lineage
from local_ingestion.platform.lineage.service import LineageService
from local_ingestion.platform.storage.schema import reset_schema

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)

DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"
SCHEMA = "lineage_it"


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(DEFAULT_URL, future=True)
    reset_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def _setup_view(engine):
    with engine.connect() as c:
        c.execute(text(f"DROP VIEW IF EXISTS {SCHEMA}.v"))
        c.execute(text(f"DROP TABLE IF EXISTS {SCHEMA}.src"))
        c.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        c.execute(text(f"CREATE TABLE {SCHEMA}.src (id int)"))
        c.execute(text(f"CREATE VIEW {SCHEMA}.v AS SELECT id FROM {SCHEMA}.src"))
        c.commit()


def _teardown_view(engine):
    with engine.connect() as c:
        c.execute(text(f"DROP VIEW IF EXISTS {SCHEMA}.v"))
        c.execute(text(f"DROP TABLE IF EXISTS {SCHEMA}.src"))
        c.commit()


def test_end_to_end_with_real_view(engine, session_factory):
    _setup_view(engine)
    try:
        with engine.connect() as c:
            res = collect_lineage(
                session_factory, datasource_id=1, ds_code="ds1",
                db="local_ingestion", schema=SCHEMA, conn=c, dialect_name="postgres",
            )
        assert res.table_edges >= 1
        assert res.views == 1

        svc = LineageService(session_factory)
        src_fqn = f"ds1.local_ingestion.{SCHEMA}.src"
        v_fqn = f"ds1.local_ingestion.{SCHEMA}.v"
        down = svc.downstream(src_fqn)
        assert any(n.fqn == v_fqn for n in down)
        rep = svc.impact_scope(src_fqn)
        assert not rep.degraded and rep.total >= 1
    finally:
        _teardown_view(engine)
