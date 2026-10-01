"""Ingestion commands for the CLI"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

from local_ingestion.cli.commands.base import BaseCommand, load_config_file
from local_ingestion.schema.data.table import Table, Column
from local_ingestion.schema.data.database import Database

logger = logging.getLogger(__name__)


class IngestTableCommand(BaseCommand):
    """Ingest table metadata command"""

    name = "ingest table"
    help = "Ingest metadata for a specific table"

    def __init__(self, metadata_service=None):
        super().__init__()
        self._metadata_service = metadata_service

    def _add_arguments(self) -> None:
        self.parser.add_argument("--database", required=True, help="Database name")
        self.parser.add_argument("--table", required=True, help="Table name")
        self.parser.add_argument(
            "--columns",
            action="store_true",
            help="Include column metadata",
        )
        self.parser.add_argument(
            "--config",
            help="Path to table configuration file (JSON)",
        )
        self.parser.add_argument(
            "--schema",
            default="default",
            help="Schema name (default: default)",
        )

    def _build_table(
        self,
        args: argparse.Namespace,
        service=None,
    ) -> Table:
        """Build table object from arguments"""
        database = args.database
        schema = args.schema
        table_name = args.table

        fully_qualified_name = f"{database}.{schema}.{table_name}"

        columns = []
        if args.columns and args.config:
            try:
                config = load_config_file(args.config)
                columns_config = config.get("columns", [])
                for col in columns_config:
                    columns.append(Column(**col))
            except Exception as e:
                logger.warning(f"Could not load column config: {e}")

        return Table(
            name=table_name,
            fullyQualifiedName=fully_qualified_name,
            database=database,
            databaseSchema=schema,
            columns=columns,
        )

    def execute(self, args: argparse.Namespace) -> int:
        """Execute the table ingestion command"""
        try:
            from local_ingestion.api.service import MetadataService

            service = self._metadata_service
            if service is None:
                db = InMemoryDatabase()
                service = MetadataService(db)

            table = self._build_table(args, service)
            table_id = service.ingest_table(table)

            self.print_success(f"Table '{table.fullyQualifiedName}' ingested successfully")
            print(f"Table ID: {table_id}")
            return 0
        except Exception as e:
            self.print_error(str(e))
            return 1


class IngestDatabaseCommand(BaseCommand):
    """Ingest database metadata command"""

    name = "ingest database"
    help = "Ingest metadata for a database and optionally its schemas"

    def __init__(self, metadata_service=None):
        super().__init__()
        self._metadata_service = metadata_service

    def _add_arguments(self) -> None:
        self.parser.add_argument("--database", required=True, help="Database name")
        self.parser.add_argument(
            "--include-schemas",
            action="store_true",
            help="Include schema metadata",
        )
        self.parser.add_argument(
            "--config",
            help="Path to database configuration file (JSON/YAML)",
        )
        self.parser.add_argument(
            "--service-name",
            default="default",
            help="OpenMetadata service name (default: default)",
        )

    def _build_database(self, args: argparse.Namespace) -> Database:
        """Build database object from arguments"""
        database_name = args.database
        fully_qualified_name = f"{args.service_name}.{database_name}"

        description = None
        if args.config:
            try:
                config = load_config_file(args.config)
                description = config.get("description")
            except Exception as e:
                logger.warning(f"Could not load config: {e}")

        return Database(
            name=database_name,
            fullyQualifiedName=fully_qualified_name,
            description=description,
        )

    def execute(self, args: argparse.Namespace) -> int:
        """Execute the database ingestion command"""
        try:
            from local_ingestion.api.service import MetadataService

            service = self._metadata_service
            if service is None:
                db = InMemoryDatabase()
                service = MetadataService(db)

            database = self._build_database(args)
            database_id = service.ingest_database(database)

            self.print_success(f"Database '{database.fullyQualifiedName}' ingested successfully")
            print(f"Database ID: {database_id}")

            if args.include_schemas:
                print("Note: Schema ingestion is not yet implemented")

            return 0
        except Exception as e:
            self.print_error(str(e))
            return 1


class BulkIngestCommand(BaseCommand):
    """Bulk ingestion command for multiple tables/databases"""

    name = "ingest all"
    help = "Bulk ingest metadata from a source configuration"

    def __init__(self, metadata_service=None):
        super().__init__()
        self._metadata_service = metadata_service

    def _add_arguments(self) -> None:
        self.parser.add_argument(
            "--source",
            required=True,
            help="Path to source configuration file (JSON/YAML)",
        )
        self.parser.add_argument(
            "--parallel",
            action="store_true",
            help="Enable parallel ingestion",
        )
        self.parser.add_argument(
            "--workers",
            type=int,
            default=4,
            help="Number of parallel workers (default: 4)",
        )
        self.parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be ingested without actually ingesting",
        )

    def _load_source_config(self, config_path: str) -> Dict[str, Any]:
        """Load source configuration"""
        try:
            config = load_config_file(config_path)
            return config
        except Exception as e:
            raise ValueError(f"Invalid source configuration: {e}")

    def _extract_tables_from_config(self, config: Dict[str, Any]) -> List[Table]:
        """Extract table objects from configuration"""
        tables = []
        tables_config = config.get("tables", [])

        for table_config in tables_config:
            try:
                columns = []
                for col_config in table_config.get("columns", []):
                    columns.append(Column(**col_config))

                table = Table(
                    name=table_config["name"],
                    fullyQualifiedName=table_config["fullyQualifiedName"],
                    database=table_config.get("database"),
                    databaseSchema=table_config.get("databaseSchema"),
                    columns=columns,
                    description=table_config.get("description"),
                )
                tables.append(table)
            except KeyError as e:
                logger.warning(f"Missing required field in table config: {e}")
                continue

        return tables

    def _ingest_table(self, service, table: Table) -> tuple[bool, str]:
        """Ingest a single table and return (success, message)"""
        try:
            table_id = service.ingest_table(table)
            return True, f"Table '{table.name}' ingested: {table_id}"
        except Exception as e:
            return False, f"Table '{table.name}' failed: {str(e)}"

    def execute(self, args: argparse.Namespace) -> int:
        """Execute the bulk ingestion command"""
        try:
            from local_ingestion.api.service import MetadataService

            config = self._load_source_config(args.source)
            service = self._metadata_service
            if service is None:
                db = InMemoryDatabase()
                service = MetadataService(db)

            tables = self._extract_tables_from_config(config)

            if not tables:
                self.print_info("No tables found in configuration")
                return 0

            self.print_info(f"Found {len(tables)} tables to ingest")

            if args.dry_run:
                self.print_info("Dry run - tables that would be ingested:")
                for table in tables:
                    print(f"  - {table.fullyQualifiedName}")
                return 0

            success_count = 0
            failure_count = 0
            results = []

            if args.parallel and TQDM_AVAILABLE:
                with ThreadPoolExecutor(max_workers=args.workers) as executor:
                    futures = {
                        executor.submit(self._ingest_table, service, table): table
                        for table in tables
                    }

                    with tqdm(total=len(tables), desc="Ingesting tables") as pbar:
                        for future in as_completed(futures):
                            success, message = future.result()
                            results.append((success, message))
                            if success:
                                success_count += 1
                            else:
                                failure_count += 1
                            pbar.update(1)
            else:
                iterator = tqdm(tables, desc="Ingesting tables") if TQDM_AVAILABLE else tables
                for table in iterator:
                    success, message = self._ingest_table(service, table)
                    results.append((success, message))
                    if success:
                        success_count += 1
                    else:
                        failure_count += 1

            self.print_info(f"\nBulk ingestion complete:")
            self.print_info(f"  Success: {success_count}")
            self.print_info(f"  Failed: {failure_count}")

            if failure_count > 0:
                self.print_info("\nFailures:")
                for success, message in results:
                    if not success:
                        print(f"  - {message}")

            return 0 if failure_count == 0 else 1

        except Exception as e:
            self.print_error(str(e))
            return 1


class InMemoryDatabase:
    """Simple in-memory database for CLI testing"""

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


def register_ingest_commands(subparsers) -> None:
    """Register all ingest commands to a subparsers object"""
    ingest_parser = subparsers.add_parser("ingest", help="Ingestion commands")
    ingest_subparsers = ingest_parser.add_subparsers(dest="ingest_command", help="Ingest commands")

    table_cmd = IngestTableCommand()
    ingest_subparsers.add_parser(
        "table",
        parents=[table_cmd.parser],
        help="Ingest a single table",
    )

    database_cmd = IngestDatabaseCommand()
    ingest_subparsers.add_parser(
        "database",
        parents=[database_cmd.parser],
        help="Ingest a database",
    )

    bulk_cmd = BulkIngestCommand()
    ingest_subparsers.add_parser(
        "all",
        parents=[bulk_cmd.parser],
        help="Bulk ingest from source config",
    )
