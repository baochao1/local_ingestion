import { cleanParams, get } from './client';
import type { AssetDetailCard, CatalogAsset, CatalogOverview, CursorPage } from '@/types';

/** MOD-09 资产检索 / 详情 / 概览。响应 camelCase。 */

export interface SearchParams {
  term?: string;
  type?: string;
  datasourceId?: number | string;
  tags?: string[];
  owner?: string;
  sensitiveOnly?: boolean;
  /** 分级过滤（后端已实现，见 FE-00 §8）。 */
  gradeMin?: number;
  cursor?: string | null;
  limit?: number;
  /** 该端点仅支持 offset 翻页（无 keyset），上限 1000。 */
  offset?: number;
}

export function searchAssets(params: SearchParams) {
  return get<CursorPage<CatalogAsset> & { results?: CatalogAsset[] }>(
    '/search',
    cleanParams(params as Record<string, unknown>),
  );
}

/**
 * 资产详情。**只接受 FQN**（后端无按数字 id 的详情接口），
 * 调用方请用 `@/utils/assets` 的链接助手，勿再拼 id。
 */
export function getAsset(fqn: string): Promise<AssetDetailCard> {
  return get<AssetDetailCard>(`/assets/${encodeURIComponent(fqn)}`);
}

export function getCatalogOverview(trendDays = 30) {
  return get<CatalogOverview>('/catalog/overview', { trend_days: trendDays });
}

// ------------------------------------------------------------- 检索分面（FR-M3）

export interface FacetBucket {
  value: string;
  count: number;
  /** 仅 id 类维度（datasource/schema）回填的展示名。 */
  label?: string;
}

export interface SearchFacets {
  dimensions: string[];
  facets: Record<string, FacetBucket[]>;
}

/**
 * 分面计数（FR-M3.1）。与 `/search` 分开请求：两者成本模型不同，
 * 分面慢不该拖慢结果列表（NFR-M2）。
 */
export function getSearchFacets(params: SearchParams, topN = 20) {
  return get<SearchFacets>('/search/facets', {
    ...cleanParams(params as Record<string, unknown>),
    topN,
  });
}

// ------------------------------------------------------- 层级浏览（MOD-09 §182-183）
//
// MOD-09 规定的浏览接口此前从未实现，HTTP 层只有 /search（限 1000 条模糊匹配），
// 资产目录因此退化成「一条搜索框」——用户必须先知道表名才能找到表。
// 这四个接口让「库 → schema → 表 → 字段」可以逐层下钻。

/** 层级浏览节点。四层资产共用，按 `entityType` 区分。 */
export interface CatalogNode {
  id: number;
  name: string;
  fqn: string;
  entityType: 'database' | 'schema' | 'table' | 'column';
  datasourceId: number;
  parentId?: number | null;
  parentFqn?: string | null;
  owner?: string | null;
  description?: string | null;
  gradeLevel?: number | null;
  gradeCode?: string | null;
  /** table 专有：TABLE | VIEW | MATERIALIZED_VIEW | EXTERNAL */
  tableType?: string | null;
  columnCount?: number | null;
  /** column 专有 */
  dataType?: string | null;
  nullable?: boolean | null;
  ordinalPosition?: number | null;
  updatedAt?: string | null;
  tags?: string[];
}

export interface BrowseParams {
  datasourceId?: number | null;
  databaseId?: number | null;
  schemaId?: number | null;
  tableId?: number | null;
  tableType?: string;
  keyword?: string;
  cursor?: string | null;
  limit?: number;
}

function browse(path: string, params: BrowseParams) {
  return get<CursorPage<CatalogNode>>(path, cleanParams(params as Record<string, unknown>));
}

/** 库列表（层级浏览第一层）。 */
export function browseDatabases(params: BrowseParams = {}) {
  return browse('/catalog/databases', params);
}

/** Schema 列表（第二层）。 */
export function browseSchemas(params: BrowseParams = {}) {
  return browse('/catalog/schemas', params);
}

/** 表/视图列表（第三层）。`tableType` 大小写不敏感。 */
export function browseTables(params: BrowseParams = {}) {
  return browse('/catalog/tables', params);
}

/** 字段列表（第四层）。 */
export function browseColumns(params: BrowseParams = {}) {
  return browse('/catalog/columns', params);
}
