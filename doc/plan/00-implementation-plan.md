# 元数据治理平台 · 实施计划

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 编写日期 | 2026-09-30 |
| 来源 | `doc/design/00` ~ `04`、`MOD-01` ~ `MOD-11`；`doc/requirement/01` ~ `04` |
| 审核结论 | 见 `01-plan-review.md`（含 8 项修订，已并入本文） |
| 部署形态 | 单实例（Q11 已确认） |

---

## 0. 已完成基线

| 项 | 状态 |
|---|---|
| 需求梳理 FR-1 ~ FR-16 | ✅ `doc/requirement/01`、`04` |
| 数据模型设计 + 完整 DDL（约 36 表） | ✅ `doc/design/01`、`02` |
| 模块划分与跨模块契约 | ✅ `doc/design/00` |
| OpenMetadata 兼容策略（ADR-8/9） | ✅ `doc/design/03` |
| 代码边界拆分（5 项混杂） | ✅ `doc/design/04`，已实施 |
| L3 区雏形 `platform/sinks`、`platform/resilience` | ✅ 已建 |

**关键架构约束（所有任务必须遵守）**：

1. 每张表只有一个 Owner 写者（总览 §4）
2. `entity_tag` 按 `security.*` / `business.*` 命名空间隔离
3. 回写只更新自己负责的列，禁止整行覆盖
4. 列表接口一律 keyset 分页
5. L3 代码不得修改 L1 文件（`schema/`、`core/connectors/`、`core/pipeline/`）
6. 千万级：批量 upsert、软删除 + 异步分批、快照走分区

---

## 1. 批次总览

```
Batch 0  基建与地基        （阻塞一切）
   ├── Batch 1  版本 Diff + 检索（两者可并行）
   ├── Batch 2  采样 → 画像 → 分级（串行依赖）
   ├── Batch 3  血缘        （全程可并行，独立）
   ├── Batch 4  权限分析
   └── Batch 5  RBAC
```

| 批次 | 目标产出 | 依赖 |
|---|---|---|
| **B0** | 元数据能真正落库、任务能被统一调度、实体身份稳定 | 无 |
| **B1** | 变更可见可告警（B1a）；资产可检索可查看（B1b） | B0 |
| **B2** | 采样 → 画像/质量 → 分类分级 | B0（B2 内部串行） |
| **B3** | 血缘（可提前到 B0 之后任意时刻） | B0 |
| **B4** | 库内账号权限分析 | B0 |
| **B5** | 平台 RBAC | B0 |

---

## 2. Batch 0：基建与地基

### T-101 工程基建与测试环境

| 项 | 内容 |
|---|---|
| 目标 | 让测试可执行、CLI 可用、配置可管理 |
| 任务 | ① 补齐测试依赖（`pytest-asyncio`、`aiohttp`，已在 `pyproject.toml` 声明但环境未装）<br>② **修复 `cli/commands/scan.py:142` 导入错误**（`PostgreSQLSourceConnector` → `PostgresSourceConnector`，当前 `scan postgres` 必崩）<br>③ 配置管理：数据库连接串、凭据加密密钥（环境变量注入）、日志配置 |
| 依赖 | 无 |
| 验收 | `pytest tests/unit/integrations` 可收集；`local-ingest scan postgres --help` 可执行；配置项可通过环境变量覆盖 |
| 预估 | 0.5 天 |

### T-102 Alembic 与迁移规范

| 项 | 内容 |
|---|---|
| 目标 | 模型变更可追溯、可回滚 |
| 任务 | ① 初始化 Alembic<br>② **确立单一真相源：SQLAlchemy ORM 模型为准，Alembic autogenerate 生成迁移**（`02-schema-ddl.sql` 降级为设计参考快照，见审核 R1）<br>③ 分区表迁移规范：Alembic 对分区支持弱，分区创建与预建写成独立运维任务而非迁移内逻辑（见审核 R2）<br>④ 大表加索引统一用 `CREATE INDEX CONCURRENTLY`（不可在事务块内） |
| 依赖 | T-101 |
| 验收 | `alembic upgrade head` 可建库；`alembic downgrade` 可回滚；分区表有独立预建脚本 |
| 预估 | 1 天 |

### T-103 ORM：数据源与凭据

| 项 | 内容 |
|---|---|
| 目标 | MOD-01 的数据基础 |
| 涉及 | `datasource`、`datasource_credential` |
| 任务 | ORM 模型（含 `environment`/`group_name`/`owner_business`/`owner_technical`）；`credential_enc` 为 `LargeBinary` |
| 依赖 | T-102 |
| 验收 | 模型与 DDL 字段一致；迁移可生成 |
| 预估 | 0.5 天 |

### T-104 ORM：核心元数据 `catalog_*`

| 项 | 内容 |
|---|---|
| 目标 | MOD-02 的数据基础 |
| 涉及 | `catalog_database`、`catalog_schema`、`catalog_table`、`catalog_column`、`entity_alias` |
| 任务 | ORM 模型 + 索引（含 keyset 复合索引 `(fqn,id)`、`(datasource_id,fqn,id)`、trigram、GIN）+ `struct_hash` 计算逻辑 |
| 依赖 | T-102 |
| 验收 | 索引与设计文档 §6.1 一致；`struct_hash` 对相同结构稳定、对任何字段变更敏感 |
| 预估 | 1.5 天 |

### T-105 PostgresSink（批量 upsert）

| 项 | 内容 |
|---|---|
| 目标 | 元数据真正落库 |
| 任务 | ① 实现 `PostgresSink`（继承泛化后的 `SinkConnector`）<br>② `execute_values` + `ON CONFLICT (fqn) WHERE deleted_at IS NULL DO UPDATE`，5000–10000 行/批<br>③ **只更新本模块负责列**（保护 `grade_level`）<br>④ 同事务写 `columns_json` 冗余<br>⑤ 接入 `CheckpointStore`（可用 `FileCheckpointStore`） |
| 依赖 | T-104、T-111、**T-114** |
| 验收 | 批量写入生效（非逐条 INSERT）；不覆盖 `grade_level`；扫描可中断续跑 |
| 预估 | 1.5 天 |

### T-106 ORM：平台基础表

| 项 | 内容 |
|---|---|
| 涉及 | `scan_run`、`audit_log`、`notification_subscription`、`notification_log`、`sample_value`、`table_snapshot`、`column_snapshot`、`change_event`、`table_profile_history` |
| 任务 | ORM 模型；后 5 张为**按月 RANGE 分区表**（PK 须含分区键） |
| 依赖 | T-102 |
| 验收 | 分区表可建；按月分区可预建与 DROP |
| 预估 | 1 天 |

### T-107 任务编排底座（MOD-10）

| 项 | 内容 |
|---|---|
| 目标 | 所有任务型模块的公共底座（**必须与持久化同批**） |
| 任务 | ① 统一任务模型 `TaskSpec`/`TaskRun`（`scan_run`）<br>② 触发：手动 / 定时（复用 APScheduler）/ 事件<br>③ **重入保护**（单实例：进程内锁 + 状态校验），封装 `LockProvider` 预留扩展<br>④ 并发控制（全局 + 每数据源）<br>⑤ 重试与退避、取消、超时<br>⑥ 依赖编排（扫描 → Diff → 通知）<br>⑦ 审计接口 `AuditService.record` |
| 依赖 | T-106 |
| 验收 | 同任务不重复执行；并发上限生效；依赖链可串联；任务历史可查询 |
| 预估 | 2 天 |

### T-108 凭据加密与连接供给（MOD-01）

| 项 | 内容 |
|---|---|
| 任务 | ① AES-256-GCM 加解密，密钥来自环境变量/KMS，`enc_algo` 记录算法与密钥版本<br>② `ConnectionProvider.acquire(datasource_id, purpose)`，按 `purpose` 校验能力位，返回上下文管理器<br>③ **只读校验**：MySQL `SHOW GRANTS`、PG 角色与权限、Snowflake `SHOW GRANTS`；具备写权限默认拒绝<br>④ 每次获取留审计 |
| 依赖 | T-103 |
| 验收 | 库中无明文凭据；写权限连接被拒；轮换可回滚；审计有记录 |
| 预估 | 1.5 天 |

### T-109 数据源管控 API（MOD-01）

| 项 | 内容 |
|---|---|
| 任务 | 数据源 CRUD（软删除 + 异步分批清理）、连通性测试、启停、凭据版本管理、健康度查询 |
| 依赖 | T-103、T-108、T-111、**T-112** |
| 验收 | 见 MOD-01 §9；API 输出 camelCase |
| 预估 | 1.5 天 |

### T-110 实体身份稳定（FR-13）

| 项 | 内容 |
|---|---|
| 目标 | 改名不被误判为删+增（**B1a 的前置**） |
| 任务 | ① 稳定 ID 策略，`fqn` 仅作当前名称<br>② 表改名检测：同 schema 内字段集合重合度（阈值 0.8）+ 名称相似度<br>③ 字段改名检测：类型 + 位置 + 名称相似度<br>④ 置信度分级：高置信自动采纳，中低置信标记待确认<br>⑤ 历史名写入 `entity_alias`；血缘边以 `entity_id` 为主<br>⑥ 孤儿标记（不立即删除） |
| 依赖 | T-104、T-105 |
| 验收 | 改名被识别为改名；血缘与标签保持；中低置信进确认队列 |
| 预估 | 2 天 |

### T-111 分页与 API 公共组件（横切）

| 项 | 内容 |
|---|---|
| 目标 | keyset 分页与响应契约统一（**必须前置**，否则各模块各写各的，后期难收敛） |
| 任务 | ① 游标编解码 `base64(fqn|id)`<br>② 统一响应：`items` + `next_cursor` + `has_more` + `approx_total`（`reltuples` 近似值）<br>③ 排序键与索引前缀一致性校验（开发期断言）<br>④ 模糊搜索深度上限（1000 条） |
| 依赖 | 无 |
| 验收 | 所有列表接口返回统一结构；深分页无 OFFSET |
| 预估 | 1 天 |

### T-112 API 序列化层（camelCase ⇄ snake_case）

| 项 | 内容 |
|---|---|
| 目标 | DB 层 snake_case、API/交换层 camelCase，对齐 OpenMetadata（ADR-8） |
| 任务 | 统一响应序列化组件；字段映射规则；分页响应结构复用 T-111 |
| 依赖 | T-102 |
| 验收 | API 输出为 camelCase；DB 为 snake_case；映射可通过单测校验全字段 |
| 预估 | 1 天 |

### T-113 造数脚本（性能验证用）

| 项 | 内容 |
|---|---|
| 目标 | 为性能用例提供数据（**不做 PoC**，仅常规性能验证） |
| 任务 | 可配置规模脚本，默认 30 万表 / 1000 万字段；写入 `catalog_*` |
| 依赖 | T-104 |
| 验收 | 可按参数生成不同规模；造数耗时可接受 |
| 预估 | 0.5 天 |

### T-114 元数据抽取 Dialect 抽象（FR-2.4）

| 项 | 内容 |
|---|---|
| 目标 | 消除各连接器重复的 SQL 与硬编码类型映射（现状 `postgres.py:329-393`） |
| 任务 | 定义 `Dialect` 接口：`list_databases/schemas/tables/columns_sql`、`normalize_type`、能力声明；实现 MySQL / PG / Snowflake 三套 |
| 依赖 | T-104 |
| 验收 | 类型归一化口径统一；同一结构在不同库算出的 `struct_hash` 一致 |
| 说明 | **须早于 T-105 落库**。否则类型串不统一会让 `struct_hash` 产生假变更，污染版本 Diff 正确性（审核 R9） |
| 预估 | 2 天 |

### T-115 DatabasePipeline transform 钩子补齐

| 项 | 内容 |
|---|---|
| 目标 | 消除两条流水线行为不一致 |
| 任务 | `database_pipeline.py:261,391,405` 当前直接 `sink.write_table`，绕过 `TablePipeline.transform`（`:211,257`）；补齐钩子 |
| 依赖 | T-105 |
| 验收 | 两条路径均经过 transform；钩子逻辑可被统一触发 |
| 说明 | 不补齐会导致后续处理逻辑被静默绕过，表现为「部分表有标签、部分没有」（审核 R10） |
| 预估 | 0.5 天 |

---

## 3. Batch 1：版本 Diff 与检索（可并行）

### B1a 版本管理与变动分析（MOD-06）

| 编号 | 任务 | 依赖 |
|---|---|---|
| T-201 | Diff 引擎：`struct_hash` 前置过滤 + 逐字段比对，产出 `change_event` | T-104、T-106、T-110 |
| T-202 | 变更分级（breaking/structural/descriptive）+ 破坏性变更识别 | T-201 |
| T-203 | 订阅管理 + 通知聚合去重 + 静默规则（复用 `integrations/`） | T-202、T-107 |
| T-204 | 变更确认闭环 + 升级通知 + 变更统计 | T-203 |
| T-205 | 血缘影响面接口**占位**（MOD-07 未上线时降级） | T-201 |

### B1b 检索与资产目录（MOD-09）

| 编号 | 任务 | 依赖 |
|---|---|---|
| T-211 | 全局检索 + 多维筛选（trigram + btree + GIN） | T-104、T-111 |
| T-212 | 资产详情聚合（并发取数，禁 N+1） | T-211 |
| T-213 | 概览统计（预计算 + 缓存） | T-211 |
| T-214 | 业务元数据：术语表、业务描述、别名、`business.*` 标签 | T-104 |
| T-215 | MOD-07/08/11 依赖**占位与降级** | T-212 |

---

## 4. Batch 2：采样 → 画像 → 分级（内部串行）

| 编号 | 任务 | 依赖 |
|---|---|---|
| T-301 | `Dialect.sample_sql` 方言抽象（PG/Snowflake 原生；MySQL 主键点查） | T-104 |
| T-302 | `StatSampler`（下推聚合）/ `ValueSampler` / `RowSampler` | T-301、T-108 |
| T-303 | 采样保护：大表熔断、超时、并发上限、低峰调度、缓存 | T-302 |
| T-304 | 采样安全：黑名单、脱敏、加密、TTL、审计；高敏熔断（读 `grade_level`） | T-302 |
| T-401 | 画像填充 `table_profile` + `table_profile_history`（MOD-04） | T-302 |
| T-402 | 质量规则执行 + 评分 + 趋势 + 报告（复用 `quality/`） | T-401 |
| T-501 | 分级标准与规则管理（MOD-05） | T-104 |
| T-502 | 识别引擎四层（词典/正则/类型/采样回验）+ 置信度合成 | T-501、T-302 |
| T-503 | 结果回写（只更新 grade 列 + `security.*` 标签）+ 人工优先 | T-502 |
| T-504 | 高敏清除任务（经 T-107 编排下发）+ 误报反馈 + 覆盖率 | T-503 |

---

## 5. Batch 3 ~ 5

| 批次 | 任务 | 依赖 |
|---|---|---|
| **B3** 血缘（MOD-07） | T-601 sqlglot 集成、T-602 视图定义推导、T-603 边与闭包表、T-604 环检测与深度控制、T-605 影响面接口（补齐 T-205 占位） | T-104 |
| **B4** 权限分析（MOD-08） | T-701 `Dialect` 采集 SQL、T-702 账号与授权采集、T-703 风险识别、T-704 基线对比、T-705 与分级联动 | T-104、T-503 |
| **B5** RBAC（MOD-11） | T-801 用户与认证、T-802 RBAC、T-803 数据权限（下推 SQL）、T-804 多租户、T-805 与 MOD-08 账号关联 | T-102 |

B3 / B4 / B5 相互独立，可在 B0 之后任意时刻并行。

---

## 6. 并行冲突矩阵（文件级）

| 任务对 | 是否冲突 | 说明 |
|---|---|---|
| T-103 / T-104 / T-106 | 否 | 各自独立 ORM 文件 |
| T-105 / T-107 | 否 | sink vs 编排 |
| T-105 / T-110 | **是** | 都写 `catalog_*` 写入路径；建议 T-105 先完成 |
| B1a / B1b | 否 | MOD-06 写 `change_event`，MOD-09 只读 |
| T-401 / T-501 | 否 | 分别写 `table_profile` 与 `entity_tag` |
| T-503 / T-105 | **潜在** | 都碰 `catalog_column`；已由「只更新自己负责列」约束化解 |

---

## 7. 验证策略

| 层 | 方式 |
|---|---|
| 单元 | 每个模块新增单测；`struct_hash`、keyset 游标、置信度合成须覆盖边界 |
| 集成 | 补齐 `tests/integration/`（README 声明但目录不存在） |
| 性能 | 常规性能用例覆盖：分页 P95 < 500ms、批量写入分钟级、级联删除无长事务（**不做独立 PoC**） |
| 回归 | 每批次结束跑全量；基线：现有 145 用例（其中 4 个 async 用例待补 `pytest-asyncio`，3 个 integration 待补 `aiohttp`） |

---

## 8. 全局风险

| # | 风险 | 缓解 |
|---|---|---|
| PG-1 | ORM 与手写 DDL 双真相源漂移 | T-102 确立 ORM 为唯一真相源（审核 R1） |
| PG-2 | 分区表迁移踩坑 | 分区预建独立为运维任务（审核 R2） |
| PG-3 | keyset 分页各模块实现不一致 | T-111 前置为公共组件（审核 R3） |
| PG-4 | 千万级写入退化为逐条 INSERT | T-105 强制批量；代码评审检查点 |
| PG-5 | L3 代码侵入 L1 | CODEOWNERS + CI（待建） |
| PG-6 | 改名检测误判 | T-110 置信度分级 + 人工确认 |
| PG-7 | 采样影响生产库 | T-303/304 硬约束；默认关闭采样 |
