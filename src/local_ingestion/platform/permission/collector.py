"""Permission collector: read-only ADMIN conn -> accounts/grants + risk (MOD-08).

Only issues SELECTs against the business database through the supplied connection
(which is an ``ADMIN``-purpose connection from ``ConnectionProvider``). Never writes
to the business database (design D2). Grant grantees are normalised to the same
account identity used when upserting accounts (e.g. MySQL ``'user'@'host'``), and
super-account ``ALL`` grants on ``*`` / ``*.*`` are stored once to avoid exploding
the table (design D4).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from sqlalchemy import text

from ..dialect import get_dialect
from .repository import PermissionRepository
from .risk import evaluate_risks

logger = structlog.get_logger()

_SUPER_GRANT = {"ALL", "ALL PRIVILEGES"}


@dataclass
class CollectResult:
    accounts: int = 0
    grants: int = 0
    risks: int = 0
    failed: int = 0


def _account_name(ds_type: str, row) -> str:
    name = row[0]
    host = row[1] if len(row) > 1 else None
    # MySQL/Snowflake grantee is 'user'@'host'; normalise accounts to match.
    if ds_type in ("mysql", "snowflake") and host:
        return f"{name}@{host}"
    return name


def collect_permissions(session_factory, *, ds_id: int, ds_type: str, db: str,
                       schema: str, conn, grade_lookup: dict | None = None,
                       run_id: datetime | None = None) -> CollectResult:
    dialect = get_dialect(ds_type)
    repo = PermissionRepository(session_factory)
    res = CollectResult()
    run_at = run_id or datetime.now(timezone.utc)

    # 1) accounts
    try:
        for row in conn.execute(text(dialect.list_accounts_sql())):
            name = _account_name(ds_type, row)
            is_super = bool(row[1]) if len(row) > 1 else False
            can_login = bool(row[2]) if len(row) > 2 else True
            repo.upsert_account(ds_id, name, account_type="user", is_super=is_super,
                                is_locked=not can_login)
            res.accounts += 1
    except Exception as exc:
        res.failed += 1
        logger.warning("permission_account_query_failed", ds=ds_id, error=str(exc))

    # 2) grants (cap super-account explosion)
    grants: list[dict] = []
    try:
        for row in conn.execute(text(dialect.list_grants_sql())):
            grantee = row[0]
            obj_type = row[1]
            obj_fqn = row[2]
            priv = (row[3] or "").upper()
            grantable = bool(row[4]) if len(row) > 4 else False
            if priv in _SUPER_GRANT and obj_fqn in ("*", "*.*"):
                repo.upsert_grant(ds_id, grantee, "ALL", obj_type, obj_fqn, grantable, run_at)
                grants.append({"account": grantee, "privilege": "ALL",
                               "object_type": obj_type, "object_fqn": obj_fqn})
                res.grants += 1
                continue
            repo.upsert_grant(ds_id, grantee, priv, obj_type, obj_fqn, grantable, run_at)
            grants.append({"account": grantee, "privilege": priv,
                           "object_type": obj_type, "object_fqn": obj_fqn})
            res.grants += 1
    except Exception as exc:
        res.failed += 1
        logger.warning("permission_grant_query_failed", ds=ds_id, error=str(exc))

    # 3) risk detection (computed, not necessarily persisted here)
    acct_rows = [{"name": a["account"], "is_super": a["is_super"],
                  "is_locked": a["is_locked"], "last_login_at": None}
                 for a in repo.list_accounts(ds_id)]
    risks = evaluate_risks(acct_rows, grants, grade_lookup=grade_lookup or {})
    res.risks = len(risks)
    logger.info("permission_collect_done", ds=ds_id, **_counts(res))
    return res


def _counts(res: CollectResult) -> dict:
    return {"accounts": res.accounts, "grants": res.grants, "risks": res.risks, "failed": res.failed}
