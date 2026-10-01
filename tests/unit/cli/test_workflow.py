"""Unit tests for workflow CLI commands"""
import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from local_ingestion.cli.base import CLIContext
from local_ingestion.cli.commands.workflow import (
    WorkflowCommandGroup,
    CreateWorkflowCommand,
    ListWorkflowsCommand,
    GetWorkflowCommand,
    RunWorkflowCommand,
    DeleteWorkflowCommand,
    WorkflowLogsCommand,
)
from local_ingestion.cli.commands.serve import ServeCommand, ServeStatusCommand
from local_ingestion.api.exceptions import NotFoundError, ValidationError


class MockDB:
    """Mock database for testing"""

    def __init__(self):
        self._store: dict[str, list[dict]] = {
            "workflows": [],
        }

    def insert(self, table_name: str, data: dict) -> str:
        self._store[table_name].append(data.copy())
        return data.get("id", "")

    def find_one(self, table_name: str, query: dict) -> dict | None:
        for item in self._store.get(table_name, []):
            if all(item.get(k) == v for k, v in query.items()):
                return item.copy()
        return None

    def find_many(self, table_name: str, query: dict) -> list[dict]:
        results = self._store.get(table_name, [])
        if not query:
            return [item.copy() for item in results]
        return [
            item.copy()
            for item in results
            if all(item.get(k) == v for k, v in query.items())
        ]

    def delete_one(self, table_name: str, query: dict) -> bool:
        for i, item in enumerate(self._store.get(table_name, [])):
            if all(item.get(k) == v for k, v in query.items()):
                self._store[table_name].pop(i)
                return True
        return False

    def clear(self):
        for key in self._store:
            self._store[key] = []


class TestCreateWorkflowCommand:
    """Tests for CreateWorkflowCommand"""

    def setup_method(self):
        self.context = CLIContext(verbose=False, quiet=False, output_format="table")
        self.command = CreateWorkflowCommand(self.context)
        self.mock_db = MockDB()
        self.command._workflow_service = self.command.workflow_service.__class__(self.mock_db)

    def test_create_workflow_missing_file(self):
        """Test that missing file returns error"""
        result = self.command.execute(["--file", "nonexistent.yaml"])
        assert result == 1

    def test_create_workflow_invalid_yaml(self):
        """Test that invalid YAML returns error"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: content: [")
            temp_path = f.name

        try:
            result = self.command.execute(["--file", temp_path])
            assert result == 1
        finally:
            Path(temp_path).unlink()

    def test_create_workflow_success(self):
        """Test successful workflow creation"""
        config = {
            "workflowConfig": {"pipelineName": "test-workflow"},
            "source": {"type": "mysql", "serviceName": "prod"},
            "sink": {"type": "file", "config": {"outputPath": "./output"}},
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(config, f)
            temp_path = f.name

        try:
            result = self.command.execute(["--file", temp_path])
            assert result == 0
        finally:
            Path(temp_path).unlink()

    def test_create_workflow_with_name(self):
        """Test workflow creation with custom name"""
        config = {
            "workflowConfig": {"pipelineName": "original-name"},
            "source": {"type": "mysql"},
            "sink": {"type": "file"},
        }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(config, f)
            temp_path = f.name

        try:
            result = self.command.execute(["--file", temp_path, "--name", "custom-name"])
            assert result == 0
        finally:
            Path(temp_path).unlink()


class TestListWorkflowsCommand:
    """Tests for ListWorkflowsCommand"""

    def setup_method(self):
        self.context = CLIContext(verbose=False, quiet=False, output_format="table")
        self.command = ListWorkflowsCommand(self.context)
        self.mock_db = MockDB()
        self.command._workflow_service = self.command.workflow_service.__class__(self.mock_db)

    def test_list_workflows_empty(self):
        """Test listing workflows when none exist"""
        result = self.command.execute([])
        assert result == 0

    def test_list_workflows_with_data(self):
        """Test listing workflows with data"""
        self.mock_db.insert("workflows", {
            "id": "test-uuid-1",
            "status": "created",
            "workflowConfig": {"pipelineName": "workflow1"},
            "source": {"type": "mysql"},
            "sink": {"type": "file"},
        })

        result = self.command.execute([])
        assert result == 0

    def test_list_workflows_with_limit(self):
        """Test listing workflows with limit"""
        result = self.command.execute(["--limit", "10"])
        assert result == 0


class TestGetWorkflowCommand:
    """Tests for GetWorkflowCommand"""

    def setup_method(self):
        self.context = CLIContext(verbose=False, quiet=False, output_format="table")
        self.command = GetWorkflowCommand(self.context)
        self.mock_db = MockDB()
        self.command._workflow_service = self.command.workflow_service.__class__(self.mock_db)

    def test_get_workflow_not_found(self):
        """Test getting non-existent workflow"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        result = self.command.execute([fake_id])
        assert result == 1

    def test_get_workflow_invalid_id(self):
        """Test getting workflow with invalid ID format"""
        result = self.command.execute(["not-a-uuid"])
        assert result == 1

    def test_get_workflow_success(self):
        """Test getting existing workflow"""
        workflow_id = "12345678-1234-1234-1234-123456789012"
        self.mock_db.insert("workflows", {
            "id": workflow_id,
            "status": "created",
            "workflowConfig": {"pipelineName": "test"},
            "source": {"type": "mysql"},
            "sink": {"type": "file"},
        })

        result = self.command.execute([workflow_id])
        assert result == 0


class TestRunWorkflowCommand:
    """Tests for RunWorkflowCommand"""

    def setup_method(self):
        self.context = CLIContext(verbose=False, quiet=False, output_format="table")
        self.command = RunWorkflowCommand(self.context)
        self.mock_db = MockDB()
        self.command._workflow_service = self.command.workflow_service.__class__(self.mock_db)

    def test_run_workflow_not_found(self):
        """Test running non-existent workflow"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        result = self.command.execute([fake_id])
        assert result == 1

    def test_run_workflow_dry_run(self):
        """Test dry run mode"""
        workflow_id = "12345678-1234-1234-1234-123456789012"
        self.mock_db.insert("workflows", {
            "id": workflow_id,
            "status": "created",
            "workflowConfig": {"pipelineName": "test"},
            "source": {"type": "mysql"},
            "sink": {"type": "file"},
        })

        result = self.command.execute([workflow_id, "--dry-run"])
        assert result == 0


class TestDeleteWorkflowCommand:
    """Tests for DeleteWorkflowCommand"""

    def setup_method(self):
        self.context = CLIContext(verbose=False, quiet=False, output_format="table")
        self.command = DeleteWorkflowCommand(self.context)
        self.mock_db = MockDB()
        self.command._workflow_service = self.command.workflow_service.__class__(self.mock_db)

    def test_delete_workflow_not_found(self):
        """Test deleting non-existent workflow"""
        fake_id = "00000000-0000-0000-0000-000000000000"
        result = self.command.execute([fake_id])
        assert result == 1

    def test_delete_workflow_success(self):
        """Test successful workflow deletion"""
        workflow_id = "12345678-1234-1234-1234-123456789012"
        self.mock_db.insert("workflows", {
            "id": workflow_id,
            "status": "created",
            "workflowConfig": {"pipelineName": "test"},
            "source": {"type": "mysql"},
            "sink": {"type": "file"},
        })

        result = self.command.execute([workflow_id, "--force"])
        assert result == 0


class TestWorkflowLogsCommand:
    """Tests for WorkflowLogsCommand"""

    def setup_method(self):
        self.context = CLIContext(verbose=False, quiet=False, output_format="table")
        self.command = WorkflowLogsCommand(self.context)

    def test_logs_invalid_id(self):
        """Test logs with invalid workflow ID"""
        result = self.command.execute(["not-a-uuid"])
        assert result == 1

    def test_logs_success(self):
        """Test logs with valid workflow ID"""
        workflow_id = "12345678-1234-1234-1234-123456789012"
        result = self.command.execute([workflow_id])
        assert result == 0

    def test_logs_with_line_limit(self):
        """Test logs with line limit"""
        workflow_id = "12345678-1234-1234-1234-123456789012"
        result = self.command.execute([workflow_id, "--last", "50"])
        assert result == 0


class TestWorkflowCommandGroup:
    """Tests for WorkflowCommandGroup"""

    def setup_method(self):
        self.context = CLIContext()
        self.group = WorkflowCommandGroup(self.context)

    def test_list_commands(self):
        """Test listing all commands"""
        commands = self.group.list_commands()
        assert "create" in commands
        assert "list" in commands
        assert "get" in commands
        assert "run" in commands
        assert "delete" in commands
        assert "logs" in commands

    def test_get_command(self):
        """Test getting individual command"""
        cmd = self.group.get_command("create")
        assert cmd is not None
        assert cmd.name == "create"

    def test_execute_unknown_command(self):
        """Test executing unknown command"""
        result = self.group.execute(["unknown-command"])
        assert result == 1

    def test_execute_no_command(self):
        """Test executing with no command"""
        result = self.group.execute([])
        assert result == 1


class TestServeCommand:
    """Tests for ServeCommand"""

    def setup_method(self):
        self.context = CLIContext(verbose=False, quiet=False)
        self.command = ServeCommand(self.context)

    def test_add_arguments(self):
        """Test that arguments are properly added"""
        parser = MagicMock()
        self.command.add_arguments(parser)
        parser.add_argument.assert_called()


class TestServeStatusCommand:
    """Tests for ServeStatusCommand"""

    def setup_method(self):
        self.context = CLIContext(verbose=False, quiet=False, output_format="table")
        self.command = ServeStatusCommand(self.context)

    def test_execute_success(self):
        """Test status command execution"""
        result = self.command.execute([])
        assert result == 0


class TestLocalIngestionCLI:
    """Tests for the main CLI"""

    def setup_method(self):
        self.context = CLIContext()

    def test_list_command_groups(self):
        """Test listing command groups"""
        from local_ingestion.cli.main import LocalIngestionCLI

        cli = LocalIngestionCLI(self.context)
        groups = cli.list_command_groups()
        assert "workflow" in groups
        assert "serve" in groups

    def test_execute_help(self):
        """Test help output"""
        from local_ingestion.cli.main import LocalIngestionCLI

        cli = LocalIngestionCLI(self.context)
        result = cli.execute(["--help"])
        assert result == 0

    def test_execute_unknown_command(self):
        """Test unknown command handling"""
        from local_ingestion.cli.main import LocalIngestionCLI

        cli = LocalIngestionCLI(self.context)
        result = cli.execute(["unknown"])
        assert result in [0, 1]

    def test_execute_workflow_list(self):
        """Test workflow list command"""
        from local_ingestion.cli.main import LocalIngestionCLI

        cli = LocalIngestionCLI(self.context)
        result = cli.execute(["workflow", "list"])
        assert result == 0
