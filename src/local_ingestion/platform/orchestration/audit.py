"""Audit service (FR-15.5 / T-107).

All modules must record critical actions through this single service rather than
writing ``audit_log`` directly (design decision D4). The actual write is
delegated to an ``AuditSink`` so the same logic can be exercised with an
in-memory sink under unit tests and a SQLAlchemy sink in production.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional


@dataclass
class AuditEntry:
    actor: Optional[str]
    action: str
    entity_type: Optional[str] = None
    entity_fqn: Optional[str] = None
    detail: dict = field(default_factory=dict)
    client_ip: Optional[str] = None
    result: Optional[str] = None
    occurred_at: Optional[datetime] = None


class AuditSink:
    def record(self, entry: AuditEntry) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class InMemoryAuditSink(AuditSink):
    def __init__(self) -> None:
        self.entries: List[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    def clear(self) -> None:
        self.entries.clear()

    def query(
        self,
        *,
        action: Optional[str] = None,
        actor: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[AuditEntry]:
        """Return audit entries newest-first, optionally filtered.

        Used by the ``GET /api/v1/audit-logs`` REST endpoint so the in-memory
        default stack exposes a queryable audit feed without Postgres.
        """
        res = list(self.entries)
        if action is not None:
            res = [e for e in res if e.action == action]
        if actor is not None:
            res = [e for e in res if e.actor == actor]
        if entity_type is not None:
            res = [e for e in res if e.entity_type == entity_type]
        res.sort(key=lambda e: e.occurred_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        if limit is not None:
            res = res[:limit]
        return res


class TeeAuditSink(InMemoryAuditSink):
    """内存缓冲 + ``audit_log`` 表双写。

    保留内存缓冲是为了无库环境（测试/本地无 PG）仍能查询；同时把审计真正
    落库，避免重启即丢。落库失败不影响主流程（best-effort）。
    """

    def __init__(self, session_factory=None) -> None:
        super().__init__()
        self._sf = session_factory
        self._sql: SqlAuditSink | None = None

    def _sql_sink(self) -> SqlAuditSink:
        if self._sql is None:
            sf = self._sf
            if sf is None:
                from ..storage.session import session_scope

                sf = session_scope
            self._sql = SqlAuditSink(sf)
        return self._sql

    def record(self, entry: AuditEntry) -> None:
        super().record(entry)
        try:
            self._sql_sink().record(entry)
        except Exception:  # noqa: BLE001 - 审计落库失败不得影响业务主流程
            pass


#: Process-wide audit sink for the default in-memory stack. The orchestration
#: ``TaskService`` (and any service that opts in) writes here so the audit REST
#: endpoint can read a single feed. Per-service sinks remain available for tests.
#: 使用双写 sink：审计同时进入 ``audit_log``，重启后仍可查。
GLOBAL_AUDIT_SINK: InMemoryAuditSink = TeeAuditSink()


class SqlAuditSink(AuditSink):
    """Persists audit entries to the ``audit_log`` table (ORM landed in T-106)."""

    def __init__(self, session_factory) -> None:
        self._sf = session_factory

    def record(self, entry: AuditEntry) -> None:
        from ..storage.models_ops import AuditLog

        with self._sf() as s:
            s.add(
                AuditLog(
                    actor=entry.actor,
                    action=entry.action,
                    entity_type=entry.entity_type,
                    entity_fqn=entry.entity_fqn,
                    detail=entry.detail,
                    client_ip=entry.client_ip,
                    result=entry.result,
                    occurred_at=entry.occurred_at,
                )
            )
            s.commit()


class AuditService:
    """Single entry point for audit logging (contract C10)."""

    def __init__(
        self,
        sink: AuditSink,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._sink = sink
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def record(
        self,
        actor: Optional[str],
        action: str,
        *,
        entity_type: Optional[str] = None,
        entity_fqn: Optional[str] = None,
        detail: Optional[dict] = None,
        client_ip: Optional[str] = None,
        result: Optional[str] = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_fqn=entity_fqn,
            detail=dict(detail or {}),
            client_ip=client_ip,
            result=result,
            occurred_at=self._clock(),
        )
        self._sink.record(entry)
        return entry
