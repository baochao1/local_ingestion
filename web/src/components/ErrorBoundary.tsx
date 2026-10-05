import { Button, Result, Space, Typography } from 'antd';
import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import { toUserMessage } from '@/api/errors';

export interface ErrorBoundaryProps {
  children: ReactNode;
  /** 变化时自动复位（一般传 `location.pathname`），避免换页后仍停在错误态。 */
  resetKey?: unknown;
  /** 兜底文案。 */
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * 页面级兜底（ux-audit-full.md G3）：任何未被 try/catch 覆盖的渲染异常
 * 都收敛到这里，头部与侧边导航保持可用，而不是整屏空白。
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps): void {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <Result
        status="error"
        title="页面出错了"
        subTitle={toUserMessage(error, '页面渲染时出现异常，其余功能仍可正常使用')}
        extra={
          <Space>
            <Button type="primary" onClick={() => this.setState({ error: null })}>
              重试
            </Button>
            <Button onClick={this.handleReload}>刷新页面</Button>
          </Space>
        }
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, wordBreak: 'break-all' }}>
          <Typography.Text code>{String(error.message ?? error)}</Typography.Text>
        </Typography.Paragraph>
      </Result>
    );
  }
}

export default ErrorBoundary;
