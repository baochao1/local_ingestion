import { Button, Space, Tag, Tooltip, Typography } from 'antd';
import { BarsOutlined, TableOutlined } from '@ant-design/icons';
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { searchAssets } from '@/api/catalog';
import { qk } from '@/api/keys';
import type { ColumnsType } from '@/components/DataTable';
import DataTable from '@/components/DataTable';
import EmptyState from '@/components/EmptyState';
import FilterBar from '@/components/FilterBar';
import type { FilterValues } from '@/components/FilterBar';
import GradeTag from '@/components/GradeTag';
import PageHeader from '@/components/PageHeader';
import type { CatalogAsset } from '@/types';
import {
  assetDetailLink,
  entityTypeText,
  guessParentFqn,
  tableDetailLink,
} from '@/utils/assets';

const PAGE_SIZE = 50;
/** 后端对模糊检索的结果上限（MOD-09 §4.1）。 */
const SEARCH_MAX = 1000;

/**
 * 资产检索 / 浏览（FE-01 §4.1）。
 *
 * 说明：`/api/v1/search` 只支持 limit/offset（无 keyset 游标），故此处按
 * offset 翻页并遵守 1000 条上限，超限提示「请收窄条件」（FE-00 §6.2）。
 */
export default function CatalogSearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTerm = searchParams.get('q') ?? '';
  const initialType = searchParams.get('type') ?? '';
  // 支持从概览指标卡深链进来：?q= 关键字、?type=table|column 类型预选
  const [filters, setFilters] = useState<FilterValues>({
    term: initialTerm,
    ...(initialType ? { type: initialType } : {}),
  });

  const params = useMemo(
    () => ({
      term: (filters.term as string) || undefined,
      type: filters.type as string | undefined,
      datasourceId: filters.datasourceId as number | undefined,
      owner: filters.owner as string | undefined,
      gradeMin: filters.gradeMin as number | undefined,
      sensitiveOnly: filters.sensitiveOnly as boolean | undefined,
    }),
    [filters],
  );
  const filterKey = JSON.stringify(params);

  const columns: ColumnsType<CatalogAsset> = [
    {
      title: '名称',
      dataIndex: 'name',
      width: 220,
      render: (_name: string, r) => {
        const isColumn = (r.entityType ?? r.type) === 'column';
        const label = r.name ?? r.fqn ?? '-';
        return (
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {/* 表 / 字段同表混排时给一个类型图标，避免看不出层级 */}
            {isColumn ? (
              <BarsOutlined style={{ color: '#8c8c8c' }} />
            ) : (
              <TableOutlined style={{ color: '#2f54eb' }} />
            )}
            {r.fqn ? (
              <Link to={assetDetailLink(r)}>{label}</Link>
            ) : (
              <span>{label}</span>
            )}
          </div>
        );
      },
    },
    {
      title: '类型',
      dataIndex: 'entityType',
      width: 90,
      // 后端返回 entityType（不是 type），此前取错字段导致整列为空
      render: (_v, r) => (
        <Tag color={(r.entityType ?? r.type) === 'table' ? 'blue' : 'default'}>
          {entityTypeText(r.entityType ?? r.type)}
        </Tag>
      ),
    },
    {
      title: '所属表',
      dataIndex: 'parentFqn',
      width: 260,
      render: (v?: string | null, r?) => {
        const kind = r?.entityType ?? r?.type;
        const parent = v ?? (kind === 'column' ? guessParentFqn(r?.fqn) : undefined);
        return parent ? (
          <Tooltip title={parent}>
            <Link to={tableDetailLink(parent)} className="mono">
              {parent}
            </Link>
          </Tooltip>
        ) : (
          '-'
        );
      },
    },
    {
      title: 'FQN',
      dataIndex: 'fqn',
      width: 300,
      render: (v?: string) => <span className="mono">{v ?? '-'}</span>,
    },
    {
      title: '分级',
      dataIndex: 'gradeLevel',
      width: 110,
      render: (v?: number) => <GradeTag level={v ?? 0} />,
    },
    { title: '负责人', dataIndex: 'owner', width: 120, render: (v) => v ?? '-' },
    {
      title: '标签',
      dataIndex: 'tags',
      render: (tags?: string[]) =>
        (tags ?? []).length ? (
          <Space size={4}>
            {tags!.map((t) => (
              <Tag key={t}>{t}</Tag>
            ))}
          </Space>
        ) : (
          '-'
        ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="资产检索"
        subtitle="检索优先：支持关键字、类型、数据源、分级、敏感过滤"
        extra={
          <Space>
            <Button
              onClick={() => {
                setFilters({});
                setSearchParams({});
              }}
            >
              清空条件
            </Button>
            <Link to="/app/catalog/browse">
              <Button type="primary">按层级浏览</Button>
            </Link>
          </Space>
        }
      />
      <FilterBar
        fields={[
          { name: 'term', label: '关键字', type: 'text', placeholder: '表名 / 字段名' },
          {
            name: 'type',
            label: '类型',
            type: 'select',
            options: [
              { label: '表', value: 'table' },
              { label: '字段', value: 'column' },
            ],
          },
          { name: 'datasourceId', label: '数据源', type: 'number' },
          { name: 'owner', label: '负责人', type: 'text' },
          {
            name: 'gradeMin',
            label: '最低分级',
            type: 'select',
            options: [
              { label: 'L1', value: 1 },
              { label: 'L2', value: 2 },
              { label: 'L3', value: 3 },
              { label: 'L4', value: 4 },
            ],
          },
          {
            name: 'sensitiveOnly',
            label: '仅敏感',
            type: 'select',
            options: [{ label: '是', value: true }],
          },
        ]}
        values={filters}
        onChange={(v) => {
          setFilters(v);
          if (v.term) setSearchParams({ q: String(v.term) });
        }}
      />
      <DataTable<CatalogAsset>
        columns={columns}
        queryKey={qk.catalog.search(params)}
        filterKey={filterKey}
        // 检索响应不含 id；且同一 fqn 可能同时命中 table 与 column，
        // 只用 fqn 会撞 React key。这里用 entityType+fqn+parentFqn 复合键。
        rowKey={(r) =>
          `${String(r.entityType ?? '')}:${String(r.fqn ?? '')}:${String(r.parentFqn ?? '')}`
        }
        scrollX={1500}
        empty={<EmptyState description="无匹配资产，请调整筛选条件" />}
        fetcher={async (cursor) => {
          const offset = Number(cursor ?? 0);
          const res = await searchAssets({ ...params, limit: PAGE_SIZE, offset });
          const items = res.items ?? res.results ?? [];
          const nextOffset = offset + items.length;
          const reachedMax = nextOffset >= SEARCH_MAX;
          return {
            items,
            // 透传总数：让用户知道自己看到的是一部分还是全部（FE-00 §6.2）
            total: res.total ?? null,
            next_cursor:
              items.length === PAGE_SIZE && !reachedMax ? String(nextOffset) : null,
          };
        }}
      />
      <Typography.Text type="secondary">
        模糊检索后端上限 {SEARCH_MAX} 条，超限时请收窄条件（MOD-09 §4.1）
      </Typography.Text>
    </div>
  );
}
