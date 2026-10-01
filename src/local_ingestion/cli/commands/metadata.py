"""Metadata commands for the CLI"""
from __future__ import annotations

import argparse
import json
import logging
from typing import Optional

from local_ingestion.cli.commands.base import BaseCommand
from local_ingestion.schema.data.table import Table
from local_ingestion.schema.data.database import Database

logger = logging.getLogger(__name__)


class ListTablesCommand(BaseCommand):
    """List tables command"""

    name = "metadata tables"
    help = "List tables with optional filtering"

    def __init__(self, metadata_service=None):
        super().__init__()
        self._metadata_service = metadata_service

    def _add_arguments(self) -> None:
        self.parser.add_argument(
            "--database",
            help="Filter by database name",
        )
        self.parser.add_argument(
            "--schema",
            help="Filter by schema name",
        )
        self.parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of results (default: 100)",
        )
        self.parser.add_argument(
            "--format",
            choices=["table", "json", "csv"],
            default="table",
            help="Output format (default: table)",
        )

    def execute(self, args: argparse.Namespace) -> int:
        """Execute the list tables command"""
        try:
            from local_ingestion.api.service import MetadataService

            from local_ingestion.cli.commands.ingest import InMemoryDatabase

            db = InMemoryDatabase() if self._metadata_service is None else self._metadata_service
            if self._metadata_service is None:
                service = MetadataService(db)
            else:
                service = self._metadata_service

            filters = {}
            if args.database:
                filters["database"] = args.database
            if args.schema:
                filters["databaseSchema"] = args.schema

            tables = service.list_tables(filters if filters else None)

            if len(tables) > args.limit:
                tables = tables[: args.limit]

            if args.format == "json":
                self._print_json(tables)
            elif args.format == "csv":
                self._print_csv(tables)
            else:
                self._print_table(tables)

            self.print_info(f"\nTotal: {len(tables)} table(s)")
            return 0
        except Exception as e:
            self.print_error(str(e))
            return 1

    def _print_table(self, tables: list[Table]) -> None:
        """Print tables in table format"""
        if not tables:
            self.print_info("No tables found")
            return

        header = f"{'Name':<30} {'Database':<20} {'Schema':<20} {'Columns':<10}"
        separator = "-" * len(header)

        print(header)
        print(separator)

        for table in tables:
            db_name = table.database or "-"
            schema_name = table.databaseSchema or "-"
            col_count = len(table.columns)
            print(f"{table.name:<30} {db_name:<20} {schema_name:<20} {col_count:<10}")

    def _print_json(self, tables: list[Table]) -> None:
        """Print tables in JSON format"""
        data = [
            {
                "name": t.name,
                "fullyQualifiedName": t.fullyQualifiedName,
                "database": t.database,
                "databaseSchema": t.databaseSchema,
                "columnCount": len(t.columns),
                "description": t.description,
            }
            for t in tables
        ]
        print(json.dumps(data, indent=2))

    def _print_csv(self, tables: list[Table]) -> None:
        """Print tables in CSV format"""
        print("Name,Database,Schema,FullyQualifiedName,ColumnCount,Description")
        for table in tables:
            desc = (table.description or "").replace(",", ";")
            print(
                f"{table.name},{table.database or ''},{table.databaseSchema or ''},"
                f"{table.fullyQualifiedName},{len(table.columns)},{desc}"
            )


class GetTableCommand(BaseCommand):
    """Get table details command"""

    name = "metadata table"
    help = "Get details for a specific table"

    def __init__(self, metadata_service=None):
        super().__init__()
        self._metadata_service = metadata_service

    def _add_arguments(self) -> None:
        self.parser.add_argument(
            "qualified-name",
            help="Fully qualified table name (e.g., database.schema.table)",
        )
        self.parser.add_argument(
            "--format",
            choices=["table", "json", "detailed"],
            default="detailed",
            help="Output format (default: detailed)",
        )

    def execute(self, args: argparse.Namespace) -> int:
        """Execute the get table command"""
        try:
            from local_ingestion.api.service import MetadataService

            from local_ingestion.cli.commands.ingest import InMemoryDatabase

            qualified_name = args.qualified_name

            if self._metadata_service is None:
                db = InMemoryDatabase()
                service = MetadataService(db)
            else:
                service = self._metadata_service

            table = service.get_table(qualified_name)

            if args.format == "json":
                print(table.model_dump_json(indent=2))
            elif args.format == "table":
                self._print_table_summary(table)
            else:
                self._print_detailed(table)

            return 0
        except Exception as e:
            self.print_error(str(e))
            return 1

    def _print_table_summary(self, table: Table) -> None:
        """Print table summary"""
        print(f"Name: {table.name}")
        print(f"Database: {table.database or '-'}")
        print(f"Schema: {table.databaseSchema or '-'}")
        print(f"Columns: {len(table.columns)}")

    def _print_detailed(self, table: Table) -> None:
        """Print detailed table information"""
        print(f"Table: {table.name}")
        print(f"Fully Qualified Name: {table.fullyQualifiedName}")
        print(f"Database: {table.database or '-'}")
        print(f"Schema: {table.databaseSchema or '-'}")
        print(f"Type: {table.tableType or 'TABLE'}")
        print(f"Description: {table.description or '(No description)'}")

        if table.columns:
            print("\nColumns:")
            print("-" * 60)
            for col in table.columns:
                nullable = "NULL" if col.nullable else "NOT NULL"
                dtype = col.dataType.value if hasattr(col.dataType, "value") else col.dataType
                print(f"  {col.name:<30} {dtype:<15} {nullable}")
        else:
            print("\nNo columns defined")


class ListDatabasesCommand(BaseCommand):
    """List databases command"""

    name = "metadata databases"
    help = "List all databases"

    def __init__(self, metadata_service=None):
        super().__init__()
        self._metadata_service = metadata_service

    def _add_arguments(self) -> None:
        self.parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of results (default: 100)",
        )
        self.parser.add_argument(
            "--format",
            choices=["table", "json", "csv"],
            default="table",
            help="Output format (default: table)",
        )

    def execute(self, args: argparse.Namespace) -> int:
        """Execute the list databases command"""
        try:
            from local_ingestion.api.service import MetadataService

            from local_ingestion.cli.commands.ingest import InMemoryDatabase

            if self._metadata_service is None:
                db = InMemoryDatabase()
                service = MetadataService(db)
            else:
                service = self._metadata_service

            databases = service.list_databases()

            if len(databases) > args.limit:
                databases = databases[: args.limit]

            if args.format == "json":
                self._print_json(databases)
            elif args.format == "csv":
                self._print_csv(databases)
            else:
                self._print_table(databases)

            self.print_info(f"\nTotal: {len(databases)} database(s)")
            return 0
        except Exception as e:
            self.print_error(str(e))
            return 1

    def _print_table(self, databases: list[Database]) -> None:
        """Print databases in table format"""
        if not databases:
            self.print_info("No databases found")
            return

        header = f"{'Name':<30} {'Fully Qualified Name':<40} {'Description':<30}"
        separator = "-" * len(header)

        print(header)
        print(separator)

        for db in databases:
            desc = (db.description or "-")[:30]
            print(f"{db.name:<30} {db.fullyQualifiedName:<40} {desc:<30}")

    def _print_json(self, databases: list[Database]) -> None:
        """Print databases in JSON format"""
        data = [
            {
                "name": d.name,
                "fullyQualifiedName": d.fullyQualifiedName,
                "description": d.description,
            }
            for d in databases
        ]
        print(json.dumps(data, indent=2))

    def _print_csv(self, databases: list[Database]) -> None:
        """Print databases in CSV format"""
        print("Name,FullyQualifiedName,Description")
        for db in databases:
            desc = (db.description or "").replace(",", ";")
            print(f"{db.name},{db.fullyQualifiedName},{desc}")


class GetDatabaseCommand(BaseCommand):
    """Get database details command"""

    name = "metadata database"
    help = "Get details for a specific database"

    def __init__(self, metadata_service=None):
        super().__init__()
        self._metadata_service = metadata_service

    def _add_arguments(self) -> None:
        self.parser.add_argument(
            "qualified-name",
            help="Fully qualified database name (e.g., service.database)",
        )
        self.parser.add_argument(
            "--format",
            choices=["table", "json"],
            default="detailed",
            help="Output format (default: detailed)",
        )

    def execute(self, args: argparse.Namespace) -> int:
        """Execute the get database command"""
        try:
            from local_ingestion.api.service import MetadataService

            from local_ingestion.cli.commands.ingest import InMemoryDatabase

            qualified_name = args.qualified_name

            if self._metadata_service is None:
                db = InMemoryDatabase()
                service = MetadataService(db)
            else:
                service = self._metadata_service

            database = service.get_database(qualified_name)

            if args.format == "json":
                print(database.model_dump_json(indent=2))
            else:
                self._print_detailed(database)

            return 0
        except Exception as e:
            self.print_error(str(e))
            return 1

    def _print_detailed(self, database: Database) -> None:
        """Print detailed database information"""
        print(f"Database: {database.name}")
        print(f"Fully Qualified Name: {database.fullyQualifiedName}")
        print(f"Description: {database.description or '(No description)'}")

        if database.owner:
            print(f"Owner: {database.owner.name} ({database.owner.type})")

        if database.tags:
            print(f"Tags: {', '.join(database.tags)}")


def register_metadata_commands(subparsers) -> None:
    """Register all metadata commands to a subparsers object"""
    metadata_parser = subparsers.add_parser("metadata", help="Metadata commands")
    metadata_subparsers = metadata_parser.add_subparsers(
        dest="metadata_command", help="Metadata operations"
    )

    list_tables_cmd = ListTablesCommand()
    metadata_subparsers.add_parser(
        "tables",
        parents=[list_tables_cmd.parser],
        help="List tables",
    )

    get_table_cmd = GetTableCommand()
    metadata_subparsers.add_parser(
        "table",
        parents=[get_table_cmd.parser],
        help="Get table details",
    )

    list_dbs_cmd = ListDatabasesCommand()
    metadata_subparsers.add_parser(
        "databases",
        parents=[list_dbs_cmd.parser],
        help="List databases",
    )

    get_db_cmd = GetDatabaseCommand()
    metadata_subparsers.add_parser(
        "database",
        parents=[get_db_cmd.parser],
        help="Get database details",
    )
