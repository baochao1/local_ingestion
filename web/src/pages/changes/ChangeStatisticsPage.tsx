import { Card, Col, Progress, Row, Statistic, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { getChangeStatistics } from '@/api/changes';
import { qk } from '@/api/keys';
import ErrorState from '@/components/ErrorState';
import FilterBar from '@/components/FilterBar';
import type { FilterValues } from '@/components/FilterBar';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import SeverityTag from '@/components/SeverityTag';
import { useDatasourceNames } from '@/hooks/useDatasourceName';
import { COLORS } from '@/theme';

/** 变更统计（FE-01 §5.3）。 */
export default function ChangeStatisticsPage() {
  const [filters, setFilters] = useState<FilterValues>({});
  const { name: dsName } = useDatasourceNames();

  const params = useMemo(() => {
    const range = filters.range as string[] | undefined;
    return {
      since: range?.[0],
      until: range?.[1],
    };
  }, [filters]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.changes.statistics(params),
    queryFn: () => getChangeStatistics(params),
  });

  const total = data?.total ?? 0;
  const bySeverity = data?.by_severity ?? {};
  const byDatasource = data?.by_datasource ?? {};

  return (
    <div>
      <PageHeader title="变更统计" subtitle="按严重度与数据源分布（MOD-06）" />
      <FilterBar
        fields={[{ name: 'range', label: '时间范围', type: 'dateRange' }]}
        values={filters}
        onChange={setFilters}
      />
      {isLoading ? (
        <LoadingSkeleton rows={6} />
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <Row gutter={16}>
          <Col span={6}>
            <Card size="small">
              <Statistic title="变更总数" value={total} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="破坏性"
                value={bySeverity.breaking ?? 0}
                valueStyle={{ color: COLORS.error }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="结构性"
                value={bySeverity.structural ?? 0}
                valueStyle={{ color: COLORS.warning }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic title="描述性" value={bySeverity.descriptive ?? 0} />
            </Card>
          </Col>

          <Col span={12} style={{ marginTop: 16 }}>
            <Card size="small" title="严重度占比">
              {(['breaking', 'structural', 'descriptive'] as const).map((k) => {
                const v = bySeverity[k] ?? 0;
                const pct = total ? Math.round((v / total) * 100) : 0;
                return (
                  <div key={k} style={{ marginBottom: 8 }}>
                    <Space2>
                      <SeverityTag severity={k} />
                      <span>
                        {v} ({pct}%)
                      </span>
                    </Space2>
                    <Progress
                      percent={pct}
                      showInfo={false}
                      strokeColor={
                        k === 'breaking'
                          ? COLORS.error
                          : k === 'structural'
                            ? COLORS.warning
                            : '#8c8c8c'
                      }
                    />
                  </div>
                );
              })}
            </Card>
          </Col>
          <Col span={12} style={{ marginTop: 16 }}>
            <Card size="small" title="按数据源">
              {Object.keys(byDatasource).length === 0 ? (
                <Typography.Text type="secondary">暂无数据</Typography.Text>
              ) : (
                Object.entries(byDatasource).map(([ds, v]) => {
                  // unknown 不是「健康/成功」，不能再用满格绿色（S1#10）
                  const unknown = ds === 'unknown';
                  return (
                    <div key={ds} style={{ marginBottom: 4 }}>
                      <Typography.Text>
                        {unknown ? '未标注数据源' : `数据源 ${dsName(ds)}`}
                      </Typography.Text>
                      <Progress
                        percent={total ? Math.round((Number(v) / total) * 100) : 0}
                        strokeColor={unknown ? '#8c8c8c' : COLORS.primary}
                      />
                    </div>
                  );
                })
              )}
            </Card>
          </Col>
        </Row>
      )}
    </div>
  );
}

/** 简易行内布局，避免额外引入组件。 */
function Space2({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>{children}</div>
  );
}
