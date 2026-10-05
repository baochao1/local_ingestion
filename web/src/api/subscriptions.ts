import { cleanParams, del, get, post } from './client';

/** MOD-06 订阅管理（后端 `/api/v1/subscriptions`，响应 camelCase）。 */

export interface Subscription {
  id: number;
  subscriber?: string;
  scopeType?: string;
  scopeFqn?: string | null;
  datasourceId?: number | null;
  minSeverity?: string;
  channel?: string;
  enabled?: boolean;
  createdAt?: string | null;
  [key: string]: any;
}

export interface SubscriptionListParams {
  subscriber?: string;
  enabled?: boolean;
  cursor?: string | null;
  limit?: number;
}

export function listSubscriptions(params: SubscriptionListParams = {}) {
  return get<{ items: Subscription[]; total?: number }>(
    '/subscriptions',
    cleanParams(params as Record<string, unknown>),
  );
}

export function createSubscription(data: Record<string, unknown>) {
  return post<Subscription>('/subscriptions', data);
}

export function muteSubscription(id: string | number) {
  return post<Subscription>(`/subscriptions/${id}/mute`);
}

export function unmuteSubscription(id: string | number) {
  return post<Subscription>(`/subscriptions/${id}/unmute`);
}

export function deleteSubscription(id: string | number) {
  return del<void>(`/subscriptions/${id}`);
}
