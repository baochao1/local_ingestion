"""Base command class for CLI commands"""
from __future__ import annotations

import argparse
import logging
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from local_ingestion.api.exceptions import ServiceError, ValidationError

logger = logging.getLogger(__name__)


class BaseCommand(ABC):
    """Abstract base class for all CLI commands"""

    name: str = ""
    help: str = ""

    def __init__(self):
        self.parser = argparse.ArgumentParser(
            prog=self.name,
            description=self.help,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        self._add_arguments()

    @abstractmethod
    def _add_arguments(self) -> None:
        """Add command-specific arguments"""
        raise NotImplementedError

    @abstractmethod
    def execute(self, args: argparse.Namespace) -> int:
        """Execute the command"""
        raise NotImplementedError

    def parse_args(self, args: Optional[list[str]] = None) -> argparse.Namespace:
        """Parse command-line arguments"""
        return self.parser.parse_args(args)

    def run(self, args: Optional[list[str]] = None) -> int:
        """Run the command with error handling"""
        try:
            parsed_args = self.parse_args(args)
            return self.execute(parsed_args)
        except ValidationError as e:
            logger.error(f"Validation error: {e.message}")
            self.parser.error(e.message)
            return 1
        except ServiceError as e:
            logger.error(f"Service error: {e.message}")
            print(f"Error: {e.message}", file=sys.stderr)
            return 1
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            print(f"Unexpected error: {e}", file=sys.stderr)
            return 1

    def print_success(self, message: str) -> None:
        """Print success message"""
        print(f"Success: {message}")

    def print_error(self, message: str) -> None:
        """Print error message"""
        print(f"Error: {message}", file=sys.stderr)

    def print_info(self, message: str) -> None:
        """Print info message"""
        print(message)


def load_config_file(config_path: str) -> Dict[str, Any]:
    """Load configuration from a JSON or YAML file"""
    import json
    import yaml

    try:
        with open(config_path, "r") as f:
            if config_path.endswith(".yaml") or config_path.endswith(".yml"):
                return yaml.safe_load(f)
            else:
                return json.load(f)
    except FileNotFoundError:
        raise ValidationError(f"Config file not found: {config_path}", field="config")
    except (json.JSONDecodeError, yaml.YAMLError) as e:
        raise ValidationError(f"Invalid config file format: {e}", field="config")
