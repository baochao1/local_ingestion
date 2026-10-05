"""Metadata scan orchestration (the missing link to the real connectors).

Before this module nothing assembled the L1 trio — a source connector
(extraction), ``DatabasePipeline`` (transform hooks) and ``PostgresSink``
(persistence) — from a *registered* datasource: the CLI printed and stopped, and
the integration tests seeded a synthetic catalog instead of scanning anything.

:class:`ScanService.run_scan` closes that gap:

    datasource row (+ encrypted credential)
      -> ConnectionProvider.acquire  (read-only guard FR-1.5 + audit)
      -> source connector for ds_type (live introspection, registry-dispatched)
      -> DatabasePipeline            (dialect-backed transform hook)
      -> PostgresSink                (idempotent upsert into ``catalog_*``)

It is therefore the first end-to-end path where governance metadata comes from a
real database rather than fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

import structlog

from local_ingestion.core.pipeline.database_pipeline import (
    DatabasePipeline,
    DatabasePipelineConfig,
)
from local_ingestion.platform.connections import METADATA, ConnectionProvider
from local_ingestion.platform.connectors import (
    ConnectorRegistryError,
    build_connection,
    connection_options,
    make_connector,
    supported_ds_types,
)
from local_ingestion.platform.storage.models_core import Datasource
from local_ingestion.platform.sinks.postgres import PostgresSink, PostgresSinkConfig

logger = structlog.get_logger()

# The supported set is derived from the connector registry, not hardcoded: an
# external distribution can register a datasource type by simply being
# installed. Keep this a function call so those registrations are visible.


class ScanError(Exception):
    """Base error for scan orchestration."""


class UnsupportedDatasourceError(ScanError):
    """Raised when no real connector exists for the datasource type yet."""


class DatasourceNotFoundError(ScanError):
    """Raised when the datasource to scan is missing or soft-deleted.

    Kept distinct from the generic :class:`ScanError` so an HTTP layer can
    answer 404 instead of 400 without string-matching the message.
    """


@dataclass
class ScanResult:
    """Outcome of one full metadata scan."""

    datasource_id: int
    datasource_code: str
    database: str
    tables_processed: int = 0
    tables_failed: int = 0
    schemas_processed: int = 0
    schemas_failed: int = 0
    databases_processed: int = 0
    databases_failed: int = 0
    readonly: bool = False
    readonly_reason: str = ""
    errors: List[Dict[str, str]] = field(default_factory=list)
    #: Summary of the MOD-05 grading pass that runs after the scan (None when
    #: grading was skipped or failed).
    classification: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return not self.errors and not (
            self.tables_failed or self.schemas_failed or self.databases_failed
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "datasource_id": self.datasource_id,
            "datasource_code": self.datasource_code,
            "database": self.database,
            "tables_processed": self.tables_processed,
            "tables_failed": self.tables_failed,
            "schemas_processed": self.schemas_processed,
            "schemas_failed": self.schemas_failed,
            "databases_processed": self.databases_processed,
            "databases_failed": self.databases_failed,
            "readonly": self.readonly,
            "readonly_reason": self.readonly_reason,
            "errors": self.errors,
            "ok": self.ok,
            "classification": self.classification,
        }


def _errors(context: Any) -> List[Dict[str, str]]:
    """Flatten pipeline ``ErrorRecord``s into JSON-serialisable dicts."""
    out: List[Dict[str, str]] = []
    for rec in getattr(context, "errors", []) or []:
        out.append(
            {
                "name": getattr(rec, "name", "UnknownError"),
                "error": str(getattr(rec, "error", rec))[:500],
                "entity_name": getattr(rec, "entity_name", None) or "",
                "entity_type": getattr(rec, "entity_type", None) or "",
            }
        )
    return out


class ScanService:
    """Runs a metadata scan of a registered datasource into the catalog.

    The connection is always taken through :class:`ConnectionProvider` so a scan
    inherits the read-only guard (FR-1.5) and the connection audit trail. Pass
    ``allow_write=True`` only for local/experimental setups where the account is
    intentionally privileged.
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        cipher: Optional[Any] = None,
        audit_sink: Optional[Callable[[Any], None]] = None,
        actor: Optional[str] = None,
        now: Optional[Callable[[], datetime]] = None,
        connector_factory: Optional[Callable[[], Any]] = None,
        sink_factory: Optional[Callable[[], Any]] = None,
        provider_cls: Any = None,
        classifier: Optional[Any] = None,
    ) -> None:
        self._sf = session_factory
        self._cipher = cipher
        self._audit_sink = audit_sink
        self._actor = actor
        self._now = now or (lambda: datetime.now(timezone.utc))
        # Deliberately has no default: the connector is picked per ds_type by
        # the connector registry. A factory is still accepted so tests can
        # inject a fake without touching the registry.
        self._connector_factory = connector_factory
        self._sink_factory = sink_factory or (lambda: PostgresSink())
        self._provider_cls = provider_cls or ConnectionProvider
        # MOD-05 grading; lazily built so tests can inject a fake instead.
        self._classifier = classifier

    # ------------------------------------------------------------------ API
    def run_scan(
        self,
        datasource_id: int,
        *,
        database: Optional[str] = None,
        schemas: Optional[Sequence[str]] = None,
        allow_write: bool = False,
        mark_deleted: bool = True,
        classify: bool = True,
    ) -> ScanResult:
        """Scan ``datasource_id`` and persist its metadata into ``catalog_*``.

        Args:
            database: Overrides ``datasource.scan_config.database``.
            schemas: Optional allow-list of schema names to scan. Deletions are
                only ever inferred *within the scanned schemas*, so a filtered
                scan never wipes tables it did not look at.
            allow_write: Relax the read-only guard (not for production).
            mark_deleted: Soft-delete catalog entities that this scan no longer
                sees, so removals surface in the next schema diff. Enabled by
                default because a scan reconciles the whole requested scope;
                pass False to retain history (e.g. for a one-off backfill).
            classify: Run MOD-05 grading right after the scan, so freshly
                ingested rows carry ``grade_level`` and PII markers instead of
                leaving the overview's sensitive metrics empty.

        Returns:
            A :class:`ScanResult` summarising what was written.
        """
        with self._sf() as session:
            ds = session.get(Datasource, datasource_id)
            if ds is None or ds.deleted_at is not None:
                raise DatasourceNotFoundError(f"数据源 {datasource_id} 不存在或已删除。")

            ds_type = (ds.ds_type or "").lower()
            if ds_type not in supported_ds_types():
                raise UnsupportedDatasourceError(
                    f"数据源 {ds.code} 的 ds_type={ds.ds_type!r} 暂无真实连接器支持"
                    f"（已支持：{sorted(supported_ds_types())}）。"
                )

            scan_config = dict(ds.scan_config or {})
            target_db = database or scan_config.get("database")
            if not target_db:
                # 兜底：未显式指定也未配置时，连上服务端自动列举用户库并选用唯一候选，
                # 同时回写 scan_config.database，使后续扫描与定时任务无需再手动传 database。
                target_db = self._discover_target_database(
                    session, ds, ds_type, self._provider_cls
                )
                scan_config["database"] = target_db
                ds.scan_config = scan_config
                session.add(ds)
                session.flush()
            raw_filter = schemas or scan_config.get("schema_filter")
            schema_filter = set(raw_filter) if raw_filter else None

            provider = self._provider_cls(
                session, cipher=self._cipher, audit_sink=self._audit_sink, actor=self._actor
            )
            try:
                source = (
                    self._connector_factory()
                    if self._connector_factory
                    else make_connector(ds_type)
                )
            except ConnectorRegistryError as exc:
                # Covers both "no such type" and "type known but its driver is
                # not installed" — the latter carries the pip-install hint.
                raise UnsupportedDatasourceError(str(exc)) from exc
            sink = self._sink_factory()
            try:
                with provider.acquire(
                    ds.id,
                    METADATA,
                    allow_write=allow_write,
                    database=target_db,
                    options=connection_options(ds),
                ) as conn:
                    source.connect(build_connection(ds_type, conn, target_db, ds))
                    sink.connect(
                        PostgresSinkConfig(
                            datasource_id=ds.id,
                            tenant_id=ds.tenant_id,
                            ds_type=ds_type,
                            mark_deleted_tables=mark_deleted,
                        )
                    )
                    pipeline = DatabasePipeline(
                        source=source,
                        sink=sink,
                        config=DatabasePipelineConfig(
                            ds_type=ds_type,
                            schema_filter=schema_filter,
                            mark_deleted_tables=mark_deleted,
                        ),
                        database=target_db,
                    )
                    ctx = pipeline.run()
                    result = ScanResult(
                        datasource_id=ds.id,
                        datasource_code=ds.code,
                        database=target_db,
                        tables_processed=ctx.tables_processed,
                        tables_failed=ctx.tables_failed,
                        schemas_processed=ctx.schemas_processed,
                        schemas_failed=ctx.schemas_failed,
                        databases_processed=ctx.databases_processed,
                        databases_failed=ctx.databases_failed,
                        readonly=conn.readonly,
                        readonly_reason=conn.readonly_reason,
                        errors=_errors(ctx),
                    )
            except Exception as exc:  # noqa: BLE001 - recorded on the datasource row
                self._record_status(session, ds, "failed", str(exc)[:500])
                logger.error("scan_failed", datasource=ds.code, error=str(exc))
                raise
            finally:
                sink.close()
                source.disconnect()

            self._record_status(
                session,
                ds,
                "success" if result.ok else "partial",
                None if result.ok else self._summarise_errors(result),
            )

            if classify:
                try:
                    result.classification = self._grade(ds.id)
                except Exception as exc:  # noqa: BLE001
                    # Grading must never fail an otherwise successful scan.
                    logger.error(
                        "classification_failed", datasource=ds.code, error=str(exc)
                    )

            logger.info("scan_finished", **result.as_dict())
            return result

    def resolve_datasource_id(self, code: str) -> int:
        """Look up a datasource id by its unique code (for task scopes)."""
        with self._sf() as session:
            ds = (
                session.query(Datasource)
                .filter(Datasource.code == code, Datasource.deleted_at.is_(None))
                .first()
            )
            if ds is None:
                raise ScanError(f"数据源 code={code!r} 不存在。")
            return int(ds.id)

    # ----------------------------------------------------------- internals
    def _discover_target_database(
        self,
        session: Any,
        ds: Any,
        ds_type: str,
        provider_cls: Any,
    ) -> str:
        """Resolve a missing ``target_db`` by listing the server's user databases.

        Used only when neither ``database=`` nor ``scan_config.database`` is set.
        Connects to the maintenance database (``postgres``), enumerates non-system
        databases and, if exactly one user database exists, returns it. When the
        choice is ambiguous or the server cannot be listed, raises a :class:`ScanError`
        that names the available databases so the operator can pick explicitly.
        """
        last_err: Optional[Exception] = None
        for maint_db in ("postgres", None):
            try:
                provider = provider_cls(
                    session,
                    cipher=self._cipher,
                    audit_sink=self._audit_sink,
                    actor=self._actor,
                )
                with provider.acquire(
                    ds.id,
                    METADATA,
                    allow_write=False,
                    database=maint_db,
                    options=connection_options(ds),
                    verify_readonly=False,
                ) as conn:
                    source = make_connector(ds_type)
                    source.connect(build_connection(ds_type, conn, maint_db, ds))
                    try:
                        found = [d.name for d in source.fetch_databases()]
                    finally:
                        source.disconnect()
            except Exception as exc:  # noqa: BLE001 - try the next maintenance db
                last_err = exc
                continue

            system_dbs = {"postgres", "template0", "template1"}
            user_dbs = [name for name in found if name not in system_dbs]
            if len(user_dbs) == 1:
                logger.info(
                    "scan_database_autodiscovered",
                    datasource=ds.code,
                    database=user_dbs[0],
                )
                return user_dbs[0]
            if not user_dbs:
                raise ScanError(
                    f"数据源 {ds.code} 未指定目标数据库，且服务端没有可用用户库"
                    f"（仅发现：{', '.join(found) or '无'}）。"
                    "请在数据源 scan_config 中设置 database，或通过 database= 显式传入。"
                )
            raise ScanError(
                f"数据源 {ds.code} 未指定目标数据库，且服务端存在多个用户库"
                f"（{', '.join(user_dbs)}）。无法自动选择，"
                "请在数据源 scan_config 中设置 database，或通过 database= 显式传入。"
            )

        raise ScanError(
            f"数据源 {ds.code} 未指定目标数据库，且无法连接服务端列举数据库：{last_err}。"
            "请在数据源 scan_config 中设置 database，或通过 database= 显式传入。"
        )

    def _grade(self, datasource_id: int) -> Dict[str, Any]:
        """Grade what this scan just wrote (MOD-05)."""
        if self._classifier is None:
            from ..classification import ClassificationService

            self._classifier = ClassificationService(self._sf)
        return self._classifier.classify_datasource(datasource_id).as_dict()

    @staticmethod
    def _summarise_errors(result: ScanResult) -> str:
        parts = [
            f"{e['entity_type'] or 'entity'} {e['entity_name']}: {e['name']} - {e['error']}"
            for e in result.errors
        ]
        return "；".join(parts)[:1000] or "部分对象扫描失败"

    def _record_status(
        self, session: Any, ds: Any, status: str, error: Optional[str]
    ) -> None:
        ds.last_scan_at = self._now()
        ds.last_scan_status = status
        ds.last_error = error
        session.commit()


def make_scan_handler(
    scan_service: ScanService,
    *,
    allow_write: bool = False,
    database: Optional[str] = None,
    schemas: Optional[Sequence[str]] = None,
) -> Callable[[Any], Dict[str, Any]]:
    """Build a T-107 task handler that runs a :class:`ScanService` scan.

    This is the ``scan`` end of the ``scan -> diff -> notify`` dependency chain
    described in :mod:`local_ingestion.platform.orchestration.service`; before it
    existed, orchestrated pipelines could only start from a synthetic seed step.

    The datasource is taken from the task scope, either ``datasource_id`` or
    ``datasource_code``. A scan that reports failures raises so the orchestrator
    applies its retry policy instead of silently continuing.
    """
    def handler(ctx: Any) -> Dict[str, Any]:
        run = getattr(ctx, "run", ctx)
        scope = dict(getattr(run, "scope", None) or {})
        ds_id = scope.get("datasource_id")
        if ds_id is None:
            code = scope.get("datasource_code")
            if code is None:
                raise ScanError(
                    "扫描任务的 scope 缺少 datasource_id 或 datasource_code。"
                )
            ds_id = scan_service.resolve_datasource_id(str(code))

        result = scan_service.run_scan(
            int(ds_id),
            database=database,
            schemas=schemas,
            allow_write=allow_write,
        )
        if not result.ok:
            raise ScanError(
                result.errors[0]["error"] if result.errors else "扫描存在失败对象"
            )
        return result.as_dict()

    return handler
