"""Workflow Runner and Executor"""

from __future__ import annotations

import logging
import threading
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from local_ingestion.core.engine.state import (
    WorkflowState,
    WorkflowEvent,
    WorkflowStatus,
    StateMachine,
    StateStore,
    StateTransitionError,
    MemoryStateStore,
)
from local_ingestion.schema.metadata.workflow import LocalWorkflowConfig

logger = logging.getLogger(__name__)


class WorkflowExecutionError(Exception):
    """Exception raised during workflow execution"""

    def __init__(self, workflow_id: str, message: str, cause: Optional[Exception] = None):
        self.workflow_id = workflow_id
        self.cause = cause
        super().__init__(message)


@dataclass
class ExecutionContext:
    """Execution context for a workflow run"""

    workflow_id: str
    config: LocalWorkflowConfig
    state: WorkflowState
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    logs: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    step_outputs: Dict[str, Any] = field(default_factory=dict)

    def add_log(self, level: str, message: str, **kwargs) -> None:
        """Add a log entry"""
        self.logs.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "message": message,
                **kwargs,
            }
        )

    def add_metric(self, name: str, value: Any) -> None:
        """Add a metric"""
        self.metrics[name] = value


class EventHandler(ABC):
    """Abstract event handler for workflow events"""

    @abstractmethod
    def handle(self, event: WorkflowEvent, state: WorkflowState) -> None:
        """Handle a workflow event"""
        raise NotImplementedError


class LoggingEventHandler(EventHandler):
    """Event handler that logs events"""

    def handle(self, event: WorkflowEvent, state: WorkflowState) -> None:
        """Log the event"""
        logger.info(
            "Workflow event: %s for workflow %s (status: %s)",
            event.value,
            state.workflow_id,
            state.status.value,
        )


class PubSubEventBus:
    """Pub/sub event bus for workflow events"""

    def __init__(self):
        self._subscribers: Dict[WorkflowEvent, List[EventHandler]] = defaultdict(list)
        self._workflow_subscribers: Dict[
            str, Dict[WorkflowEvent, List[EventHandler]]
        ] = defaultdict(lambda: defaultdict(list))
        self._lock = threading.RLock()

    def subscribe(
        self,
        event: WorkflowEvent,
        handler: EventHandler,
        workflow_id: Optional[str] = None,
    ) -> None:
        """Subscribe to an event"""
        with self._lock:
            if workflow_id:
                self._workflow_subscribers[workflow_id][event].append(handler)
            else:
                self._subscribers[event].append(handler)

    def unsubscribe(
        self,
        event: WorkflowEvent,
        handler: EventHandler,
        workflow_id: Optional[str] = None,
    ) -> None:
        """Unsubscribe from an event"""
        with self._lock:
            if workflow_id:
                handlers = self._workflow_subscribers.get(workflow_id, {}).get(event, [])
                if handler in handlers:
                    handlers.remove(handler)
            else:
                if handler in self._subscribers[event]:
                    self._subscribers[event].remove(handler)

    def publish(self, event: WorkflowEvent, state: WorkflowState) -> None:
        """Publish an event to all subscribers"""
        with self._lock:
            for handler in self._subscribers[event]:
                try:
                    handler.handle(event, state)
                except Exception as e:
                    logger.error("Error in event handler: %s", e)

            workflow_id = state.workflow_id
            if workflow_id in self._workflow_subscribers:
                for handler in self._workflow_subscribers[workflow_id][event]:
                    try:
                        handler.handle(event, state)
                    except Exception as e:
                        logger.error(
                            "Error in workflow-specific event handler: %s", e
                        )


class WorkflowExecutor:
    """Executes workflow steps with state machine and event handling"""

    def __init__(
        self,
        state_store: Optional[StateStore] = None,
        event_bus: Optional[PubSubEventBus] = None,
    ):
        self._state_store = state_store or MemoryStateStore()
        self._event_bus = event_bus or PubSubEventBus()
        self._running_workflows: Dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._event_bus.subscribe(WorkflowEvent.START, LoggingEventHandler())
        self._event_bus.subscribe(WorkflowEvent.COMPLETE, LoggingEventHandler())
        self._event_bus.subscribe(WorkflowEvent.FAIL, LoggingEventHandler())

    def create_workflow(
        self, workflow_id: str, config: LocalWorkflowConfig
    ) -> WorkflowState:
        """Create a new workflow state"""
        state = WorkflowState(
            workflow_id=workflow_id,
            status=WorkflowStatus.CREATED,
        )
        self._state_store.save(state)
        return state

    def load_workflow(self, workflow_id: str) -> Optional[WorkflowState]:
        """Load workflow state"""
        return self._state_store.load(workflow_id)

    def transition(
        self, workflow_id: str, event: WorkflowEvent
    ) -> WorkflowState:
        """Transition workflow state"""
        state = self._state_store.load(workflow_id)
        if state is None:
            raise ValueError(f"Workflow not found: {workflow_id}")

        try:
            next_status = StateMachine.get_next_status(state.status, event)
            state.update_status(next_status)
            self._state_store.save(state)
            self._event_bus.publish(event, state)
            return state
        except StateTransitionError as e:
            logger.warning(
                "Invalid state transition for workflow %s: %s", workflow_id, e
            )
            raise

    def execute_workflow(
        self,
        workflow_id: str,
        config: LocalWorkflowConfig,
        step_handlers: Optional[Dict[str, Callable]] = None,
    ) -> ExecutionContext:
        """Execute a workflow"""
        state = self._state_store.load(workflow_id)
        if state is None:
            raise ValueError(f"Workflow not found: {workflow_id}")

        if state.status != WorkflowStatus.CREATED:
            raise WorkflowExecutionError(
                workflow_id, f"Workflow is not in CREATED state: {state.status}"
            )

        stop_event = threading.Event()
        self._running_workflows[workflow_id] = stop_event

        context = ExecutionContext(
            workflow_id=workflow_id,
            config=config,
            state=state,
        )

        try:
            self.transition(workflow_id, WorkflowEvent.START)
            state = self._state_store.load(workflow_id)
            context.state = state
            context.add_log("INFO", f"Workflow started: {workflow_id}")

            if step_handlers:
                state.total_steps = len(step_handlers)
                self._state_store.save(state)

                for step_name, handler in step_handlers.items():
                    if stop_event.is_set():
                        context.add_log("WARNING", "Workflow execution paused")
                        break

                    state.current_step = step_name
                    self._state_store.save(state)

                    try:
                        context.add_log("INFO", f"Executing step: {step_name}")
                        result = handler(context)
                        context.step_outputs[step_name] = result
                        state.completed_steps += 1
                        self._state_store.save(state)
                    except Exception as e:
                        context.add_log("ERROR", f"Step {step_name} failed: {e}")
                        state.error_message = str(e)
                        self._state_store.save(state)
                        raise WorkflowExecutionError(
                            workflow_id, f"Step {step_name} failed", cause=e
                        )

            self.transition(workflow_id, WorkflowEvent.COMPLETE)
            state = self._state_store.load(workflow_id)
            context.state = state
            context.add_log("INFO", "Workflow completed successfully")
        except Exception as e:
            context.add_log("ERROR", f"Workflow failed: {e}")
            try:
                self.transition(workflow_id, WorkflowEvent.FAIL)
            except StateTransitionError:
                pass
            state = self._state_store.load(workflow_id)
            context.state = state
            raise
        finally:
            context.ended_at = datetime.now(timezone.utc)
            with self._lock:
                self._running_workflows.pop(workflow_id, None)

        return context

    def pause_workflow(self, workflow_id: str) -> WorkflowState:
        """Pause a running workflow"""
        if workflow_id in self._running_workflows:
            self._running_workflows[workflow_id].set()

        return self.transition(workflow_id, WorkflowEvent.PAUSE)

    def cancel_workflow(self, workflow_id: str) -> WorkflowState:
        """Cancel a workflow"""
        if workflow_id in self._running_workflows:
            self._running_workflows[workflow_id].set()

        return self.transition(workflow_id, WorkflowEvent.CANCEL)

    def retry_workflow(self, workflow_id: str) -> WorkflowState:
        """Retry a failed workflow"""
        state = self._state_store.load(workflow_id)
        if state is None:
            raise ValueError(f"Workflow not found: {workflow_id}")

        if state.status not in (WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
            raise WorkflowExecutionError(
                workflow_id,
                f"Cannot retry workflow in {state.status} state",
            )

        state.retry_count += 1
        state.status = WorkflowStatus.CREATED
        state.error_message = None
        self._state_store.save(state)
        self._event_bus.publish(WorkflowEvent.RETRY, state)
        return state


class WorkflowRunner:
    """High-level workflow runner with configuration management"""

    def __init__(
        self,
        executor: Optional[WorkflowExecutor] = None,
        state_store: Optional[StateStore] = None,
    ):
        self._executor = executor or WorkflowExecutor(state_store=state_store)
        self._workflows: Dict[str, LocalWorkflowConfig] = {}
        self._lock = threading.RLock()

    def load_workflow(self, config: LocalWorkflowConfig) -> str:
        """Load a workflow from configuration"""
        workflow_id = str(uuid.uuid4())
        with self._lock:
            self._workflows[workflow_id] = config

        self._executor.create_workflow(workflow_id, config)
        logger.info("Loaded workflow: %s", workflow_id)
        return workflow_id

    def execute(
        self,
        workflow_id: str,
        step_handlers: Optional[Dict[str, Callable]] = None,
    ) -> ExecutionContext:
        """Execute a loaded workflow"""
        with self._lock:
            config = self._workflows.get(workflow_id)
            if config is None:
                raise ValueError(f"Workflow not found: {workflow_id}")

        logger.info("Executing workflow: %s", workflow_id)
        return self._executor.execute_workflow(workflow_id, config, step_handlers)

    def pause(self, workflow_id: str) -> WorkflowState:
        """Pause a running workflow"""
        logger.info("Pausing workflow: %s", workflow_id)
        return self._executor.pause_workflow(workflow_id)

    def resume(
        self,
        workflow_id: str,
        step_handlers: Optional[Dict[str, Callable]] = None,
    ) -> ExecutionContext:
        """Resume a paused workflow"""
        with self._lock:
            config = self._workflows.get(workflow_id)
            if config is None:
                raise ValueError(f"Workflow not found: {workflow_id}")

        state = self._executor.transition(workflow_id, WorkflowEvent.RESUME)
        if state.status != WorkflowStatus.RUNNING:
            raise WorkflowExecutionError(
                workflow_id, f"Cannot resume workflow in {state.status} state"
            )

        logger.info("Resuming workflow: %s", workflow_id)
        return self._executor.execute_workflow(workflow_id, config, step_handlers)

    def cancel(self, workflow_id: str) -> WorkflowState:
        """Cancel a workflow"""
        logger.info("Cancelling workflow: %s", workflow_id)
        return self._executor.cancel_workflow(workflow_id)

    def get_state(self, workflow_id: str) -> Optional[WorkflowState]:
        """Get current workflow state"""
        return self._executor.load_workflow(workflow_id)

    def list_workflows(self) -> List[str]:
        """List all loaded workflow IDs"""
        with self._lock:
            return list(self._workflows.keys())

    def unload_workflow(self, workflow_id: str) -> bool:
        """Unload a workflow from memory"""
        with self._lock:
            if workflow_id in self._workflows:
                del self._workflows[workflow_id]
                return True
            return False
