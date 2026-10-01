"""API 公共组件（L3）：keyset 分页（T-111）与 camelCase 序列化（T-112）。

本包是 L3 本地扩展区的新增公共组件，供 MOD-01 / MOD-02 / MOD-06 / MOD-09
的列表接口复用，避免各模块各写一套分页（审核 R3 / PG-3）。

注意：与顶层 `local_ingestion.api`（另一套既有的 FastAPI 服务）无关，
本包不引入 FastAPI 依赖，纯 Python 可测。
"""

from local_ingestion.platform.api.pagination import (
    CURSOR_SEPARATOR,
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    SEARCH_MAX_DEPTH,
    SEARCH_MAX_PAGES,
    CursorError,
    InvalidCursorError,
    KeysetIndexMismatchError,
    KeysetPage,
    assert_index_prefix,
    build_keyset_clause,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    keyset_clause_from_cursor,
)
from local_ingestion.platform.api.serialization import (
    SerializationDepthError,
    camelize,
    snakify,
    to_camel,
    to_snake,
)

__all__ = [
    "CURSOR_SEPARATOR",
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "SEARCH_MAX_DEPTH",
    "SEARCH_MAX_PAGES",
    "CursorError",
    "InvalidCursorError",
    "KeysetIndexMismatchError",
    "KeysetPage",
    "assert_index_prefix",
    "build_keyset_clause",
    "clamp_limit",
    "decode_cursor",
    "encode_cursor",
    "keyset_clause_from_cursor",
    "SerializationDepthError",
    "camelize",
    "snakify",
    "to_camel",
    "to_snake",
]
