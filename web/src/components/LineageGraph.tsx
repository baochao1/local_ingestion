import { Background, Controls, MarkerType, MiniMap, ReactFlow } from '@xyflow/react';
import type { Edge, Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMemo } from 'react';
import { COLORS } from '@/theme';
import EmptyState from '@/components/EmptyState';

export interface LineageGraphProps {
  nodes: Node[];
  edges: Edge[];
  /** 布局方向：LR 横向（默认）/ TB 纵向。 */
  direction?: 'LR' | 'TB';
  height?: number;
  onNodeClick?: (node: Node) => void;
}

/** 无坐标时按有向图分层自动布局（上游在左/上）。 */
function layoutNodes(nodes: Node[], edges: Edge[], direction: 'LR' | 'TB'): Node[] {
  const incoming = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  edges.forEach((e) => {
    outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e.target]);
    incoming.set(e.target, (incoming.get(e.target) ?? 0) + 1);
  });

  const depth = new Map<string, number>();
  const queue: string[] = [];
  nodes.forEach((n) => {
    if (!incoming.get(n.id)) {
      depth.set(n.id, 0);
      queue.push(n.id);
    }
  });
  while (queue.length > 0) {
    const current = queue.shift() as string;
    (outgoing.get(current) ?? []).forEach((target) => {
      const next = (depth.get(current) ?? 0) + 1;
      if ((depth.get(target) ?? -1) < next) {
        depth.set(target, next);
        queue.push(target);
      }
    });
  }

  const perLayer = new Map<number, number>();
  const isLR = direction === 'LR';
  return nodes.map((node) => {
    const layer = depth.get(node.id) ?? 0;
    const index = perLayer.get(layer) ?? 0;
    perLayer.set(layer, index + 1);
    return {
      ...node,
      position: isLR ? { x: layer * 260, y: index * 80 } : { x: index * 200, y: layer * 120 },
      sourcePosition: (isLR ? 'right' : 'bottom') as never,
      targetPosition: (isLR ? 'left' : 'top') as never,
    };
  });
}

/** 血缘有向图（@xyflow/react 封装，FE-00 §5.2）。 */
export function LineageGraph({
  nodes,
  edges,
  direction = 'LR',
  height = 480,
  onNodeClick,
}: LineageGraphProps) {
  const layoutedNodes = useMemo(
    () => layoutNodes(nodes ?? [], edges ?? [], direction),
    [nodes, edges, direction],
  );

  const styledEdges = useMemo(
    () =>
      (edges ?? []).map((edge) => ({
        ...edge,
        type: edge.type ?? 'smoothstep',
        markerEnd: edge.markerEnd ?? { type: MarkerType.ArrowClosed },
        style: { stroke: COLORS.primary, ...(edge.style ?? {}) },
      })),
    [edges],
  );

  if (!nodes || nodes.length === 0) return <EmptyState description="暂无血缘数据" />;

  return (
    <div style={{ width: '100%', height, border: '1px solid #f0f0f0', borderRadius: 6 }}>
      <ReactFlow
        nodes={layoutedNodes}
        edges={styledEdges}
        fitView
        minZoom={0.2}
        onNodeClick={onNodeClick ? (_event, node) => onNodeClick(node) : undefined}
      >
        <Background gap={16} />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>
    </div>
  );
}

export default LineageGraph;
