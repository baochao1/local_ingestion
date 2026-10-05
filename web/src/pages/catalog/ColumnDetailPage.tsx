import { Button, Card, Collapse, Descriptions, Space, Tag, Typography } from 'antd';
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
import { guessParentFqn, tableDetailLink } from '@/utils/assets';

/**
 * 字段详情（FE-01 §4.3）。
 *
 * 路由参数：`?fqn=<字段 FQN>&parent=<父表 FQN>`。
 * 后端 `/api/v1/assets/{fqn}` 已支持字段 FQN（含父表回指），因此这里与表详情
 * 共用同一个接口；`parent` 缺省时按「列 FQN = 父表 FQN + 列名」推断。
 */
export default function ColumnDetailPage() {
  const [searchParams] = useSearchParams();
  const fqn = searchParams.get('fqn') ?? '';
  const parentFqn = searchParams.get('parent') ?? guessParentFqn(fqn) ?? '';

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.catalog.column(fqn),
    queryFn: () => getAsset(fqn),
    enabled: !!fqn,
  });
  const dsName = useDatasourceName(data?.datasourceId ?? null);

  if (!fqn) {
    return <EmptyState description="缺少字段 FQN，请从资产目录或表详情进入" />;
  }
  if (isLoading) return <LoadingSkeleton rows={6} />;
  if (isError || !data)
    return <ErrorState error={error} onRetry={() => void refetch()} />;

  return (
    <div>
      <PageHeader
        title={String(data.name ?? data.fqn ?? '字段详情')}
        subtitle={`字段 · ${String(data.fqn ?? '-')}`}
        breadcrumb={[
          { title: <Link to="/app/catalog">资产目录</Link> },
          { title: <Link to={tableDetailLink(parentFqn)}>{parentFqn || '所属表'}</Link> },
          { title: String(data.name ?? data.fqn ?? '') },
        ]}
        extra={
          <Button>
            <Link to={`/app/changes/entities/column/${encodeURIComponent(fqn)}/history`}>
              变更历史
            </Link>
          </Button>
        }
      />

      <Card size="small" style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="FQN">
            <span className="mono">{String(data.fqn ?? '-')}</span>
          </Descriptions.Item>
          <Descriptions.Item label="所属表">
            {parentFqn ? (
              <Link to={tableDetailLink(parentFqn)} className="mono">
                {parentFqn}
              </Link>
            ) : (
              '-'
            )}
          </Descriptions.Item>
          <Descriptions.Item label="数据类型">
            {String(data.dataType ?? '-')}
          </Descriptions.Item>
          <Descriptions.Item label="可空">
            {data.nullable == null ? '-' : data.nullable ? '是' : '否'}
          </Descriptions.Item>
          {data.gradeLevel != null ? (
            <Descriptions.Item label="分级">
              <GradeTag level={Number(data.gradeLevel)} />
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item label="敏感">
            {data.isPii ? <Tag color="red">是</Tag> : <Tag>否</Tag>}
          </Descriptions.Item>
          {data.owner ? (
            <Descriptions.Item label="负责人">{String(data.owner)}</Descriptions.Item>
          ) : null}
          {data.datasourceId != null ? (
            <Descriptions.Item label="数据源">
              <Link to={`/app/datasources/${data.datasourceId}`}>{dsName}</Link>
            </Descriptions.Item>
          ) : null}
          <Descriptions.Item label="描述" span={2}>
            {data.description ? String(data.description) : '-'}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <SuspenseSection available={false} title="字段级血缘（MOD-07）" />
      <div style={{ height: 16 }} />
      <SuspenseSection available={false} title="样本值（MOD-03）" />
      <div style={{ height: 16 }} />

      <Collapse
        items={[
          {
            key: 'raw',
            label: <Typography.Text type="secondary">原始响应（调试用）</Typography.Text>,
            children: <JsonView value={data} />,
          },
        ]}
      />
      <Space style={{ marginTop: 16 }}>
        <Typography.Text type="secondary">
          字段通过所属表进入最可靠；直接深链时系统会按列名推断父表。
        </Typography.Text>
      </Space>
    </div>
  );
}
