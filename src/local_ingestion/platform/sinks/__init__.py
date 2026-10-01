"""Local sink implementations (L3)."""

from local_ingestion.platform.sinks.config import (
    FileSinkConfig,
    FileSourceConfig,
)
from local_ingestion.platform.sinks.local_file import (
    BaseFileSink,
    JSONFileSink,
    NDJSONFileSink,
    ParquetFileSink,
    LocalFileSinkConfig,
    FileFormat,
)
from local_ingestion.platform.sinks.postgres import (
    PostgresSink,
    PostgresSinkConfig,
)

__all__ = [
    "FileSinkConfig",
    "FileSourceConfig",
    "BaseFileSink",
    "JSONFileSink",
    "NDJSONFileSink",
    "ParquetFileSink",
    "LocalFileSinkConfig",
    "FileFormat",
    "PostgresSink",
    "PostgresSinkConfig",
]
