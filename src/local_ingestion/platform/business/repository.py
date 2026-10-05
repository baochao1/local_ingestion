"""Business metadata repositories (MOD-09 / FR-14).

In-memory + SQLAlchemy implementations behind a common Protocol. The SQL variant
is best-effort (exercised against Postgres in integration); unit tests use memory.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Protocol

from .models import (
    BusinessMetadataInput,
    BusinessMetadataView,
    BusinessTermInput,
    BusinessTermView,
)


class BusinessRepository(Protocol):
    def upsert_term(self, inp: BusinessTermInput) -> BusinessTermView: ...
    def list_terms(self, domain: Optional[str] = None) -> List[BusinessTermView]: ...
    def get_term(self, term_code: str) -> Optional[BusinessTermView]: ...
    def upsert_metadata(self, entity_type: str, entity_id: int,
                        inp: BusinessMetadataInput) -> BusinessMetadataView: ...
    def get_metadata(self, entity_type: str, entity_id: int) -> Optional[BusinessMetadataView]: ...
    def set_tags(self, entity_type: str, entity_id: int,
                 tags: Dict[str, str]) -> BusinessMetadataView: ...
    def find_by_alias(self, alias: str) -> List[BusinessMetadataView]: ...


def _term_view(m) -> BusinessTermView:
    return BusinessTermView(
        id=m.id, term_code=m.term_code, term_name=m.term_name, domain=m.domain,
        definition=m.definition, owner=m.owner, status=m.status,
        created_at=m.created_at, updated_at=m.updated_at,
    )


def _meta_view(m) -> BusinessMetadataView:
    return BusinessMetadataView(
        id=m.id, entity_type=m.entity_type, entity_id=m.entity_id, alias=m.alias,
        business_desc=m.business_desc, domain=m.domain, owner_business=m.owner_business,
        term_codes=list(m.term_codes or []), tags=dict(m.tags or {}),
        created_at=m.created_at, updated_at=m.updated_at,
    )


class InMemoryBusinessRepository:
    def __init__(self) -> None:
        self._terms: Dict[str, BusinessTermView] = {}
        self._seq_t = 1
        self._meta: Dict[tuple, BusinessMetadataView] = {}
        self._seq_m = 1

    def upsert_term(self, inp: BusinessTermInput) -> BusinessTermView:
        now = datetime.now()
        if inp.term_code in self._terms:
            v = self._terms[inp.term_code]
            v.term_name = inp.term_name
            v.domain = inp.domain
            v.definition = inp.definition
            v.owner = inp.owner
            v.status = inp.status
            v.updated_at = now
            return v
        v = BusinessTermView(
            id=self._seq_t, term_code=inp.term_code, term_name=inp.term_name,
            domain=inp.domain, definition=inp.definition, owner=inp.owner,
            status=inp.status, created_at=now, updated_at=now,
        )
        self._seq_t += 1
        self._terms[inp.term_code] = v
        return v

    def list_terms(self, domain: Optional[str] = None) -> List[BusinessTermView]:
        return [v for v in self._terms.values() if domain is None or v.domain == domain]

    def get_term(self, term_code: str) -> Optional[BusinessTermView]:
        return self._terms.get(term_code)

    def upsert_metadata(self, entity_type: str, entity_id: int,
                        inp: BusinessMetadataInput) -> BusinessMetadataView:
        now = datetime.now()
        key = (entity_type, entity_id)
        existing = self._meta.get(key)
        if existing:
            if inp.alias is not None:
                existing.alias = inp.alias
            if inp.business_desc is not None:
                existing.business_desc = inp.business_desc
            if inp.domain is not None:
                existing.domain = inp.domain
            if inp.owner_business is not None:
                existing.owner_business = inp.owner_business
            if inp.term_codes is not None:
                existing.term_codes = list(inp.term_codes)
            if inp.tags is not None:
                existing.tags = dict(inp.tags)
            existing.updated_at = now
            return existing
        v = BusinessMetadataView(
            id=self._seq_m, entity_type=entity_type, entity_id=entity_id,
            alias=inp.alias, business_desc=inp.business_desc, domain=inp.domain,
            owner_business=inp.owner_business,
            term_codes=list(inp.term_codes or []), tags=dict(inp.tags or {}),
            created_at=now, updated_at=now,
        )
        self._seq_m += 1
        self._meta[key] = v
        return v

    def get_metadata(self, entity_type: str, entity_id: int) -> Optional[BusinessMetadataView]:
        return self._meta.get((entity_type, entity_id))

    def set_tags(self, entity_type: str, entity_id: int,
                 tags: Dict[str, str]) -> BusinessMetadataView:
        existing = self.get_metadata(entity_type, entity_id)
        if existing is None:
            return self.upsert_metadata(entity_type, entity_id, BusinessMetadataInput(tags=tags))
        existing.tags = dict(tags)
        existing.updated_at = datetime.now()
        return existing

    def find_by_alias(self, alias: str) -> List[BusinessMetadataView]:
        return [v for v in self._meta.values() if v.alias == alias]


class SqlBusinessRepository:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def upsert_term(self, inp: BusinessTermInput) -> BusinessTermView:
        from ..storage.models_governance import BusinessTerm

        with self._sf() as s:
            m = s.query(BusinessTerm).filter(BusinessTerm.term_code == inp.term_code).first()
            if m is None:
                m = BusinessTerm(term_code=inp.term_code)
                s.add(m)
            m.term_name = inp.term_name
            m.domain = inp.domain
            m.definition = inp.definition
            m.owner = inp.owner
            m.status = inp.status
            s.commit()
            s.refresh(m)
            return _term_view(m)

    def list_terms(self, domain: Optional[str] = None) -> List[BusinessTermView]:
        from ..storage.models_governance import BusinessTerm

        with self._sf() as s:
            q = s.query(BusinessTerm)
            if domain:
                q = q.filter(BusinessTerm.domain == domain)
            return [_term_view(m) for m in q.all()]

    def get_term(self, term_code: str) -> Optional[BusinessTermView]:
        from ..storage.models_governance import BusinessTerm

        with self._sf() as s:
            m = s.query(BusinessTerm).filter(BusinessTerm.term_code == term_code).first()
            return _term_view(m) if m else None

    def upsert_metadata(self, entity_type: str, entity_id: int,
                        inp: BusinessMetadataInput) -> BusinessMetadataView:
        from ..storage.models_governance import BusinessMetadata

        with self._sf() as s:
            m = (
                s.query(BusinessMetadata)
                .filter(BusinessMetadata.entity_type == entity_type, BusinessMetadata.entity_id == entity_id)
                .first()
            )
            if m is None:
                m = BusinessMetadata(entity_type=entity_type, entity_id=entity_id)
                s.add(m)
            if inp.alias is not None:
                m.alias = inp.alias
            if inp.business_desc is not None:
                m.business_desc = inp.business_desc
            if inp.domain is not None:
                m.domain = inp.domain
            if inp.owner_business is not None:
                m.owner_business = inp.owner_business
            if inp.term_codes is not None:
                m.term_codes = list(inp.term_codes)
            if inp.tags is not None:
                m.tags = dict(inp.tags)
            s.commit()
            s.refresh(m)
            return _meta_view(m)

    def get_metadata(self, entity_type: str, entity_id: int) -> Optional[BusinessMetadataView]:
        from ..storage.models_governance import BusinessMetadata

        with self._sf() as s:
            m = (
                s.query(BusinessMetadata)
                .filter(BusinessMetadata.entity_type == entity_type, BusinessMetadata.entity_id == entity_id)
                .first()
            )
            return _meta_view(m) if m else None

    def set_tags(self, entity_type: str, entity_id: int,
                 tags: Dict[str, str]) -> BusinessMetadataView:
        existing = self.get_metadata(entity_type, entity_id)
        if existing is None:
            return self.upsert_metadata(entity_type, entity_id, BusinessMetadataInput(tags=tags))
        return self.upsert_metadata(entity_type, entity_id, BusinessMetadataInput(tags=tags))

    def find_by_alias(self, alias: str) -> List[BusinessMetadataView]:
        from ..storage.models_governance import BusinessMetadata

        with self._sf() as s:
            rows = s.query(BusinessMetadata).filter(BusinessMetadata.alias == alias).all()
            return [_meta_view(m) for m in rows]
