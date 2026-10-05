# MOD-12 协作与流程（审批流 + 工单）

| 项目 | 内容 |
|---|---|
| 模块编号 | MOD-12 |
| 负责需求 | FR-17 |
| 优先级 | P1 |
| 前置依赖 | MOD-06（破坏性变更联动建单）、MOD-10（审计 C10）、MOD-09（资产发布/标注审批入口） |
| 对应设计 | `01-product-requirements.md` §3 FR-17 |

---

## 1. 模块定位与目标

原 `01-product-requirements.md` §5.1 将「协作能力（评论、认领、审批流）」列为**本期不做**，导致对标 Alation / Collibra / OpenMetadata / DataHub 时在售前对比中被问住。本模块补全其中两项最关键的企业治理协作能力：

1. **审批流（Approval）**——资产发布、分类分级结果、敏感标注、删除等高风险动作，须由责任人**审批通过**后方可生效（human-in-the-loop）。
2. **工单（Ticket）**——数据问题、权限申请、破坏性变更跟进等工作项，具备**分派 / 状态机 / 评论线程 / SLA**，可跟踪「谁在处理、处理到哪一步」。

评论线程同时服务于审批与工单，实现「协作记录可审计」。所有决策与状态流转经 MOD-10 `audit_log` 留痕（契约 C10）。

---

## 2. 功能需求（映射 FR-17）

| 编号 | 功能 | 说明 |
|---|---|---|
| FR-17.1 | 提交审批请求 | 资源类型（asset/classification/sensitive_tag/datasource）、动作、发起人、审批人、优先级、理由 |
| FR-17.2 | 审批决策 | 通过/驳回（带意见）；决策不可重复；需重提须重新发起 |
| FR-17.3 | 审批范围 | publish / classify / sensitive_tag / delete |
| FR-17.4 | 创建工单 | 数据问题(data_issue)、权限申请(access_request)、其他(other)；含优先级 P0–P3、SLA 到期 |
| FR-17.5 | 工单状态机 | `open → in_progress → resolved → closed`，`closed → in_progress`（重开） |
| FR-17.6 | 分派与评论 | 可指派处理人；工单/审批均可追加评论与处理记录 |
| FR-17.7 | 自动建单 | FR-7 破坏性变更被确认后，自动创建 `change_auto` 工单（P0、SLA 24h） |
| FR-17.8 | 审计留痕 | 审批决策、工单流转写入 `audit_log` |
| FR-17.9 | 外部集成 | 经 MOD-10 Webhook/事件（FR-16）推送至 Jira / ServiceNow |

---

## 3. 数据模型

### 3.1 `approval_request`（审批请求）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | 自增 |
| tenant_id | BIGINT | 多租户 |
| resource_type | TEXT | asset / classification / sensitive_tag / datasource |
| resource_fqn | TEXT | 被审批资产 FQN |
| action_type | TEXT | publish / classify / sensitive_tag / delete |
| title | TEXT | 审批标题 |
| requested_by | TEXT | 发起人 |
| approver | TEXT? | 指定审批人（可空，由角色策略解析） |
| status | TEXT | pending / approved / rejected（默认 pending） |
| priority | TEXT | P0–P3（默认 P2） |
| reason | TEXT? | 申请理由 |
| decided_at / decided_by / decided_comment | — | 决策时间/人/意见 |
| created_at | TIMESTAMPTZ | — |

约束：`status IN (pending,approved,rejected)`；`action_type IN (publish,classify,sensitive_tag,delete)`。

### 3.2 `governance_ticket`（工单）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | — |
| tenant_id | BIGINT | — |
| title / description | TEXT | 标题/描述 |
| ticket_type | TEXT | data_issue / access_request / change_auto / other |
| priority | TEXT | P0–P3 |
| status | TEXT | open / in_progress / resolved / closed |
| reporter / assignee | TEXT | 报告人/处理人 |
| related_fqn | TEXT? | 关联资产/变更 FQN |
| source | TEXT | manual / change_auto |
| sla_due_at | TIMESTAMPTZ? | SLA 到期 |
| resolved_at / closed_at | TIMESTAMPTZ? | — |
| created_at / updated_at | TIMESTAMPTZ | — |

约束：`status IN (open,in_progress,resolved,closed)`；`ticket_type IN (data_issue,access_request,change_auto,other)`。

### 3.3 `governance_comment`（评论/处理记录，审批与工单共用）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | BIGINT PK | — |
| tenant_id | BIGINT | — |
| target_type | TEXT | approval / ticket |
| target_id | BIGINT | 关联 id |
| author | TEXT | 作者 |
| body | TEXT | 内容 |
| created_at | TIMESTAMPTZ | — |

约束：`target_type IN (approval,ticket)`，并建 `(target_type, target_id, created_at DESC)` 索引。

---

## 4. 状态机

### 4.1 审批
```
        submit
   ──────────────▶ pending
   pending ─approve──▶ approved (终态)
   pending ─reject──▶ rejected (终态)
```
- 已决策的审批不可再次决策（抛 `ApprovalAlreadyDecidedError`）。
- 需变更结论须重新发起审批。

### 4.2 工单
```
   open ──assign──▶ open (仅更新 assignee)
   open ──▶ in_progress ──▶ resolved ──▶ closed
                     ▲                      │
                     └──── reopen ──────────┘ (closed → in_progress)
```
合法转移表（`TICKET_TRANSITIONS`）：
- open → {in_progress, resolved, closed}
- in_progress → {resolved, closed}
- resolved → {in_progress, closed}
- closed → {in_progress}

非法转移抛 `InvalidTicketTransitionError`。

---

## 5. REST 接口（基座 `/api/v1/governance`）

> 实现见 `src/local_ingestion/api/routers/governance.py`，默认内存栈可运行，生产可切 SQL（`SqlGovernanceRepository`）。

### 5.1 审批
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/approvals` | 提交审批；body: `resource_type, resource_fqn, action_type, title, requested_by, approver?, priority?, reason?, actor?` |
| GET | `/approvals` | 列表；query: `status, resource_type, approver, limit, offset` |
| GET | `/approvals/{id}` | 详情 |
| POST | `/approvals/{id}/approve` | 通过；body: `actor, comment?` |
| POST | `/approvals/{id}/reject` | 驳回；body: `actor, comment?` |
| GET | `/approvals/{id}/comments` | 评论列表 |
| POST | `/approvals/{id}/comments` | 追加评论；body: `author, body` |

错误码：审批不存在 `404`；重复决策 `409`；动作非法 `422`。

### 5.2 工单
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/tickets` | 创建；body: `title, description?, ticket_type?, priority?, reporter?, assignee?, related_fqn?, source?, sla_hours?, actor?` |
| GET | `/tickets` | 列表；query: `status, ticket_type, assignee, reporter, related_fqn, limit, offset` |
| GET | `/tickets/{id}` | 详情 |
| POST | `/tickets/{id}/assign` | 分派；body: `assignee, actor?` |
| POST | `/tickets/{id}/transition` | 状态流转；body: `to_status, actor?` |
| GET | `/tickets/{id}/comments` | 评论列表 |
| POST | `/tickets/{id}/comments` | 追加评论；body: `author, body` |

错误码：工单不存在 `404`；非法流转 `422`。

---

## 6. 跨模块交互

| 契约 | 方向 | 说明 |
|---|---|---|
| C13 审批流接口 | MOD-12 → 提供；MOD-09（资产发布/标注审批入口）、MOD-11（按角色解析审批人）消费 | L2 |
| C14 工单接口 | MOD-12 → 提供；MOD-06（联动建单）、MOD-10（审计/通知）消费 | L2 |

### 6.1 与 MOD-06 联动（FR-17.7）
`ChangeConfirmService.ack` 支持可选回调 `on_after_ack(change, action)`（**解耦设计**：changes 模块不依赖 governance 模块）。在 `api/routers/changes.py` 中注入回调：当 `change.severity == "breaking"` 时，调用 `TicketService.create_from_change` 自动创建 `change_auto` 工单（P0、SLA 24h、关联 `related_fqn`）。该调用包裹于 `try/except`，失败仅记日志，不影响变更确认主流程。

### 6.2 与 MOD-10 审计
`ApprovalService` / `TicketService` 在构造时注入 `AuditService`，所有 `approval.approve/reject/comment`、`ticket.create/assign/transition/comment` 均写 `audit_log`（动作形如 `approval.approved`、`ticket.in_progress`）。

### 6.3 与 MOD-09 / MOD-11
- MOD-09 资产详情「业务」/「分级」Tab 提供「发起审批」入口（前端设计见 `FE-01`）。
- MOD-11 提供角色→审批人解析（后续可让 `approver` 为空时按资源等级自动指派审批人）。

---

## 7. 验收标准

1. 可创建审批请求，pending 状态正确；通过/驳回后状态终态，二次决策返回 409。
2. 工单可创建并经状态机合法流转；非法流转返回 422；closed 可重开。
3. 审批与工单可追加评论，评论列表按时间升序。
4. 所有审批决策、工单流转在 `audit_log` 留有记录。
5. 对一条 **breaking** 变更执行 `ack` 后，自动生成一条 `change_auto` 工单（P0、SLA 24h、关联 FQN）。
6. REST 接口与错误码符合 §5；单元/集成测试覆盖 `tests/unit/platform/test_governance.py`。
