import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Card, Input, Space, Tag, Tree, Typography } from 'antd';
import type { TreeDataNode } from 'antd';
import { Link } from 'react-router-dom';
import {
  browseColumns,
  browseDatabases,
  browseSchemas,
  browseTables,
} from '@/api/catalog';
import type { CatalogNode } from '@/api/catalog';
import { listDatasources } from '@/api/datasources';
import type { ColumnsType } from '@/components/DataTable';
import DataTable from '@/components/DataTable';
import EmptyState from '@/components/EmptyState';
import GradeTag from '@/components/GradeTag';
import PageHeader from '@/components/PageHeader';
import { columnDetailLink, tableDetailLink } from '@/utils/assets';

/**
 * 资产层级浏览（MOD-09 §182-183）。
 *
 * 左侧「数据源 → 库 → schema」树，右侧显示所选节点的**下一层**内容：
 * 选中数据源列库、选中库列 schema、选中 schema 列表、选中表列字段。
 *
 * 这是与「资产检索」互补的另一半：检索要求用户先知道名字，
 * 浏览让用户发现自己有什么数据——此前这一半完全缺失，
 * 资产目录只剩一条搜索框。
 */

type NodeKind = 'datasource' | 'database' | 'schema' | 'table';

interface Selection {
  kind: NodeKind;
  id: number;
  name: string;
}

const PREFIX: Record<NodeKind, string> = {
  datasource: 'ds',
  database: 'db',
  schema: 'sch',
  table: 'tbl',
};

const nodeKey = (kind: NodeKind, id: number) => `${PREFIX[kind]}-${id}`;

function parseKey(key: string): { kind: NodeKind; id: number } | null {
  const sep = key.lastIndexOf('-');
  if (sep < 0) return null;
  const prefix = key.slice(0, sep);
  const id = Number(key.slice(sep + 1));
  if (!Number.isFinite(id)) return null;
  const kind = (Object.keys(PREFIX) as NodeKind[]).find((k) => PREFIX[k] === prefix);
  return kind ? { kind, id } : null;
}

/** 把懒加载到的子节点挂到树上对应位置。 */
function attachChildren(
  nodes: TreeDataNode[],
  key: string,
  children: TreeDataNode[],
): TreeDataNode[] {
  return nodes.map((n) => {
    if (n.key === key) return { ...n, children };
    if (n.children) return { ...n, children: attachChildren(n.children, key, children) };
    return n;
  });
}

async function loadChildren(kind: NodeKind, id: number): Promise<TreeDataNode[]> {
  if (kind === 'datasource') {
    const page = await browseDatabases({ datasourceId: id, limit: 200 });
    return (page.items ?? []).map((n) => ({
      key: nodeKey('database', n.id),
      title: n.name,
      isLeaf: false,
    }));
  }
  if (kind === 'database') {
    const page = await browseSchemas({ databaseId: id, limit: 200 });
    return (page.items ?? []).map((n) => ({
      key: nodeKey('schema', n.id),
      title: n.name,
      // 表不进树：一个 schema 下可能有上千张表，放右侧列表分页展示
      isLeaf: true,
    }));
  }
  return [];
}

export default function CatalogBrowsePage() {
  const [treeData, setTreeData] = useState<TreeDataNode[]>([]);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [keyword, setKeyword] = useState('');

  useEffect(() => {
    listDatasources({})
      .then((page) => {
        setTreeData(
          (page.items ?? []).map((ds) => ({
            key: nodeKey('datasource', ds.id),
            title: ds.name ?? ds.code ?? `#${ds.id}`,
            isLeaf: false,
          })),
        );
      })
      .catch(() => setTreeData([]));
  }, []);

  const loadData = useCallback(async (node: TreeDataNode) => {
    const parsed = parseKey(String(node.key));
    if (!parsed) return;
    const children = await loadChildren(parsed.kind, parsed.id);
    setTreeData((prev) => attachChildren(prev, String(node.key), children));
  }, []);

  const onSelect = useCallback((_keys: React.Key[], info: { node: TreeDataNode }) => {
    const parsed = parseKey(String(info.node.key));
    if (!parsed) return;
    setSelected({ kind: parsed.kind, id: parsed.id, name: String(info.node.title ?? '') });
    setKeyword('');
  }, []);

  /** 表名 → 继续下钻看字段；详情页由操作列单独提供。 */
  const drillDown = (kind: NodeKind, node: CatalogNode) =>
    setSelected({ kind, id: node.id, name: node.name });

  const databaseColumns: ColumnsType<CatalogNode> = [
    {
      title: '库',
      dataIndex: 'name',
      render: (name: string, r) => (
        <Button type="link" size="small" style={{ padding: 0 }} onClick={() => drillDown('database', r)}>
          {name}
        </Button>
      ),
    },
    { title: '负责人', dataIndex: 'owner', width: 140, render: (v) => v ?? '—' },
    { title: '描述', dataIndex: 'description', render: (v) => v ?? '—' },
  ];

  const schemaColumns: ColumnsType<CatalogNode> = [
    {
      title: 'Schema',
      dataIndex: 'name',
      render: (name: string, r) => (
        <Button type="link" size="small" style={{ padding: 0 }} onClick={() => drillDown('schema', r)}>
          {name}
        </Button>
      ),
    },
    { title: '负责人', dataIndex: 'owner', width: 140, render: (v) => v ?? '—' },
    { title: '描述', dataIndex: 'description', render: (v) => v ?? '—' },
  ];

  const tableColumns: ColumnsType<CatalogNode> = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (name: string, r) => (
        <Button type="link" size="small" style={{ padding: 0 }} onClick={() => drillDown('table', r)}>
          {name}
        </Button>
      ),
    },
    {
      // 视图与表分开显示——后端把二者都存进 catalog_table，
      // 靠 table_type 区分；不显示这一列用户就分不清哪张是视图。
      title: '类型',
      dataIndex: 'tableType',
      width: 140,
      render: (v?: string | null) =>
        v === 'VIEW' ? <Tag color="purple">视图</Tag> : <Tag>表</Tag>,
    },
    {
      title: '字段数',
      dataIndex: 'columnCount',
      width: 90,
      render: (v?: number | null) => v ?? '—',
    },
    {
      title: '分级',
      dataIndex: 'gradeLevel',
      width: 110,
      render: (v?: number | null) => (v ? <GradeTag level={v} /> : <Tag>未分级</Tag>),
    },
    { title: '负责人', dataIndex: 'owner', width: 120, render: (v) => v ?? '—' },
    {
      title: '操作',
      width: 100,
      render: (_v, r) => (
        <Link to={tableDetailLink(r.fqn)}>
          <Button type="link" size="small">
            详情
          </Button>
        </Link>
      ),
    },
  ];

  const columnColumns: ColumnsType<CatalogNode> = [
    {
      title: '字段名',
      dataIndex: 'name',
      render: (name: string, r) => (
        <Link to={columnDetailLink(r.fqn, r.parentFqn ?? undefined)}>
          <span className="mono">{name}</span>
        </Link>
      ),
    },
    {
      title: '类型',
      dataIndex: 'dataType',
      width: 180,
      render: (v?: string | null) => <span className="mono">{v ?? '—'}</span>,
    },
    {
      title: '可空',
      dataIndex: 'nullable',
      width: 80,
      // 「可空」用文字而非仅靠颜色，避免色觉障碍用户无法区分
      render: (v?: boolean | null) => (v === false ? '否' : '是'),
    },
    {
      title: '分级',
      dataIndex: 'gradeLevel',
      width: 110,
      render: (v?: number | null) => (v ? <GradeTag level={v} /> : <Tag>未分级</Tag>),
    },
    { title: '描述', dataIndex: 'description', render: (v) => v ?? '—' },
  ];

  const view = useMemo(() => {
    if (!selected) return null;
    const { kind, id } = selected;
    switch (kind) {
      case 'datasource':
        return {
          heading: `${selected.name} · 库`,
          columns: databaseColumns,
          fetcher: (cursor: string | null) =>
            browseDatabases({ datasourceId: id, keyword: keyword || undefined, cursor }),
        };
      case 'database':
        return {
          heading: `${selected.name} · Schema`,
          columns: schemaColumns,
          fetcher: (cursor: string | null) =>
            browseSchemas({ databaseId: id, keyword: keyword || undefined, cursor }),
        };
      case 'schema':
        return {
          heading: `${selected.name} · 表 / 视图`,
          columns: tableColumns,
          fetcher: (cursor: string | null) =>
            browseTables({ schemaId: id, keyword: keyword || undefined, cursor }),
        };
      case 'table':
        return {
          heading: '字段',
          columns: columnColumns,
          fetcher: async (cursor: string | null) => {
            const page = await browseColumns({ tableId: id, keyword: keyword || undefined, cursor });
            // 后端按 (fqn, id) 稳定分页；单表字段有限（一次取全），
            // 展示顺序按表内位置排，符合「看表结构」的心智。
            return {
              ...page,
              items: [...(page.items ?? [])].sort(
                (a, b) => (a.ordinalPosition ?? 0) - (b.ordinalPosition ?? 0),
              ),
            };
          },
        };
    }
    // 列定义随 selected 变化，交给 useMemo 依赖
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, keyword]);

  return (
    <div>
      <PageHeader
        title="资产浏览"
        subtitle="按 数据源 → 库 → Schema → 表 → 字段 逐层下钻"
        extra={
          <Link to="/app/catalog">
            <Button>切换到资产检索</Button>
          </Link>
        }
      />
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        <Card size="small" title="资产树" style={{ width: 300, flex: '0 0 300px' }}>
          {treeData.length === 0 ? (
            <EmptyState description="暂无数据源" />
          ) : (
            <Tree
              treeData={treeData}
              loadData={loadData}
              onSelect={onSelect}
              showLine
              blockNode
            />
          )}
        </Card>
        <Card
          size="small"
          title={view?.heading ?? '请在左侧选择'}
          style={{ flex: 1, minWidth: 0 }}
          extra={
            view ? (
              <Space>
                <Input.Search
                  allowClear
                  placeholder="按名称过滤"
                  style={{ width: 220 }}
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                />
                {selected?.kind === 'table' && (
                  <Button size="small" onClick={() => setSelected(null)}>
                    收起
                  </Button>
                )}
              </Space>
            ) : null
          }
        >
          {!selected || !view ? (
            <Typography.Text type="secondary">
              从左侧选择一个数据源，逐层展开到库、Schema 与表。
            </Typography.Text>
          ) : (
            <DataTable<CatalogNode>
              columns={view.columns}
              queryKey={['catalog-browse', selected.kind, selected.id, keyword]}
              filterKey={`${selected.kind}-${selected.id}-${keyword}`}
              rowKey="id"
              scrollX={900}
              empty={<EmptyState description="该层级下暂无内容" />}
              fetcher={view.fetcher}
            />
          )}
        </Card>
      </div>
    </div>
  );
}
