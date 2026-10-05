import { Tag } from 'antd';
import { COLORS } from '@/theme';

export type ChangeSeverity = 'descriptive' | 'structural' | 'breaking';

const GRAY = '#8c8c8c';

const SEVERITY_MAP: Record<string, { color: string; label: string }> = {
  descriptive: { color: GRAY, label: '描述性' },
  structural: { color: COLORS.warning, label: '结构性' },
  breaking: { color: COLORS.error, label: '破坏性' },
};

export interface SeverityTagProps {
  severity: ChangeSeverity | string;
}

/** 变更严重度：灰/橙/红（FE-00 §5.1）。 */
export function SeverityTag({ severity }: SeverityTagProps) {
  const key = String(severity ?? '').toLowerCase();
  const item = SEVERITY_MAP[key];
  if (!item) return <Tag>{severity ?? '-'}</Tag>;
  return <Tag color={item.color}>{item.label}</Tag>;
}

export default SeverityTag;
