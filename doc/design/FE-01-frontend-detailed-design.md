# 元数据治理平台 · 前端详细设计（Frontend Detailed Design）

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 编写日期 | 2026-10-02 |
| 前置文档 | `FE-00-frontend-overview.md`、`doc/api/API.md`、`doc/design/MOD-01`~`MOD-11` |
| 文档作用 | 逐模块、逐页面的组件级规格，含路由、接口契约、布局、字段、四态、交互，供 code agent 直接生成 UI |

> 标注【目标接口】的端点来自 MOD-xx 设计文档，当前 `API.md` 尚未实现，前端须以「降级/占位」呈现，待后端补齐。已实现端点以 `API.md` 为准。

---

## 0. 通用约定（所有页面复用）

- **四态**：每个数据区必须实现 `LoadingSkeleton` / `EmptyState` / `ErrorState` / `Data`。错误区提供「重试」。
- **降级区**：详情聚合页中来自 MOD-07/08/11 的区块，用 `<SuspenseSection available={bool}>` 包裹，不可用时显示「该能力暂不可用」，其余正常。
- **列表**：统一用 `<DataTable>`（封装 keyset 游标：`cursor` + `limit`，响应 `next_cursor`）。
- **危险操作**：删除、凭据变更、导出、采样、取消任务 → `<ConfirmDanger>` + 审计提示。
- **任务型操作**：提交后拿到 `run_id`/`task_id`，用 `<TaskProgressLink id>` 引导至 `/tasks/:id`。
- **时间格式**：统一 `YYYY-MM-DD HH:mm`；相对时间（如「3 分钟前」）可选。
- **FQN**：完全限定名（如 `ds.db.schema.table`），全局作为资产唯一标识展示与跳转。

---

## 1. 登录（Auth）

**路由** `/login`　**权限码** 无（公开）

**依赖接口**
- `POST /api/v1/auth/login`【目标接口】→ `{ username, password }` → `{ access_token, refresh_token }`
- `POST /api/v1/auth/refresh`【目标接口】→ `{ refresh_token }` → `{ access_token }`
- 降级：当前无认证，登录页可「跳过登录直接进入」(dev only)。

**布局**
```
┌──────────────────────────────┐
│   Logo  元数据治理平台          │
│                               │
│   用户名 [__________]          │
│   密码   [__________]          │
│              [ 登录 ]          │
│   提示：平台账号由管理员分配     │
└──────────────────────────────┘
```
- 居中卡片，左右可加品牌/标语区。
- 登录成功：存 token（Zustand + localStorage），拉取权限码，跳 `/dashboard`。
- 错误：顶部 `Alert` 显示后端 `message`（如「用户名或密码错误」）。
- 失败 401：保持页面，提示重试。

---

## 2. 概览工作台（Dashboard）

**路由** `/dashboard`　**权限码** `metadata:read`

**依赖接口**
- `GET /api/v1/catalog/overview?trend_days=30` → 资产大盘
  - 出参（目标形状）：`{ total_tables, total_columns, total_datasources, grade_distribution: {L1,L2,L3,L4}, sensitive_ratio, quality_distribution, change_trend: [{date, count}], top_changing_tables: [{fqn, change_count}] }`
- `GET /api/v1/system/health`（已实现 MOD-10）→ `{ status, timestamp, components: [{component, status, message}] }`
- `GET /api/v1/changes/statistics?since&until` → `{ total, by_severity: {descriptive, structural, breaking}, by_datasource }`

**布局**
```
PageHeader: 概览
├─ 指标卡行 (4-6 卡片): 数据源数 | 表数 | 字段数 | 敏感资产占比 | 近30天变更数 | 平台健康
├─ 左列
│   ├─ 分级分布（饼/环形图）L1-L4 + 敏感占比
│   └─ 质量分布（柱状/堆叠）
├─ 右列
│   ├─ 变更趋势（折线/面积图，按日）
│   └─ 不稳定表 Top10（列表，点击跳 /catalog/tables/:id）
└─ 平台健康条: 按 `components[]` 动态渲染各组件状态点（DB / API 等）
```
- 指标卡点击可跳对应模块（如「变更数」→ `/changes`）。
- 图表用 `@ant-design/charts`；降级：health 不可用时状态条全灰 + 「健康信息暂不可用」。

---

## 3. 数据源管理（MOD-01）

**路由** `/datasources`、`/datasources/:id`　**权限码** `datasource:read`（写需 `datasource:write`）

**依赖接口**
- `GET /api/v1/datasources?enabled&environment&group&type` + 游标 → 列表（`API.md`）
- `POST /api/v1/datasources` 注册（含 `code,name,dsType,host,port,environment,groupName,ownerBusiness,ownerTechnical,enabled,scanEnabled,samplingEnabled,username,password,scanConfig,samplingConfig,allowWrite`）
- `POST /api/v1/datasources/test` 连通性测试（不保存）
- `GET /api/v1/datasources/{id}` 详情（不含凭据）
- `PUT /api/v1/datasources/{id}` 更新
- `DELETE /api/v1/datasources/{id}` 软删除
- `POST .../enable` `/disable` 启停
- `POST .../credentials`（username,password）新增版本；`POST .../credentials/{ver}/activate` 切换
- `GET .../health` → `{ last_scan_at, last_scan_status, last_error, connectivity }`
- `POST .../scan` 触发扫描（任务）；`POST .../classify` 触发分级（任务）

### 3.1 列表页 `/datasources`
```
PageHeader: 数据源 [+ 新建数据源]
FilterBar: 环境(select) | 分组(select) | 类型(select) | 状态(启停)
DataTable 列: 名称 | 编码 | 类型 | 环境 | 分组 | 负责人 | 扫描开关 | 采样开关 | 健康(StatusTag) | 操作(详情/启停/删除)
```
- 行操作：启用/禁用、删除（危险确认）、「立即扫描」「重跑分级」（任务型）。

### 3.2 新建/编辑抽屉 `DataSourceForm`
字段分组：
- **连接**：dsType(select: MySQL/PostgreSQL/Snowflake/SQLServer/BigQuery)、host、port、username、password
- **基础**：code、name、environment(select: prod/test/dev)、groupName、ownerBusiness、ownerTechnical
- **策略**：scanEnabled(switch)、samplingEnabled(switch)、scanConfig(JSON/表单：库/schema 黑白名单、调度 cron、并发上限)、samplingConfig(JSON/表单：采样率、上限行数、超时、黑名单列)
- 底部：「测试连接」(调 `/test`) → 显示结果（成功/失败原因/只读校验结论）；「保存」(调 POST/PUT)。
- 保存前若具备写权限：依 `allowWrite` 策略显示风险提示（FR-1.5）。

### 3.3 详情页 `/datasources/:id`
```
PageHeader: {name} [编辑] [启停] [立即扫描] [重跑分级] [删除]
Tabs:
 ├─ 概览: 基础信息 + 能力位(supports_sampling/profiling/lineage)
 ├─ 健康: last_scan_at/status/last_error + 连通性趋势(StatusTag)
 ├─ 采集策略: scanConfig/samplingConfig 只读展示(JsonView)
 ├─ 凭据: 版本列表(版本号/激活态/创建时间) [+ 新增版本] [激活] (datasource:write)
 └─ 扫描任务: 最近 scan_run 列表(跳 /tasks)
```
- 凭据版本列表：激活态高亮；新增版本弹表单（username/password）→ 校验连通后写入。
- 删除：`<ConfirmDanger>` 提示「将异步清理其下全部元数据，不可恢复」。

---

## 4. 资产目录（MOD-09）

**路由** `/catalog`、`/catalog/tables/:id`、`/catalog/columns/:id`　**权限码** `metadata:read`

**依赖接口**
- 检索 `GET /api/v1/search?term&type(table|column)&datasourceId&tags&owner&sensitiveOnly&gradeMin(分级≥N,1-9)&limit&offset`（当前；`gradeMin` 已落地）
- 目标：`GET /api/v1/catalog/search`、`/catalog/tables`、`/catalog/columns`（多维筛选 + keyset）
- 详情 `GET /api/v1/assets/{fqn}`（当前）；目标 `/catalog/tables/{id}`、`/catalog/columns/{id}`（聚合）
- 预览 `GET /api/v1/catalog/tables/{id}/preview`【目标接口】（脱敏样本，审计）
- 业务元数据 `GET/PUT /api/v1/business/entities/{type}/{entity_id}`（`entity_id` 为平台整数主键，非 FQN）、`POST .../tags`、`GET /api/v1/business/terms`

### 4.1 检索/浏览页 `/catalog`
```
PageHeader: 资产目录 (全局搜索框复用)
FilterBar: 关键字 | 类型(表/字段) | 数据源 | 分级(最低 L1-L4 → 映射 gradeMin) | 标签 | 仅敏感 | 负责人
结果区:
 ├─ 表结果 DataTable: 表名(FQN) | 库/Schema | 数据源 | 分级(GradeTag) | 字段数 | 负责人 | 操作(详情)
 └─ 字段结果 DataTable: 字段名 | 所属表(FQN) | 类型 | 分级 | 操作(字段详情)
```
- 关键字支持表名/字段名模糊；多选分级/标签，其中分级多选映射为 `gradeMin` 参数（取所选最低等级为阈值）。
- 模糊搜索超限（>1000）→ 顶部提示「结果过多，请收窄条件」。
- 行点击 → 表/字段详情。

### 4.2 表详情 `/catalog/tables/:id`（聚合视图，核心页）
```
PageHeader: {fqn} [+ 业务描述] [预览样本] [订阅变更]
概览卡: 数据源 | 库/Schema | 类型 | 表级分级(GradeTag) | 字段数 | 行数 | profiled_at
Tabs:
 ├─ 结构(字段列表): DataTable 列=字段名|类型|可空|默认|分级(GradeTag)|标签|操作(字段详情)
 ├─ 画像(MOD-04, 降级区): 字段统计概览 + 质量评分 + [查看趋势]
 ├─ 质量(MOD-04, 降级区): 质量规则通过率 + 评分 + [报告导出]
 ├─ 分级标签(MOD-05): security 标签列表(名称/来源/置信度) + [人工标注]
 ├─ 业务(MOD-09 FR-14): 别名/业务描述/业务域/业务负责人/术语 + [编辑]
 ├─ 变更(MOD-06): 近期 change_event 列表(跳变更详情)
 ├─ 血缘(MOD-07, 降级区): 一度上下游缩略 + [查看完整血缘]
 └─ 授权(MOD-08, 降级区): 该表授权情况(账号×权限)
```
- 每个 Tab 区块相互独立 `useQuery` 并发；降级区块显示「暂不可用」。
- 「预览样本」→ 弹 `RowSampleDrawer`（调 preview，审计，脱敏展示）。
- 「业务」编辑 → 表单(alias, business_desc, domain, owner_business, term_codes[], tags{}) → PUT。

### 4.3 字段详情 `/catalog/columns/:id`
```
PageHeader: {table.fqn}.{column}
概览: 类型 | 可空 | 默认 | 分级(GradeTag) | security标签
Tabs:
 ├─ 统计(MOD-04): null_count/null_ratio/distinct_count/min/max/mean/stddev/top_values
 ├─ 样本值(MOD-03): distinct 取值样例(脱敏) [查看全部]
 ├─ 分级: 标签 + 置信度 + [人工标注/反馈误报]
 └─ 字段血缘(MOD-07): 上游字段 → 本字段 → 下游字段 (LineageGraph 横向)
```

---

## 5. 数据变更（MOD-06）

**路由** `/changes`、`/changes/:id`、`/changes/statistics`、`/changes/entities/:type/:fqn/history`、`/subscriptions`　**权限码** `change:read`（确认需 `change:ack`）

**依赖接口**
- `GET /api/v1/changes?severity&datasource_id&entity_type&entity_fqn&ack_status&limit&offset`
- `GET /api/v1/changes/{id}` → before/after 结构
- `POST /api/v1/changes/{id}/ack` → `{ actor, action }`（action: processed/misreport/ignore）
- `GET /api/v1/changes/statistics?since&until`
- `GET /api/v1/changes/entities/{type}/{fqn}/history`
- 【目标接口】`POST /api/v1/snapshots/compare`、`/subscriptions`(GET/POST)、`/subscriptions/{id}/mute`

### 5.1 变更列表 `/changes`
```
PageHeader: 数据变更 [统计] [订阅管理]
FilterBar: 严重度(descriptive/structural/breaking) | 数据源 | 对象类型 | 确认状态(待确认/已确认) | 时间范围
DataTable: 时间 | 严重度(SeverityTag) | 对象(FQN,链接) | 变更类型(added/modified/deleted/renamed) | 数据源 | 确认状态 | 操作(详情)
```
- 行按严重度配色（breaking 红）。
- 批量/单条「确认」→ 弹 action 选择。

### 5.2 变更详情 `/changes/:id`
```
PageHeader: 变更 #{id} [确认]
信息: 严重度 | 类型 | 对象 | 数据源 | 时间 | 状态
对比区(before → after):
 ├─ 表级: 新增/删除/改名说明
 └─ 字段级: 逐字段 diff 表(字段名|属性|旧值→新值，变更项高亮)
影响面(MOD-07, 降级): 下游表列表 + 责任人(若已接入血缘)
```

### 5.3 统计 `/changes/statistics`
```
PageHeader: 变更统计
Filters: since/until
图表: 按严重度分布(饼) | 按数据源排行(柱) | 按表稳定性(排行 Top, 高频变更表)
列表: 不稳定对象 Top（点击跳历史）
```

### 5.4 单实体历史 `/changes/entities/:type/:fqn/history`
- 时间线展示该对象的历次变更（change_type + 时间 + 严重度）。

### 5.5 订阅管理 `/subscriptions`【目标接口】
- 列表（订阅者/数据源/库/表/变更类型/静默状态）+ 新建（选择粒度与通道）+ 静默开关。

---

## 6. 画像与质量（MOD-04）

**路由** `/profile/tables/:id`、`/profile/quality/rules`、`/profile/quality/results`　**权限码** `profile:read`

**依赖接口**
- `GET /api/v1/profiles/tables/{id}` → 每表一行 JSONB（per-column stats）
- `GET /api/v1/profiles/tables/{id}/history` → 趋势（含 quality_score）
- `POST /api/v1/profiles/tasks` 下发画像任务（任务型）
- `GET /api/v1/quality/rules` / `POST` / `POST .../from-schema`
- `GET /api/v1/quality/results` / `GET /api/v1/quality/scores`
- `GET /api/v1/quality/reports/{table_id}` 导出（HTML/JSON，需 `export:execute`）

### 6.1 表画像 `/profile/tables/:id`
```
PageHeader: {fqn} 画像 [重算(任务)] [质量报告导出]
新鲜度: profiled_at + 是否过期提示(默认7天)
字段统计表: 字段|行数|空值率|唯一值数|min|max|mean|stddev|top_values
质量评分卡: 表级评分(大数字+色) + 规则通过率
趋势区(可折叠): 选择字段 → 折线(行数/空值率/均值) + 评分时间序列(history)
```

### 6.2 质量规则 `/profile/quality/rules`
```
PageHeader: 质量规则 [+ 新建] [从JSON Schema生成]
DataTable: 规则名 | 类型(not_null/unique/range/pattern/referential/custom_sql) | 作用对象 | 严重度(error/warning/info) | 状态 | 操作(编辑/删除)
新建表单: 类型 + 表达式/参数 + 严重度 + 绑定表/字段
```

### 6.3 校验结果/评分 `/profile/quality/results`
```
Filters: 表 | 规则 | 通过状态
DataTable: 表 | 规则 | 结果(通过/失败) | 评分 | 时间
评分视图: 按数据源/库/表维度质量分排行(可排序)
```

---

## 7. 分类分级（MOD-05）

**路由** `/classification`、`/classification/tags`、`/classification/rules`、`/classification/sensitive-assets`　**权限码** `classification:read`（标注需 `classification:write`）

**依赖接口**
- `GET /api/v1/classification/coverage` → 覆盖率（已分级/未分级字段数）
- `GET /api/v1/classification/tags` / `POST`（分级标准 L1-L4）
- `GET /api/v1/classification/rules` / `POST`
- `POST /api/v1/classification/tasks` 下发识别任务
- `POST /api/v1/classification/entities/{type}/{id}/tags` 人工标注（manual）
- `POST /api/v1/classification/feedback` 误报反馈
- `GET /api/v1/classification/sensitive-assets` / `/export`

### 7.1 概览 `/classification`
```
PageHeader: 分类分级 [下发识别任务] [敏感资产清单]
覆盖率卡: 已分级字段占比(进度条) + 按等级分布
快捷入口: 分级标准 | 识别规则 | 敏感资产清单
```

### 7.2 分级标准 `/classification/tags`
- 列表：等级(如 L1 公开~L4 核心)、名称、描述、版本（标准变更记录版本）。
- 编辑/新增（记录版本）。

### 7.3 识别规则 `/classification/rules`
```
DataTable: 规则名 | 策略层(L1词典/L2正则/L3类型/L4采样回验) | 匹配模式 | 命中等级 | 状态
新建: 选择策略层 + 词典/正则/类型启发式 + 对应等级
```

### 7.4 敏感资产清单 `/classification/sensitive-assets`
```
FilterBar: 最小等级(L3/L4) | 数据源 | 标签
DataTable: 字段(FQN) | 类型 | 等级(GradeTag) | 来源(rule/sample/manual) | 置信度 | 操作(详情/人工标注/反馈)
[导出合规报表](export:execute)
```
- 行「人工标注」→ 弹窗选等级/来源=manual，写 `entity_tag`。
- 「反馈误报」→ 提交 feedback，进入误报闭环。

---

## 8. 血缘分析（MOD-07）

**路由** `/lineage/tables/:id`、`/lineage/columns/:id`　**权限码** `lineage:read`

**依赖接口**
- `GET /api/v1/lineage/tables/{id}/upstream?depth=`【目标接口】
- `GET /api/v1/lineage/tables/{id}/downstream?depth=`【目标接口】
- `GET /api/v1/lineage/tables/{id}/impact?max_depth=`（当前已有 `/lineage/tables/{fqn}/impact`）
- `GET /api/v1/lineage/columns/{id}`【目标接口】
- `POST /api/v1/lineage/parse`（提交 SQL 解析任务）、`/import`（外部导入）、`/edges`（人工标注）、`DELETE /edges/{id}`、`/closure/rebuild`

### 8.1 表血缘 `/lineage/tables/:id`
```
PageHeader: {fqn} 血缘 [深度: select 1-5] [解析SQL] [导入] [人工标注] [重建闭包]
主区: <LineageGraph> 有向图
 ├─ 方向切换: 上游 / 下游 / 全部
 ├─ 节点: 表(FQN)，边: 血缘边(标注 source: view/sql_parse/etl/manual + confidence)
 ├─ 环检测: 存在环的节点高亮警示
 └─ 点击节点: 跳该表详情 / 查看影响面报告
侧栏(影响面): 分层下游列表 + 涉及数据源 + 聚合责任人(调用 impact)
```

### 8.2 字段级血缘 `/lineage/columns/:id`
```
主区: 横向 LineageGraph: 上游字段 → 当前字段 → 下游字段
边标注来源与置信度
```

### 8.3 解析/导入（弹窗）
- 解析 SQL：文本框粘贴 SQL/ETL 脚本 → 提交任务 → 提示「解析任务已提交，完成后查看」。
- 外部导入：上传/粘贴 ETL 系统导出 JSON。

---

## 9. 权限分析（MOD-08）

**路由** `/permissions/accounts`、`/permissions/matrix`、`/permissions/risks`、`/permissions/changes`　**权限码** `permission:read`

**依赖接口**
- `GET /api/v1/permissions/accounts?datasource_id&risk=`【目标接口】
- `GET /api/v1/permissions/accounts/{id}/grants`
- `GET /api/v1/permissions/matrix`
- `GET /api/v1/permissions/entities/{type}/{id}/grants`
- `GET /api/v1/permissions/risks` / `POST /risks/{id}/ack`
- `GET /api/v1/permissions/changes` / `POST /baseline/refresh` / `POST /tasks` / `GET /export`

### 9.1 账号列表 `/permissions/accounts`
```
FilterBar: 数据源 | 风险类型(超管/过度授权/僵尸/无主)
DataTable: 账号 | 主机 | 角色 | 数据源 | 风险标记(SeverityTag) | 最后登录 | 操作(授权明细/关联责任人)
```

### 9.2 权限矩阵 `/permissions/matrix`
```
筛选: 数据源 | 账号 | 对象类型
矩阵表(可滚动): 行=账号, 列=对象(FQN), 单元格=权限(SELECT/INSERT/.../ALL)
高敏对象( grade>=L3 )列 红色高亮
点击单元格: 查看授权明细(含来源)
```

### 9.3 风险项 `/permissions/risks`
```
DataTable: 风险类型 | 账号 | 对象 | 等级 | 说明 | 状态(待确认/已忽略) | 操作(确认/忽略)
[导出合规报表]
```

### 9.4 权限变更 `/permissions/changes`
```
与基线对比列表: 账号 | 变更类型(新增授权/回收/权限提升) | 对象 | 时间
[更新基线为当前状态]
```

---

## 10. 采样（MOD-03）

**路由** `/sampling/preview/:id`、`/sampling/columns/:id/values`　**权限码** `sample:execute`（查看原文需 `sample:view_raw`）

**依赖接口**
- `GET /api/v1/catalog/tables/{id}/preview`【目标接口】（脱敏样本行，需审计）
- `GET /api/v1/sampling/columns/{id}/values`（脱敏样本值）
- `DELETE /api/v1/sampling/columns/{id}/values`（清除样本）
- `POST /api/v1/sampling/tasks`（下发采样任务）

### 10.1 样本行预览 `/sampling/preview/:id`
```
PageHeader: {fqn} 样本预览 (提示: 已脱敏, 此操作已审计)
[重新采样(任务)] 
采样行表格: 展示脱敏后样本行(手机号/身份证掩码)
采样时间 + 有效期 + 新鲜度提示
```
- 敏感列默认掩码（如 `138****1234`）；`sample:view_raw` 才显示原文开关（高危）。

### 10.2 字段样本值 `/sampling/columns/:id/values`
```
PageHeader: {column} 样本值 [清除样本]
distinct 取值列表(脱敏) + 出现频次
同源字段详情页「样本值」Tab 复用
```

---

## 11. 任务与运维（MOD-10）

**路由** `/tasks`、`/tasks/:id`（列表/详情/取消/重试/提交【已实现 MOD-10】）、`/tasks/audit`（审计日志【已实现】，REST `GET /api/v1/audit-logs`）、`/tasks/partitions`（分区状态【已实现】，REST `GET /api/v1/tasks/partitions`）；平台健康/指标 `/api/v1/system/health`、`/api/v1/system/metrics`（已实现 MOD-10）　**权限码** 依模块；审计需 `audit:read`

**依赖接口**
- `GET /api/v1/tasks?jobType&status&datasourceId` / `POST /api/v1/tasks`（提交）/ `GET /api/v1/tasks/{id}`（含 `stats`/日志）/ `POST /api/v1/tasks/{id}/cancel` / `POST /api/v1/tasks/{id}/retry`（全部已实现）
- `GET /api/v1/tasks/partitions`（已实现，运维视角只读）
- `GET /api/v1/audit-logs`（已实现，action/actor/entityType/limit 过滤）
- `GET /api/v1/system/health` / `GET /api/v1/system/metrics`（已实现 MOD-10）
- `GET /api/v1/openapi.json`

### 11.1 任务列表 `/tasks`
```
FilterBar: 任务类型(metadata/sample/profile/classify/lineage/permission) | 状态(pending/running/success/failed/cancelled/timeout) | 数据源
DataTable: 任务ID | 类型 | 数据源 | 状态(StatusTag) | 进度 | 开始/结束 | 耗时 | 操作(详情/取消/重试)
```
- 提交/重试**立即返回**（后端线程池后台执行，见 `API.md` Tasks 执行模型）；running/pending 行轮询进度（React Query refetchInterval），终态停止轮询。

### 11.2 任务详情 `/tasks/:id`
```
PageHeader: 任务 #{id} [取消] [重试]
信息: 类型 | 范围(scope) | 状态 | 触发方式 | 重试策略 | 耗时 | 错误(若失败)
执行日志: 时间线/滚动日志(按 datasource/库/表 维度的失败明细)
下游编排: 触发出的下游任务(扫描→Diff→通知 链)
```

### 11.3 平台健康 `/api/v1/system/health`
- 状态卡：按 `components[]` 渲染各组件（数据库、API 等）状态（绿/黄/红点 + 明细）。

### 11.4 指标 `/api/v1/system/metrics`
- 展示 Prometheus 指标端点说明 + 关键指标卡片（任务成功率、队列长度、平均耗时）。可嵌入 Grafana 链接（若部署）。

### 11.5 审计日志 `/tasks/audit`
```
FilterBar: 动作类型(任务 submit/cancel/retry/success/failure 等) | 操作者 | 实体类型
DataTable: 时间(occurredAt) | 操作者(actor) | 动作(action) | 对象(entityFqn) | 详情(JsonView, detail)
```
- 数据源/治理等服务的审计条目需其 `AuditService` 指向 `GLOBAL_AUDIT_SINK` 才会出现（当前仅编排任务审计已接入）。

### 11.6 分区状态 `/tasks/partitions`
- 分区表列表 + 分区策略(RANGE) + 分区键 + 保留窗口(`retentionWindowDays`，应用层声明、DB 侧执行)。
- 内省 `models_ops` 的声明式分区；分区创建/保留为数据库层职责，本接口只读。

---

## 12. 业务元数据（MOD-09 FR-14）

**路由** `/business/terms`、`/business/entities`　**权限码** `metadata:read`

**依赖接口**
- `GET /api/v1/business/terms?domain` / `POST` / `GET /terms/{code}`
- `GET/PUT /api/v1/business/entities/{type}/{entity_id}`（`entity_id` 平台整数主键；alias, business_desc, domain, owner_business, term_codes[], tags{}）
- `POST /api/v1/business/entities/{type}/{entity_id}/tags`

### 12.1 术语表 `/business/terms`
```
PageHeader: 业务术语 [+ 新建术语]
DataTable: 术语编码 | 名称 | 业务域 | 定义 | 负责人 | 状态
新建: term_code/term_name/domain/definition/owner/status
```
- 术语可被资产详情「业务」Tab 关联（term_codes）。

### 12.2 实体业务信息
- 编辑表单复用 §4.2「业务」Tab；标签写 `business.*` 命名空间（与 security 隔离）。

---

## 13. 系统管理（MOD-11，P3）

**路由** `/admin/users`、`/admin/roles`、`/admin/data-policies`、`/admin/account-mappings`　**权限码** 管理员

**依赖接口**（全部【目标接口】）
- `POST /api/v1/auth/login` / `/auth/refresh`
- `GET/POST /api/v1/users`
- `GET/POST /api/v1/roles` / `PUT /roles/{id}/permissions` / `PUT /users/{id}/roles`
- `GET/POST /api/v1/data-policies`
- `POST /api/v1/account-mappings`

### 13.1 用户 `/admin/users`
- 列表（用户名/显示名/邮箱/来源 local/ldap/oauth/状态）+ 新建（含认证源）。

### 13.2 角色与权限 `/admin/roles`
- 角色列表 + 角色权限配置（勾选 perm_code 集合，见 MOD-11 §4.2）+ 用户-角色分配。

### 13.3 数据权限策略 `/admin/data-policies`
- 列表（subject_type/user/role, scope_type, scope_fqn, effect allow/deny, actions）+ 新建（按数据源/库/表粒度授权）。

### 13.4 业务账号关联 `/admin/account-mappings`
- 列表（业务库账号 ↔ 平台用户）+ 新建映射（支撑 MOD-08 FR-6.7 责任人关联）。

---

## 14. 跨页通用交互清单（供 code agent 实现）

| 交互 | 实现要点 |
|---|---|
| 全局搜索 ⌘K | Header 命令面板，输入跳 `/catalog?q=`，结果分组表/字段 |
| 资产跳转 | 任意 FQN/ID 可点击 → 表/字段详情；支持面包屑回退 |
| 任务型提交 | 提交后 `<TaskProgressLink>` 复制 `run_id` → `/tasks/:id`，Toast 提示 |
| 危险确认 | `<ConfirmDanger>` 统一文案 + 审计声明 |
| 导出 | 调用导出接口（多为文件流），`export:execute` 校验；失败提示 |
| 分页 | 仅 keyset 游标，「加载更多/下一页」，无页码跳页 |
| 降级 | `<SuspenseSection>` 包裹未上线模块区块 |
| 权限隐藏 | Sider 菜单按 perm_code 过滤；按钮按权限禁用/隐藏 |

---

## 15. 协作流程：审批流 + 工单（MOD-12）

**路由** `/governance/approvals`、`/governance/tickets`　**权限码** `governance:read`（操作需 `governance:approve` / `governance:ticket`）

**依赖接口**（基座 `/api/v1/governance`）
- 审批：`POST /approvals`、`GET /approvals`、`GET /approvals/{id}`、`POST /approvals/{id}/approve`、`POST /approvals/{id}/reject`、`GET/POST /approvals/{id}/comments`
- 工单：`POST /tickets`、`GET /tickets`、`GET /tickets/{id}`、`POST /tickets/{id}/assign`、`POST /tickets/{id}/transition`、`GET/POST /tickets/{id}/comments`
- 联动：FR-7 破坏性变更 `ack` 后自动创建 `change_auto` 工单（P0、SLA 24h、关联 FQN）

### 15.1 审批流 `/governance/approvals`
```
PageHeader: 审批流 [+ 提交审批]
FilterBar: 状态(pending/approved/rejected) | 资源类型 | 审批人
DataTable: 标题 | 资源(FQN) | 动作(publish/classify/sensitive_tag/delete) | 发起人 | 审批人 | 优先级 | 状态(StatusTag) | 创建时间 | 操作(详情/通过/驳回)
```
- 行「通过/驳回」→ 弹确认框（含意见输入）→ 调 `approve`/`reject`；已决策行禁用按钮。
- 详情抽屉：申请信息 + 决策信息（决策人/时间/意见）+ 评论线程 + 追加评论。
- 提交审批弹窗：选资源类型/动作/FQN/审批人/优先级/理由 → `POST /approvals`。

### 15.2 工单 `/governance/tickets`
```
PageHeader: 工单 [+ 新建工单]
FilterBar: 状态(open/in_progress/resolved/closed) | 类型(data_issue/access_request/change_auto/other) | 处理人 | 来源
DataTable: 标题 | 类型(GradeTag 风格) | 优先级(P0-P3 色) | 状态(StatusTag) | 报告人 | 处理人 | SLA到期 | 关联FQN | 创建时间 | 操作(详情)
```
- 行「分派」→ 选处理人 → `assign`；「流转」→ 选目标状态（仅合法状态可选）→ `transition`；非法流转置灰。
- 详情抽屉：描述 + 状态时间线（创建/处理中/解决/关闭）+ SLA 倒计时 + 评论线程（处理记录）。
- 新建工单弹窗：标题/类型/优先级/描述/关联FQN/SLA小时数 → `POST /tickets`。
- **联动可视化**：`change_auto` 类型工单标记「自动生成」，点击关联FQN 跳资产/变更详情，显式体现「破坏性变更 → 自动跟进工单」闭环。

---

## 16. 落地优先级建议（与后端阶段对齐）

| 批次 | 前端页面 | 依据 |
|---|---|---|
| 第一批（当前 API 可联调） | 登录(降级) / 概览 / 数据源 / 资产目录(检索+详情用 /search+/assets) / 变更 / 任务运维(列表+详情) / **协作流程(审批+工单，MOD-12 已落地)** | `API.md` 已落地 |
| 第二批 | 画像质量 / 分类分级 / 采样 | 依赖 MOD-03/04/05 接口补齐 |
| 第三批 | 血缘 / 权限分析 / 业务元数据 | 依赖 MOD-07/08 + 业务元数据接口 |
| 第四批 | 系统管理(鉴权/RBAC) | 依赖 MOD-11（P3） |

> 每批前端应先以「降级/占位」形态就位，待后端接口就绪后填充数据，避免返工。
