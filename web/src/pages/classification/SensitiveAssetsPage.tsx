import { toUserMessage } from '@/api/errors';
import { App, Button, Card, Input, Modal, Select, Space, Tag, Typography } from 'antd';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { annotateEntity, listSensitiveAssets } from '@/api/classification';
import type { SensitiveAsset } from '@/api/classification';
import { listDatasources } from '@/api/datasources';
import type { ColumnsType } from '@/components/DataTable';
import DataTable from '@/components/DataTable';
import EmptyState from '@/components/EmptyState';
import FilterBar from '@/components/FilterBar';
import type { FilterValues } from '@/components/FilterBar';
import GradeTag from '@/components/GradeTag';
import PageHeader from '@/components/PageHeader';
import { columnDetailLink, tableDetailLink } from '@/utils/assets';

/**
 * 达到该级别的人工修正需走审批。与后端
 * `platform/classification/annotation.py::APPROVAL_REQUIRED_GRADE` 保持一致。
 */
const APPROVAL_REQUIRED_GRADE = 4;

/** 引擎给出的判定原因 → 中文。 */
const REASON_TEXT: Record<string, string> = {
  credential: '凭据 / 密钥',
  'credential:key': '凭据 / 密钥',
  'credential:cn': '凭据（中文列名）',
  identifier: '强标识（证件/银行卡）',
  'identifier:cn': '强标识（中文列名）',
  personal: '个人信息',
  'personal:name': '个人姓名',
  'personal:cn': '个人信息（中文列名）',
  business: '业务敏感',
  'business:money': '金额类型',
  'business:cn': '业务敏感（中文列名）',
  default: '默认（无规则命中）',
  'no-columns': '表内无字段',
};

function reasonText(reason?: string | null): string {
  if (!reason) return '—';
  if (reason.startsWith('max-column:')) {
    return `来自最敏感的字段：${reasonText(reason.slice('max-column:'.length))}`;
  }
  return REASON_TEXT[reason] ?? reason;
}

/**
 * 敏感资产清单（MOD-05 / FR-9.8）。
 *
 * 这是分级结果的**主要出口**：在此之前，分级算完只写进 `catalog_column.grade_level`，
 * 唯一能被消费的地方是资产检索的 `gradeMin` 筛选——用户看不到「哪些字段敏感、
 * 在哪张表、为什么被判敏感」。
 */
export default function SensitiveAssetsPage() {
  const { message } = App.useApp();
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  /** 正在复核的条目（null 表示未打开弹窗）。 */
  const [editing, setEditing] = useState<SensitiveAsset | null>(null);
  const [newLevel, setNewLevel] = useState(1);
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [filters, setFilters] = useState<FilterValues>(() => {
    const ds = searchParams.get('datasourceId');
    return {
      gradeMin: 3,
      entityType: 'column',
      ...(ds ? { datasourceId: Number(ds) } : {}),
    };
  });

  const datasources = useQuery({
    queryKey: ['datasources', 'for-filter'],
    queryFn: () => listDatasources({}),
  });

  const params = useMemo(
    () => ({
      gradeMin: filters.gradeMin as number | undefined,
      entityType: (filters.entityType as 'column' | 'table') ?? 'column',
      datasourceId: filters.datasourceId as number | undefined,
      keyword: filters.keyword as string | undefined,
    }),
    [filters],
  );

  const dsOptions = (datasources.data?.items ?? []).map((d) => ({
    label: d.name ?? d.code ?? `#${d.id}`,
    value: d.id,
  }));

  const openReview = (row: SensitiveAsset) => {
    setEditing(row);
    setNewLevel(row.gradeLevel);
    setReason('');
  };

  /** 提交人工复核结论。L1–L3 直接生效；L4/L5 走审批。 */
  const submitReview = async () => {
    if (!editing) return;
    setSubmitting(true);
    try {
      const res = await annotateEntity(editing.entityType, editing.id, {
        gradeLevel: newLevel,
        reason: reason || undefined,
        entityFqn: editing.fqn,
      });
      if (res.pendingApproval) {
        message.info(`L${newLevel} 属于高敏级别，已提交审批（#${res.approvalId}），批准后生效`);
      } else {
        message.success(`已把「${editing.name}」修正为 L${newLevel}`);
      }
      setEditing(null);
      // 修正后该条目可能已不满足当前级别筛选，整个列表需要重取
      await qc.invalidateQueries({ queryKey: ['classification'] });
    } catch (e: unknown) {
      message.error(toUserMessage(e, '修正失败'));
    } finally {
      setSubmitting(false);
    }
  };

  const columns: ColumnsType<SensitiveAsset> = [
    {
      title: '字段',
      dataIndex: 'name',
      width: 220,
      render: (name: string, r) =>
        r.entityType === 'column' ? (
          <Link to={columnDetailLink(r.fqn, r.tableFqn ?? undefined)}>
            <span className="mono">{name}</span>
          </Link>
        ) : (
          <span className="mono">{name}</span>
        ),
    },
    {
      title: '所属表',
      dataIndex: 'tableName',
      width: 220,
      render: (v: string | null | undefined, r) =>
        r.entityType === 'table' || !r.tableFqn ? (
          '—'
        ) : (
          <Link to={tableDetailLink(r.tableFqn)}>
            <span className="mono">{v ?? r.tableFqn}</span>
          </Link>
        ),
    },
    {
      title: '类型',
      dataIndex: 'dataType',
      width: 170,
      render: (v?: string | null) => <span className="mono">{v ?? '—'}</span>,
    },
    {
      title: '级别',
      dataIndex: 'gradeLevel',
      width: 160,
      render: (v: number) => <GradeTag level={v} />,
    },
    {
      title: '判定原因',
      dataIndex: 'gradeReason',
      render: (v?: string | null) => reasonText(v),
    },
    {
      title: '标签',
      dataIndex: 'tags',
      width: 140,
      render: (tags?: string[]) =>
        tags && tags.length ? (
          <Space size={4}>
            {tags.map((t) => (
              <Tag key={t} color={t === 'PII' ? 'orange' : t === 'HIGH' ? 'red' : undefined}>
                {t}
              </Tag>
            ))}
          </Space>
        ) : (
          '—'
        ),
    },
    {
      title: '操作',
      width: 90,
      render: (_v: unknown, r: SensitiveAsset) => (
        <Button type="link" size="small" onClick={() => openReview(r)}>
          复核
        </Button>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="敏感资产清单"
        subtitle="达到指定级别的字段及其判定依据——分级结果的主要出口"
      />
      <FilterBar
        fields={[
          {
            name: 'gradeMin',
            label: '最低级别',
            type: 'select',
            options: [
              { label: 'L2 业务敏感及以上', value: 2 },
              { label: 'L3 个人信息及以上', value: 3 },
              { label: 'L4 高敏个人信息及以上', value: 4 },
              { label: 'L5 机密', value: 5 },
            ],
          },
          {
            name: 'entityType',
            label: '对象类型',
            type: 'select',
            options: [
              { label: '字段', value: 'column' },
              { label: '表', value: 'table' },
            ],
          },
          { name: 'datasourceId', label: '数据源', type: 'select', options: dsOptions },
          { name: 'keyword', label: '名称', type: 'text' },
        ]}
        values={filters}
        onChange={setFilters}
      />
      <DataTable<SensitiveAsset>
        columns={columns}
        queryKey={['classification', 'sensitive-assets', params]}
        filterKey={JSON.stringify(params)}
        rowKey="id"
        scrollX={1200}
        empty={
          <EmptyState
            description="该条件下没有敏感资产"
            extra={
              <Typography.Text type="secondary">
                可以放宽「最低级别」，或确认该数据源是否已跑过分级。
              </Typography.Text>
            }
          />
        }
        fetcher={async (cursor) => listSensitiveAssets({ ...params, cursor })}
      />
      <Card size="small" style={{ marginTop: 16 }}>
        <Typography.Text type="secondary">
          判定原因由识别引擎给出（列名词典 / 类型 / 采样回验）。若认为判定有误，
          用行内「复核」修正——人工结论的优先级高于自动识别，引擎重跑也不会覆盖。
        </Typography.Text>
      </Card>

      <Modal
        open={editing !== null}
        title="复核分级结果"
        okText="确认修正"
        cancelText="取消"
        confirmLoading={submitting}
        onOk={() => void submitReview()}
        onCancel={() => setEditing(null)}
      >
        {editing && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <div>
              <Typography.Text type="secondary">对象</Typography.Text>
              <div className="mono">{editing.fqn}</div>
            </div>
            <div>
              <Typography.Text type="secondary">当前级别</Typography.Text>
              <div style={{ marginTop: 4 }}>
                <GradeTag level={editing.gradeLevel} />
                {editing.gradeReason ? (
                  <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                    引擎依据：{reasonText(editing.gradeReason)}
                  </Typography.Text>
                ) : null}
              </div>
            </div>
            <div>
              <Typography.Text type="secondary">修正为</Typography.Text>
              <Select
                style={{ width: '100%', marginTop: 4 }}
                value={newLevel}
                onChange={setNewLevel}
                options={[
                  { value: 1, label: 'L1 内部（不含个人信息）' },
                  { value: 2, label: 'L2 业务敏感' },
                  { value: 3, label: 'L3 个人信息' },
                  { value: 4, label: 'L4 高敏个人信息' },
                  { value: 5, label: 'L5 机密' },
                ]}
              />
            </div>
            <div>
              <Typography.Text type="secondary">修正理由（可选，留档）</Typography.Text>
              <Input.TextArea
                rows={2}
                style={{ marginTop: 4 }}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="例如：这是表名而非人名，规则误报"
              />
            </div>
            {newLevel >= APPROVAL_REQUIRED_GRADE ? (
              <Typography.Text type="warning">
                L{APPROVAL_REQUIRED_GRADE}/L5 属于高敏级别，修正需经审批后生效。
              </Typography.Text>
            ) : (
              <Typography.Text type="warning">
                修正后该对象不会被自动识别覆盖，直到撤销人工标注。
              </Typography.Text>
            )}
          </Space>
        )}
      </Modal>
    </div>
  );
}
