"""Connector registry: dispatch, lazy imports and plugin discovery.

These pin the two properties that make the registry worth having:

* adding a datasource is **one spec**, not edits scattered through ScanService;
* a datasource's driver is imported **only when that datasource is scanned**,
  so a host without the optional extras can still scan everything else.
"""
from __future__ import annotations

import logging
import sys
import types

import pytest
from sqlalchemy.engine import URL

import local_ingestion.platform.connectors.registry as registry
from local_ingestion.platform.connectors import (
    BUILTIN_SPECS,
    ConnectorImportError,
    ConnectorRegistryError,
    ConnectorSpec,
    UnknownConnectorError,
    build_connection,
    connection_options,
    get_spec,
    load_external,
    make_connector,
    register,
    reset_to_builtins,
    supported_ds_types,
)
from local_ingestion.platform.scan.service import ScanService, UnsupportedDatasourceError


@pytest.fixture(autouse=True)
def _clean_registry():
    """Every test starts from built-ins only (no leaked plugin registrations)."""
    reset_to_builtins()
    yield
    reset_to_builtins()


def _ds(ds_type: str = "postgres", scan_config: dict | None = None):
    return types.SimpleNamespace(
        ds_type=ds_type,
        scan_config={"database": "db"} if scan_config is None else scan_config,
        deleted_at=None,
        code="ds1",
    )


class _Conn:
    """Stands in for the object ``ConnectionProvider.acquire`` yields."""

    def __init__(self, url: URL) -> None:
        self.url = url


# ------------------------------------------------------------- dispatch
def test_builtin_types_are_registered():
    assert {"postgres", "postgresql", "mysql", "mariadb", "snowflake"} <= set(
        supported_ds_types()
    )


def test_lookup_is_case_and_space_insensitive():
    assert get_spec("  POSTGRES ") is get_spec("postgres")
    assert get_spec("MariaDB") is get_spec("mysql")


def test_unknown_type_says_what_is_supported():
    with pytest.raises(UnknownConnectorError) as exc:
        get_spec("db2")
    message = str(exc.value)
    assert "db2" in message and "postgres" in message


def test_make_connector_returns_a_real_connector():
    assert type(make_connector("postgres")).__name__ == "PostgresSourceConnector"


def test_mysql_and_snowflake_are_marked_experimental():
    """They are wired but never exercised against a live instance."""
    assert get_spec("mysql").experimental
    assert get_spec("snowflake").experimental
    assert not get_spec("postgres").experimental


def test_duplicate_registration_is_rejected_without_override():
    spec = ConnectorSpec(
        ds_types=("postgres",), connector="m:Conn", connection="m:Conn"
    )
    with pytest.raises(ConnectorRegistryError):
        register(spec)
    register(spec, override=True)
    assert get_spec("postgres") is spec


def test_override_registration_can_replace_builtin():
    spec = ConnectorSpec(ds_types=("postgres",), connector="m:Conn", connection="m:Conn")
    register(spec, override=True)
    assert get_spec("postgres") is spec


# -------------------------------------------------- lazy / optional imports
def test_registry_does_not_eagerly_import_connectors():
    """Specs are strings, so importing the registry pulls in no connector."""
    names = {v.__name__ for v in vars(registry).values() if isinstance(v, type)}
    assert not {
        "PostgresSourceConnector",
        "MySQLSourceConnector",
        "SnowflakeSourceConnector",
    } & names
    for spec in BUILTIN_SPECS:
        assert isinstance(spec.connector, str) and ":" in spec.connector


def test_missing_optional_driver_gets_an_install_hint():
    spec = ConnectorSpec(
        ds_types=("noodb",),
        connector="totally_absent_pkg:Connector",
        connection="totally_absent_pkg:Conn",
        extras="noodb",
    )
    register(spec, override=True)
    with pytest.raises(ConnectorImportError) as exc:
        make_connector("noodb")
    assert 'pip install "local-ingestion[noodb]"' in str(exc.value)


def test_malformed_target_is_reported_clearly():
    spec = ConnectorSpec(ds_types=("bad",), connector="no_colon_here", connection="m:C")
    register(spec, override=True)
    with pytest.raises(ConnectorImportError) as exc:
        make_connector("bad")
    assert "module:Class" in str(exc.value)


# -------------------------------------------------------- plugin discovery
def test_external_spec_is_loaded_from_env(tmp_path, monkeypatch):
    """Installing a distribution is enough — no change to this project."""
    (tmp_path / "extconn_plugin.py").write_text(
        "from local_ingestion.platform.connectors import ConnectorSpec\n"
        "class FakeConnector:\n"
        "    pass\n"
        "SPEC = ConnectorSpec(\n"
        "    ds_types=('clickhouse',),\n"
        "    connector='extconn_plugin:FakeConnector',\n"
        "    connection='local_ingestion.schema.service.connection:PostgresConnection',\n"
        ")\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("LOCAL_INGESTION_CONNECTOR_SPECS", "extconn_plugin:SPEC")
    try:
        load_external(force=True)
        assert "clickhouse" in supported_ds_types()
        assert type(make_connector("clickhouse")).__name__ == "FakeConnector"
    finally:
        sys.modules.pop("extconn_plugin", None)


def test_entry_points_are_discovered(monkeypatch):
    """The ``pip install`` path: a distribution publishes a spec entry-point."""
    spec = ConnectorSpec(ds_types=("clickhouse",), connector="x:C", connection="x:C")

    class _EP:
        value = "demo_pkg.specs:SPEC"

    class _WithSelect(list):
        def select(self, group):
            return self if group == registry.ENTRY_POINT_GROUP else []

    import importlib.metadata as metadata

    monkeypatch.setattr(metadata, "entry_points", lambda: _WithSelect([_EP()]))
    # Already-imported modules are returned as-is, so no real package is needed.
    monkeypatch.setitem(
        sys.modules, "demo_pkg.specs", types.SimpleNamespace(SPEC=spec)
    )
    load_external(force=True)
    assert get_spec("clickhouse") is spec


def test_entry_points_without_select_api(monkeypatch):
    """Older ``entry_points()`` returns a plain mapping instead of a selector."""
    spec = ConnectorSpec(ds_types=("db2",), connector="x:C", connection="x:C")

    class _EP:
        value = "demo_pkg.specs:SPEC"

    import importlib.metadata as metadata

    monkeypatch.setattr(
        metadata, "entry_points", lambda: {registry.ENTRY_POINT_GROUP: [_EP()]}
    )
    monkeypatch.setitem(
        sys.modules, "demo_pkg.specs", types.SimpleNamespace(SPEC=spec)
    )
    load_external(force=True)
    assert get_spec("db2") is spec


def test_broken_plugin_does_not_break_other_types(monkeypatch):
    monkeypatch.setenv("LOCAL_INGESTION_CONNECTOR_SPECS", "no_such_plugin_module:SPEC")
    load_external(force=True)  # must not raise
    assert "postgres" in supported_ds_types()


def test_reset_drops_external_registrations(monkeypatch):
    spec = ConnectorSpec(ds_types=("db2",), connector="m:Conn", connection="m:Conn")
    register(spec, override=True)
    assert "db2" in supported_ds_types()
    reset_to_builtins()
    assert "db2" not in supported_ds_types()


# ------------------------------------------------------- connection builders
def test_default_builder_uses_dialect_default_port():
    url = URL.create(
        "postgresql+psycopg2", username="u", password="p", host="h", database="db"
    )
    conn_config = build_connection("postgres", _Conn(url), None, _ds("postgres"))
    assert conn_config.hostPort == "h:5432"
    assert (conn_config.username, conn_config.password) == ("u", "p")
    assert conn_config.database == "db"


def test_database_argument_overrides_the_url():
    url = URL.create("postgresql+psycopg2", username="u", password="p", host="h")
    conn_config = build_connection("postgres", _Conn(url), "other", _ds("postgres"))
    assert conn_config.database == "other"


def test_mysql_builder_uses_mysql_default_port():
    url = URL.create("mysql+pymysql", username="u", password="p", host="h", database="db")
    conn_config = build_connection("mysql", _Conn(url), None, _ds("mysql"))
    assert conn_config.hostPort == "h:3306"


def test_snowflake_builder_reads_account_and_query_params():
    """Snowflake has no host/port: account is the host, warehouse/role are query."""
    url = URL.create(
        "snowflake",
        username="u",
        password="p",
        host="acct",
        database="db",
        query={"warehouse": "wh", "role": "r"},
    )
    conn_config = build_connection("snowflake", _Conn(url), None, _ds("snowflake"))
    assert conn_config.account == "acct"
    assert conn_config.warehouse == "wh"
    assert conn_config.role == "r"
    assert conn_config.database == "db"


def test_connection_options_come_from_scan_config():
    assert connection_options(_ds("postgres", {"connection_options": {"sslmode": "require"}})) == {
        "sslmode": "require"
    }
    assert connection_options(_ds("postgres", {"options": {"role": "r"}})) == {"role": "r"}
    assert connection_options(_ds("postgres", {})) is None


# ------------------------------------------------------------ observability
def test_experimental_connector_warns_once(caplog, monkeypatch):
    monkeypatch.setattr(registry, "_WARNED_EXPERIMENTAL", set())
    with caplog.at_level(logging.WARNING):
        make_connector("mysql")
        make_connector("mysql")
    warnings = [r for r in caplog.records if "experimental" in r.getMessage()]
    assert len(warnings) == 1


# ---------------------------------------------------------- ScanService wiring
def test_scan_rejects_a_type_without_a_connector():
    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, model, pk):
            return _ds("db2")

    with pytest.raises(UnsupportedDatasourceError):
        ScanService(lambda: _Session()).run_scan(1)
