import { useState } from 'react';
import { Alert, Button, Card, Col, Popconfirm, Progress, Row, Select, Space, Statistic, Table, Tag, Typography, message } from 'antd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { getProfileHistory, getProfileSnapshot, getTableProfile } from '@/api/profiles';
import { submitTask } from '@/api/tasks';
import type { ProfileColumn } from '@/api/profiles';
import ColumnHistogram from '@/components/profile/ColumnHistogram';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';

/**
 * 表画像（MOD-04 / FR-M2）。
 *
 * 这一页存在的理由：画像此前**能算出来但无处可看**——runner 写进了
 * `table_profile`，前端只有占位路由。用户看到的是「表结构登记簿」，
 * 看不到「表里的数据长什么样」。
 */

/** 抽出 HTTP 状态码；后端 404 表示「从未画像」，与「画像失败」是两回事。 */
function statusOf(error: unknown): number | undefined {
  const candidate = error as {
    code?: unknown;
    status?: unknown;
    response?: { status?: unknown };
  };
  const raw = candidate?.code ?? candidate?.status ?? candidate?.response?.status;
  return typeof raw === 'number' ? raw : undefined;
}

function formatValue(value: ProfileColumn['min']): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  return String(value);
}

export default function TableProfilePage() {
  const { id } = useParams<{ id: string }>();
  const tableId = id ?? '';
  const [snapshotDate, setSnapshotDate] = useState<string | null>(null);

  const profile = useQuery({
    queryKey: ['profile', tableId],
    queryFn: () => getTableProfile(tableId),
    enabled: Boolean(tableId),
    retry: false,
  });
  const history = useQuery({
    queryKey: ['profile-history', tableId],
    queryFn: () => getProfileHistory(tableId),
    enabled: Boolean(tableId),
    retry: false,
  });
  const snapshot = useQuery({
    queryKey: ['profile-snapshot', tableId, snapshotDate],
    queryFn: () => getProfileSnapshot(tableId, snapshotDate as string),
    enabled: Boolean(tableId) && Boolean(snapshotDate),
    retry: false,
  });

  // 触发画像：提交 JobType.PROFILE 任务（后端 handler 已注册）。
  // 必须在任何 early return 之前声明 —— hooks 不能条件调用。
  const queryClient = useQueryClient();
  const refresh = useMutation({
    mutationFn: () =>
      submitTask({
        jobType: 'profile',
        scope: {
          tableId: Number(tableId),
          datasourceId: Number(profile.data?.datasourceId ?? 0),
        },
      }),
    onSuccess: () => {
      message.success('画像任务已提交');
      // 任务是异步执行的，轮询刷新比让用户手动刷新更可靠。
      setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ['profile', tableId] });
        void queryClient.invalidateQueries({ queryKey: ['profile-history', tableId] });
      }, 2000);
    },
    onError: (error) => {
      message.error(`提交失败：${(error as Error)?.message ?? '未知错误'}`);
    },
  });

  if (profile.isLoading) return <LoadingSkeleton rows={6} />;

  if (profile.isError) {
    if (statusOf(profile.error) === 404) {
      return (
        <>
          <PageHeader title="表画像" breadcrumb={[{ title: '资产目录', href: '/app/catalog' }, { title: '表画像' }]} />
          <Card>
            <EmptyState description="该表尚未画像" />
          </Card>
        </>
      );
    }
    return <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />;
  }

  const data = profile.data!;
  // 选定历史日期时用快照的列级统计覆盖当前值（FR-M2.3）。
  const columns: ProfileColumn[] =
    snapshotDate && snapshot.data ? snapshot.data.columns : data.columns ?? [];
  const sampled = (data.sampleRate ?? 1) < 1;
  const samplePercent = Math.round((data.sampleRate ?? 1) * 100);

  const columnDefs = [
    {
      title: '字段',
      dataIndex: 'name',
      render: (name: string, row: ProfileColumn) => (
        <Space>
          <Typography.Text strong>{name}</Typography.Text>
          {row.skippedReason ? <Tag>{row.skippedReason}</Tag> : null}
        </Space>
      ),
    },
    {
      title: '空值率',
      dataIndex: 'nullRatio',
      width: 180,
      render: (ratio: number | null | undefined) =>
        ratio === null || ratio === undefined ? (
          '—'
        ) : (
          <Space size={8}>
            <Progress
              percent={Math.round(ratio * 100)}
              size="small"
              style={{ width: 90 }}
            />
            <Typography.Text type="secondary">{(ratio * 100).toFixed(1)}%</Typography.Text>
          </Space>
        ),
    },
    { title: '唯一值', dataIndex: 'distinctCount', width: 100, render: (v: number | null) => v ?? '—' },
    {
      title: '最小 ~ 最大',
      width: 200,
      render: (_: unknown, row: ProfileColumn) =>
        `${formatValue(row.min)} ~ ${formatValue(row.max)}`,
    },
    { title: '中位数', dataIndex: 'median', width: 110, render: (v: number | null) => formatValue(v ?? null) },
    {
      title: '分布',
      width: 90,
      render: (_: unknown, row: ProfileColumn) =>
        row.histogram ? (
          <Typography.Text type="secondary">
            {row.histogram.byLength ? '长度分布' : '取值分布'}
          </Typography.Text>
        ) : (
          '—'
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title="表画像"
        subtitle={`表 #${data.tableId} · 数据源 #${data.datasourceId}`}
        breadcrumb={[{ title: '资产目录', href: '/app/catalog' }, { title: '表画像' }]}
        extra={
          <Space>
            <Select
              allowClear
              placeholder="切换历史快照"
              style={{ width: 220 }}
              value={snapshotDate ?? undefined}
              onChange={(value) => setSnapshotDate(value ?? null)}
              options={(history.data?.items ?? []).map((item) => ({
                value: item.profiledDate,
                label: `${item.profiledDate}（${item.rowCount ?? '—'} 行）`,
              }))}
            />
            {/* FR-M2.5：敏感操作二次确认，并说明会以只读方式访问目标库。 */}
            <Popconfirm
              title="立即采集画像？"
              description="将以只读方式查询目标库统计列级分布；大表会自动降采样，超阈值表将被跳过。"
              okText="开始采集"
              cancelText="取消"
              onConfirm={() => refresh.mutate()}
            >
              <Button type="primary" loading={refresh.isPending}>
                立即采集
              </Button>
            </Popconfirm>
          </Space>
        }
      />

      {data.status !== 'success' ? (
        <Alert
          style={{ marginBottom: 16 }}
          type={data.status === 'skipped' ? 'warning' : 'error'}
          showIcon
          message={data.status === 'skipped' ? '该表已跳过画像' : '上次画像失败'}
          description={data.errorMessage ?? undefined}
        />
      ) : null}

      {/* FR-M2.6：采样得来的统计值必须显式标注，否则用户会当成精确值用。 */}
      {sampled ? (
        <Alert
          style={{ marginBottom: 16 }}
          type="info"
          showIcon
          message={`以下统计基于 ${samplePercent}% 采样，为近似值`}
        />
      ) : null}

      <Card style={{ marginBottom: 16 }}>
        <Row gutter={24}>
          <Col span={6}>
            <Statistic title="行数" value={data.rowCount ?? 0} />
          </Col>
          <Col span={6}>
            <Statistic title="字段数" value={data.columnCount ?? columns.length} />
          </Col>
          <Col span={6}>
            <Statistic
              title="采样率"
              value={samplePercent}
              suffix="%"
            />
          </Col>
          <Col span={6}>
            <Statistic title="耗时" value={data.durationMs ?? 0} suffix="ms" />
          </Col>
        </Row>
        {snapshotDate ? (
          <Typography.Text type="secondary">
            正在查看 {snapshotDate} 的快照
            {snapshot.isLoading ? '（加载中）' : ''}
          </Typography.Text>
        ) : null}
      </Card>

      <Card title="字段级统计">
        <Table
          rowKey="name"
          size="small"
          dataSource={columns}
          columns={columnDefs}
          pagination={false}
          expandable={{
            expandedRowRender: (row) =>
              row.histogram ? (
                <ColumnHistogram histogram={row.histogram} />
              ) : (
                <EmptyState description="该字段无分布图" />
              ),
            rowExpandable: (row) => Boolean(row.histogram),
          }}
        />
      </Card>
    </>
  );
}
