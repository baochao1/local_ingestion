import { Button, Descriptions, Form, Input, Modal, Select, Space, Table, Tag } from 'antd';
import type { ColumnsType } from '@/components/DataTable';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import {
  addApprovalComment,
  approveApproval,
  createApproval,
  listApprovalComments,
  listApprovals,
  rejectApproval,
  toItems,
} from '@/api/governance';
import { qk } from '@/api/keys';
import { toUserMessage } from '@/api/errors';
import { currentActor } from '@/api/client';
import type { ApprovalCreatePayload } from '@/api/governance';
import ConfirmDanger from '@/components/ConfirmDanger';
import DetailDrawer from '@/components/DetailDrawer';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import FilterBar from '@/components/FilterBar';
import type { FilterValues } from '@/components/FilterBar';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import StatusTag from '@/components/StatusTag';
import type { ApprovalComment, ApprovalRequest } from '@/types';
import { App } from 'antd';

const APPROVAL_STATUS_MAP = {
  pending: { color: '#faad14', label: '待审批' },
  approved: { color: '#52c41a', label: '已通过' },
  rejected: { color: '#ff4d4f', label: '已驳回' },
};

/** 审批流（FE-01 §15.1）。后端字段为 snake_case，列表筛选参数为 status_filter。 */
export default function ApprovalsPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [filters, setFilters] = useState<FilterValues>({});
  const [openId, setOpenId] = useState<number | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [form] = Form.useForm();
  const [createForm] = Form.useForm();

  const params = useMemo(
    () => ({
      status_filter: filters.status as string | undefined,
      resource_type: filters.resourceType as string | undefined,
      approver: filters.approver as string | undefined,
    }),
    [filters],
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.governance.approvals(params),
    queryFn: () => listApprovals(params),
  });

  const items = toItems<ApprovalRequest>(data);

  const detail = useQuery({
    queryKey: qk.governance.approval(openId ?? 0),
    queryFn: () =>
      items.find((i) => i.id === openId) ?? Promise.resolve(null as ApprovalRequest | null),
    enabled: openId != null,
  });

  const comments = useQuery({
    queryKey: qk.governance.approvalComments(openId ?? 0),
    queryFn: () => listApprovalComments(openId as number),
    enabled: openId != null,
  });

  const decide = useMutation({
    mutationFn: ({ id, ok, note }: { id: number; ok: boolean; note?: string }) =>
      ok ? approveApproval(id, { note }) : rejectApproval(id, { note }),
    onSuccess: () => {
      message.success('已提交决策');
      void qc.invalidateQueries({ queryKey: ['governance'] });
      setOpenId(null);
    },
    onError: (e: unknown) => message.error(toUserMessage(e, '操作失败')),
  });

  const commentMut = useMutation({
    mutationFn: (content: string) =>
      addApprovalComment(openId as number, { author: 'console', content }),
    onSuccess: () => {
      form.resetFields();
      void qc.invalidateQueries({ queryKey: qk.governance.approvalComments(openId ?? 0) });
    },
    onError: (e: unknown) => message.error(toUserMessage(e, '评论失败')),
  });

  const createMut = useMutation({
    mutationFn: (values: ApprovalCreatePayload) => createApproval(values),
    onSuccess: () => {
      message.success('审批已提交');
      setCreateOpen(false);
      createForm.resetFields();
      void qc.invalidateQueries({ queryKey: ['governance'] });
    },
    onError: (e: unknown) => message.error(toUserMessage(e, '提交失败')),
  });

  const columns: ColumnsType<ApprovalRequest> = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '标题', dataIndex: 'title', width: 200 },
    {
      title: '资源',
      dataIndex: 'resource_fqn',
      width: 240,
      render: (v?: string) => <span className="mono">{v ?? '-'}</span>,
    },
    // 后端返回 action_type / requested_by：此前取 action / requester 导致三列恒为空（B4）
    {
      title: '动作',
      dataIndex: 'action_type',
      width: 120,
      render: (v?: string) => v ?? '-',
    },
    { title: '发起人', dataIndex: 'requested_by', width: 110, render: (v?: string) => v ?? '-' },
    { title: '审批人', dataIndex: 'approver', width: 110, render: (v?: string) => v ?? '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v?: string) => <StatusTag status={v ?? '-'} mapping={APPROVAL_STATUS_MAP} />,
    },
    {
      title: '操作',
      width: 160,
      render: (_v, r) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => setOpenId(r.id)}>
            详情
          </Button>
          <ConfirmDanger
            title="确认通过该审批？"
            description={`审批「${r.title ?? `#${r.id}`}」将标记为已通过，资源 ${r.resource_fqn ?? '-'} 可继续后续动作。`}
            disabled={r.status !== 'pending'}
            onConfirm={() => decide.mutate({ id: r.id, ok: true })}
          >
            <Button type="link" size="small" disabled={r.status !== 'pending'}>
              通过
            </Button>
          </ConfirmDanger>
          <ConfirmDanger
            title="确认驳回该审批？"
            description={`审批「${r.title ?? `#${r.id}`}」将被驳回，操作人需要修改后重新提交。`}
            disabled={r.status !== 'pending'}
            onConfirm={() => decide.mutate({ id: r.id, ok: false })}
          >
            <Button type="link" size="small" danger disabled={r.status !== 'pending'}>
              驳回
            </Button>
          </ConfirmDanger>
        </Space>
      ),
    },
  ];

  const current = detail.data ?? items.find((i) => i.id === openId) ?? null;

  return (
    <div>
      <PageHeader
        title="审批流"
        subtitle="MOD-12：发布/分级/敏感标记/删除等动作的审批"
        extra={
          <Button type="primary" onClick={() => setCreateOpen(true)}>
            提交审批
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
              { label: '待审批', value: 'pending' },
              { label: '已通过', value: 'approved' },
              { label: '已驳回', value: 'rejected' },
            ],
          },
          { name: 'resourceType', label: '资源类型', type: 'text' },
          { name: 'approver', label: '审批人', type: 'text' },
        ]}
        values={filters}
        onChange={setFilters}
      />

      {isLoading ? (
        <LoadingSkeleton rows={6} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : items.length === 0 ? (
        <EmptyState description="暂无审批" />
      ) : (
        <Table<ApprovalRequest>
          columns={columns}
          dataSource={items}
          rowKey="id"
          size="small"
          pagination={false}
          scroll={{ x: 1100 }}
        />
      )}

      <DetailDrawer
        open={openId != null}
        onClose={() => setOpenId(null)}
        title={current?.title ?? '审批详情'}
        width={720}
        extra={
          current?.status === 'pending' ? (
            <Space>
              <ConfirmDanger
                title="确认通过该审批？"
                description={`审批「${current.title ?? `#${current.id}`}」将标记为已通过。`}
                auditHint="决策记录与操作人将被审计"
                onConfirm={() => decide.mutate({ id: current.id, ok: true, note: form.getFieldValue('note') })}
              >
                <Button type="primary">通过</Button>
              </ConfirmDanger>
              <ConfirmDanger
                title="确认驳回该审批？"
                description={`审批「${current.title ?? `#${current.id}`}」将被驳回。`}
                auditHint="决策记录与操作人将被审计"
                onConfirm={() => decide.mutate({ id: current.id, ok: false, note: form.getFieldValue('note') })}
              >
                <Button danger>驳回</Button>
              </ConfirmDanger>
            </Space>
          ) : undefined
        }
      >
        {current ? (
          <>
            <Descriptions column={1} size="small" bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="资源">{current.resource_fqn ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="动作">{current.action_type ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <StatusTag status={current.status ?? '-'} mapping={APPROVAL_STATUS_MAP} />
              </Descriptions.Item>
              <Descriptions.Item label="理由">{current.reason ?? '-'}</Descriptions.Item>
              <Descriptions.Item label="决策意见">
                {/* 后端落库字段名是 decided_comment */}
                {(current.decided_comment ?? current.decision_note ?? '-') as string}
              </Descriptions.Item>
            </Descriptions>

            <div style={{ marginBottom: 8 }}>
              {(comments.data ?? []).map((c: ApprovalComment, i: number) => (
                <div key={i} style={{ marginBottom: 6 }}>
                  <Tag>{c.author ?? '-'}</Tag>
                  <span>{c.content ?? ''}</span>
                </div>
              ))}
            </div>

            <Form form={form} layout="vertical">
              <Form.Item name="note" label="意见 / 评论">
                <Input.TextArea rows={3} placeholder="审批意见或评论内容" />
              </Form.Item>
              <Space>
                <Button
                  onClick={() => {
                    const content = form.getFieldValue('note');
                    if (!content) return;
                    commentMut.mutate(content);
                  }}
                >
                  追加评论
                </Button>
              </Space>
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
        title="提交审批"
        destroyOnHidden
      >
        <Form
          form={createForm}
          layout="vertical"
          initialValues={{ resource_type: 'asset', action_type: 'publish', requested_by: currentActor() }}
          onFinish={(v) => createMut.mutate(v as ApprovalCreatePayload)}
        >
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="resource_type" label="资源类型" rules={[{ required: true }]}>
            <Input placeholder="如 asset / table" />
          </Form.Item>
          <Form.Item name="resource_fqn" label="资源 FQN" rules={[{ required: true }]}>
            <Input className="mono" placeholder="如 seed.schema.tbl1" />
          </Form.Item>
          <Form.Item name="action_type" label="动作" rules={[{ required: true }]}>
            <Select
              options={['publish', 'classify', 'sensitive_tag', 'delete'].map((v) => ({
                label: v,
                value: v,
              }))}
            />
          </Form.Item>
          <Form.Item name="requested_by" label="发起人" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="approver" label="审批人">
            <Input />
          </Form.Item>
          <Form.Item name="reason" label="理由">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
