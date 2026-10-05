import { cleanParams, get, post } from './client';
import type {
  ChangeEvent,
  ChangeStatistics,
  CursorPage,
} from '@/types';

/** MOD-06 数据变更。注意：后端**直接返回 snake_case**，未 camelize。 */

export interface ChangeListParams {
  datasourceId?: number | string;
  severity?: string;
  changeType?: string;
  entityType?: string;
  entityFqn?: string;
  since?: string;
  until?: string;
  ackStatus?: string;
  cursor?: string | null;
  limit?: number;
}

/**
 * 后端返回 `{changes, count}`（不是 `{items}`），而 DataTable 需要
 * `{items, next_cursor, total}` 信封，这里做归一化，避免列表永远为空。
 */
export async function listChanges(
  params: ChangeListParams = {},
): Promise<CursorPage<ChangeEvent> & { nextCursor?: string | null }> {
  const res = await get<Record<string, any>>(
    '/changes',
    cleanParams(params as Record<string, unknown>),
  );
  const items = Array.isArray(res)
    ? res
    : ((res?.items ?? res?.changes ?? []) as ChangeEvent[]);
  return {
    items,
    next_cursor: res?.next_cursor ?? res?.nextCursor ?? null,
    total: res?.total ?? res?.count ?? null,
  };
}

export function getChangeStatistics(params: { since?: string; until?: string } = {}) {
  return get<ChangeStatistics>('/changes/statistics', cleanParams(params));
}

export function getEntityHistory(
  entityType: string,
  entityFqn: string,
  params: { cursor?: string | null; limit?: number } = {},
) {
  return get<CursorPage<ChangeEvent> & { nextCursor?: string | null }>(
    `/changes/entities/${encodeURIComponent(entityType)}/${encodeURIComponent(entityFqn)}/history`,
    cleanParams(params as Record<string, unknown>),
  );
}

export function getChange(id: string | number) {
  return get<ChangeEvent>(`/changes/${id}`);
}

/** 变更确认（FR-7.9）。body: `{ ack_action, ack_by? }`。 */
export function ackChange(id: string | number, data: { ack_action: string; ack_by?: string }) {
  return post<ChangeEvent>(`/changes/${id}/ack`, data);
}
