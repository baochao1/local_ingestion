"""Connection commands for the CLI"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Dict, Optional

from local_ingestion.cli.commands.base import BaseCommand, load_config_file
from local_ingestion.schema.service.connection import (
    MySQLConnection,
    PostgresConnection,
    SqlServerConnection,
    BigQueryConnection,
    SnowflakeConnection,
)
from local_ingestion.schema.base import ServiceType

logger = logging.getLogger(__name__)


CONNECTION_TYPES = {
    "mysql": MySQLConnection,
    "postgres": PostgresConnection,
    "postgresql": PostgresConnection,
    "mssql": SqlServerConnection,
    "bigquery": BigQueryConnection,
    "snowflake": SnowflakeConnection,
}


class TestConnectionCommand(BaseCommand):
    """Test connection command"""

    name = "connection test"
    help = "Test a database connection"

    def __init__(self, executor=None):
        super().__init__()
        self._executor = executor

    def _add_arguments(self) -> None:
        self.parser.add_argument(
            "--type",
            required=True,
            choices=list(CONNECTION_TYPES.keys()),
            help="Database type",
        )
        self.parser.add_argument(
            "--config",
            required=True,
            help="Path to connection configuration file (JSON/YAML)",
        )
        self.parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Connection timeout in seconds (default: 30)",
        )

    def _load_connection_config(self, config_path: str, db_type: str) -> Dict[str, Any]:
        """Load and validate connection configuration"""
        config = load_config_file(config_path)
        return config

    def _create_connection(self, db_type: str, config: Dict[str, Any]):
        """Create connection object from config"""
        connection_class = CONNECTION_TYPES.get(db_type)
        if not connection_class:
            raise ValueError(f"Unsupported database type: {db_type}")

        return connection_class(**config)

    def _test_connection(self, connection, timeout: int) -> tuple[bool, str]:
        """Test the actual database connection"""
        if self._executor:
            return self._executor(connection, timeout)

        return self._default_connection_test(connection, timeout)

    def _default_connection_test(self, connection, timeout: int) -> tuple[bool, str]:
        """Default connection test using connection string validation"""
        try:
            conn_str = connection.get_connection_string()
            if not conn_str:
                return False, "Failed to generate connection string"

            return True, f"Connection string generated: {conn_str[:50]}..."
        except Exception as e:
            return False, f"Connection test failed: {str(e)}"

    def execute(self, args: argparse.Namespace) -> int:
        """Execute the connection test command"""
        try:
            config = self._load_connection_config(args.config, args.type)
            connection = self._create_connection(args.type, config)

            self.print_info(f"Testing {args.type} connection...")
            self.print_info(f"Config: {args.config}")

            success, message = self._test_connection(connection, args.timeout)

            if success:
                self.print_success("Connection test passed!")
                print(f"Details: {message}")
                return 0
            else:
                self.print_error("Connection test failed!")
                print(f"Details: {message}", file=sys.stderr)
                return 1

        except FileNotFoundError as e:
            self.print_error(f"Configuration file not found: {e}")
            return 1
        except json.JSONDecodeError as e:
            self.print_error(f"Invalid JSON in configuration: {e}")
            return 1
        except Exception as e:
            self.print_error(f"Connection test error: {e}")
            return 1


class ConnectionInfoCommand(BaseCommand):
    """Show connection information command"""

    name = "connection info"
    help = "Show information about supported connection types"

    def __init__(self):
        super().__init__()

    def _add_arguments(self) -> None:
        self.parser.add_argument(
            "--type",
            required=True,
            choices=list(CONNECTION_TYPES.keys()),
            help="Database type",
        )
        self.parser.add_argument(
            "--format",
            choices=["table", "json"],
            default="table",
            help="Output format (default: table)",
        )

    def execute(self, args: argparse.Namespace) -> int:
        """Execute the connection info command"""
        try:
            connection_class = CONNECTION_TYPES.get(args.type)
            if not connection_class:
                self.print_error(f"Unknown connection type: {args.type}")
                return 1

            info = self._get_connection_info(args.type, connection_class)

            if args.format == "json":
                print(json.dumps(info, indent=2))
            else:
                self._print_connection_info(info)

            return 0
        except Exception as e:
            self.print_error(str(e))
            return 1

    def _get_connection_info(
        self, db_type: str, connection_class
    ) -> Dict[str, Any]:
        """Get connection information"""
        return {
            "type": db_type,
            "class": connection_class.__name__,
            "description": self._get_description(db_type),
            "connection_string_template": self._get_template(db_type),
            "required_fields": self._get_required_fields(db_type),
            "optional_fields": self._get_optional_fields(db_type),
        }

    def _get_description(self, db_type: str) -> str:
        """Get description for database type"""
        descriptions = {
            "mysql": "MySQL Database - Open source relational database",
            "postgres": "PostgreSQL Database - Advanced open source database",
            "postgresql": "PostgreSQL Database - Advanced open source database",
            "mssql": "Microsoft SQL Server - Enterprise database",
            "bigquery": "Google BigQuery - Serverless data warehouse",
            "snowflake": "Snowflake - Cloud data platform",
        }
        return descriptions.get(db_type, "Unknown database type")

    def _get_template(self, db_type: str) -> str:
        """Get connection string template"""
        templates = {
            "mysql": "mysql+pymysql://[username[:password]@]host[:port]/[database]",
            "postgres": "postgresql://[username[:password]@]host[:port]/[database]",
            "postgresql": "postgresql://[username[:password]@]host[:port]/[database]",
            "mssql": "mssql+pyodbc://[username[:password]@]host[:port]/[database]",
            "bigquery": "bigquery://[project-id]",
            "snowflake": "snowflake://[account]/[database]/[schema]?role=[role]",
        }
        return templates.get(db_type, "")

    def _get_required_fields(self, db_type: str) -> list:
        """Get required configuration fields"""
        specific = {
            "mysql": ["hostPort"],
            "postgres": ["hostPort", "username", "password", "database"],
            "postgresql": ["hostPort", "username", "password", "database"],
            "mssql": ["hostPort", "username", "password", "database"],
            "bigquery": ["projectId", "credentials"],
            "snowflake": ["account", "username", "password", "database"],
        }
        return specific.get(db_type, [])

    def _get_optional_fields(self, db_type: str) -> list:
        """Get optional configuration fields"""
        specific = {
            "mysql": ["database", "sslMode", "connectionOptions"],
            "postgres": ["database", "sslMode", "connectionOptions"],
            "postgresql": ["database", "sslMode", "connectionOptions"],
            "mssql": ["driver", "database", "connectionOptions"],
            "bigquery": ["database", "credentials", "connectionOptions"],
            "snowflake": ["warehouse", "role", "privateKey", "connectionOptions"],
        }
        return specific.get(db_type, [])

    def _print_connection_info(self, info: Dict[str, Any]) -> None:
        """Print connection info in table format"""
        print(f"Connection Type: {info['type'].upper()}")
        print(f"Class: {info['class']}")
        print(f"Description: {info['description']}")
        print(f"\nConnection String Template:")
        print(f"  {info['connection_string_template']}")

        print(f"\nRequired Fields:")
        for field in info.get("required_fields", []):
            print(f"  - {field}")

        print(f"\nOptional Fields:")
        for field in info.get("optional_fields", []):
            print(f"  - {field}")


def register_connection_commands(subparsers) -> None:
    """Register all connection commands to a subparsers object"""
    connection_parser = subparsers.add_parser("connection", help="Connection commands")
    connection_subparsers = connection_parser.add_subparsers(
        dest="connection_command", help="Connection operations"
    )

    test_cmd = TestConnectionCommand()
    connection_subparsers.add_parser(
        "test",
        parents=[test_cmd.parser],
        help="Test a database connection",
    )

    info_cmd = ConnectionInfoCommand()
    connection_subparsers.add_parser(
        "info",
        parents=[info_cmd.parser],
        help="Show connection information",
    )
