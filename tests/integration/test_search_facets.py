"""Search facet integration (FR-M3) — needs ``PG_TEST=1``.

Correctness here is about two things: that counts agree with a direct query
(AC-3.1), and that *coordinated* filtering works — selecting a datasource must
still leave the other datasources visible in their own facet, or the user can
never switch (FC1).
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from local_ingestion.platform.search.facets import compute_facets
from local_ingestion.platform.storage.schema import reset_schema

pytestmark = pytest.mark.skipif(
    os.getenv("PG_TEST") != "1",
    reason="requires a running PostgreSQL (set PG_TEST=1)",
)

DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"

DS_A = 9301
DS_B = 9302
SCHEMA_1 = 9301
SCHEMA_2 = 9302
DB_ID = 9301

# (id, datasource_id, schema_id, name, grade, owner, tags)
TABLES = [
    (9401, DS_A, SCHEMA_1, "orders", 3, "alice", ["pii"]),
    (9402, DS_A, SCHEMA_1, "payments", 4, "bob", []),
    (9403, DS_B, SCHEMA_2, "events", 3, "alice", ["pii"]),
]


@pytest.fixture(scope="module")
def seeded():
    engine = create_engine(os.getenv("DATABASE_URL", DEFAULT_URL), future=True)
    reset_schema(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with engine.begin() as conn:
        for ds_id, code in ((DS_A, "ds_a"), (DS_B, "ds_b")):
            conn.execute(
                text(
                    "INSERT INTO datasource (id, code, name, ds_type) "
                    "VALUES (:i,:c,:c,'postgres')"
                ),
                {"i": ds_id, "c": code},
            )
        conn.execute(
            text(
                "INSERT INTO catalog_database (id, datasource_id, name, fqn) "
                "VALUES (:i,:d,'db','ds_a.db')"
            ),
            {"i": DB_ID, "d": DS_A},
        )
        for schema_id, name in ((SCHEMA_1, "sales"), (SCHEMA_2, "ops")):
            conn.execute(
                text(
                    "INSERT INTO catalog_schema (id, datasource_id, database_id, name, fqn) "
                    "VALUES (:i,:d,:db,:n,'ds_a.db.' || :n)"
                ),
                {"i": schema_id, "d": DS_A, "db": DB_ID, "n": name},
            )
        for tid, ds_id, schema_id, name, grade, owner, tags in TABLES:
            conn.execute(
                text(
                    "INSERT INTO catalog_table "
                    "(id, datasource_id, schema_id, name, fqn, grade_level, owner, tags) "
                    "VALUES (:i,:d,:s,:n,'fqn.' || :n,:g,:o,CAST(:t AS jsonb))"
                ),
                {
                    "i": tid,
                    "d": ds_id,
                    "s": schema_id,
                    "n": name,
                    "g": grade,
                    "o": owner,
                    "t": __import__("json").dumps(tags),
                },
            )

    yield factory, engine
    engine.dispose()


def _counts(facets: dict, dimension: str) -> dict[str, int]:
    return {row["value"]: row["count"] for row in facets[dimension]}


def test_facet_counts_match_the_data(seeded):
    factory, _ = seeded
    facets = compute_facets(factory)

    assert _counts(facets, "datasource") == {str(DS_A): 2, str(DS_B): 1}
    assert _counts(facets, "grade") == {"3": 2, "4": 1}
    assert _counts(facets, "owner") == {"alice": 2, "bob": 1}
    assert _counts(facets, "tag") == {"pii": 2}


def test_schema_facet_is_labelled_with_names(seeded):
    factory, _ = seeded
    facets = compute_facets(factory)
    labels = {row["value"]: row["label"] for row in facets["schema"]}
    assert labels[str(SCHEMA_1)] == "sales"
    assert labels[str(SCHEMA_2)] == "ops"


def test_other_dimensions_narrow_when_one_is_selected(seeded):
    """Filtering by datasource must narrow grade/owner/tag (FC1)."""
    factory, _ = seeded
    facets = compute_facets(factory, datasource_id=DS_A)

    assert _counts(facets, "grade") == {"3": 1, "4": 1}
    assert _counts(facets, "owner") == {"alice": 1, "bob": 1}


def test_selected_dimension_stays_fully_visible(seeded):
    """...but the datasource facet itself must still list datasource B.

    Otherwise picking one datasource erases the alternative and the user is
    stuck — the whole reason coordinated faceting exists.
    """
    factory, _ = seeded
    facets = compute_facets(factory, datasource_id=DS_A)
    assert _counts(facets, "datasource") == {str(DS_A): 2, str(DS_B): 1}


def test_term_filter_applies_to_facets(seeded):
    factory, _ = seeded
    facets = compute_facets(factory, term="order")
    assert _counts(facets, "datasource") == {str(DS_A): 1}


def test_top_n_caps_each_dimension(seeded):
    factory, _ = seeded
    facets = compute_facets(factory, top_n=1)
    for dimension, rows in facets.items():
        assert len(rows) <= 1, f"{dimension} exceeded top_n"


def test_facets_agree_with_a_direct_query(seeded):
    """AC-3.1: counts must equal what a plain GROUP BY returns."""
    factory, engine = seeded
    facets = compute_facets(factory)

    with engine.connect() as conn:
        direct = dict(
            conn.execute(
                text(
                    "SELECT datasource_id::text, COUNT(*) FROM catalog_table "
                    "WHERE deleted_at IS NULL GROUP BY 1"
                )
            ).all()
        )

    assert _counts(facets, "datasource") == direct
