"""Database related data models"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field

from local_ingestion.schema.base import EntityReference


class DatabaseSchema(BaseModel):
    """Database Schema entity"""
    name: str
    fullyQualifiedName: str
    database: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[EntityReference] = None
    tags: List[str] = Field(default_factory=list)


class Database(BaseModel):
    """Database entity"""
    name: str
    fullyQualifiedName: str
    description: Optional[str] = None
    owner: Optional[EntityReference] = None
    tags: List[str] = Field(default_factory=list)
