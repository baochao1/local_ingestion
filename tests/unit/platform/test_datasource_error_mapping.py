"""驱动层异常 → 用户可行动文案的映射（ux-audit P1-1）。

背景：service.py 曾把 `str(exc)[:500]` 原样塞进 ConnectivityResult.reason，
经 router 转成 400 detail 后，用户在界面上直接看到 pymysql 堆栈、
WinError 10061 与 sqlalche.me 链接。
"""
from __future__ import annotations

from local_ingestion.platform.datasource.service import classify_connectivity_error


def test_connection_refused_has_no_driver_internals():
    raw = (
        '(pymysql.err.OperationalError) (2003, "Can\'t connect to MySQL server on '
        "'localhost' ([WinError 10061] 由于目标计算机积极拒绝，无法连接。)\")"
        "(Background on this error at: https://sqlalche.me/e/21/e3q8)"
    )
    msg = classify_connectivity_error(RuntimeError(raw))
    assert "pymysql" not in msg
    assert "sqlalche.me" not in msg
    assert "WinError" not in msg
    assert "拒绝连接" in msg


def test_auth_failure_is_actionable():
    msg = classify_connectivity_error(
        RuntimeError(
            '(psycopg2.OperationalError) FATAL: password authentication failed for user "x"'
        )
    )
    assert "凭据" in msg or "账号" in msg


def test_timeout_is_actionable():
    msg = classify_connectivity_error(RuntimeError("(psycopg2.OperationalError) timeout expired"))
    assert "超时" in msg


def test_timed_out_variant_is_actionable():
    # "timed out" 不含 "timeout" 子串，曾漏判导致原始异常外泄
    msg = classify_connectivity_error(
        RuntimeError(
            "(pymysql.err.OperationalError) (2003, \"Can't connect to MySQL server "
            "on '10.255.255.1' (timed out)\")\n(Background on this error at: "
            "https://sqlalche.me/e/21/e3q8)"
        )
    )
    assert "pymysql" not in msg
    assert "sqlalche.me" not in msg
    assert "超时" in msg


def test_unknown_host_is_actionable():
    msg = classify_connectivity_error(
        RuntimeError("(psycopg2.OperationalError) could not translate host name 'nope' to address")
    )
    assert "主机地址" in msg


def test_unknown_error_is_bounded_and_prefixed():
    msg = classify_connectivity_error(RuntimeError("X" * 1000))
    assert msg.startswith("无法连接目标库")
    assert len(msg) <= 260
