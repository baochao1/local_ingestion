/**
 * 错误归一：把后端/网络异常统一拍平成「可直接渲染给用户的一行字符串」。
 *
 * 背景（ux-audit-full.md S0#2/#3）：FastAPI 的 422 响应体是
 * `{"detail":[{"type":"missing","loc":["body","actor"],"msg":"Field required"}]}`，
 * 前端直接把它当 React 子节点渲染会触发
 * `Objects are not valid as a React child` 并整站白屏。
 * 这里统一在 API 出口做归一，禁止任何对象/数组形式的错误文字流入 UI。
 */

/** HTTP 状态码 → 面向用户的措辞（FE-00 §6.1）。 */
const STATUS_TEXT: Record<number, string> = {
  400: '请求参数有误',
  401: '登录已失效，请重新登录',
  403: '没有权限执行该操作',
  404: '资源不存在',
  409: '数据状态冲突',
  422: '请求参数有误',
  429: '操作过于频繁，请稍后重试',
  500: '服务端内部错误',
  502: '网关错误',
  503: '服务暂时不可用',
};

/** FastAPI 校验错误 `type` → 中文原因。 */
const VALIDATION_TYPE_TEXT: Record<string, string> = {
  missing: '缺少必填字段',
  string_type: '应为字符串',
  int_type: '应为整数',
  int_parsing: '应为整数',
  float_parsing: '应为数值',
  bool_parsing: '应为布尔值',
  enum: '取值不在允许范围内',
  value_error: '取值不合法',
  string_too_short: '内容过短',
  greater_than_equal: '小于允许的最小值',
  less_than_equal: '超出允许的最大值',
};

/** `loc` 里的 body/query/path 是传输位置，不是字段含义，不展示给用户。 */
const LOC_IGNORED = new Set(['body', 'query', 'path', 'header', 'cookie']);

function flattenValidationItem(item: unknown): string {
  if (typeof item === 'string') return item;
  if (typeof item !== 'object' || item === null) return String(item);
  const e = item as { loc?: unknown[]; type?: string; msg?: string };
  const loc = (e.loc ?? []).map(String).filter((p) => !LOC_IGNORED.has(p));
  const field = loc.join('.') || '请求体';
  const reason = VALIDATION_TYPE_TEXT[e.type ?? ''] ?? e.msg ?? '取值不合法';
  return `${field}：${reason}`;
}

/**
 * 把任意 `detail` / `message` 值安全地转成字符串。
 * 数组取每项的可读描述用「；」连接；对象优先取 `message`/`msg`，否则 JSON 兜底。
 */
export function flattenDetail(detail: unknown): string | undefined {
  if (detail === undefined || detail === null) return undefined;
  if (typeof detail === 'string') {
    const s = detail.trim();
    return s || undefined;
  }
  if (Array.isArray(detail)) {
    const parts = detail.map(flattenValidationItem).filter(Boolean);
    return parts.length ? parts.join('；') : undefined;
  }
  if (typeof detail === 'object') {
    const o = detail as Record<string, unknown>;
    for (const key of ['message', 'msg', 'detail']) {
      const text = flattenDetail(o[key]);
      if (text) return text;
    }
    try {
      return JSON.stringify(detail);
    } catch {
      return undefined;
    }
  }
  return String(detail);
}

/** 合成给用户看的错误信息：`前缀：具体原因`。 */
export function composeErrorMessage(
  status: number | undefined,
  body: Record<string, unknown> | undefined,
): string {
  const prefix = typeof status === 'number' ? STATUS_TEXT[status] : undefined;
  const raw = flattenDetail(body?.message) ?? flattenDetail(body?.detail);
  if (raw && prefix && !raw.startsWith(prefix)) return `${prefix}：${raw}`;
  return raw ?? prefix ?? '请求失败';
}

function asRecord(v: unknown): Record<string, unknown> | undefined {
  return typeof v === 'object' && v !== null ? (v as Record<string, unknown>) : undefined;
}

/** 任意异常 → 可安全渲染的一行文字（ErrorState / ErrorBoundary / message.error 共用）。 */
export function toUserMessage(error: unknown, fallback = '请求失败'): string {
  if (error === null || error === undefined) return fallback;
  if (typeof error === 'string') return error.trim() || fallback;
  if (error instanceof Error) return error.message || fallback;
  const e = error as {
    code?: unknown;
    message?: unknown;
    detail?: unknown;
    response?: { status?: number; data?: unknown };
  };
  if (e.response) {
    return composeErrorMessage(e.response.status, asRecord(e.response.data));
  }
  const text = flattenDetail(e.message) ?? flattenDetail(e.detail);
  if (text) return text;
  const prefix = typeof e.code === 'number' ? STATUS_TEXT[e.code] : undefined;
  return prefix ?? fallback;
}

/**
 * 判断错误是否值得让用户重试（ux-audit P1-3）。
 *
 * 404/403/409 属于确定性失败，重试必然再次失败，会把用户引入无效循环；
 * 网络错误、5xx、429 才是可恢复的。
 */
export function isRecoverableError(error: unknown): boolean {
  // 注意：api/client.ts 的响应拦截器已把 axios 错误归一成 ApiError { code, message, detail }，
  // 不再有 response 字段；这里先读 code，再兼容原生 axios 错误。
  const e = error as { code?: unknown; response?: { status?: number } } | null | undefined;
  const status = typeof e?.code === 'number' ? e.code : e?.response?.status;
  if (typeof status === 'number') {
    if (status === 404 || status === 403 || status === 409) return false;
    return status >= 500 || status === 429 || status === 0;
  }
  // 无状态码＝网络层失败（断网/CORS/超时），可重试
  return true;
}

export default toUserMessage;
