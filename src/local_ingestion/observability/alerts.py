"""Alert Management Module

Provides alert management with:
- Alert rules: failure_threshold, latency_threshold, data_quality_threshold
- Alert levels: INFO, WARNING, CRITICAL
- Alert handlers: EmailHandler, SlackHandler

Supports extensible handler architecture for custom notifications.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Alert:
    """Alert instance representing a triggered alert."""

    rule_name: str
    level: AlertLevel
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False
    resolved: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary representation."""
        return {
            "rule_name": self.rule_name,
            "level": self.level.value,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
            "acknowledged": self.acknowledged,
            "resolved": self.resolved,
        }

    def acknowledge(self) -> None:
        """Mark alert as acknowledged."""
        self.acknowledged = True

    def resolve(self) -> None:
        """Mark alert as resolved."""
        self.resolved = True


class AlertRule(ABC):
    """Abstract base class for alert rules."""

    def __init__(self, name: str, level: AlertLevel, description: str = ""):
        self.name = name
        self.level = level
        self.description = description

    @abstractmethod
    def evaluate(self, context: Dict[str, Any]) -> Optional[Alert]:
        """Evaluate the rule against current context.

        Args:
            context: Dictionary containing metric values and context information

        Returns:
            Alert if rule is triggered, None otherwise
        """
        pass

    @abstractmethod
    def is_triggered(self, context: Dict[str, Any]) -> bool:
        """Check if the rule condition is met.

        Args:
            context: Dictionary containing metric values

        Returns:
            True if rule condition is met
        """
        pass


class FailureThresholdRule(AlertRule):
    """Alert rule that triggers when failure count exceeds threshold."""

    def __init__(
        self,
        name: str = "failure_threshold",
        threshold: int = 10,
        window_seconds: int = 300,
        level: AlertLevel = AlertLevel.WARNING,
    ):
        super().__init__(name, level, "Triggers when failure count exceeds threshold")
        self.threshold = threshold
        self.window_seconds = window_seconds
        self._failure_history: List[tuple[float, int]] = []

    def record_failure(self, count: int = 1) -> None:
        """Record a failure for threshold evaluation."""
        current_time = time.time()
        self._failure_history.append((current_time, count))
        self._cleanup_old_failures()

    def _cleanup_old_failures(self) -> None:
        """Remove failures outside the evaluation window."""
        cutoff_time = time.time() - self.window_seconds
        self._failure_history = [
            (t, c) for t, c in self._failure_history if t > cutoff_time
        ]

    def is_triggered(self, context: Dict[str, Any]) -> bool:
        """Check if failure count exceeds threshold."""
        total_failures = sum(count for _, count in self._failure_history)
        return total_failures >= self.threshold

    def evaluate(self, context: Dict[str, Any]) -> Optional[Alert]:
        """Evaluate the failure threshold rule."""
        self._cleanup_old_failures()

        if not self.is_triggered(context):
            return None

        total_failures = sum(count for _, count in self._failure_history)
        return Alert(
            rule_name=self.name,
            level=self.level,
            message=f"Failure count ({total_failures}) exceeded threshold ({self.threshold}) in the last {self.window_seconds}s",
            metadata={
                "threshold": self.threshold,
                "actual_count": total_failures,
                "window_seconds": self.window_seconds,
            },
        )

    def reset(self) -> None:
        """Reset failure history."""
        self._failure_history.clear()


class LatencyThresholdRule(AlertRule):
    """Alert rule that triggers when latency exceeds threshold."""

    def __init__(
        self,
        name: str = "latency_threshold",
        threshold_ms: float = 5000.0,
        level: AlertLevel = AlertLevel.WARNING,
    ):
        super().__init__(name, level, "Triggers when latency exceeds threshold")
        self.threshold_ms = threshold_ms

    def is_triggered(self, context: Dict[str, Any]) -> bool:
        """Check if latency exceeds threshold."""
        latency_ms = context.get("latency_ms", 0.0)
        return latency_ms > self.threshold_ms

    def evaluate(self, context: Dict[str, Any]) -> Optional[Alert]:
        """Evaluate the latency threshold rule."""
        if not self.is_triggered(context):
            return None

        latency_ms = context.get("latency_ms", 0.0)
        return Alert(
            rule_name=self.name,
            level=self.level,
            message=f"Latency ({latency_ms:.2f}ms) exceeded threshold ({self.threshold_ms:.2f}ms)",
            metadata={
                "threshold_ms": self.threshold_ms,
                "actual_latency_ms": latency_ms,
            },
        )


class DataQualityThresholdRule(AlertRule):
    """Alert rule that triggers when data quality metrics fall below threshold."""

    def __init__(
        self,
        name: str = "data_quality_threshold",
        min_quality_score: float = 0.95,
        level: AlertLevel = AlertLevel.CRITICAL,
    ):
        super().__init__(name, level, "Triggers when data quality score falls below threshold")
        self.min_quality_score = min_quality_score

    def is_triggered(self, context: Dict[str, Any]) -> bool:
        """Check if data quality score is below threshold."""
        quality_score = context.get("quality_score", 1.0)
        return quality_score < self.min_quality_score

    def evaluate(self, context: Dict[str, Any]) -> Optional[Alert]:
        """Evaluate the data quality threshold rule."""
        if not self.is_triggered(context):
            return None

        quality_score = context.get("quality_score", 0.0)
        return Alert(
            rule_name=self.name,
            level=self.level,
            message=f"Data quality score ({quality_score:.4f}) fell below threshold ({self.min_quality_score:.4f})",
            metadata={
                "threshold": self.min_quality_score,
                "actual_score": quality_score,
            },
        )


class AlertHandler(ABC):
    """Abstract base class for alert handlers."""

    def __init__(self, name: str):
        self.name = name
        self._enabled = True

    @abstractmethod
    def handle(self, alert: Alert) -> None:
        """Handle an alert notification.

        Args:
            alert: The alert to handle
        """
        pass

    def enable(self) -> None:
        """Enable this handler."""
        self._enabled = True

    def disable(self) -> None:
        """Disable this handler."""
        self._enabled = False

    @property
    def is_enabled(self) -> bool:
        """Check if handler is enabled."""
        return self._enabled


class EmailHandler(AlertHandler):
    """Email alert handler."""

    def __init__(
        self,
        smtp_host: str = "localhost",
        smtp_port: int = 587,
        from_addr: str = "",
        to_addrs: Optional[List[str]] = None,
        use_tls: bool = True,
    ):
        super().__init__("email")
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_addr = from_addr
        self.to_addrs = to_addrs or []
        self.use_tls = use_tls

    def handle(self, alert: Alert) -> None:
        """Send alert via email."""
        if not self._enabled:
            return

        subject = f"[{alert.level.value.upper()}] OpenMetadata Alert: {alert.rule_name}"
        body = self._format_email_body(alert)

        logger.info(
            "Email alert would be sent: to=%s, subject=%s",
            self.to_addrs,
            subject,
        )

    def _format_email_body(self, alert: Alert) -> str:
        """Format alert as email body."""
        lines = [
            f"Alert: {alert.rule_name}",
            f"Level: {alert.level.value.upper()}",
            f"Time: {alert.timestamp.isoformat()}",
            f"Message: {alert.message}",
            "",
            "Metadata:",
        ]
        for key, value in alert.metadata.items():
            lines.append(f"  {key}: {value}")
        return "\n".join(lines)


class SlackHandler(AlertHandler):
    """Slack alert handler."""

    def __init__(
        self,
        webhook_url: str = "",
        channel: str = "#alerts",
        username: str = "OpenMetadata Alerts",
    ):
        super().__init__("slack")
        self.webhook_url = webhook_url
        self.channel = channel
        self.username = username

    def handle(self, alert: Alert) -> None:
        """Send alert to Slack."""
        if not self._enabled:
            return

        payload = self._format_slack_payload(alert)

        logger.info(
            "Slack alert would be sent: channel=%s, rule=%s",
            self.channel,
            alert.rule_name,
        )

    def _format_slack_payload(self, alert: Alert) -> Dict[str, Any]:
        """Format alert as Slack message payload."""
        level_emoji = {
            AlertLevel.INFO: ":information_source:",
            AlertLevel.WARNING: ":warning:",
            AlertLevel.CRITICAL: ":rotating_light:",
        }

        return {
            "channel": self.channel,
            "username": self.username,
            "text": f"{level_emoji.get(alert.level, '')} *{alert.rule_name}*",
            "attachments": [
                {
                    "color": self._get_color_for_level(alert.level),
                    "fields": [
                        {"title": "Level", "value": alert.level.value.upper(), "short": True},
                        {"title": "Time", "value": alert.timestamp.isoformat(), "short": True},
                        {"title": "Message", "value": alert.message, "short": False},
                    ],
                }
            ],
        }

    def _get_color_for_level(self, level: AlertLevel) -> str:
        """Get Slack attachment color for alert level."""
        colors = {
            AlertLevel.INFO: "good",
            AlertLevel.WARNING: "warning",
            AlertLevel.CRITICAL: "danger",
        }
        return colors.get(level, "good")


class AlertManager:
    """Central alert manager for evaluating rules and dispatching alerts.

    Manages alert rules, maintains alert history, and dispatches notifications
    through registered handlers.
    """

    def __init__(self):
        self._rules: Dict[str, AlertRule] = {}
        self._handlers: List[AlertHandler] = []
        self._alerts: List[Alert] = []
        self._active_alerts: Dict[str, Alert] = {}
        self._lock = threading.RLock()
        self._evaluation_callbacks: List[Callable[[Alert], None]] = []

    def add_rule(self, rule: AlertRule) -> None:
        """Register an alert rule.

        Args:
            rule: Alert rule to add
        """
        with self._lock:
            self._rules[rule.name] = rule
            logger.info("Added alert rule: %s", rule.name)

    def remove_rule(self, name: str) -> None:
        """Remove an alert rule.

        Args:
            name: Name of rule to remove
        """
        with self._lock:
            if name in self._rules:
                del self._rules[name]
                logger.info("Removed alert rule: %s", name)

    def add_handler(self, handler: AlertHandler) -> None:
        """Register an alert handler.

        Args:
            handler: Alert handler to add
        """
        with self._lock:
            self._handlers.append(handler)
            logger.info("Added alert handler: %s", handler.name)

    def remove_handler(self, name: str) -> None:
        """Remove an alert handler.

        Args:
            name: Name of handler to remove
        """
        with self._lock:
            self._handlers = [h for h in self._handlers if h.name != name]
            logger.info("Removed alert handler: %s", name)

    def on_alert(self, callback: Callable[[Alert], None]) -> None:
        """Register a callback to be called when alerts are triggered.

        Args:
            callback: Function to call with triggered alerts
        """
        with self._lock:
            self._evaluation_callbacks.append(callback)

    def evaluate(self, context: Dict[str, Any]) -> List[Alert]:
        """Evaluate all rules against current context.

        Args:
            context: Dictionary containing metric values and context

        Returns:
            List of triggered alerts
        """
        triggered_alerts = []

        with self._lock:
            for rule in self._rules.values():
                alert = rule.evaluate(context)
                if alert:
                    self._process_alert(alert)
                    triggered_alerts.append(alert)

        return triggered_alerts

    def _process_alert(self, alert: Alert) -> None:
        """Process a triggered alert through handlers.

        Dedup is **per rule**, not per timestamp: a rule that stays breached must
        produce one active alert, not one alert per evaluation. The key used to
        include ``timestamp``, which is unique for every freshly built ``Alert``
        — so every ``evaluate()`` appended another copy (3 rules × 3 evaluations
        produced 6 alerts instead of 3). The active entry is released in
        :meth:`resolve_alert`, so a rule can fire again after being resolved.
        """
        alert_key = alert.rule_name

        if alert_key in self._active_alerts:
            return

        self._alerts.append(alert)
        self._active_alerts[alert_key] = alert

        for handler in self._handlers:
            try:
                handler.handle(alert)
            except Exception as e:
                logger.error("Error in alert handler %s: %s", handler.name, e)

        for callback in self._evaluation_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error("Error in alert callback: %s", e)

    def acknowledge_alert(self, index: int) -> bool:
        """Acknowledge an alert by index.

        Args:
            index: Index of alert in history

        Returns:
            True if alert was acknowledged
        """
        with self._lock:
            if 0 <= index < len(self._alerts):
                self._alerts[index].acknowledge()
                return True
            return False

    def resolve_alert(self, index: int) -> bool:
        """Resolve an alert by index.

        Args:
            index: Index of alert in history

        Returns:
            True if alert was resolved
        """
        with self._lock:
            if 0 <= index < len(self._alerts):
                alert = self._alerts[index]
                alert.resolve()
                # 释放该规则的去重占位，使其后续再次越阈值时仍能告警。
                self._active_alerts.pop(alert.rule_name, None)
                return True
            return False

    def get_active_alerts(self, level: Optional[AlertLevel] = None) -> List[Alert]:
        """Get all active (unresolved) alerts.

        Args:
            level: Optional filter by alert level

        Returns:
            List of active alerts
        """
        with self._lock:
            alerts = [a for a in self._alerts if not a.resolved]
            if level:
                alerts = [a for a in alerts if a.level == level]
            return alerts

    def get_alert_history(
        self,
        limit: int = 100,
        level: Optional[AlertLevel] = None,
        resolved: Optional[bool] = None,
    ) -> List[Alert]:
        """Get alert history with optional filters.

        Args:
            limit: Maximum number of alerts to return
            level: Optional filter by alert level
            resolved: Optional filter by resolved status

        Returns:
            List of matching alerts
        """
        with self._lock:
            alerts = list(self._alerts)

            if level is not None:
                alerts = [a for a in alerts if a.level == level]

            if resolved is not None:
                alerts = [a for a in alerts if a.resolved == resolved]

            alerts.sort(key=lambda a: a.timestamp, reverse=True)
            return alerts[:limit]

    def get_active_count(self, level: Optional[AlertLevel] = None) -> int:
        """Get count of active alerts.

        Args:
            level: Optional filter by alert level

        Returns:
            Number of active alerts
        """
        return len(self.get_active_alerts(level))

    def clear_resolved(self) -> int:
        """Clear resolved alerts from history.

        Returns:
            Number of alerts cleared
        """
        with self._lock:
            initial_count = len(self._alerts)
            self._alerts = [a for a in self._alerts if not a.resolved]
            self._active_alerts.clear()
            return initial_count - len(self._alerts)
