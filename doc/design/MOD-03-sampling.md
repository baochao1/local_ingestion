# MOD-03 数据采样 · 详细设计

| 项目 | 内容 |
|---|---|
| 模块编号 | MOD-03 |
| 负责需求 | FR-8（含 `04` 补充项 FR-8.9 ~ FR-8.11） |
| 优先级 | P0（MOD-04、MOD-05 的共同前置） |
| 依赖模块 | MOD-01（连接、采样策略）、MOD-02（元数据）、MOD-10（任务、审计） |
| 被依赖 | MOD-04（统计型）、MOD-05（值样本型） |

---

## 1. 职责与边界

### 1.1 职责

1. **统计型采样**：行数、空值率、唯一值数、极值、均值、标准差 —— **由数据库侧聚合下推**
2. **值样本型采样**：字段 distinct 取值样例，供分类分级回验
3. **样本行采样**：少量真实记录用于预览（须脱敏）
4. **生产保护**：只读账号、大表熔断、超时、并发上限、低峰调度
5. **样本安全**：敏感列黑名单、采样后脱敏、加密、TTL、审计

### 1.2 边界（不做）

- 不做画像结果持久化（属 MOD-04）
- 不做敏感识别（属 MOD-05）——只负责取样本
- 不做质量规则判定（属 MOD-04）
- **不决定是否该采样**：熔断判定由 MOD-05 写入的 `grade_level` 决定，本模块只读该列

---

## 2. 需求映射

| 需求 | 本模块实现 |
|---|---|
| FR-8.1 统计型采样 | `StatSampler` |
| FR-8.2 值样本型采样 | `ValueSampler` |
| FR-8.3 样本行采样 | `RowSampler` |
| FR-8.4 采样策略可配 | `sampling_config`（数据源级）+ 任务级覆盖 |
| FR-8.5 跨库方言适配 | `Dialect.sample_sql`（由 MOD-02 方言层提供） |
| FR-8.6 采样安全 | 黑名单、脱敏、加密、TTL、审计 |
| FR-8.7 高敏反向联动 | 采样前读 `grade_level` 熔断；清除样本经 MOD-10 异步任务 |
| FR-8.8 样本默认不落库 | 内存消费为主；落库须显式开启 |
| FR-8.9 采样新鲜度 | 样本标记采样时间与有效期 |
| FR-8.10 与扫描编排 | 作为独立任务，编排于扫描之后（不嵌入扫描） |
| FR-8.11 采样结果缓存 | 同列有效期内不重复采样 |

---

## 3. 数据模型

| 表 | 用途 | 所有权 |
|---|---|---|
| `sample_value` | 样本值（默认不写，按月分区） | **本模块写**（MOD-05 内存消费为主） |

读取但不写：`catalog_column`（含 `grade_level` 熔断判断）、`datasource.sampling_config`。

---

## 4. 核心设计

### 4.1 三条采样路径

| 采样器 | 输入 | 产物 | 实现方式 |
|---|---|---|---|
| `StatSampler` | 表 + 字段列表 | 统计值 | **SQL 下推聚合**，返回聚合结果，不拉行 |
| `ValueSampler` | 字段 | N 个 distinct 取值 | `SELECT DISTINCT col ... LIMIT N`（带采样） |
| `RowSampler` | 表 | 少量样本行 | 采样后取行，逐字段脱敏 |

**严禁**拉全量行到 Python 计算统计值——既慢又有采样偏差。

`StatSampler` 下推示例：

```sql
SELECT COUNT(*)                     AS row_count,
       COUNT(col)                   AS non_null_count,
       COUNT(DISTINCT col)          AS distinct_count,
       MIN(col), MAX(col), AVG(col), STDDEV(col)
FROM schema.table TABLESAMPLE SYSTEM (:rate);
```

### 4.2 采样方言策略（FR-8.5）

| 数据库 | 原生采样 | 策略 |
|---|---|---|
| PostgreSQL | ✅ `TABLESAMPLE BERNOULLI(n)` / `SYSTEM(n)` | 原生下推 |
| Snowflake | ✅ `SAMPLE(n)` / `TABLESAMPLE` | 原生下推 |
| **MySQL** | ❌ **不支持 TABLESAMPLE** | 主键范围随机点查 |

**MySQL 替代方案**（按代价排序）：

1. **主键范围随机点查**（推荐）：`WHERE id >= FLOOR(MIN + RAND()*(MAX-MIN)) LIMIT 1`，重复 N 次，走索引
2. 主键取模 `WHERE id % 1000 = 7`：分布均匀但用不上索引 → 全表扫描，大表禁用
3. `ORDER BY RAND() LIMIT n`：全表排序，**生产环境绝对禁用**

能力位 `datasource.supports_sampling` 由 MOD-01 探测；不支持时 MOD-10 不下发采样任务。

### 4.3 生产保护（硬约束）

| 保护项 | 机制 |
|---|---|
| 只读账号 | 经 MOD-01 `acquire(purpose='sample')`，连接已校验只读 |
| 大表熔断 | 采样前查估算行数（`information_schema.TABLE_ROWS` / PG `reltuples`），超阈值跳过或降级极小采样率 |
| 超时 | 单表采样超时中断并记录 |
| 并发上限 | 全局 + 每数据源并发上限（建议 ≤ 数据源连接数的 1/4） |
| 低峰调度 | 经 MOD-10 cron 排到业务低峰 |
| 宽表分批 | 字段数超阈值的表，聚合 SQL 分批下发 |
| 缓存 | 有效期内同一列不重复采样（FR-8.11） |

### 4.4 安全闭环

```
采样前：查 catalog_column.grade_level
        └─ 已达高敏阈值（如 ≥ L4）→ 跳过该列（熔断）

采样中：黑名单列（sampling_config.sensitive_blacklist）跳过

采样后：按列初步判定立即脱敏（手机号/身份证掩码）

落库（若开启）：value_masked（默认）；value_enc 仅显式开启
                + expires_at TTL

反向联动：MOD-05 判定高敏后 → MOD-10 下发清除任务 → 本模块删除该列样本
```

**熔断判定通过读 `catalog_column.grade_level` 实现，而非调用 MOD-05 接口**——避免 MOD-03 ↔ MOD-05 循环依赖（见总览 §5.1）。

### 4.5 采样编排（FR-8.10）

采样是**独立任务**，由 MOD-10 编排于扫描之后，不嵌入扫描主流程：

```
扫描任务（MOD-02）成功
    → 触发采样任务（本模块，按数据源/表粒度分批）
    → 触发画像任务（MOD-04，消费统计值）
    → 触发分级任务（MOD-05，消费样本值）
```

理由：采样会显著拖慢扫描，耦合在一起会导致扫描窗口不可控；独立后可按数据源单独调整频率与并发。

---

## 5. 对外接口

### 5.1 提供给其他模块（契约）

| 契约 | 接口 | 消费方 |
|---|---|---|
| C3 | `StatSampler.sample_stats(table_id, columns) -> Dict[str, ColumnStats]` | MOD-04 |
| C4 | `ValueSampler.sample_values(column_id, limit) -> List[str]` | MOD-05 |
| — | `RowSampler.sample_rows(table_id, limit) -> List[Dict]`（已脱敏） | MOD-09（预览） |
| — | `SamplingService.purge_samples(column_ids)` | 由 MOD-10 异步调用（高敏清除） |

**C3 / C4 为同步调用（L2），单次调用限定单表/单列，返回结果不入本模块存储**（除非显式开启持久化）。

### 5.2 REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/sampling/tasks` | 下发采样任务（按数据源/库/表范围） |
| GET | `/api/v1/sampling/columns/{id}/values` | 查看某列样本（脱敏后，需授权） |
| GET | `/api/v1/sampling/tables/{id}/rows` | 查看样本行（脱敏后） |
| DELETE | `/api/v1/sampling/columns/{id}/values` | 清除某列样本 |

---

## 6. 依赖的其他模块

| 模块 | 依赖内容 | 形式 |
|---|---|---|
| MOD-01 | 连接（purpose=sample）、采样策略、能力位 | L2 |
| MOD-02 | 字段元数据、`Dialect.sample_sql` | L2 |
| MOD-10 | 任务编排、调度、审计、并发控制 | L2/L3 |

**反向**：MOD-05 通过 MOD-10 异步调用本模块的样本清除能力（避免直接循环依赖）。

---

## 7. 关键设计决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | 统计值用 SQL 下推，不拉行 | 拉全量行到 Python 既慢又有偏差；下推返回单个数字 |
| D2 | 三条路径分离 | 统计、值样本、样本行的产物与消费方完全不同，混用会两头不讨好 |
| D3 | MySQL 走主键点查 | MySQL 无 `TABLESAMPLE`；`ORDER BY RAND()` 在生产库是灾难 |
| D4 | 样本默认不落库（ADR-6） | 每列 20 值 × 千万列 = 2 亿行，会让容量规划全面失效；同时缩小 PII 暴露面 |
| D5 | 熔断通过读 `grade_level` 而非调用 MOD-05 | 打破循环依赖，降级为单向 |
| D6 | 采样独立任务化 | 嵌入扫描会使扫描窗口不可控 |
| D7 | 采样须经 MOD-01 只读连接 | 元数据平台绝不应具备业务库写权限 |

---

## 8. 异常与边界处理

| 场景 | 处理 |
|---|---|
| 表过大超阈值 | 熔断跳过并记录原因；任务标记部分完成 |
| 查询超时 | 中断该表，继续其余；记录失败明细 |
| 生产库负载过高 | 并发上限 + 低峰调度 + 可手动暂停任务 |
| 采样中列被删 | 跳过，记录 |
| 高敏列判定变更 | 通过 MOD-10 清除任务清理已有样本 |
| 不支持采样的数据库 | 能力位拦截，任务不下发，明确提示 |
| 无主键表（MySQL 点查不可用） | 降级为极小比例全表扫描或跳过（可配） |

---

## 9. 验收标准

1. 对亿级大表采样不产生长查询，生产库负载无明显上升
2. 统计值由数据库侧聚合产出，平台不拉取全量行
3. MySQL 数据源采样可用（主键点查路径生效）
4. 黑名单列与高敏列不被采样
5. 样本值默认不落库；开启落库时有 TTL 且可被清除
6. 所有采样动作有审计记录
7. 同一列有效期内不重复采样
8. 采样任务可中断、可续跑、可取消
