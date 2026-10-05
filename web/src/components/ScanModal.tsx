import { Modal, Space, Switch, Typography } from 'antd';
import { useState } from 'react';

interface ScanModalProps {
  open: boolean;
  title?: string;
  confirmLoading?: boolean;
  onCancel: () => void;
  onConfirm: (allowWrite: boolean) => void;
}

/** 扫描确认弹窗：默认保持只读（FR-1.5）。
 *
 * 当数据源使用具备写权限的账号（如 postgres 超级用户）时，只读校验会拒绝扫描；
 * 本地/测试环境可勾选 allowWrite 临时放行。 */
export default function ScanModal({
  open,
  title = '确认扫描',
  confirmLoading,
  onCancel,
  onConfirm,
}: ScanModalProps) {
  const [allowWrite, setAllowWrite] = useState(false);

  return (
    <Modal
      open={open}
      title={title}
      okText="开始扫描"
      cancelText="取消"
      confirmLoading={confirmLoading}
      onCancel={onCancel}
      onOk={() => onConfirm(allowWrite)}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        将以只读方式连接数据源（FR-1.5 安全策略）。若账号具备写权限（如 postgres 超级用户），
        只读校验会拒绝扫描，此时可勾选下方选项放行。
      </Typography.Paragraph>
      <Space>
        <Switch checked={allowWrite} onChange={setAllowWrite} />
        <Typography.Text>允许写权限（allowWrite，仅本地 / 测试使用）</Typography.Text>
      </Space>
    </Modal>
  );
}
