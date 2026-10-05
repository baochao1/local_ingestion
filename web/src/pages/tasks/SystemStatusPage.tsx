import { Card, Col, Row, Space, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { getSystemHealth, getSystemMetrics } from '@/api/tasks';
import { qk } from '@/api/keys';
import ErrorState from '@/components/ErrorState';
import JsonView from '@/components/JsonView';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import { COLORS } from '@/theme';

const STATUS_COLOR: Record<string, string> = {
  ok: COLORS.success,
  healthy: COLORS.success,
  up: COLORS.success,
  degraded: COLORS.warning,
  warn: COLORS.warning,
  down: COLORS.error,
  error: COLORS.error,
  fail: COLORS.error,
};

/** 平台健康与指标（FE-01 §11.3 / §11.4）。 */
export default function SystemStatusPage() {
  const health = useQuery({
    queryKey: qk.system.health(),
    queryFn: () => getSystemHealth(),
    refetchInterval: 30_000,
  });
  const metrics = useQuery({
    queryKey: qk.system.metrics(),
    queryFn: () => getSystemMetrics(),
    refetchInterval: 30_000,
  });

  const components = health.data?.components ?? [];

  return (
    <div>
      <PageHeader title="平台健康与指标" subtitle="MOD-10：健康检查与运行时指标" />

      <Row gutter={16}>
        <Col span={12}>
          <Card
            size="small"
            title="系统健康"
            extra={<Tag color={STATUS_COLOR[health.data?.status ?? ''] ?? 'default'}>{health.data?.status ?? '-'}</Tag>}
          >
            {health.isLoading ? (
              <LoadingSkeleton rows={3} />
            ) : health.isError ? (
              <ErrorState error={health.error} onRetry={() => void health.refetch()} />
            ) : components.length === 0 ? (
              <Typography.Text type="secondary">无组件信息</Typography.Text>
            ) : (
              <Space direction="vertical" style={{ width: '100%' }}>
                {components.map((c, i) => (
                  <Space key={i} align="start">
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: '50%',
                        background: STATUS_COLOR[c.status ?? ''] ?? '#8c8c8c',
                        display: 'inline-block',
                        marginTop: 6,
                      }}
                    />
                    <span style={{ minWidth: 120 }}>{c.component ?? '-'}</span>
                    <Tag color={STATUS_COLOR[c.status ?? ''] ?? 'default'}>{c.status ?? '-'}</Tag>
                    <Typography.Text type="secondary">{c.message ?? ''}</Typography.Text>
                  </Space>
                ))}
              </Space>
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="运行时指标（原始）">
            {metrics.isLoading ? (
              <LoadingSkeleton rows={6} />
            ) : metrics.isError ? (
              <ErrorState error={metrics.error} onRetry={() => void metrics.refetch()} />
            ) : (
              <JsonView value={metrics.data ?? {}} />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
