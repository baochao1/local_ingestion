"""Pipeline Module - Core pipeline components for metadata extraction workflows"""

from local_ingestion.core.pipeline.base import Pipeline, PipelineContext, PipelineStatus, ErrorRecord
from local_ingestion.core.pipeline.table_pipeline import TablePipeline, TablePipelineConfig
from local_ingestion.core.pipeline.database_pipeline import DatabasePipeline, DatabasePipelineConfig
from local_ingestion.core.pipeline.parallel import ParallelPipeline, WorkerPool, PipelineExecutor

__all__ = [
    "Pipeline",
    "PipelineContext",
    "PipelineStatus",
    "ErrorRecord",
    "TablePipeline",
    "TablePipelineConfig",
    "DatabasePipeline",
    "DatabasePipelineConfig",
    "ParallelPipeline",
    "WorkerPool",
    "PipelineExecutor",
]
