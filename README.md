# Local Ingestion Module

轻量级本地元数据摄取模块，支持本地开发和测试环境。

## 功能特性

- **多数据库支持**: 连接 MySQL、PostgreSQL、Snowflake 等数据源
- **流水线引擎**: 可配置的 ETL 流水线，支持并行执行
- **工作流调度**: Cron 和间隔调度工作流
- **数据质量检查**: 内置数据质量验证和分析
- **可观测性**: Prometheus 指标和健康检查端点
- **通知系统**: Email 和 Webhook 告警
- **命令行工具**: 简洁的命令行摄取和启动接口

## 快速开始

### 安装

```bash
pip install -e .
```

### 运行元数据摄取

```bash
local-ingest --config examples/config_mysql.yaml
```

### 启动 API 服务

```bash
local-serve --host 0.0.0.0 --port 8080
```

## 配置示例

参考 `examples/` 目录下的配置模板：

| 配置文件 | 说明 |
|---------|------|
| `config_mysql.yaml` | MySQL 数据源配置 |
| `config_postgres.yaml` | PostgreSQL 数据源配置 |
| `config_snowflake.yaml` | Snowflake 数据源配置 |
| `workflow_etl.yaml` | 完整 ETL 工作流配置 |

## 项目结构

```
local-ingestion/
├── src/local_ingestion/
│   ├── api/              # REST API 服务
│   ├── cli/              # 命令行工具
│   ├── core/             # 核心引擎
│   │   ├── connectors/   # 数据库连接器
│   │   ├── engine/       # 工作流引擎
│   │   └── pipeline/     # 流水线执行
│   ├── observability/    # 可观测性 (Metrics, Alerts, Health)
│   ├── quality/          # 数据质量 (Rules, Validator, Reporter)
│   ├── integrations/     # 集成扩展 (Webhook, Notifications, Plugins)
│   └── schema/           # 数据模型
├── tests/                # 测试
│   └── unit/             # 含 integrations/（跨进程集成用例）
│                         # tests/integration/ 目录尚未建立
├── examples/             # 配置示例
├── .github/workflows/    # CI/CD 配置
├── pyproject.toml
└── README.md
```

## 模块说明

### Core - 核心引擎

| 模块 | 说明 |
|------|------|
| `connectors` | MySQL, PostgreSQL, Snowflake 连接器 |
| `engine` | WorkflowRunner, Scheduler, State, Monitor |
| `pipeline` | TablePipeline, DatabasePipeline, ParallelPipeline |

### Observability - 可观测性

| 模块 | 说明 |
|------|------|
| `metrics` | Prometheus 指标收集 (Counter, Gauge, Histogram) |
| `alerts` | 告警系统 (FailureThreshold, LatencyThreshold) |
| `health` | 健康检查 (Database, MessageQueue, Storage) |

### Quality - 数据质量

| 模块 | 说明 |
|------|------|
| `rules` | 质量规则 (not_null, unique, range_check, pattern_match) |
| `validator` | 验证引擎 (TableValidator, ColumnValidator, BatchValidator) |
| `reporter` | 报告生成 (HTML/JSON, 导出到 OpenMetadata) |

### Integrations - 集成扩展

| 模块 | 说明 |
|------|------|
| `webhook` | Webhook 通知 (异步发送, HMAC 签名验证) |
| `notifications` | 通知服务 (Email, Slack) |
| `plugins` | 插件系统 (动态加载, 热插拔) |

## 开发

### 环境设置

```bash
pip install -e ".[dev,test]"
```

### 运行测试

```bash
# 所有测试
pytest tests/ -v

# 单元测试
pytest tests/unit/ -v

# 集成测试
pytest tests/unit/integrations/ -v
```

> 注：`tests/integration/`（跨进程/真实数据源）目录尚未建立，当前集成测试位于
> `tests/unit/integrations/`。运行前需安装测试依赖：`pip install -e ".[test]"`；
> 缺少 `aiohttp` / `pytest-asyncio` 时该目录会收集失败。

### 代码检查

```bash
# Lint
ruff check src/

# 格式化
ruff format src/

# 类型检查
mypy src/
```

## CI/CD

GitHub Actions 工作流：

- **CI** (`.github/workflows/ci.yml`): Lint, Test (Python 3.10-3.12), Build, Security Scan
- **CD** (`.github/workflows/cd.yml`): Build, Integration Tests, PyPI Publish, Staging/Production Deploy

## 测试覆盖

实测统计（`pytest tests/unit -q`，2026-09-30）：

| 模块 | 测试数 |
|------|--------|
| Schema | 28 |
| API | 92 |
| CLI | 104 |
| Core (connectors, pipeline, engine) | 159 |
| Observability (metrics, alerts, health) | 92 |
| Platform (pagination, serialization, credentials, connections) | 122 |
| Quality (rules, validator, reporter) | 85 |
| Integrations (webhook, notifications, plugins) | 72 |
| **总计** | **754** |

## 许可证

本模块是 OpenMetadata 项目的一部分，基于 [Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0) 发布。
