"""Fixtures for permission unit tests (PG-backed, skipped without PG_TEST)."""
import os

import pytest
from sqlalchemy import create_engine, delete as sa_delete
from sqlalchemy.orm import sessionmaker

from local_ingestion.platform.storage.models_core import Datasource
from local_ingestion.platform.storage.models_ops import Account, AccountGrant
from local_ingestion.platform.storage.schema import reset_schema

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)

DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(DEFAULT_URL, future=True)
    reset_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _clean(session_factory):
    # insert a datasource (id=1) and clear prior permission rows
    with session_factory() as s:
        if s.get(Datasource, 1) is None:
            s.add(Datasource(id=1, tenant_id=0, code="ds1", name="ds1", ds_type="postgres",
                             scan_config={}))
        s.execute(sa_delete(AccountGrant))
        s.execute(sa_delete(Account))
        s.commit()
    yield
    with session_factory() as s:
        s.execute(sa_delete(AccountGrant))
        s.execute(sa_delete(Account))
        s.commit()
