"""Data-source persistence (MOD-01 / T-109).

A small repository boundary so :class:`DataSourceService` stays storage-agnostic:

* ``InMemoryDatasourceRepository`` — unit tests and the single-instance MVP.
* ``SqlDatasourceRepository`` — persists to the ``datasource`` /
  ``datasource_credential`` tables (ORM landed in T-103/T-106).

Both expose the same attribute surface (``.id``, ``.code``, ``.ds_type`` …) so
the service reads them uniformly via duck typing.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, List, Optional, Protocol
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from ..storage.models_core import Datasource, DatasourceCredential
from ..storage.session import session_scope


class DuplicateDatasourceError(Exception):
    """The datasource violates a uniqueness constraint (in practice ``code``).

    Raised when the INSERT itself rejects the row, i.e. the caller's
    "does this code already exist?" pre-check raced with a concurrent
    registrant. Repository-level so the storage layer stays free of service
    concepts; :class:`DataSourceService` translates it to ``ConflictError``.
    """

    def __init__(self, code: Optional[str] = None) -> None:
        super().__init__(f"数据源唯一约束冲突：code={code!r}")
        self.code = code


def _is_unique_violation(exc: IntegrityError) -> bool:
    """True only for genuine unique/duplicate-key violations (PG 23505 等）。

    其他 IntegrityError（CHECK/FK/NOT NULL …）不得误报成"code 已存在"，
    否则真实原因会被掩盖。
    """
    orig = getattr(exc, "orig", None)
    pgcode = getattr(orig, "pgcode", None)
    if pgcode:
        return pgcode == "23505"
    text = str(orig or exc).lower()
    return "unique" in text or "duplicate key" in text


class DatasourceRepository(Protocol):
    def create_datasource(self, data: dict) -> Any: ...
    def create_credential(self, data: dict) -> Any: ...
    def create_datasource_with_credential(
        self,
        data: dict,
        cred_factory: Optional[Callable[[int], dict]] = None,
    ) -> Any:
        """Create a datasource and its first credential atomically.

        ``cred_factory`` receives the freshly assigned ``datasource_id`` and
        returns the credential payload — the id is needed up front because the
        ciphertext is bound to it (AAD).
        """
        ...
    def get_datasource(self, ds_id: int) -> Any: ...
    def get_datasource_by_code(self, code: str) -> Any: ...
    def list_datasources(
        self,
        *,
        enabled: Optional[bool] = None,
        environment: Optional[str] = None,
        group_name: Optional[str] = None,
        ds_type: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[Any]: ...
    def update_datasource(self, ds_id: int, changes: dict) -> Any: ...
    def soft_delete_datasource(self, ds_id: int) -> None: ...
    def list_credentials(self, ds_id: int) -> List[Any]: ...
    def get_credential(self, ds_id: int, version: int) -> Any: ...
    def set_active_credential(self, ds_id: int, version: int) -> None: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryDatasourceRepository:
    """Pure-python repository backed by dicts; used for tests and MVP runtime."""

    def __init__(self) -> None:
        self._ds: dict[int, Any] = {}
        self._cred: dict[int, Any] = {}
        self._ds_seq = 0
        self._cred_seq = 0
        self._code_index: dict[str, int] = {}

    def create_datasource(self, data: dict) -> Any:
        self._ds_seq += 1
        obj = SimpleNamespace(
            id=self._ds_seq,
            deleted_at=None,
            created_at=_now(),
            updated_at=_now(),
            **{k: data.get(k) for k in (
                "tenant_id", "code", "name", "ds_type", "host", "port",
                "environment", "group_name", "owner_business", "owner_technical",
                "enabled", "scan_enabled", "sampling_enabled", "scan_config",
                "sampling_config", "supports_sampling", "supports_lineage",
                "supports_profiling", "last_scan_at", "last_scan_status",
                "last_error",
            )},
        )
        self._ds[obj.id] = obj
        self._code_index[obj.code] = obj.id
        return obj

    def create_credential(self, data: dict) -> Any:
        self._cred_seq += 1
        obj = SimpleNamespace(
            id=self._cred_seq,
            datasource_id=data["datasource_id"],
            version=data.get("version", 1),
            username=data.get("username"),
            credential_enc=data["credential_enc"],
            enc_algo=data.get("enc_algo", "AES-256-GCM"),
            is_active=data.get("is_active", True),
            verified_at=data.get("verified_at"),
            expires_at=data.get("expires_at"),
            created_at=_now(),
        )
        self._cred[obj.id] = obj
        return obj

    def create_datasource_with_credential(
        self,
        data: dict,
        cred_factory: Optional[Callable[[int], dict]] = None,
    ) -> Any:
        obj = self.create_datasource(data)
        if cred_factory is not None:
            try:
                self.create_credential(cred_factory(obj.id))
            except Exception:
                # Mirror the SQL repository: a failed credential rolls the
                # datasource back instead of leaving a credential-less row that
                # blocks re-registration under the same code.
                self._ds.pop(obj.id, None)
                self._code_index.pop(obj.code, None)
                raise
        return obj

    def get_datasource(self, ds_id: int) -> Any:
        obj = self._ds.get(ds_id)
        return obj if obj and obj.deleted_at is None else None

    def get_datasource_by_code(self, code: str) -> Any:
        ds_id = self._code_index.get(code)
        if ds_id is None:
            return None
        return self.get_datasource(ds_id)

    def list_datasources(
        self,
        *,
        enabled: Optional[bool] = None,
        environment: Optional[str] = None,
        group_name: Optional[str] = None,
        ds_type: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[Any]:
        out = [o for o in self._ds.values() if o.deleted_at is None]
        if enabled is not None:
            out = [o for o in out if bool(o.enabled) == enabled]
        if environment is not None:
            out = [o for o in out if o.environment == environment]
        if group_name is not None:
            out = [o for o in out if o.group_name == group_name]
        if ds_type is not None:
            out = [o for o in out if o.ds_type == ds_type]
        if keyword:
            kw = keyword.lower()
            out = [
                o
                for o in out
                if kw in (o.code or "").lower() or kw in (o.name or "").lower()
            ]
        return sorted(out, key=lambda o: o.code)

    def update_datasource(self, ds_id: int, changes: dict) -> Any:
        obj = self.get_datasource(ds_id)
        if obj is None:
            raise KeyError(ds_id)
        for k, v in changes.items():
            setattr(obj, k, v)
        obj.updated_at = _now()
        return obj

    def soft_delete_datasource(self, ds_id: int) -> None:
        obj = self._ds.get(ds_id)
        if obj is not None:
            obj.deleted_at = _now()

    def list_credentials(self, ds_id: int) -> List[Any]:
        return [c for c in self._cred.values() if c.datasource_id == ds_id]

    def get_credential(self, ds_id: int, version: int) -> Any:
        for c in self._cred.values():
            if c.datasource_id == ds_id and c.version == version:
                return c
        return None

    def set_active_credential(self, ds_id: int, version: int) -> None:
        for c in self._cred.values():
            if c.datasource_id == ds_id:
                c.is_active = (c.version == version)


class SqlDatasourceRepository:
    """Persists to the ``datasource`` / ``datasource_credential`` tables."""

    def __init__(self, session_factory=session_scope) -> None:
        self._sf = session_factory

    def create_datasource(self, data: dict) -> Datasource:
        # Each repository call owns its session, so it must own the commit too:
        # nothing upstream commits it (``session_scope`` hands out a bare
        # Session, whose context manager merely closes => rolls back).
        with self._sf() as s:
            m = Datasource(**data)
            s.add(m)
            try:
                s.flush()
                s.commit()
            except IntegrityError as exc:
                if _is_unique_violation(exc):
                    raise DuplicateDatasourceError(data.get("code")) from exc
                from ..datasource.service import DataSourceServiceError

                raise DataSourceServiceError(str(exc.orig or exc)) from exc
            s.refresh(m)
            s.expunge(m)
            return m

    def create_credential(self, data: dict) -> DatasourceCredential:
        with self._sf() as s:
            m = DatasourceCredential(**data)
            s.add(m)
            s.flush()
            s.commit()
            s.refresh(m)
            s.expunge(m)
            return m

    def create_datasource_with_credential(
        self,
        data: dict,
        cred_factory: Optional[Callable[[int], dict]] = None,
    ) -> Datasource:
        """Create the datasource and its first credential in ONE transaction.

        ``register`` used to commit the datasource first and the credential in a
        second transaction, so any credential-side failure (cipher error,
        constraint violation) left an orphan datasource row behind that could
        never be re-registered under the same code. Both inserts now share one
        session: the id ``cred_factory`` needs — it binds the ciphertext to
        ``datasource_id`` — comes from a flush, which stays inside the
        transaction, so a later failure rolls back *both* rows.
        """
        with self._sf() as s:
            m = Datasource(**data)
            s.add(m)
            try:
                s.flush()  # assigns the id without committing
            except IntegrityError as exc:
                # uq_datasource_code is a partial unique index, so this fires on
                # a genuine race: the caller's pre-check read ran before the
                # competing INSERT committed. 其他 IntegrityError（CHECK/FK/…）
                # 不能误报成 code 冲突，透出真实原因。
                if _is_unique_violation(exc):
                    raise DuplicateDatasourceError(data.get("code")) from exc
                from ..datasource.service import DataSourceServiceError

                raise DataSourceServiceError(str(exc.orig or exc)) from exc
            if cred_factory is not None:
                s.add(DatasourceCredential(**cred_factory(m.id)))
                s.flush()
            s.commit()
            s.refresh(m)
            s.expunge(m)
            return m

    def get_datasource(self, ds_id: int) -> Optional[Datasource]:
        from sqlalchemy import select

        with self._sf() as s:
            stmt = select(Datasource).where(
                Datasource.id == ds_id, Datasource.deleted_at.is_(None)
            )
            m = s.scalars(stmt).first()
            if m is not None:
                s.expunge(m)
            return m

    def get_datasource_by_code(self, code: str) -> Optional[Datasource]:
        from sqlalchemy import select

        with self._sf() as s:
            stmt = select(Datasource).where(
                Datasource.code == code, Datasource.deleted_at.is_(None)
            )
            m = s.scalars(stmt).first()
            if m is not None:
                s.expunge(m)
            return m

    def list_datasources(
        self,
        *,
        enabled: Optional[bool] = None,
        environment: Optional[str] = None,
        group_name: Optional[str] = None,
        ds_type: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> List[Datasource]:
        from sqlalchemy import or_, select

        with self._sf() as s:
            stmt = select(Datasource).where(Datasource.deleted_at.is_(None))
            if enabled is not None:
                stmt = stmt.where(Datasource.enabled.is_(enabled))
            if environment is not None:
                stmt = stmt.where(Datasource.environment == environment)
            if group_name is not None:
                stmt = stmt.where(Datasource.group_name == group_name)
            if ds_type is not None:
                stmt = stmt.where(Datasource.ds_type == ds_type)
            if keyword:
                like = f"%{keyword}%"
                stmt = stmt.where(
                    or_(Datasource.code.ilike(like), Datasource.name.ilike(like))
                )
            rows = s.scalars(stmt.order_by(Datasource.code)).all()
            for r in rows:
                s.expunge(r)
            return list(rows)

    def update_datasource(self, ds_id: int, changes: dict) -> Datasource:
        with self._sf() as s:
            m = s.get(Datasource, ds_id)
            if m is None or m.deleted_at is not None:
                raise KeyError(ds_id)
            for k, v in changes.items():
                setattr(m, k, v)
            s.flush()
            s.commit()
            s.refresh(m)
            s.expunge(m)
            return m

    def soft_delete_datasource(self, ds_id: int) -> None:
        with self._sf() as s:
            m = s.get(Datasource, ds_id)
            if m is not None:
                m.deleted_at = _now()
                s.flush()
                s.commit()

    def list_credentials(self, ds_id: int) -> List[DatasourceCredential]:
        from sqlalchemy import select

        with self._sf() as s:
            stmt = select(DatasourceCredential).where(
                DatasourceCredential.datasource_id == ds_id
            ).order_by(DatasourceCredential.version)
            rows = s.scalars(stmt).all()
            for r in rows:
                s.expunge(r)
            return list(rows)

    def get_credential(self, ds_id: int, version: int) -> Optional[DatasourceCredential]:
        from sqlalchemy import select

        with self._sf() as s:
            stmt = select(DatasourceCredential).where(
                DatasourceCredential.datasource_id == ds_id,
                DatasourceCredential.version == version,
            )
            m = s.scalars(stmt).first()
            if m is not None:
                s.expunge(m)
            return m

    def set_active_credential(self, ds_id: int, version: int) -> None:
        from sqlalchemy import select

        with self._sf() as s:
            stmt = select(DatasourceCredential).where(
                DatasourceCredential.datasource_id == ds_id
            )
            for c in s.scalars(stmt).all():
                c.is_active = (c.version == version)
            s.flush()
            s.commit()
