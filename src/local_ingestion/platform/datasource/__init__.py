"""Data-source management (MOD-01 / T-109)."""
from __future__ import annotations

from .repository import (
    InMemoryDatasourceRepository,
    SqlDatasourceRepository,
)
from .schemas import (
    CredentialCreate,
    DatasourceCreate,
    DatasourceUpdate,
    TestConnectionRequest,
)
from .service import (
    Capabilities,
    ConnectivityResult,
    ConnectionFailedError,
    ConflictError,
    DataSourceService,
    DataSourceServiceError,
    NotFoundError,
    WriteAccessDeniedError,
    prod_capability_detector,
    prod_connectivity_checker,
)

__all__ = [
    "InMemoryDatasourceRepository",
    "SqlDatasourceRepository",
    "CredentialCreate",
    "DatasourceCreate",
    "DatasourceUpdate",
    "TestConnectionRequest",
    "Capabilities",
    "ConnectivityResult",
    "ConnectionFailedError",
    "ConflictError",
    "DataSourceService",
    "DataSourceServiceError",
    "NotFoundError",
    "WriteAccessDeniedError",
    "prod_capability_detector",
    "prod_connectivity_checker",
]
