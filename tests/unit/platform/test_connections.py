"""T-108 ②③④：连接供给（能力位校验 / 只读校验 / 审计）"""
import pytest

from local_ingestion.platform.connections import (
    ADMIN,
    METADATA,
    SAMPLE,
    ConnectionError,
    ConnectionProvider,
    DataSourceConnection,
    DatasourceUnavailableError,
    MissingCredentialError,
    PurposeNotAllowedError,
    WriteAccessError,
    build_url,
    evaluate_readonly,
)


class _FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


class _FakeCredential:
    def __init__(self, datasource_id: int, username: str = "reader"):
        self.id = 11
        self.version = 3
        self.datasource_id = datasource_id
        self.username = username
        self.credential_enc = b"\x00" * 40
        self.enc_algo = "AES-256-GCM:kv1"
        self.is_active = True


class _FakeDatasource:
    def __init__(self, **overrides):
        self.id = 1
        self.tenant_id = 0
        self.code = "ds_demo"
        self.ds_type = "postgres"
        self.host = "db.internal"
        self.port = 5432
        self.enabled = True
        self.scan_enabled = True
        self.sampling_enabled = True
        self.supports_sampling = True
        self.deleted_at = None
        self.scan_config = {}
        self.__dict__.update(overrides)


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return self

    def first(self):
        return self._row


class _FakeSession:
    """只实现 ConnectionProvider 用到的两个入口。"""

    def __init__(self, datasource=None, credential=None):
        self._datasource = datasource if datasource is not None else _FakeDatasource()
        self._credential = credential

    def get(self, model, ident):
        return self._datasource

    def execute(self, stmt):  # noqa: ARG002 - 语句内容由 ORM 负责，这里只回固定结果
        return _FakeResult(self._credential)


class _FakeCipher:
    def decrypt_row(self, row):  # noqa: D102 - 测试替身
        return "plain-password"


def _make_provider(
    datasource=None,
    credential=None,
    *,
    readonly=(True, "只读"),
    audit=None,
):
    session = _FakeSession(datasource, credential)
    calls: list[tuple] = []

    def verifier(engine, ds_type):
        calls.append((engine, ds_type))
        return readonly

    provider = ConnectionProvider(
        session,
        cipher=_FakeCipher(),
        verifier=verifier,
        audit_sink=audit if audit is not None else (lambda record: None),
        actor="tester",
        engine_factory=lambda url: _FakeEngine(),
    )
    return provider, calls


def _audit_recorder():
    records: list[dict] = []

    def sink(record):
        records.append(record)

    return records, sink


# --------------------------------------------------------------------------
# build_url
# --------------------------------------------------------------------------
def test_build_url_maps_ds_type_to_driver():
    url = build_url("mysql", username="u", password="p", host="h", port=3306)
    assert url.drivername == "mysql+pymysql"
    assert url.host == "h"


def test_build_url_falls_back_to_default_port():
    url = build_url("postgres", username="u", password="p", host="h", port=None)
    assert url.port == 5432


def test_build_url_rejects_unknown_ds_type():
    with pytest.raises(ConnectionError):
        build_url("oracle", username="u", password="p", host="h", port=1521)


def test_safe_url_never_exposes_password():
    url = build_url(
        "postgres", username="reader", password="s3cr3t", host="h", port=5432
    )
    assert "s3cr3t" not in url.render_as_string()
    assert "s3cr3t" in DataSourceConnection(
        datasource_id=1,
        code="c",
        ds_type="postgres",
        purpose=METADATA,
        url=url,
        readonly=True,
        credential_id=1,
        credential_version=1,
        engine=_FakeEngine(),
    ).secret_url()


# --------------------------------------------------------------------------
# evaluate_readonly
# --------------------------------------------------------------------------
def test_postgres_readonly_when_no_write_attributes():
    assert evaluate_readonly("postgres", [(False, False, 0)])[0] is True


@pytest.mark.parametrize(
    "row",
    [(True, False, 0), (False, True, 0), (False, False, 5)],
)
def test_postgres_write_detected(row):
    readonly, reason = evaluate_readonly("postgres", [row])
    assert readonly is False
    assert reason


def test_mysql_grants_with_write_keyword():
    readonly, reason = evaluate_readonly("mysql", [("GRANT ALL PRIVILEGES ON *.*",)])
    assert readonly is False
    assert "ALL PRIVILEGES" in reason


def test_mysql_readonly_grants_pass():
    assert evaluate_readonly("mysql", [("GRANT SELECT ON db.*",)])[0] is True


def test_snowflake_non_select_privilege_is_write():
    assert evaluate_readonly("snowflake", [("SELECT",)])[0] is True
    assert evaluate_readonly("snowflake", [("OWNERSHIP",)])[0] is False


def test_unknown_dialect_rows_treated_as_readonly_by_default():
    # 未定义探针的方言不应因为"看不懂"就被判为可写；探针层会另行报错。
    assert evaluate_readonly("mysql", [])[0] is True


# --------------------------------------------------------------------------
# acquire: 能力位与存在性
# --------------------------------------------------------------------------
def test_acquire_returns_connection_and_disposes_engine():
    provider, _ = _make_provider(credential=_FakeCredential(1))
    with provider.acquire(1, METADATA) as conn:
        assert conn.code == "ds_demo"
        assert conn.readonly is True
        assert conn.credential_version == 3
        engine = conn.engine
    assert engine.disposed is True


def test_acquire_rejects_soft_deleted_datasource():
    provider, _ = _make_provider(datasource=_FakeDatasource(deleted_at="2026-01-01"))
    with pytest.raises(DatasourceUnavailableError):
        with provider.acquire(1, METADATA):
            pass


@pytest.mark.parametrize(
    "overrides,purpose",
    [
        ({"enabled": False}, METADATA),
        ({"scan_enabled": False}, METADATA),
        ({"sampling_enabled": False}, SAMPLE),
        ({"supports_sampling": False}, SAMPLE),
    ],
)
def test_acquire_enforces_capability_bits(overrides, purpose):
    provider, _ = _make_provider(
        datasource=_FakeDatasource(**overrides), credential=_FakeCredential(1)
    )
    with pytest.raises(PurposeNotAllowedError):
        with provider.acquire(1, purpose):
            pass


def test_sample_purpose_does_not_require_scan_enabled():
    provider, _ = _make_provider(
        datasource=_FakeDatasource(scan_enabled=False), credential=_FakeCredential(1)
    )
    with provider.acquire(1, SAMPLE) as conn:
        assert conn.purpose is SAMPLE


def test_acquire_requires_active_credential():
    records, sink = _audit_recorder()
    provider, _ = _make_provider(credential=None, audit=sink)
    with pytest.raises(MissingCredentialError):
        with provider.acquire(1, METADATA):
            pass
    assert records[0]["result"] == "denied"


# --------------------------------------------------------------------------
# acquire: 只读校验
# --------------------------------------------------------------------------
def test_write_capable_connection_is_rejected_by_default():
    records, sink = _audit_recorder()
    provider, _ = _make_provider(
        credential=_FakeCredential(1), readonly=(False, "具备 INSERT 权限"), audit=sink
    )
    with pytest.raises(WriteAccessError):
        with provider.acquire(1, METADATA):
            pass
    assert records[-1]["result"] == "denied"
    assert "INSERT" in records[-1]["detail"]["reason"]


def test_allow_write_overrides_rejection():
    provider, _ = _make_provider(
        credential=_FakeCredential(1), readonly=(False, "具备 INSERT 权限")
    )
    with provider.acquire(1, METADATA, allow_write=True) as conn:
        assert conn.readonly is False


def test_admin_purpose_skips_readonly_probe():
    provider, calls = _make_provider(credential=_FakeCredential(1))
    with provider.acquire(1, ADMIN) as conn:
        assert conn.readonly is False
    assert calls == []  # 未触发只读探针


def test_verify_readonly_flag_can_be_disabled():
    provider, calls = _make_provider(credential=_FakeCredential(1))
    with provider.acquire(1, METADATA, verify_readonly=False):
        pass
    assert calls == []


# --------------------------------------------------------------------------
# acquire: 审计
# --------------------------------------------------------------------------
def test_successful_acquire_writes_audit_without_password():
    records, sink = _audit_recorder()
    provider, _ = _make_provider(credential=_FakeCredential(1), audit=sink)
    with provider.acquire(1, SAMPLE) as conn:
        url_in_audit = records[-1]["detail"]["url"]
    assert records[-1]["result"] == "ok"
    assert records[-1]["action"] == "datasource.connection.acquire"
    assert records[-1]["detail"]["purpose"] == "sample"
    assert records[-1]["detail"]["readonly"] is True
    assert "plain-password" not in url_in_audit
    assert conn.safe_url() == url_in_audit
