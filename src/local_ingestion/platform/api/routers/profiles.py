"""画像只读接口（MOD-04 / FR-M2）。

Why this module exists
----------------------
Profiling has been able to *compute* a profile since stage 2, but nothing could
read one back: ``table_profile`` had no endpoint, so the UI had nothing to
render and the placeholder route stayed a placeholder. These endpoints are the
read side only.

Triggering a profile run is deliberately **not** here. It needs a live
connection to the business database, which means wiring
:class:`platform.connections.ConnectionProvider` (including credential
decryption) and a task handler under ``JobType.PROFILE`` — both still
unwired in this repo. Shipping a trigger that cannot resolve a connection
would produce a 500 instead of a profile, so it lands with ``tasks.py``.

Payload shape
-------------
``stats`` is stored as ``{column: {metric: value}}``. That is compact in the
database but awkward to render, so it is reshaped into a ``columns`` list with
``null_ratio`` derived (the UI needs the ratio far more often than the raw
count).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from ...api.serialization import camelize
from ...profile.store import get_profile, list_history
from ...storage.session import session_scope

router = APIRouter(prefix="/api/v1/profiles", tags=["Profiling"])


def _open_session() -> Session:
    """New platform-DB session. Callers must close it."""
    return session_scope()


def _column_rows(stats: dict[str, Any], row_count: int) -> list[dict[str, Any]]:
    """``{column: metrics}`` → renderable list, with ``null_ratio`` derived."""
    rows: list[dict[str, Any]] = []
    for name, metrics in stats.items():
        if name.startswith("_"):
            continue  # ``_row_count`` is table-level metadata, not a column
        if not isinstance(metrics, dict):
            continue
        row: dict[str, Any] = dict(metrics)
        row["name"] = name
        nulls = metrics.get("null_count")
        if isinstance(nulls, (int, float)) and row_count:
            row["null_ratio"] = nulls / row_count
        rows.append(row)
    rows.sort(key=lambda item: str(item.get("name")))
    return rows


def _profile_payload(profile: Any) -> dict[str, Any]:
    stats = profile.stats or {}
    row_count = int(stats.get("_row_count") or profile.row_count or 0)
    return camelize(
        {
            "table_id": profile.table_id,
            "datasource_id": profile.datasource_id,
            "status": profile.status,
            "row_count": profile.row_count,
            "column_count": profile.column_count,
            "sample_rate": profile.sample_rate,
            "sampled_rows": profile.sampled_rows,
            "profiled_at": profile.profiled_at,
            "duration_ms": profile.duration_ms,
            "error_message": profile.error_message,
            "columns": _column_rows(stats, row_count),
        }
    )


@router.get("/tables/{table_id}")
def read_profile(table_id: int) -> dict[str, Any]:
    """Current profile for one table. 404 when it has never been profiled.

    "Never profiled" and "profiling failed" are different states and the UI
    shows them differently, so the former is a 404 while the latter is a 200
    with ``status='failed'`` and an ``errorMessage``.
    """
    session = _open_session()
    try:
        profile = get_profile(session, table_id)
    finally:
        session.close()
    if profile is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"no profile for table_id={table_id}",
        )
    return _profile_payload(profile)


@router.get("/tables/{table_id}/history")
def read_history(
    table_id: int,
    limit: int = Query(30, ge=1, le=365),
) -> dict[str, Any]:
    """Snapshot dates for one table, newest first.

    ``stats`` is intentionally omitted: a list of full payloads would be
    enormous. Fetch a single day via ``/history/{date}`` when comparing.
    """
    session = _open_session()
    try:
        rows = list_history(session, table_id, limit=limit)
    finally:
        session.close()
    return camelize(
        {
            "table_id": table_id,
            "items": [
                {
                    "profiled_date": row.profiled_date,
                    "row_count": row.row_count,
                    "quality_score": row.quality_score,
                    "profiled_at": row.profiled_at,
                }
                for row in rows
            ],
        }
    )


@router.get("/tables/{table_id}/history/{profiled_date}")
def read_history_snapshot(table_id: int, profiled_date: str) -> dict[str, Any]:
    """One day's snapshot including full per-column stats (FR-M2.3)."""
    session = _open_session()
    try:
        rows = list_history(session, table_id, limit=365)
    finally:
        session.close()
    for row in rows:
        if str(row.profiled_date) == profiled_date:
            stats = row.stats or {}
            row_count = int(stats.get("_row_count") or row.row_count or 0)
            return camelize(
                {
                    "table_id": table_id,
                    "profiled_date": row.profiled_date,
                    "row_count": row.row_count,
                    "quality_score": row.quality_score,
                    "columns": _column_rows(stats, row_count),
                }
            )
    raise HTTPException(
        status_code=http_status.HTTP_404_NOT_FOUND,
        detail=f"no snapshot for table_id={table_id} on {profiled_date}",
    )
