"""分类分级接口（MOD-05）。

MOD-05 §5 定义了 9 个接口，此前**一个都没实现**——分级结果只能被搜索的
``gradeMin`` 筛选间接消费，用户「能触发分级任务，但看不到任何结果」。

本路由先暴露只读部分（分级结果、覆盖率、敏感资产清单、分级标准、识别规则），
它们是「分级结果界面」的数据源。

级别阶梯以 :mod:`platform.classification.rules` 为准（1–5 级），
通过 ``/ladder`` 暴露给前端，避免界面自己硬编码一套。
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ...api.pagination import InvalidCursorError, clamp_limit
from ...api.serialization import camelize
from ...classification.queries import (
    GRADE_LADDER,
    SENSITIVE_THRESHOLD,
    ClassificationQueryService,
    CoverageSummary,
    DatasourceCoverage,
    gb_level_of,
)

router = APIRouter(prefix="/api/v1/classification", tags=["Classification"])


def get_query_service() -> ClassificationQueryService:
    """生产接线：读 ``catalog_*`` 与 ``classification_*`` 表。"""
    from ...classification.queries import SqlClassificationQueryRepository
    from ...storage.session import session_scope

    return ClassificationQueryService(SqlClassificationQueryRepository(session_scope))


def _coverage_row(cov: DatasourceCoverage) -> Dict[str, Any]:
    """``DatasourceCoverage`` → dict，补上 ``asdict`` 拿不到的派生比例。"""
    row = asdict(cov)
    row["coverage_ratio"] = cov.coverage_ratio
    return row


def _coverage_payload(summary: CoverageSummary) -> Dict[str, Any]:
    payload = asdict(summary)
    payload["by_datasource"] = [_coverage_row(d) for d in summary.by_datasource]
    payload["coverage_ratio"] = summary.coverage_ratio
    payload["sensitive_ratio"] = summary.sensitive_ratio
    payload["sensitive_threshold"] = SENSITIVE_THRESHOLD
    return payload


@router.get("/ladder")
def get_ladder() -> Dict[str, Any]:
    """分级阶梯定义（1–5）。前端据此渲染级别标签与说明，避免各写一套。"""
    return camelize(
        {
            "threshold": SENSITIVE_THRESHOLD,
            "levels": [
                {"level": lvl, **meta} for lvl, meta in sorted(GRADE_LADDER.items())
            ],
        }
    )


@router.get("/coverage")
def get_coverage(
    datasourceId: Optional[int] = Query(None, description="只看某个数据源"),
    svc: ClassificationQueryService = Depends(get_query_service),
) -> Dict[str, Any]:
    """分级覆盖率（FR-9.11）：总量、已分级、敏感占比、级别分布、按数据源分组。"""
    return camelize(_coverage_payload(svc.coverage(datasource_id=datasourceId)))


@router.get("/sensitive-assets")
def list_sensitive_assets(
    gradeMin: int = Query(
        SENSITIVE_THRESHOLD, description="最低级别（含），默认 2＝业务敏感"
    ),
    datasourceId: Optional[int] = None,
    entityType: str = Query("column", description="column | table"),
    keyword: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: Optional[int] = None,
    svc: ClassificationQueryService = Depends(get_query_service),
) -> Dict[str, Any]:
    """敏感资产清单（FR-9.8）：默认字段级，带所属表与命中原因。"""
    if entityType not in ("column", "table"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"entityType 只能是 column 或 table，收到 {entityType!r}",
        )
    try:
        page = svc.sensitive_assets(
            grade_min=max(1, gradeMin),
            datasource_id=datasourceId,
            entity_type=entityType,
            keyword=keyword,
            cursor=cursor,
            limit=clamp_limit(limit),
        )
    except InvalidCursorError as exc:
        raise HTTPException(
            # 游标来自用户输入，回显原文会把任意内容反射给用户
            status_code=status.HTTP_400_BAD_REQUEST, detail="游标无效或已过期，请重新发起查询"
        ) from exc
    return page.to_dict()


@router.get("/sensitive-assets/export")
def export_sensitive_assets(
    gradeMin: int = Query(SENSITIVE_THRESHOLD, description="最低级别（含），默认 2＝业务敏感"),
    datasourceId: Optional[int] = None,
    entityType: str = Query("column", description="column | table"),
    keyword: Optional[str] = None,
    svc: ClassificationQueryService = Depends(get_query_service),
):
    """合规清单导出（对标 S0-1，标书必考项）。

    此前分级结果只能"在界面上看"，没有任何导出出口，而"分类分级结果管理 /
    报表导出"是分类分级类项目的必考项。导出含 **GB/T 43697-2024 国标级别列**
    （核心/重要/一般），可直接作为分级结果清单提交。
    """
    import csv
    import io as _io
    from datetime import datetime as _dt, timezone as _tz

    from fastapi.responses import StreamingResponse

    if entityType not in ("column", "table"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"entityType 只能是 column 或 table，收到 {entityType!r}",
        )

    rows: List[Any] = []
    cursor: Optional[str] = None
    for _ in range(50):  # 翻页上限，防止游标异常导致死循环
        page = svc.sensitive_assets(
            grade_min=max(1, gradeMin),
            datasource_id=datasourceId,
            entity_type=entityType,
            keyword=keyword,
            cursor=cursor,
            limit=clamp_limit(500),
        )
        rows.extend(page.items)
        if not page.next_cursor:
            break
        cursor = page.next_cursor

    buf = _io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["数据源ID", "所属表", "资产FQN", "名称", "数据类型", "业务级别",
         "业务级别名称", "国标级别(GB/T 43697)", "是否个人信息", "命中原因", "标签"]
    )
    for r in rows:
        meta = GRADE_LADDER.get(int(r.grade_level), {})
        writer.writerow([
            r.datasource_id,
            r.table_name or "",
            r.fqn,
            r.name,
            r.data_type or "",
            r.grade_level,
            meta.get("label", ""),
            gb_level_of(r.grade_level),
            "是" if r.is_pii else "否",
            r.grade_reason or "",
            "|".join(r.tags or []),
        ])

    # Excel 打开中文 CSV 需要 BOM，否则乱码
    payload = "\ufeff" + buf.getvalue()
    stamp = _dt.now(_tz.utc).strftime("%Y%m%d")
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="sensitive-assets-{stamp}.csv"',
            "X-Row-Count": str(len(rows)),
        },
    )


@router.get("/tags")
def list_tags(
    svc: ClassificationQueryService = Depends(get_query_service),
) -> Dict[str, Any]:
    """分级标准（``classification_tag``）。"""
    tags: List[Any] = svc.tags()
    return camelize({"items": [asdict(t) for t in tags], "total": len(tags)})


@router.get("/rules")
def list_rules(
    svc: ClassificationQueryService = Depends(get_query_service),
) -> Dict[str, Any]:
    """识别规则（``classification_rule``）。"""
    rules: List[Any] = svc.rules()
    return camelize({"items": [asdict(r) for r in rules], "total": len(rules)})


# --------------------------------------------------------------- 人工复核（FR-9.5）


class AnnotateRequest(BaseModel):
    """人工修正某个实体的级别。"""

    gradeLevel: int = Field(..., ge=1, le=9, description="人工判定的级别（1–9，本产品用 1–5）")
    actor: Optional[str] = Field(None, description="操作者（当前无认证，由调用方传入）")
    reason: Optional[str] = Field(None, description="修正理由（留档）")
    entityFqn: Optional[str] = Field(
        None, description="实体 FQN，仅用于审批列表里展示可读对象"
    )


def get_annotation_service() -> Any:
    """生产接线：写 ``entity_tag`` 并回写 catalog 行。"""
    from ...classification.annotation import AnnotationService
    from ...storage.session import session_scope

    return AnnotationService(session_scope)


def _submit_annotation_approval(
    *, entity_type: str, entity_id: int, body: AnnotateRequest
) -> Any:
    """把高分级的修正提交审批（不进 catalog 行，批准后才生效）。"""
    from ...classification.annotation import PendingAnnotation
    from ...governance.models import ApprovalInput

    # governance router 位于 local_ingestion/api/routers/（非 platform/），
    # 相对导入层级不同，故用绝对导入避免数目数错。
    from local_ingestion.api.routers.governance import get_approval_service

    pending = PendingAnnotation(
        entity_type=entity_type,
        entity_id=entity_id,
        grade_level=body.gradeLevel,
        applied_by=body.actor,
    )
    target = body.entityFqn or f"{entity_type} #{entity_id}"
    return get_approval_service().create(
        ApprovalInput(
            resource_type="classification",
            resource_fqn=body.entityFqn or f"{entity_type}:{entity_id}",
            action_type="sensitive_tag",
            title=f"分级修正：{target} → L{body.gradeLevel}",
            requested_by=body.actor or "unknown",
            priority="P2",
            reason=pending.to_reason(),
        )
    )


@router.post("/entities/{entity_type}/{entity_id}/tags")
def annotate_entity(
    entity_type: str,
    entity_id: int,
    body: AnnotateRequest,
    svc: Any = Depends(get_annotation_service),
) -> Dict[str, Any]:
    """人工修正级别（FR-9.5）。

    按风险分级审批：**L1–L3 立即生效**（日常修正多为降级误报），
    **L4/L5 提交审批**后才生效——否则审批队列会被日常修正淹没。

    生效的修正会写入 ``entity_tag``（``source='manual'``）并同步回写
    ``grade_level``，引擎在重跑时跳过该实体。
    """
    from ...classification.annotation import (
        APPROVAL_REQUIRED_GRADE,
        AnnotationError,
        EntityNotFound,
    )

    if body.gradeLevel >= APPROVAL_REQUIRED_GRADE:
        approval = _submit_annotation_approval(
            entity_type=entity_type, entity_id=entity_id, body=body
        )
        return camelize(
            {
                "pendingApproval": True,
                "approvalId": approval.id,
                "entityType": entity_type,
                "entityId": entity_id,
                "gradeLevel": body.gradeLevel,
            }
        )

    try:
        ann = svc.annotate(
            entity_type=entity_type,
            entity_id=entity_id,
            grade_level=body.gradeLevel,
            actor=body.actor,
        )
    except AnnotationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except EntityNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return camelize({"pendingApproval": False, **asdict(ann)})


@router.delete(
    "/entities/{entity_type}/{entity_id}/tags", status_code=status.HTTP_204_NO_CONTENT
)
def clear_annotation(
    entity_type: str,
    entity_id: int,
    svc: Any = Depends(get_annotation_service),
) -> None:
    """撤销人工标注，实体重新交由引擎判定。"""
    from ...classification.annotation import AnnotationError

    try:
        svc.clear(entity_type=entity_type, entity_id=entity_id)
    except AnnotationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
