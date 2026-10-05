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


def test_changes_after_baseline(session_factory):
    _seed(session_factory)
    svc = PermissionQueryService(session_factory)
    svc.mark_baseline(1)
    repo = PermissionRepository(session_factory)
    repo.upsert_grant(1, "app", "DROP", "table", "db.s.orders",
                      detected_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
    changes = svc.changes(1)
    assert any(c["kind"] == "added" and c["privilege"] == "DROP" for c in changes)
