"""Workflow configuration tests"""
import pytest
import tempfile
import yaml
from local_ingestion.schema.metadata.workflow import (
    LocalWorkflowConfig,
    WorkflowConfig,
    FileSinkConfig,
    SourceConfig,
    LogLevels,
)


class TestWorkflowConfig:
    def test_config_creation(self):
        config = WorkflowConfig(pipelineName="test-workflow")
        assert config.pipelineName == "test-workflow"

    def test_default_logger_level(self):
        config = WorkflowConfig()
        assert config.loggerLevel == LogLevels.INFO


class TestLocalWorkflowConfig:
    def test_from_dict(self):
        data = {
            "workflowConfig": {
                "loggerLevel": "DEBUG",
                "pipelineName": "mysql-ingest"
            },
            "source": {
                "type": "mysql",
                "serviceName": "prod-mysql",
                "config": {
                    "hostPort": "localhost:3306"
                }
            },
            "sink": {
                "type": "file",
                "config": {
                    "outputPath": "./output.json"
                }
            }
        }
        config = LocalWorkflowConfig.from_dict(data)
        assert config.workflowConfig.pipelineName == "mysql-ingest"
        assert config.source["type"] == "mysql"
        assert config.sink["type"] == "file"

    def test_from_yaml(self):
        data = {
            "workflowConfig": {"pipelineName": "test"},
            "source": {"type": "mysql"},
            "sink": {"type": "file", "config": {"outputPath": "out.json"}}
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(data, f)
            path = f.name

        config = LocalWorkflowConfig.from_yaml(path)
        assert config.workflowConfig.pipelineName == "test"

        import os
        os.unlink(path)


class TestFileSinkConfig:
    def test_defaults(self):
        config = FileSinkConfig()
        assert config.type == "file"
        assert config.outputPath == "./output"
        assert config.format == "json"

    def test_ndjson_format(self):
        config = FileSinkConfig(format="ndjson")
        assert config.format == "ndjson"
