"""Permission query service (MOD-08): matrix, entity grants, risks, changes.

Reads the catalog populated by the collector; risk items are computed on demand
from accounts + grants (+ optional grade lookup from MOD-05) so they always
reflect the latest data without a separate persistence table.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select

from ..storage.models_core import CatalogColumn, CatalogTable, Datasource
from ..storage.session import session_scope
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


def _risk_id(r: dict) -> str:
    basis = f"{r.get('type')}|{r.get('account')}|{r.get('object_fqn')}|{r.get('privilege')}"
    return hashlib.md5(basis.encode()).hexdigest()[:12]


class PermissionQueryService:
    def __init__(self, session_factory):
        self._sf = session_factory

    def _grade_lookup(self, datasource_id: int) -> dict[str, int]:
        """object_fqn -> grade_level, read from MOD-05 classification results.

        Without this the ``high_sensitivity`` rule can never fire. Grant rows
        carry whatever qualification the source dialect produced (PG yields
        ``schema.table``), while catalog FQNs are fully qualified
        (``ds.db.schema.table``), so every dotted suffix is registered and both
        forms resolve. The highest grade wins on a suffix collision.
        """
        out: dict[str, int] = {}
        with self._sf() as s:
            for model in (CatalogTable, CatalogColumn):
                rows = s.execute(
                    select(model.fqn, model.grade_level).where(
                        model.datasource_id == datasource_id,
                        model.deleted_at.is_(None),
                        model.grade_level.is_not(None),
                    )
                ).all()
                for fqn, grade in rows:
                    if grade is None:
                        continue
                    parts = fqn.split(".")
                    for i in range(len(parts)):
                        key = ".".join(parts[i:])
                        if out.get(key, 0) < grade:
                            out[key] = grade
        return out

    def matrix(self, datasource_id: int, account: str | None = None, limit: int = 200) -> list[dict]:
        return PermissionRepository(self._sf).list_accounts(datasource_id, account, limit)

    def grants_of_account(self, datasource_id: int, account: str) -> list[dict]:
        return PermissionRepository(self._sf).get_grants_of_account(datasource_id, account)

    def get_entity_grants(self, object_fqn: str) -> list[dict]:
        return PermissionRepository(self._sf).get_entity_grants(object_fqn)

    def risks(self, datasource_id: int, severity: str | None = None,
              grade_lookup: dict | None = None) -> list[dict]:
        repo = PermissionRepository(self._sf)
        # default to the real MOD-05 grades unless the caller supplies its own
        if grade_lookup is None:
            grade_lookup = self._grade_lookup(datasource_id)
        accounts = repo.list_accounts(datasource_id)
        grants: list[dict] = []
        for a in accounts:
            grants.extend(repo.get_grants_of_account(datasource_id, a["account"]))
        acct_rows = [{
            "name": a["account"], "is_super": a["is_super"], "is_locked": a["is_locked"],
            "last_login_at": _parse_login(a["last_login_at"]),
        } for a in accounts]
        items = evaluate_risks(acct_rows, grants, grade_lookup=grade_lookup or {})
        acked = self._acked_set(datasource_id)
        out = []
        for r in items:
            r["id"] = _risk_id(r)
            r["acked"] = r["id"] in acked
            out.append(r)
        if severity:
            out = [i for i in out if i["severity"] == severity]
        return out

    def ack_risk(self, datasource_id: int, risk_id: str) -> None:
        with session_scope() as s:
            ds = s.get(Datasource, datasource_id)
            cfg = dict(ds.scan_config or {})
            acked = set(cfg.get("acked_risks", []))
            acked.add(risk_id)
            cfg["acked_risks"] = list(acked)
            ds.scan_config = cfg
            s.commit()

    def _acked_set(self, datasource_id: int) -> set:
        with session_scope() as s:
            ds = s.get(Datasource, datasource_id)
            return set((ds.scan_config or {}).get("acked_risks", []))

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
