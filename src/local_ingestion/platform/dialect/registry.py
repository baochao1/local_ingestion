"""Dialect registry (T-114).

Maps a data-source type (the same ``ds_type`` used by
``platform.connections``) to a concrete :class:`Dialect`. Unknown types raise
:class:`UnknownDialectError` so the caller can decide whether to fall back to
the legacy L1 connector during the dual-track period.
"""
from __future__ import annotations

from .base import Dialect
from .mysql import MySQLDialect
from .postgres import PostgresDialect
from .snowflake import SnowflakeDialect

_DIALECTS: dict[str, type[Dialect]] = {
    "postgres": PostgresDialect,
    "postgresql": PostgresDialect,
    "mysql": MySQLDialect,
    "mariadb": MySQLDialect,
    "snowflake": SnowflakeDialect,
}


class UnknownDialectError(ValueError):
    """Raised when no dialect is registered for a data-source type."""


def get_dialect(name: str) -> Dialect:
    """Return a :class:`Dialect` instance for ``name`` (case/space insensitive)."""
    key = (name or "").strip().lower()
    cls = _DIALECTS.get(key)
    if cls is None:
        raise UnknownDialectError(
            f"未知方言：{name!r}（已注册：{', '.join(sorted(set(_DIALECTS)))}）"
        )
    return cls()


def available_dialects() -> list[str]:
    """Return the canonical (de-duplicated) registered dialect names."""
    return sorted(set(_DIALECTS))
