"""Base type definitions"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field


class FQN(BaseModel):
    """Fully Qualified Name - complete path identifier for an entity"""
    root: str
    children: List[str] = []

    def __str__(self) -> str:
        return ".".join([self.root] + self.children)

    @classmethod
    def from_string(cls, fqn_str: str) -> "FQN":
        parts = fqn_str.split(".")
        return cls(root=parts[0], children=parts[1:])

    @property
    def parent(self) -> Optional["FQN"]:
        if not self.children:
            return None
        return FQN(root=self.root, children=self.children[:-1])


class EntityReference(BaseModel):
    """Entity reference"""
    id: str = ""
    type: str
    name: str
    fullyQualifiedName: Optional[str] = None


class StackTraceError(BaseModel):
    """Error information"""
    name: str
    error: str
    stackTrace: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class ServiceType(str, Enum):
    """Service type enumeration"""
    DATABASE = "Database"
    MESSAGING = "Messaging"
    DASHBOARD = "Dashboard"
    PIPELINE = "Pipeline"
    STORAGE = "Storage"
    MLMODEL = "MlModel"
    SEARCH = "Search"
    METADATA = "Metadata"
    GIS = "GIS"


class DataType(str, Enum):
    """Data type enumeration"""
    STRING = "STRING"
    TEXT = "TEXT"
    BOOLEAN = "BOOLEAN"
    BYTES = "BYTES"
    DATE = "DATE"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    SMALLINT = "SMALLINT"
    TINYINT = "TINYINT"
    FLOAT = "FLOAT"
    DOUBLE = "DOUBLE"
    DECIMAL = "DECIMAL"
    UUID = "UUID"
    JSON = "JSON"
    BINARY = "BINARY"
    ARRAY = "ARRAY"
    MAP = "MAP"
    STRUCT = "STRUCT"
    UNKNOWN = "UNKNOWN"
