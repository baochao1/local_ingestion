"""Output formatting utilities for CLI"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

try:
    from rich.console import Console
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


class OutputFormatter:
    """Output formatting utility for different output formats"""

    @staticmethod
    def format_json(data: Any, indent: int = 2) -> str:
        """Format data as JSON string"""
        return json.dumps(data, indent=indent, default=str)

    @staticmethod
    def format_yaml(data: Any) -> str:
        """Format data as YAML string"""
        if not YAML_AVAILABLE:
            raise ImportError(
                "PyYAML is required for YAML output. "
                "Install it with: pip install pyyaml"
            )
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    @staticmethod
    def format_table(
        data: List[Dict[str, Any]],
        columns: Optional[List[str]] = None,
    ) -> str:
        """Format data as ASCII table string"""
        if not data:
            return "No data to display"

        if columns is None:
            if isinstance(data[0], dict):
                columns = list(data[0].keys())
            else:
                return str(data)

        col_widths = {col: len(col) for col in columns}
        for row in data:
            for col in columns:
                value = str(row.get(col, ""))
                col_widths[col] = max(col_widths[col], len(value))

        header = " | ".join(col.ljust(col_widths[col]) for col in columns)
        separator = "-+-".join("-" * col_widths[col] for col in columns)

        lines = [header, separator]

        for row in data:
            line = " | ".join(
                str(row.get(col, "")).ljust(col_widths[col]) for col in columns
            )
            lines.append(line)

        return "\n".join(lines)

    @staticmethod
    def format_table_rich(
        data: List[Dict[str, Any]],
        columns: Optional[List[str]] = None,
    ) -> str:
        """Format data as a rich table (if rich is available)"""
        if not RICH_AVAILABLE:
            return OutputFormatter.format_table(data, columns)

        if not data:
            return "No data to display"

        if columns is None:
            if isinstance(data[0], dict):
                columns = list(data[0].keys())
            else:
                return str(data)

        console = Console()
        table = Table(show_header=True, header_style="bold")

        for col in columns:
            table.add_column(col)

        for row in data:
            table.add_row(*[str(row.get(col, "")) for col in columns])

        with console.capture() as capture:
            console.print(table)

        return capture.get()

    @classmethod
    def format(
        cls,
        data: Any,
        format_type: str = "table",
        columns: Optional[List[str]] = None,
    ) -> str:
        """Format data based on specified format type"""
        if isinstance(data, list) and data and isinstance(data[0], dict):
            if format_type == "json":
                return cls.format_json(data)
            elif format_type == "yaml":
                return cls.format_yaml(data)
            elif format_type in ("table", "rich"):
                return cls.format_table(data, columns)
            else:
                return cls.format_table(data, columns)
        elif isinstance(data, dict):
            if format_type == "json":
                return cls.format_json(data)
            elif format_type == "yaml":
                return cls.format_yaml(data)
            else:
                return cls.format_json(data)
        else:
            return str(data)
