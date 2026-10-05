import { Tag } from 'antd';
import { COLORS } from '@/theme';

/**
 * 分级阶梯（1–5），与后端 `platform/classification/rules.py` 的 `GRADE_CODES` 对齐。
 *
 * 这里**必须是 5 级**：引擎会把字段判到 5 级（CONFIDENTIAL，工资/征信/密钥），
 * 此前组件只认 1–4，L5 数据渲染成「未分级」——概览的分级分布也因此恒为 0。
 * 级别定义以后端 `/api/v1/classification/ladder` 为单一事实来源，改这里时同步核对。
 */
export type GradeLevel = 1 | 2 | 3 | 4 | 5;

const GRADE_MAP: Record<number, { color: string; label: string }> = {
  1: { color: 'default', label: 'L1 内部' },
  2: { color: COLORS.primary, label: 'L2 业务敏感' },
  3: { color: COLORS.warning, label: 'L3 个人信息' },
  4: { color: COLORS.error, label: 'L4 高敏个人信息' },
  5: { color: COLORS.sensitive, label: 'L5 机密' },
};

export interface GradeTagProps {
  /** 允许 number，便于直接透传接口返回的等级字段。 */
  level: GradeLevel | number;
}

/** 分级标签 L1-L5：灰/蓝/橙/红/深红（FE-00 §5.1）。 */
export function GradeTag({ level }: GradeTagProps) {
  const item = GRADE_MAP[Number(level)];
  if (!item) return <Tag>未分级</Tag>;
  return <Tag color={item.color}>{item.label}</Tag>;
}

export default GradeTag;
