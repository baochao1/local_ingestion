import { Button, Table, Typography } from 'antd';
import type { TableProps } from 'antd';
import { useInfiniteQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import type { ReactNode } from 'react';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import LoadingSkeleton from '@/components/LoadingSkeleton';

/** keyset 游标分页响应包络（FE-00 §6.2）。 */
export interface CursorPage<T> {
  items: T[];
  next_cursor?: string | null;
  total?: number | null;
}

/** 等价于 antd 的 ColumnsType<T>，避免深路径导入。 */
export type ColumnsType<T> = NonNullable<TableProps<T>['columns']>;

export interface DataTableProps<T> {
  columns: ColumnsType<T>;
  /** React Query key（由页面传入）。 */
  queryKey: readonly unknown[];
  /** 按游标取一页；cursor 为 null 表示首页。 */
  fetcher: (cursor: string | null) => Promise<CursorPage<T>>;
  rowKey: keyof T | ((row: T) => string | number);
  /** 变化时自动重置游标（直接并入 queryKey）。 */
  filterKey?: unknown;
  empty?: ReactNode;
  size?: 'small' | 'middle';
  scrollX?: number;
}

/**
 * keyset 游标分页表格：无页码、无 OFFSET（FE-00 §6.2，ADR-5）。
 * 四态：LoadingSkeleton / ErrorState(重试) / EmptyState / Data。
 */
export function DataTable<T>({
  columns,
  queryKey,
  fetcher,
  rowKey,
  filterKey,
  empty,
  size = 'small',
  scrollX,
}: DataTableProps<T>) {
  const {
    data,
    error,
    isLoading,
    isError,
    isFetchingNextPage,
    hasNextPage,
    fetchNextPage,
    refetch,
  } = useInfiniteQuery({
    // filterKey 并入 queryKey：筛选变化即换键 → 游标自动回到首页
    queryKey: [...queryKey, filterKey],
    queryFn: ({ pageParam }) => fetcher(pageParam),
    initialPageParam: null as string | null,
    // 兼容两种信封：camelize 后端返回 `nextCursor`，snake 后端返回 `next_cursor`
    getNextPageParam: (lastPage) =>
      ((lastPage as any)?.next_cursor ??
        (lastPage as any)?.nextCursor ??
        undefined) as string | null | undefined,
  });

  const items = useMemo(
    () => (data?.pages ?? []).flatMap((page) => page?.items ?? []),
    [data],
  );
  // 兼容 `total` 与 `approxTotal` 两种计数字段
  const total =
    (data?.pages?.[0] as any)?.total ??
    (data?.pages?.[0] as any)?.approxTotal ??
    null;

  if (isLoading) return <LoadingSkeleton rows={6} />;

  if (isError)
    return (
      <ErrorState
        error={error}
        onRetry={() => {
          void refetch();
        }}
      />
    );

  if (items.length === 0) return <>{empty ?? <EmptyState />}</>;

  return (
    <>
      <Table<T>
        columns={columns}
        dataSource={items}
        rowKey={rowKey as unknown as TableProps<T>['rowKey']}
        size={size}
        pagination={false}
        scroll={scrollX ? { x: scrollX } : undefined}
      />
      <div style={{ marginTop: 12, textAlign: 'center' }}>
        {hasNextPage ? (
          <Button
            onClick={() => {
              void fetchNextPage();
            }}
            loading={isFetchingNextPage}
          >
            加载更多
          </Button>
        ) : (
          <Typography.Text type="secondary">
            {total != null ? `已加载 ${items.length} / ${total} 条，没有更多数据` : '没有更多数据'}
          </Typography.Text>
        )}
      </div>
    </>
  );
}

export default DataTable;
