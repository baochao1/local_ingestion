"""Connection supply for data sources (T-108 ②③④).

``ConnectionProvider.acquire(datasource_id, purpose)`` is the single place that
is allowed to turn a stored credential into a usable connection. It enforces,
in order:

* the datasource exists and is not soft-deleted;
* the **capability bits** required by the purpose (``enabled``/``scan_enabled``/
  ``sampling_enabled``/``supports_sampling``);
* **read-only verification** for every non-admin purpose — a connection that
  holds write privileges is rejected by default, because scanning and sampling
  must never be able to mutate a business database (see decision Q7 in
  ``doc/plan/02-decisions.md``);
* an **audit record** for both granted and denied attempts.

It returns a context manager, so the engine is always disposed even if the
caller raises.

Read-only probes are plain SQL per dialect (MySQL ``SHOW GRANTS``, PostgreSQL
role/privilege queries, Snowflake ``SHOW GRANTS``). They intentionally avoid the
L1 upstream connector layer: this module lives in L3 and must not modify L1.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session

from .credentials import CredentialCipher

__all__ = [
    "ADMIN",
    "METADATA",
    "SAMPLE",
    "ConnectionError",
    "ConnectionPurpose",
    "DataSourceConnection",
    "DatasourceUnavailableError",
    "ConnectionProvider",
    "MissingCredentialError",
    "PurposeNotAllowedError",
    "ReadOnlyVerifier",
    "WriteAccessError",
    "build_url",
    "evaluate_readonly",
    "probe_readonly",
]

AUDIT_ACTION: str = "datasource.connection.acquire"

DRIVERNAMES: dict[str, str] = {
    "mysql": "mysql+pymysql",
    "mariadb": "mysql+pymysql",
    "postgres": "postgresql+psycopg2",
    "postgresql": "postgresql+psycopg2",
    "snowflake": "snowflake",
    "sqlserver": "mssql+pyodbc",
    "bigquery": "bigquery",
}
DEFAULT_PORTS: dict[str, int] = {
    "mysql": 3306,
    "mariadb": 3306,
    "postgres": 5432,
    "postgresql": 5432,
    "snowflake": 443,
    "sqlserver": 1433,
}

READONLY_PROBE_SQL: dict[str, str] = {
    "mysql": "SHOW GRANTS FOR CURRENT_USER",
    "postgres": (
        "SELECT "
        "(SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls "
        "   FROM pg_roles WHERE rolname = current_user) AS role_write, "
        "(SELECT has_database_privilege(current_user, current_database(), 'CREATE')) "
        "   AS db_create, "
        "(SELECT count(*) FROM information_schema.role_table_grants "
        "   WHERE grantee = current_user "
        "     AND privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE')) "
        "   AS write_grants"
    ),
    "snowflake": "SHOW GRANTS TO USER CURRENT_USER()",
}

_WRITE_KEYWORDS = (
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "CREATE",
    "ALTER",
    "TRUNCATE",
    "REVOKE",
    "LOCK TABLES",
    "REFERENCES",
    "GRANT OPTION",
    "ALL PRIVILEGES",
)
_SNOWFLAKE_READ_PRIVILEGES = {
    "SELECT",
    "USAGE",
    "MONITOR",
    "READ",
    "REFERENCE_USAGE",
}


class ConnectionError(Exception):
    """Base error raised while acquiring a data-source connection."""


class DatasourceUnavailableError(ConnectionError):
    """Datasource missing, soft-deleted or disabled."""


class MissingCredentialError(ConnectionError):
    """No active credential is stored for the datasource."""


class PurposeNotAllowedError(ConnectionError):
    """The datasource lacks the capability bits required by the purpose."""


class WriteAccessError(ConnectionError):
    """The connection holds write privileges and the purpose forbids them."""


class ConnectionPurpose(str, Enum):
    """Why a connection is being acquired — drives capability checks."""

    METADATA = "metadata"
    """元数据扫描：只读，要求 ``scan_enabled``。"""
    SAMPLE = "sample"
    """数据采样：只读，要求 ``sampling_enabled`` + ``supports_sampling``。"""
    ADMIN = "admin"
    """管控操作（连通性测试、权限分析）：允许写权限，不做只读校验。"""


METADATA = ConnectionPurpose.METADATA
SAMPLE = ConnectionPurpose.SAMPLE
ADMIN = ConnectionPurpose.ADMIN


def _normalize_ds_type(ds_type: str) -> str:
    return (ds_type or "").strip().lower()


def build_url(
    ds_type: str,
    *,
    username: str | None,
    password: str | None,
    host: str | None,
    port: int | None,
    database: str | None = None,
    options: dict[str, Any] | None = None,
) -> URL:
    """Build a SQLAlchemy URL for a datasource without leaking the password.

    The password lives in the URL object only; render it with
    ``url.render_as_string()`` (masked) or ``safe_url()`` from
    :class:`DataSourceConnection`. Never log
    ``render_as_string(hide_password=False)``.
    """
    normalized = _normalize_ds_type(ds_type)
    drivername = DRIVERNAMES.get(normalized)
    if drivername is None:
        raise ConnectionError(f"不支持的数据源类型：{ds_type!r}")
    return URL.create(
        drivername=drivername,
        username=username or None,
        password=password or None,
        host=host or None,
        port=int(port) if port else DEFAULT_PORTS.get(normalized),
        database=database or None,
        query={str(k): str(v) for k, v in (options or {}).items()} or None,
    )


def evaluate_readonly(ds_type: str, rows: Sequence[Sequence[Any]]) -> tuple[bool, str]:
    """Interpret probe rows: return ``(is_readonly, reason)``."""
    normalized = _normalize_ds_type(ds_type)
    if normalized == "postgres":
        if not rows:
            return False, "只读探针未返回任何行"
        role_write, db_create, write_grants = rows[0][:3]
        if role_write:
            return False, "角色具备超级用户/建库/建角色/绕过 RLS 权限"
        if db_create:
            return False, "具备当前数据库的 CREATE 权限"
        if int(write_grants or 0) > 0:
            return False, (
                f"具备 {write_grants} 项写权限（INSERT/UPDATE/DELETE/TRUNCATE）"
            )
        return True, "角色属性与表权限均为只读"

    # MySQL / Snowflake：按关键字判定（宽松读权限白名单之外的即视为写）
    matched: list[str] = []
    for row in rows:
        cells = [str(cell) for cell in row if cell is not None]
        if normalized == "snowflake":
            for cell in cells:
                privilege = cell.strip().upper()
                if privilege in {"ROLE", "GRANTED_TO", "GRANTEE_NAME", "USER"}:
                    continue
                if privilege and privilege not in _SNOWFLAKE_READ_PRIVILEGES:
                    if re.fullmatch(r"[A-Z_ ]{3,}", privilege):
                        matched.append(privilege)
        else:
            joined = " ".join(cells)
            # `SHOW GRANTS` 的一行形如 "GRANT SELECT, INSERT ON db.* TO 'u'@'h'"；
            # 必须只看 GRANT ... ON 之间的权限列表，否则每行都会命中 "GRANT" 本身。
            grant_match = re.search(r"GRANT\s+(.*?)\s+ON\b", joined, re.IGNORECASE)
            privileges = (grant_match.group(1) if grant_match else joined).upper()
            for keyword in _WRITE_KEYWORDS:
                if re.search(rf"\b{keyword}\b", privileges):
                    matched.append(keyword)
    if matched:
        return False, "具备写权限：" + ", ".join(sorted(set(matched)))
    return True, "授权中未发现写权限关键字"


def probe_readonly(engine: Engine, ds_type: str) -> tuple[bool, str]:
    """Run the dialect's read-only probe against a live connection."""
    normalized = _normalize_ds_type(ds_type)
    sql = READONLY_PROBE_SQL.get(normalized)
    if sql is None:
        return False, f"未定义 {ds_type!r} 的只读探针 SQL"
    with engine.connect() as conn:
        rows = [tuple(row) for row in conn.execute(text(sql))]
    return evaluate_readonly(normalized, rows)


ReadOnlyVerifier = Callable[[Engine, str], tuple[bool, str]]


@dataclass(frozen=True)
class DataSourceConnection:
    """A usable, audited connection to a data source."""

    datasource_id: int
    code: str
    ds_type: str
    purpose: ConnectionPurpose
    url: URL
    readonly: bool
    credential_id: int | None
    credential_version: int | None
    engine: Engine
    readonly_reason: str = ""
    _owns_engine: bool = field(default=True, repr=False, compare=False)

    def safe_url(self) -> str:
        """URL with the password masked — safe for logs and audit details."""
        return self.url.render_as_string()

    def secret_url(self) -> str:
        """URL including the password — only for handing to SQLAlchemy."""
        return self.url.render_as_string(hide_password=False)

    @contextmanager
    def connect(self) -> Iterator[Any]:
        with self.engine.connect() as conn:
            yield conn

    def close(self) -> None:
        if self._owns_engine:
            self.engine.dispose()


class ConnectionProvider:
    """Loads a datasource + active credential and hands out a connection."""

    def __init__(
        self,
        session: Session,
        *,
        cipher: CredentialCipher | None = None,
        verifier: ReadOnlyVerifier | None = None,
        audit_sink: Callable[[Any], None] | None = None,
        actor: str | None = None,
        engine_factory: Callable[[URL], Engine] = create_engine,
    ) -> None:
        self._session = session
        self._cipher = cipher
        self._verifier = verifier or probe_readonly
        self._audit_sink = audit_sink
        self._actor = actor
        self._engine_factory = engine_factory

    # -- internals ------------------------------------------------------
    def _cipher_or_default(self) -> CredentialCipher:
        if self._cipher is None:
            self._cipher = CredentialCipher()
        return self._cipher

    def _audit(
        self,
        datasource: Any | None,
        purpose: ConnectionPurpose,
        result: str,
        detail: dict[str, Any],
    ) -> None:
        if self._audit_sink is None:
            return
        self._audit_sink(
            {
                "action": AUDIT_ACTION,
                "result": result,
                "actor": self._actor,
                "tenant_id": getattr(datasource, "tenant_id", 0)
                if datasource is not None
                else 0,
                "entity_type": "datasource",
                "entity_fqn": getattr(datasource, "code", None)
                if datasource is not None
                else None,
                "detail": {**detail, "purpose": purpose.value},
            }
        )

    def _load_datasource(self, datasource_id: int) -> Any:
        from .storage.models_core import Datasource

        row = self._session.get(Datasource, datasource_id)
        if row is None or getattr(row, "deleted_at", None) is not None:
            raise DatasourceUnavailableError(
                f"数据源 {datasource_id} 不存在或已删除。"
            )
        return row

    @staticmethod
    def _check_capability(datasource: Any, purpose: ConnectionPurpose) -> None:
        if not datasource.enabled:
            raise PurposeNotAllowedError(
                f"数据源 {datasource.code} 已停用（enabled=false）。"
            )
        if purpose is ConnectionPurpose.METADATA and not datasource.scan_enabled:
            raise PurposeNotAllowedError(
                f"数据源 {datasource.code} 未开启扫描（scan_enabled=false）。"
            )
        if purpose is ConnectionPurpose.SAMPLE:
            if not datasource.sampling_enabled:
                raise PurposeNotAllowedError(
                    f"数据源 {datasource.code} 未开启采样（sampling_enabled=false）；"
                    "采样默认关闭，需运维显式授权（决策 Q7）。"
                )
            if not datasource.supports_sampling:
                raise PurposeNotAllowedError(
                    f"数据源 {datasource.code} 不支持采样（supports_sampling=false）。"
                )

    def _load_credential(self, datasource_id: int) -> Any:
        from sqlalchemy import select

        from .storage.models_core import DatasourceCredential

        stmt = (
            select(DatasourceCredential)
            .where(DatasourceCredential.datasource_id == datasource_id)
            .where(DatasourceCredential.is_active.is_(True))
            .order_by(DatasourceCredential.version.desc())
        )
        row = self._session.execute(stmt).scalars().first()
        if row is None:
            raise MissingCredentialError(
                f"数据源 {datasource_id} 没有启用中的凭据记录。"
            )
        return row

    # -- public API ------------------------------------------------------
    @contextmanager
    def acquire(
        self,
        datasource_id: int,
        purpose: ConnectionPurpose = ConnectionPurpose.METADATA,
        *,
        allow_write: bool = False,
        database: str | None = None,
        options: dict[str, Any] | None = None,
        verify_readonly: bool = True,
    ) -> Iterator[DataSourceConnection]:
        """Acquire a connection for ``purpose`` as a context manager."""
        purpose = ConnectionPurpose(purpose)
        datasource = None
        try:
            datasource = self._load_datasource(datasource_id)
            self._check_capability(datasource, purpose)
            credential = self._load_credential(datasource_id)
            password = self._cipher_or_default().decrypt_row(credential)
            url = build_url(
                datasource.ds_type,
                username=credential.username,
                password=password,
                host=datasource.host,
                port=datasource.port,
                database=database
                or (datasource.scan_config or {}).get("database"),
                options=options,
            )
        except ConnectionError as exc:
            self._audit(datasource, purpose, "denied", {"reason": str(exc)})
            raise

        engine = self._engine_factory(url)
        readonly = False
        reason = "not verified"
        if purpose is ConnectionPurpose.ADMIN or not verify_readonly:
            readonly = False
            reason = (
                "purpose=admin，跳过只读校验"
                if purpose is ADMIN
                else "已跳过只读校验"
            )
        else:
            readonly, reason = self._verifier(engine, datasource.ds_type)
            if not readonly and not allow_write:
                engine.dispose()
                self._audit(
                    datasource,
                    purpose,
                    "denied",
                    {
                        "reason": reason,
                        "credential_version": credential.version,
                        "url": url.render_as_string(),
                    },
                )
                raise WriteAccessError(
                    f"数据源 {datasource.code} 的连接具备写权限，"
                    f"拒绝用于 {purpose.value}：{reason}。"
                    "如确需使用，请改用只读账号或显式传入 allow_write=True。"
                )

        connection = DataSourceConnection(
            datasource_id=datasource.id,
            code=datasource.code,
            ds_type=datasource.ds_type,
            purpose=purpose,
            url=url,
            readonly=readonly,
            credential_id=credential.id,
            credential_version=credential.version,
            engine=engine,
            readonly_reason=reason,
        )
        self._audit(
            datasource,
            purpose,
            "ok",
            {
                "readonly": readonly,
                "readonly_reason": reason,
                "credential_version": credential.version,
                "url": connection.safe_url(),
                "allow_write": allow_write,
            },
        )
        try:
            yield connection
        finally:
            connection.close()
