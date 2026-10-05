"""Re-entrancy / mutual-exclusion locks for the orchestration layer (T-107).

Single-instance deployment is confirmed (Q11), so an in-process lock is
sufficient. The lock is encapsulated behind ``LockProvider`` so that a future
multi-instance deployment can swap in a PostgreSQL advisory-lock backed
provider *without* touching business code::

    SELECT pg_try_advisory_lock(hashtext('job:' || job_id));
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Dict, Iterator


class LockProvider:
    """Abstract lock namespace. Implementations guard a logical key."""

    @contextmanager
    def lock(self, key: str) -> Iterator[None]:
        raise NotImplementedError


class ProcessLockProvider(LockProvider):
    """Per-key re-entrant locks held in this process (single-instance MVP)."""

    def __init__(self) -> None:
        self._locks: Dict[str, threading.RLock] = {}
        self._gate = threading.Lock()

    @contextmanager
    def lock(self, key: str) -> Iterator[None]:
        with self._gate:
            owned = key not in self._locks
            lk = self._locks.setdefault(key, threading.RLock())
        lk.acquire()
        try:
            yield
        finally:
            lk.release()
            # Keep the lock object warm; clearing is optional and harmless.
            if owned:
                with self._gate:
                    self._locks.pop(key, None)
