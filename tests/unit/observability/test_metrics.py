"""Unit Tests for Metrics Module"""

import pytest
from datetime import datetime, timezone

from local_ingestion.observability.metrics import (
    MetricType,
    Metric,
    Counter,
    Gauge,
    Histogram,
    MetricsCollector,
)


class TestMetric:
    """Tests for Metric dataclass."""

    def test_metric_creation(self):
        """Test basic metric creation."""
        metric = Metric(
            name="test_metric",
            value=42.0,
            metric_type=MetricType.COUNTER,
        )
        assert metric.name == "test_metric"
        assert metric.value == 42.0
        assert metric.metric_type == MetricType.COUNTER
        assert metric.tags == {}
        assert metric.timestamp is not None

    def test_metric_to_dict(self):
        """Test metric conversion to dictionary."""
        metric = Metric(
            name="test_metric",
            value=10.0,
            metric_type=MetricType.GAUGE,
            tags={"env": "test"},
            description="Test metric",
        )
        result = metric.to_dict()

        assert result["name"] == "test_metric"
        assert result["value"] == 10.0
        assert result["type"] == "gauge"
        assert result["tags"] == {"env": "test"}
        assert result["description"] == "Test metric"


class TestCounter:
    """Tests for Counter metric."""

    def test_counter_initial_value(self):
        """Test counter starts at zero."""
        counter = Counter("test_counter", "A test counter")
        assert counter.value == 0.0

    def test_counter_increment(self):
        """Test counter increments correctly."""
        counter = Counter("test_counter")
        new_value = counter.increment()
        assert new_value == 1.0
        assert counter.value == 1.0

    def test_counter_increment_by_amount(self):
        """Test counter increments by specific amount."""
        counter = Counter("test_counter")
        counter.increment(5)
        assert counter.value == 5.0

    def test_counter_multiple_increments(self):
        """Test multiple counter increments."""
        counter = Counter("test_counter")
        for _ in range(10):
            counter.increment()
        assert counter.value == 10.0

    def test_counter_reset(self):
        """Test counter reset."""
        counter = Counter("test_counter")
        counter.increment(100)
        counter.reset()
        assert counter.value == 0.0

    def test_counter_get_metric(self):
        """Test getting metric representation."""
        counter = Counter("test_counter", "Description", tags={"env": "test"})
        counter.increment(5)
        metric = counter.get_metric()

        assert metric.name == "test_counter"
        assert metric.value == 5.0
        assert metric.metric_type == MetricType.COUNTER


class TestGauge:
    """Tests for Gauge metric."""

    def test_gauge_initial_value(self):
        """Test gauge starts at zero."""
        gauge = Gauge("test_gauge")
        assert gauge.value == 0.0

    def test_gauge_set_value(self):
        """Test setting gauge value."""
        gauge = Gauge("test_gauge")
        gauge.set(42.5)
        assert gauge.value == 42.5

    def test_gauge_increment(self):
        """Test gauge increment."""
        gauge = Gauge("test_gauge")
        gauge.set(10)
        gauge.increment(5)
        assert gauge.value == 15.0

    def test_gauge_decrement(self):
        """Test gauge decrement."""
        gauge = Gauge("test_gauge")
        gauge.set(10)
        gauge.decrement(3)
        assert gauge.value == 7.0

    def test_gauge_can_go_negative(self):
        """Test gauge can go negative."""
        gauge = Gauge("test_gauge")
        gauge.decrement(10)
        assert gauge.value == -10.0


class TestHistogram:
    """Tests for Histogram metric."""

    def test_histogram_initial_state(self):
        """Test histogram starts empty."""
        hist = Histogram("test_histogram")
        stats = hist.get_stats()
        assert stats["count"] == 0
        assert stats["avg"] == 0.0

    def test_histogram_observe(self):
        """Test histogram observation."""
        hist = Histogram("test_histogram")
        hist.observe(1.0)
        hist.observe(2.0)
        hist.observe(3.0)

        stats = hist.get_stats()
        assert stats["count"] == 3
        assert stats["sum"] == 6.0
        assert stats["avg"] == 2.0
        assert stats["min"] == 1.0
        assert stats["max"] == 3.0

    def test_histogram_percentiles(self):
        """Test histogram percentile calculation."""
        hist = Histogram("test_histogram")
        for i in range(100):
            hist.observe(float(i))

        stats = hist.get_stats()
        assert stats["p50"] == 50.0
        assert stats["p90"] == 90.0
        assert stats["p95"] == 95.0
        assert stats["p99"] == 99.0

    def test_histogram_bucket_counts(self):
        """Test histogram bucket counts."""
        hist = Histogram("test_histogram", buckets=[1.0, 5.0, 10.0])
        hist.observe(0.5)
        hist.observe(3.0)
        hist.observe(7.0)
        hist.observe(15.0)

        bucket_counts = hist.get_bucket_counts()
        assert bucket_counts["le_1.0"] == 1
        assert bucket_counts["le_5.0"] == 2
        assert bucket_counts["le_10.0"] == 3
        assert bucket_counts["le_+Inf"] == 4


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    def test_collector_initialization(self):
        """Test collector initializes with default metrics."""
        collector = MetricsCollector()

        assert collector.get_counter("ingestion_success_total") is not None
        assert collector.get_counter("ingestion_failure_total") is not None
        assert collector.get_gauge("active_workflows") is not None
        assert collector.get_histogram("pipeline_duration_seconds") is not None

    def test_record_success(self):
        """Test recording successful ingestion."""
        collector = MetricsCollector()
        collector.record_success()

        counter = collector.get_counter("ingestion_success_total")
        assert counter.value == 1.0

    def test_record_failure(self):
        """Test recording failed ingestion."""
        collector = MetricsCollector()
        collector.record_failure()

        counter = collector.get_counter("ingestion_failure_total")
        assert counter.value == 1.0

    def test_record_rows(self):
        """Test recording rows processed."""
        collector = MetricsCollector()
        collector.record_rows(1000)

        counter = collector.get_counter("rows_processed")
        assert counter.value == 1000.0

    def test_record_duration(self):
        """Test recording pipeline duration."""
        collector = MetricsCollector()
        collector.record_duration(1.5)

        hist = collector.get_histogram("pipeline_duration_seconds")
        stats = hist.get_stats()
        assert stats["count"] == 1
        assert stats["avg"] == 1.5

    def test_set_active_workflows(self):
        """Test setting active workflow count."""
        collector = MetricsCollector()
        collector.set_active_workflows(5)

        gauge = collector.get_gauge("active_workflows")
        assert gauge.value == 5.0

    def test_increment_decrement_active_workflows(self):
        """Test incrementing and decrementing active workflows."""
        collector = MetricsCollector()
        collector.set_active_workflows(3)
        collector.increment_active_workflows()
        collector.increment_active_workflows()

        gauge = collector.get_gauge("active_workflows")
        assert gauge.value == 5.0

        collector.decrement_active_workflows()
        assert gauge.value == 4.0

    def test_custom_counter(self):
        """Test creating custom counter."""
        collector = MetricsCollector()
        counter = collector.counter("custom_counter", "A custom counter")
        counter.increment(10)

        assert collector.get_counter("custom_counter").value == 10.0

    def test_custom_histogram(self):
        """Test creating custom histogram."""
        collector = MetricsCollector()
        hist = collector.histogram("custom_histogram", "A custom histogram", [1.0, 5.0, 10.0])
        hist.observe(3.0)

        assert collector.get_histogram("custom_histogram") is not None

    def test_get_all_metrics(self):
        """Test getting all metrics."""
        collector = MetricsCollector()
        collector.record_success()
        collector.set_active_workflows(2)

        metrics = collector.get_all_metrics()
        assert len(metrics) >= 5

    def test_export_prometheus(self):
        """Test Prometheus format export."""
        collector = MetricsCollector()
        collector.record_success()
        collector.set_active_workflows(5)
        collector.record_duration(1.5)

        prometheus_output = collector.export_prometheus()

        assert "ingestion_success_total" in prometheus_output
        assert "active_workflows" in prometheus_output
        assert "pipeline_duration_seconds" in prometheus_output
        assert "# HELP" in prometheus_output
        assert "# TYPE" in prometheus_output

    def test_clear_metrics(self):
        """Test clearing all metrics."""
        collector = MetricsCollector()
        collector.record_success()
        collector.set_active_workflows(5)

        collector.clear()

        assert collector.get_counter("ingestion_success_total").value == 0.0
        assert collector.get_gauge("active_workflows").value == 0.0
