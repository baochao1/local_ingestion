"""Business metadata (MOD-09 / FR-14)."""
from __future__ import annotations

from .models import (
    BusinessMetadataInput,
    BusinessMetadataView,
    BusinessTermInput,
    BusinessTermView,
)
from .repository import (
    BusinessRepository,
    InMemoryBusinessRepository,
    SqlBusinessRepository,
)
from .service import BusinessService


def build_in_memory_business_stack():
    """Fully wired in-memory business stack (no database)."""
    repo = InMemoryBusinessRepository()
    return BusinessService(repo), repo


def build_sql_business_stack(session_factory=None):
    """同内存版装配，但业务术语/实体元数据落在 PostgreSQL。"""
    if session_factory is None:
        from ..storage.session import session_scope

        session_factory = session_scope
    repo = SqlBusinessRepository(session_factory)
    return BusinessService(repo), repo


__all__ = [
    "BusinessMetadataInput",
    "BusinessMetadataView",
    "BusinessTermInput",
    "BusinessTermView",
    "BusinessRepository",
    "InMemoryBusinessRepository",
    "SqlBusinessRepository",
    "BusinessService",
    "build_in_memory_business_stack",
    "build_sql_business_stack",
]
