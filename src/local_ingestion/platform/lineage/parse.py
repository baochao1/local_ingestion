"""sqlglot-backed lineage parsing (MOD-07).

Pure, dependency-free-of-DB functions that turn a SQL view definition (or any
SELECT) into table-level and column-level lineage edges. Source tables/columns
are qualified into the stable FQN form ``ds.db.schema.table[.column]`` (consistent
with entity identity, FR-13) by falling back to the view's own database/schema
when the definition omits qualifiers (which ``pg_get_viewdef`` does).
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

FQN_SEP = "."

_DIALECT_MAP = {
    "postgres": "postgres",
    "mysql": "mysql",
    "snowflake": "snowflake",
}


def _sqlglot_dialect(dialect: str) -> str:
    return _DIALECT_MAP.get(dialect, "postgres")


def _qualify_table(table: exp.Table, ds: str, db: str, schema: str) -> str:
    """Stable FQN for a source table, falling back to view db/schema."""
    name = table.name
    sch = table.db or schema
    cat = table.catalog or db
    return FQN_SEP.join(p for p in (ds, cat, sch, name) if p)


def _col_fqn(ds: str, cat: str | None, sch: str | None, tbl: str, col: str,
             default_db: str, default_schema: str) -> str:
    return FQN_SEP.join(p for p in (ds, cat or default_db, sch or default_schema, tbl, col) if p)


def _top_select(tree: exp.Expression) -> exp.Select | None:
    if isinstance(tree, exp.Select):
        return tree
    return tree.find(exp.Select)


def extract_table_edges(ds: str, db: str, schema: str, view: str,
                       definition: str | None, dialect: str = "postgres") -> list[tuple[str, str]]:
    """Return ``[(src_fqn, tgt_fqn), ...]`` for one view/query definition."""
    if not definition:
        return []
    try:
        tree = sqlglot.parse_one(definition, read=_sqlglot_dialect(dialect))
    except Exception:
        return []
    tgt = FQN_SEP.join((ds, db, schema, view))
    out: list[tuple[str, str]] = []
    for t in tree.find_all(exp.Table):
        # Skip the view being defined (CREATE VIEW v ...), which appears as an
        # unqualified table with the view name.
        if t.name == view and (t.db or schema) == schema and (t.catalog or db) == db:
            continue
        src = _qualify_table(t, ds, db, schema)
        if src != tgt:
            out.append((src, tgt))
    return out


def extract_column_edges(ds: str, db: str, schema: str, view: str,
                        definition: str | None, dialect: str = "postgres") -> list[tuple[str, str]]:
    """Return ``[(src_col_fqn, tgt_col_fqn), ...]`` for one view/query definition.

    Walk each output projection and collect the base columns it references,
    resolving table aliases to their real (catalog, db, name). This reliably
    captures column passthrough and simple transforms in view bodies (which are
    almost always a single SELECT over base tables). Transitivity through nested
    CTEs/subqueries is handled because every referenced base column surfaces here.
    """
    if not definition:
        return []
    try:
        tree = sqlglot.parse_one(definition, read=_sqlglot_dialect(dialect))
    except Exception:
        return []
    select = _top_select(tree)
    if select is None:
        return []
    # alias (or table name) -> (catalog, db, name)
    alias_map: dict[str, tuple] = {}
    from_tables: list[tuple] = []
    for t in tree.find_all(exp.Table):
        alias_map[t.alias_or_name] = (t.catalog, t.db, t.name)
        from_tables.append((t.catalog, t.db, t.name))

    tgt_view = FQN_SEP.join((ds, db, schema, view))
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for proj in select.expressions:
        col_name = proj.alias_or_name
        for col in proj.find_all(exp.Column):
            tbl = col.table or ""  # unqualified column has empty table reference
            # `pg_get_viewdef` yields unaliased single-table views (SELECT id FROM t1);
            # fall back to the sole FROM table so the table name is not lost.
            if not tbl and len(from_tables) == 1:
                cat, sch, real_tbl = from_tables[0]
            else:
                cat, sch, real_tbl = alias_map.get(tbl, (None, None, tbl))
            src_fqn = _col_fqn(ds, cat, sch, real_tbl, col.name, db, schema)
            tgt_fqn = FQN_SEP.join((tgt_view, col_name))
            key = (src_fqn, tgt_fqn)
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out
