"""Platform storage layer: ORM models and metadata.

The runtime uses these ORM classes; Alembic migrations under ``migrations/``
are generated from ``Base.metadata``. The initial schema is replayed from
``doc/design/02-schema-ddl.sql`` by migration ``0001_initial``.
"""
from .base import Base, SoftDeleteMixin, TimestampMixin
from .models_core import *  # noqa: F401,F403
from .models_governance import *  # noqa: F401,F403
from .models_ops import *  # noqa: F401,F403

__all__ = ["Base", "TimestampMixin", "SoftDeleteMixin"]
