"""Argument parser for CLI"""
from __future__ import annotations

import argparse
import sys
from argparse import ArgumentParser, Namespace
from typing import Any, Dict, List, Optional, Callable

from local_ingestion.cli.base import CLIContext, CommandGroup


class CommandParser:
    """Command group parser"""

    def __init__(self, name: str, help_text: str = ""):
        self.name = name
        self.help_text = help_text
        self._subparsers: Dict[str, Any] = {}
        self._parser: Optional[ArgumentParser] = None

    def add_subparser(
        self,
        name: str,
        help_text: str = "",
    ) -> Any:
        """Add a subparser for a command"""
        if self._parser is None:
            raise RuntimeError("Parser not initialized. Call setup() first.")
        subparser = self._parser.add_subparsers(dest=name, help=help_text)
        return subparser

    def setup(self, parser: ArgumentParser) -> None:
        """Setup the command parser"""
        self._parser = parser


def build_parser(
    prog: str = "local-ingestion",
    description: str = "Local Ingestion CLI",
    version: str = "0.1.0",
) -> ArgumentParser:
    """Build the main argument parser

    Args:
        prog: Program name
        description: Program description
        version: Program version

    Returns:
        Configured ArgumentParser instance
    """
    parser = ArgumentParser(
        prog=prog,
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose output",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress non-error output",
    )

    parser.add_argument(
        "-f",
        "--format",
        choices=["json", "table", "yaml"],
        default="table",
        help="Output format (default: table)",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"{prog} {version}",
    )

    return parser


def parse_args(
    parser: ArgumentParser,
    args: Optional[List[str]] = None,
) -> Namespace:
    """Parse arguments using the given parser

    Args:
        parser: ArgumentParser instance
        args: Arguments to parse (defaults to sys.argv)

    Returns:
        Parsed arguments namespace
    """
    return parser.parse_args(args)


def create_context(args: Namespace) -> CLIContext:
    """Create CLIContext from parsed arguments

    Args:
        args: Parsed arguments namespace

    Returns:
        CLIContext instance
    """
    return CLIContext(
        verbose=getattr(args, "verbose", False),
        quiet=getattr(args, "quiet", False),
        output_format=getattr(args, "format", "table"),
    )


def add_global_options(parser: ArgumentParser) -> None:
    """Add global options to a parser

    Args:
        parser: ArgumentParser to add options to
    """
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable verbose output",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=False,
        help="Suppress non-error output",
    )

    parser.add_argument(
        "-f",
        "--format",
        choices=["json", "table", "yaml"],
        default="table",
        help="Output format (default: table)",
    )
