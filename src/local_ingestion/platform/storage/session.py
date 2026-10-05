"""Platform metadata DB session factory (L3 local extension area).

The platform stores its own governance tables (``datasource``, ``catalog_*``,
``scan_run`` …) in a PostgreSQL instance configured via ``DATABASE_URL``. This
module lazily builds a single engine + sessionmaker so every caller shares one
connection pool.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_database_url

_engine: Optional[Engine] = None
_maker: Optional[sessionmaker] = None


def get_engine() -> Engine:
    """Return the shared metadata-DB engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_engine(get_database_url(), future=True, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> sessionmaker:
    """Return a configured ``sessionmaker`` bound to the shared engine."""
    global _maker
    if _maker is None:
        _maker = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _maker


def session_scope() -> Session:
    """Convenience factory returning a new ``Session`` (caller closes it)."""
    return get_sessionmaker()()
