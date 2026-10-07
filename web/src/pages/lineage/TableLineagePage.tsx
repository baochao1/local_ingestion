import { useMemo, useState } from 'react';
import { Alert, Card, Segmented, Space, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import type { Edge, Node } from '@xyflow/react';
import {
  getLineageDownstream,
  getLineageUpstream,
} from '@/api/misc';
import EmptyState from '@/components/EmptyState';
import ErrorState from '@/components/ErrorState';
import LineageGraph from '@/components/LineageGraph';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import PageHeader from '@/components/PageHeader';

/**
 * 表血缘（MOD-07 / FR-M4.3）。
 *
 * 这一页存在的理由：血缘**能算出来但无处可看** —— 采集器写进了
 * `lineage_*` 表，`LineageGraph` 组件也早已实现，唯独没有页面挂载它。
 *
 * 只画**直接**上下游（depth=1）。闭包只返回 (fqn, depth)，不含父子关系，
 * 按 depth 相邻层连边会凭空造出并不存在的边 —— 宁可少画，不可画错（E8）。
 */
export default function TableLineagePage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const fqn = searchParams.get('fqn') ?? '';
  const [direction, setDirection] = useState<'LR' | 'TB'>('LR');

  const upstream = useQuery({
    queryKey: ['lineage', 'upstream', fqn],
    queryFn: () => getLineageUpstream(fqn, 1),
    enabled: Boolean(fqn),
    retry: false,
  });
  const downstream = useQuery({
    queryKey: ['lineage', 'downstream', fqn],
    queryFn: () => getLineageDownstream(fqn, 1),
    enabled: Boolean(fqn),
    retry: false,
  });

  const { nodes, edges } = useMemo(() => {
    if (!fqn) return { nodes: [], edges: [] };

    const nodeList: Node[] = [
      {
        id: fqn,
        data: { label: fqn.split('.').slice(-2).join('.') },
        position: { x: 0, y: 0 },
        style: { borderColor: '#2f54eb', borderWidth: 2 },
      },
    ];
    const edgeList: Edge[] = [];
    const seen = new Set<string>([fqn]);

    const add = (fq: string, kind: 'up' | 'down') => {
      if (!fq || seen.has(fq)) return;
      seen.add(fq);
      nodeList.push({
        id: fq,
        data: { label: fq.split('.').slice(-2).join('.') },
        position: { x: 0, y: 0 },
        style: { borderColor: kind === 'up' ? '#52c41a' : '#fa8c16' },
      });
      edgeList.push(
        kind === 'up'
          ? { id: `${fq}->${fqn}`, source: fq, target: fqn }
          : { id: `${fqn}->${fq}`, source: fqn, target: fq },
      );
    };

    (upstream.data?.nodes ?? []).forEach((n) => add(n.fqn, 'up'));
    (downstream.data?.nodes ?? []).forEach((n) => add(n.fqn, 'down'));
    return { nodes: nodeList, edges: edgeList };
  }, [fqn, upstream.data, downstream.data]);

  if (!fqn) {
    return (
      <>
        <PageHeader title="表血缘" />
        <Card>
          <EmptyState description="请通过 ?fqn= 指定要查看的表" />
        </Card>
      </>
    );
  }

  if (upstream.isLoading || downstream.isLoading) return <LoadingSkeleton rows={6} />;
  if (upstream.isError) {
    return <ErrorState error={upstream.error} onRetry={() => void upstream.refetch()} />;
  }
  if (downstream.isError) {
    return (
      <ErrorState error={downstream.error} onRetry={() => void downstream.refetch()} />
    );
  }

  const upCount = upstream.data?.nodes?.length ?? 0;
  const downCount = downstream.data?.nodes?.length ?? 0;

  return (
    <>
      <PageHeader
        title="表血缘"
        subtitle={<span className="mono">{fqn}</span>}
        breadcrumb={[{ title: '资产目录', href: '/app/catalog' }, { title: '表血缘' }]}
        extra={
          <Space>
            <Segmented
              value={direction}
              onChange={(value) => setDirection(value as 'LR' | 'TB')}
              options={[
                { label: '横向', value: 'LR' },
                { label: '纵向', value: 'TB' },
              ]}
            />
          </Space>
        }
      />

      <Card>
        {upCount === 0 && downCount === 0 ? (
          <EmptyState
            description={
              <span>
                未采集到该表的血缘。血缘由扫描后的 <code>lineage.collect</code> 任务产出，
                未跑过采集时这里为空（并非出错）。
              </span>
            }
          />
        ) : (
          <>
            <Typography.Text type="secondary">
              上游 {upCount} · 下游 {downCount}（仅直接上下游；点击节点可切换到该表）
            </Typography.Text>
            <div style={{ marginTop: 8 }}>
              <LineageGraph
                nodes={nodes}
                edges={edges}
                direction={direction}
                height={420}
                onNodeClick={(node) => {
                  if (node.id !== fqn) {
                    navigate(`/app/lineage/tables?fqn=${encodeURIComponent(node.id)}`);
                  }
                }}
              />
            </div>
          </>
        )}
        <Alert
          style={{ marginTop: 12 }}
          type="info"
          showIcon
          message="多层影响面请使用「影响面」接口；本页只保证直接上下游的准确性。"
        />
      </Card>
    </>
  );
}
