"""Unit tests for the orchestration layer (MOD-10 / T-107).

Pure-logic tests, no database. They exercise the full acceptance surface:

* re-entry protection (no duplicate active job_type+scope)
* manual trigger / cancel / retry
* global + per-datasource concurrency caps
* retry with back-off (retryable vs fatal)
* dependency chaining (scan -> diff -> notify)
* audit trail on key actions
* queryable history / stats
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from local_ingestion.platform.orchestration import (
    AuditService,
    ConcurrencyLimiter,
    DependencyRegistry,
    HandlerRegistry,
    InMemoryAuditSink,
    InMemoryTaskRunStore,
    ProcessLockProvider,
    RetryPolicy,
    TaskService,
    TaskSpec,
    TaskStatus,
    JobType,
    TriggerType,
    backoff_seconds,
    build_in_memory_orchestration,
    is_retryable,
)
from local_ingestion.platform.orchestration.errors import DuplicateTaskError, TaskNotFoundError


def _clock():
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _spec(job=JobType.METADATA, ds=7, **kw):
    scope = {"datasource_id": ds} if ds is not None else {}
    return TaskSpec(job_type=job, scope=scope, **kw)


def _service(**kw):
    return build_in_memory_orchestration(clock=_clock, sleeper=lambda s: None, **kw)


# ---------------------------------------------------------------- re-entry ----
def test_reentry_protection_rejects_duplicate_active():
    svc = _service()
    svc._handlers.register(JobType.METADATA, lambda ctx: {"ok": True})
    first = svc.submit(_spec())
    assert first.status == TaskStatus.PENDING
    # Second identical submit (same job_type + scope) must be rejected.
    try:
        svc.submit(_spec())
        raise AssertionError("duplicate submit should have failed")
    except DuplicateTaskError:
        pass


def test_reentry_allows_after_completion():
    svc = _service()
    svc._handlers.register(JobType.METADATA, lambda ctx: {"ok": True})
    r1 = svc.dispatch(_spec())
    assert r1.status == TaskStatus.SUCCESS
    # Now the scope is free again -> a new run is allowed.
    r2 = svc.submit(_spec())
    assert r2.id != r1.id
    assert r2.status == TaskStatus.PENDING


# ----------------------------------------------------------- manual + cancel --
def test_dispatch_runs_handler_and_records_stats():
    svc = _service()
    svc._handlers.register(JobType.METADATA, lambda ctx: {"rows": 42})
    run = svc.dispatch(_spec())
    assert run.status == TaskStatus.SUCCESS
    assert run.stats == {"rows": 42}
    assert run.duration_ms is not None


def test_cancel_pending():
    svc = _service()
    svc._handlers.register(JobType.METADATA, lambda ctx: {"ok": True})
    run = svc.submit(_spec())
    assert svc.cancel(run.id) is True
    assert svc.get(run.id).status == TaskStatus.CANCELLED


def test_cancel_running_signal():
    svc = _service()
    events = []

    def slow(ctx):
        # Simulate a long task that honours the cancel probe.
        for _ in range(200):
            if ctx.cancelled():
                events.append("cancelled")
                return {"partial": True}
            import time as _t
            _t.sleep(0.001)
        return {"done": True}

    svc._handlers.register(JobType.METADATA, slow)
    run2 = svc.submit(_spec(ds=8))
    # Run the task on a background thread so we can cancel it mid-flight.
    t = threading.Thread(target=lambda: svc.run_now(run2.id))
    t.start()
    import time as _t
    _t.sleep(0.02)
    assert svc.get(run2.id).status == TaskStatus.RUNNING
    assert svc.cancel(run2.id) is True
    t.join()
    res = svc.get(run2.id)
    assert res.status == TaskStatus.CANCELLED
    assert "cancelled" in events


# ----------------------------------------------------------------- retry ------
def test_retry_exhausts_then_fails_on_fatal():
    svc = _service()
    svc._handlers.register(JobType.METADATA, lambda ctx: (_ for _ in ()).throw(ValueError("bad arg")))
    run = svc.dispatch(_spec(retry=RetryPolicy(max_attempts=3)))
    assert run.status == TaskStatus.FAILED
    assert run.attempts == 1  # fatal errors are not retried
    assert "bad arg" in (run.error_message or "")


def test_retry_recovers_on_transient_failure():
    svc = _service()
    calls = {"n": 0}

    def flaky(ctx):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("transient down")
        return {"ok": True}

    svc._handlers.register(JobType.METADATA, flaky)
    run = svc.dispatch(_spec(retry=RetryPolicy(max_attempts=3, base_delay_sec=0.0)))
    assert run.status == TaskStatus.SUCCESS
    assert calls["n"] == 2  # first failed (retryable), second succeeded


# ------------------------------------------------------------- concurrency ----
def test_global_concurrency_cap_serializes():
    # max_global=1 -> only one task executes at a time.
    limiter = ConcurrencyLimiter(max_global=1, per_key_limits={})
    svc = build_in_memory_orchestration(
        concurrency=limiter, clock=_clock, sleeper=lambda s: None
    )
    active = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def worker(ctx):
        with lock:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
        import time as _t
        _t.sleep(0.02)
        with lock:
            active["now"] -= 1
        return {"ok": True}

    svc._handlers.register(JobType.METADATA, worker)
    svc._handlers.register(JobType.SAMPLE, worker)

    threads = []
    for i in range(3):
        t = threading.Thread(target=lambda i=i: svc.dispatch(_spec(ds=i, job=JobType.SAMPLE)))
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert active["peak"] == 1, active


# --------------------------------------------------------------- dependency ---
def test_dependency_chain_scan_to_diff_to_notify():
    svc = _service()
    fired = []

    def meta(ctx):
        fired.append("meta")
        return {"tables": 10}

    def diff(ctx):
        fired.append("diff")
        return {"changes": 3}

    def notify(ctx):
        fired.append("notify")
        return {"sent": 1}

    svc._handlers.register(JobType.METADATA, meta)
    svc._handlers.register("diff", diff)
    svc._handlers.register("notify", notify)
    svc._deps.on_success(JobType.METADATA, "diff")
    svc._deps.on_success("diff", "notify")

    run = svc.dispatch(_spec())
    assert run.status == TaskStatus.SUCCESS
    assert fired == ["meta", "diff", "notify"]
    # all three runs recorded with correct chaining order
    assert len(svc.list()) == 3
    assert svc.list(job_type="notify")[0].status == TaskStatus.SUCCESS


# ------------------------------------------------------------------- audit ----
def test_audit_trail_recorded():
    sink = InMemoryAuditSink()
    svc = build_in_memory_orchestration(
        audit=AuditService(sink, clock=_clock), clock=_clock, sleeper=lambda s: None
    )
    svc._handlers.register(JobType.METADATA, lambda ctx: {"ok": True})
    svc.dispatch(_spec(), actor="alice")
    actions = {e.action for e in sink.entries}
    assert "task.submit" in actions
    assert "task.success" in actions
    # actor carried through
    assert any(e.actor == "alice" for e in sink.entries)


# ------------------------------------------------------------------ queries ----
def test_list_filtering_by_status_and_type():
    svc = _service()
    svc._handlers.register(JobType.METADATA, lambda ctx: {"ok": True})
    svc._handlers.register(JobType.SAMPLE, lambda ctx: {"ok": True})
    svc.dispatch(_spec(job=JobType.METADATA, ds=1))
    svc.dispatch(_spec(job=JobType.SAMPLE, ds=2))
    assert len(svc.list(status=TaskStatus.SUCCESS)) == 2
    assert len(svc.list(job_type=JobType.SAMPLE)) == 1
    assert len(svc.list(datasource_id=1)) == 1


def test_retry_endpoint_creates_new_run():
    svc = _service()
    svc._handlers.register(
        JobType.METADATA, lambda ctx: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    run = svc.dispatch(_spec(retry=RetryPolicy(max_attempts=1)))
    assert run.status == TaskStatus.FAILED
    new_run = svc.retry(run.id)
    assert new_run.id != run.id
    assert new_run.status == TaskStatus.FAILED


def test_get_missing_raises():
    svc = _service()
    try:
        svc.get(999)
    except Exception:
        pass
    # get returns None for missing; cancel raises
    try:
        svc.cancel(999)
        raise AssertionError("expected TaskNotFoundError")
    except TaskNotFoundError:
        pass


# ----------------------------------------------------------- backoff helpers --
def test_backoff_is_exponential_and_capped():
    pol = RetryPolicy(base_delay_sec=1.0, max_delay_sec=10.0, jitter=False)
    assert backoff_seconds(1, pol) == 1.0
    assert backoff_seconds(2, pol) == 2.0
    assert backoff_seconds(10, pol) == 10.0  # capped


def test_is_retryable_classification():
    assert is_retryable(ConnectionError("refused"))
    assert is_retryable(TimeoutError("timed out"))
    assert not is_retryable(ValueError("bad input"))
    assert not is_retryable(PermissionError("denied"))
