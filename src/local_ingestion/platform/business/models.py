"""Business metadata domain models (MOD-09 / FR-14).

Kept in its own tables (``business_term`` / ``business_metadata``) and never
written into ``catalog_*`` (design D1: single writer per table). Business tags
(``business.*`` namespace) live on ``business_metadata.tags`` so they stay isolated
from MOD-05's ``security.*`` tags on ``entity_tag``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class BusinessTermView:
    id: int
    term_code: str
    term_name: str
    domain: Optional[str]
    definition: Optional[str]
    owner: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass
class BusinessMetadataView:
    id: int
    entity_type: str
    entity_id: int
    alias: Optional[str]
    business_desc: Optional[str]
    domain: Optional[str]
    owner_business: Optional[str]
    term_codes: List[str]
    tags: Dict[str, str]
    created_at: datetime
    updated_at: datetime


@dataclass
class BusinessTermInput:
    term_code: str
    term_name: str
    domain: Optional[str] = None
    definition: Optional[str] = None
    owner: Optional[str] = None
    status: str = "active"


@dataclass
class BusinessMetadataInput:
    alias: Optional[str] = None
    business_desc: Optional[str] = None
    domain: Optional[str] = None
    owner_business: Optional[str] = None
    term_codes: Optional[List[str]] = None
    tags: Optional[Dict[str, str]] = None
