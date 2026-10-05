import { cleanParams, get, post } from './client';

/** MOD-08 权限分析：账号 / 授权 / 风险 / 变更 / 导出。响应全部 snake_case。 */

export interface PermissionAccount {
  account: string;
  type: string | null;
  is_super: boolean;
  is_locked: boolean;
  host: string | null;
  last_login_at: string | null;
}

export interface PermissionGrant {
  account: string | null;
  account_id: number;
  privilege: string;
  object_type: string;
  object_fqn: string;
  grantable: boolean;
  detected_at: string;
}

export type RiskType =
  | 'super'
  | 'locked'
  | 'dormant'
  | 'orphan'
  | 'excessive'
  | 'high_sensitivity';

export type RiskSeverity = 'high' | 'medium' | 'info' | 'low';

export interface PermissionRisk {
  id: string;
  type: RiskType;
  account: string;
  object_fqn?: string;
  privilege?: string;
  severity: RiskSeverity;
  detail: string;
  acked: boolean;
}

export interface PermissionChange {
  kind: 'added' | 'revoked';
  account_id: number;
  privilege: string;
  object_fqn: string;
}

export interface PermissionExport {
  datasource_id: number;
  accounts: number;
  risks: number;
  high_sensitivity_count: number;
  generated_at: string;
  high_sensitivity: PermissionRisk[];
}

export function listAccounts(datasourceId: number, account?: string) {
  return get<PermissionAccount[]>('/accounts', cleanParams({ datasource_id: datasourceId, account }));
}

export function getAccountGrants(datasourceId: number, account: string) {
  return get<PermissionGrant[]>(`/accounts/${encodeURIComponent(account)}/grants`, {
    datasource_id: datasourceId,
  });
}

export function listRisks(datasourceId: number, severity?: string) {
  return get<PermissionRisk[]>('/risks', cleanParams({ datasource_id: datasourceId, severity }));
}

export function ackRisk(datasourceId: number, riskId: string) {
  return post<{ ok: boolean }>(`/risks/${riskId}/ack`, undefined, {
    datasource_id: datasourceId,
  });
}

export function listChanges(datasourceId: number) {
  return get<PermissionChange[]>('/changes', { datasource_id: datasourceId });
}

export function exportReport(datasourceId: number) {
  return get<PermissionExport>('/export', { datasource_id: datasourceId });
}

/** 触发一次只读权限采集任务（permission.collect），立即返回任务 ID。 */
export function triggerPermissionScan(datasourceId: number, schema?: string) {
  return post<{ task_id: number }>('/permissions/tasks', {
    datasource_id: datasourceId,
    schema,
  });
}
