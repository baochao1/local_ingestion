/**
 * React Query queryKey 工厂。
 *
 * 约定：列表 key 末位放筛选参数对象；`<DataTable>` 会把 `filterKey` 并入 key，
 * 因此筛选变化即换 key，游标自动回到首页。
 */
export const qk = {
  datasources: {
    all: ['datasources'] as const,
    list: (p?: unknown) => ['datasources', 'list', p] as const,
    detail: (id: string | number) => ['datasources', 'detail', id] as const,
    health: (id: string | number) => ['datasources', 'health', id] as const,
  },
  catalog: {
    search: (p?: unknown) => ['catalog', 'search', p] as const,
    overview: (days?: number) => ['catalog', 'overview', days] as const,
    asset: (fqn: string) => ['catalog', 'asset', fqn] as const,
    table: (id: string | number) => ['catalog', 'table', id] as const,
    column: (id: string | number) => ['catalog', 'column', id] as const,
  },
  changes: {
    list: (p?: unknown) => ['changes', 'list', p] as const,
    detail: (id: string | number) => ['changes', 'detail', id] as const,
    statistics: (p?: unknown) => ['changes', 'statistics', p] as const,
    history: (type: string, fqn: string) => ['changes', 'history', type, fqn] as const,
  },
  tasks: {
    list: (p?: unknown) => ['tasks', 'list', p] as const,
    detail: (id: string | number) => ['tasks', 'detail', id] as const,
  },
  subscriptions: {
    all: ['subscriptions'] as const,
    list: (p?: unknown) => ['subscriptions', 'list', p] as const,
  },
  audit: {
    list: (p?: unknown) => ['audit', 'list', p] as const,
  },
  partitions: {
    list: () => ['partitions', 'list'] as const,
  },
  system: {
    health: () => ['system', 'health'] as const,
    metrics: () => ['system', 'metrics'] as const,
  },
  governance: {
    approvals: (p?: unknown) => ['governance', 'approvals', p] as const,
    approval: (id: string | number) => ['governance', 'approval', id] as const,
    approvalComments: (id: string | number) => ['governance', 'approvalComments', id] as const,
    tickets: (p?: unknown) => ['governance', 'tickets', p] as const,
    ticket: (id: string | number) => ['governance', 'ticket', id] as const,
    ticketComments: (id: string | number) => ['governance', 'ticketComments', id] as const,
  },
  lineage: {
    impact: (fqn: string) => ['lineage', 'impact', fqn] as const,
  },
  business: {
    terms: () => ['business', 'terms'] as const,
    entity: (type: string, id: string | number) => ['business', 'entity', type, id] as const,
  },
} as const;
