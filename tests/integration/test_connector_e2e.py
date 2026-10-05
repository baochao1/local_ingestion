"""Real connector end-to-end: live source database -> catalog -> change detection.

Skipped unless ``PG_TEST=1``. Unlike :mod:`tests.integration.test_pg_integration`,
which seeds a synthetic catalog with ``seed_catalog``, this module scans a *real*,
live PostgreSQL database through the full L1 chain::

    ConnectionProvider (read-only guard FR-1.5 + audit)
      -> PostgresSourceConnector (live introspection)
      -> DatabasePipeline        (dialect-backed transform hook)
      -> PostgresSink            (idempotent upsert into catalog_*)
      -> SchemaDiffer            (real schema evolution vs. previous scan)

Each test gets its **own** source database, because ``catalog_*`` rows are unique
by ``fqn`` alone (partial unique index), so two datasources pointing at the same
source would collide on upsert.

What this module proves (and the synthetic tests cannot):

* The extraction SQL actually runs against a modern PostgreSQL **17** server.
* Scanning works with a least-privilege account: registering a datasource whose
  credential holds write privileges is rejected (FR-1.5).
* Re-scanning is idempotent (no duplicate/duplicated rows).
* A real ``ALTER TABLE``/``CREATE TABLE`` on the source surfaces as real
  ``column_added`` / ``type_changed`` / ``table_added`` changes.
"""
from __future__ import annotations

import os

# Settings validates CREDENTIAL_ENCRYPTION_KEY on first use, so make the module
# self-contained before any local_ingestion import pulls in platform.config.
os.environ.setdefault("CREDENTIAL_ENCRYPTION_KEY", "e2e-integration-test-key-0000000")

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker

from local_ingestion.platform.datasource.repository import SqlDatasourceRepository
from local_ingestion.platform.datasource.service import (
    ConflictError,
    DataSourceService,
    WriteAccessDeniedError,
)
from local_ingestion.platform.catalog.service import OverviewService
from local_ingestion.platform.catalog.source import SqlCatalogStatsSource
from local_ingestion.platform.changes.models import ChangeEventInput
from local_ingestion.platform.changes.repository import SqlChangeRepository
from local_ingestion.platform.changes.service import ChangeConfirmService
from local_ingestion.platform.orchestration.audit import AuditService, InMemoryAuditSink
from local_ingestion.platform.orchestration.lock import ProcessLockProvider
from local_ingestion.platform.orchestration.models import (
    TaskSpec,
    TaskStatus,
    TriggerType,
)
from local_ingestion.platform.orchestration.registry import (
    DependencyRegistry,
    HandlerRegistry,
)
from local_ingestion.platform.orchestration.service import TaskService
from local_ingestion.platform.orchestration.store import InMemoryTaskRunStore
from local_ingestion.platform.scan import ScanService, make_scan_handler
from local_ingestion.platform.storage.models_core import (
    CatalogColumn,
    CatalogTable,
    Datasource,
)
from local_ingestion.platform.storage.schema import reset_schema
from local_ingestion.platform.versioning.adapter import build_catalog_state
from local_ingestion.platform.versioning.classify import ImpactClassifier
from local_ingestion.platform.versioning.diff import SchemaDiffer

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)

DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"

_SOURCE_USER = "li_e2e_ro"
_SOURCE_PASSWORD = "li_e2e_ro_pwd"

_SOURCE_DDL = [
    """
    CREATE TABLE customers (
        id integer PRIMARY KEY,
        name varchar(64) NOT NULL,
        email varchar(128)
    )
    """,
    "COMMENT ON COLUMN customers.email IS 'customer contact email'",
    """
    CREATE TABLE orders (
        id bigint PRIMARY KEY,
        customer_id integer NOT NULL,
        amount numeric(12,2) NOT NULL,
        created_at timestamp NOT NULL DEFAULT now()
    )
    """,
]


# Graded level -> persisted change_event.severity
_LEVEL_TO_SEVERITY = {
    "P0": "breaking",
    "P1": "breaking",
    "P2": "structural",
    "P3": "descriptive",
}


def _base_url():
    return make_url(os.getenv("DATABASE_URL", DEFAULT_URL))


def _url_for(database: str) -> str:
    """Connection string for ``database`` on the same server (secrets included)."""
    return _base_url().set(database=database).render_as_string(hide_password=False)


# --------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def engine():
    url = os.getenv("DATABASE_URL", DEFAULT_URL)
    eng = create_engine(url, future=True)
    reset_schema(eng)  # clean slate + test partitions
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def source(request):
    """Create a throwaway source database with real business tables.

    The scanning queries run as a least-privilege role so the FR-1.5 read-only
    policy is exercised end-to-end, not bypassed.
    """
    base = _base_url()
    database = f"li_src_{request.node.name}"[:63]
    admin_url = base.set(database="postgres").render_as_string(hide_password=False)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": _SOURCE_USER}
            ).scalar()
            if not exists:
                conn.execute(
                    text(
                        f"CREATE ROLE {_SOURCE_USER} LOGIN PASSWORD '{_SOURCE_PASSWORD}'"
                    )
                )
            conn.execute(text(f"DROP DATABASE IF EXISTS {database} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {database}"))

        src = create_engine(_url_for(database), future=True)
        try:
            with src.begin() as conn:
                for stmt in _SOURCE_DDL:
                    conn.execute(text(stmt))
                # Least-privilege: CONNECT + read only. Future tables created by
                # this owner inherit SELECT through ALTER DEFAULT PRIVILEGES, so
                # new tables created later in the test are still scannable.
                conn.execute(text(f"GRANT CONNECT ON DATABASE {database} TO {_SOURCE_USER}"))
                conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {_SOURCE_USER}"))
                conn.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {_SOURCE_USER}"))
                conn.execute(
                    text(
                        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                        f"GRANT SELECT ON TABLES TO {_SOURCE_USER}"
                    )
                )
        finally:
            src.dispose()

        yield database
    finally:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {database} WITH (FORCE)"))
        admin.dispose()


# ---------------------------------------------------------------------- helpers
def _register(session_factory, *, code: str, database: str) -> int:
    """Register the source as a datasource and return its id."""
    service = DataSourceService(SqlDatasourceRepository(session_factory))
    service.register(
        {
            "code": code,
            "name": f"E2E source {code}",
            "ds_type": "postgres",
            "host": _base_url().host or "localhost",
            "port": _base_url().port or 5432,
            "username": _SOURCE_USER,
            "password": _SOURCE_PASSWORD,
            "scan_config": {"database": database},
        },
        actor="connector-e2e",
    )
    with session_factory() as s:
        ds = s.query(Datasource).filter(Datasource.code == code).first()
        return ds.id


def _column_rows(session_factory, datasource_id: int):
    """Return [(table_name, Column)] ordered by table + ordinal position."""
    stmt = (
        select(
            CatalogTable.name.label("table_name"),
            CatalogColumn.name.label("column_name"),
            CatalogColumn.ordinal_position,
            CatalogColumn.data_type,
            CatalogColumn.data_type_display,
            CatalogColumn.data_length,
            CatalogColumn.nullable,
            CatalogColumn.default_value,
            CatalogColumn.description,
        )
        .join(CatalogTable, CatalogTable.id == CatalogColumn.table_id)
        .where(
            CatalogColumn.datasource_id == datasource_id,
            CatalogColumn.deleted_at.is_(None),
        )
        .order_by(CatalogTable.name, CatalogColumn.ordinal_position)
    )
    with session_factory() as s:
        return list(s.execute(stmt))


def _counts(session_factory, datasource_id: int):
    with session_factory() as s:
        tables = s.scalar(
            select(func.count())
            .select_from(CatalogTable)
            .where(
                CatalogTable.datasource_id == datasource_id,
                CatalogTable.deleted_at.is_(None),
            )
        )
        columns = s.scalar(
            select(func.count())
            .select_from(CatalogColumn)
            .where(
                CatalogColumn.datasource_id == datasource_id,
                CatalogColumn.deleted_at.is_(None),
            )
        )
    return tables, columns


def _catalog_state(session_factory, datasource_id: int):
    with session_factory() as s:
        tables = (
            s.query(CatalogTable)
            .filter(
                CatalogTable.deleted_at.is_(None),
                CatalogTable.datasource_id == datasource_id,
            )
            .order_by(CatalogTable.fqn)
            .all()
        )
        cols = (
            s.query(CatalogColumn)
            .filter(
                CatalogColumn.deleted_at.is_(None),
                CatalogColumn.datasource_id == datasource_id,
            )
            .all()
        )
        by_table: dict = {}
        for c in cols:
            by_table.setdefault(c.table_id, []).append(c)
        return build_catalog_state(tables, by_table)


def _mutate_source(database: str) -> None:
    """Apply real DDL to the live source database."""
    eng = create_engine(_url_for(database), future=True)
    try:
        with eng.begin() as conn:
            conn.execute(text("ALTER TABLE customers ADD COLUMN phone varchar(32)"))
            conn.execute(text("ALTER TABLE customers ALTER COLUMN email TYPE text"))
            conn.execute(
                text(
                    "CREATE TABLE order_items ("
                    " id bigint PRIMARY KEY,"
                    " order_id bigint NOT NULL,"
                    " sku varchar(32),"
                    " qty integer NOT NULL)"
                )
            )
    finally:
        eng.dispose()


def _drop_from_source(database: str) -> None:
    """Drop a column and a whole table on the live source database."""
    eng = create_engine(_url_for(database), future=True)
    try:
        with eng.begin() as conn:
            conn.execute(text("ALTER TABLE customers DROP COLUMN email"))
            conn.execute(text("DROP TABLE orders"))
    finally:
        eng.dispose()


def _drop_orders(database: str) -> None:
    eng = create_engine(_url_for(database), future=True)
    try:
        with eng.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS orders"))
    finally:
        eng.dispose()


def _add_second_schema(database: str) -> None:
    """Add a second schema so partial (filtered) scans have an out-of-scope side."""
    eng = create_engine(_url_for(database), future=True)
    try:
        with eng.begin() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS sales"))
            conn.execute(
                text("CREATE TABLE IF NOT EXISTS sales.deals ("
                     " id bigint PRIMARY KEY,"
                     " title text)")
            )
    finally:
        eng.dispose()


def _drop_orders_and_deals(database: str) -> None:
    eng = create_engine(_url_for(database), future=True)
    try:
        with eng.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS orders"))
            conn.execute(text("DROP TABLE IF EXISTS sales.deals"))
    finally:
        eng.dispose()


def _active_table_fqns(session_factory, ds_id: int) -> set:
    """FQNs still visible in the catalog (``deleted_at IS NULL``)."""
    with session_factory() as s:
        rows = s.execute(
            select(CatalogTable.fqn).where(
                CatalogTable.datasource_id == ds_id,
                CatalogTable.deleted_at.is_(None),
            )
        ).all()
    return {fqn for (fqn,) in rows}


# ------------------------------------------------------------------------ tests
def test_scan_persists_real_catalog(engine, session_factory, source):
    """A real scan writes faithful metadata into catalog_*."""
    ds_id = _register(session_factory, code="e2e_conn_scan", database=source)

    result = ScanService(session_factory).run_scan(ds_id)

    assert result.ok, result.errors
    # The connection really was read-only (FR-1.5), not just declared.
    assert result.readonly is True, result.readonly_reason
    assert result.database == source
    assert result.tables_processed == 2
    assert result.tables_failed == 0

    with session_factory() as s:
        tables = (
            s.query(CatalogTable)
            .filter(
                CatalogTable.deleted_at.is_(None), CatalogTable.datasource_id == ds_id
            )
            .all()
        )
        by_name = {t.name: t for t in tables}
        assert set(by_name) == {"customers", "orders"}
        assert f"{source}.public.customers" in {t.fqn for t in tables}
        assert by_name["customers"].table_type == "TABLE"
        assert by_name["customers"].column_count == 3
        assert by_name["orders"].column_count == 4
        assert by_name["customers"].struct_hash

    rows = _column_rows(session_factory, ds_id)
    columns = {(r.table_name, r.column_name): r for r in rows}

    assert [r.column_name for r in rows if r.table_name == "customers"] == [
        "id",
        "name",
        "email",
    ]
    assert [r.column_name for r in rows if r.table_name == "orders"] == [
        "id",
        "customer_id",
        "amount",
        "created_at",
    ]

    # Type fidelity straight from the live catalog.
    assert columns[("customers", "name")].data_type_display == "character varying(64)"
    assert columns[("customers", "name")].data_length == 64
    assert columns[("orders", "amount")].data_type_display == "numeric(12,2)"

    # Nullability, comments and defaults are really extracted.
    assert columns[("customers", "id")].nullable is False
    assert columns[("customers", "email")].nullable is True
    assert columns[("customers", "email")].description == "customer contact email"
    assert "now()" in (columns[("orders", "created_at")].default_value or "")

    # Every column was classified (no UNKNOWN leaking into the catalog).
    assert all(r.data_type for r in rows)
    assert {r.data_type for r in rows} & {"UNKNOWN", ""} == set()


def test_rescan_is_idempotent(engine, session_factory, source):
    """Re-running a scan must not duplicate or lose rows."""
    ds_id = _register(session_factory, code="e2e_conn_idem", database=source)
    scan = ScanService(session_factory)

    first = scan.run_scan(ds_id)
    first_counts = _counts(session_factory, ds_id)

    second = scan.run_scan(ds_id)
    second_counts = _counts(session_factory, ds_id)

    assert first.tables_processed == second.tables_processed == 2
    assert first_counts == second_counts == (2, 7)

    with session_factory() as s:
        ds = s.get(Datasource, ds_id)
        assert ds.last_scan_status == "success"
        assert ds.last_scan_at is not None
        assert ds.last_error is None


def test_rescan_detects_live_schema_evolution(engine, session_factory, source):
    """Real DDL on the source surfaces as real catalog changes."""
    ds_id = _register(session_factory, code="e2e_conn_evolve", database=source)
    scan = ScanService(session_factory)

    assert scan.run_scan(ds_id).ok
    baseline = _catalog_state(session_factory, ds_id)
    assert len(baseline.tables) == 2

    _mutate_source(source)

    result = scan.run_scan(ds_id)
    assert result.ok, result.errors
    assert result.tables_processed == 3

    current = _catalog_state(session_factory, ds_id)
    diff = SchemaDiffer().diff(baseline, current, datasource_id=ds_id)

    added_tables = [
        c.fqn for c in diff.table_changes if c.change_type == "table_added"
    ]
    assert any("order_items" in fqn for fqn in added_tables)

    added_columns = {
        c.column for c in diff.column_changes if c.change_type == "column_added"
    }
    assert "phone" in added_columns

    type_changes = {
        c.column for c in diff.column_changes if c.change_type == "type_changed"
    }
    assert "email" in type_changes

    # Nothing regressed: the pre-existing tables were matched, not re-created.
    assert not diff.tables_removed
    assert not diff.tables_renamed
    assert len(_catalog_state(session_factory, ds_id).tables) == 3


def test_rescan_detects_removed_entities(engine, session_factory, source):
    """Dropping a column/table on the source is detected as removal, not amnesia.

    This is the change that the previous sink left invisible: vanished entities
    were never soft-deleted, so a re-scan simply kept stale catalog rows and the
    diff reported nothing.
    """
    ds_id = _register(session_factory, code="e2e_conn_removed", database=source)
    scan = ScanService(session_factory)

    assert scan.run_scan(ds_id).ok
    baseline = _catalog_state(session_factory, ds_id)
    assert len(baseline.tables) == 2

    _drop_from_source(source)

    result = scan.run_scan(ds_id)
    assert result.ok, result.errors
    assert result.tables_processed == 1  # only `customers` remains

    current = _catalog_state(session_factory, ds_id)
    diff = SchemaDiffer().diff(baseline, current, datasource_id=ds_id)

    assert any("orders" in fqn for fqn in diff.tables_removed)
    assert "email" in {
        c.column for c in diff.column_changes if c.change_type == "column_removed"
    }

    # The catalog really dropped them (soft-deleted), not just the diff view.
    active = _active_table_fqns(session_factory, ds_id)
    assert not any(fqn.endswith("public.orders") for fqn in active)


def test_mark_deleted_switch_gates_removal(engine, session_factory, source):
    """``mark_deleted_tables`` must actually gate the behaviour, end to end."""
    ds_id = _register(session_factory, code="e2e_conn_switch", database=source)
    scan = ScanService(session_factory)
    assert scan.run_scan(ds_id).ok

    _drop_orders(source)

    # Switch off: vanished entities are retained (history preserved).
    off = scan.run_scan(ds_id, mark_deleted=False)
    assert off.ok, off.errors
    assert any(
        fqn.endswith("public.orders") for fqn in _active_table_fqns(session_factory, ds_id)
    )

    # Switch on: the same scan now reconciles them away.
    on = scan.run_scan(ds_id, mark_deleted=True)
    assert on.ok, on.errors
    assert not any(
        fqn.endswith("public.orders") for fqn in _active_table_fqns(session_factory, ds_id)
    )


def test_partial_scan_keeps_out_of_scope_entities(engine, session_factory, source):
    """A filtered scan must not read "not scanned" as "deleted".

    Deletion-marking is confined to the schemas a scan actually visited, so
    scanning only ``public`` leaves other schemas' rows alone even when they are
    equally gone from the source.
    """
    ds_id = _register(session_factory, code="e2e_conn_scope", database=source)
    scan = ScanService(session_factory)
    _add_second_schema(source)

    assert scan.run_scan(ds_id).ok
    assert len(_active_table_fqns(session_factory, ds_id)) == 3

    _drop_orders_and_deals(source)

    result = scan.run_scan(ds_id, schemas=["public"])
    assert result.ok, result.errors

    active = _active_table_fqns(session_factory, ds_id)
    assert not any(fqn.endswith("public.orders") for fqn in active)  # in scope
    assert any(fqn.endswith("sales.deals") for fqn in active)        # out of scope


def test_concurrent_register_surfaces_conflict(engine, session_factory, source):
    """The loser of a code race gets ConflictError, not a raw DB error.

    ``uq_datasource_code`` is partial (``WHERE deleted_at IS NULL``) and the
    existence pre-check is a separate read, so a genuine race can only be
    caught by the INSERT. It must surface as a domain error — and leave nothing
    half-registered behind.
    """
    ds_id = _register(session_factory, code="e2e_conn_race", database=source)

    repo = SqlDatasourceRepository(session_factory)
    # The row really is there — so only a stale read can let the INSERT through.
    assert repo.get_datasource_by_code("e2e_conn_race") is not None
    repo.get_datasource_by_code = lambda code: None  # pre-check read was stale
    service = DataSourceService(repo)
    try:
        service.register(
            {
                "code": "e2e_conn_race",
                "name": "racing registrant",
                "ds_type": "postgres",
                "host": _base_url().host or "localhost",
                "port": _base_url().port or 5432,
                "username": _SOURCE_USER,
                "password": _SOURCE_PASSWORD,
                "scan_config": {"database": source},
            }
        )
        raise AssertionError("expected ConflictError")
    except ConflictError:
        pass

    with session_factory() as s:
        rows = s.query(Datasource).filter(Datasource.code == "e2e_conn_race").all()
        assert len(rows) == 1
        assert rows[0].id == ds_id
    assert len(repo.list_credentials(ds_id)) == 1


def test_cli_scan_run_ingests_into_catalog(engine, session_factory, source):
    """``scan run`` must really ingest, not just print a connectivity preview.

    The pre-existing ``scan mysql|postgres`` commands dump metadata to stdout and
    never touch ``catalog_*`` (they have no datasource identity to attach rows
    to). This pins that ``scan run`` goes through ScanService and lands rows.
    """
    from local_ingestion.cli.base import CLIContext
    from local_ingestion.cli.commands.scan import ScanRunCommand

    code = "e2e_conn_cli_run"
    ds_id = _register(session_factory, code=code, database=source)

    cmd = ScanRunCommand(CLIContext(quiet=True))
    assert cmd.execute(["--datasource", code]) == 0

    with session_factory() as s:
        tables = (
            s.query(CatalogTable)
            .filter(
                CatalogTable.datasource_id == ds_id,
                CatalogTable.deleted_at.is_(None),
            )
            .count()
        )
    assert tables >= 2  # customers + orders really landed

    # An unknown datasource is an error, not a silent no-op.
    assert ScanRunCommand(CLIContext(quiet=True)).execute(["--datasource", "nope"]) == 1


def test_scan_produces_grades_that_feed_the_overview(engine, session_factory, source):
    """Scanned rows must be graded, or the overview's sensitive metrics stay 0.

    ``grade_level`` used to be written only by the seeder (random ints), so a
    real scan left it NULL: ``sensitive_count`` (grade >= 2) was always 0 and
    change-impact grading saw no PII. This pins the whole chain: scan -> grading
    -> overview metric.
    """
    ds_id = _register(session_factory, code="e2e_conn_grade", database=source)

    result = ScanService(session_factory).run_scan(ds_id)
    assert result.ok, result.errors
    assert result.classification["columns_graded"] > 0

    with session_factory() as s:
        def _col(name):
            return (
                s.query(CatalogColumn)
                .filter(
                    CatalogColumn.datasource_id == ds_id,
                    CatalogColumn.name == name,
                    CatalogColumn.deleted_at.is_(None),
                )
                .first()
            )

        email = _col("email")
        amount = _col("amount")
        sku = _col("customer_id")

    assert email.grade_level == 3          # 个人信息
    assert email.grade_code == "PII"
    assert "PII" in email.tags
    assert email.properties.get("pii") is True

    assert amount.grade_level == 2         # 业务敏感（金额）
    assert sku.grade_level == 1            # 普通业务字段

    stats = SqlCatalogStatsSource(session_factory)
    assert stats.sensitive_count() > 0

    overview = OverviewService(stats).get_overview()
    assert overview.sensitive_count > 0
    assert overview.sensitive_ratio > 0


def test_presentation_endpoints_serve_scanned_data(engine, session_factory, source):
    """呈现出口：搜索 / 资产详情 / 总览必须吃到真实扫描数据。

    SearchService 与 AssetDetailService 早就实现（真查 catalog_*），但没有任何
    HTTP 路由；总览端点又只接内存数据源。三者都曾导致「扫进来了却看不见」。
    """
    from fastapi.testclient import TestClient

    from local_ingestion.api.app import app

    ds_id = _register(session_factory, code="e2e_conn_present", database=source)
    assert ScanService(session_factory).run_scan(ds_id).ok

    client = TestClient(app)

    found = client.get("/api/v1/search", params={"term": "customers"})
    assert found.status_code == 200, found.text
    assert any(hit["name"] == "customers" for hit in found.json()["items"])

    fqn = f"{source}.public.customers"
    detail = client.get(f"/api/v1/assets/{fqn}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["name"] == "customers"
    assert any(col["name"] == "email" for col in body["columns"])

    overview = client.get("/api/v1/catalog/overview")
    assert overview.status_code == 200, overview.text
    assert overview.json()["sensitive_count"] > 0


def test_write_account_registration_rejected(engine, session_factory, source):
    """FR-1.5: a credential holding write privileges cannot be registered."""
    service = DataSourceService(SqlDatasourceRepository(session_factory))

    with pytest.raises(WriteAccessDeniedError):
        service.register(
            {
                "code": "e2e_conn_write_forbidden",
                "name": "E2E privileged account",
                "ds_type": "postgres",
                "host": _base_url().host or "localhost",
                "port": _base_url().port or 5432,
                "username": _base_url().username or "postgres",
                "password": _base_url().password or "",
                "scan_config": {"database": source},
            },
            actor="connector-e2e",
        )


def test_orchestrated_real_scan_diff_confirm_overview(engine, session_factory, source):
    """T-107 dependency chain driven by a REAL scan instead of a seed fixture.

    The pre-existing integration test starts its chain from a synthetic ``seed``
    handler; here the ``scan`` handler really connects to the source database, so
    the whole chain runs on metadata that came from a live catalog.
    """
    ds_id = _register(session_factory, code="e2e_conn_chain", database=source)
    scan = ScanService(session_factory)

    # Scan once to establish the baseline snapshot, then evolve the source.
    assert scan.run_scan(ds_id).ok
    baseline = _catalog_state(session_factory, ds_id)
    _mutate_source(source)

    repo = SqlChangeRepository(session_factory)
    audit = AuditService(InMemoryAuditSink())
    confirm = ChangeConfirmService(repo, audit)
    ctx: dict = {}

    def h_diff(c):
        current = _catalog_state(session_factory, ds_id)
        diff = SchemaDiffer().diff(baseline, current, datasource_id=ds_id)
        graded = ImpactClassifier().classify(diff)
        for g in graded:
            repo.add(
                ChangeEventInput(
                    entity_type=(
                        "table" if g.change_type.startswith("table") else "column"
                    ),
                    change_type=g.change_type,
                    severity=_LEVEL_TO_SEVERITY[g.level],
                    entity_fqn=g.fqn,
                    datasource_id=g.datasource_id,
                    before_json={},
                    after_json={"level": g.level},
                )
            )
        ctx["changes"] = len(graded)
        return {"changes": ctx["changes"]}

    def h_confirm(c):
        pending = repo.list(ack_status="pending", limit=10)
        if pending:
            confirm.ack(pending[0].id, "orchestrator", "acknowledged")
            ctx["acked"] = pending[0].id
        return {"acked": ctx.get("acked")}

    def h_overview(c):
        ov = OverviewService(SqlCatalogStatsSource(session_factory), repo).get_overview()
        ctx["tables"] = ov.tables_count
        return {"tables": ov.tables_count}

    handlers = HandlerRegistry()
    handlers.register("scan", make_scan_handler(scan))
    handlers.register("diff", h_diff)
    handlers.register("confirm", h_confirm)
    handlers.register("overview", h_overview)
    deps = DependencyRegistry()
    deps.on_success("scan", "diff")
    deps.on_success("diff", "confirm")
    deps.on_success("confirm", "overview")

    svc = TaskService(
        store=InMemoryTaskRunStore(),
        audit=audit,
        locks=ProcessLockProvider(),
        handlers=handlers,
        deps=deps,
    )
    run = svc.dispatch(
        TaskSpec(
            job_type="scan",
            scope={"datasource_id": ds_id},
            trigger=TriggerType.MANUAL,
        )
    )

    assert run.status == TaskStatus.SUCCESS
    # phone added, email retyped, order_items created
    assert ctx.get("changes", 0) >= 3
    assert ctx.get("acked") is not None
    assert ctx.get("tables", 0) >= 3
    assert len(svc.list(job_type="scan")) == 1
