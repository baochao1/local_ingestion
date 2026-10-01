"""Workflow Scheduler using APScheduler"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.events import (
        EVENT_JOB_EXECUTED,
        EVENT_JOB_ERROR,
        EVENT_JOB_MISSED,
        EVENT_JOB_SUBMITTED,
    )

    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False

from local_ingestion.schema.metadata.workflow import LocalWorkflowConfig

logger = logging.getLogger(__name__)


class TriggerType(str, Enum):
    """Trigger type enumeration"""

    INTERVAL = "interval"
    CRON = "cron"
    DATE = "date"


@dataclass
class Schedule:
    """Workflow schedule representation"""

    schedule_id: str
    workflow_id: str
    trigger_type: TriggerType
    trigger_args: Dict[str, Any]
    next_run_time: Optional[datetime] = None
    last_run_time: Optional[datetime] = None
    enabled: bool = True
    max_instances: int = 1
    misfire_grace_time: int = 60

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "schedule_id": self.schedule_id,
            "workflow_id": self.workflow_id,
            "trigger_type": self.trigger_type.value,
            "trigger_args": self.trigger_args,
            "next_run_time": self.next_run_time.isoformat() if self.next_run_time else None,
            "last_run_time": self.last_run_time.isoformat() if self.last_run_time else None,
            "enabled": self.enabled,
            "max_instances": self.max_instances,
            "misfire_grace_time": self.misfire_grace_time,
        }


class WorkflowScheduler:
    """Scheduler for workflow execution using APScheduler"""

    def __init__(self, executor: Optional[Any] = None):
        if not APSCHEDULER_AVAILABLE:
            raise ImportError(
                "APScheduler is required for scheduling. Install with: pip install apscheduler"
            )

        self._scheduler = BackgroundScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 3,
                "misfire_grace_time": 60,
            }
        )
        self._executor = executor
        self._schedules: Dict[str, Schedule] = {}
        self._workflow_callbacks: Dict[str, Callable] = {}
        self._lock = threading.RLock()
        self._setup_listeners()
        self._running = False

    def _setup_listeners(self) -> None:
        """Setup scheduler event listeners"""
        self._scheduler.add_listener(
            self._on_job_executed, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )
        self._scheduler.add_listener(
            self._on_job_missed, EVENT_JOB_MISSED
        )
        self._scheduler.add_listener(
            self._on_job_submitted, EVENT_JOB_SUBMITTED
        )

    def _on_job_executed(self, event) -> None:
        """Handle job executed event"""
        schedule_id = event.job_id
        with self._lock:
            if schedule_id in self._schedules:
                self._schedules[schedule_id].last_run_time = datetime.now(timezone.utc)

        if event.exception:
            logger.error("Job %s failed with exception: %s", schedule_id, event.exception)
        else:
            logger.info("Job %s completed successfully", schedule_id)

    def _on_job_missed(self, event) -> None:
        """Handle job missed event"""
        logger.warning("Job %s was missed", event.job_id)

    def _on_job_submitted(self, event) -> None:
        """Handle job submitted event"""
        logger.debug("Job %s submitted for execution", event.job_id)

    def _create_trigger(
        self, trigger_type: TriggerType, trigger_args: Dict[str, Any]
    ):
        """Create APScheduler trigger from config"""
        if trigger_type == TriggerType.INTERVAL:
            return IntervalTrigger(
                weeks=trigger_args.get("weeks", 0),
                days=trigger_args.get("days", 0),
                hours=trigger_args.get("hours", 0),
                minutes=trigger_args.get("minutes", 0),
                seconds=trigger_args.get("seconds", 0),
                start_date=trigger_args.get("start_date"),
                end_date=trigger_args.get("end_date"),
            )
        elif trigger_type == TriggerType.CRON:
            return CronTrigger(
                year=trigger_args.get("year"),
                month=trigger_args.get("month"),
                day=trigger_args.get("day"),
                week=trigger_args.get("week"),
                day_of_week=trigger_args.get("day_of_week"),
                hour=trigger_args.get("hour"),
                minute=trigger_args.get("minute"),
                second=trigger_args.get("second"),
                start_date=trigger_args.get("start_date"),
                end_date=trigger_args.get("end_date"),
                timezone=trigger_args.get("timezone"),
            )
        else:
            raise ValueError(f"Unsupported trigger type: {trigger_type}")

    def schedule(
        self,
        workflow_id: str,
        trigger_type: TriggerType,
        trigger_args: Dict[str, Any],
        workflow_callback: Callable,
        schedule_id: Optional[str] = None,
        max_instances: int = 1,
        misfire_grace_time: int = 60,
    ) -> Schedule:
        """Schedule a workflow for execution"""
        import uuid

        if schedule_id is None:
            schedule_id = str(uuid.uuid4())

        schedule = Schedule(
            schedule_id=schedule_id,
            workflow_id=workflow_id,
            trigger_type=trigger_type,
            trigger_args=trigger_args,
            max_instances=max_instances,
            misfire_grace_time=misfire_grace_time,
        )

        trigger = self._create_trigger(trigger_type, trigger_args)

        def job_wrapper():
            callback = self._workflow_callbacks.get(schedule_id)
            if callback:
                try:
                    callback(workflow_id)
                except Exception as e:
                    logger.error("Error in scheduled job %s: %s", schedule_id, e)
                    raise

        job = self._scheduler.add_job(
            job_wrapper,
            trigger=trigger,
            id=schedule_id,
            name=f"workflow-{workflow_id}",
            replace_existing=True,
            max_instances=max_instances,
            misfire_grace_time=misfire_grace_time,
        )

        schedule.next_run_time = job.next_run_time

        with self._lock:
            self._schedules[schedule_id] = schedule
            self._workflow_callbacks[schedule_id] = workflow_callback

        logger.info(
            "Scheduled workflow %s with schedule %s, next run: %s",
            workflow_id,
            schedule_id,
            job.next_run_time,
        )

        return schedule

    def unschedule(self, schedule_id: str) -> bool:
        """Remove a schedule"""
        with self._lock:
            if schedule_id in self._schedules:
                self._scheduler.remove_job(schedule_id)
                del self._schedules[schedule_id]
                self._workflow_callbacks.pop(schedule_id, None)
                logger.info("Unscheduled workflow: %s", schedule_id)
                return True
            return False

    def unschedule_workflow(self, workflow_id: str) -> List[str]:
        """Remove all schedules for a workflow"""
        removed = []
        with self._lock:
            for schedule_id, schedule in list(self._schedules.items()):
                if schedule.workflow_id == workflow_id:
                    self._scheduler.remove_job(schedule_id)
                    removed.append(schedule_id)

            for schedule_id in removed:
                del self._schedules[schedule_id]
                self._workflow_callbacks.pop(schedule_id, None)

        if removed:
            logger.info(
                "Unscheduled %d schedules for workflow: %s",
                len(removed),
                workflow_id,
            )

        return removed

    def pause_schedule(self, schedule_id: str) -> bool:
        """Pause a schedule"""
        try:
            self._scheduler.pause_job(schedule_id)
            with self._lock:
                if schedule_id in self._schedules:
                    self._schedules[schedule_id].enabled = False
            logger.info("Paused schedule: %s", schedule_id)
            return True
        except Exception as e:
            logger.error("Failed to pause schedule %s: %s", schedule_id, e)
            return False

    def resume_schedule(self, schedule_id: str) -> bool:
        """Resume a paused schedule"""
        try:
            self._scheduler.resume_job(schedule_id)
            with self._lock:
                if schedule_id in self._schedules:
                    self._schedules[schedule_id].enabled = True
            logger.info("Resumed schedule: %s", schedule_id)
            return True
        except Exception as e:
            logger.error("Failed to resume schedule %s: %s", schedule_id, e)
            return False

    def get_schedule(self, schedule_id: str) -> Optional[Schedule]:
        """Get a schedule by ID"""
        with self._lock:
            return self._schedules.get(schedule_id)

    def list_schedules(
        self,
        workflow_id: Optional[str] = None,
        enabled_only: bool = False,
    ) -> List[Schedule]:
        """List all schedules"""
        with self._lock:
            schedules = list(self._schedules.values())

        if workflow_id:
            schedules = [s for s in schedules if s.workflow_id == workflow_id]

        if enabled_only:
            schedules = [s for s in schedules if s.enabled]

        return schedules

    def get_next_run(self, schedule_id: str) -> Optional[datetime]:
        """Get next run time for a schedule"""
        try:
            job = self._scheduler.get_job(schedule_id)
            if job:
                return job.next_run_time
        except Exception as e:
            logger.error("Failed to get next run for %s: %s", schedule_id, e)

        with self._lock:
            schedule = self._schedules.get(schedule_id)
            if schedule:
                return schedule.next_run_time

        return None

    def get_next_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get next run times for all jobs"""
        jobs = self._scheduler.get_jobs()
        results = []

        for job in jobs[:limit]:
            schedule_id = job.id
            with self._lock:
                schedule = self._schedules.get(schedule_id)

            results.append(
                {
                    "schedule_id": schedule_id,
                    "workflow_id": schedule.workflow_id if schedule else None,
                    "next_run_time": job.next_run_time,
                    "enabled": schedule.enabled if schedule else True,
                }
            )

        return results

    def start(self) -> None:
        """Start the scheduler"""
        if not self._running:
            self._scheduler.start()
            self._running = True
            logger.info("Workflow scheduler started")

    def stop(self, wait: bool = True) -> None:
        """Stop the scheduler"""
        if self._running:
            self._scheduler.shutdown(wait=wait)
            self._running = False
            logger.info("Workflow scheduler stopped")

    def is_running(self) -> bool:
        """Check if scheduler is running"""
        return self._running

    def run_now(self, schedule_id: str) -> bool:
        """Trigger immediate execution of a scheduled job"""
        try:
            job = self._scheduler.get_job(schedule_id)
            if job:
                job.modify(next_run_time=datetime.now(timezone.utc))
                logger.info("Triggered immediate run for schedule: %s", schedule_id)
                return True
            return False
        except Exception as e:
            logger.error("Failed to trigger immediate run for %s: %s", schedule_id, e)
            return False
