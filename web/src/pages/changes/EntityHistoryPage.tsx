import { useParams } from 'react-router-dom';
import { getEntityHistory } from '@/api/changes';
import { qk } from '@/api/keys';
import type { ColumnsType } from '@/components/DataTable';
import DataTable from '@/components/DataTable';
import EmptyState from '@/components/EmptyState';
import PageHeader from '@/components/PageHeader';
import SeverityTag from '@/components/SeverityTag';
import type { ChangeEvent } from '@/types';

/** 单实体变更历史（FE-01 §5.4）。 */
export default function EntityHistoryPage() {
  const { type, fqn } = useParams<{ type: string; fqn: string }>();

  const columns: ColumnsType<ChangeEvent> = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 80,
    },
    {
      title: '严重度',
      dataIndex: 'severity',
      width: 100,
      render: (v?: string) => <SeverityTag severity={v ?? '-'} />,
    },
    { title: '变更类型', dataIndex: 'change_type', width: 150 },
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
        title="实体变更历史"
        subtitle={<span className="mono">{fqn}</span>}
      />
      <DataTable<ChangeEvent>
        columns={columns}
        queryKey={qk.changes.history(type ?? '', fqn ?? '')}
        rowKey="id"
        scrollX={900}
        empty={<EmptyState description="该实体暂无变更历史" />}
        fetcher={async (cursor) =>
          getEntityHistory(type as string, fqn as string, { cursor })
        }
      />
    </div>
  );
}
