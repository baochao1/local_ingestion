"""Connection model tests"""
import pytest
from local_ingestion.schema.service.connection import (
    MySQLConnection,
    PostgresConnection,
    SqlServerConnection,
    BigQueryConnection,
    SnowflakeConnection,
)
from local_ingestion.schema.base import ServiceType


class TestMySQLConnection:
    def test_connection_creation(self):
        conn = MySQLConnection(hostPort="localhost:3306")
        assert conn.hostPort == "localhost:3306"

    def test_connection_string(self):
        conn = MySQLConnection(
            hostPort="localhost:3306",
            username="root",
            password="secret",
            database="mydb"
        )
        conn_str = conn.get_connection_string()
        assert "mysql+pymysql://" in conn_str
        assert "root:secret" in conn_str
        assert "/mydb" in conn_str


class TestPostgresConnection:
    def test_connection_string(self):
        conn = PostgresConnection(
            hostPort="localhost:5432",
            username="pguser",
            database="pgdb"
        )
        conn_str = conn.get_connection_string()
        assert "postgresql://" in conn_str
        assert "pguser" in conn_str


class TestSnowflakeConnection:
    def test_connection_string(self):
        conn = SnowflakeConnection(
            account="mycompany",
            username="user",
            database="SNOWDB",
            warehouse="COMPUTE_WH"
        )
        conn_str = conn.get_connection_string()
        assert "snowflake://" in conn_str
        assert "mycompany" in conn_str
        assert "SNOWDB" in conn_str
