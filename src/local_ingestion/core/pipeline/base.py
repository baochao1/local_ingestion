"""Base pipeline classes for metadata extraction workflows"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generator, List, Optional

import structlog

from local_ingestion.core.connectors.base import SourceConnector, SinkConnector
from local_ingestion.schema.base import StackTraceError

logger = structlog.get_logger()


class PipelineStatus(str, Enum):
    """Pipeline execution status"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ErrorRecord:
    """Record of an error that occurred during pipeline execution"""

    def __init__(
        self,
        name: str,
        error: str,
        stackTrace: Optional[str] = None,
        timestamp: Optional[str] = None,
        entity_name: Optional[str] = None,
        entity_type: Optional[str] = None,
        recoverable: bool = False,
    ):
        self.name = name
        self.error = error
        self.stackTrace = stackTrace
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        self.entity_name = entity_name
        self.entity_type = entity_type
        self.recoverable = recoverable


class PipelineContext:
    """Context for pipeline execution tracking"""

    def __init__(
        self,
        pipeline_id: Optional[str] = None,
        pipeline_name: Optional[str] = None,
        checkpoint_store: Optional[Any] = None,
    ):
        self.pipeline_id = pipeline_id or str(uuid.uuid4())
        self.pipeline_name = pipeline_name
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.status: PipelineStatus = PipelineStatus.PENDING
        self.tables_processed: int = 0
        self.tables_failed: int = 0
        self.databases_processed: int = 0
        self.databases_failed: int = 0
        self.schemas_processed: int = 0
        self.schemas_failed: int = 0
        self.errors: List[ErrorRecord] = []
        self.checkpoint_data: Dict[str, Any] = {}
        # Optional pluggable store (duck-typed: set/get). Concrete
        # implementations live in local_ingestion.platform.resilience (L3) so
        # this upstream-aligned file stays free of local dependencies.
        self._checkpoint_store = checkpoint_store
        self._progress_callbacks: List[callable] = []

    def start(self) -> None:
        """Mark pipeline as started"""
        self.start_time = datetime.now(timezone.utc)
        self.status = PipelineStatus.RUNNING
        logger.info(
            "pipeline_started",
            pipeline_id=self.pipeline_id,
            pipeline_name=self.pipeline_name,
        )

    def stop(self) -> None:
        """Mark pipeline as stopped"""
        self.end_time = datetime.now(timezone.utc)
        self.status = PipelineStatus.STOPPED
        logger.info(
            "pipeline_stopped",
            pipeline_id=self.pipeline_id,
            duration=self.duration_seconds,
        )

    def complete(self) -> None:
        """Mark pipeline as completed"""
        self.end_time = datetime.now(timezone.utc)
        self.status = PipelineStatus.COMPLETED
        logger.info(
            "pipeline_completed",
            pipeline_id=self.pipeline_id,
            duration=self.duration_seconds,
            tables_processed=self.tables_processed,
            tables_failed=self.tables_failed,
        )

    def fail(self, error: Optional[Exception] = None) -> None:
        """Mark pipeline as failed"""
        self.end_time = datetime.now(timezone.utc)
        self.status = PipelineStatus.FAILED
        if error:
            self.add_error(
                name=type(error).__name__,
                error=str(error),
                stackTrace=None,
            )
        logger.error(
            "pipeline_failed",
            pipeline_id=self.pipeline_id,
            duration=self.duration_seconds,
            error_count=len(self.errors),
        )

    def add_error(
        self,
        name: str,
        error: str,
        stackTrace: Optional[str] = None,
        entity_name: Optional[str] = None,
        entity_type: Optional[str] = None,
        recoverable: bool = False,
    ) -> None:
        """Add an error record to the context"""
        error_record = ErrorRecord(
            name=name,
            error=error,
            stackTrace=stackTrace,
            entity_name=entity_name,
            entity_type=entity_type,
            recoverable=recoverable,
        )
        self.errors.append(error_record)
        logger.warning(
            "pipeline_error",
            pipeline_id=self.pipeline_id,
            error_name=name,
            error_message=error,
            entity_name=entity_name,
            entity_type=entity_type,
            recoverable=recoverable,
        )

    def increment_tables_processed(self) -> None:
        """Increment tables processed counter"""
        self.tables_processed += 1
        self._notify_progress()

    def increment_tables_failed(self) -> None:
        """Increment tables failed counter"""
        self.tables_failed += 1
        self._notify_progress()

    def increment_databases_processed(self) -> None:
        """Increment databases processed counter"""
        self.databases_processed += 1
        self._notify_progress()

    def increment_databases_failed(self) -> None:
        """Increment databases failed counter"""
        self.databases_failed += 1
        self._notify_progress()

    def increment_schemas_processed(self) -> None:
        """Increment schemas processed counter"""
        self.schemas_processed += 1
        self._notify_progress()

    def increment_schemas_failed(self) -> None:
        """Increment schemas failed counter"""
        self.schemas_failed += 1
        self._notify_progress()

    def set_checkpoint(self, key: str, value: Any) -> None:
        """Store checkpoint data for resume capability.

        The in-memory dict is always updated; when a `checkpoint_store` was
        injected the value is additionally persisted through it.
        """
        self.checkpoint_data[key] = value
        if self._checkpoint_store is not None:
            self._checkpoint_store.set(self.pipeline_id, key, value)
        logger.debug(
            "checkpoint_set",
            pipeline_id=self.pipeline_id,
            key=key,
        )

    def get_checkpoint(self, key: str, default: Any = None) -> Any:
        """Retrieve checkpoint data.

        Prefers the injected store (survives process restarts); falls back to
        the in-memory dict so behaviour is unchanged when no store is set.
        """
        if self._checkpoint_store is not None:
            value = self._checkpoint_store.get(self.pipeline_id, key)
            if value is not None:
                return value
        return self.checkpoint_data.get(key, default)

    def add_progress_callback(self, callback: callable) -> None:
        """Add a callback for progress updates"""
        self._progress_callbacks.append(callback)

    def _notify_progress(self) -> None:
        """Notify all progress callbacks"""
        for callback in self._progress_callbacks:
            try:
                callback(self)
            except Exception as e:
                logger.warning(
                    "progress_callback_error",
                    error=str(e),
                )

    @property
    def duration_seconds(self) -> Optional[float]:
        """Get pipeline duration in seconds"""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    @property
    def success_rate(self) -> float:
        """Calculate success rate as a percentage"""
        total = self.tables_processed + self.tables_failed
        if total == 0:
            return 100.0
        return (self.tables_processed / total) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary for serialization"""
        return {
            "pipeline_id": self.pipeline_id,
            "pipeline_name": self.pipeline_name,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status.value,
            "tables_processed": self.tables_processed,
            "tables_failed": self.tables_failed,
            "databases_processed": self.databases_processed,
            "databases_failed": self.databases_failed,
            "schemas_processed": self.schemas_processed,
            "schemas_failed": self.schemas_failed,
            "error_count": len(self.errors),
            "duration_seconds": self.duration_seconds,
            "success_rate": self.success_rate,
        }


class Pipeline(ABC):
    """Abstract base class for all pipelines"""

    def __init__(
        self,
        source: SourceConnector,
        sink: SinkConnector,
        name: Optional[str] = None,
    ):
        self.source = source
        self.sink = sink
        self.name = name or self.__class__.__name__
        self.context: Optional[PipelineContext] = None
        self._validate_called = False

    @abstractmethod
    def validate(self) -> bool:
        """Validate pipeline configuration and connectivity

        Returns:
            True if pipeline is valid, False otherwise
        """
        pass

    @abstractmethod
    def run(self) -> PipelineContext:
        """Execute the pipeline

        Returns:
            PipelineContext with execution results
        """
        pass

    def cleanup(self) -> None:
        """Cleanup pipeline resources"""
        if self.source and self.source.is_connected():
            self.source.disconnect()
        logger.info("pipeline_cleanup_complete", pipeline_name=self.name)

    @contextmanager
    def execution_context(self) -> Generator[PipelineContext, None, None]:
        """Context manager for pipeline execution with proper cleanup"""
        context = PipelineContext(pipeline_name=self.name)
        self.context = context
        try:
            context.start()
            yield context
            if context.status == PipelineStatus.RUNNING:
                context.complete()
        except Exception as e:
            context.fail(e)
            raise
        finally:
            self.cleanup()

    def __enter__(self) -> "Pipeline":
        """Enter context manager"""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager"""
        self.cleanup()


class PipelineChainer:
    """Utility for chaining multiple pipelines together"""

    def __init__(self):
        self._pipelines: List[Pipeline] = []

    def add(self, pipeline: Pipeline) -> "PipelineChainer":
        """Add a pipeline to the chain

        Args:
            pipeline: Pipeline to add

        Returns:
            Self for chaining
        """
        self._pipelines.append(pipeline)
        return self

    def run_all(self) -> List[PipelineContext]:
        """Run all pipelines in sequence

        Returns:
            List of PipelineContext objects for each pipeline
        """
        contexts = []
        for pipeline in self._pipelines:
            with pipeline.execution_context() as context:
                pipeline.run()
            contexts.append(context)
        return contexts

    def __len__(self) -> int:
        """Get number of pipelines in chain"""
        return len(self._pipelines)
