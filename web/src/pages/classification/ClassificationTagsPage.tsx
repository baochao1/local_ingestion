import { Card, Table, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { listClassificationTags } from '@/api/classification';
import type { ClassificationTag } from '@/api/classification';
import ErrorState from '@/components/ErrorState';
import GradeTag from '@/components/GradeTag';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';

/**
 * 分级标准（MOD-05 / FR-9.1）。
 *
 * 数据来自 `classification_tag` 表——它此前**没有任何界面**，
 * 表里已有 seed 好的标准却无人能看到。
 */
export default function ClassificationTagsPage() {
  const q = useQuery({ queryKey: ['classification', 'tags'], queryFn: listClassificationTags });

  if (q.isLoading) return <LoadingSkeleton rows={6} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const items = q.data?.items ?? [];

  return (
    <div>
      <PageHeader title="分级标准" subtitle="标签库：每个标签的含义、类别与默认级别" />
      <Card size="small">
        <Table<ClassificationTag>
          size="small"
          rowKey="id"
          dataSource={items}
          pagination={false}
          locale={{ emptyText: '暂无分级标准' }}
          columns={[
            {
              title: '标签编码',
              dataIndex: 'tagKey',
              width: 180,
              render: (v: string) => <span className="mono">{v}</span>,
            },
            { title: '名称', dataIndex: 'tagName', width: 140 },
            {
              title: '类别',
              dataIndex: 'category',
              width: 120,
              render: (v?: string | null) => (v ? <Tag>{v}</Tag> : '—'),
            },
            {
              title: '默认级别',
              dataIndex: 'gradeLevel',
              width: 160,
              render: (v?: number | null) => (v ? <GradeTag level={v} /> : '—'),
            },
            { title: '说明', dataIndex: 'description', render: (v?: string | null) => v ?? '—' },
            {
              title: '状态',
              dataIndex: 'enabled',
              width: 90,
              render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
            },
          ]}
        />
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
          标签的「默认级别」是标签库自身的定级；字段的最终级别由识别引擎判定后写入
          `catalog_column.grade_level`，两者不一致时以引擎结果为准。
        </Typography.Text>
      </Card>
    </div>
  );
}
