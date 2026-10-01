"""Keyset pagination tests"""
import base64

import pytest
from sqlalchemy import Integer, String, column
from sqlalchemy.dialects import postgresql

from local_ingestion.platform.api.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CursorError,
    InvalidCursorError,
    KeysetIndexMismatchError,
    KeysetPage,
    assert_index_prefix,
    build_keyset_clause,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    keyset_clause_from_cursor,
)


class _Row:
    """模拟 ORM 行对象"""

    def __init__(self, fqn: str, id: int) -> None:
        self.fqn = fqn
        self.id = id


def _compile(clause):
    """把表达式编译成 PG SQL 字面量形式，便于断言。"""
    return str(
        clause.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


class TestCursorRoundTrip:
    def test_roundtrip_simple(self):
        cursor = encode_cursor({"fqn": "pg.public.users", "id": 42})
        assert decode_cursor(cursor) == ("pg.public.users", 42)

    def test_roundtrip_with_unicode(self):
        fqn = "pg.默认库.public.用户表"
        cursor = encode_cursor({"fqn": fqn, "id": 10000000001})
        assert decode_cursor(cursor) == (fqn, 10000000001)

    def test_roundtrip_fqn_containing_separator(self):
        cursor = encode_cursor({"fqn": "pg|a.public.users", "id": 7})
        assert decode_cursor(cursor) == ("pg|a.public.users", 7)

    def test_cursor_is_url_safe(self):
        cursor = encode_cursor({"fqn": "pg.public.?>&users", "id": 1})
        assert "=" not in cursor
        assert "+" not in cursor and "/" not in cursor

    def test_encode_from_object(self):
        assert decode_cursor(encode_cursor(_Row("pg.public.t1", 5))) == (
            "pg.public.t1",
            5,
        )

    def test_encode_from_tuple(self):
        assert decode_cursor(encode_cursor(("pg.public.t1", 5))) == (
            "pg.public.t1",
            5,
        )

    def test_encode_accepts_string_id(self):
        assert decode_cursor(encode_cursor({"fqn": "t", "id": "9"})) == ("t", 9)


class TestDecodeErrors:
    @pytest.mark.parametrize("bad", ["", "   ", "not-base64!!", "@@@@"])
    def test_invalid_cursor_raises(self, bad):
        with pytest.raises(InvalidCursorError):
            decode_cursor(bad)

    def test_missing_separator_raises(self):
        payload = base64.urlsafe_b64encode(b"pg.public.users").decode()
        with pytest.raises(InvalidCursorError):
            decode_cursor(payload.rstrip("="))

    def test_non_integer_id_raises(self):
        payload = base64.urlsafe_b64encode(b"pg.public.users|abc").decode()
        with pytest.raises(InvalidCursorError):
            decode_cursor(payload.rstrip("="))

    def test_non_string_raises(self):
        with pytest.raises(InvalidCursorError):
            decode_cursor(123)  # type: ignore[arg-type]


class TestEncodeErrors:
    def test_missing_key_raises(self):
        with pytest.raises(CursorError):
            encode_cursor({"fqn": "pg.public.users"})

    def test_bad_object_raises(self):
        with pytest.raises(CursorError):
            encode_cursor(object())


class TestBuildKeysetClause:
    def test_row_value_comparison_sql(self):
        clause = build_keyset_clause(
            [
                (column("fqn", String), "pg.public.users"),
                (column("id", Integer), 42),
            ]
        )
        sql = _compile(clause).replace(" ", "")
        assert "(fqn,id)>" in sql

    def test_empty_returns_true(self):
        assert _compile(build_keyset_clause([])).strip().lower() == "true"

    def test_from_cursor(self):
        cursor = encode_cursor({"fqn": "pg.public.users", "id": 42})
        clause = keyset_clause_from_cursor(
            cursor, column("fqn", String), column("id", Integer)
        )
        assert "(fqn,id)>" in _compile(clause).replace(" ", "")

    def test_from_empty_cursor_is_noop(self):
        clause = keyset_clause_from_cursor(None, column("fqn"), column("id"))
        assert _compile(clause).strip().lower() == "true"


class TestAssertIndexPrefix:
    def test_exact_match_ok(self):
        assert_index_prefix(("fqn", "id"), ("fqn", "id"))

    def test_prefix_subset_ok(self):
        assert_index_prefix(
            ("datasource_id", "fqn", "id"),
            ("datasource_id", "fqn", "id", "tenant_id"),
        )

    def test_mismatch_raises(self):
        with pytest.raises(KeysetIndexMismatchError):
            assert_index_prefix(("name", "id"), ("fqn", "id"))

    def test_reverse_order_raises(self):
        with pytest.raises(KeysetIndexMismatchError):
            assert_index_prefix(("id", "fqn"), ("fqn", "id"))

    def test_shorter_index_raises(self):
        with pytest.raises(KeysetIndexMismatchError):
            assert_index_prefix(("datasource_id", "fqn", "id"), ("fqn", "id"))

    def test_empty_sort_keys_raises(self):
        with pytest.raises(KeysetIndexMismatchError):
            assert_index_prefix((), ("fqn", "id"))


class TestKeysetPage:
    def test_empty_result(self):
        page = KeysetPage.build([], limit=20, approx_total=0)
        assert page.items == []
        assert page.has_more is False
        assert page.next_cursor is None

    def test_partial_last_page(self):
        rows = [{"fqn": f"t{i}", "id": i} for i in range(3)]
        page = KeysetPage.build(rows, limit=20)
        assert len(page.items) == 3
        assert page.has_more is False
        assert page.next_cursor is None

    def test_exactly_limit_rows_no_more(self):
        rows = [{"fqn": f"t{i}", "id": i} for i in range(2)]
        page = KeysetPage.build(rows, limit=2)
        assert page.has_more is False
        assert page.next_cursor is None

    def test_over_fetch_sets_has_more_and_cursor(self):
        rows = [{"fqn": f"t{i}", "id": i} for i in range(3)]
        page = KeysetPage.build(rows, limit=2, approx_total=1000)
        assert len(page.items) == 2
        assert page.has_more is True
        assert decode_cursor(page.next_cursor) == ("t1", 1)
        assert page.approx_total == 1000

    def test_zero_limit_raises(self):
        with pytest.raises(ValueError):
            KeysetPage.build([], limit=0)

    def test_to_dict_camel(self):
        page = KeysetPage.build(
            [{"fqn": "t0", "id": 0}, {"fqn": "t1", "id": 1}], limit=1
        )
        payload = page.to_dict()
        assert set(payload) == {"items", "nextCursor", "hasMore", "approxTotal"}
        assert payload["hasMore"] is True
        assert payload["items"] == [{"fqn": "t0", "id": 0}]

    def test_to_dict_snake(self):
        page = KeysetPage.build([], limit=10, approx_total=0)
        payload = page.to_dict(camel=False)
        assert set(payload) == {"items", "next_cursor", "has_more", "approx_total"}
        assert payload["has_more"] is False


class TestClampLimit:
    def test_default(self):
        assert clamp_limit(None) == DEFAULT_PAGE_SIZE

    def test_upper_bound(self):
        assert clamp_limit(100000) == MAX_PAGE_SIZE

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            clamp_limit("abc")  # type: ignore[arg-type]
