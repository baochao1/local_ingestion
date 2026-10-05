"""Data-source management service (MOD-01 / T-109).

Owns the datasource lifecycle on top of a :class:`DatasourceRepository`:

* register with connectivity test + read-only verification (FR-1.5, explicitly
  bypassable via allow_write);
* credential encryption (AES-256-GCM, multi-version rotation, D1/D3);
* enable / disable, soft-delete that fans out an async batched cleanup task
  through the MOD-10 orchestrator (D6);
* credential version management and health probe.

The service is storage-agnostic: it depends on a repository, an audit sink, the
orchestrator and a *connectivity checker* abstraction — all injectable, so the
unit tests run without any database.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Protocol

_log = logging.getLogger(__name__)

from .repository import DuplicateDatasourceError
from ..credentials import CredentialCipher
from ..orchestration import (
    AuditService,
    InMemoryAuditSink,
    TaskService,
    TaskSpec,
    TriggerType,
)

ALLOWED_DS_TYPES = frozenset(
    {"mysql", "postgres", "postgresql", "snowflake", "sqlserver", "bigquery", "other"}
)


class DataSourceServiceError(Exception):
    """Base error for data-source management."""


class ConflictError(DataSourceServiceError):
    """Duplicate code / unique violation."""


class NotFoundError(DataSourceServiceError):
    """Referenced data source does not exist (or is soft-deleted)."""


class ConnectionFailedError(DataSourceServiceError):
    """Connectivity test failed."""


class WriteAccessDeniedError(DataSourceServiceError):
    """Connection holds write privileges and policy forbids it (FR-1.5)."""


class ConnectivityResult:
    def __init__(self, connected: bool, readonly: bool, reason: str) -> None:
        self.connected = connected
        self.readonly = readonly
        self.reason = reason

    def as_dict(self) -> Dict[str, Any]:
        return {"connected": self.connected, "readonly": self.readonly, "reason": self.reason}


class Capabilities:
    def __init__(
        self,
        supports_sampling: bool,
        supports_lineage: bool,
        supports_profiling: bool,
    ) -> None:
        self.supports_sampling = supports_sampling
        self.supports_lineage = supports_lineage
        self.supports_profiling = supports_profiling


class ConnectivityChecker(Protocol):
    def __call__(
        self,
        ds_type: str,
        host: Optional[str],
        port: Optional[int],
        username: Optional[str],
        password: Optional[str],
        database: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> ConnectivityResult: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


CONNECT_TIMEOUT_SEC = 3
_DIALECTS_WITH_CONNECT_TIMEOUT = frozenset({"mysql", "postgres", "postgresql"})


def engine_kwargs(ds_type: str) -> Dict[str, Any]:
    """关系型方言支持 connect_timeout；非关系型（snowflake/bigquery）传入会报错，故不传。"""
    if (ds_type or "").lower() in _DIALECTS_WITH_CONNECT_TIMEOUT:
        return {"connect_args": {"connect_timeout": CONNECT_TIMEOUT_SEC}}
    return {}


def classify_connectivity_error(exc: BaseException) -> str:
    """把驱动层异常映射为「用户可行动」的一行文案。

    原始异常（pymysql / psycopg2 堆栈、WinError 码、sqlalche.me 链接）只进日志，
    不再经 API detail 暴露到界面（ux-audit P1-1）。
    """
    text = str(exc)
    lowered = text.lower()
    # 注意要同时匹配 "timeout" 与 "timed out"（后者不含前者的子串）
    if "timeout" in lowered or "timed out" in lowered:
        return "连接目标库超时，请检查网络连通性与防火墙/安全组设置"
    if any(
        k in lowered
        for k in (
            "name or service not known",
            "could not translate host name",
            "nodename nor servname",
            "unknown host",
        )
    ):
        return "无法解析目标主机地址，请检查主机填写是否正确"
    if any(
        k in lowered
        for k in ("connection refused", "actively refused", "拒绝", "10061", "could not connect")
    ):
        return "目标主机拒绝连接，请确认主机与端口是否正确、数据库服务是否已启动"
    if any(
        k in lowered
        for k in ("access denied", "authentication failed", "password authentication", "认证失败")
    ):
        return "账号或密码不被目标库接受，请检查凭据"
    if "does not exist" in lowered and "database" in lowered:
        return "目标库不存在，请检查默认库名或 database 配置"
    return f"无法连接目标库：{text[:200]}"


def prod_connectivity_checker(
    ds_type: str,
    host: Optional[str],
    port: Optional[int],
    username: Optional[str],
    password: Optional[str],
    database: Optional[str] = None,
    options: Optional[Dict[str, Any]] = None,
) -> ConnectivityResult:
    """Live connectivity + read-only probe using SQLAlchemy (production)."""
    from sqlalchemy import create_engine, text

    from ..connections import build_url, probe_readonly

    try:
        url = build_url(
            ds_type,
            username=username,
            password=password,
            host=host,
            port=port,
            database=database,
            options=options,
        )
    except Exception as exc:  # noqa: BLE001 - surface as connectivity failure
        _log.warning("connectivity check rejected params: %r", exc)
        return ConnectivityResult(False, False, "连接参数非法，请检查类型/主机/端口等填写")

    engine = create_engine(url, **engine_kwargs(ds_type))
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        readonly, reason = probe_readonly(engine, ds_type)
        return ConnectivityResult(True, readonly, reason)
    except Exception as exc:  # noqa: BLE001 - any failure = unreachable
        _log.warning("connectivity probe failed: %r", exc)
        return ConnectivityResult(False, False, classify_connectivity_error(exc))
    finally:
        engine.dispose()


def prod_capability_detector(ds_type: str) -> Capabilities:
    """Per-dialect capability defaults (D5: capability bits front-loaded)."""
    t = (ds_type or "").lower()
    if t == "mysql":
        # MySQL has no TABLESAMPLE; sampling must use a PK point-query instead.
        return Capabilities(supports_sampling=False, supports_lineage=True, supports_profiling=True)
    if t in ("postgres", "postgresql", "snowflake", "sqlserver", "bigquery", "other"):
        return Capabilities(supports_sampling=True, supports_lineage=True, supports_profiling=True)
    return Capabilities(False, False, False)


class DataSourceService:
    def __init__(
        self,
        repository: Any,
        *,
        cipher: Optional[CredentialCipher] = None,
        audit: Optional[AuditService] = None,
        task_service: Optional[TaskService] = None,
        connectivity_checker: Optional[ConnectivityChecker] = None,
        capability_detector: Optional[Callable[[str], Capabilities]] = None,
        allow_write: bool = False,
        audit_actor: Optional[str] = None,
    ) -> None:
        self._repo = repository
        self._cipher = cipher or CredentialCipher()
        self._audit = audit or AuditService(InMemoryAuditSink())
        self._tasks = task_service
        self._checker = connectivity_checker or prod_connectivity_checker
        self._caps = capability_detector or prod_capability_detector
        self._allow_write = allow_write
        self._actor = audit_actor

    # ----------------------------------------------------------- validation
    @staticmethod
    def _validate_spec(spec: Dict[str, Any]) -> None:
        if not spec.get("code"):
            raise DataSourceServiceError("code 为必填")
        if not spec.get("name"):
            raise DataSourceServiceError("name 为必填")
        ds_type = spec.get("ds_type")
        if not ds_type or str(ds_type).lower() not in ALLOWED_DS_TYPES:
            raise DataSourceServiceError(
                f"ds_type 非法：{ds_type!r}（允许 {sorted(ALLOWED_DS_TYPES)}）"
            )
        port = spec.get("port")
        if port is not None and not (1 <= int(port) <= 65535):
            raise DataSourceServiceError(f"port 超出范围：{port}")
        user = spec.get("username")
        pwd = spec.get("password")
        if (user is None) != (pwd is None):
            raise DataSourceServiceError("username 与 password 须同时提供或同时省略")

    # -------------------------------------------------------------- register
    def register(
        self,
        spec: Dict[str, Any],
        *,
        actor: Optional[str] = None,
        allow_write: Optional[bool] = None,
    ) -> Dict[str, Any]:
        self._validate_spec(spec)
        actor = actor or self._actor
        code = spec["code"]
        ds_type = str(spec["ds_type"]).lower()
        effective_allow_write = self._allow_write if allow_write is None else allow_write
        if self._repo.get_datasource_by_code(code) is not None:
            raise ConflictError(f"数据源 code 已存在：{code}")

        username = spec.get("username")
        password = spec.get("password")
        database = (spec.get("scan_config") or {}).get("database")
        options = (spec.get("scan_config") or {}).get("options")

        conn = self._checker(ds_type, spec.get("host"), spec.get("port"), username, password, database, options)
        if not conn.connected:
            raise ConnectionFailedError(conn.reason)
        if not conn.readonly and not effective_allow_write:
            raise WriteAccessDeniedError(
                f"连接具备写权限，注册被拒绝（FR-1.5 只读策略）：{conn.reason}"
            )

        caps = self._caps(ds_type)
        ds_payload = {
            "tenant_id": 0,
            "code": code,
            "name": spec["name"],
            "ds_type": ds_type,
            "host": spec.get("host"),
            "port": spec.get("port"),
            "environment": spec.get("environment"),
            "group_name": spec.get("group_name"),
            "owner_business": spec.get("owner_business"),
            "owner_technical": spec.get("owner_technical"),
            "enabled": spec.get("enabled", True),
            "scan_enabled": spec.get("scan_enabled", True),
            "sampling_enabled": spec.get("sampling_enabled", False),
            "scan_config": spec.get("scan_config") or {},
            "sampling_config": spec.get("sampling_config") or {},
            "supports_sampling": caps.supports_sampling,
            "supports_lineage": caps.supports_lineage,
            "supports_profiling": caps.supports_profiling,
        }
        has_cred = username is not None and password is not None

        def _cred_factory(ds_id: int) -> Dict[str, Any]:
            blob, enc_algo = self._cipher.encrypt(password, datasource_id=ds_id)
            return {
                "datasource_id": ds_id,
                "version": 1,
                "username": username,
                "credential_enc": blob,
                "enc_algo": enc_algo,
                "is_active": True,
                "verified_at": _now(),
            }

        # Atomic: the datasource and its first credential must land together —
        # otherwise a credential-side failure leaves a credential-less
        # datasource that can never be re-registered under the same code.
        atomic = getattr(self._repo, "create_datasource_with_credential", None)
        try:
            if callable(atomic):
                ds = atomic(ds_payload, _cred_factory if has_cred else None)
            else:  # legacy repository without the atomic hook
                ds = self._repo.create_datasource(ds_payload)
                if has_cred:
                    self._repo.create_credential(_cred_factory(ds.id))
        except DuplicateDatasourceError as exc:
            # The existence pre-check above is a separate read, so a concurrent
            # registrant can slip past it; the unique index then rejects the
            # INSERT. Surface that as a domain conflict, not a DB error.
            raise ConflictError(f"数据源 code 已存在：{code}") from exc

        if has_cred:
            self._audit.record(
                actor, "datasource.credential.create",
                entity_type="datasource", entity_fqn=code,
                detail={"version": 1}, result="ok",
            )

        fr15_bypass = (not conn.readonly) and effective_allow_write
        self._audit.record(
            actor, "datasource.register",
            entity_type="datasource", entity_fqn=code,
            detail={
                "ds_type": ds_type,
                "readonly": conn.readonly,
                "allow_write": effective_allow_write,
                "fr15_bypass": fr15_bypass,
            },
            result="ok",
        )
        return self._to_view(ds)

    # ----------------------------------------------------------- test-only
    def test_connection(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        ds_type = str(spec.get("ds_type") or "").lower()
        result = self._checker(
            ds_type, spec.get("host"), spec.get("port"),
            spec.get("username"), spec.get("password"),
            (spec.get("scan_config") or {}).get("database"),
            (spec.get("scan_config") or {}).get("options"),
        )
        return result.as_dict()

    # ---------------------------------------------------------------- query
    def list_datasources(
        self,
        *,
        enabled: Optional[bool] = None,
        environment: Optional[str] = None,
        group_name: Optional[str] = None,
        ds_type: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows = self._repo.list_datasources(
            enabled=enabled, environment=environment,
            group_name=group_name, ds_type=ds_type, keyword=keyword,
        )
        return [self._to_view(r) for r in rows]

    def get_datasource(self, ds_id: int) -> Dict[str, Any]:
        ds = self._repo.get_datasource(ds_id)
        if ds is None:
            raise NotFoundError(f"数据源 {ds_id}")
        return self._to_view(ds)

    def update_datasource(self, ds_id: int, changes: Dict[str, Any]) -> Dict[str, Any]:
        if self._repo.get_datasource(ds_id) is None:
            raise NotFoundError(f"数据源 {ds_id}")
        ds = self._repo.update_datasource(ds_id, changes)
        return self._to_view(ds)

    def enable(self, ds_id: int) -> Dict[str, Any]:
        return self.update_datasource(ds_id, {"enabled": True})

    def disable(self, ds_id: int) -> Dict[str, Any]:
        return self.update_datasource(ds_id, {"enabled": False})

    # ------------------------------------------------------------- delete
    def delete_datasource(self, ds_id: int, *, actor: Optional[str] = None) -> None:
        ds = self._repo.get_datasource(ds_id)
        if ds is None:
            raise NotFoundError(f"数据源 {ds_id}")
        self._repo.soft_delete_datasource(ds_id)
        actor = actor or self._actor
        if self._tasks is not None:
            # 异步分批清理（D6）：追加任务，由编排器下发；不阻塞请求、不触发长事务。
            self._tasks.submit(
                TaskSpec(
                    job_type="datasource_cleanup",
                    scope={"datasource_id": ds_id},
                    trigger=TriggerType.MANUAL,
                    payload={"note": "软删后异步分批软删 catalog_*，每批 5000 行，可中断续跑"},
                ),
                actor=actor or "system",
            )
        self._audit.record(
            actor, "datasource.delete",
            entity_type="datasource", entity_fqn=getattr(ds, "code", str(ds_id)),
            detail={"datasource_id": ds_id}, result="soft-deleted",
        )

    # ---------------------------------------------------------- credentials
    def add_credential_version(
        self, ds_id: int, username: str, password: str, *, actor: Optional[str] = None
    ) -> int:
        ds = self._repo.get_datasource(ds_id)
        if ds is None:
            raise NotFoundError(f"数据源 {ds_id}")
        existing = self._repo.list_credentials(ds_id)
        version = (max((c.version for c in existing), default=0)) + 1
        blob, enc_algo = self._cipher.encrypt(password, datasource_id=ds_id)
        self._repo.create_credential(
            {
                "datasource_id": ds_id,
                "version": version,
                "username": username,
                "credential_enc": blob,
                "enc_algo": enc_algo,
                "is_active": False,  # 新版本默认不激活，验证通过后由 activate 切换
                "verified_at": _now(),
            }
        )
        self._audit.record(
            actor or self._actor, "datasource.credential.rotate",
            entity_type="datasource", entity_fqn=getattr(ds, "code", str(ds_id)),
            detail={"version": version}, result="created",
        )
        return version

    def activate_credential(self, ds_id: int, version: int, *, actor: Optional[str] = None) -> int:
        cred = self._repo.get_credential(ds_id, version)
        if cred is None:
            raise NotFoundError(f"凭据版本 ds={ds_id} v={version}")
        self._repo.set_active_credential(ds_id, version)
        ds = self._repo.get_datasource(ds_id)
        self._audit.record(
            actor or self._actor, "datasource.credential.activate",
            entity_type="datasource", entity_fqn=getattr(ds, "code", str(ds_id)),
            detail={"version": version}, result="activated",
        )
        return version

    # -------------------------------------------------------------- health
    def health(self, ds_id: int) -> Dict[str, Any]:
        ds = self._repo.get_datasource(ds_id)
        if ds is None:
            raise NotFoundError(f"数据源 {ds_id}")
        creds = self._repo.list_credentials(ds_id)
        active_version = next((c.version for c in creds if getattr(c, "is_active", False)), None)
        return {
            "datasource_id": ds.id,
            "code": ds.code,
            "enabled": bool(ds.enabled),
            "last_scan_at": ds.last_scan_at,
            "last_scan_status": ds.last_scan_status,
            "last_error": ds.last_error,
            "credential_present": bool(creds),
            "active_credential_version": active_version,
        }

    # -------------------------------------------------------------- helpers
    def _to_view(self, ds: Any) -> Dict[str, Any]:
        creds = self._repo.list_credentials(ds.id)
        return {
            "id": ds.id,
            "code": ds.code,
            "name": ds.name,
            "ds_type": ds.ds_type,
            "host": getattr(ds, "host", None),
            "port": getattr(ds, "port", None),
            "environment": getattr(ds, "environment", None),
            "group_name": getattr(ds, "group_name", None),
            "owner_business": getattr(ds, "owner_business", None),
            "owner_technical": getattr(ds, "owner_technical", None),
            "enabled": bool(ds.enabled),
            "scan_enabled": bool(ds.scan_enabled),
            "sampling_enabled": bool(ds.sampling_enabled),
            "supports_sampling": bool(ds.supports_sampling),
            "supports_lineage": bool(ds.supports_lineage),
            "supports_profiling": bool(ds.supports_profiling),
            "last_scan_at": ds.last_scan_at,
            "last_scan_status": ds.last_scan_status,
            "last_error": ds.last_error,
            "credential_versions": [c.version for c in creds],
            "active_credential_version": next(
                (c.version for c in creds if getattr(c, "is_active", False)), None
            ),
        }
