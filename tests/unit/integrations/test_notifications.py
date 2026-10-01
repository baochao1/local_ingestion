"""Unit tests for notifications module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from local_ingestion.integrations.notifications import (
    EmailChannel,
    EmailConfig,
    NotificationService,
    SlackChannel,
    SlackConfig,
)
from local_ingestion.integrations.webhook import WebhookEvent


class TestEmailConfig:
    """Tests for EmailConfig"""

    def test_config_defaults(self):
        """Test email config defaults"""
        config = EmailConfig(
            smtp_host="mail.example.com",
            to_addresses=["test@example.com"],
        )
        assert config.smtp_host == "mail.example.com"
        assert config.enabled is True
        assert config.smtp_port == 587
        assert config.smtp_tls is True

    def test_config_with_auth(self):
        """Test email config with authentication"""
        config = EmailConfig(
            smtp_host="mail.example.com",
            smtp_user="user",
            smtp_password="secret",
            to_addresses=["test@example.com"],
        )
        assert config.smtp_user == "user"
        assert config.smtp_password == "secret"


class TestEmailChannel:
    """Tests for EmailChannel"""

    @pytest.fixture
    def config(self):
        """Create test config"""
        return EmailConfig(
            smtp_host="localhost",
            to_addresses=["recipient@example.com"],
        )

    @pytest.fixture
    def channel(self, config):
        """Create test channel"""
        return EmailChannel(config)

    def test_render_template(self, channel):
        """Test template rendering"""
        channel._config.templates["html"] = "<p>${message}</p>"
        result = channel.render_template("html", {"message": "Hello"})
        assert result == "<p>Hello</p>"

    def test_render_template_missing(self, channel):
        """Test template rendering with missing template"""
        result = channel.render_template("nonexistent", {"message": "Hello"})
        assert result == "{message}"

    @pytest.mark.asyncio
    async def test_send_no_recipients(self, channel):
        """Test sending with no recipients"""
        channel._email_config.to_addresses = []
        result = await channel.send("Test", "Message")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self, channel):
        """Test successful email send"""
        with patch.object(channel, "_send_smtp", new_callable=AsyncMock):
            result = await channel.send("Test Subject", "Test Message")
            assert result is True

    def test_channel_enabled(self, channel):
        """Test channel enabled property"""
        assert channel.enabled is True
        channel._config.enabled = False
        assert channel.enabled is False


class TestSlackConfig:
    """Tests for SlackConfig"""

    def test_config_defaults(self):
        """Test Slack config defaults"""
        config = SlackConfig(webhook_url="https://hooks.slack.com/test")
        assert config.webhook_url == "https://hooks.slack.com/test"
        assert config.username == "Local Ingestion Bot"
        assert config.icon_emoji == ":robot_face:"
        assert config.enabled is True


class TestSlackChannel:
    """Tests for SlackChannel"""

    @pytest.fixture
    def config(self):
        """Create test config"""
        return SlackConfig(
            webhook_url="https://hooks.slack.com/services/test",
            channel="#alerts",
        )

    @pytest.fixture
    def channel(self, config):
        """Create test channel"""
        return SlackChannel(config)

    def test_format_slack_message_info(self, channel):
        """Test formatting info level message"""
        payload = channel._format_slack_message(
            "Test Title",
            "Test message content",
            level="info",
        )
        assert payload["channel"] == "#alerts"
        assert len(payload["blocks"]) == 2

    def test_format_slack_message_with_context(self, channel):
        """Test formatting message with context"""
        payload = channel._format_slack_message(
            "Workflow Status",
            "Workflow completed",
            level="success",
            context={"workflow_id": "wf-123", "duration": "5s"},
        )
        assert len(payload["blocks"]) == 3

    def test_format_slack_message_error(self, channel):
        """Test formatting error level message"""
        payload = channel._format_slack_message(
            "Error",
            "Something went wrong",
            level="error",
        )
        assert ":x:" in payload["blocks"][0]["text"]["text"]

    @pytest.mark.asyncio
    async def test_send_no_webhook_url(self, channel):
        """Test sending with no webhook URL"""
        channel._slack_config.webhook_url = ""
        result = await channel.send("Test", "Message")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self, channel):
        """Test successful Slack send"""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response

        with patch.object(channel, "_get_session", AsyncMock(return_value=mock_session)):
            result = await channel.send("Test", "Message")
            assert result is True

    @pytest.mark.asyncio
    async def test_send_failure(self, channel):
        """Test failed Slack send"""
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="invalid_payload")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock()

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response

        with patch.object(channel, "_get_session", AsyncMock(return_value=mock_session)):
            result = await channel.send("Test", "Message")
            assert result is False

    @pytest.mark.asyncio
    async def test_close(self, channel):
        """Test closing channel"""
        channel._session = MagicMock()
        channel._session.closed = False
        channel._session.close = AsyncMock()

        await channel.close()
        channel._session.close.assert_called_once()


class TestNotificationService:
    """Tests for NotificationService"""

    @pytest.fixture
    def service(self):
        """Create test service"""
        return NotificationService()

    def test_register_channel(self, service):
        """Test registering a notification channel"""
        config = EmailConfig(smtp_host="localhost", to_addresses=[])
        channel = EmailChannel(config)
        service.register_channel("email", channel)
        assert service.get_channel("email") is channel

    def test_unregister_channel(self, service):
        """Test unregistering a channel"""
        config = EmailConfig(smtp_host="localhost", to_addresses=[])
        channel = EmailChannel(config)
        service.register_channel("email", channel)
        assert service.unregister_channel("email") is True
        assert service.get_channel("email") is None

    def test_get_nonexistent_channel(self, service):
        """Test getting nonexistent channel"""
        assert service.get_channel("nonexistent") is None

    @pytest.mark.asyncio
    async def test_notify_specific_channels(self, service):
        """Test notifying specific channels only"""
        email_config = EmailConfig(smtp_host="localhost", to_addresses=["test@example.com"])
        email_channel = EmailChannel(email_config)
        service.register_channel("email", email_channel)

        slack_config = SlackConfig(webhook_url="https://hooks.slack.com/test")
        slack_channel = SlackChannel(slack_config)
        service.register_channel("slack", slack_channel)

        with patch.object(email_channel, "send", new_callable=AsyncMock) as mock_email:
            with patch.object(slack_channel, "send", new_callable=AsyncMock) as mock_slack:
                mock_email.return_value = True
                mock_slack.return_value = True

                results = await service.notify(
                    "Test",
                    "Message",
                    channels=["email"],
                )
                assert "email" in results
                assert "slack" not in results

    @pytest.mark.asyncio
    async def test_notify_disabled_channel(self, service):
        """Test that disabled channels are skipped"""
        email_config = EmailConfig(smtp_host="localhost", to_addresses=["test@example.com"])
        email_config.enabled = False
        email_channel = EmailChannel(email_config)
        service.register_channel("email", email_channel)

        results = await service.notify("Test", "Message", channels=["email"])
        assert results["email"] is True

    @pytest.mark.asyncio
    async def test_notify_workflow_event(self, service):
        """Test workflow event notification"""
        email_config = EmailConfig(smtp_host="localhost", to_addresses=["test@example.com"])
        email_channel = EmailChannel(email_config)
        service.register_channel("email", email_channel)

        with patch.object(email_channel, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            results = await service.notify_workflow_event(
                event=WebhookEvent.WORKFLOW_COMPLETED,
                workflow_id="wf-123",
                status="completed",
                message="Workflow finished successfully",
            )
            assert results["email"] is True
            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_all(self, service):
        """Test closing all channels"""
        slack_config = SlackConfig(webhook_url="https://hooks.slack.com/test")
        slack_channel = SlackChannel(slack_config)
        service.register_channel("slack", slack_channel)

        slack_channel._session = MagicMock()
        slack_channel._session.closed = False
        slack_channel._session.close = AsyncMock()

        await service.close_all()
        assert len(service._channels) == 0
