"""Business metadata service (MOD-09 / FR-14).

Thin orchestration over :class:`BusinessRepository`: glossary term CRUD, per-entity
business metadata upsert, business.* tag management and alias lookup. Stateless
besides the repository it delegates to.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .models import (
    BusinessMetadataInput,
    BusinessMetadataView,
    BusinessTermInput,
    BusinessTermView,
)
from .repository import BusinessRepository


class BusinessService:
    def __init__(self, repo: BusinessRepository) -> None:
        self._repo = repo

    # -- glossary terms -----------------------------------------------------
    def upsert_term(self, inp: BusinessTermInput) -> BusinessTermView:
        return self._repo.upsert_term(inp)

    def list_terms(self, domain: Optional[str] = None) -> List[BusinessTermView]:
        return self._repo.list_terms(domain=domain)

    def get_term(self, term_code: str) -> Optional[BusinessTermView]:
        return self._repo.get_term(term_code)

    # -- per-entity business metadata --------------------------------------
    def set_metadata(self, entity_type: str, entity_id: int,
                     inp: BusinessMetadataInput) -> BusinessMetadataView:
        return self._repo.upsert_metadata(entity_type, entity_id, inp)

    def get_metadata(self, entity_type: str, entity_id: int) -> Optional[BusinessMetadataView]:
        return self._repo.get_metadata(entity_type, entity_id)

    def set_tags(self, entity_type: str, entity_id: int,
                 tags: Dict[str, str]) -> BusinessMetadataView:
        return self._repo.set_tags(entity_type, entity_id, tags)

    def find_by_alias(self, alias: str) -> List[BusinessMetadataView]:
        return self._repo.find_by_alias(alias)
