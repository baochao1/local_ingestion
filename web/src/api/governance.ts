import { cleanParams, currentActor, get, post } from './client';
import type { ApprovalComment, ApprovalRequest, Ticket, TicketComment } from '@/types';

/**
 * MOD-12 审批流 + 工单。
 *
 * 契约说明（ux-audit-full.md G3）：请求体字段名以**后端为准**——决策是
 * `{actor, comment}`、工单流转是 `{to_status, actor}`；列表筛选参数是 `status_filter`。
 * 历史上前端发过 `decided_by` / `decision_note` / `status`，正是那一处不一致
 * 导致 422 → 全站白屏，此处不再保留旧名。
 */

/**
 * 决策意见。后端字段叫 `comment`，这里用语义更准的 `note` 作为入参名，
 * 出口统一映射，避免调用方再写错。
 */
export interface DecisionPayload {
  actor?: string;
  note?: string;
}

// ------------------------------------------------------------------ 审批
export interface ApprovalListParams {
  /** 后端实际参数名是 `status_filter`（不是 `status`）。 */
  status_filter?: string;
  resource_type?: string;
  approver?: string;
  cursor?: string | null;
  limit?: number;
}

export function listApprovals(params: ApprovalListParams = {}) {
  return get<ApprovalRequest[] | { items: ApprovalRequest[] }>(
    '/governance/approvals',
    cleanParams(params as Record<string, unknown>),
  );
}

export interface ApprovalCreatePayload {
  resource_type: string;
  resource_fqn: string;
  /** 后端字段名是 `action_type`，不是 `action`。 */
  action_type: string;
  title: string;
  requested_by?: string;
  approver?: string;
  priority?: string;
  reason?: string;
  actor?: string;
}

export function createApproval(data: ApprovalCreatePayload) {
  const actor = currentActor(data.actor);
  return post<ApprovalRequest>('/governance/approvals', { ...data, actor });
}

export function getApproval(id: string | number) {
  return get<ApprovalRequest>(`/governance/approvals/${id}`);
}

export function approveApproval(id: string | number, data: DecisionPayload = {}) {
  return post<ApprovalRequest>(`/governance/approvals/${id}/approve`, {
    actor: currentActor(data.actor),
    comment: data.note,
  });
}

export function rejectApproval(id: string | number, data: DecisionPayload = {}) {
  return post<ApprovalRequest>(`/governance/approvals/${id}/reject`, {
    actor: currentActor(data.actor),
    comment: data.note,
  });
}

export function listApprovalComments(id: string | number) {
  return get<ApprovalComment[]>(`/governance/approvals/${id}/comments`);
}

export function addApprovalComment(id: string | number, data: Record<string, unknown>) {
  return post<ApprovalComment>(`/governance/approvals/${id}/comments`, data);
}

// ------------------------------------------------------------------ 工单
export interface TicketListParams {
  status_filter?: string;
  ticket_type?: string;
  assignee?: string;
  source?: string;
  cursor?: string | null;
  limit?: number;
}

export function listTickets(params: TicketListParams = {}) {
  return get<Ticket[] | { items: Ticket[] }>(
    '/governance/tickets',
    cleanParams(params as Record<string, unknown>),
  );
}

export function createTicket(data: Record<string, unknown>) {
  return post<Ticket>('/governance/tickets', data);
}

export function getTicket(id: string | number) {
  return get<Ticket>(`/governance/tickets/${id}`);
}

export function assignTicket(id: string | number, data: { assignee: string; actor?: string }) {
  return post<Ticket>(`/governance/tickets/${id}/assign`, {
    assignee: data.assignee,
    actor: currentActor(data.actor),
  });
}

/** 后端字段是 `to_status`（不是 `status`）。 */
export function transitionTicket(
  id: string | number,
  data: { to_status: string; actor?: string },
) {
  return post<Ticket>(`/governance/tickets/${id}/transition`, {
    to_status: data.to_status,
    actor: currentActor(data.actor),
  });
}

export function listTicketComments(id: string | number) {
  return get<TicketComment[]>(`/governance/tickets/${id}/comments`);
}

export function addTicketComment(id: string | number, data: Record<string, unknown>) {
  return post<TicketComment>(`/governance/tickets/${id}/comments`, data);
}

/**
 * 后端列表信封不统一：有的返回数组、有的 `{items}`、治理模块返回
 * `{approvals}` / `{tickets}`。这里统一成数组：优先 `items`，
 * 否则取响应里第一个数组字段（避免整页空白）。
 */
export function toItems<T>(res: unknown): T[] {
  if (!res) return [];
  if (Array.isArray(res)) return res as T[];
  if (typeof res !== 'object') return [];
  const obj = res as Record<string, unknown>;
  if (Array.isArray(obj.items)) return obj.items as T[];
  for (const v of Object.values(obj)) {
    if (Array.isArray(v)) return v as T[];
  }
  return [];
}
