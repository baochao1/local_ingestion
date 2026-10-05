import { cleanParams, del, get, post, put } from './client';
import type {
  DataSource,
  DatasourceHealth,
  DatasourceTestResult,
  TaskRun,
} from '@/types';

/** MOD-01 数据源 + 扫描（后端前缀 `/api/v1/datasources`，响应 camelCase）。 */

export interface DatasourceListParams {
  keyword?: string;
  dsType?: string;
  enabled?: boolean;
  cursor?: string | null;
  limit?: number;
}

export function listDatasources(params: DatasourceListParams = {}) {
  // 后端查询参数名为 `type`（非 `dsType`），此处做映射，避免筛选静默失效。
  const { dsType, ...rest } = params;
  return get<{ items: DataSource[]; next_cursor?: string | null; total?: number }>(
    '/datasources',
    cleanParams({ ...rest, type: dsType } as Record<string, unknown>),
  );
}

export function createDataSource(data: Record<string, unknown>) {
  return post<DataSource>('/datasources', data);
}

export function testConnection(data: Record<string, unknown>) {
  return post<DatasourceTestResult>('/datasources/test', data);
}

export function getDataSource(id: string | number) {
  return get<DataSource>(`/datasources/${id}`);
}

export function updateDataSource(id: string | number, data: Record<string, unknown>) {
  return put<DataSource>(`/datasources/${id}`, data);
}

export function deleteDataSource(id: string | number) {
  return del<void>(`/datasources/${id}`);
}

export function enableDataSource(id: string | number) {
  return post<DataSource>(`/datasources/${id}/enable`);
}

export function disableDataSource(id: string | number) {
  return post<DataSource>(`/datasources/${id}/disable`);
}

/** 凭据轮换（危险操作，前端需二次确认 + 审计提示）。 */
export function rotateCredentials(id: string | number, data: Record<string, unknown>) {
  return post<unknown>(`/datasources/${id}/credentials`, data);
}

export function activateCredential(id: string | number, version: string | number) {
  return post<unknown>(`/datasources/${id}/credentials/${version}/activate`);
}

export function getDatasourceHealth(id: string | number) {
  return get<DatasourceHealth>(`/datasources/${id}/health`);
}

/** 触发扫描：`POST /api/v1/datasources/{id}/scan`（任务化，返回任务）。 */
export function scanDatasource(id: string | number, data: Record<string, unknown> = {}) {
  return post<TaskRun & { runId?: number; scanRunId?: number }>(
    `/datasources/${id}/scan`,
    data,
  );
}

/** 触发分级：`POST /api/v1/datasources/{id}/classify`。 */
export function classifyDatasource(id: string | number, data: Record<string, unknown> = {}) {
  return post<TaskRun & { runId?: number }>(`/datasources/${id}/classify`, data);
}
