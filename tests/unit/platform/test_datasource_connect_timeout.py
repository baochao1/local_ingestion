"""连通性探测的 engine 参数（ux-audit P1-2）。

只测纯函数，不真连数据库：目标是把失败等待从约 6 秒（系统默认超时）压到 3 秒。
"""
from __future__ import annotations

from local_ingestion.platform.datasource.service import (
    CONNECT_TIMEOUT_SEC,
    engine_kwargs,
)


def test_relational_dialects_get_connect_timeout():
    assert engine_kwargs("postgresql") == {"connect_args": {"connect_timeout": CONNECT_TIMEOUT_SEC}}
    assert engine_kwargs("mysql") == {"connect_args": {"connect_timeout": CONNECT_TIMEOUT_SEC}}
    assert CONNECT_TIMEOUT_SEC == 3


def test_dialects_without_connect_timeout_get_nothing():
    # snowflake / bigquery 不接受 connect_timeout，传入会直接导致连接失败
    assert engine_kwargs("snowflake") == {}
    assert engine_kwargs("bigquery") == {}
    assert engine_kwargs("other") == {}


def test_case_insensitive():
    assert engine_kwargs("PostgreSQL") == {
        "connect_args": {"connect_timeout": CONNECT_TIMEOUT_SEC}
    }
