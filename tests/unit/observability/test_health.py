"""Unit Tests for Health Module"""

import pytest
import asyncio
from datetime import datetime, timezone

from local_ingestion.observability.health import (
    ComponentHealth,
    HealthCheckResult,
    SystemHealth,
    HealthCheck,
    DatabaseHealthCheck,
    MessageQueueHealthCheck,
    StorageHealthCheck,
    HealthCheckService,
)


class TestHealthCheckResult:
    """Tests for HealthCheckResult dataclass."""

    def test_result_creation(self):
        """Test basic result creation."""
        result = HealthCheckResult(
            component="database",
            status=ComponentHealth.HEALTHY,
            message="Connection successful",
        )

        assert result.component == "database"
        assert result.status == ComponentHealth.HEALTHY
        assert result.message == "Connection successful"
        assert result.latency_ms == 0.0
        assert result.timestamp is not None

    def test_result_to_dict(self):
        """Test result conversion to dictionary."""
        result = HealthCheckResult(
            component="database",
            status=ComponentHealth.HEALTHY,
            message="OK",
            latency_ms=10.5,
            metadata={"version": "1.0"},
        )

        data = result.to_dict()
        assert data["component"] == "database"
        assert data["status"] == "healthy"
        assert data["message"] == "OK"
        assert data["latency_ms"] == 10.5
        assert data["metadata"] == {"version": "1.0"}

    def test_is_healthy(self):
        """Test is_healthy property."""
        healthy_result = HealthCheckResult(
            component="test",
            status=ComponentHealth.HEALTHY,
        )
        assert healthy_result.is_healthy is True

        unhealthy_result = HealthCheckResult(
            component="test",
            status=ComponentHealth.UNHEALTHY,
        )
        assert unhealthy_result.is_healthy is False


class TestSystemHealth:
    """Tests for SystemHealth dataclass."""

    def test_system_health_creation(self):
        """Test system health creation."""
        result = HealthCheckResult(
            component="database",
            status=ComponentHealth.HEALTHY,
        )
        system_health = SystemHealth(
            overall_status=ComponentHealth.HEALTHY,
            checks=[result],
        )

        assert system_health.overall_status == ComponentHealth.HEALTHY
        assert len(system_health.checks) == 1

    def test_system_health_to_dict(self):
        """Test system health conversion to dictionary."""
        result = HealthCheckResult(
            component="database",
            status=ComponentHealth.HEALTHY,
        )
        system_health = SystemHealth(
            overall_status=ComponentHealth.HEALTHY,
            checks=[result],
        )

        data = system_health.to_dict()
        assert data["overall_status"] == "healthy"
        assert len(data["checks"]) == 1

    def test_get_unhealthy_components(self):
        """Test getting unhealthy components."""
        healthy = HealthCheckResult(
            component="database",
            status=ComponentHealth.HEALTHY,
        )
        unhealthy = HealthCheckResult(
            component="cache",
            status=ComponentHealth.UNHEALTHY,
        )
        degraded = HealthCheckResult(
            component="queue",
            status=ComponentHealth.DEGRADED,
        )

        system_health = SystemHealth(
            overall_status=ComponentHealth.DEGRADED,
            checks=[healthy, unhealthy, degraded],
        )

        unhealthy_components = system_health.get_unhealthy_components()
        assert len(unhealthy_components) == 1
        assert unhealthy_components[0].component == "cache"

    def test_get_component(self):
        """Test getting specific component."""
        result = HealthCheckResult(
            component="database",
            status=ComponentHealth.HEALTHY,
        )
        system_health = SystemHealth(
            overall_status=ComponentHealth.HEALTHY,
            checks=[result],
        )

        found = system_health.get_component("database")
        assert found is not None
        assert found.component == "database"

        not_found = system_health.get_component("nonexistent")
        assert not_found is None


class TestDatabaseHealthCheck:
    """Tests for DatabaseHealthCheck."""

    def test_check_creation(self):
        """Test health check creation."""
        check = DatabaseHealthCheck(
            name="postgres_db",
            connection_string="postgresql://localhost:5432/test",
            query="SELECT 1",
        )

        assert check.name == "postgres_db"
        assert check.connection_string == "postgresql://localhost:5432/test"

    def test_check_sync(self):
        """Test synchronous health check execution."""
        check = DatabaseHealthCheck(name="test_db")
        result = check.check_sync()

        assert result.component == "test_db"
        assert result.status in [ComponentHealth.HEALTHY, ComponentHealth.UNHEALTHY]
        assert result.latency_ms >= 0


class TestMessageQueueHealthCheck:
    """Tests for MessageQueueHealthCheck."""

    def test_check_creation(self):
        """Test health check creation."""
        check = MessageQueueHealthCheck(
            name="rabbitmq",
            queue_url="amqp://localhost:5672",
        )

        assert check.name == "rabbitmq"
        assert check.queue_url == "amqp://localhost:5672"

    def test_check_sync(self):
        """Test synchronous health check execution."""
        check = MessageQueueHealthCheck(name="test_queue")
        result = check.check_sync()

        assert result.component == "test_queue"
        assert result.status in [ComponentHealth.HEALTHY, ComponentHealth.UNHEALTHY]


class TestStorageHealthCheck:
    """Tests for StorageHealthCheck."""

    def test_check_creation(self):
        """Test health check creation."""
        check = StorageHealthCheck(
            name="s3_bucket",
            storage_path="s3://my-bucket",
        )

        assert check.name == "s3_bucket"
        assert check.storage_path == "s3://my-bucket"

    def test_check_sync(self):
        """Test synchronous health check execution."""
        check = StorageHealthCheck(name="test_storage")
        result = check.check_sync()

        assert result.component == "test_storage"
        assert result.status in [ComponentHealth.HEALTHY, ComponentHealth.UNHEALTHY]


class TestHealthCheckService:
    """Tests for HealthCheckService."""

    def test_service_creation(self):
        """Test service creation."""
        service = HealthCheckService()
        assert len(service._checks) == 0

    def test_register_check(self):
        """Test registering health check."""
        service = HealthCheckService()
        check = DatabaseHealthCheck(name="test_db")
        service.register_check(check)

        assert "test_db" in service._checks

    def test_unregister_check(self):
        """Test unregistering health check."""
        service = HealthCheckService()
        check = DatabaseHealthCheck(name="test_db")
        service.register_check(check)
        service.unregister_check("test_db")

        assert "test_db" not in service._checks

    def test_check_all(self):
        """Test checking all registered health checks."""
        service = HealthCheckService()
        service.register_check(DatabaseHealthCheck(name="db1"))
        service.register_check(DatabaseHealthCheck(name="db2"))

        result = service.check_all_sync()

        assert result.overall_status in ComponentHealth
        assert len(result.checks) == 2

    def test_get_check_result(self):
        """Test getting specific check result."""
        service = HealthCheckService()
        check = DatabaseHealthCheck(name="test_db")
        service.register_check(check)
        service.check_all_sync()

        result = service.get_check_result("test_db")
        assert result is not None
        assert result.component == "test_db"

    def test_get_last_health(self):
        """Test getting last health status."""
        service = HealthCheckService()
        service.register_check(DatabaseHealthCheck(name="test_db"))
        service.check_all_sync()

        last_health = service.get_last_health()
        assert last_health is not None
        assert len(last_health.checks) == 1

    def test_get_last_health_when_no_checks_run(self):
        """Test getting last health when no checks have run."""
        service = HealthCheckService()
        last_health = service.get_last_health()
        assert last_health is None

    def test_compute_overall_status_all_healthy(self):
        """Test overall status when all checks are healthy."""
        service = HealthCheckService()
        results = [
            HealthCheckResult(component="db", status=ComponentHealth.HEALTHY),
            HealthCheckResult(component="queue", status=ComponentHealth.HEALTHY),
        ]

        status = service._compute_overall_status(results)
        assert status == ComponentHealth.HEALTHY

    def test_compute_overall_status_with_unhealthy(self):
        """Test overall status when any check is unhealthy."""
        service = HealthCheckService()
        results = [
            HealthCheckResult(component="db", status=ComponentHealth.HEALTHY),
            HealthCheckResult(component="queue", status=ComponentHealth.UNHEALTHY),
        ]

        status = service._compute_overall_status(results)
        assert status == ComponentHealth.UNHEALTHY

    def test_compute_overall_status_with_degraded(self):
        """Test overall status when checks include degraded."""
        service = HealthCheckService()
        results = [
            HealthCheckResult(component="db", status=ComponentHealth.HEALTHY),
            HealthCheckResult(component="queue", status=ComponentHealth.DEGRADED),
        ]

        status = service._compute_overall_status(results)
        assert status == ComponentHealth.DEGRADED

    def test_compute_overall_status_with_unknown(self):
        """Test overall status when checks include unknown."""
        service = HealthCheckService()
        results = [
            HealthCheckResult(component="db", status=ComponentHealth.HEALTHY),
            HealthCheckResult(component="queue", status=ComponentHealth.UNKNOWN),
        ]

        status = service._compute_overall_status(results)
        assert status == ComponentHealth.DEGRADED

    def test_compute_overall_status_empty(self):
        """Test overall status with no checks."""
        service = HealthCheckService()
        status = service._compute_overall_status([])
        assert status == ComponentHealth.UNKNOWN

    def test_on_health_change_callback(self):
        """Test health change callback registration."""
        service = HealthCheckService()
        callback_called = []

        def callback(health):
            callback_called.append(health)

        service.on_health_change(callback)
        service.register_check(DatabaseHealthCheck(name="test_db"))
        service.check_all_sync()

        assert len(callback_called) == 1
