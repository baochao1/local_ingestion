import { Card, Col, Progress, Row, Space, Statistic, Table, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getCatalogOverview } from '@/api/catalog';
import { getChangeStatistics } from '@/api/changes';
import { getLadder } from '@/api/classification';
import { qk } from '@/api/keys';
import { getSystemHealth } from '@/api/tasks';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';
import { COLORS } from '@/theme';

/**
 * 概览工作台（FE-01 §2）。
 *
 * 注意：`/api/v1/catalog/overview` 属于 `api/routers`，**未走 camelize**，
 * 因此字段是 snake_case（total_tables / grade_distribution / change_trend …）。
 * 这里同时兼容两种命名，避免后端后续调整导致页面失效。
 */
function pick(d: Record<string, any> | undefined, snake: string, camel: string) {
  if (!d) return undefined;
  return d[snake] ?? d[camel];
}

// 后端部分概览字段在某些情况下会返回对象（如 change_trend: {}）而非数组，
// 直接传给 antd <Table> 会抛 `rawData.some is not a function`。统一兜底成数组。
function asArray<T>(x: unknown): T[] {
  return Array.isArray(x) ? (x as T[]) : [];
}

/**
 * 分级键归一：后端历史上按 `grade_level` 原值出键（"1"/"2"，甚至越界的 "5"），
 * 前端按 "L1" 取值永远拿不到 → 首页分级分布恒为 0（ux-audit-full.md S1#5）。
 * 这里双向兼容：数字键补 L 前缀，越界/未知键归入「未分级」而不是丢弃。
 */
function normalizeGradeDist(raw: Record<string, number> | undefined): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(raw ?? {})) {
    const n = Number(v ?? 0);
    if (/^\d+$/.test(k)) {
      const lvl = Number(k);
      // 1–5 级全部保留：原先 >4 被误并入「未分级」，导致 L5 在概览页消失
      const key = lvl >= 1 && lvl <= 5 ? `L${lvl}` : UNGRADED_KEY;
      out[key] = (out[key] ?? 0) + n;
    } else {
      out[k] = (out[k] ?? 0) + n;
    }
  }
  return out;
}

const UNGRADED_KEY = 'ungraded';

export default function DashboardPage() {
  const overview = useQuery({
    queryKey: qk.catalog.overview(30),
    queryFn: () => getCatalogOverview(30),
  });
  const health = useQuery({
    queryKey: qk.system.health(),
    queryFn: () => getSystemHealth(),
    refetchInterval: 60_000,
  });
  const stats = useQuery({
    queryKey: qk.changes.statistics({}),
    queryFn: () => getChangeStatistics(),
  });

  const d = overview.data as Record<string, any> | undefined;
  const totalTables = Number(pick(d, 'total_tables', 'tables_count') ?? 0);
  const totalColumns = Number(pick(d, 'total_columns', 'columns_count') ?? 0);
  // 字段缺失时显示 `—`（未知）而不是 0（已知为零）——治理看板不能拿 0 冒充「没数据」
  const rawDatasources = pick(d, 'datasources_count', 'datasourcesCount');
  const totalDatasources = rawDatasources == null ? null : Number(rawDatasources);
  const sensitiveRatio = Number(pick(d, 'sensitive_ratio', 'sensitiveRatio') ?? 0);
  // 分级阶梯以后端 /classification/ladder 为单一事实来源：
  // 概览页曾硬编码「L1 公开/L2 内部/L3 敏感/L4 高度敏感」，与分级页的
  // 「L1 内部/L2 业务敏感/L3 个人信息/L4 高敏个人信息/L5 机密」冲突（对标 S0-2 / UX F-006）。
  const ladder = useQuery({
    queryKey: ['classification', 'ladder'],
    queryFn: getLadder,
    staleTime: 5 * 60_000,
  });
  const gradeRows: { key: string; label: string; gb?: string }[] = [
    ...(ladder.data?.levels ?? []).map((lv) => ({
      key: `L${lv.level}`,
      label: `L${lv.level} ${lv.label}`,
      gb: lv.gbLevel,
    })),
    { key: UNGRADED_KEY, label: '未分级' },
  ];

  const gradeDist = normalizeGradeDist(
    (pick(d, 'grade_distribution', 'gradeDistribution') ?? {}) as Record<string, number>,
  );
  const changeTrend = asArray<{ date: string; count: number }>(
    pick(d, 'change_trend', 'changeTrend'),
  );
  const topTables = asArray<{
    fqn: string;
    change_count?: number;
    changeCount?: number;
  }>(pick(d, 'top_changing_tables', 'topChangingTables'));

  const changeTotal = stats.data?.total ?? 0;
  const bySeverity = stats.data?.by_severity ?? {};
  // 分级分布的分母用分级桶自身之和（覆盖表 + 字段），比只取字段数更准确
  const gradeTotal = Object.values(gradeDist).reduce((a, b) => a + (Number(b) || 0), 0);

  if (overview.isLoading) return <LoadingSkeleton rows={8} />;
  if (overview.isError)
    return <ErrorState error={overview.error} onRetry={() => void overview.refetch()} />;

  return (
    <div>
      <PageHeader title="概览" subtitle="资产大盘 · 变更趋势 · 平台健康" />

      <Row gutter={16}>
        <Col span={4}>
          <Card size="small">
            <Link to="/app/datasources">
              <Statistic title="数据源" value={totalDatasources ?? '—'} />
            </Link>
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Link to="/app/catalog?type=table">
              <Statistic title="表" value={totalTables} />
            </Link>
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Link to="/app/catalog?type=column">
              <Statistic title="字段" value={totalColumns} />
            </Link>
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="敏感资产占比"
              value={Math.round(sensitiveRatio * 100)}
              suffix="%"
              valueStyle={{ color: COLORS.sensitive }}
            />
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Link to="/app/changes">
              <Statistic title="变更总数" value={changeTotal} />
            </Link>
          </Card>
        </Col>
        <Col span={4}>
          <Card size="small">
            <Statistic
              title="平台健康"
              value={health.data?.status ?? '-'}
              valueStyle={{
                color:
                  health.data?.status === 'ok' || health.data?.status === 'healthy'
                    ? COLORS.success
                    : COLORS.warning,
              }}
            />
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card size="small" title="分级分布">
            {Object.keys(gradeDist).length === 0 ? (
              <EmptyState description="暂无分级数据" />
            ) : (
              gradeRows.map(({ key: g, label, gb }) => {
                const v = gradeDist[g] ?? 0;
                const pct = gradeTotal ? Math.round((v / gradeTotal) * 100) : 0;
                return (
                  <div key={g} style={{ marginBottom: 8 }}>
                    <Space>
                      <Tag>{label}</Tag>
                      {gb ? (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          国标：{gb}
                        </Typography.Text>
                      ) : null}
                      <span>
                        {v}（{pct}%）
                      </span>
                    </Space>
                    <Progress
                      percent={pct}
                      showInfo={false}
                      strokeColor={
                        g === 'L4'
                          ? COLORS.error
                          : g === 'L3'
                            ? COLORS.warning
                            : g === 'L2'
                              ? COLORS.primary
                              : '#8c8c8c'
                      }
                    />
                  </div>
                );
              })
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="变更严重度">
            {(['breaking', 'structural', 'descriptive'] as const).map((k) => {
              const v = bySeverity[k] ?? 0;
              return (
                <div key={k} style={{ marginBottom: 6 }}>
                  <Tag
                    color={
                      k === 'breaking'
                        ? COLORS.error
                        : k === 'structural'
                          ? COLORS.warning
                          : '#8c8c8c'
                    }
                  >
                    {k}
                  </Tag>
                  <span>{v}</span>
                </div>
              );
            })}
            <Typography.Text type="secondary">
              {stats.isError ? '变更统计不可用' : null}
            </Typography.Text>
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={12}>
          <Card size="small" title="变更趋势（近 30 天）">
            {changeTrend.length === 0 ? (
              <EmptyState description="暂无趋势数据" />
            ) : (
              <Table
                size="small"
                pagination={false}
                scroll={{ y: 240 }}
                rowKey={(r) => String(r.date)}
                dataSource={changeTrend}
                columns={[
                  { title: '日期', dataIndex: 'date' },
                  { title: '变更数', dataIndex: 'count' },
                ]}
              />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title="变更最频繁表 Top10">
            {topTables.length === 0 ? (
              <EmptyState description="暂无数据" />
            ) : (
              <Table
                size="small"
                pagination={false}
                scroll={{ y: 240 }}
                rowKey={(r) => r.fqn}
                dataSource={topTables}
                columns={[
                  {
                    title: 'FQN',
                    dataIndex: 'fqn',
                    render: (v: string) => (
                      <Link to={`/app/catalog?q=${encodeURIComponent(v)}`}>
                        <span className="mono">{v}</span>
                      </Link>
                    ),
                  },
                  {
                    title: '变更数',
                    width: 90,
                    render: (_v, r) => r.change_count ?? r.changeCount ?? '-',
                  },
                ]}
              />
            )}
          </Card>
        </Col>
      </Row>

      <Card size="small" title="平台健康" style={{ marginTop: 16 }}>
        {health.isLoading ? (
          <LoadingSkeleton rows={2} />
        ) : health.isError ? (
          <Typography.Text type="secondary">健康信息暂不可用</Typography.Text>
        ) : (
          <Space wrap>
            {(health.data?.components ?? []).map((c, i) => (
              <Tag
                key={i}
                color={
                  c.status === 'ok' || c.status === 'healthy' || c.status === 'up'
                    ? COLORS.success
                    : c.status === 'degraded' || c.status === 'warn'
                      ? COLORS.warning
                      : COLORS.error
                }
              >
                {c.component}: {c.status}
              </Tag>
            ))}
          </Space>
        )}
      </Card>
    </div>
  );
}
