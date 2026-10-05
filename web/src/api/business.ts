import { get, post } from './client';

/** MOD-09 业务元数据。注意：后端**直接返回 snake_case**，未 camelize。 */

export interface BusinessTerm {
  id?: number;
  term_code?: string;
  term_name?: string;
  domain?: string | null;
  definition?: string | null;
  owner?: string | null;
  status?: string;
  created_at?: string | null;
  updated_at?: string | null;
  [key: string]: any;
}

export function listBusinessTerms(params: { domain?: string } = {}) {
  return get<{ terms: BusinessTerm[] }>('/business/terms', params);
}

export function createBusinessTerm(data: Record<string, unknown>) {
  return post<BusinessTerm>('/business/terms', data);
}
