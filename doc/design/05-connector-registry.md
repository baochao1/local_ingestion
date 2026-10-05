# 连接器注册表 · 数据源扩展机制

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 编写日期 | 2026-10-02 |
| 依赖文档 | `04-code-boundary-upstream-vs-local.md`（L1/L3 边界，ADR-9）、`MOD-02-scan-persistence.md` |
| 改动范围 | 新增 `src/local_ingestion/platform/connectors/`；改造 `platform/scan/service.py`；`pyproject.toml` extras |
| 配套产物 | 无 |

---

## 1. 背景与动机

### 1.1 改造前的问题

`ScanService` 把 PostgreSQL 写死在三处：

- 模块级 `from local_ingestion.core.connectors.postgres import PostgresSourceConnector`
- 默认工厂 `lambda: PostgresSourceConnector()`
- `build_source_connection()` 硬编码返回 `PostgresConnection`
- `SUPPORTED_DS_TYPES = frozenset({"postgres", "postgresql"})` 常量

项目里 `core/connectors/{mysql,snowflake}.py`（L1）虽然已经实现了 `SourceConnector` 全部方法（查 `information_schema`），但因为没有注册到扫描链路，**接一个 MySQL 数据源要改主程序 3~4 处**——这正是"写死"。

### 1.2 为什么不复刻 OpenMetadata 的 `ServiceSpec`

上游的 `ServiceSpec` 是约定路径下的清单类，用字符串声明 `metadata_source_class` / `lineage_source_class` / `usage_source_class` 等字段，由 `importlib` 动态导入。

它的两个真实目的决定了我们**不照搬**：

1. **延迟导入以隔离重依赖**：声明成字符串，用到时才 `import`，未装 mysql 的环境不会因为 import 一个 connector 就把 `pymysql` 拖进来。
2. **一个服务支持多种 ingestion 类型**（metadata / lineage / usage / profiler），所以需要一串字段。

本项目只有 metadata 一种 ingestion 类型，没有多类型多态需求；且上游用约定文件路径（`metadata.ingestion.source.<type>.<name>.service_spec`）会逼第三方把代码塞进我们的目录树，对二开项目反而更难维护。因此我们**只保留"字符串声明 + 动态导入"这一条核心思想**，简化为「一个 `ds_type` → 一个 `ConnectorSpec`」。

### 1.3 边界约束（来自 04 文档 ADR-9）

`core/connectors/` 是 L1 上游同步区，铁律规定「L3 功能扩展不得修改 L1 文件」。因此：

- **连接器实现**仍留在 `core/connectors/`（L1，只动算法不动接线）；
- **连接器与 `ds_type` 的映射**放 `platform/connectors/`（L3，自由变更）。

---

## 2. 设计

### 2.1 核心类型 `ConnectorSpec`

```python
@dataclass(frozen=True)
class ConnectorSpec:
    ds_types: Tuple[str, ...]      # 支持的 ds_type 值（首个为 canonical）
    connector: str                 # "module:Class" → SourceConnector 子类
    connection: str                # "module:Class" → connection schema 模型
    extras: Optional[str] = None   # 可选依赖名，用于缺依赖时的安装提示
    experimental: bool = False     # 接进来但从未对真实实例跑过的连接器
    build: Optional[Callable] = None  # (conn, database, ds, conn_cls) -> conn_cfg
```

`connector` / `connection` 都是 `"module:Class"` 字符串，在**真正扫描该类型时**才由 `resolve()` 用 `importlib.import_module` 导入。这意味着导入 registry 本身**不会**把 `pymysql` / `snowflake-sqlalchemy` 带进来。

### 2.2 三种注册途径

| 途径 | 触发方式 | 适用场景 |
|---|---|---|
| 内置 | 在 `BUILTIN_SPECS` 里追加一个 `ConnectorSpec` | 主仓库维护的核心数据源 |
| entry-point | 第三方包在 `pyproject.toml` 声明 `[project.entry-points."local_ingestion.connectors"]` | **装包即生效**，无需改主项目代码、无需重新构建 |
| 环境变量 | `LOCAL_INGESTION_CONNECTOR_SPECS="your.pkg:SPEC"`（逗号分隔多个） | 调试 / 不发布包的临时接入 |

`load_external()` 在 `get_spec()` 首次被调用时幂等地扫描 entry-points 与 env 变量；单个插件加载失败只记日志、跳过，不影响其余数据源。

### 2.3 接线改造

`ScanService.run_scan` 改为：

- 校验 `ds_type not in supported_ds_types()`（`supported_ds_types()` 是函数，能看见运行时注册的外部类型，不再用常量）；
- 连接器实例由 `make_connector(ds_type)` 取得（可经 `connector_factory` 注入以测试）；
- 连接模型由 `build_connection(ds_type, conn, database, ds)` 构造，`conn` 来自 `ConnectionProvider.acquire`（只读护栏 + 审计复用）；
- `acquire` 额外接收 `connection_options(ds)`（见 §3.3）。

---

## 3. 关键决策

### 3.1 字符串声明 = 延迟导入

`ConnectorSpec` 引用类用 `"module:Class"` 而非直接导入对象。这样：

- 没装 `pymysql` 的机器仍能扫 PostgreSQL；
- 缺依赖暴露时，`make_connector` 抛 `ConnectorImportError`，信息带安装提示：
  `请安装可选依赖：pip install "local-ingestion[mysql]"`。

### 3.2 extras 拆分与需求对齐

`pymysql` / `snowflake-sqlalchemy` 从主 `dependencies` 移到 `[project.optional-dependencies]`：

```toml
mysql     = ["pymysql>=1.0"]
snowflake = ["snowflake-sqlalchemy>=1.0"]
all       = ["local-ingestion[mysql,snowflake]"]
```

`psycopg2-binary` 保留为主依赖——本产品目录存储本身就是 PostgreSQL，且它是唯一经真实 E2E 验证过的连接器。这一步让"插件化"闭环：装包 → 装驱动 → 类型可扫描。

### 3.3 Snowflake 的 `account` / `warehouse` / `role` 约定

`SnowflakeConnection` 需要 `account`（必填）、`warehouse`、`role`，而这些**不在 SQLAlchemy URL 里**。约定：

- `account` 取数据源的 `host` 字段（`snowflake://user:pw@<account>/db`）；
- `warehouse` / `role` 通过 `scan_config.connection_options` 经 `ConnectionProvider.acquire(options=...)` 进入 URL query，再由 snowflake 专属 `build` 函数取出。

这样无需为 Snowflake 拓宽 `datasource` 表结构。MySQL / PostgreSQL 走默认 `build`（host/port/username/password/database 取自 URL，端口缺省回退到方言默认端口）。

### 3.4 experimental 标记

MySQL / Snowflake 标 `experimental=True`。第一次被 `make_connector` 用到时打一条 warning，使"从未对真实实例跑过"这一事实持续可见。

---

## 4. 使用

### 4.1 内置类型

安装对应 extras 后直接可用：

```bash
pip install "local-ingestion[mysql]"        # 或 [snowflake] / [all]
local-ingest scan run --datasource my_mysql
```

已注册：`postgres` / `postgresql`、`mysql` / `mariadb`、`snowflake`。

### 4.2 第三方包（entry-point）

```python
# 在 your_connector_pkg/specs.py
from local_ingestion.platform.connectors import ConnectorSpec

class ClickHouseSource:
    ...

SPEC = ConnectorSpec(
    ds_types=("clickhouse",),
    connector="your_connector_pkg.source:ClickHouseSource",
    connection="local_ingestion.schema.service.connection:PostgresConnection",
)
```

```toml
# pyproject.toml
[project.entry-points."local_ingestion.connectors"]
clickhouse = "your_connector_pkg.specs:SPEC"
```

`pip install your-connector-pkg` 之后，无需改动主项目，`ds_type="clickhouse"` 即可被 `scan run` 调度。`ConnectorSpec` 可被注册多次（也可直接是返回 spec 的 callable）。

### 4.3 临时接入（环境变量）

```bash
LOCAL_INGESTION_CONNECTOR_SPECS="your_connector_pkg.specs:SPEC" local-serve
```

---

## 5. 验证

- 单测 `tests/unit/platform/test_connector_registry.py`：分发正确性、大小写/空白归一、重复注册拒绝、缺依赖提示文案、env 动态导入、entry-point 两种 API 形态（含无 `select` 的旧式 mapping）、各 `build` 函数、experimental 仅 warn 一次、`ScanService` 对未知类型抛 `UnsupportedDatasourceError`。
- 真实发现验证：构造与 `pip install` 产物等价的 `*.dist-info/entry_points.txt` 置于 `PYTHONPATH`，新进程中 `demo` 类型被发现且可实例化；移除路径后如期报 `UnknownConnectorError`。
- PostgreSQL 端到端回归：经 registry 调度后摄取行为与改造前一致（目录表真实写入）。

---

## 6. 已知限制

1. **MySQL / Snowflake 标为 experimental**：连接器实现存在但**从未对真实实例执行过**；目前只验证了「分发正确性」。接入真实实例并跑通 E2E 后，方可摘除 `experimental`。
2. **连接模型仍集中声明**：`connection` 字段指向 `schema.service.connection` 下的既有模型（L1）。若某数据源需要全新的连接字段，仍需在上游同步区的连接模型里扩字段或走 L2 转换层——这是 ADR-9 对 L1 的约束，非本机制的缺陷。
3. **`acquire` 的只读护栏与审计**：外部连接器完全复用 `ConnectionProvider`，因此继承 FR-1.5 只读校验与连接审计；自定义连接器不必自行实现。
