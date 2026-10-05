import { Input, Modal, Space, Switch, Typography } from 'antd';
import { useEffect, useState } from 'react';

interface ScanModalProps {
  open: boolean;
  title?: string;
  confirmLoading?: boolean;
  onCancel: () => void;
  /** database 为空表示沿用数据源 scan_config 的配置或走自动发现。 */
  onConfirm: (allowWrite: boolean, database?: string) => void;
}

/** 扫描确认弹窗：默认保持只读（FR-1.5）。
 *
 * 当数据源使用具备写权限的账号（如 postgres 超级用户）时，只读校验会拒绝扫描；
 * 本地/测试环境可勾选 allowWrite 临时放行。
 *
 * 「目标数据库」对应后端 `database=` 入参：留空时后端回退到
 * `scan_config.database`；两者都缺失才会尝试连接服务端自动列举用户库，
 * 而自动列举仅在服务端只有 1 个用户库时能选定，多库场景必须在此显式指定。
 */
export default function ScanModal({
  open,
  title = '确认扫描',
  confirmLoading,
  onCancel,
  onConfirm,
}: ScanModalProps) {
  const [allowWrite, setAllowWrite] = useState(false);
  const [database, setDatabase] = useState('');

  // 弹窗实例是复用的（始终挂载），每次打开都要重置，
  // 否则上一次的勾选/输入会残留到下一次扫描。
  useEffect(() => {
    if (open) {
      setAllowWrite(false);
      setDatabase('');
    }
  }, [open]);

  return (
    <Modal
      open={open}
      title={title}
      okText="开始扫描"
      cancelText="取消"
      confirmLoading={confirmLoading}
      onCancel={onCancel}
      onOk={() => onConfirm(allowWrite, database.trim() || undefined)}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        将以只读方式连接数据源（FR-1.5 安全策略）。若账号具备写权限（如 postgres 超级用户），
        只读校验会拒绝扫描，此时可勾选下方选项放行。
      </Typography.Paragraph>
      <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
        目标数据库可选：留空则使用数据源 scan_config 中已配置的库；若未配置，
        系统会尝试连接服务端自动发现（仅当该服务端只有 1 个用户库时可用），否则需在此显式指定。
      </Typography.Paragraph>
      <Input
        value={database}
        onChange={(e) => setDatabase(e.target.value)}
        placeholder="目标数据库（可选），如 postgres"
        allowClear
        style={{ marginBottom: 12 }}
      />
      <Space>
        <Switch checked={allowWrite} onChange={setAllowWrite} />
        <Typography.Text>允许写权限（allowWrite，仅本地 / 测试使用）</Typography.Text>
      </Space>
    </Modal>
  );
}
