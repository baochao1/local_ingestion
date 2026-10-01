"""T-108 ①：凭据 AES-256-GCM 加解密"""
import base64
import os

import pytest

from local_ingestion.platform import config
from local_ingestion.platform.credentials import (
    ALGORITHM,
    DEFAULT_KEY_VERSION,
    CredentialCipher,
    CredentialError,
    DecryptionError,
    UnsupportedAlgorithmError,
    build_aad,
    build_enc_algo,
    decrypt_secret,
    encrypt_secret,
    mask_secret,
    parse_enc_algo,
)

KEY = base64.b64decode(base64.b64encode(os.urandom(32)))
OTHER_KEY = os.urandom(32)


class _FakeCredentialRow:
    """替身 ORM 行：只提供解密所需属性。"""

    def __init__(
        self, datasource_id: int, blob: bytes, enc_algo: str, cred_id: int = 7
    ):
        self.id = cred_id
        self.datasource_id = datasource_id
        self.credential_enc = blob
        self.enc_algo = enc_algo


def test_roundtrip_returns_original_secret():
    blob, algo = encrypt_secret("p@ssw0rd", KEY, datasource_id=1)
    assert decrypt_secret(blob, KEY, datasource_id=1, enc_algo=algo) == "p@ssw0rd"
    assert algo == f"{ALGORITHM}:{DEFAULT_KEY_VERSION}"


def test_nonce_randomizes_ciphertext():
    first, _ = encrypt_secret("same", KEY, datasource_id=1)
    second, _ = encrypt_secret("same", KEY, datasource_id=1)
    assert first != second


def test_aad_binds_datasource_scope():
    blob, algo = encrypt_secret("secret", KEY, datasource_id=1)
    with pytest.raises(DecryptionError):
        decrypt_secret(blob, KEY, datasource_id=2, enc_algo=algo)


def test_credential_id_is_part_of_aad_when_present():
    blob, algo = encrypt_secret("secret", KEY, datasource_id=1, credential_id=7)
    with pytest.raises(DecryptionError):
        decrypt_secret(blob, KEY, datasource_id=1, credential_id=8, enc_algo=algo)
    assert (
        decrypt_secret(blob, KEY, datasource_id=1, credential_id=7, enc_algo=algo)
        == "secret"
    )


def test_tampered_ciphertext_is_rejected():
    blob, algo = encrypt_secret("secret", KEY, datasource_id=1)
    tampered = bytearray(blob)
    tampered[-1] ^= 0xFF
    with pytest.raises(DecryptionError):
        decrypt_secret(bytes(tampered), KEY, datasource_id=1, enc_algo=algo)


def test_truncated_blob_is_rejected():
    with pytest.raises(DecryptionError):
        decrypt_secret(b"\x00" * 8, KEY, datasource_id=1)


def test_wrong_key_is_rejected():
    blob, algo = encrypt_secret("secret", KEY, datasource_id=1)
    with pytest.raises(DecryptionError):
        decrypt_secret(blob, OTHER_KEY, datasource_id=1, enc_algo=algo)


def test_error_message_never_leaks_secret():
    blob, algo = encrypt_secret("super-secret-pwd", KEY, datasource_id=1)
    with pytest.raises(DecryptionError) as excinfo:
        decrypt_secret(blob, OTHER_KEY, datasource_id=1, enc_algo=algo)
    assert "super-secret-pwd" not in str(excinfo.value)


@pytest.mark.parametrize("key", [b"", os.urandom(16), os.urandom(64)])
def test_wrong_key_length_rejected(key):
    with pytest.raises(CredentialError):
        encrypt_secret("x", key, datasource_id=1)


def test_parse_enc_algo_defaults_to_kv1_for_bare_algorithm():
    # DDL 里 enc_algo 的默认值是不带版本号的 'AES-256-GCM'
    assert parse_enc_algo("AES-256-GCM") == (ALGORITHM, DEFAULT_KEY_VERSION)
    assert parse_enc_algo(None) == (ALGORITHM, DEFAULT_KEY_VERSION)
    assert parse_enc_algo("AES-256-GCM:kv2") == (ALGORITHM, "kv2")


def test_parse_enc_algo_rejects_unknown_algorithm():
    with pytest.raises(UnsupportedAlgorithmError):
        parse_enc_algo("AES-128-CBC")


def test_build_enc_algo_and_aad_are_stable():
    assert build_enc_algo("kv3") == f"{ALGORITHM}:kv3"
    assert build_aad(3, 4) == f"{ALGORITHM}|ds=3;cred=4".encode()


def test_mask_secret_hides_content():
    assert mask_secret("hunter2") == "***(7 bytes)"
    assert mask_secret(None) == "<none>"


def test_cipher_decrypt_row_reads_orm_shape():
    cipher = CredentialCipher(KEY)
    blob, algo = cipher.encrypt("db-password", datasource_id=42)
    row = _FakeCredentialRow(42, blob, algo)
    assert cipher.decrypt_row(row) == "db-password"


def test_cipher_default_key_comes_from_environment(monkeypatch):
    raw = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", raw)
    config.reload_settings()
    cipher = CredentialCipher()
    blob, algo = cipher.encrypt("from-env", datasource_id=1)
    assert cipher.decrypt(blob, datasource_id=1, enc_algo=algo) == "from-env"
