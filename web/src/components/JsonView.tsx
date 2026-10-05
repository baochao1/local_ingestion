import { Button, Typography } from 'antd';
import { useMemo } from 'react';

export interface JsonViewProps {
  value: unknown;
  copyable?: boolean;
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

/** 只读 JSON 展示（脱敏/配置/审计详情）。 */
export function JsonView({ value, copyable = true }: JsonViewProps) {
  const text = useMemo(() => {
    if (value === undefined || value === null) return '';
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }, [value]);

  if (!text) return <Typography.Text type="secondary">—</Typography.Text>;

  return (
    <div>
      {copyable ? (
        <Button
          size="small"
          type="link"
          style={{ paddingLeft: 0 }}
          onClick={() => writeClipboard(text)}
        >
          复制
        </Button>
      ) : null}
      <pre
        style={{
          margin: 0,
          padding: 12,
          maxHeight: 400,
          overflow: 'auto',
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 6,
          fontSize: 12,
          lineHeight: 1.6,
        }}
      >
        {text}
      </pre>
    </div>
  );
}

export default JsonView;
