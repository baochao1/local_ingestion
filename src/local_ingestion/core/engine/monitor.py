"""Workflow Monitoring and Metrics Collection"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from local_ingestion.core.engine.state import WorkflowState, WorkflowStatus

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Metric type enumeration"""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class Metric:
    """Metric representation"""

    name: str
    value: float
    metric_type: MetricType
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "name": self.name,
            "value": self.value,
            "type": self.metric_type.value,
            "timestamp": self.timestamp.isoformat(),
            "tags": self.tags,
        }


class MetricsCollector:
    """Collects and aggregates metrics for workflows"""

    def __init__(self, storage_path: Optional[str] = None):
        self._metrics: Dict[str, List[Metric]] = defaultdict(list)
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = defaultdict(float)
        self._timers: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()
        self._storage_path = Path(storage_path) if storage_path else None
        if self._storage_path:
            self._storage_path.mkdir(parents=True, exist_ok=True)

    def increment(self, name: str, value: float = 1.0, tags: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter metric"""
        with self._lock:
            self._counters[name] += value
            metric = Metric(
                name=name,
                value=self._counters[name],
                metric_type=MetricType.COUNTER,
                tags=tags or {},
            )
            self._metrics[name].append(metric)
            self._persist_metric(metric)

    def gauge(self, name: str, value: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric"""
        with self._lock:
            self._gauges[name] = value
            metric = Metric(
                name=name,
                value=value,
                metric_type=MetricType.GAUGE,
                tags=tags or {},
            )
            self._metrics[name].append(metric)
            self._persist_metric(metric)

    def timing(self, name: str, duration_ms: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a timing metric"""
        with self._lock:
            self._timers[name].append(duration_ms)
            metric = Metric(
                name=name,
                value=duration_ms,
                metric_type=MetricType.TIMER,
                tags=tags or {},
            )
            self._metrics[name].append(metric)
            self._persist_metric(metric)

    def _persist_metric(self, metric: Metric) -> None:
        """Persist metric to storage"""
        if self._storage_path:
            try:
                file_path = self._storage_path / f"{metric.name}.jsonl"
                with open(file_path, "a") as f:
                    f.write(json.dumps(metric.to_dict()) + "\n")
            except Exception as e:
                logger.error("Failed to persist metric: %s", e)

    def get_metrics(
        self,
        name: Optional[str] = None,
        workflow_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Metric]:
        """Get metrics with optional filtering"""
        with self._lock:
            if name:
                metrics = list(self._metrics.get(name, []))
            else:
                metrics = []
                for metric_list in self._metrics.values():
                    metrics.extend(metric_list)

            if workflow_id:
                metrics = [m for m in metrics if m.tags.get("workflow_id") == workflow_id]

            if since:
                metrics = [m for m in metrics if m.timestamp >= since]

            metrics.sort(key=lambda m: m.timestamp, reverse=True)
            return metrics[:limit]

    def get_counter(self, name: str) -> float:
        """Get current counter value"""
        with self._lock:
            return self._counters.get(name, 0.0)

    def get_gauge(self, name: str) -> float:
        """Get current gauge value"""
        with self._lock:
            return self._gauges.get(name, 0.0)

    def get_timer_stats(self, name: str) -> Dict[str, float]:
        """Get timing statistics"""
        with self._lock:
            timings = self._timers.get(name, [])
            if not timings:
                return {"count": 0, "min": 0.0, "max": 0.0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0}

            sorted_timings = sorted(timings)
            count = len(sorted_timings)

            return {
                "count": count,
                "min": sorted_timings[0],
                "max": sorted_timings[-1],
                "avg": sum(sorted_timings) / count,
                "p50": sorted_timings[int(count * 0.5)],
                "p95": sorted_timings[int(count * 0.95)] if count > 1 else sorted_timings[0],
                "p99": sorted_timings[int(count * 0.99)] if count > 1 else sorted_timings[0],
            }

    def get_all_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of all metrics"""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "timers": {name: self.get_timer_stats(name) for name in self._timers},
                "total_metric_count": sum(len(m) for m in self._metrics.values()),
            }

    def clear(self, name: Optional[str] = None) -> None:
        """Clear metrics"""
        with self._lock:
            if name:
                self._metrics.pop(name, None)
                self._counters.pop(name, None)
                self._gauges.pop(name, None)
                self._timers.pop(name, None)
            else:
                self._metrics.clear()
                self._counters.clear()
                self._gauges.clear()
                self._timers.clear()


@dataclass
class WorkflowMetrics:
    """Metrics for a specific workflow"""

    workflow_id: str
    status: WorkflowStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    steps_completed: int = 0
    steps_total: int = 0
    error_count: int = 0
    retry_count: int = 0
    logs_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "steps_completed": self.steps_completed,
            "steps_total": self.steps_total,
            "error_count": self.error_count,
            "retry_count": self.retry_count,
            "logs_count": self.logs_count,
            "progress_percent": (self.steps_completed / self.steps_total * 100) if self.steps_total > 0 else 0.0,
        }


class LogEntry:
    """Log entry for workflow execution"""

    def __init__(
        self,
        workflow_id: str,
        timestamp: datetime,
        level: str,
        message: str,
        step: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.workflow_id = workflow_id
        self.timestamp = timestamp
        self.level = level
        self.message = message
        self.step = step
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "workflow_id": self.workflow_id,
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "message": self.message,
            "step": self.step,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LogEntry":
        """Create from dictionary"""
        timestamp = data["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        return cls(
            workflow_id=data["workflow_id"],
            timestamp=timestamp,
            level=data["level"],
            message=data["message"],
            step=data.get("step"),
            metadata=data.get("metadata", {}),
        )


class WorkflowMonitor:
    """Monitor workflow execution and collect logs/metrics"""

    def __init__(
        self,
        metrics_collector: Optional[MetricsCollector] = None,
        logs_path: Optional[str] = None,
    ):
        self._metrics_collector = metrics_collector or MetricsCollector()
        self._logs_path = Path(logs_path) if logs_path else None
        self._tracked_workflows: Dict[str, WorkflowState] = {}
        self._workflow_logs: Dict[str, List[LogEntry]] = defaultdict(list)
        # 可重入锁：track_workflow 等公开方法持有锁后会调用 _log，后者再次加锁。
        # 用普通 Lock 会自我死锁（track_workflow 永远无法返回）。
        self._lock = threading.RLock()

        if self._logs_path:
            self._logs_path.mkdir(parents=True, exist_ok=True)

    def track_workflow(self, workflow_id: str, state: Optional[WorkflowState] = None) -> None:
        """Start tracking a workflow"""
        with self._lock:
            if state is None:
                state = WorkflowState(
                    workflow_id=workflow_id,
                    status=WorkflowStatus.PENDING,
                )
            self._tracked_workflows[workflow_id] = state
            self._log(workflow_id, "INFO", "Workflow tracking started")
            self._metrics_collector.increment(
                "workflow.tracked",
                tags={"workflow_id": workflow_id, "status": state.status.value},
            )

    def stop_tracking(self, workflow_id: str) -> None:
        """Stop tracking a workflow"""
        with self._lock:
            if workflow_id in self._tracked_workflows:
                del self._tracked_workflows[workflow_id]
                self._log(workflow_id, "INFO", "Workflow tracking stopped")

    def get_metrics(self, workflow_id: str) -> Optional[WorkflowMetrics]:
        """Get metrics for a specific workflow"""
        with self._lock:
            state = self._tracked_workflows.get(workflow_id)
            if state is None:
                return None

            logs = self._workflow_logs.get(workflow_id, [])
            error_logs = [l for l in logs if l.level == "ERROR"]

            duration_ms = None
            if state.started_at:
                end_time = state.completed_at or datetime.now(timezone.utc)
                duration_ms = (end_time - state.started_at).total_seconds() * 1000

            return WorkflowMetrics(
                workflow_id=workflow_id,
                status=state.status,
                start_time=state.started_at or state.created_at,
                end_time=state.completed_at,
                duration_ms=duration_ms,
                steps_completed=state.completed_steps,
                steps_total=state.total_steps,
                error_count=len(error_logs),
                retry_count=state.retry_count,
                logs_count=len(logs),
            )

    def get_logs(self, workflow_id: str, last_n: Optional[int] = None, level: Optional[str] = None) -> List[LogEntry]:
        """Get logs for a workflow"""
        with self._lock:
            logs = list(self._workflow_logs.get(workflow_id, []))

        if level:
            logs = [l for l in logs if l.level == level.upper()]

        logs.sort(key=lambda l: l.timestamp, reverse=True)

        if last_n:
            logs = logs[:last_n]

        return logs

    def _log(
        self,
        workflow_id: str,
        level: str,
        message: str,
        step: Optional[str] = None,
        **metadata,
    ) -> None:
        """Add a log entry"""
        entry = LogEntry(
            workflow_id=workflow_id,
            timestamp=datetime.now(timezone.utc),
            level=level,
            message=message,
            step=step,
            metadata=metadata,
        )

        with self._lock:
            self._workflow_logs[workflow_id].append(entry)
            self._persist_log(entry)

        if level == "ERROR":
            self._metrics_collector.increment(
                "workflow.errors",
                tags={"workflow_id": workflow_id},
            )
        elif level == "WARNING":
            self._metrics_collector.increment(
                "workflow.warnings",
                tags={"workflow_id": workflow_id},
            )

    def log_info(self, workflow_id: str, message: str, **metadata) -> None:
        """Log info message"""
        self._log(workflow_id, "INFO", message, **metadata)

    def log_warning(self, workflow_id: str, message: str, **metadata) -> None:
        """Log warning message"""
        self._log(workflow_id, "WARNING", message, **metadata)

    def log_error(self, workflow_id: str, message: str, **metadata) -> None:
        """Log error message"""
        self._log(workflow_id, "ERROR", message, **metadata)

    def log_debug(self, workflow_id: str, message: str, **metadata) -> None:
        """Log debug message"""
        self._log(workflow_id, "DEBUG", message, **metadata)

    def _persist_log(self, entry: LogEntry) -> None:
        """Persist log entry to storage"""
        if self._logs_path:
            try:
                file_path = self._logs_path / f"{entry.workflow_id}.jsonl"
                with open(file_path, "a") as f:
                    f.write(json.dumps(entry.to_dict()) + "\n")
            except Exception as e:
                logger.error("Failed to persist log entry: %s", e)

    def get_all_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of all tracked workflows"""
        with self._lock:
            tracked_count = len(self._tracked_workflows)
            running_count = sum(
                1 for s in self._tracked_workflows.values() if s.status == WorkflowStatus.RUNNING
            )
            completed_count = sum(
                1 for s in self._tracked_workflows.values() if s.status == WorkflowStatus.COMPLETED
            )
            failed_count = sum(
                1 for s in self._tracked_workflows.values() if s.status == WorkflowStatus.FAILED
            )

            return {
                "tracked_workflows": tracked_count,
                "running": running_count,
                "completed": completed_count,
                "failed": failed_count,
                "metrics": self._metrics_collector.get_all_metrics_summary(),
            }

    def update_state(self, state: WorkflowState) -> None:
        """Update tracked workflow state"""
        with self._lock:
            self._tracked_workflows[state.workflow_id] = state
            self._metrics_collector.increment(
                "workflow.state_changes",
                tags={
                    "workflow_id": state.workflow_id,
                    "status": state.status.value,
                },
            )

    def get_tracked_workflows(self) -> List[str]:
        """Get list of tracked workflow IDs"""
        with self._lock:
            return list(self._tracked_workflows.keys())
