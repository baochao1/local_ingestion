"""MOD-08 T4: permission collector (read-only -> accounts/grants + risk)."""
from local_ingestion.platform.permission.collector import collect_permissions


class _FakeConn:
    def __init__(self, accounts, grants):
        self.accounts = accounts
        self.grants = grants

    def execute(self, sql, params=None):
        s = str(sql).lower()
        if "pg_roles" in s or "mysql.user" in s:
            return self.accounts
        return self.grants


def test_collector_persists_and_scores(session_factory):
    fake = _FakeConn([("alice", False, True)], [("alice", "table", "db.s.t1", "SELECT", False)])
    res = collect_permissions(session_factory, ds_id=1, ds_type="postgres",
                             db="db", schema="s", conn=fake)
    assert res.accounts == 1 and res.grants == 1 and res.risks >= 0


def test_collector_grant_failure_isolated(session_factory):
    class _BoomGrantConn:
        def execute(self, sql, params=None):
            if "role_table_grants" in str(sql).lower():
                raise RuntimeError("grant query failed")
            return [("alice", False, True)]
    res = collect_permissions(session_factory, ds_id=1, ds_type="postgres",
                             db="db", schema="s", conn=_BoomGrantConn())
    assert res.failed == 1
    assert res.accounts == 1


def test_collector_mysql_grantee_normalised(session_factory):
    # MySQL grantee is 'user'@'host'; account must match grant grantee
    fake = _FakeConn([("alice", "10.%", False, "N")],
                     [("alice@10.%", "table", "db.s.t1", "SELECT", False)])
    res = collect_permissions(session_factory, ds_id=1, ds_type="mysql",
                             db="db", schema="s", conn=fake)
    # single account despite grantee carrying host
    assert res.accounts == 1
    from local_ingestion.platform.permission.repository import PermissionRepository
    assert PermissionRepository(session_factory).get_grants_of_account(1, "alice@10.%")
