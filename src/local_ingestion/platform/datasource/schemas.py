"""Pydantic schemas for the data-source management API (MOD-01 / T-109).

Field names follow the OpenMetadata camelCase convention (ADR-8). The router
converts them to snake_case via :func:`snakify` before handing to the service,
and the service responses are converted back with :func:`camelize`.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DatasourceCreate(BaseModel):
    code: str
    name: str
    dsType: str = Field(alias="dsType")
    host: Optional[str] = None
    port: Optional[int] = None
    environment: Optional[str] = None
    groupName: Optional[str] = None
    ownerBusiness: Optional[str] = None
    ownerTechnical: Optional[str] = None
    enabled: bool = True
    scanEnabled: bool = True
    samplingEnabled: bool = False
    username: Optional[str] = None
    password: Optional[str] = None
    scanConfig: Dict[str, Any] = Field(default_factory=dict)
    samplingConfig: Dict[str, Any] = Field(default_factory=dict)
    allowWrite: bool = Field(False, alias="allowWrite")

    model_config = {"populate_by_name": True}


class DatasourceUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    environment: Optional[str] = None
    groupName: Optional[str] = None
    ownerBusiness: Optional[str] = None
    ownerTechnical: Optional[str] = None
    enabled: Optional[bool] = None
    scanEnabled: Optional[bool] = None
    samplingEnabled: Optional[bool] = None
    scanConfig: Optional[Dict[str, Any]] = None
    samplingConfig: Optional[Dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class CredentialCreate(BaseModel):
    username: str
    password: str


class TestConnectionRequest(BaseModel):
    dsType: str
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    database: Optional[str] = None
    options: Optional[Dict[str, Any]] = None

    model_config = {"populate_by_name": True}
