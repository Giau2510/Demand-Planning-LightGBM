"""1.2.13 resource audit: resource figures of every job attempt, a timed-out job thread keeps its lock until it ends, two
heavy jobs never run together, a heavy job waits (bounded) while the commit headroom is below what its job type
measurably needed, and the explanation caches give their panel / traces back (stale versions at once, all when idle)."""
import gc
import json
import sys
import threading
import time
import weakref
from datetime import timedelta

import numpy as np
import pytest

from app import db
from app import settings_service as ss
from app import timeutil
from app.jobs import resources, runner
from app.jobs.scheduler import Scheduler


def _row(key):
    with db.read() as c:
        return db.one(c, "SELECT * FROM job_runs WHERE idempotency_key=?", (key,))


def _res(key):
    return json.loads(_row(key)["result_json"] or "{}").get("resources")


def _freeze_after(r):
    t = timeutil.parse_iso(r["next_attempt_at"]) + timedelta(seconds=1)   # computed once
    timeutil.set_now_override(lambda: t)


def _settings(monkeypatch, **upd):
    base = ss.ScheduleSettings().model_copy(update=upd)
    monkeypatch.setattr(runner.ss, "get", lambda s, conn=None: base if s == "schedule" else ss.SECTIONS[s]())


@pytest.fixture(autouse=True)
def no_live_jobs():
    yield
    deadline = time.time() + 10
    while runner.live_jobs() and time.time() < deadline:
        time.sleep(0.05)
    for t in threading.enumerate():
        if t.name.startswith("reap-"):
            t.join(10)
    assert runner.live_jobs() == []


# ---------------------------------------------------------------- readings
@pytest.mark.skipif(sys.platform not in ("win32", "linux"), reason="memory readings: Windows / Linux")
def test_snapshot_reads_this_process_and_the_machine():
    s = resources.snapshot()
    assert s["private"] > 0 and s["ws"] > 0 and s["cpu_user"] >= 0
    assert s["phys_total"] > s["phys_avail"] > 0 and s["commit_avail"] > 0


@pytest.mark.skipif(sys.platform not in ("win32", "linux"), reason="memory readings: Windows / Linux")
def test_the_meter_sees_the_peak_and_the_cpu_of_the_work():
    m = resources.JobMeter(interval=0.05).start()
    a = np.ones(200 * resources.MB // 8)        # 200 MB touched
    t0 = time.process_time()
    while time.process_time() - t0 < 0.3:
        a.sum()
    time.sleep(0.2)
    del a
    r = m.stop().result()
    json.dumps(r)
    assert r["private_mb"]["peak"] - r["private_mb"]["start"] >= 150
    assert r["private_mb"]["end"] < r["private_mb"]["peak"]
    assert r["wall_s"] >= 0.5 and r["cpu_user_s"] + r["cpu_kernel_s"] >= 0.25 and r["samples"] >= 3
    assert r["machine_mb"]["commit_avail_min"] <= r["machine_mb"]["commit_avail_start"]


def test_readings_never_fail_a_job(monkeypatch):
    def boom():
        raise OSError("no counters")
    monkeypatch.setattr(resources, "_read", boom)
    assert resources.snapshot() == {}
    r = resources.JobMeter(interval=0.01).start().stop().result()
    assert r["private_mb"]["peak"] is None and r["samples"] == 0
    assert resources.release_memory()["released_mb"] is None
    assert resources.peak_growth_mb(None) is None and resources.peak_growth_mb({"private_mb": {"peak": 5, "start": 2}}) == 3


# ---------------------------------------------------------------- job records
def test_every_attempt_records_its_resources(monkeypatch):
    from app.sync import NotApplicable
    calls = {"n": 0}

    def d0(job_id, params):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("source down")
        return {"status": "SUCCEEDED"}
    monkeypatch.setattr(runner, "_handlers", lambda: {"D0_SYNC": d0, "D1_SYNC": lambda j, p: (_ for _ in ()).throw(
        NotApplicable("demo"))})
    r = runner.execute("D0_SYNC", "D0_SYNC:res")
    assert r["status"] == "RETRY_WAIT"
    first = _res("D0_SYNC:res")
    assert first["attempt"] == 1 and first["pid"] > 0 and "private_mb" in first and first["heavy"] is False
    assert json.loads(_row("D0_SYNC:res")["result_json"])["params"] == {}
    _freeze_after(r)
    r = runner.execute("D0_SYNC", "D0_SYNC:res")
    assert r["status"] == "SUCCEEDED" and _res("D0_SYNC:res")["attempt"] == 2
    assert json.loads(_row("D0_SYNC:res")["result_json"])["result"] == {"status": "SUCCEEDED"}
    assert "cleanup" not in _res("D0_SYNC:res")          # light job: no forced collection
    r = runner.execute("D1_SYNC", "D1_SYNC:na")
    assert r["status"] == "SKIPPED" and _res("D1_SYNC:na")["attempt"] == 1


def test_a_heavy_job_records_its_memory_check_and_no_forced_collection(monkeypatch):
    monkeypatch.setattr(runner, "_handlers", lambda: {"TRAIN_PUBLISH": lambda j, p, cancel=None: {
        "status": "SUCCEEDED", "n": int(np.ones(10_000_000).sum())}})
    r = runner.execute("TRAIN_PUBLISH", "TRAIN_PUBLISH:heavy")
    assert r["status"] == "SUCCEEDED"
    res = _res("TRAIN_PUBLISH:heavy")
    assert res["heavy"] is True and "cleanup" not in res     # measured useless (0-6 MB): not done
    assert res["memory_check"]["decision"] == "NO_BASELINE"


# ---------------------------------------------------------------- duplicates / overlap
def test_a_timed_out_thread_keeps_its_lock_until_it_really_ends(monkeypatch):
    _settings(monkeypatch, timeout_seconds=1, max_attempts=3)
    gate = threading.Event()

    def stubborn(job_id, params):          # ignores the timeout (like lgb.train between two cancel checks)
        gate.wait(20)
        return {"status": "SUCCEEDED"}
    monkeypatch.setattr(runner, "_handlers", lambda: {"D0_SYNC": stubborn})
    r = runner.execute("D0_SYNC", "D0_SYNC:slow")
    assert r["status"] == "RETRY_WAIT" and r["reason_code"] == "TIMEOUT"
    assert _res("D0_SYNC:slow")["thread_alive_after_timeout"] is True
    assert [j["job_type"] for j in runner.live_jobs()] == ["D0_SYNC"]
    with db.read() as c:
        assert db.one(c, "SELECT * FROM job_locks WHERE lock_name='job:D0_SYNC'")       # lock kept
    r2 = runner.execute("D0_SYNC", "D0_SYNC:next")                  # no second run of the same type meanwhile
    assert r2["note"] == "LOCKED" and "still running" in r2["busy"]
    assert _row("D0_SYNC:next")["status"] == "RETRY_WAIT" and _row("D0_SYNC:next")["reason_code"] == "LOCKED"
    gate.set()
    for t in threading.enumerate():
        if t.name.startswith("reap-"):
            t.join(10)
    assert runner.live_jobs() == []
    with db.read() as c:
        assert not db.one(c, "SELECT * FROM job_locks WHERE lock_name='job:D0_SYNC'")   # released when it ended
    r3 = runner.execute("D0_SYNC", "D0_SYNC:after")
    assert r3["status"] == "SUCCEEDED"


def test_two_heavy_jobs_never_run_together_but_light_jobs_do(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def train(job_id, params, cancel=None):
        started.set()
        release.wait(20)
        return {"status": "SUCCEEDED"}
    monkeypatch.setattr(runner, "_handlers", lambda: {"TRAIN_PUBLISH": train,
                                                      "FORECAST_EXTEND": lambda j, p, cancel=None: {"status": "SUCCEEDED"},
                                                      "D0_SYNC": lambda j, p: {"status": "SUCCEEDED"}})
    t = threading.Thread(target=runner.execute, args=("TRAIN_PUBLISH", "TRAIN_PUBLISH:sched", "MANUAL"))
    t.start()
    assert started.wait(10)
    r = runner.execute("FORECAST_EXTEND", "FORECAST_EXTEND:x")
    assert r["note"] == "LOCKED" and "heavy job TRAIN_PUBLISH" in r["busy"]
    d0 = runner.execute("D0_SYNC", "D0_SYNC:during")
    assert d0["status"] == "SUCCEEDED" and _res("D0_SYNC:during")["other_jobs"][0].startswith("TRAIN_PUBLISH ")
    release.set()
    t.join(10)
    assert _row("TRAIN_PUBLISH:sched")["status"] == "SUCCEEDED"
    assert runner.execute("FORECAST_EXTEND", "FORECAST_EXTEND:y")["status"] == "SUCCEEDED"


def test_a_backfill_is_heavy_a_regular_d1_is_not():
    assert runner.is_heavy("D1_SYNC", {"backfill_start": "2026-01-01"}) and not runner.is_heavy("D1_SYNC", {})
    assert runner.is_heavy("TRAIN_PUBLISH") and runner.is_heavy("FORECAST_EXTEND") and not runner.is_heavy("D0_SYNC")


# ---------------------------------------------------------------- memory guard
def _history(job_type, start_mb, peak_mb, n=1):
    with db.tx() as c:
        for i in range(n):
            c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, "
                      "created_at, result_json) VALUES (?,?,?, 'SCHEDULE', 'SUCCEEDED', 1, 4, ?, ?)",
                      (f"JOB-H-{job_type}-{i}", job_type, f"{job_type}:hist{i}", f"2026-10-0{i + 1}T00:00:00+00:00",
                       json.dumps({"params": {}, "resources": {"private_mb": {"start": start_mb, "peak": peak_mb}}})))


def _machine(monkeypatch, commit_mb, phys_mb):
    monkeypatch.setattr(resources, "snapshot", lambda: {"private": 500 * resources.MB, "ws": 400 * resources.MB,
                                                        "commit_avail": commit_mb * resources.MB,
                                                        "phys_avail": phys_mb * resources.MB})


def test_the_memory_need_is_the_largest_measured_growth_of_the_job_type():
    assert runner.memory_need_mb("TRAIN_PUBLISH") is None
    _history("TRAIN_PUBLISH", 800, 2800)
    _history("D0_SYNC", 500, 9000)                      # another job type never counts
    assert runner.memory_need_mb("TRAIN_PUBLISH") == 2000


def test_a_heavy_job_waits_while_the_commit_headroom_is_too_small_and_the_waits_are_bounded(monkeypatch):
    _settings(monkeypatch, max_attempts=2)
    calls = {"n": 0}

    def train(job_id, params, cancel=None):
        calls["n"] += 1
        return {"status": "SUCCEEDED"}
    monkeypatch.setattr(runner, "_handlers", lambda: {"TRAIN_PUBLISH": train})
    _history("TRAIN_PUBLISH", 1000, 3000)               # measured need 2,000 MB -> 2,500 MB with the margin
    _machine(monkeypatch, commit_mb=2400, phys_mb=300)
    r = runner.execute("TRAIN_PUBLISH", "TRAIN_PUBLISH:mem")
    assert r["status"] == "RETRY_WAIT" and r["reason_code"] == "INSUFFICIENT_MEMORY" and calls["n"] == 0
    chk = _res("TRAIN_PUBLISH:mem")["memory_check"]
    assert chk["decision"] == "INSUFFICIENT_MEMORY" and chk["need_mb"] == 2000 and chk["commit_avail_mb"] == 2400
    with db.read() as c:
        assert not db.one(c, "SELECT * FROM job_locks")                      # nothing held while waiting
    _freeze_after(r)
    r = runner.execute("TRAIN_PUBLISH", "TRAIN_PUBLISH:mem")
    assert r["status"] == "FAILED" and r["attempt"] == 2 and calls["n"] == 0     # bounded: no endless waiting
    with db.read() as c:
        assert db.one(c, "SELECT * FROM alerts WHERE code='RETRIES_EXHAUSTED'")
    _machine(monkeypatch, commit_mb=6000, phys_mb=300)   # enough commit, little physical RAM: runs, paging expected
    r = runner.execute("TRAIN_PUBLISH", "TRAIN_PUBLISH:mem2")
    assert r["status"] == "SUCCEEDED" and calls["n"] == 1
    assert _res("TRAIN_PUBLISH:mem2")["memory_check"]["decision"] == "PAGING_EXPECTED"
    _machine(monkeypatch, commit_mb=6000, phys_mb=5000)
    assert runner.memory_check("TRAIN_PUBLISH")["decision"] == "OK"


def test_light_jobs_are_never_held_by_the_memory_guard(monkeypatch):
    _history("D0_SYNC", 100, 9000)
    _machine(monkeypatch, commit_mb=10, phys_mb=10)
    monkeypatch.setattr(runner, "_handlers", lambda: {"D0_SYNC": lambda j, p: {"status": "SUCCEEDED"}})
    assert runner.execute("D0_SYNC", "D0_SYNC:light")["status"] == "SUCCEEDED"
    assert "memory_check" not in _res("D0_SYNC:light")


# ---------------------------------------------------------------- explanation caches
class _Panel:
    pass


def test_explanations_drop_stale_panels_at_once_and_everything_when_idle():
    from app.ml import explain
    a, b = _Panel(), _Panel()
    wa, wb = weakref.ref(a), weakref.ref(b)
    explain._cache.clear()
    explain._inputs.clear()
    explain._cache[("run-a", "s1")] = {"status": "OK", "panel": a}
    explain._cache[("run-a", "s2")] = {"status": "OK", "panel": a}
    explain._cache[("run-a", "s3")] = {"status": "DATA_CHANGED"}
    explain._cache[("run-b", "s1")] = {"status": "OK", "panel": b}
    explain._inputs[("run-b", "v")] = {"panel": b}
    assert explain._drop_stale_panels({"panel": b}) == 2
    assert set(explain._cache) == {("run-a", "s3"), ("run-b", "s1")}
    del a
    gc.collect()
    assert wa() is None                                    # the old panel is really freed
    explain._last_used[0] = time.monotonic()
    assert explain.release_idle(60) == 0                   # in use: kept
    explain._last_used[0] = time.monotonic() - 120
    assert explain.release_idle(60) == 3 and not explain._cache and not explain._inputs
    del b
    gc.collect()
    assert wb() is None


def test_shap_traces_are_released_when_idle_and_the_scheduler_does_it():
    from app.ml import explain, shap_audit
    explain._cache.clear()
    explain._inputs.clear()
    shap_audit._cache.clear()
    shap_audit._cache[("k",)] = {"_comps": list(range(1000))}
    shap_audit._last_used[0] = time.monotonic()
    assert Scheduler.release_idle_caches(60) == 0
    shap_audit._last_used[0] = time.monotonic() - 120
    explain._cache.clear()
    explain._inputs.clear()
    explain._inputs[("run", "v")] = {"panel": _Panel()}
    explain._last_used[0] = time.monotonic() - 120
    assert Scheduler.release_idle_caches(60) == 2
    assert not shap_audit._cache and not explain._inputs


def test_the_idle_release_never_raises(monkeypatch):
    from app.ml import explain

    def boom(_s):
        raise RuntimeError("x")
    monkeypatch.setattr(explain, "release_idle", boom)
    assert Scheduler.release_idle_caches(0) == 0


# ---------------------------------------------------------------- training memory: same model
def test_dropping_the_raw_matrix_and_the_frame_keeps_the_model_identical(small_demo):
    import lightgbm as lgb
    from app.data.demand import load_demand, resolve_scope
    from app.ml import model
    from app.ml.features import build_panel, direct_training_matrix, feature_names, is_direct, training_matrix
    with db.read() as c:
        scope = resolve_scope(c)
    panel = build_panel(load_demand(scope["scope_key"]))
    cfg = ss.get("model")
    booster, info = model.train(panel, cfg)
    # the path before 1.2.13: the caller's raw matrix stays referenced during the boosting rounds
    X, y = (direct_training_matrix(panel, cfg, model.direct_max_horizon(cfg)) if is_direct(cfg)
            else training_matrix(panel, cfg))
    ref = lgb.train(model.lgb_params(cfg), lgb.Dataset(X, y, feature_name=feature_names(cfg),
                                                       categorical_feature=["sku_code", "fc_code"], free_raw_data=True),
                    num_boost_round=cfg.num_boost_round)
    assert info["n_rows"] == len(y)
    assert booster.model_to_string() == ref.model_to_string()


def test_the_preallocated_training_matrices_equal_the_stacked_ones_exactly(small_demo):
    from app.data.demand import load_demand, resolve_scope
    from app.ml import model
    from app.ml.features import build_panel, direct_training_matrix, training_matrix
    with db.read() as c:
        scope = resolve_scope(c)
    panel = build_panel(load_demand(scope["scope_key"]))
    base = ss.get("model")
    for cfg in (base.model_copy(update={"forecast_strategy": "RECURSIVE"}),
                base.model_copy(update={"forecast_strategy": "DIRECT"})):
        if cfg.forecast_strategy == "DIRECT":
            new = direct_training_matrix(panel, cfg, model.direct_max_horizon(cfg))
            old = direct_training_matrix(panel, cfg, model.direct_max_horizon(cfg), with_index=True)[:2]   # np.vstack path
        else:
            new = training_matrix(panel, cfg)
            old = training_matrix(panel, cfg, with_index=True)[:2]
        assert new[0].dtype == old[0].dtype == np.float32 and new[1].dtype == old[1].dtype
        assert new[0].shape == old[0].shape and new[0].shape[0] > 1000
        assert np.array_equal(new[0], old[0], equal_nan=True) and np.array_equal(new[1], old[1], equal_nan=True)
    empty = training_matrix(panel, base, min_t=10_000)          # no day qualifies
    assert empty[0].shape == (0, empty[0].shape[1]) and empty[0].dtype == np.float32 and empty[1].size == 0


# ---------------------------------------------------------------- Excel exports
def test_an_excel_export_leaves_no_workbook_behind():
    """The workbook of an export (one object per cell, linked both ways) is cyclic garbage: the helper frees it before
    returning, not whenever Python's full collection happens to run (forecast export: 0.67 GB kept, measured)."""
    from datetime import date

    import pandas as pd
    from openpyxl.workbook.workbook import Workbook

    from app.data.excel_io import dataframe_to_xlsx
    gc.collect()
    count = lambda: sum(isinstance(o, Workbook) for o in gc.get_objects())  # noqa: E731
    before = count()
    gc.disable()           # no automatic collection: only the helper itself can free the workbook
    try:
        content = dataframe_to_xlsx({"a": pd.DataFrame({"x": range(2000), "d": [date(2026, 1, 1)] * 2000})},
                                    date_format="DD/MM/YYYY")
        after = count()
    finally:
        gc.enable()
    assert content[:2] == b"PK" and after == before
