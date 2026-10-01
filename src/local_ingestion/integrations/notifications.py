"""Notification channels for local ingestion workflows."""

from __future__ import annotations

import logging
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from string import Template
from typing import Any, Dict, List, Optional

import aiohttp

from local_ingestion.integrations.webhook import WebhookEvent, WebhookPayload

logger = logging.getLogger(__name__)


@dataclass
class NotificationConfig:
    """Base notification configuration"""

    enabled: bool = True
    templates: Dict[str, str] = field(default_factory=dict)


@dataclass
class EmailConfig(NotificationConfig):
    """Email notification configuration"""

    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_tls: bool = True
    from_address: str = "noreply@localingestion"
    to_addresses: List[str] = field(default_factory=list)


@dataclass
class SlackConfig(NotificationConfig):
    """Slack notification configuration"""

    webhook_url: str = ""
    channel: Optional[str] = None
    username: str = "Local Ingestion Bot"
    icon_emoji: str = ":robot_face:"


class NotificationChannel(ABC):
    """Abstract base class for notification channels"""

    def __init__(self, config: NotificationConfig):
        """
        Initialize notification channel.

        Args:
            config: Channel configuration
        """
        self._config = config

    @property
    def enabled(self) -> bool:
        """Check if channel is enabled"""
        return self._config.enabled

    @abstractmethod
    async def send(
        self,
        title: str,
        message: str,
        level: str = "info",
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send notification.

        Args:
            title: Notification title
            message: Notification message
            level: Notification level (info, warning, error)
            context: Optional context data

        Returns:
            True if notification was sent successfully
        """
        raise NotImplementedError

    def render_template(self, template_key: str, context: Dict[str, Any]) -> str:
        """
        Render a notification template.

        Args:
            template_key: Key of the template to render
            context: Template context data

        Returns:
            Rendered template string
        """
        template_str = self._config.templates.get(template_key, "{message}")
        try:
            template = Template(template_str)
            return template.safe_substitute(context)
        except Exception as e:
            logger.warning("Template rendering failed: %s", str(e))
            return template_str


class EmailChannel(NotificationChannel):
    """Email notification channel using SMTP"""

    def __init__(self, config: EmailConfig):
        """
        Initialize email channel.

        Args:
            config: Email configuration
        """
        super().__init__(config)
        self._email_config = config

    async def send(
        self,
        title: str,
        message: str,
        level: str = "info",
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send email notification.

        Args:
            title: Email subject
            message: Email body
            level: Notification level (info, warning, error)
            context: Optional context data

        Returns:
            True if email was sent successfully
        """
        if not self._email_config.to_addresses:
            logger.warning("No recipient addresses configured for email")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = title
            msg["From"] = self._email_config.from_address
            msg["To"] = ", ".join(self._email_config.to_addresses)

            context_with_level = {**(context or {}), "level": level}
            html_content = self.render_template("html", context_with_level)
            text_content = self.render_template("text", context_with_level)

            if html_content:
                msg.attach(MIMEText(html_content, "html"))
            else:
                msg.attach(MIMEText(message, "plain"))

            if text_content and html_content:
                msg.attach(MIMEText(text_content, "plain"))

            await self._send_smtp(msg)
            logger.info("Email sent successfully: %s", title)
            return True

        except Exception as e:
            logger.error("Failed to send email: %s", str(e))
            return False

    async def _send_smtp(self, msg: MIMEMultipart) -> None:
        """Send email via SMTP"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._smtp_send, msg)

    def _smtp_send(self, msg: MIMEMultipart) -> None:
        """Synchronous SMTP send"""
        with smtplib.SMTP(
            self._email_config.smtp_host,
            self._email_config.smtp_port,
        ) as server:
            if self._email_config.smtp_tls:
                server.starttls()

            if self._email_config.smtp_user and self._email_config.smtp_password:
                server.login(
                    self._email_config.smtp_user,
                    self._email_config.smtp_password,
                )

            server.send_message(msg)


class SlackChannel(NotificationChannel):
    """Slack notification channel using webhook API"""

    def __init__(self, config: SlackConfig):
        """
        Initialize Slack channel.

        Args:
            config: Slack configuration
        """
        super().__init__(config)
        self._slack_config = config
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()

    def _format_slack_message(
        self,
        title: str,
        message: str,
        level: str = "info",
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Format message for Slack.

        Args:
            title: Message title
            message: Message content
            level: Notification level
            context: Optional context data

        Returns:
            Slack message payload
        """
        level_emoji = {
            "info": ":information_source:",
            "warning": ":warning:",
            "error": ":x:",
            "success": ":white_check_mark:",
        }.get(level, ":speech_balloon:")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{level_emoji} {title}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message,
                },
            },
        ]

        if context:
            fields = []
            for key, value in context.items():
                if value is not None:
                    fields.append(
                        {
                            "type": "mrkdwn",
                            "text": f"*{key}:*\n{value}",
                        }
                    )
            if fields:
                blocks.append(
                    {
                        "type": "section",
                        "fields": fields,
                    }
                )

        return {
            "username": self._slack_config.username,
            "icon_emoji": self._slack_config.icon_emoji,
            "channel": self._slack_config.channel,
            "blocks": blocks,
        }

    async def send(
        self,
        title: str,
        message: str,
        level: str = "info",
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send Slack notification.

        Args:
            title: Message title
            message: Message content
            level: Notification level (info, warning, error)
            context: Optional context data

        Returns:
            True if message was sent successfully
        """
        if not self._slack_config.webhook_url:
            logger.warning("Slack webhook URL not configured")
            return False

        try:
            payload = self._format_slack_message(title, message, level, context)
            session = await self._get_session()

            async with session.post(
                self._slack_config.webhook_url,
                json=payload,
            ) as response:
                if response.status == 200:
                    logger.info("Slack message sent successfully: %s", title)
                    return True
                else:
                    body = await response.text()
                    logger.error(
                        "Slack API error: status=%d, body=%s",
                        response.status,
                        body,
                    )
                    return False

        except Exception as e:
            logger.error("Failed to send Slack message: %s", str(e))
            return False


class NotificationService:
    """Service for managing notification channels"""

    def __init__(self):
        self._channels: Dict[str, NotificationChannel] = {}

    def register_channel(
        self, name: str, channel: NotificationChannel
    ) -> None:
        """
        Register a notification channel.

        Args:
            name: Unique channel name
            channel: Notification channel instance
        """
        self._channels[name] = channel

    def unregister_channel(self, name: str) -> bool:
        """
        Unregister a notification channel.

        Args:
            name: Channel name to remove

        Returns:
            True if channel was removed
        """
        if name in self._channels:
            del self._channels[name]
            return True
        return False

    def get_channel(self, name: str) -> Optional[NotificationChannel]:
        """
        Get a registered channel.

        Args:
            name: Channel name

        Returns:
            NotificationChannel or None
        """
        return self._channels.get(name)

    async def notify(
        self,
        title: str,
        message: str,
        level: str = "info",
        context: Optional[Dict[str, Any]] = None,
        channels: Optional[List[str]] = None,
    ) -> Dict[str, bool]:
        """
        Send notification through specified channels.

        Args:
            title: Notification title
            message: Notification message
            level: Notification level
            context: Optional context data
            channels: Optional list of channel names (None = all)

        Returns:
            Dictionary mapping channel names to success status
        """
        results = {}
        target_channels = (
            channels if channels is not None else list(self._channels.keys())
        )

        for name in target_channels:
            channel = self._channels.get(name)
            if channel is None:
                logger.warning("Channel not found: %s", name)
                results[name] = False
                continue

            if not channel.enabled:
                logger.debug("Channel disabled: %s", name)
                results[name] = True
                continue

            try:
                success = await channel.send(title, message, level, context)
                results[name] = success
            except Exception as e:
                logger.error("Notification failed for %s: %s", name, str(e))
                results[name] = False

        return results

    async def notify_workflow_event(
        self,
        event: WebhookEvent,
        workflow_id: str,
        status: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, bool]:
        """
        Send notification for workflow event.

        Args:
            event: Webhook event type
            workflow_id: Workflow identifier
            status: Workflow status
            message: Status message
            context: Optional context data

        Returns:
            Dictionary mapping channel names to success status
        """
        level_map = {
            WebhookEvent.WORKFLOW_STARTED: "info",
            WebhookEvent.WORKFLOW_COMPLETED: "success",
            WebhookEvent.WORKFLOW_FAILED: "error",
            WebhookEvent.ALERT_TRIGGERED: "warning",
        }
        level = level_map.get(event, "info")

        title = f"Workflow {status}: {workflow_id}"
        full_context = {
            "workflow_id": workflow_id,
            "status": status,
            "event": event.value,
            **(context or {}),
        }

        return await self.notify(title, message, level, full_context)

    async def close_all(self) -> None:
        """Close all channel resources"""
        for channel in self._channels.values():
            if hasattr(channel, "close"):
                await channel.close()
        self._channels.clear()


import asyncio
