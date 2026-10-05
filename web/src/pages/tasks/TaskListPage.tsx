import { Button, Space, Table, Typography } from 'antd';
import dayjs from 'dayjs';
import type { ColumnsType } from '@/components/DataTable';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { cancelTask, listTasks, retryTask, submitTask } from '@/api/tasks';
import { qk } from '@/api/keys';
import ConfirmDanger from '@/components/ConfirmDanger';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import FilterBar from '@/components/FilterBar';
import type { FilterValues } from '@/components/FilterBar';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import StatusTag from '@/components/StatusTag';
import TaskProgressLink from '@/components/TaskProgressLink';
import { useDatasourceMap, useDatasourceNames } from '@/hooks/useDatasourceName';
import { toUserMessage } from '@/api/errors';
import type { TaskRun } from '@/types';
import { App } from 'antd';

const JOB_TYPES = [
  'metadata',
  'sample',
  'profile',
  'classify',
  'lineage',
  'permission',
] as const;

const STATUSES = ['pending', 'running', 'success', 'failed', 'cancelled', 'timeout'] as const;

/** 任务列表（FE-01 §11.1）。任务接口无游标，故用普通查询 + 轮询。 */
export default function TaskListPage() {
  const { message } = App.useApp();
  const [filters, setFilters] = useState<FilterValues>({});
  const { name: dsName } = useDatasourceNames();
  const { data: dsMap, isLoading: dsLoading } = useDatasourceMap();
  // 示例任务需要一个真实存在的数据源：取第一个可用 ID，避免硬编码导致 500
  const firstDatasourceId = dsMap?.keys().next().value as number | undefined;
  const [autoRefresh, setAutoRefresh] = useState(true);

  const params = useMemo(
    () => ({
      jobType: filters.jobType as string | undefined,
      status: filters.status as string | undefined,
      datasourceId: filters.datasourceId as number | undefined,
    }),
    [filters],
  );

  const { data, isLoading, isError, error, refetch, isFetching, dataUpdatedAt } = useQuery({
    queryKey: qk.tasks.list(params),
    queryFn: () => listTasks(params),
  });

  const items = data?.items ?? [];
  const hasActive = items.some((t) => t.status === 'pending' || t.status === 'running');

  // running/pending 行轮询进度（FE-01 §11.1）
  const { refetch: poll } = useQuery({
    queryKey: [...qk.tasks.list(params), 'poll'],
    queryFn: () => listTasks(params),
    refetchInterval: hasActive && autoRefresh ? 3000 : false,
    enabled: hasActive,
  });
  void poll;

  const columns: ColumnsType<TaskRun> = [
    {
      title: '任务ID',
      dataIndex: 'id',
      width: 90,
      render: (id: number) => <TaskProgressLink id={id} />,
    },
    { title: '类型', dataIndex: 'jobType', width: 110 },
    {
      title: '数据源',
      width: 160,
      // 裸数字 ID 无法识别：解析成名称 + 详情链接（S1#10）
      render: (_v, r) => {
        const dsId = r.scope?.datasourceId ?? r.scope?.datasource_id ?? null;
        if (dsId == null) return '-';
        return <Link to={`/app/datasources/${dsId}`}>{dsName(dsId)}</Link>;
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s?: string) => <StatusTag status={s ?? '-'} />,
    },
    { title: '重试次数', dataIndex: 'attempts', width: 90, render: (v) => v ?? 0 },
    {
      title: '开始 / 结束',
      width: 320,
      render: (_v, r) => (
        <span className="mono" style={{ fontSize: 12 }}>
          {r.startedAt ? String(r.startedAt).replace('T', ' ').slice(0, 19) : '-'} →{' '}
          {r.finishedAt ? String(r.finishedAt).replace('T', ' ').slice(0, 19) : '-'}
        </span>
      ),
    },
    {
      title: '耗时',
      dataIndex: 'durationMs',
      width: 90,
      render: (v?: number | null) => (v == null ? '-' : `${v} ms`),
    },
    {
      title: '操作',
      width: 140,
      render: (_v, r) => (
        <Space size={4}>
          <Link to={`/app/tasks/${r.id}`}>详情</Link>
          <ConfirmDanger
            title={`取消任务 #${r.id}？`}
            disabled={!(r.status === 'pending' || r.status === 'running')}
            onConfirm={async () => {
              await cancelTask(r.id);
              message.success('已发起取消');
              void refetch();
            }}
          >
            <Button type="link" size="small" disabled={!(r.status === 'pending' || r.status === 'running')}>
              取消
            </Button>
          </ConfirmDanger>
          <Button
            type="link"
            size="small"
            disabled={!(r.status === 'failed' || r.status === 'cancelled')}
            onClick={async () => {
              try {
                const next = await retryTask(r.id);
                message.success(`已提交重试，新任务 ${next.id}`);
                void refetch();
              } catch (e: any) {
                message.error(toUserMessage(e, '重试失败'));
              }
            }}
          >
            重试
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="任务列表"
        subtitle="提交后在后台线程池执行，立即返回；可在此跟踪进度"
        extra={
          <Space>
            <Button
              disabled={firstDatasourceId == null || dsLoading}
              title={firstDatasourceId == null ? '请先注册数据源' : undefined}
              onClick={async () => {
                if (firstDatasourceId == null) {
                  message.warning('请先注册数据源，再提交示例扫描任务');
                  return;
                }
                try {
                  const run = await submitTask({
                    jobType: 'metadata',
                    scope: { datasource_id: firstDatasourceId },
                    trigger: 'manual',
                  });
                  message.success(`已提交任务 ${run.id}`);
                  void refetch();
                } catch (e: unknown) {
                  message.error(toUserMessage(e, '提交失败'));
                }
              }}
            >
              提交示例扫描任务
            </Button>
            {hasActive ? (
              <>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {dataUpdatedAt ? `最后更新 ${dayjs(dataUpdatedAt).format('HH:mm:ss')}` : ''}
                  {autoRefresh ? ' · 自动刷新中' : ' · 已暂停'}
                </Typography.Text>
                <Button size="small" onClick={() => setAutoRefresh((v) => !v)}>
                  {autoRefresh ? '暂停刷新' : '恢复刷新'}
                </Button>
              </>
            ) : null}
            <Button onClick={() => void refetch()} loading={isFetching}>
              刷新
            </Button>
          </Space>
        }
      />

      <FilterBar
        fields={[
          {
            name: 'jobType',
            label: '任务类型',
            type: 'select',
            options: JOB_TYPES.map((v) => ({ label: v, value: v })),
          },
          {
            name: 'status',
            label: '状态',
            type: 'select',
            options: STATUSES.map((v) => ({ label: v, value: v })),
          },
          { name: 'datasourceId', label: '数据源', type: 'number' },
        ]}
        values={filters}
        onChange={setFilters}
      />

      {isLoading ? (
        <LoadingSkeleton rows={6} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : items.length === 0 ? (
        <EmptyState description="暂无任务" />
      ) : (
        <Table<TaskRun>
          columns={columns}
          dataSource={items}
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ x: 1100 }}
        />
      )}
      <Typography.Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
        任务状态：pending / running / success / failed / cancelled / timeout
      </Typography.Text>
    </div>
  );
}
