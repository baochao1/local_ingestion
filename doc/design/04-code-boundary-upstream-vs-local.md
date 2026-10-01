# 代码边界清单 · 上游同步区 vs 本地扩展区

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 编写日期 | 2026-09-30 |
| 依赖文档 | `03-openmetadata-compatibility.md`（ADR-8 / ADR-9） |
| 盘点范围 | `src/local_ingestion/` 全部 59 个源文件 |
| 配套产物 | `tools/sync/upstream_manifest.json`（见 §7） |

---

## 1. 分区定义

| 区 | 名称 | 含义 | 变更规则 |
|---|---|---|---|
| **L1** | 上游同步区 | 提取自 OpenMetadata 摄取模块的实体模型与摄取逻辑，与上游存在语义对应关系 | **谨慎变更**。改前先查上游是否已有同类改动；优先 upstream-first |
| **L2** | 兼容适配层 | OpenMetadata schema ⇄ 内部模型的双向转换（**新建**） | 自由变更，随上游 schema 演进同步 |
| **L3** | 本地扩展区 | 本产品自有能力：持久化、采样、分级、血缘、权限、检索、编排、API、CLI | 自由变更，不参与同步 |

**铁律（ADR-9）**：L3 功能扩展不得修改 L1 文件。新增能力通过继承、组合或插件实现。

---

## 2. 判定原则

判断一个文件属于 L1 还是 L3，看三条：

1. **上游是否存在语义对应物**（OpenMetadata 摄取框架有 `ServiceConnection`、`SourceConfig`、`Database/Table/Column` 实体、`source/database/*` 连接器）
2. **是否是本产品自有的治理能力**（采样、分级、血缘、权限、检索、编排 —— 上游无对应）
3. **是否为本地工程实现**（API、CLI、调度引擎、文件输出）

---

## 3. 文件级清单

### 3.1 `schema/` —— 实体与配置模型（L1 为主）

| 文件 | 分区 | 判定依据 |
|---|---|---|
| `schema/__init__.py` | L1 | 实体模型导出 |
| `schema/base.py` | L1 | `DataType`、`EntityReference`、`FQN`、`ServiceType`、`StackTraceError` 均对应上游类型 |
| `schema/data/__init__.py` | L1 | |
| `schema/data/database.py` | L1 | `Database` / `DatabaseSchema` 对应上游实体 |
| `schema/data/table.py` | L1 | `Table` / `Column` / `TableProfile` 对应上游实体（字段命名已是 OpenMetadata 风格） |
| `schema/metadata/__init__.py` | L1 | |
| `schema/metadata/workflow.py` | L1 | `SourceConfig` / `SinkConfig` / `FilterPattern` / `LogLevels` 对应上游 ingestion 配置 |
| `schema/service/__init__.py` | L1 | |
| **`schema/service/connection.py`** | **⚠ 混杂** | `DatabaseConnection` 系（L1）与 `FileSinkConfig` / `FileSourceConfig`（L3）同文件 —— 见 §4.1 |

### 3.2 `core/connectors/` —— 摄取连接器（L1 为主）

| 文件 | 分区 | 判定依据 |
|---|---|---|
| `core/connectors/__init__.py` | ⚠ 混杂 | 同时导出 L1 连接器与 L3 的 `file_sink` —— 见 §4.3 |
| **`core/connectors/base.py`** | **⚠ 混杂** | `SourceConnector`（L1）；`SinkConnector`（L1 概念）但 `connect()` 签名绑定 L3 的 `FileSinkConfig`（`:121`）—— 见 §4.2 |
| `core/connectors/mysql.py` | L1 | 对应上游 `source/database/mysql` |
| `core/connectors/postgres.py` | L1 | 对应上游 `source/database/postgres`；其中 `_map_postgres_type`（`:329-393`）硬编码映射属本地实现，建议随 `Dialect` 抽象外移 |
| `core/connectors/snowflake.py` | L1 | 对应上游 `source/database/snowflake` |
| **`core/connectors/file_sink.py`** | **L3** | 本地文件输出，上游无对应 —— **应移出 L1 目录**，见 §4.3 |

### 3.3 `core/pipeline/` —— 流水线（L1 骨架 + L3 扩展）

| 文件 | 分区 | 判定依据 |
|---|---|---|
| `core/pipeline/__init__.py` | L1 | |
| **`core/pipeline/base.py`** | **⚠ 混杂** | Pipeline 骨架（L1）+ checkpoint 机制（`:182-193`，L3）—— 见 §4.4 |
| `core/pipeline/database_pipeline.py` | L1 | 对应上游库→schema→表→字段遍历逻辑 |
| `core/pipeline/table_pipeline.py` | L1 骨架 | 骨架对应上游；`transform` 钩子（`:211`）为本地扩展，建议以组合方式外挂 |
| `core/pipeline/parallel.py` | **L3** | 本地并行优化，上游无对应 |

### 3.4 `core/engine/` —— 调度引擎（全部 L3）

| 文件 | 分区 | 判定依据 |
|---|---|---|
| `core/engine/__init__.py` / `monitor.py` / `scheduler.py` / `state.py` / `workflow_runner.py` | **L3** | 本地 APScheduler 调度、7 状态状态机、监控，上游无对应（上游走 Workflow + Airflow） |

### 3.5 `api/` `cli/` `quality/` `integrations/` `observability/`（全部 L3）

| 目录 | 分区 | 说明 |
|---|---|---|
| `api/`（app.py、base.py、exceptions.py、service.py、routes/*） | **L3** | 本产品自有 REST 服务 |
| `cli/`（main.py、parser.py、formatter.py、base.py、commands/*） | **L3** | 本产品自有 CLI |
| `quality/`（rules.py、validator.py、reporter.py） | **L3** | 本地质量能力（上游质量能力在独立模块，结构不同） |
| `integrations/`（webhook.py、notifications.py、plugins.py） | **L3** | 本地集成 |
| `observability/`（metrics.py、alerts.py、health.py） | **L3** | 本地可观测 |

### 3.6 L2 适配层（**待新建**）

```
src/local_ingestion/adapter/openmetadata/
├── __init__.py
├── mapper.py        # 字段映射与 camelCase ⇄ snake_case 转换
├── importer.py      # OpenMetadata 实体 JSON → 内部模型
├── exporter.py      # 内部模型 → OpenMetadata 实体 JSON
└── versions/        # 上游 schema 版本分支适配
```

### 3.7 `tests/` 归类规则

测试随被测对象走：测 L1 的放 `tests/upstream/`，测 L3 的放 `tests/<模块>/`。适配层测试放 `tests/adapter/`，**映射用例必须覆盖全字段**（防止上游字段变更静默丢失）。

---

## 4. 混杂文件与拆分建议（5 项，优先处理）

这 5 处是同步冲突的真正来源——不是"将来可能冲突"，而是**每次同步都会撞**。建议在阶段一处理。

> **状态：✅ 5 项均已完成（2026-09-30）**。实现方式见各子节「已实施」说明。

### 4.1 `schema/service/connection.py`

**问题**：`DatabaseConnection`（L1）与 `FileSinkConfig` / `FileSourceConfig`（L3，`:127` `:137`）同文件。

**拆分**：

```
schema/service/connection.py     → 仅保留 ServiceConnectionBase / DatabaseConnection / 各数据库连接（L1）
platform/sinks/config.py         → FileSinkConfig / FileSourceConfig（L3）
```

### 4.2 `core/connectors/base.py:121`

**问题**：`SinkConnector.connect(config: FileSinkConfig)` —— **L1 文件依赖了 L3 类型**，依赖方向违规。

**修复**：签名泛化为协议/泛型：

```python
class SinkConnector(ABC):
    @abstractmethod
    def connect(self, config: Any) -> None: ...   # 或定义 SinkConfig Protocol
```

（此改动同时也是 MOD-02 实现 `PostgresSink` 的前置条件。）

### 4.3 `core/connectors/file_sink.py` 与 `__init__.py`

**问题**：`file_sink.py`（L3）与 L1 连接器同目录，`__init__.py` 一并导出，视觉上难以区分同步边界。

**拆分**：`file_sink.py` → `platform/sinks/local_file.py`；`connectors/__init__.py` 只导出 L1 连接器。

### 4.4 `core/pipeline/base.py` 的 checkpoint

**问题**：Pipeline 骨架（L1）与 checkpoint 续跑机制（`:182-193`，L3）同文件。

**拆分**：checkpoint → `platform/resilience/checkpoint.py`；`base.py` 只保留骨架，通过组合注入 checkpoint 能力。

### 4.5 `schema/base.py` 与 `postgres.py` 的本地化偏离

| 项 | 说明 | 建议 |
|---|---|---|
| `schema/base.py:1` 中文文档字符串 `"""基础类型定义"""` | 本地化改动，同步时与上游注释冲突 | 注释改用英文对齐上游 |
| `postgres.py:25` 类名 `PostgresSourceConnector` | 与上游惯例不一致；且 `cli/commands/scan.py:142` 导入了不存在的 `PostgreSQLSourceConnector`（**现存 bug**） | 同步前明确以哪侧为准；bug 须修 |

---

## 5. 目标目录结构

**方案：渐进式**（不主张一次性大搬家，成本高风险大）

| 阶段 | 动作 | 必要性 |
|---|---|---|
| 阶段一 | ① 建立清单与规则（`upstream_manifest.json` + CODEOWNERS + CI 检查）<br>② 新建 `adapter/openmetadata/`（纯新增，无破坏） | **必做** |
| 阶段一 | 拆分 §4 的 5 项混杂文件 | **必做**（否则持续冲突） |
| 可选评估 | 大规模物理重排为 `ingestion/`（L1）+ `platform/`（L3）顶层分区 | 收益是边界一目了然；代价是全量改 import 与测试。<br>**建议至少完成混杂拆分后再评估** |

若决定做物理重排，目标结构：

```
src/local_ingestion/
├── ingestion/            # L1 上游同步区
│   ├── schema/           # 实体与配置模型（不含 FileSinkConfig）
│   ├── connectors/       # base / mysql / postgres / snowflake
│   └── pipeline/         # 骨架（不含 checkpoint、parallel）
├── adapter/              # L2 兼容适配层
│   └── openmetadata/
└── platform/             # L3 本地扩展
    ├── persistence/      # PostgresSink、ORM、迁移
    ├── orchestration/    # MOD-10 任务编排
    ├── sampling/         # MOD-03
    ├── profile/          # MOD-04
    ├── classification/   # MOD-05
    ├── versioning/       # MOD-06
    ├── lineage/          # MOD-07
    ├── permission/       # MOD-08
    ├── catalog/          # MOD-09
    ├── sinks/            # local_file（自 §4.3 迁入）
    ├── resilience/       # checkpoint（自 §4.4 迁入）
    ├── quality/ integrations/ observability/
    └── api/ cli/
```

---

## 6. 变更规则

### 6.1 L1 文件

| 场景 | 规则 |
|---|---|
| 修 bug | 先查上游是否已修；已修则同步上游，未修则本地修并**提交 upstream issue/PR** |
| 加能力 | **禁止**直接加。通过继承 / 组合 / 插件在 L3 实现 |
| 改签名 | 需专项评审；对外影响的改动优先 upstream-first |
| 改注释/格式 | 尽量避免；格式化差异会在每次同步时产生噪音 diff |

### 6.2 L3 文件

自由变更。唯一约束：**不得反向 import 并修改 L1 行为**（可读可调，不可改）。

### 6.3 L2 适配层

上游 schema 演进时同步更新；新增映射须补测试。

---

## 7. CI 与工程约束

### 7.1 清单文件 `tools/sync/upstream_manifest.json`

```jsonc
{
  "upstream": {
    "project": "openmetadata",
    "repo": "https://github.com/open-metadata/OpenMetadata",
    "baseline": {
      "version": "TODO",        // ← 首次同步前必须填写
      "commit": "TODO",
      "date": "TODO"
    },
    "path_mapping_status": "PENDING"   // 上游精确路径待首次同步时核实补齐
  },
  "l1_files": [
    "src/local_ingestion/schema/base.py",
    "src/local_ingestion/schema/data/database.py",
    "src/local_ingestion/schema/data/table.py",
    "src/local_ingestion/schema/metadata/workflow.py",
    "src/local_ingestion/schema/service/connection.py",
    "src/local_ingestion/core/connectors/base.py",
    "src/local_ingestion/core/connectors/mysql.py",
    "src/local_ingestion/core/connectors/postgres.py",
    "src/local_ingestion/core/connectors/snowflake.py",
    "src/local_ingestion/core/pipeline/base.py",
    "src/local_ingestion/core/pipeline/database_pipeline.py",
    "src/local_ingestion/core/pipeline/table_pipeline.py"
  ],
  "split_pending": [
    "schema/service/connection.py: FileSinkConfig/FileSourceConfig -> platform/sinks/config.py",
    "core/connectors/base.py: SinkConnector.connect signature -> generic",
    "core/connectors/file_sink.py -> platform/sinks/local_file.py",
    "core/pipeline/base.py: checkpoint -> platform/resilience/checkpoint.py",
    "schema/base.py: docstring localization"
  ]
}
```

### 7.2 `.github/CODEOWNERS`

```
# L1 上游同步区：需同步责任人审批
/src/local_ingestion/schema/            @sync-owner
/src/local_ingestion/core/connectors/   @sync-owner
/src/local_ingestion/core/pipeline/     @sync-owner
/src/local_ingestion/ingestion/         @sync-owner

# L2 适配层
/src/local_ingestion/adapter/           @sync-owner

# L3 本地扩展区：模块各自 owner
/src/local_ingestion/platform/          @platform-team
```

### 7.3 CI 检查（建议两个 job）

| Job | 检查内容 |
|---|---|
| `boundary-check` | PR 中若触碰 `l1_files`，要求 sync-owner 审批；并提示"确认上游是否已有同类改动" |
| `upstream-drift` | 定时（如每周）拉取上游对应文件做 diff，输出偏离报告，人工判断是否同步 |

---

## 8. 上游同步 Runbook

```
1. 确认基线：读取 upstream_manifest.json 的 baseline（首次同步前必须先补齐）
2. 拉取目标版本的上游代码，仅比对 L1 清单内文件
3. 生成 diff，按三类处理：
   ├─ 上游新增能力        → 合入（L3 不受影响）
   ├─ 上游修改 schema/签名 → 更新 L2 适配层（必要时加版本分支）
   └─ 与本地改动冲突      → 评估：能移到 L3 就移；否则 upstream-first
4. 更新 baseline（version / commit / date）
5. 回归：
   ├─ 摄取用例（tests/upstream/）
   ├─ 适配层全字段映射用例（tests/adapter/）
   └─ 关键路径性能用例
6. 记录同步日志（合入了什么、跳过了什么、跳过的理由）
```

---

## 9. 首次同步前必须完成的前置项

| # | 前置项 | 状态 |
|---|---|---|
| 1 | 补齐 `upstream_manifest.json` 的 baseline（版本/commit/日期） | ⬜ 待填（需提供提取时的上游版本） |
| 2 | 核实并补齐上游路径映射（当前 `PENDING`，不臆断路径） | ⬜ 待核实 |
| 3 | 完成 §4 的 5 项混杂拆分 | ✅ **已完成**（2026-09-30） |
| 4 | 修复 `cli/commands/scan.py:142` 导入错误 | ⬜ 待修（`PostgreSQLSourceConnector` → `PostgresSourceConnector`） |
| 5 | 建立 CODEOWNERS 与 `boundary-check` CI | ⬜ 待做 |
| 6 | 偏离盘点：区分「有意偏离」与「无意偏离」，前者记录理由 | ⬜ 待做 |

### 已实施的代码结构（2026-09-30）

```
src/local_ingestion/platform/            # 新增 L3 区
├── sinks/
│   ├── config.py                        # FileSinkConfig / FileSourceConfig（自 connection.py 移出）
│   └── local_file.py                    # 自 core/connectors/file_sink.py 迁入
└── resilience/
    └── checkpoint.py                    # CheckpointStore / InMemory / FileCheckpointStore
```

同步验证：`tests/unit/schema`、`tests/unit/core/test_connectors.py`、`tests/unit/core/test_pipeline.py`、`tests/unit/api`、`tests/unit/cli` 全部通过（134 + 192 passed）。
已知预存在环境问题（与本次改动无关）：缺 `aiohttp` 导致 `tests/unit/integrations` 收集失败；缺 `pytest-asyncio` 导致 4 个 async 用例失败。

---

## 10. 风险

| # | 风险 | 缓解 |
|---|---|---|
| R12 | 混杂文件未拆分，每次同步冲突累积 | 阶段一完成 §4 五项拆分 |
| R13 | 基线未记录，无法判断偏离来源 | 首次同步前强制补齐 baseline |
| R14 | L1 路径映射臆断导致同步错对象 | 标注 `PENDING`，核实后再填 |
| R15 | 长期不同步导致偏离过大，最终被迫放弃合入 | 建立 `upstream-drift` 定时检查（周级），避免长期断更 |
| R16 | 本产品 `Dialect` 抽象与上游抽取方式分歧扩大 | 明确以本地 `Dialect` 为准并记录；同步时只取上游 SQL 与类型映射更新 |
