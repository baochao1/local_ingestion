"""Search repository boundary (MOD-09 / T-211).

Two implementations share one interface:

* ``InMemoryCatalogRepository`` — unit tests and the single-instance MVP.
* ``SqlCatalogRepository`` — queries ``catalog_table`` / ``catalog_column``
  (PostgreSQL ``ILIKE`` against the GIN/trigram indexes landed in T-104).

Both return normalized :class:`CatalogRecord` objects so the service applies
scoring uniformly regardless of backend.
"""
from __future__ import annotations

from typing import List, Optional, Protocol

from .models import CatalogRecord


class CatalogRepository(Protocol):
    def search(
        self,
        *,
        term: Optional[str],
        datasource_id: Optional[int] = None,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        owner: Optional[str] = None,
        sensitive_only: bool = False,
        grade_min: Optional[int] = None,
    ) -> List[CatalogRecord]: ...


class InMemoryCatalogRepository:
    def __init__(self, records: Optional[List[CatalogRecord]] = None) -> None:
        self._records = list(records or [])

    def search(
        self,
        *,
        term: Optional[str],
        datasource_id: Optional[int] = None,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        owner: Optional[str] = None,
        sensitive_only: bool = False,
        grade_min: Optional[int] = None,
    ) -> List[CatalogRecord]:
        q = (term or "").lower()
        toks = q.split() if q else []
        out: List[CatalogRecord] = []
        for r in self._records:
            if datasource_id is not None and r.datasource_id != datasource_id:
                continue
            if type is not None and r.entity_type != type:
                continue
            if owner is not None and (r.owner or "").lower() != owner.lower():
                continue
            if sensitive_only and not r.is_pii:
                continue
            if grade_min is not None and r.importance < grade_min:
                continue
            if tags:
                if not any(t.lower() in [x.lower() for x in r.tags] for t in tags):
                    continue
            if toks:
                haystack = " ".join(
                    [r.name, r.description or "", " ".join(r.tags), r.owner or ""]
                ).lower()
                # OR match across tokens (MVP; SQL backend uses a single ILIKE).
                if not any(tok in haystack for tok in toks):
                    continue
            out.append(r)
        return out


class SqlCatalogRepository:
    """Queries catalog tables; relies on the GIN/trigram indexes for speed."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def search(
        self,
        *,
        term: Optional[str],
        datasource_id: Optional[int] = None,
        type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        owner: Optional[str] = None,
        sensitive_only: bool = False,
        grade_min: Optional[int] = None,
    ) -> List[CatalogRecord]:
        from sqlalchemy import or_, select

        from ..storage.models_core import CatalogColumn, CatalogTable

        with self._sf() as s:
            records: List[CatalogRecord] = []
            if type in (None, "table"):
                stmt = select(CatalogTable).where(CatalogTable.deleted_at.is_(None))
                if datasource_id is not None:
                    stmt = stmt.where(CatalogTable.datasource_id == datasource_id)
                if owner is not None:
                    stmt = stmt.where(CatalogTable.owner.ilike(f"%{owner}%"))
                if term:
                    stmt = stmt.where(CatalogTable.name.ilike(f"%{term}%"))
                if grade_min is not None:
                    stmt = stmt.where(CatalogTable.grade_level >= grade_min)
                if tags:
                    for t in tags:
                        stmt = stmt.where(CatalogTable.tags.contains([t]))
                for m in s.scalars(stmt).all():
                    records.append(
                        CatalogRecord(
                            fqn=m.fqn,
                            name=m.name,
                            entity_type="table",
                            datasource_id=m.datasource_id,
                            schema=m.fqn.rsplit(".", 1)[0] if "." in m.fqn else None,
                            description=m.description,
                            tags=list(m.tags or []),
                            owner=m.owner,
                            is_pii="PII" in (m.tags or []),
                            importance=m.grade_level or 0,
                            id=m.id,
                        )
                    )
            if type in (None, "column"):
                stmt = select(CatalogColumn).where(CatalogColumn.deleted_at.is_(None))
                if datasource_id is not None:
                    # join through table to filter by datasource
                    from ..storage.models_core import CatalogTable as CT

                    stmt = stmt.join(CT, CatalogColumn.table_id == CT.id).where(
                        CT.datasource_id == datasource_id
                    )
                if term:
                    stmt = stmt.where(CatalogColumn.name.ilike(f"%{term}%"))
                if grade_min is not None:
                    stmt = stmt.where(CatalogColumn.grade_level >= grade_min)
                if sensitive_only:
                    stmt = stmt.where(CatalogColumn.tags.contains(["PII"]))
                for m in s.scalars(stmt).all():
                    records.append(
                        CatalogRecord(
                            fqn=m.fqn,
                            name=m.name,
                            entity_type="column",
                            datasource_id=m.datasource_id,
                            parent_fqn=m.fqn.rsplit(".", 1)[0] if "." in m.fqn else None,
                            description=m.description,
                            tags=list(m.tags or []),
                            is_pii="PII" in (m.tags or []),
                            importance=m.grade_level or 0,
                            id=m.id,
                        )
                    )
            return records
