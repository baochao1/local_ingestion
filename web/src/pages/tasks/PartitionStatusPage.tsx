import { Alert, Table, Tag } from 'antd';
import type { ColumnsType } from '@/components/DataTable';
import { useQuery } from '@tanstack/react-query';
import { listPartitions } from '@/api/tasks';
import { qk } from '@/api/keys';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import type { PartitionInfo } from '@/types';

/** 分区状态（FE-01 §11.6，运维视角只读）。 */
export default function PartitionStatusPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.partitions.list(),
    queryFn: () => listPartitions(),
  });

  const items = data?.items ?? [];

  const columns: ColumnsType<PartitionInfo> = [
    { title: '表', dataIndex: 'table', render: (v) => <span className="mono">{v}</span> },
    {
      title: '分区策略',
      dataIndex: 'partitionStrategy',
      width: 120,
      render: (v) => (v ? <Tag>{v}</Tag> : '-'),
    },
    {
      title: '分区键',
      dataIndex: 'partitionKey',
      width: 160,
      render: (v) => <span className="mono">{v ?? '-'}</span>,
    },
    { title: '保留窗口(天)', dataIndex: 'retentionWindowDays', width: 120 },
    { title: '管理方', dataIndex: 'managedBy', width: 120 },
  ];

  return (
    <div>
      <PageHeader title="分区状态" subtitle="运维视角：平台操作表的声明式分区方案" />
      {data?.note ? (
        <Alert type="info" showIcon message={data.note} style={{ marginBottom: 16 }} />
      ) : null}
      {isLoading ? (
        <LoadingSkeleton rows={5} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : items.length === 0 ? (
        <EmptyState description="未发现分区表" />
      ) : (
        <Table<PartitionInfo>
          columns={columns}
          dataSource={items}
          rowKey="table"
          size="small"
          pagination={false}
        />
      )}
    </div>
  );
}
