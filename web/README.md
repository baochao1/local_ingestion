# 元数据治理平台 · Web 控制台

按 `doc/design/FE-00-frontend-overview.md`（总纲）与 `FE-01-frontend-detailed-design.md`（逐页规格）从零搭建的前端 SPA。

## 技术栈

React 18 + TypeScript + Vite · Ant Design v5 · React Router v6 · TanStack Query v5 · Zustand · Axios · dayjs

## 启动

```bash
npm install
npm run dev      # http://localhost:5173
```

后端 REST 基座为 `/api/v1`，dev 已配置代理到 `http://localhost:8090`（见 `vite.config.ts`）。
若后端端口不同：`VITE_PROXY_TARGET=http://localhost:8000 npm run dev`。
接口基址可用 `VITE_API_BASE` 覆盖（默认 `/api/v1`）。

其他命令：`npm run typecheck`、`npm run build`。

## 目录

```
src/
├─ api/         请求层（axios 实例 + 各模块端点 + queryKey 工厂）
├─ components/  通用组件（FE-00 §5.2）
├─ layouts/     AppShell（Sider / Header / ⌘K 全局搜索）
├─ pages/       各模块页面
├─ store/       Zustand（认证）
├─ types/       后端响应类型
└─ router.tsx   路由地图（FE-00 §3）
```

## 落地范围（FE-01 §16）

- **第一批（已实现，可联调）**：登录(降级) / 概览 / 数据源 / 资产目录 / 数据变更 / 任务运维 / 平台健康 / 协作流程（审批+工单）
- **第二~四批**：画像质量、分类分级、采样、血缘、权限分析、业务元数据、系统管理 —— 已以 `DegradedPage` 降级占位就位，待后端接口补齐后填充

## 注意事项

- **字段命名不统一**：`datasources / search / assets / tasks / audit / system / partitions` 后端返回 **camelCase**；`changes / governance / business / lineage / catalog` 返回 **snake_case**。已在 `src/types/index.ts` 标注。
- **分页**：列表统一走 `<DataTable>` 的 keyset 游标；但 `/api/v1/search` 后端仅支持 limit/offset，故资产检索按 offset 翻页并遵守 1000 条上限。
- **认证**：MOD-11 未上线，登录页提供「跳过登录直接进入」降级入口。
