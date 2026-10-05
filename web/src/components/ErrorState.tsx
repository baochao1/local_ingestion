import { Button, Result, Typography } from 'antd';
import type { ReactNode } from 'react';
import { isRecoverableError, toUserMessage } from '@/api/errors';

export interface ErrorStateProps {
  error?: unknown;
  onRetry?: () => void;
  description?: ReactNode;
  /** 不可恢复错误（404/403/409）的返回出口；未提供时回退浏览器后退。 */
  onBack?: () => void;
}

/**
 * 归一后端 `{ code, message, detail }` 与 axios 错误。
 * 统一走 `toUserMessage`，保证返回值一定是字符串（对象/数组错误不会流到 JSX）。
 */
export function pickErrorMessage(error: unknown): string | undefined {
  if (!error) return undefined;
  const text = toUserMessage(error, '');
  return text || undefined;
}

/** 四态之一：错误（必须提供「重试」按钮，FE-01 §0）。 */
export function ErrorState({ error, onRetry, description, onBack }: ErrorStateProps) {
  const message = pickErrorMessage(error);
  // 404/403/409 重试必然再次失败：改为给出返回出口，避免用户陷入无效循环
  const recoverable = isRecoverableError(error);
  return (
    <Result
      status="error"
      title="加载失败"
      subTitle={description ?? message ?? '请求出错，请稍后重试'}
      extra={
        recoverable ? (
          <Button type="primary" onClick={() => (onRetry ? onRetry() : window.location.reload())}>
            重试
          </Button>
        ) : (
          <Button type="primary" onClick={() => (onBack ? onBack() : window.history.back())}>
            返回列表
          </Button>
        )
      }
    >
      {message ? (
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, wordBreak: 'break-all' }}>
          <Typography.Text code>{message}</Typography.Text>
        </Typography.Paragraph>
      ) : null}
    </Result>
  );
}

export default ErrorState;
