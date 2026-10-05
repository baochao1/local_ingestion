"""Partition status REST API (MOD-10 / FE-01 §11.6, 运维视角).

The platform's operational store (``platform/storage/models_ops.py``) declares
Postgres declarative partitioning (``postgresql_partition_by``) on several
high-volume tables. This endpoint introspects those ORM definitions and reports
the partition scheme per table. Partition *creation* and retention enforcement
live at the database/DBA layer — the app only declares the scheme — so this is a
read-only status view, not a partition-management API.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from ...api.serialization import camelize
from ...storage.base import Base

router = APIRouter(prefix="/api/v1/tasks/partitions", tags=["Tasks"])

#: Operational retention policy (days). Declared here as the app's intended
#: window; actual enforcement is DB-side.
DEFAULT_RETENTION_DAYS = 90

_PARTITION_RE = re.compile(r"(\w+)\s*\(\s*([\w]+)\s*\)")


def _discover_partitioned_tables() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for cls in Base.__subclasses__():
        if getattr(cls, "__module__", "") != "local_ingestion.platform.storage.models_ops":
            continue
        table = getattr(cls, "__tablename__", None)
        args = getattr(cls, "__table_args__", None)
        if not table or not args:
            continue
        if not isinstance(args, (tuple, list)):
            args = (args,)
        for item in args:
            if isinstance(item, dict) and "postgresql_partition_by" in item:
                raw = item["postgresql_partition_by"]
                m = _PARTITION_RE.search(raw)
                strategy = m.group(1) if m else raw
                key = m.group(2) if m else None
                out.append(
                    {
                        "table": table,
                        "partitionStrategy": strategy,
                        "partitionKey": key,
                        "retentionWindowDays": DEFAULT_RETENTION_DAYS,
                        "managedBy": "database",
                    }
                )
    out.sort(key=lambda r: r["table"])
    return out


@router.get("")
def list_partitions() -> Dict[str, Any]:
    """List partitioned operational tables and their scheme."""
    tables = _discover_partitioned_tables()
    return camelize(
        {
            "items": tables,
            "total": len(tables),
            "note": "Partition creation/retention is enforced at the database layer; "
            "the app only declares the scheme.",
        }
    )
