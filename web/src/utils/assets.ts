/**
 * 资产详情链接：全站统一按 **FQN** 跳转。
 *
 * 背景：`/api/v1/assets/{fqn}` 只接受 FQN，早期实现把检索结果的数字 id 拼进
 * `/app/catalog/tables/{id}`，导致详情页 100% 404、核心旅程「找表 → 看字段」断裂
 * （doc/design/ux-audit-full.md S0#1 / B1）。
 * 任何跳转资产详情的地方都必须走这里，不要再拼数字 id。
 */

export const ASSET_TYPE_TEXT: Record<string, string> = {
  table: '表',
  column: '字段',
  database: '库',
  schema: 'Schema',
};

export function entityTypeText(t?: string): string {
  if (!t) return '资产';
  return ASSET_TYPE_TEXT[t] ?? t;
}

/** 推断父表 FQN（列 FQN = 父表 FQN + '.' + 列名），仅在拿不到 parentFqn 时兜底。 */
export function guessParentFqn(fqn?: string): string | undefined {
  if (!fqn) return undefined;
  const idx = fqn.lastIndexOf('.');
  return idx > 0 ? fqn.slice(0, idx) : undefined;
}

export function tableDetailLink(fqn?: string): string {
  return `/app/catalog/tables?fqn=${encodeURIComponent(fqn ?? '')}`;
}

export function columnDetailLink(fqn?: string, parentFqn?: string | null): string {
  const parent = parentFqn ?? guessParentFqn(fqn);
  const base = `/app/catalog/columns?fqn=${encodeURIComponent(fqn ?? '')}`;
  return parent ? `${base}&parent=${encodeURIComponent(parent)}` : base;
}

/** 按检索结果的类型分流到表/字段详情页。 */
export function assetDetailLink(item: { fqn?: string; entityType?: string; type?: string; parentFqn?: string | null }): string {
  const fqn = item.fqn;
  if (!fqn) return '/app/catalog';
  const kind = item.entityType ?? item.type;
  return kind === 'column'
    ? columnDetailLink(fqn, item.parentFqn)
    : kind === 'table'
      ? tableDetailLink(fqn)
      : tableDetailLink(fqn);
}
