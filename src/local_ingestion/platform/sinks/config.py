"""Local sink/source configurations (L3).

Moved out of `schema.service.connection` (L1 upstream sync area) to keep the
sync surface clean. These models have no upstream counterpart.

Note: `schema.metadata.workflow.FileSinkConfig` (L1) is a different model —
it is the workflow-level sink config and remains upstream-aligned.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class FileSinkConfig(BaseModel):
    """Configuration for local file sink connectors"""

    outputPath: str
    format: str = "json"
    prettyPrint: bool = True
    compression: Optional[str] = None

    model_config = {"populate_by_name": True}


class FileSourceConfig(BaseModel):
    """Configuration for local file source connectors"""

    inputPath: str
    format: str = "json"

    model_config = {"populate_by_name": True}
