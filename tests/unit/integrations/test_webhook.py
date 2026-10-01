"""Unit tests for webhook module."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from local_ingestion.integrations.webhook import (
    WebhookConfig,
    WebhookEvent,
    WebhookManager,
    WebhookPayload,
    WebhookSender,
)


class TestWebhookPayload:
    """Tests for WebhookPayload"""

    def test_payload_creation(self):
        """Test creating a webhook payload"""
        payload = WebhookPayload(
            event=WebhookEvent.WORKFLOW_STARTED,
            workflow_id="wf-123",
            data={"message": "test"},
        )
        assert payload.event == WebhookEvent.WORKFLOW_STARTED
        assert payload.workflow_id == "wf-123"
        assert payload.data["message"] == "test"
        assert payload.timestamp is not None

    def test_payload_to_dict(self):
        """Test converting payload to dictionary"""
        payload = WebhookPayload(
            event=WebhookEvent.WORKFLOW_COMPLETED,
            workflow_id="wf-456",
            data={"status": "success"},
            metadata={"key": "value"},
        )
        data = payload.to_dict()
        assert data["event"] == "workflow_completed"
        assert data["workflow_id"] == "wf-456"
        assert data["data"]["status"] == "success"
        assert data["metadata"]["key"] == "value"

    def test_payload_to_json(self):
        """Test converting payload to JSON"""
        payload = WebhookPayload(
            event=WebhookEvent.WORKFLOW_FAILED,
            workflow_id="wf-789",
        )
        json_str = payload.to_json()
        assert '"event": "workflow_failed"' in json_str
        assert '"workflow_id": "wf-789"' in json_str


class TestWebhookConfig:
    """Tests for WebhookConfig"""

    def test_config_creation(self):
        """Test creating webhook config"""
        config = WebhookConfig(
            url="https://example.com/webhook",
            secret="my-secret",
            timeout=60,
        )
        assert config.url == "https://example.com/webhook"
        assert config.secret == "my-secret"
        assert config.timeout == 60

    def test_config_invalid_url(self):
        """Test that invalid URL raises error"""
        with pytest.raises(ValueError, match="Invalid webhook URL"):
            WebhookConfig(url="not-a-valid-url")


class TestWebhookSender:
    """Tests for WebhookSender"""

    @pytest.fixture
    def config(self):
        """Create test config"""
        return WebhookConfig(
            url="https://example.com/webhook",
            secret="test-secret",
            retry_count=1,
        )

    @pytest.fixture
    def sender(self, config):
        """Create test sender"""
        return WebhookSender(config)

    def test_signature_generation(self, sender):
        """Test HMAC-SHA256 signature generation"""
        payload = '{"event": "test"}'
        signature = sender._generate_signature(payload)
        assert signature.startswith("sha256=")
        assert len(signature) == 71

    def test_verify_signature_valid(self, sender):
        """Test verifying valid signature"""
        payload = '{"event": "test"}'
        signature = sender._generate_signature(payload)
        assert sender.verify_signature(payload, signature) is True

    def test_verify_signature_invalid(self, sender):
        """Test verifying invalid signature"""
        payload = '{"event": "test"}'
        assert sender.verify_signature(payload, "sha256=invalid") is False

    def test_verify_signature_no_secret(self):
        """Test verifying without secret configured"""
        config = WebhookConfig(url="https://example.com/webhook")
        sender = WebhookSender(config)
        assert sender.verify_signature("{}", "sha256=abc") is False

    def test_prepare_headers(self, sender):
        """Test preparing request headers"""
        payload = '{"event": "test"}'
        headers = sender._prepare_headers(payload)
        assert headers["Content-Type"] == "application/json"
        assert "X-Webhook-Signature" in headers
        assert headers["User-Agent"] == "LocalIngestion-Webhook/1.0"

    def test_prepare_headers_no_secret(self):
        """Test preparing headers without secret"""
        config = WebhookConfig(url="https://example.com/webhook")
        sender = WebhookSender(config)
        headers = sender._prepare_headers('{"event": "test"}')
        assert "X-Webhook-Signature" not in headers

    @pytest.mark.asyncio
    async def test_send_success(self, sender):
        """Test successful webhook send"""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response

        with patch.object(sender, "_get_session", AsyncMock(return_value=mock_session)):
            result = await sender.send(
                event=WebhookEvent.WORKFLOW_COMPLETED,
                workflow_id="wf-123",
                data={"status": "ok"},
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_send_failure(self, sender):
        """Test failed webhook send"""
        mock_response = AsyncMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Internal Server Error")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response

        with patch.object(sender, "_get_session", AsyncMock(return_value=mock_session)):
            result = await sender.send(
                event=WebhookEvent.WORKFLOW_FAILED,
                workflow_id="wf-123",
            )
            assert result is False


class TestWebhookManager:
    """Tests for WebhookManager"""

    @pytest.fixture
    def manager(self):
        """Create test manager"""
        return WebhookManager()

    @pytest.fixture
    def config(self):
        """Create test config"""
        return WebhookConfig(url="https://example.com/webhook")

    def test_register_webhook(self, manager, config):
        """Test registering a webhook"""
        sender = manager.register("test-webhook", config)
        assert sender is not None
        assert manager.get("test-webhook") is sender

    def test_unregister_webhook(self, manager, config):
        """Test unregistering a webhook"""
        manager.register("test-webhook", config)
        assert manager.unregister("test-webhook") is True
        assert manager.get("test-webhook") is None

    def test_unregister_nonexistent(self, manager):
        """Test unregistering nonexistent webhook"""
        assert manager.unregister("nonexistent") is False

    def test_subscribe_handler(self, manager):
        """Test subscribing to events"""
        handler = MagicMock()
        manager.subscribe(WebhookEvent.WORKFLOW_STARTED, handler)
        manager.subscribe(WebhookEvent.WORKFLOW_COMPLETED, handler)

    def test_unsubscribe_handler(self, manager):
        """Test unsubscribing from events"""
        handler = MagicMock()
        manager.subscribe(WebhookEvent.WORKFLOW_STARTED, handler)
        manager.unsubscribe(WebhookEvent.WORKFLOW_STARTED, handler)

    @pytest.mark.asyncio
    async def test_broadcast(self, manager, config):
        """Test broadcasting to multiple webhooks"""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response

        sender1 = manager.register("webhook1", config)
        sender2 = manager.register("webhook2", config)

        with patch.object(WebhookSender, "_get_session", AsyncMock(return_value=mock_session)):
            results = await manager.broadcast(
                event=WebhookEvent.WORKFLOW_COMPLETED,
                workflow_id="wf-123",
            )
            assert len(results) == 2


class TestWebhookEvent:
    """Tests for WebhookEvent enum"""

    def test_event_values(self):
        """Test webhook event values"""
        assert WebhookEvent.WORKFLOW_STARTED.value == "workflow_started"
        assert WebhookEvent.WORKFLOW_COMPLETED.value == "workflow_completed"
        assert WebhookEvent.WORKFLOW_FAILED.value == "workflow_failed"
        assert WebhookEvent.ALERT_TRIGGERED.value == "alert_triggered"

    def test_event_count(self):
        """Test number of event types"""
        assert len(WebhookEvent) == 4
