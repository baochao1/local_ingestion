"""Dialect abstraction package (T-114, FR-2.4). L3 bypass for L1 connectors."""
from __future__ import annotations

from .base import Dialect, _longest_match
from .mysql import MySQLDialect
from .postgres import PostgresDialect
from .registry import UnknownDialectError, available_dialects, get_dialect
from .snowflake import SnowflakeDialect

__all__ = [
    "Dialect",
    "PostgresDialect",
    "MySQLDialect",
    "SnowflakeDialect",
    "get_dialect",
    "available_dialects",
    "UnknownDialectError",
    "_longest_match",
]
