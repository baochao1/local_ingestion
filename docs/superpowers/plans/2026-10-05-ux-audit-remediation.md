# UX 审计整改 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 UX 审计报告（`.ux-audit/final-report.md`）中的 1 条 P0 与 12 条 P1 中可代码化的部分，核心是让「提交失败」与「错误发生」对用户可见、可读、可恢复。

**Architecture:** 分三条线推进，互不阻塞：(1) 后端把驱动层异常映射为领域文案并加连接超时，从源头消灭技术栈信息泄漏与 6 秒静默；(2) 前端统一走已有的 `toUserMessage` / `ConfirmDanger` / `ErrorState` 三件套，补齐进度说明、错误分流与删除入口；(3) a11y 与信息架构的收敛（筛选控件可访问名、触控尺寸、占位模块标记）。全部改动复用仓库既有抽象，不新增设计体系。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / pytest（后端，`.venv/Scripts/python -m pytest`）；React 18 / TypeScript 5.6 / antd 5 / @tanstack/react-query / Vite（前端，`npm run typecheck`，本计划新增 vitest 用于纯函数测试）；Playwright（回归验证，复用 `.ux-audit/*.py`）

**前置条件：** 后端起在 `127.0.0.1:8090`，前端起在 `5173`（`.\start-backend.ps1` / `.\start-frontend.ps1`）。审计证据见 `.ux-audit/`，回归可复用其中的脚本。

**不在本计划内（需先决策）：**
- P1-6 分级指标口径冲突（概览页 vs 分级页数值/命名/配色两套）— 需后端先统一统计接口与分级字典，建议单独立项
- P1-12 窄屏（375px）布局崩塌 — 需产品先明确是否支持移动端。若定位桌面，本计划外只需在窄屏加一条最小宽度提示

---

## Task 1: 示例任务不再硬编码 datasource_id（P0-1）

**Files:**
- Modify: `web/src/pages/tasks/TaskListPage.tsx:1-19` (imports), `:150-168` (示例任务按钮)
- Test: 无单元测试（前端无组件测试环境）— 用 Playwright 回归，见 Step 4

**背景：** `TaskListPage.tsx:157` 写死 `scope: { datasource_id: 1 }`，而库中实际数据源 ID 为 3/4/5，导致 `POST /api/v1/tasks` 必然 500（外键约束）。页面已引入 `useDatasourceNames()`，但它只暴露 name 函数；改用 `useDatasourceMap()` 可直接拿到 id→name 的 Map。

- [ ] **Step 1: 改 import，引入 toUserMessage 与 useDatasourceMap**

```tsx
// TaskListPage.tsx 顶部
import { useDatasourceMap } from '@/hooks/useDatasourceName';
import { toUserMessage } from '@/api/errors';
```

- [ ] **Step 2: 取首个可用数据源 ID，无数据源时禁用按钮**

把第 36 行 `const { name: dsName } = useDatasourceNames();` 改为同时拿到 Map：

```tsx
const { name: dsName } = useDatasourceNames();
const { data: dsMap, isLoading: dsLoading } = useDatasourceMap();
const firstDatasourceId = dsMap?.keys().next().value as number | undefined;
```

- [ ] **Step 3: 替换按钮逻辑（去掉硬编码 1，统一错误文案）**

```tsx
<Button
  disabled={firstDatasourceId == null || dsLoading}
  title={firstDatasourceId == null ? '请先注册数据源' : undefined}
  onClick={async () => {
    if (firstDatasourceId == null) {
      message.warning('请先注册数据源，再提交示例扫描任务');
      return;
    }
    try {
      const run = await submitTask({
        jobType: 'metadata',
        scope: { datasource_id: firstDatasourceId },
        trigger: 'manual',
      });
      message.success(`已提交任务 ${run.id}`);
      void refetch();
    } catch (e: unknown) {
      message.error(toUserMessage(e, '提交失败'));
    }
  }}
>
  提交示例扫描任务
</Button>
```

- [ ] **Step 4: 类型检查与回归**

Run: `cd web && npm run typecheck` — 期望 0 error
Run: `cd .. && .venv/Scripts/python.exe .ux-audit/happy_path.py` — 期望 `[提交示例扫描任务] toasts=` 不再出现 `服务端内部错误`，且 `backend.out` 末尾为 `POST /api/v1/tasks 201`

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/tasks/TaskListPage.tsx
git commit -m "fix(tasks): 示例扫描任务改用首个可用数据源，移除硬编码 ID"
```

---

## Task 2: 后端把驱动层异常映射为领域文案（P1-1）

**Files:**
- Modify: `src/local_ingestion/platform/datasource/service.py:119-131`
- Create: `tests/unit/platform/test_datasource_error_mapping.py`

**背景：** `service.py:128-129` 把 `str(exc)[:500]` 原样塞进 `ConnectivityResult.reason`，经 `_handle_errors`（`routers/datasources.py:59-60`）转为 400 detail 后，用户在界面上看到 `请求参数有误：(pymysql.err.OperationalError) (2003, "Can't connect to MySQL server..." [WinError 10061]...) (Background on this error at: https://sqlalche.me/e/21/e3q8)`。

- [ ] **Step 1: 写失败测试**

`tests/unit/platform/test_datasource_error_mapping.py`：

```python
"""驱动层异常 → 用户可行动文案的映射（ux-audit P1-1）。"""
from local_ingestion.platform.datasource.service import classify_connectivity_error


def test_connection_refused_has_no_driver_internals():
    raw = (
        '(pymysql.err.OperationalError) (2003, "Can\'t connect to MySQL server on '
        "'localhost' ([WinError 10061] 由于目标计算机积极拒绝，无法连接。)\")"
        "(Background on this error at: https://sqlalche.me/e/21/e3q8)"
    )
    msg = classify_connectivity_error(RuntimeError(raw))
    assert "pymysql" not in msg
    assert "sqlalche.me" not in msg
    assert "WinError" not in msg
    assert "拒绝连接" in msg


def test_auth_failure_is_actionable():
    msg = classify_connectivity_error(
        RuntimeError('(psycopg2.OperationalError) FATAL: password authentication failed for user "x"')
    )
    assert "凭据" in msg or "账号" in msg


def test_timeout_is_actionable():
    msg = classify_connectivity_error(RuntimeError("(psycopg2.OperationalError) timeout expired"))
    assert "超时" in msg


def test_unknown_error_is_bounded_and_prefixed():
    msg = classify_connectivity_error(RuntimeError("X" * 1000))
    assert msg.startswith("无法连接目标库")
    assert len(msg) <= 260
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/platform/test_datasource_error_mapping.py -v`
Expected: FAIL — `ImportError: cannot import name 'classify_connectivity_error'`

- [ ] **Step 3: 实现映射函数**

在 `service.py` 顶部补 `import logging` 与 `_log = logging.getLogger(__name__)`（放在 `ALLOWED_DS_TYPES` 之后），并新增：

```python
def classify_connectivity_error(exc: BaseException) -> str:
    """把驱动层异常映射为用户可行动的一行文案（原始异常只入日志，不外泄）。"""
    text = str(exc)
    lowered = text.lower()
    if "timeout" in lowered:
        return "连接目标库超时，请检查网络连通性与防火墙/安全组设置"
    if any(k in lowered for k in ("name or service not known", "could not translate host name", "nodename nor servname")):
        return "无法解析目标主机地址，请检查主机填写是否正确"
    if any(k in lowered for k in ("connection refused", "actively refused", "拒绝", "10061", "could not connect")):
        return "目标主机拒绝连接，请确认主机与端口是否正确、数据库服务是否已启动"
    if any(k in lowered for k in ("access denied", "authentication failed", "password authentication")):
        return "账号或密码不被目标库接受，请检查凭据"
    if "does not exist" in lowered and "database" in lowered:
        return "目标库不存在，请检查默认库名或 database 配置"
    return f"无法连接目标库：{text[:200]}"
```

- [ ] **Step 4: 替换两处 `str(exc)` 透传**

`service.py:119-120`：

```python
    except Exception as exc:  # noqa: BLE001 - surface as connectivity failure
        _log.warning("connectivity check rejected params: %r", exc)
        return ConnectivityResult(False, False, "连接参数非法，请检查类型/主机/端口等填写")
```

`service.py:128-129`：

```python
    except Exception as exc:  # noqa: BLE001 - any failure = unreachable
        _log.warning("connectivity probe failed: %r", exc)
        return ConnectivityResult(False, False, classify_connectivity_error(exc))
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/platform/test_datasource_error_mapping.py -v`
Expected: 4 passed

Run: `.venv/Scripts/python.exe -m pytest tests/unit/platform/test_datasource.py -v`
Expected: 全部通过（确认未破坏既有行为）

- [ ] **Step 6: Commit**

```bash
git add src/local_ingestion/platform/datasource/service.py tests/unit/platform/test_datasource_error_mapping.py
git commit -m "fix(datasource): 连通性异常映射为领域文案，不再外泄驱动堆栈"
```

---

## Task 3: 为连通性探测设置显式连接超时（P1-2 后端部分）

**Files:**
- Modify: `src/local_ingestion/platform/datasource/service.py:122`
- Create: `tests/unit/platform/test_datasource_connect_timeout.py`

**背景：** 实测提交后约 6 秒才返回结果——后端在连接 `localhost:3306` 时等待系统默认超时。目标是让失败快速返回（3 秒）。

- [ ] **Step 1: 写失败测试（只测纯函数，不真连库）**

```python
"""连通性探测的 engine 参数（ux-audit P1-2）。"""
from local_ingestion.platform.datasource.service import engine_kwargs


def test_relational_dialects_get_connect_timeout():
    assert engine_kwargs("postgresql") == {"connect_args": {"connect_timeout": 3}}
    assert engine_kwargs("mysql") == {"connect_args": {"connect_timeout": 3}}


def test_dialects_without_connect_timeout_get_nothing():
    # snowflake/bigquery 不接受 connect_timeout，传入会导致连接失败
    assert engine_kwargs("snowflake") == {}
    assert engine_kwargs("bigquery") == {}
    assert engine_kwargs("other") == {}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/platform/test_datasource_connect_timeout.py -v`
Expected: FAIL — cannot import name `engine_kwargs`

- [ ] **Step 3: 实现**

`service.py` 中 `classify_connectivity_error` 之后新增：

```python
CONNECT_TIMEOUT_SEC = 3
_DIALECTS_WITH_CONNECT_TIMEOUT = frozenset({"mysql", "postgres", "postgresql"})


def engine_kwargs(ds_type: str) -> Dict[str, Any]:
    """关系型方言支持 connect_timeout；非关系型传入会直接报错，故不传。"""
    if (ds_type or "").lower() in _DIALECTS_WITH_CONNECT_TIMEOUT:
        return {"connect_args": {"connect_timeout": CONNECT_TIMEOUT_SEC}}
    return {}
```

把 `service.py:122` 的 `engine = create_engine(url)` 改为：

```python
    engine = create_engine(url, **engine_kwargs(ds_type))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/unit/platform/test_datasource_connect_timeout.py -v`
Expected: 3 passed

- [ ] **Step 5: 实测等待时长下降**

Run: `.venv/Scripts/python.exe .ux-audit/verify_submit.py`
Expected: 结果 toast 出现时间从 t+6.0s 提前到约 t+3.x s

- [ ] **Step 6: Commit**

```bash
git add src/local_ingestion/platform/datasource/service.py tests/unit/platform/test_datasource_connect_timeout.py
git commit -m "perf(datasource): 连通性探测增加 3s 连接超时，缩短失败等待"
```

---

## Task 4: 提交过程给出阶段性说明（P1-2 前端部分）

**Files:**
- Modify: `web/src/pages/datasources/DataSourceCreateModal.tsx:26-30` (state), `:60-91` (handleSubmit), `:93-111` (Modal footer)

**背景：** 提交后只有按钮转圈（实测 `loading=true` 持续约 6 秒），用户不知道系统在连接目标库。同时 `catch` 用 `e?.message ?? '创建失败'`，应改用项目已有的 `toUserMessage`。

- [ ] **Step 1: 增加进度状态与文案**

在组件内 `const [submitting, setSubmitting] = useState(false);` 后加：

```tsx
const [progress, setProgress] = useState('');
```

- [ ] **Step 2: 改写 handleSubmit**

```tsx
  const handleSubmit = async () => {
    try {
      const v = await form.validateFields();
      setSubmitting(true);
      setProgress('正在校验并连接目标库…');
      await createDataSource({ /* 原有字段保持不变 */ });
      setProgress('');
      message.success('数据源创建成功');
      form.resetFields();
      onCreated();
      onClose();
    } catch (e: unknown) {
      setProgress('');
      if (e && typeof e === 'object' && 'errorFields' in e) {
        // antd 校验失败：字段红字已经渲染，不再弹 toast
        return;
      }
      message.error(toUserMessage(e, '创建失败'));
    } finally {
      setSubmitting(false);
    }
  };
```

同时在文件顶部 import 补 `import { toUserMessage } from '@/api/errors';`，并移除 `catch (e: any)` 的 any 标注。注意：`handleTest` 的 catch 同样改为 `toUserMessage(e, '连接测试失败')`。

- [ ] **Step 3: 在弹窗里渲染进度条**

在 `<Form>` 之前插入：

```tsx
{progress ? (
  <Alert type="info" showIcon message={progress} style={{ marginBottom: 12 }} />
) : null}
```

并从 antd import 补 `Alert`；提交按钮文案在 submitting 时改为「提交中…」（`loading={submitting}` 已存在）。

- [ ] **Step 4: 类型检查与回归**

Run: `cd web && npm run typecheck` — 期望 0 error
Run: `cd .. && .venv/Scripts/python.exe .ux-audit/verify_submit.py`
Expected: t+0.5s 采样出现「正在校验并连接目标库…」；最终 toast 文案为「请求参数有误：目标主机拒绝连接，请确认主机与端口是否正确、数据库服务是否已启动」，且不含 pymysql / sqlalche.me

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/datasources/DataSourceCreateModal.tsx
git commit -m "fix(datasource): 提交过程显示进度说明，错误走 toUserMessage"
```

---

## Task 5: ErrorState 按可恢复性分流（P1-3）

**Files:**
- Modify: `web/src/api/errors.ts`（新增 `isRecoverableError`）
- Modify: `web/src/components/ErrorState.tsx:22-42`
- Create: `web/src/api/errors.test.ts`
- Create: `web/vitest.config.ts`
- Modify: `web/package.json`（test script + devDependency）

**背景：** `ErrorState` 无条件渲染「重试」，导致 404 也提供必然失败的重试；文案「资源不存在：数据源不存在：999」语义重复（前缀由 `composeErrorMessage` 的 `404: '资源不存在'` 与后端 detail 拼接而成）。

- [ ] **Step 1: 搭建最小前端测试环境**

Run: `cd web && npm i -D vitest@^2.1.0`

`web/package.json` scripts 增加 `"test": "vitest run"`。

**不需要新建 vitest 配置**：`web/vitest.config.ts` 无需创建——`web/vite.config.ts:10-14` 已配置 `@` → `src` 的 alias，vitest 会自动读取它。默认 include 已覆盖 `src/**/*.test.ts`。注意 `package.json` 为 `"type": "module"`，因此配置里**不能**用 `__dirname`（vite.config.ts 用的是 `fileURLToPath(new URL(...))`，保持这个写法）。

- [ ] **Step 2: 写失败测试**

`web/src/api/errors.test.ts`：

```ts
import { describe, expect, it } from 'vitest';
import { isRecoverableError } from './errors';

describe('isRecoverableError', () => {
  it('404 不可恢复', () => {
    expect(isRecoverableError({ response: { status: 404, data: {} } })).toBe(false);
  });
  it('403 不可恢复', () => {
    expect(isRecoverableError({ response: { status: 403, data: {} } })).toBe(false);
  });
  it('500 与 429 可恢复', () => {
    expect(isRecoverableError({ response: { status: 500, data: {} } })).toBe(true);
    expect(isRecoverableError({ response: { status: 429, data: {} } })).toBe(true);
  });
  it('网络错误（无 response）默认可恢复', () => {
    expect(isRecoverableError(new Error('Network Error'))).toBe(true);
  });
});
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd web && npm test` — Expected: FAIL（isRecoverableError 未导出）

- [ ] **Step 4: 实现**

`web/src/api/errors.ts` 末尾（`toUserMessage` 之后）新增：

```ts
/** 判断错误是否值得让用户重试：网络/服务端/限流可重试，404/403/409 重试必然再次失败。 */
export function isRecoverableError(error: unknown): boolean {
  const status = (error as { response?: { status?: number } } | null)?.response?.status;
  if (typeof status === 'number') {
    if (status === 404 || status === 403 || status === 409) return false;
    return status >= 500 || status === 429 || status === 0;
  }
  return true;
}
```

- [ ] **Step 5: ErrorState 按可恢复性渲染**

```tsx
export function ErrorState({ error, onRetry, description, onBack }: ErrorStateProps) {
  const message = pickErrorMessage(error);
  const recoverable = isRecoverableError(error);
  return (
    <Result
      status="error"
      title="加载失败"
      subTitle={description ?? message ?? '请求出错，请稍后重试'}
      extra={
        recoverable ? (
          <Button type="primary" onClick={() => (onRetry ? onRetry() : window.location.reload())}>
            重试
          </Button>
        ) : (
          <Button type="primary" onClick={() => (onBack ? onBack() : window.history.back())}>
            返回列表
          </Button>
        )
      }
    >
      {/* 原有 message 段落保持不变 */}
    </Result>
  );
}
```

同时 `ErrorStateProps` 增加 `onBack?: () => void;`，并从 `./errors` 的导入补 `isRecoverableError`（注意 `ErrorState.tsx` 的 import 路径是 `@/api/errors`）。

- [ ] **Step 6: 跑测试 + 类型检查**

Run: `cd web && npm test` — Expected: 4 passed
Run: `cd web && npm run typecheck` — Expected: 0 error

- [ ] **Step 7: 回归详情页**

Run: `cd .. && .venv/Scripts/python.exe .ux-audit/verify_requests.py`
Expected: `/app/datasources/999` 页面文本仍为错误态，但不再出现「重 试」，出现「返回列表」

- [ ] **Step 8: Commit**

```bash
git add web/package.json web/package-lock.json web/src/api/errors.ts web/src/api/errors.test.ts web/src/components/ErrorState.tsx
git commit -m "fix(error-state): 按可恢复性分流，404/403 不再提供无意义的重试"
```

---

## Task 6: 订阅停用确认 + 数据源删除入口（P1-4、P1-11）

**Files:**
- Modify: `web/src/pages/changes/SubscriptionPage.tsx:45-52`
- Modify: `web/src/pages/datasources/DataSourceListPage.tsx:66-137`（操作列）、`:5-11`（import）

**背景：** 订阅「停用」直接执行（实测 `POST /subscriptions/4/mute` 无确认），同页「删除」有 Popconfirm；数据源页「停用」已正确使用 `ConfirmDanger`（`DataSourceListPage.tsx:100-117`）——照抄它即可。另外 `deleteDataSource()` API 已存在（`api/datasources.ts:44-46`）但 UI 未使用。

- [ ] **Step 1: 订阅停用改为 ConfirmDanger**

删除 `SubscriptionPage.tsx:45-52` 里的 `toggle` 函数（它直接发请求、无二次确认），改为在操作列用 `ConfirmDanger` 包裹。沿用该文件已 import 的 `muteSubscription` / `unmuteSubscription`（**不要**臆造 `disableSubscription`）：

```tsx
{s.enabled ? (
  <ConfirmDanger
    title="停用订阅"
    description={`停用后将不再接收该范围的变更通知：${s.subscriber ?? s.id}`}
    okText="停用"
    onConfirm={async () => {
      try {
        await muteSubscription(s.id);
        message.success('已停用');
        invalidate();
      } catch (e: unknown) {
        message.error(toUserMessage(e, '操作失败'));
      }
    }}
  >
    <Button type="link" size="small" danger>停用</Button>
  </ConfirmDanger>
) : (
  /* 启用分支保持直接执行，或同样加确认——与停用保持一致即可 */
)}
```

需确认 `SubscriptionPage.tsx` 已 import `ConfirmDanger` 与 `toUserMessage`，没有则补上。

- [ ] **Step 2: 数据源操作列补删除按钮**

在 `DataSourceListPage.tsx` 的操作列 `</Space>` 之前插入：

```tsx
<ConfirmDanger
  title="删除数据源"
  description={`删除后关联的扫描任务与资产引用需要处理：${r.code}`}
  okText="删除"
  onConfirm={async () => {
    try {
      await deleteDataSource(r.id);
      message.success('已删除');
      invalidate();
    } catch (e: unknown) {
      message.error(toUserMessage(e, '删除失败'));
    }
  }}
>
  <Button type="link" size="small" danger>删除</Button>
</ConfirmDanger>
```

并在 import 补 `deleteDataSource`，把操作列宽度从 `280` 调整到 `340` 以容纳第四个按钮。

- [ ] **Step 3: 类型检查**

Run: `cd web && npm run typecheck` — Expected: 0 error

- [ ] **Step 4: 交互回归（写操作被拦截，无副作用）**

Run: `cd .. && .venv/Scripts/python.exe .ux-audit/confirm_probe.py`
Expected: `[订阅/停用] popconfirm=True`；数据源删除按钮点击后同样 `popconfirm=True`

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/changes/SubscriptionPage.tsx web/src/pages/datasources/DataSourceListPage.tsx
git commit -m "fix(subscriptions,datasources): 停用统一二次确认，补数据源删除入口"
```

---

## Task 7: 未落地能力的导航诚实化与占位页引导（P1-5、P1-7）

**Files:**
- Modify: `web/src/pages/placeholders/DegradedPage.tsx`（占位页组件，已定位确认）
- Modify: `web/src/layouts/AppShell.tsx:40-87`（`MenuItem` 接口与 `MENU` 数组）、`:222-228`（菜单渲染）

**背景：** 一级导航 15 项（`AppShell.tsx:50-87` 的 `MENU`），其中画像质量（MOD-04）、血缘（MOD-07）、权限分析（MOD-08）、采样（MOD-03）、系统管理（MOD-11）等模块的 20+ 路由渲染 `DegradedPage`，文案含「MOD-XX 的接口尚未在后端落地」这类内部代号，且无返回出口。注意：**分类分级已落地**（实测页面有真实数据），不要误标为规划中。

- [ ] **Step 1: 给 MenuItem 增加 planned 标记**

`web/src/layouts/AppShell.tsx:40-47` 的 `MenuItem` 接口加字段：

```tsx
  /** 后端能力未落地：菜单上标记「规划中」，避免用户逐个点开踩空。 */
  planned?: boolean;
```

并在 `MENU` 中为未落地项打标（按实测状态）：

```tsx
  { key: '/app/profile', label: '画像质量', icon: <ExperimentOutlined />, perm: 'profile:read', planned: true },
  { key: '/app/lineage', label: '血缘', icon: <ApartmentOutlined />, perm: 'lineage:read', planned: true },
  { key: '/app/permissions', label: '权限分析', icon: <LockOutlined />, perm: 'permission:read', planned: true },
  { key: '/app/sampling', label: '采样', icon: <ExperimentOutlined />, perm: 'sample:execute', planned: true },
  { key: '/app/admin', label: '系统管理', icon: <SettingOutlined />, planned: true },
```

- [ ] **Step 2: 占位页改为用户语言 + 返回出口**

把 `DegradedPage.tsx` 的渲染替换为（保留它现有的 props 与降级信息结构，只改用户可见文案与操作）：

```tsx
<Result
  status="info"
  title={`${pageName} 尚未开放`}
  subTitle="该能力依赖的后端接口还在建设中，暂无数据可展示。"
  extra={
    <Space>
      <Button type="primary" onClick={() => navigate('/app/dashboard')}>返回概览</Button>
      <Button onClick={() => window.history.back()}>返回上一页</Button>
    </Space>
  }
>
  <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
    如需了解排期，请联系平台管理员。
  </Typography.Paragraph>
</Result>
```

把 MOD-XX 代号从用户可见文案中移除；如需保留排查信息，放到 `title` 属性或仅开发环境展示。

- [ ] **Step 3: 菜单渲染时输出「规划中」标记**

`AppShell.tsx:222-228` 的 `menuItems.map` 改为：

```tsx
items={menuItems.map((m) => ({
  key: m.key,
  icon: m.icon,
  label: m.planned ? (
    <Space size={6}>
      {m.label}
      <Tag style={{ marginInlineEnd: 0 }}>规划中</Tag>
    </Space>
  ) : (
    m.label
  ),
  children: m.children?.map((c) => ({ key: c.key, label: c.label })),
}))}
```

`AppShell.tsx` 顶部需补 `import { Tag } from 'antd';`（若尚未导入）。

- [ ] **Step 4: 类型检查 + 全站巡检**

Run: `cd web && npm run typecheck` — Expected: 0 error
Run: `cd d:/workspace/my_github/local_ingestion/.ux-audit && ..\.venv\Scripts\python.exe ..\check_all_pages.py` — Expected: 占位路由页面文本含「尚未开放」且出现「返回概览」，无 `MOD-` 代号（输出到 `.ux-audit/pages_report.json`，不覆盖项目根的旧文件）

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "fix(nav): 未落地模块标记规划中，占位页改为用户语言并提供返回出口"
```

---

## Task 8: 筛选控件可访问名与触控目标（P1-8、P1-10）

**Files:**
- Modify: `web/src/components/FilterBar.tsx:69-118`（四类控件统一补 `aria-label`）
- Modify: 操作列使用 `size="small"` 的页面（Step 3 定位）

**背景：** 19 个筛选控件无 `label[for]` / `aria-label`（读屏只念「组合框」）；操作列按钮实测 44×24px、复选框 12×12px，低于 44×44 触控下限。

**关键简化：** 全站筛选控件都由 `FilterBar` 统一渲染（各页面只传 `fields` 数组），因此**只改 `FilterBar.tsx` 一处即可覆盖全部 19 个控件**，无需逐个页面改，也无需新建 `FilterSelect` 组件。

- [ ] **Step 1: 给 Select 补 aria-label**

`FilterBar.tsx:79-91` 的 `<Select` 增加一行：

```tsx
            <Select
              aria-label={field.label}
              allowClear
              style={{ minWidth: 160 }}
              placeholder={field.placeholder ?? `请选择${field.label}`}
```

- [ ] **Step 2: 给其余三类控件同样补上**

`Input`（`:69-78`）加 `aria-label={field.label}`；`InputNumber`（`:92-99`）加 `aria-label={field.label}`；`DatePicker.RangePicker`（`:100-118`）加 `aria-label={`${field.label} 日期范围`}`。

- [ ] **Step 3: 定位并放大触控目标**

Run: `cd web && rg -n 'size="small"' src/pages src/components --glob '!*.test.*'`

对操作列的按钮：去掉 `size="small"` 或改为 `size="middle"`，并把容器 `Space size={4}` 改为 `Space size={8}`。复选框热区在全局样式入口（`src/theme` 或 `index.css`，以实际存在者为准）补：

```css
.ant-checkbox-wrapper { position: relative; }
.ant-checkbox-wrapper::before { content: ''; position: absolute; inset: -10px; }
```

- [ ] **Step 4: 类型检查 + DOM 复验**

Run: `cd web && npm run typecheck` — Expected: 0 error
Run: `cd d:/workspace/my_github/local_ingestion && .venv/Scripts/python.exe .ux-audit/button_audit.py` — Expected: `inputUnlabeled` 数量显著下降（目标 0）

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "a11y(filters): 筛选控件补可访问名，操作列与复选框触控热区达标"
```

---

## Task 9: 任务列表轮询可见化（P1-9）

**Files:**
- Modify: `web/src/pages/tasks/TaskListPage.tsx:47-62`（查询与工具条）、`:169-171`（刷新按钮）

**背景：** 代码为 `refetchInterval: hasActive ? 3000 : false`（`TaskListPage.tsx:59`），实测存在约 2-3 秒的自动刷新，但界面无提示也无暂停开关。

- [ ] **Step 1: 增加暂停开关与最后更新时间**

```tsx
const [autoRefresh, setAutoRefresh] = useState(true);

// 复用 react-query 的 dataUpdatedAt 作为「最后更新」时间，不再自造状态
const { data, isLoading, isError, error, refetch, isFetching, dataUpdatedAt } = useQuery({
  queryKey: qk.tasks.list(params),
  queryFn: () => listTasks(params),
});
```

轮询改为 `refetchInterval: hasActive && autoRefresh ? 3000 : false`。

- [ ] **Step 2: 在 PageHeader extra 渲染状态**

```tsx
<Space size={8}>
  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
    {dataUpdatedAt ? `最后更新 ${dayjs(dataUpdatedAt).format('HH:mm:ss')}` : ''}
    {hasActive && autoRefresh ? ' · 自动刷新中' : ''}
  </Typography.Text>
  <Button
    size="small"
    onClick={() => setAutoRefresh((v) => !v)}
    disabled={!hasActive}
  >
    {autoRefresh ? '暂停刷新' : '恢复刷新'}
  </Button>
  <Button onClick={() => void refetch()} loading={isFetching}>刷新</Button>
</Space>
```

（项目已依赖 `dayjs`，直接 import 使用。）

- [ ] **Step 3: 类型检查**

Run: `cd web && npm run typecheck` — Expected: 0 error

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/tasks/TaskListPage.tsx
git commit -m "fix(tasks): 轮询可见化，提供最后更新时间与暂停开关"
```

---

## Task 10: P2 收尾（rowKey 与快捷键文案）

**Files:**
- Modify: `web/src/pages/tasks/AuditLogPage.tsx`（rowKey 用索引，触发 antd 弃用告警）
- Modify: `web/src/layouts/AppShell.tsx:242-248`（顶栏搜索框，placeholder 写死 `⌘K`）

- [ ] **Step 1: rowKey 改为业务主键**

先确认当前写法：Run: `cd web && rg -n "rowKey" src/pages/tasks/AuditLogPage.tsx`

把 `rowKey={(_, index) => index}`（或等价写法）改为 `rowKey={(r) => r.id}`；若审计条目无稳定 id，改用组合键：

```tsx
rowKey={(r) => `${r.occurred_at}-${r.action}-${r.actor ?? ''}`}
```

- [ ] **Step 2: 快捷键按平台渲染**

`AppShell.tsx:242-248` 的搜索框改为：

在组件内（`AppShell.tsx` 的 Header 组件体内）计算并替换 placeholder：

```tsx
const isMac = /mac|iphone|ipad/i.test(
  (navigator as { userAgentData?: { platform?: string } }).userAgentData?.platform
    ?? navigator.platform
    ?? navigator.userAgent,
);
const shortcut = isMac ? '⌘K' : 'Ctrl+K';
```

然后把 `AppShell.tsx:244` 的 `placeholder="搜索资产（⌘K）"` 改为：

```tsx
placeholder={`搜索资产（${shortcut}）`}
```

> 提示：`navigator.platform` 已废弃，上面的写法优先用 `userAgentData.platform`，取不到时回退。若项目已封装平台判断工具则直接复用，不要重复实现。

- [ ] **Step 3: 类型检查 + 全站巡检**

Run: `cd web && npm run typecheck` — Expected: 0 error
Run: `cd d:/workspace/my_github/local_ingestion/.ux-audit && ..\.venv\Scripts\python.exe ..\check_all_pages.py` — Expected: `/app/tasks/audit` 控制台不再出现 `rowKey` 弃用告警

- [ ] **Step 4: Commit**

```bash
git add web/src
git commit -m "chore(ui): rowKey 改用业务主键，搜索快捷键按平台渲染"
```

---

## 验收清单（全部任务完成后）

- [ ] `.venv/Scripts/python.exe -m pytest tests/unit/platform -q` 全绿
- [ ] `cd web && npm run typecheck && npm test` 全绿
- [ ] `.venv/Scripts/python.exe .ux-audit/happy_path.py` — 示例任务不再 500
- [ ] `.venv/Scripts/python.exe .ux-audit/verify_submit.py` — 有进度文案，错误文案无 pymysql / sqlalche.me
- [ ] `.venv/Scripts/python.exe .ux-audit/verify_requests.py` — 详情页不再出现「重 试」
- [ ] `.venv/Scripts/python.exe .ux-audit/confirm_probe.py` — 停用/删除均有确认
- [ ] `.venv/Scripts/python.exe .ux-audit/empty_state_probe.py` — 空态仍 7/7 覆盖（回归，防破坏）
- [ ] 更新 `.ux-audit/final-report.md`：把已完成项标记为「已修复」，P1-6 / P1-12 保留为待决策
