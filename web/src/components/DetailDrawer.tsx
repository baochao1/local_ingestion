import { Button, Drawer, Space } from 'antd';
import type { ReactNode } from 'react';

export interface DetailDrawerProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  width?: number | string;
  children?: ReactNode;
  extra?: ReactNode;
}

/** 右侧详情抽屉（FE-00 §5.2）。 */
export function DetailDrawer({
  open,
  onClose,
  title,
  width = 640,
  children,
  extra,
}: DetailDrawerProps) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      title={title}
      width={width}
      footer={
        <div style={{ textAlign: 'right' }}>
          <Space>
            <Button onClick={onClose}>关闭</Button>
            {extra}
          </Space>
        </div>
      }
    >
      {children}
    </Drawer>
  );
}

export default DetailDrawer;
