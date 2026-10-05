"""MOD-07 T3: lineage repository (edges + closure + walk)."""
from local_ingestion.platform.lineage.repository import LineageRepository


def test_upsert_table_edge_idempotent(session_factory):
    repo = LineageRepository(session_factory)
    repo.upsert_table_edge("ds.db.s.t1", "ds.db.s.v", src_table_id=1, tgt_table_id=2,
                          edge_source="view", confidence=1.0)
    repo.upsert_table_edge("ds.db.s.t1", "ds.db.s.v", src_table_id=1, tgt_table_id=2,
                          edge_source="view", confidence=1.0)
    assert repo.count_table_edges() == 1  # unique index dedupes


def test_column_edge_upsert(session_factory):
    repo = LineageRepository(session_factory)
    repo.upsert_column_edge("ds.db.s.t1.id", "ds.db.s.v.id", edge_source="view")
    repo.upsert_column_edge("ds.db.s.t1.id", "ds.db.s.v.id", edge_source="view")
    with session_factory() as s:
        from local_ingestion.platform.storage.models_ops import LineageColumnEdge
        from sqlalchemy import select, func
        n = s.execute(select(func.count()).select_from(LineageColumnEdge)
                      .where(LineageColumnEdge.deleted_at.is_(None))).scalar_one()
    assert n == 1


def test_rebuild_closure_multihop_and_cycle(session_factory):
    repo = LineageRepository(session_factory)
    repo.upsert_table_edge("A", "B")
    repo.upsert_table_edge("B", "C")
    repo.upsert_table_edge("C", "B")  # cycle B<->C, must not loop forever
    n = repo.rebuild_closure(max_depth=20)
    assert n >= 3  # A->B, B->C, A->C (and the back-edge capped)
    pairs = {(r.ancestor_fqn, r.descendant_fqn) for r in repo.all_closure()}
    assert ("A", "B") in pairs and ("A", "C") in pairs and ("B", "C") in pairs


def test_walk_closure_down_and_up(session_factory):
    repo = LineageRepository(session_factory)
    repo.upsert_table_edge("A", "B")
    repo.upsert_table_edge("B", "C")
    repo.rebuild_closure()
    down = repo.walk_closure("A", "down")
    assert {d["fqn"] for d in down} == {"B", "C"}
    up = repo.walk_closure("C", "up")
    assert {u["fqn"] for u in up} == {"A", "B"}


def test_soft_delete_edge(session_factory):
    repo = LineageRepository(session_factory)
    repo.upsert_table_edge("X", "Y")
    deleted = repo.soft_delete_edge("X", "Y")
    assert deleted == 1
    assert repo.count_table_edges() == 0
