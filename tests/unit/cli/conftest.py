"""Pytest fixtures for CLI tests"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))


@pytest.fixture
def mock_database():
    """Fixture providing a mock database for testing"""
    from tests.unit.cli.test_commands import MockDatabase

    db = MockDatabase()
    yield db
    db.clear()


@pytest.fixture
def mock_metadata_service(mock_database):
    """Fixture providing a mock metadata service"""
    from local_ingestion.api.service import MetadataService

    return MetadataService(mock_database)


@pytest.fixture
def sample_table():
    """Fixture providing a sample table"""
    from local_ingestion.schema.data.table import Table, Column

    return Table(
        name="users",
        fullyQualifiedName="prod.mysql.users",
        database="mysql",
        databaseSchema="public",
        columns=[
            Column(name="id", dataType="INTEGER"),
            Column(name="name", dataType="STRING"),
        ],
    )


@pytest.fixture
def sample_database():
    """Fixture providing a sample database"""
    from local_ingestion.schema.data.database import Database

    return Database(
        name="prod_db",
        fullyQualifiedName="prod.prod_db",
        description="Production database",
    )
