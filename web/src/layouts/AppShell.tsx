import { useEffect, useMemo, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Avatar,
  Dropdown,
  Input,
  Layout,
  List,
  Menu,
  Modal,
  Space,
  Tag,
  Typography,
  theme as antdTheme,
} from 'antd';
import {
  ApartmentOutlined,
  DatabaseOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  SearchOutlined,
  SettingOutlined,
  SwapOutlined,
  TableOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { searchAssets } from '@/api/catalog';
import { qk } from '@/api/keys';
import { hasPerm, useAuthStore } from '@/store/auth';
import ErrorState from '@/components/ErrorState';
import LoadingSkeleton from '@/components/LoadingSkeleton';
import ErrorBoundary from '@/components/ErrorBoundary';
import { assetDetailLink } from '@/utils/assets';

const { Header, Sider, Content } = Layout;

interface MenuItem {
  key: string;
  label: string;
  icon?: React.ReactNode;
  /** MOD-11 权限码；为空则始终可见。 */
  perm?: string;
  /** 后端能力未落地：菜单上标记「规划中」，避免用户逐个点开踩空（ux-audit P1-7）。 */
  planned?: boolean;
  children?: MenuItem[];
}

/** Sider 菜单（FE-00 §4 / §7）：按 perm_code 过滤，无 MOD-11 时全可见。 */
const MENU: MenuItem[] = [
  { key: '/app/dashboard', label: '概览', icon: <DashboardOutlined />, perm: 'metadata:read' },
  { key: '/app/datasources', label: '数据源', icon: <DatabaseOutlined />, perm: 'datasource:read' },
  { key: '/app/catalog/browse', label: '资产浏览', icon: <TableOutlined />, perm: 'metadata:read' },
  { key: '/app/catalog', label: '资产检索', icon: <SearchOutlined />, perm: 'metadata:read' },
  { key: '/app/changes', label: '数据变更', icon: <SwapOutlined />, perm: 'change:read' },
  { key: '/app/profile', label: '画像质量', icon: <ExperimentOutlined />, perm: 'profile:read', planned: true },
  {
    // 分组 key 不用路径：子项里已有一个 /app/classification（概览），
    // SubMenu 的 key 若与之相同会被 antd 视为重复 key。
    key: 'classification-group',
    label: '分类分级',
    icon: <SafetyCertificateOutlined />,
    perm: 'classification:read',
    children: [
      { key: '/app/classification', label: '概览' },
      { key: '/app/classification/sensitive-assets', label: '敏感资产清单' },
      { key: '/app/classification/tags', label: '分级标准' },
      { key: '/app/classification/rules', label: '识别规则' },
    ],
  },
  { key: '/app/lineage', label: '血缘', icon: <ApartmentOutlined />, perm: 'lineage:read', planned: true },
  { key: '/app/permissions', label: '权限分析', icon: <LockOutlined />, perm: 'permission:read', planned: true },
  { key: '/app/sampling', label: '采样', icon: <ExperimentOutlined />, perm: 'sample:execute', planned: true },
  { key: '/app/tasks', label: '任务运维', icon: <SettingOutlined />, perm: 'audit:read' },
  { key: '/app/business', label: '业务元数据', icon: <TeamOutlined />, perm: 'metadata:read' },
  {
    key: '/app/governance',
    label: '协作流程',
    icon: <TeamOutlined />,
    perm: 'governance:read',
    children: [
      { key: '/app/governance/approvals', label: '审批流' },
      { key: '/app/governance/tickets', label: '工单' },
    ],
  },
  { key: '/app/admin', label: '系统管理', icon: <SettingOutlined />, planned: true },
];

/** 快捷键提示按平台渲染：Windows 上没有 ⌘ 键（taste-skill §14 copy self-audit）。 */
const IS_MAC = /mac|iphone|ipad/i.test(
  (navigator as { userAgentData?: { platform?: string } }).userAgentData?.platform ??
    navigator.platform ??
    navigator.userAgent,
);
const SEARCH_SHORTCUT = IS_MAC ? '⌘K' : 'Ctrl+K';

function visibleMenu(): MenuItem[] {
  return MENU.filter((item) => hasPerm(item.perm)).map((item) => ({
    ...item,
    children: item.children?.filter((c) => hasPerm(c.perm)),
  }));
}

/** ⌘K 全局搜索：输入直达 /app/catalog?q=（FE-00 §4）。 */
function GlobalSearch({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [term, setTerm] = useState('');
  const enabled = open && term.trim().length >= 2;

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: qk.catalog.search({ term }),
    queryFn: () => searchAssets({ term, limit: 8 }),
    enabled,
  });

  const items = useMemo(() => data?.items ?? data?.results ?? [], [data]);

  const go = () => {
    onClose();
    navigate(`/app/catalog?q=${encodeURIComponent(term)}`);
  };

  return (
    <Modal open={open} onCancel={onClose} footer={null} title="全局搜索" width={640}>
      <Input
        autoFocus
        size="large"
        prefix={<SearchOutlined />}
        placeholder="搜索表名 / 字段名，回车在资产目录中打开"
        value={term}
        onChange={(e) => setTerm(e.target.value)}
        onPressEnter={go}
      />
      <div style={{ marginTop: 12, minHeight: 120 }}>
        {!enabled ? (
          <Typography.Text type="secondary">输入至少 2 个字符开始搜索</Typography.Text>
        ) : isLoading ? (
          <LoadingSkeleton rows={3} />
        ) : isError ? (
          <ErrorState
            error={error}
            onRetry={() => {
              void refetch();
            }}
          />
        ) : items.length === 0 ? (
          <Typography.Text type="secondary">无匹配结果</Typography.Text>
        ) : (
          <List
            size="small"
            dataSource={items}
            rowKey={(item) => String(item.fqn ?? item.id ?? item.title ?? item.type ?? '')}
            renderItem={(item) => (
              <List.Item
                style={{ cursor: 'pointer' }}
                onClick={() => {
                  onClose();
                  // 统一走 FQN 跳转：按数字 id 拼 URL 会撞上 assets 接口的 404
                  navigate(
                    item.fqn
                      ? assetDetailLink(item as Record<string, unknown>)
                      : `/app/catalog?q=${encodeURIComponent(String(item.name ?? ''))}`,
                  );
                }}
              >
                <Space direction="vertical" size={0}>
                  <Typography.Text strong>{String(item.name ?? item.fqn ?? '-')}</Typography.Text>
                  <Typography.Text type="secondary" className="mono">
                    {String(item.fqn ?? '')}
                  </Typography.Text>
                </Space>
              </List.Item>
            )}
          />
        )}
      </div>
    </Modal>
  );
}

/** App Shell：Sider + Header + Content（FE-00 §4）。 */
export default function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { token } = antdTheme.useToken();
  const [collapsed, setCollapsed] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const username = useAuthStore((s) => s.username);
  const logout = useAuthStore((s) => s.logout);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const menuItems = useMemo(visibleMenu, []);
  const selectedKey =
    menuItems
      .flatMap((m) => [m.key, ...(m.children ?? []).map((c) => c.key)])
      .filter((k) => location.pathname.startsWith(k))
      .sort((a, b) => b.length - a.length)[0] ?? '/app/dashboard';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} width={200}>
        <div
          style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontWeight: 600,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
          }}
        >
          {collapsed ? 'MG' : '元数据治理平台'}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems.map((m) => ({
            key: m.key,
            icon: m.icon,
            label: m.planned ? (
              <Space size={6}>
                {m.label}
                <Tag style={{ marginInlineEnd: 0 }}>规划中</Tag>
              </Space>
            ) : (
              m.label
            ),
            children: m.children?.map((c) => ({ key: c.key, label: c.label })),
          }))}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: token.colorBgContainer,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '0 16px',
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <Input
            style={{ maxWidth: 360 }}
            placeholder={`搜索资产（${SEARCH_SHORTCUT}）`}
            prefix={<SearchOutlined />}
            readOnly
            onClick={() => setSearchOpen(true)}
          />
          <Dropdown
            menu={{
              items: [
                { key: 'who', label: username ? `当前用户：${username}` : '未登录（降级模式）' },
                { type: 'divider' },
                {
                  key: 'logout',
                  label: '退出登录',
                  onClick: () => {
                    logout();
                    navigate('/login');
                  },
                },
              ],
            }}
          >
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} />
              <span>{username ?? 'guest'}</span>
            </Space>
          </Dropdown>
        </Header>
        <Content className="page-content">
          {/* G3：页面级兜底，任一路内容崩溃时保留 Sider/Header 可用 */}
          <ErrorBoundary resetKey={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </Content>
      </Layout>
      <GlobalSearch open={searchOpen} onClose={() => setSearchOpen(false)} />
    </Layout>
  );
}
