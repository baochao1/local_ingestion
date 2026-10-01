"""Core Connectors Module - Source connectors for metadata extraction (L1).

This package is part of the upstream sync area and must contain ONLY source
connectors. Sink implementations are local extensions and live in
`local_ingestion.platform.sinks` (L3).

See doc/design/04-code-boundary-upstream-vs-local.md
"""

from local_ingestion.core.connectors.base import SourceConnector, SinkConnector
from local_ingestion.core.connectors.mysql import MySQLSourceConnector
from local_ingestion.core.connectors.postgres import PostgresSourceConnector
from local_ingestion.core.connectors.snowflake import SnowflakeSourceConnector

__all__ = [
    "SourceConnector",
    "SinkConnector",
    "MySQLSourceConnector",
    "PostgresSourceConnector",
    "SnowflakeSourceConnector",
]
