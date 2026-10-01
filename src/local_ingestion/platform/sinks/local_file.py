"""File sink connectors for writing metadata to files (L3 local extension).

Moved out of `core.connectors` so the upstream sync area (L1) contains only
source connectors. Implements the generic `SinkConnector` contract.
"""
from __future__ import annotations

import json
from abc import abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING
from enum import Enum

import structlog

try:
    import orjson
except ImportError:
    orjson = None

from local_ingestion.core.connectors.base import SinkConnector
from local_ingestion.schema.data.database import Database, DatabaseSchema
from local_ingestion.schema.data.table import Table
from local_ingestion.schema.metadata.workflow import FileSinkConfig as WorkflowFileSinkConfig

# Re-export FileSinkConfig for backward compatibility (tests import from this module)
FileSinkConfig = WorkflowFileSinkConfig

if TYPE_CHECKING:
    import pandas as pd

logger = structlog.get_logger()


class FileFormat(str, Enum):
    """File format enumeration"""
    JSON = "json"
    NDJSON = "ndjson"
    PARQUET = "parquet"


class LocalFileSinkConfig:
    """Local configuration for file sink connectors (simpler than schema version)"""

    def __init__(
        self,
        output_path: str,
        format: Union[str, FileFormat] = "json",
        pretty_print: bool = True,
        compression: Optional[str] = None,
    ):
        self.output_path = output_path
        self.format = FileFormat(format) if isinstance(format, str) else format
        self.pretty_print = pretty_print
        self.compression = compression


FileSinkConfigType = Union[WorkflowFileSinkConfig, LocalFileSinkConfig]


class BaseFileSink(SinkConnector):
    """Base class for file sink connectors"""

    def __init__(self) -> None:
        super().__init__()
        self._file_handle: Optional[Any] = None
        self._output_path: Optional[Path] = None
        self._entities_written: int = 0

    def connect(self, config: FileSinkConfigType) -> None:
        """Connect to the file sink

        Args:
            config: File sink configuration (supports both schema and local config)
        """
        self._config = config
        try:
            output_path = getattr(config, "outputPath", None) or getattr(config, "output_path", None)
            format_val = getattr(config, "format", "json")
            pretty_print = getattr(config, "prettyPrint", None) or getattr(config, "pretty_print", True)
            compression = getattr(config, "compression", None)

            self._output_path = Path(output_path)
            self._output_path.parent.mkdir(parents=True, exist_ok=True)

            file_format = FileFormat(format_val) if isinstance(format_val, str) else format_val
            if file_format == FileFormat.JSON:
                mode = "w"
            else:
                mode = "w"

            self._file_handle = open(self._output_path, mode, encoding="utf-8")

            self._connected = True
            logger.info(
                "file_sink_connected",
                path=str(self._output_path),
                format=file_format.value,
            )

        except Exception as e:
            self._log_connection_error(e)
            self._connected = False
            raise

    def flush(self) -> None:
        """Flush pending writes to the file"""
        if self._file_handle:
            self._file_handle.flush()

    def close(self) -> None:
        """Close the file handle"""
        if self._file_handle:
            self._file_handle.close()
            self._file_handle = None
        self._connected = False
        logger.info(
            "file_sink_closed",
            path=str(self._output_path),
            entities_written=self._entities_written,
        )

    def write_database(self, database: Database) -> None:
        """Write database metadata to the sink

        Args:
            database: Database object to write
        """
        self._write_entity(database.model_dump(), "database")

    def write_table(self, table: Table) -> None:
        """Write table metadata to the sink

        Args:
            table: Table object to write
        """
        self._write_entity(table.model_dump(), "table")

    def write_schema(self, schema: DatabaseSchema) -> None:
        """Write schema metadata to the sink

        Args:
            schema: DatabaseSchema object to write
        """
        self._write_entity(schema.model_dump(), "schema")

    @abstractmethod
    def _write_entity(self, entity: Dict[str, Any], entity_type: str) -> None:
        """Write entity to the file

        Args:
            entity: Entity data as dictionary
            entity_type: Type of entity (database, table, etc.)
        """
        pass


class JSONFileSink(BaseFileSink):
    """JSON file sink connector that writes metadata as a JSON array"""

    def __init__(self) -> None:
        super().__init__()
        self._buffer: List[Dict[str, Any]] = []
        self._is_array_open: bool = False
        self._pretty_print: bool = True

    def connect(self, config: FileSinkConfigType) -> None:
        """Connect to the JSON file sink

        Args:
            config: File sink configuration
        """
        super().connect(config)
        self._buffer = []
        self._is_array_open = False
        self._pretty_print = getattr(config, "prettyPrint", None) or getattr(config, "pretty_print", True)

    def _write_entity(self, entity: Dict[str, Any], entity_type: str) -> None:
        """Write entity to the JSON file

        Args:
            entity: Entity data as dictionary
            entity_type: Type of entity
        """
        try:
            if not self._is_array_open:
                self._file_handle.write("[\n")
                self._is_array_open = True

            self._buffer.append(entity)
            self._entities_written += 1

        except Exception as e:
            self._log_write_error(e, entity_type)
            raise

    def flush(self) -> None:
        """Flush all buffered entities to the JSON file"""
        if self._buffer and self._file_handle:
            indent = 2 if self._pretty_print else None

            for i, entity in enumerate(self._buffer):
                json_str = json.dumps(entity, indent=indent, default=str, ensure_ascii=False)
                self._file_handle.write(json_str)
                if i < len(self._buffer) - 1:
                    self._file_handle.write(",\n")

            self._file_handle.write("\n]")
            self._file_handle.flush()
            self._buffer = []

    def close(self) -> None:
        """Close the JSON file and flush remaining entities"""
        if self._buffer:
            self.flush()
        elif self._is_array_open and self._file_handle:
            self._file_handle.write("]")
        super().close()


class NDJSONFileSink(BaseFileSink):
    """NDJSON (Newline Delimited JSON) file sink connector"""

    def _write_entity(self, entity: Dict[str, Any], entity_type: str) -> None:
        """Write entity to the NDJSON file

        Args:
            entity: Entity data as dictionary
            entity_type: Type of entity
        """
        try:
            if self._file_handle:
                if orjson is not None:
                    json_bytes = orjson.dumps(entity, option=orjson.OPT_SERIALIZE_NUMPY)
                    self._file_handle.write(json_bytes.decode("utf-8") + "\n")
                else:
                    json_str = json.dumps(entity, default=str)
                    self._file_handle.write(json_str + "\n")
                self._entities_written += 1

        except Exception as e:
            self._log_write_error(e, entity_type)
            raise


class ParquetFileSink(BaseFileSink):
    """Parquet file sink connector"""

    def __init__(self) -> None:
        super().__init__()
        self._buffer: List[Dict[str, Any]] = []
        self._pandas: Optional[Any] = None

    def connect(self, config: FileSinkConfigType) -> None:
        """Connect to the Parquet file sink

        Args:
            config: File sink configuration
        """
        super().connect(config)
        self._buffer = []

        try:
            import pandas as pd
            self._pandas = pd
        except ImportError:
            logger.warning("pandas_not_available")
            logger.warning("pyarrow_not_available")

    def _write_entity(self, entity: Dict[str, Any], entity_type: str) -> None:
        """Buffer entity for writing to Parquet file

        Args:
            entity: Entity data as dictionary
            entity_type: Type of entity
        """
        self._buffer.append(entity)
        self._entities_written += 1

    def write_table(self, table: Table) -> None:
        """Write table metadata to the sink

        Args:
            table: Table object to write
        """
        table_dict = table.model_dump()
        self._write_entity(table_dict, "table")

    def _serialize_complex_types(self, data: Any) -> Any:
        """Serialize complex types for Parquet compatibility

        Args:
            data: Data to serialize

        Returns:
            Serializable data
        """
        if isinstance(data, dict):
            return json.dumps(data, default=str)
        elif isinstance(data, list):
            return json.dumps(data, default=str)
        return data

    def flush(self) -> None:
        """Flush all buffered entities to the Parquet file"""
        if not self._buffer or not self._pandas:
            return

        try:
            df = self._pandas.DataFrame(self._buffer)

            for col in df.columns:
                df[col] = df[col].apply(self._serialize_complex_types)

            compression = "snappy"
            if self._config and hasattr(self._config, "compression") and self._config.compression:
                compression_map = {
                    "gzip": "gzip",
                    "brotli": "brotli",
                    "none": None,
                }
                compression = compression_map.get(self._config.compression, "snappy")

            df.to_parquet(
                str(self._output_path),
                engine="pyarrow",
                compression=compression,
                index=False,
            )

            self._file_handle.flush()
            self._buffer = []
            logger.info("parquet_written", path=str(self._output_path), rows=len(df))

        except Exception as e:
            logger.error("parquet_write_error", error=str(e))
            raise

    def close(self) -> None:
        """Close the Parquet file and flush remaining entities"""
        if self._buffer:
            self.flush()
        super().close()
