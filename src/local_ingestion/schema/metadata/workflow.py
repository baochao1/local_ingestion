"""Workflow configuration models"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field


class LogLevels(str, Enum):
    """Log levels"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class FilterPattern(BaseModel):
    """Include/exclude filter patterns"""
    includes: Optional[List[str]] = None
    excludes: Optional[List[str]] = None


class SourceConfig(BaseModel):
    """Base source configuration"""
    includeTables: bool = True
    includeViews: bool = True
    includeStoredProcedures: bool = False
    includeTags: bool = True
    markDeletedTables: bool = True
    databaseFilterPattern: Optional[FilterPattern] = None
    schemaFilterPattern: Optional[FilterPattern] = None
    tableFilterPattern: Optional[FilterPattern] = None


class DatabaseSourceConfig(SourceConfig):
    """Database source configuration"""
    markDeletedTables: bool = True
    includeTables: bool = True
    includeViews: bool = True
    useCollatedTables: bool = False


class SinkConfig(BaseModel):
    """Base sink configuration"""
    type: str


class FileSinkConfig(SinkConfig):
    """File sink configuration"""
    type: str = "file"
    outputPath: str = "./output"
    format: str = "json"  # json, ndjson, csv


class WorkflowConfig(BaseModel):
    """Workflow configuration"""
    loggerLevel: LogLevels = LogLevels.INFO
    pipelineName: Optional[str] = None


class LocalWorkflowConfig(BaseModel):
    """Complete workflow configuration"""
    workflowConfig: WorkflowConfig = Field(default_factory=WorkflowConfig)
    source: Dict[str, Any] = Field(default_factory=dict)
    sink: Dict[str, Any] = Field(default_factory=dict)
    processor: Optional[Dict[str, Any]] = None

    @classmethod
    def from_yaml(cls, path: str) -> "LocalWorkflowConfig":
        """Load config from YAML file"""
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalWorkflowConfig":
        """Load config from dict"""
        return cls.model_validate(data)
