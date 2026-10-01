"""Platform runtime configuration (L3 local extension area).

Configuration is read from environment variables:

- ``DATABASE_URL``: metadata database (PostgreSQL) connection string.
- ``CREDENTIAL_ENCRYPTION_KEY``: AES-256-GCM key used to encrypt data-source
  credentials. It is wrapped in ``SecretStr`` so it can never leak through
  ``repr()``, ``str()``, logging or ``model_dump()``. It is never persisted.
- ``LOG_LEVEL``: logging level, defaults to ``INFO``.

Only :func:`get_settings` should be used by callers; the result is cached and
can be refreshed with :func:`reload_settings` (e.g. after tests mutate env).
"""
from __future__ import annotations

import base64
import binascii
import os
from functools import lru_cache
from typing import Final, Optional

from pydantic import BaseModel, Field, SecretStr, field_validator

AES_256_KEY_BYTES: Final = 32
"""AES-256-GCM requires a 32-byte key."""

DEFAULT_DATABASE_URL: Final = (
    "postgresql+psycopg2://postgres:postgres@localhost:5432/local_ingestion"
)
DEFAULT_LOG_LEVEL: Final = "INFO"

VALID_LOG_LEVELS: Final = (
    "CRITICAL",
    "ERROR",
    "WARNING",
    "INFO",
    "DEBUG",
    "NOTSET",
)

__all__ = [
    "AES_256_KEY_BYTES",
    "ConfigurationError",
    "Settings",
    "get_settings",
    "reload_settings",
    "get_database_url",
    "get_credential_encryption_key",
    "get_log_level",
]


class ConfigurationError(ValueError):
    """Raised when platform configuration is missing or invalid."""


def _decode_encryption_key(raw: str) -> bytes:
    """Decode an AES-256 key given as raw, base64 or hex into 32 raw bytes."""
    value = raw.strip()
    candidates: list[bytes] = [value.encode("utf-8")]
    try:
        candidates.append(base64.b64decode(value, validate=True))
    except (binascii.Error, ValueError):
        pass
    if len(value) == AES_256_KEY_BYTES * 2:
        try:
            candidates.append(bytes.fromhex(value))
        except ValueError:
            pass

    for candidate in candidates:
        if len(candidate) == AES_256_KEY_BYTES:
            return candidate

    raise ConfigurationError(
        "CREDENTIAL_ENCRYPTION_KEY 无效：AES-256-GCM 需要 "
        f"{AES_256_KEY_BYTES} 字节密钥（32 字符原始串 / 44 字符 base64 / "
        f"64 字符 hex），实际得到 {len(value)} 字符。"
        "可用以下命令生成：python -c "
        '"import base64, os; print(base64.b64encode(os.urandom(32)).decode())"'
    )


class Settings(BaseModel):
    """Validated platform settings loaded from the environment."""

    database_url: str = Field(
        default=DEFAULT_DATABASE_URL,
        description="Metadata database (PostgreSQL) connection string.",
    )
    credential_encryption_key: SecretStr = Field(
        description="AES-256-GCM key for data-source credentials (secret).",
    )
    log_level: str = Field(
        default=DEFAULT_LOG_LEVEL,
        description="Logging level name, e.g. INFO.",
    )

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        url = value.strip()
        if not url:
            raise ConfigurationError(
                "DATABASE_URL 不能为空；示例："
                "postgresql+psycopg2://user:pwd@localhost:5432/local_ingestion"
            )
        return url

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in VALID_LOG_LEVELS:
            raise ConfigurationError(
                f"LOG_LEVEL 无效：{value!r}；可选值："
                f"{', '.join(VALID_LOG_LEVELS)}"
            )
        return level

    @field_validator("credential_encryption_key")
    @classmethod
    def _validate_encryption_key(cls, value: SecretStr) -> SecretStr:
        # 仅校验长度；明文不进入异常消息，避免密钥泄漏到日志。
        _decode_encryption_key(value.get_secret_value())
        return value

    def encryption_key_bytes(self) -> bytes:
        """Return the raw 32-byte AES key (never log the return value)."""
        return _decode_encryption_key(
            self.credential_encryption_key.get_secret_value()
        )


def _load_settings() -> Settings:
    """Build :class:`Settings` from the current process environment."""
    env = os.environ
    raw_key: Optional[str] = env.get("CREDENTIAL_ENCRYPTION_KEY")
    if raw_key is None or not raw_key.strip():
        raise ConfigurationError(
            "缺少必需的环境变量 CREDENTIAL_ENCRYPTION_KEY（数据源凭据加密密钥）。"
            "该密钥不入库、不进日志，请通过环境变量或密钥管理服务注入；"
            "生成命令：python -c "
            '"import base64, os; print(base64.b64encode(os.urandom(32)).decode())"'
        )

    return Settings(
        database_url=env.get("DATABASE_URL") or DEFAULT_DATABASE_URL,
        credential_encryption_key=SecretStr(raw_key),
        log_level=env.get("LOG_LEVEL") or DEFAULT_LOG_LEVEL,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached platform settings (loaded on first call)."""
    return _load_settings()


def reload_settings() -> Settings:
    """Drop the cache and re-read the environment."""
    get_settings.cache_clear()
    return get_settings()


def get_database_url() -> str:
    """Return the metadata database connection string."""
    return get_settings().database_url


def get_credential_encryption_key() -> bytes:
    """Return the raw 32-byte credential encryption key (handle with care)."""
    return get_settings().encryption_key_bytes()


def get_log_level() -> str:
    """Return the configured logging level name (upper case)."""
    return get_settings().log_level
