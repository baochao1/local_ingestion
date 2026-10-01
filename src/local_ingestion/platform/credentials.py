"""Data-source credential encryption (T-108 ①).

Secrets are encrypted with AES-256-GCM before they are written to
``datasource_credential.credential_enc``. Three properties matter:

1. **Authenticated encryption** — GCM's tag makes tampering detectable, so a
   ciphertext moved from another row (or hand-edited in the database) fails to
   decrypt instead of silently yielding a wrong password.
2. **AAD binding** — the datasource id is bound as additional authenticated
   data, so a valid blob for datasource A cannot be replayed on datasource B.
3. **Key versioning** — ``enc_algo`` carries ``<algorithm>:<key-version>`` so a
   future key rotation can decrypt old rows with the matching key instead of
   re-encrypting everything in one shot.

The key itself comes from :mod:`local_ingestion.platform.config` (env/KMS
injected, never persisted, wrapped in ``SecretStr``). It must never be logged;
:exc:`DecryptionError` messages are therefore deliberately generic.
"""
from __future__ import annotations

import os
from typing import Final

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import AES_256_KEY_BYTES, get_credential_encryption_key

ALGORITHM: Final = "AES-256-GCM"
DEFAULT_KEY_VERSION: Final = "kv1"
NONCE_BYTES: Final = 12
"""GCM standard nonce length (96 bit)."""
TAG_BYTES: Final = 16
"""GCM authentication tag length, appended by ``AESGCM.encrypt``."""
MIN_BLOB_BYTES: Final = NONCE_BYTES + TAG_BYTES
"""Shortest possible blob: empty plaintext + tag."""

__all__ = [
    "ALGORITHM",
    "DEFAULT_KEY_VERSION",
    "CredentialCipher",
    "CredentialError",
    "DecryptionError",
    "UnsupportedAlgorithmError",
    "build_enc_algo",
    "build_aad",
    "decrypt_secret",
    "encrypt_secret",
    "parse_enc_algo",
    "mask_secret",
]

SecretInput = str | bytes


class CredentialError(Exception):
    """Base error for credential encryption failures."""


class DecryptionError(CredentialError):
    """Raised when a credential blob cannot be decrypted or authenticated."""


class UnsupportedAlgorithmError(CredentialError):
    """Raised when ``enc_algo`` names an algorithm/key version we cannot use."""


def build_enc_algo(key_version: str = DEFAULT_KEY_VERSION) -> str:
    """Render the ``enc_algo`` column value, e.g. ``AES-256-GCM:kv1``."""
    return f"{ALGORITHM}:{key_version}"


def parse_enc_algo(enc_algo: str | None) -> tuple[str, str]:
    """Split ``enc_algo`` into ``(algorithm, key_version)``.

    Values written before key versions existed (the DDL default is the bare
    ``'AES-256-GCM'``) are read as the default key version.
    """
    raw = (enc_algo or ALGORITHM).strip()
    algorithm, _, version = raw.partition(":")
    if algorithm.upper() != ALGORITHM:
        raise UnsupportedAlgorithmError(
            f"不支持的凭据加密算法：{algorithm!r}（当前仅支持 {ALGORITHM}）"
        )
    return ALGORITHM, (version or DEFAULT_KEY_VERSION)


def build_aad(datasource_id: int, credential_id: int | None = None) -> bytes:
    """Build the additional authenticated data bound to a credential blob."""
    scope = f"ds={int(datasource_id)}"
    if credential_id is not None:
        scope = f"{scope};cred={int(credential_id)}"
    return f"{ALGORITHM}|{scope}".encode()


def _coerce_secret(secret: SecretInput) -> bytes:
    if isinstance(secret, bytes):
        return secret
    return str(secret).encode("utf-8")


def encrypt_secret(
    secret: SecretInput,
    key: bytes,
    *,
    datasource_id: int,
    credential_id: int | None = None,
    key_version: str = DEFAULT_KEY_VERSION,
) -> tuple[bytes, str]:
    """Encrypt ``secret``; return ``(blob, enc_algo)``.

    The blob layout is ``nonce(12) || ciphertext || tag(16)``.
    """
    if len(key) != AES_256_KEY_BYTES:
        raise CredentialError(
            f"AES-256-GCM 需要 {AES_256_KEY_BYTES} 字节密钥，实际 {len(key)} 字节。"
        )
    nonce = os.urandom(NONCE_BYTES)
    blob = AESGCM(key).encrypt(
        nonce, _coerce_secret(secret), build_aad(datasource_id, credential_id)
    )
    return nonce + blob, build_enc_algo(key_version)


def decrypt_secret(
    blob: bytes,
    key: bytes,
    *,
    datasource_id: int,
    credential_id: int | None = None,
    enc_algo: str | None = None,
) -> str:
    """Decrypt and authenticate a blob produced by :func:`encrypt_secret`."""
    if len(key) != AES_256_KEY_BYTES:
        raise CredentialError(
            f"AES-256-GCM 需要 {AES_256_KEY_BYTES} 字节密钥，实际 {len(key)} 字节。"
        )
    parse_enc_algo(enc_algo)
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise DecryptionError("凭据密文格式非法（期望 bytes）。")
    raw = bytes(blob)
    if len(raw) < MIN_BLOB_BYTES:
        raise DecryptionError(
            f"凭据密文过短：{len(raw)} 字节（至少 {MIN_BLOB_BYTES} 字节）。"
        )
    nonce, payload = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
    try:
        plain = AESGCM(key).decrypt(
            nonce, payload, build_aad(datasource_id, credential_id)
        )
    except InvalidTag as exc:
        # 不回显密钥、密文或 AAD，避免把敏感信息写进日志。
        raise DecryptionError(
            "凭据解密失败：密文被篡改、不属于该数据源，或密钥不匹配。"
        ) from exc
    return plain.decode("utf-8")


def mask_secret(secret: SecretInput | None) -> str:
    """Render a secret for logs/UI: never more than a length hint."""
    if secret is None:
        return "<none>"
    return f"***({len(_coerce_secret(secret))} bytes)"


class CredentialCipher:
    """Convenience wrapper that binds the platform key and row scope."""

    def __init__(
        self,
        key: bytes | None = None,
        *,
        key_version: str = DEFAULT_KEY_VERSION,
        bind_credential_id: bool = False,
    ) -> None:
        self._key = key if key is not None else get_credential_encryption_key()
        self.key_version = key_version
        self.bind_credential_id = bind_credential_id
        """为 True 时把凭据行 id 也绑进 AAD（加密与解密必须一致）。"""

    def encrypt(
        self,
        secret: SecretInput,
        *,
        datasource_id: int,
        credential_id: int | None = None,
    ) -> tuple[bytes, str]:
        return encrypt_secret(
            secret,
            self._key,
            datasource_id=datasource_id,
            credential_id=credential_id,
            key_version=self.key_version,
        )

    def decrypt(
        self,
        blob: bytes,
        *,
        datasource_id: int,
        credential_id: int | None = None,
        enc_algo: str | None = None,
    ) -> str:
        return decrypt_secret(
            blob,
            self._key,
            datasource_id=datasource_id,
            credential_id=credential_id,
            enc_algo=enc_algo,
        )

    def decrypt_row(self, row: object) -> str:
        """Decrypt an ORM ``DatasourceCredential`` row (decoupled by duck typing)."""
        return self.decrypt(
            row.credential_enc,
            datasource_id=row.datasource_id,
            credential_id=getattr(row, "id", None) if self.bind_credential_id else None,
            enc_algo=getattr(row, "enc_algo", None),
        )
