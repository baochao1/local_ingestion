import { Breadcrumb, Space, Typography } from 'antd';
import type { BreadcrumbProps } from 'antd';
import type { ReactNode } from 'react';

export interface PageHeaderBreadcrumbItem {
  title: ReactNode;
  href?: string;
}

export interface PageHeaderProps {
  title: ReactNode;
  breadcrumb?: PageHeaderBreadcrumbItem[];
  extra?: ReactNode;
  subtitle?: ReactNode;
}

/** 页头：面包屑 + 标题（+副标题）+ 右侧操作区（FE-00 §4）。 */
export function PageHeader({ title, breadcrumb, extra, subtitle }: PageHeaderProps) {
  return (
    <div style={{ marginBottom: 16 }}>
      {breadcrumb && breadcrumb.length > 0 ? (
        <Breadcrumb
          style={{ marginBottom: 8 }}
          items={breadcrumb as BreadcrumbProps['items']}
        />
      ) : null}
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ minWidth: 0 }}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            {title}
          </Typography.Title>
          {subtitle ? (
            <div style={{ marginTop: 4 }}>
              <Typography.Text type="secondary">{subtitle}</Typography.Text>
            </div>
          ) : null}
        </div>
        {extra ? <Space wrap>{extra}</Space> : null}
      </div>
    </div>
  );
}

export default PageHeader;
