"""Checkpoint storage abstractions for pipeline resume (L3).

The pipeline skeleton (L1) only knows the duck-typed interface below; concrete
stores live here so that the upstream sync area stays free of local concerns.

Memory store keeps the historical behaviour (per-run dict). File store is the
single-node durable option; a PostgreSQL-backed store can be added later
(MOD-02 / T1.6) without touching L1 code.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()


class CheckpointStore(ABC):
    """Pluggable checkpoint storage.

    Implementations are injected into `PipelineContext`; L1 pipeline code never
    imports a concrete store.
    """

    @abstractmethod
    def save(self, pipeline_id: str, data: Dict[str, Any]) -> None:
        """Persist the full checkpoint payload for a pipeline run."""

    @abstractmethod
    def load(self, pipeline_id: str) -> Dict[str, Any]:
        """Load the checkpoint payload for a pipeline run."""

    def set(self, pipeline_id: str, key: str, value: Any) -> None:
        data = self.load(pipeline_id)
        data[key] = value
        self.save(pipeline_id, data)

    def get(self, pipeline_id: str, key: str, default: Any = None) -> Any:
        return self.load(pipeline_id).get(key, default)


class InMemoryCheckpointStore(CheckpointStore):
    """Process-local checkpoint store (default, non-durable)."""

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    def save(self, pipeline_id: str, data: Dict[str, Any]) -> None:
        self._data[pipeline_id] = dict(data)

    def load(self, pipeline_id: str) -> Dict[str, Any]:
        return self._data.setdefault(pipeline_id, {})


class FileCheckpointStore(CheckpointStore):
    """Durable single-node checkpoint store backed by JSON files."""

    def __init__(self, directory: str) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, pipeline_id: str) -> Path:
        return self._dir / f"{pipeline_id}.json"

    def save(self, pipeline_id: str, data: Dict[str, Any]) -> None:
        try:
            self._path(pipeline_id).write_text(
                json.dumps(data, default=str), encoding="utf-8"
            )
        except OSError as exc:
            logger.error(
                "checkpoint_write_failed",
                pipeline_id=pipeline_id,
                error=str(exc),
            )
            raise

    def load(self, pipeline_id: str) -> Dict[str, Any]:
        path = self._path(pipeline_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning(
                "checkpoint_load_failed",
                pipeline_id=pipeline_id,
                error=str(exc),
            )
            return {}
