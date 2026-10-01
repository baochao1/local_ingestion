"""Keyset（游标）分页公共组件（L3 / T-111）。

为什么禁止 OFFSET 分页
----------------------
``OFFSET n LIMIT m`` 在千万级元数据上是被禁止的（设计文档 §7.1）：数据库必须
先扫描并丢弃前 ``n`` 行，代价随 ``n`` 线性增长，深翻页直接超时。keyset 分页
把「第几页」换成「从哪一行之后继续」，把条件下推为可走索引的**行值比较**::

    SELECT id, fqn, name FROM catalog_table
    WHERE deleted_at IS NULL
      AND (fqn, id) > (:last_fqn, :last_id)
    ORDER BY fqn, id
    LIMIT :limit;

!!! 最容易踩的坑：排序键必须与索引前缀一致 !!!
----------------------------------------------
行值比较 ``(fqn, id) > (:fqn, :id)`` **只有在存在与排序键顺序一致的复合索引**
时才能走 index scan。一旦排序键与索引前缀不匹配（例如按 ``(name, id)`` 排序
却只有 ``(fqn, id)`` 索引），PostgreSQL 会退化为**全表排序 + 全表扫描**，
千万行下直接超时——这是 keyset 分页最常见的落地失败点（设计文档 §6.2）。

因此本模块提供 :func:`assert_index_prefix` 作为**开发期断言**：

* 排序 ``(fqn, id)`` → 索引必须含前缀 ``(fqn, id)``
* 等值筛选 + 排序 ``(datasource_id, fqn, id)`` → 索引 ``(datasource_id, fqn, id)``
* **游标键永远放在索引最后**；等值筛选列放前面，游标键放后面。
* 若筛选列（如 ``grade_level``）参与排序，索引须为 ``(grade_level, fqn, id)``。

游标格式
--------
``cursor = base64url(fqn + "|" + id)``（规范见设计文档 §7.1）。对外不透明：
前端只原样回传，不感知内部结构。用 URL-safe 字母表并去掉 ``=`` 填充。

总数问题
--------
keyset 无法高效提供精确 ``COUNT(*)``，故契约只给 ``approx_total``
（PG ``pg_class.reltuples`` 近似值）+ ``has_more``（设计文档 §7.4）。
**不要把 ``approx_total`` 当精确值计算分页数。**
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    TypeVar,
    Union,
)

from sqlalchemy import true, tuple_
from sqlalchemy.sql.elements import ColumnElement

from local_ingestion.platform.api.serialization import camelize

T = TypeVar("T")

#: 游标载荷分隔符。fqn 允许含 ``|``，故解析时用 rpartition 取最后一段为 id。
CURSOR_SEPARATOR: str = "|"

#: 默认每页条数。
DEFAULT_PAGE_SIZE: int = 50

#: 单页上限，防止一次性拉爆内存/网络。
MAX_PAGE_SIZE: int = 200

#: 模糊搜索结果深度上限（FR-11.7）：模糊匹配无稳定游标，必须限制深度。
SEARCH_MAX_DEPTH: int = 1000

#: 模糊搜索最大页数（1000 条 / 20 条每页）。
SEARCH_MAX_PAGES: int = 50


class CursorError(ValueError):
    """游标编解码错误的基类（继承 ``ValueError`` 便于上层统一捕获）。"""


class InvalidCursorError(CursorError):
    """游标无法解码：非法 base64 / 结构不符 / id 非整数 / 非字符串输入。"""


class KeysetIndexMismatchError(ValueError):
    """keyset 排序键与复合索引前缀不一致，会退化为全表排序。"""


def clamp_limit(limit: Optional[int], *, default: int = DEFAULT_PAGE_SIZE) -> int:
    """把外部传入的页大小收敛到 ``[1, MAX_PAGE_SIZE]``。"""
    if limit is None:
        return default
    try:
        value = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"limit 必须是整数，收到 {limit!r}") from exc
    if value <= 0:
        return default
    return min(value, MAX_PAGE_SIZE)


def _extract_keyset_values(
    last_row: Union[Mapping[str, Any], Sequence[Any], Any]
) -> Tuple[str, int]:
    """从「上一页最后一行」取出 ``(fqn, id)``。

    支持三种形态：``Mapping``（含 ``fqn``/``id``）、``(fqn, id)`` 序列、
    或带 ``.fqn``/``.id`` 属性的对象（SQLAlchemy ORM 实例、pydantic 模型）。
    """
    if isinstance(last_row, Mapping):
        try:
            return str(last_row["fqn"]), int(last_row["id"])
        except KeyError as exc:
            raise CursorError(
                f"行缺少 keyset 排序键 {exc}，需要 'fqn' 与 'id'"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise CursorError(
                f"行的 keyset 排序键无法编码：fqn 需为字符串、id 需为整数，"
                f"收到 {last_row!r}"
            ) from exc

    if isinstance(last_row, (tuple, list)) and len(last_row) == 2:
        try:
            return str(last_row[0]), int(last_row[1])
        except (TypeError, ValueError) as exc:
            raise CursorError(
                f"二元组游标键必须是 (fqn, id)，收到 {last_row!r}"
            ) from exc

    fqn = getattr(last_row, "fqn", None)
    row_id = getattr(last_row, "id", None)
    if fqn is None or row_id is None:
        raise CursorError(
            f"无法从 {type(last_row).__name__} 取 keyset 排序键："
            f"需要 .fqn 与 .id 属性"
        )
    try:
        return str(fqn), int(row_id)
    except (TypeError, ValueError) as exc:
        raise CursorError(
            f"对象的 keyset 排序键无法编码：fqn={fqn!r}, id={row_id!r}"
        ) from exc


def encode_cursor(last_row: Union[Mapping[str, Any], Sequence[Any], Any]) -> str:
    """把上一页最后一行编码成不透明游标 ``base64url("fqn|id")``。

    Args:
        last_row: 上一页最后一行。支持 ``Mapping`` / ``(fqn, id)`` 序列 /
            带 ``.fqn``、``.id`` 属性的对象（ORM 实例最常见）。

    Returns:
        URL-safe base64 字符串（已去掉 ``=`` 填充）。

    Raises:
        CursorError: 行缺少 ``fqn``/``id``，或类型无法编码。
    """
    fqn, row_id = _extract_keyset_values(last_row)
    payload = f"{fqn}{CURSOR_SEPARATOR}{row_id}"
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def decode_cursor(cursor: str) -> Tuple[str, int]:
    """把游标解回 ``(fqn, id)``，用于拼 keyset 的 ``WHERE`` 条件。

    Args:
        cursor: :func:`encode_cursor` 产出的字符串。

    Returns:
        ``(fqn, id)`` 二元组；``id`` 为 ``int``（DDL 中 ``id`` 为 BIGINT）。

    Raises:
        InvalidCursorError: 输入不是非空字符串、不是合法 base64、
            载荷不是 ``fqn|id`` 结构、或 id 不是整数。
    """
    if not isinstance(cursor, str):
        raise InvalidCursorError(f"游标必须是字符串，收到 {type(cursor).__name__}")
    raw = cursor.strip()
    if not raw:
        raise InvalidCursorError("游标不能为空字符串")

    try:
        raw_bytes = raw.encode("ascii")
    except UnicodeEncodeError as exc:
        raise InvalidCursorError(f"游标含非 ASCII 字符: {cursor!r}") from exc

    padding = "=" * (-len(raw_bytes) % 4)
    try:
        payload = base64.urlsafe_b64decode(
            raw_bytes + padding.encode("ascii")
        ).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursorError(f"游标不是合法的 base64 编码: {cursor!r}") from exc

    if not payload:
        raise InvalidCursorError(f"游标解码后为空: {cursor!r}")

    fqn, sep, raw_id = payload.rpartition(CURSOR_SEPARATOR)
    if not sep or not fqn:
        raise InvalidCursorError(
            f"游标载荷格式应为 'fqn{CURSOR_SEPARATOR}id'，实际为 {payload!r}"
        )
    try:
        row_id = int(raw_id)
    except ValueError as exc:
        raise InvalidCursorError(
            f"游标中的 id 不是整数: {raw_id!r}（载荷 {payload!r}）"
        ) from exc
    return fqn, row_id


def build_keyset_clause(
    sort_keys_values: Sequence[Tuple[Any, Any]],
) -> ColumnElement[bool]:
    """生成行值比较条件 ``(k1, k2, ...) > (:v1, :v2, ...)``。

    Args:
        sort_keys_values: ``[(列或列表达式, 上一页该列的值), ...]``，
            **顺序必须与 ``ORDER BY`` 完全一致**，否则游标语义错误（会漏行/重行）。

    Returns:
        可直接传给 ``Select.where()`` 的布尔表达式；空序列返回 SQL ``true()``
        （即「首页不附加游标条件」）。

    Warning:
        这些列必须对应一个**前缀一致**的复合索引，否则全表排序。用
        :func:`assert_index_prefix` 在开发期校验。
    """
    if not sort_keys_values:
        return true()
    columns = [item[0] for item in sort_keys_values]
    values = [item[1] for item in sort_keys_values]
    return tuple_(*columns) > tuple_(*values)


def keyset_clause_from_cursor(
    cursor: Optional[str],
    fqn_column: Any,
    id_column: Any,
) -> ColumnElement[bool]:
    """从游标一步生成 ``(fqn, id) > (:fqn, :id)``；``cursor`` 为空则首页无条件。"""
    if cursor is None or not cursor.strip():
        return true()
    last_fqn, last_id = decode_cursor(cursor)
    return build_keyset_clause([(fqn_column, last_fqn), (id_column, last_id)])


def assert_index_prefix(
    sort_keys: Sequence[str],
    index_columns: Sequence[str],
) -> None:
    """开发期断言：keyset 排序键必须是复合索引的**前缀**。

    Args:
        sort_keys: ``ORDER BY`` 的列名顺序，如 ``("datasource_id", "fqn", "id")``。
        index_columns: 实际复合索引的列顺序。

    Raises:
        KeysetIndexMismatchError: 排序键不是索引前缀，或任一方为空。
    """
    if not sort_keys:
        raise KeysetIndexMismatchError("keyset 排序键不能为空")
    if not index_columns:
        raise KeysetIndexMismatchError("索引列不能为空，keyset 必须有匹配的复合索引")

    size = len(sort_keys)
    if len(index_columns) < size:
        raise KeysetIndexMismatchError(
            f"排序键 {tuple(sort_keys)} 长度超过索引 {tuple(index_columns)}："
            f"索引无法覆盖排序键，keyset 会退化为全表排序"
        )
    if tuple(index_columns[:size]) != tuple(sort_keys):
        raise KeysetIndexMismatchError(
            f"排序键 {tuple(sort_keys)} 不是索引 {tuple(index_columns)} 的前缀："
            f"排序键必须与索引前缀一致（筛选列在前、游标键在后），"
            f"否则 keyset 会退化为全表排序"
        )


@dataclass
class KeysetPage(Generic[T]):
    """keyset 分页统一响应结构（T-111 契约）。

    Attributes:
        items: 当前页数据（已剔除用于探测 ``has_more`` 的多取行）。
        next_cursor: 下一页游标；``has_more`` 为假时为 ``None``。
        has_more: 是否还有下一页。由「多取一行」探测得出，不依赖总数。
        approx_total: 近似总数（PG ``reltuples``）；无法估算时为 ``None``。
            **不是精确值**，不要用于计算「共多少页」。
    """

    items: List[T]
    next_cursor: Optional[str]
    has_more: bool
    approx_total: Optional[int] = None

    @classmethod
    def build(
        cls,
        rows: Sequence[T],
        limit: int,
        *,
        approx_total: Optional[int] = None,
        cursor_builder: Callable[[Any], str] = encode_cursor,
    ) -> "KeysetPage[T]":
        """从「多取一行」的结果构造分页响应。

        约定：调用方查询时 ``LIMIT limit + 1``。若取回行数 ``> limit``，
        说明还有下一页，剔除多余行并据当前页最后一行生成游标。

        Raises:
            ValueError: ``limit`` 非正数。
        """
        if limit <= 0:
            raise ValueError(f"limit 必须为正整数，收到 {limit}")

        materialized: List[T] = list(rows)
        has_more = len(materialized) > limit
        items = materialized[:limit]
        next_cursor = cursor_builder(items[-1]) if has_more and items else None
        return cls(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            approx_total=approx_total,
        )

    def to_dict(self, *, camel: bool = True) -> Dict[str, Any]:
        """转成响应 dict，并对 ``items`` 递归做 camelCase 序列化（复用 T-112）。

        Args:
            camel: ``True``（默认，API 对外）输出 ``nextCursor`` / ``hasMore`` /
                ``approxTotal``；``False`` 输出计划文档中的 snake 名。
        """
        if camel:
            return {
                "items": camelize(self.items),
                "nextCursor": self.next_cursor,
                "hasMore": self.has_more,
                "approxTotal": self.approx_total,
            }
        return {
            "items": camelize(self.items),
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
            "approx_total": self.approx_total,
        }
