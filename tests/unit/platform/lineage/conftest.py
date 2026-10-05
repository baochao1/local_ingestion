"""Shared fixtures for lineage unit tests that touch PostgreSQL.

Mirrors ``tests/integration/test_pg_integration.py``: skipped unless ``PG_TEST=1``,
then provisions a clean schema and exposes ``session_factory``.
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from local_ingestion.platform.storage.models_ops import (
    LineageClosure,
    LineageColumnEdge,
    LineageTableEdge,
)
from local_ingestion.platform.storage.schema import reset_schema
from sqlalchemy import delete

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)

DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"


@pytest.fixture(scope="module")
def engine():
    url = os.getenv("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, future=True)
    reset_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _clean_lineage(session_factory):
    yield
    with session_factory() as s:
        s.execute(delete(LineageClosure))
        s.execute(delete(LineageColumnEdge))
        s.execute(delete(LineageTableEdge))
        s.commit()
