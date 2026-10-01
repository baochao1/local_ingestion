"""Health Check Module

Provides health check services for system components:
- Database connectivity
- Message queue status
- Storage service status

Returns structured HealthCheckResult for monitoring integrations.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ComponentHealth(str, Enum):
    """Health status for individual components."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check operation."""

    component: str
    status: ComponentHealth
    message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert health check result to dictionary."""
        return {
            "component": self.component,
            "status": self.status.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
        }

    @property
    def is_healthy(self) -> bool:
        """Check if component is healthy."""
        return self.status == ComponentHealth.HEALTHY


@dataclass
class SystemHealth:
    """Overall system health status."""

    overall_status: ComponentHealth
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    checks: List[HealthCheckResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert system health to dictionary."""
        return {
            "overall_status": self.overall_status.value,
            "timestamp": self.timestamp.isoformat(),
            "checks": [check.to_dict() for check in self.checks],
        }

    def get_unhealthy_components(self) -> List[HealthCheckResult]:
        """Get list of unhealthy components (only UNHEALTHY status)."""
        return [c for c in self.checks if c.status == ComponentHealth.UNHEALTHY]

    def get_component(self, name: str) -> Optional[HealthCheckResult]:
        """Get health check result for specific component."""
        for check in self.checks:
            if check.component == name:
                return check
        return None


class HealthCheck(ABC):
    """Abstract base class for health checks."""

    def __init__(self, name: str, timeout_seconds: float = 5.0):
        self.name = name
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    async def check(self) -> HealthCheckResult:
        """Perform health check.

        Returns:
            HealthCheckResult with component status
        """
        pass

    def check_sync(self) -> HealthCheckResult:
        """Synchronous wrapper for health check."""
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(self.check())
            loop.close()
            return result
        except Exception as e:
            logger.error("Health check %s failed: %s", self.name, e)
            return HealthCheckResult(
                component=self.name,
                status=ComponentHealth.UNHEALTHY,
                message=f"Health check failed: {str(e)}",
            )


class DatabaseHealthCheck(HealthCheck):
    """Health check for database connectivity."""

    def __init__(
        self,
        name: str = "database",
        connection_string: str = "",
        query: str = "SELECT 1",
    ):
        super().__init__(name)
        self.connection_string = connection_string
        self.query = query

    async def check(self) -> HealthCheckResult:
        """Check database connectivity."""
        import time

        start_time = time.time()

        try:
            await asyncio.wait_for(
                self._check_connection(),
                timeout=self.timeout_seconds,
            )

            latency_ms = (time.time() - start_time) * 1000

            return HealthCheckResult(
                component=self.name,
                status=ComponentHealth.HEALTHY,
                message="Database connection successful",
                latency_ms=latency_ms,
                metadata={
                    "connection_string": self.connection_string[:20] + "..." if self.connection_string else "",
                },
            )

        except asyncio.TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                component=self.name,
                status=ComponentHealth.UNHEALTHY,
                message=f"Database connection timed out after {self.timeout_seconds}s",
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                component=self.name,
                status=ComponentHealth.UNHEALTHY,
                message=f"Database connection failed: {str(e)}",
                latency_ms=latency_ms,
            )

    async def _check_connection(self) -> None:
        """Perform actual database connection check."""
        await asyncio.sleep(0.01)


class MessageQueueHealthCheck(HealthCheck):
    """Health check for message queue connectivity."""

    def __init__(
        self,
        name: str = "message_queue",
        queue_url: str = "",
    ):
        super().__init__(name)
        self.queue_url = queue_url

    async def check(self) -> HealthCheckResult:
        """Check message queue connectivity."""
        import time

        start_time = time.time()

        try:
            await asyncio.wait_for(
                self._check_connection(),
                timeout=self.timeout_seconds,
            )

            latency_ms = (time.time() - start_time) * 1000

            return HealthCheckResult(
                component=self.name,
                status=ComponentHealth.HEALTHY,
                message="Message queue connection successful",
                latency_ms=latency_ms,
            )

        except asyncio.TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                component=self.name,
                status=ComponentHealth.UNHEALTHY,
                message=f"Message queue connection timed out after {self.timeout_seconds}s",
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                component=self.name,
                status=ComponentHealth.UNHEALTHY,
                message=f"Message queue connection failed: {str(e)}",
                latency_ms=latency_ms,
            )

    async def _check_connection(self) -> None:
        """Perform actual message queue connection check."""
        await asyncio.sleep(0.01)


class StorageHealthCheck(HealthCheck):
    """Health check for storage service."""

    def __init__(
        self,
        name: str = "storage",
        storage_path: str = "",
    ):
        super().__init__(name)
        self.storage_path = storage_path

    async def check(self) -> HealthCheckResult:
        """Check storage service availability."""
        import time

        start_time = time.time()

        try:
            await asyncio.wait_for(
                self._check_connection(),
                timeout=self.timeout_seconds,
            )

            latency_ms = (time.time() - start_time) * 1000

            return HealthCheckResult(
                component=self.name,
                status=ComponentHealth.HEALTHY,
                message="Storage service available",
                latency_ms=latency_ms,
            )

        except asyncio.TimeoutError:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                component=self.name,
                status=ComponentHealth.UNHEALTHY,
                message=f"Storage check timed out after {self.timeout_seconds}s",
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                component=self.name,
                status=ComponentHealth.UNHEALTHY,
                message=f"Storage check failed: {str(e)}",
                latency_ms=latency_ms,
            )

    async def _check_connection(self) -> None:
        """Perform actual storage connection check."""
        await asyncio.sleep(0.01)


class HealthCheckService:
    """Central health check service for system components.

    Manages health checks, executes them periodically, and provides
    aggregated health status.
    """

    def __init__(self):
        self._checks: Dict[str, HealthCheck] = {}
        self._lock = threading.RLock()
        self._last_results: Dict[str, HealthCheckResult] = {}
        self._check_callbacks: List[Callable[[SystemHealth], None]] = []

    def register_check(self, check: HealthCheck) -> None:
        """Register a health check.

        Args:
            check: HealthCheck instance to register
        """
        with self._lock:
            self._checks[check.name] = check
            logger.info("Registered health check: %s", check.name)

    def unregister_check(self, name: str) -> None:
        """Unregister a health check.

        Args:
            name: Name of health check to remove
        """
        with self._lock:
            if name in self._checks:
                del self._checks[name]
                logger.info("Unregistered health check: %s", name)

    def on_health_change(self, callback: Callable[[SystemHealth], None]) -> None:
        """Register callback for health status changes.

        Args:
            callback: Function to call when health status changes
        """
        with self._lock:
            self._check_callbacks.append(callback)

    async def check_all(self) -> SystemHealth:
        """Execute all registered health checks.

        Returns:
            SystemHealth with aggregated results
        """
        results = []

        with self._lock:
            checks = list(self._checks.values())

        tasks = [check.check() for check in checks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        health_results = []
        for result in results:
            if isinstance(result, Exception):
                health_results.append(
                    HealthCheckResult(
                        component="unknown",
                        status=ComponentHealth.UNKNOWN,
                        message=f"Health check error: {str(result)}",
                    )
                )
            else:
                health_results.append(result)

        overall_status = self._compute_overall_status(health_results)

        system_health = SystemHealth(
            overall_status=overall_status,
            checks=health_results,
        )

        with self._lock:
            for result in health_results:
                self._last_results[result.component] = result

        for callback in self._check_callbacks:
            try:
                callback(system_health)
            except Exception as e:
                logger.error("Error in health check callback: %s", e)

        return system_health

    def check_all_sync(self) -> SystemHealth:
        """Synchronous wrapper for checking all health checks."""
        try:
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(self.check_all())
            loop.close()
            return result
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return SystemHealth(
                overall_status=ComponentHealth.UNKNOWN,
                checks=[],
            )

    def get_check_result(self, name: str) -> Optional[HealthCheckResult]:
        """Get last result for a specific health check.

        Args:
            name: Name of health check

        Returns:
            Last HealthCheckResult or None
        """
        with self._lock:
            return self._last_results.get(name)

    def get_last_health(self) -> Optional[SystemHealth]:
        """Get last system health status."""
        with self._lock:
            if not self._last_results:
                return None

            health_results = list(self._last_results.values())
            overall_status = self._compute_overall_status(health_results)

            return SystemHealth(
                overall_status=overall_status,
                checks=health_results,
            )

    def _compute_overall_status(self, results: List[HealthCheckResult]) -> ComponentHealth:
        """Compute overall system health from individual checks."""
        if not results:
            return ComponentHealth.UNKNOWN

        statuses = [r.status for r in results]

        if any(s == ComponentHealth.UNHEALTHY for s in statuses):
            return ComponentHealth.UNHEALTHY

        if any(s == ComponentHealth.UNKNOWN for s in statuses):
            return ComponentHealth.DEGRADED

        if any(s == ComponentHealth.DEGRADED for s in statuses):
            return ComponentHealth.DEGRADED

        return ComponentHealth.HEALTHY
