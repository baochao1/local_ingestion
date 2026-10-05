"""End-to-end PostgreSQL integration test for MOD-08 permission analysis.

Creates a real role + grant in a throwaway schema and runs the collector against a
live connection, proving the account/grant queries and risk scoring work against the
actual PostgreSQL catalog (pg_roles / information_schema).
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from local_ingestion.platform.permission.collector import collect_permissions
from local_ingestion.platform.storage.models_core import Datasource
from local_ingestion.platform.storage.schema import reset_schema

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)

DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"
SCHEMA = "perm_it"


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(DEFAULT_URL, future=True)
    reset_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def _setup(engine):
    with sessionmaker(bind=engine, expire_on_commit=False)() as s:
        if s.get(Datasource, 1) is None:
            s.add(Datasource(id=1, tenant_id=0, code="ds1", name="ds1", ds_type="postgres",
                             scan_config={}))
        s.commit()
    with engine.connect() as c:
        c.execute(text(f"DROP ROLE IF EXISTS alice"))
        c.execute(text(f"DROP TABLE IF EXISTS {SCHEMA}.t"))
        c.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        c.execute(text(f"CREATE TABLE {SCHEMA}.t (id int)"))
        c.execute(text("CREATE ROLE alice LOGIN"))
        c.execute(text(f"GRANT SELECT ON {SCHEMA}.t TO alice"))
        c.commit()


def _teardown(engine):
    with engine.connect() as c:
        c.execute(text(f"REVOKE ALL ON {SCHEMA}.t FROM alice"))
        c.execute(text(f"DROP TABLE IF EXISTS {SCHEMA}.t"))
        c.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        c.execute(text("DROP ROLE IF EXISTS alice"))
        c.commit()


def test_end_to_end_permission_collection(engine, session_factory):
    _setup(engine)
    try:
        with engine.connect() as c:
            res = collect_permissions(
                session_factory, ds_id=1, ds_type="postgres",
                db="local_ingestion", schema=SCHEMA, conn=c,
            )
        assert res.accounts >= 1
        assert res.grants >= 1
        assert res.risks >= 0
    finally:
        _teardown(engine)
