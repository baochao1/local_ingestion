"""Webhook notification system for local ingestion workflows."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)


class WebhookEvent(str, Enum):
    """Webhook event types"""

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    ALERT_TRIGGERED = "alert_triggered"


@dataclass
class WebhookPayload:
    """Webhook payload structure"""

    event: WebhookEvent
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    workflow_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert payload to dictionary"""
        return {
            "event": self.event.value,
            "timestamp": self.timestamp,
            "workflow_id": self.workflow_id,
            "data": self.data,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Convert payload to JSON string"""
        return json.dumps(self.to_dict())


@dataclass
class WebhookConfig:
    """Webhook configuration"""

    url: str
    secret: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    retry_count: int = 3
    retry_delay: float = 1.0

    def __post_init__(self) -> None:
        """Validate webhook URL"""
        parsed = urlparse(self.url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid webhook URL: {self.url}")


class WebhookSender:
    """Asynchronous webhook sender with retry support"""

    def __init__(self, config: WebhookConfig):
        """
        Initialize webhook sender.

        Args:
            config: Webhook configuration
        """
        self._config = config
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self._config.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """Close the aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()

    def _generate_signature(self, payload: str) -> str:
        """
        Generate HMAC-SHA256 signature for payload.

        Args:
            payload: JSON payload string

        Returns:
            Hex-encoded signature
        """
        if not self._config.secret:
            raise ValueError("Webhook secret is not configured")
        signature = hmac.new(
            self._config.secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        )
        return f"sha256={signature.hexdigest()}"

    def _prepare_headers(self, payload: str) -> Dict[str, str]:
        """
        Prepare request headers with optional signature.

        Args:
            payload: JSON payload string

        Returns:
            Headers dictionary
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "LocalIngestion-Webhook/1.0",
        }
        headers.update(self._config.headers)

        if self._config.secret:
            headers["X-Webhook-Signature"] = self._generate_signature(payload)

        return headers

    def verify_signature(self, payload: str, signature: str) -> bool:
        """
        Verify webhook signature.

        Args:
            payload: Original payload string
            signature: Signature to verify

        Returns:
            True if signature is valid
        """
        if not self._config.secret:
            return False
        expected = self._generate_signature(payload)
        return hmac.compare_digest(expected, signature)

    async def send(
        self,
        event: WebhookEvent,
        workflow_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Send webhook notification.

        Args:
            event: Webhook event type
            workflow_id: Optional workflow identifier
            data: Optional event data
            metadata: Optional metadata

        Returns:
            True if webhook was sent successfully
        """
        payload = WebhookPayload(
            event=event,
            workflow_id=workflow_id,
            data=data or {},
            metadata=metadata or {},
        )
        payload_json = payload.to_json()
        headers = self._prepare_headers(payload_json)

        last_error: Optional[Exception] = None
        for attempt in range(self._config.retry_count):
            try:
                session = await self._get_session()
                async with session.post(
                    self._config.url,
                    data=payload_json,
                    headers=headers,
                ) as response:
                    if response.status >= 200 and response.status < 300:
                        logger.info(
                            "Webhook sent successfully: event=%s, status=%d",
                            event.value,
                            response.status,
                        )
                        return True
                    else:
                        body = await response.text()
                        logger.warning(
                            "Webhook request failed: event=%s, status=%d, body=%s",
                            event.value,
                            response.status,
                            body[:200],
                        )
                        last_error = Exception(f"HTTP {response.status}: {body[:200]}")

            except aiohttp.ClientError as e:
                logger.warning(
                    "Webhook request error (attempt %d/%d): %s",
                    attempt + 1,
                    self._config.retry_count,
                    str(e),
                )
                last_error = e

            if attempt < self._config.retry_count - 1:
                await asyncio.sleep(self._config.retry_delay * (attempt + 1))

        logger.error(
            "Webhook failed after %d attempts: event=%s, error=%s",
            self._config.retry_count,
            event.value,
            str(last_error),
        )
        return False


class WebhookManager:
    """Manager for multiple webhook senders"""

    def __init__(self):
        self._senders: Dict[str, WebhookSender] = {}
        self._event_handlers: Dict[WebhookEvent, List[Callable]] = {
            event: [] for event in WebhookEvent
        }

    def register(self, name: str, config: WebhookConfig) -> WebhookSender:
        """
        Register a webhook sender.

        Args:
            name: Unique name for the webhook
            config: Webhook configuration

        Returns:
            Registered WebhookSender
        """
        sender = WebhookSender(config)
        self._senders[name] = sender
        return sender

    def unregister(self, name: str) -> bool:
        """
        Unregister a webhook sender.

        Args:
            name: Name of the webhook to unregister

        Returns:
            True if webhook was removed
        """
        if name in self._senders:
            del self._senders[name]
            return True
        return False

    def get(self, name: str) -> Optional[WebhookSender]:
        """
        Get a registered webhook sender.

        Args:
            name: Name of the webhook

        Returns:
            WebhookSender or None if not found
        """
        return self._senders.get(name)

    def subscribe(
        self, event: WebhookEvent, handler: Callable[[WebhookPayload], None]
    ) -> None:
        """
        Subscribe to webhook events.

        Args:
            event: Event type to subscribe to
            handler: Callback handler
        """
        if handler not in self._event_handlers[event]:
            self._event_handlers[event].append(handler)

    def unsubscribe(
        self, event: WebhookEvent, handler: Callable[[WebhookPayload], None]
    ) -> None:
        """
        Unsubscribe from webhook events.

        Args:
            event: Event type to unsubscribe from
            handler: Callback handler to remove
        """
        if handler in self._event_handlers[event]:
            self._event_handlers[event].remove(handler)

    async def broadcast(
        self,
        event: WebhookEvent,
        workflow_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, bool]:
        """
        Broadcast webhook to all registered senders.

        Args:
            event: Webhook event type
            workflow_id: Optional workflow identifier
            data: Optional event data
            metadata: Optional metadata

        Returns:
            Dictionary mapping sender names to success status
        """
        payload = WebhookPayload(
            event=event,
            workflow_id=workflow_id,
            data=data or {},
            metadata=metadata or {},
        )

        results = {}
        for name, sender in self._senders.items():
            try:
                success = await sender.send(
                    event=event,
                    workflow_id=workflow_id,
                    data=data,
                    metadata=metadata,
                )
                results[name] = success
            except Exception as e:
                logger.error("Failed to send webhook to %s: %s", name, str(e))
                results[name] = False

        for handler in self._event_handlers[event]:
            try:
                handler(payload)
            except Exception as e:
                logger.error("Event handler failed: %s", str(e))

        return results

    async def close_all(self) -> None:
        """Close all webhook sessions"""
        for sender in self._senders.values():
            await sender.close()
        self._senders.clear()
