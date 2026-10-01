"""CLI base components for Local Ingestion"""
from __future__ import annotations

import json
import logging
import sys
from abc import ABC, abstractmethod
from argparse import ArgumentParser, Namespace
from typing import Any, Dict, List, Optional

from local_ingestion.cli.formatter import OutputFormatter

logger = logging.getLogger(__name__)


class CLIContext:
    """Context object holding CLI execution state"""

    def __init__(
        self,
        verbose: bool = False,
        quiet: bool = False,
        output_format: str = "table",
    ):
        self.verbose = verbose
        self.quiet = quiet
        self.output_format = output_format
        self._state: Dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        """Set state value"""
        self._state[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get state value"""
        return self._state.get(key, default)

    def is_verbose(self) -> bool:
        """Check if verbose mode is enabled"""
        return self.verbose

    def is_quiet(self) -> bool:
        """Check if quiet mode is enabled"""
        return self.quiet

    def get_output_format(self) -> str:
        """Get output format"""
        return self.output_format

    def __repr__(self) -> str:
        return (
            f"CLIContext(verbose={self.verbose}, quiet={self.quiet}, "
            f"output_format={self.output_format})"
        )


class BaseCommand(ABC):
    """Abstract base command class"""

    name: str = ""
    help: str = ""

    def __init__(self, context: Optional[CLIContext] = None):
        self._context = context or CLIContext()

    @property
    def context(self) -> CLIContext:
        """Get CLI context"""
        return self._context

    @property
    def command_name(self) -> str:
        """Get command name"""
        return self.name

    @property
    def command_help(self) -> str:
        """Get command help text"""
        return self.help

    @abstractmethod
    def execute(self, args: List[str]) -> int:
        """Execute command, returns exit code"""
        raise NotImplementedError

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Add command-specific arguments"""
        pass

    def print_error(self, message: str) -> None:
        """Print error message to stderr"""
        if not self._context.is_quiet():
            print(f"Error: {message}", file=sys.stderr)

    def print_warning(self, message: str) -> None:
        """Print warning message to stderr"""
        if self._context.is_verbose() and not self._context.is_quiet():
            print(f"Warning: {message}", file=sys.stderr)

    def print_info(self, message: str) -> None:
        """Print info message to stdout"""
        if not self._context.is_quiet():
            print(message)

    def print_success(self, message: str) -> None:
        """Print success message to stdout"""
        if not self._context.is_quiet():
            print(f"[OK] {message}")

    def log_debug(self, message: str) -> None:
        """Log debug message"""
        if self._context.is_verbose():
            logger.debug(message)


class CommandGroup:
    """Command group for organizing related commands"""

    def __init__(self, name: str, help: str = ""):
        self.name = name
        self.help = help
        self._commands: Dict[str, BaseCommand] = {}

    def register(self, command: BaseCommand) -> None:
        """Register a command"""
        self._commands[command.name] = command

    def get_command(self, name: str) -> Optional[BaseCommand]:
        """Get command by name"""
        return self._commands.get(name)

    def list_commands(self) -> List[str]:
        """List all registered command names"""
        return list(self._commands.keys())

    def get_all_commands(self) -> Dict[str, BaseCommand]:
        """Get all registered commands"""
        return self._commands.copy()
