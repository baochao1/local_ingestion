import { toUserMessage } from '@/api/errors';
import { App, Button, Card, Descriptions, Modal, Space, Tag, Typography } from 'antd';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import {
  classifyDatasource,
  disableDataSource,
  enableDataSource,
  getDataSource,
  getDatasourceHealth,
  scanDatasource,
} from '@/api/datasources';
import { qk } from '@/api/keys';
import ConfirmDanger from '@/components/ConfirmDanger';
import ErrorState from '@/components/ErrorState';
import JsonView from '@/components/JsonView';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import ScanModal from '@/components/ScanModal';
import TaskProgressLink from '@/components/TaskProgressLink';

/** 数据源详情（FE-01 §3.3）：概览 / 健康 / 扫描。 */
export default function DataSourceDetailPage() {
  const { message } = App.useApp();
  const { id } = useParams<{ id: string }>();
  const [scanOpen, setScanOpen] = useState(false);
  const [scanLoading, setScanLoading] = useState(false);

  const ds = useQuery({
    queryKey: qk.datasources.detail(id ?? ''),
    queryFn: () => getDataSource(id as string),
    enabled: !!id,
  });
  const health = useQuery({
    queryKey: qk.datasources.health(id ?? ''),
    queryFn: () => getDatasourceHealth(id as string),
    enabled: !!id,
    refetchInterval: 30_000,
  });

  if (ds.isLoading) return <LoadingSkeleton rows={6} />;
  if (ds.isError || !ds.data)
    return <ErrorState error={ds.error} onRetry={() => void ds.refetch()} />;

  const data = ds.data;

  const runTask = async (fn: () => Promise<any>, label: string) => {
    try {
      const res = await fn();
      const runId = res?.id ?? res?.runId ?? res?.scanRunId;
      if (runId) {
        Modal.success({
          title: `${label}已提交`,
          content: <TaskProgressLink id={runId} label={`查看任务 #${runId}`} />,
        });
      } else {
        message.success(`${label}已提交`);
      }
    } catch (e: any) {
      message.error(toUserMessage(e, `${label}提交失败`));
    }
  };

  return (
    <div>
      <PageHeader
        title={data.name ?? data.code ?? `数据源 #${data.id}`}
        breadcrumb={[{ title: '数据源' }, { title: String(data.code ?? data.id) }]}
        extra={
          <Space>
            <Button onClick={() => setScanOpen(true)}>立即扫描</Button>
            <Button onClick={() => void runTask(() => classifyDatasource(data.id), '分级')}>
              立即分级
            </Button>
            {data.enabled ? (
              <ConfirmDanger
                title="停用数据源"
                description={`停用后将不再对其执行扫描等操作：${data.code ?? data.id}`}
                okText="停用"
                onConfirm={async () => {
                  try {
                    await disableDataSource(data.id);
                    message.success('已停用');
                    void ds.refetch();
                  } catch (e: any) {
                    message.error(toUserMessage(e, '操作失败'));
                  }
                }}
              >
                <Button>停用</Button>
              </ConfirmDanger>
            ) : (
              <Button
                onClick={async () => {
                  try {
                    await enableDataSource(data.id);
                    message.success('已启用');
                    void ds.refetch();
                  } catch (e: any) {
                    message.error(toUserMessage(e, '操作失败'));
                  }
                }}
              >
                启用
              </Button>
            )}
          </Space>
        }
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="ID">{data.id}</Descriptions.Item>
          <Descriptions.Item label="编码">{data.code ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="名称">{data.name ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="类型">{data.dsType ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="状态">
            {data.enabled ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {data.createdAt ? String(data.createdAt).replace('T', ' ').slice(0, 19) : '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        size="small"
        title="健康状态"
        style={{ marginBottom: 16 }}
        extra={<Button size="small" onClick={() => void health.refetch()}>刷新</Button>}
      >
        {health.isLoading ? (
          <LoadingSkeleton rows={2} />
        ) : health.isError ? (
          <ErrorState error={health.error} onRetry={() => void health.refetch()} />
        ) : (
          <Space direction="vertical">
            <Typography.Text>
              状态：<Tag>{health.data?.status ?? '-'}</Tag>
            </Typography.Text>
            <Typography.Text>
              最近扫描：<Tag>{health.data?.lastScanStatus ?? '-'}</Tag>
              {health.data?.lastScanAt
                ? ` @ ${String(health.data.lastScanAt).replace('T', ' ').slice(0, 19)}`
                : ''}
            </Typography.Text>
            {health.data?.message ? (
              <Typography.Text type="secondary">{health.data.message}</Typography.Text>
            ) : null}
          </Space>
        )}
      </Card>

      <Card size="small" title="原始配置">
        <JsonView value={data} />
      </Card>
      <ScanModal
        open={scanOpen}
        title={`扫描 ${data.code ?? data.id}`}
        confirmLoading={scanLoading}
        onCancel={() => setScanOpen(false)}
        onConfirm={async (allowWrite) => {
          setScanLoading(true);
          try {
            const res = await scanDatasource(data.id, { allowWrite });
            const runId = res?.id ?? res?.runId ?? res?.scanRunId;
            if (runId) {
              Modal.success({
                title: '扫描已提交',
                content: <TaskProgressLink id={runId} label={`查看任务 #${runId}`} />,
              });
            } else {
              message.success('扫描完成');
            }
            void ds.refetch();
          } catch (e: any) {
            message.error(toUserMessage(e, '扫描失败'));
          } finally {
            setScanLoading(false);
            setScanOpen(false);
          }
        }}
      />
    </div>
  );
}
