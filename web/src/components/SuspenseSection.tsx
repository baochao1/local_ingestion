import { Alert, Card } from 'antd';
import type { ReactNode } from 'react';

export interface SuspenseSectionProps {
  available: boolean;
  title?: ReactNode;
  /** 降级态可不传 children，直接渲染 fallback。 */
  children?: ReactNode;
  fallback?: ReactNode;
}

/** 详情页可降级区块：不可用时显示「该能力暂不可用」（FE-01 §0）。 */
export function SuspenseSection({ available, title, children, fallback }: SuspenseSectionProps) {
  if (available) return <>{children}</>;
  const content =
    fallback ?? (
      <Alert
        type="warning"
        showIcon
        message="该能力暂不可用"
        description="相关模块尚未上线，暂不提供数据。"
      />
    );
  return (
    <Card size="small" title={title}>
      {content}
    </Card>
  );
}

export default SuspenseSection;
