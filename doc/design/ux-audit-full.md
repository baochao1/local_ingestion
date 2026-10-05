# 全站交互可用性审计（ux-page-audit）

- 审计日期：2026-10-03
- 审计方式：产品经理视角 + Nielsen 十项启发式，Playwright 真实走查（21 个路由、点击/输入/提交流程、网络与控制台采集）
- 证据目录：`.playwright-mcp/ux-audit/full/`（截图 + `report.json`）、`.playwright-mcp/ux-audit/probe2~5`（针对性交互验证）
- 环境：前端 `http://127.0.0.1:5173`，后端 `http://127.0.0.1:8090`（本地 Postgres，含 `seed_demo_data.py` 造的演示数据）

---

## 一、背景

**范围**：`/app` 下全部 21 个已实现路由 + 1 个降级占位页，覆盖三条完整操作旅程：

1. 数据源接入：数据源列表 → 新建（填空/校验/试连）→ 详情 → 触发扫描 → 跳任务详情
2. 找表看字段：全局搜索/资产目录检索 → 表详情 → 字段详情
3. 变更闭环：变更列表 → 变更详情 → 确认/标记修复 → 变更统计；协作侧：审批 → 决策，工单 → 分派/流转

**目标用户**（据 `doc/requirement/01-product-requirements.md` §1.3）：数据平台/DBA（关注"连不上是什么原因、变更影响谁"）、数据治理/合规（关注"哪些是敏感的、分级对不对"）、数据分析/业务（关注"我要找的那张表在哪、字段什么意思"）、安全审计（关注"谁动了什么"）。

**核心任务与成功标准**：

| 核心任务 | 成功标准 | 本次实测结果 |
|---|---|---|
| 接入一个数据源并跑通扫描 | 填表 → 试连 → 提交 → 看到任务进度 | ✅ 主干可用（表单校验、试连、扫描弹窗、任务链接均正常） |
| 找到一张表并看懂它的字段 | 搜索结果点进去能看到表结构和字段含义 | ❌ **完全不可用**（详情页 100% 404） |
| 处理一条变更并确认 | 打开变更 → 看懂改了什么 → 确认 → 影响面可追 | ⚠️ 能确认，但看不懂（before/after 为空 {}，无字段级 diff，无法跳实体） |
| 处理一条审批/工单 | 打开 → 决策/流转 → 状态更新 | ❌ **点击即整站白屏** |

---

## 二、总体结论

**主干"能跑"，但三条业务主线里两条走不通，且存在会让整个应用崩溃的缺陷。**

具体水位：

- **数据源模块**是唯一达到"可交付"水准的模块（上一轮 `ux-audit-datasources.md` 的修复确实生效：停用有二次确认、筛选项已改下拉、空提交有字段级校验、扫描弹窗说明了只读策略）。
- **资产目录模块事实上是坏的**：搜索结果的「类型」列 6/6 行为空，「名称」列不可点；即使手输 URL 进详情页，也 100% 报「资产不存在」。这是产品的核心主张（"找表/看字段"）第一次使用就撞墙。
- **协作流模块会让整个 SPA 崩溃**：审批「通过/驳回」、工单「流转」点击后 `#root` 内容长度从 33678 掉到 0，整页白屏。根因是前后端请求体字段名不一致（前端发 `decided_by`，后端要 `actor`）触发 422，而前端把 FastAPI 的 `detail` 数组当 React 子节点渲染，且全站没有 ErrorBoundary 兜底。
- **首页在展示错误数字**：「数据源」指标恒为 0（实际 3 个），「分级分布」L1–L4 全为 0（后端返回 `{"1":2791,"2":2,"3":91,"5":4}`）。对一个"治理看板"，展示错误的 KPI 比展示不出来更伤信任。
- **业务语义严重缺失**：`TriggerType.MANUAL`、`task.failure`、`RANGE`、`seed_scope_type_1`、`metadata`、`dsType: postgresql` 这类后端标识符大量直接铺在界面上；数据源在多处以裸数字 ID（"数据源 3"）出现；表详情用一段 JSON 代替字段列表。
- **导航误导**：侧边栏 13 个一级项里有 6 个（画像质量、分类分级、血缘、权限分析、采样、系统管理）点进去是"该能力暂不可用"占位页；同时另有 5 个**已实现**页面（订阅管理、审计日志、分区状态、平台健康、实体变更历史）在菜单里**没有任何入口**，只能手输 URL。

**视觉风格不是主要矛盾。** 当前是 antd v5 默认皮肤 + 零自定义 CSS，观感"传统"属实，但用户抱怨的"字段列出来不知道什么意思、交互没有串联"本质是**语义层缺失**与**链路断裂**，不是配色和圆角问题。先修下面第三节的 G1–G4，观感问题会自解大半。

---

## 三、变更定级建议：整体变更 vs 局部变更

### 结论

需要 **4 项横向（整体）改造 + 1 项可选视觉收敛**，其余是逐页局部修复。**不建议做推倒重来的视觉重构**——成本高、收益低，且当前布局骨架（Sider + Header + PageHeader + DataTable/FilterBar 四态）本身是合理的，值得保留。

### A. 整体变更（横切，影响全部页面，必须先做）

| 编号 | 变更 | 为什么必须整体做 | 涉及面 |
|---|---|---|---|
| **G1** | **建立统一语义字典层** | 目前 16 个文件各自硬编码或干脆不映射，同一个 `structural` 在概览是英文、在变更列表是「结构性」，改一处漏十处 | 新增 `web/src/constants/enums.ts`（数据源类型、任务类型/状态/触发方式、变更类型/实体类型/确认状态、严重度、分级、订阅范围/级别/渠道、审批动作/状态、工单类型/优先级/状态、审计动作/结果、健康状态、分区策略）；改造 `StatusTag/GradeTag/SeverityTag` 支持从字典取，新增 `EnumTag` 组件 |
| **G2** | **建立实体引用解析与跳转** | 「变更→实体→字段」「审批→资源」「工单→关联表」是同一种需求：把 `fqn`/`datasourceId` 解析成「人类可读名称 + 可点链接」。现在每页各写各的，且都不跳 | 新增 `web/src/components/EntityRef.tsx`（props: `fqn` / `entityType` / `datasourceId`，内部走 `catalog` API 解析名称并渲染 `<Link>`）；新增 `useDatasourceName(id)` 查询钩子做 ID→名称缓存 |
| **G3** | **健壮性：ErrorBoundary + 错误归一 + 契约对齐** | 不修这个，任何一次接口报错都会把整个应用打成白屏；且这是"一类"问题（422 数组渲染），不是一处 bug | 新增 `web/src/components/ErrorBoundary.tsx` 并包在 `AppShell` 外层；改造 `web/src/api/client.ts` 响应拦截器，把 `detail` 数组/对象统一拍平成可读中文串；修正 `api/governance.ts` 的 `approve/reject/transition` 请求体字段名 |
| **G4** | **导航信息架构重组** | 6/13 菜单项指向占位页、5 个可用页面无入口，是结构性问题 | `web/src/layouts/AppShell.tsx` 的 `MENU` 常量：已上线模块置顶；未上线模块收拢为单个「未上线能力」子菜单（或加 `disabled` + "未上线" 角标）；为订阅管理/审计日志/分区状态/平台健康补子菜单入口 |

**G5（可选，视觉收敛，非重构）**：在现有 antd 主题上叠一层，即可明显"去传统化"，但优先级低于以上四项——

- 内容区加最大宽度约束（现在 1440px 下表格/卡片被拉满，长文行宽失控）
- 详情页从"整页 Descriptions 平铺"改为「左主右辅 + Tabs」的信息层级（FE-01 已经这么设计了，实现没跟上）
- 统一状态色语义（现在绿=启用/成功/ok 混用，橙=待执行/待审批/优先级 P2 混用）
- 表格信息密度：`DataTable` 默认 `size="small"`，但详情页的 JSON 区块与卡片间距没有节奏

### B. 局部变更（逐页修，不动结构）

见第五节的逐页清单，每页标注了「整体改造能覆盖的部分」和「必须单独改的部分」。

### C. 需要后端配合的变更（前端无法单方面修好）

| # | 后端问题 | 影响页面 | 建议 |
|---|---|---|---|
| B1 | `GET /assets/{path}` 只接受 FQN，而路由/搜索给的是数字 id → 详情页 404 | 表详情、字段详情 | 二选一：① 新增 `GET /assets/by-id/{id}`；② 前端统一改用 `?fqn=` 路由参数（改动更小，推荐，且与 `AppShell` 全局搜索已有的正确实现一致） |
| B2 | 审批 `POST /approvals/{id}/approve` 要求 `{actor, ...}`，工单 `POST /tickets/{id}/transition` 要求 `{to_status, ...}` | 审批流、工单 | 对齐字段名（或前端改），并保证 422 只在前端有校验时出现 |
| B3 | `/catalog/overview` 不返回数据源数量 → 首页指标只能显示 0 | 概览 | 补 `datasources_count`；`grade_distribution` 的 key 用 `"1"` 而前端按 `"L1"` 取，需约定统一（且 `"5"` 超出 L1–L4 定义，应回 `null`/`未分级`） |
| B4 | `/governance/approvals` 返回 `action_type`/`requested_by`，前端取 `action`/`发起人` | 审批流 | 统一命名（前端 `types/index.ts` 已是 snake_case 的地方就统一 snake_case） |
| B5 | 数据源列表未实现 keyset 游标（`total` 为 `null`） | 数据源列表 | 补 `cursor`/`limit`/`total`，让「加载更多」真正可用（`ux-audit-datasources.md` 已列为后续项） |
| B6 | `/audit-logs` 返回的 `detail` 是大对象，无分页 | 审计日志 | 列表接口不返回 `detail`，改由详情抽屉按需拉；补 `cursor`/`limit` |

---

## 四、问题清单（按严重度降序）

### S0 — 阻断

| # | 问题 | 现象与证据 | 影响 | 建议 |
|---|---|---|---|---|
| 1 | **资产详情页 100% 打不开，核心旅程断路** | 资产目录点击「account」→ 跳 `/app/catalog/tables/5` → `GET /api/v1/assets/5` 返回 **404** → 页面显示「加载失败 / 资产不存在: 5」。字段详情同病（`/app/catalog/columns/5274` → 404）。证据：`full/04-catalog-search/02-after-click-name.png`、`full/05-table-detail/01-table-detail.png`、`full/06-column-detail/01-column-detail.png`、`full/report.json`（badResponses） | 「找表 → 看字段」是产品第一核心任务（FE-00 §1.2「检索优先」），当前完全无法完成 | 前端路由改为 `/app/catalog/tables?fqn=...` 并把 `getAsset(fqn)` 传 FQN（`AppShell` 全局搜索已是正确实现，照抄即可）；同时修 `CatalogSearchPage.tsx:48-53` 只按 `type` 区分 `tables`/`columns` 的跳转 |
| 2 | **审批「通过/驳回」导致整个应用白屏** | 点击后 `#root` 内容长度 33626 → **0**，整页空白（连侧边栏都没了）。`pageerror`: `Objects are not valid as a React child (found: object with keys {type, loc, msg, input})`。根因：前端发 `{decided_by, decision_note}`，后端要 `{actor}` → 422 → `detail` 是数组 → 被当 React 子节点渲染 → 崩。证据：`probe2/04-approval-after-approve.png`、`probe3.py` 输出；后端复现 `POST /approvals/6/approve` → `422 {"detail":[{"type":"missing","loc":["body","actor"],...}]}` | 审批流是 MOD-12 的全部价值所在，点一次崩一次；且用户完全不知道发生了什么（无任何错误提示，就是白屏） | G3：① 修 `api/governance.ts` 的请求体字段名；② `client.ts` 把 `detail` 数组拍平成中文消息；③ 加 `ErrorBoundary`，让单页崩溃不至于带走整个应用 |
| 3 | **工单「流转」同样整站白屏** | 操作列的选择框选中即提交 → `#root` 33678 → **0**，同样报 `Objects are not valid as a React child`。后端要 `{to_status}`，前端发 `{status}` → 422。证据：`probe4.py` 输出、`probe2/06-ticket-transition.png` | 工单状态机（FR-17.5 `open→in_progress→resolved→closed`）无法使用 | 同 #2；另需给「流转」加二次确认（见 #8） |

### S1 — 严重

| # | 问题 | 现象与证据 | 影响 | 建议 |
|---|---|---|---|---|
| 4 | **首页「数据源」指标恒为 0（展示错误数据）** | 概览页「数据源 **0**」，而 `GET /api/v1/datasources` 实际返回 3 条。`GET /catalog/overview` 的响应里根本没有数据源数量字段。证据：`full/01-dashboard/01-dashboard.png` | 治理看板首屏就在说谎，用户会据此判断"平台里没有数据源" | B3 补字段；前端在字段缺失时显示 `—` 而非 `0`（`—` 表示"未知"，`0` 表示"已知为零"，二者不可混） |
| 5 | **首页「分级分布」全为 0** | L1 0(0%) / L2 0(0%) / L3 0(0%) / L4 0(0%)，而后端 `grade_distribution` = `{"1":2791,"2":2,"3":91,"5":4}`。前端按 `"L1"` 取值，后端给 `"1"`，永远取不到。证据：同上截图 + `curl /catalog/overview` | 分类分级是治理的第一卖点，图表却永远空着；且 key `"5"` 超出 L1–L4 定义，4 个字段被静默吞掉 | 统一 key 约定（建议后端直接返回 `L1..L4` + `unclassified`）；前端对未知 key 归入「未分级」而不是丢弃 |
| 6 | **审批列表「动作」「发起人」「审批人」三列恒为空** | DOM 提取：4 行数据的这三列全部为 `""`。后端返回的是 `action_type` / `requested_by` / `approver`，前端取 `action` / 发起人。证据：`probe5.py` 输出、`full/13-approvals/01-approvals.png` | 审批人看不出这条审批要干什么（`publish`? `delete`?），只能靠标题猜 | B4 对齐字段名 |
| 7 | **订阅「删除」无二次确认，点击即删除** | 实测：点击「删除」后 `confirm_dialog_count = 0`，表格行数 **3 → 2**，无任何确认弹窗、无撤销。证据：`probe2.py` 输出 | 误点即丢失订阅配置，且违反项目自身规约（FE-01 §0「危险操作 = `<ConfirmDanger>` + 审计提示」）——数据源停用用了 `ConfirmDanger`，订阅删除没用 | 包一层 `ConfirmDanger`，文案说明"将不再收到该范围的通知" |
| 8 | **工单「流转」选择即提交、无确认；「分派」用 `window.prompt`** | `TicketsPage.tsx`：流转是行内 Select，`onChange` 直接 `mutate`；分派弹原生 `window.prompt('分派给（用户名）')`——与 antd 设计体系断裂，且要求用户凭空记住用户名（违反"识别优于回忆"） | 状态机误操作无防护；分派流程不可用（没人知道该输谁） | 流转改 `ConfirmDanger`；分派改 antd `Modal` + 用户下拉（MOD-11 上线前可先做"最近分派人"建议列表） |
| 9 | **后端标识符大面积直出，业务用户看不懂** | 实测可见：`TriggerType.MANUAL`（任务详情"触发方式"）、`task.failure`/`failed`/`ok`（审计日志）、`RANGE`/`database`（分区状态）、`seed_scope_type_1`/`seed_channel_1`/`structural`（订阅管理）、`seed_job_type_1`/`metadata`（任务列表）、`table_renamed`/`seed_entity_type_2`/`pending`（变更列表）、`postgresql`（数据源类型）、`healthy`/`running`（平台健康）。共 16 个文件涉及 | 违反 Nielsen #2「系统与真实世界匹配」。目标用户是 DBA 和治理人员，不是看日志的开发 | G1 统一字典层。`TriggerType.MANUAL` 这类 Python 枚举 repr 泄漏尤其要修（应显示「手动触发」） |
| 10 | **数据源以裸数字 ID 呈现，无法识别、无法跳转** | 任务列表「数据源」列显示 `3`；变更统计「数据源 3」；订阅/表详情「数据源 ID = 3」；筛选条件要求用户手输数据源 ID（资产目录、变更列表、任务列表） | 用户必须记住"3 号是 pg_local"，且输入错误无从发现 | G2 用 `EntityRef` 渲染名称 + 链接；筛选项从"手输 ID"改为数据源下拉（数据源数量可控，一次拉全） |
| 11 | **用 JSON 铺开代替业务表格/视图** | 表详情「字段（N）」整段 `<JsonView value={columns}/>`；任务详情「执行结果 / 日志（stats）」是 `{"Attempts":1,"SubmittedBy":null}`；系统页「运行时指标（原始）」；数据源详情「原始配置」把整个对象（含 `credentialVersions`）铺出 20+ 行 | 表结构是资产目录的核心信息，用 JSON 看等于没有；且这些区块把详情页撑得极长 | 表详情改为字段表格（列：字段名 / 类型 / 可空 / 分级 / 描述）；任务 stats 按语义拆成"重试次数/提交人"；原始 JSON 一律收进「高级信息」折叠面板（`ux-audit-datasources.md` 已把这条列为可保留的调试期形态，现在到了收敛的时候） |
| 12 | **变更详情 before/after 为空 `{}`，无字段级 diff，实体不可点** | 实测「变更前 (before)」「变更后 (after)」两块都只显示 `{}`；「实体 FQN」为 `-`；标题「变更 #4」无信息量。证据：`full/08-change-detail/01-change-detail.png` | FR-3.2 要求字段级 diff（新增/删除/改名/类型/约束/顺序），FR-7 要求破坏性变更可评估影响面。当前用户看完仍然不知道"到底改了什么" | 后端 `before_json`/`after_json` 落数据；前端做字段级 diff 表（仅高亮变化行，不是并排两份 JSON）；`entity_fqn` 用 `EntityRef` 渲染为链接，并补「查看该实体变更历史」入口 |
| 13 | **侧边栏 6/13 项指向"该能力暂不可用"，5 个可用页面无入口** | 菜单：概览/数据源/资产目录/数据变更/画像质量/分类分级/血缘/权限分析/采样/任务运维/业务元数据/协作流程/系统管理。其中画像质量、分类分级、血缘、权限分析、采样、系统管理 → `DegradedPage`；而无入口的是 `/app/subscriptions`、`/app/tasks/audit`、`/app/tasks/partitions`、`/app/system`（菜单里没有）、`/app/changes/entities/:type/:fqn/history`。证据：`probe5.py` 菜单提取 + `full/20-degraded-lineage/01-degraded.png` | 用户点 6 次撞墙（形成"这系统啥都没有"的第一印象），同时 5 个真能用的功能没人找得到 | G4：未上线模块收拢为一个折叠的「未上线能力」分组或加 `disabled`+"未上线"角标；`任务运维` 补子菜单（任务列表/审计日志/分区状态）；`系统管理` 分组放平台健康；`业务元数据` 下挂术语表与实体信息 |
| 14 | **筛选逐字符发请求，「查询」按钮语义虚设** | 实测：在数据源「关键字」框输入 `pglocal`（7 字符，间隔 120ms），触发 **7 次**请求：`keyword=p`→`pg`→`pgl`→`pglo`→`pgloc`→`pgloca`→`pglocal`。`FilterBar` 无防抖，`onChange` 直连查询 | 全站 8 个列表页都受影响，是持续的后端压力与闪烁源；同时用户会困惑"我还没点查询，怎么结果就变了" | `FilterBar` 输入类字段加 300ms 防抖（下拉类可立即触发）；或改为「本地暂存 + 点查询才提交」的显式语义，二选一并全站统一 |

### S2 — 一般

| # | 问题 | 现象与证据 | 影响 | 建议 |
|---|---|---|---|---|
| 15 | 面包屑全站不可点，详情页缺少返回路径 | `PageHeader` 支持 `breadcrumb[].href` 但**无一个页面传**。数据源详情「数据源 / ds_pg_01」、表详情、变更详情、任务详情、降级页的「首页」都点不动。证据：各详情页截图 | 深链进入后无法回到列表，只能靠侧边栏重找 | 给 `PageHeader` 的 breadcrumb 补 `href`；`AppShell` 增加基于路由自动生成的面包屑，避免每页手写 |
| 16 | 5 个已实现页面全站零入口 | 见 #13。`EntityHistoryPage`、`SubscriptionPage`、`AuditLogPage`、`PartitionStatusPage`、`SystemStatusPage` 无任何 `<Link>` 指向，只能手输 URL | 已交付的功能等于不存在 | G4 补菜单；另在 `ChangeDetailPage` 加「查看该实体变更历史」「订阅此实体变更」，在 `TableDetailPage` 加「变更历史」 |
| 17 | 审计日志表格因内嵌 JSON 而不可用 | 每行「详情」列嵌一个多行 JSON，行高约 145px，一屏只能看 2–3 条；`limit` 硬编码 200、无分页、无总数；「操作者」列全为 `-`。页脚还留着"数据源/治理等服务的审计需将其 AuditService 指向 GLOBAL_AUDIT_SINK 后才会出现"。证据：`full/17-audit-log/01-audit.png` | 审计日志是合规刚需，当前既看不全也看不懂 | 列表去掉 `detail` 列，改行点击开 `DetailDrawer` 展示；补游标分页与总数；页脚开发说明移入文档；`rowKey` 用 `id`（现在用数组下标，触发 antd 废弃告警） |
| 18 | 分区状态页正文是英文 | Alert 原文：`Partition creation/retention is enforced at the database layer; the app only declares the scheme.` 表格里 `RANGE`/`database` 也是原始值。证据：`full/18-partitions/01-partitions.png` | 中文界面里突兀，且这句话讲的是实现细节，不是用户需要知道的 | 改为中文业务表述，例如「分区由数据库层自动创建与清理，平台仅登记当前策略」 |
| 19 | 表单用文本框替代枚举/数字控件 | 业务术语表「状态」是普通 `Input`，placeholder 写 `active`（要求用户手敲枚举）；工单「SLA 小时数」用 `<Input type="number">`（提交为字符串）；订阅「数据源 ID」是文本框。证据：代码 `BusinessTermsPage.tsx`、`TicketsPage.tsx` | 用户不知道能填什么，填错要到提交才报错 | 改 `Select` / `InputNumber`；这是 G1 字典层的直接受益点 |
| 20 | 工单表格横向溢出，流转控件被裁切 | 实测 `TABLE` 右边界 `1524` > 视口 `1440`，`clientWidth 1440 / scrollWidth 1440`（表格自身溢出但未提供 `scroll.x`），最后一列的选择框被切掉一半。证据：`probe2.py` 输出、`full/14-tickets/01-tickets.png`（右侧"状"字被切） | 工单的核心操作（流转）在 1440px 下看不全 | 给表格加 `scroll={{x:...}}`（`DataTable` 已有该能力，工单页用的是原生 antd Table 没走它）；或把「流转」收进行操作「更多」菜单 |
| 21 | 调试用元素残留在正式界面 | 任务列表页头「提交示例扫描任务」按钮，硬编码 `scope: {datasource_id: 1}`；任务列表页脚常驻 `任务状态：pending / running / success / failed / cancelled / timeout`；审计日志页脚开发说明。证据：`full/11-tasks-list/01-tasks-list.png` | 用户会误点示例按钮（往 1 号数据源发任务），且开发术语污染界面 | 移除或收进 dev-only 分支（`import.meta.env.DEV`） |
| 22 | 列表普遍无排序、无总数 | 数据源/变更/任务/术语/订阅列表均无排序；除数据源外多数不显示总数；资产目录明确提示"模糊检索后端上限 1000 条"但用户无法感知自己是否被截断 | 数据量大时无法定位（如"最近失败的任务"） | 至少给时间列加默认倒序；`DataTable` 支持受控排序；总数可见 |
| 23 | 登录表单是假的，且无路由守卫 | 任意用户名/密码都能"登录"（`onFinish` 不校验不发请求，直接写 localStorage）；未登录也能直接访问 `/app/dashboard`（Header 显示 `guest`）；页面还留着「跳过登录直接进入（dev）」。证据：`full/21-login/01-login.png` | 演示/评审时会被认为"没有鉴权"；真实上线前必须收敛 | 属于 MOD-11 未上线的已知降级（见第六节取舍），但建议：把「跳过登录（dev）」按钮改为仅 `import.meta.env.DEV` 显示；补一个最小 `RequireAuth` 守卫，未登录跳 `/login` |
| 24 | 任务列表存在无效轮询 | `TaskListPage.tsx` 额外创建了一个 `poll` query 并用 `void poll` 丢弃结果——每 3 秒发一次重复请求，返回值完全不用 | 无谓的后端压力 | 删除该 query（主查询已有 `refetchInterval`） |
| 25 | 空态/错误态不成体系 | `BusinessTermsPage`、`SubscriptionPage` 完全没有 `error` 分支（接口挂了只看到空表）；`ChangeStatisticsPage`、`SystemStatusPage` 用纯文本「暂无数据」而非 `EmptyState`。证据：代码 + 各页截图 | FE-01 §0 要求"每个数据区四态齐全"，实现参差 | 统一走 `DataTable` 或抽一个 `AsyncSection` 组件承载四态 |
| 26 | 同页内中英文状态自相矛盾 | 变更列表：「严重度」列是中文「描述性/结构性」，而「变更类型/实体类型/确认状态」列是英文 `table_renamed`/`pending`，筛选项却是中文「待确认/已确认」；任务列表：状态列中文「失败」，状态筛选项是 `failed`；概览：严重度用英文 `breaking` 而其他页用中文「破坏性」。证据：各页截图 | 同一概念在不同位置不同表达，用户要建立两套映射 | G1 字典层统一；加一条 lint/约定：任何面向用户的枚举必须走字典 |

### S3 — 轻微

| # | 问题 | 建议 |
|---|---|---|
| 27 | 审计日志 `rowKey` 用数组下标，触发 antd 废弃告警（`full/report.json` 唯一非 404 的控制台错误） | 改用记录 `id` |
| 28 | 数据源页副标题承诺「凭据轮换」，但界面无任何轮换入口（`datasources.ts` 已有 `rotateCredentials` API） | 要么补入口（详情页「凭据」Tab），要么改副标题 |
| 29 | 降级页文案面向开发者：「MOD-07 的接口尚未在后端落地，前端已按目标形态预留页面，待接口就绪后填充数据」 | 改为面向用户的「该功能正在建设中」，把模块号移入 tooltip 或内部文档 |
| 30 | 分页文案「已加载 3 / 3 条，没有更多数据」措辞重复别扭 | 改为「共 3 条」；有下一页时显示「已显示 50 / 共 2888 条 · 加载更多」 |
| 31 | 数据源详情「健康状态：状态 -」渲染出空 Tag；「创建时间 -」（`createdAt` 缺失） | 字段缺失时整行隐藏或显示 `—`，不要渲染空标签 |
| 32 | 变更详情标题「变更 #4」、任务列表任务 ID 显示「#3 复制」（复制按钮图标与 ID 挤在一起像操作文案） | 变更标题用「表名 · 变更类型 · 时间」；任务 ID 列把复制按钮移到 hover 才出现 |
| 33 | 审批详情抽屉用 `items.find(...)` 伪造 queryFn（不发请求，数据可能陈旧）；评论无时间戳；评论作者硬编码 `console`；一个 TextArea 同时承担「决策意见」和「追加评论」 | 抽屉改为按 id 拉详情；评论补时间戳；作者取当前用户；决策意见与评论分开 |

---

## 五、逐页细化分析

> 每页格式：**该页要解决什么 → 实测问题 → 变更归属**（G*=整体改造覆盖 / L*=需单独改）

### 1. 概览 `/app/dashboard`
**要解决什么**：让治理负责人一眼看到资产规模、敏感占比、变更热度、平台是否健康。

**实测问题**：
- 「数据源」= **0**（实际 3）——错误数据（S1#4）
- 「分级分布」L1–L4 全 0（后端有 2791 个 L1）——取值键不匹配（S1#5）
- 「变更严重度」用英文 `breaking/structural/descriptive`，与全站 `SeverityTag` 的中文不一致（S2#26）
- 「平台健康」显示 `database: healthy` / `api: healthy` 原始英文，且"healthy"与卡片里的绿色 Tag 重复表达（S1#9）
- 6 个指标卡只有「变更总数」可点（→ 变更列表），「数据源」「表」「字段」都不可点——而这些恰恰是用户看完数字后最想钻取的地方（S2）
- 「变更趋势」空，「变更频繁表 Top10」空（数据不足，属数据侧）
- 代码里有 `pick()`/`asArray()` 双命名兼容层兜 snake/camel 两种返回——说明后端契约不稳，应修契约而非长期兜（见 C 节）

**变更归属**：G1（严重度/健康状态走字典）、G2（指标卡可点跳转 + 数据源名称解析）、L（指标取值键、缺字段显示 `—` 而非 0）、B3（后端补数据源计数）

### 2. 数据源列表 `/app/datasources`
**要解决什么**：纳管哪些库、它们通不通、最近扫过没有。

**实测问题（本页是全站做得最好的）**：
- ✅ 停用有 `ConfirmDanger`，文案说清后果 +「此操作将被审计」
- ✅ 空提交有 3 条字段级错误（请输入编码/名称/选择类型），弹窗不关、输入保留
- ✅ 空结果区分「没有匹配的数据源」+「清除筛选」
- ❌ 「类型」列显示 `postgresql` 原始英文（G1）
- ❌ 列只有 ID/编码/名称/类型/状态/操作——FE-01 §3 要求的「环境、分组、负责人、扫描开关、采样开关、健康」全都没有，而这些正是"DBA 判断该不该动它"的依据
- ❌ 「编码」是纯文本，不可点（详情入口只有 ID 列，而 ID 是最没有业务含义的一列）
- ❌ 副标题承诺「凭据轮换」但无入口（S3#28）
- ❌ 筛选逐字符发请求（S1#14）
- ❌ 无排序；`total` 为 `null` 导致"加载更多"永远不会出现（B5）

**变更归属**：G1（类型中文）、G4（无）、L（补列、把「名称」做成详情链接、加排序）、B5

### 3. 新建数据源弹窗（非路由）
**要解决什么**：注册一个数据源，并确认能连上。

**实测问题**：
- ✅ 「测试连接」与「提交」分离，试连结果会区分"只读/具备写权限"，这是本页最亮的设计
- ❌ 17 个字段平铺在一个弹窗里，无分组（FE-01 要求分「连接信息 / 责任人 / 策略开关」），且「允许写权限注册」这个安全开关和其他 3 个普通开关挤在一行
- ❌ 「类型」选项 label = value = `mysql/postgres/snowflake` 原始英文，用户需知道产品支持哪些类型才能选（虽已改 Select，但仍显示英文）
- ❌ 除 4 个开关外**没有任何字段有帮助说明**：`环境` 是什么？`分组` 用来干什么？「业务负责人」为什么是自由文本而不是从用户列表选？
- ❌ 试连只校验 5 个字段，而提交校验全部——用户可能试连成功但提交失败
- ❌ 提交失败只弹 `message.error`，无字段级定位

**变更归属**：G1（类型中文）、G2（负责人改用户选择器）、L（字段分组 + 补 tooltip + 试连校验范围对齐提交）

### 4. 数据源详情 `/app/datasources/:id`
**要解决什么**：这个源现在的状态如何、能不能扫、配置长什么样。

**实测问题**：
- ✅ 「立即扫描」→ 扫描弹窗明确解释只读策略（FR-1.5），扫描后 `TaskProgressLink` 直达任务详情
- ❌ 「健康状态：状态 **-**」渲染出一个空 Tag；「创建时间 **-**」；「最近扫描」显示 `success` 原始英文（S3#31、S1#9）
- ❌ 「原始配置」把整个 DataSource 对象铺 20+ 行 JSON，含 `credentialVersions`/`activeCredentialVersion` 这类内部字段（S1#11）
- ❌ 只有 6 个信息项 + 2 个 JSON 块，**没有任何"这个源底下有什么"**——不展示该源下的 schema/表数量、不展示扫描历史、不展示上次扫描失败原因
- ❌ 面包屑「数据源」不可点（S2#15）
- ❌ 无「编辑」，无凭据轮换

**变更归属**：G2（关联资产列表跳转）、L（健康状态映射、JSON 折叠、补扫描历史与失败原因）

### 5. 资产目录 `/app/catalog`
**要解决什么**：全平台 2888 个资产里，快速找到"我要的那张表/那个字段"。

**实测问题（本模块问题最集中）**：
- ❌ 「类型」列 **6/6 行全空**——接口返回 `entityType`，前端取 `type`（S1，实测确认）
- ❌ 「名称」列不可点（`r.id` 存在时也指向 `/tables/{id}` 且不区分 column）
- ❌ 表行和字段行**混在同一个列表里且没有任何视觉区分**（没有缩进、没有图标、没有父表提示），用户看到 `account` 后面跟着 `account_name`、`account_type`、`created_at`…（实测截图第一屏就是），很难判断哪些是表、哪些是字段
- ❌ 2888 条结果，分页是自造的 offset 游标，上限 1000，**不显示总数**，用户永远不知道"我看到的是一部分还是全部"
- ❌ 「数据源」筛选要求手工输入数字 ID（S1#10）
- ❌ 「负责人」「标签」列几乎全为 `-`，「分级」全是「未分级」——列表的信息密度很低，真正有用的 FQN 又长到撑满列宽
- ❌ 无排序（按名称/按分级/按敏感排序都是刚需）

**变更归属**：**这是最需要重做的一页**。G1（类型中文）、G2（名称可点 + 跳转分流）、L（表/字段分层展示或加类型图标、显示总数、数据源筛选改下拉、加排序）、B1（详情接口）

### 6. 表详情 `/app/catalog/tables/:id` — **完全不可用**
- ❌ `GET /api/v1/assets/5` → 404 → 「加载失败 / 资产不存在: 5」（S0#1）
- 即使数据能出来，仍有：字段区块是 JSON 而非表格（S1#11）、「数据源 ID」是裸数字（S1#10）、画像/血缘/权限三块硬编码 `available={false}`（合理降级）、面包屑不可点、无跳字段详情/变更历史/数据源的入口

**变更归属**：B1（修接口/路由）+ 几乎全部 G1/G2 + L（字段表格）

### 7. 字段详情 `/app/catalog/columns/:id` — **完全不可用**
- ❌ 同样 404（S0#1）
- ❌「可空」渲染 `true`/`false`/`null` 英文（S1#9）
- ❌ 除 ⌘K 全局搜索外**零入口**
- 缺：所属表链接、字段变更历史、样本值预览（`/app/sampling/columns/:id/values` 有路由无入口）

**变更归属**：同表详情

### 8. 数据变更列表 `/app/changes`
**要解决什么**：最近数据库结构/描述改了什么，哪些是破坏性的。

**实测问题**：
- ❌ 「变更类型」`table_renamed`、「实体类型」`seed_entity_type_2`、「确认状态」`pending` 全英文，而同页筛选项是中文「待确认/已确认」——同页自相矛盾（S2#26）
- ❌ 「实体 FQN」为 `-`（数据侧），且 FQN 也不可点
- ❌ 「数据源」筛选要手输 ID；「变更类型」「实体类型」筛选是**自由文本**，要求用户自己敲内部枚举值
- ❌ 无排序、无行内操作、无分页信息
- FE-01 §5 要求「breaking 行红色」，未实现——破坏性变更在列表里和描述性变更长得一样

**变更归属**：G1（三个枚举走字典）、G2（FQN 可点）、L（筛选改下拉、breaking 行高亮、加排序）

### 9. 变更详情 `/app/changes/:id`
**要解决什么**：这次变更到底改了什么，我确认还是修了。

**实测问题**：
- ❌「变更前 (before)」和「变更后 (after)」都只显示 `{}`——**核心信息为空**（S1#12）
- ❌ 「实体 FQN」为 `-`，无任何通往实体的链接（S1#12）
- ❌ 标题「变更 #4」对用户零信息量
- ✅ 「确认接受」「标记为已修复」都用了 `ConfirmDanger` 且文案说清后果——本页唯一亮点
- 缺：该实体的变更历史入口、关联的自动工单（FR-17.7）、订阅该实体变更

**变更归属**：B（before/after 数据）、G2、L（字段级 diff 表 + 标题改为「表名 · 变更类型」）

### 10. 变更统计 `/app/changes/statistics`
- ✅ 严重度占比图（中文 Tag + 百分比 + Progress）是对的
- ❌「按数据源」显示「数据源 **unknown**」配一条**满格绿色进度条**——绿色在别处表示"成功/健康"，这里只是"未知"，色彩语义误导（S1#10）
- ❌ 空态是纯文本「暂无数据」而非 `EmptyState`（S2#25）
- ❌ 无「返回变更列表」入口；时间筛选同样逐次触发

**变更归属**：G1/G2 + L（未知值改用中性色、补返回链接）

### 11. 实体变更历史 `/app/changes/entities/:type/:fqn/history`
- ❌ **全站零入口**（S2#16）
- ❌「变更类型」「确认状态」英文；「ID」列是纯文本不可点进变更详情（列表里唯一没有链接的 ID 列）
- ❌ 页面不展示 `type` 参数；无面包屑

**变更归属**：G1/G4 + L（ID 列加链接）

### 12. 订阅管理 `/app/subscriptions`
- ❌ **全站零入口**（S2#16）
- ❌「删除」无二次确认，实测点击即删（S1#7）
- ❌「范围」`seed_scope_type_1`、「渠道」`seed_channel_1` 原始英文；「最低级别」一列混着 `structural` 和 `P1` 两种体系（S1#9）
- ❌「数据源 ID」是文本框；表单里「范围」选项 label=value 原始英文；「对象 FQN」不随范围联动禁用
- ❌ 无筛选、无搜索、无错误态分支

**变更归属**：G1/G4 + L（ConfirmDanger、表单联动、数据源改下拉）

### 13. 任务列表 `/app/tasks`
- ❌「类型」`seed_job_type_1`/`metadata` 英文；「数据源」裸数字 ID 或 `-`（S1#9/#10）
- ❌ 筛选「任务类型」「状态」的选项是原始英文，而状态列本身是中文「失败」（S2#26）
- ❌ 页头「提交示例扫描任务」调试按钮（硬编码 `datasource_id: 1`）（S2#21）
- ❌ 页脚常驻开发枚举说明 `pending / running / success / failed / cancelled / timeout`（S2#21）
- ❌ 无效轮询每 3s 重复请求（S2#24）
- ❌ 任务 ID 列显示「#3 复制」，复制图标与 ID 挤在一起像操作文案（S3#32）
- ❌ 重试后提示「已提交重试，新任务 {id}」，但新任务号不可点
- ✅ 取消有 `ConfirmDanger`

**变更归属**：G1 + L（移除调试元素、删死轮询、重试后给链接）

### 14. 任务详情 `/app/tasks/:id`
- ❌「触发方式」显示 **`TriggerType.MANUAL`**——Python 枚举 repr 泄漏到 UI（S1#9，本页最刺眼）
- ❌「范围 scope」是 JSON `{"datasourceId": 3}`；「执行结果 / 日志（stats）」是 `{"Attempts":1,"SubmittedBy":null}`（含 PascalCase 字段名）——两者都该是语义化展示（S1#11）
- ❌ 无返回列表、无跳触发源数据源
- ✅「错误信息」写得好：「数据源 ds_pg_01 未指定目标数据库：scan_config.database 为空，且未通过 database= 显式传入。」——这是全站最好的错误文案，可作为其他错误提示的模板

**变更归属**：G1/G2 + L（stats 语义化拆分）

### 15. 审计日志 `/app/tasks/audit`
- ❌ 行高被内嵌 JSON 撑到 ~145px，一屏 2–3 条，`limit` 硬编码 200、无分页无总数（S2#17）
- ❌「操作者」列全为 `-`；「动作」`task.failure`、「结果」`failed/ok/accepted` 原始英文（S1#9）
- ❌ 页脚开发说明（S2#21）
- ❌ `rowKey` 用数组下标触发 antd 废弃告警（S3#27）
- ❌ 筛选「动作」placeholder 写「如 task.cancel」，要求用户知道内部动作码
- ❌ 无入口（S2#16）

**变更归属**：G1/G4 + L（详情列改抽屉、补分页）

### 16. 分区状态 `/app/tasks/partitions`
- ❌ 正文 Alert 是英文（S2#18）
- ❌ `RANGE`/`database` 原始值
- ❌ 无筛选、无分页、无入口

**变更归属**：G1/G4 + L（文案中文化）

### 17. 平台健康与指标 `/app/system`
- ❌「运行时指标（**原始**）」标题自带"原始"，内容是一段 JSON——把开发视图直接给了用户（S1#11）
- ❌ 组件状态 `healthy`/`ok`/`running` 原始英文（S1#9）
- ❌ 空态是纯文本（S2#25）；无手动刷新按钮（只有 30s 轮询）
- ❌ 无菜单入口（S2#16）

**变更归属**：G1/G4 + L（指标改结构化卡片 + 补刷新）

### 18. 业务术语表 `/app/business/terms`
- ❌ **无筛选、无搜索、无排序、无分页**（`fetcher` 一次性拉全量并返回 `next_cursor: null`，却仍显示"没有更多数据"）
- ❌ 新增表单「状态」是普通 `Input`，placeholder 写 `active`（S2#19）
- ❌ 无编辑/删除/详情，列表行不可点
- ❌ 无错误态分支（S2#25）
- ❌ 列表内容全是 `seed_code_1`/`seed_name_1`（演示数据，非 UI 问题但影响评审印象）

**变更归属**：G1 + L（补筛选、状态改 Select、错误态）

### 19. 审批流 `/app/governance/approvals`
- ❌ **「通过/驳回」点击导致整站白屏**（S0#2）
- ❌「动作」「发起人」「审批人」三列恒为空（S1#6，实测确认）
- ❌ 决策无二次确认（S1#8）
- ❌「资源」`seed.schema.tbl1` 不可点（应为可点资产链接）；提交审批弹窗「资源类型」是自由文本「如 table」、「动作」选项是原始英文
- ❌ 详情抽屉数据来自列表行（不发请求）、评论无时间戳、作者硬编码 `console`、一个 TextArea 兼两职（S3#33）
- ❌ 无区分"我发起的/我审批的"

**变更归属**：G3（致命）+ G1/G2 + L（抽屉改造、弹窗字段）

### 20. 工单 `/app/governance/tickets`
- ❌ **「流转」点击导致整站白屏**（S0#3）
- ❌ 表格横向溢出，流转控件被裁切（S2#20）
- ❌「分派」用 `window.prompt`（S1#8）
- ❌「类型」`data_issue`、「优先级」`P2` 原始值；「关联 FQN」不可点
- ❌ SLA 用 `Input type="number"`（S2#19）；无 SLA 超期高亮/排序
- ❌ `change_auto` 自动工单不回跳触发它的变更（FR-17.7 的闭环缺失）

**变更归属**：G3（致命）+ G1/G2 + L（表格 scroll、分派改造）

### 21. 降级占位页 `DegradedPage`（25 个路由复用）
- ❌ 文案面向开发者（`MOD-07 的接口尚未在后端落地…`）（S3#29）
- ❌ 面包屑「首页」不可点（S2#15）
- ❌ 被侧边栏 6 个一级菜单当作正常入口（S1#13）——这才是问题所在：占位页本身做得不算差，是**导航把它暴露成了主入口**

**变更归属**：G4（主）+ L（文案）

---

## 六、已确认可保留的设计取舍

以下几项看起来可疑，但经核实是刻意设计，**下一轮审计不必重复提出**：

1. **keyset 游标分页无页码**（ADR-5，千万级数据下禁用深 OFFSET）——合理。但需补"还有更多/总数"的感知（S2#22）。
2. **「允许写权限」默认关闭且需显式勾选**（FR-1.5 只读平台安全策略）——刻意为之，扫描弹窗的解释文案写得好，保留。
3. **未上线模块以「该能力暂不可用」占位而非报错**（FE-00 §1.2 原则④"降级可视"）——合理，只需修导航暴露方式与文案措辞。
4. **登录降级（MOD-11 未上线，任意账号可进）**——`LoginPage` 注释已说明是为将来接真实接口保留表单结构。可保留，但「跳过登录（dev）」入口建议收进 `import.meta.env.DEV`。
5. **原生 JSON 全量展示**（`JsonView`）——调试期形态，`ux-audit-datasources.md` 已记录。本期建议只做"折叠到高级信息"，不删除（排查问题时仍需要）。
6. **权限码为空时放行全部菜单**（MOD-11 缺席的降级语义，FE-00 §7）——合理。
7. **`DataTable` 默认 `size="small"`**——后台系统信息密度取向，保留。

---

## 七、验证方式

### 复现本次发现的问题

```bash
# 0) 前置：Postgres 已启动、后端与前端分别在 8090 / 5173
.\start-backend.ps1
.\start-frontend.ps1

# 1) 全站走查（21 个场景，产出截图 + 控制台/网络报告）
python "C:/Users/jinwa/.claude/skills/ux-page-audit/scripts/audit.py" \
  --plan .playwright-mcp/ux-audit/plan-full.json --out .playwright-mcp/ux-audit/full

# 2) 针对性交互验证（筛选逐字符发请求、横向溢出、删除/审批有无二次确认）
.venv\Scripts\python.exe .playwright-mcp/ux-audit/probe2.py

# 3) 复现两个白屏崩溃（会打印 pageerror 与 root 长度变化）
.venv\Scripts\python.exe .playwright-mcp/ux-audit/probe3.py   # 审批「通过」
.venv\Scripts\python.exe .playwright-mcp/ux-audit/probe4.py   # 工单「流转」

# 4) 表格列内容提取（验证"某些列恒为空"）
.venv\Scripts\python.exe .playwright-mcp/ux-audit/probe5.py
```

后端契约问题可脱离前端直接验证：

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8090/api/v1/assets/5           # 404 → S0#1
curl -s -X POST -H "Content-Type: application/json" \
  http://127.0.0.1:8090/api/v1/governance/approvals/6/approve                            # 422 → S0#2
curl -s http://127.0.0.1:8090/api/v1/catalog/overview | python -m json.tool              # 无数据源计数、grade key 为 "1"
```

### 修完之后怎么确认

1. 重跑 `audit.py` + `check_all_pages.py`，要求：`pageerrors` 全 0、非预期 404 全 0、无 antd 废弃告警。
2. 重跑 `probe2.py`：`filterbar_requests_while_typing_7_chars` 应从 **7** 降到 1–2；`subscription_delete.confirm_dialog_count` 应为 **≥1**；`horizontal_overflow.tickets.clipped` 应为 **[]**。
3. 重跑 `probe3.py`/`probe4.py`：点「通过」「流转」后 `root_after` 不应为 0，应出现成功提示且行状态更新。
4. 逐页对照 FE-01 的逐页规格自查（尤其是四态齐备、危险操作确认、时间格式 `YYYY-MM-DD HH:mm`）。
5. 人工复走三条主线旅程，要求全程不出现英文枚举、裸数字 ID、`{}` 空块。

---

## 八、建议实施顺序

| 阶段 | 内容 | 覆盖问题 |
|---|---|---|
| **P0（半天，止血）** | G3：修 3 个接口契约 + 加 `ErrorBoundary` + `client.ts` 错误归一 | S0#2、S0#3、S1#7/S1#8（同类防护） |
| **P1（1 天，恢复核心旅程）** | B1 + 资产目录/表详情/字段详情改造（路由改 FQN、名称可点、类型列、字段表格、分层展示） | S0#1、S2#22、部分 S1#11 |
| **P2（2 天，信息可信）** | 首页指标（B3 + `—` 语义）、审批三列表（B4）、变更详情 diff、数据源 ID→名称、订阅删除确认 | S1#4~#7、S1#10、S1#12 |
| **P3（2 天，语义与导航）** | G1 字典层全量替换 + G4 导航重组 + 面包屑 | S1#9、S1#13、S2#15/#16/#26 |
| **P4（1.5 天，清理）** | 审计日志改造、任务页调试元素、Toast/空态统一、分区页中文化、`FilterBar` 防抖 | S1#14、S2#17~#25、S3 全部 |
| **P5（可选）** | G5 视觉收敛（内容最大宽度、详情页 Tabs 化、状态色语义、间距节奏） | 观感类 |

**一句话给决策者**：不需要重做视觉，需要补一层「业务语义 + 实体链路 + 错误兜底」。P0+P1 各半天到一天，就能让产品从"演示会白屏、核心页面打不开"回到"能正常演示"。

---

## 九、修复收敛记录（2026-10-04）

本审计出的问题按第八节顺序推进，以下为已落地的部分。**下一轮审计不必重复提出**。

### 已修复：P0（止血，G3）

| 项 | 处置 |
|---|---|
| S0#2 审批决策白屏 | `api/governance.ts` 改发 `{actor, comment}`；后端 `DecisionRequest` 兼容旧名 `decided_by`/`decision_note` |
| S0#3 工单流转白屏 | 改发 `{to_status, actor}`；后端 `TransitionRequest` 兼容旧名 `status` |
| G3 错误兜底 | 新增 `web/src/api/errors.ts`（detail 数组/对象 → 一行中文）+ `web/src/components/ErrorBoundary.tsx`（挂 `AppShell` 的 `Outlet` 与 `/app` 路由外两层） |
| 后端错误归一 | `api/app.py` 注册 `RequestValidationError` 处理器，422 `detail` 统一为字符串，如「请求参数有误：actor：缺少必填字段」 |
| S1#7 订阅删除无确认 | 删除改走 `ConfirmDanger`，文案说明"将不再收到该范围的通知" |
| S1#8 决策/流转无确认 | 审批行内与抽屉的「通过/驳回」加 `ConfirmDanger`；工单「流转」改为「确认流转」Modal，选中不再即提交 |

验收：probe3（审批）`root` 37010→37233、probe4（工单）38638→38799，`pageerror` 均为 0；probe2 `subscription_delete.confirm_dialog_count` 由 0 → 1。

### 已修复：P1（恢复核心旅程，B1）

| 项 | 处置 |
|---|---|
| S0#1 资产详情 404 | 路由由 `/app/catalog/tables/:id` 改为 `/app/catalog/tables?fqn=`、字段同理 `?fqn=&parent=`；新增 `web/src/utils/assets.ts` 作为**唯一**跳转入口（AppShell 全局搜索、目录列表、表详情字段名、字段详情面包屑全部改用它） |
| 字段级详情 | 后端 `SqlCatalogProvider` 增加按字段 FQN 的回退查询，`AssetDetail` 补 `parentFqn/dataType/nullable/datasourceId/gradeLevel`，`/assets/{fqn}` 现在表与字段都可用 |
| 资产目录类型列空 | 取 `entityType`（原取 `type`）；渲染中文 Tag「表 / 字段」 |
| 表/字段混排难分辨 | 名称列加类型图标；新增「所属表」列（字段行可点回父表） |
| S1#11 字段用 JSON 铺开 | 表详情字段改为表格（字段名 / 类型 / 可空 / 说明，敏感列打标），每个字段名可点进字段详情；原始响应收进「原始响应（调试用）」折叠面板 |
| 详情页空值 | 分级/负责人/数据源/标签在缺失时整行不渲染，不再出现空 Tag 或 `-` |

验收：`.playwright-mcp/ux-audit/probe6.py` 复走「目录 → 点名称 → 表详情 → 点字段 → 字段详情」，`pageerror` 0、非预期 4xx 0，字段详情显示「数据类型 BIGINT / 可空 否 / 所属表 local_ingestion.public.account」。

### 已修复：P2（信息可信）

| 项 | 处置 |
|---|---|
| S1#4 首页数据源恒为 0（B3） | 后端 `CatalogStatsSource` 新增 `count_datasources()`，`CatalogOverview` 补 `datasources_count`；前端字段缺失时显示 `—` 而不是 0 |
| S1#5 分级分布全为 0（B3） | 分级键统一为 `L1..L4` + `ungraded`（新增 `grade_key()`：越界值如 5 归入未分级而不是被丢弃）；前端 `normalizeGradeDist` 双向兼容数字键，并新增「未分级」行；分母改用分级桶之和 |
| S1#6 审批三列恒为空（B4） | 前端改取后端实际字段 `action_type` / `requested_by` / `approver`；抽屉「决策意见」改取 `decided_comment`；`types/index.ts` 同步标注 |
| S1#10 数据源裸数字 ID | 新增 `web/src/hooks/useDatasourceName.ts`（一次拉全量做 id→名称缓存）；接入任务列表、变更统计、订阅、表/字段详情；变更统计的 `unknown` 不再用满格绿色 |
| S1#12 变更详情 before/after 为空 `{}` | 详情改为**字段级 diff 表**（属性 / 变更前 / 变更后 / 变化类型），只列变化行；无明细时给明确空态而非两个 `{}`；标题改为「变更类型 · 实体 FQN」，实体 FQN 可点进资产详情并附「变更历史」 |

验收（`.playwright-mcp/ux-audit/probe7.py`）：首页显示「数据源 3 / 表 253 / 字段 2,635 / L1 2791(97%) / L3 91(3%) / 未分级 4」；审批列表动作 `publish`、发起人 `alice`（原为空）；任务列表数据源列显示 `pg_local`（原为裸数字）；`pageerror` 0、非预期 4xx 0。

### 仍待处理（属 P3–P4，未动）

- **S1#12 的上游缺口**：库里所有 `change_event.before_json` / `after_json` 均为 null —— src 中没有任何生产者把 `SchemaDiffer` 的结果写进这两个字段（变更事件当前只由演示数据/外部写入产生）。前端 diff 视图已就位，但要真正看到字段级 diff，需要先把 MOD-06 的「diff → change_event 落库」链路接通，建议单开一项。
- 英文枚举直出（G1 字典层）、导航重组（G4）、面包屑（S2#15）
- `FilterBar` 防抖（S1#14，实测仍为 7 次请求）、审计日志与调试元素清理（S2#17/#21）

### 新发现（非 UI，需决策）

- `tests/unit/platform/test_governance.py` 断言 `open→resolved`、`in_progress→closed` 应为 422，但 `models.TICKET_TRANSITIONS` 明确允许这两条转移——是测试过期还是状态机定义需收紧，需确认后统一。
- `tests/unit/platform/test_changes.py::test_changes_rest_flow` 断言 `count == 1` 实际为 4，系 router 模块级 `_state` 跨用例复用导致的污染，需给测试加隔离。
