"""MOD-08 T2: permission repository (accounts/grants upsert + baseline diff)."""
from datetime import datetime, timezone

from local_ingestion.platform.permission.repository import PermissionRepository


def test_upsert_account_idempotent(session_factory):
    r = PermissionRepository(session_factory)
    r.upsert_account(ds_id=1, name="alice", account_type="user", is_super=False)
    r.upsert_account(ds_id=1, name="alice", account_type="user", is_super=False)
    assert r.count_accounts(1) == 1


def test_upsert_grant_resolves_account(session_factory):
    r = PermissionRepository(session_factory)
    r.upsert_account(ds_id=1, name="alice")
    r.upsert_grant(ds_id=1, account="alice", privilege="SELECT",
                   object_type="table", object_fqn="db.s.t1", detected_at=datetime(2026, 1, 1))
    grants = r.get_grants_of_account(1, "alice")
    assert any(g["object_fqn"] == "db.s.t1" and g["privilege"] == "SELECT" for g in grants)


def test_baseline_diff_detects_new_grant(session_factory):
    r = PermissionRepository(session_factory)
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    r.upsert_grant(ds_id=1, account="alice", privilege="SELECT", object_type="table",
                   object_fqn="db.s.t1", detected_at=t1)
    r.mark_baseline(1)
    r.upsert_grant(ds_id=1, account="alice", privilege="SELECT", object_type="table",
                   object_fqn="db.s.t1", detected_at=t2)
    r.upsert_grant(ds_id=1, account="alice", privilege="DELETE", object_type="table",
                   object_fqn="db.s.t1", detected_at=t2)
    diff = r.diff_vs_baseline(1)
    assert any(d["kind"] == "added" and d["privilege"] == "DELETE" for d in diff)
    assert not any(d["kind"] == "revoked" for d in diff)


def test_entity_grants(session_factory):
    r = PermissionRepository(session_factory)
    r.upsert_grant(ds_id=1, account="alice", privilege="SELECT", object_type="table",
                   object_fqn="db.s.t1", detected_at=datetime(2026, 1, 1))
    assert any(g["account_id"] is not None for g in r.get_entity_grants("db.s.t1"))
