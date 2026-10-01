# 决策记录（Q1–Q15 / D1–D3）

日期：2026-09-30
决策人：代理（用户授权"你来决策"）
状态：**已生效，可推翻** —— 推翻时请在本文件追加一条修订，勿原地改写。

总原则：**不阻塞 B0 开工；凡涉及合规与不可逆动作，一律取"默认关闭 + 显式开启"的保守值。**

---

## 1. 需求侧 Q1–Q10（`03-roadmap-and-open-questions.md`）

| # | 问题 | 决策 | 理由 |
|---|---|---|---|
| Q1 | FR-6 口径 | 先做**数据源侧账号权限治理**；平台 RBAC 表结构保留（`role`/`permission`/`user_role`/`data_policy` 已建），实现排 P3 | 前者是治理价值主战场，后者可延后且不影响建模 |
| Q2 | 分级标准 | **可配置模型**，`classification_tag.grade_level` 预设 4 档（1–4，DDL 允许 1–9）+ `grade_code`/`color`，规则库给一套默认值 | 无既定规范，先可配置后固化 |
| Q3 | 规模上限 | **按亿级做分区设计**（已按月 RANGE 分区：6 张分区表），**按千万级做容量验证** | 分区策略改不动，容量目标可分期 |
| Q4 | 部署形态 | **私有化单租户**，所有表保留 `tenant_id DEFAULT 0`（现已如此） | 与 Q11 已确认的单实例部署一致，多租户仅留字段 |
| Q5 | 实时性 | MVP **天级调度（cron）**，不引入 CDC | 元数据场景天级足够，CDC 成本与收益不匹配 |
| Q6 | 是否需要前端 | 本期**仅交付 API**，前端另立项目 | 与 Q14 一致，避免 API 契约被 UI 反复改动 |
| Q7 | 采样能否访问生产库 | **默认关闭 + 显式授权**：① `datasource.sampling_enabled` 默认 `false`（DDL 已如此）；② 仅当数据源显式开启且连接账号为只读账号时才采样；③ 样本入库前强制脱敏（`sample_value.value_masked`/`value_enc`），`expires_at` 默认 30 天 TTL；④ 采样范围受 `sampling_config.sensitive_blacklist` 约束。**未在运维侧完成审批的数据源一律不开启** | 合规问题的正确解法是"能力具备、默认不开"，而不是"不实现"。FR-8/FR-9 管线照常开发，生产是否开启由运维审批决定 → **Q7 不再阻塞排期** |
| Q8 | 非数据库数据源 | Dialect/连接器抽象**预留接口**，实现（Hive/Kafka/对象存储/BI）排到后期 | 抽象成本在 T-114 里一并付掉 |
| Q9 | 血缘数据来源 | 先**视图定义推导 + SQL 解析（sqlglot，ADR-7）**，后续再对接 Airflow/DolphinScheduler | 纯 SQL 解析可独立交付，外部对接需环境 |
| Q10 | `InMemoryDB`/文件落盘 | **保留文件 sink 作为可选输出**，新增 `PostgresSink` 并行（即 T-105） | 有外部使用方风险，不删除既有路径 |

---

## 2. 审核侧 Q13–Q15（`04-requirement-review.md`）

| # | 问题 | 决策 | 理由 |
|---|---|---|---|
| Q13 | 改名检测是否需人工确认 | **不做工单流程**。自动链路：`struct_hash` 命中优先判定为"未变"；未命中则生成候选改名 → 写 `change_event(change_type='renamed', severity='structural')` 并携带置信度与 `entity_alias` 历史名；提供 API 供人工确认/回滚，**高置信候选自动采纳**（同 datasource、同一 scan_run 内"删除+新增"配对、fqn 相似度过阈值） | 工单流程属产品形态，本期不做；但改名必须可追溯、可回滚，`entity_alias` 表已为此预留 |
| Q14 | 检索是否需前端 | **仅 API**（同 Q6），返回结构按"可被其他系统消费"设计（分页 + camelCase 序列化层 T-112 已就绪） | 与 Q6 保持单一口径 |
| Q15 | 并发规模 / QPS（NFR-1.7） | 单实例私有化：**并发用户 ≤ 50，检索 API 峰值 50 QPS，P95 < 500ms**；不引入 Redis 等外部组件，靠 PG 索引 + keyset 分页 + 进程内可选 LRU 达成 | 与 Q11 单实例部署一致；指标写进验收，做性能回归测试时被断言 |

---

## 3. 计划侧 D1–D3（`01-plan-review.md`）

| # | 问题 | 决策 | 理由 |
|---|---|---|---|
| D1 | T-114 Dialect 抽象：重构 L1 连接器 vs 旁路新增 | **旁路新增**：在 L3 新建 `platform/dialect/`，L1 三个连接器**一行不改**，通过适配器逐步切换；切换完成前旧逻辑保留（双轨期） | 改 L1 会与上游同步冲突，直接违反代码边界约束（`04-code-boundary`）。风险最低且可逆 |
| D2 | 造数脚本规模 | **参数化三档**：`smoke` 1k 表 / 2w 列（默认，CI 用）、`dev` 5w 表 / 100w 列、`perf` 30w 表 / 1000w 列；档位由 CLI 参数选择，默认 smoke | 采纳审核建议的 30w/1000w 作为 perf 上限，但默认档必须能在 CI 里秒级跑完 |
| D3 | B0 之后先 B1a（Diff）还是 B1b（检索） | **先 B1a（FR-13 身份稳定 + 版本 Diff），再 B1b（检索）** | 审核自己指出"FR-13 不并入阶段一，则版本 Diff 会产出大量改名误报"；检索若检索的是被误判的数据，可见价值反而变成负价值。`change_event` 也是检索的重要数据源，先有正确的 Diff 才有可用的检索。**检索仍排 B1 内第二顺位，不降级** |

---

## 4. 由此确定的开工顺序

```
T-101 工程基建收尾（装测试依赖、修文档失真）   ← 当前
T-111/T-112 已完成（分页/序列化）
T-102/T-103/T-104/T-106 已完成（Alembic + ORM 全量，已与 DDL 对齐）
T-108 凭据加密与连接供给        ← 下一个
T-114 Dialect 抽象（旁路）
T-105 PostgresSink（依赖 T-114）
T-115 DatabasePipeline transform 钩子
T-110 实体身份稳定
T-107 任务编排底座
T-109 数据源管控 API
T-113 造数脚本
```

## 4.1 进展（2026-09-30）

| 项 | 状态 |
|---|---|
| ORM ↔ DDL 对齐（`alembic check` 无漂移）+ 清理遗留未使用导入 | ✅ |
| T-101 工程基建：安装 `aiohttp`/`pytest-asyncio` 等测试依赖，解除 3 个收集错误 | ✅ |
| 回归基线 | ✅ `pytest tests/unit -q` → **754 passed**（此前因缺依赖从未真正跑通过） |
| T-108 凭据加密（`platform/credentials.py`）+ 连接供给（`platform/connections.py`） | ✅ 含 122 个平台层用例；只读探针已在真实 PG 上双向验证（owner 角色判为可写、只读角色判为只读） |
| T-114 Dialect 抽象（旁路 `platform/dialect/`） | ✅ 新增 `base.py` + `postgres/mysql/snowflake.py` + `registry.py`；**逐字复刻** L1 三个连接器的系统表 SQL 与类型映射，`normalize_type` 与 L1 `_map_*_type` 在 46 条用例上结果完全一致；registry 支持 `postgres/postgresql/mysql/mariadb/snowflake` 别名，未知方言抛 `UnknownDialectError`。**L1 连接器零改动**（决策 D1）。测试 `tests/unit/platform/test_dialect.py` 46 passed，平台层 168 passed |
| T-105 PostgresSink（依赖 T-114） | ✅ 新增 `platform/sinks/postgres.py`：`PostgresSink(SinkConnector)` + `PostgresSinkConfig`。缓冲后按 DB→schema→table→column 依赖顺序单事务批量 upsert，用 `pg_insert ... ON CONFLICT (fqn) WHERE deleted_at IS NULL DO UPDATE`（已验证 `index_where` 正确匹配部分唯一索引）；只更新本模块负责列，**显式排除 `grade_level`/`grade_code`**（MOD-05 所有）；schema 由表 FQN 派生（pipeline 不调 write_schema）；列 `data_type` 经 T-114 方言对 UNKNOWN 兜底归一。纯单元 4 passed；DB 支撑 2 用例在 `DATABASE_URL` 可达时跑（无 Docker 时 skip）。平台层 + 核心 sink/pipeline 回归 278 passed |

**顺带修掉的两个预存在缺陷**（被"缺依赖导致全量测试从未跑通"掩盖）：

1. `core/engine/monitor.py:284` `WorkflowMonitor._lock` 用 `threading.Lock()`，而
   `track_workflow` 持锁后调用 `_log` 再次加锁 → **必现自锁死**；改为 `RLock()`。
2. `observability/alerts.py` `_process_alert` 的去重键含 `timestamp`，每次评估都是新
   `Alert` → 去重永不命中，**持续越阈值的规则每次评估都追加一条告警**（3 规则 × 3 次
   评估 = 6 条）。改为按 `rule_name` 去重，并在 `resolve_alert` 时释放占位。
   同时修正 `test_log_messages` 的过期断言（`track_workflow` 本身会写一条 INFO 日志）。

## 5. 仍必须由用户/运维给出的输入（代理无法代替）

1. **Q7 的生产审批**：本机开发一律不采样；若某数据源要开采样，须在运维侧留痕。
2. **上游版本号/commit/日期**（`04-code-boundary-upstream-vs-local.md` 的三个 `"TODO"`）：本仓库无 git 元数据，无法自动取得，需人工填写。
