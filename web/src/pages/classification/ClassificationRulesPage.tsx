import { Card, Table, Tag, Tooltip, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { listClassificationRules, listClassificationTags } from '@/api/classification';
import type { ClassificationRule } from '@/api/classification';
import ErrorState from '@/components/ErrorState';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';

/** 规则类型的中文说明（后端 rule_kind 枚举）。 */
const RULE_KIND_TEXT: Record<string, { label: string; hint: string }> = {
  column_name: { label: '列名匹配', hint: '按字段名的关键词判断（如 phone / email）' },
  regex: { label: '正则匹配', hint: '按字段值格式匹配（采样回验时使用）' },
  data_type: { label: '类型匹配', hint: '按字段数据类型判断' },
  sample_verify: { label: '采样回验', hint: '用实际数据样本验证，置信度最高' },
};

/**
 * 识别规则（MOD-05 / FR-9.2、FR-9.3）。
 *
 * 规则来自 `classification_rule` 表；引擎按 `priority` 升序求值，
 * 先命中者胜出——所以「优先级」列对排查误报很关键。
 */
export default function ClassificationRulesPage() {
  const rules = useQuery({ queryKey: ['classification', 'rules'], queryFn: listClassificationRules });
  const tags = useQuery({ queryKey: ['classification', 'tags'], queryFn: listClassificationTags });

  if (rules.isLoading) return <LoadingSkeleton rows={6} />;
  if (rules.isError) return <ErrorState error={rules.error} onRetry={() => void rules.refetch()} />;

  const tagNames = new Map((tags.data?.items ?? []).map((t) => [t.tagKey, t.tagName]));
  const items = rules.data?.items ?? [];

  return (
    <div>
      <PageHeader
        title="识别规则"
        subtitle="按优先级升序求值，先命中者胜出；优先级数字越小越先匹配"
      />
      <Card size="small">
        <Table<ClassificationRule>
          size="small"
          rowKey="id"
          dataSource={items}
          pagination={false}
          locale={{ emptyText: '暂无识别规则' }}
          columns={[
            {
              title: '目标标签',
              dataIndex: 'tagKey',
              width: 200,
              render: (v: string) => (
                <span>
                  {tagNames.get(v) ? `${tagNames.get(v)} ` : ''}
                  <span className="mono" style={{ opacity: 0.65 }}>
                    {v}
                  </span>
                </span>
              ),
            },
            {
              title: '规则类型',
              dataIndex: 'ruleKind',
              width: 140,
              render: (v: string) => {
                const meta = RULE_KIND_TEXT[v];
                return meta ? (
                  <Tooltip title={meta.hint}>
                    <Tag>{meta.label}</Tag>
                  </Tooltip>
                ) : (
                  <Tag>{v}</Tag>
                );
              },
            },
            {
              title: '匹配模式',
              dataIndex: 'pattern',
              render: (v?: string | null) =>
                v ? (
                  <span className="mono" style={{ wordBreak: 'break-all' }}>
                    {v}
                  </span>
                ) : (
                  '—'
                ),
            },
            {
              title: '置信度',
              dataIndex: 'confidence',
              width: 100,
              render: (v: number) => v.toFixed(3),
            },
            {
              title: '优先级',
              dataIndex: 'priority',
              width: 90,
              sorter: (a: ClassificationRule, b: ClassificationRule) => a.priority - b.priority,
            },
            {
              title: '状态',
              dataIndex: 'enabled',
              width: 90,
              render: (v: boolean) => (v ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
            },
          ]}
        />
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 12 }}>
          当前引擎内置的关键词词典（中英文）与这些规则并行生效；本表展示的是表驱动的规则集。
        </Typography.Text>
      </Card>
    </div>
  );
}
