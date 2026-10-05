import { cleanParams, currentActor, del, get, post } from './client';
import type { CursorPage } from '@/types';

/** MOD-05 分类分级：结果查询、覆盖率、敏感资产、分级标准与识别规则。 */

/** 级别阶梯（后端为单一事实来源）。 */
export interface ClassificationLevel {
  level: number;
  code: string;
  label: string;
  description: string;
  /** GB/T 43697-2024 对应级别：核心 / 重要 / 一般（后端 GRADE_LADDER 提供）。 */
  gbLevel?: string;
}

export interface LadderResponse {
  /** 达到该级别即计入「敏感资产」。 */
  threshold: number;
  levels: ClassificationLevel[];
}

export interface DatasourceCoverage {
  datasourceId: number;
  name?: string | null;
  totalColumns: number;
  gradedColumns: number;
  sensitiveColumns: number;
  totalTables: number;
  gradedTables: number;
  coverageRatio: number;
}

export interface CoverageSummary {
  totalColumns: number;
  gradedColumns: number;
  sensitiveColumns: number;
  totalTables: number;
  gradedTables: number;
  /** 级别 → 字段数；`ungraded` 键为未分级（**不计入 L1**）。 */
  gradeDistribution: Record<string, number>;
  byDatasource: DatasourceCoverage[];
  coverageRatio: number;
  sensitiveRatio: number;
  sensitiveThreshold: number;
}

export interface SensitiveAsset {
  id: number;
  entityType: 'column' | 'table';
  name: string;
  fqn: string;
  datasourceId: number;
  gradeLevel: number;
  gradeCode?: string | null;
  tableId?: number | null;
  tableName?: string | null;
  tableFqn?: string | null;
  dataType?: string | null;
  /** 引擎给出的判定原因（credential / personal / identifier…）。 */
  gradeReason?: string | null;
  isPii?: boolean;
  tags?: string[];
}

export interface ClassificationTag {
  id: number;
  tagKey: string;
  tagName: string;
  category?: string | null;
  gradeLevel?: number | null;
  gradeCode?: string | null;
  color?: string | null;
  description?: string | null;
  enabled: boolean;
}

export interface ClassificationRule {
  id: number;
  tagKey: string;
  /** column_name | regex | data_type | sample_verify */
  ruleKind: string;
  pattern?: string | null;
  confidence: number;
  priority: number;
  enabled: boolean;
}

export interface SensitiveAssetParams {
  gradeMin?: number;
  datasourceId?: number | string;
  entityType?: 'column' | 'table';
  keyword?: string;
  cursor?: string | null;
  limit?: number;
}

export function getLadder() {
  return get<LadderResponse>('/classification/ladder');
}

export function getCoverage(datasourceId?: number | string) {
  return get<CoverageSummary>(
    '/classification/coverage',
    cleanParams({ datasourceId } as Record<string, unknown>),
  );
}

export function listSensitiveAssets(params: SensitiveAssetParams = {}) {
  return get<CursorPage<SensitiveAsset>>(
    '/classification/sensitive-assets',
    cleanParams(params as Record<string, unknown>),
  );
}

export function listClassificationTags() {
  return get<{ items: ClassificationTag[]; total: number }>('/classification/tags');
}

export function listClassificationRules() {
  return get<{ items: ClassificationRule[]; total: number }>('/classification/rules');
}

// --------------------------------------------------------------- 人工复核（FR-9.5）

export interface AnnotationResult {
  entityType: 'column' | 'table';
  entityId: number;
  entityFqn?: string | null;
  gradeLevel: number;
  gradeCode: string;
  tagKey: string;
  source: string;
  appliedBy?: string | null;
}

/**
 * 人工修正的响应。两种形态：
 * - `pendingApproval: true` —— L4/L5 的高敏提升需审批，**尚未生效**，改走 `approvalId`；
 * - `pendingApproval: false` —— 已直接生效。
 */
export type AnnotateResponse = {
  pendingApproval: boolean;
  approvalId?: number;
  entityFqn?: string | null;
  gradeCode?: string;
  tagKey?: string;
  source?: string;
  appliedBy?: string | null;
} & Pick<AnnotationResult, 'entityType' | 'entityId' | 'gradeLevel'>;

/** 人工修正级别。L1–L3 立即生效；L4/L5 提交审批后生效（FR-9.5）。 */
export function annotateEntity(
  entityType: 'column' | 'table',
  entityId: number,
  body: { gradeLevel: number; reason?: string; actor?: string; entityFqn?: string },
) {
  return post<AnnotateResponse>(`/classification/entities/${entityType}/${entityId}/tags`, {
    ...body,
    actor: currentActor(body.actor),
  });
}

/** 撤销人工标注，实体重新交由引擎判定。 */
export function clearAnnotation(entityType: 'column' | 'table', entityId: number) {
  return del<void>(`/classification/entities/${entityType}/${entityId}/tags`);
}
