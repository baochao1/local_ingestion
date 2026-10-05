"""End-to-end PostgreSQL integration tests (T-113 / 串联).

Skipped unless ``PG_TEST=1`` is set. Exercises the SQL-backed repositories and the
full change pipeline:

    T-201 diff -> T-202 grade -> T-204 persist / confirm / escalate
    -> T-203 notify (reused aggregator) -> T-213 overview

wired through the T-107 orchestrator (dependency chaining).
"""
from __future__ import annotations

import asyncio
import os

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from local_ingestion.platform.storage.schema import reset_schema
from local_ingestion.platform.storage.seed import seed_catalog
from local_ingestion.platform.storage.models_core import (
    CatalogColumn,
    CatalogTable,
    Datasource,
)
from local_ingestion.platform.versioning.adapter import build_catalog_state
from local_ingestion.platform.versioning.diff import SchemaDiffer
from local_ingestion.platform.versioning.classify import ImpactClassifier
from local_ingestion.platform.changes.models import ChangeEventInput
from local_ingestion.platform.changes.repository import SqlChangeRepository
from local_ingestion.platform.changes.service import (
    ChangeConfirmService,
    ChangeEscalationService,
    ChangeStatsService,
)
from local_ingestion.platform.catalog.source import SqlCatalogStatsSource
from local_ingestion.platform.catalog.service import OverviewService
from local_ingestion.platform.notify.models import SubscriptionSpec
from local_ingestion.platform.notify.repository import (
    InMemoryNotificationLogStore,
    InMemorySubscriptionRepository,
)
from local_ingestion.platform.notify.service import NotificationAggregator
from local_ingestion.platform.orchestration.audit import AuditService, InMemoryAuditSink
from local_ingestion.platform.orchestration.lock import ProcessLockProvider
from local_ingestion.platform.orchestration.models import TaskSpec, TriggerType
from local_ingestion.platform.orchestration.registry import (
    DependencyRegistry,
    HandlerRegistry,
)
from local_ingestion.platform.orchestration.service import TaskService
from local_ingestion.platform.orchestration.store import InMemoryTaskRunStore

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)

DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"

# Graded level -> persisted change_event.severity
_LEVEL_TO_SEVERITY = {
    "P0": "breaking",
    "P1": "breaking",
    "P2": "structural",
    "P3": "descriptive",
}


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


def _run_diff_persist(session_factory, *, datasource_code):
    """Read baseline catalog from PG, mutate it, diff+grade, persist as ChangeEvents."""
    repo = SqlChangeRepository(session_factory)
    with session_factory() as s:
        ds = s.query(Datasource).filter(Datasource.code == datasource_code).first()
        tables = (
            s.query(CatalogTable)
            .filter(CatalogTable.deleted_at.is_(None), CatalogTable.datasource_id == ds.id)
            .all()
        )
        cols = (
            s.query(CatalogColumn)
            .filter(CatalogColumn.deleted_at.is_(None), CatalogColumn.datasource_id == ds.id)
            .all()
        )
        by_table: dict = {}
        for c in cols:
            by_table.setdefault(c.table_id, []).append(c)
        baseline = build_catalog_state(tables, by_table)
    modified = build_catalog_state(tables, by_table)
    # Introduce a breaking/structural change + a dropped table.
    modified.tables[0].columns[0].data_type = "text"
    modified.tables.pop()
    result = SchemaDiffer().diff(baseline, modified, datasource_id=ds.id)
    graded = ImpactClassifier().classify(result)
    for g in graded:
        repo.add(
            ChangeEventInput(
                entity_type="table" if g.change_type.startswith("table") else "column",
                change_type=g.change_type,
                severity=_LEVEL_TO_SEVERITY[g.level],
                entity_fqn=g.fqn,
                datasource_id=g.datasource_id,
                before_json={},
                after_json={"level": g.level},
            )
        )
    return len(graded)


def test_seed_and_overview(engine, session_factory):
    seed_catalog(engine, tables=40, columns_per_table=5,
                 datasource_code="ov_ds", database="ov_db")
    src = SqlCatalogStatsSource(session_factory)
    repo = SqlChangeRepository(session_factory)
    ov = OverviewService(src, repo).get_overview()
    assert ov.tables_count >= 40
    assert ov.columns_count >= 200
    assert ov.sensitive_count >= 0  # grade-based, may be 0


def test_diff_persist_confirm_loop(engine, session_factory):
    seed_catalog(engine, tables=50, columns_per_table=8,
                 datasource_code="it_ds", database="it_db")
    n = _run_diff_persist(session_factory, datasource_code="it_ds")
    assert n >= 1

    repo = SqlChangeRepository(session_factory)
    confirm = ChangeConfirmService(repo, AuditService(InMemoryAuditSink()))
    pending = repo.list(ack_status="pending", limit=10)
    ev = confirm.ack(pending[0].id, "tester", "acknowledged")
    assert ev.ack_status == "closed"
    assert ev.ack_action == "acknowledged"

    stats = ChangeStatsService(repo).statistics(
        datetime(2000, 1, 1, tzinfo=timezone.utc),
        datetime(2100, 1, 1, tzinfo=timezone.utc),
    )
    assert stats.total == n
    assert 0 < stats.ack_rate <= 1


def test_escalation_reuses_t203(engine, session_factory):
    repo = SqlChangeRepository(session_factory)
    old = datetime.now(timezone.utc) - timedelta(days=2)
    repo.add(ChangeEventInput(
        entity_type="table", change_type="table_removed", severity="breaking",
        entity_fqn="db.s.t_old", datasource_id=1, detected_at=old,
    ))
    subs = InMemorySubscriptionRepository()
    subs.create(SubscriptionSpec(
        subscriber="op", scope_type="global", min_severity="P0", channel="email",
    ))
    agg = NotificationAggregator(subs, InMemoryNotificationLogStore())
    esc = ChangeEscalationService(repo, agg, deadline=timedelta(hours=1))

    class Sender:
        def __init__(self):
            self.calls = []

        async def send(self, title, message, level, context):
            self.calls.append((title, context))
            return True

    sender = Sender()
    outcome = asyncio.run(esc.escalate(sender))
    assert outcome.sent >= 1
    assert len(sender.calls) >= 1


def test_orchestrated_pipeline(engine, session_factory):
    """T-107 dependency chaining across the full change pipeline."""
    seed_catalog(engine, tables=20, columns_per_table=4,
                 datasource_code="or_ds", database="or_db")
    repo = SqlChangeRepository(session_factory)
    # Pre-create a breaking change so the 'confirm' step has something to close.
    repo.add(ChangeEventInput(
        entity_type="table", change_type="table_removed", severity="breaking",
        entity_fqn="or_db.public.t0", datasource_id=1,
        detected_at=datetime.now(timezone.utc) - timedelta(days=1),
    ))
    audit = AuditService(InMemoryAuditSink())
    confirm_svc = ChangeConfirmService(repo, audit)
    ctx: dict = {}

    def h_seed(c):
        ctx["seeded"] = True
        return {"ok": True}

    def h_diff(c):
        ctx["diffed"] = _run_diff_persist(session_factory, datasource_code="or_ds")
        return {"diffed": ctx["diffed"]}

    def h_confirm(c):
        pend = repo.list(severity="breaking", ack_status="pending", limit=10)
        if pend:
            confirm_svc.ack(pend[0].id, "orchestrator", "acknowledged")
            ctx["acked"] = pend[0].id
        return {"acked": ctx.get("acked")}

    def h_overview(c):
        src = SqlCatalogStatsSource(session_factory)
        ov = OverviewService(src, repo).get_overview()
        ctx["tables"] = ov.tables_count
        return {"tables": ov.tables_count}

    handlers = HandlerRegistry()
    handlers.register("seed", h_seed)
    handlers.register("diff", h_diff)
    handlers.register("confirm", h_confirm)
    handlers.register("overview", h_overview)
    deps = DependencyRegistry()
    deps.on_success("seed", "diff")
    deps.on_success("diff", "confirm")
    deps.on_success("confirm", "overview")

    svc = TaskService(
        store=InMemoryTaskRunStore(), audit=audit, locks=ProcessLockProvider(),
        handlers=handlers, deps=deps,
    )
    svc.dispatch(TaskSpec(job_type="seed", scope={}, trigger=TriggerType.MANUAL))

    assert ctx.get("seeded")
    assert ctx.get("diffed", 0) >= 1
    assert ctx.get("acked") is not None
    assert ctx.get("tables", 0) >= 20
    assert len(svc.list(job_type="overview")) == 1
    assert len(svc.list(job_type="seed")) == 1
