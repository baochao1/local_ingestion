import { Empty } from 'antd';
import type { ReactNode } from 'react';

export interface EmptyStateProps {
  description?: ReactNode;
  extra?: ReactNode;
}

/** 四态之一：空数据。 */
export function EmptyState({ description, extra }: EmptyStateProps) {
  return (
    <div style={{ padding: '32px 0', textAlign: 'center' }}>
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description ?? '暂无数据'} />
      {extra ? <div style={{ marginTop: 12 }}>{extra}</div> : null}
    </div>
  );
}

export default EmptyState;
