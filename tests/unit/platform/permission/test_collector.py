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
    # account row = (name, host, is_super, is_locked)
    fake = _FakeConn([("alice", None, False, False)],
                     [("alice", "table", "db.s.t1", "SELECT", False)])
    res = collect_permissions(session_factory, ds_id=1, ds_type="postgres",
                             db="db", schema="s", conn=fake)
    assert res.accounts == 1 and res.grants == 1 and res.risks >= 0


def test_collector_grant_failure_isolated(session_factory):
    class _BoomGrantConn:
        def execute(self, sql, params=None):
            if "role_table_grants" in str(sql).lower():
                raise RuntimeError("grant query failed")
            return [("alice", None, False, False)]
    res = collect_permissions(session_factory, ds_id=1, ds_type="postgres",
                             db="db", schema="s", conn=_BoomGrantConn())
    assert res.failed == 1
    assert res.accounts == 1


def test_collector_mysql_grantee_normalised(session_factory):
    # MySQL grantee is 'user'@'host'; account must match grant grantee.
    # Row = (name, host, is_super, is_locked) — MySQL returns 1/0 for the flags.
    fake = _FakeConn([("alice", "10.%", 1, 1)],
                     [("alice@10.%", "table", "db.s.t1", "SELECT", False)])
    res = collect_permissions(session_factory, ds_id=1, ds_type="mysql",
                             db="db", schema="s", conn=fake)
    # single account despite grantee carrying host
    assert res.accounts == 1
    from local_ingestion.platform.permission.repository import PermissionRepository
    repo = PermissionRepository(session_factory)
    assert repo.get_grants_of_account(1, "alice@10.%")
    # regression: host must map to identity, NOT be misread as is_super
    alice = [a for a in repo.list_accounts(1) if a["account"] == "alice@10.%"][0]
    assert alice["is_super"] is True and alice["is_locked"] is True


def test_snowflake_unsupported_fails_cleanly(session_factory):
    # SHOW-based output would otherwise be parsed positionally (row[1]=host)
    # and fabricate accounts, so the dialect must refuse instead.
    fake = _FakeConn([], [])
    res = collect_permissions(session_factory, ds_id=1, ds_type="snowflake",
                              db="db", schema="s", conn=fake)
    assert res.accounts == 0 and res.grants == 0
    assert res.failed == 2  # both accounts and grants query refused
    from local_ingestion.platform.permission.repository import PermissionRepository
    assert PermissionRepository(session_factory).list_accounts(1) == []
