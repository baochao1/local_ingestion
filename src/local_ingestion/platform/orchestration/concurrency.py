"""Concurrency limiters for task execution (FR-12.4 / T-107).

Two levels are enforced via counting semaphores:

* a global platform-wide cap, and
* a per-key cap (usually one per ``concurrency_key`` — e.g. a datasource, so a
  single source is never hammered by too many concurrent jobs).

Queued tasks are simply blocked on ``acquire`` until a slot frees up; the
caller can observe queue length indirectly through the limiter's counters.
"""
from __future__ import annotations

import threading
from typing import Dict


class ConcurrencyLimiter:
    def __init__(
        self,
        max_global: int = 8,
        per_key_limits: Dict[str, int] | None = None,
    ) -> None:
        self._max_global = max_global
        self._per_key_limits = dict(per_key_limits or {})
        self._global = threading.Semaphore(max_global)
        self._key_sems: Dict[str, threading.Semaphore] = {}
        self._gate = threading.Lock()
        self._active = 0
        self._active_by_key: Dict[str, int] = {}

    def _key_sem(self, key: str) -> threading.Semaphore:
        with self._gate:
            sem = self._key_sems.get(key)
            if sem is None:
                limit = self._per_key_limits.get(key, 2**30)
                sem = threading.Semaphore(limit)
                self._key_sems[key] = sem
            return sem

    def acquire(self, key: str) -> None:
        self._global.acquire()
        self._key_sem(key).acquire()
        with self._gate:
            self._active += 1
            self._active_by_key[key] = self._active_by_key.get(key, 0) + 1

    def release(self, key: str) -> None:
        with self._gate:
            self._active -= 1
            self._active_by_key[key] = max(0, self._active_by_key.get(key, 1) - 1)
        self._key_sem(key).release()
        self._global.release()

    def snapshot(self) -> Dict[str, int]:
        with self._gate:
            return {"active": self._active, "by_key": dict(self._active_by_key)}
