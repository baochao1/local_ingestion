import { Navigate, Route, Routes } from 'react-router-dom';
import AppShell from '@/layouts/AppShell';
import ErrorBoundary from '@/components/ErrorBoundary';
import LoginPage from '@/pages/auth/LoginPage';
import DashboardPage from '@/pages/dashboard/DashboardPage';
import DataSourceListPage from '@/pages/datasources/DataSourceListPage';
import DataSourceDetailPage from '@/pages/datasources/DataSourceDetailPage';
import CatalogSearchPage from '@/pages/catalog/CatalogSearchPage';
import CatalogBrowsePage from '@/pages/catalog/CatalogBrowsePage';
import TableDetailPage from '@/pages/catalog/TableDetailPage';
import ColumnDetailPage from '@/pages/catalog/ColumnDetailPage';
import ChangeListPage from '@/pages/changes/ChangeListPage';
import ChangeDetailPage from '@/pages/changes/ChangeDetailPage';
import ChangeStatisticsPage from '@/pages/changes/ChangeStatisticsPage';
import EntityHistoryPage from '@/pages/changes/EntityHistoryPage';
import SubscriptionPage from '@/pages/changes/SubscriptionPage';
import TaskListPage from '@/pages/tasks/TaskListPage';
import TaskDetailPage from '@/pages/tasks/TaskDetailPage';
import AuditLogPage from '@/pages/tasks/AuditLogPage';
import PartitionStatusPage from '@/pages/tasks/PartitionStatusPage';
import SystemStatusPage from '@/pages/tasks/SystemStatusPage';
import ApprovalsPage from '@/pages/governance/ApprovalsPage';
import TicketsPage from '@/pages/governance/TicketsPage';
import BusinessTermsPage from '@/pages/business/BusinessTermsPage';
import ClassificationOverviewPage from '@/pages/classification/ClassificationOverviewPage';
import ClassificationTagsPage from '@/pages/classification/ClassificationTagsPage';
import ClassificationRulesPage from '@/pages/classification/ClassificationRulesPage';
import SensitiveAssetsPage from '@/pages/classification/SensitiveAssetsPage';
import DegradedPage from '@/pages/placeholders/DegradedPage';

/**
 * Route map — FE-00 §3. Modules whose backend APIs are not implemented yet
 * (MOD-03/04/05/07/08/11) render <DegradedPage> per FE-01 §16 ("每批前端应先以
 * 降级/占位形态就位").
 */
export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* 外层兜底：AppShell 自身异常时不至于整站白屏（G3） */}
      <Route
        path="/app"
        element={
          <ErrorBoundary>
            <AppShell />
          </ErrorBoundary>
        }
      >
        <Route index element={<Navigate to="/app/dashboard" replace />} />

        {/* 第一批：API 已落地 */}
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="datasources" element={<DataSourceListPage />} />
        <Route path="datasources/:id" element={<DataSourceDetailPage />} />
        <Route path="catalog" element={<CatalogSearchPage />} />
        {/* 层级浏览：数据源 → 库 → Schema → 表 → 字段（MOD-09 §182-183） */}
        <Route path="catalog/browse" element={<CatalogBrowsePage />} />
        {/* 资产详情统一按 FQN 定位（?fqn=），不用数字 id：后端 /assets 只认 FQN */}
        <Route path="catalog/tables" element={<TableDetailPage />} />
        <Route path="catalog/columns" element={<ColumnDetailPage />} />
        <Route path="changes" element={<ChangeListPage />} />
        <Route path="changes/statistics" element={<ChangeStatisticsPage />} />
        <Route path="changes/entities/:type/:fqn/history" element={<EntityHistoryPage />} />
        <Route path="changes/:id" element={<ChangeDetailPage />} />
        <Route path="subscriptions" element={<SubscriptionPage />} />
        <Route path="tasks" element={<TaskListPage />} />
        <Route path="tasks/audit" element={<AuditLogPage />} />
        <Route path="tasks/partitions" element={<PartitionStatusPage />} />
        <Route path="tasks/:id" element={<TaskDetailPage />} />
        <Route path="system" element={<SystemStatusPage />} />
        <Route path="governance/approvals" element={<ApprovalsPage />} />
        <Route path="governance/tickets" element={<TicketsPage />} />

        {/* 第二批：MOD-03/04/05 */}
        <Route
          path="profile/tables/:id"
          element={<DegradedPage module="MOD-04" title="表画像" />}
        />
        <Route
          path="profile/quality/rules"
          element={<DegradedPage module="MOD-04" title="质量规则" />}
        />
        <Route
          path="profile/quality/results"
          element={<DegradedPage module="MOD-04" title="校验结果 / 评分" />}
        />
        {/* 第三批：MOD-05 分类分级——后端查询接口已落地，不再降级 */}
        <Route path="classification" element={<ClassificationOverviewPage />} />
        <Route path="classification/tags" element={<ClassificationTagsPage />} />
        <Route path="classification/rules" element={<ClassificationRulesPage />} />
        <Route
          path="classification/sensitive-assets"
          element={<SensitiveAssetsPage />}
        />
        <Route
          path="sampling/preview/:id"
          element={<DegradedPage module="MOD-03" title="样本行预览" />}
        />
        <Route
          path="sampling/columns/:id/values"
          element={<DegradedPage module="MOD-03" title="字段样本值" />}
        />

        {/* 第三批：MOD-07/08 + 业务元数据 */}
        <Route path="lineage/tables/:id" element={<DegradedPage module="MOD-07" title="表血缘" />} />
        <Route
          path="lineage/columns/:id"
          element={<DegradedPage module="MOD-07" title="字段级血缘" />}
        />
        <Route
          path="permissions/accounts"
          element={<DegradedPage module="MOD-08" title="账号列表" />}
        />
        <Route
          path="permissions/matrix"
          element={<DegradedPage module="MOD-08" title="权限矩阵" />}
        />
        <Route path="permissions/risks" element={<DegradedPage module="MOD-08" title="风险项" />} />
        <Route
          path="permissions/changes"
          element={<DegradedPage module="MOD-08" title="权限变更" />}
        />
        <Route path="business/terms" element={<BusinessTermsPage />} />
        <Route
          path="business/entities"
          element={<DegradedPage module="MOD-09" title="实体业务信息" />}
        />

        {/* 第四批：MOD-11 */}
        <Route path="admin/users" element={<DegradedPage module="MOD-11" title="用户" />} />
        <Route path="admin/roles" element={<DegradedPage module="MOD-11" title="角色与权限" />} />
        <Route
          path="admin/data-policies"
          element={<DegradedPage module="MOD-11" title="数据权限策略" />}
        />
        <Route
          path="admin/account-mappings"
          element={<DegradedPage module="MOD-11" title="业务账号关联" />}
        />

        {/* 模块索引路由：无独立首页的模块指向降级占位，供 Sider 菜单直达 */}
        <Route path="profile" element={<DegradedPage module="MOD-04" title="画像与质量" />} />
        <Route path="lineage" element={<DegradedPage module="MOD-07" title="血缘分析" />} />
        <Route path="permissions" element={<DegradedPage module="MOD-08" title="权限分析" />} />
        <Route path="sampling" element={<DegradedPage module="MOD-03" title="采样" />} />
        <Route path="business" element={<Navigate to="/app/business/terms" replace />} />
        <Route path="admin" element={<DegradedPage module="MOD-11" title="系统管理" />} />
        <Route path="governance" element={<Navigate to="/app/governance/approvals" replace />} />
      </Route>

      <Route path="/" element={<Navigate to="/app/dashboard" replace />} />
      <Route path="*" element={<Navigate to="/app/dashboard" replace />} />
    </Routes>
  );
}
