"""Feature availability registry (T-215 / MOD-09 D7).

Declares whether a deferred upstream module is currently deployed. Modules that
are scheduled later (MOD-07 lineage, MOD-08 authorization, MOD-11 visibility) are
reported as *unavailable* by default so consuming modules degrade gracefully
rather than failing (FR-7.6 / MOD-09 §4.4).
"""
from __future__ import annotations

from typing import Dict

MOD_LINEAGE = "MOD-07"
MOD_AUTHORIZATION = "MOD-08"
MOD_VISIBILITY = "MOD-11"


class FeatureAvailability:
    def __init__(self, available: Dict[str, bool] | None = None) -> None:
        self._available: Dict[str, bool] = dict(available or {})

    def declare(self, name: str, available: bool) -> None:
        self._available[name] = available

    def is_available(self, name: str) -> bool:
        return bool(self._available.get(name, False))


def default_availability() -> FeatureAvailability:
    """Out-of-the-box: MOD-07 lineage is deployed; the rest are still deferred.

    Lineage ships with a collector, a closure table and REST endpoints, so
    reporting it unavailable hid a working module (FR-M4.5). Pages still degrade
    to an empty state when nothing has been collected yet (C6).
    """
    return FeatureAvailability({
        MOD_LINEAGE: True,
        MOD_AUTHORIZATION: False,
        MOD_VISIBILITY: False,
    })
