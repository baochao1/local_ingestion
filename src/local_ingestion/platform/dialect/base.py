"""Dialect abstraction (T-114, FR-2.4) — L3 bypass, does NOT modify L1.

This package centralises the system-catalog SQL and type mappings that the
upstream L1 ``local_ingestion.core.connectors.*`` classes currently hard-code
inline. Per code-boundary decision D1 the L1 connectors are left untouched;
once the scanning pipeline migrates to this layer the duplicated SQL/maps in
L1 can be deleted (dual-track period).

The contracts here are a superset of what L1 currently implements:

* metadata catalog queries (databases / schemas / tables / columns);
* ``normalize_type`` — the only behaviour that is correctness-critical and is
  asserted, string-for-string, against the L1 mappers in the test suite;
* capability declaration (``supports_sampling`` / ``sample_sql``), forward
  input for MOD-03;
* account / grant listing SQL (``list_accounts_sql`` / ``list_grants_sql``),
  forward input for MOD-08 — these mirror the read-only probe SQL already used
  by ``platform.connections``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict

from local_ingestion.schema.base import DataType


def _longest_match(raw_upper: str, mapping: Dict[str, DataType]) -> DataType:
    """Match ``raw_upper`` against ``mapping`` by longest key first.

    Mirrors the substring-matching used by the L1 connector mappers exactly
    (``sorted(keys, key=len, reverse=True)`` then ``key in raw_upper``), so the
    normalised result is identical during the dual-track period.
    """
    for key in sorted(mapping, key=len, reverse=True):
        if key in raw_upper:
            return mapping[key]
    return DataType.UNKNOWN


class Dialect(ABC):
    """Abstraction over one database's metadata queries and type mapping."""

    # -- identity ---------------------------------------------------------
    @property
    @abstractmethod
    def name(self) -> str:
        """Normalised dialect name, e.g. ``"postgres"``."""

    # -- metadata catalog queries ----------------------------------------
    @abstractmethod
    def list_databases_sql(self) -> str:
        """SQL returning one row per database (column 0 = name)."""

    @abstractmethod
    def list_schemas_sql(self) -> str:
        """SQL returning schema rows; may reference the ``:database`` param."""

    @abstractmethod
    def list_tables_sql(self) -> str:
        """SQL returning table rows; references the ``:schema`` param."""

    @abstractmethod
    def list_columns_sql(self) -> str:
        """SQL returning column rows; references ``:schema`` / ``:table``."""

    # -- type normalization ----------------------------------------------
    @abstractmethod
    def normalize_type(self, raw_type: str, **meta: object) -> DataType:
        """Map a raw database type string to :class:`DataType`."""

    # -- capability declaration (MOD-03) ---------------------------------
    @property
    def supports_sampling(self) -> bool:
        """Whether this dialect can produce a row-level sample."""
        return False

    def sample_sql(self, table: str, rate: float) -> str:
        """Return SQL sampling ``table`` at fraction ``rate`` (0 < rate <= 1).

        ``table`` must be a caller-validated, already-qualified identifier;
        only ``rate`` is rendered as a numeric literal here.
        """
        raise NotImplementedError(f"{self.name} does not support sampling")

    # -- account / grant queries (MOD-08) --------------------------------
    def list_accounts_sql(self) -> str:
        """SQL returning one row per account/login role."""
        raise NotImplementedError(f"{self.name} has no account listing SQL")

    def list_grants_sql(self) -> str:
        """SQL returning privilege grants (grantee / object / privilege)."""
        raise NotImplementedError(f"{self.name} has no grant listing SQL")
