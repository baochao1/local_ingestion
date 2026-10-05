"""Unit tests for the data-source management service (MOD-01 / T-109).

Runs entirely in-memory: a fake connectivity checker + in-memory repository,
cipher, audit sink and orchestrator. Verifies every acceptance criterion from
the design without a database.
"""
from __future__ import annotations

import os

from local_ingestion.platform.credentials import CredentialCipher
from local_ingestion.platform.datasource.repository import (
    DuplicateDatasourceError,
    InMemoryDatasourceRepository,
)
from local_ingestion.platform.datasource.service import (
    ConflictError,
    ConnectivityResult,
    ConnectionFailedError,
    DataSourceService,
    DataSourceServiceError,
    NotFoundError,
    WriteAccessDeniedError,
    prod_capability_detector,
)
from local_ingestion.platform.orchestration import (
    AuditService,
    InMemoryAuditSink,
    build_in_memory_orchestration,
)


def _checker(*, connected=True, readonly=True, reason=""):
    state = {"connected": connected, "readonly": readonly, "reason": reason, "calls": []}

    def _fn(ds_type, host, port, username, password, database=None, options=None):
        state["calls"].append((ds_type, host, port, username, password, database, options))
        return ConnectivityResult(state["connected"], state["readonly"], state["reason"])

    return _fn, state


def _make(checker, *, allow_write=False):
    repo = InMemoryDatasourceRepository()
    cipher = CredentialCipher(key=os.urandom(32))
    audit = AuditService(InMemoryAuditSink())
    tasks = build_in_memory_orchestration()
    return DataSourceService(
        repo,
        cipher=cipher,
        audit=audit,
        task_service=tasks,
        connectivity_checker=checker,
        allow_write=allow_write,
    ), repo, audit, tasks


SPEC = {
    "code": "ds1",
    "name": "DS One",
    "ds_type": "postgres",
    "host": "h",
    "port": 5432,
    "username": "u",
    "password": "p",
    "scan_config": {"database": "db"},
}


def test_register_success_and_no_secret_leak():
    checker, _ = _checker()
    repo = InMemoryDatasourceRepository()
    cipher = CredentialCipher(key=os.urandom(32))
    sink = InMemoryAuditSink()
    audit = AuditService(sink)
    tasks = build_in_memory_orchestration()
    svc = DataSourceService(
        repo, cipher=cipher, audit=audit, task_service=tasks, connectivity_checker=checker
    )
    view = svc.register(dict(SPEC))
    assert view["id"] == 1
    assert view["code"] == "ds1"
    assert view["ds_type"] == "postgres"
    assert view["credential_versions"] == [1]
    assert view["active_credential_version"] == 1
    # secrets must never be exposed on the view
    assert "password" not in view
    assert "credential_enc" not in view
    # cipher stored a blob, not plaintext
    creds = repo.list_credentials(1)
    assert len(creds) == 1
    assert creds[0].credential_enc != b"p"
    # audit trail
    acts = {e.action for e in sink.entries}
    assert "datasource.register" in acts
    assert "datasource.credential.create" in acts


def test_register_duplicate_code_conflicts():
    checker, _ = _checker()
    svc, _, _, _ = _make(checker)
    svc.register(dict(SPEC))
    try:
        svc.register(dict(SPEC))
        raise AssertionError("expected ConflictError")
    except ConflictError:
        pass


def test_register_maps_unique_violation_to_conflict():
    """A registrant that races past the pre-check still fails as ConflictError.

    The existence check is a separate read, so a competing registrant can pass
    it and only be rejected later by the partial unique index on ``code``. That
    raw DB failure must not leak out of the service.
    """
    checker, _ = _checker()

    class _RacingRepo(InMemoryDatasourceRepository):
        def get_datasource_by_code(self, code):
            return None  # the read ran before the competing INSERT committed

        def create_datasource_with_credential(self, data, cred_factory=None):
            raise DuplicateDatasourceError(data["code"])

    svc = DataSourceService(
        _RacingRepo(),
        cipher=CredentialCipher(key=os.urandom(32)),
        audit=AuditService(InMemoryAuditSink()),
        connectivity_checker=checker,
    )
    try:
        svc.register(dict(SPEC))
        raise AssertionError("expected ConflictError")
    except ConflictError as e:
        assert SPEC["code"] in str(e)


def test_register_connection_failure():
    checker, _ = _checker(connected=False, reason="refused")
    svc, _, _, _ = _make(checker)
    try:
        svc.register(dict(SPEC))
        raise AssertionError("expected ConnectionFailedError")
    except ConnectionFailedError as e:
        assert "refused" in str(e)


def test_register_rejects_write_access_by_default():
    checker, _ = _checker(connected=True, readonly=False)
    svc, _, _, _ = _make(checker, allow_write=False)
    try:
        svc.register(dict(SPEC))
        raise AssertionError("expected WriteAccessDeniedError")
    except WriteAccessDeniedError:
        pass


def test_register_allows_write_when_policy_permits():
    checker, _ = _checker(connected=True, readonly=False)
    svc, _, _, _ = _make(checker, allow_write=True)
    view = svc.register(dict(SPEC))
    assert view["id"] == 1


def test_register_allow_write_kwarg_overrides_instance_flag():
    """Request-level allow_write=True must override an instance-level False.

    This is the exact path the API uses: the route forwards body.allowWrite
    straight to register(), so the service instance's default policy (False)
    must not block an explicit opt-in.
    """
    checker, _ = _checker(connected=True, readonly=False)
    svc, _, _, _ = _make(checker, allow_write=False)
    view = svc.register(dict(SPEC), allow_write=True)
    assert view["id"] == 1


def test_register_default_kwarg_respects_instance_policy():
    """Omitting the kwarg falls back to the instance-level policy."""
    checker, _ = _checker(connected=True, readonly=False)
    svc, _, _, _ = _make(checker, allow_write=False)
    try:
        svc.register(dict(SPEC))
        raise AssertionError("expected WriteAccessDeniedError")
    except WriteAccessDeniedError:
        pass


def test_register_audit_records_fr15_bypass():
    """A write-permission bypass must be visible in the audit trail."""
    checker, _ = _checker(connected=True, readonly=False)
    sink = InMemoryAuditSink()
    svc = DataSourceService(
        InMemoryDatasourceRepository(),
        cipher=CredentialCipher(key=os.urandom(32)),
        audit=AuditService(sink),
        connectivity_checker=checker,
        allow_write=True,
    )
    svc.register(dict(SPEC))
    reg = [e for e in sink.entries if e.action == "datasource.register"][0]
    assert reg.detail["allow_write"] is True
    assert reg.detail["fr15_bypass"] is True


def test_register_requires_username_and_password_together():
    checker, _ = _checker()
    svc, _, _, _ = _make(checker)
    try:
        svc.register({**SPEC, "username": "u", "password": None})
        raise AssertionError("expected validation error")
    except DataSourceServiceError:
        pass


def test_invalid_ds_type_rejected():
    checker, _ = _checker()
    svc, _, _, _ = _make(checker)
    try:
        svc.register({**SPEC, "ds_type": "oracle"})
        raise AssertionError("expected validation error")
    except DataSourceServiceError:
        pass


def test_register_is_atomic_when_credential_write_fails():
    """A credential-side failure must not leave a credential-less datasource.

    ``register`` used to commit the datasource in its own transaction and the
    credential in a second one, so a cipher error left an orphan row that
    permanently squatted the unique code (retrying raised ConflictError).
    """
    checker, _ = _checker()
    repo = InMemoryDatasourceRepository()

    class _BrokenCipher:
        def encrypt(self, password, *, datasource_id=None):
            raise RuntimeError("cipher backend unavailable")

    svc = DataSourceService(
        repo,
        cipher=_BrokenCipher(),
        audit=AuditService(InMemoryAuditSink()),
        connectivity_checker=checker,
    )
    try:
        svc.register(dict(SPEC))
        raise AssertionError("expected the cipher failure to surface")
    except RuntimeError:
        pass

    # Rolled back: no datasource, so the code is still free.
    assert repo.get_datasource_by_code(SPEC["code"]) is None

    retry = DataSourceService(
        repo,
        cipher=CredentialCipher(key=os.urandom(32)),
        audit=AuditService(InMemoryAuditSink()),
        connectivity_checker=checker,
    )
    view = retry.register(dict(SPEC))
    assert view["credential_versions"] == [1]
    assert view["active_credential_version"] == 1


def test_credential_rotation_and_activation():
    checker, _ = _checker()
    svc, repo, _, _ = _make(checker)
    ds = svc.register(dict(SPEC))
    v2 = svc.add_credential_version(ds["id"], "u2", "p2")
    assert v2 == 2
    # new version is NOT active by default
    assert svc.get_datasource(ds["id"])["active_credential_version"] == 1
    svc.activate_credential(ds["id"], v2)
    assert svc.get_datasource(ds["id"])["active_credential_version"] == 2
    assert len(repo.list_credentials(ds["id"])) == 2


def test_soft_delete_fans_out_cleanup_task():
    checker, _ = _checker()
    svc, repo, _, tasks = _make(checker)
    ds = svc.register(dict(SPEC))
    svc.delete_datasource(ds["id"])
    # soft delete: not physically gone
    assert repo.get_datasource(ds["id"]) is None  # repository hides soft-deleted
    # but a batched async cleanup task was dispatched via the orchestrator
    cleanup = tasks.list(job_type="datasource_cleanup")
    assert len(cleanup) == 1
    assert cleanup[0].scope["datasource_id"] == ds["id"]


def test_not_found_paths():
    checker, _ = _checker()
    svc, _, _, _ = _make(checker)
    for fn in (lambda: svc.get_datasource(99), lambda: svc.health(99), lambda: svc.delete_datasource(99)):
        try:
            fn()
            raise AssertionError("expected NotFoundError")
        except NotFoundError:
            pass


def test_test_connection_passthrough():
    checker, state = _checker(connected=True, readonly=True)
    svc, _, _, _ = _make(checker)
    res = svc.test_connection({"ds_type": "postgres", "host": "h", "username": "u", "password": "p"})
    assert res == {"connected": True, "readonly": True, "reason": ""}
    assert state["calls"]


def test_health_shape():
    checker, _ = _checker()
    svc, _, _, _ = _make(checker)
    ds = svc.register(dict(SPEC))
    h = svc.health(ds["id"])
    assert h["datasource_id"] == ds["id"]
    assert h["credential_present"] is True
    assert h["active_credential_version"] == 1


def test_capability_detector_dialect_bits():
    assert prod_capability_detector("postgres").supports_sampling is True
    # MySQL has no TABLESAMPLE -> sampling disabled by front-loaded capability
    assert prod_capability_detector("mysql").supports_sampling is False
    assert prod_capability_detector("mysql").supports_profiling is True
