import { useQuery } from '@tanstack/react-query';
import { listDatasources } from '@/api/datasources';
import { qk } from '@/api/keys';

/**
 * 数据源 ID → 名称解析（G2 的一部分）。
 *
 * 界面上大量位置只拿到 `datasource_id`，直接渲染成裸数字（"数据源 3"），
 * 用户必须记住编号含义（ux-audit-full.md S1#10）。数据源数量可控，
 * 这里一次性拉全量做 id → 名称缓存，供各列表/详情复用。
 */
export function useDatasourceMap() {
  return useQuery({
    queryKey: qk.datasources.list({ all: 1 }),
    queryFn: async () => {
      const res = await listDatasources({ limit: 200 });
      const items = res.items ?? [];
      const map = new Map<number, string>();
      for (const d of items) {
        if (d.id == null) continue;
        map.set(Number(d.id), String(d.name ?? d.code ?? `数据源 ${d.id}`));
      }
      return map;
    },
    staleTime: 5 * 60_000,
  });
}

/** 单个 id 的名称；拿不到时回退「数据源 N」，避免又出现裸数字。 */
export function useDatasourceName(id?: number | string | null): string | undefined {
  const { data } = useDatasourceMap();
  if (id == null) return undefined;
  const key = Number(id);
  return data?.get(key) ?? `数据源 ${id}`;
}

/**
 * 列表页批量解析：把 id → 名称的 Map 暴露出去，
 * 避免每行各发一次请求。
 */
export function useDatasourceNames(): {
  name: (id?: number | string | null) => string | undefined;
  loading: boolean;
} {
  const { data, isLoading } = useDatasourceMap();
  return {
    loading: isLoading,
    name: (id) => {
      if (id == null) return undefined;
      const key = Number(id);
      return data?.get(key) ?? `数据源 ${id}`;
    },
  };
}
