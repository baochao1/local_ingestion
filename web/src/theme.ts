import type { ThemeConfig } from 'antd';

/** Design tokens — FE-00 §5. */
export const COLORS = {
  primary: '#2f54eb',
  success: '#52c41a',
  warning: '#faad14',
  error: '#ff4d4f',
  sensitive: '#cf1322',
} as const;

export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: COLORS.primary,
    colorSuccess: COLORS.success,
    colorWarning: COLORS.warning,
    colorError: COLORS.error,
    borderRadius: 6,
    fontSize: 14,
  },
};
