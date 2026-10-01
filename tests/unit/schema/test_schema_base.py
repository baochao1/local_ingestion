"""Schema base types tests"""
import pytest
from local_ingestion.schema.base import FQN, EntityReference, StackTraceError, ServiceType, DataType


class TestFQN:
    def test_from_string_simple(self):
        fqn = FQN.from_string("database.table")
        assert fqn.root == "database"
        assert fqn.children == ["table"]

    def test_from_string_nested(self):
        fqn = FQN.from_string("db.schema.table.column")
        assert fqn.root == "db"
        assert fqn.children == ["schema", "table", "column"]

    def test_str_representation(self):
        fqn = FQN(root="db", children=["schema", "table"])
        assert str(fqn) == "db.schema.table"

    def test_parent(self):
        fqn = FQN(root="db", children=["schema", "table"])
        parent = fqn.parent
        assert parent is not None
        assert str(parent) == "db.schema"


class TestEntityReference:
    def test_basic_creation(self):
        ref = EntityReference(type="Table", name="users")
        assert ref.type == "Table"
        assert ref.name == "users"


class TestStackTraceError:
    def test_creation(self):
        error = StackTraceError(name="TestError", error="Something went wrong")
        assert error.name == "TestError"
        assert error.error == "Something went wrong"
        assert error.timestamp is not None


class TestEnums:
    def test_service_type_values(self):
        assert ServiceType.DATABASE.value == "Database"
        assert ServiceType.MESSAGING.value == "Messaging"

    def test_data_type_values(self):
        assert DataType.STRING.value == "STRING"
        assert DataType.INTEGER.value == "INTEGER"
