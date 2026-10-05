"""MOD-07 T2: sqlglot table/column edge extraction."""
from local_ingestion.platform.lineage.parse import extract_table_edges, extract_column_edges

DEF = "CREATE VIEW v AS SELECT a.id, b.name FROM db.s.t1 a JOIN db.s.t2 b ON a.id=b.id"


def test_extract_table_edges_qualifies_fqn():
    edges = extract_table_edges("ds1", "db", "s", "v", DEF)
    srcs = {e[0] for e in edges}
    assert "ds1.db.s.t1" in srcs and "ds1.db.s.t2" in srcs
    assert all(e[1] == "ds1.db.s.v" for e in edges)


def test_extract_column_edges_resolves_upstream():
    col_edges = extract_column_edges("ds1", "db", "s", "v", DEF)
    targets = {e[1] for e in col_edges}
    assert "ds1.db.s.v.id" in targets
    srcs = {e[0] for e in col_edges}
    assert "ds1.db.s.t1.id" in srcs and "ds1.db.s.t2.name" in srcs


def test_empty_definition_is_safe():
    assert extract_table_edges("ds1", "db", "s", "v", None) == []
    assert extract_column_edges("ds1", "db", "s", "v", "") == []


def test_unqualified_definition_falls_back_to_view_schema():
    # pg_get_viewdef returns unqualified names; must qualify via view db/schema
    defn = "SELECT a.id FROM t1 a"
    edges = extract_table_edges("ds1", "mydb", "public", "v", defn)
    assert ("ds1.mydb.public.t1", "ds1.mydb.public.v") in edges
    col_edges = extract_column_edges("ds1", "mydb", "public", "v", defn)
    assert ("ds1.mydb.public.t1.id", "ds1.mydb.public.v.id") in col_edges


def test_unaliased_single_table_view_keeps_table_name():
    # pg_get_viewdef for a single-table view: SELECT id FROM t1 (no alias)
    defn = "SELECT id FROM t1"
    col_edges = extract_column_edges("ds1", "mydb", "public", "v", defn)
    assert ("ds1.mydb.public.t1.id", "ds1.mydb.public.v.id") in col_edges
    # regression: table name must NOT be dropped
    assert not any(e[0].endswith(".id") and e[0].count(".") == 3 for e in col_edges)
