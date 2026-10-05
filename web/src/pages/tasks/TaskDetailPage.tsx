import { toUserMessage } from '@/api/errors';
import { Button, Card, Descriptions, Space, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { cancelTask, getTask, retryTask } from '@/api/tasks';
import { qk } from '@/api/keys';
import ConfirmDanger from '@/components/ConfirmDanger';
import ErrorState from '@/components/ErrorState';
import JsonView from '@/components/JsonView';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import StatusTag from '@/components/StatusTag';
import { App } from 'antd';

/** 任务详情（FE-01 §11.2）：信息 + 执行结果/日志 + 取消/重试。 */
export default function TaskDetailPage() {
  const { message } = App.useApp();
  const { id } = useParams<{ id: string }>();
  const taskId = Number(id);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: qk.tasks.detail(taskId),
    queryFn: () => getTask(taskId),
    enabled: Number.isFinite(taskId),
    // 未终态时轮询（后端为异步执行）
    refetchInterval: (query) => {
      const status = (query.state.data as { status?: string } | undefined)?.status;
      return status === 'pending' || status === 'running' ? 3000 : false;
    },
  });

  if (isLoading) return <LoadingSkeleton rows={6} />;
  if (isError || !data)
    return <ErrorState error={error} onRetry={() => void refetch()} />;

  const active = data.status === 'pending' || data.status === 'running';

  return (
    <div>
      <PageHeader
        title={`任务 #${data.id}`}
        breadcrumb={[{ title: '任务运维' }, { title: `#${data.id}` }]}
        extra={
          <Space>
            <Button onClick={() => void refetch()} loading={isFetching}>
              刷新
            </Button>
            <ConfirmDanger
              title={`取消任务 #${data.id}？`}
              disabled={!active}
              onConfirm={async () => {
                await cancelTask(data.id);
                message.success('已发起取消');
                void refetch();
              }}
            >
              <Button danger disabled={!active}>
                取消
              </Button>
            </ConfirmDanger>
            <Button
              type="primary"
              disabled={!(data.status === 'failed' || data.status === 'cancelled')}
              onClick={async () => {
                try {
                  const next = await retryTask(data.id);
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
        }
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="类型">{data.jobType ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <StatusTag status={data.status ?? '-'} />
          </Descriptions.Item>
          <Descriptions.Item label="触发方式">{data.trigger ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="重试次数">{data.attempts ?? 0}</Descriptions.Item>
          <Descriptions.Item label="开始时间">
            {data.startedAt ? String(data.startedAt).replace('T', ' ').slice(0, 19) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="结束时间">
            {data.finishedAt ? String(data.finishedAt).replace('T', ' ').slice(0, 19) : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="耗时">
            {data.durationMs == null ? '-' : `${data.durationMs} ms`}
          </Descriptions.Item>
          <Descriptions.Item label="提交人">{data.submittedBy ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="范围 scope" span={2}>
            <JsonView value={data.scope ?? {}} />
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {data.errorMessage ? (
        <Card size="small" title="错误信息" style={{ marginBottom: 16 }}>
          <Typography.Text type="danger" className="mono">
            {data.errorMessage}
          </Typography.Text>
        </Card>
      ) : null}

      <Card size="small" title="执行结果 / 日志（stats）">
        <JsonView value={data.stats ?? {}} />
      </Card>
    </div>
  );
}
