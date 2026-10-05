import { Space, Table, Tag } from 'antd';
import type { ColumnsType } from '@/components/DataTable';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { listAuditLogs } from '@/api/tasks';
import { qk } from '@/api/keys';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import FilterBar from '@/components/FilterBar';
import type { FilterValues } from '@/components/FilterBar';
import JsonView from '@/components/JsonView';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import type { AuditEntry } from '@/types';

/** 审计日志（FE-01 §11.5）：读 GLOBAL_AUDIT_SINK 共享 sink。 */
export default function AuditLogPage() {
  const [filters, setFilters] = useState<FilterValues>({});

  const params = useMemo(
    () => ({
      action: filters.action as string | undefined,
      actor: filters.actor as string | undefined,
      entityType: filters.entityType as string | undefined,
      limit: 200,
    }),
    [filters],
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.audit.list(params),
    queryFn: () => listAuditLogs(params),
  });

  const items = data?.items ?? [];

  const columns: ColumnsType<AuditEntry> = [
    {
      title: '时间',
      dataIndex: 'occurredAt',
      width: 180,
      render: (v?: string | null) =>
        v ? String(v).replace('T', ' ').slice(0, 19) : '-',
    },
    { title: '操作者', dataIndex: 'actor', width: 120, render: (v) => v ?? '-' },
    {
      title: '动作',
      dataIndex: 'action',
      width: 160,
      render: (v?: string) => (v ? <Tag>{v}</Tag> : '-'),
    },
    {
      title: '对象',
      dataIndex: 'entityFqn',
      width: 260,
      render: (v?: string | null) => <span className="mono">{v ?? '-'}</span>,
    },
    {
      title: '结果',
      dataIndex: 'result',
      width: 100,
      render: (v?: string | null) => (v ? <Tag>{v}</Tag> : '-'),
    },
    {
      title: '详情',
      dataIndex: 'detail',
      render: (v?: Record<string, unknown>) => <JsonView value={v ?? {}} copyable={false} />,
    },
  ];

  return (
    <div>
      <PageHeader
        title="审计日志"
        subtitle="仅展示已接入共享审计 sink 的服务条目（当前为编排任务操作）"
      />
      <FilterBar
        fields={[
          { name: 'action', label: '动作', type: 'text', placeholder: '如 task.cancel' },
          { name: 'actor', label: '操作者', type: 'text' },
          { name: 'entityType', label: '实体类型', type: 'text' },
        ]}
        values={filters}
        onChange={setFilters}
      />
      {isLoading ? (
        <LoadingSkeleton rows={6} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : items.length === 0 ? (
        <EmptyState description="暂无审计记录" />
      ) : (
        <Table<AuditEntry>
          columns={columns}
          dataSource={items}
          // 稳定业务键：索引作 rowKey 会让行状态（展开/选中）在数据刷新后错位
          rowKey={(r) =>
            `${r.occurredAt ?? ''}-${r.action ?? ''}-${r.actor ?? ''}-${r.entityFqn ?? ''}`
          }
          size="small"
          pagination={false}
          scroll={{ x: 1000 }}
        />
      )}
      <Space style={{ marginTop: 8 }}>
        <span style={{ fontSize: 12, color: '#8c8c8c' }}>
          数据源/治理等服务的审计需将其 AuditService 指向 GLOBAL_AUDIT_SINK 后才会出现
        </span>
      </Space>
    </div>
  );
}
