"""MOD-07 T4: lineage collector (read-only -> edges)."""
from local_ingestion.platform.lineage.collector import collect_lineage


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        return self._rows


def test_collector_writes_table_and_column_edges(session_factory):
    fake = _FakeConn([("v", "SELECT a.id, b.name FROM db.s.t1 a JOIN db.s.t2 b ON a.id=b.id")])
    res = collect_lineage(session_factory, datasource_id=1, ds_code="ds1", db="db",
                         schema="s", conn=fake, dialect_name="postgres")
    assert res.views == 1
    assert res.table_edges >= 2
    assert res.column_edges >= 2
    assert res.failed == 0


def test_collector_skips_empty_definitions(session_factory):
    fake = _FakeConn([("v", None), ("w", "")])
    res = collect_lineage(session_factory, datasource_id=1, ds_code="ds1", db="db",
                         schema="s", conn=fake, dialect_name="postgres")
    assert res.views == 0 and res.table_edges == 0


def test_collector_isolates_per_view_failure(session_factory):
    # second row is malformed SQL; collection must continue without crashing
    fake = _FakeConn([("good", "SELECT a.id FROM db.s.t1 a"), ("bad", "SELECT 1 FROM")])
    res = collect_lineage(session_factory, datasource_id=1, ds_code="ds1", db="db",
                         schema="s", conn=fake, dialect_name="postgres")
    # bad view yields no edges; good view still contributes
    assert res.views == 2
    assert res.table_edges == 1
    assert res.failed == 0


def test_collector_connection_failure_is_reported(session_factory):
    class _BoomConn:
        def execute(self, sql, params=None):
            raise RuntimeError("connection lost")

    res = collect_lineage(session_factory, datasource_id=1, ds_code="ds1", db="db",
                         schema="s", conn=_BoomConn(), dialect_name="postgres")
    assert res.failed == 1
    assert res.table_edges == 0
