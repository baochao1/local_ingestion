"""MOD-07 T1: dialect view_definition_sql returns parameterized view-def SELECTs."""
import pytest

from local_ingestion.platform.dialect import get_dialect

PARAMS = [
    ("postgres", "pg_get_viewdef"),
    ("mysql", "information_schema.views"),
    ("snowflake", "information_schema.views"),
]


@pytest.mark.parametrize("ds_type,expected_substr", PARAMS)
def test_view_definition_sql_contains_source(ds_type, expected_substr):
    d = get_dialect(ds_type)
    sql = d.view_definition_sql()
    assert expected_substr.lower() in sql.lower()
    assert ":schema" in sql  # must be parameterised per schema
