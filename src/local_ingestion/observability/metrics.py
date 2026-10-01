"""Metrics Collection and Export Module

Provides metrics collection with support for:
- Counter: Monotonically increasing values (e.g., ingestion_success_total)
- Gauge: Point-in-time values (e.g., active_workflows)
- Histogram: Distribution of values (e.g., pipeline_duration_seconds)

Supports Prometheus-compatible text format export.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class MetricType(str, Enum):
    """Metric type enumeration."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class Metric:
    """Individual metric data point."""

    name: str
    value: float
    metric_type: MetricType
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tags: Dict[str, str] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert metric to dictionary representation."""
        return {
            "name": self.name,
            "value": self.value,
            "type": self.metric_type.value,
            "timestamp": self.timestamp.isoformat(),
            "tags": self.tags,
            "description": self.description,
        }


class Counter:
    """Counter metric that only increments."""

    def __init__(
        self,
        name: str,
        description: str = "",
        initial_value: float = 0.0,
        tags: Optional[Dict[str, str]] = None,
    ):
        self._name = name
        self._description = description
        self._value = initial_value
        self._tags = tags or {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        """Get counter name."""
        return self._name

    @property
    def description(self) -> str:
        """Get counter description."""
        return self._description

    @property
    def value(self) -> float:
        """Get current counter value."""
        with self._lock:
            return self._value

    def increment(self, amount: float = 1.0) -> float:
        """Increment counter by amount and return new value."""
        with self._lock:
            self._value += amount
            return self._value

    def reset(self) -> None:
        """Reset counter to zero."""
        with self._lock:
            self._value = 0.0

    def get_metric(self) -> Metric:
        """Get current metric representation."""
        with self._lock:
            return Metric(
                name=self._name,
                value=self._value,
                metric_type=MetricType.COUNTER,
                tags=dict(self._tags),
                description=self._description,
            )


class Gauge:
    """Gauge metric that can go up or down."""

    def __init__(
        self,
        name: str,
        description: str = "",
        initial_value: float = 0.0,
        tags: Optional[Dict[str, str]] = None,
    ):
        self._name = name
        self._description = description
        self._value = initial_value
        self._tags = tags or {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        """Get gauge name."""
        return self._name

    @property
    def description(self) -> str:
        """Get gauge description."""
        return self._description

    @property
    def value(self) -> float:
        """Get current gauge value."""
        with self._lock:
            return self._value

    def set(self, value: float) -> float:
        """Set gauge to specific value and return it."""
        with self._lock:
            self._value = value
            return self._value

    def increment(self, amount: float = 1.0) -> float:
        """Increment gauge by amount and return new value."""
        with self._lock:
            self._value += amount
            return self._value

    def decrement(self, amount: float = 1.0) -> float:
        """Decrement gauge by amount and return new value."""
        with self._lock:
            self._value -= amount
            return self._value

    def get_metric(self) -> Metric:
        """Get current metric representation."""
        with self._lock:
            return Metric(
                name=self._name,
                value=self._value,
                metric_type=MetricType.GAUGE,
                tags=dict(self._tags),
                description=self._description,
            )


class Histogram:
    """Histogram metric for recording distributions."""

    def __init__(
        self,
        name: str,
        description: str = "",
        buckets: Optional[List[float]] = None,
        tags: Optional[Dict[str, str]] = None,
    ):
        self._name = name
        self._description = description
        self._buckets = buckets or [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        self._values: List[float] = []
        self._sum = 0.0
        self._count = 0
        self._tags = tags or {}
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        """Get histogram name."""
        return self._name

    @property
    def description(self) -> str:
        """Get histogram description."""
        return self._description

    @property
    def buckets(self) -> List[float]:
        """Get bucket boundaries."""
        return list(self._buckets)

    def observe(self, value: float) -> None:
        """Record an observation."""
        with self._lock:
            self._values.append(value)
            self._sum += value
            self._count += 1

    def get_metric(self) -> Metric:
        """Get current metric representation."""
        with self._lock:
            avg = self._sum / self._count if self._count > 0 else 0.0
            return Metric(
                name=self._name,
                value=avg,
                metric_type=MetricType.HISTOGRAM,
                tags=dict(self._tags),
                description=self._description,
            )

    def get_stats(self) -> Dict[str, float]:
        """Get histogram statistics."""
        with self._lock:
            if not self._values:
                return {
                    "count": 0,
                    "sum": 0.0,
                    "avg": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "p50": 0.0,
                    "p90": 0.0,
                    "p95": 0.0,
                    "p99": 0.0,
                }

            sorted_values = sorted(self._values)
            count = len(sorted_values)

            def percentile(p: float) -> float:
                idx = int(count * p)
                if idx >= count:
                    idx = count - 1
                return sorted_values[idx]

            return {
                "count": self._count,
                "sum": self._sum,
                "avg": self._sum / count,
                "min": sorted_values[0],
                "max": sorted_values[-1],
                "p50": percentile(0.5),
                "p90": percentile(0.9),
                "p95": percentile(0.95),
                "p99": percentile(0.99),
            }

    def get_bucket_counts(self) -> Dict[str, int]:
        """Get cumulative bucket counts for Prometheus histogram."""
        with self._lock:
            if not self._values:
                return {f"le_{bucket}": 0 for bucket in self._buckets} | {"le_+Inf": 0}

            result = {}
            sorted_values = sorted(self._values)

            for bucket in self._buckets:
                count = sum(1 for v in sorted_values if v <= bucket)
                result[f"le_{bucket}"] = count

            result["le_+Inf"] = len(sorted_values)
            return result


class MetricsCollector:
    """Central metrics collector managing all metric types.

    Provides pre-defined metrics for common use cases:
    - ingestion_success_total: Total successful ingestions
    - ingestion_failure_total: Total failed ingestions
    - rows_processed: Total rows processed
    - pipeline_duration_seconds: Pipeline execution duration
    - active_workflows: Number of currently active workflows

    Supports Prometheus text format export.
    """

    DEFAULT_METRICS = {
        "ingestion_success_total": ("Total successful ingestions", MetricType.COUNTER),
        "ingestion_failure_total": ("Total failed ingestions", MetricType.COUNTER),
        "rows_processed": ("Total rows processed", MetricType.COUNTER),
        "pipeline_duration_seconds": ("Pipeline execution duration in seconds", MetricType.HISTOGRAM),
        "active_workflows": ("Number of currently active workflows", MetricType.GAUGE),
    }

    def __init__(self):
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._lock = threading.RLock()
        self._initialized = False
        self._init_default_metrics()

    def _init_default_metrics(self) -> None:
        """Initialize default metrics."""
        with self._lock:
            for name, (description, metric_type) in self.DEFAULT_METRICS.items():
                if metric_type == MetricType.COUNTER:
                    self._counters[name] = Counter(name, description)
                elif metric_type == MetricType.GAUGE:
                    self._gauges[name] = Gauge(name, description)
                elif metric_type == MetricType.HISTOGRAM:
                    self._histograms[name] = Histogram(name, description)
            self._initialized = True

    def counter(self, name: str, description: str = "") -> Counter:
        """Get or create a counter metric."""
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name, description)
            return self._counters[name]

    def gauge(self, name: str, description: str = "") -> Gauge:
        """Get or create a gauge metric."""
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name, description)
            return self._gauges[name]

    def histogram(self, name: str, description: str = "", buckets: Optional[List[float]] = None) -> Histogram:
        """Get or create a histogram metric."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name, description, buckets)
            return self._histograms[name]

    def record_success(self, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a successful ingestion."""
        counter = self.counter("ingestion_success_total", "Total successful ingestions")
        counter.increment()
        if tags:
            self._counters[f"ingestion_success_total_with_tags_{hash(str(tags))}"] = Counter(
                f'ingestion_success_total{{tags="{tags}"}}',
                "Total successful ingestions",
            )

    def record_failure(self, tags: Optional[Dict[str, str]] = None) -> None:
        """Record a failed ingestion."""
        counter = self.counter("ingestion_failure_total", "Total failed ingestions")
        counter.increment()

    def record_rows(self, count: int, tags: Optional[Dict[str, str]] = None) -> None:
        """Record number of rows processed."""
        counter = self.counter("rows_processed", "Total rows processed")
        counter.increment(count)

    def record_duration(self, seconds: float, tags: Optional[Dict[str, str]] = None) -> None:
        """Record pipeline execution duration."""
        hist = self.histogram("pipeline_duration_seconds", "Pipeline execution duration in seconds")
        hist.observe(seconds)

    def set_active_workflows(self, count: int) -> None:
        """Set the number of active workflows."""
        gauge = self.gauge("active_workflows", "Number of currently active workflows")
        gauge.set(count)

    def increment_active_workflows(self) -> None:
        """Increment active workflow count."""
        gauge = self.gauge("active_workflows", "Number of currently active workflows")
        gauge.increment()

    def decrement_active_workflows(self) -> None:
        """Decrement active workflow count."""
        gauge = self.gauge("active_workflows", "Number of currently active workflows")
        gauge.decrement()

    def get_counter(self, name: str) -> Optional[Counter]:
        """Get counter by name."""
        with self._lock:
            return self._counters.get(name)

    def get_gauge(self, name: str) -> Optional[Gauge]:
        """Get gauge by name."""
        with self._lock:
            return self._gauges.get(name)

    def get_histogram(self, name: str) -> Optional[Histogram]:
        """Get histogram by name."""
        with self._lock:
            return self._histograms.get(name)

    def get_all_metrics(self) -> List[Metric]:
        """Get all current metrics."""
        metrics = []
        with self._lock:
            for counter in self._counters.values():
                metrics.append(counter.get_metric())
            for gauge in self._gauges.values():
                metrics.append(gauge.get_metric())
            for histogram in self._histograms.values():
                metrics.append(histogram.get_metric())
        return metrics

    def export_prometheus(self) -> str:
        """Export all metrics in Prometheus text format.

        Returns:
            Prometheus text format string suitable for /metrics endpoint.
        """
        lines = []

        with self._lock:
            for counter in self._counters.values():
                metric = counter.get_metric()
                lines.append(f"# HELP {metric.name} {metric.description}")
                lines.append(f"# TYPE {metric.name} counter")
                tags_str = self._format_tags(metric.tags)
                lines.append(f"{metric.name}{tags_str} {metric.value}")

            for gauge in self._gauges.values():
                metric = gauge.get_metric()
                lines.append(f"# HELP {metric.name} {metric.description}")
                lines.append(f"# TYPE {metric.name} gauge")
                tags_str = self._format_tags(metric.tags)
                lines.append(f"{metric.name}{tags_str} {metric.value}")

            for histogram in self._histograms.values():
                metric = histogram.get_metric()
                stats = histogram.get_stats()
                bucket_counts = histogram.get_bucket_counts()

                lines.append(f"# HELP {metric.name} {metric.description}")
                lines.append(f"# TYPE {metric.name} histogram")

                for bucket, count in bucket_counts.items():
                    lines.append(f'{metric.name}_bucket{{le="{bucket}"}} {count}')

                lines.append(f"{metric.name}_sum {stats['sum']}")
                lines.append(f"{metric.name}_count {stats['count']}")

        return "\n".join(lines) + "\n"

    def _format_tags(self, tags: Dict[str, str]) -> str:
        """Format tags for Prometheus label format."""
        if not tags:
            return ""
        label_parts = [f'{k}="{v}"' for k, v in tags.items()]
        return "{" + ",".join(label_parts) + "}"

    def clear(self) -> None:
        """Clear all metrics."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._init_default_metrics()
