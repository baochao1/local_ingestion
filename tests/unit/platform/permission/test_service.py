"""MOD-08 T5: permission query service (matrix / entity grants / risks / changes)."""
from datetime import datetime, timezone

from local_ingestion.platform.permission.repository import PermissionRepository
from local_ingestion.platform.permission.service import PermissionQueryService


def _seed(session_factory):
    r = PermissionRepository(session_factory)
    r.upsert_account(1, "alice", is_super=True)
    r.upsert_account(1, "app", is_super=False)
    r.upsert_grant(1, "app", "DELETE", "table", "db.s.orders",
                   detected_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    return r


def test_matrix_and_account_grants(session_factory):
    _seed(session_factory)
    svc = PermissionQueryService(session_factory)
    matrix = svc.matrix(1)
    assert any(m["account"] == "alice" for m in matrix)
    grants = svc.grants_of_account(1, "app")
    assert any(g["object_fqn"] == "db.s.orders" and g["privilege"] == "DELETE" for g in grants)


def test_entity_grants(session_factory):
    _seed(session_factory)
    svc = PermissionQueryService(session_factory)
    assert any(g["account_id"] is not None for g in svc.get_entity_grants("db.s.orders"))


def test_risks_detects_super_and_excessive(session_factory):
    _seed(session_factory)
    svc = PermissionQueryService(session_factory)
    risks = svc.risks(1)
    types = {r["type"] for r in risks}
    assert "super" in types and "excessive" in types


def _seed_graded_table(session_factory, fqn: str, grade: int) -> None:
    """Create the minimal catalog FK chain so ``fqn`` carries ``grade_level``."""
    from local_ingestion.platform.storage.models_core import (
        CatalogDatabase,
        CatalogSchema,
        CatalogTable,
    )

    with session_factory() as s:
        db_row = CatalogDatabase(datasource_id=1, name="db", fqn=f"graded_{grade}.db")
        s.add(db_row)
        s.flush()
        sch = CatalogSchema(datasource_id=1, database_id=db_row.id, name="s",
                            fqn=f"graded_{grade}.db.s")
        s.add(sch)
        s.flush()
        s.add(CatalogTable(datasource_id=1, schema_id=sch.id, name="orders",
                           fqn=fqn, grade_level=grade))
        s.commit()


def test_high_sensitivity_risk_uses_mod05_grade(session_factory):
    # grade_level=4 >= HIGH_GRADE_THRESHOLD(3) and "app" holds DELETE on it
    _seed_graded_table(session_factory, "db.s.orders", grade=4)
    _seed(session_factory)
    risks = PermissionQueryService(session_factory).risks(1)
    high = [r for r in risks if r["type"] == "high_sensitivity"]
    assert high, risks
    assert high[0]["object_fqn"] == "db.s.orders"
    assert "L4" in high[0]["detail"]


def test_graded_column_shortens_via_suffix(session_factory):
    # grants are dialect-qualified (schema.table) while catalog FQNs are fully
    # qualified; the lookup must match on the dotted suffix
    _seed_graded_table(session_factory, "ds1.mydb.public.orders", grade=5)
    svc = PermissionQueryService(session_factory)
    assert svc._grade_lookup(1).get("public.orders") == 5


def test_risk_id_is_stable_and_ack_persists(session_factory):
    _seed(session_factory)
    svc = PermissionQueryService(session_factory)
    risks = svc.risks(1)
    assert risks and all(r["id"] and r["acked"] is False for r in risks)
    target = next(r for r in risks if r["type"] == "excessive")
    svc.ack_risk(1, target["id"])
    after = {r["id"]: r for r in svc.risks(1)}
    # ids are content-derived, so they survive a recompute of the risk list
    assert target["id"] in after and after[target["id"]]["acked"] is True


def test_changes_after_baseline(session_factory):
    _seed(session_factory)
    svc = PermissionQueryService(session_factory)
    svc.mark_baseline(1)
    repo = PermissionRepository(session_factory)
    repo.upsert_grant(1, "app", "DROP", "table", "db.s.orders",
                      detected_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
    changes = svc.changes(1)
    assert any(c["kind"] == "added" and c["privilege"] == "DROP" for c in changes)
