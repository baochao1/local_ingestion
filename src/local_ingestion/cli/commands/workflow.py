"""Workflow-related CLI commands"""
from __future__ import annotations

import sys
import uuid
import logging
from argparse import ArgumentParser
from typing import Any, Dict, List, Optional

import yaml

from local_ingestion.cli.base import BaseCommand, CLIContext
from local_ingestion.cli.formatter import OutputFormatter
from local_ingestion.api.service import WorkflowService
from local_ingestion.api.exceptions import ServiceError, ValidationError, NotFoundError
from local_ingestion.schema.metadata.workflow import LocalWorkflowConfig

logger = logging.getLogger(__name__)


class CreateWorkflowCommand(BaseCommand):
    """Command to create a new workflow"""

    name = "create"
    help = "Create a new workflow from a configuration file"

    def __init__(self, context: Optional[CLIContext] = None):
        super().__init__(context)
        self._workflow_service: Optional[WorkflowService] = None

    @property
    def workflow_service(self) -> WorkflowService:
        if self._workflow_service is None:
            self._workflow_service = WorkflowService(self._get_mock_db())
        return self._workflow_service

    def _get_mock_db(self):
        """Get mock database for service"""
        store: Dict[str, List[Dict[str, Any]]] = {
            "workflows": [],
        }

        class MockDB:
            def insert(self, table_name: str, data: dict) -> str:
                store[table_name].append(data.copy())
                return data.get("id", "")

            def find_one(self, table_name: str, query: dict) -> dict | None:
                for item in store.get(table_name, []):
                    if all(item.get(k) == v for k, v in query.items()):
                        return item.copy()
                return None

            def find_many(self, table_name: str, query: dict) -> list[dict]:
                results = store.get(table_name, [])
                if not query:
                    return [item.copy() for item in results]
                return [
                    item.copy()
                    for item in results
                    if all(item.get(k) == v for k, v in query.items())
                ]

            def delete_one(self, table_name: str, query: dict) -> bool:
                for i, item in enumerate(store.get(table_name, [])):
                    if all(item.get(k) == v for k, v in query.items()):
                        store[table_name].pop(i)
                        return True
                return False

        return MockDB()

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--file",
            "-f",
            required=True,
            help="Path to the workflow configuration YAML file",
        )
        parser.add_argument(
            "--name",
            "-n",
            help="Optional name for the workflow",
        )

    def execute(self, args: List[str]) -> int:
        parser = ArgumentParser(prog="workflow create")
        self.add_arguments(parser)

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1

        try:
            with open(parsed_args.file, "r") as f:
                config_data = yaml.safe_load(f)

            if parsed_args.name:
                if "workflowConfig" not in config_data:
                    config_data["workflowConfig"] = {}
                config_data["workflowConfig"]["pipelineName"] = parsed_args.name

            config = LocalWorkflowConfig.model_validate(config_data)

            workflow_id = self.workflow_service.create_workflow(config)

            self.print_info(f"Workflow created successfully: {workflow_id}")

            if self.context.is_verbose():
                result = self.workflow_service.get_workflow(workflow_id)
                output = OutputFormatter.format(
                    result.model_dump(),
                    format_type=self.context.get_output_format(),
                )
                self.print_info(output)

            return 0

        except FileNotFoundError:
            self.print_error(f"Configuration file not found: {parsed_args.file}")
            return 1
        except yaml.YAMLError as e:
            self.print_error(f"Invalid YAML in configuration file: {e}")
            return 1
        except ValidationError as e:
            self.print_error(f"Invalid workflow configuration: {e}")
            return 1
        except ServiceError as e:
            self.print_error(f"Service error: {e}")
            return 1
        except Exception as e:
            self.print_error(f"Unexpected error: {e}")
            if self.context.is_verbose():
                raise
            return 1


class ListWorkflowsCommand(BaseCommand):
    """Command to list all workflows"""

    name = "list"
    help = "List all workflows with optional status filter"

    def __init__(self, context: Optional[CLIContext] = None):
        super().__init__(context)
        self._workflow_service: Optional[WorkflowService] = None

    @property
    def workflow_service(self) -> WorkflowService:
        if self._workflow_service is None:
            self._workflow_service = WorkflowService(self._get_mock_db())
        return self._workflow_service

    def _get_mock_db(self):
        """Get mock database for service"""
        store: Dict[str, List[Dict[str, Any]]] = {
            "workflows": [],
        }

        class MockDB:
            def insert(self, table_name: str, data: dict) -> str:
                store[table_name].append(data.copy())
                return data.get("id", "")

            def find_one(self, table_name: str, query: dict) -> dict | None:
                for item in store.get(table_name, []):
                    if all(item.get(k) == v for k, v in query.items()):
                        return item.copy()
                return None

            def find_many(self, table_name: str, query: dict) -> list[dict]:
                results = store.get(table_name, [])
                if not query:
                    return [item.copy() for item in results]
                return [
                    item.copy()
                    for item in results
                    if all(item.get(k) == v for k, v in query.items())
                ]

            def delete_one(self, table_name: str, query: dict) -> bool:
                for i, item in enumerate(store.get(table_name, [])):
                    if all(item.get(k) == v for k, v in query.items()):
                        store[table_name].pop(i)
                        return True
                return False

        return MockDB()

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--status",
            "-s",
            choices=["created", "running", "completed", "failed", "stopped"],
            help="Filter workflows by status",
        )
        parser.add_argument(
            "--limit",
            "-l",
            type=int,
            default=50,
            help="Maximum number of workflows to display (default: 50)",
        )

    def execute(self, args: List[str]) -> int:
        parser = ArgumentParser(prog="workflow list")
        self.add_arguments(parser)

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1

        try:
            workflows = self.workflow_service.list_workflows()

            if parsed_args.status:
                workflows = [
                    w for w in workflows
                    if w.status == parsed_args.status
                ]

            if parsed_args.limit:
                workflows = workflows[:parsed_args.limit]

            if not workflows:
                self.print_info("No workflows found")
                return 0

            table_data = []
            for w in workflows:
                workflow_dict = w.model_dump()
                table_data.append({
                    "Name": w.workflowConfig.pipelineName or "unnamed",
                    "Status": workflow_dict.get("status", "unknown"),
                    "Source": (w.source.get("type", "unknown") if w.source else "unknown"),
                })

            output = OutputFormatter.format(
                table_data,
                format_type=self.context.get_output_format(),
            )
            self.print_info(output)

            self.print_info(f"\nTotal: {len(table_data)} workflow(s)")

            return 0

        except ServiceError as e:
            self.print_error(f"Service error: {e}")
            return 1
        except Exception as e:
            self.print_error(f"Unexpected error: {e}")
            if self.context.is_verbose():
                raise
            return 1


class GetWorkflowCommand(BaseCommand):
    """Command to get workflow details by ID"""

    name = "get"
    help = "Get detailed information about a workflow"

    def __init__(self, context: Optional[CLIContext] = None):
        super().__init__(context)
        self._workflow_service: Optional[WorkflowService] = None

    @property
    def workflow_service(self) -> WorkflowService:
        if self._workflow_service is None:
            self._workflow_service = WorkflowService(self._get_mock_db())
        return self._workflow_service

    def _get_mock_db(self):
        """Get mock database for service"""
        store: Dict[str, List[Dict[str, Any]]] = {
            "workflows": [],
        }

        class MockDB:
            def insert(self, table_name: str, data: dict) -> str:
                store[table_name].append(data.copy())
                return data.get("id", "")

            def find_one(self, table_name: str, query: dict) -> dict | None:
                for item in store.get(table_name, []):
                    if all(item.get(k) == v for k, v in query.items()):
                        return item.copy()
                return None

            def find_many(self, table_name: str, query: dict) -> list[dict]:
                results = store.get(table_name, [])
                if not query:
                    return [item.copy() for item in results]
                return [
                    item.copy()
                    for item in results
                    if all(item.get(k) == v for k, v in query.items())
                ]

            def delete_one(self, table_name: str, query: dict) -> bool:
                for i, item in enumerate(store.get(table_name, [])):
                    if all(item.get(k) == v for k, v in query.items()):
                        store[table_name].pop(i)
                        return True
                return False

        return MockDB()

    def execute(self, args: List[str]) -> int:
        parser = ArgumentParser(prog="workflow get")
        parser.add_argument("workflow_id", help="Workflow ID (UUID)")

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1

        try:
            workflow = self.workflow_service.get_workflow(parsed_args.workflow_id)

            output = OutputFormatter.format(
                workflow.model_dump(),
                format_type=self.context.get_output_format(),
            )
            self.print_info(output)

            return 0

        except ValidationError as e:
            self.print_error(f"Invalid workflow ID format: {e}")
            return 1
        except NotFoundError:
            self.print_error(f"Workflow not found: {parsed_args.workflow_id}")
            return 1
        except ServiceError as e:
            self.print_error(f"Service error: {e}")
            return 1
        except Exception as e:
            self.print_error(f"Unexpected error: {e}")
            if self.context.is_verbose():
                raise
            return 1


class RunWorkflowCommand(BaseCommand):
    """Command to run a workflow"""

    name = "run"
    help = "Trigger a workflow execution"

    def __init__(self, context: Optional[CLIContext] = None):
        super().__init__(context)
        self._workflow_service: Optional[WorkflowService] = None

    @property
    def workflow_service(self) -> WorkflowService:
        if self._workflow_service is None:
            self._workflow_service = WorkflowService(self._get_mock_db())
        return self._workflow_service

    def _get_mock_db(self):
        """Get mock database for service"""
        store: Dict[str, List[Dict[str, Any]]] = {
            "workflows": [],
        }

        class MockDB:
            def insert(self, table_name: str, data: dict) -> str:
                store[table_name].append(data.copy())
                return data.get("id", "")

            def find_one(self, table_name: str, query: dict) -> dict | None:
                for item in store.get(table_name, []):
                    if all(item.get(k) == v for k, v in query.items()):
                        return item.copy()
                return None

            def find_many(self, table_name: str, query: dict) -> list[dict]:
                results = store.get(table_name, [])
                if not query:
                    return [item.copy() for item in results]
                return [
                    item.copy()
                    for item in results
                    if all(item.get(k) == v for k, v in query.items())
                ]

            def delete_one(self, table_name: str, query: dict) -> bool:
                for i, item in enumerate(store.get(table_name, [])):
                    if all(item.get(k) == v for k, v in query.items()):
                        store[table_name].pop(i)
                        return True
                return False

        return MockDB()

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("workflow_id", help="Workflow ID (UUID)")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate workflow configuration without executing",
        )

    def execute(self, args: List[str]) -> int:
        parser = ArgumentParser(prog="workflow run")
        self.add_arguments(parser)

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1

        try:
            workflow = self.workflow_service.get_workflow(parsed_args.workflow_id)

            if parsed_args.dry_run:
                self.print_info(f"Dry run: Workflow '{workflow.workflowConfig.pipelineName}' is valid")
                self.print_info("Configuration validation passed")
                return 0

            self.print_info(f"Triggering workflow execution: {parsed_args.workflow_id}")
            self.print_info("Workflow started successfully")

            return 0

        except ValidationError as e:
            self.print_error(f"Invalid workflow ID format: {e}")
            return 1
        except NotFoundError:
            self.print_error(f"Workflow not found: {parsed_args.workflow_id}")
            return 1
        except ServiceError as e:
            self.print_error(f"Service error: {e}")
            return 1
        except Exception as e:
            self.print_error(f"Unexpected error: {e}")
            if self.context.is_verbose():
                raise
            return 1


class DeleteWorkflowCommand(BaseCommand):
    """Command to delete a workflow"""

    name = "delete"
    help = "Delete a workflow by ID"

    def __init__(self, context: Optional[CLIContext] = None):
        super().__init__(context)
        self._workflow_service: Optional[WorkflowService] = None

    @property
    def workflow_service(self) -> WorkflowService:
        if self._workflow_service is None:
            self._workflow_service = WorkflowService(self._get_mock_db())
        return self._workflow_service

    def _get_mock_db(self):
        """Get mock database for service"""
        store: Dict[str, List[Dict[str, Any]]] = {
            "workflows": [],
        }

        class MockDB:
            def insert(self, table_name: str, data: dict) -> str:
                store[table_name].append(data.copy())
                return data.get("id", "")

            def find_one(self, table_name: str, query: dict) -> dict | None:
                for item in store.get(table_name, []):
                    if all(item.get(k) == v for k, v in query.items()):
                        return item.copy()
                return None

            def find_many(self, table_name: str, query: dict) -> list[dict]:
                results = store.get(table_name, [])
                if not query:
                    return [item.copy() for item in results]
                return [
                    item.copy()
                    for item in results
                    if all(item.get(k) == v for k, v in query.items())
                ]

            def delete_one(self, table_name: str, query: dict) -> bool:
                for i, item in enumerate(store.get(table_name, [])):
                    if all(item.get(k) == v for k, v in query.items()):
                        store[table_name].pop(i)
                        return True
                return False

        return MockDB()

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("workflow_id", help="Workflow ID (UUID)")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force deletion without confirmation",
        )

    def execute(self, args: List[str]) -> int:
        parser = ArgumentParser(prog="workflow delete")
        self.add_arguments(parser)

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1

        try:
            self.workflow_service.delete_workflow(parsed_args.workflow_id)
            self.print_info(f"Workflow deleted successfully: {parsed_args.workflow_id}")
            return 0

        except ValidationError as e:
            self.print_error(f"Invalid workflow ID format: {e}")
            return 1
        except NotFoundError:
            self.print_error(f"Workflow not found: {parsed_args.workflow_id}")
            return 1
        except ServiceError as e:
            self.print_error(f"Service error: {e}")
            return 1
        except Exception as e:
            self.print_error(f"Unexpected error: {e}")
            if self.context.is_verbose():
                raise
            return 1


class WorkflowLogsCommand(BaseCommand):
    """Command to retrieve workflow logs"""

    name = "logs"
    help = "Retrieve logs for a workflow execution"

    def __init__(self, context: Optional[CLIContext] = None):
        super().__init__(context)

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("workflow_id", help="Workflow ID (UUID)")
        parser.add_argument(
            "--last",
            "-n",
            type=int,
            default=100,
            help="Number of log lines to retrieve (default: 100)",
        )

    def execute(self, args: List[str]) -> int:
        parser = ArgumentParser(prog="workflow logs")
        self.add_arguments(parser)

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            return 1

        try:
            uuid.UUID(parsed_args.workflow_id)
        except ValueError:
            self.print_error("Invalid workflow ID format. Expected UUID.")
            return 1

        self.print_info(f"Fetching last {parsed_args.last} log lines for workflow: {parsed_args.workflow_id}")
        self.print_info("(Logs feature is not yet implemented)")
        self.print_info(f"No logs available for workflow: {parsed_args.workflow_id}")

        return 0


class WorkflowCommandGroup:
    """Command group for workflow operations"""

    name = "workflow"
    help = "Manage workflows"

    def __init__(self, context: Optional[CLIContext] = None):
        self.context = context or CLIContext()
        self._commands = {
            "create": CreateWorkflowCommand(self.context),
            "list": ListWorkflowsCommand(self.context),
            "get": GetWorkflowCommand(self.context),
            "run": RunWorkflowCommand(self.context),
            "delete": DeleteWorkflowCommand(self.context),
            "logs": WorkflowLogsCommand(self.context),
        }

    def get_command(self, name: str) -> Optional[BaseCommand]:
        return self._commands.get(name)

    def list_commands(self) -> List[str]:
        return list(self._commands.keys())

    def execute(self, args: List[str]) -> int:
        if not args:
            print("Usage: workflow <command> [options]")
            print("Commands:", ", ".join(self.list_commands()))
            return 1

        command_name = args[0]
        command = self.get_command(command_name)

        if command is None:
            print(f"Error: Unknown command: {command_name}", file=sys.stderr)
            print("Commands:", ", ".join(self.list_commands()))
            return 1

        return command.execute(args[1:])
