import { toUserMessage } from '@/api/errors';
import { App, Button, Form, Input, Modal, Tag, message } from 'antd';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { createBusinessTerm, listBusinessTerms } from '@/api/business';
import type { BusinessTerm } from '@/api/business';
import { qk } from '@/api/keys';
import type { ColumnsType } from '@/components/DataTable';
import DataTable from '@/components/DataTable';
import EmptyState from '@/components/EmptyState';
import PageHeader from '@/components/PageHeader';

/** 业务术语表（MOD-09）：后端已落库，可查看与新增。 */
export default function BusinessTermsPage() {
  const { message } = App.useApp();
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: qk.business.terms() });

  const createMut = useMutation({
    mutationFn: (data: Record<string, unknown>) => createBusinessTerm(data),
    onSuccess: () => {
      message.success('术语已创建');
      setOpen(false);
      form.resetFields();
      invalidate();
    },
    onError: (e: any) => message.error(toUserMessage(e, '创建失败')),
  });

  const columns: ColumnsType<BusinessTerm> = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '术语编码', dataIndex: 'term_code', width: 180 },
    { title: '术语名称', dataIndex: 'term_name', width: 200 },
    { title: '域', dataIndex: 'domain', width: 120, render: (v: string | null) => v ?? '-' },
    { title: '定义', dataIndex: 'definition', render: (v: string | null) => v ?? '-' },
    { title: '负责人', dataIndex: 'owner', width: 120, render: (v: string | null) => v ?? '-' },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v?: string) => (v === 'active' ? <Tag color="green">生效</Tag> : <Tag>{v ?? '-'}</Tag>),
    },
  ];

  return (
    <div>
      <PageHeader
        title="业务术语表"
        subtitle="MOD-09：业务术语与定义"
        extra={
          <Button type="primary" onClick={() => setOpen(true)}>
            新建术语
          </Button>
        }
      />
      <DataTable<BusinessTerm>
        columns={columns}
        queryKey={qk.business.terms()}
        rowKey="id"
        scrollX={900}
        empty={<EmptyState description="暂无业务术语" />}
        fetcher={async () => {
          const res = await listBusinessTerms();
          const items = res?.terms ?? [];
          return { items, total: items.length, next_cursor: null };
        }}
      />

      <Modal
        title="新建业务术语"
        open={open}
        onCancel={() => setOpen(false)}
        destroyOnHidden
        onOk={() => form.submit()}
        confirmLoading={createMut.isPending}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ status: 'active' }}
          onFinish={(v) => createMut.mutate(v)}
        >
          <Form.Item label="术语编码" name="term_code" rules={[{ required: true, message: '请输入编码' }]}>
            <Input placeholder="如 term_order_amount" />
          </Form.Item>
          <Form.Item label="术语名称" name="term_name" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如 订单金额" />
          </Form.Item>
          <Form.Item label="业务域" name="domain">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item label="定义" name="definition">
            <Input.TextArea rows={3} placeholder="可选" />
          </Form.Item>
          <Form.Item label="负责人" name="owner">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item label="状态" name="status">
            <Input placeholder="active" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
