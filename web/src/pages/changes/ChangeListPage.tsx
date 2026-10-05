import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { listChanges } from '@/api/changes';
import { qk } from '@/api/keys';
import type { ColumnsType } from '@/components/DataTable';
import DataTable from '@/components/DataTable';
import EmptyState from '@/components/EmptyState';
import FilterBar from '@/components/FilterBar';
import type { FilterValues } from '@/components/FilterBar';
import PageHeader from '@/components/PageHeader';
import SeverityTag from '@/components/SeverityTag';
import type { ChangeEvent } from '@/types';

/** 变更列表（FE-01 §5.1）。注意后端字段为 snake_case。 */
export default function ChangeListPage() {
  const [filters, setFilters] = useState<FilterValues>({});

  const params = useMemo(
    () => ({
      datasourceId: filters.datasourceId as number | undefined,
      severity: filters.severity as string | undefined,
      changeType: filters.changeType as string | undefined,
      entityType: filters.entityType as string | undefined,
      ackStatus: filters.ackStatus as string | undefined,
    }),
    [filters],
  );
  const filterKey = JSON.stringify(params);

  const columns: ColumnsType<ChangeEvent> = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 80,
      render: (id: number) => <Link to={`/app/changes/${id}`}>{id}</Link>,
    },
    {
      title: '严重度',
      dataIndex: 'severity',
      width: 100,
      render: (v?: string) => <SeverityTag severity={v ?? '-'} />,
    },
    { title: '变更类型', dataIndex: 'change_type', width: 150 },
    { title: '实体类型', dataIndex: 'entity_type', width: 100 },
    {
      title: '实体 FQN',
      dataIndex: 'entity_fqn',
      width: 320,
      render: (v?: string) => <span className="mono">{v ?? '-'}</span>,
    },
    {
      title: '发现时间',
      dataIndex: 'detected_at',
      width: 170,
      render: (v?: string) => (v ? String(v).replace('T', ' ').slice(0, 19) : '-'),
    },
    { title: '确认状态', dataIndex: 'ack_status', width: 100, render: (v) => v ?? '-' },
  ];

  return (
    <div>
      <PageHeader
        title="数据变更"
        subtitle="结构/描述性变更追踪（MOD-06）"
        extra={<Link to="/app/changes/statistics">查看统计</Link>}
      />
      <FilterBar
        fields={[
          { name: 'datasourceId', label: '数据源', type: 'number' },
          {
            name: 'severity',
            label: '严重度',
            type: 'select',
            options: [
              { label: '破坏性', value: 'breaking' },
              { label: '结构性', value: 'structural' },
              { label: '描述性', value: 'descriptive' },
            ],
          },
          { name: 'changeType', label: '变更类型', type: 'text' },
          { name: 'entityType', label: '实体类型', type: 'text' },
          {
            name: 'ackStatus',
            label: '确认状态',
            type: 'select',
            options: [
              { label: '待确认', value: 'pending' },
              { label: '已确认', value: 'closed' },
            ],
          },
        ]}
        values={filters}
        onChange={setFilters}
      />
      <DataTable<ChangeEvent>
        columns={columns}
        queryKey={qk.changes.list(params)}
        filterKey={filterKey}
        rowKey="id"
        scrollX={1200}
        empty={<EmptyState description="暂无变更记录" />}
        fetcher={async (cursor) => listChanges({ ...params, cursor })}
      />
    </div>
  );
}
