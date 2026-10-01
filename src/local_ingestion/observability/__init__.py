"""Observability Module for Local Ingestion

This module provides comprehensive observability features including:
- Metrics collection and export (Prometheus format)
- Alert management and notification handling
- Health check services for system components
"""

from local_ingestion.observability.metrics import (
    MetricsCollector,
    Counter,
    Gauge,
    Histogram,
    MetricType,
)
from local_ingestion.observability.alerts import (
    AlertManager,
    Alert,
    AlertLevel,
    AlertRule,
    AlertHandler,
    EmailHandler,
    SlackHandler,
    FailureThresholdRule,
    LatencyThresholdRule,
    DataQualityThresholdRule,
)
from local_ingestion.observability.health import (
    HealthCheckService,
    HealthCheckResult,
    ComponentHealth,
    DatabaseHealthCheck,
    MessageQueueHealthCheck,
    StorageHealthCheck,
)

__all__ = [
    # Metrics
    "MetricsCollector",
    "Counter",
    "Gauge",
    "Histogram",
    "MetricType",
    # Alerts
    "AlertManager",
    "Alert",
    "AlertLevel",
    "AlertRule",
    "AlertHandler",
    "EmailHandler",
    "SlackHandler",
    "FailureThresholdRule",
    "LatencyThresholdRule",
    "DataQualityThresholdRule",
    # Health
    "HealthCheckService",
    "HealthCheckResult",
    "ComponentHealth",
    "DatabaseHealthCheck",
    "MessageQueueHealthCheck",
    "StorageHealthCheck",
]
