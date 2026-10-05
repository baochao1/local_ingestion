import { Card, Collapse, Descriptions, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from '@/components/DataTable';
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { getAsset } from '@/api/catalog';
import { qk } from '@/api/keys';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import GradeTag from '@/components/GradeTag';
import JsonView from '@/components/JsonView';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import SuspenseSection from '@/components/SuspenseSection';
import { useDatasourceName } from '@/hooks/useDatasourceName';
import type { AssetDetailCard, AssetDetailColumn } from '@/types';
import { columnDetailLink } from '@/utils/assets';

/**
 * 表详情聚合视图（FE-01 §4.2）。
 *
 * 路由参数：`?fqn=<表 FQN>`。后端只有 `/api/v1/assets/{fqn}`，此前按数字 id
 * 取导致 100% 404（ux-audit-full.md S0#1），现全站统一走 FQN。
 */
export default function TableDetailPage() {
  const [searchParams] = useSearchParams();
  const fqn = searchParams.get('fqn') ?? '';

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.catalog.table(fqn),
    queryFn: () => getAsset(fqn),
    enabled: !!fqn,
  });
  // hook 必须在任何提前 return 之前调用
  const dsName = useDatasourceName(data?.datasourceId ?? null);

  if (!fqn) {
    return <EmptyState description="缺少资产 FQN，请从资产目录进入" />;
  }
  if (isLoading) return <LoadingSkeleton rows={8} />;
  if (isError || !data)
    return <ErrorState error={error} onRetry={() => void refetch()} />;

  const rows = data.columns ?? [];

  const fieldColumns: ColumnsType<AssetDetailColumn> = [
    {
      title: '字段名',
      dataIndex: 'name',
      width: 220,
      render: (v?: string) =>
        v ? (
          <Space size={4}>
            <Link to={columnDetailLink(`${data.fqn}.${v}`, data.fqn ?? null)}>{v}</Link>
            {rows.find((c) => c.name === v)?.isPii ? <Tag color="red">敏感</Tag> : null}
          </Space>
        ) : (
          '-'
        ),
    },
    { title: '类型', dataIndex: 'dataType', width: 140, render: (v?: string) => v ?? '-' },
    {
      title: '可空',
      dataIndex: 'nullable',
      width: 90,
      render: (v?: boolean) => (v == null ? '-' : v ? '是' : '否'),
    },
    { title: '说明', dataIndex: 'comment', render: (v?: string | null) => v ?? '-' },
  ];

  return (
    <div>
      <PageHeader
        title={String(data.name ?? data.fqn ?? '资产详情')}
        subtitle={`表 · ${String(data.fqn ?? '-')}`}
        breadcrumb={[
          { title: <Link to="/app/catalog">资产目录</Link> },
          { title: String(data.name ?? data.fqn ?? '') },
        ]}
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="FQN">
            <span className="mono">{String(data.fqn ?? '-')}</span>
          </Descriptions.Item>
          <Descriptions.Item label="类型">{data.entityType ?? 'table'}</Descriptions.Item>
          {/* 字段缺失时整行不渲染，避免出现空 Tag / “-” 污染页面 */}
          {data.gradeLevel != null ? (
            <Descriptions.Item label="分级">
              <GradeTag level={Number(data.gradeLevel)} />
            </Descriptions.Item>
          ) : null}
          {data.owner ? (
            <Descriptions.Item label="负责人">{String(data.owner)}</Descriptions.Item>
          ) : null}
          {data.datasourceId != null ? (
            <Descriptions.Item label="数据源">
              <Link to={`/app/datasources/${data.datasourceId}`}>{dsName}</Link>
            </Descriptions.Item>
          ) : null}
          {data.tags && data.tags.length > 0 ? (
            <Descriptions.Item label="标签">
              <Space size={4}>
                {data.tags.map((t) => (
                  <Tag key={t}>{t}</Tag>
                ))}
              </Space>
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item label="描述" span={2}>
            {data.description ? String(data.description) : '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card size="small" title={`字段（${rows.length}）`} style={{ marginBottom: 16 }}>
        {rows.length > 0 ? (
          <Table<AssetDetailColumn>
            columns={fieldColumns}
            dataSource={rows}
            rowKey={(r) => String(r.fqn ?? r.name ?? '')}
            size="small"
            pagination={rows.length > 20 ? { pageSize: 20 } : false}
            scroll={{ x: 800 }}
          />
        ) : (
          <EmptyState description="该表暂无字段信息（可能未完成扫描）" />
        )}
      </Card>

      <SuspenseSection available={false} title="画像与质量（MOD-04）" />
      <div style={{ height: 16 }} />
      <SuspenseSection available={false} title="血缘（MOD-07）" />
      <div style={{ height: 16 }} />
      <SuspenseSection available={false} title="权限分析（MOD-08）" />
      <div style={{ height: 16 }} />

      {/* 原始响应收进折叠面板：排查仍需要，但不再是阅读主线（S1#11） */}
      <Collapse
        items={[
          {
            key: 'raw',
            label: <Typography.Text type="secondary">原始响应（调试用）</Typography.Text>,
            children: <JsonView value={data as AssetDetailCard} />,
          },
        ]}
      />
    </div>
  );
}
