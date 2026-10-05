"""Permission persistence (MOD-08). Account/grant upsert + baseline diff.

Grants are linked to :class:`Account` via ``account_id`` (the model has no
``grantee`` text column). Each collection run stamps rows with ``detected_at``;
baseline comparison stores the baseline snapshot inside ``datasource.scan_config``
(no extra migration needed), so ``diff_vs_baseline`` can report added/revoked
privileges across runs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..storage.models_core import Datasource
from ..storage.models_ops import Account, AccountGrant

_DEFAULT_TENANT = 0

_GRANT_UNIQUE = ("datasource_id", "account_id", "privilege", "object_fqn")


class PermissionRepository:
    def __init__(self, session_factory):
        self._sf = session_factory

    # -- accounts -----------------------------------------------------------
    def upsert_account(self, ds_id: int, name: str, account_type: Optional[str] = None,
                      host_pattern: Optional[str] = None, is_super: bool = False,
                      is_locked: bool = False, last_login_at: Optional[datetime] = None,
                      tenant_id: int = _DEFAULT_TENANT) -> int:
        with self._sf() as s:
            row = s.execute(
                select(Account).where(
                    Account.datasource_id == ds_id, Account.account_name == name,
                    Account.host_pattern.is_(host_pattern), Account.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if row is None:
                row = Account(datasource_id=ds_id, account_name=name, host_pattern=host_pattern,
                              tenant_id=tenant_id)
                s.add(row)
            row.account_type = account_type
            row.is_super = is_super
            row.is_locked = is_locked
            row.last_login_at = last_login_at
            s.commit()
            s.refresh(row)
            return row.id

    def _resolve_account_id(self, s: Session, ds_id: int, name: str,
                           host_pattern: Optional[str] = None) -> Optional[int]:
        row = s.execute(
            select(Account).where(
                Account.datasource_id == ds_id, Account.account_name == name,
                Account.host_pattern.is_(host_pattern), Account.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if row is None:
            row = Account(datasource_id=ds_id, account_name=name, host_pattern=host_pattern)
            s.add(row)
            s.flush()
        return row.id

    # -- grants -------------------------------------------------------------
    def upsert_grant(self, ds_id: int, account: str, privilege: str, object_type: str,
                    object_fqn: str, grantable: bool = False,
                    detected_at: Optional[datetime] = None,
                    host_pattern: Optional[str] = None,
                    tenant_id: int = _DEFAULT_TENANT) -> AccountGrant:
        detected_at = detected_at or datetime.now(timezone.utc)
        with self._sf() as s:
            account_id = self._resolve_account_id(s, ds_id, account, host_pattern)
            existing = s.execute(
                select(AccountGrant).where(
                    AccountGrant.datasource_id == ds_id,
                    AccountGrant.account_id == account_id,
                    AccountGrant.privilege == privilege,
                    AccountGrant.object_fqn == object_fqn,
                    AccountGrant.deleted_at.is_(None),
                )
            ).scalar_one_or_none()
            if existing is None:
                existing = AccountGrant(
                    datasource_id=ds_id, account_id=account_id, privilege=privilege,
                    object_type=object_type, object_fqn=object_fqn, tenant_id=tenant_id,
                )
                s.add(existing)
            existing.grantable = grantable
            existing.detected_at = detected_at
            s.commit()
            s.refresh(existing)
            return existing

    def count_accounts(self, ds_id: int, tenant_id: int = _DEFAULT_TENANT) -> int:
        with self._sf() as s:
            return s.execute(
                select(func.count()).select_from(Account).where(
                    Account.datasource_id == ds_id, Account.deleted_at.is_(None),
                    Account.tenant_id == tenant_id,
                )
            ).scalar_one()

    # -- queries ------------------------------------------------------------
    def list_accounts(self, ds_id: int, account: Optional[str] = None,
                     limit: int = 200) -> list[dict]:
        with self._sf() as s:
            q = select(Account).where(
                Account.datasource_id == ds_id, Account.deleted_at.is_(None))
            if account:
                q = q.where(Account.account_name == account)
            rows = s.execute(q.limit(limit)).scalars().all()
        return [{
            "account": a.account_name, "type": a.account_type, "is_super": a.is_super,
            "is_locked": a.is_locked, "host": a.host_pattern,
            "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None,
        } for a in rows]

    def get_grants_of_account(self, ds_id: int, account: str) -> list[dict]:
        with self._sf() as s:
            rows = s.execute(
                select(AccountGrant, Account.account_name).join(
                    Account, AccountGrant.account_id == Account.id).where(
                    AccountGrant.datasource_id == ds_id, Account.account_name == account,
                    AccountGrant.deleted_at.is_(None),
                )
            ).all()
        return [self._grant_dict(g, name) for g, name in rows]

    def get_entity_grants(self, object_fqn: str) -> list[dict]:
        with self._sf() as s:
            rows = s.execute(
                select(AccountGrant, Account.account_name).join(
                    Account, AccountGrant.account_id == Account.id).where(
                    AccountGrant.object_fqn == object_fqn, AccountGrant.deleted_at.is_(None),
                )
            ).all()
        return [self._grant_dict(g, name) for g, name in rows]

    @staticmethod
    def _grant_dict(g: AccountGrant, account_name: str | None = None) -> dict:
        return {
            "account": account_name, "account_id": g.account_id, "privilege": g.privilege,
            "object_type": g.object_type, "object_fqn": g.object_fqn,
            "grantable": g.grantable, "detected_at": g.detected_at.isoformat(),
        }

    # -- baseline / diff ----------------------------------------------------
    def mark_baseline(self, ds_id: int) -> datetime:
        baseline_at = datetime.now(timezone.utc)
        keys = self._current_grant_keys(ds_id)
        with self._sf() as s:
            ds = s.get(Datasource, ds_id)
            cfg = dict(ds.scan_config or {})
            cfg["permission_baseline"] = {
                "at": baseline_at.isoformat(),
                "keys": [[k[0], k[1], k[2]] for k in keys],
            }
            ds.scan_config = cfg
            s.commit()
        return baseline_at

    def diff_vs_baseline(self, ds_id: int) -> list[dict]:
        with self._sf() as s:
            ds = s.get(Datasource, ds_id)
            cfg = ds.scan_config or {}
            snap = cfg.get("permission_baseline")
        if not snap:
            return []
        base_keys = {tuple(k) for k in snap["keys"]}
        cur_keys = self._current_grant_keys(ds_id)
        added = [self._diff_item("added", k) for k in (cur_keys - base_keys)]
        revoked = [self._diff_item("revoked", k) for k in (base_keys - cur_keys)]
        return added + revoked

    def _current_grant_keys(self, ds_id: int) -> set[tuple]:
        with self._sf() as s:
            max_at = s.execute(
                select(func.max(AccountGrant.detected_at)).where(
                    AccountGrant.datasource_id == ds_id, AccountGrant.deleted_at.is_(None))
            ).scalar()
            if max_at is None:
                return set()
            rows = s.execute(
                select(AccountGrant.account_id, AccountGrant.privilege, AccountGrant.object_fqn).where(
                    AccountGrant.datasource_id == ds_id, AccountGrant.detected_at == max_at,
                    AccountGrant.deleted_at.is_(None),
                )
            ).all()
        return {(r[0], r[1], r[2]) for r in rows}

    @staticmethod
    def _diff_item(kind: str, key: tuple) -> dict:
        return {"kind": kind, "account_id": key[0], "privilege": key[1], "object_fqn": key[2]}
