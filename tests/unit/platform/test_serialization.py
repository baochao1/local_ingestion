"""camelCase / snake_case serialization tests"""
from typing import Optional

import pytest
from pydantic import BaseModel

from local_ingestion.platform.api.serialization import (
    SerializationDepthError,
    camelize,
    snakify,
    to_camel,
    to_snake,
)


class TestToCamel:
    @pytest.mark.parametrize(
        "snake,expected",
        [
            ("fqn", "fqn"),
            ("id", "id"),
            ("name", "name"),
            ("data_type", "dataType"),
            ("numeric_precision", "numericPrecision"),
            ("fully_qualified_name", "fullyQualifiedName"),
            ("datasource_id", "datasourceId"),
            ("", ""),
            ("alreadyCamel", "alreadyCamel"),
        ],
    )
    def test_to_camel(self, snake, expected):
        assert to_camel(snake) == expected

    def test_double_underscore_collapsed(self):
        assert to_camel("a__b") == "aB"


class TestToSnake:
    @pytest.mark.parametrize(
        "camel,expected",
        [
            ("fqn", "fqn"),
            ("id", "id"),
            ("dataType", "data_type"),
            ("fullyQualifiedName", "fully_qualified_name"),
            ("numericPrecision", "numeric_precision"),
            ("HTTPServer", "http_server"),
            ("parseFQNValue", "parse_fqn_value"),
            ("sha256Hash", "sha256_hash"),
            ("data_type", "data_type"),
            ("", ""),
        ],
    )
    def test_to_snake(self, camel, expected):
        assert to_snake(camel) == expected

    def test_idempotent_on_snake(self):
        assert to_snake(to_snake("data_type")) == "data_type"


class TestRoundTrip:
    @pytest.mark.parametrize(
        "snake",
        [
            "fqn",
            "id",
            "name",
            "data_type",
            "numeric_precision",
            "fully_qualified_name",
            "datasource_id",
        ],
    )
    def test_snake_to_camel_and_back(self, snake):
        assert to_snake(to_camel(snake)) == snake

    def test_dict_roundtrip(self):
        payload = {"fqn": "t", "data_type": "int", "numeric_precision": 10}
        assert snakify(camelize(payload)) == payload


class TestCamelize:
    def test_flat_dict(self):
        assert camelize({"fqn": "t", "data_type": "int"}) == {
            "fqn": "t",
            "dataType": "int",
        }

    def test_nested_dict(self):
        payload = {"table_name": "t", "owner": {"user_id": 1, "team_name": "x"}}
        assert camelize(payload) == {
            "tableName": "t",
            "owner": {"userId": 1, "teamName": "x"},
        }

    def test_nested_list_of_dicts(self):
        payload = {"column_list": [{"column_name": "a"}, {"column_name": "b"}]}
        assert camelize(payload) == {
            "columnList": [{"columnName": "a"}, {"columnName": "b"}]
        }

    def test_list_root(self):
        assert camelize([{"data_type": "int"}]) == [{"dataType": "int"}]

    def test_non_string_keys_preserved(self):
        assert camelize({1: {"data_type": "int"}}) == {1: {"dataType": "int"}}

    def test_values_not_modified(self):
        assert camelize({"note": "data_type_stays"}) == {
            "note": "data_type_stays"
        }

    def test_scalar_passthrough(self):
        assert camelize(42) == 42
        assert camelize(None) is None


class TestSnakify:
    def test_flat_dict(self):
        assert snakify({"fqn": "t", "dataType": "int"}) == {
            "fqn": "t",
            "data_type": "int",
        }

    def test_nested(self):
        payload = {"tableName": "t", "columns": [{"columnName": "a"}]}
        assert snakify(payload) == {
            "table_name": "t",
            "columns": [{"column_name": "a"}],
        }


class _SnakeColumn(BaseModel):
    column_name: str
    data_type: str
    numeric_precision: Optional[int] = None


class _SnakeTable(BaseModel):
    fully_qualified_name: str
    columns: list[_SnakeColumn] = []


class _CamelTable(BaseModel):
    name: str
    fullyQualifiedName: str
    dataTypeDisplay: str = ""


class TestPydanticModels:
    def test_snake_model_camelized(self):
        model = _SnakeTable(
            fully_qualified_name="db.s.t",
            columns=[
                _SnakeColumn(
                    column_name="id", data_type="int", numeric_precision=10
                )
            ],
        )
        assert camelize(model) == {
            "fullyQualifiedName": "db.s.t",
            "columns": [
                {"columnName": "id", "dataType": "int", "numericPrecision": 10}
            ],
        }

    def test_already_camel_model_is_identity(self):
        model = _CamelTable(
            name="t", fullyQualifiedName="db.s.t", dataTypeDisplay="int"
        )
        assert camelize(model) == {
            "name": "t",
            "fullyQualifiedName": "db.s.t",
            "dataTypeDisplay": "int",
        }

    def test_camel_model_to_snake(self):
        model = _CamelTable(
            name="t", fullyQualifiedName="db.s.t", dataTypeDisplay="int"
        )
        assert snakify(model) == {
            "name": "t",
            "fully_qualified_name": "db.s.t",
            "data_type_display": "int",
        }

    def test_pydantic_roundtrip(self):
        model = _SnakeTable(
            fully_qualified_name="db.s.t",
            columns=[_SnakeColumn(column_name="id", data_type="int")],
        )
        assert snakify(camelize(model)) == model.model_dump()


class TestDepthGuard:
    def test_depth_exceeded_raises(self):
        payload: dict = {"leaf": 1}
        for _ in range(40):
            payload = {"nested": payload}
        with pytest.raises(SerializationDepthError):
            camelize(payload)

    def test_custom_max_depth(self):
        payload = {"a": {"b": 1}}
        assert camelize(payload, max_depth=2) == {"a": {"b": 1}}
