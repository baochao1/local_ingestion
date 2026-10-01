# MOD-07 血缘分析 · 详细设计

| 项目 | 内容 |
|---|---|
| 模块编号 | MOD-07 |
| 负责需求 | FR-4、FR-16.5（外部血缘导入） |
| 优先级 | P2（独立性最强，可全程并行） |
| 依赖模块 | MOD-02（元数据、实体解析）、MOD-10（任务、审计） |
| 被依赖 | MOD-06（影响面）、MOD-09（血缘展示） |

---

## 1. 职责与边界

### 1.1 职责

1. **血缘解析**：表级与字段级血缘
2. **血缘存储**：边表 + 预计算传递闭包
3. **上下游追溯**与**影响面分析**
4. **环检测**与深度控制
5. **来源与置信度标注**
6. **外部血缘导入**（FR-16.5）

### 1.2 边界（不做）

- 不做元数据扫描（MOD-02）
- 不做变更判定（MOD-06）——只提供影响面查询
- 不做血缘的可视化渲染（前端 / MOD-09 提供数据）

---

## 2. 需求映射

| 需求 | 本模块实现 |
|---|---|
| FR-4.1 表级血缘 | 视图定义推导 + SQL 解析 |
| FR-4.2 字段级血缘 | sqlglot 列级 lineage |
| FR-4.3 上下游追溯 | 闭包表查询 |
| FR-4.4 影响面分析 | 下游闭包 + 责任人聚合 |
| FR-4.5 环检测与展示 | `CYCLE` / path 检测 + 深度上限 |
| FR-4.6 来源与置信度标注 | `edge_source` + `confidence` |
| FR-16.5 外部血缘导入 | 从调度系统导入 |

---

## 3. 数据模型

| 表 | 用途 | 所有权 |
|---|---|---|
| `lineage_table_edge` | 表级血缘边 | **本模块写** |
| `lineage_column_edge` | 字段级血缘边 | **本模块写** |
| `lineage_closure` | 传递闭包（派生，异步重建） | **本模块写** |

只读：`catalog_*`（MOD-02）、视图定义（经 MOD-01 连接获取）。

**标识策略**：边同时存 `*_fqn`（字符串，兼容未纳管外部对象）与 `*_id`（可空，指向纳管实体）。改名场景下 `entity_id` 不变，血缘自动保持（配合 MOD-02 的 FR-13）。

---

## 4. 核心设计

### 4.1 血缘来源与置信度

| 来源 | 说明 | 置信度 |
|---|---|---|
| `view` | 库内视图定义推导（`pg_get_viewdef` / `SHOW CREATE VIEW`） | 高（1.0） |
| `sql_parse` | ETL 脚本 / 查询日志解析（sqlglot） | 中高（0.7–0.9） |
| `etl_system` | 从 Airflow/DolphinScheduler 导入（FR-16.5） | 中高 |
| `manual` | 人工标注 | 按标注者设定 |

多来源命中同一条边时保留最高置信度来源，并记录全部来源于 `properties`。

### 4.2 解析技术选型（ADR-7）

**引入 `sqlglot`**：

- 纯 Python，无 JVM 依赖，与现有技术栈一致
- 原生支持列级 lineage
- 否决 Calcite / ANTLR / JSQLParser（JVM 依赖，运维成本高）

**视图定义推导**是覆盖率最高、成本最低的起点：库内视图的上下游关系是确定性的，不需要猜测。

### 4.3 闭包表与多跳查询

**问题**：递归 CTE 在千万边 + 深多跳下代价高，且存在环导致死循环风险。

**方案**：异步预计算**传递闭包** `lineage_closure(ancestor, descendant, depth)`：

| 操作 | 走闭包表 | 复杂度 |
|---|---|---|
| 一度上下游 | 边表 | O(出度) |
| 多跳追溯 | 闭包表 | O(结果集) |
| 影响面评估 | 闭包表 | O(结果集) |

**重建策略**：血缘边变更后触发增量重建；定期全量重建兜底。重建期间旧闭包仍可服务（双写切换）。

### 4.4 环检测

真实环境存在循环依赖（视图互引、ETL 回环）：

```sql
WITH RECURSIVE walk AS (
    SELECT e.tgt_fqn AS node, 1 AS depth,
           ARRAY[e.src_fqn, e.tgt_fqn] AS path
    FROM lineage_table_edge e
    WHERE e.src_fqn = :start
  UNION ALL
    SELECT e.tgt_fqn, w.depth + 1, w.path || e.tgt_fqn
    FROM walk w JOIN lineage_table_edge e ON e.src_fqn = w.node
    WHERE w.depth < :max_depth              -- 深度硬上限
      AND NOT (e.tgt_fqn = ANY(w.path))     -- 环检测
)
SELECT node, min(depth) FROM walk GROUP BY node;
```

`NOT (tgt = ANY(path))` 手工防环兼容 PG 11+；PG 14+ 可用 `CYCLE node SET is_cycle USING path`。

**生产路径走闭包表，递归仅用于重建兜底。**

### 4.5 影响面分析（供 MOD-06）

```python
def impact_scope(entity_id, entity_type='table', max_depth=5) -> ImpactReport:
    """返回下游对象列表、按 depth 分层、聚合责任人"""
```

返回：分层下游列表、总数、涉及的数据源、聚合的责任人（用于变更通知扩展范围）。

---

## 5. 对外接口

### 5.1 提供给其他模块

| 契约 | 接口 | 消费方 |
|---|---|---|
| C7 | `LineageService.impact_scope(entity_id, max_depth)` | MOD-06 |
| — | `LineageService.upstream(entity_id, depth)` / `downstream(...)` | MOD-09 |
| — | `LineageService.get_column_lineage(column_id)` | MOD-09 |

### 5.2 REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/lineage/tables/{id}/upstream` | 上游追溯（depth 参数） |
| GET | `/api/v1/lineage/tables/{id}/downstream` | 下游追溯 |
| GET | `/api/v1/lineage/tables/{id}/impact` | 影响面报告 |
| GET | `/api/v1/lineage/columns/{id}` | 字段级血缘 |
| POST | `/api/v1/lineage/parse` | 提交 SQL/脚本解析任务 |
| POST | `/api/v1/lineage/import` | 外部血缘导入（FR-16.5） |
| POST | `/api/v1/lineage/edges` | 人工标注血缘 |
| DELETE | `/api/v1/lineage/edges/{id}` | 删除血缘边 |
| POST | `/api/v1/lineage/closure/rebuild` | 触发闭包重建 |

---

## 6. 依赖的其他模块

| 模块 | 依赖内容 | 形式 |
|---|---|---|
| MOD-02 | 实体解析（FQN → 稳定 ID）、视图定义元数据 | L2 |
| MOD-01 | 连接（读取视图定义） | L2 |
| MOD-10 | 任务编排、审计 | L2/L3 |

---

## 7. 关键设计决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | 引入 sqlglot（ADR-7） | 纯 Python、原生列级血缘、无 JVM 依赖 |
| D2 | 关系表 + 预计算闭包，不引入图数据库（ADR-2） | 血缘规模未达图库收益阈值；引入会显著增加运维与一致性复杂度 |
| D3 | 边同时存 FQN 与 ID | FQN 兼容未纳管外部对象；ID 保证改名场景血缘不断裂 |
| D4 | 递归仅用于闭包重建，生产查询走闭包 | 递归在深多跳与环场景下不可控 |
| D5 | 先做视图定义推导 | 覆盖率最高、成本最低、确定性最强；SQL 解析覆盖有限 |
| D6 | 血缘标注来源与置信度 | 不同来源可靠性差异大，混为一谈会误导用户 |

---

## 8. 异常与边界处理

| 场景 | 处理 |
|---|---|
| 环 | path 检测 + 深度上限；闭包构建时环只记录最短路径 |
| 外部未纳管对象 | 以 FQN 存边，`*_id` 为空；标记为外部对象 |
| 解析失败（方言不支持） | 记录失败明细，不阻断其他对象 |
| 闭包过期（边已变更） | 标记闭包陈旧，查询结果标注；异步重建 |
| 深度过大 | 硬上限截断并提示 |
| 同名不同库 | 以 FQN 区分，ID 精确匹配 |
| 巨视图（定义超长） | 解析超时保护 |

---

## 9. 验收标准

1. 库内视图血缘可被自动推导
2. 提交的 SQL 可被解析出表级与字段级血缘
3. 影响面查询返回分层下游与责任人聚合
4. 环形依赖不导致查询死循环
5. 多跳追溯走闭包表，响应时间可接受
6. 表改名后血缘保持（配合 MOD-02 FR-13）
7. 血缘来源与置信度可查询
