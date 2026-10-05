# Local Ingestion API 接口文档

> 自动生成自 OpenAPI 规范（版本 `0.1.0`）。

> 基础路径：`/api/v1`。当前部署未启用鉴权（快照于 2026-10-02，以实际部署为准）。


本文件供后续 Web 前端对接使用：列出全部端点的路径、方法、参数与请求体字段，文末附数据模型（响应结构）、枚举值与对接约定。

## 目录

- **Health**

  - `GET /health` — Health Check

- **Root**

  - `GET /` — Root

- **Tables**

  - `POST /api/v1/tables` — Create Table

  - `GET /api/v1/tables` — List Tables

  - `GET /api/v1/tables/{qualified_name}` — Get Table

- **Databases**

  - `POST /api/v1/databases` — Create Database

  - `GET /api/v1/databases` — List Databases

  - `GET /api/v1/databases/{qualified_name}` — Get Database

- **Workflows**

  - `GET /api/v1/workflows` — List Workflows

  - `POST /api/v1/workflows` — Create Workflow

  - `GET /api/v1/workflows/{workflow_id}` — Get Workflow

  - `DELETE /api/v1/workflows/{workflow_id}` — Delete Workflow

- **DataSources**

  - `POST /api/v1/datasources` — Register Datasource

  - `GET /api/v1/datasources` — List Datasources

  - `POST /api/v1/datasources/test` — Test Connection

  - `GET /api/v1/datasources/{datasource_id}` — Get Datasource

  - `PUT /api/v1/datasources/{datasource_id}` — Update Datasource

  - `DELETE /api/v1/datasources/{datasource_id}` — Delete Datasource

  - `POST /api/v1/datasources/{datasource_id}/enable` — Enable Datasource

  - `POST /api/v1/datasources/{datasource_id}/disable` — Disable Datasource

  - `POST /api/v1/datasources/{datasource_id}/credentials` — Add Credential

  - `POST /api/v1/datasources/{datasource_id}/credentials/{version}/activate` — Activate Credential

  - `GET /api/v1/datasources/{datasource_id}/health` — Datasource Health

- **Scans**

  - `POST /api/v1/datasources/{datasource_id}/classify` — Classify Datasource

  - `POST /api/v1/datasources/{datasource_id}/scan` — Run Scan

- **Search**

  - `GET /api/v1/search` — Search

- **Assets**

  - `GET /api/v1/assets/{fqn}` — Asset Detail

- **Changes**

  - `GET /api/v1/changes/statistics` — Get Statistics

  - `GET /api/v1/changes` — List Changes

  - `GET /api/v1/changes/entities/{entity_type}/{entity_fqn}/history` — Entity History

  - `GET /api/v1/changes/{change_id}` — Get Change

  - `POST /api/v1/changes/{change_id}/ack` — Ack Change

- **Catalog**

  - `GET /api/v1/catalog/overview` — Overview

- **Lineage**

  - `GET /api/v1/lineage/tables/{fqn}/impact` — Impact

- **Business Metadata**

  - `GET /api/v1/business/terms` — List Terms

  - `POST /api/v1/business/terms` — Create Term

  - `GET /api/v1/business/terms/{term_code}` — Get Term

  - `GET /api/v1/business/entities/{entity_type}/{entity_id}` — Get Entity Metadata

  - `PUT /api/v1/business/entities/{entity_type}/{entity_id}` — Put Entity Metadata

  - `POST /api/v1/business/entities/{entity_type}/{entity_id}/tags` — Set Entity Tags

- **Meta**

  - `GET /api/v1/meta/degradation` — Degradation

- **Governance**（MOD-12 审批流 + 工单）

  - `POST /api/v1/governance/approvals` — 提交审批
  - `GET /api/v1/governance/approvals` — 审批列表
  - `GET /api/v1/governance/approvals/{id}` — 审批详情
  - `POST /api/v1/governance/approvals/{id}/approve` — 通过
  - `POST /api/v1/governance/approvals/{id}/reject` — 驳回
  - `GET /api/v1/governance/approvals/{id}/comments` — 审批评论
  - `POST /api/v1/governance/approvals/{id}/comments` — 追加评论
  - `POST /api/v1/governance/tickets` — 创建工单
  - `GET /api/v1/governance/tickets` — 工单列表
  - `GET /api/v1/governance/tickets/{id}` — 工单详情
  - `POST /api/v1/governance/tickets/{id}/assign` — 分派
  - `POST /api/v1/governance/tickets/{id}/transition` — 状态流转
  - `GET /api/v1/governance/tickets/{id}/comments` — 工单评论
  - `POST /api/v1/governance/tickets/{id}/comments` — 追加评论

- **System**（MOD-10 健康与运行时指标）

  - `GET /api/v1/system/health` — System Health
  - `GET /api/v1/system/metrics` — Runtime Metrics

- **Tasks**（MOD-10 任务运维 / T-107）

  - `GET /api/v1/tasks` — 任务列表（job_type/status/datasourceId 过滤）
  - `POST /api/v1/tasks` — 提交任务
  - `GET /api/v1/tasks/{id}` — 任务详情
  - `POST /api/v1/tasks/{id}/cancel` — 取消
  - `POST /api/v1/tasks/{id}/retry` — 重试
  - `GET /api/v1/tasks/partitions` — 分区状态（运维视角）

- **Audit**（MOD-10 审计日志 / FR-15.5）

  - `GET /api/v1/audit-logs` — 审计日志（action/actor/entityType/limit 过滤）


---

## Health


### `GET /health`

**Health Check**


Health check endpoint


**响应状态码**


- `200`: Successful Response


---

## Root


### `GET /`

**Root**


Root endpoint


**响应状态码**


- `200`: Successful Response


---

## Tables


### `POST /api/v1/tables`

**Create Table**


Create a new table


**请求体（application/json）**


| 字段 | 类型 | 必填 | 默认 | 说明 |

|------|------|------|------|------|

| name | string | 是 |  |  |

| fullyQualifiedName | string | 是 |  |  |

| description | string/null | 否 |  |  |

| columns | array | 否 | [] |  |

| database | string/null | 否 |  |  |

| databaseSchema | string/null | 否 |  |  |


**响应状态码**


- `201`: Successful Response

- `422`: Validation Error


### `GET /api/v1/tables`

**List Tables**


List all tables


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| database | query | string/null | 否 |  |

| databaseSchema | query | string/null | 否 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `GET /api/v1/tables/{qualified_name}`

**Get Table**


Get table by qualified name


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| qualified_name | path | string | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


---

## Databases


### `POST /api/v1/databases`

**Create Database**


Create a new database


**请求体（application/json）**


| 字段 | 类型 | 必填 | 默认 | 说明 |

|------|------|------|------|------|

| name | string | 是 |  |  |

| fullyQualifiedName | string | 是 |  |  |

| description | string/null | 否 |  |  |

| owner | string/null | 否 |  |  |


**响应状态码**


- `201`: Successful Response

- `422`: Validation Error


### `GET /api/v1/databases`

**List Databases**


List all databases


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| owner | query | string/null | 否 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `GET /api/v1/databases/{qualified_name}`

**Get Database**


Get database by qualified name


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| qualified_name | path | string | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


---

## Workflows


### `GET /api/v1/workflows`

**List Workflows**


List all workflows


**响应状态码**


- `200`: Successful Response


### `POST /api/v1/workflows`

**Create Workflow**


Create a new workflow


**请求体（application/json）**


（无字段定义或为 `$ref` 引用）


**响应状态码**


- `201`: Successful Response

- `422`: Validation Error


### `GET /api/v1/workflows/{workflow_id}`

**Get Workflow**


Get workflow by ID


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| workflow_id | path | string | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `DELETE /api/v1/workflows/{workflow_id}`

**Delete Workflow**


Delete workflow


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| workflow_id | path | string | 是 |  |


**响应状态码**


- `204`: Successful Response

- `422`: Validation Error


---

## DataSources


### `POST /api/v1/datasources`

**Register Datasource**


**请求体（application/json）**


| 字段 | 类型 | 必填 | 默认 | 说明 |

|------|------|------|------|------|

| code | string | 是 |  |  |

| name | string | 是 |  |  |

| dsType | string | 是 |  |  |

| host | string/null | 否 |  |  |

| port | integer/null | 否 |  |  |

| environment | string/null | 否 |  |  |

| groupName | string/null | 否 |  |  |

| ownerBusiness | string/null | 否 |  |  |

| ownerTechnical | string/null | 否 |  |  |

| enabled | boolean | 否 | True |  |

| scanEnabled | boolean | 否 | True |  |

| samplingEnabled | boolean | 否 | False |  |

| username | string/null | 否 |  |  |

| password | string/null | 否 |  |  |

| scanConfig | object | 否 |  |  |

| samplingConfig | object | 否 |  |  |

| allowWrite | boolean | 否 | False |  |


**响应状态码**


- `201`: Successful Response

- `422`: Validation Error


### `GET /api/v1/datasources`

**List Datasources**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| enabled | query | boolean/null | 否 |  |

| environment | query | string/null | 否 |  |

| group | query | string/null | 否 |  |

| type | query | string/null | 否 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `POST /api/v1/datasources/test`

**Test Connection**


**请求体（application/json）**


| 字段 | 类型 | 必填 | 默认 | 说明 |

|------|------|------|------|------|

| dsType | string | 是 |  |  |

| host | string/null | 否 |  |  |

| port | integer/null | 否 |  |  |

| username | string/null | 否 |  |  |

| password | string/null | 否 |  |  |

| database | string/null | 否 |  |  |

| options | object/null | 否 |  |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `GET /api/v1/datasources/{datasource_id}`

**Get Datasource**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| datasource_id | path | integer | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `PUT /api/v1/datasources/{datasource_id}`

**Update Datasource**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| datasource_id | path | integer | 是 |  |


**请求体（application/json）**


| 字段 | 类型 | 必填 | 默认 | 说明 |

|------|------|------|------|------|

| name | string/null | 否 |  |  |

| host | string/null | 否 |  |  |

| port | integer/null | 否 |  |  |

| environment | string/null | 否 |  |  |

| groupName | string/null | 否 |  |  |

| ownerBusiness | string/null | 否 |  |  |

| ownerTechnical | string/null | 否 |  |  |

| enabled | boolean/null | 否 |  |  |

| scanEnabled | boolean/null | 否 |  |  |

| samplingEnabled | boolean/null | 否 |  |  |

| scanConfig | object/null | 否 |  |  |

| samplingConfig | object/null | 否 |  |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `DELETE /api/v1/datasources/{datasource_id}`

**Delete Datasource**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| datasource_id | path | integer | 是 |  |


**响应状态码**


- `204`: Successful Response

- `422`: Validation Error


### `POST /api/v1/datasources/{datasource_id}/enable`

**Enable Datasource**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| datasource_id | path | integer | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `POST /api/v1/datasources/{datasource_id}/disable`

**Disable Datasource**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| datasource_id | path | integer | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `POST /api/v1/datasources/{datasource_id}/credentials`

**Add Credential**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| datasource_id | path | integer | 是 |  |


**请求体（application/json）**


| 字段 | 类型 | 必填 | 默认 | 说明 |

|------|------|------|------|------|

| username | string | 是 |  |  |

| password | string | 是 |  |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `POST /api/v1/datasources/{datasource_id}/credentials/{version}/activate`

**Activate Credential**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| datasource_id | path | integer | 是 |  |

| version | path | integer | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `GET /api/v1/datasources/{datasource_id}/health`

**Datasource Health**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| datasource_id | path | integer | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


---

## Scans


### `POST /api/v1/datasources/{datasource_id}/classify`

**Classify Datasource**


(Re-)grade the datasource's catalog rows without rescanning.


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| datasource_id | path | integer | 是 |  |


**请求体（application/json）**


（无字段定义或为 `$ref` 引用）


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `POST /api/v1/datasources/{datasource_id}/scan`

**Run Scan**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| datasource_id | path | integer | 是 |  |


**请求体（application/json）**


（无字段定义或为 `$ref` 引用）


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


---

## Search


### `GET /api/v1/search`

**Search**


Search tables and columns of the catalog.


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| term | query | string/null | 否 |  |

| type | query | string/null | 否 | table | column |

| datasourceId | query | integer/null | 否 |  |

| tags | query | array/null | 否 |  |

| owner | query | string/null | 否 |  |

| sensitiveOnly | query | boolean | 否 |  |

| gradeMin | query | integer/null | 否 | 按 grade_level≥N 过滤（1–9） |

| limit | query | integer | 否 |  |

| offset | query | integer | 否 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


---

## Assets


### `GET /api/v1/assets/{fqn}`

**Asset Detail**


Detail card for one asset (table fqn).


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| fqn | path | string | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


---

## Changes


### `GET /api/v1/changes/statistics`

**Get Statistics**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| since | query | string/null | 否 |  |

| until | query | string/null | 否 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `GET /api/v1/changes`

**List Changes**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| severity | query | string/null | 否 |  |

| datasource_id | query | integer/null | 否 |  |

| entity_type | query | string/null | 否 |  |

| entity_fqn | query | string/null | 否 |  |

| ack_status | query | string/null | 否 |  |

| limit | query | integer | 否 |  |

| offset | query | integer | 否 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `GET /api/v1/changes/entities/{entity_type}/{entity_fqn}/history`

**Entity History**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| entity_type | path | string | 是 |  |

| entity_fqn | path | string | 是 |  |

| limit | query | integer | 否 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `GET /api/v1/changes/{change_id}`

**Get Change**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| change_id | path | integer | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `POST /api/v1/changes/{change_id}/ack`

**Ack Change**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| change_id | path | integer | 是 |  |


**请求体（application/json）**


| 字段 | 类型 | 必填 | 默认 | 说明 |

|------|------|------|------|------|

| actor | string | 是 |  |  |

| action | string | 是 |  |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


---

## Catalog


### `GET /api/v1/catalog/overview`

**Overview**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| trend_days | query | integer | 否 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


---

## Lineage


### `GET /api/v1/lineage/tables/{fqn}/impact`

**Impact**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| fqn | path | string | 是 |  |

| max_depth | query | integer | 否 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


---

## Business Metadata


### `GET /api/v1/business/terms`

**List Terms**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| domain | query | string/null | 否 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `POST /api/v1/business/terms`

**Create Term**


**请求体（application/json）**


| 字段 | 类型 | 必填 | 默认 | 说明 |

|------|------|------|------|------|

| term_code | string | 是 |  |  |

| term_name | string | 是 |  |  |

| domain | string/null | 否 |  |  |

| definition | string/null | 否 |  |  |

| owner | string/null | 否 |  |  |

| status | string | 否 | active |  |


**响应状态码**


- `201`: Successful Response

- `422`: Validation Error


### `GET /api/v1/business/terms/{term_code}`

**Get Term**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| term_code | path | string | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `GET /api/v1/business/entities/{entity_type}/{entity_id}`

**Get Entity Metadata**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| entity_type | path | string | 是 |  |

| entity_id | path | integer | 是 |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `PUT /api/v1/business/entities/{entity_type}/{entity_id}`

**Put Entity Metadata**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| entity_type | path | string | 是 |  |

| entity_id | path | integer | 是 |  |


**请求体（application/json）**


| 字段 | 类型 | 必填 | 默认 | 说明 |

|------|------|------|------|------|

| alias | string/null | 否 |  |  |

| business_desc | string/null | 否 |  |  |

| domain | string/null | 否 |  |  |

| owner_business | string/null | 否 |  |  |

| term_codes | array/null | 否 |  |  |

| tags | object/null | 否 |  |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


### `POST /api/v1/business/entities/{entity_type}/{entity_id}/tags`

**Set Entity Tags**


**路径 / 查询参数**


| 名称 | 位置 | 类型 | 必填 | 说明 |

|------|------|------|------|------|

| entity_type | path | string | 是 |  |

| entity_id | path | integer | 是 |  |


**请求体（application/json）**


| 字段 | 类型 | 必填 | 默认 | 说明 |

|------|------|------|------|------|

| tags | object | 是 |  |  |


**响应状态码**


- `200`: Successful Response

- `422`: Validation Error


---

## Meta


### `GET /api/v1/meta/degradation`

**Degradation**


**响应状态码**


- `200`: Successful Response


---

## Governance（MOD-12 审批流 + 工单）

> 全部端点基座 `/api/v1/governance`。默认内存栈运行；生产可切 SQL。详见 `MOD-12-governance.md`。

### `POST /api/v1/governance/approvals`

**提交审批请求**

请求体字段：`resource_type`(asset/classification/sensitive_tag/datasource)、`resource_fqn`、`action_type`(publish/classify/sensitive_tag/delete)、`title`、`requested_by`、`approver?`、`priority?`(默认 P2)、`reason?`、`actor?`

**响应状态码**

- `201`: 创建成功，返回审批对象
- `422`: action_type 非法

### `GET /api/v1/governance/approvals`

**审批列表**。query：`status`(pending/approved/rejected)、`resource_type`、`approver`、`limit`(默认50)、`offset`

### `GET /api/v1/governance/approvals/{id}`

**审批详情**。→ `404` 不存在

### `POST /api/v1/governance/approvals/{id}/approve`

**通过审批**。body：`actor`、`comment?`。→ `409` 已决策；`404` 不存在

### `POST /api/v1/governance/approvals/{id}/reject`

**驳回审批**。body：`actor`、`comment?`。→ `409` 已决策；`404` 不存在

### `GET /api/v1/governance/approvals/{id}/comments`

**审批评论列表**（按时间升序）

### `POST /api/v1/governance/approvals/{id}/comments`

**追加审批评论**。body：`author`、`body`

### `POST /api/v1/governance/tickets`

**创建工单**。body：`title`、`description?`、`ticket_type?`(data_issue/access_request/other)、`priority?`(默认P2)、`reporter?`、`assignee?`、`related_fqn?`、`source?`(manual)、`sla_hours?`、`actor?`

→ `422`：ticket_type 非法

### `GET /api/v1/governance/tickets`

**工单列表**。query：`status`(open/in_progress/resolved/closed)、`ticket_type`、`assignee`、`reporter`、`related_fqn`、`limit`、`offset`

### `GET /api/v1/governance/tickets/{id}`

**工单详情**。→ `404` 不存在

### `POST /api/v1/governance/tickets/{id}/assign`

**分派处理人**。body：`assignee`、`actor?`

### `POST /api/v1/governance/tickets/{id}/transition`

**状态流转**。body：`to_status`、`actor?`。合法：`open→{in_progress}`、`in_progress→{resolved}`、`resolved→{in_progress,closed}`、`closed→in_progress`（FR-17.5：中间状态不可跳过）

→ `422`：非法转移

### `GET /api/v1/governance/tickets/{id}/comments`

**工单评论列表**

### `POST /api/v1/governance/tickets/{id}/comments`

**追加工单评论**。body：`author`、`body`

---

## System（MOD-10 健康与运行时指标）

> 基座 `/api/v1/system`。供前端健康条（FE-01 §2）与运维页（§11.3/§11.4）使用，亦可作为外部监控探针。

### `GET /api/v1/system/health`

**系统健康**，返回整体状态与各组件检查结果。

**响应字段**：`status`(healthy|degraded)、`timestamp`、`components[]`（`component`、`status`、`message`）

- 数据库探针为「尽力而为」：默认内存栈无 Postgres 时，数据库组件返回 `degraded`（整体 `degraded`），不会让整个健康调用失败。

### `GET /api/v1/system/metrics`

**运行时指标**：`uptimeSeconds`、`appVersion`、`pythonVersion`、`environment`、`startedAt`。

> 业务侧指标（变更统计、审批/工单计数等）由各模块端点提供：`GET /api/v1/changes/statistics`、`GET /api/v1/governance/approvals`、`GET /api/v1/governance/tickets`。

---

## Tasks（MOD-10 任务运维 / T-107）

> 基座 `/api/v1/tasks`。复用 `platform/orchestration` 的 `TaskService`，存储为进程内单例（`InMemoryTaskRunStore`）。默认内存栈下任务运行记录存于进程内存，重启即清空；接入 Postgres 时改用 `SqlTaskRunStore(session_scope)`（落到 `scan_run` 表）。

**执行模型（异步）**：任务在线程池（`ThreadPoolExecutor`，默认 4 worker，低于编排全局并发上限 8）中后台执行。提交/重试**立即返回**（不阻塞 HTTP 请求），前端轮询 `GET /api/v1/tasks/{id}` 观察 `pending → running → success/failed/cancelled`。返回的 run 是 worker 共享的活动对象，其 `status` 在被序列化时可能已推进到 `running` 甚至终态，属正常现象。

### `GET /api/v1/tasks`

**任务列表**，支持过滤。

**查询参数**：`jobType`(metadata|sample|profile|classify|lineage|permission)、`status`(pending|running|success|failed|cancelled|timeout)、`datasourceId`(int)

**出参**：`{ items: [TaskRun], total }`

### `POST /api/v1/tasks`

**提交并后台执行任务**。请求体：`{ jobType, scope, trigger(manual|cron|event), concurrencyKey?, priority?, payload? }`。同一 `jobType+scope` 存在活跃任务时返回 `409`（重入保护）。成功后立即返回（通常为 `pending`），任务在线程池中执行。

### `GET /api/v1/tasks/{id}`

**任务详情**（含 `stats`/`payload`/时间字段）。

### `POST /api/v1/tasks/{id}/cancel`

取消 pending/running 任务。pending 直接置 `cancelled`；running 发取消信号。返回 `{ cancelled, task }`。

### `POST /api/v1/tasks/{id}/retry`

仅对 `failed`/`cancelled` 任务可重试（其余返回 `409`），提交一个新运行并后台执行，立即返回。

### `GET /api/v1/tasks/partitions`

**分区状态（运维视角）**。内省 `platform/storage/models_ops.py` 的 ORM 声明式分区（`postgresql_partition_by`），返回各操作表的分区方案：`{ items: [{ table, partitionStrategy, partitionKey, retentionWindowDays, managedBy }], total, note }`。分区创建/保留在数据库层执行，接口仅声明方案（只读）。

---

## Audit（MOD-10 审计日志 / FR-15.5）

> 基座 `/api/v1/audit-logs`。读取进程级共享 sink `GLOBAL_AUDIT_SINK`（默认内存栈）。当前仅「接入该共享 sink 的服务」所写条目可见——编排 `TaskService`（任务 submit/cancel/retry/success/failure）已接入；其余服务（数据源、治理等）仍使用各自独立 sink，需指向 `GLOBAL_AUDIT_SINK` 才会出现。

### `GET /api/v1/audit-logs`

**查询参数**：`action`、`actor`、`entityType`、`limit`(默认 100，最大 1000)

**出参**：`{ items: [AuditEntry], total }`，按 `occurredAt` 倒序。`AuditEntry`：`actor / action / entityType / entityFqn / detail / clientIp / result / occurredAt`。

---

## 数据模型（Schemas）

> 响应体引用的对象结构。嵌套对象以类型名标注，可在此章节检索。


### AckRequest

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| actor | string | 是 |  |

| action | string | 是 |  |


### ClassifyRequest

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| all | boolean | 否 |  |


### CredentialCreate

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| username | string | 是 |  |

| password | string | 是 |  |


### DatabaseCreate

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| name | string | 是 |  |

| fullyQualifiedName | string | 是 |  |

| description | string/null | 否 |  |

| owner | string/null | 否 |  |


### DatasourceCreate

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| code | string | 是 |  |

| name | string | 是 |  |

| dsType | string | 是 |  |

| host | string/null | 否 |  |

| port | integer/null | 否 |  |

| environment | string/null | 否 |  |

| groupName | string/null | 否 |  |

| ownerBusiness | string/null | 否 |  |

| ownerTechnical | string/null | 否 |  |

| enabled | boolean | 否 |  |

| scanEnabled | boolean | 否 |  |

| samplingEnabled | boolean | 否 |  |

| username | string/null | 否 |  |

| password | string/null | 否 |  |

| scanConfig | object | 否 |  |

| samplingConfig | object | 否 |  |

| allowWrite | boolean | 否 |  |


### DatasourceUpdate

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| name | string/null | 否 |  |

| host | string/null | 否 |  |

| port | integer/null | 否 |  |

| environment | string/null | 否 |  |

| groupName | string/null | 否 |  |

| ownerBusiness | string/null | 否 |  |

| ownerTechnical | string/null | 否 |  |

| enabled | boolean/null | 否 |  |

| scanEnabled | boolean/null | 否 |  |

| samplingEnabled | boolean/null | 否 |  |

| scanConfig | object/null | 否 |  |

| samplingConfig | object/null | 否 |  |


### HTTPValidationError

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| detail | array | 否 |  |


### HealthResponse

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| status | string | 是 |  |

| version | string | 否 |  |


### MetadataBody

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| alias | string/null | 否 |  |

| business_desc | string/null | 否 |  |

| domain | string/null | 否 |  |

| owner_business | string/null | 否 |  |

| term_codes | array/null | 否 |  |

| tags | object/null | 否 |  |


### ScanRequest

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| database | string/null | 否 |  |

| schemas | array/null | 否 |  |

| allowWrite | boolean | 否 |  |

| markDeleted | boolean | 否 |  |


### TableCreate

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| name | string | 是 |  |

| fullyQualifiedName | string | 是 |  |

| description | string/null | 否 |  |

| columns | array | 否 |  |

| database | string/null | 否 |  |

| databaseSchema | string/null | 否 |  |


### TagsBody

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| tags | object | 是 |  |


### TermBody

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| term_code | string | 是 |  |

| term_name | string | 是 |  |

| domain | string/null | 否 |  |

| definition | string/null | 否 |  |

| owner | string/null | 否 |  |

| status | string | 否 |  |


### TestConnectionRequest

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| dsType | string | 是 |  |

| host | string/null | 否 |  |

| port | integer/null | 否 |  |

| username | string/null | 否 |  |

| password | string/null | 否 |  |

| database | string/null | 否 |  |

| options | object/null | 否 |  |


### ValidationError

| 字段 | 类型 | 必填 | 说明 |

|------|------|------|------|

| loc | array | 是 |  |

| msg | string | 是 |  |

| type | string | 是 |  |

| input |  | 否 |  |

| ctx | object | 否 |  |


---

## 枚举值参考

(OpenAPI 中未声明枚举)


---

## 对接约定（补充）

- **`allowWrite` 为按请求覆盖、不持久化**：注册（`POST /api/v1/datasources`）与扫描（`POST /api/v1/datasources/{id}/scan`）各自独立接受 `allowWrite`。传 `true` 仅对该次请求豁免 FR-1.5 只读校验；已注册数据源本身不记录“允许写”。因此若注册时使用了写权限凭据，扫描时仍需再次传 `allowWrite: true`，否则扫描会被只读守卫拒绝。

- **安全审计**：当 `allowWrite=true` 实际豁免了只读校验时，审计事件 `datasource.register` 的 `detail` 会写入 `allow_write` 与 `fr15_bypass: true`，便于追溯。

- **安全提示**：当前整个 API 未启用鉴权，`allowWrite` 可由任意能访问服务的调用者设置；生产环境应在鉴权层或全局开关处约束其可用性。
