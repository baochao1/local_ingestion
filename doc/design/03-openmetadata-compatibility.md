# OpenMetadata 兼容策略 · 详细设计

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 编写日期 | 2026-09-30 |
| 决策依据 | 用户确认：独立产品；摄取模块提取自 OpenMetadata；需兼容其 schema 以便复用后续更新与合入上游变更 |
| 影响范围 | 数据模型边界、代码组织、API 命名、上游同步流程 |

---

## 1. 定位与结论

**定位**：本产品是**独立产品**，其摄取模块提取自 OpenMetadata。目标是保留复用上游更新与合入上游变更的能力。

**核心结论（ADR-8）**：

> **内部存储用自有优化模型，对外交换用 OpenMetadata 兼容 schema。**
> 二者通过适配层转换，不在存储层强行兼容。

即「**存储不兼容，边界兼容**」。

---

## 2. 为什么不在存储层直接兼容

OpenMetadata 的持久化方式是把整个实体以 JSON 存入 `entity` 表（文档/EAV 风格），这在它的设计目标下合理，但与本产品的规模目标冲突：

| 本产品需求 | 文档式 JSON 存储的问题 |
|---|---|
| 千万级**字段级**检索与筛选 | 字段嵌在 JSON 内，需 JSONB 内部索引，代价高且能力受限 |
| 字段级血缘、字段级分级 | 字段无独立行，无法独立建边与打标 |
| keyset 分页 + 复合排序 | JSON 内字段无法作为稳定排序键走索引 |
| 分级筛选（`grade_level` 范围查询） | 需 JSONB 表达式索引，远慢于独立列 |
| 快照 Diff（签名前置过滤） | 无法在库内做签名比对过滤 |

**若存储层强行兼容，前面所有针对千万级的优化（列打散、冗余 JSONB、keyset 索引、分区）全部作废。**

反之，若在边界层兼容（导入/导出/API 使用 OpenMetadata schema），则复用与合入上游的能力不受影响——因为**上游摄取模块产出的是实体 JSON，不是存储结构**。

---

## 3. 分层架构

```
┌──────────────────────────────────────────────────────────┐
│ L1 上游同步区（upstream-aligned）                          │
│    摄取连接器、实体 schema 定义、pipeline 骨架              │
│    尽量与 OpenMetadata 保持一致，便于 diff / merge          │
└────────────────────────┬─────────────────────────────────┘
                         │ 实体 JSON（OpenMetadata schema）
┌────────────────────────▼─────────────────────────────────┐
│ L2 兼容适配层（adapter）                                   │
│    OpenMetadata JSON  ⇄  内部模型                         │
│    字段映射、命名转换（camelCase ⇄ snake_case）、版本适配   │
└────────────────────────┬─────────────────────────────────┘
                         │ 内部模型
┌────────────────────────▼─────────────────────────────────┐
│ L3 本地扩展区                                              │
│    持久化（自有关系模型）、采样、分级、血缘、权限、检索、编排  │
│    不侵入 L1，不修改上游同步文件                            │
└──────────────────────────────────────────────────────────┘
```

**关键约束**：L3 的功能扩展不得修改 L1 文件。新增能力通过继承、组合或插件（`integrations/plugins.py`）实现。否则每次上游同步都会产生冲突。

---

## 4. 命名约定

| 层 | 命名 | 示例 | 理由 |
|---|---|---|---|
| 数据库（PG） | `snake_case` | `fqn`、`data_type`、`numeric_precision` | SQL 惯例；避免大小写敏感问题 |
| 内部模型 / API / 交换 | `camelCase` | `fullyQualifiedName`、`dataType`、`precision` | **对齐 OpenMetadata**，减少适配成本 |

**现有代码已符合此约定**：`schema/data/table.py` 的 `fullyQualifiedName`、`dataTypeDisplay`、`ordinalPosition` 已是 OpenMetadata 风格（`table.py:46,14,19`）。因此适配层的工作量集中在**导入/导出与 API 边界**，而非重写模型。

---

## 5. Schema 映射表

| OpenMetadata（交换层） | 内部模型（PG） | 说明 |
|---|---|---|
| `databaseService` | `datasource` | 服务/数据源 |
| `database.fullyQualifiedName` | `catalog_database.fqn` | |
| `databaseSchema.fullyQualifiedName` | `catalog_schema.fqn` | |
| `table.fullyQualifiedName` | `catalog_table.fqn` | FQN 均为 `service.db.schema.table` 形式，语义一致 |
| `table.columns[]` | `catalog_column` 行 **+** `catalog_table.columns_json` | 决策 A：双写 |
| `table.tableType` | `catalog_table.table_type` | |
| `column.dataType` / `dataTypeDisplay` | `data_type` / `data_type_display` | |
| `column.ordinalPosition` | `ordinal_position` | |
| `column.precision` / `scale` | `numeric_precision` / `numeric_scale` | 内部加前缀避免与 `NUMERIC(p,s)` 混淆 |
| `column.children` | `catalog_column.children`（JSONB） | 决策 B |
| `table.profile` | `table_profile.stats`（JSONB） | 决策 D |
| `tags[]` | `tags` JSONB **+** `entity_tag` 行 | 决策 F；含来源与置信度扩展 |
| `owner`（EntityReference） | `owner` + `business_metadata.owner_business` | 本产品区分业务/技术负责人（FR-1.9） |

**扩展字段（OpenMetadata 无对应）**：`struct_hash`、`grade_level`、`numeric_*` 前缀、`entity_alias`、`business_*`。这些是本地扩展，导出时按 OpenMetadata schema 省略或放入 `extension` 区，导入时忽略未知字段。

---

## 6. 上游同步机制

### 6.1 同步区清单（建议）

| 目录/文件 | 归属 | 说明 |
|---|---|---|
| `core/connectors/base.py` | L1 | 连接器契约 |
| `core/connectors/mysql.py` / `postgres.py` / `snowflake.py` | L1 | 摄取逻辑 |
| `core/pipeline/*` | L1（骨架） | 流水线骨架；扩展走子类 |
| `schema/data/*` | L1 | 实体 schema 定义 |
| `schema/service/connection.py` | L1 | 连接配置 |
| `core/engine/*` | L2 | 已有本地改造（状态机扩展） |
| `quality/*`、`integrations/*`、`observability/*` | L3 | 本地能力 |
| 新增的采样/分级/血缘/检索/编排 | L3 | 本地能力 |

### 6.2 同步流程

```
1. 跟踪上游 OpenMetadata 版本（记录当前基线版本与 commit）
2. 拉取上游变更 → 仅比对 L1 同步区
3. 冲突类型：
   ├─ 上游新增能力 → 直接合入（L3 不受影响）
   ├─ 上游修改 schema → 适配层（L2）增加版本分支处理
   └─ 与本地改动冲突 → 评估：能移到 L3 就移，否则 upstream-first
4. 合入后回归：摄取用例 + 适配层映射用例
```

### 6.3 已存在的偏离（同步前需评估）

1. **类名不一致**：`PostgresSourceConnector`（`postgres.py:25`）vs OpenMetadata 惯例 `PostgresSQLSourceConnector`；且 `cli/commands/scan.py:142` 导入了不存在的 `PostgreSQLSourceConnector`（现存 bug）。同步时需明确以哪一侧为准。
2. **抽取方式**：现有实现直接查系统表（`information_schema` / `pg_catalog`），未使用 OpenMetadata 的 `DatabaseMetaData` 式抽象。本产品已规划 `Dialect` 抽象层（MOD-02 D1），**与上游收敛时需二选一**，建议以本地 `Dialect` 为准（因需承载采样与权限查询）。
3. **状态机**：`engine/state.py:270-291` 的 7 状态为本地设计。

**建议**：首次同步前先做一次偏离盘点，把「有意偏离」与「无意偏离」分开，前者记录理由，后者修正。

---

## 7. 兼容性落地任务

| # | 任务 | 归属模块 |
|---|---|---|
| 1 | 定义 L1/L3 目录边界并写入贡献规范 | 全局 |
| 2 | 实现 OpenMetadata 实体 JSON **导入**（元数据接入） | MOD-02 |
| 3 | 实现 OpenMetadata 实体 JSON **导出**（资产清单、迁移） | MOD-09 / MOD-16 |
| 4 | API 层统一 camelCase，DB 层 snake_case 映射 | 全局 |
| 5 | 适配层版本分支（支持上游 schema 演进） | MOD-02 |
| 6 | 记录上游基线版本，建立同步检查清单 | 工程规范 |

---

## 8. 决策记录

### ADR-8：存储不兼容，边界兼容

- **决策**：内部存储采用自有优化关系模型；对外交换（导入/导出/API）采用 OpenMetadata 兼容 schema，通过适配层转换。
- **理由**：存储层兼容会作废千万级性能优化；边界层兼容足以支撑复用上游与合入变更，因为上游摄取产出的是实体 JSON 而非存储结构。
- **代价**：需长期维护适配层；上游 schema 演进时需同步更新映射。
- **否决方案**：直接采用 OpenMetadata 存储 schema（性能不满足 NFR-1）、完全不兼容（丧失复用上游能力）。

### ADR-9：代码分三层，L3 不修改 L1

- **决策**：上游同步区与本地扩展区物理隔离，本地扩展通过继承/组合/插件实现。
- **理由**：混合修改会导致每次上游同步产生大量冲突，最终被迫放弃同步。
- **代价**：部分改造需绕开上游文件，设计上稍复杂。

---

## 9. 风险

| # | 风险 | 缓解 |
|---|---|---|
| R8 | 上游 schema 大版本重构，适配层成本剧增 | 适配层按版本分支；锁定上游基线版本，非必要不追新 |
| R9 | 本地 `Dialect` 抽象与上游抽取方式分歧扩大 | 明确以本地为准并记录；同步时只取上游的 SQL 与类型映射更新 |
| R10 | L3 代码逐渐侵入 L1，同步冲突累积 | 贡献规范 + CI 检查（L1 文件变更需专项评审） |
| R11 | 偏离未盘点，首次同步冲突爆炸 | 同步前先做偏离盘点（见 §6.3） |
