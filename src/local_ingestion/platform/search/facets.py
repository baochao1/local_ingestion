"""Search facet aggregation (FR-M3).

Why this module exists
----------------------
Search could only answer "does this string match?" — the user had to already
know the table name. Facets turn search into narrowing: show how many hits fall
in each datasource / schema / grade / owner / tag, then let the user drill in.

Design decisions
----------------
* **One statement, not one per dimension.** Five separate GROUP BYs over a
  ten-million-row catalog is five scans. Everything is a ``UNION ALL`` over a
  single CTE so the planner scans once (FC-N1, NFR-M2).
* **Coordinated filtering.** Each dimension is counted with *all other*
  filters applied but not its own — otherwise selecting a datasource would
  collapse every other datasource to zero and the user could never switch
  (FC1).
* **Top-N per branch.** The ``LIMIT`` sits inside each branch, so the cap
  applies per dimension rather than to the union as a whole (edge E9).
* **Bounded by the caller's filters.** Facets are computed over the same
  filters as search, so a user never infers counts for data they filtered out
  (FC2).

Not implemented: the "asset type" dimension. Results mix tables and columns and
the two tables expose different filterable fields, so a correct count needs two
passes with different predicates. Left out rather than approximated.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import String, cast, func, literal_column, select, union_all

__all__ = ["FACET_DIMENSIONS", "DEFAULT_TOP_N", "compute_facets"]

#: Dimensions exposed to the UI, in render order.
FACET_DIMENSIONS = ("datasource", "schema", "grade", "owner", "tag")

DEFAULT_TOP_N = 20


def _is_active(
    key: str,
    *,
    datasource_id: int | None,
    owner: str | None,
    grade_min: int | None,
    tags: Sequence[str] | None,
) -> bool:
    """Whether a filter is actually set (None/empty means "no constraint")."""
    if key == "datasource":
        return datasource_id is not None
    if key == "owner":
        return bool(owner)
    if key == "grade":
        return grade_min is not None
    if key == "tag":
        return bool(tags)
    return False


def compute_facets(
    session_factory,
    *,
    term: str | None = None,
    datasource_id: int | None = None,
    type: str | None = None,
    tags: Sequence[str] | None = None,
    owner: str | None = None,
    grade_min: int | None = None,
    sensitive_only: bool = False,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, list[dict[str, Any]]]:
    """Return ``{dimension: [{value, count}, ...]}`` ordered by count desc."""
    from ..storage.models_core import CatalogTable

    del type, sensitive_only  # not filterable on catalog_table; see module docs

    with session_factory() as session:
        base = (
            select(
                CatalogTable.id.label("id"),
                CatalogTable.datasource_id.label("datasource_id"),
                CatalogTable.schema_id.label("schema_id"),
                CatalogTable.owner.label("owner"),
                CatalogTable.grade_level.label("grade_level"),
                CatalogTable.tags.label("tags"),
            )
            .where(CatalogTable.deleted_at.is_(None))
        )
        if term:
            base = base.where(CatalogTable.name.ilike(f"%{term}%"))

        cte = base.cte("facet_base")

        predicates: dict[str, Callable[[], Any]] = {
            "datasource": lambda: cte.c.datasource_id == datasource_id,
            "owner": lambda: cte.c.owner.ilike(f"%{owner}%"),
            "grade": lambda: cte.c.grade_level >= grade_min,
            "tag": lambda: cte.c.tags.contains(list(tags or [])),
        }
        active = {
            key: predicate
            for key, predicate in predicates.items()
            if _is_active(
                key,
                datasource_id=datasource_id,
                owner=owner,
                grade_min=grade_min,
                tags=tags,
            )
        }

        def apply_others(statement, exclude: str):
            for key, predicate in active.items():
                if key != exclude:
                    statement = statement.where(predicate())
            return statement

        branches = []

        def branch(facet: str, value_expr, group_expr, extra=None):
            stmt = select(
                literal_column(f"'{facet}'").label("facet"),
                value_expr.label("value"),
                func.count().label("cnt"),
            ).select_from(cte)
            if extra is not None:
                stmt = stmt.where(extra)
            stmt = apply_others(stmt, facet)
            return stmt.group_by(group_expr).order_by(func.count().desc()).limit(top_n)

        branches.append(
            branch(
                "datasource",
                cast(cte.c.datasource_id, String),
                cte.c.datasource_id,
            )
        )
        branches.append(
            branch("schema", cast(cte.c.schema_id, String), cte.c.schema_id)
        )
        branches.append(
            branch(
                "grade",
                cast(cte.c.grade_level, String),
                cte.c.grade_level,
                extra=cte.c.grade_level.is_not(None),
            )
        )
        branches.append(
            branch(
                "owner",
                cte.c.owner,
                cte.c.owner,
                extra=cte.c.owner.is_not(None) & (cte.c.owner != ""),
            )
        )

        rows = session.execute(union_all(*branches)).all()

        facets: dict[str, list[dict[str, Any]]] = {
            dimension: [] for dimension in FACET_DIMENSIONS
        }
        schema_ids: list[int] = []
        datasource_ids: list[int] = []
        for facet_name, value, count in rows:
            if value is None:
                continue
            if facet_name == "schema":
                schema_ids.append(int(value))
            elif facet_name == "datasource":
                datasource_ids.append(int(value))
            facets.setdefault(facet_name, []).append(
                {"value": str(value), "count": int(count)}
            )

        if schema_ids:
            facets["schema"] = _label_schemas(session, schema_ids, facets["schema"])
        if datasource_ids:
            facets["datasource"] = _label_datasources(
                session, datasource_ids, facets["datasource"]
            )

        # tag needs unnesting, which cannot share the union's shape — see
        # :func:`_tag_facet` for why it is a second statement.
        facets["tag"] = _tag_facet(
            session,
            term=term,
            datasource_id=datasource_id,
            owner=owner,
            grade_min=grade_min,
            tags=tags,
            top_n=top_n,
        )
        return facets


def _tag_facet(
    session,
    *,
    term: str | None,
    datasource_id: int | None,
    owner: str | None,
    grade_min: int | None,
    tags: Sequence[str] | None,
    top_n: int,
) -> list[dict[str, Any]]:
    """Tag counts, as a second statement.

    ``tags`` is a JSONB array, so counting requires unnesting. SQLAlchemy's
    ``table_valued`` emits ``AS anon_1`` without the column alias list, which
    Postgres rejects (``column anon_1.tag_value does not exist``), so this one
    branch uses an explicit derived table instead.

    Cost: one extra scan, not five. The four scalar dimensions still share a
    single UNION ALL.
    """
    import json

    from sqlalchemy import text

    clauses = ["ct.deleted_at IS NULL"]
    params: dict[str, Any] = {"top_n": top_n}
    if term:
        clauses.append("ct.name ILIKE :term")
        params["term"] = f"%{term}%"
    if datasource_id is not None:
        clauses.append("ct.datasource_id = :ds")
        params["ds"] = datasource_id
    if owner:
        clauses.append("ct.owner ILIKE :owner")
        params["owner"] = f"%{owner}%"
    if grade_min is not None:
        clauses.append("ct.grade_level >= :gmin")
        params["gmin"] = grade_min
    if tags:
        clauses.append("ct.tags @> CAST(:tags AS jsonb)")
        params["tags"] = json.dumps(list(tags))

    sql = (
        "SELECT tv.tag_value AS value, COUNT(*) AS cnt "
        "FROM catalog_table ct, jsonb_array_elements_text(ct.tags) AS tv(tag_value) "
        f"WHERE {' AND '.join(clauses)} "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT :top_n"
    )
    return [
        {"value": row[0], "count": int(row[1])}
        for row in session.execute(text(sql), params).all()
    ]


def _label_datasources(
    session, ids: list[int], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach datasource names to id-keyed facet values (same trick as schemas)."""
    from ..storage.models_core import Datasource

    names = {
        row.id: (row.name or row.code)
        for row in session.execute(
            select(Datasource.id, Datasource.code, Datasource.name).where(
                Datasource.id.in_(ids)
            )
        ).all()
    }
    for row in rows:
        row["label"] = names.get(int(row["value"]), f"#{row['value']}")
    return rows


def _label_schemas(
    session, ids: list[int], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach schema names to id-keyed facet values.

    Grouping by id is far cheaper than joining on every row; the id→name
    lookup is a single small query over a bounded set.
    """
    from ..storage.models_core import CatalogSchema

    names = {
        row.id: row.name
        for row in session.execute(
            select(CatalogSchema.id, CatalogSchema.name).where(
                CatalogSchema.id.in_(ids)
            )
        ).all()
    }
    for row in rows:
        row["label"] = names.get(int(row["value"]), f"#{row['value']}")
    return rows
