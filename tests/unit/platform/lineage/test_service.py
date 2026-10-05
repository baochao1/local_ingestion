"""MOD-07 T5: LineageService upstream/downstream/impact (replaces placeholder)."""
from local_ingestion.platform.lineage.service import LineageService
from local_ingestion.platform.lineage.models import ImpactReport


def test_downstream_multi_hop_and_cycle(session_factory):
    svc = LineageService(session_factory)
    svc.repo.upsert_table_edge("A", "B")
    svc.repo.upsert_table_edge("B", "C")
    svc.repo.upsert_table_edge("C", "B")  # cycle B<->C
    svc.repo.rebuild_closure()
    down = svc.downstream("A", max_depth=10)
    fqns = {n.fqn for n in down}
    assert "B" in fqns and "C" in fqns  # cycle does not loop forever


def test_upstream(session_factory):
    svc = LineageService(session_factory)
    svc.repo.upsert_table_edge("A", "B")
    svc.repo.upsert_table_edge("B", "C")
    svc.repo.rebuild_closure()
    up = svc.upstream("C")
    fqns = {n.fqn for n in up}
    assert "A" in fqns and "B" in fqns


def test_impact_aggregates_data_sources(session_factory):
    svc = LineageService(session_factory)
    svc.repo.upsert_table_edge("ds1.db.s.A", "ds1.db.s.B")
    svc.repo.upsert_table_edge("ds1.db.s.A", "ds2.db.s.C")
    svc.repo.rebuild_closure()
    rep = svc.impact_scope("ds1.db.s.A")
    assert isinstance(rep, ImpactReport)
    assert rep.total == 2
    assert not rep.degraded
    assert set(rep.data_sources) == {"ds1", "ds2"}


def test_empty_impact_is_not_degraded(session_factory):
    svc = LineageService(session_factory)
    rep = svc.impact_scope("nonexistent")
    assert rep.total == 0
    assert not rep.degraded  # real service, not placeholder
