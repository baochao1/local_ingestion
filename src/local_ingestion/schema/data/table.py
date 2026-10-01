"""Table related data models"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from local_ingestion.schema.base import DataType, EntityReference


class Column(BaseModel):
    """Column definition"""
    name: str
    dataType: DataType = DataType.UNKNOWN
    dataTypeDisplay: str = ""
    dataLength: Optional[int] = None
    precision: Optional[int] = None
    scale: Optional[int] = None
    nullable: bool = True
    ordinalPosition: Optional[int] = None
    default: Optional[str] = None
    description: Optional[str] = None
    children: List["Column"] = []
    tags: List[str] = []

    model_config = {"use_enum_values": True}


class TableProfile(BaseModel):
    """Table statistics"""
    rowCount: Optional[int] = None
    columnCount: Optional[int] = None
    sizeInBytes: Optional[int] = None
    sizeInBytesApproximate: Optional[int] = None
    lastUpdated: Optional[str] = None
    lastProfilerRun: Optional[str] = None
    minValue: Optional[Dict[str, Any]] = None
    maxValue: Optional[Dict[str, Any]] = None
    mean: Optional[Dict[str, float]] = None
    sum: Optional[Dict[str, float]] = None
    stdDev: Optional[Dict[str, float]] = None


class Table(BaseModel):
    """Table entity"""
    name: str
    fullyQualifiedName: str

    database: Optional[str] = None
    databaseSchema: Optional[str] = None

    columns: List[Column] = Field(default_factory=list)
    tableType: Optional[str] = None

    profile: Optional[TableProfile] = None

    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    owner: Optional[EntityReference] = None

    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None

    model_config = {"populate_by_name": True}
