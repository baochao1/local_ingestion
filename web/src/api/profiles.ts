import { get } from './client';

/** MOD-04 画像（只读）。响应 camelCase。 */

export interface ProfileHistogram {
  /** true 表示横轴是字符串长度而非取值（FR-M2.2）。 */
  byLength: boolean;
  edges: number[];
  labels: string[];
  counts: number[];
  /** freedman_diaconis 或 sturges —— 决定桶数如何得出。 */
  method: string;
}

export interface ProfileColumn {
  name: string;
  nullCount?: number | null;
  nullRatio?: number | null;
  distinctCount?: number | null;
  min?: number | string | null;
  max?: number | string | null;
  mean?: number | null;
  stddev?: number | null;
  q1?: number | null;
  median?: number | null;
  q3?: number | null;
  minLength?: number | null;
  maxLength?: number | null;
  histogram?: ProfileHistogram;
  skippedReason?: string;
  [key: string]: unknown;
}

export interface TableProfile {
  tableId: number;
  datasourceId: number;
  status: string;
  rowCount?: number | null;
  columnCount?: number | null;
  /** 1 表示全量；小于 1 时统计值是近似值，界面必须标注（FR-M2.6）。 */
  sampleRate?: number | null;
  sampledRows?: number | null;
  profiledAt?: string | null;
  durationMs?: number | null;
  errorMessage?: string | null;
  columns: ProfileColumn[];
  [key: string]: unknown;
}

export interface ProfileHistoryItem {
  profiledDate: string;
  rowCount?: number | null;
  qualityScore?: number | null;
  profiledAt?: string | null;
}

export interface ProfileSnapshot {
  tableId: number;
  profiledDate: string;
  rowCount?: number | null;
  qualityScore?: number | null;
  columns: ProfileColumn[];
}

/** 当前画像。表从未画像时返回 404（与「画像失败」是两种状态）。 */
export function getTableProfile(tableId: string | number) {
  return get<TableProfile>(`/profiles/tables/${tableId}`);
}

/** 快照日期列表（不含 stats，避免列表体积膨胀）。 */
export function getProfileHistory(tableId: string | number, limit = 30) {
  return get<{ tableId: number; items: ProfileHistoryItem[] }>(
    `/profiles/tables/${tableId}/history`,
    { limit },
  );
}

/** 单日快照（含完整列级统计），用于历史对比（FR-M2.3）。 */
export function getProfileSnapshot(tableId: string | number, profiledDate: string) {
  return get<ProfileSnapshot>(`/profiles/tables/${tableId}/history/${profiledDate}`);
}
