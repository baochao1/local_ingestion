import { Tag } from 'antd';
import { COLORS } from '@/theme';

const GRAY = '#8c8c8c';
const PURPLE = '#722ed1';

export interface StatusMappingItem {
  color: string;
  label: string;
}

/** 内置任务状态映射（FE-00 §5.1）。 */
export const TASK_STATUS_MAP: Record<string, StatusMappingItem> = {
  pending: { color: GRAY, label: '待执行' },
  running: { color: COLORS.primary, label: '执行中' },
  success: { color: COLORS.success, label: '成功' },
  failed: { color: COLORS.error, label: '失败' },
  cancelled: { color: COLORS.warning, label: '已取消' },
  timeout: { color: PURPLE, label: '超时' },
};

export interface StatusTagProps {
  status: string;
  /** 覆盖/扩展内置映射（同名字段优先）。 */
  mapping?: Record<string, StatusMappingItem>;
}

/** 通用状态标签；未知状态原样展示，不报错。 */
export function StatusTag({ status, mapping }: StatusTagProps) {
  const key = String(status ?? '').toLowerCase();
  const item = { ...TASK_STATUS_MAP, ...(mapping ?? {}) }[key];
  if (!item) return <Tag>{status ?? '-'}</Tag>;
  return <Tag color={item.color}>{item.label}</Tag>;
}

export default StatusTag;
