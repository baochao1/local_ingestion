"""Subscription management + change notification (MOD-06 / T-203)."""
from __future__ import annotations

from datetime import timedelta

from .models import (
    AggregatedNotification,
    ChangeDetail,
    NotificationOutcome,
    SubscriptionSpec,
    SubscriptionView,
)
from .repository import (
    InMemoryNotificationLogStore,
    InMemorySubscriptionRepository,
    NotificationLogStore,
    SqlNotificationLogStore,
    SqlSubscriptionRepository,
    SubscriptionRepository,
)
from .service import (
    NotificationAggregator,
    Sender,
    SubscriptionService,
)


def build_in_memory_notify_stack(cooldown: timedelta = timedelta(hours=24)):
    """Fully wired in-process notify stack (no database)."""
    repo = InMemorySubscriptionRepository()
    logs = InMemoryNotificationLogStore()
    return (
        SubscriptionService(repo),
        NotificationAggregator(repo, logs, cooldown=cooldown),
        repo,
        logs,
    )


def build_sql_notify_stack(cooldown: timedelta = timedelta(hours=24), session_factory=None):
    """Same wiring as the in-memory stack but persisted to PostgreSQL.

    订阅落在 ``notification_subscription``、发送记录落在 ``notification_log``。
    """
    if session_factory is None:
        from ..storage.session import session_scope

        session_factory = session_scope
    repo = SqlSubscriptionRepository(session_factory)
    logs = SqlNotificationLogStore(session_factory)
    return (
        SubscriptionService(repo),
        NotificationAggregator(repo, logs, cooldown=cooldown),
        repo,
        logs,
    )


__all__ = [
    "AggregatedNotification",
    "ChangeDetail",
    "NotificationOutcome",
    "SubscriptionSpec",
    "SubscriptionView",
    "InMemoryNotificationLogStore",
    "InMemorySubscriptionRepository",
    "NotificationLogStore",
    "SqlNotificationLogStore",
    "SqlSubscriptionRepository",
    "SubscriptionRepository",
    "NotificationAggregator",
    "Sender",
    "SubscriptionService",
    "build_in_memory_notify_stack",
    "build_sql_notify_stack",
]
