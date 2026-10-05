import { Button, Card, Collapse, Descriptions, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from '@/components/DataTable';
import { useMemo } from 'react';
import { Link, useParams } from 'react-router-dom';
import { App, Modal } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ackChange, getChange } from '@/api/changes';
import { qk } from '@/api/keys';
import { toUserMessage } from '@/api/errors';
import ConfirmDanger from '@/components/ConfirmDanger';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import JsonView from '@/components/JsonView';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import SeverityTag from '@/components/SeverityTag';
import { useDatasourceName } from '@/hooks/useDatasourceName';
import { assetDetailLink } from '@/utils/assets';

interface DiffRow {
  key: string;
  before: string;
  after: string;
  kind: 'changed' | 'added' | 'removed';
}

const KIND_TAG: Record<DiffRow['kind'], { color: string; text: string }> = {
  changed: { color: 'blue', text: '修改' },
  added: { color: 'green', text: '新增' },
  removed: { color: 'red', text: '删除' },
};

function toText(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

/** 只要「变化行」：新增 / 删除 / 改值，不做两份 JSON 并排（FR-3.2）。 */
function buildDiff(
  before: Record<string, unknown> | null,
  after: Record<string, unknown> | null,
): DiffRow[] {
  const keys = new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})]);
  const rows: DiffRow[] = [];
  for (const k of keys) {
    const b = (before ?? {})[k];
    const a = (after ?? {})[k];
    const bt = toText(b);
    const at = toText(a);
    const hadB = Object.prototype.hasOwnProperty.call(before ?? {}, k);
    const hadA = Object.prototype.hasOwnProperty.call(after ?? {}, k);
    if (!hadB && hadA) rows.push({ key: k, before: '', after: at, kind: 'added' });
    else if (hadB && !hadA) rows.push({ key: k, before: bt, after: '', kind: 'removed' });
    else if (bt !== at) rows.push({ key: k, before: bt, after: at, kind: 'changed' });
  }
  return rows;
}

/** 变更详情（FE-01 §5.2）：字段级 diff + 确认闭环（FR-7.9）。 */
export default function ChangeDetailPage() {
  const { message } = App.useApp();
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.changes.detail(id ?? ''),
    queryFn: () => getChange(id as string),
    enabled: !!id,
  });

  const dsName = useDatasourceName(data?.datasource_id ?? null);

  const ack = useMutation({
    mutationFn: (action: string) => ackChange(data!.id, { ack_action: action }),
    onSuccess: () => {
      message.success('已确认');
      void qc.invalidateQueries({ queryKey: qk.changes.detail(id ?? '') });
      void refetch();
    },
    onError: (e: unknown) => message.error(toUserMessage(e, '确认失败')),
  });

  const before = (data?.before_json ?? null) as Record<string, unknown> | null;
  const after = (data?.after_json ?? null) as Record<string, unknown> | null;
  const diffRows = useMemo(() => buildDiff(before, after), [before, after]);
  const hasRawDetail = Object.keys(before ?? {}).length > 0 || Object.keys(after ?? {}).length > 0;

  if (isLoading) return <LoadingSkeleton rows={8} />;
  if (isError || !data) return <ErrorState error={error} onRetry={() => void refetch()} />;

  const entityType = String(data.entity_type ?? '');
  const fqn = String(data.entity_fqn ?? '');
  const canJump = (entityType === 'table' || entityType === 'column') && fqn.length > 0;

  const diffColumns: ColumnsType<DiffRow> = [
    { title: '属性', dataIndex: 'key', width: 220 },
    {
      title: '变更前',
      dataIndex: 'before',
      render: (v: string) => v || <Typography.Text type="secondary">（空）</Typography.Text>,
    },
    {
      title: '变更后',
      dataIndex: 'after',
      render: (v: string) => v || <Typography.Text type="secondary">（空）</Typography.Text>,
    },
    {
      title: '变化',
      dataIndex: 'kind',
      width: 90,
      render: (k: DiffRow['kind']) => <Tag color={KIND_TAG[k]?.color}>{KIND_TAG[k]?.text ?? k}</Tag>,
    },
  ];

  return (
    <div>
      <PageHeader
        title={`${data.change_type ?? '变更'} · ${fqn || `#${data.id}`}`}
        subtitle={`变更 #${data.id}${dsName ? ` · ${dsName}` : ''}`}
        breadcrumb={[
          { title: <Link to="/app/changes">数据变更</Link> },
          { title: `#${data.id}` },
        ]}
        extra={
          data.ack_status !== 'closed' ? (
            <Space>
              <ConfirmDanger
                title="确认接受该变更？"
                description="确认后变更将标记为已处理（此操作将被审计）"
                okText="确认接受"
                onConfirm={() => ack.mutate('accept')}
              >
                <Button type="primary">确认接受</Button>
              </ConfirmDanger>
              <ConfirmDanger
                title="确认为已修复？"
                okText="标记已修复"
                onConfirm={() => ack.mutate('fixed')}
              >
                <Button>标记已修复</Button>
              </ConfirmDanger>
            </Space>
          ) : (
            <Tag color="green">已确认</Tag>
          )
        }
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="严重度">
            <SeverityTag severity={data.severity ?? '-'} />
          </Descriptions.Item>
          <Descriptions.Item label="变更类型">{data.change_type ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="实体类型">{entityType || '-'}</Descriptions.Item>
          <Descriptions.Item label="确认状态">{data.ack_status ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="实体 FQN" span={2}>
            {canJump ? (
              <Space size={4}>
                <Link to={assetDetailLink({ fqn, entityType })} className="mono">
                  {fqn}
                </Link>
                <Link
                  to={`/app/changes/entities/${entityType}/${encodeURIComponent(fqn)}/history`}
                >
                  变更历史
                </Link>
              </Space>
            ) : (
              <span className="mono">{fqn || '-'}</span>
            )}
          </Descriptions.Item>
          {data.datasource_id != null ? (
            <Descriptions.Item label="数据源">
              <Link to={`/app/datasources/${data.datasource_id}`}>{dsName}</Link>
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item label="发现时间">
            {data.detected_at ? String(data.detected_at).replace('T', ' ').slice(0, 19) : '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card size="small" title={`变更明细（${diffRows.length} 项变化）`} style={{ marginBottom: 16 }}>
        {diffRows.length > 0 ? (
          <Table<DiffRow>
            columns={diffColumns}
            dataSource={diffRows}
            rowKey="key"
            size="small"
            pagination={false}
            scroll={{ x: 760 }}
          />
        ) : (
          <EmptyState
            description={
              hasRawDetail
                ? 'before / after 内容一致，本次变更没有可对比的字段级差异'
                : '本次变更未记录 before / after 明细（变更检测链路尚未回填该字段）'
            }
          />
        )}
      </Card>

      {/* 原始记录收进折叠区：排查仍需要，但不再是阅读主线（S1#11） */}
      <Collapse
        items={[
          {
            key: 'raw',
            label: <Typography.Text type="secondary">原始记录（调试用）</Typography.Text>,
            children: <JsonView value={data} />,
          },
        ]}
      />
      <div style={{ marginTop: 16 }}>
        <Button
          onClick={() => {
            Modal.info({ title: '原始记录', width: 720, content: <JsonView value={data} /> });
          }}
        >
          查看原始记录
        </Button>
      </div>
    </div>
  );
}
