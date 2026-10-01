# 元数据治理平台 · 设计方向

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0（初稿，待评审） |
| 编写日期 | 2026-09-30 |
| 依赖文档 | `01-product-requirements.md` |
| 文档状态 | 设计方向，未含完整 DDL，实现前需细化 |

> 本文只定**方向与关键决策**，不替代详细设计。数据模型的完整 DDL、索引与查询范式在评审通过后另出。

---

## 1. 总体架构

### 1.1 分层

```
┌─ 接入层 ─────────────────────────────────────────────┐
│  REST API（FastAPI，现有 api/ 扩展）   │  前端（本期不做） │
└──────────────────────────────────────────────────────┘
┌─ 能力层 ─────────────────────────────────────────────┐
│ 扫描引擎 │ 采样引擎 │ 分类分级引擎 │ 血缘引擎 │ 画像引擎 │ 版本Diff │ 权限分析 │
└──────────────────────────────────────────────────────┘
┌─ 编排层（复用现有）──────────────────────────────────┐
│ APScheduler │ WorkflowRunner │ 状态机(7×8) │ checkpoint │ 并行执行 │
└──────────────────────────────────────────────────────┘
┌─ 连接层 ─────────────────────────────────────────────┐
│ SourceConnector（扩展采样能力位）│ 方言抽象层 │ SinkConnector │
└──────────────────────────────────────────────────────┘
┌─ 存储层（新增，本期核心）────────────────────────────┐
│ PostgreSQL：元数据库 / 快照 / 血缘 / 标签 / 任务 / 权限  │
└──────────────────────────────────────────────────────┘
```

### 1.2 设计原则

1. **存储层先行**。版本、血缘、权限、变动全部依赖「可关联、可查询、可追溯」的持久化。当前 `InMemoryDB`（`api/app.py:22`）与文件落盘（`file_sink.py:31-35`）无法支撑，此项不落地则其余功能皆为空中楼阁。
2. **复用现有编排，不重写**。调度、状态机、checkpoint、并行、告警通道已有可用实现，直接承载新增任务类型。
3. **能力层插件化**。新增数据源/质量规则/分类规则/血缘解析器走 `integrations/plugins.py` 的热插拔机制。
4. **方言差异必须收敛**。系统表查询、类型映射、采样语法三处差异统一到方言抽象层，杜绝连接器内各自硬编码（现状：`postgres.py:329-393`）。
5. **业务数据只在采样引擎内流转**，且默认不落库。

---

## 2. 存储选型

### 2.1 结论：PostgreSQL 作为唯一主存储

MVP 阶段不引入图数据库、不引入 Elasticsearch、不引入消息队列。

### 2.2 容量测算

| 表 | 预估行数 | 单条大小 | 数据+索引体积 |
|---|---|---|---|
| `metadata_database` / `schema` | 数千 | — | 可忽略 |
| `metadata_table` | 30–50 万 | ~1KB | < 1 GB |
| `metadata_column` | **1000–1500 万** | ~200–300B | 5–8 GB |
| `table_profile`（画像） | 30–50 万（每表 1 行 JSONB） | ~2KB | 1–2 GB |
| `lineage_edge` | 10–50 万 | 小 | 可忽略 |
| `entity_tag`（分类分级） | 2000–5000 万 | 小 | 5–15 GB |
| `metadata_snapshot` | 每次扫描 × 全量 | — | **增长最快，须分区** |

**结论**：全库在 10–30 GB 量级，处于单机 PostgreSQL 的舒适区，千万级绰绰有余，配合分区可支撑至亿级。

### 2.3 真正的风险不在数据库，在设计

以下六项是性能成败的关键，须在设计阶段定死：

| # | 风险 | 对策 |
|---|---|---|
| 1 | 深分页 `OFFSET` 在千万行上代价线性增长 | **强制 keyset 游标分页**：`WHERE (fqn, id) > (:last_fqn, :last_id) ORDER BY fqn, id LIMIT n`。须在 API 契约层统一，后改代价极大 |
| 2 | 列嵌套在 `Table.columns`（`table.py:51`）中，若整表 JSONB 化则字段级血缘/分级/检索全部不可行 | **列打散为独立行** `metadata_column`（可索引、可 join）；同时在 `metadata_table` 冗余一份 columns JSONB 供详情接口一次读取 |
| 3 | `ON DELETE CASCADE` 删千万行 → 长事务、锁、WAL 爆写、复制延迟 | **软删除 `deleted_at` + 异步分批物理清理**（每批约 5000 行，带间隔）；快照类用分区 `DROP PARTITION` |
| 4 | 血缘递归存在环（视图互引、ETL 回环）导致死循环 | PG 14+ `CYCLE` 子句兜底；主方案为**异步预计算传递闭包表**，查询走闭包 |
| 5 | 逐条 INSERT 写千万行耗时数小时 | `execute_values` 批量 `INSERT ... ON CONFLICT DO UPDATE`，5000–10000 行/批（SQLAlchemy 2.0 原生支持） |
| 6 | 快照表随扫描轮次线性膨胀 | 声明式分区（按 `scan_id` 或时间）+ 保留窗口外直接 drop |

### 2.4 关键索引方向

- `metadata_column(fqn)`：btree + `text_pattern_ops`（支持前缀搜索）
- 表名模糊搜索：GIN trigram（`pg_trgm`）
- 多值标签检索：JSONB + GIN
- 分级筛选：column 表独立的 `grade` 列 + btree（不放 JSONB 内）
- 快照/任务表：按时间 + 数据源的复合索引

### 2.5 何时应引入外部组件

| 触发条件 | 引入 |
|---|---|
| 需要跨实体模糊搜索 + 相关性排序体验 | PostgreSQL 作 source of truth，外挂 ES/OpenSearch 只读搜索副本 |
| 血缘规模达千万边且多跳查询频繁 | 评估图数据库（Neo4j / Apache AGE）作为血缘专用存储 |
| 需要近实时变更捕获 | 引入 CDC（Debezium）+ 消息队列 |

**以上均为触发式引入，不在 MVP 范围。**

---

## 3. 数据模型方向

### 3.1 实体划分

```
datasource（数据源，含加密凭据）
  └── database_instance
        └── database_schema
              └── metadata_table
                    └── metadata_column   ← 千万级核心表
                          ├── entity_tag  ← 分类分级标签（最大表）
                          └── column_sample（默认不落库）

scan_run（每次扫描）
  └── snapshot（快照，分区表）
        └── change_event（diff 结果）

lineage_edge + lineage_closure（血缘边 + 预计算闭包）
table_profile（画像，每表 1 行 JSONB）
quality_rule + quality_result
classification_rule + classification_tag（分级标准）
account_grant（库内账号授权，FR-6）
```

### 3.2 三个必须提前定死的建模决策

**决策 A：列打散为行 + 表级冗余 JSONB**
理由：字段级血缘、字段级分级、按列名/类型检索都要求列可索引；而详情接口若逐列 join 会带来 30 倍放大。冗余一份 JSONB 换详情接口单次读取，是值得的空间换时间。

**决策 B：标签必须携带来源与置信度**
现有 `tags: List[str]`（`table.py:23,57`）无法表达 `{名称, 来源: 规则|采样|人工, 置信度, 生效时间}`，且无法保证人工修正不被自动扫描覆盖（FR-9.5）。须升级为结构化标签。

**决策 C：画像每表一行 JSONB，而非每列一行**
`TableProfile`（`table.py:28-40`）的 `minValue/maxValue/mean/sum/stdDev` 本就是 `Dict[str, Any]`（per-column），天然适配「每表一行 JSONB」。此举把画像表从千万行降到数十万行。

---

## 4. 各功能域技术路线

### 4.1 FR-2 数据扫描

- 抽取方言抽象层，收敛系统表查询与类型映射
- 增量检测下沉到字段级：为表和列计算**结构签名**（列名+类型+约束+顺序的哈希），通过签名比对识别变更，替代现有「比 description 与列数」的弱判断（`database_pipeline.py:358-376`）
- 扫描状态从 `FileStateStore`（`engine/state.py:160-217`）迁移到 PG
- **须修复**：`DatabasePipeline` 直接调用 `sink.write_table`（`:261,391,405`），未走 `TablePipeline` 的 `transform` 钩子（`:211,257`）。两条路径行为不一致，新增的处理逻辑会被 DatabasePipeline 静默绕过

### 4.2 FR-8 数据采样（三条独立路径）

| 路径 | 产物 | 方式 |
|---|---|---|
| `StatSampler` | 统计值 | **SQL 下推聚合**：`SELECT COUNT(*), COUNT(DISTINCT c), MIN(c), MAX(c), AVG(c), STDDEV(c) ...` |
| `ValueSampler` | 字段 distinct 取值 | 供分类分级与质量规则回验 |
| `RowSampler` | 少量样本行 | 预览用，须脱敏 |

**严禁**拉全量行到 Python 计算统计值——既慢又有采样偏差。

**方言差异（关键）**：

| 数据库 | 采样能力 |
|---|---|
| PostgreSQL | 原生 `TABLESAMPLE BERNOULLI(n)` / `SYSTEM(n)` |
| Snowflake | 原生 `SAMPLE(n)` / `TABLESAMPLE` |
| **MySQL** | **不支持 TABLESAMPLE** |

MySQL 替代方案（按代价排序）：主键范围随机点查（走索引，推荐）→ 主键取模（均匀分布但全表扫描）→ `ORDER BY RAND()`（全表排序，**生产禁用**）。

因此须在 `SourceConnector`（`base.py:25`）新增采样能力位（如 `supports_sampling` / `sample_strategy`），对不支持的源不下发采样任务。

**生产保护**：只读账号、采样前估算表大小并熔断大表、单表超时、并发上限、低峰调度、宽表聚合分批下发。

**安全闭环**：敏感列黑名单 → 采样后即时脱敏 → 分类分级判定高敏后反向停止采样并清除样本 → 样本加密 + TTL → 全程审计。

### 4.3 FR-9 分类分级

- 识别策略分层：字段名词典 → 正则规则 → 类型启发式 → **采样值回验**（降误报关键）
- **引擎做成独立异步任务，不做成 Sink**。理由：Sink 是单向终点（`base.py:112`），而分类分级是「读元数据 → 打标 → 回写」；挂成 Sink 会导致规则更新后必须全库重扫
- 现有 `SinkConnector.connect()` 签名硬编码 `FileSinkConfig`（`base.py:121`），且 `BaseFileSink` 含 `_file_handle`（`file_sink.py:62`）——实现 PG Sink 前须先泛化 Sink 抽象
- 表级等级 = 其字段的最高等级（聚合得出）
- 可复用 `RuleFactory.from_json_schema`（`quality/rules.py:582`）作为分类规则加载器

### 4.4 FR-4 血缘

- 引入 **sqlglot**（纯 Python，无 JVM 依赖，原生支持列级 lineage）
- 存储：`lineage_edge` 表 + 异步预计算 `lineage_closure`，多跳查询走闭包
- 环检测：`CYCLE` 子句 + 深度上限
- 血缘标注来源与置信度（视图推导 / SQL 解析 / 人工）

### 4.5 FR-3 版本与 FR-7 变动

- 快照表分区存储；diff 基于结构签名做字段级三态比对（added/modified/deleted）
- 破坏性变更识别：删表、删列、类型收窄、新增非空约束
- 告警复用现有 `integrations/webhook.py`（HMAC）/ `notifications.py`（Email、Slack），补充去重与聚合
- 与血缘联动：变更后推送下游责任人

### 4.6 FR-5 画像与质量

- 画像由 `StatSampler` 下推聚合填充 `table_profile`，把现有 `TableProfile` 空壳（`table.py:28-40`）填实
- 质量规则沿用现有 `quality/rules.py` 6 类规则与 `validator.py`
- 画像/质量任务与元数据扫描**解耦独立调度**，避免拖慢扫描主流程

### 4.7 FR-6 账号权限分析

- MySQL：`mysql.user` + `SHOW GRANTS`
- PostgreSQL：`pg_roles` + `information_schema.role_table_grants`
- Snowflake：`GRANTS_TO_USERS` / `GRANTS_TO_ROLES`
- 风险规则：超管、过度授权、长期未使用、无主账号
- 与分级联动标注高敏资产上的授权

---

## 5. 架构决策记录（ADR）

### ADR-1：主存储选 PostgreSQL

- **决策**：PostgreSQL 作为唯一主存储，SQLAlchemy 2.0 + Alembic 管理迁移。
- **理由**：千万级数据量在 PG 舒适区（10–30GB）；JSONB 原生支持嵌套元数据与画像；递归 CTE 可支撑血缘；项目已依赖 SQLAlchemy 与 psycopg2。
- **否决方案**：图数据库（血缘外无优势、运维重）、Elasticsearch（不适合做 source of truth）、文件系统/对象存储（无法支撑关联查询）。

### ADR-2：MVP 不引入图数据库

- **决策**：血缘先用关系表 + 预计算闭包。
- **理由**：血缘规模（十万至百万边）远未达图数据库收益阈值；引入图库会显著增加运维与一致性复杂度。
- **触发条件**：血缘边达千万级且多跳查询成为瓶颈时重新评估。

### ADR-3：MVP 不引入 Elasticsearch

- **决策**：检索先用 PG 索引（btree + trigram + GIN）。
- **理由**：按 FQN 前缀检索、表名模糊匹配、标签筛选，PG 索引均可满足。
- **触发条件**：需要跨实体相关性排序的搜索体验时，以 PG 为主库、ES 为只读副本引入。

### ADR-4：分类分级不做成 Sink，做成独立引擎

- **决策**：`ClassificationEngine` 作为独立异步能力，通过 transform 钩子可选接入实时链路。
- **理由**：Sink 语义为单向终点，无法表达「读—打标—回写」；独立引擎支持规则迭代后对存量重跑，无需触发全库重扫。
- **附带**：须先泛化 `SinkConnector` 的 config 类型；须补齐 `DatabasePipeline` 缺失的 transform 钩子。

### ADR-5：全线强制 keyset 分页

- **决策**：所有列表 API 统一采用游标分页，禁用深 OFFSET。
- **理由**：千万行下深 OFFSET 代价线性增长，且分页方式一旦进入 API 契约与前端，后期改造代价极大。
- **影响**：API 契约须在设计阶段定死。

### ADR-6：样本值默认不持久化

- **决策**：采样样本默认仅在内存中消费，结论（标签/置信度）才落库；样本落库须显式开启且带 TTL。
- **理由**：每列 20 个样本值 × 千万列 = 2 亿行，会使容量规划全面失效；同时降低 PII 泄露面。

### ADR-7：血缘解析选 sqlglot

- **决策**：引入 sqlglot。
- **理由**：纯 Python，无 JVM 依赖，原生支持列级血缘，与现有技术栈一致。
- **否决方案**：Calcite / ANTLR（JVM 依赖，运维成本高）、JSQLParser（同上）。

---

## 6. 主要风险

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | 存储模型设计失误 | 全盘返工，所有下游模块受影响 | 存储设计与 PoC 先行，压测验证后再铺开 |
| R2 | 采样拖垮生产库 | 生产事故 | 只读账号 + 熔断 + 超时 + 并发上限 + 低峰调度，且默认关闭 |
| R3 | 样本数据泄露 PII | 合规风险 | 默认不落库 + 脱敏 + 加密 + TTL + 审计 |
| R4 | 双路径不一致（DatabasePipeline 无 transform） | 功能静默失效，排查困难 | 统一流水线钩子，补测试 |
| R5 | 快照无限膨胀 | 存储失控 | 分区 + 保留策略，上线即有 |
| R6 | 血缘环导致查询死循环 | 服务不可用 | CYCLE 检测 + 深度上限 + 闭包预计算 |
| R7 | 方言差异散落各连接器 | 维护成本随数据源数量线性增长 | 早期即建方言抽象层，勿拖延 |

---

## 7. 与现有代码的衔接点

| 现有资产 | 复用方式 |
|---|---|
| `SourceConnector`（`base.py:25`） | 扩展采样能力位，不改既有 4 方法契约 |
| `SinkConnector`（`base.py:112`） | **须重构**：泛化 config 类型，剥离文件句柄假设 |
| `TablePipeline.transform`（`:211`） | 作为可选实时处理钩子 |
| `DatabasePipeline`（`:261,391,405`） | **须补齐** transform 钩子 |
| 状态机（`engine/state.py:270-291`） | 复用承载新增任务类型 |
| checkpoint（`pipeline/base.py:182-193`） | 复用，状态存储迁至 PG |
| APScheduler（`engine/scheduler.py`） | 复用，新增采样/画像/分级任务 |
| 质量规则（`quality/rules.py`） | 复用，扩展分类规则 |
| 插件机制（`integrations/plugins.py`） | 复用，承接新数据源与新规则 |
| 告警通道（`integrations/webhook.py`、`notifications.py`） | 复用，补去重与聚合 |
| Prometheus（`observability/`） | 复用，覆盖新增任务指标 |
