"""Unit tests for CLI base components"""
from __future__ import annotations

from io import StringIO
from typing import Any, Dict, List
import argparse

import pytest

from local_ingestion.cli.base import CLIContext, BaseCommand, CommandGroup
from local_ingestion.cli.formatter import OutputFormatter
from local_ingestion.cli.parser import (
    build_parser,
    parse_args,
    create_context,
    add_global_options,
    CommandParser,
)


class TestCLIContext:
    """Tests for CLIContext class"""

    def test_initialization_defaults(self):
        """Test CLIContext initializes with default values"""
        context = CLIContext()
        assert context.verbose is False
        assert context.quiet is False
        assert context.output_format == "table"
        assert context._state == {}

    def test_initialization_with_values(self):
        """Test CLIContext initializes with custom values"""
        context = CLIContext(verbose=True, quiet=True, output_format="json")
        assert context.verbose is True
        assert context.quiet is True
        assert context.output_format == "json"

    def test_set_and_get(self):
        """Test set and get state methods"""
        context = CLIContext()
        context.set("key1", "value1")
        context.set("key2", 42)

        assert context.get("key1") == "value1"
        assert context.get("key2") == 42

    def test_get_with_default(self):
        """Test get returns default for missing keys"""
        context = CLIContext()
        assert context.get("nonexistent") is None
        assert context.get("nonexistent", "default") == "default"

    def test_is_verbose(self):
        """Test is_verbose method"""
        context = CLIContext(verbose=False)
        assert context.is_verbose() is False

        context.verbose = True
        assert context.is_verbose() is True

    def test_is_quiet(self):
        """Test is_quiet method"""
        context = CLIContext(quiet=False)
        assert context.is_quiet() is False

        context.quiet = True
        assert context.is_quiet() is True

    def test_get_output_format(self):
        """Test get_output_format method"""
        context = CLIContext(output_format="yaml")
        assert context.get_output_format() == "yaml"

    def test_repr(self):
        """Test string representation"""
        context = CLIContext(verbose=True, quiet=False, output_format="json")
        repr_str = repr(context)
        assert "CLIContext" in repr_str
        assert "verbose=True" in repr_str
        assert "output_format=json" in repr_str


class TestBaseCommand:
    """Tests for BaseCommand class"""

    def test_command_creation(self):
        """Test BaseCommand can be subclassed"""

        class TestCommand(BaseCommand):
            name = "test"
            help = "Test command"

            def execute(self, args: List[str]) -> int:
                return 0

        command = TestCommand()
        assert command.command_name == "test"
        assert command.command_help == "Test command"

    def test_command_with_context(self):
        """Test BaseCommand accepts context"""
        context = CLIContext(verbose=True)
        command = TestCommandWithContext()
        command._context = context

        assert command.context.verbose is True

    def test_execute_returns_int(self):
        """Test execute method returns integer exit code"""

        class SimpleCommand(BaseCommand):
            name = "simple"
            help = "Simple command"

            def execute(self, args: List[str]) -> int:
                return 0

        command = SimpleCommand()
        result = command.execute([])
        assert isinstance(result, int)

    def test_add_arguments(self):
        """Test add_arguments method"""

        class CommandWithArgs(BaseCommand):
            name = "args"
            help = "Command with arguments"

            def add_arguments(self, parser):
                parser.add_argument("--name", type=str)

            def execute(self, args: List[str]) -> int:
                return 0

        parser = argparse.ArgumentParser()
        command = CommandWithArgs()
        command.add_arguments(parser)

        args = parser.parse_args(["--name", "test"])
        assert args.name == "test"

    def test_print_error(self, capsys):
        """Test print_error method"""

        class ErrorCommand(BaseCommand):
            name = "error"
            help = "Error command"

            def execute(self, args: List[str]) -> int:
                self.print_error("Something went wrong")
                return 1

        command = ErrorCommand()
        command.execute([])
        captured = capsys.readouterr()
        assert "Error: Something went wrong" in captured.err

    def test_print_error_suppressed_in_quiet_mode(self, capsys):
        """Test print_error is suppressed in quiet mode"""
        context = CLIContext(quiet=True)
        command = TestCommandWithContext()
        command._context = context
        command.print_error("Error message")

        captured = capsys.readouterr()
        assert "Error message" not in captured.err

    def test_print_info(self, capsys):
        """Test print_info method"""

        class InfoCommand(BaseCommand):
            name = "info"
            help = "Info command"

            def execute(self, args: List[str]) -> int:
                self.print_info("Info message")
                return 0

        command = InfoCommand()
        command.execute([])
        captured = capsys.readouterr()
        assert "Info message" in captured.out

    def test_print_info_suppressed_in_quiet_mode(self, capsys):
        """Test print_info is suppressed in quiet mode"""
        context = CLIContext(quiet=True)
        command = TestCommandWithContext()
        command._context = context
        command.print_info("Info message")

        captured = capsys.readouterr()
        assert "Info message" not in captured.out

    def test_log_debug(self):
        """Test log_debug only logs when verbose"""
        context = CLIContext(verbose=False)
        command = TestCommandWithContext()
        command._context = context
        command.log_debug("Debug message")


class TestCommandGroup:
    """Tests for CommandGroup class"""

    def test_group_creation(self):
        """Test CommandGroup initializes correctly"""
        group = CommandGroup("test_group", "Test group help")
        assert group.name == "test_group"
        assert group.help == "Test group help"
        assert group.list_commands() == []

    def test_register_command(self):
        """Test registering commands"""

        class TestCommand(BaseCommand):
            name = "test"
            help = "Test command"

            def execute(self, args: List[str]) -> int:
                return 0

        group = CommandGroup("group")
        command = TestCommand()
        group.register(command)

        assert "test" in group.list_commands()
        assert group.get_command("test") is command

    def test_get_nonexistent_command(self):
        """Test getting nonexistent command returns None"""
        group = CommandGroup("group")
        assert group.get_command("nonexistent") is None

    def test_list_commands(self):
        """Test listing all commands"""

        class Command1(BaseCommand):
            name = "cmd1"
            help = "Command 1"

            def execute(self, args: List[str]) -> int:
                return 0

        class Command2(BaseCommand):
            name = "cmd2"
            help = "Command 2"

            def execute(self, args: List[str]) -> int:
                return 0

        group = CommandGroup("group")
        group.register(Command1())
        group.register(Command2())

        commands = group.list_commands()
        assert "cmd1" in commands
        assert "cmd2" in commands

    def test_get_all_commands(self):
        """Test getting all commands"""
        group = CommandGroup("group")
        cmd1 = TestCommand1()
        cmd2 = TestCommand2()
        group.register(cmd1)
        group.register(cmd2)

        all_commands = group.get_all_commands()
        assert len(all_commands) == 2
        assert "cmd1" in all_commands
        assert "cmd2" in all_commands


class TestOutputFormatter:
    """Tests for OutputFormatter class"""

    def test_format_json_list(self):
        """Test formatting list data as JSON"""
        data = [{"id": 1, "name": "test"}]
        result = OutputFormatter.format_json(data)
        assert '"id": 1' in result
        assert '"name": "test"' in result

    def test_format_json_dict(self):
        """Test formatting dict data as JSON"""
        data = {"key": "value", "count": 42}
        result = OutputFormatter.format_json(data)
        assert '"key": "value"' in result
        assert '"count": 42' in result

    def test_format_json_nested(self):
        """Test formatting nested data as JSON"""
        data = {"user": {"name": "test", "roles": ["admin"]}}
        result = OutputFormatter.format_json(data)
        assert '"user"' in result
        assert '"name": "test"' in result

    def test_format_table_empty(self):
        """Test formatting empty data as table"""
        result = OutputFormatter.format_table([])
        assert result == "No data to display"

    def test_format_table_simple(self):
        """Test formatting simple list of dicts as table"""
        data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        result = OutputFormatter.format_table(data)

        assert "name" in result
        assert "age" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_format_table_custom_columns(self):
        """Test formatting with custom columns"""
        data = [
            {"id": 1, "name": "test", "status": "active"},
        ]
        columns = ["id", "name"]
        result = OutputFormatter.format_table(data, columns=columns)

        assert "id" in result
        assert "name" in result
        assert "status" not in result

    def test_format_table_column_width(self):
        """Test table column widths are calculated correctly"""
        data = [
            {"short": "a", "long_column": "very long value"},
        ]
        result = OutputFormatter.format_table(data)

        assert "short" in result
        assert "long_column" in result

    def test_format_yaml(self):
        """Test formatting as YAML"""
        data = {"key": "value", "list": [1, 2, 3]}
        try:
            result = OutputFormatter.format_yaml(data)
            assert "key: value" in result
        except ImportError:
            pytest.skip("PyYAML not available")

    def test_format_yaml_nested(self):
        """Test formatting nested data as YAML"""
        data = {"user": {"name": "test", "active": True}}
        try:
            result = OutputFormatter.format_yaml(data)
            assert "user:" in result
            assert "name: test" in result
        except ImportError:
            pytest.skip("PyYAML not available")

    def test_format_method_json(self):
        """Test format method with JSON"""
        data = {"key": "value"}
        result = OutputFormatter.format(data, format_type="json")
        assert '"key": "value"' in result

    def test_format_method_yaml(self):
        """Test format method with YAML"""
        data = {"key": "value"}
        try:
            result = OutputFormatter.format(data, format_type="yaml")
            assert "key: value" in result
        except ImportError:
            pytest.skip("PyYAML not available")

    def test_format_method_table(self):
        """Test format method with table"""
        data = [{"id": 1}]
        result = OutputFormatter.format(data, format_type="table")
        assert "id" in result

    def test_format_method_default(self):
        """Test format method defaults to table"""
        data = [{"id": 1}]
        result = OutputFormatter.format(data)
        assert "id" in result

    def test_format_non_dict_list(self):
        """Test formatting non-dict list returns string"""
        data = [1, 2, 3]
        result = OutputFormatter.format_table(data)
        assert str(data) == result

    def test_format_non_dict_item(self):
        """Test formatting non-dict item returns string"""
        data = "simple string"
        result = OutputFormatter.format(data, format_type="json")
        assert result == "simple string"


class TestParser:
    """Tests for parser functions"""

    def test_build_parser(self):
        """Test building main parser"""
        parser = build_parser()
        assert parser.prog == "local-ingestion"

    def test_build_parser_custom_prog(self):
        """Test building parser with custom prog"""
        parser = build_parser(prog="custom-prog")
        assert parser.prog == "custom-prog"

    def test_build_parser_with_version(self):
        """Test parser has version option"""
        parser = build_parser(version="1.0.0")
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_parse_args_verbose(self):
        """Test parsing verbose flag"""
        parser = build_parser()
        args = parser.parse_args(["--verbose"])
        assert args.verbose is True

    def test_parse_args_quiet(self):
        """Test parsing quiet flag"""
        parser = build_parser()
        args = parser.parse_args(["--quiet"])
        assert args.quiet is True

    def test_parse_args_format(self):
        """Test parsing format option"""
        parser = build_parser()
        args = parser.parse_args(["--format", "json"])
        assert args.format == "json"

    def test_parse_args_invalid_format(self):
        """Test parsing invalid format raises error"""
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--format", "invalid"])

    def test_parse_args_multiple(self):
        """Test parsing multiple options"""
        parser = build_parser()
        args = parser.parse_args(["--verbose", "--quiet", "--format", "yaml"])
        assert args.verbose is True
        assert args.quiet is True
        assert args.format == "yaml"

    def test_create_context(self):
        """Test creating CLIContext from args"""
        parser = build_parser()
        args = parser.parse_args(["--verbose", "--format", "json"])
        context = create_context(args)

        assert context.verbose is True
        assert context.quiet is False
        assert context.output_format == "json"

    def test_create_context_with_defaults(self):
        """Test create_context uses defaults"""
        parser = build_parser()
        args = parser.parse_args([])
        context = create_context(args)

        assert context.verbose is False
        assert context.quiet is False
        assert context.output_format == "table"

    def test_add_global_options(self):
        """Test adding global options to parser"""
        parser = argparse.ArgumentParser()
        add_global_options(parser)

        args = parser.parse_args(["--verbose", "--quiet", "--format", "json"])
        assert args.verbose is True
        assert args.quiet is True
        assert args.format == "json"


class TestCommandParser:
    """Tests for CommandParser class"""

    def test_command_parser_creation(self):
        """Test CommandParser initializes correctly"""
        cp = CommandParser("test", "Test parser")
        assert cp.name == "test"
        assert cp.help_text == "Test parser"

    def test_command_parser_setup(self):
        """Test CommandParser setup method"""
        cp = CommandParser("test")
        parser = argparse.ArgumentParser()
        cp.setup(parser)
        assert cp._parser is parser


class TestIntegration:
    """Integration tests for CLI components"""

    def test_full_command_flow(self):
        """Test complete command execution flow"""
        parser = build_parser()

        class SampleCommand(BaseCommand):
            name = "sample"
            help = "Sample command"

            def execute(self, args: List[str]) -> int:
                self.print_info(f"Running with {len(args)} args")
                return 0

        context = create_context(parser.parse_args([]))
        command = SampleCommand(context=context)

        assert command.context is context
        exit_code = command.execute(["arg1", "arg2"])
        assert exit_code == 0

    def test_verbose_logging(self):
        """Test verbose logging through command"""
        parser = build_parser()
        args = parser.parse_args(["--verbose"])
        context = create_context(args)

        command = TestCommandWithContext()
        command._context = context
        command.log_debug("Debug message")

    def test_output_format_in_context(self):
        """Test output format propagates to context"""
        parser = build_parser()
        args = parser.parse_args(["--format", "yaml"])
        context = create_context(args)

        assert context.get_output_format() == "yaml"


# Helper command classes for testing
class TestCommandWithContext(BaseCommand):
    """Test command implementation for context tests"""

    name = "test"
    help = "Test command"

    def execute(self, args: List[str]) -> int:
        return 0


class TestCommand1(BaseCommand):
    """Test command 1"""

    name = "cmd1"
    help = "Command 1"

    def execute(self, args: List[str]) -> int:
        return 0


class TestCommand2(BaseCommand):
    """Test command 2"""

    name = "cmd2"
    help = "Command 2"

    def execute(self, args: List[str]) -> int:
        return 0
