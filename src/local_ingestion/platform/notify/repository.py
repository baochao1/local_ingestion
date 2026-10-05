"""Subscription + notification-log repositories (MOD-06 / T-203).

Two implementations share the interfaces: an in-memory one for unit tests and
the MVP, plus a SQLAlchemy one backed by ``notification_subscription`` /
``notification_log`` (DDL landed for this module).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Protocol

from .models import SubscriptionSpec, SubscriptionView


class SubscriptionRepository(Protocol):
    def create(self, spec: SubscriptionSpec) -> SubscriptionView: ...
    def list(self) -> List[SubscriptionView]: ...
    def list_enabled(self) -> List[SubscriptionView]: ...
    def get(self, sub_id: int) -> Optional[SubscriptionView]: ...
    def delete(self, sub_id: int) -> bool: ...
    def set_enabled(self, sub_id: int, enabled: bool) -> None: ...


def _view(m) -> SubscriptionView:
    return SubscriptionView(
        id=m.id, subscriber=m.subscriber, scope_type=m.scope_type,
        scope_fqn=m.scope_fqn, datasource_id=m.datasource_id,
        min_severity=m.min_severity, channel=m.channel, enabled=m.enabled,
        created_at=m.created_at,
    )


class InMemorySubscriptionRepository:
    def __init__(self) -> None:
        self._rows: List[SubscriptionView] = []
        self._seq = 1

    def create(self, spec: SubscriptionSpec) -> SubscriptionView:
        v = SubscriptionView(
            id=self._seq, subscriber=spec.subscriber, scope_type=spec.scope_type,
            scope_fqn=spec.scope_fqn, datasource_id=spec.datasource_id,
            min_severity=spec.min_severity, channel=spec.channel, enabled=spec.enabled,
        )
        self._seq += 1
        self._rows.append(v)
        return v

    def list(self) -> List[SubscriptionView]:
        return list(self._rows)

    def list_enabled(self) -> List[SubscriptionView]:
        return [r for r in self._rows if r.enabled]

    def get(self, sub_id: int) -> Optional[SubscriptionView]:
        return next((r for r in self._rows if r.id == sub_id), None)

    def delete(self, sub_id: int) -> bool:
        before = len(self._rows)
        self._rows = [r for r in self._rows if r.id != sub_id]
        return len(self._rows) < before

    def set_enabled(self, sub_id: int, enabled: bool) -> None:
        r = self.get(sub_id)
        if r:
            r.enabled = enabled


class SqlSubscriptionRepository:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def create(self, spec: SubscriptionSpec) -> SubscriptionView:
        from ..storage.models_ops import NotificationSubscription

        with self._sf() as s:
            m = NotificationSubscription(
                subscriber=spec.subscriber, scope_type=spec.scope_type,
                scope_fqn=spec.scope_fqn, datasource_id=spec.datasource_id,
                min_severity=spec.min_severity, channel=spec.channel,
                channel_conf=spec.channel_conf, enabled=spec.enabled,
            )
            s.add(m)
            s.commit()
            s.refresh(m)
            return _view(m)

    def list(self) -> List[SubscriptionView]:
        from ..storage.models_ops import NotificationSubscription

        with self._sf() as s:
            return [_view(m) for m in s.query(NotificationSubscription).all()]

    def list_enabled(self) -> List[SubscriptionView]:
        from ..storage.models_ops import NotificationSubscription

        with self._sf() as s:
            return [_view(m) for m in
                    s.query(NotificationSubscription)
                    .filter(NotificationSubscription.enabled.is_(True)).all()]

    def get(self, sub_id: int) -> Optional[SubscriptionView]:
        from ..storage.models_ops import NotificationSubscription

        with self._sf() as s:
            m = s.get(NotificationSubscription, sub_id)
            return _view(m) if m else None

    def delete(self, sub_id: int) -> bool:
        from ..storage.models_ops import NotificationSubscription

        with self._sf() as s:
            m = s.get(NotificationSubscription, sub_id)
            if not m:
                return False
            s.delete(m)
            s.commit()
            return True

    def set_enabled(self, sub_id: int, enabled: bool) -> None:
        from ..storage.models_ops import NotificationSubscription

        with self._sf() as s:
            m = s.get(NotificationSubscription, sub_id)
            if m:
                m.enabled = enabled
                s.commit()


class NotificationLogStore(Protocol):
    def recent(self, subscription_id: int, change_id: int, since: datetime) -> bool: ...
    def record(self, subscription_id: int, change_id: int, channel: str,
               status: str, error: Optional[str] = None) -> None: ...


class InMemoryNotificationLogStore:
    def __init__(self) -> None:
        # (subscription_id, change_id, sent_at, channel, status, error)
        self._rows: List[tuple] = []

    def recent(self, subscription_id: int, change_id: int, since: datetime) -> bool:
        return any(
            r[0] == subscription_id and r[1] == change_id and r[2] >= since
            for r in self._rows
        )

    def record(self, subscription_id: int, change_id: int, channel: str,
               status: str, error: Optional[str] = None) -> None:
        from datetime import datetime as _dt

        self._rows.append((subscription_id, change_id, _dt.now(), channel, status, error))


class SqlNotificationLogStore:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def recent(self, subscription_id: int, change_id: int, since: datetime) -> bool:
        from ..storage.models_ops import NotificationLog

        with self._sf() as s:
            cnt = s.query(NotificationLog).filter(
                NotificationLog.subscription_id == subscription_id,
                NotificationLog.change_id == change_id,
                NotificationLog.created_at >= since,
            ).count()
            return cnt > 0

    def record(self, subscription_id: int, change_id: int, channel: str,
               status: str, error: Optional[str] = None) -> None:
        from ..storage.models_ops import NotificationLog

        with self._sf() as s:
            s.add(NotificationLog(
                subscription_id=subscription_id, change_id=change_id,
                channel=channel, status=status, error_message=error,
            ))
            s.commit()
