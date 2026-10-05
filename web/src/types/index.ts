/**
 * 后端响应类型。
 *
 * 重要（已核对后端源码）：后端并非全部 camelCase —— `datasources / search /
 * assets / tasks / audit / system / partitions / scans` 会走 `camelize`，
 * 而 `changes / governance / business / lineage / catalog` 目前**直接返回 snake_case**。
 * 因此这里按模块分别标注字段命名。
 *
 * 复杂 DTO 带 `[key: string]: any` 索引签名：后端字段仍在演进，避免前端因
 * 个别字段缺失而编译失败；已知字段仍给出显式声明便于补全。
 */

/** keyset 游标分页包络（FE-00 §6.2）。 */
export interface CursorPage<T> {
  items: T[];
  next_cursor?: string | null;
  total?: number | null;
}

// ------------------------------------------------------------------ MOD-01 数据源（camelCase）
export interface DataSource {
  id: number;
  code?: string;
  name?: string;
  dsType?: string;
  enabled?: boolean;
  createdAt?: string;
  updatedAt?: string;
  [key: string]: any;
}

export interface DatasourceHealth {
  datasourceId?: number;
  status?: string;
  lastScanStatus?: string | null;
  lastScanAt?: string | null;
  message?: string;
  [key: string]: any;
}

export interface DatasourceTestResult {
  /** 后端实际返回 `{connected, readonly, reason}`；ok/success 为兼容保留。 */
  connected?: boolean;
  readonly?: boolean;
  reason?: string;
  ok?: boolean;
  success?: boolean;
  message?: string;
  [key: string]: any;
}

// ------------------------------------------------------------------ MOD-09 资产（camelCase）
export interface CatalogAsset {
  id?: number;
  fqn?: string;
  name?: string;
  type?: string;
  gradeLevel?: number;
  gradeCode?: string;
  datasourceId?: number;
  owner?: string;
  tags?: string[];
  description?: string;
  [key: string]: any;
}

/** `/assets/{fqn}` 详情卡（camelCase；entityType 为 table 或 column）。 */
export interface AssetDetailCard {
  fqn?: string;
  entityType?: 'table' | 'column' | string;
  name?: string;
  schema?: string;
  description?: string | null;
  tags?: string[];
  owner?: string | null;
  isPii?: boolean;
  importance?: number;
  datasourceId?: number | null;
  gradeLevel?: number | null;
  columns?: AssetDetailColumn[];
  /** 仅字段详情：父表信息，用于「所属表」回跳。 */
  parentFqn?: string | null;
  dataType?: string | null;
  nullable?: boolean | null;
  business?: unknown;
  quality?: unknown;
  lineage?: unknown;
  grants?: unknown;
  recentChanges?: unknown;
  degradedSources?: string[];
  [key: string]: unknown;
}

export interface AssetDetailColumn {
  name?: string;
  dataType?: string;
  nullable?: boolean;
  comment?: string | null;
  isPii?: boolean;
  importance?: number;
  [key: string]: unknown;
}

export interface CatalogOverview {
  totalTables?: number;
  totalColumns?: number;
  totalDatasources?: number;
  gradeDistribution?: Record<string, number>;
  sensitiveRatio?: number;
  qualityDistribution?: Record<string, number>;
  changeTrend?: { date: string; count: number }[];
  topChangingTables?: { fqn: string; changeCount: number }[];
  [key: string]: any;
}

// ------------------------------------------------------------------ MOD-06 变更（snake_case！）
export interface ChangeEvent {
  id: number;
  entity_type?: string;
  entity_fqn?: string;
  change_type?: string;
  severity?: 'descriptive' | 'structural' | 'breaking' | string;
  detected_at?: string;
  datasource_id?: number;
  before_json?: Record<string, any> | null;
  after_json?: Record<string, any> | null;
  ack_status?: string;
  [key: string]: any;
}

export interface ChangeStatistics {
  total?: number;
  by_severity?: Record<string, number>;
  by_datasource?: Record<string, number>;
  [key: string]: any;
}

// ------------------------------------------------------------------ MOD-10 任务（camelCase）
export type TaskStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'cancelled'
  | 'timeout'
  | string;

export interface TaskRun {
  id: number;
  jobType?: string;
  scope?: Record<string, any>;
  trigger?: string;
  status?: TaskStatus;
  attempts?: number;
  stats?: Record<string, any>;
  errorMessage?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  durationMs?: number | null;
  createdAt?: string | null;
  submittedBy?: string | null;
  [key: string]: any;
}

export interface PartitionInfo {
  table?: string;
  partitionStrategy?: string;
  partitionKey?: string | null;
  retentionWindowDays?: number;
  managedBy?: string;
  [key: string]: any;
}

export interface AuditEntry {
  actor?: string | null;
  action?: string;
  entityType?: string | null;
  entityFqn?: string | null;
  detail?: Record<string, any>;
  clientIp?: string | null;
  result?: string | null;
  occurredAt?: string | null;
  [key: string]: any;
}

export interface SystemHealth {
  status?: string;
  timestamp?: string;
  components?: { component?: string; status?: string; message?: string }[];
  [key: string]: any;
}

export interface SystemMetrics {
  [key: string]: any;
}

// ------------------------------------------------------------------ MOD-12 治理（snake_case！）
export interface ApprovalRequest {
  id: number;
  title?: string;
  resource_type?: string;
  resource_fqn?: string;
  /** 后端字段名（`asdict` 直出 snake_case），不是 `action` / `requester`。 */
  action_type?: string;
  /** 后端字段名，不是 `requester`。 */
  requested_by?: string;
  approver?: string;
  priority?: string;
  status?: string;
  reason?: string;
  created_at?: string;
  decided_at?: string;
  decision_note?: string;
  [key: string]: any;
}

export interface ApprovalComment {
  id?: number;
  author?: string;
  content?: string;
  created_at?: string;
  [key: string]: any;
}

export interface Ticket {
  id: number;
  title?: string;
  ticket_type?: string;
  priority?: string;
  status?: string;
  reporter?: string;
  assignee?: string;
  sla_due_at?: string;
  related_fqn?: string;
  source?: string;
  description?: string;
  created_at?: string;
  [key: string]: any;
}

export interface TicketComment {
  id?: number;
  author?: string;
  content?: string;
  created_at?: string;
  [key: string]: any;
}

// ------------------------------------------------------------------ MOD-07 血缘 / MOD-09 业务（snake_case！）
export interface LineageImpact {
  fqn?: string;
  upstream?: unknown[];
  downstream?: unknown[];
  impact?: unknown;
  [key: string]: any;
}

export interface BusinessTerm {
  term_code?: string;
  name?: string;
  definition?: string;
  [key: string]: any;
}

export interface BusinessMetadata {
  entity_type?: string;
  entity_id?: number | string;
  description?: string;
  aliases?: string[];
  tags?: string[];
  [key: string]: any;
}
