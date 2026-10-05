"""Permission query service (MOD-08): matrix, entity grants, risks, changes.

Reads the catalog populated by the collector; risk items are computed on demand
from accounts + grants (+ optional grade lookup from MOD-05) so they always
reflect the latest data without a separate persistence table.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .repository import PermissionRepository
from .risk import evaluate_risks


def _parse_login(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


class PermissionQueryService:
    def __init__(self, session_factory):
        self._sf = session_factory

    def matrix(self, datasource_id: int, account: str | None = None, limit: int = 200) -> list[dict]:
        return PermissionRepository(self._sf).list_accounts(datasource_id, account, limit)

    def grants_of_account(self, datasource_id: int, account: str) -> list[dict]:
        return PermissionRepository(self._sf).get_grants_of_account(datasource_id, account)

    def get_entity_grants(self, object_fqn: str) -> list[dict]:
        return PermissionRepository(self._sf).get_entity_grants(object_fqn)

    def risks(self, datasource_id: int, severity: str | None = None,
              grade_lookup: dict | None = None) -> list[dict]:
        repo = PermissionRepository(self._sf)
        accounts = repo.list_accounts(datasource_id)
        grants: list[dict] = []
        for a in accounts:
            grants.extend(repo.get_grants_of_account(datasource_id, a["account"]))
        acct_rows = [{
            "name": a["account"], "is_super": a["is_super"], "is_locked": a["is_locked"],
            "last_login_at": _parse_login(a["last_login_at"]),
        } for a in accounts]
        items = evaluate_risks(acct_rows, grants, grade_lookup=grade_lookup or {})
        if severity:
            items = [i for i in items if i["severity"] == severity]
        return items

    def changes(self, datasource_id: int) -> list[dict]:
        return PermissionRepository(self._sf).diff_vs_baseline(datasource_id)

    def mark_baseline(self, datasource_id: int) -> datetime:
        return PermissionRepository(self._sf).mark_baseline(datasource_id)

    def export_report(self, datasource_id: int, grade_lookup: dict | None = None) -> dict:
        repo = PermissionRepository(self._sf)
        accounts = repo.list_accounts(datasource_id)
        risks = self.risks(datasource_id, grade_lookup=grade_lookup)
        high = [r for r in risks if r["type"] == "high_sensitivity"]
        return {
            "datasource_id": datasource_id,
            "accounts": len(accounts),
            "risks": len(risks),
            "high_sensitivity_count": len(high),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "high_sensitivity": high,
        }
