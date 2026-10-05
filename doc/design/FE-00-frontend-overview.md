# 元数据治理平台 · 前端概要设计（Frontend High-Level Design）

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 编写日期 | 2026-10-02 |
| 前置文档 | `doc/design/00-modules-overview.md`、`doc/api/API.md`、`doc/design/MOD-01`~`MOD-11` |
| 文档作用 | 定义前端的产品定位、信息架构、技术栈、导航结构、设计系统基线、API 层约定，是 `FE-01-frontend-detailed-design.md` 的总纲 |

---

## 1. 产品定位与前端角色

本平台是**企业级元数据治理平台**（由现有「本地元数据摄取模块」升级而来），后端已提供完整 REST API（`doc/api/API.md`，基座 `/api/v1`）。本阶段目标是构建**面向多角色用户的 Web 控制台**，作为用户唯一直接触达面（对应 MOD-09 定义）。

> 关键事实：当前仓库**无前端代码**（需求文档 §2.3 明确「前端 零」），本期须从零搭建。后端 API 已部分落地（`API.md` 快照于 2026-10-02），但大量治理能力（画像、分级、血缘、权限分析、任务运维等）在 MOD-xx 中还处于「设计/规划」阶段。前端应**按目标产品形态设计**，并据此与后端对齐接口（见 §8 差距说明）。

### 1.1 目标用户与对应前端视图

| 角色 | 主用模块 | 前端重点 |
|---|---|---|
| 数据平台 / DBA | MOD-01、MOD-02、MOD-06、MOD-10 | 数据源管理、扫描/任务运维、变更追踪 |
| 数据治理 / 合规 | MOD-05、MOD-08、MOD-09 | 分类分级、敏感资产清单、权限风险、业务术语 |
| 数据分析 / 业务 | MOD-09、MOD-04、MOD-07 | 资产检索、画像质量、血缘追溯 |
| 安全审计 | MOD-08、MOD-10、MOD-11 | 权限矩阵、风险项、审计日志、账号关联 |

### 1.2 设计原则

1. **检索优先**：千万级字段元数据下，搜索/筛选是第一入口（MOD-09 核心）。
2. **分层加载**：列表只返主信息（表名/分级），详情按需并发聚合（MOD-09 §4.2）。
3. **游标分页**：所有列表强制 keyset 游标，禁深 OFFSET（ADR-5）；前端需适配。
4. **降级可视**：血缘/权限/数据权限等未上线模块，对应区块显示「不可用」而非报错（MOD-09 §6）。
5. **敏感操作确认**：采样、导出、凭据变更、删除等需二次确认 + 审计提示。
6. **只读平台**：前端不提供任何写业务库的能力，仅管理元数据平台的配置与任务。

---

## 2. 技术栈建议

> 仅建议，code agent 可据团队规范替换；但接口契约、组件划分、状态处理需遵循本 spec。

| 层 | 选型 | 理由 |
|---|---|---|
| 框架 | **React 18 + TypeScript + Vite** | 生态成熟、类型安全、构建快 |
| UI 组件库 | **Ant Design v5** | 企业控制台首选，表单/表格/抽屉/标签齐全，中文友好 |
| 路由 | **React Router v6** | 模块化的嵌套路由，适配本 IA |
| 服务端状态 | **TanStack Query (React Query) v5** | 缓存、游标分页、重试、并发取数天然契合 MOD-09 详情聚合 |
| 客户端状态 | **Zustand** | 轻量，存放登录态、当前数据源、过滤器 |
| 图谱/血缘 | **@xyflow/react (React Flow)** | 表级/字段级血缘有向图、环检测展示 |
| 可视化 | **@ant-design/charts** 或 **ECharts** | 概览大盘、质量趋势、变更排行 |
| 请求层 | **Axios + 拦截器** | 统一 baseURL、401 刷新、错误归一 |
| 表单 | **React Hook Form + Zod** | 数据源注册、规则配置等强校验场景 |
| 国际化 | 本期仅中文，预留 i18n 结构 | — |

---

## 3. 信息架构（IA）与路由地图

```
/login                                 登录
/app
 ├─ /dashboard                         概览工作台（MOD-09 overview + MOD-10 health）
 ├─ /datasources                       数据源管理（MOD-01）
 │   ├─ /datasources                   列表
 │   └─ /datasources/:id               详情（概览/健康/策略/凭据/扫描）
 ├─ /catalog                           资产目录（MOD-09）
 │   ├─ /catalog?q=...                 检索 + 浏览（表/字段）
 │   ├─ /catalog/tables/:id            表详情聚合视图
 │   └─ /catalog/columns/:id           字段详情聚合视图
 ├─ /changes                           数据变更（MOD-06）
 │   ├─ /changes                       变更列表
 │   ├─ /changes/:id                   变更详情（before/after）
 │   ├─ /changes/statistics            变更统计
 │   ├─ /changes/entities/:type/:fqn/history  单实体历史
 │   └─ /subscriptions                 订阅管理
 ├─ /profile                           画像与质量（MOD-04）
 │   ├─ /profile/tables/:id            表画像 + 质量
 │   ├─ /profile/quality/rules         质量规则
 │   └─ /profile/quality/results       校验结果/评分
 ├─ /classification                    分类分级（MOD-05）
 │   ├─ /classification                概览/覆盖率
 │   ├─ /classification/tags           分级标准
 │   ├─ /classification/rules          识别规则
 │   └─ /classification/sensitive-assets  敏感资产清单
 ├─ /lineage                           血缘分析（MOD-07）
 │   ├─ /lineage/tables/:id            表血缘（上下游/影响面）
 │   └─ /lineage/columns/:id           字段级血缘
 ├─ /permissions                       权限分析（MOD-08）
 │   ├─ /permissions/accounts          账号列表
 │   ├─ /permissions/matrix            权限矩阵
 │   ├─ /permissions/risks             风险项
 │   └─ /permissions/changes           权限变更
 ├─ /sampling                          采样（MOD-03）
 │   ├─ /sampling/preview/:id          样本行预览（脱敏）
 │   └─ /sampling/columns/:id/values   字段样本值
 ├─ /tasks                             任务与运维（MOD-10，列表/详情/取消/重试/提交已落地）
 │   ├─ /tasks                         任务列表【已实现】
 │   ├─ /tasks/:id                     任务详情/日志【已实现】
 │   ├─ /tasks/audit                   审计日志【已实现】(GET /api/v1/audit-logs)
 │   └─ /tasks/partitions              分区状态【已实现】(GET /api/v1/tasks/partitions)
 ├─ /system                            平台健康与指标（MOD-10，已实现）
 │   ├─ /api/v1/system/health          健康
 │   └─ /api/v1/system/metrics         指标
 ├─ /business                          业务元数据（MOD-09 FR-14）
 │   ├─ /business/terms                术语表
 │   └─ /business/entities?...         业务描述/别名/标签
 ├─ /governance                        协作流程（MOD-12）
 │   ├─ /governance/approvals          审批流
 │   └─ /governance/tickets            工单
 └─ /admin                             系统管理（MOD-11，P3）
     ├─ /admin/users                   用户
     ├─ /admin/roles                   角色与权限
     ├─ /admin/data-policies           数据权限策略
     └─ /admin/account-mappings        业务账号关联
```

> 业务元数据（术语/标签）既是独立菜单，也可从资产详情抽屉直接维护，二者复用同一组接口。

---

## 4. 全局布局（App Shell）

```
┌───────────────────────────────────────────────────────────────┐
│ Header: Logo | 全局搜索框(⌘K) | 当前数据源上下文 | 用户/角色下拉 │
├──────────┬────────────────────────────────────────────────────┤
│ Sider    │  Content（路由出口，每个页面含 PageHeader + 内容区） │
│ 导航菜单 │                                                      │
│ - 概览   │                                                      │
│ - 数据源 │                                                      │
│ - 资产目录│                                                      │
│ - 数据变更│                                                      │
│ - 画像质量│                                                      │
│ - 分类分级│                                                      │
│ - 血缘   │                                                      │
│ - 权限分析│                                                      │
│ - 采样   │                                                      │
│ - 任务运维│                                                      │
│ - 业务元数据│                                                    │
│ - 协作流程│                                                      │
│ - 系统管理│                                                      │
└──────────┴────────────────────────────────────────────────────┘
```

- **Sider**：可折叠；菜单项随登录用户权限（`MOD-11` 功能权限码）动态显隐。
- **Header 全局搜索**：聚焦即弹出命令面板（⌘K），输入关键字直达资产检索（`/catalog?q=`），结果按「表/字段」分组。
- **PageHeader**：标题 + 面包屑 + 右侧操作区（如「立即扫描」「导出」「新建」）。
- **响应式**：默认桌面端后台；Sider 在窄屏抽屉化；核心列表/详情支持折叠。

---

## 5. 设计系统基线（Design Tokens）

统一视觉语言，便于 code agent 直接落地。建议基于 Ant Design 主题定制：

| Token | 取值建议 | 用途 |
|---|---|---|
| 主色 primary | `#2f54eb`（蓝） | 主操作、链接、选中 |
| 成功 success | `#52c41a` | 健康/通过 |
| 警告 warning | `#faad14` | 部分完成/低置信 |
| 危险 error | `#ff4d4f` | 破坏性变更/超管风险/删除 |
| 敏感高亮 sensitive | `#cf1322`（深红底） | 高敏资产（L3/L4）标记 |
| 圆角 radius | `6px` | 卡片/按钮 |
| 间距 spacing | 基于 8px 栅格 | 卡片间距 16/24 |
| 字体 | 系统字体栈 + `14px` 正文 | — |

### 5.1 通用等级/严重度色板（贯穿全站）

| 语义 | 色 | 使用点 |
|---|---|---|
| 分级 L1/L2/L3/L4 | 灰/蓝/橙/红 | 资产标签、敏感资产清单 |
| 变更 severity: descriptive/structural/breaking | 灰/橙/红 | 变更列表、统计 |
| 任务状态 pending/running/success/failed/cancelled/timeout | 灰/蓝/绿/红/橙/紫 | 任务列表 |
| 权限风险 高/中/低 | 红/橙/灰 | 风险项 |

### 5.2 通用组件库（须封装，复用于各页）

| 组件 | 说明 | 关键 props |
|---|---|---|
| `<PageHeader>` | 标题+面包屑+操作区 | `title, breadcrumb, extra` |
| `<DataTable>` | 封装 keyset 游标分页的表格 | `columns, queryKey, fetcher, cursorKey` |
| `<FilterBar>` | 行内筛选条件组 | `fields, onChange` |
| `<GradeTag>` | 分级标签 | `level` (1-4) |
| `<SeverityTag>` | 变更严重度标签 | `severity` |
| `<StatusTag>` | 通用状态标签 | `status, mapping` |
| `<ConfirmDanger>` | 危险操作二次确认 | `title, onConfirm` |
| `<DetailDrawer>` | 右侧抽屉详情 | `open, width, sections` |
| `<EmptyState>` / `<ErrorState>` / `<LoadingSkeleton>` | 三态 | — |
| `<JsonView>` | 只读 JSON 展示 | `value` |
| `<LineageGraph>` | 血缘有向图（React Flow 封装） | `nodes, edges, direction` |
| `<SuspenseSection>` | 详情页可降级区块（某模块不可用时显示「不可用」） | `available, fallback` |

---

## 6. API 层约定（前端必须遵守）

后端基座 `/api/v1`，当前未启用鉴权（`API.md` 顶部声明）。前端请求层须按以下契约封装：

### 6.1 请求封装

- `baseURL` 可配置（`.env`：`VITE_API_BASE=/api/v1`）。
- `Authorization: Bearer <token>`，从 Zustand 读取；401 触发刷新（`MOD-11` `/auth/refresh`）或跳登录。
- 统一错误归一：`{ code, message, detail }`；`422` 用于字段校验错误，映射到表单。

### 6.2 列表分页：keyset 游标

- **请求**：`?cursor=<last_key>&limit=<n>`（设计强制，ADR-5）。
- **响应**包络（前端自定义约定，需与后端对齐）：
  ```json
  { "items": [...], "next_cursor": "string|null", "total": "number|null" }
  ```
- `DataTable` 仅维护 `cursor` 栈，上滑/「加载更多」翻页；**禁止 OFFSET**。
- 模糊搜索类（如 `/catalog/search`）无稳定游标，后端限制上限（1000/50 页），前端超限提示「请收窄条件」（MOD-09 §4.1）。

### 6.3 详情聚合：并发取数

表/字段详情聚合 6+ 模块数据，前端用 React Query **并行**发起多个 `useQuery`（各模块独立），单模块失败不阻断其余（配合 `<SuspenseSection>`）。

### 6.4 任务化操作

所有耗时动作（扫描、采样、画像、分级、血缘解析、权限采集）经 `MOD-10` 异步任务，**前端提交后立即返回 `scan_run_id`/任务 ID**，跳转/提示到 `/tasks/:id` 查看进度，禁止同步等待。

### 6.5 审计敏感操作

采样预览、导出、凭据变更、删除、人工标注等接口调用前，前端弹确认框并展示「此操作将被审计」提示（MOD-10 §4.9）。

---

## 7. 权限与导航可见性

- 登录后从 `MOD-11` 获取当前用户权限码集合（`perm_code` 列表，见 MOD-11 §4.2）。
- Sider 菜单按权限码显隐：`datasource:read`、`metadata:read`、`change:read`、`profile:read`、`classification:read`、`lineage:read`、`permission:read`、`sample:execute`、`audit:read`、`export:execute` 等。
- 无 `MOD-11`（P3 未上线）时：默认全菜单可见（降级），不阻断使用。

---

## 8. 当前 API 与设计目标差距（前端须知，避免返工）

`API.md`（当前已实现）与 MOD-xx（目标）存在差异，前端设计以**目标形态**为准，但需知道：

| 能力 | 当前 API（已实现） | 目标 API（MOD-xx） | 前端处理 |
|---|---|---|---|
| 资产检索 | `/api/v1/search`（term/type/datasourceId/tags/owner/sensitiveOnly/**gradeMin**/limit/offset） | `/api/v1/catalog/search`、`/catalog/tables`、`/catalog/columns` | 按目标设计；当前用 `/search` 兜底；**分级过滤（gradeMin）已实现** |
| 资产详情 | `/api/v1/assets/{fqn}` | `/catalog/tables/{id}`、`/catalog/columns/{id}`（聚合） | 详请聚合走目标；当前用 `/assets` |
| 概览 | `/api/v1/catalog/overview` | 同 | 一致 |
| 变更 | `/api/v1/changes*`、`/changes/statistics`、`/entities/.../history` | 增加 `/snapshots/compare`、`/subscriptions` | 列表/统计/历史可用；订阅/对比待补 |
| 血缘 | 仅 `/lineage/tables/{fqn}/impact` | 增加 upstream/downstream/columns/parse/import | 仅影响面可用；其余降级 |
| 平台健康/指标 | `/api/v1/system/health`、`/api/v1/system/metrics`（**已实现，MOD-10**） | 同 | 一致；健康条/运维页可直接联调 |
| 协作流程（审批+工单） | `/api/v1/governance/*`（**已实现，MOD-12**） | 同 | 一致；详见 §3 路由与 FE-01 §15 |
| 画像/质量/分级/权限/采样 | **API.md 未含** | MOD-04/05/07/08/03 全套 REST | 设计完整，待后端补齐 |
| 任务运维 REST | `/api/v1/tasks*` 列表/详情/取消/重试/提交【已实现 MOD-10】；`/api/v1/audit-logs`【已实现】；`/api/v1/tasks/partitions`【已实现，运维视角只读】 | 暴露 `/api/v1/tasks*` REST（MOD-10） | 列表/详情/取消/重试/提交/审计/分区均可用 |
| 认证 | 无 | `MOD-11` `/auth/login` 等 | 前端预留登录页与 guard，当前可跳过 |

> 结论：前端按目标全量设计；与后端联调时以 `API.md` 已落地部分为首批，未落地部分以「降级/占位」呈现，待后端补齐。

---

## 9. 交付物与验收（前端侧）

1. 可运行 SPA，登录后可进入各模块。
2. 全局搜索 + 资产目录检索/筛选/游标分页可用。
3. 数据源管理全流程（注册含连通性测试、启停、凭据轮换、健康）。
4. 变更列表/详情/统计/历史/确认闭环可用。
5. 表/字段详情聚合视图（降级区块正确）。
6. 画像质量、分类分级、血缘、权限分析、采样、任务运维各页可呈现对应数据。
7. 敏感操作有二次确认与审计提示。
8. 列表全量 keyset 游标，无深 OFFSET。

---

## 10. 与详细设计的关系

`FE-01-frontend-detailed-design.md` 按模块逐页给出：**路由、依赖接口（契约）、页面布局（区域划分）、核心组件与字段、加载/空/错/降级四态、关键交互**。Code agent 应依据详细设计直接生成组件代码，并复用 §5.2 通用组件。
