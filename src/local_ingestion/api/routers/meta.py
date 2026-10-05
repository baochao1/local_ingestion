"""Meta endpoints: degradation status of deferred-module dependencies (T-215)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from local_ingestion.platform.degrade.registry import DegradationRegistry, build_default_registry

router = APIRouter(prefix="/api/v1/meta", tags=["Meta"])

_state: dict = {}


def get_registry() -> DegradationRegistry:
    if "r" not in _state:
        _state["r"] = build_default_registry()
    return _state["r"]


@router.get("/degradation")
def degradation(svc: DegradationRegistry = Depends(get_registry)):
    return svc.describe()
