# 项目进度快照（换电脑续接用）

> 用途：记录截至 **2026-10-01** 的真实仓库状态、已完成任务、环境要点与下一步，方便在新机器上 clone 后无缝续接。
> 本文件是「快照」，不是规划。规划以 `00-implementation-plan.md` / `03-roadmap-and-open-questions.md` 为准；关键决策以 `02-decisions.md` 为准。

---

## 0. 仓库现状（权威事实，来自 git）

| 项 | 值 |
|---|---|
| 远程仓库 | `https://github.com/baochao1/local_ingestion`（origin） |
| 当前分支 | `main`，已跟踪 `origin/main` |
| HEAD | `d9c58b9` T-110: entity identity stability (FR-13) |
| 工作区 | **含未提交 WIP**：T-107 编排底座 + T-109 数据源管控 API（19 单测）+ Batch1（T-201/T-202 Diff 引擎 10 单测、T-211 全局检索 9 单测、T-203 订阅与通知 10 单测、T-212 资产详情 4 单测、T-204 变更确认 9 单测、T-213 概览统计 4 单测、T-205 血缘影响面占位 3 单测、T-214 业务元数据 4 单测、T-215 占位降级 3 单测）已实现；全量 906 passed |

**提交历史（新 → 旧）**：

```
d9c58b9  T-110  实体身份稳定 (FR-13)        —— 新增 platform/identity.py
86b9434  T-115  DatabasePipeline transform 钩子补齐（修 MOD-02 7.1-2）
7f7b423  T-105  新增 PostgresSink（批量 upsert 入 catalog_*）
d364055  T-114  Dialect 抽象（L3 旁路，不动 L1 连接器）
14b01f1  init   元数据治理平台脚手架（含大量地基，见下方「已落地」）
```

> `14b01f1` 是巨型初始提交，Batch 0 的核心地基（ORM、alembic、凭据加密、分页/序列化、监控修复）均包含其中，并非「未做」。

---

## 1. 任务完成矩阵（Batch 0：T-101 ~ T-115）

| 任务 | 内容 | 状态 | 落点 |
|---|---|---|---|
| T-101 | 工程基建与测试环境 | ✅ 已落地 | init（依赖已写入 pyproject；`scan.py:142` 导入错误已修） |
| T-102 | Alembic 与迁移规范 | ✅ 已落地 | init（`migrations/env.py` `compare_comments=False`；`0001_initial.py`） |
| T-103 | ORM：数据源与凭据 | ✅ 已落地 | init（`platform/storage/`） |
| T-104 | ORM：核心元数据 `catalog_*` + `struct_hash` | ✅ 已落地 | init |
| T-105 | PostgresSink 批量 upsert | ✅ 已提交 | `7f7b423`（`platform/sinks/`） |
| T-106 | ORM：平台基础表（含按月分区表） | ✅ 已落地 | init（0001 建 37 表 + 6 分区表） |
| T-107 | 任务编排底座 (MOD-10) | ✅ **已实现（未提交）** | `platform/orchestration/`：`TaskService`/`AuditService`/`LockProvider`/`ConcurrencyLimiter`/`RetryPolicy`/`HandlerRegistry`/`DependencyRegistry` + 内存/Sql 存储，15 单测 |
| T-108 | 凭据加密与连接供给 (MOD-01) | ✅ 已落地 | init（`platform/credentials.py` AES-256-GCM、`connections.py` ConnectionProvider + 只读校验） |
| T-109 | 数据源管控 API (MOD-01) | ✅ **已实现（未提交）** | `platform/datasource/`（服务+仓储+Schema）+ `platform/api/routers/datasources.py`（挂载至 `api/app.py`）；CRUD/连通性/只读校验/凭据多版本/软删异步任务/审计/健康 + 19 单测 |
| T-110 | 实体身份稳定 (FR-13) | ✅ 已提交 | `d9c58b9`（`platform/identity.py`：稳定 ID、改名检测、entity_alias、孤儿标记） |
| T-111 | 分页与 API 公共组件 | ✅ 已落地 | init（`platform/api/pagination.py`，keyset 游标 `base64(fqn\|id)`） |
| T-112 | API 序列化层（camelCase⇄snake_case） | ✅ 已落地 | init（`platform/api/serialization.py`） |
| T-113 | 造数脚本（性能验证） | ✅ 已落地（未提交） | CLI `seed` 子命令（`cli/main.py`）+ `platform/storage/seed.py`（分级造数）+ `schema.py`（建表/drop/测试分区）；档位 smoke/dev/perf |
| T-114 | 元数据抽取 Dialect 抽象 (FR-2.4) | ✅ 已提交 | `d364055`（`platform/dialect/`，PG/MySQL/Snowflake） |
| T-115 | DatabasePipeline transform 钩子补齐 | ✅ 已提交 | `86b9434` |

**结论**：Batch 0 全部落地（**T-113 造数脚本已实现，未提交**）。T-107/T-109 已实现（未提交）。Batch 1（**T-201–T-215 全部**）已实现（未提交）。**端到端串联已用本地 PG（postgres:17 容器）+ 集成测试验证**：造数 → Diff(T-201) → 分级(T-202) → 变更持久化(T-204) → 确认闭环 → 升级通知（复用 T-203 aggregator）→ 概览统计(T-213)，并经 T-107 编排依赖链贯通；`tests/integration/test_pg_integration.py`（需 `PG_TEST=1`）4 个用例全绿，全量单测 906 passed。其余均已在仓库中。

---

## 2. 下一步（建议顺序）

1. **T-107 任务编排底座（MOD-10）已落地（未提交）** —— 验收点全覆盖：重入保护、手动触发/取消/重试、全局+每数据源并发上限、指数退避重试、依赖链（扫描→Diff→通知）、审计留痕、历史查询。
2. **T-109 数据源管控 API（MOD-01）已落地（未提交）** —— CRUD/连通性测试/只读校验/凭据多版本/软删异步清理任务/审计/健康度，已挂载 `api/app.py` 路由；19 单测。
3. **Batch 1 核心已落地（未提交）**：
   - B1a：T-201 Diff 引擎 + T-202 变更分级（`platform/versioning/`，复用 identity 重命名识别；10 单测）。
   - B1b：T-211 全局检索（`platform/search/`，评分/过滤/分页；9 单测）。
   - B1a：T-203 订阅管理 + 通知聚合去重 + 静默（`platform/notify/`，复用 `integrations.notifications` 多渠道；10 单测）。
   - B1b：T-212 资产详情聚合（`platform/asset/`，并发取数 + 占位降级；4 单测）。
   - B1a：T-204 变更确认闭环 + 升级通知 + 变更统计（`platform/changes/`，复用 T-203 aggregator 与 T-107 审计；9 单测）。
   - B1b：T-213 概览统计（`platform/catalog/`，TTL 缓存 + 变更趋势复用 T-204，质量源降级；4 单测）。
   - B1a：T-205 血缘影响面占位（`platform/lineage/`，MOD-07 未上线降级为直接责任人，contract C7；3 单测）。
   - B1b：T-214 业务元数据（`platform/business/`，术语表 + 实体业务元数据 + `business.*` 标签，独立表不污染 catalog；4 单测）。
   - B1a：T-215 占位与降级（`platform/resilience` + `platform/degrade/`，MOD-07/08/11 依赖可降级注册表；3 单测）。
4. **Batch 1（T-201–T-215）已全部落地（未提交）**；**T-113 造数脚本已实现（未提交）**；端到端串联已用 PG 集成测试验证（`tests/integration/test_pg_integration.py`，需 `PG_TEST=1`），修复了 `change_event` 复合主键/时区/约束三处 PG 兼容性缺陷。
5. 剩余可选工作：① 提交本轮及之前批次成果；② 真实数据源端到端（T-105/T-115 连接器链路）串联；③ 性能压测（dev/perf 档，已达 30w 表/1000w 列目标）。

---

## 2.5 MOD-07 血缘分析 实现状态（2026-10-05, 分支 `feat/mod07-mod08-lineage-permission`）

T-205 占位（`PlaceHolderLineageService` 恒返回 `degraded=True`）已**替换为生产级实现**。DDL/ORM/方言 SQL 早已就绪，本次补齐采集器 + 落库 + 查询 + 接口。

**新增/修改文件**
- `platform/dialect/{base,postgres,mysql,snowflake}.py`：新增 `view_definition_sql()`（取视图定义，参数化 `:schema`）。
- `platform/lineage/parse.py`：sqlglot 表级 + 列级血缘解析（FQN 限定，缺省回退视图 db/schema）。
- `platform/lineage/repository.py`：边表幂等 upsert（唯一索引）、闭包表带环检测/深度上限的递归 CTE 重建、walk/列表查询。
- `platform/lineage/collector.py`：ADMIN 只读连接拉取视图定义 → 解析 → 落边（单视图失败隔离，从不写业务库）。
- `platform/lineage/service.py` + `models.py`：`LineageService.upstream/downstream/impact`（由预计算闭包回答），彻底移除降级占位。
- `platform/lineage/tasks.py`：注册 `lineage.collect` / `lineage.closure.rebuild` 处理器，依赖链 `metadata(scan) → lineage.collect → lineage.closure.rebuild`。
- `platform/orchestration/service.py`：新增公开 `register_handler` / `add_dependency` / `registered_handlers`。
- `api/routers/lineage.py`：扩展为 8 端点（upstream / downstream / impact / parse / edges 增删 / import / closure/rebuild）。
- `pyproject.toml`：新增依赖 `sqlglot>=25.0`（纯 Python，无 JVM）。

**测试**：`tests/unit/platform/lineage/{test_parse,test_repository,test_collector,test_service,test_tasks}.py` + `tests/unit/api/test_lineage_api.py` + `tests/integration/test_lineage_pg.py`（建真实视图跑端到端）。全绿（需 `PG_TEST=1`；`fastapi`/`sqlglot` 在 `.venv` 内）。

**竞品对齐（OpenMetadata/DataHub/Atlas）**：列级血缘（DataHub 式 SQL 解析）、手动/外部血缘标注（OpenMetadata）、影响面聚合数据源（Atlas）。**FR-4.1~4.6、FR-16.5 部分**已覆盖。已知缺口：巨视图列级解析超时保护、跨 schema 多 schema 批量采集（当前按 `scan_config.schemas` 遍历，缺省 public）——列为后续增强。

> 注：本文档其余部分为更早的快照（HEAD `d9c58b9`，906 用例）；本分支在此基础上新增上述 MOD-07 工作，尚未并入 `main`。

---

## 2.6 MOD-08 账号权限分析 实现状态（2026-10-05, 分支 `feat/mod07-mod08-lineage-permission`）

DDL/ORM/方言 SQL 已就绪，本次补齐采集器 + 落库 + 风险识别 + 查询 + 接口，**接口由 0/9 落地为 9+ 端点**。

**新增/修改文件**
- `platform/dialect/{base,postgres,mysql,snowflake}.py`：扩展 `list_accounts_sql`（**统一四列契约 `(name, host, is_super, is_locked)`**；PG 取 `rolsuper`，MySQL 取真实列 `Super_priv`——注意 `mysql.user` **没有** `is_super` 列，早期版本因此会在 MySQL 上直接报错）、`list_grants_sql`（统一 `(grantee, object_type, object_fqn, privilege, grantable)` 五列，表级+列级合并）。PostgreSQL/MySQL 均走 `information_schema` SELECT；**Snowflake 显式抛 `NotImplementedError` 拒绝采集**——`SHOW USERS` 无法包 SELECT 且列位与契约不符，按位取值会把 `CREATED_ON` 当成 host、凭空造出 `ALICE@2024-01-01` 这类假账号。
- `platform/permission/risk.py`：风险识别引擎（超管 / 过度授权 / 僵尸 / 无主 / 高敏资产授权）。
- `platform/permission/repository.py`：`account`/`account_grant` 幂等 upsert、`baseline` 快照存于 `datasource.scan_config`、变更 diff。
- `platform/permission/collector.py`：ADMIN 只读拉取账号/授权 → 落库 + 风险计算（单查询失败隔离，绝不写业务库）。
- `platform/permission/service.py`：`matrix`/实体授权/风险/变更/导出。
- `platform/permission/tasks.py`：注册 `permission.collect`（`ADMIN` 只读，独立触发，不挂 scan 依赖链）。
- `api/routers/permissions.py` + `api/app.py`：9 端点（accounts / accounts/{account}/grants / matrix / entities/grants / risks / risks/{id}/ack / changes / baseline/refresh / tasks / export）。

**测试**：`tests/unit/platform/permission/{test_risk,test_repository,test_collector,test_service,test_tasks,test_api}.py` + `tests/integration/test_permission_pg.py`（建真实角色+授权跑端到端）。

**竞品对齐（Atlas/Collibra/Alation + GB/T 43697/等保/DCMM）**：超管/过度授权/僵尸/无主识别、高敏资产授权重点标注、权限基线对比与变更追踪、合规报表导出。

**风险 ack 已闭环**：风险项带内容派生稳定 `id`（`type|account|object_fqn|privilege` 的 md5 前 12 位），`POST /api/v1/permissions/risks/{id}/ack` 将 ack 集合写入 `datasource.scan_config.acked_risks`，`risks()` 回填 `acked` 标志；已补单元 + API 测试。

**高敏规则已接线**：`PermissionQueryService._grade_lookup()` 从 MOD-05 的 `catalog_table`/`catalog_column.grade_level` 读取分级，注册所有点号后缀以匹配方言短名（PG 授权里是 `schema.table` 而 catalog FQN 是全限定），取冲突时的最高级。此前 `grade_lookup` 恒为空，`high_sensitivity` 风险永不触发——现已修复并补测试。

**已知缺口（写入计划 `2026-10-05-mod08-permission.md` 自审）**：① Snowflake 账号/授权采集暂不支持（后续需 `SNOWFLAKE.ACCOUNT_USAGE.USERS` + `GRANTS_TO_USERS` 角色→用户展开判定 `is_super`，待有真实 Snowflake 账号验证后再实现，当前拒绝而非产出脏数据）；② PG `last_login` 原生缺失（best-effort，无登录记录者标为僵尸），生产环境建议接入 `pg_stat_statements`/审计日志或外部 IAM；③ MySQL 同名账号 `host` 区分已通过 `'user'@'host'` 归一化；④ 责任人关联（MOD-11）降级处理（`evaluate_risks(orphan_check=...)` 钩子已就绪，待 MOD-11 用户映射接线后启用）。

---

## 3. 换电脑环境搭建（必读）

```bash
# 1) 拉取
git clone https://github.com/baochao1/local_ingestion
cd local-ingestion

# 2) 安装（含 dev/test 依赖：cryptography>=42 / aiohttp>=3.9 / pytest-asyncio>=0.21）
pip install -e ".[dev,test]"

# 3) 数据库（alembic 基线依赖一个真实 PG）
#    本地用 docker：容器名 li-pg，镜像 postgres:16，库名 ddlbasis
#    alembic 回放 0001 会建 37 表 + 6 分区表 + 初始 classification_tag(10)/classification_rule
alembic upgrade head
alembic check        # 期望：No new upgrade operations detected

# 4) 跑测试基线
pytest tests/unit -q   # 基线 869 passed（2026-10-01 实测，venv 隔离环境）
```

**依赖/环境坑（已踩过，务必注意）**：
- `pyproject` 声明了 `aiohttp` / `pytest-asyncio`，但**环境必须先 `pip install -e ".[test]"`**；否则 `tests/unit/integrations/` 收集失败、全量测试中断，会误以为通过。
- 加密依赖 `cryptography>=42`（T-108 引入），缺失会直接 import 失败。
- `struct_hash` 口径必须与 DDL 一致：**DDL 未插 tenant 种子行**，新库首次 `alembic upgrade head` 后无租户数据属正常。
- 当前（2026-10-01）激活的 Python 是 Codex 自带解释器，全局 `pip install` 会撞 `OpenAI\Codex\bin` 文件锁（`WinError 448`）；改用仓库内 `venv` 隔离（`python -m venv .venv` → `.venv\Scripts\python.exe -m pip install -e ".[dev,test]"` → 用 `.venv/.../pytest` 跑测试），`.venv/` 已在 `.gitignore`。

---

## 4. 关键架构约束（所有后续任务必须遵守）

1. 每张表只有一个 Owner 写者（总览 §4）。
2. `entity_tag` 按 `security.*` / `business.*` 命名空间隔离，互不覆盖。
3. 回写只更新自己负责的列，禁止整行覆盖（已用 T-105 的 `ON CONFLICT ... DO UPDATE` 限定列保障）。
4. 列表接口一律 keyset 分页（`platform/api/pagination.py` 已统一）。
5. **L3 代码不得修改 L1 文件**（`schema/`、`core/connectors/`、`core/pipeline/`）——T-114 的 Dialect 是「旁路新增」而非改 L1。
6. 千万级：批量 upsert、软删除 + 异步分批、快照走分区。

---

## 5. 已知修复（已合入 init，仅作回归提醒）

- `core/engine/monitor.py`：`WorkflowMonitor._lock` 由 `threading.Lock` 改为 `RLock`，修复 `track_workflow` 持锁后调 `_log` 再次加锁导致的**必现自锁死**。
- `observability/alerts.py`：`_process_alert` 去重键曾含 `timestamp` 导致每次评估都追加重复告警，已改为按 `rule_name` 去重并在 `resolve_alert` 释放占位。
- `cli/commands/scan.py:142`：导入名 `PostgreSQLSourceConnector` 应为 `PostgresSourceConnector`，已修正（`scan postgres` 不再崩溃）。
