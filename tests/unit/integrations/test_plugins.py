"""Unit tests for plugins module."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_ingestion.integrations.plugins import (
    CustomConnectorPlugin,
    PluginError,
    PluginLoadError,
    PluginManager,
    PluginMetadata,
    PluginNotFoundError,
)


class TestPluginMetadata:
    """Tests for PluginMetadata"""

    def test_metadata_creation(self):
        """Test creating plugin metadata"""
        metadata = PluginMetadata(
            name="test-plugin",
            version="1.0.0",
            description="A test plugin",
            author="Test Author",
        )
        assert metadata.name == "test-plugin"
        assert metadata.version == "1.0.0"
        assert metadata.author == "Test Author"

    def test_metadata_defaults(self):
        """Test plugin metadata defaults"""
        metadata = PluginMetadata(name="test", version="1.0")
        assert metadata.description == ""
        assert metadata.author is None
        assert metadata.dependencies == []


class TestCustomConnectorPlugin:
    """Tests for CustomConnectorPlugin"""

    @pytest.fixture
    def plugin(self):
        """Create test plugin instance"""
        return CustomConnectorPlugin()

    def test_plugin_properties(self, plugin):
        """Test plugin property accessors"""
        assert plugin.name == "custom_connector"
        assert plugin.version == "1.0.0"
        assert "connector" in plugin.description.lower()

    def test_plugin_initialization(self, plugin):
        """Test plugin initialization"""
        config = {"connector_type": "custom_source"}
        plugin.initialize(config)
        assert plugin._connector_type == "custom_source"

    def test_plugin_execute(self, plugin):
        """Test plugin execution"""
        plugin.initialize({})
        context = {
            "records": [{"id": 1, "name": "test"}],
        }
        result = plugin.execute(context)
        assert result["records_processed"] == 1
        assert len(result["records"]) == 1
        assert result["records"][0]["_processed_by"] == "custom_connector"

    def test_plugin_execute_empty_records(self, plugin):
        """Test plugin execution with empty records"""
        plugin.initialize({})
        context = {"records": []}
        result = plugin.execute(context)
        assert result["records_processed"] == 0
        assert result["records"] == []


class TestPluginManager:
    """Tests for PluginManager"""

    @pytest.fixture
    def manager(self):
        """Create test manager"""
        return PluginManager()

    def test_manager_creation(self):
        """Test creating plugin manager"""
        manager = PluginManager(plugin_dirs=["/plugins"])
        assert "/plugins" in manager._plugin_dirs

    def test_add_plugin_directory(self, manager):
        """Test adding plugin directory"""
        manager.add_plugin_directory("/custom/plugins")
        assert "/custom/plugins" in manager._plugin_dirs

    def test_register_plugin(self, manager):
        """Test registering a plugin class"""
        manager.register_plugin(CustomConnectorPlugin)
        assert "custom_connector" in manager.list_plugins()

    def test_unregister_plugin(self, manager):
        """Test unregistering a plugin"""
        manager.register_plugin(CustomConnectorPlugin)
        assert manager.unregister_plugin("custom_connector") is True
        assert "custom_connector" not in manager.list_plugins()

    def test_unregister_nonexistent(self, manager):
        """Test unregistering nonexistent plugin"""
        assert manager.unregister_plugin("nonexistent") is False

    def test_load_plugin_registered(self, manager):
        """Test loading a registered plugin"""
        manager.register_plugin(CustomConnectorPlugin)
        plugin = manager.load_plugin("custom_connector", {"connector_type": "test"})
        assert plugin is not None
        assert manager.is_loaded("custom_connector")

    def test_load_plugin_twice(self, manager):
        """Test loading same plugin twice returns same instance"""
        manager.register_plugin(CustomConnectorPlugin)
        plugin1 = manager.load_plugin("custom_connector")
        plugin2 = manager.load_plugin("custom_connector")
        assert plugin1 is plugin2

    def test_load_plugin_not_found(self, manager):
        """Test loading nonexistent plugin raises error"""
        with pytest.raises(PluginNotFoundError, match="Plugin not found"):
            manager.load_plugin("nonexistent_plugin")

    def test_load_plugin_with_class(self, manager):
        """Test loading plugin with provided class"""
        plugin = manager.load_plugin(
            "custom_connector",
            plugin_class=CustomConnectorPlugin,
        )
        assert plugin is not None

    def test_load_plugin_init_error(self, manager):
        """Test that plugin initialization errors are wrapped"""
        class BadPlugin:
            name = "bad_plugin"
            version = "1.0"

            def initialize(self, config):
                raise ValueError("Init failed")

        with pytest.raises(PluginLoadError, match="Failed to load plugin"):
            manager.load_plugin("bad_plugin", plugin_class=BadPlugin)

    def test_unload_plugin(self, manager):
        """Test unloading a plugin"""
        manager.register_plugin(CustomConnectorPlugin)
        manager.load_plugin("custom_connector")
        assert manager.unload_plugin("custom_connector") is True
        assert not manager.is_loaded("custom_connector")

    def test_unload_plugin_not_loaded(self, manager):
        """Test unloading plugin that is not loaded"""
        manager.register_plugin(CustomConnectorPlugin)
        assert manager.unload_plugin("custom_connector") is False

    def test_execute_plugin(self, manager):
        """Test executing a plugin"""
        manager.register_plugin(CustomConnectorPlugin)
        manager.load_plugin("custom_connector")

        result = manager.execute_plugin(
            "custom_connector",
            {"records": [{"id": 1}]},
        )
        assert result["records_processed"] == 1

    def test_execute_plugin_not_loaded(self, manager):
        """Test executing unloaded plugin raises error"""
        with pytest.raises(PluginNotFoundError, match="Plugin not loaded"):
            manager.execute_plugin("custom_connector", {})

    def test_get_plugin(self, manager):
        """Test getting plugin instance"""
        manager.register_plugin(CustomConnectorPlugin)
        manager.load_plugin("custom_connector")
        plugin = manager.get_plugin("custom_connector")
        assert plugin is not None
        assert plugin.name == "custom_connector"

    def test_get_plugin_not_loaded(self, manager):
        """Test getting unloaded plugin returns None"""
        assert manager.get_plugin("custom_connector") is None

    def test_list_loaded_plugins(self, manager):
        """Test listing loaded plugins"""
        manager.register_plugin(CustomConnectorPlugin)
        manager.load_plugin("custom_connector")
        assert "custom_connector" in manager.list_loaded_plugins()

    def test_shutdown_all(self, manager):
        """Test shutting down all plugins"""
        manager.register_plugin(CustomConnectorPlugin)
        manager.load_plugin("custom_connector")
        manager.shutdown_all()
        assert len(manager.list_loaded_plugins()) == 0
        assert len(manager.list_plugins()) == 0

    def test_discover_plugins_empty_dir(self, manager):
        """Test discovering plugins in empty directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager.add_plugin_directory(tmpdir)
            discovered = manager.discover_plugins()
            assert len(discovered) == 0

    def test_discover_plugins_nonexistent_dir(self, manager):
        """Test discovering plugins in nonexistent directory"""
        manager.add_plugin_directory("/nonexistent/path")
        discovered = manager.discover_plugins()
        assert len(discovered) == 0


class TestPluginErrors:
    """Tests for plugin error classes"""

    def test_plugin_error(self):
        """Test PluginError base class"""
        error = PluginError("Test error")
        assert str(error) == "Test error"

    def test_plugin_load_error(self):
        """Test PluginLoadError"""
        error = PluginLoadError("Failed to load")
        assert isinstance(error, PluginError)

    def test_plugin_not_found_error(self):
        """Test PluginNotFoundError"""
        error = PluginNotFoundError("Plugin not found")
        assert isinstance(error, PluginError)
