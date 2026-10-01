"""Unit Tests for Alerts Module"""

import pytest
from datetime import datetime, timezone

from local_ingestion.observability.alerts import (
    AlertLevel,
    Alert,
    AlertRule,
    AlertHandler,
    EmailHandler,
    SlackHandler,
    FailureThresholdRule,
    LatencyThresholdRule,
    DataQualityThresholdRule,
    AlertManager,
)


class TestAlert:
    """Tests for Alert dataclass."""

    def test_alert_creation(self):
        """Test basic alert creation."""
        alert = Alert(
            rule_name="test_rule",
            level=AlertLevel.WARNING,
            message="Test alert message",
        )

        assert alert.rule_name == "test_rule"
        assert alert.level == AlertLevel.WARNING
        assert alert.message == "Test alert message"
        assert alert.acknowledged is False
        assert alert.resolved is False
        assert alert.timestamp is not None

    def test_alert_to_dict(self):
        """Test alert conversion to dictionary."""
        alert = Alert(
            rule_name="test_rule",
            level=AlertLevel.CRITICAL,
            message="Critical alert",
            metadata={"key": "value"},
        )

        result = alert.to_dict()
        assert result["rule_name"] == "test_rule"
        assert result["level"] == "critical"
        assert result["message"] == "Critical alert"
        assert result["metadata"] == {"key": "value"}

    def test_alert_acknowledge(self):
        """Test acknowledging alert."""
        alert = Alert(
            rule_name="test_rule",
            level=AlertLevel.WARNING,
            message="Test alert",
        )
        assert alert.acknowledged is False

        alert.acknowledge()
        assert alert.acknowledged is True

    def test_alert_resolve(self):
        """Test resolving alert."""
        alert = Alert(
            rule_name="test_rule",
            level=AlertLevel.WARNING,
            message="Test alert",
        )
        assert alert.resolved is False

        alert.resolve()
        assert alert.resolved is True


class TestFailureThresholdRule:
    """Tests for FailureThresholdRule."""

    def test_rule_creation(self):
        """Test rule creation."""
        rule = FailureThresholdRule(
            name="custom_failure",
            threshold=5,
            window_seconds=60,
        )

        assert rule.name == "custom_failure"
        assert rule.threshold == 5
        assert rule.window_seconds == 60

    def test_rule_not_triggered_initially(self):
        """Test rule not triggered initially."""
        rule = FailureThresholdRule(threshold=5)
        assert rule.is_triggered({}) is False

    def test_rule_triggered_after_threshold(self):
        """Test rule triggered after exceeding threshold."""
        rule = FailureThresholdRule(threshold=3)

        rule.record_failure()
        assert rule.is_triggered({}) is False

        rule.record_failure()
        assert rule.is_triggered({}) is False

        rule.record_failure()
        assert rule.is_triggered({}) is True

    def test_rule_evaluate_returns_alert(self):
        """Test rule evaluation returns alert when triggered."""
        rule = FailureThresholdRule(threshold=2)

        rule.record_failure()
        rule.record_failure()

        alert = rule.evaluate({})
        assert alert is not None
        assert alert.rule_name == "failure_threshold"
        assert alert.level == AlertLevel.WARNING

    def test_rule_evaluate_returns_none_when_not_triggered(self):
        """Test rule evaluation returns None when not triggered."""
        rule = FailureThresholdRule(threshold=5)
        rule.record_failure(3)

        alert = rule.evaluate({})
        assert alert is None

    def test_rule_reset(self):
        """Test rule reset clears history."""
        rule = FailureThresholdRule(threshold=2)
        rule.record_failure()
        rule.record_failure()

        assert rule.is_triggered({}) is True

        rule.reset()
        assert rule.is_triggered({}) is False


class TestLatencyThresholdRule:
    """Tests for LatencyThresholdRule."""

    def test_rule_not_triggered_below_threshold(self):
        """Test rule not triggered when latency is below threshold."""
        rule = LatencyThresholdRule(threshold_ms=1000.0)
        context = {"latency_ms": 500.0}

        assert rule.is_triggered(context) is False

    def test_rule_triggered_above_threshold(self):
        """Test rule triggered when latency exceeds threshold."""
        rule = LatencyThresholdRule(threshold_ms=1000.0)
        context = {"latency_ms": 1500.0}

        assert rule.is_triggered(context) is True

    def test_rule_evaluate_returns_alert(self):
        """Test rule evaluation returns alert when triggered."""
        rule = LatencyThresholdRule(threshold_ms=1000.0)
        context = {"latency_ms": 2000.0}

        alert = rule.evaluate(context)
        assert alert is not None
        assert alert.rule_name == "latency_threshold"
        assert alert.level == AlertLevel.WARNING
        assert "2000" in alert.message


class TestDataQualityThresholdRule:
    """Tests for DataQualityThresholdRule."""

    def test_rule_not_triggered_above_threshold(self):
        """Test rule not triggered when quality is above threshold."""
        rule = DataQualityThresholdRule(min_quality_score=0.9)
        context = {"quality_score": 0.95}

        assert rule.is_triggered(context) is False

    def test_rule_triggered_below_threshold(self):
        """Test rule triggered when quality is below threshold."""
        rule = DataQualityThresholdRule(min_quality_score=0.9)
        context = {"quality_score": 0.85}

        assert rule.is_triggered(context) is True

    def test_rule_evaluate_returns_alert(self):
        """Test rule evaluation returns alert when triggered."""
        rule = DataQualityThresholdRule(min_quality_score=0.9, level=AlertLevel.CRITICAL)
        context = {"quality_score": 0.80}

        alert = rule.evaluate(context)
        assert alert is not None
        assert alert.rule_name == "data_quality_threshold"
        assert alert.level == AlertLevel.CRITICAL


class TestEmailHandler:
    """Tests for EmailHandler."""

    def test_handler_creation(self):
        """Test handler creation."""
        handler = EmailHandler(
            smtp_host="smtp.example.com",
            smtp_port=587,
            from_addr="alerts@example.com",
            to_addrs=["admin@example.com"],
        )

        assert handler.smtp_host == "smtp.example.com"
        assert handler.smtp_port == 587
        assert handler.name == "email"
        assert handler.is_enabled is True

    def test_handler_enable_disable(self):
        """Test handler enable/disable."""
        handler = EmailHandler()
        assert handler.is_enabled is True

        handler.disable()
        assert handler.is_enabled is False

        handler.enable()
        assert handler.is_enabled is True

    def test_handler_handle(self):
        """Test handler handle method (logs without exception)."""
        handler = EmailHandler(to_addrs=["test@example.com"])
        alert = Alert(
            rule_name="test_rule",
            level=AlertLevel.WARNING,
            message="Test alert",
        )

        handler.handle(alert)


class TestSlackHandler:
    """Tests for SlackHandler."""

    def test_handler_creation(self):
        """Test handler creation."""
        handler = SlackHandler(
            webhook_url="https://hooks.slack.com/services/xxx",
            channel="#alerts",
            username="Test Alerts",
        )

        assert handler.channel == "#alerts"
        assert handler.username == "Test Alerts"
        assert handler.name == "slack"

    def test_handler_handle(self):
        """Test handler handle method (logs without exception)."""
        handler = SlackHandler(channel="#test-alerts")
        alert = Alert(
            rule_name="test_rule",
            level=AlertLevel.CRITICAL,
            message="Critical test alert",
        )

        handler.handle(alert)


class TestAlertManager:
    """Tests for AlertManager."""

    def test_manager_creation(self):
        """Test manager creation."""
        manager = AlertManager()
        assert len(manager._rules) == 0
        assert len(manager._handlers) == 0
        assert len(manager._alerts) == 0

    def test_add_rule(self):
        """Test adding alert rule."""
        manager = AlertManager()
        rule = FailureThresholdRule()
        manager.add_rule(rule)

        assert rule.name in manager._rules

    def test_remove_rule(self):
        """Test removing alert rule."""
        manager = AlertManager()
        rule = FailureThresholdRule(name="test_rule")
        manager.add_rule(rule)
        manager.remove_rule("test_rule")

        assert "test_rule" not in manager._rules

    def test_add_handler(self):
        """Test adding alert handler."""
        manager = AlertManager()
        handler = EmailHandler()
        manager.add_handler(handler)

        assert len(manager._handlers) == 1
        assert manager._handlers[0].name == "email"

    def test_remove_handler(self):
        """Test removing alert handler."""
        manager = AlertManager()
        handler = EmailHandler()
        manager.add_handler(handler)
        manager.remove_handler("email")

        assert len(manager._handlers) == 0

    def test_evaluate_no_rules(self):
        """Test evaluation with no rules returns empty list."""
        manager = AlertManager()
        alerts = manager.evaluate({})

        assert alerts == []

    def test_evaluate_triggers_alert(self):
        """Test evaluation triggers alert when rule is met."""
        manager = AlertManager()
        rule = FailureThresholdRule(threshold=1)
        manager.add_rule(rule)

        rule.record_failure()

        alerts = manager.evaluate({})
        assert len(alerts) == 1
        assert alerts[0].rule_name == "failure_threshold"

    def test_get_active_alerts(self):
        """Test getting active alerts."""
        manager = AlertManager()
        rule = FailureThresholdRule(threshold=1)
        manager.add_rule(rule)
        rule.record_failure()
        manager.evaluate({})

        active_alerts = manager.get_active_alerts()
        assert len(active_alerts) == 1

    def test_get_active_alerts_filtered_by_level(self):
        """Test getting active alerts filtered by level."""
        manager = AlertManager()
        rule1 = FailureThresholdRule(name="rule1", level=AlertLevel.WARNING, threshold=1)
        rule2 = DataQualityThresholdRule(name="rule2", level=AlertLevel.CRITICAL)
        manager.add_rule(rule1)
        manager.add_rule(rule2)

        rule1.record_failure()
        manager.evaluate({})

        active_warning = manager.get_active_alerts(level=AlertLevel.WARNING)
        assert len(active_warning) == 1

        alert2 = rule2.evaluate({"quality_score": 0.5})
        if alert2:
            manager._process_alert(alert2)

        active_critical = manager.get_active_alerts(level=AlertLevel.CRITICAL)
        assert len(active_critical) == 1

    def test_acknowledge_alert(self):
        """Test acknowledging alert."""
        manager = AlertManager()
        rule = FailureThresholdRule(threshold=1)
        manager.add_rule(rule)
        rule.record_failure()
        manager.evaluate({})

        assert manager._alerts[0].acknowledged is False
        manager.acknowledge_alert(0)
        assert manager._alerts[0].acknowledged is True

    def test_resolve_alert(self):
        """Test resolving alert."""
        manager = AlertManager()
        rule = FailureThresholdRule(threshold=1)
        manager.add_rule(rule)
        rule.record_failure()
        manager.evaluate({})

        assert manager._alerts[0].resolved is False
        manager.resolve_alert(0)
        assert manager._alerts[0].resolved is True

    def test_get_alert_history(self):
        """Test getting alert history."""
        manager = AlertManager()
        rule1 = FailureThresholdRule(name="rule1", threshold=1)
        rule2 = FailureThresholdRule(name="rule2", threshold=1)
        rule3 = FailureThresholdRule(name="rule3", threshold=1)
        manager.add_rule(rule1)
        manager.add_rule(rule2)
        manager.add_rule(rule3)

        rule1.record_failure()
        manager.evaluate({})

        rule2.record_failure()
        manager.evaluate({})

        rule3.record_failure()
        manager.evaluate({})

        history = manager.get_alert_history(limit=10)
        assert len(history) == 3

    def test_get_active_count(self):
        """Test getting active alert count."""
        manager = AlertManager()
        rule1 = FailureThresholdRule(name="rule1", threshold=1)
        rule2 = FailureThresholdRule(name="rule2", threshold=1)
        manager.add_rule(rule1)
        manager.add_rule(rule2)

        rule1.record_failure()
        manager.evaluate({})

        rule2.record_failure()
        manager.evaluate({})

        assert manager.get_active_count() == 2

    def test_repeated_evaluation_does_not_duplicate_alerts(self):
        """持续越阈值的规则只应产生一条活跃告警，而不是每次评估一条。"""
        manager = AlertManager()
        rule = FailureThresholdRule(name="steady", threshold=1)
        manager.add_rule(rule)

        rule.record_failure()
        manager.evaluate({})
        manager.evaluate({})
        manager.evaluate({})

        assert len(manager.get_alert_history()) == 1
        assert manager.get_active_count() == 1

        # 告警解决后再次越阈值，应能重新告警（不永久静默）。
        manager.resolve_alert(0)
        assert manager.get_active_count() == 0
        rule.record_failure()
        manager.evaluate({})
        assert manager.get_active_count() == 1

    def test_clear_resolved(self):
        """Test clearing resolved alerts."""
        manager = AlertManager()
        rule = FailureThresholdRule(threshold=1)
        manager.add_rule(rule)

        rule.record_failure()
        manager.evaluate({})
        manager.resolve_alert(0)

        cleared = manager.clear_resolved()
        assert cleared == 1
        assert len(manager._alerts) == 0

    def test_on_alert_callback(self):
        """Test alert callback registration."""
        manager = AlertManager()
        callback_called = []

        def callback(alert):
            callback_called.append(alert)

        manager.on_alert(callback)

        rule = FailureThresholdRule(threshold=1)
        manager.add_rule(rule)
        rule.record_failure()
        manager.evaluate({})

        assert len(callback_called) == 1
