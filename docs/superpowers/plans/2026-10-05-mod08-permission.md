# MOD-08 账号权限分析 实现计划（生产级）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 MOD-08 权限分析——只读采集业务库账号/角色与授权，构建权限矩阵、风险识别（超管/过度授权/僵尸/无主/高敏资产授权）、权限基线对比与变更追踪，对齐 Apache Atlas / Collibra / Alation 的权限治理能力域。

**Architecture:** 复用 `ConnectionProvider.acquire(ds_id, ADMIN)`（只读、跳过只读校验、绝不写业务库）、`Dialect` 抽象层（T-114，已预留 `list_accounts_sql`/`list_grants_sql`）、`TaskService`（T-107）、实体身份稳定化（FR-13）。采集器只执行方言 SQL + 落库，**不执行任何授权变更**（设计 D2）。与 MOD-05 分级通过读 `catalog_column.grade_level` 联动（L1 读表、可降级），与 MOD-11 责任人关联可降级（设计 D5）。

**Tech Stack:** Python 3.10+, SQLAlchemy 2.0, FastAPI, PostgreSQL, pytest（+ `PG_TEST=1` 集成）。

**竞品对齐（来自 `competitive-benchmark-2026-10.md` §2.2 / §7）：**
- Apache Atlas：标签（分级）沿血缘/权限传播 → 本计划「高敏资产授权」风险项（FR-6.5）。
- Collibra：权限策略 + 职责分离 → 风险识别规则 + 账号责任人关联（FR-6.7，降级）。
- Alation：账号治理/敏感资产授权重点标注 → 权限矩阵高亮 + 风险聚合。
- 等保 2.0：账号鉴别、访问控制、审计 → 本模块只读、全量审计（MOD-10）。
- DCMM「数据安全」域：权限分析是明确能力项；GB/T 43697 要求重要/核心数据访问重点管控。
- 现状断点：`account`/`account_grant` DDL（`02-schema-ddl.sql:479-509`）+ ORM（`models_ops.py:170+`）已就绪；方言 SQL 已写好（`dialect/postgres.py:171,177`）但**无采集器调用**；接口 **0/9**。

**注意（生产约束，来自设计 §8）：**
- 只读：`purpose=ADMIN`，`ConnectionProvider` 对 ADMIN 不做只读校验（见 `connections.py:423`），但本模块仍**只 SELECT，绝不写业务库**。
- 超管 `ALL PRIVILEGES ON *.*` 授权对象可达数万，展开须限制粒度（设计 D4），避免写入爆炸。
- 同名账号不同 host（MySQL）以 `host_pattern` 区分。
- 授权对象未纳管时以 FQN 存储、`entity_id` 为空，标记外部对象。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/local_ingestion/platform/dialect/base.py` | `list_accounts_sql`/`list_grants_sql` 增补 `is_super`/`object_type`/`object_fqn`/`grantable` 形态 |
| `src/local_ingestion/platform/dialect/postgres.py` | 实现 PG 账号 + 授权（表级 + 列级）查询 |
| `src/local_ingestion/platform/dialect/mysql.py` / `snowflake.py` | 同形查询（information_schema 视图） |
| `src/local_ingestion/platform/permission/repository.py` | account/account_grant upsert、基线快照、风险项写入 |
| `src/local_ingestion/platform/permission/risk.py` | 风险识别规则引擎（超管/过度/僵尸/无主/高敏） |
| `src/local_ingestion/platform/permission/collector.py` | ADMIN 只读采集 → 落库 + 实体解析 + 风险计算（MOD-10 handler） |
| `src/local_ingestion/platform/permission/service.py` | 矩阵/风险/变更/实体授权查询 |
| `src/local_ingestion/platform/permission/tasks.py` | 注册 `TaskService` handler + 独立触发 |
| `src/local_ingestion/api/routers/permissions.py` | 9 个端点（新建，未在 app.py 注册） |
| `tests/unit/platform/permission/test_risk.py` | 风险规则单测 |
| `tests/unit/platform/permission/test_repository.py` | upsert/基线单测 |
| `tests/unit/platform/permission/test_collector.py` | 采集器单测（fake conn） |
| `tests/unit/platform/permission/test_service.py` | 矩阵/变更单测 |
| `tests/unit/platform/dialect/test_grants.py` | 三方言授权 SQL 单测 |
| `tests/integration/test_permission_pg.py` | PG 集成（需 `PG_TEST=1`） |

---

### Task 1: Dialect 账号 / 授权查询（PG 为主，三方言同形）

**Files:**
- Modify: `src/local_ingestion/platform/dialect/base.py`、`postgres.py`、`mysql.py`、`snowflake.py`
- Test: `tests/unit/platform/dialect/test_grants.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/unit/platform/dialect/test_grants.py
import pytest
from local_ingestion.platform.dialect import get_dialect

def test_accounts_sql_shape():
    sql = get_dialect("postgres").list_accounts_sql()
    assert "pg_roles" in sql and "rolsuper" in sql and "rolcanlogin" in sql

def test_grants_sql_returns_object_type_and_grantable():
    sql = get_dialect("postgres").list_grants_sql()
    # 必须返回 grantee, object_type, object_fqn, privilege, grantable 五列
    for col in ("grantee", "object_type", "object_fqn", "privilege", "grantable"):
        assert col in sql.lower()
```

- [ ] **Step 2: 运行失败**
- [ ] **Step 3: 实现**

`postgres.py`：

```python
    def list_accounts_sql(self) -> str:
        # 仅可登录角色；rolsuper/rolcanlogin 供风险识别（超管/锁定）
        return (
            "SELECT rolname, rolsuper, rolcanlogin "
            "FROM pg_roles WHERE rolcanlogin ORDER BY rolname"
        )

    def list_grants_sql(self) -> str:
        # 表级 + 列级授权合并；object_fqn 用 schema.table[.col]
        return """
        SELECT grantee,
               'table'  AS object_type,
               table_schema || '.' || table_name AS object_fqn,
               privilege_type AS privilege,
               is_grantable = 'YES' AS grantable
        FROM information_schema.role_table_grants
        UNION ALL
        SELECT rg.grantee,
               'column' AS object_type,
               rg.table_schema || '.' || rg.table_name || '.' || rg.column_name AS object_fqn,
               rg.privilege_type AS privilege,
               rg.is_grantable = 'YES' AS grantable
        FROM information_schema.role_column_grants rg
        ORDER BY grantee, object_fqn
        """
```

`mysql.py` / `snowflake.py`（同形，走 information_schema）：

```python
    def list_accounts_sql(self) -> str:
        # MySQL: mysql.user；Snowflake 用 SHOW USERS（非 SELECT，见下方说明）
        return (
            "SELECT user, is_super, account_locked "
            "FROM mysql.user ORDER BY user"
        )

    def list_grants_sql(self) -> str:
        return """
        SELECT grantee,
               'table' AS object_type,
               table_schema || '.' || table_name AS object_fqn,
               privilege_type AS privilege,
               is_grantable = 'YES' AS grantable
        FROM information_schema.table_privileges
        ORDER BY grantee, object_fqn
        """
```

> Snowflake 账号需 `SHOW USERS`（非 SELECT）。**实现时用 `Dialect.fetch_accounts(conn)` / `fetch_grants(conn)` 方言方法**封装差异（PG/MySQL 走 SQL，Snowflake 解析 `SHOW` 结果），collector 统一调用方法而非裸 SQL。本 Task 先固化 PG（已验证路径），mysql/snowflake 同形 SQL + SHOW 解析在 collector Task 中补齐。
- [ ] **Step 4: 运行通过**
- [ ] **Step 5: 提交**

```bash
git add src/local_ingestion/platform/dialect tests/unit/platform/dialect/test_grants.py
git commit -m "feat(dialect): account + grant listing SQL for MOD-08"
```

---

### Task 2: 权限 Repository（账号/授权 upsert + 基线）

**Files:**
- Create: `src/local_ingestion/platform/permission/repository.py`
- Test: `tests/unit/platform/permission/test_repository.py`

- [ ] **Step 1: 写失败测试**

```python
def test_upsert_account_idempotent(session_factory):
    from local_ingestion.platform.permission.repository import PermissionRepository
    r = PermissionRepository(session_factory)
    r.upsert_account(ds_id=1, name="alice", account_type="user", is_super=False)
    r.upsert_account(ds_id=1, name="alice", account_type="user", is_super=False)
    assert r.count_accounts(1) == 1

def test_baseline_diff_detects_new_grant(session_factory):
    r = PermissionRepository(session_factory)
    r.upsert_grant(ds_id=1, account="alice", privilege="SELECT",
                   object_type="table", object_fqn="db.s.t1", run_id=1)
    r.mark_baseline(ds_id=1, run_id=1)
    r.upsert_grant(ds_id=1, account="alice", privilege="SELECT",
                   object_type="table", object_fqn="db.s.t1", run_id=2)
    r.upsert_grant(ds_id=1, account="alice", privilege="DELETE",
                   object_type="table", object_fqn="db.s.t1", run_id=2)
    diff = r.diff_vs_baseline(ds_id=1, run_id=2)
    assert any(d["kind"] == "added" and d["privilege"] == "DELETE" for d in diff)
```

- [ ] **Step 2: 运行失败**
- [ ] **Step 3: 实现**

```python
# src/local_ingestion/platform/permission/repository.py
from __future__ import annotations
from sqlalchemy import select, func
from ..storage.models_ops import Account, AccountGrant

class PermissionRepository:
    def __init__(self, session_factory):
        self._sf = session_factory

    def upsert_account(self, ds_id, name, account_type=None, host_pattern=None,
                       is_super=False, is_locked=False, last_login_at=None):
        with self._sf() as s:
            row = s.execute(select(Account).where(
                Account.datasource_id == ds_id, Account.account_name == name,
                Account.host_pattern.is_(host_pattern),
                Account.deleted_at.is_(None))).scalar_one_or_none()
            if row is None:
                row = Account(datasource_id=ds_id, account_name=name, host_pattern=host_pattern)
                s.add(row)
            row.account_type = account_type
            row.is_super = is_super
            row.is_locked = is_locked
            row.last_login_at = last_login_at
            s.commit()
            return row.id

    def upsert_grant(self, ds_id, account, privilege, object_type, object_fqn,
                     grantable=False, run_id=None):
        with self._sf() as s:
            existing = s.execute(select(AccountGrant).where(
                AccountGrant.datasource_id == ds_id, AccountGrant.object_fqn == object_fqn,
                AccountGrant.privilege == privilege, AccountGrant.deleted_at.is_(None))
            ).scalars().all()
            # 同 FQN+privilege 可能多账号；按 account 去重
            for g in existing:
                if g.privilege == privilege:
                    g.deleted_at = None  # 复用
            else:
                s.add(AccountGrant(datasource_id=ds_id, account_id=None,
                                   privilege=privilege, object_type=object_type,
                                   object_fqn=object_fqn, grantable=grantable))
            s.commit()

    def count_accounts(self, ds_id) -> int:
        with self._sf() as s:
            return s.execute(select(func.count()).select_from(Account)
                             .where(Account.datasource_id == ds_id,
                                    Account.deleted_at.is_(None))).scalar_one()

    def mark_baseline(self, ds_id, run_id):
        # 将指定 run 的授权标记为基线（软逻辑：写入 baseline_run 表/标记列）
        with self._sf() as s:
            s.execute(__import__("sqlalchemy").text(
                "UPDATE account_grant SET properties = jsonb_set(properties, '{baseline}', 'true') "
                "WHERE datasource_id = :ds AND detected_at <= (SELECT detected_at FROM account_grant WHERE id = :rid)"
            ), {"ds": ds_id, "rid": run_id})
            s.commit()

    def diff_vs_baseline(self, ds_id, run_id) -> list[dict]:
        with self._sf() as s:
            base = s.execute(select(AccountGrant).where(
                AccountGrant.datasource_id == ds_id,
                AccountGrant.properties.op("->>")("baseline") == "true",
                AccountGrant.deleted_at.is_(None))).scalars().all()
            cur = s.execute(select(AccountGrant).where(
                AccountGrant.datasource_id == ds_id,
                AccountGrant.detected_at >= (s.execute(__import__("sqlalchemy").text(
                    "SELECT detected_at FROM account_grant WHERE id=:rid"), {"rid": run_id}).scalar_one()),
                AccountGrant.deleted_at.is_(None))).scalars().all()
            base_keys = {(g.account_id, g.privilege, g.object_fqn) for g in base}
            cur_keys = {(g.account_id, g.privilege, g.object_fqn) for g in cur}
            return [{"kind": "added", **_k} for _k in (cur_keys - base_keys)] + \
                   [{"kind": "revoked", **_k} for _k in (base_keys - cur_keys)]
```

- [ ] **Step 4: 运行通过**
- [ ] **Step 5: 提交**

```bash
git add src/local_ingestion/platform/permission/repository.py tests/unit/platform/permission/test_repository.py
git commit -m "feat(permission): account/grant repository with baseline diff"
```

---

### Task 3: 风险识别引擎（超管/过度/僵尸/无主/高敏）

**Files:**
- Create: `src/local_ingestion/platform/permission/risk.py`
- Test: `tests/unit/platform/permission/test_risk.py`

- [ ] **Step 1: 写失败测试**

```python
from local_ingestion.platform.permission.risk import evaluate_risks

def test_super_account_flagged():
    accts = [{"name": "root", "is_super": True, "is_locked": False, "last_login_at": None}]
    risks = evaluate_risks(accts, grants=[], grade_lookup={})
    assert any(r["type"] == "super" for r in risks)

def test_excessive_delete_on_table():
    grants = [{"account": "app", "privilege": "DELETE", "object_type": "table",
               "object_fqn": "db.s.orders"}]
    risks = evaluate_risks([{"name": "app", "is_super": False}], grants, grade_lookup={})
    assert any(r["type"] == "excessive" for r in risks)

def test_high_sensitivity_grant_flagged():
    grants = [{"account": "analyst", "privilege": "SELECT", "object_type": "table",
               "object_fqn": "db.s.pii_users"}]
    risks = evaluate_risks([{"name": "analyst", "is_super": False}], grants,
                          grade_lookup={"db.s.pii_users": 4})
    assert any(r["type"] == "high_sensitivity" for r in risks)
```

- [ ] **Step 2: 运行失败**
- [ ] **Step 3: 实现**

```python
# src/local_ingestion/platform/permission/risk.py
"""Risk rules for account/grant analysis (FR-6.3). Pure, testable."""
from __future__ import annotations

EXCESSIVE_PRIVILEGES = {"INSERT", "UPDATE", "DELETE", "TRUNCATE", "CREATE", "DROP", "ALTER"}
HIGH_GRADE_THRESHOLD = 3  # grade_level >= 3 == 重要/核心（GB/T 43697 映射）

def evaluate_risks(accounts, grants, grade_lookup=None, *,
                   dormant_days: int = 180, orphan_check=None) -> list[dict]:
    grade_lookup = grade_lookup or {}
    risks: list[dict] = []
    acct_names = {a["name"] for a in accounts}

    for a in accounts:
        if a.get("is_super"):
            risks.append({"type": "super", "account": a["name"],
                          "severity": "high", "detail": "具备实例级超级权限"})
        if a.get("is_locked"):
            risks.append({"type": "locked", "account": a["name"],
                          "severity": "info", "detail": "账号已锁定"})
        # 僵尸：超阈值未登录（best-effort，PG 原生无 last_login）
        if a.get("last_login_at") is None:
            risks.append({"type": "dormant", "account": a["name"],
                          "severity": "medium", "detail": "从未登录/无登录记录"})
        # 无主：没有映射到平台用户（orphan_check 可注入；默认按名称匹配失败）
        if orphan_check is not None and not orphan_check(a["name"]):
            risks.append({"type": "orphan", "account": a["name"],
                          "severity": "medium", "detail": "未关联责任人/平台用户"})

    by_acct: dict[str, list] = {}
    for g in grants:
        by_acct.setdefault(g.get("account") or _owner_of(g), []).append(g)

    for acct, gs in by_acct.items():
        if acct not in acct_names:
            continue
        for g in gs:
            priv = (g.get("privilege") or "").upper()
            if priv in EXCESSIVE_PRIVILEGES and priv != "SELECT":
                risks.append({"type": "excessive", "account": acct,
                              "object_fqn": g["object_fqn"], "privilege": priv,
                              "severity": "high",
                              "detail": f"{acct} 对 {g['object_fqn']} 具备 {priv}"})
            grade = grade_lookup.get(g["object_fqn"])
            if grade is not None and grade >= HIGH_GRADE_THRESHOLD:
                risks.append({"type": "high_sensitivity", "account": acct,
                              "object_fqn": g["object_fqn"], "privilege": priv,
                              "severity": "high",
                              "detail": f"{acct} 可访问高敏对象 {g['object_fqn']}(L{grade})"})
    return risks

def _owner_of(grant: dict) -> str:
    return grant.get("account") or "unknown"
```

- [ ] **Step 4: 运行通过**
- [ ] **Step 5: 提交**

```bash
git add src/local_ingestion/platform/permission/risk.py tests/unit/platform/permission/test_risk.py
git commit -m "feat(permission): risk detection engine (super/excessive/dormant/orphan/high-sensitivity)"
```

---

### Task 4: 权限采集器（ADMIN 只读 → 落库 + 风险）

**Files:**
- Create: `src/local_ingestion/platform/permission/collector.py`
- Test: `tests/unit/platform/permission/test_collector.py`

- [ ] **Step 1: 写失败测试**

```python
from local_ingestion.platform.permission.collector import collect_permissions

class _FakeConn:
    def __init__(self, accounts, grants): self.accounts = accounts; self.grants = grants
    def execute(self, sql):
        if "pg_roles" in str(sql).lower(): return self.accounts
        return self.grants

def test_collector_persists_and_scores(session_factory):
    fake = _FakeConn([("alice", False, True)],
                     [("alice", "table", "db.s.t1", "SELECT", False)])
    res = collect_permissions(session_factory, ds_id=1, ds_type="postgres",
                              db="db", schema="s", conn=fake)
    assert res.accounts == 1 and res.grants == 1 and res.risks >= 0
```

- [ ] **Step 2: 运行失败**
- [ ] **Step 3: 实现**

```python
# src/local_ingestion/platform/permission/collector.py
"""Permission collector: read-only ADMIN conn -> account/grant + risk (MOD-08)."""
from __future__ import annotations
import structlog
from .repository import PermissionRepository
from .risk import evaluate_risks

logger = structlog.get_logger()

class CollectResult:
    def __init__(self): self.accounts = 0; self.grants = 0; self.risks = 0; self.failed = 0

def collect_permissions(session_factory, *, ds_id, ds_type, db, schema, conn,
                        grade_lookup=None, run_id=None) -> CollectResult:
    """Only SELECTs from the business DB. Never writes to it (design D2)."""
    from sqlalchemy import text
    from ..dialect import get_dialect
    repo = PermissionRepository(session_factory)
    res = CollectResult()
    # 1) accounts
    for row in conn.execute(text(get_dialect(ds_type).list_accounts_sql())):
        name, is_super, can_login = row[0], bool(row[1]), bool(row[2])
        repo.upsert_account(ds_id, name, account_type="user",
                            is_super=is_super, is_locked=not can_login)
        res.accounts += 1
    # 2) grants（限制超管展开粒度，设计 D4）
    grants = []
    for row in conn.execute(text(get_dialect(ds_type).list_grants_sql())):
        grantee, obj_type, obj_fqn, priv, grantable = row[0], row[1], row[2], row[3], bool(row[4])
        # 超管全部权限类授权不逐对象展开（避免数万行写爆）
        if priv in ("ALL PRIVILEGES", "ALL") and obj_fqn in ("*.*", "*"):
            repo.upsert_grant(ds_id, grantee, "ALL", obj_type, obj_fqn, grantable, run_id=run_id)
            grants.append({"account": grantee, "privilege": "ALL",
                           "object_type": obj_type, "object_fqn": obj_fqn})
            continue
        repo.upsert_grant(ds_id, grantee, priv, obj_type, obj_fqn, grantable, run_id=run_id)
        grants.append({"account": grantee, "privilege": priv,
                       "object_type": obj_type, "object_fqn": obj_fqn})
        res.grants += 1
    # 3) 风险
    acct_rows = [{"name": a[0], "is_super": bool(a[1]), "is_locked": not bool(a[2]),
                  "last_login_at": None} for a in
                 conn.execute(text(get_dialect(ds_type).list_accounts_sql()))]
    risks = evaluate_risks(acct_rows, grants, grade_lookup=grade_lookup or {})
    res.risks = len(risks)
    logger.info("permission_collect_done", ds=ds_id, **res.__dict__)
    return res
```

- [ ] **Step 4: 运行通过**
- [ ] **Step 5: 提交**

```bash
git add src/local_ingestion/platform/permission/collector.py tests/unit/platform/permission/test_collector.py
git commit -m "feat(permission): ADMIN read-only collector with risk scoring"
```

---

### Task 5: 权限 Service（矩阵 / 风险 / 变更 / 实体授权）

**Files:**
- Create: `src/local_ingestion/platform/permission/service.py`
- Test: `tests/unit/platform/permission/test_service.py`

- [ ] **Step 1: 写失败测试**

```python
from local_ingestion.platform.permission.service import PermissionQueryService

def test_matrix_account_centric(session_factory):
    from local_ingestion.platform.permission.repository import PermissionRepository
    r = PermissionRepository(session_factory)
    r.upsert_account(1, "alice"); r.upsert_grant(1, "alice", "SELECT", "table", "db.s.t1")
    svc = PermissionQueryService(session_factory)
    matrix = svc.matrix(datasource_id=1)
    assert any(m["account"] == "alice" for m in matrix)

def test_entity_grants(session_factory):
    from local_ingestion.platform.permission.repository import PermissionRepository
    r = PermissionRepository(session_factory)
    r.upsert_grant(1, "alice", "SELECT", "table", "db.s.t1")
    svc = PermissionQueryService(session_factory)
    assert any(g["account"] == "alice" for g in svc.get_entity_grants("db.s.t1"))
```

- [ ] **Step 2: 运行失败**
- [ ] **Step 3: 实现**

```python
# src/local_ingestion/platform/permission/service.py
from __future__ import annotations
from sqlalchemy import select, func
from ..storage.models_ops import Account, AccountGrant

class PermissionQueryService:
    def __init__(self, session_factory):
        self._sf = session_factory

    def matrix(self, *, datasource_id, account=None, risk=None, limit=200, cursor=None):
        with self._sf() as s:
            q = s.query(Account).filter(Account.datasource_id == datasource_id,
                                        Account.deleted_at.is_(None))
            if account:
                q = q.filter(Account.account_name == account)
            rows = q.limit(limit).all()
            return [{"account": a.account_name, "type": a.account_type,
                     "is_super": a.is_super, "is_locked": a.is_locked} for a in rows]

    def get_entity_grants(self, object_fqn):
        with self._sf() as s:
            rows = s.execute(select(AccountGrant).where(
                AccountGrant.object_fqn == object_fqn,
                AccountGrant.deleted_at.is_(None))).scalars().all()
            return [{"account": r.account_id, "privilege": r.privilege,
                     "object_type": r.object_type, "grantable": r.grantable} for r in rows]

    def risks(self, *, datasource_id, severity=None, limit=200):
        # 风险计算为采集时落地或实时重算；此处从风险视图/表读取
        with self._sf() as s:
            rows = s.execute(select(RiskItem).where(
                RiskItem.datasource_id == datasource_id)).scalars().all() if False else []
            return rows  # 实际从 permission_risk 表读取（Task 2 扩展）
```

> `risks()` 实际读取 `permission_risk` 表（在 repository Task 中扩展 upsert_risk）；本 Task 给出接口契约，实现时补全表读写。
- [ ] **Step 4: 运行通过**
- [ ] **Step 5: 提交**

```bash
git add src/local_ingestion/platform/permission/service.py tests/unit/platform/permission/test_service.py
git commit -m "feat(permission): query service (matrix/entity grants/risks)"
```

---

### Task 6: 接入 TaskService（独立触发，不阻塞扫描）

**Files:**
- Create: `src/local_ingestion/platform/permission/tasks.py`
- Modify: `src/local_ingestion/api/app.py`（注册权限路由，见 Task 7）
- Test: `tests/unit/platform/permission/test_tasks.py`

- [ ] **Step 1: 写失败测试**

```python
def test_register_permission_handler(task_service):
    from local_ingestion.platform.permission.tasks import register_permission_tasks
    register_permission_tasks(task_service, session_factory_stub, conn_provider_stub)
    assert "permission.collect" in task_service.registered_handlers()
```

- [ ] **Step 2: 运行失败**
- [ ] **Step 3: 实现**

```python
# src/local_ingestion/platform/permission/tasks.py
from __future__ import annotations
from local_ingestion.platform.connections import ConnectionProvider, ADMIN
from .collector import collect_permissions

JOB = "permission.collect"

def register_permission_tasks(task_service, session_factory, conn_provider: ConnectionProvider):
    def run(ctx):
        ds_id = ctx.scope["datasource_id"]
        from ..storage.models_core import Datasource
        with session_factory() as s:
            ds = s.get(Datasource, ds_id)
        with conn_provider.acquire(ds_id, ADMIN) as conn:  # 只读
            return collect_permissions(
                session_factory, ds_id=ds_id, ds_type=ds.ds_type,
                db=(ds.scan_config or {}).get("database"), schema=ctx.scope.get("schema"),
                conn=conn, grade_lookup=_grade_lookup(session_factory, ds_id),
            ).__dict__
    task_service.register_handler(JOB, run)
    # 权限分析为独立任务，不挂到 scan 依赖链（只读、低频、可按需触发）
```

- [ ] **Step 4: 运行通过**
- [ ] **Step 5: 提交**

```bash
git add src/local_ingestion/platform/permission/tasks.py tests/unit/platform/permission/test_tasks.py
git commit -m "feat(permission): register collector in TaskService (standalone trigger)"
```

---

### Task 7: REST API（9 端点）

**Files:**
- Create: `src/local_ingestion/api/routers/permissions.py`
- Modify: `src/local_ingestion/api/app.py`（加入 `app.include_router(_permissions_router)`）

- [ ] **Step 1: 写失败测试（TestClient）**

```python
def test_accounts_and_matrix_endpoints(client, session_factory):
    from local_ingestion.platform.permission.repository import PermissionRepository
    PermissionRepository(session_factory).upsert_account(1, "alice")
    assert client.get("/api/v1/permissions/accounts?datasource_id=1").status_code == 200
    assert client.get("/api/v1/permissions/matrix?datasource_id=1").status_code == 200
```

- [ ] **Step 2: 运行失败**
- [ ] **Step 3: 实现**

```python
# src/local_ingestion/api/routers/permissions.py
from fastapi import APIRouter, Depends, Query, Body
from local_ingestion.platform.permission.service import PermissionQueryService

router = APIRouter(prefix="/api/v1/permissions", tags=["Permissions"])

def get_svc():
    from ...storage.session import session_scope
    return PermissionQueryService(session_scope)

@router.get("/accounts")
def list_accounts(datasource_id: int = Query(...), risk: str = Query(None),
                  svc: PermissionQueryService = Depends(get_svc)):
    return svc.matrix(datasource_id=datasource_id, risk=risk)

@router.get("/accounts/{account}/grants")
def account_grants(datasource_id: int, account: str, svc=Depends(get_svc)):
    # 账号维度授权明细
    return svc.grants_of_account(datasource_id, account)

@router.get("/matrix")
def matrix(datasource_id: int = Query(...), svc=Depends(get_svc)):
    return svc.matrix(datasource_id=datasource_id)

@router.get("/entities/{entity_type}/{entity_id}/grants")
def entity_grants(entity_type: str, entity_id: int, svc=Depends(get_svc)):
    fqn = _fqn_of(entity_type, entity_id)  # 经实体解析 FR-13
    return svc.get_entity_grants(fqn)

@router.get("/risks")
def risks(datasource_id: int = Query(...), severity: str = Query(None), svc=Depends(get_svc)):
    return svc.risks(datasource_id=datasource_id, severity=severity)

@router.post("/risks/{risk_id}/ack")
def ack_risk(risk_id: int, svc=Depends(get_svc)):
    svc.ack_risk(risk_id); return {"ok": True}

@router.get("/changes")
def changes(datasource_id: int = Query(...), svc=Depends(get_svc)):
    return svc.diff_vs_baseline(datasource_id, latest_run(svc))

@router.post("/baseline/refresh")
def refresh_baseline(datasource_id: int = Body(...), svc=Depends(get_svc)):
    svc.mark_baseline(datasource_id); return {"ok": True}

@router.post("/tasks")
def trigger(datasource_id: int = Body(...), schema: str = Body(None), svc=Depends(get_svc)):
    # 经 TaskService 下发 permission.collect（ADMIN 只读）
    from ...platform.permission.tasks import JOB
    task_id = svc.task_service.submit(JOB, scope={"datasource_id": datasource_id, "schema": schema})
    return {"task_id": task_id}

@router.get("/export")
def export(datasource_id: int = Query(...), svc=Depends(get_svc)):
    # 合规报表导出（CSV/JSON），含高敏资产授权重点标注
    return svc.export_report(datasource_id)
```

`app.py` 注册：

```python
from local_ingestion.api.routers.permissions import router as _permissions_router
# ... 在 MOD-08 区块（紧邻 _governance_router）加入：
app.include_router(_permissions_router)
```

- [ ] **Step 4: 运行通过**
- [ ] **Step 5: 提交**

```bash
git add src/local_ingestion/api/routers/permissions.py src/local_ingestion/api/app.py tests/unit/api/test_permissions_api.py
git commit -m "feat(permission): 9 REST endpoints + router registration (0/9 -> 9/9)"
```

---

### Task 8: 集成测试 + 迁移校验 + 进度更新

**Files:**
- Create: `tests/integration/test_permission_pg.py`（需 `PG_TEST=1`）
- Verify: `alembic check` 确认 `account`/`account_grant` 已在迁移中

- [ ] **Step 1: 写集成测试**

```python
import pytest, os
pytestmark = pytest.mark.skipif(not os.getenv("PG_TEST"), reason="needs PG")

def test_permission_e2e(pg_session_factory, pg_connection_provider):
    from local_ingestion.platform.permission.collector import collect_permissions
    res = collect_permissions(pg_session_factory, ds_id=1, ds_type="postgres",
                              db="test", schema="public", conn=pg_conn)
    assert res.accounts >= 1
```

- [ ] **Step 2: 运行** `PG_TEST=1 pytest tests/integration/test_permission_pg.py -v` → PASS
- [ ] **Step 3: 迁移校验** `alembic check` → `No new upgrade operations detected`
- [ ] **Step 4: 全量回归** `pytest tests/unit -q` 全绿（基线 906 + 本计划约 25 用例）
- [ ] **Step 5: 提交 + 更新 `doc/plan/03-progress.md`**：记录 MOD-08 落地、接口 0/9→9/9、只读 ADMIN 约束、与 MOD-05 分级联动。

---

## 自审（Spec Coverage）

- [x] FR-6.1 账号与授权采集（三方言）→ Task 1/4
- [x] FR-6.2 权限矩阵（双向）→ Task 5/7
- [x] FR-6.3 风险识别（超管/过度/僵尸/无主/高敏）→ Task 3
- [x] FR-6.4 权限变更追踪 → Task 2（基线 diff）+ Task 7 `/changes`
- [x] FR-6.5 与分级联动（高敏资产授权）→ Task 3 `grade_lookup`
- [x] FR-6.6 权限基线对比 → Task 2/7
- [x] FR-6.7 责任人关联（可降级）→ Task 5（orphan_check 注入）
- [x] 竞品对齐：Atlas 标签传播(高敏授权)、Collibra 职责分离、Alation 敏感资产重点标注
- [x] 生产约束：ADMIN 只读、零业务库写、超管展开限粒度、外部对象 FQN 容错
- [ ] 已知缺口（写入进度文档）：Snowflake `SHOW USERS` 解析、PG `last_login` 原生缺失（best-effort）、MySQL host_pattern 区分 — 均在 Task 1/4 标注，作为后续增强，不阻塞首发。
