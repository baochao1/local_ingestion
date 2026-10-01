"""Database model tests"""
import pytest
from local_ingestion.schema.data.database import Database, DatabaseSchema


class TestDatabase:
    def test_database_creation(self):
        db = Database(name="mydb", fullyQualifiedName="mydb")
        assert db.name == "mydb"

    def test_database_with_description(self):
        db = Database(
            name="mydb",
            fullyQualifiedName="mydb",
            description="My database"
        )
        assert db.description == "My database"


class TestDatabaseSchema:
    def test_schema_creation(self):
        schema = DatabaseSchema(
            name="public",
            fullyQualifiedName="mydb.public"
        )
        assert schema.name == "public"

    def test_schema_with_database(self):
        schema = DatabaseSchema(
            name="public",
            fullyQualifiedName="mydb.public",
            database="mydb"
        )
        assert schema.database == "mydb"
