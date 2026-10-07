# 实施计划 · 采样画像与画像可视化（FR-M1 + FR-M2）

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 编写日期 | 2026-10-05 |
| 生成方法 | Spec Kit `/speckit.plan` |
| 对应 Spec | `doc/requirement/05-1-profiling-spec.md`（v1.0） |
| 总纲 | `doc/requirement/05-openmetadata-migration-spec.md`（v1.1） |
| 范围 | 仅 FR-M1 + FR-M2。**不含** FR-M3/M4/M5/M6/M9（见 `05-2`~`05-4`） |
| 状态 | ⛔ **实施前必须通过 §1 门禁**，其中 G1 为法务阻塞 |

---

## 1. 准入门禁（Gate）

| # | 条件 | 现状 | 责任方 |
|---|---|---|---|
| ~~G1~~ | ~~OQ-0 法务结论~~ | ✅ **已解除**（用户声明学习用途、非商用，2026-10-05）。**保留义务**：每个移植文件标注上游来源与版本（D0/R-M4） | — |
| G2 | CI `boundary-check` / `upstream-drift` 建立 | ⬜ 未建立（`design/04` §7.3 已设计） | 工程 |
| G3 | 检索 P95 基线压测取得 | ➖ **本特性不依赖**（属 `05-2`） | — |
| G4 | 目标数据源只读账号就位 | ⬜ 待确认 | 运维 |
| **G5** | 本特性专项：PQ-1（采样分档阈值）、PQ-3（stats 体积上限）、PQ-4（图表库）已定 | ⬜ 未决 | 架构 + 前端 |

> **G1 未决时的降级路径**：若法务结论为"不可行"，本计划改为**纯思路自研**——不复制任何上游代码行，仅按其算法思路实现（Freedman–Diaconis 分桶、分档阈值、相对基数跳过）。功能范围不变，工作量上浮，且不建立 `upstream_manifest` 条目。

---

## 2. 现状落点（已核实，决定本计划的工作量）

| 能力 | 状态 | 证据 |
|---|---|---|
| 采样 SQL | ✅ **三方言均已实现** | `platform/dialect/postgres.py:167` `TABLESAMPLE BERNOULLI(pct)`；`snowflake.py:112` `TABLESAMPLE(pct)`；`mysql.py:112` `WHERE RAND() < rate` |
| 采样能力声明 | ✅ | `platform/dialect/base.py:74` `supports_sampling` |
| 当前画像表 | ✅ **字段完全对口** | `platform/storage/models_governance.py:26` —— `row_count`/`column_count`/`size_bytes`/`stats` JSONB/`sample_rate`/`sampled_rows`/`profiled_at`/`duration_ms`/`status`/`error_message`；唯一索引 `uq_profile_table` |
| 画像历史表 | ✅ **按日期 RANGE 分区** | `models_governance.py:143` —— 复合主键 `(id, profiled_date)`，`postgresql_partition_by: RANGE (profiled_date)` |
| 状态枚举 | ✅ 已含 `skipped` | `models_governance.py:46` —— `pending/running/success/failed/skipped`，正好对应"大表跳过" |
| 任务编排 | ✅ | `platform/orchestration/service.py:103` `submit` / `run_now` / `retry` / `cancel` |
| 前端图组件位置 | ✅ 有占位路由可替换 | `web/src/pages/placeholders/DegradedPage.tsx` |

**结论**：本特性**不需要新建任何数据库表**，也不需要新增采样 SQL。工作量集中在"执行器 + 呈现层"。

---

## 3. 架构决策

| # | 决策 | 理由 | 代价 |
|---|---|---|---|
| **D1** | 全部新增代码落在 `platform/profile/`（L3） | ADR-9 / PC4：`schema/`、`core/` 属 L1，不得修改 | 无 |
| **D2** | 复用 `Dialect.sample_sql(table, rate)` 作为**内联视图**，外层叠加聚合：`SELECT <aggs> FROM (<sample_sql>) AS _s` | 已有实现且三方言可用；不重复造采样 SQL | `sample_sql` 返回 `SELECT *`，作为子查询会带全列；见 D3 |
| **D3** | **全量时不套子查询**：`rate >= 1.0` 时直接对原表聚合 | `TABLESAMPLE BERNOULLI(100)` 语义正确但多余一层扫描；直接聚合更快 | 分支逻辑 |
| **D4** | 列级统计**一次 SQL 聚合多指标**，列数超阈值时分批 | 减少往返；避免每列一次查询 | 批大小需调 |
| **D5** | **直方图两阶段**：阶段一取 `count/min/max/IQR`，阶段二按算出的桶边界做分桶计数 | 桶边界依赖 IQR，无法一条 SQL 完成 | 两次查询 |
| **D6** | 分桶优先用库内函数（PG `width_bucket`），不支持时生成 `CASE WHEN`，**两者都不行才取样本到内存用纯 Python 统计** | PC3：`pandas` 不得升为运行时依赖 | 内存路径为最后手段，需限样本量 |
| **D7** | 分位数按方言查表覆写（近似函数优先），**结果中记录所用方法** | FR-M1.5 / AC-1.6；不同库精度不同，必须可追溯 | 需维护方言表 |
| **D8** | 写库：`TableProfile` 按 `table_id` **upsert**（唯一索引），同时写 `TableProfileHistory` | 当前态唯一 + 历史按日留存，两个表已为此设计 | 双写 |
| **D9** | 历史保留利用 RANGE 分区：按日期 `DROP/DETACH PARTITION` 清理 | `models_governance.py:155` 已按 `profiled_date` 分区，清理成本极低 | 需分区维护作业（待 PQ-2 定策略） |
| **D10** | 复用既有 `status` 枚举，不新增状态；"大表跳过"用 `skipped` | 枚举已含 `skipped`（`models_governance.py:46`） | 无 |
| **D11** | 任务接入既有 `platform/orchestration`，不自建调度 | 已有并发/重试/锁/取消（FR-M1.9） | 需按其 TaskService 契约实现 |
| **D12** | 前端图表库：**先用已装的 `@ant-design/charts`**；若直方图能力不足再引 ECharts，**禁止同时引入** | 总纲 A5 / PC4；已装但零 import 是浪费 | 待 PQ-4；可能二次切换 |
| **D13** | 采样标识符沿用现有约定：表名由调用方校验后传入，`rate` 以数值字面量渲染 | `dialect/base.py:81` 明确"table must be a caller-validated identifier" | 画像层必须保留标识符校验断言，防注入 |

---

## 4. 文件结构

```
src/local_ingestion/platform/profile/          # 新增（L3）
├── __init__.py
├── config.py          # 采样分档阈值、列数上限、直方图桶上限、大表跳过阈值、批大小
├── sampling.py        # 采样率决策 + 采样子查询构造（D2/D3）
├── metrics.py         # 列级统计项定义与聚合 SQL 构造（D4）
├── quantile.py        # 各方言分位数函数覆写表（D7）
├── histogram.py       # 桶边界计算（Freedman–Diaconis + 退化策略）+ 分桶 SQL 生成（D5/D6）
├── selector.py        # 采样列白/黑名单三级继承（FR-M1.7）
├── runner.py          # 画像执行编排：行数估算 → 采样 → 统计 → 直方图 → 落库
├── store.py           # TableProfile / TableProfileHistory 读写（D8）
└── tasks.py           # 接入 platform/orchestration 的任务定义（D11）

src/local_ingestion/platform/api/routers/
└── profiles.py        # 画像查询 / 触发接口（新增路由）

web/src/api/
└── profiles.ts        # 画像接口封装

web/src/pages/profile/
└── TableProfilePage.tsx   # 替换占位路由

web/src/components/profile/
├── ProfileSummary.tsx       # 表级概览（FR-M2.1）
├── ColumnStatsList.tsx      # 列级统计列表 + 采样标注（FR-M2.6）
└── ColumnHistogram.tsx      # 直方图（FR-M2.2）
```

**每个移植文件头部须记录**：来源文件路径 + 上游版本号（总纲 §2.3.5 / R-M4）。移植清单见 `05-1` 附录 A。

---

## 5. 实施步骤

### 阶段 1 · 算法层（可独立验证，不碰数据库）

| # | 任务 | 产出 | 验证 |
|---|---|---|---|
| 1.1 | `config.py`：采样分档阈值、桶上限、列数上限、跳过阈值 | 可配置常量 | 单测 |
| 1.2 | `histogram.py`：Freedman–Diaconis 桶宽 + IQR=0 退化 + Sturges 退化 + 桶数封顶 | 纯函数 `bin_edges(min,max,iqr,count)` | 单测覆盖 `05-1` E3/E5 |
| 1.3 | `quantile.py`：方言 → 分位数函数覆写表 | 查表函数 | 单测三方言 |
| 1.4 | `selector.py`：列白/黑名单三级继承（table → schema → database） | 解析函数 | 单测 |
| 1.5 | `sampling.py`：按行数分档决策 + 采样子查询构造（含全量直通分支） | `decide_rate(row_count)` / `build_sample_from(...)` | 单测 + SQL 快照断言 |

### 阶段 2 · 执行层（需真实数据源）

| # | 任务 | 产出 | 验证 |
|---|---|---|---|
| 2.1 | `metrics.py`：列级聚合 SQL 构造（分批） | SQL 构造 + 结果解析 | 集成测试（PG） |
| 2.2 | 行数估算：系统表优先，失败退化 `COUNT(*)`（记录降级原因） | 函数 | 集成测试，覆盖 `05-1` E2 |
| 2.3 | `store.py`：`TableProfile` upsert + `TableProfileHistory` 写入 | 读写函数 | 集成测试，覆盖 AC-1.5 |
| 2.4 | `runner.py`：编排全流程，含 `skipped`（大表）、失败原因记录、幂等 | 执行入口 | 集成测试，覆盖 E6/E8/E9/E10 |
| 2.5 | `tasks.py`：接入 `platform/orchestration` | 任务定义 | 集成测试，覆盖 FR-M1.9 |

### 阶段 3 · 接口与前端

| # | 任务 | 依赖 |
|---|---|---|
| 3.1 | `api/routers/profiles.py`：画像查询 / 触发（含二次确认提示所需信息） | 阶段 2 |
| 3.2 | `web/src/api/profiles.ts` + 三个画像组件 | PQ-4 已定（D12） |
| 3.3 | 替换占位路由，接入 `router.tsx` | 3.1 + 3.2 |
| 3.4 | 降级态：不支持采样 / 未采集 / 失败 的三种展示（FR-M2.4） | 3.3 |

---

## 6. 测试策略

| 层 | 内容 | 对应验收 |
|---|---|---|
| 单测（无 DB） | 分档决策、桶边界算法（含 IQR=0 与桶数封顶）、分位数方言表、列选择继承、stats 序列化 | AC-1.1 / AC-1.3 |
| 集成（PG，`PG_TEST=1`） | 混合类型表画像；**全量表的空值率与唯一值数与直接查询精确一致** | AC-1.2 |
| 只读验证 | 用只读账号完整跑通；断言期间无写语句 | AC-1.4（PC2） |
| 历史快照 | 连续两次画像后可查两次快照与差异 | AC-1.5 |
| 方言覆盖 | PG / MySQL / Snowflake 三方言的采样与分位数路径 | FR-M1.2 / FR-M1.5 |
| 回归 | 既有 754 单测全绿；`schema/`、`core/` 零改动 | NFR-M6 |
| 契约 | 统计结果中采样标记与分位数方法字段必存在 | AC-1.6 / FR-M1.10 |

---

## 7. 依赖

| 类型 | 项 | 说明 |
|---|---|---|
| 运行时新增依赖 | **无** | 只使用已有 `sqlalchemy`；`pandas` 不得升为运行时（PC3） |
| 前端 | `@ant-design/charts`（已装）或 ECharts（待 PQ-4，二选一） | 禁止同时引入 |
| 上游 | 仅移植算法与常量，不引包 | 总纲 §2.3.5 |

---

## 8. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| P1 | **法务（G1）未决** | 见 §1 降级路径；未决不启动 |
| P2 | `sample_sql` 用 f-string 拼表名，画像沿用会放大注入面 | D13：调用方校验标识符 + 画像层保留断言；测试覆盖恶意表名 |
| P3 | MySQL 无 `TABLESAMPLE`，`WHERE RAND() < rate` 需全表扫 | 对 MySQL 大表强制走 `skipped` 或降采样率；日志告警 |
| P4 | `stats` JSONB 膨胀（宽表 × 直方图） | NFR-M3 体积上限 + 超限降级（阈值待 PQ-3） |
| P5 | `TableProfileHistory` 分区未自动创建，写入会失败 | 需确认分区维护机制是否已有；若无，列入阶段 2 前置 |
| P6 | 两阶段直方图使查询数翻倍 | 阶段一结果可缓存复用；仅在需要直方图时执行阶段二 |
| P7 | 全量表精确性断言（AC-1.2）在并发写入下不稳定 | 只读账号 + 测试环境快照，避免读写并发 |

---

## 9. 待澄清对实施的影响

| 待澄清 | 阻塞的 step | 若未定的处理 |
|---|---|---|
| PQ-1 采样分档阈值 | 1.1 | 先按上游分档实现，阈值外置为配置项，后续可调 |
| PQ-2 历史保留策略 | 2.3 + D9 | 先只写不清理；分区维护机制确认后再加清理作业（P5） |
| PQ-3 stats 体积上限 | 1.1 | 先设保守默认值并记日志，超限降级 |
| PQ-4 图表库 | 3.2 | 按 D12 先用 `@ant-design/charts` |
| PQ-5 是否支持分区采样 | 2.2 | 先不支持；分区采集补齐后再评估 |
