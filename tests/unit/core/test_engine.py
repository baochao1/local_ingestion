"""Unit tests for workflow engine components"""

import json
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from local_ingestion.core.engine.state import (
    WorkflowState,
    WorkflowEvent,
    WorkflowStatus,
    StateMachine,
    StateStore,
    FileStateStore,
    MemoryStateStore,
    StateTransitionError,
)
from local_ingestion.core.engine.workflow_runner import (
    WorkflowRunner,
    WorkflowExecutor,
    ExecutionContext,
    WorkflowExecutionError,
    PubSubEventBus,
)
from local_ingestion.core.engine.scheduler import (
    WorkflowScheduler,
    TriggerType,
    Schedule,
)
from local_ingestion.core.engine.monitor import (
    WorkflowMonitor,
    MetricsCollector,
    WorkflowMetrics,
    LogEntry,
    Metric,
    MetricType,
)
from local_ingestion.schema.metadata.workflow import LocalWorkflowConfig, WorkflowConfig


class TestWorkflowState:
    """Tests for WorkflowState"""

    def test_state_creation(self):
        """Test creating a workflow state"""
        state = WorkflowState(
            workflow_id="test-123",
            status=WorkflowStatus.CREATED,
        )
        assert state.workflow_id == "test-123"
        assert state.status == WorkflowStatus.CREATED
        assert state.created_at is not None
        assert state.updated_at is not None

    def test_state_to_dict(self):
        """Test converting state to dictionary"""
        state = WorkflowState(
            workflow_id="test-123",
            status=WorkflowStatus.RUNNING,
            total_steps=5,
            completed_steps=2,
        )
        data = state.to_dict()
        assert data["workflow_id"] == "test-123"
        assert data["status"] == "running"
        assert data["total_steps"] == 5
        assert data["completed_steps"] == 2

    def test_state_from_dict(self):
        """Test creating state from dictionary"""
        data = {
            "workflow_id": "test-456",
            "status": "completed",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T01:00:00+00:00",
            "total_steps": 3,
            "completed_steps": 3,
        }
        state = WorkflowState.from_dict(data)
        assert state.workflow_id == "test-456"
        assert state.status == WorkflowStatus.COMPLETED
        assert state.total_steps == 3

    def test_state_update_status(self):
        """Test updating workflow status"""
        state = WorkflowState(
            workflow_id="test-123",
            status=WorkflowStatus.CREATED,
        )
        state.update_status(WorkflowStatus.RUNNING)
        assert state.status == WorkflowStatus.RUNNING
        assert state.started_at is not None

    def test_state_progress(self):
        """Test progress calculation"""
        state = WorkflowState(
            workflow_id="test-123",
            status=WorkflowStatus.RUNNING,
            total_steps=10,
            completed_steps=5,
        )
        assert state.progress() == 50.0

    def test_state_progress_zero_steps(self):
        """Test progress with zero total steps"""
        state = WorkflowState(
            workflow_id="test-123",
            status=WorkflowStatus.CREATED,
            total_steps=0,
            completed_steps=0,
        )
        assert state.progress() == 0.0


class TestStateMachine:
    """Tests for StateMachine"""

    def test_valid_transition_created_to_running(self):
        """Test valid transition from created to running"""
        assert StateMachine.can_transition(
            WorkflowStatus.CREATED, WorkflowEvent.START
        )
        next_status = StateMachine.get_next_status(
            WorkflowStatus.CREATED, WorkflowEvent.START
        )
        assert next_status == WorkflowStatus.RUNNING

    def test_valid_transition_running_to_paused(self):
        """Test valid transition from running to paused"""
        assert StateMachine.can_transition(
            WorkflowStatus.RUNNING, WorkflowEvent.PAUSE
        )
        next_status = StateMachine.get_next_status(
            WorkflowStatus.RUNNING, WorkflowEvent.PAUSE
        )
        assert next_status == WorkflowStatus.PAUSED

    def test_invalid_transition(self):
        """Test invalid transition raises error"""
        assert not StateMachine.can_transition(
            WorkflowStatus.CREATED, WorkflowEvent.PAUSE
        )
        with pytest.raises(StateTransitionError):
            StateMachine.get_next_status(WorkflowStatus.CREATED, WorkflowEvent.PAUSE)

    def test_completed_state_transitions(self):
        """Test transitions from completed state"""
        assert not StateMachine.can_transition(
            WorkflowStatus.COMPLETED, WorkflowEvent.START
        )


class TestMemoryStateStore:
    """Tests for MemoryStateStore"""

    def test_save_and_load(self):
        """Test saving and loading state"""
        store = MemoryStateStore()
        state = WorkflowState(
            workflow_id="test-123",
            status=WorkflowStatus.CREATED,
        )
        store.save(state)
        loaded = store.load("test-123")
        assert loaded is not None
        assert loaded.workflow_id == "test-123"
        assert loaded.status == WorkflowStatus.CREATED

    def test_load_nonexistent(self):
        """Test loading nonexistent state"""
        store = MemoryStateStore()
        loaded = store.load("nonexistent")
        assert loaded is None

    def test_delete(self):
        """Test deleting state"""
        store = MemoryStateStore()
        state = WorkflowState(
            workflow_id="test-123",
            status=WorkflowStatus.CREATED,
        )
        store.save(state)
        assert store.delete("test-123") is True
        assert store.load("test-123") is None

    def test_delete_nonexistent(self):
        """Test deleting nonexistent state"""
        store = MemoryStateStore()
        assert store.delete("nonexistent") is False

    def test_list_all(self):
        """Test listing all states"""
        store = MemoryStateStore()
        store.save(WorkflowState(workflow_id="1", status=WorkflowStatus.CREATED))
        store.save(WorkflowState(workflow_id="2", status=WorkflowStatus.RUNNING))
        states = store.list_all()
        assert len(states) == 2

    def test_clear(self):
        """Test clearing all states"""
        store = MemoryStateStore()
        store.save(WorkflowState(workflow_id="1", status=WorkflowStatus.CREATED))
        store.save(WorkflowState(workflow_id="2", status=WorkflowStatus.RUNNING))
        store.clear()
        assert len(store.list_all()) == 0


class TestFileStateStore:
    """Tests for FileStateStore"""

    def test_save_and_load(self):
        """Test saving and loading state to file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FileStateStore(storage_path=tmpdir)
            state = WorkflowState(
                workflow_id="test-123",
                status=WorkflowStatus.CREATED,
            )
            store.save(state)
            loaded = store.load("test-123")
            assert loaded is not None
            assert loaded.workflow_id == "test-123"

    def test_persistence(self):
        """Test state persists across store instances"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state = WorkflowState(
                workflow_id="test-123",
                status=WorkflowStatus.RUNNING,
                total_steps=5,
            )

            store1 = FileStateStore(storage_path=tmpdir)
            store1.save(state)

            store2 = FileStateStore(storage_path=tmpdir)
            loaded = store2.load("test-123")
            assert loaded is not None
            assert loaded.status == WorkflowStatus.RUNNING
            assert loaded.total_steps == 5


class TestPubSubEventBus:
    """Tests for PubSubEventBus"""

    def test_subscribe_and_publish(self):
        """Test subscribing and publishing events"""
        bus = PubSubEventBus()
        received = []

        class TestHandler:
            def handle(self, event, state):
                received.append((event, state.workflow_id))

        handler = TestHandler()
        state = WorkflowState(workflow_id="test-123", status=WorkflowStatus.RUNNING)
        bus.subscribe(WorkflowEvent.START, handler)
        bus.publish(WorkflowEvent.START, state)
        assert len(received) == 1
        assert received[0][0] == WorkflowEvent.START
        assert received[0][1] == "test-123"

    def test_unsubscribe(self):
        """Test unsubscribing from events"""
        bus = PubSubEventBus()
        received = []

        class TestHandler:
            def handle(self, event, state):
                received.append(event)

        handler = TestHandler()
        bus.subscribe(WorkflowEvent.START, handler)
        bus.unsubscribe(WorkflowEvent.START, handler)
        state = WorkflowState(workflow_id="test", status=WorkflowStatus.RUNNING)
        bus.publish(WorkflowEvent.START, state)
        assert len(received) == 0

    def test_workflow_specific_subscription(self):
        """Test workflow-specific subscriptions"""
        bus = PubSubEventBus()
        received = []

        class TestHandler:
            def handle(self, event, state):
                received.append(state.workflow_id)

        handler = TestHandler()
        state1 = WorkflowState(workflow_id="wf1", status=WorkflowStatus.RUNNING)
        state2 = WorkflowState(workflow_id="wf2", status=WorkflowStatus.RUNNING)

        bus.subscribe(WorkflowEvent.START, handler, workflow_id="wf1")
        bus.publish(WorkflowEvent.START, state1)
        bus.publish(WorkflowEvent.START, state2)

        assert len(received) == 1
        assert received[0] == "wf1"


class TestWorkflowExecutor:
    """Tests for WorkflowExecutor"""

    def test_create_workflow(self):
        """Test creating a workflow"""
        executor = WorkflowExecutor(state_store=MemoryStateStore())
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        state = executor.create_workflow("wf-123", config)
        assert state.workflow_id == "wf-123"
        assert state.status == WorkflowStatus.CREATED

    def test_execute_workflow_success(self):
        """Test successful workflow execution"""
        executor = WorkflowExecutor(state_store=MemoryStateStore())
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        executor.create_workflow("wf-123", config)

        steps_executed = []

        def step1(ctx):
            steps_executed.append("step1")

        def step2(ctx):
            steps_executed.append("step2")

        context = executor.execute_workflow(
            "wf-123",
            config,
            step_handlers={"step1": step1, "step2": step2},
        )

        assert len(steps_executed) == 2
        assert context.state.status == WorkflowStatus.COMPLETED

    def test_execute_workflow_not_found(self):
        """Test executing nonexistent workflow"""
        executor = WorkflowExecutor(state_store=MemoryStateStore())
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        with pytest.raises(ValueError, match="Workflow not found"):
            executor.execute_workflow("nonexistent", config)

    def test_pause_workflow(self):
        """Test pausing a workflow"""
        executor = WorkflowExecutor(state_store=MemoryStateStore())
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        executor.create_workflow("wf-123", config)
        executor.transition("wf-123", WorkflowEvent.START)
        state = executor.pause_workflow("wf-123")
        assert state.status == WorkflowStatus.PAUSED

    def test_cancel_workflow(self):
        """Test cancelling a workflow"""
        executor = WorkflowExecutor(state_store=MemoryStateStore())
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        executor.create_workflow("wf-123", config)
        executor.transition("wf-123", WorkflowEvent.START)
        state = executor.cancel_workflow("wf-123")
        assert state.status == WorkflowStatus.CANCELLED

    def test_retry_workflow(self):
        """Test retrying a failed workflow"""
        executor = WorkflowExecutor(state_store=MemoryStateStore())
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        executor.create_workflow("wf-123", config)
        executor.transition("wf-123", WorkflowEvent.START)
        executor.transition("wf-123", WorkflowEvent.FAIL)
        state = executor.retry_workflow("wf-123")
        assert state.status == WorkflowStatus.CREATED
        assert state.retry_count == 1


class TestWorkflowRunner:
    """Tests for WorkflowRunner"""

    def test_load_workflow(self):
        """Test loading a workflow"""
        runner = WorkflowRunner()
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        workflow_id = runner.load_workflow(config)
        assert workflow_id is not None
        assert len(workflow_id) == 36

    def test_execute_workflow(self):
        """Test executing a loaded workflow"""
        runner = WorkflowRunner()
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        workflow_id = runner.load_workflow(config)

        executed = []

        def my_step(ctx):
            executed.append(True)

        context = runner.execute(workflow_id, {"my_step": my_step})
        assert len(executed) == 1
        assert context.state.status == WorkflowStatus.COMPLETED

    def test_pause_and_resume(self):
        """Test pausing a workflow in running state"""
        runner = WorkflowRunner()
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        workflow_id = runner.load_workflow(config)
        state = runner.get_state(workflow_id)
        assert state.status == WorkflowStatus.CREATED
        runner._executor.transition(workflow_id, WorkflowEvent.START)
        state = runner.pause(workflow_id)
        assert state.status == WorkflowStatus.PAUSED

    def test_cancel(self):
        """Test cancelling a workflow"""
        runner = WorkflowRunner()
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        workflow_id = runner.load_workflow(config)
        runner.cancel(workflow_id)
        state = runner.get_state(workflow_id)
        assert state.status == WorkflowStatus.CANCELLED

    def test_list_workflows(self):
        """Test listing loaded workflows"""
        runner = WorkflowRunner()
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        runner.load_workflow(config)
        runner.load_workflow(config)
        workflows = runner.list_workflows()
        assert len(workflows) == 2

    def test_unload_workflow(self):
        """Test unloading a workflow"""
        runner = WorkflowRunner()
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        workflow_id = runner.load_workflow(config)
        assert runner.unload_workflow(workflow_id) is True
        assert runner.unload_workflow(workflow_id) is False


class TestMetricsCollector:
    """Tests for MetricsCollector"""

    def test_increment(self):
        """Test incrementing a counter"""
        collector = MetricsCollector()
        collector.increment("test_counter", 5)
        assert collector.get_counter("test_counter") == 5

    def test_gauge(self):
        """Test setting a gauge"""
        collector = MetricsCollector()
        collector.gauge("test_gauge", 42.5)
        assert collector.get_gauge("test_gauge") == 42.5

    def test_timing(self):
        """Test recording timing"""
        collector = MetricsCollector()
        collector.timing("test_timer", 100.0)
        collector.timing("test_timer", 200.0)
        stats = collector.get_timer_stats("test_timer")
        assert stats["count"] == 2
        assert stats["min"] == 100.0
        assert stats["max"] == 200.0

    def test_get_metrics_with_filter(self):
        """Test getting metrics with filters"""
        collector = MetricsCollector()
        collector.increment("test_metric", tags={"workflow_id": "wf1"})
        collector.increment("test_metric", tags={"workflow_id": "wf2"})

        metrics = collector.get_metrics(name="test_metric", workflow_id="wf1")
        assert len(metrics) == 1
        assert metrics[0].tags["workflow_id"] == "wf1"

    def test_clear(self):
        """Test clearing metrics"""
        collector = MetricsCollector()
        collector.increment("test_metric")
        collector.gauge("test_gauge", 10)
        collector.clear()
        assert collector.get_counter("test_metric") == 0
        assert collector.get_gauge("test_gauge") == 0


class TestWorkflowMonitor:
    """Tests for WorkflowMonitor"""

    def test_track_workflow(self):
        """Test tracking a workflow"""
        monitor = WorkflowMonitor()
        state = WorkflowState(workflow_id="wf-123", status=WorkflowStatus.RUNNING)
        monitor.track_workflow("wf-123", state)
        tracked = monitor.get_tracked_workflows()
        assert "wf-123" in tracked

    def test_get_metrics(self):
        """Test getting workflow metrics"""
        monitor = WorkflowMonitor()
        state = WorkflowState(
            workflow_id="wf-123",
            status=WorkflowStatus.RUNNING,
            total_steps=10,
            completed_steps=5,
        )
        monitor.track_workflow("wf-123", state)
        metrics = monitor.get_metrics("wf-123")
        assert metrics is not None
        assert metrics.steps_completed == 5
        assert metrics.steps_total == 10

    def test_log_messages(self):
        """Test logging messages"""
        monitor = WorkflowMonitor()
        monitor.track_workflow("wf-123")
        monitor.log_info("wf-123", "Test info message")
        monitor.log_error("wf-123", "Test error message")
        logs = monitor.get_logs("wf-123")
        # 3 条：track_workflow 的 "Workflow tracking started" + INFO + ERROR
        assert len(logs) == 3
        levels = [l.level for l in logs]
        assert "INFO" in levels
        assert "ERROR" in levels

    def test_get_logs_with_limit(self):
        """Test getting logs with limit"""
        monitor = WorkflowMonitor()
        monitor.track_workflow("wf-123")
        for i in range(10):
            monitor.log_info("wf-123", f"Message {i}")
        logs = monitor.get_logs("wf-123", last_n=5)
        assert len(logs) == 5

    def test_stop_tracking(self):
        """Test stopping workflow tracking"""
        monitor = WorkflowMonitor()
        monitor.track_workflow("wf-123")
        monitor.stop_tracking("wf-123")
        assert "wf-123" not in monitor.get_tracked_workflows()


class TestLogEntry:
    """Tests for LogEntry"""

    def test_log_entry_creation(self):
        """Test creating a log entry"""
        entry = LogEntry(
            workflow_id="wf-123",
            timestamp=datetime.now(timezone.utc),
            level="INFO",
            message="Test message",
            step="step1",
            metadata={"key": "value"},
        )
        assert entry.workflow_id == "wf-123"
        assert entry.level == "INFO"
        assert entry.step == "step1"

    def test_log_entry_to_dict(self):
        """Test converting log entry to dict"""
        entry = LogEntry(
            workflow_id="wf-123",
            timestamp=datetime.now(timezone.utc),
            level="ERROR",
            message="Error occurred",
        )
        data = entry.to_dict()
        assert data["workflow_id"] == "wf-123"
        assert data["level"] == "ERROR"
        assert data["message"] == "Error occurred"

    def test_log_entry_from_dict(self):
        """Test creating log entry from dict"""
        data = {
            "workflow_id": "wf-123",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "level": "WARNING",
            "message": "Warning message",
        }
        entry = LogEntry.from_dict(data)
        assert entry.workflow_id == "wf-123"
        assert entry.level == "WARNING"


class TestExecutionContext:
    """Tests for ExecutionContext"""

    def test_execution_context_creation(self):
        """Test creating execution context"""
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        state = WorkflowState(workflow_id="wf-123", status=WorkflowStatus.RUNNING)
        context = ExecutionContext(
            workflow_id="wf-123",
            config=config,
            state=state,
        )
        assert context.workflow_id == "wf-123"
        assert len(context.logs) == 0
        assert len(context.step_outputs) == 0

    def test_add_log(self):
        """Test adding log entries"""
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        state = WorkflowState(workflow_id="wf-123", status=WorkflowStatus.RUNNING)
        context = ExecutionContext(
            workflow_id="wf-123",
            config=config,
            state=state,
        )
        context.add_log("INFO", "Test message", key="value")
        assert len(context.logs) == 1
        assert context.logs[0]["level"] == "INFO"
        assert context.logs[0]["message"] == "Test message"

    def test_add_metric(self):
        """Test adding metrics"""
        config = LocalWorkflowConfig(
            workflowConfig=WorkflowConfig(pipelineName="test"),
            source={"type": "mysql"},
            sink={"type": "file"},
        )
        state = WorkflowState(workflow_id="wf-123", status=WorkflowStatus.RUNNING)
        context = ExecutionContext(
            workflow_id="wf-123",
            config=config,
            state=state,
        )
        context.add_metric("rows_processed", 100)
        assert context.metrics["rows_processed"] == 100


class TestWorkflowScheduler:
    """Tests for WorkflowScheduler"""

    def test_scheduler_not_available_without_apscheduler(self):
        """Test that scheduler requires APScheduler"""
        with patch("local_ingestion.core.engine.scheduler.APSCHEDULER_AVAILABLE", False):
            with pytest.raises(ImportError, match="APScheduler is required"):
                WorkflowScheduler()

    def test_schedule_creation(self):
        """Test creating a schedule"""
        schedule = Schedule(
            schedule_id="sched-123",
            workflow_id="wf-123",
            trigger_type=TriggerType.INTERVAL,
            trigger_args={"minutes": 5},
        )
        assert schedule.schedule_id == "sched-123"
        assert schedule.trigger_type == TriggerType.INTERVAL
        assert schedule.enabled is True

    def test_schedule_to_dict(self):
        """Test converting schedule to dict"""
        schedule = Schedule(
            schedule_id="sched-123",
            workflow_id="wf-123",
            trigger_type=TriggerType.CRON,
            trigger_args={"hour": 9, "minute": 0},
        )
        data = schedule.to_dict()
        assert data["schedule_id"] == "sched-123"
        assert data["trigger_type"] == "cron"
        assert data["trigger_args"]["hour"] == 9


class TestWorkflowExecutionError:
    """Tests for WorkflowExecutionError"""

    def test_error_creation(self):
        """Test creating execution error"""
        cause = ValueError("Original error")
        error = WorkflowExecutionError("wf-123", "Execution failed", cause=cause)
        assert error.workflow_id == "wf-123"
        assert error.cause is cause
        assert "Execution failed" in str(error)
