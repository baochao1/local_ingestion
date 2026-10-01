"""Integration modules for local ingestion.

This package provides webhook notifications, notification channels,
and a plugin system for extending local ingestion capabilities.
"""

from local_ingestion.integrations.notifications import (
    EmailChannel,
    EmailConfig,
    NotificationChannel,
    NotificationConfig,
    NotificationService,
    SlackChannel,
    SlackConfig,
)
from local_ingestion.integrations.plugins import (
    CustomConnectorPlugin,
    PluginError,
    PluginInterface,
    PluginLoadError,
    PluginManager,
    PluginMetadata,
    PluginNotFoundError,
)
from local_ingestion.integrations.webhook import (
    WebhookConfig,
    WebhookEvent,
    WebhookManager,
    WebhookPayload,
    WebhookSender,
)

__all__ = [
    # Webhook
    "WebhookEvent",
    "WebhookPayload",
    "WebhookConfig",
    "WebhookSender",
    "WebhookManager",
    # Notifications
    "NotificationConfig",
    "NotificationChannel",
    "EmailConfig",
    "EmailChannel",
    "SlackConfig",
    "SlackChannel",
    "NotificationService",
    # Plugins
    "PluginInterface",
    "PluginMetadata",
    "PluginManager",
    "PluginError",
    "PluginLoadError",
    "PluginNotFoundError",
    "CustomConnectorPlugin",
]
