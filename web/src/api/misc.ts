import { get, put, post } from './client';
import type { BusinessMetadata, BusinessTerm, LineageImpact } from '@/types';

/** MOD-07 血缘（仅影响面可用）+ MOD-09 业务元数据。两者后端均返回 snake_case。 */

export function getLineageImpact(fqn: string, params: { depth?: number } = {}) {
  return get<LineageImpact>(
    `/lineage/tables/${encodeURIComponent(fqn)}/impact`,
    params as Record<string, unknown>,
  );
}

export function listBusinessTerms() {
  return get<BusinessTerm[]>('/business/terms');
}

export function createBusinessTerm(data: Record<string, unknown>) {
  return post<BusinessTerm>('/business/terms', data);
}

export function getBusinessTerm(termCode: string) {
  return get<BusinessTerm>(`/business/terms/${encodeURIComponent(termCode)}`);
}

export function getBusinessMetadata(entityType: string, entityId: string | number) {
  return get<BusinessMetadata | null>(
    `/business/entities/${encodeURIComponent(entityType)}/${entityId}`,
  );
}

export function upsertBusinessMetadata(
  entityType: string,
  entityId: string | number,
  data: Record<string, unknown>,
) {
  return put<BusinessMetadata>(
    `/business/entities/${encodeURIComponent(entityType)}/${entityId}`,
    data,
  );
}

export function addBusinessTags(
  entityType: string,
  entityId: string | number,
  data: Record<string, unknown>,
) {
  return post<BusinessMetadata>(
    `/business/entities/${encodeURIComponent(entityType)}/${entityId}/tags`,
    data,
  );
}
