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
| 工作区 | 干净（无未提交改动） |

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
| T-107 | **任务编排底座 (MOD-10)** | ⬜ **未开始** | 无任何 orchestration 模块 |
| T-108 | 凭据加密与连接供给 (MOD-01) | ✅ 已落地 | init（`platform/credentials.py` AES-256-GCM、`connections.py` ConnectionProvider + 只读校验） |
| T-109 | 数据源管控 API (MOD-01) | ⬜ 未开始 | — |
| T-110 | 实体身份稳定 (FR-13) | ✅ 已提交 | `d9c58b9`（`platform/identity.py`：稳定 ID、改名检测、entity_alias、孤儿标记） |
| T-111 | 分页与 API 公共组件 | ✅ 已落地 | init（`platform/api/pagination.py`，keyset 游标 `base64(fqn\|id)`） |
| T-112 | API 序列化层（camelCase⇄snake_case） | ✅ 已落地 | init（`platform/api/serialization.py`） |
| T-113 | 造数脚本（性能验证） | ⬜ 未开始 | — |
| T-114 | 元数据抽取 Dialect 抽象 (FR-2.4) | ✅ 已提交 | `d364055`（`platform/dialect/`，PG/MySQL/Snowflake） |
| T-115 | DatabasePipeline transform 钩子补齐 | ✅ 已提交 | `86b9434` |

**结论**：Batch 0 中仅 **T-107（编排底座）、T-109（数据源 API）、T-113（造数脚本）** 尚未启动；其余均已在仓库中。

---

## 2. 下一步（建议顺序）

1. **T-107 任务编排底座（MOD-10）** —— 当前唯一阻塞 Batch 1 的地基项。
   依赖 T-106（已落地）。目标：统一 `TaskSpec`/`TaskRun`、触发（手动/定时/事件）、重入保护、并发控制、重试退避、依赖编排（扫描→Diff→通知）、`AuditService.record`。
   **关键约束**：须与持久化同批，避免各模块各自实现调度/防重。
2. T-109 数据源管控 API（依赖 T-103/T-108/T-111/T-112）。
3. Batch 1 可并行两条线：
   - B1a 版本 Diff（T-201~T-205，依赖 T-110 已就绪）；
   - B1b 检索与资产目录（T-211~T-215，依赖 T-104/T-111 已就绪）。

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
pytest tests/unit -q   # 基线 754 passed（见 README §测试覆盖）
```

**依赖/环境坑（已踩过，务必注意）**：
- `pyproject` 声明了 `aiohttp` / `pytest-asyncio`，但**环境必须先 `pip install -e ".[test]"`**；否则 `tests/unit/integrations/` 收集失败、全量测试中断，会误以为通过。
- 加密依赖 `cryptography>=42`（T-108 引入），缺失会直接 import 失败。
- `struct_hash` 口径必须与 DDL 一致：**DDL 未插 tenant 种子行**，新库首次 `alembic upgrade head` 后无租户数据属正常。

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
