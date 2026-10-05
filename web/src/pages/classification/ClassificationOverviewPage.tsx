import { Card, Col, Progress, Row, Space, Statistic, Table, Tag, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { getCoverage, getLadder } from '@/api/classification';
import type { DatasourceCoverage } from '@/api/classification';
import ErrorState from '@/components/ErrorState';
import GradeTag from '@/components/GradeTag';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';

/**
 * 分类分级概览（MOD-05 / FR-9.11）。
 *
 * 这一页存在的理由：分级任务此前**能触发但结果无处可看**——引擎跑完把
 * `grade_level` 写进 catalog 表，然后没有任何界面能读它。用户点完「立即分级」
 * 拿到一个任务号，就断了。
 */
export default function ClassificationOverviewPage() {
  const coverage = useQuery({ queryKey: ['classification', 'coverage'], queryFn: () => getCoverage() });
  const ladder = useQuery({ queryKey: ['classification', 'ladder'], queryFn: getLadder });

  if (coverage.isLoading || ladder.isLoading) return <LoadingSkeleton rows={6} />;
  if (coverage.isError) {
    return <ErrorState error={coverage.error} onRetry={() => void coverage.refetch()} />;
  }
  const cov = coverage.data!;
  const levels = ladder.data?.levels ?? [];
  const dist = cov.gradeDistribution ?? {};
  const ungraded = dist.ungraded ?? 0;

  /** 每级的字段数与占比（分母用已分级字段，未分级单列一行）。 */
  const rows = [
    ...levels.map((lv) => ({
      key: String(lv.level),
      level: lv.level,
      label: lv.label,
      description: lv.description,
      count: dist[String(lv.level)] ?? 0,
    })),
    ...(ungraded > 0
      ? [
          {
            key: 'ungraded',
            level: 0,
            label: '未分级',
            description: '尚未跑过识别规则，不计入任何级别',
            count: ungraded,
          },
        ]
      : []),
  ];
  const total = cov.totalColumns || 1;

  const dsColumns = [
    {
      title: '数据源',
      dataIndex: 'name',
      render: (name: string | null, r: DatasourceCoverage) => name ?? `#${r.datasourceId}`,
    },
    {
      title: '字段覆盖率',
      dataIndex: 'coverageRatio',
      width: 220,
      render: (ratio: number, r: DatasourceCoverage) => (
        <Space>
          <Progress percent={Math.round(ratio * 100)} size="small" style={{ width: 120 }} />
          <Typography.Text type="secondary">
            {r.gradedColumns} / {r.totalColumns}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '敏感字段',
      dataIndex: 'sensitiveColumns',
      width: 110,
      render: (n: number) => (n > 0 ? <Tag color="orange">{n}</Tag> : <Tag>{n}</Tag>),
    },
    {
      title: '表',
      dataIndex: 'totalTables',
      width: 140,
      render: (_v: number, r: DatasourceCoverage) => `${r.gradedTables} / ${r.totalTables}`,
    },
    {
      title: '操作',
      width: 120,
      render: (_v: unknown, r: DatasourceCoverage) => (
        <Link to={`/app/classification/sensitive-assets?datasourceId=${r.datasourceId}`}>
          看敏感资产
        </Link>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="分类分级"
        subtitle={`分级标准、识别规则与结果（敏感阈值：L${cov.sensitiveThreshold} 及以上）`}
        extra={
          // 用 <Link> 直接渲染 <a>；不能再套 Typography.Link，否则 <a> 嵌套 <a>
          <Space size="middle">
            <Link to="/app/classification/sensitive-assets">敏感资产清单</Link>
            <Link to="/app/classification/tags">分级标准</Link>
            <Link to="/app/classification/rules">识别规则</Link>
          </Space>
        }
      />

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="字段总数" value={cov.totalColumns} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="已分级"
              value={cov.gradedColumns}
              suffix={`/ ${cov.totalColumns}`}
            />
            <Typography.Text type="secondary">
              覆盖率 {(cov.coverageRatio * 100).toFixed(1)}%
            </Typography.Text>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title={`敏感字段（L${cov.sensitiveThreshold}+）`}
              value={cov.sensitiveColumns}
              valueStyle={{ color: cov.sensitiveColumns > 0 ? '#faad14' : undefined }}
            />
            <Typography.Text type="secondary">
              占已分级 {(cov.sensitiveRatio * 100).toFixed(1)}%
            </Typography.Text>
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="表" value={cov.gradedTables} suffix={`/ ${cov.totalTables}`} />
          </Card>
        </Col>
      </Row>

      <Card size="small" title="分级分布" style={{ marginBottom: 16 }}>
        {cov.gradedColumns === 0 ? (
          <Typography.Text type="secondary">
            还没有任何分级结果。在「数据源」页对一个数据源点「立即分级」即可。
          </Typography.Text>
        ) : (
          <Table
            size="small"
            rowKey="key"
            pagination={false}
            dataSource={rows}
            columns={[
              {
                title: '级别',
                dataIndex: 'level',
                width: 160,
                render: (level: number) =>
                  level === 0 ? <Tag>未分级</Tag> : <GradeTag level={level} />,
              },
              { title: '说明', dataIndex: 'description' },
              {
                title: '字段数',
                dataIndex: 'count',
                width: 100,
                render: (n: number) => n.toLocaleString(),
              },
              {
                title: '占比',
                dataIndex: 'count',
                width: 240,
                render: (n: number) => (
                  <Progress
                    percent={Math.round((n / total) * 1000) / 10}
                    size="small"
                    // 未分级用灰条，避免与级别色混淆
                    strokeColor={n === ungraded && n > 0 ? '#d9d9d9' : undefined}
                  />
                ),
              },
            ]}
          />
        )}
      </Card>

      <Card size="small" title="按数据源">
        <Table
          size="small"
          rowKey="datasourceId"
          pagination={false}
          dataSource={cov.byDatasource}
          columns={dsColumns as never}
          locale={{ emptyText: '暂无数据源' }}
        />
      </Card>
    </div>
  );
}
