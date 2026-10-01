"""Table model tests"""
import pytest
from local_ingestion.schema.data.table import Column, Table, TableProfile
from local_ingestion.schema.base import DataType


class TestColumn:
    def test_column_creation(self):
        col = Column(name="id", dataType=DataType.INTEGER, nullable=False)
        assert col.name == "id"
        assert col.dataType == DataType.INTEGER
        assert col.nullable is False

    def test_column_defaults(self):
        col = Column(name="name", dataType=DataType.STRING)
        assert col.nullable is True
        assert col.tags == []


class TestTable:
    def test_table_creation(self):
        table = Table(
            name="users",
            fullyQualifiedName="db.schema.users"
        )
        assert table.name == "users"
        assert table.columns == []

    def test_table_with_columns(self):
        columns = [
            Column(name="id", dataType=DataType.INTEGER),
            Column(name="name", dataType=DataType.STRING),
        ]
        table = Table(
            name="users",
            fullyQualifiedName="db.schema.users",
            columns=columns
        )
        assert len(table.columns) == 2

    def test_table_serialization(self):
        table = Table(
            name="users",
            fullyQualifiedName="db.schema.users",
            database="db",
            databaseSchema="schema"
        )
        data = table.model_dump()
        assert data["name"] == "users"
        assert data["database"] == "db"


class TestTableProfile:
    def test_profile_creation(self):
        profile = TableProfile(rowCount=1000, columnCount=5)
        assert profile.rowCount == 1000
        assert profile.columnCount == 5
