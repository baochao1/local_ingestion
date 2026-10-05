import { cleanParams, get, post } from './client';
import type {
  AuditEntry,
  CursorPage,
  PartitionInfo,
  SystemHealth,
  SystemMetrics,
  TaskRun,
} from '@/types';

/** MOD-10 任务运维 / 审计 / 分区 / 平台健康指标。响应 camelCase。 */

export interface TaskListParams {
  jobType?: string;
  status?: string;
  datasourceId?: number | string;
  limit?: number;
}

export function listTasks(params: TaskListParams = {}) {
  return get<CursorPage<TaskRun>>('/tasks', cleanParams(params as Record<string, unknown>));
}

export interface TaskSubmitBody {
  jobType: string;
  scope?: Record<string, unknown>;
  trigger?: 'manual' | 'cron' | 'event';
  concurrencyKey?: string;
  priority?: number;
  payload?: Record<string, unknown>;
}

/** 提交并后台执行；立即返回（通常为 pending）。 */
export function submitTask(body: TaskSubmitBody) {
  return post<TaskRun>('/tasks', body);
}

export function getTask(id: string | number) {
  return get<TaskRun>(`/tasks/${id}`);
}

export function cancelTask(id: string | number) {
  return post<{ cancelled?: boolean; task?: TaskRun }>(`/tasks/${id}/cancel`);
}

export function retryTask(id: string | number) {
  return post<TaskRun>(`/tasks/${id}/retry`);
}

export function listAuditLogs(params: {
  action?: string;
  actor?: string;
  entityType?: string;
  limit?: number;
} = {}) {
  return get<CursorPage<AuditEntry>>('/audit-logs', cleanParams(params as Record<string, unknown>));
}

export function listPartitions() {
  return get<CursorPage<PartitionInfo> & { note?: string }>('/tasks/partitions');
}

export function getSystemHealth() {
  return get<SystemHealth>('/system/health');
}

export function getSystemMetrics() {
  return get<SystemMetrics>('/system/metrics');
}
