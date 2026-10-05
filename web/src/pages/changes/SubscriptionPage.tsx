import { App, Button, Form, Input, Modal, Select, Space, Switch, Tag } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import {
  createSubscription,
  deleteSubscription,
  listSubscriptions,
  muteSubscription,
  unmuteSubscription,
} from '@/api/subscriptions';
import type { Subscription } from '@/api/subscriptions';
import { qk } from '@/api/keys';
import { toUserMessage } from '@/api/errors';
import type { ColumnsType } from '@/components/DataTable';
import ConfirmDanger from '@/components/ConfirmDanger';
import DataTable from '@/components/DataTable';
import EmptyState from '@/components/EmptyState';
import { useDatasourceNames } from '@/hooks/useDatasourceName';
import PageHeader from '@/components/PageHeader';

const SCOPE_TYPES = ['global', 'datasource', 'schema', 'table'];
const SEVERITIES = ['P0', 'P1', 'P2', 'P3'];
const CHANNELS = ['email', 'webhook', 'im'];

/** 订阅管理（MOD-06）：订阅已落库，可增删改查。 */
export default function SubscriptionPage() {
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const qc = useQueryClient();
  const { name: dsName } = useDatasourceNames();
  const invalidate = () => qc.invalidateQueries({ queryKey: qk.subscriptions.all });

  const createMut = useMutation({
    mutationFn: (data: Record<string, unknown>) => createSubscription(data),
    onSuccess: () => {
      message.success('订阅已创建');
      setOpen(false);
      form.resetFields();
      invalidate();
    },
    onError: (e: unknown) => message.error(toUserMessage(e, '创建失败')),
  });

  const toggle = async (s: Subscription) => {
    try {
      if (s.enabled) await muteSubscription(s.id);
      else await unmuteSubscription(s.id);
      message.success(s.enabled ? '已停用' : '已启用');
      invalidate();
    } catch (e: unknown) {
      message.error(toUserMessage(e, '操作失败'));
    }
  };

  const remove = async (s: Subscription) => {
    try {
      await deleteSubscription(s.id);
      message.success('已删除');
      invalidate();
    } catch (e: unknown) {
      message.error(toUserMessage(e, '删除失败'));
    }
  };

  const columns: ColumnsType<Subscription> = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '订阅人', dataIndex: 'subscriber', width: 200 },
    { title: '范围', dataIndex: 'scopeType', width: 110 },
    { title: '对象 FQN', dataIndex: 'scopeFqn', render: (v: string | null) => v ?? '-' },
    {
      title: '数据源',
      dataIndex: 'datasourceId',
      width: 150,
      render: (v: number | null) => (v == null ? '-' : dsName(v)),
    },
    { title: '最低级别', dataIndex: 'minSeverity', width: 100 },
    { title: '渠道', dataIndex: 'channel', width: 100 },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 90,
      render: (v?: boolean) =>
        v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>,
    },
    {
      title: '操作',
      width: 200,
      render: (_v, r) => (
        <Space size={4}>
          {r.enabled ? (
            // 停用会中断变更通知，需二次确认（与同列「删除」保持一致）
            <ConfirmDanger
              title="停用该订阅？"
              description={`停用后 ${r.subscriber ?? '该订阅人'} 将不再收到「${r.scopeFqn ?? r.scopeType ?? '该范围'}」的变更通知，可随时重新启用。`}
              okText="停用"
              onConfirm={() => toggle(r)}
            >
              <Button type="link" size="small" danger>
                停用
              </Button>
            </ConfirmDanger>
          ) : (
            <Button type="link" size="small" onClick={() => void toggle(r)}>
              启用
            </Button>
          )}
          <ConfirmDanger
            title="确认删除该订阅？"
            description={`删除后 ${r.subscriber ?? '该订阅人'} 将不再收到「${r.scopeFqn ?? r.scopeType ?? '该范围'}」的变更通知，需重新创建才能恢复。`}
            okText="删除"
            onConfirm={() => remove(r)}
          >
            <Button type="link" size="small" danger>
              删除
            </Button>
          </ConfirmDanger>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="订阅管理"
        subtitle="变更订阅：范围、级别、通知渠道"
        extra={
          <Button type="primary" onClick={() => setOpen(true)}>
            新建订阅
          </Button>
        }
      />
      <DataTable<Subscription>
        columns={columns}
        queryKey={qk.subscriptions.list({})}
        rowKey="id"
        scrollX={1100}
        empty={<EmptyState description="暂无订阅" />}
        fetcher={async () => listSubscriptions({})}
      />

      <Modal
        title="新建订阅"
        open={open}
        onCancel={() => setOpen(false)}
        destroyOnHidden
        onOk={() => form.submit()}
        confirmLoading={createMut.isPending}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ scopeType: 'global', minSeverity: 'P2', channel: 'email', enabled: true }}
          onFinish={(v) =>
            createMut.mutate({
              subscriber: v.subscriber,
              scopeType: v.scopeType,
              scopeFqn: v.scopeFqn || null,
              datasourceId: v.datasourceId ?? null,
              minSeverity: v.minSeverity,
              channel: v.channel,
              enabled: v.enabled,
            })
          }
        >
          <Form.Item label="订阅人" name="subscriber" rules={[{ required: true, message: '请输入订阅人' }]}>
            <Input placeholder="邮箱或账号" />
          </Form.Item>
          <Form.Item label="范围" name="scopeType">
            <Select options={SCOPE_TYPES.map((t) => ({ label: t, value: t }))} />
          </Form.Item>
          <Form.Item label="对象 FQN" name="scopeFqn">
            <Input placeholder="如 seed.schema.tbl1（global 可留空）" />
          </Form.Item>
          <Form.Item label="数据源 ID" name="datasourceId">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item label="最低级别" name="minSeverity">
            <Select options={SEVERITIES.map((t) => ({ label: t, value: t }))} />
          </Form.Item>
          <Form.Item label="通知渠道" name="channel">
            <Select options={CHANNELS.map((t) => ({ label: t, value: t }))} />
          </Form.Item>
          <Form.Item label="启用" name="enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
