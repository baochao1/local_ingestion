"""Unit tests for CLI commands"""
import argparse
import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from local_ingestion.cli.commands.ingest import (
    IngestTableCommand,
    IngestDatabaseCommand,
    BulkIngestCommand,
    InMemoryDatabase,
)
from local_ingestion.cli.commands.metadata import (
    ListTablesCommand,
    GetTableCommand,
    ListDatabasesCommand,
    GetDatabaseCommand,
)
from local_ingestion.cli.commands.connection import (
    TestConnectionCommand,
    ConnectionInfoCommand,
)
from local_ingestion.api.service import MetadataService
from local_ingestion.api.exceptions import NotFoundError, ConflictError, ValidationError
from local_ingestion.schema.data.table import Table, Column
from local_ingestion.schema.data.database import Database


class MockDatabase:
    """Mock database for testing"""

    def __init__(self):
        self._store: dict[str, list[dict]] = {
            "metadata_tables": [],
            "metadata_databases": [],
            "workflows": [],
        }

    def insert(self, table_name: str, data: dict) -> str:
        self._store[table_name].append(data)
        return data.get("id", "")

    def find_one(self, table_name: str, query: dict) -> dict | None:
        for item in self._store.get(table_name, []):
            if all(item.get(k) == v for k, v in query.items()):
                return item
        return None

    def find_many(self, table_name: str, query: dict) -> list[dict]:
        results = self._store.get(table_name, [])
        if not query:
            return list(results)
        return [
            item
            for item in results
            if all(item.get(k) == v for k, v in query.items())
        ]

    def delete_one(self, table_name: str, query: dict) -> bool:
        for i, item in enumerate(self._store.get(table_name, [])):
            if all(item.get(k) == v for k, v in query.items()):
                self._store[table_name].pop(i)
                return True
        return False

    def clear(self):
        for key in self._store:
            self._store[key] = []


class TestTableIngestCommand:
    """Tests for TableIngestCommand"""

    def setup_method(self):
        self.db = MockDatabase()
        self.service = MetadataService(self.db)
        self.command = IngestTableCommand(metadata_service=self.service)

    def test_ingest_table_with_required_args(self):
        """Test ingesting a table with required arguments only"""
        args = argparse.Namespace(
            database="test_db",
            table="users",
            columns=False,
            config=None,
            schema="default",
        )

        result = self.command.execute(args)

        assert result == 0
        stored = self.db.find_one("metadata_tables", {"fullyQualifiedName": "test_db.default.users"})
        assert stored is not None
        assert stored["name"] == "users"

    def test_ingest_table_with_custom_schema(self):
        """Test ingesting a table with a custom schema"""
        args = argparse.Namespace(
            database="prod",
            table="orders",
            columns=False,
            config=None,
            schema="sales",
        )

        result = self.command.execute(args)

        assert result == 0
        stored = self.db.find_one("metadata_tables", {"fullyQualifiedName": "prod.sales.orders"})
        assert stored is not None

    def test_ingest_table_missing_database(self):
        """Test that missing database argument raises error"""
        command = IngestTableCommand()
        with pytest.raises(SystemExit):
            command.parse_args(["--table", "users"])

    def test_ingest_table_missing_table(self):
        """Test that missing table argument raises error"""
        command = IngestTableCommand()
        with pytest.raises(SystemExit):
            command.parse_args(["--database", "test_db"])

    def test_ingest_table_with_columns_config(self):
        """Test ingesting a table with column configuration"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(
                {
                    "columns": [
                        {"name": "id", "dataType": "INTEGER"},
                        {"name": "name", "dataType": "STRING"},
                    ]
                },
                f,
            )
            config_path = f.name

        try:
            args = argparse.Namespace(
                database="test_db",
                table="users",
                columns=True,
                config=config_path,
                schema="default",
            )

            result = self.command.execute(args)

            assert result == 0
            stored = self.db.find_one("metadata_tables", {"fullyQualifiedName": "test_db.default.users"})
            assert stored is not None
            assert len(stored["columns"]) == 2
        finally:
            os.unlink(config_path)


class TestDatabaseIngestCommand:
    """Tests for DatabaseIngestCommand"""

    def setup_method(self):
        self.db = MockDatabase()
        self.service = MetadataService(self.db)
        self.command = IngestDatabaseCommand(metadata_service=self.service)

    def test_ingest_database_with_required_args(self):
        """Test ingesting a database with required arguments only"""
        args = argparse.Namespace(
            database="test_db",
            include_schemas=False,
            config=None,
            service_name="default",
        )

        result = self.command.execute(args)

        assert result == 0
        stored = self.db.find_one("metadata_databases", {"fullyQualifiedName": "default.test_db"})
        assert stored is not None
        assert stored["name"] == "test_db"

    def test_ingest_database_missing_database(self):
        """Test that missing database argument raises error"""
        command = IngestDatabaseCommand()
        with pytest.raises(SystemExit):
            command.parse_args([])

    def test_ingest_database_with_description(self):
        """Test ingesting a database with description"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"description": "Production database"}, f)
            config_path = f.name

        try:
            args = argparse.Namespace(
                database="prod_db",
                include_schemas=False,
                config=config_path,
                service_name="prod",
            )

            result = self.command.execute(args)

            assert result == 0
            stored = self.db.find_one(
                "metadata_databases", {"fullyQualifiedName": "prod.prod_db"}
            )
            assert stored is not None
            assert stored["description"] == "Production database"
        finally:
            os.unlink(config_path)


class TestBulkIngestCommand:
    """Tests for BulkIngestCommand"""

    def setup_method(self):
        self.db = MockDatabase()
        self.service = MetadataService(self.db)
        self.command = BulkIngestCommand(metadata_service=self.service)

    def test_bulk_ingest_dry_run(self):
        """Test bulk ingestion in dry-run mode"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(
                {
                    "tables": [
                        {
                            "name": "users",
                            "fullyQualifiedName": "prod.mysql.users",
                            "columns": [],
                        },
                        {
                            "name": "orders",
                            "fullyQualifiedName": "prod.mysql.orders",
                            "columns": [],
                        },
                    ]
                },
                f,
            )
            config_path = f.name

        try:
            args = argparse.Namespace(
                source=config_path,
                parallel=False,
                workers=4,
                dry_run=True,
            )

            result = self.command.execute(args)

            assert result == 0
            assert len(self.db.find_many("metadata_tables", {})) == 0
        finally:
            os.unlink(config_path)

    def test_bulk_ingest_actual(self):
        """Test actual bulk ingestion"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(
                {
                    "tables": [
                        {
                            "name": "users",
                            "fullyQualifiedName": "prod.mysql.users",
                            "columns": [],
                        },
                        {
                            "name": "orders",
                            "fullyQualifiedName": "prod.mysql.orders",
                            "columns": [],
                        },
                    ]
                },
                f,
            )
            config_path = f.name

        try:
            args = argparse.Namespace(
                source=config_path,
                parallel=False,
                workers=4,
                dry_run=False,
            )

            result = self.command.execute(args)

            assert result == 0
            tables = self.db.find_many("metadata_tables", {})
            assert len(tables) == 2
        finally:
            os.unlink(config_path)

    def test_bulk_ingest_missing_source(self):
        """Test that missing source file raises error"""
        args = argparse.Namespace(
            source="/nonexistent/config.json",
            parallel=False,
            workers=4,
            dry_run=False,
        )

        result = self.command.execute(args)

        assert result == 1


class TestListTablesCommand:
    """Tests for ListTablesCommand"""

    def setup_method(self):
        self.db = MockDatabase()
        self.service = MetadataService(self.db)
        self.command = ListTablesCommand(metadata_service=self.service)

        table1 = Table(name="users", fullyQualifiedName="db.schema.users")
        table2 = Table(name="orders", fullyQualifiedName="db.schema.orders")
        self.service.ingest_table(table1)
        self.service.ingest_table(table2)

    def test_list_tables_default(self):
        """Test listing tables with default options"""
        args = argparse.Namespace(
            database=None,
            schema=None,
            limit=100,
            format="table",
        )

        result = self.command.execute(args)

        assert result == 0

    def test_list_tables_with_limit(self):
        """Test listing tables with a limit"""
        args = argparse.Namespace(
            database=None,
            schema=None,
            limit=1,
            format="table",
        )

        result = self.command.execute(args)

        assert result == 0

    def test_list_tables_json_format(self):
        """Test listing tables in JSON format"""
        args = argparse.Namespace(
            database=None,
            schema=None,
            limit=100,
            format="json",
        )

        result = self.command.execute(args)

        assert result == 0


class TestGetTableCommand:
    """Tests for GetTableCommand"""

    def setup_method(self):
        self.db = MockDatabase()
        self.service = MetadataService(self.db)
        self.command = GetTableCommand(metadata_service=self.service)

        self.table = Table(
            name="users",
            fullyQualifiedName="db.schema.users",
            columns=[Column(name="id", dataType="INTEGER")],
        )
        self.service.ingest_table(self.table)

    def test_get_table_success(self):
        """Test getting an existing table"""
        args = argparse.Namespace(
            qualified_name="db.schema.users",
            format="detailed",
        )

        result = self.command.execute(args)

        assert result == 0

    def test_get_table_not_found(self):
        """Test getting a non-existent table"""
        args = argparse.Namespace(
            qualified_name="nonexistent.schema.table",
            format="detailed",
        )

        result = self.command.execute(args)

        assert result == 1


class TestListDatabasesCommand:
    """Tests for ListDatabasesCommand"""

    def setup_method(self):
        self.db = MockDatabase()
        self.service = MetadataService(self.db)
        self.command = ListDatabasesCommand(metadata_service=self.service)

        db1 = Database(name="db1", fullyQualifiedName="prod.db1")
        db2 = Database(name="db2", fullyQualifiedName="prod.db2")
        self.service.ingest_database(db1)
        self.service.ingest_database(db2)

    def test_list_databases_default(self):
        """Test listing databases with default options"""
        args = argparse.Namespace(
            limit=100,
            format="table",
        )

        result = self.command.execute(args)

        assert result == 0


class TestGetDatabaseCommand:
    """Tests for GetDatabaseCommand"""

    def setup_method(self):
        self.db = MockDatabase()
        self.service = MetadataService(self.db)
        self.command = GetDatabaseCommand(metadata_service=self.service)

        self.database = Database(
            name="prod_db",
            fullyQualifiedName="prod.prod_db",
            description="Production database",
        )
        self.service.ingest_database(self.database)

    def test_get_database_success(self):
        """Test getting an existing database"""
        args = argparse.Namespace(
            qualified_name="prod.prod_db",
            format="detailed",
        )

        result = self.command.execute(args)

        assert result == 0

    def test_get_database_not_found(self):
        """Test getting a non-existent database"""
        args = argparse.Namespace(
            qualified_name="nonexistent.db",
            format="detailed",
        )

        result = self.command.execute(args)

        assert result == 1


class TestConnectionCommands:
    """Tests for connection commands"""

    def test_test_connection_missing_type(self):
        """Test that missing type argument raises error"""
        command = TestConnectionCommand()
        with pytest.raises(SystemExit):
            command.parse_args(["--config", "config.json"])

    def test_connection_info_mysql(self):
        """Test getting connection info for MySQL"""
        command = ConnectionInfoCommand()
        args = argparse.Namespace(
            type="mysql",
            format="table",
        )

        result = command.execute(args)

        assert result == 0


class TestArgumentValidation:
    """Tests for argument validation"""

    def test_table_command_argument_parsing(self):
        """Test that table command parses arguments correctly"""
        command = IngestTableCommand()
        args = command.parse_args(
            ["--database", "test_db", "--table", "users", "--schema", "public"]
        )

        assert args.database == "test_db"
        assert args.table == "users"
        assert args.schema == "public"
        assert args.columns is False

    def test_database_command_argument_parsing(self):
        """Test that database command parses arguments correctly"""
        command = IngestDatabaseCommand()
        args = command.parse_args(
            ["--database", "test_db", "--include-schemas", "--service-name", "prod"]
        )

        assert args.database == "test_db"
        assert args.include_schemas is True
        assert args.service_name == "prod"

    def test_list_tables_command_argument_parsing(self):
        """Test that list tables command parses arguments correctly"""
        command = ListTablesCommand()
        args = command.parse_args(
            ["--database", "test_db", "--schema", "public", "--limit", "50", "--format", "json"]
        )

        assert args.database == "test_db"
        assert args.schema == "public"
        assert args.limit == 50
        assert args.format == "json"
