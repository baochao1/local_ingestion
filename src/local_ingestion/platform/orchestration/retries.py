"""Retry / back-off policy helpers (FR-12.6 / T-107)."""
from __future__ import annotations

import random
import time
from typing import Callable

from .models import RetryPolicy


class RetryableError(Exception):
    """Mark an exception as explicitly retryable."""


# Markers used to heuristically classify an arbitrary exception as retryable
# (connection/timeout/deadlock/rate-limit) vs. fatal (param/permission).
_RETRYABLE_MARKERS = (
    "timeout", "connection", "deadlock", "locked", "ratelimit", "rate_limit",
    "temporarily", "try again", "busy", "unavailable", "reset",
)


def is_retryable(exc: BaseException) -> bool:
    """Heuristic: connection-level / transient faults are retryable."""
    if isinstance(exc, RetryableError):
        return True
    text = (type(exc).__name__ + " " + str(exc)).lower()
    return any(m in text for m in _RETRYABLE_MARKERS)


def backoff_seconds(attempt: int, policy: RetryPolicy) -> float:
    """Exponential back-off with optional full jitter (0.5x..1.5x)."""
    raw = min(policy.max_delay_sec, policy.base_delay_sec * (2 ** max(0, attempt - 1)))
    if policy.jitter:
        raw = raw * (0.5 + random.random())
    return raw


def sleep_with_cancel(
    seconds: float,
    is_cancelled: Callable[[], bool],
    sleeper: Callable[[float], None] = time.sleep,
    poll: float = 0.05,
) -> bool:
    """Sleep, but wake early if cancellation is requested.

    Returns ``True`` if cancelled during the wait.
    """
    waited = 0.0
    while waited < seconds:
        if is_cancelled():
            return True
        step = min(poll, seconds - waited)
        sleeper(step)
        waited += step
    return is_cancelled()
