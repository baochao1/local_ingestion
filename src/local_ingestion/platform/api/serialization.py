"""camelCase ⇄ snake_case 双向序列化（L3 / T-112）。

依据 ADR-8（``doc/design/03-openmetadata-compatibility.md`` §4）：

* **数据库层（PG）** 用 ``snake_case``：``fqn``、``data_type``、``numeric_precision``
* **内部模型 / API / 交换层** 用 ``camelCase``：对齐 OpenMetadata schema

因此转换只发生在**边界**（API 出入参、导入/导出），内部模型本身不改。
现有 ``schema/data/table.py`` 已是 OpenMetadata camelCase 风格
（``fullyQualifiedName`` / ``dataTypeDisplay`` / ``ordinalPosition``），
故 ``camelize`` 对它们应保持恒等（单 token 不改写）。

边界规则
--------
* 首字母缩略词整体小写：``fqn`` → ``fqn``，``FQNHash`` → ``fqn_hash``
* 数字作为 token 的一部分，不额外切开：``sha256Hash`` → ``sha256_hash``
* 连续大写（缩略词）后接单词时正确断词：``HTTPServer`` → ``http_server``
* 已是 snake_case 的输入幂等：``data_type`` → ``data_type``

已知限制
--------
``to_snake(to_camel(s)) == s`` 对**数字紧邻下划线**的名字不保证成立：
``col_2_name`` → ``col2Name`` → ``col2_name``（下划线被数字吸收）。
这是 camelCase 的固有信息损失，若需严格往返，请在边界层维护显式字段映射表。
"""
from __future__ import annotations

import re
from typing import Any, List, Mapping, Tuple

from pydantic import BaseModel

#: 递归深度上限，防止自引用/环结构导致无限递归。
MAX_DEPTH: int = 32

#: ``HTTPServer`` → ``HTTP_Server``：连续大写后接「大写+小写」处断开。
_ACRONYM_RUN_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")

#: ``dataType`` → ``data_Type``；``sha256Hash`` → ``sha256_Hash``（数字也触发）。
_LOWER_OR_DIGIT_TO_UPPER = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class SerializationDepthError(ValueError):
    """嵌套结构超过 ``MAX_DEPTH``，可能存在循环引用。"""


def to_camel(snake_str: str) -> str:
    """snake_case → camelCase。

    ``fqn`` → ``fqn``；``data_type`` → ``dataType``；
    ``numeric_precision`` → ``numericPrecision``；``id`` → ``id``。

    单 token（无下划线）原样返回，因此已 camelCase 的名字恒等。
    """
    if not snake_str or "_" not in snake_str:
        return snake_str
    head, *rest = snake_str.split("_")
    return head + "".join(token[:1].upper() + token[1:] for token in rest if token)


def to_snake(camel_str: str) -> str:
    """camelCase / PascalCase → snake_case。

    ``dataType`` → ``data_type``；``fullyQualifiedName`` → ``fully_qualified_name``；
    ``HTTPServer`` → ``http_server``；``parseFQNValue`` → ``parse_fqn_value``；
    ``sha256Hash`` → ``sha256_hash``；``fqn`` → ``fqn``；``data_type`` → ``data_type``。
    """
    if not camel_str:
        return camel_str
    stage1 = _ACRONYM_RUN_BOUNDARY.sub("_", camel_str)
    stage2 = _LOWER_OR_DIGIT_TO_UPPER.sub("_", stage1)
    return stage2.lower()


def _convert_key(key: Any, key_fn: Any) -> Any:
    """只对字符串 key 做转换，非字符串 key（如 int）原样保留。"""
    return key_fn(key) if isinstance(key, str) else key


def _convert(obj: Any, key_fn: Any, max_depth: int, depth: int) -> Any:
    """按 ``key_fn`` 递归转换容器结构的 key（不改动字符串 value）。"""
    if depth > max_depth:
        raise SerializationDepthError(
            f"结构嵌套超过 {max_depth} 层，可能存在循环引用"
        )

    if isinstance(obj, BaseModel):
        # pydantic v2：转成纯 dict 后继续递归，嵌套模型也会被展开。
        return _convert(obj.model_dump(), key_fn, max_depth, depth + 1)

    if isinstance(obj, Mapping):
        return {
            _convert_key(k, key_fn): _convert(v, key_fn, max_depth, depth + 1)
            for k, v in obj.items()
        }

    if isinstance(obj, list):
        return [_convert(v, key_fn, max_depth, depth + 1) for v in obj]

    if isinstance(obj, tuple):
        return tuple(_convert(v, key_fn, max_depth, depth + 1) for v in obj)

    return obj


def camelize(obj: Any, *, max_depth: int = MAX_DEPTH) -> Any:
    """把 snake_case 结构递归转成 camelCase。

    支持 ``dict`` / ``list`` / ``tuple`` / pydantic v2 model（走 ``model_dump()``）
    的任意嵌套组合；叶子值（含字符串 value）原样返回——**只改 key，不改 value**。

    Raises:
        SerializationDepthError: 超过 ``max_depth``。
    """
    return _convert(obj, to_camel, max_depth, 0)


def snakify(obj: Any, *, max_depth: int = MAX_DEPTH) -> Any:
    """把 camelCase 结构递归转成 snake_case（落库前用）。

    与 :func:`camelize` 完全对称。
    """
    return _convert(obj, to_snake, max_depth, 0)


def roundtrip_check(sample: Mapping[str, Any]) -> Tuple[bool, List[str]]:
    """调试/单测辅助：校验 ``snakify(camelize(x)) == x`` 是否成立。

    Returns:
        ``(是否全部通过, 不一致的 key 列表)``。
    """
    restored = snakify(camelize(dict(sample)))
    mismatched = [
        str(key)
        for key in sample
        if str(key) not in restored or restored[str(key)] is not sample[key]
    ]
    return (not mismatched, mismatched)
