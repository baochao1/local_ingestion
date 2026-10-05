"""Metadata scan orchestration.

See :mod:`local_ingestion.platform.scan.service` for the glue between a
registered datasource and the real connector pipeline.

``supported_ds_types`` is re-exported from the connector registry rather than
being a constant here: external distributions can register datasource types by
simply being installed, so the set is only knowable at call time.
"""
from local_ingestion.platform.connectors import supported_ds_types

from .service import (
    DatasourceNotFoundError,
    ScanError,
    ScanResult,
    ScanService,
    UnsupportedDatasourceError,
    make_scan_handler,
)

__all__ = [
    "DatasourceNotFoundError",
    "ScanError",
    "ScanResult",
    "ScanService",
    "UnsupportedDatasourceError",
    "make_scan_handler",
    "supported_ds_types",
]
