# MOD-08 账号权限分析 · 详细设计

| 项目 | 内容 |
|---|---|
| 模块编号 | MOD-08 |
| 负责需求 | FR-6（含 `04` 补充项 FR-6.6、FR-6.7） |
| 优先级 | P2 |
| 依赖模块 | MOD-01（连接）、MOD-02（元数据）、MOD-05（分级）、MOD-10（任务、审计） |
| 被依赖 | MOD-09（展示）、MOD-11（权限策略参考） |

---

## 1. 职责与边界

### 1.1 职责

1. **采集库内账号与授权**：账号、角色、授权项
2. **权限矩阵**：账号 × 库/表/字段 的授权视图
3. **风险识别**：超管、过度授权、僵尸账号、无主账号
4. **权限变更追踪**与对比
5. **与分级联动**：高敏资产上的授权重点标注

### 1.2 边界（不做）

- **不做平台自身的账号权限体系**（属 MOD-11）
- 不做授权变更执行（只分析，不改业务库权限）
- 不做账号生命周期管理（创建/删除账号）

> **口径确认（Q1）**：FR-6 指「扫描并分析业务库内的账号权限」。平台自身 RBAC 为 FR-10 / MOD-11。

---

## 2. 需求映射

| 需求 | 本模块实现 |
|---|---|
| FR-6.1 采集账号与授权 | 三方言采集器 |
| FR-6.2 权限矩阵 | `account_grant` 多维查询 |
| FR-6.3 风险识别 | 规则化风险检测 |
| FR-6.4 权限变更追踪 | 与基线快照对比 |
| FR-6.5 与分级联动 | 关联 `grade_level` 标注 |
| FR-6.6 权限基线对比 | 基线快照与差异 |
| FR-6.7 账号与责任人关联 | 关联平台用户 |

---

## 3. 数据模型

| 表 | 用途 | 所有权 |
|---|---|---|
| `account` | 库内账号/角色 | **本模块写** |
| `account_grant` | 授权项 | **本模块写** |

只读：`catalog_*`（MOD-02）、`catalog_column.grade_level`（MOD-05）、`app_user`（MOD-11，用于 FR-6.7 关联）。

---

## 4. 核心设计

### 4.1 方言采集（FR-6.1）

采集 SQL 由 **MOD-02 的 `Dialect` 抽象层**提供（`list_accounts_sql` / `list_grants_sql`），本模块只负责执行与落库——与元数据扫描共用方言抽象，避免第二套方言实现。

| 数据库 | 账号 | 授权 |
|---|---|---|
| MySQL | `mysql.user` | `SHOW GRANTS FOR 'u'@'h'` |
| PostgreSQL | `pg_roles` / `pg_auth_members` | `information_schema.role_table_grants`、`has_table_privilege` |
| Snowflake | `SHOW USERS` / `SHOW ROLES` | `SHOW GRANTS TO USER/ROLE`、`GRANTS_TO_USERS` |

### 4.2 采集流程

```
[触发：定时 / 手动]
   ├─ 1. MOD-01 获取连接（purpose='permission'）
   ├─ 2. 经 Dialect 取账号列表 → upsert account
   ├─ 3. 逐账号取授权 → 解析为 (privilege, object_type, object_fqn) → upsert account_grant
   ├─ 4. 通过 MOD-02 实体解析，将 object_fqn 关联到 entity_id
   ├─ 5. 风险规则检测 → 生成风险项
   ├─ 6. 与基线对比 → 生成权限变更
   └─ 7. 审计留痕（MOD-10）
```

**性能注意**：账号数 × 对象数可能很大（超管账号授权对象可达数万）。解析与落库需批量，且对「全部权限」类授权（如 `ALL PRIVILEGES ON *.*`）做展开时须限制展开粒度，避免写入爆炸。

### 4.3 风险识别规则（FR-6.3）

| 风险 | 判定 |
|---|---|
| 超管账号 | 具备全局/实例级管理权限（`SUPER`、`rolsuper`、`ALL ON *.*`） |
| 过度授权 | 对库/表具备超出职责的权限（如业务账号具备 DDL 或 DELETE） |
| 长期未使用 | `last_login_at` 超阈值或从未登录 |
| 无主账号 | 未关联任何责任人/平台用户 |
| 弱口令策略 | 密码策略缺失/过期未改（视数据库可获取程度） |
| **高敏资产授权** | 对 `grade_level ≥ 3` 的对象具备读/写权限（FR-6.5 联动） |

风险项可配置启用与阈值。

### 4.4 权限基线对比（FR-6.6）

- 首次采集建立基线
- 后续采集与基线对比，产出：新增授权、回收授权、权限提升
- 权限提升（如 SELECT → DELETE）重点告警
- 支持人工更新基线（接受当前状态为新基线）

### 4.5 与分级联动（FR-6.5）

在权限矩阵中，对被授权对象标注其 `grade_level`；对高敏对象（≥ L3）的授权：

- 权限矩阵中高亮
- 纳入风险识别（高敏资产授权）
- 变更追踪中重点告警

---

## 5. 对外接口

### 5.1 提供给其他模块

| 契约 | 接口 | 消费方 |
|---|---|---|
| — | `PermissionQuery.matrix(filters)` | MOD-09 |
| — | `PermissionQuery.risks(scope)` | MOD-09 |
| — | `PermissionQuery.get_entity_grants(entity_id)` | MOD-09（资产详情展示授权情况） |

### 5.2 REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/permissions/accounts` | 账号列表（按数据源/风险筛选） |
| GET | `/api/v1/permissions/accounts/{id}/grants` | 某账号授权明细 |
| GET | `/api/v1/permissions/matrix` | 权限矩阵（账号 × 对象） |
| GET | `/api/v1/permissions/entities/{type}/{id}/grants` | 某对象的授权情况 |
| GET | `/api/v1/permissions/risks` | 风险项列表 |
| POST | `/api/v1/permissions/risks/{id}/ack` | 风险确认/忽略 |
| GET | `/api/v1/permissions/changes` | 权限变更（与基线对比） |
| POST | `/api/v1/permissions/baseline/refresh` | 更新基线 |
| POST | `/api/v1/permissions/tasks` | 下发采集任务 |
| GET | `/api/v1/permissions/export` | 导出合规报表 |

---

## 6. 依赖的其他模块

| 模块 | 依赖内容 | 形式 |
|---|---|---|
| MOD-01 | 连接（purpose='permission'） | L2 |
| MOD-02 | `Dialect` 采集 SQL、实体解析 | L2 |
| MOD-05 | 对象分级（`grade_level`） | L1 读表 |
| MOD-11 | 平台用户（用于 FR-6.7 关联责任人） | L1 读表，**可降级** |
| MOD-10 | 任务编排、审计 | L2/L3 |

---

## 7. 关键设计决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | 复用 MOD-02 的 `Dialect` 采集 SQL | 避免第二套方言实现；权限查询与元数据查询同源 |
| D2 | 只分析不执行授权变更 | 平台绝不应具备业务库写权限（与 MOD-01 D4 一致） |
| D3 | 高敏对象授权纳入风险 | 权限治理的核心价值在于「谁能碰敏感数据」 |
| D4 | 对「全部权限」类授权限制展开粒度 | 超管授权对象可达数万，无限制展开会写爆 |
| D5 | MOD-11 依赖可降级 | MOD-11 排期 P3，不可用时责任人关联降级为账号名匹配 |

---

## 8. 异常与边界处理

| 场景 | 处理 |
|---|---|
| 无权限查看账号（权限不足） | 记录并标记数据源权限采集不可用，不阻断其他采集 |
| 授权对象未纳管 | 以 FQN 存储，`entity_id` 为空，标记外部对象 |
| 授权展开量过大 | 截断 + 标记「授权范围过大」，不逐对象展开 |
| 同名账号不同 host | 以 `host_pattern` 区分（MySQL 特性） |
| 账号被删除 | 软删除保留历史，供变更追踪 |
| 角色继承（PG） | 解析 `pg_auth_members` 展开角色继承链，避免漏算 |

---

## 9. 验收标准

1. 三种数据源的账号与授权可被采集
2. 权限矩阵可查询（账号维度与对象维度双向）
3. 风险项被正确识别（超管、过度授权、僵尸、无主）
4. 高敏资产上的授权被标注并纳入风险
5. 权限变更可与基线对比并告警
6. 采集过程不对业务库产生写操作
7. MOD-11 未上线时本模块仍可用（降级验证）
