import { Popconfirm } from 'antd';
import { useState } from 'react';
import type { ReactNode } from 'react';
import { COLORS } from '@/theme';

export interface ConfirmDangerProps {
  title: ReactNode;
  description?: ReactNode;
  onConfirm: () => void | Promise<void>;
  okText?: string;
  cancelText?: string;
  /** 触发按钮/链接。 */
  children: ReactNode;
  /** 审计提示；false 关闭，字符串可自定义（FE-00 §6.5）。 */
  auditHint?: boolean | ReactNode;
  disabled?: boolean;
}

/** 危险操作二次确认 + 审计提示（FE-01 §0）。 */
export function ConfirmDanger({
  title,
  description,
  onConfirm,
  okText = '确认',
  cancelText = '取消',
  children,
  auditHint = true,
  disabled,
}: ConfirmDangerProps) {
  const [loading, setLoading] = useState(false);

  const handleConfirm = async () => {
    try {
      setLoading(true);
      await onConfirm();
    } finally {
      setLoading(false);
    }
  };

  const hint = auditHint === false ? null : auditHint === true ? '此操作将被审计' : auditHint;

  return (
    <Popconfirm
      title={title}
      description={
        <>
          {description}
          {hint ? <div style={{ marginTop: 4, color: COLORS.warning }}>{hint}</div> : null}
        </>
      }
      okText={okText}
      cancelText={cancelText}
      okButtonProps={{ danger: true, loading }}
      onConfirm={handleConfirm}
      disabled={disabled}
    >
      <span style={{ display: 'inline-block' }}>{children}</span>
    </Popconfirm>
  );
}

export default ConfirmDanger;
