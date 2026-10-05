import { App, Button, Space, Tooltip } from 'antd';
import { Link } from 'react-router-dom';
import type { ReactNode } from 'react';

export interface TaskProgressLinkProps {
  id: number | string;
  label?: ReactNode;
}

function writeClipboard(text: string) {
  if (navigator.clipboard?.writeText) {
    void navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
}

/** 任务型操作引导：链接到 /app/tasks/{id} + 一键复制任务 ID（FE-01 §14）。 */
export function TaskProgressLink({ id, label }: TaskProgressLinkProps) {
  const { message } = App.useApp();
  return (
    <Space size={4}>
      <Link to={`/app/tasks/${id}`}>{label ?? `#${id}`}</Link>
      <Tooltip title="复制任务 ID">
        <Button
          type="link"
          size="small"
          style={{ padding: 0, height: 'auto' }}
          onClick={() => {
            writeClipboard(String(id));
            message.success('任务 ID 已复制');
          }}
        >
          复制
        </Button>
      </Tooltip>
    </Space>
  );
}

export default TaskProgressLink;
