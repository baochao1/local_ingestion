"""sqlglot-backed lineage parsing (MOD-07).

Pure, dependency-free-of-DB functions that turn a SQL view definition (or any
SELECT) into table-level and column-level lineage edges. Source tables/columns
are qualified into the stable FQN form ``ds.db.schema.table[.column]`` (consistent
with entity identity, FR-13) by falling back to the view's own database/schema
when the definition omits qualifiers (which ``pg_get_viewdef`` does).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

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


# --------------------------------------------------------------------------
# FR-M4: resilient parsing — fallback chain, timeout, CTE folding, error capture
# --------------------------------------------------------------------------

DEFAULT_PARSE_TIMEOUT_SEC = 30.0


@dataclass
class ParseOutcome:
    """Result of parsing one definition — never raises.

    Carrying ``error`` / ``timed_out`` is the point: a statement that produced
    no lineage must be explainable, not silently indistinguishable from a
    statement with no upstream (FR-M4.4).
    """

    table_edges: list[tuple[str, str]] = field(default_factory=list)
    column_edges: list[tuple[str, str]] = field(default_factory=list)
    parser: str = ""
    error: str | None = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None and not self.timed_out


def _cte_names(tree: exp.Expression) -> set[str]:
    """Names introduced by WITH clauses.

    A CTE is an intermediate result, not a source. Without folding these out,
    ``WITH x AS (...) SELECT * FROM x`` produces an edge pointing at a table
    that does not exist — the orphan-node problem FR-M4.2 is about.
    """
    return {cte.alias_or_name for cte in tree.find_all(exp.CTE) if cte.alias_or_name}


def _parse_with_sqlglot(
    ds: str, db: str, schema: str, view: str, definition: str, dialect: str
) -> ParseOutcome:
    try:
        tree = sqlglot.parse_one(definition, read=_sqlglot_dialect(dialect))
    except Exception as exc:  # noqa: BLE001 - the reason is the deliverable
        return ParseOutcome(parser="sqlglot", error=f"parse failed: {exc}")
    if tree is None:
        return ParseOutcome(parser="sqlglot", error="parser returned no tree")

    intermediate = _cte_names(tree)
    tgt = FQN_SEP.join((ds, db, schema, view))

    table_edges: list[tuple[str, str]] = []
    seen_tables: set[tuple[str, str]] = set()
    for table in tree.find_all(exp.Table):
        if table.name in intermediate or table.name == view:
            continue
        src = _qualify_table(table, ds, db, schema)
        if src != tgt and (src, tgt) not in seen_tables:
            seen_tables.add((src, tgt))
            table_edges.append((src, tgt))

    column_edges: list[tuple[str, str]] = []
    select = _top_select(tree)
    if select is not None:
        alias_map: dict[str, tuple] = {}
        from_tables: list[tuple] = []
        for table in tree.find_all(exp.Table):
            if table.name in intermediate:
                continue
            alias_map[table.alias_or_name] = (table.catalog, table.db, table.name)
            from_tables.append((table.catalog, table.db, table.name))

        seen_cols: set[tuple[str, str]] = set()
        for projection in select.expressions:
            col_name = projection.alias_or_name
            for column in projection.find_all(exp.Column):
                tbl = column.table or ""
                if not tbl and len(from_tables) == 1:
                    cat, sch, real_tbl = from_tables[0]
                else:
                    cat, sch, real_tbl = alias_map.get(tbl, (None, None, tbl))
                src_fqn = _col_fqn(ds, cat, sch, real_tbl, column.name, db, schema)
                tgt_fqn = FQN_SEP.join((tgt, col_name))
                if (src_fqn, tgt_fqn) not in seen_cols:
                    seen_cols.add((src_fqn, tgt_fqn))
                    column_edges.append((src_fqn, tgt_fqn))

    return ParseOutcome(
        table_edges=table_edges, column_edges=column_edges, parser="sqlglot"
    )


#: Ordered fallback chain. Adding a parser is a one-line registration; today
#: sqlglot is the only one installed, and pretending otherwise would be worse
#: than saying so (see LC-NOTE below).
_PARSERS = {"sqlglot": _parse_with_sqlglot}


def _run_with_timeout(fn, timeout_sec: float):
    """Run ``fn`` in a daemon thread, giving up after ``timeout_sec``.

    This is best-effort: Python cannot kill a running thread, so a pathological
    statement still burns CPU in the background. What it does guarantee is that
    the caller is *not* blocked indefinitely — which is what LC1 requires.
    """
    box: dict[str, object] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout_sec)
    if thread.is_alive():
        raise TimeoutError(f"exceeded {timeout_sec}s")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box.get("value")


def parse_definition(
    ds: str,
    db: str,
    schema: str,
    view: str,
    definition: str | None,
    dialect: str = "postgres",
    timeout_sec: float = DEFAULT_PARSE_TIMEOUT_SEC,
) -> ParseOutcome:
    """Parse one definition through the fallback chain.

    Tries each registered parser in order and returns the first success. A
    timeout on one parser moves on to the next rather than abandoning the
    statement (FR-M4.1).
    """
    if not definition or not definition.strip():
        return ParseOutcome(error="empty definition")

    last: ParseOutcome | None = None
    for name, parser in _PARSERS.items():
        try:
            outcome = _run_with_timeout(
                lambda p=parser: p(ds, db, schema, view, definition, dialect),
                timeout_sec,
            )
        except TimeoutError:
            last = ParseOutcome(
                parser=name,
                timed_out=True,
                error=f"parser {name} timed out after {timeout_sec}s",
            )
            continue
        except Exception as exc:  # noqa: BLE001
            last = ParseOutcome(parser=name, error=f"parser {name} crashed: {exc}")
            continue
        if outcome is not None and outcome.ok:
            return outcome
        last = outcome
    return last or ParseOutcome(error="no parser registered")
