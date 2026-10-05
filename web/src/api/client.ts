import axios from 'axios';
import type { AxiosRequestConfig } from 'axios';
import { useAuthStore } from '@/store/auth';
import { composeErrorMessage, flattenDetail } from './errors';

/** REST 基座：`VITE_API_BASE` 可覆盖，默认 `/api/v1`（由 vite dev proxy 转发）。 */
export const API_BASE = (import.meta.env.VITE_API_BASE as string) || '/api/v1';

export const http = axios.create({
  baseURL: API_BASE,
  timeout: 30_000,
});

/**
 * 当前操作人。MOD-11（RBAC）未上线，登录是降级形态，
 * 因此兜底到 `guest`：宁可审计里记 guest，也不要因为缺 actor 触发 422。
 */
export function currentActor(explicit?: string): string {
  return explicit || useAuthStore.getState().username || 'guest';
}

/** 归一后的错误形状（FE-00 §6.1：`{ code, message, detail }`）。 */
export interface ApiError {
  code?: string | number;
  message: string;
  detail?: unknown;
}

http.interceptors.request.use((config) => {
  const { token } = useAuthStore.getState();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status;
    const data = error?.response?.data;
    if (status === 401) {
      useAuthStore.getState().logout();
    }
    const apiError: ApiError = {
      code: status ?? data?.code,
      // ux-audit-full.md G3：detail 可能是 FastAPI 的错误对象数组，必须归一成字符串，
      // 否则页面把它当 React 子节点渲染会崩溃。
      message: composeErrorMessage(status, data),
      detail: flattenDetail(data?.detail),
    };
    return Promise.reject(apiError);
  },
);

/** 发送请求的唯一入口：返回响应体 `data`，错误已归一为 `ApiError`。 */
export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const res = await http.request<T>(config);
  return res.data;
}

export function get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
  return request<T>({ method: 'GET', url, params });
}

export function post<T>(url: string, data?: unknown, params?: Record<string, unknown>): Promise<T> {
  return request<T>({ method: 'POST', url, data, params });
}

export function put<T>(url: string, data?: unknown): Promise<T> {
  return request<T>({ method: 'PUT', url, data });
}

export function del<T>(url: string): Promise<T> {
  return request<T>({ method: 'DELETE', url });
}

/** 去掉 undefined / 空串，避免把空筛选条件发给后端。 */
export function cleanParams(params: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    out[k] = v;
  }
  return out;
}
