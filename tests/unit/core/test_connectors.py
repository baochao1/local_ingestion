"""Unit tests for core connectors"""
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from local_ingestion.core.connectors.base import SourceConnector, SinkConnector
from local_ingestion.core.connectors.mysql import MySQLSourceConnector
from local_ingestion.core.connectors.postgres import PostgresSourceConnector
from local_ingestion.core.connectors.snowflake import SnowflakeSourceConnector
from local_ingestion.platform.sinks.local_file import (
    JSONFileSink,
    NDJSONFileSink,
    ParquetFileSink,
    FileFormat,
)
from local_ingestion.schema.data.database import Database, DatabaseSchema
from local_ingestion.schema.data.table import Table, Column
from local_ingestion.schema.metadata.workflow import FileSinkConfig
from local_ingestion.schema.service.connection import (
    MySQLConnection,
    PostgresConnection,
    SnowflakeConnection,
)
from local_ingestion.schema.base import DataType


class TestSourceConnector:
    """Tests for SourceConnector base class"""

    def test_is_connected_initially_false(self):
        """Test that connector is not connected initially"""
        connector = MagicMock(spec=SourceConnector)
        connector.is_connected.return_value = False
        assert connector.is_connected() is False

    def test_connection_state_property(self):
        """Test connection state tracking"""
        connector = MagicMock(spec=SourceConnector)
        connector._connected = False
        assert connector._connected is False


class TestSinkConnector:
    """Tests for SinkConnector base class"""

    def test_is_connected_initially_false(self):
        """Test that sink connector is not connected initially"""
        connector = MagicMock(spec=SinkConnector)
        connector.is_connected.return_value = False
        assert connector.is_connected() is False

    def test_pending_writes_initially_empty(self):
        """Test that pending writes list is initially empty"""
        connector = MagicMock(spec=SinkConnector)
        connector._pending_writes = []
        assert connector._pending_writes == []


class TestMySQLSourceConnector:
    """Tests for MySQL source connector"""

    def test_initialization(self):
        """Test MySQL connector initialization"""
        connector = MySQLSourceConnector()
        assert connector._connected is False
        assert connector._engine is None
        assert connector._session_factory is None
        assert connector._retry_attempts == 3

    def test_connection_config(self):
        """Test MySQL connection configuration"""
        config = MySQLConnection(
            hostPort="localhost:3306",
            username="testuser",
            password="testpass",
            database="testdb",
        )
        conn_str = config.get_connection_string()
        assert "mysql+pymysql://" in conn_str
        assert "testuser:testpass" in conn_str
        assert "localhost:3306" in conn_str
        assert "testdb" in conn_str

    def test_connection_config_without_password(self):
        """Test MySQL connection configuration without password"""
        config = MySQLConnection(
            hostPort="localhost:3306",
            username="testuser",
            database="testdb",
        )
        conn_str = config.get_connection_string()
        assert "mysql+pymysql://" in conn_str
        assert "testuser:" in conn_str

    @patch("local_ingestion.core.connectors.mysql.create_engine")
    def test_connect_success(self, mock_create_engine):
        """Test successful MySQL connection"""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        connector = MySQLSourceConnector()
        config = MySQLConnection(
            hostPort="localhost:3306",
            username="testuser",
            password="testpass",
            database="testdb",
        )

        connector.connect(config)

        assert connector.is_connected() is True
        mock_create_engine.assert_called_once()

    @patch("local_ingestion.core.connectors.mysql.create_engine")
    def test_connect_failure(self, mock_create_engine):
        """Test MySQL connection failure"""
        mock_create_engine.side_effect = Exception("Connection failed")

        connector = MySQLSourceConnector()
        config = MySQLConnection(
            hostPort="localhost:3306",
            username="testuser",
            password="testpass",
            database="testdb",
        )

        with pytest.raises(Exception):
            connector.connect(config)

        assert connector.is_connected() is False

    def test_disconnect(self):
        """Test MySQL disconnection"""
        connector = MySQLSourceConnector()
        connector._connected = True
        mock_engine = MagicMock()
        connector._engine = mock_engine

        connector.disconnect()

        assert connector.is_connected() is False
        mock_engine.dispose.assert_called_once()
        assert connector._engine is None

    def test_map_mysql_type_strings(self):
        """Test MySQL type mapping for string types"""
        connector = MySQLSourceConnector()

        assert connector._map_mysql_type("VARCHAR") == DataType.STRING
        assert connector._map_mysql_type("CHAR") == DataType.STRING
        assert connector._map_mysql_type("TEXT") == DataType.TEXT
        assert connector._map_mysql_type("ENUM") == DataType.STRING

    def test_map_mysql_type_numeric(self):
        """Test MySQL type mapping for numeric types"""
        connector = MySQLSourceConnector()

        assert connector._map_mysql_type("INT") == DataType.INTEGER
        assert connector._map_mysql_type("BIGINT") == DataType.BIGINT
        assert connector._map_mysql_type("SMALLINT") == DataType.SMALLINT
        assert connector._map_mysql_type("TINYINT") == DataType.TINYINT
        assert connector._map_mysql_type("DECIMAL") == DataType.DECIMAL
        assert connector._map_mysql_type("FLOAT") == DataType.FLOAT
        assert connector._map_mysql_type("DOUBLE") == DataType.DOUBLE

    def test_map_mysql_type_datetime(self):
        """Test MySQL type mapping for datetime types"""
        connector = MySQLSourceConnector()

        assert connector._map_mysql_type("DATE") == DataType.DATE
        assert connector._map_mysql_type("TIME") == DataType.TIME
        assert connector._map_mysql_type("DATETIME") == DataType.TIMESTAMP
        assert connector._map_mysql_type("TIMESTAMP") == DataType.TIMESTAMP

    def test_map_mysql_type_boolean(self):
        """Test MySQL type mapping for boolean types"""
        connector = MySQLSourceConnector()

        assert connector._map_mysql_type("BOOLEAN") == DataType.BOOLEAN
        assert connector._map_mysql_type("BOOL") == DataType.BOOLEAN

    def test_map_mysql_type_binary(self):
        """Test MySQL type mapping for binary types"""
        connector = MySQLSourceConnector()

        assert connector._map_mysql_type("BINARY") == DataType.BINARY
        assert connector._map_mysql_type("BLOB") == DataType.BINARY
        assert connector._map_mysql_type("JSON") == DataType.JSON

    def test_map_mysql_type_unknown(self):
        """Test MySQL type mapping for unknown types"""
        connector = MySQLSourceConnector()

        assert connector._map_mysql_type("CUSTOM_TYPE") == DataType.UNKNOWN


class TestPostgresSourceConnector:
    """Tests for PostgreSQL source connector"""

    def test_initialization(self):
        """Test PostgreSQL connector initialization"""
        connector = PostgresSourceConnector()
        assert connector._connected is False
        assert connector._engine is None
        assert connector._retry_attempts == 3

    def test_connection_config(self):
        """Test PostgreSQL connection configuration"""
        config = PostgresConnection(
            hostPort="localhost:5432",
            username="testuser",
            password="testpass",
            database="testdb",
        )
        conn_str = config.get_connection_string()
        assert "postgresql://" in conn_str
        assert "testuser:testpass" in conn_str
        assert "localhost:5432" in conn_str
        assert "testdb" in conn_str

    @patch("local_ingestion.core.connectors.postgres.create_engine")
    def test_connect_success(self, mock_create_engine):
        """Test successful PostgreSQL connection"""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        connector = PostgresSourceConnector()
        config = PostgresConnection(
            hostPort="localhost:5432",
            username="testuser",
            password="testpass",
            database="testdb",
        )

        connector.connect(config)

        assert connector.is_connected() is True
        mock_create_engine.assert_called_once()

    def test_disconnect(self):
        """Test PostgreSQL disconnection"""
        connector = PostgresSourceConnector()
        connector._connected = True
        mock_engine = MagicMock()
        connector._engine = mock_engine

        connector.disconnect()

        assert connector.is_connected() is False
        mock_engine.dispose.assert_called_once()
        assert connector._engine is None

    def test_map_postgres_type_strings(self):
        """Test PostgreSQL type mapping for string types"""
        connector = PostgresSourceConnector()

        assert connector._map_postgres_type("VARCHAR") == DataType.STRING
        assert connector._map_postgres_type("CHAR") == DataType.STRING
        assert connector._map_postgres_type("TEXT") == DataType.TEXT

    def test_map_postgres_type_numeric(self):
        """Test PostgreSQL type mapping for numeric types"""
        connector = PostgresSourceConnector()

        assert connector._map_postgres_type("INTEGER") == DataType.INTEGER
        assert connector._map_postgres_type("BIGINT") == DataType.BIGINT
        assert connector._map_postgres_type("SMALLINT") == DataType.SMALLINT
        assert connector._map_postgres_type("NUMERIC") == DataType.DECIMAL
        assert connector._map_postgres_type("REAL") == DataType.FLOAT
        assert connector._map_postgres_type("DOUBLE PRECISION") == DataType.DOUBLE

    def test_map_postgres_type_datetime(self):
        """Test PostgreSQL type mapping for datetime types"""
        connector = PostgresSourceConnector()

        assert connector._map_postgres_type("DATE") == DataType.DATE
        assert connector._map_postgres_type("TIME") == DataType.TIME
        assert connector._map_postgres_type("TIMESTAMP") == DataType.TIMESTAMP

    def test_map_postgres_type_boolean(self):
        """Test PostgreSQL type mapping for boolean types"""
        connector = PostgresSourceConnector()

        assert connector._map_postgres_type("BOOLEAN") == DataType.BOOLEAN

    def test_map_postgres_type_json(self):
        """Test PostgreSQL type mapping for JSON types"""
        connector = PostgresSourceConnector()

        assert connector._map_postgres_type("JSON") == DataType.JSON
        assert connector._map_postgres_type("JSONB") == DataType.JSON

    def test_map_postgres_type_uuid(self):
        """Test PostgreSQL type mapping for UUID type"""
        connector = PostgresSourceConnector()

        assert connector._map_postgres_type("UUID") == DataType.UUID

    def test_map_postgres_type_unknown(self):
        """Test PostgreSQL type mapping for unknown types"""
        connector = PostgresSourceConnector()

        assert connector._map_postgres_type("CUSTOM_TYPE") == DataType.UNKNOWN


class TestSnowflakeSourceConnector:
    """Tests for Snowflake source connector"""

    def test_initialization(self):
        """Test Snowflake connector initialization"""
        connector = SnowflakeSourceConnector()
        assert connector._connected is False
        assert connector._engine is None
        assert connector._retry_attempts == 3

    def test_connection_config(self):
        """Test Snowflake connection configuration"""
        config = SnowflakeConnection(
            account="testaccount",
            username="testuser",
            password="testpass",
            database="testdb",
            warehouse="testwh",
            role="testrole",
        )
        conn_str = config.get_connection_string()
        assert "snowflake://" in conn_str
        assert "testaccount" in conn_str
        assert "testdb" in conn_str
        assert "testwh" in conn_str
        assert "role=testrole" in conn_str

    @patch("local_ingestion.core.connectors.snowflake.create_engine")
    def test_connect_success(self, mock_create_engine):
        """Test successful Snowflake connection"""
        mock_engine = MagicMock()
        mock_create_engine.return_value = mock_engine

        connector = SnowflakeSourceConnector()
        config = SnowflakeConnection(
            account="testaccount",
            username="testuser",
            password="testpass",
            database="testdb",
            warehouse="testwh",
        )

        connector.connect(config)

        assert connector.is_connected() is True
        mock_create_engine.assert_called_once()

    def test_disconnect(self):
        """Test Snowflake disconnection"""
        connector = SnowflakeSourceConnector()
        connector._connected = True
        mock_engine = MagicMock()
        connector._engine = mock_engine

        connector.disconnect()

        assert connector.is_connected() is False
        mock_engine.dispose.assert_called_once()
        assert connector._engine is None

    def test_map_snowflake_type_strings(self):
        """Test Snowflake type mapping for string types"""
        connector = SnowflakeSourceConnector()

        assert connector._map_snowflake_type("VARCHAR") == DataType.STRING
        assert connector._map_snowflake_type("CHAR") == DataType.STRING
        assert connector._map_snowflake_type("TEXT") == DataType.TEXT
        assert connector._map_snowflake_type("STRING") == DataType.STRING

    def test_map_snowflake_type_numeric(self):
        """Test Snowflake type mapping for numeric types"""
        connector = SnowflakeSourceConnector()

        assert connector._map_snowflake_type("NUMBER") == DataType.DECIMAL
        assert connector._map_snowflake_type("INT") == DataType.INTEGER
        assert connector._map_snowflake_type("INTEGER") == DataType.INTEGER
        assert connector._map_snowflake_type("BIGINT") == DataType.BIGINT
        assert connector._map_snowflake_type("FLOAT") == DataType.FLOAT
        assert connector._map_snowflake_type("DOUBLE") == DataType.DOUBLE

    def test_map_snowflake_type_datetime(self):
        """Test Snowflake type mapping for datetime types"""
        connector = SnowflakeSourceConnector()

        assert connector._map_snowflake_type("DATE") == DataType.DATE
        assert connector._map_snowflake_type("TIME") == DataType.TIME
        assert connector._map_snowflake_type("DATETIME") == DataType.TIMESTAMP
        assert connector._map_snowflake_type("TIMESTAMP") == DataType.TIMESTAMP

    def test_map_snowflake_type_boolean(self):
        """Test Snowflake type mapping for boolean types"""
        connector = SnowflakeSourceConnector()

        assert connector._map_snowflake_type("BOOLEAN") == DataType.BOOLEAN

    def test_map_snowflake_type_json(self):
        """Test Snowflake type mapping for JSON types"""
        connector = SnowflakeSourceConnector()

        assert connector._map_snowflake_type("VARIANT") == DataType.JSON
        assert connector._map_snowflake_type("JSON") == DataType.JSON
        assert connector._map_snowflake_type("OBJECT") == DataType.JSON

    def test_map_snowflake_type_array(self):
        """Test Snowflake type mapping for array types"""
        connector = SnowflakeSourceConnector()

        assert connector._map_snowflake_type("ARRAY") == DataType.ARRAY
        assert connector._map_snowflake_type("MAP") == DataType.MAP

    def test_map_snowflake_type_unknown(self):
        """Test Snowflake type mapping for unknown types"""
        connector = SnowflakeSourceConnector()

        assert connector._map_snowflake_type("CUSTOM_TYPE") == DataType.UNKNOWN


class TestJSONFileSink:
    """Tests for JSON file sink connector"""

    def test_initialization(self):
        """Test JSON sink initialization"""
        sink = JSONFileSink()
        assert sink.is_connected() is False
        assert sink._buffer == []
        assert sink._is_array_open is False

    def test_config_creation(self):
        """Test FileSinkConfig creation"""
        config = FileSinkConfig(
            outputPath="/tmp/test.json",
            format="json",
        )
        assert config.outputPath == "/tmp/test.json"
        assert config.format == "json"

    def test_config_format_enum(self):
        """Test FileFormat enum values"""
        assert FileFormat.JSON.value == "json"
        assert FileFormat.NDJSON.value == "ndjson"
        assert FileFormat.PARQUET.value == "parquet"

    def test_connect_and_disconnect(self):
        """Test JSON sink connect and disconnect"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = JSONFileSink()
            config = FileSinkConfig(
                outputPath=f"{tmpdir}/test.json",
                format="json",
            )

            sink.connect(config)
            assert sink.is_connected() is True

            sink.close()
            assert sink.is_connected() is False

    def test_write_database(self):
        """Test writing database to JSON sink"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = JSONFileSink()
            config = FileSinkConfig(
                outputPath=f"{tmpdir}/test.json",
                format="json",
            )

            sink.connect(config)
            database = Database(
                name="testdb",
                fullyQualifiedName="testdb",
                description="Test database",
            )
            sink.write_database(database)
            sink.close()

            with open(f"{tmpdir}/test.json", "r") as f:
                content = f.read()
                assert "testdb" in content

    def test_write_multiple_entities(self):
        """Test writing multiple entities to JSON sink"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = JSONFileSink()
            config = FileSinkConfig(
                outputPath=f"{tmpdir}/test.json",
                format="json",
            )

            sink.connect(config)
            database = Database(name="testdb", fullyQualifiedName="testdb")
            sink.write_database(database)
            sink.write_database(Database(name="testdb2", fullyQualifiedName="testdb2"))
            sink.close()

            with open(f"{tmpdir}/test.json", "r") as f:
                content = f.read()
                # Count occurrences of the specific database names
                assert '"name": "testdb"' in content
                assert '"name": "testdb2"' in content

    def test_flush(self):
        """Test flushing JSON sink"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = JSONFileSink()
            config = FileSinkConfig(
                outputPath=f"{tmpdir}/test.json",
                format="json",
            )

            sink.connect(config)
            sink.flush()
            sink.close()


class TestNDJSONFileSink:
    """Tests for NDJSON file sink connector"""

    def test_initialization(self):
        """Test NDJSON sink initialization"""
        sink = NDJSONFileSink()
        assert sink.is_connected() is False

    def test_connect_and_disconnect(self):
        """Test NDJSON sink connect and disconnect"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = NDJSONFileSink()
            config = FileSinkConfig(
                outputPath=f"{tmpdir}/test.ndjson",
                format="ndjson",
            )

            sink.connect(config)
            assert sink.is_connected() is True

            sink.close()
            assert sink.is_connected() is False

    def test_write_database(self):
        """Test writing database to NDJSON sink"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = NDJSONFileSink()
            config = FileSinkConfig(
                outputPath=f"{tmpdir}/test.ndjson",
                format="ndjson",
            )

            sink.connect(config)
            database = Database(
                name="testdb",
                fullyQualifiedName="testdb",
                description="Test database",
            )
            sink.write_database(database)
            sink.close()

            with open(f"{tmpdir}/test.ndjson", "r") as f:
                lines = f.readlines()
                assert len(lines) == 1
                data = json.loads(lines[0])
                assert data["name"] == "testdb"

    def test_write_multiple_entities(self):
        """Test writing multiple entities to NDJSON sink"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = NDJSONFileSink()
            config = FileSinkConfig(
                outputPath=f"{tmpdir}/test.ndjson",
                format="ndjson",
            )

            sink.connect(config)
            sink.write_database(Database(name="db1", fullyQualifiedName="db1"))
            sink.write_database(Database(name="db2", fullyQualifiedName="db2"))
            sink.write_database(Database(name="db3", fullyQualifiedName="db3"))
            sink.close()

            with open(f"{tmpdir}/test.ndjson", "r") as f:
                lines = f.readlines()
                assert len(lines) == 3

    def test_newline_separated_format(self):
        """Test that NDJSON uses newline-separated format"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = NDJSONFileSink()
            config = FileSinkConfig(
                outputPath=f"{tmpdir}/test.ndjson",
                format="ndjson",
            )

            sink.connect(config)
            sink.write_database(Database(name="db1", fullyQualifiedName="db1"))
            sink.write_database(Database(name="db2", fullyQualifiedName="db2"))
            sink.close()

            with open(f"{tmpdir}/test.ndjson", "rb") as f:
                content = f.read()
                assert content.endswith(b"\n")


class TestParquetFileSink:
    """Tests for Parquet file sink connector"""

    def test_initialization(self):
        """Test Parquet sink initialization"""
        sink = ParquetFileSink()
        assert sink.is_connected() is False
        assert sink._buffer == []

    def test_connect(self):
        """Test Parquet sink connect"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = ParquetFileSink()
            config = FileSinkConfig(
                outputPath=f"{tmpdir}/test.parquet",
                format="parquet",
            )

            sink.connect(config)
            assert sink.is_connected() is True
            sink.close()

    def test_disconnect(self):
        """Test Parquet sink disconnect"""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = ParquetFileSink()
            config = FileSinkConfig(
                outputPath=f"{tmpdir}/test.parquet",
                format="parquet",
            )

            sink.connect(config)
            sink.close()
            assert sink.is_connected() is False


class TestFileSinkConfig:
    """Tests for FileSinkConfig"""

    def test_default_values(self):
        """Test default config values"""
        config = FileSinkConfig(outputPath="/tmp/test.json")
        assert config.format == "json"

    def test_ndjson_format(self):
        """Test NDJSON format configuration"""
        config = FileSinkConfig(outputPath="/tmp/test.ndjson", format="ndjson")
        assert config.format == "ndjson"

    def test_parquet_format(self):
        """Test Parquet format configuration"""
        config = FileSinkConfig(outputPath="/tmp/test.parquet", format="parquet")
        assert config.format == "parquet"


class TestSchemaModels:
    """Tests for schema models used by connectors"""

    def test_database_model(self):
        """Test Database model creation"""
        db = Database(
            name="testdb",
            fullyQualifiedName="testdb",
            description="Test database",
        )
        assert db.name == "testdb"
        assert db.fullyQualifiedName == "testdb"
        assert db.description == "Test database"

    def test_database_schema_model(self):
        """Test DatabaseSchema model creation"""
        schema = DatabaseSchema(
            name="public",
            fullyQualifiedName="testdb.public",
            database="testdb",
            description="Public schema",
        )
        assert schema.name == "public"
        assert schema.database == "testdb"

    def test_table_model(self):
        """Test Table model creation"""
        table = Table(
            name="users",
            fullyQualifiedName="testdb.public.users",
            database="testdb",
            databaseSchema="public",
        )
        assert table.name == "users"
        assert table.database == "testdb"
        assert table.databaseSchema == "public"

    def test_column_model(self):
        """Test Column model creation"""
        column = Column(
            name="id",
            dataType=DataType.INTEGER,
            dataTypeDisplay="INTEGER",
            nullable=False,
            ordinalPosition=1,
        )
        assert column.name == "id"
        assert column.dataType == DataType.INTEGER
        assert column.nullable is False
        assert column.ordinalPosition == 1

    def test_column_model_dump(self):
        """Test Column model serialization"""
        column = Column(
            name="id",
            dataType=DataType.INTEGER,
            dataTypeDisplay="INTEGER",
            nullable=False,
            ordinalPosition=1,
        )
        data = column.model_dump()
        assert data["name"] == "id"
        assert data["dataType"] == "INTEGER"
        assert data["nullable"] is False
