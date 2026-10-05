"""Change-event repositories (MOD-06 / T-204).

Two implementations share the interface: an in-memory one for unit tests / the
MVP, plus a SQLAlchemy one backed by the ``change_event`` table (DDL + ORM landed).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol

from .models import ACK_CLOSED, ACK_PENDING, ChangeEventInput, ChangeEventView


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a naive datetime to UTC-aware (PG stores ``timestamptz`` as UTC)."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


class ChangeRepository(Protocol):
    def add(self, inp: ChangeEventInput) -> ChangeEventView: ...
    def get(self, change_id: int) -> Optional[ChangeEventView]: ...
    def list(self, *, severity=None, datasource_id=None, entity_type=None,
             entity_fqn=None, ack_status=None, since=None, until=None,
             limit: int = 50, offset: int = 0) -> List[ChangeEventView]: ...
    def windowed(self, since: datetime, until: datetime) -> List[ChangeEventView]: ...
    def get_history(self, entity_type: str, entity_fqn: str,
                    limit: int = 50) -> List[ChangeEventView]: ...
    def set_ack(self, change_id: int, action: str, actor: str, at: datetime) -> None: ...


def _view(m) -> ChangeEventView:
    return ChangeEventView(
        id=m.id, detected_at=m.detected_at, scan_run_id=m.scan_run_id,
        datasource_id=m.datasource_id, entity_type=m.entity_type, entity_id=m.entity_id,
        entity_fqn=m.entity_fqn, change_type=m.change_type, severity=m.severity,
        before_json=m.before_json, after_json=m.after_json, notified=m.notified,
        ack_status=m.ack_status, ack_action=m.ack_action, ack_by=m.ack_by, ack_at=m.ack_at,
    )


class InMemoryChangeRepository:
    def __init__(self) -> None:
        self._rows: List[ChangeEventView] = []
        self._seq = 1

    def add(self, inp: ChangeEventInput) -> ChangeEventView:
        dt = inp.detected_at or datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ev = ChangeEventView(
            id=self._seq, detected_at=dt,
            scan_run_id=inp.scan_run_id, datasource_id=inp.datasource_id,
            entity_type=inp.entity_type, entity_id=inp.entity_id, entity_fqn=inp.entity_fqn,
            change_type=inp.change_type, severity=inp.severity,
            before_json=inp.before_json, after_json=inp.after_json, notified=False,
            ack_status=ACK_PENDING, ack_action=None, ack_by=None, ack_at=None,
        )
        self._seq += 1
        self._rows.append(ev)
        return ev

    def get(self, change_id: int) -> Optional[ChangeEventView]:
        return next((r for r in self._rows if r.id == change_id), None)

    def _matches(self, e, *, severity, datasource_id, entity_type, entity_fqn,
                 ack_status, since, until) -> bool:
        if severity and e.severity != severity:
            return False
        if datasource_id is not None and e.datasource_id != datasource_id:
            return False
        if entity_type and e.entity_type != entity_type:
            return False
        if entity_fqn and e.entity_fqn != entity_fqn:
            return False
        if ack_status and e.ack_status != ack_status:
            return False
        if since and e.detected_at < _aware(since):
            return False
        if until and e.detected_at > _aware(until):
            return False
        return True

    def list(self, *, severity=None, datasource_id=None, entity_type=None,
             entity_fqn=None, ack_status=None, since=None, until=None,
             limit: int = 50, offset: int = 0) -> List[ChangeEventView]:
        f = [e for e in self._rows if self._matches(
            e, severity=severity, datasource_id=datasource_id, entity_type=entity_type,
            entity_fqn=entity_fqn, ack_status=ack_status, since=since, until=until)]
        return f[offset:offset + limit]

    def windowed(self, since: datetime, until: datetime) -> List[ChangeEventView]:
        lo, hi = _aware(since), _aware(until)
        return [e for e in self._rows if lo <= e.detected_at <= hi]

    def get_history(self, entity_type: str, entity_fqn: str,
                    limit: int = 50) -> List[ChangeEventView]:
        f = [e for e in self._rows if e.entity_type == entity_type and e.entity_fqn == entity_fqn]
        f.sort(key=lambda x: x.detected_at, reverse=True)
        return f[:limit]

    def set_ack(self, change_id: int, action: str, actor: str, at: datetime) -> None:
        e = self.get(change_id)
        if e:
            e.ack_status = ACK_CLOSED
            e.ack_action = action
            e.ack_by = actor
            e.ack_at = at


class SqlChangeRepository:
    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def add(self, inp: ChangeEventInput) -> ChangeEventView:
        from ..storage.models_ops import ChangeEvent

        with self._sf() as s:
            m = ChangeEvent(
                entity_type=inp.entity_type, change_type=inp.change_type, severity=inp.severity,
                entity_fqn=inp.entity_fqn, datasource_id=inp.datasource_id, entity_id=inp.entity_id,
                scan_run_id=inp.scan_run_id, before_json=inp.before_json, after_json=inp.after_json,
                detected_at=inp.detected_at or datetime.now(timezone.utc),
            )
            s.add(m)
            s.commit()
            s.refresh(m)
            return _view(m)

    def get(self, change_id: int) -> Optional[ChangeEventView]:
        from ..storage.models_ops import ChangeEvent

        with self._sf() as s:
            m = (
                s.query(ChangeEvent)
                .filter(ChangeEvent.id == change_id)
                .first()
            )
            return _view(m) if m else None

    def list(self, *, severity=None, datasource_id=None, entity_type=None,
             entity_fqn=None, ack_status=None, since=None, until=None,
             limit: int = 50, offset: int = 0) -> List[ChangeEventView]:
        from ..storage.models_ops import ChangeEvent

        with self._sf() as s:
            q = s.query(ChangeEvent)
            if severity:
                q = q.filter(ChangeEvent.severity == severity)
            if datasource_id is not None:
                q = q.filter(ChangeEvent.datasource_id == datasource_id)
            if entity_type:
                q = q.filter(ChangeEvent.entity_type == entity_type)
            if entity_fqn:
                q = q.filter(ChangeEvent.entity_fqn == entity_fqn)
            if ack_status:
                q = q.filter(ChangeEvent.ack_status == ack_status)
            if since:
                q = q.filter(ChangeEvent.detected_at >= _aware(since))
            if until:
                q = q.filter(ChangeEvent.detected_at <= _aware(until))
            rows = q.order_by(ChangeEvent.detected_at.desc()).offset(offset).limit(limit).all()
            return [_view(m) for m in rows]

    def windowed(self, since: datetime, until: datetime) -> List[ChangeEventView]:
        from ..storage.models_ops import ChangeEvent

        with self._sf() as s:
            rows = s.query(ChangeEvent).filter(
                ChangeEvent.detected_at >= _aware(since), ChangeEvent.detected_at <= _aware(until)).all()
            return [_view(m) for m in rows]

    def get_history(self, entity_type: str, entity_fqn: str,
                    limit: int = 50) -> List[ChangeEventView]:
        from ..storage.models_ops import ChangeEvent

        with self._sf() as s:
            rows = (
                s.query(ChangeEvent)
                .filter(ChangeEvent.entity_type == entity_type, ChangeEvent.entity_fqn == entity_fqn)
                .order_by(ChangeEvent.detected_at.desc()).limit(limit).all()
            )
            return [_view(m) for m in rows]

    def set_ack(self, change_id: int, action: str, actor: str, at: datetime) -> None:
        from ..storage.models_ops import ChangeEvent

        with self._sf() as s:
            m = (
                s.query(ChangeEvent)
                .filter(ChangeEvent.id == change_id)
                .first()
            )
            if m:
                m.ack_status = ACK_CLOSED
                m.ack_action = action
                m.ack_by = actor
                m.ack_at = at
                s.commit()
