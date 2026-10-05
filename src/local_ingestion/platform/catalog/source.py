"""Catalog statistics sources for the overview rollup (MOD-09 / T-213).

Two implementations share the interface: an in-memory one (tests / MVP) and a
SQLAlchemy one backed by ``catalog_table`` / ``catalog_column`` (``grade_level``
is the grading ordinal landed with the catalog). Quality stats are not yet
available (module not deployed) so the SQL source returns ``None`` and the
overview flags ``quality`` as degraded.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Protocol

from .models import SENSITIVE_GRADE_THRESHOLD, grade_key


class CatalogStatsSource(Protocol):
    def count_tables(self) -> int: ...
    def count_columns(self) -> int: ...
    def count_datasources(self) -> int: ...
    def grade_distribution(self) -> Dict[str, int]: ...
    def sensitive_count(self, threshold: int) -> int: ...
    def quality_distribution(self) -> Optional[Dict[str, int]]: ...


class InMemoryCatalogStatsSource:
    def __init__(self, table_grades: Optional[List[int]] = None,
                 column_grades: Optional[List[int]] = None,
                 datasource_count: int = 0) -> None:
        self._tg: List[int] = list(table_grades or [])
        self._cg: List[int] = list(column_grades or [])
        self._ds: List[int] = [0] * int(datasource_count or 0)

    def count_tables(self) -> int:
        return len(self._tg)

    def count_columns(self) -> int:
        return len(self._cg)

    def count_datasources(self) -> int:
        return len(self._ds)

    def grade_distribution(self) -> Dict[str, int]:
        d: Dict[str, int] = {}
        for g in self._tg + self._cg:
            key = grade_key(g)
            d[key] = d.get(key, 0) + 1
        return d

    def sensitive_count(self, threshold: int = SENSITIVE_GRADE_THRESHOLD) -> int:
        return sum(1 for g in self._tg + self._cg if g is not None and g >= threshold)

    def quality_distribution(self) -> Optional[Dict[str, int]]:
        return None  # quality module not deployed -> degraded


class SqlCatalogStatsSource:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def count_tables(self) -> int:
        from ..storage.models_core import CatalogTable

        with self._sf() as s:
            return s.query(CatalogTable).filter(CatalogTable.deleted_at.is_(None)).count()

    def count_columns(self) -> int:
        from ..storage.models_core import CatalogColumn

        with self._sf() as s:
            return s.query(CatalogColumn).filter(CatalogColumn.deleted_at.is_(None)).count()

    def count_datasources(self) -> int:
        from ..storage.models_core import Datasource

        with self._sf() as s:
            return s.query(Datasource).filter(Datasource.deleted_at.is_(None)).count()

    def grade_distribution(self) -> Dict[str, int]:
        from ..storage.models_core import CatalogColumn, CatalogTable

        with self._sf() as s:
            tg = s.query(CatalogTable.grade_level).filter(CatalogTable.deleted_at.is_(None)).all()
            cg = s.query(CatalogColumn.grade_level).filter(CatalogColumn.deleted_at.is_(None)).all()
        d: Dict[str, int] = {}
        for (g,) in list(tg) + list(cg):
            # 统一为 L1..L4 / ungraded，越界值（如 5）归入未分级而不是被静默丢弃
            key = grade_key(g)
            d[key] = d.get(key, 0) + 1
        return d

    def sensitive_count(self, threshold: int = SENSITIVE_GRADE_THRESHOLD) -> int:
        from ..storage.models_core import CatalogColumn, CatalogTable

        with self._sf() as s:
            t = (
                s.query(CatalogTable)
                .filter(CatalogTable.deleted_at.is_(None), CatalogTable.grade_level >= threshold)
                .count()
            )
            c = (
                s.query(CatalogColumn)
                .filter(CatalogColumn.deleted_at.is_(None), CatalogColumn.grade_level >= threshold)
                .count()
            )
        return t + c

    def quality_distribution(self) -> Optional[Dict[str, int]]:
        return None  # quality module not deployed -> degraded
