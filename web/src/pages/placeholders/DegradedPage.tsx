import { Alert, Button, Card, Descriptions, Space, Tag } from 'antd';
import { useNavigate } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';

export interface DegradedPageProps {
  /** 模块编号，如 MOD-04。 */
  module?: string;
  title?: string;
  /** 该页面依赖但尚未落地的接口列表。 */
  apis?: string[];
}

/**
 * 降级占位页（FE-01 §16：未落地模块先以降级/占位形态就位）。
 * 明确展示「暂不可用」而非报错，并列出待补接口，便于后续联调。
 */
export default function DegradedPage({ module, title, apis }: DegradedPageProps) {
  const navigate = useNavigate();
  const name = title ?? '该能力';
  return (
    <div>
      <PageHeader title={name} breadcrumb={[{ title: '首页' }, { title: name }]} />
      <Card>
        <Alert
          type="info"
          showIcon
          message={`${name} 尚未开放`}
          description="该能力依赖的服务还在建设中，当前没有数据可展示。你可以先使用「数据源 / 资产检索 / 任务运维 / 数据变更 / 协作流程」等已开放的功能。"
        />
        <Space style={{ marginTop: 16 }}>
          <Button type="primary" onClick={() => navigate('/app/dashboard')}>
            返回概览
          </Button>
          <Button onClick={() => navigate(-1)}>返回上一页</Button>
        </Space>
        {/* 内部模块代号（MOD-xx）仅供联调排查，开发环境才展示，避免业务用户看到内部代号 */}
        {import.meta.env.DEV && module ? (
          <Descriptions style={{ marginTop: 16 }} column={1} size="small" bordered>
            <Descriptions.Item label="内部模块代号（联调用）">
              <Tag>{module}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="页面">{title ?? '-'}</Descriptions.Item>
            {apis && apis.length > 0 ? (
              <Descriptions.Item label="待补接口">
                {apis.map((a) => (
                  <div key={a} className="mono">
                    {a}
                  </div>
                ))}
              </Descriptions.Item>
            ) : null}
          </Descriptions>
        ) : null}
      </Card>
    </div>
  );
}
