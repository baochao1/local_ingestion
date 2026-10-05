# 数据源模块 交互可用性审计

> 审计方式：产品经理视角 + Nielsen 十项启发式，借助 Playwright 探针在真实页面上走查取证。
> 工具：`~/.claude/skills/ux-page-audit/`（本次新建的可复用 skill，含探针脚本）。
> 范围：列表 `/app/datasources` → 筛选 → 新建弹窗（空提交 / 试连）→ 扫描弹窗 → 详情 `/app/datasources/:id`。
> 证据：`.playwright-mcp/ux-audit/out*/`（截图）与 `report.json`（控制台错误 / 页面异常 / 失败请求）。

## 总体结论

数据源模块的主干流程（查看→新建→扫描→详情）整体可用，但存在 **1 个阻断性缺陷、2 个"操作静默无效/无防护"的严重问题**。
其中"筛选静默失效"和"停用无二次确认"最伤用户信任——前者让用户以为系统没数据、后者让一次误点直接改变线上状态。
本次已全部修复并回归验证。

## 问题清单与处理结果

| # | 严重度 | 问题 | 根因 | 处理 |
|---|--------|------|------|------|
| 1 | **S0 阻断** | 详情页整个崩溃白屏（`useState is not defined`） | `DataSourceDetailPage.tsx` 使用了 `useState` 却未 import | ✅ 已修（补 import，并合并重复的 antd import） |
| 2 | **S1 严重** | 「停用」是无二次确认的破坏性操作，误点即生效且无审计提示 | 列表页/详情页的启停按钮直接调 `disableDataSource`，未使用项目已有的 `ConfirmDanger` 组件 | ✅ 已修（两处均改用 `ConfirmDanger`，确认文案说明后果 + 「此操作将被审计」） |
| 3 | **S1 严重** | 「关键字」「类型」筛选**静默失效**：输入后点查询，列表毫无变化，用户会误以为没有数据 | 前端发 `keyword`/`dsType`，后端只接受 `type`，且后端根本没有 `keyword` 参数 | ✅ 已修（后端补 `keyword` 搜索 code/name；前端把 `dsType` 映射为 `type`） |
| 4 | **S1 严重** | 扫描被只读策略拒绝时，用户只看到 `500 Internal Server Error`，无法得知"勾选允许写权限即可" | `WriteAccessError` 未被捕获，冒泡成 500 | ✅ 已修（`scans.py` 捕获并返回 **400 + 可行动中文提示**） |
| 5 | S2 一般 | 「类型」筛选是自由文本输入，用户需回忆并手打类型名 | FilterBar 里 `type: 'text'`，而类型是有限集合 | ✅ 已修（改为下拉，选项复用 `DS_TYPES`） |
| 6 | S2 一般 | 筛选无结果时仍显示「暂无数据源」，误导用户以为系统里没数据，且无退出筛选的出口 | `empty` 未区分"无数据"与"无匹配" | ✅ 已修（区分两种文案；有筛选时提供「清除筛选」按钮） |
| 7 | S3 轻微 | `destroyOnClose` 已废弃，控制台告警 | `ScanModal.tsx` | ✅ 已修（改 `destroyOnHidden`，与新建弹窗一致） |
| 8 | S3 轻微 | `findDOMNode is deprecated` StrictMode 告警 | `DataSourceCreateModal.tsx` 用 Tooltip 包裹 Form.Item | ✅ 已修（改用 Form.Item 原生 `tooltip`） |

## 已确认可保留的设计取舍（不修，记录以免反复提出）

- **keyset 游标分页无页码**：性能与大数据量稳定性考量（ADR-5）。当前后端未实现游标分页，列表一次性返回并显示「已加载 N / N 条」，行为一致，非缺陷。
- **「允许写权限」默认关闭且需显式勾选**：安全策略 FR-1.5，刻意为之。本次只是把它的失败反馈从"500"改成"可行动提示"，策略本身不动。
- **详情页「原始配置」全量 JSON 展示**：开发/调试期形态；可作为后续打磨项折叠到「高级信息」。

## 验证结果

- 探针回归（`out4`）：6 个场景 **0 页面异常**；不再有 `destroyOnClose`/`findDOMNode` 告警；唯一的 4xx 是扫描场景**预期内**的只读策略拒绝（已带可行动文案）。
- 针对性验证：
  - 关键字筛选 `zzz_none` → 0 行 + 「没有匹配的数据源」+「清除筛选」；点清除后恢复 3 行。
  - 类型筛选选 `mysql` → 0 行（筛选真正生效）。
  - 点「停用」→ 弹出确认框：`停用数据源 / 停用后将不再对其执行扫描等操作：ds_pg_01 / 此操作将被审计`；取消不产生副作用（数据源仍为启用）。
  - 详情页正常渲染（标题 `pg_local`，按钮：立即扫描 / 立即分级 / 停用 / 刷新 / 复制）。
- 后端单测：`pytest -k "datasource or scan or repository"` → 41 passed, 9 skipped。
- 前端类型检查：`npm run typecheck` **全部通过（0 error）**。本轮的存量错误已一并修复：
  - `web/src/pages/governance/ApprovalsPage.tsx` — `toItems(data)` 漏传泛型，补 `toItems<ApprovalRequest>(data)`。
  - `web/src/api/subscriptions.ts` — `listSubscriptions` 未走 `cleanParams`，补齐以与其余 api 模块一致。

## 后续可做（未纳入本次）

- 后端为数据源列表补游标分页（`cursor`/`limit`），让「加载更多」可用。
