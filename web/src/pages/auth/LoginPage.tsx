import { Alert, Button, Card, Form, Input, Typography } from 'antd';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '@/store/auth';

/**
 * 登录页（FE-01 §1）。
 *
 * MOD-11 未上线，后端无 `/auth/login`，因此降级为「跳过登录直接进入」。
 * 表单仍保留，便于后续接真实认证接口。
 */
export default function LoginPage() {
  const navigate = useNavigate();
  const setSession = useAuthStore((s) => s.setSession);
  const enterAsGuest = useAuthStore((s) => s.enterAsGuest);
  const [error, setError] = useState<string | null>(null);

  const onFinish = (values: { username: string; password: string }) => {
    // 后端暂无认证接口：本地建立会话并进入（dev 降级）。
    setSession(`dev.${values.username}`, values.username, []);
    navigate('/app/dashboard');
  };

  const skip = () => {
    enterAsGuest();
    navigate('/app/dashboard');
  };

  return (
    <div
      style={{
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f0f2f5',
      }}
    >
      <Card style={{ width: 380 }}>
        <Typography.Title level={4} style={{ textAlign: 'center', marginBottom: 4 }}>
          元数据治理平台
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ textAlign: 'center' }}>
          平台账号由管理员分配
        </Typography.Paragraph>

        {error ? <Alert type="error" message={error} style={{ marginBottom: 12 }} /> : null}

        <Form layout="vertical" onFinish={onFinish}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input placeholder="请输入用户名" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password placeholder="请输入密码" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block>
            登录
          </Button>
        </Form>

        <Alert
          type="info"
          showIcon
          style={{ marginTop: 16 }}
          message="当前后端未启用认证（MOD-11 未上线）"
          description={
            <Button type="link" style={{ paddingLeft: 0 }} onClick={skip}>
              跳过登录直接进入（dev）
            </Button>
          }
        />
      </Card>
    </div>
  );
}
