"""Workflow State Management"""

from __future__ import annotations

import json
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WorkflowStatus(str, Enum):
    """Workflow status enumeration"""

    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PENDING = "pending"


class WorkflowEvent(str, Enum):
    """Workflow event enumeration"""

    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    COMPLETE = "complete"
    FAIL = "fail"
    CANCEL = "cancel"
    RETRY = "retry"
    TIMEOUT = "timeout"


@dataclass
class WorkflowState:
    """Workflow state representation"""

    workflow_id: str
    status: WorkflowStatus
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_step: Optional[str] = None
    total_steps: int = 0
    completed_steps: int = 0
    error_message: Optional[str] = None
    retry_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary"""
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowState":
        """Create state from dictionary"""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = datetime.now(timezone.utc)

        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at)

        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at)

        return cls(
            workflow_id=data["workflow_id"],
            status=WorkflowStatus(data["status"]),
            created_at=created_at,
            updated_at=updated_at,
            started_at=started_at,
            completed_at=completed_at,
            current_step=data.get("current_step"),
            total_steps=data.get("total_steps", 0),
            completed_steps=data.get("completed_steps", 0),
            error_message=data.get("error_message"),
            retry_count=data.get("retry_count", 0),
            metadata=data.get("metadata", {}),
        )

    def update_status(self, status: WorkflowStatus) -> None:
        """Update workflow status"""
        self.status = status
        self.updated_at = datetime.now(timezone.utc)

        if status == WorkflowStatus.RUNNING and self.started_at is None:
            self.started_at = datetime.now(timezone.utc)
        elif status in (
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        ):
            self.completed_at = datetime.now(timezone.utc)

    def progress(self) -> float:
        """Calculate progress percentage"""
        if self.total_steps == 0:
            return 0.0
        return (self.completed_steps / self.total_steps) * 100


class StateStore(ABC):
    """Abstract state store interface"""

    @abstractmethod
    def save(self, state: WorkflowState) -> None:
        """Save workflow state"""
        raise NotImplementedError

    @abstractmethod
    def load(self, workflow_id: str) -> Optional[WorkflowState]:
        """Load workflow state"""
        raise NotImplementedError

    @abstractmethod
    def delete(self, workflow_id: str) -> bool:
        """Delete workflow state"""
        raise NotImplementedError

    @abstractmethod
    def list_all(self) -> List[WorkflowState]:
        """List all workflow states"""
        raise NotImplementedError


class FileStateStore(StateStore):
    """File-based state store implementation"""

    def __init__(self, storage_path: str = ".workflow_state"):
        self._storage_path = Path(storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _get_file_path(self, workflow_id: str) -> Path:
        """Get file path for workflow state"""
        return self._storage_path / f"{workflow_id}.json"

    def save(self, state: WorkflowState) -> None:
        """Save workflow state to file"""
        with self._lock:
            file_path = self._get_file_path(state.workflow_id)
            data = state.to_dict()
            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug("Saved state for workflow: %s", state.workflow_id)

    def load(self, workflow_id: str) -> Optional[WorkflowState]:
        """Load workflow state from file"""
        with self._lock:
            file_path = self._get_file_path(workflow_id)
            if not file_path.exists():
                return None

            try:
                with open(file_path) as f:
                    data = json.load(f)
                return WorkflowState.from_dict(data)
            except (json.JSONDecodeError, KeyError) as e:
                logger.error("Failed to load state for workflow %s: %s", workflow_id, e)
                return None

    def delete(self, workflow_id: str) -> bool:
        """Delete workflow state file"""
        with self._lock:
            file_path = self._get_file_path(workflow_id)
            if file_path.exists():
                file_path.unlink()
                logger.debug("Deleted state for workflow: %s", workflow_id)
                return True
            return False

    def list_all(self) -> List[WorkflowState]:
        """List all workflow states from files"""
        with self._lock:
            states = []
            for file_path in self._storage_path.glob("*.json"):
                try:
                    with open(file_path) as f:
                        data = json.load(f)
                    states.append(WorkflowState.from_dict(data))
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Failed to load state file %s: %s", file_path, e)
            return states


class MemoryStateStore(StateStore):
    """In-memory state store for testing"""

    def __init__(self):
        self._store: Dict[str, WorkflowState] = {}
        self._lock = threading.RLock()

    def save(self, state: WorkflowState) -> None:
        """Save workflow state to memory"""
        with self._lock:
            self._store[state.workflow_id] = state

    def load(self, workflow_id: str) -> Optional[WorkflowState]:
        """Load workflow state from memory"""
        with self._lock:
            return self._store.get(workflow_id)

    def delete(self, workflow_id: str) -> bool:
        """Delete workflow state from memory"""
        with self._lock:
            if workflow_id in self._store:
                del self._store[workflow_id]
                return True
            return False

    def list_all(self) -> List[WorkflowState]:
        """List all workflow states from memory"""
        with self._lock:
            return list(self._store.values())

    def clear(self) -> None:
        """Clear all states"""
        with self._lock:
            self._store.clear()


class StateTransitionError(Exception):
    """Exception raised for invalid state transitions"""

    def __init__(self, current_status: WorkflowStatus, event: WorkflowEvent):
        self.current_status = current_status
        self.event = event
        super().__init__(
            f"Invalid transition: {event.value} from {current_status.value}"
        )


class StateMachine:
    """State machine for workflow state transitions"""

    VALID_TRANSITIONS: Dict[WorkflowStatus, Dict[WorkflowEvent, WorkflowStatus]] = {
        WorkflowStatus.CREATED: {
            WorkflowEvent.START: WorkflowStatus.RUNNING,
            WorkflowEvent.CANCEL: WorkflowStatus.CANCELLED,
        },
        WorkflowStatus.RUNNING: {
            WorkflowEvent.PAUSE: WorkflowStatus.PAUSED,
            WorkflowEvent.COMPLETE: WorkflowStatus.COMPLETED,
            WorkflowEvent.FAIL: WorkflowStatus.FAILED,
            WorkflowEvent.CANCEL: WorkflowStatus.CANCELLED,
            WorkflowEvent.RETRY: WorkflowStatus.RUNNING,
            WorkflowEvent.TIMEOUT: WorkflowStatus.FAILED,
        },
        WorkflowStatus.PAUSED: {
            WorkflowEvent.RESUME: WorkflowStatus.RUNNING,
            WorkflowEvent.CANCEL: WorkflowStatus.CANCELLED,
        },
        WorkflowStatus.PENDING: {
            WorkflowEvent.START: WorkflowStatus.RUNNING,
            WorkflowEvent.CANCEL: WorkflowStatus.CANCELLED,
        },
    }

    @classmethod
    def can_transition(cls, current: WorkflowStatus, event: WorkflowEvent) -> bool:
        """Check if transition is valid"""
        transitions = cls.VALID_TRANSITIONS.get(current, {})
        return event in transitions

    @classmethod
    def get_next_status(
        cls, current: WorkflowStatus, event: WorkflowEvent
    ) -> WorkflowStatus:
        """Get next status for event"""
        if not cls.can_transition(current, event):
            raise StateTransitionError(current, event)
        return cls.VALID_TRANSITIONS[current][event]
