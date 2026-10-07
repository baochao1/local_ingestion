"""FR-M4: resilient lineage parsing.

The behaviours under test are the ones that make lineage trustworthy enough to
switch on by default: CTEs must not appear as phantom source tables, a broken
statement must explain itself instead of contributing zero edges, and one
pathological statement must not stall the whole run.
"""
from __future__ import annotations

import time

from local_ingestion.platform.lineage import parse
from local_ingestion.platform.lineage.parse import ParseOutcome, parse_definition

DS, DB, SCHEMA, VIEW = "ds1", "db1", "sales", "v_orders"


def test_cte_is_folded_into_its_source():
    """WITH x AS (SELECT ... FROM t1) SELECT * FROM x → edge from t1, not x."""
    sql = "WITH x AS (SELECT id FROM sales.t1) SELECT id FROM x"
    outcome = parse_definition(DS, DB, SCHEMA, VIEW, sql)

    assert outcome.ok, outcome.error
    sources = {edge[0] for edge in outcome.table_edges}
    assert not any(source.endswith(".x") for source in sources), "CTE leaked as a source"
    assert any(source.endswith(".t1") for source in sources)


def test_multiple_ctes_are_all_folded():
    sql = (
        "WITH a AS (SELECT id FROM sales.t1), "
        "b AS (SELECT id FROM a) "
        "SELECT id FROM b"
    )
    outcome = parse_definition(DS, DB, SCHEMA, VIEW, sql)
    sources = {edge[0] for edge in outcome.table_edges}
    assert not ({"a", "b"} & {s.rsplit(".", 1)[-1] for s in sources})
    assert any(source.endswith(".t1") for source in sources)


def test_view_itself_is_not_a_source():
    sql = f"SELECT id FROM {SCHEMA}.t1"
    outcome = parse_definition(DS, DB, SCHEMA, VIEW, sql)
    assert all(not edge[0].endswith(f".{VIEW}") for edge in outcome.table_edges)


def test_column_lineage_through_a_cte():
    sql = "WITH x AS (SELECT user_id FROM sales.t1) SELECT user_id AS uid FROM x"
    outcome = parse_definition(DS, DB, SCHEMA, VIEW, sql)
    assert outcome.ok, outcome.error
    assert outcome.column_edges, "expected column edges through the CTE"


def test_empty_definition_reports_a_reason():
    outcome = parse_definition(
        DS, DB, SCHEMA, VIEW, "   "
    )
    assert not outcome.ok
    assert "empty" in (outcome.error or "")


def test_failure_is_captured_not_swallowed():
    """A parse failure must leave an explanation (FR-M4.4)."""

    def boom(*_args, **_kwargs):
        raise ValueError("intentional")

    original = parse._PARSERS
    parse._PARSERS = {"boom": boom}
    try:
        outcome = parse_definition(DS, DB, SCHEMA, VIEW, "SELECT 1")
    finally:
        parse._PARSERS = original

    assert not outcome.ok
    assert "intentional" in (outcome.error or "")


def test_falls_back_to_the_next_parser():
    def bad(*_args, **_kwargs):
        raise ValueError("first parser failed")

    def good(*_args, **_kwargs):
        return ParseOutcome(table_edges=[("src", "tgt")], parser="good")

    original = parse._PARSERS
    parse._PARSERS = {"bad": bad, "good": good}
    try:
        outcome = parse_definition(DS, DB, SCHEMA, VIEW, "SELECT 1")
    finally:
        parse._PARSERS = original

    assert outcome.ok
    assert outcome.parser == "good"
    assert outcome.table_edges == [("src", "tgt")]


def test_timeout_moves_on_instead_of_hanging():
    def slow(*_args, **_kwargs):
        time.sleep(5)
        return ParseOutcome(parser="slow")

    original = parse._PARSERS
    parse._PARSERS = {"slow": slow}
    try:
        started = time.monotonic()
        outcome = parse_definition(DS, DB, SCHEMA, VIEW, "SELECT 1", timeout_sec=0.2)
        elapsed = time.monotonic() - started
    finally:
        parse._PARSERS = original

    assert outcome.timed_out
    assert elapsed < 2, "timeout did not release the caller"


def test_successful_parse_records_the_parser_used():
    outcome = parse_definition(DS, DB, SCHEMA, VIEW, "SELECT id FROM sales.t1")
    assert outcome.ok
    assert outcome.parser == "sqlglot"
