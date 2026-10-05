"""人工标注（MOD-05 / FR-9.5）。

设计约定原文：**``source='manual'`` 的标签，自动引擎不得覆盖。**

在此之前这条约定只存在于注释里——没有任何代码写入 ``entity_tag``，
分级结果全部由引擎推导，用户无法纠正误判。后果在界面上很直观：
``name`` 这类字段被规则一律判为 L3「个人信息」（包括表名、库名），
而没有任何途径把它改回来。

本模块补上这条路径：

1. 写入 ``entity_tag``（``tag_key='MANUAL'``，``source='manual'``）作为**权威标记**；
2. 同步回写 ``catalog_column`` / ``catalog_table`` 的 ``grade_level`` / ``grade_code``，
   让下游（检索筛选、变更影响判定）立即看到人工结论；
3. 引擎在重跑时通过 :meth:`AnnotationService.manual_entity_ids` 拿到这些实体并跳过。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, Optional, Set

import structlog

from .rules import GRADE_CODES

logger = structlog.get_logger()

#: 人工标注使用的固定标签键。一个实体最多一条 manual 记录
#: （``uq_etag_entity_tag`` 对 ``(entity_type, entity_id, tag_key)`` 唯一）。
MANUAL_TAG_KEY = "MANUAL"

#: 允许人工标注的实体类型。
SUPPORTED_TYPES = ("column", "table")

#: 达到该级别（含）的人工修正**需要审批**才生效。
#:
#: 按风险分级审批，而非一刀切：L1–L3 的修正直接生效（绝大多数误报都是"降级"），
#: 只有把字段提升到 L4 高敏 / L5 机密才走审批——否则审批队列会被日常修正淹没，
#: 最终沦为批量点「通过」的形式。
APPROVAL_REQUIRED_GRADE = 4

#: 待审批载荷的标识，写入 ``approval_request.reason``。
PENDING_KIND = "classification.annotate"


class AnnotationError(ValueError):
    """人工标注入参非法。"""


class EntityNotFound(LookupError):
    """目标实体不存在或已删除。"""


@dataclass
class Annotation:
    """一次人工标注的结果。"""

    entity_type: str
    entity_id: int
    entity_fqn: Optional[str]
    grade_level: int
    grade_code: str
    tag_key: str = MANUAL_TAG_KEY
    source: str = "manual"
    applied_by: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity_fqn": self.entity_fqn,
            "grade_level": self.grade_level,
            "grade_code": self.grade_code,
            "tag_key": self.tag_key,
            "source": self.source,
            "applied_by": self.applied_by,
        }


def _model_for(entity_type: str) -> Any:
    """按实体类型取 catalog 模型（延迟导入，避免模块级循环依赖）。"""
    from ..storage.models_core import CatalogColumn, CatalogTable

    if entity_type == "column":
        return CatalogColumn
    if entity_type == "table":
        return CatalogTable
    raise AnnotationError(
        f"不支持人工标注的实体类型：{entity_type!r}（仅支持 {' / '.join(SUPPORTED_TYPES)}）"
    )


class AnnotationService:
    """人工复核：覆盖引擎的判定，并让结论对下游立即生效。"""

    def __init__(self, session_factory: Any) -> None:
        self._sf = session_factory

    def annotate(
        self,
        *,
        entity_type: str,
        entity_id: int,
        grade_level: int,
        actor: Optional[str] = None,
    ) -> Annotation:
        """把实体的级别改为人工指定的值。

        Raises:
            AnnotationError: 类型不支持或级别越界。
            EntityNotFound: 实体不存在 / 已软删除。
        """
        from ..storage.models_governance import EntityTag

        if not isinstance(grade_level, int) or not (1 <= grade_level <= 9):
            raise AnnotationError(f"级别必须是 1–9 的整数，收到 {grade_level!r}")
        model = _model_for(entity_type)
        grade_code = GRADE_CODES.get(grade_level, f"L{grade_level}")

        with self._sf() as s:
            row = s.get(model, entity_id)
            if row is None or getattr(row, "deleted_at", None) is not None:
                raise EntityNotFound(f"{entity_type} #{entity_id} 不存在或已删除")

            tag = (
                s.query(EntityTag)
                .filter(
                    EntityTag.entity_type == entity_type,
                    EntityTag.entity_id == entity_id,
                    EntityTag.tag_key == MANUAL_TAG_KEY,
                    EntityTag.deleted_at.is_(None),
                )
                .one_or_none()
            )
            if tag is None:
                tag = EntityTag(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    tag_key=MANUAL_TAG_KEY,
                    source="manual",
                )
                s.add(tag)

            tag.entity_fqn = getattr(row, "fqn", None)
            tag.grade_level = grade_level
            tag.confidence = 1.0
            tag.applied_by = actor
            tag.source = "manual"

            # 回写 catalog 行：检索筛选（gradeMin）与变更影响判定都读这里，
            # 只写 entity_tag 的话人工结论不会立即生效。
            row.grade_level = grade_level
            row.grade_code = grade_code

            s.commit()
            fqn = getattr(row, "fqn", None)

        result = Annotation(
            entity_type=entity_type,
            entity_id=entity_id,
            entity_fqn=fqn,
            grade_level=grade_level,
            grade_code=grade_code,
            applied_by=actor,
        )
        logger.info("classification_annotated", **result.as_dict())
        return result

    def clear(self, *, entity_type: str, entity_id: int) -> None:
        """撤销人工标注（实体随后可由引擎重新判定）。"""
        from ..storage.models_governance import EntityTag

        _model_for(entity_type)  # 类型校验
        with self._sf() as s:
            tag = (
                s.query(EntityTag)
                .filter(
                    EntityTag.entity_type == entity_type,
                    EntityTag.entity_id == entity_id,
                    EntityTag.tag_key == MANUAL_TAG_KEY,
                    EntityTag.deleted_at.is_(None),
                )
                .one_or_none()
            )
            if tag is not None:
                s.delete(tag)
                s.commit()

    def manual_entity_ids(
        self, entity_type: str, entity_ids: Optional[Iterable[int]] = None
    ) -> Set[int]:
        """取已被人工标注的实体 ID，供引擎在重跑时跳过（FR-9.5）。"""
        from ..storage.models_governance import EntityTag

        with self._sf() as s:
            q = s.query(EntityTag.entity_id).filter(
                EntityTag.entity_type == entity_type,
                EntityTag.source == "manual",
                EntityTag.deleted_at.is_(None),
            )
            if entity_ids is not None:
                ids = list(entity_ids)
                if not ids:
                    return set()
                q = q.filter(EntityTag.entity_id.in_(ids))
            return {row[0] for row in q.all()}


@dataclass
class PendingAnnotation:
    """等待审批的分级修正。

    载荷编码进 ``approval_request.reason``（JSON）——审批表没有 payload 字段，
    而为此加一列会牵动 DDL 迁移；载荷很小且只有本模块解析，故直接复用 reason。
    """

    entity_type: str
    entity_id: int
    grade_level: int
    applied_by: Optional[str] = None

    def to_reason(self) -> str:
        return json.dumps(
            {"kind": PENDING_KIND, **asdict(self)}, ensure_ascii=False
        )

    @classmethod
    def from_reason(cls, reason: Optional[str]) -> Optional["PendingAnnotation"]:
        """解析审批记录的 ``reason``；不是本模块的载荷则返回 ``None``。"""
        if not reason:
            return None
        try:
            data = json.loads(reason)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("kind") != PENDING_KIND:
            return None
        try:
            return cls(
                entity_type=str(data["entity_type"]),
                entity_id=int(data["entity_id"]),
                grade_level=int(data["grade_level"]),
                applied_by=data.get("applied_by"),
            )
        except (KeyError, TypeError, ValueError):
            logger.warning("pending_annotation_malformed", reason=reason)
            return None


def apply_approved_annotation(reason: Optional[str], session_factory: Any) -> bool:
    """审批通过后落地一次修正。

    Returns:
        是否真的应用了（``False`` 表示该审批不是分级修正载荷）。

    Note:
        审批流程与分级是两个模块，这里由审批侧在通过后调用，
        避免 governance 反向依赖 classification 的内部实现。
    """
    pending = PendingAnnotation.from_reason(reason)
    if pending is None:
        return False
    AnnotationService(session_factory).annotate(
        entity_type=pending.entity_type,
        entity_id=pending.entity_id,
        grade_level=pending.grade_level,
        actor=pending.applied_by,
    )
    logger.info("classification_approval_applied", **asdict(pending))
    return True
