import {
  Button,
  Descriptions,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from '@/components/DataTable';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import {
  addTicketComment,
  assignTicket,
  createTicket,
  listTicketComments,
  listTickets,
  toItems,
  transitionTicket,
} from '@/api/governance';
import { qk } from '@/api/keys';
import { toUserMessage } from '@/api/errors';
import DetailDrawer from '@/components/DetailDrawer';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import FilterBar from '@/components/FilterBar';
import type { FilterValues } from '@/components/FilterBar';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import StatusTag from '@/components/StatusTag';
import type { Ticket, TicketComment } from '@/types';
import { App } from 'antd';

const TICKET_STATUS_MAP = {
  open: { color: '#faad14', label: '待处理' },
  in_progress: { color: '#2f54eb', label: '处理中' },
  resolved: { color: '#52c41a', label: '已解决' },
  closed: { color: '#8c8c8c', label: '已关闭' },
};

const PRIORITY_COLOR: Record<string, string> = {
  P0: '#ff4d4f',
  P1: '#faad14',
  P2: '#2f54eb',
  P3: '#8c8c8c',
};

/** 工单（FE-01 §15.2）。含 change_auto 联动标记。 */
export default function TicketsPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [filters, setFilters] = useState<FilterValues>({});
  const [openId, setOpenId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  /** 待确认的状态流转：选中 ≠ 提交（ux-audit-full.md S1#8）。 */
  const [pendingTransition, setPendingTransition] = useState<{
    id: number;
    from: string;
    to: string;
  } | null>(null);
  const [form] = Form.useForm();
  const [createForm] = Form.useForm();

  const statusLabel = (s: string) => TICKET_STATUS_MAP[s as keyof typeof TICKET_STATUS_MAP]?.label ?? s;

  const params = useMemo(
    () => ({
      status_filter: filters.status as string | undefined,
      ticket_type: filters.ticketType as string | undefined,
      assignee: filters.assignee as string | undefined,
    }),
    [filters],
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.governance.tickets(params),
    queryFn: () => listTickets(params),
  });

  const items = toItems<Ticket>(data);

  const comments = useQuery({
    queryKey: qk.governance.ticketComments(openId ?? 0),
    queryFn: () => listTicketComments(openId as number),
    enabled: openId != null,
  });

  const assignMut = useMutation({
    mutationFn: ({ id, assignee }: { id: number; assignee: string }) =>
      assignTicket(id, { assignee }),
    onSuccess: () => {
      message.success('已分派');
      void qc.invalidateQueries({ queryKey: ['governance'] });
    },
    onError: (e: unknown) => message.error(toUserMessage(e, '分派失败')),
  });

  const transitionMut = useMutation({
    mutationFn: ({ id, status }: { id: number; status: string }) =>
      transitionTicket(id, { to_status: status }),
    onSuccess: () => {
      message.success('状态已流转');
      setPendingTransition(null);
      void qc.invalidateQueries({ queryKey: ['governance'] });
    },
    onError: (e: unknown) => message.error(toUserMessage(e, '流转失败')),
  });

  const commentMut = useMutation({
    mutationFn: (content: string) =>
      addTicketComment(openId as number, { author: 'console', content }),
    onSuccess: () => {
      form.resetFields();
      void qc.invalidateQueries({ queryKey: qk.governance.ticketComments(openId ?? 0) });
    },
    onError: (e: unknown) => message.error(toUserMessage(e, '评论失败')),
  });

  const createMut = useMutation({
    mutationFn: (values: Record<string, unknown>) => createTicket(values),
    onSuccess: () => {
      message.success('工单已创建');
      setCreateOpen(false);
      createForm.resetFields();
      void qc.invalidateQueries({ queryKey: ['governance'] });
    },
    onError: (e: unknown) => message.error(toUserMessage(e, '创建失败')),
  });

  const columns: ColumnsType<Ticket> = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '标题', dataIndex: 'title', width: 220 },
    {
      title: '类型',
      dataIndex: 'ticket_type',
      width: 120,
      render: (v?: string) =>
        v === 'change_auto' ? <Tag color="purple">自动生成</Tag> : <Tag>{v ?? '-'}</Tag>,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 90,
      render: (v?: string) =>
        v ? <Tag color={PRIORITY_COLOR[v] ?? 'default'}>{v}</Tag> : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v?: string) => <StatusTag status={v ?? '-'} mapping={TICKET_STATUS_MAP} />,
    },
    { title: '报告人', dataIndex: 'reporter', width: 110 },
    { title: '处理人', dataIndex: 'assignee', width: 110 },
    {
      title: '关联 FQN',
      dataIndex: 'related_fqn',
      width: 220,
      render: (v?: string) => <span className="mono">{v ?? '-'}</span>,
    },
    {
      title: '操作',
      width: 200,
      render: (_v, r) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => setOpenId(r.id)}>
            详情
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => {
              const name = window.prompt('分派给（用户名）', r.assignee ?? '');
              if (name) assignMut.mutate({ id: r.id, assignee: name });
            }}
          >
            分派
          </Button>
          <Select
            size="small"
            style={{ width: 110 }}
            placeholder="流转"
            value={undefined}
            onChange={(v: string) => setPendingTransition({ id: r.id, from: r.status ?? '-', to: v })}
            options={['open', 'in_progress', 'resolved', 'closed'].map((s) => ({
              label: statusLabel(s),
              value: s,
              disabled: s === r.status,
            }))}
          />
        </Space>
      ),
    },
  ];

  const current = items.find((i) => i.id === openId) ?? null;

  return (
    <div>
      <PageHeader
        title="工单"
        subtitle="MOD-12：数据问题 / 权限申请 / 破坏性变更自动跟进"
        extra={
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            新建工单
          </Button>
        }
      />
      <FilterBar
        fields={[
          {
            name: 'status',
            label: '状态',
            type: 'select',
            options: [
              { label: '待处理', value: 'open' },
              { label: '处理中', value: 'in_progress' },
              { label: '已解决', value: 'resolved' },
              { label: '已关闭', value: 'closed' },
            ],
          },
          {
            name: 'ticketType',
            label: '类型',
            type: 'select',
            options: ['data_issue', 'access_request', 'change_auto', 'other'].map((v) => ({
              label: v,
              value: v,
            })),
          },
          { name: 'assignee', label: '处理人', type: 'text' },
        ]}
        values={filters}
        onChange={setFilters}
      />

      {isLoading ? (
        <LoadingSkeleton rows={6} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : items.length === 0 ? (
        <EmptyState description="暂无工单" />
      ) : (
        <Table<Ticket>
          columns={columns}
          dataSource={items}
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ x: 1300 }}
        />
      )}

      <Modal
        open={pendingTransition != null}
        title="确认流转工单状态"
        okText="确认流转"
        cancelText="取消"
        okButtonProps={{ danger: pendingTransition?.to === 'closed' }}
        confirmLoading={transitionMut.isPending}
        onCancel={() => setPendingTransition(null)}
        onOk={() =>
          pendingTransition &&
          transitionMut.mutate({ id: pendingTransition.id, status: pendingTransition.to })
        }
      >
        <Space direction="vertical" size={4}>
          <span>
            工单 #{pendingTransition?.id} 的状态将从
            <Typography.Text strong> {statusLabel(pendingTransition?.from ?? '-')} </Typography.Text>
            变更为
            <Typography.Text strong> {statusLabel(pendingTransition?.to ?? '-')} </Typography.Text>
            。
          </span>
          <Typography.Text type="warning">状态流转会同步写入审计日志。</Typography.Text>
        </Space>
      </Modal>

      <DetailDrawer
        open={openId != null}
        onClose={() => setOpenId(null)}
        title={current?.title ?? '工单详情'}
        width={720}
      >
        {current ? (
          <>
            <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="类型">{current.ticket_type ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <StatusTag status={current.status ?? '-'} mapping={TICKET_STATUS_MAP} />
              </Descriptions.Item>
              <Descriptions.Item label="优先级">{current.priority ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="处理人">{current.assignee ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="SLA 到期">
                {current.sla_due_at ? String(current.sla_due_at).replace('T', ' ').slice(0, 19) : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="关联 FQN">
                <span className="mono">{current.related_fqn ?? '-'}</span>
              </Descriptions.Item>
              <Descriptions.Item label="描述">{current.description ?? '-'}</Descriptions.Item>
            </Descriptions>

            <div style={{ marginBottom: 8 }}>
              {(comments.data ?? []).map((c: TicketComment, i: number) => (
                <div key={i} style={{ marginBottom: 6 }}>
                  <Tag>{c.author ?? '-'}</Tag>
                  <span>{c.content ?? ''}</span>
                </div>
              ))}
            </div>

            <Form form={form} layout="vertical">
              <Form.Item name="content" label="处理记录 / 评论">
                <Input.TextArea rows={3} />
              </Form.Item>
              <Button
                onClick={() => {
                  const content = form.getFieldValue('content');
                  if (!content) return;
                  commentMut.mutate(content);
                }}
              >
                追加评论
              </Button>
            </Form>
          </>
        ) : (
          <LoadingSkeleton rows={4} />
        )}
      </DetailDrawer>

      <Modal
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createForm.submit()}
        title="新建工单"
        destroyOnHidden
      >
        <Form form={createForm} layout="vertical" onFinish={(v) => createMut.mutate(v)}>
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="ticket_type" label="类型">
            <Select
              options={['data_issue', 'access_request', 'change_auto', 'other'].map((v) => ({
                label: v,
                value: v,
              }))}
            />
          </Form.Item>
          <Form.Item name="priority" label="优先级">
            <Select options={['P0', 'P1', 'P2', 'P3'].map((v) => ({ label: v, value: v }))} />
          </Form.Item>
          <Form.Item name="related_fqn" label="关联 FQN">
            <Input className="mono" />
          </Form.Item>
          <Form.Item name="sla_hours" label="SLA 小时数">
            <Input type="number" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
