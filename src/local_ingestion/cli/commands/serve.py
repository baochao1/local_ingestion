"""Server-related CLI commands"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
from argparse import ArgumentParser
from typing import Any, Dict, List, Optional

try:
    import uvicorn
    UVICORN_AVAILABLE = True
except ImportError:
    UVICORN_AVAILABLE = False

from local_ingestion.cli.base import BaseCommand, CLIContext
from local_ingestion.cli.formatter import OutputFormatter

logger = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_WORKERS = 1


class ServeCommand(BaseCommand):
    """Command to start the local ingestion server"""

    name = "serve"
    help = "Start the local ingestion server"

    def __init__(self, context: Optional[CLIContext] = None):
        super().__init__(context)
        self._server_thread: Optional[threading.Thread] = None
        self._server_running = False

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--host",
            default=DEFAULT_HOST,
            help=f"Host to bind to (default: {DEFAULT_HOST})",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=DEFAULT_PORT,
            help=f"Port to bind to (default: {DEFAULT_PORT})",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=DEFAULT_WORKERS,
            help=f"Number of worker processes (default: {DEFAULT_WORKERS})",
        )
        parser.add_argument(
            "--socket",
            help="Unix socket path to bind to (alternative to host:port)",
        )
        parser.add_argument(
            "--reload",
            action="store_true",
            help="Enable auto-reload on file changes (watchdog required)",
        )

    def execute(self, args: List[str]) -> int:
        parser = ArgumentParser(prog="serve")
        self.add_arguments(parser)

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1

        if not UVICORN_AVAILABLE:
            self.print_error("uvicorn is required to run the server")
            self.print_info("Install with: pip install local-ingestion[server]")
            return 1

        try:
            self._validate_args(parsed_args)
        except ValueError as e:
            self.print_error(str(e))
            return 1

        self.print_info(f"Starting server on {parsed_args.host}:{parsed_args.port}")

        try:
            config = uvicorn.Config(
                "local_ingestion.api.app:app",
                host=parsed_args.host,
                port=parsed_args.port,
                workers=parsed_args.workers,
                reload=parsed_args.reload,
                log_level="info" if self.context.is_verbose() else "warning",
            )
            server = uvicorn.Server(config)
            server.run()

            return 0

        except Exception as e:
            self.print_error(f"Failed to start server: {e}")
            if self.context.is_verbose():
                raise
            return 1

    def _validate_args(self, args: Any) -> None:
        """Validate server arguments"""
        if args.workers < 1:
            raise ValueError("Workers must be at least 1")

        if args.port < 1 or args.port > 65535:
            raise ValueError("Port must be between 1 and 65535")

        if args.socket and os.path.exists(args.socket):
            os.remove(args.socket)


class ServeStatusCommand(BaseCommand):
    """Command to check server status"""

    name = "status"
    help = "Check the status of the local ingestion server"

    def __init__(self, context: Optional[CLIContext] = None):
        super().__init__(context)

    def execute(self, args: List[str]) -> int:
        parser = ArgumentParser(prog="serve status")
        parser.add_argument(
            "--host",
            default="localhost",
            help="Server host (default: localhost)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=DEFAULT_PORT,
            help=f"Server port (default: {DEFAULT_PORT})",
        )

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1

        status_data = [
            {
                "component": "Server",
                "status": "unknown",
                "details": "Unable to determine",
            }
        ]

        try:
            import requests
            response = requests.get(
                f"http://{parsed_args.host}:{parsed_args.port}/health",
                timeout=5,
            )
            if response.status_code == 200:
                data = response.json()
                status_data = [
                    {
                        "component": "Server",
                        "status": "running",
                        "details": f"Version {data.get('version', 'unknown')}",
                    }
                ]
        except ImportError:
            status_data = [
                {
                    "component": "Server",
                    "status": "unknown",
                    "details": "requests library not available",
                }
            ]
        except Exception:
            status_data = [
                {
                    "component": "Server",
                    "status": "stopped",
                    "details": "Server not responding",
                }
            ]

        output = OutputFormatter.format(
            status_data,
            format_type=self.context.get_output_format(),
        )
        self.print_info(output)

        return 0


class ServeCommandGroup:
    """Command group for server operations"""

    name = "serve"
    help = "Manage the local ingestion server"

    def __init__(self, context: Optional[CLIContext] = None):
        self.context = context or CLIContext()
        self._commands: Dict[str, BaseCommand] = {
            "serve": ServeCommand(self.context),
            "status": ServeStatusCommand(self.context),
        }

    def get_command(self, name: str) -> Optional[BaseCommand]:
        return self._commands.get(name)

    def list_commands(self) -> List[str]:
        return list(self._commands.keys())

    def execute(self, args: List[str]) -> int:
        if not args:
            return self._commands["serve"].execute([])

        command_name = args[0]
        command = self.get_command(command_name)

        if command is None:
            self.print_error(f"Unknown command: {command_name}")
            print("Commands:", ", ".join(self.list_commands()))
            return 1

        return command.execute(args[1:])
