"""Plugin system for local ingestion extensibility."""

from __future__ import annotations

import importlib
import importlib.util
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class PluginError(Exception):
    """Base exception for plugin errors"""

    pass


class PluginLoadError(PluginError):
    """Exception raised when plugin loading fails"""

    pass


class PluginNotFoundError(PluginError):
    """Exception raised when plugin is not found"""

    pass


class PluginInterface(ABC):
    """Abstract base class for plugins"""

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name"""
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self) -> str:
        """Plugin version"""
        raise NotImplementedError

    @property
    def description(self) -> str:
        """Plugin description"""
        return ""

    @abstractmethod
    def initialize(self, config: Dict[str, Any]) -> None:
        """
        Initialize the plugin.

        Args:
            config: Plugin configuration
        """
        raise NotImplementedError

    @abstractmethod
    def execute(self, context: Dict[str, Any]) -> Any:
        """
        Execute the plugin.

        Args:
            context: Execution context

        Returns:
            Plugin execution result
        """
        raise NotImplementedError

    def shutdown(self) -> None:
        """Cleanup plugin resources"""
        pass


@dataclass
class PluginMetadata:
    """Plugin metadata"""

    name: str
    version: str
    description: str = ""
    author: Optional[str] = None
    entry_point: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    config_schema: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class PluginManager:
    """Manager for plugin lifecycle and discovery"""

    def __init__(self, plugin_dirs: Optional[List[str]] = None):
        """
        Initialize plugin manager.

        Args:
            plugin_dirs: Optional list of plugin directory paths
        """
        self._plugins: Dict[str, Type[PluginInterface]] = {}
        self._instances: Dict[str, PluginInterface] = {}
        self._configs: Dict[str, Dict[str, Any]] = {}
        self._plugin_dirs = plugin_dirs or []

    def add_plugin_directory(self, path: str) -> None:
        """
        Add a plugin directory to search.

        Args:
            path: Directory path
        """
        if path not in self._plugin_dirs:
            self._plugin_dirs.append(path)

    def register_plugin(self, plugin_class: Type[PluginInterface]) -> None:
        """
        Register a plugin class.

        Args:
            plugin_class: Plugin class to register
        """
        instance = plugin_class()
        name = instance.name
        self._plugins[name] = plugin_class
        logger.info("Registered plugin: %s (version %s)", name, instance.version)

    def unregister_plugin(self, name: str) -> bool:
        """
        Unregister a plugin.

        Args:
            name: Plugin name

        Returns:
            True if plugin was removed
        """
        if name in self._instances:
            self.unload_plugin(name)
        if name in self._plugins:
            del self._plugins[name]
            return True
        return False

    def discover_plugins(self) -> List[PluginMetadata]:
        """
        Discover plugins in configured directories.

        Returns:
            List of discovered plugin metadata
        """
        discovered = []

        for plugin_dir in self._plugin_dirs:
            path = Path(plugin_dir)
            if not path.exists() or not path.is_dir():
                logger.warning("Plugin directory not found: %s", plugin_dir)
                continue

            for file_path in path.glob("*.py"):
                if file_path.name.startswith("_"):
                    continue

                try:
                    metadata = self._discover_plugin_file(file_path)
                    if metadata:
                        discovered.append(metadata)
                except Exception as e:
                    logger.error(
                        "Failed to discover plugin in %s: %s",
                        file_path,
                        str(e),
                    )

        return discovered

    def _discover_plugin_file(self, file_path: Path) -> Optional[PluginMetadata]:
        """
        Discover plugin from file.

        Args:
            file_path: Path to plugin file

        Returns:
            Plugin metadata or None
        """
        module_name = f"plugin_{file_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            logger.debug("Module load failed for %s: %s", file_path, str(e))
            return None

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, PluginInterface)
                and attr is not PluginInterface
            ):
                instance = attr()
                return PluginMetadata(
                    name=instance.name,
                    version=instance.version,
                    description=instance.description,
                )

        return None

    def load_plugin(
        self,
        name: str,
        config: Optional[Dict[str, Any]] = None,
        plugin_class: Optional[Type[PluginInterface]] = None,
    ) -> PluginInterface:
        """
        Load a plugin instance.

        Args:
            name: Plugin name
            config: Optional plugin configuration
            plugin_class: Optional plugin class (if not registered)

        Returns:
            Loaded plugin instance

        Raises:
            PluginNotFoundError: If plugin not found
            PluginLoadError: If plugin fails to load
        """
        if name in self._instances:
            logger.debug("Plugin already loaded: %s", name)
            return self._instances[name]

        plugin_cls = plugin_class or self._plugins.get(name)
        if plugin_cls is None:
            raise PluginNotFoundError(f"Plugin not found: {name}")

        try:
            instance = plugin_cls()
            instance.initialize(config or {})
            self._instances[name] = instance
            self._configs[name] = config or {}
            logger.info("Loaded plugin: %s", name)
            return instance

        except Exception as e:
            raise PluginLoadError(f"Failed to load plugin {name}: {str(e)}") from e

    def unload_plugin(self, name: str) -> bool:
        """
        Unload a plugin instance.

        Args:
            name: Plugin name

        Returns:
            True if plugin was unloaded
        """
        if name not in self._instances:
            return False

        try:
            instance = self._instances[name]
            instance.shutdown()
            del self._instances[name]
            if name in self._configs:
                del self._configs[name]
            logger.info("Unloaded plugin: %s", name)
            return True

        except Exception as e:
            logger.error("Failed to unload plugin %s: %s", name, str(e))
            return False

    def execute_plugin(
        self, name: str, context: Dict[str, Any]
    ) -> Any:
        """
        Execute a loaded plugin.

        Args:
            name: Plugin name
            context: Execution context

        Returns:
            Plugin execution result

        Raises:
            PluginNotFoundError: If plugin not loaded
        """
        instance = self._instances.get(name)
        if instance is None:
            raise PluginNotFoundError(f"Plugin not loaded: {name}")

        return instance.execute(context)

    def get_plugin(self, name: str) -> Optional[PluginInterface]:
        """
        Get a loaded plugin instance.

        Args:
            name: Plugin name

        Returns:
            Plugin instance or None
        """
        return self._instances.get(name)

    def list_plugins(self) -> List[str]:
        """
        List all registered plugin names.

        Returns:
            List of plugin names
        """
        return list(self._plugins.keys())

    def list_loaded_plugins(self) -> List[str]:
        """
        List all loaded plugin names.

        Returns:
            List of loaded plugin names
        """
        return list(self._instances.keys())

    def is_loaded(self, name: str) -> bool:
        """
        Check if plugin is loaded.

        Args:
            name: Plugin name

        Returns:
            True if plugin is loaded
        """
        return name in self._instances

    def shutdown_all(self) -> None:
        """Shutdown all loaded plugins"""
        for name in list(self._instances.keys()):
            self.unload_plugin(name)
        self._plugins.clear()
        logger.info("All plugins shutdown")


class CustomConnectorPlugin(PluginInterface):
    """Example custom connector plugin"""

    @property
    def name(self) -> str:
        return "custom_connector"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def description(self) -> str:
        return "Custom connector plugin for extending data source capabilities"

    def initialize(self, config: Dict[str, Any]) -> None:
        """Initialize the plugin with configuration"""
        self._config = config
        self._connector_type = config.get("connector_type", "custom")
        logger.info(
            "CustomConnectorPlugin initialized with type: %s",
            self._connector_type,
        )

    def execute(self, context: Dict[str, Any]) -> Any:
        """Execute the custom connector"""
        source = context.get("source", {})
        records = context.get("records", [])

        processed = []
        for record in records:
            processed_record = {
                **record,
                "_connector_type": self._connector_type,
                "_processed_by": self.name,
            }
            processed.append(processed_record)

        return {
            "connector_type": self._connector_type,
            "records_processed": len(records),
            "records": processed,
        }
