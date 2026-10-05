"""Connector registry — maps ``ds_type`` to a source connector (L3 local).

Why this exists
---------------
``core.connectors`` (L1) owns the connector *implementations* and is an
upstream sync area; deciding which connector serves which ``ds_type`` is a
local concern, so the mapping lives here instead.

Why specs hold ``"module:Class"`` strings
-----------------------------------------
The same reason upstream OpenMetadata declares its ``ServiceSpec`` fields as
strings: the import is deferred until the datasource type is *actually*
scanned. A host without ``pymysql`` installed can still scan PostgreSQL — the
missing driver only surfaces (with an actionable message) when a MySQL
datasource is scanned. Importing the classes eagerly at module import would
turn an optional dependency into a hard one.

Adding a datasource
-------------------
1. **Built-in** — append one :class:`ConnectorSpec` to :data:`BUILTIN_SPECS`.
2. **External distribution** — ship a ``ConnectorSpec`` and expose it via the
   ``local_ingestion.connectors`` entry-point group, or point
   ``LOCAL_INGESTION_CONNECTOR_SPECS`` at ``"your.pkg:SPEC"``. Nothing in this
   project changes and nothing is rebuilt — ``pip install`` is enough, because
   :func:`get_spec` discovers external specs lazily on first lookup.
"""
from __future__ import annotations

import importlib
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Iterable, Optional, Tuple

from ..connections import DEFAULT_PORTS

logger = logging.getLogger(__name__)

#: Entry-point group external distributions use to publish connector specs.
ENTRY_POINT_GROUP = "local_ingestion.connectors"

#: Env var holding extra ``"module:ATTR"`` targets (comma separated).
ENV_SPECS = "LOCAL_INGESTION_CONNECTOR_SPECS"


class ConnectorRegistryError(Exception):
    """Base error for the connector registry."""


class UnknownConnectorError(ConnectorRegistryError):
    """No spec is registered for the requested ``ds_type``."""


class ConnectorImportError(ConnectorRegistryError):
    """A spec's ``module:Class`` target could not be imported."""


def _normalize(ds_type: str) -> str:
    return (ds_type or "").strip().lower()


@dataclass(frozen=True)
class ConnectorSpec:
    """Declarative wiring for one datasource type.

    Attributes:
        ds_types: ``ds_type`` values served by this spec (first is canonical).
        connector: ``"module:Class"`` resolving to a ``SourceConnector``.
        connection: ``"module:Class"`` resolving to a connection schema model.
        extras: Optional extra that must be installed (drives the error hint).
        experimental: Connector exists but has never been exercised against a
            live instance; scanning logs a warning so the gap stays visible.
        build: ``(conn, database, datasource, connection_cls) -> connection``.
            Defaults to :func:`_default_build_connection`, which is enough for
            anything reachable from a SQLAlchemy URL.
    """

    ds_types: Tuple[str, ...]
    connector: str
    connection: str
    extras: Optional[str] = None
    experimental: bool = False
    build: Optional[Callable[..., Any]] = None

    @property
    def canonical(self) -> str:
        return _normalize(self.ds_types[0]) if self.ds_types else ""

    def label(self) -> str:
        return self.extras or self.canonical


# --------------------------------------------------------------- builders
def _default_build_connection(
    conn: Any,
    database: Optional[str],
    datasource: Any,
    connection_cls: Any,
) -> Any:
    """Build a connection config from the acquired URL (host/port/auth/db)."""
    url = conn.url
    ds_type = _normalize(getattr(datasource, "ds_type", "") or "")
    port = url.port or DEFAULT_PORTS.get(ds_type)
    host = url.host or ""
    return connection_cls(
        hostPort=f"{host}:{port}" if port else host,
        username=url.username,
        password=url.password,
        database=database or url.database,
    )


def _snowflake_build_connection(
    conn: Any,
    database: Optional[str],
    datasource: Any,
    connection_cls: Any,
) -> Any:
    """Snowflake needs ``account``/``warehouse``/``role``, not host/port.

    ``account`` is the URL host (``snowflake://user:pw@<account>/db``);
    ``warehouse``/``role`` travel as URL query params (see
    :func:`~local_ingestion.platform.connections.build_url` options).
    """
    url = conn.url
    query = {str(k): str(v) for k, v in (url.query or {}).items()}
    return connection_cls(
        account=url.host or "",
        username=url.username,
        password=url.password,
        database=database or url.database,
        warehouse=query.get("warehouse"),
        role=query.get("role"),
    )


def connection_options(datasource: Any) -> Optional[Dict[str, str]]:
    """Extra URL query params for a datasource (``scan_config.connection_options``).

    This is how dialect-specific extras reach the connection — Snowflake's
    ``warehouse``/``role`` for instance — without widening the datasource table.
    """
    cfg = getattr(datasource, "scan_config", None) or {}
    raw = cfg.get("connection_options") or cfg.get("options")
    if not isinstance(raw, dict) or not raw:
        return None
    return {str(k): str(v) for k, v in raw.items()}


# ------------------------------------------------------------ built-ins
_POSTGRES = ConnectorSpec(
    ds_types=("postgres", "postgresql"),
    connector="local_ingestion.core.connectors.postgres:PostgresSourceConnector",
    connection="local_ingestion.schema.service.connection:PostgresConnection",
)

_MYSQL = ConnectorSpec(
    ds_types=("mysql", "mariadb"),
    connector="local_ingestion.core.connectors.mysql:MySQLSourceConnector",
    connection="local_ingestion.schema.service.connection:MySQLConnection",
    extras="mysql",
    experimental=True,
)

_SNOWFLAKE = ConnectorSpec(
    ds_types=("snowflake",),
    connector="local_ingestion.core.connectors.snowflake:SnowflakeSourceConnector",
    connection="local_ingestion.schema.service.connection:SnowflakeConnection",
    extras="snowflake",
    experimental=True,
    build=_snowflake_build_connection,
)

BUILTIN_SPECS: Tuple[ConnectorSpec, ...] = (_POSTGRES, _MYSQL, _SNOWFLAKE)


# ------------------------------------------------------------- registry
_SPECS: Dict[str, ConnectorSpec] = {}
_EXTERNAL_LOADED = False
_WARNED_EXPERIMENTAL: set[str] = set()


def _hint(extras: Optional[str], what: str, target: str, exc: BaseException) -> str:
    base = f"无法加载连接器 {what}（{target}）：{exc}"
    if extras:
        return f'{base}\n请安装可选依赖：pip install "local-ingestion[{extras}]"'
    return base


def resolve(target: str, *, what: str, extras: Optional[str] = None) -> Any:
    """Import ``"module:Class"`` and return the attribute.

    Raises:
        ConnectorImportError: with an actionable hint when the failure looks
            like a missing optional dependency.
    """
    module_name, sep, attr = target.partition(":")
    if not sep or not module_name or not attr:
        raise ConnectorImportError(
            f"连接器配置 {what} 必须形如 'module:Class'，实际为 {target!r}"
        )
    try:
        module = importlib.import_module(module_name)
    except BaseException as exc:  # noqa: BLE001 - surfaced as ConnectorImportError
        raise ConnectorImportError(_hint(extras, what, target, exc)) from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise ConnectorImportError(
            f"模块 {module_name!r} 中没有 {attr!r}（连接器配置 {what}）"
        ) from exc


def register(spec: ConnectorSpec, *, override: bool = False) -> None:
    """Register ``spec`` under each of its ``ds_types``.

    Args:
        override: Replace an existing registration instead of raising.
    """
    if not spec.ds_types:
        raise ConnectorRegistryError("ConnectorSpec.ds_types 不能为空")
    for ds_type in spec.ds_types:
        key = _normalize(ds_type)
        current = _SPECS.get(key)
        if current is not None and current is not spec and not override:
            raise ConnectorRegistryError(
                f"ds_type={ds_type!r} 已注册给 {current.connector}；"
                "如需替换请传 override=True"
            )
        _SPECS[key] = spec
    logger.debug("connector registered", ds_types=list(spec.ds_types))


def unregister(ds_type: str) -> bool:
    return _SPECS.pop(_normalize(ds_type), None) is not None


def reset_to_builtins() -> None:
    """Drop every registration (including external ones) and re-add built-ins.

    Exposed for tests and for hot-reloading the connector set.
    """
    _SPECS.clear()
    _WARNED_EXPERIMENTAL.clear()
    global _EXTERNAL_LOADED
    _EXTERNAL_LOADED = False
    for spec in BUILTIN_SPECS:
        register(spec)


def load_external(force: bool = False) -> None:
    """Discover specs from entry-points and ``LOCAL_INGESTION_CONNECTOR_SPECS``.

    Idempotent and non-fatal: a broken plugin must not stop every other
    datasource from being scanned, so failures are logged and skipped.
    """
    global _EXTERNAL_LOADED
    if _EXTERNAL_LOADED and not force:
        return
    _EXTERNAL_LOADED = True

    for target in _entry_point_targets() + _env_targets():
        try:
            obj = resolve(target, what="external")
        except ConnectorRegistryError as exc:
            logger.error("connector plugin load failed: %s", exc)
            continue
        for spec in _as_specs(obj, target):
            try:
                register(spec, override=True)
            except ConnectorRegistryError as exc:
                logger.error("connector plugin register failed: %s", exc)


def _entry_point_targets() -> list[str]:
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover - Python < 3.10
        return []
    try:
        eps = entry_points()
        selected = (
            eps.select(group=ENTRY_POINT_GROUP)
            if hasattr(eps, "select")
            else eps.get(ENTRY_POINT_GROUP, [])
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("entry point scan failed: %s", exc)
        return []
    # ``EntryPoint.value`` is already the "module:attr" string we need.
    return [ep.value for ep in selected if getattr(ep, "value", None)]


def _env_targets() -> list[str]:
    raw = os.getenv(ENV_SPECS, "") or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def _as_specs(obj: Any, target: str) -> Iterable[ConnectorSpec]:
    if isinstance(obj, ConnectorSpec):
        return [obj]
    if isinstance(obj, (list, tuple)):
        return [item for item in obj if isinstance(item, ConnectorSpec)]
    if callable(obj):
        obj = obj()
        return _as_specs(obj, target)
    logger.error("连接器插件 %s 未返回 ConnectorSpec（实际 %r）", target, type(obj))
    return []


# ---------------------------------------------------------------- lookups
def get_spec(ds_type: str) -> ConnectorSpec:
    """Return the spec for ``ds_type``.

    Raises:
        UnknownConnectorError: when nothing is registered for the type.
    """
    load_external()
    key = _normalize(ds_type)
    spec = _SPECS.get(key)
    if spec is None:
        raise UnknownConnectorError(
            f"ds_type={ds_type!r} 暂无连接器支持（已注册：{sorted(supported_ds_types())}）"
        )
    return spec


def make_connector(ds_type: str) -> Any:
    """Instantiate the source connector registered for ``ds_type``."""
    spec = get_spec(ds_type)
    if spec.experimental and spec.canonical not in _WARNED_EXPERIMENTAL:
        _WARNED_EXPERIMENTAL.add(spec.canonical)
        logger.warning(
            "connector %s is experimental: never exercised against a live instance",
            spec.canonical,
        )
    cls = resolve(spec.connector, what=f"{spec.canonical} connector", extras=spec.extras)
    return cls()


def build_connection(
    ds_type: str,
    conn: Any,
    database: Optional[str],
    datasource: Any = None,
) -> Any:
    """Translate an acquired L3 connection into an L1 connector config."""
    spec = get_spec(ds_type)
    connection_cls = resolve(
        spec.connection, what=f"{spec.canonical} connection", extras=spec.extras
    )
    builder = spec.build or _default_build_connection
    return builder(conn, database, datasource, connection_cls)


def supported_ds_types() -> FrozenSet[str]:
    """Every ``ds_type`` with a connector right now (built-in + external)."""
    load_external()
    return frozenset(_SPECS)


def known_specs() -> Dict[str, ConnectorSpec]:
    load_external()
    return dict(_SPECS)


reset_to_builtins()
