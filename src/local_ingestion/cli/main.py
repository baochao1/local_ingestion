"""Local Ingestion CLI - Main entry point"""
from __future__ import annotations

import logging
import sys
from argparse import ArgumentParser
from typing import List, Optional

from local_ingestion.cli.base import CLIContext, CommandGroup
from local_ingestion.cli.parser import build_parser, create_context
from local_ingestion.cli.commands.workflow import WorkflowCommandGroup
from local_ingestion.cli.commands.serve import ServeCommandGroup
from local_ingestion.cli.commands.scan import ScanMySQLCommand, ScanPostgresCommand

__version__ = "0.1.0"
__all__ = ["main", "version", "serve"]

version = __version__

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Configure logging for the CLI"""
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class LocalIngestionCLI:
    """Main CLI application"""

    def __init__(self, context: Optional[CLIContext] = None):
        self.context = context or CLIContext()
        self._command_groups: dict[str, any] = {}
        self._register_commands()

    def _register_commands(self) -> None:
        """Register all command groups"""
        self._command_groups["workflow"] = WorkflowCommandGroup(self.context)
        self._command_groups["serve"] = ServeCommandGroup(self.context)
        self._scan_commands = {
            "mysql": ScanMySQLCommand(self.context),
            "postgres": ScanPostgresCommand(self.context),
        }

    def get_command_group(self, name: str) -> Optional[any]:
        """Get a command group by name"""
        return self._command_groups.get(name)

    def list_command_groups(self) -> List[str]:
        """List all available command groups"""
        return list(self._command_groups.keys())

    def execute(self, args: Optional[List[str]] = None) -> int:
        """Execute the CLI with the given arguments"""
        if args is None:
            args = sys.argv[1:]

        if not args:
            return self._print_help()

        command = args[0]

        if command in ("-h", "--help"):
            return self._print_help()

        if command == "workflow":
            workflow_group = self.get_command_group("workflow")
            if workflow_group:
                return workflow_group.execute(args[1:])
            self._print_error(f"Unknown command: {command}")
            return 1

        if command == "serve":
            serve_group = self.get_command_group("serve")
            if serve_group:
                return serve_group.execute(args[1:])
            self._print_error(f"Unknown command: {command}")
            return 1

        if command == "scan":
            if len(args) < 2:
                self._print_error("Usage: scan <mysql|postgres> [options]")
                return 1
            scan_type = args[1]
            scan_cmd = self._scan_commands.get(scan_type)
            if scan_cmd:
                return scan_cmd.execute(args[2:])
            self._print_error(f"Unknown scan type: {scan_type}")
            return 1

        self._print_error(f"Unknown command: {command}")
        return self._print_help()

    def _print_help(self) -> int:
        """Print CLI help"""
        help_text = f"""Local Ingestion CLI v{version}

Usage: local-ingestion <command> [options]

Commands:
  workflow    Manage workflows (create, list, get, run, delete, logs)
  serve       Start the local ingestion server
  scan        Scan database and extract metadata

Scan Subcommands:
  mysql       Scan MySQL database
  postgres    Scan PostgreSQL database

Global Options:
  -v, --verbose    Enable verbose output
  -q, --quiet      Suppress non-error output
  -f, --format     Output format (json, table, yaml) [default: table]
  --version        Show version information
  -h, --help       Show this help message

Examples:
  local-ingestion scan mysql --host 186.64.10.29 --port 3306 --username root --password rootpassword --database mysql --schema mysql
  local-ingestion scan postgres --host localhost --port 5432 --username postgres --password xxx --database mydb
  local-ingestion serve --port 8080
"""
        print(help_text)
        return 0

    def _print_error(self, message: str) -> None:
        """Print error message"""
        print(f"Error: {message}", file=sys.stderr)


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for the CLI"""
    if args is None:
        args = sys.argv[1:]

    # Handle scan commands directly
    if args and args[0] == "scan" and len(args) > 1:
        from local_ingestion.cli.commands.scan import ScanMySQLCommand, ScanPostgresCommand
        context = CLIContext()
        scan_type = args[1]
        scan_cmd = {"mysql": ScanMySQLCommand(context), "postgres": ScanPostgresCommand(context)}.get(scan_type)
        if scan_cmd:
            return scan_cmd.execute(args[2:])
        print(f"Unknown scan type: {scan_type}", file=sys.stderr)
        print("Usage: scan <mysql|postgres> [options]", file=sys.stderr)
        return 1

    # Parse global args first
    parser = build_parser(prog="local-ingestion", description="Local Ingestion CLI", version=version)
    
    # Add subparsers for commands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Scan subcommand
    scan_parser = subparsers.add_parser("scan", help="Scan database")
    scan_subparsers = scan_parser.add_subparsers(dest="db_type", help="Database type")
    
    mysql_parser = scan_subparsers.add_parser("mysql", help="Scan MySQL database")
    mysql_parser.add_argument("--host", required=True)
    mysql_parser.add_argument("--port", type=int, default=3306)
    mysql_parser.add_argument("--username", required=True)
    mysql_parser.add_argument("--password", required=True)
    mysql_parser.add_argument("--database", default="mysql")
    mysql_parser.add_argument("--schema", default="information_schema")
    mysql_parser.add_argument("--include-columns", action="store_true")
    mysql_parser.add_argument("--output")
    
    postgres_parser = scan_subparsers.add_parser("postgres", help="Scan PostgreSQL database")
    postgres_parser.add_argument("--host", required=True)
    postgres_parser.add_argument("--port", type=int, default=5432)
    postgres_parser.add_argument("--username", required=True)
    postgres_parser.add_argument("--password", required=True)
    postgres_parser.add_argument("--database", required=True)
    postgres_parser.add_argument("--schema", default="public")
    postgres_parser.add_argument("--include-columns", action="store_true")
    postgres_parser.add_argument("--output")
    
    # Workflow subcommand
    workflow_parser = subparsers.add_parser("workflow", help="Manage workflows")
    workflow_subparsers = workflow_parser.add_subparsers(dest="action")
    workflow_subparsers.add_parser("list", help="List workflows")
    workflow_subparsers.add_parser("status", help="Show workflow status")
    
    # Serve subcommand
    serve_parser = subparsers.add_parser("serve", help="Start API server")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8080)
    serve_parser.add_argument("--workers", type=int, default=1)

    try:
        parsed_args = parser.parse_args(args)
    except SystemExit:
        return 1

    setup_logging(verbose=getattr(parsed_args, "verbose", False), quiet=getattr(parsed_args, "quiet", False))

    # Handle scan command
    if getattr(parsed_args, "command", None) == "scan":
        context = CLIContext(verbose=getattr(parsed_args, "verbose", False), quiet=getattr(parsed_args, "quiet", False))
        db_type = getattr(parsed_args, "db_type", None)
        
        if db_type == "mysql":
            cmd = ScanMySQLCommand(context)
            scan_args = []
            for attr in ["host", "port", "username", "password", "database", "schema"]:
                val = getattr(parsed_args, attr, None)
                if val:
                    scan_args.extend([f"--{attr}", str(val)])
            if getattr(parsed_args, "include_columns", False):
                scan_args.append("--include-columns")
            if getattr(parsed_args, "output", None):
                scan_args.extend(["--output", parsed_args.output])
            return cmd.execute(scan_args)
        elif db_type == "postgres":
            cmd = ScanPostgresCommand(context)
            scan_args = []
            for attr in ["host", "port", "username", "password", "database", "schema"]:
                val = getattr(parsed_args, attr, None)
                if val:
                    scan_args.extend([f"--{attr}", str(val)])
            if getattr(parsed_args, "include_columns", False):
                scan_args.append("--include-columns")
            if getattr(parsed_args, "output", None):
                scan_args.extend(["--output", parsed_args.output])
            return cmd.execute(scan_args)
        else:
            scan_parser.print_help()
            return 1
    
    # Handle serve command
    if getattr(parsed_args, "command", None) == "serve":
        return serve(parsed_args)
    
    # Default help
    parser.print_help()
    return 0


def serve(args: Optional[List[str]] = None) -> int:
    """Standalone server entry point for local-serve script"""
    import uvicorn
    
    if args is None:
        args = sys.argv[1:]  # Get all arguments after script name
    
    parser = ArgumentParser(prog="local-serve")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument("--workers", type=int, default=1, help="Number of workers")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    
    parsed_args = parser.parse_args(args)
    
    config = uvicorn.Config(
        "local_ingestion.api.app:app",
        host=parsed_args.host,
        port=parsed_args.port,
        workers=parsed_args.workers,
        reload=parsed_args.reload,
        log_level="info",
    )
    server = uvicorn.Server(config)
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
