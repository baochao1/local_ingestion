"""Periodic metadata scanning.

Runs :meth:`ScanService.run_scan` for every scan-enabled datasource from an
APScheduler background thread — one interval job per datasource, so a per-source
cadence (``scan_config.interval_minutes``) is possible without a workflow.

Two safety properties matter here:

* ``max_instances=1`` + ``coalesce=True`` — a scan that takes longer than its
  interval never overlaps itself, and missed runs collapse into one.
* Failures are logged, never raised — a broken datasource must not kill the
  scheduler thread (and therefore all other datasources' scans).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import structlog

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger

    APSCHEDULER_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the optional extra
    APSCHEDULER_AVAILABLE = False

logger = structlog.get_logger()

DEFAULT_INTERVAL_MINUTES = 60
#: ``scan_config`` key that overrides the global cadence per datasource.
INTERVAL_CONFIG_KEY = "interval_minutes"


@dataclass
class ScanJob:
    """One scheduled datasource and its cadence."""

    datasource_id: int
    datasource_code: str
    interval_minutes: int
    next_run_time: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "datasource_id": self.datasource_id,
            "datasource_code": self.datasource_code,
            "interval_minutes": self.interval_minutes,
            "next_run_time": self.next_run_time,
        }


class ScanScheduler:
    """Schedule recurring scans for scan-enabled datasources.

    Args:
        session_factory: Platform DB session factory (also used to construct the
            :class:`ScanService` per run, so each run gets a fresh session).
        scan_service_factory: Overridable for tests; defaults to building a
            :class:`ScanService` on ``session_factory``.
        default_interval_minutes: Cadence used when a datasource does not carry
            its own ``scan_config.interval_minutes``.
    """

    def __init__(
        self,
        session_factory: Callable,
        scan_service_factory: Optional[Callable] = None,
        default_interval_minutes: int = DEFAULT_INTERVAL_MINUTES,
    ) -> None:
        self._sf = session_factory
        self._default_interval = max(1, int(default_interval_minutes))
        self._scan_service_factory = scan_service_factory or (
            lambda: ScanServiceFactory(session_factory)
        )
        self._jobs: Dict[int, ScanJob] = {}
        self._scheduler: Any = None
        self._running = False

    # -- lifecycle ------------------------------------------------------
    def start(self) -> bool:
        """Schedule every eligible datasource. Returns False if not started."""
        if self._running:
            return True
        if not APSCHEDULER_AVAILABLE:
            logger.warning(
                "scan_scheduler_unavailable",
                note="apscheduler 未安装，定时扫描不可用（手动/REST 触发不受影响）",
            )
            return False

        targets = self._scan_targets()
        if not targets:
            logger.info("scan_scheduler_no_targets", note="没有启用扫描的数据源")
            return False

        self._scheduler = BackgroundScheduler(
            job_defaults={"coalesce": True, "max_instances": 1}
        )
        for ds_id, code, interval in targets:
            self._scheduler.add_job(
                self._run_one,
                trigger=IntervalTrigger(minutes=interval),
                args=[ds_id],
                id=f"scan-{ds_id}",
                name=f"scan-{code}",
                replace_existing=True,
                max_instances=1,
            )
            self._jobs[ds_id] = ScanJob(
                datasource_id=ds_id,
                datasource_code=code,
                interval_minutes=interval,
            )
        self._scheduler.start()
        self._running = True
        # ``next_run_time`` is only populated once the scheduler is running.
        for ds_id, job in self._jobs.items():
            ap_job = self._scheduler.get_job(f"scan-{ds_id}")
            job.next_run_time = (
                str(ap_job.next_run_time)
                if ap_job is not None and getattr(ap_job, "next_run_time", None)
                else None
            )
        logger.info("scan_scheduler_started", jobs=len(self._jobs))
        return True

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
        self._running = False
        self._jobs.clear()
        logger.info("scan_scheduler_stopped")

    def is_running(self) -> bool:
        return self._running

    def list_jobs(self) -> List[ScanJob]:
        return list(self._jobs.values())

    # -- internals ------------------------------------------------------
    def _scan_targets(self) -> List[tuple]:
        """Datasources that are enabled, scan-enabled and not deleted."""
        from ..storage.models_core import Datasource

        with self._sf() as s:
            rows = (
                s.query(Datasource)
                .filter(
                    Datasource.deleted_at.is_(None),
                    Datasource.enabled.is_(True),
                    Datasource.scan_enabled.is_(True),
                )
                .all()
            )
            return [
                (ds.id, ds.code, self._interval_for(ds))
                for ds in rows
            ]

    def _interval_for(self, ds: Any) -> int:
        cfg = dict(ds.scan_config or {})
        raw = cfg.get(INTERVAL_CONFIG_KEY)
        # `or` would silently turn an explicit 0 into the default; keep 0 so it
        # clamps to the 1-minute floor instead of becoming an hour.
        if raw is None:
            raw = self._default_interval
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return self._default_interval

    def _run_one(self, datasource_id: int) -> None:
        """Execute one scheduled scan; never let an exception escape."""
        try:
            service = self._scan_service_factory()
            result = service.run_scan(datasource_id)
            logger.info(
                "scheduled_scan_done",
                datasource_id=datasource_id,
                ok=result.ok,
                tables_processed=result.tables_processed,
                tables_failed=result.tables_failed,
            )
        except Exception as exc:  # noqa: BLE001 - must not kill the thread
            logger.error(
                "scheduled_scan_failed",
                datasource_id=datasource_id,
                error=str(exc),
                exc_info=True,
            )


def ScanServiceFactory(session_factory: Callable):
    """Build a :class:`ScanService` (kept separate to avoid a circular import)."""
    from .service import ScanService

    return ScanService(session_factory)
