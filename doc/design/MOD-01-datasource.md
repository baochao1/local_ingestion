# MOD-01 数据源管控 · 详细设计

| 项目 | 内容 |
|---|---|
| 模块编号 | MOD-01 |
| 负责需求 | FR-1（含 `04` 审核补充项 FR-1.7 ~ FR-1.10） |
| 优先级 | P0 |
| 依赖模块 | MOD-10（审计、任务编排） |
| 被依赖 | MOD-02、MOD-03、MOD-08、MOD-09、MOD-11 |

---

## 1. 职责与边界

### 1.1 职责

1. 数据源的注册、编辑、启停、删除
2. **凭据的加密存储、轮换与访问控制**（本模块是唯一可触碰凭据的模块）
3. 连通性测试与权限校验（强制只读）
4. 采集策略配置（扫描范围、调度、采样开关、并发）
5. 数据源健康度跟踪
6. 环境标识、分组与负责人管理

### 1.2 边界（不做）

- 不做元数据采集（属 MOD-02）
- 不做账号权限分析（属 MOD-08）——本模块只提供连接
- **不向任何模块暴露明文凭据**，只提供已建立的连接对象（契约 C1）
- 不做数据源内部对象的治理（表/字段属 MOD-02 及后续模块）

---

## 2. 需求映射

| 需求 | 本模块实现 |
|---|---|
| FR-1.1 注册/编辑/启停/删除 | 数据源 CRUD + 软删除 |
| FR-1.2 凭据加密存储与轮换 | `datasource_credential` 多版本 + `is_active` |
| FR-1.3 连通性测试 | 保存前校验可达性与权限 |
| FR-1.4 采集策略配置 | `scan_config` / `sampling_config` JSONB |
| FR-1.5 采集只读化 | 连接建立后校验只读，拒绝具备写权限的连接 |
| FR-1.6 健康度 | `last_scan_at` / `last_scan_status` / `last_error` |
| FR-1.7 环境标识 | `environment` 字段（prod/test/dev） |
| FR-1.8 数据源分组 | `group_name` 字段 |
| FR-1.9 负责人 | `owner_business` / `owner_technical` |
| FR-1.10 连接模板 | 同类数据源参数模板复用 |

> **DDL 补充**：`04` 审核新增的 FR-1.7 ~ FR-1.9 需在 `datasource` 表增加 `environment`、`group_name`、`owner_business`、`owner_technical` 四列，已同步至 `02-schema-ddl.sql`。

---

## 3. 数据模型

| 表 | 用途 | 所有权 |
|---|---|---|
| `datasource` | 数据源主记录与策略配置 | **本模块独占写** |
| `datasource_credential` | 加密凭据多版本 | **本模块独占写** |

关键字段说明：

- `credential_enc BYTEA`：应用层 AES-256-GCM 加密后的凭据，**密钥来自环境变量/KMS，绝不入库**
- `is_active`：同一数据源仅一个活跃版本（部分唯一索引保证），支持轮换期并存
- `supports_sampling` / `supports_lineage` / `supports_profiling`：能力位，由连接器探测或人工配置，决定下游模块能否下发任务
- `scan_config` / `sampling_config`：结构化策略，见 DDL 注释

---

## 4. 核心设计

### 4.1 数据源注册流程

```
1. 用户提交配置（连接参数 + 凭据 + 策略）
2. 校验参数合法性（类型、必填、端口范围）
3. 【连通性测试】用提交的凭据建立临时连接
      ├─ 失败 → 返回具体错误，不保存
      └─ 成功 → 继续
4. 【只读校验】检查连接是否具备写权限
      ├─ 具备写权限 → 按策略拒绝或告警（FR-1.5）
      └─ 只读 → 继续
5. 【能力探测】探测采样/血缘/画像支持情况 → 写入能力位
6. 凭据加密 → 写入 datasource_credential(version=1, is_active=true)
7. 写入 datasource 主记录
8. MOD-10 审计留痕（credential_change）
9. 返回数据源 ID；可选立即触发一次扫描（MOD-02）
```

### 4.2 凭据加密方案

| 项 | 方案 |
|---|---|
| 算法 | AES-256-GCM（含认证标签，防篡改） |
| 密钥来源 | 环境变量或 KMS，**禁止入库、禁止进日志** |
| 密钥标识 | `enc_algo` 字段记录算法与密钥版本，便于轮换 |
| 轮换流程 | 新增版本 → 验证新凭据连通 → 切换 `is_active` → 保留旧版本至观察期结束 → 清理 |
| 内存安全 | 解密后的明文凭据仅存在于连接建立过程，不缓存、不落日志 |

### 4.3 连接获取接口（契约 C1）

本模块对外**只提供连接对象，不提供凭据**：

```python
class ConnectionProvider:
    def acquire(self, datasource_id: int, purpose: str) -> ConnectionContext:
        """purpose: scan | sample | profile | permission
        - 校验数据源启用状态
        - 按 purpose 校验能力位
        - 解密活跃凭据并建立连接
        - 审计留痕（谁、何时、为何目的访问）
        - 返回上下文管理器，退出即关闭连接
        """
```

**约束**：

- `purpose` 决定是否允许：如 `supports_sampling=False` 时拒绝 `purpose=sample`
- 返回上下文管理器，强制 `with` 使用，避免连接泄漏
- 每次获取均审计（MOD-10）

### 4.4 只读校验

| 数据库 | 校验方式 |
|---|---|
| MySQL | `SHOW GRANTS` 解析是否含 INSERT/UPDATE/DELETE/DROP/ALTER |
| PostgreSQL | 查 `has_table_privilege` 与角色属性（`rolsuper`、`rolcreatedb`） |
| Snowflake | `SHOW GRANTS TO USER` / `CURRENT_ROLE` 权限解析 |

校验结果记入数据源健康信息；具备写权限的连接按策略处理（默认拒绝保存，可由管理员显式放行并标记风险）。

### 4.5 删除策略

数据源删除**不触发物理级联**（千万级 column 级联风险，见数据模型设计 §5.3）：

```
1. 软删除 datasource（deleted_at）
2. MOD-10 下发异步清理任务：按 datasource_id 分批软删
   catalog_column → catalog_table → catalog_schema → catalog_database
   每批 5000 行，可中断可续跑
3. 快照/变更类数据随分区保留策略自然过期
```

---

## 5. 对外接口

### 5.1 提供给其他模块（契约）

| 契约 | 接口 | 消费方 |
|---|---|---|
| C1 | `ConnectionProvider.acquire(datasource_id, purpose)` | MOD-02、03、08 |
| — | `DatasourceQuery.get(datasource_id)` / `list(...)` | 全部 |
| — | `PolicyProvider.get_scan_config(id)` / `get_sampling_config(id)` | MOD-02、03 |

### 5.2 REST API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/datasources` | 注册（含连通性测试与只读校验） |
| GET | `/api/v1/datasources` | 列表（keyset 分页、按环境/分组/类型筛选） |
| GET | `/api/v1/datasources/{id}` | 详情（不含凭据） |
| PUT | `/api/v1/datasources/{id}` | 更新配置 |
| DELETE | `/api/v1/datasources/{id}` | 软删除 + 下发异步清理 |
| POST | `/api/v1/datasources/test` | 连通性测试（不保存） |
| POST | `/api/v1/datasources/{id}/credentials` | 新增凭据版本 |
| POST | `/api/v1/datasources/{id}/credentials/{ver}/activate` | 切换活跃凭据 |
| POST | `/api/v1/datasources/{id}/enable` `/disable` | 启停 |
| GET | `/api/v1/datasources/{id}/health` | 健康度 |

---

## 6. 依赖的其他模块

| 模块 | 依赖内容 | 形式 |
|---|---|---|
| MOD-10 | 审计留痕（凭据变更、连接获取） | L2 |
| MOD-10 | 异步清理任务下发 | L3 |
| MOD-10 | 定时健康探测任务 | L3 |

---

## 7. 关键设计决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | 凭据独立表 + 多版本 | 支持轮换期新旧并存，切换失败可回滚 |
| D2 | 只提供连接对象，不提供凭据 | 最小权限暴露，避免凭据扩散到各模块内存与日志 |
| D3 | 应用层加密而非数据库层 | 密钥不入库，DBA 无法解密；便于 KMS 接入 |
| D4 | 强制只读校验 | 元数据平台绝不应具备业务库写权限，是安全底线 |
| D5 | 能力位前置到数据源 | 下游模块据此决定是否下发任务，避免 MySQL 采样等无谓失败 |
| D6 | 删除走异步分批 | 避免千万行级联（NFR-1） |

---

## 8. 异常与边界处理

| 场景 | 处理 |
|---|---|
| 连通性测试超时 | 可配超时（默认 10s），超时返回明确错误不保存 |
| 凭据解密失败 | 标记数据源异常，告警，不重试无限次 |
| 具备写权限 | 默认拒绝；管理员显式放行需审计并标记风险 |
| 凭据轮换后连接失败 | 保留旧版本可快速回滚；`is_active` 切换仅在验证通过后 |
| 数据源被删除但任务在跑 | 运行中任务检测到 `deleted_at` 后主动中止（幂等） |
| 并发编辑同一数据源 | 乐观锁（`updated_at` 比对） |

---

## 9. 验收标准

1. 注册数据源时凭据以密文入库，数据库中检索不到明文
2. 具备写权限的连接被拒绝并给出明确提示
3. 凭据轮换过程中不中断采集，失败可回滚
4. 任何模块无法通过 API 获取明文凭据
5. 删除数据源不产生长事务；千万级数据下清理可分批中断续跑
6. 所有凭据变更与连接获取均有审计记录
