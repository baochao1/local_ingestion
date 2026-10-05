"""REST API for business metadata (MOD-09 / FR-14).

业务术语与实体元数据持久化在 PostgreSQL（``business_term`` /
``business_metadata``），平台库不可用时退回内存栈。
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from local_ingestion.platform.business import (
    build_in_memory_business_stack,
    build_sql_business_stack,
)
from local_ingestion.platform.business.models import BusinessMetadataInput, BusinessTermInput
from local_ingestion.platform.business.service import BusinessService

router = APIRouter(prefix="/api/v1/business", tags=["Business Metadata"])

_state: dict = {}


def _build_business_service() -> BusinessService:
    """SQL 优先；平台库不可用时退回内存栈（降级契约）。"""
    try:
        svc, _ = build_sql_business_stack()
        return svc
    except Exception:  # noqa: BLE001 - 降级是此处的契约
        svc, _ = build_in_memory_business_stack()
        return svc


def get_business_service() -> BusinessService:
    if "svc" not in _state:
        _state["svc"] = _build_business_service()
    return _state["svc"]


class TermBody(BaseModel):
    term_code: str
    term_name: str
    domain: Optional[str] = None
    definition: Optional[str] = None
    owner: Optional[str] = None
    status: str = "active"


class MetadataBody(BaseModel):
    alias: Optional[str] = None
    business_desc: Optional[str] = None
    domain: Optional[str] = None
    owner_business: Optional[str] = None
    term_codes: Optional[list] = None
    tags: Optional[Dict[str, str]] = None


class TagsBody(BaseModel):
    tags: Dict[str, str]


@router.get("/terms")
def list_terms(domain: Optional[str] = None, svc: BusinessService = Depends(get_business_service)):
    return {"terms": [asdict(t) for t in svc.list_terms(domain=domain)]}


@router.post("/terms", status_code=status.HTTP_201_CREATED)
def create_term(body: TermBody, svc: BusinessService = Depends(get_business_service)):
    term = svc.upsert_term(BusinessTermInput(**body.model_dump()))
    return asdict(term)


@router.get("/terms/{term_code}")
def get_term(term_code: str, svc: BusinessService = Depends(get_business_service)):
    t = svc.get_term(term_code)
    if t is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="term not found")
    return asdict(t)


@router.get("/entities/{entity_type}/{entity_id}")
def get_entity_metadata(entity_type: str, entity_id: int,
                       svc: BusinessService = Depends(get_business_service)):
    m = svc.get_metadata(entity_type, entity_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no business metadata")
    return asdict(m)


@router.put("/entities/{entity_type}/{entity_id}")
def put_entity_metadata(entity_type: str, entity_id: int, body: MetadataBody,
                        svc: BusinessService = Depends(get_business_service)):
    meta = svc.set_metadata(entity_type, entity_id, BusinessMetadataInput(**body.model_dump()))
    return asdict(meta)


@router.post("/entities/{entity_type}/{entity_id}/tags")
def set_entity_tags(entity_type: str, entity_id: int, body: TagsBody,
                   svc: BusinessService = Depends(get_business_service)):
    meta = svc.set_tags(entity_type, entity_id, body.tags)
    return asdict(meta)
