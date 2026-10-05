import { Skeleton } from 'antd';

export interface LoadingSkeletonProps {
  rows?: number;
  active?: boolean;
  title?: boolean;
}

/** 四态之一：加载中骨架屏（FE-01 §0）。 */
export function LoadingSkeleton({ rows = 3, active = true, title = true }: LoadingSkeletonProps) {
  return <Skeleton active={active} title={title} paragraph={{ rows }} />;
}

export default LoadingSkeleton;
