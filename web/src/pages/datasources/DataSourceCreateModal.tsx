import {
  Alert,
  App,
  Button,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Switch,
} from 'antd';
import { useState } from 'react';
import { createDataSource, testConnection } from '@/api/datasources';
import { toUserMessage } from '@/api/errors';

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

/** 与后端 `ALLOWED_DS_TYPES` 保持一致（platform/datasource/service.py）。 */
export const DS_TYPES = [
  'mysql',
  'postgres',
  'postgresql',
  'snowflake',
  'sqlserver',
  'bigquery',
  'other',
];

/**
 * 新建数据源（MOD-01 §3.1）。表单直接对接后端
 * `POST /api/v1/datasources`（注册）与 `POST /api/v1/datasources/test`（连通性测试）。
 */
export default function DataSourceCreateModal({ open, onClose, onCreated }: Props) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [submitting, setSubmitting] = useState(false);
  const [testing, setTesting] = useState(false);
  // 注册会先连接目标库做只读探测，耗时可达数秒，必须让用户知道系统在做什么
  const [progress, setProgress] = useState('');

  const handleTest = async () => {
    try {
      const v = await form.validateFields([
        'dsType',
        'host',
        'port',
        'username',
        'password',
        'database',
      ]);
      setTesting(true);
      const res = await testConnection({
        dsType: v.dsType,
        host: v.host ?? null,
        port: v.port ?? null,
        username: v.username ?? null,
        password: v.password ?? null,
        // 指定库后连通性测试才真正探测目标库，而不是连到默认库
        database: v.database ?? null,
      });
      // 后端返回 `{connected, readonly, reason}`（ok/success/message 为兼容字段）
      const connected = res?.connected ?? res?.ok ?? res?.success;
      const detail = res?.reason ?? res?.message;
      if (connected) {
        message.success(
          `连接成功${res?.readonly ? '（只读）' : '（具备写权限）'}${detail ? `：${detail}` : ''}`,
        );
      } else {
        // detail 来自后端 reason 字段：截断并压平换行，避免长堆栈淹没提示
        const flat = typeof detail === 'string' ? detail.replace(/\s+/g, ' ').slice(0, 120) : '';
        message.error(`连接失败${flat ? `：${flat}` : ''}`);
      }
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) {
        // antd 校验失败：字段红字已渲染，不再弹 toast
        return;
      }
      message.error(toUserMessage(e, '连接测试失败'));
    } finally {
      setTesting(false);
    }
  };

  const handleSubmit = async () => {
    try {
      const v = await form.validateFields();
      setSubmitting(true);
      setProgress('正在校验并连接目标库…');
      await createDataSource({
        code: v.code,
        name: v.name,
        dsType: v.dsType,
        host: v.host ?? null,
        port: v.port ?? null,
        environment: v.environment || null,
        groupName: v.groupName || null,
        ownerBusiness: v.ownerBusiness || null,
        ownerTechnical: v.ownerTechnical || null,
        enabled: v.enabled,
        scanEnabled: v.scanEnabled,
        samplingEnabled: v.samplingEnabled,
        username: v.username || null,
        password: v.password || null,
        // 目标库写入 scan_config.database，供后续扫描直接使用（否则只能依赖自动发现）
        scanConfig: v.database ? { database: v.database } : {},
        // FR-1.5：连接具备写权限（或无法验证只读）时，须显式允许写权限才能注册
        allowWrite: v.allowWrite,
      });
      setProgress('');
      message.success('数据源创建成功');
      form.resetFields();
      onCreated();
      onClose();
    } catch (e: unknown) {
      setProgress('');
      if (e && typeof e === 'object' && 'errorFields' in e) {
        // antd 校验失败：字段红字已渲染，不再弹「创建失败」误导用户
        return;
      }
      message.error(toUserMessage(e, '创建失败'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="新建数据源"
      open={open}
      onCancel={onClose}
      width={680}
      destroyOnHidden
      footer={[
        <Button key="test" onClick={handleTest} loading={testing}>
          测试连接
        </Button>,
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button key="submit" type="primary" loading={submitting} onClick={handleSubmit}>
          提交
        </Button>,
      ]}
    >
      {progress ? (
        <Alert type="info" showIcon message={progress} style={{ marginBottom: 12 }} />
      ) : null}
      <Form
        form={form}
        layout="vertical"
        initialValues={{ enabled: true, scanEnabled: true, samplingEnabled: false, allowWrite: false }}
      >
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item label="编码" name="code" rules={[{ required: true, message: '请输入编码' }]}>
              <Input placeholder="唯一编码，如 ds_mysql_01" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="名称" name="name" rules={[{ required: true, message: '请输入名称' }]}>
              <Input placeholder="展示名称" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="类型" name="dsType" rules={[{ required: true, message: '请选择类型' }]}>
              <Select
                placeholder="请选择"
                showSearch
                options={DS_TYPES.map((t) => ({ label: t, value: t }))}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="环境" name="environment">
              <Input placeholder="如 prod / test" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="主机" name="host">
              <Input placeholder="如 127.0.0.1" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="端口" name="port">
              <InputNumber style={{ width: '100%' }} placeholder="如 3306" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="业务负责人" name="ownerBusiness">
              <Input placeholder="可选" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="技术负责人" name="ownerTechnical">
              <Input placeholder="可选" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="分组" name="groupName">
              <Input placeholder="可选" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="用户名" name="username">
              <Input placeholder="可选" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label="密码" name="password">
              <Input.Password placeholder="可选" />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item
              label="目标数据库"
              name="database"
              tooltip="可选，写入 scan_config.database。留空则扫描时自动发现（仅当该服务端只有 1 个用户库时可用）；服务端有多个用户库时必须指定"
            >
              <Input placeholder="如 postgres / mydb" />
            </Form.Item>
          </Col>
        </Row>
        <Space size={24} wrap>
          <Form.Item label="启用" name="enabled" valuePropName="checked" style={{ marginBottom: 0 }}>
            <Switch />
          </Form.Item>
          <Form.Item
            label="启用扫描"
            name="scanEnabled"
            valuePropName="checked"
            style={{ marginBottom: 0 }}
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label="启用采样"
            name="samplingEnabled"
            valuePropName="checked"
            style={{ marginBottom: 0 }}
          >
            <Switch />
          </Form.Item>
          <Form.Item
            label="允许写权限注册"
            name="allowWrite"
            valuePropName="checked"
            style={{ marginBottom: 0 }}
            tooltip="FR-1.5 只读策略：连接具备写权限（或无法验证只读）时，须显式勾选才能注册"
          >
            <Switch />
          </Form.Item>
        </Space>
      </Form>
    </Modal>
  );
}
