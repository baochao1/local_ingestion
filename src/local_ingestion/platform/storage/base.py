"""ORM base and shared mixins for the platform storage layer (L3).

Every persisted entity is defined here as the single source of truth; Alembic
migrations are generated from ``Base.metadata``. The raw DDL in
``doc/design/02-schema-ddl.sql`` documents the initial schema and is replayed by
the first migration.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all metadata entities."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = ["Base", "TimestampMixin", "SoftDeleteMixin", "BigInteger", "Boolean",
           "DateTime", "Integer", "SmallInteger", "Text", "JSONB"]
