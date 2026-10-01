"""Parallel execution components for pipelines"""
from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from contextlib import asynccontextmanager

import structlog

from local_ingestion.core.connectors.base import SourceConnector, SinkConnector
from local_ingestion.core.pipeline.base import Pipeline, PipelineContext, PipelineStatus
from local_ingestion.core.pipeline.table_pipeline import TablePipeline, TablePipelineConfig

logger = structlog.get_logger()


@dataclass
class WorkerPoolConfig:
    """Configuration for worker pool"""

    max_workers: int = 4
    queue_size: int = 100
    timeout_seconds: float = 300.0
    retry_attempts: int = 3
    retry_delay_seconds: float = 1.0


class WorkerPool:
    """Worker pool for parallel pipeline execution"""

    def __init__(self, config: Optional[WorkerPoolConfig] = None):
        self.config = config or WorkerPoolConfig()
        self._executor: Optional[ThreadPoolExecutor] = None
        self._active_tasks: Dict[str, Future] = {}
        self._completed_tasks: List[str] = []
        self._failed_tasks: List[str] = []

    def start(self) -> None:
        """Start the worker pool"""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self.config.max_workers,
                thread_name_prefix="pipeline_worker_",
            )
            logger.info(
                "worker_pool_started",
                max_workers=self.config.max_workers,
            )

    def stop(self) -> None:
        """Stop the worker pool and wait for tasks to complete"""
        if self._executor:
            self._executor.shutdown(wait=True)
            self._executor = None
            logger.info(
                "worker_pool_stopped",
                completed=len(self._completed_tasks),
                failed=len(self._failed_tasks),
            )

    def submit(
        self,
        task_id: str,
        func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> Future:
        """Submit a task to the worker pool

        Args:
            task_id: Unique task identifier
            func: Function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function

        Returns:
            Future object representing the task
        """
        if self._executor is None:
            self.start()

        future = self._executor.submit(func, *args, **kwargs)
        self._active_tasks[task_id] = future
        logger.debug(
            "task_submitted",
            task_id=task_id,
            active_tasks=len(self._active_tasks),
        )
        return future

    def get_result(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """Get result of a submitted task

        Args:
            task_id: Task identifier
            timeout: Optional timeout in seconds

        Returns:
            Task result

        Raises:
            KeyError: If task not found
            TimeoutError: If timeout exceeded
        """
        if task_id not in self._active_tasks:
            raise KeyError(f"Task {task_id} not found")

        future = self._active_tasks[task_id]
        return future.result(timeout=timeout)

    def is_task_complete(self, task_id: str) -> bool:
        """Check if a task is complete

        Args:
            task_id: Task identifier

        Returns:
            True if task is complete
        """
        if task_id not in self._active_tasks:
            return False
        return self._active_tasks[task_id].done()

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task

        Args:
            task_id: Task identifier

        Returns:
            True if task was cancelled
        """
        if task_id not in self._active_tasks:
            return False
        return self._active_tasks[task_id].cancel()

    def get_active_count(self) -> int:
        """Get number of active tasks"""
        return len(self._active_tasks)

    def wait_for_completion(
        self,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Wait for all active tasks to complete

        Args:
            timeout: Optional timeout in seconds

        Returns:
            Dictionary with completion statistics
        """
        results = {
            "completed": [],
            "failed": [],
            "cancelled": [],
        }

        for task_id, future in list(self._active_tasks.items()):
            try:
                future.result(timeout=timeout)
                results["completed"].append(task_id)
                self._completed_tasks.append(task_id)
            except asyncio.CancelledError:
                results["cancelled"].append(task_id)
            except Exception as e:
                results["failed"].append(task_id)
                self._failed_tasks.append(task_id)
                logger.error(
                    "task_failed",
                    task_id=task_id,
                    error=str(e),
                )
            finally:
                del self._active_tasks[task_id]

        return results

    def __enter__(self) -> "WorkerPool":
        """Enter context manager"""
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager"""
        self.stop()


@dataclass
class PipelineExecutorConfig:
    """Configuration for pipeline executor"""

    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    timeout_seconds: float = 3600.0
    continue_on_error: bool = True
    parallel_workers: int = 4


class PipelineExecutor:
    """Executor for running pipelines with retry logic and error handling"""

    def __init__(
        self,
        config: Optional[PipelineExecutorConfig] = None,
        worker_pool: Optional[WorkerPool] = None,
    ):
        self.config = config or PipelineExecutorConfig()
        self.worker_pool = worker_pool or WorkerPool()
        self._execution_history: List[Dict[str, Any]] = []

    def execute(
        self,
        pipeline: Pipeline,
        use_retry: bool = True,
    ) -> PipelineContext:
        """Execute a single pipeline with retry logic

        Args:
            pipeline: Pipeline to execute
            use_retry: Whether to use retry logic on failure

        Returns:
            PipelineContext with execution results
        """
        last_error: Optional[Exception] = None
        attempt = 0

        while attempt < self.config.max_retries if use_retry else 1:
            attempt += 1
            try:
                logger.info(
                    "pipeline_execution_attempt",
                    pipeline=pipeline.name,
                    attempt=attempt,
                    max_retries=self.config.max_retries,
                )

                context = pipeline.run()

                self._record_execution(
                    pipeline_name=pipeline.name,
                    attempt=attempt,
                    success=True,
                    context=context,
                )

                return context

            except Exception as e:
                last_error = e
                logger.warning(
                    "pipeline_execution_failed",
                    pipeline=pipeline.name,
                    attempt=attempt,
                    error=str(e),
                )

                if not use_retry or attempt >= self.config.max_retries:
                    if not self.config.continue_on_error:
                        raise

                if attempt < self.config.max_retries:
                    import time
                    time.sleep(self.config.retry_delay_seconds * attempt)

        with pipeline.execution_context() as context:
            if last_error:
                context.fail(last_error)

        return context

    def execute_parallel(
        self,
        pipelines: List[Pipeline],
    ) -> List[PipelineContext]:
        """Execute multiple pipelines in parallel

        Args:
            pipelines: List of pipelines to execute

        Returns:
            List of PipelineContext objects
        """
        contexts: List[PipelineContext] = []
        task_ids: Dict[str, int] = {}

        with self.worker_pool:
            for i, pipeline in enumerate(pipelines):
                task_id = str(uuid.uuid4())
                task_ids[task_id] = i

                self.worker_pool.submit(
                    task_id=task_id,
                    func=self.execute,
                    pipeline=pipeline,
                )

            results = self.worker_pool.wait_for_completion(
                timeout=self.config.timeout_seconds,
            )

            for i, pipeline in enumerate(pipelines):
                context = pipeline.context
                if context:
                    contexts.append(context)

        return contexts

    def execute_with_callbacks(
        self,
        pipeline: Pipeline,
        on_progress: Optional[Callable[[PipelineContext], None]] = None,
        on_complete: Optional[Callable[[PipelineContext], None]] = None,
        on_error: Optional[Callable[[Exception, PipelineContext], None]] = None,
    ) -> PipelineContext:
        """Execute pipeline with progress callbacks

        Args:
            pipeline: Pipeline to execute
            on_progress: Callback for progress updates
            on_complete: Callback when execution completes
            on_error: Callback when error occurs

        Returns:
            PipelineContext with execution results
        """
        if on_progress:
            with pipeline.execution_context() as context:
                context.add_progress_callback(on_progress)
                try:
                    pipeline.run()
                except Exception as e:
                    if on_error:
                        on_error(e, context)
                    raise
                finally:
                    if on_complete:
                        on_complete(context)

        return pipeline.run()

    def _record_execution(
        self,
        pipeline_name: str,
        attempt: int,
        success: bool,
        context: PipelineContext,
    ) -> None:
        """Record execution in history

        Args:
            pipeline_name: Name of the pipeline
            attempt: Attempt number
            success: Whether execution succeeded
            context: Pipeline context
        """
        record = {
            "pipeline_name": pipeline_name,
            "attempt": attempt,
            "success": success,
            "timestamp": context.start_time.isoformat() if context.start_time else None,
            "duration": context.duration_seconds,
            "tables_processed": context.tables_processed,
            "tables_failed": context.tables_failed,
            "status": context.status.value,
        }
        self._execution_history.append(record)

    def get_execution_history(self) -> List[Dict[str, Any]]:
        """Get execution history

        Returns:
            List of execution records
        """
        return self._execution_history.copy()

    def clear_history(self) -> None:
        """Clear execution history"""
        self._execution_history.clear()


class ParallelPipeline:
    """Pipeline that executes multiple sub-pipelines in parallel"""

    def __init__(
        self,
        name: Optional[str] = None,
        config: Optional[WorkerPoolConfig] = None,
    ):
        self.name = name or self.__class__.__name__
        self.config = config or WorkerPoolConfig()
        self._pipelines: List[Pipeline] = []
        self._worker_pool = WorkerPool(self.config)
        self.context: Optional[PipelineContext] = None

    def add_pipeline(self, pipeline: Pipeline) -> "ParallelPipeline":
        """Add a pipeline to the parallel execution

        Args:
            pipeline: Pipeline to add

        Returns:
            Self for chaining
        """
        self._pipelines.append(pipeline)
        return self

    def validate(self) -> bool:
        """Validate all pipelines

        Returns:
            True if all pipelines are valid
        """
        for pipeline in self._pipelines:
            if not pipeline.validate():
                logger.error(
                    "pipeline_validation_failed",
                    pipeline=pipeline.name,
                )
                return False
        return True

    def run(self) -> PipelineContext:
        """Execute all pipelines in parallel

        Returns:
            PipelineContext with aggregated results
        """
        if not self._pipelines:
            raise ValueError("No pipelines to execute")

        context = PipelineContext(pipeline_name=self.name)
        self.context = context
        context.start()

        try:
            if not self.validate():
                context.fail(RuntimeError("Pipeline validation failed"))
                return context

            executor = PipelineExecutor(
                config=PipelineExecutorConfig(
                    parallel_workers=self.config.max_workers,
                ),
                worker_pool=self._worker_pool,
            )

            contexts = executor.execute_parallel(self._pipelines)

            self._aggregate_results(context, contexts)

            if any(c.status == PipelineStatus.FAILED for c in contexts):
                context.fail()
            else:
                context.complete()

        except Exception as e:
            context.fail(e)
            raise
        finally:
            self.cleanup()

        return context

    def _aggregate_results(
        self,
        context: PipelineContext,
        contexts: List[PipelineContext],
    ) -> None:
        """Aggregate results from multiple pipeline executions

        Args:
            context: Main context to aggregate into
            contexts: List of individual pipeline contexts
        """
        for ctx in contexts:
            context.tables_processed += ctx.tables_processed
            context.tables_failed += ctx.tables_failed
            context.databases_processed += ctx.databases_processed
            context.databases_failed += ctx.databases_failed
            context.schemas_processed += ctx.schemas_processed
            context.schemas_failed += ctx.schemas_failed
            context.errors.extend(ctx.errors)

    def cleanup(self) -> None:
        """Cleanup all pipelines"""
        for pipeline in self._pipelines:
            pipeline.cleanup()
        logger.info(
            "parallel_pipeline_cleanup_complete",
            pipeline=self.name,
        )

    def __len__(self) -> int:
        """Get number of pipelines"""
        return len(self._pipelines)

    def __enter__(self) -> "ParallelPipeline":
        """Enter context manager"""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager"""
        self.cleanup()
