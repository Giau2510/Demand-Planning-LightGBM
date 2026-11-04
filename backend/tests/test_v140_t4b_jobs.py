"""1.4.0 T4b tests: the SEL2 job handlers (ml/sel2/jobs.py) run by jobs/runner.py - FORECAST_REFRESH in SEL2 mode
(AVG_DEMAND read that never blocks, sel2-day in a child), CANDIDATE_TRAIN, FORECAST_EXPORT (stale / AVG re-export),
retry / NOT_READY mapping, the emergency switch, the overlap rule next to a running training and the child-process
wrapper (JSON result, timeout, cancellation kills the process tree).

The heavy child is always a fake injected with sel2_jobs.set_child_runner; the wrapper itself is exercised with tiny
`python -c` children only. Isolated databases (conftest), fixed Vietnam times: unit tests and integration with fakes."""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from app import db
from app import settings_service as ss
from app import timeutil
from app.jobs import resources, runner
from app.ml import daily_refresh as dr
from app.ml.sel2 import avg_demand, export
from app.ml.sel2 import jobs as sel2_jobs
from app.timeutil import VN_TZ

from test_v131_refresh import _d1_ok, _freeze, _no_real_bigquery  # noqa: F401 (autouse fixture)
from test_v131_refresh_jobs import _bq_scope, _patched_get, _sched
from test_v140_t4b_planning import TUE, _at, _export, _sel2_run

PUBLISHED = {"ok": True, "result": {"status": "PUBLISHED", "run_id": "FRR-1", "flags": ["MODEL_PREV_WEEK"],
                                    "model_version": "SEL2 x", "export": {"ok": True, "result": {"version": 1}}}}


@pytest.fixture(autouse=True)
def _reset_child():
    yield
    sel2_jobs.set_child_runner(None)


@pytest.fixture
def env(sel2_on, monkeypatch):
    _bq_scope()
    _freeze(_at(TUE, "05:10"))
    _d1_ok(day=TUE)
    monkeypatch.setattr(ss, "get", _patched_get(_sched(refresh_enabled=True)))
    reads = []

    def read(d, cfg=None, bq=None):                                 # records a completed CURRENT read, as the real one
        reads.append(str(d))
        rid = db.new_id("AVR")
        with db.tx() as c:
            c.execute("INSERT INTO avg_demand_reads(id, source_table, business_date, kind, n_rows, source_modified, "
                      "completed_at) VALUES (?, ?, ?, 'CURRENT', 3, ?, ?)",
                      (rid, ss.get("sel2_pipeline").avg_demand_table, str(d), "2026-11-02T22:00:00+00:00",
                       timeutil.now_iso()))
        return {"read_id": rid, "rows": 3, "source_modified": "2026-11-02T22:00:00+00:00"}
    monkeypatch.setattr(avg_demand, "read_current", read)
    return reads


def _child(calls, result):
    def run(args, timeout, cancel):
        calls.append(list(args))
        return result(args) if callable(result) else result
    sel2_jobs.set_child_runner(run)


def _refresh(key="FORECAST_REFRESH:2026-11-03:05:10", **params):
    return runner.execute("FORECAST_REFRESH", key, "SCHEDULE", None, {"business_date": str(TUE), **params})


def _result(row):
    return json.loads(row["result_json"])["result"]


# ================================================================== FORECAST_REFRESH (SEL2 mode)
def test_refresh_reads_avg_then_runs_sel2_day_in_the_child(env):
    calls = []
    _child(calls, PUBLISHED)
    row = _refresh()
    assert row["status"] == "SUCCEEDED" and row["reason_code"] == "SEL2_PUBLISHED"
    assert calls == [["sel2-day", "--date", str(TUE), "--yes", "--trigger", "SCHEDULE", "--job-id", row["id"]]]
    assert env == [str(TUE)]
    res = _result(row)
    assert res["refresh_run_id"] == "FRR-1" and res["export"]["version"] == 1 and res["flags"] == ["MODEL_PREV_WEEK"]
    _child(calls, PUBLISHED)
    row = _refresh(key="FORECAST_REFRESH:2026-11-03:RERUN", force=True)
    assert calls[-1] == ["sel2-day", "--date", str(TUE), "--yes", "--force", "--trigger", "SCHEDULE",
                         "--job-id", row["id"]]
    assert env == [str(TUE)]                                         # the read of the day is not repeated


def test_avg_read_failure_is_a_flag_and_never_blocks(env, monkeypatch):
    def boom(d, cfg=None, bq=None):
        raise RuntimeError("bq down")
    monkeypatch.setattr(avg_demand, "read_current", boom)
    calls = []
    _child(calls, PUBLISHED)
    row = _refresh()
    assert row["status"] == "SUCCEEDED" and len(calls) == 1
    res = _result(row)
    assert "AVG_READ_FAILED" in res["flags"] and res["avg_read"]["status"] == "FAILED"


def test_child_error_mapping_retry_not_ready_failed(env):
    calls = []
    _child(calls, {"ok": False, "code": "SEL2_LOW_MEMORY", "detail": "free commit 900 MB"})
    row = _refresh(key="FORECAST_REFRESH:2026-11-03:A")
    assert row["status"] == "RETRY_WAIT" and row["reason_code"] == "SEL2_LOW_MEMORY" and row["next_attempt_at"]
    _child(calls, {"ok": False, "code": "OPEN_HOURS_INVALID", "detail": "lag"})
    row = _refresh(key="FORECAST_REFRESH:2026-11-03:B")
    assert row["status"] == "SKIPPED" and row["reason_code"] == "OPEN_HOURS_INVALID"
    _child(calls, {"ok": False, "code": "SEL2_NO_MODEL", "detail": "none"})
    row = _refresh(key="FORECAST_REFRESH:2026-11-03:C")
    assert row["status"] == "FAILED" and row["reason_code"] == "SEL2_NO_MODEL"
    _child(calls, {"ok": True, "result": {"status": "ALREADY_PUBLISHED", "run_id": "FRR-1"}})
    row = _refresh(key="FORECAST_REFRESH:2026-11-03:D")
    assert row["status"] == "SKIPPED" and row["reason_code"] == "ALREADY_PUBLISHED"


def test_refresh_without_todays_d1_is_not_ready_and_spawns_nothing(sel2_on, monkeypatch):
    _bq_scope()
    _freeze(_at(TUE, "05:10"))
    monkeypatch.setattr(ss, "get", _patched_get(_sched(refresh_enabled=True)))
    calls = []
    _child(calls, PUBLISHED)
    row = _refresh()
    assert row["status"] == "SKIPPED" and row["reason_code"] == "REFRESH_WAITS_FOR_D1" and calls == []


def test_switch_off_refresh_runs_the_131_refresh_and_no_child(monkeypatch):
    _bq_scope()
    _freeze(_at(TUE, "05:10"))
    monkeypatch.setattr(ss, "get", _patched_get(_sched(refresh_enabled=True)))
    seen, calls = [], []
    monkeypatch.setattr(dr, "run", lambda business_date=None, job_id=None, cancel=None, progress=None,
                        trigger="SCHEDULE": seen.append(business_date) or {"status": "PUBLISHED"})
    _child(calls, PUBLISHED)
    assert _refresh()["status"] == "SUCCEEDED"
    assert seen == [str(TUE)] and calls == []


# ================================================================== CANDIDATE_TRAIN / TRAIN_PUBLISH / switch
def test_candidate_train_child_success_and_retryable_low_memory(env):
    calls = []
    _child(calls, {"ok": True, "result": {"origin": "2026-11-02", "trained": ["MOC"], "skipped": []}})
    row = runner.execute("CANDIDATE_TRAIN", "CANDIDATE_TRAIN:2026-11-02", "SCHEDULE", None, {"origin": "2026-11-02"})
    assert row["status"] == "SUCCEEDED"
    assert calls == [["sel2-train", "--origin", "2026-11-02", "--yes", "--trigger", "SCHEDULE", "--job-id", row["id"]]]
    _child(calls, {"ok": False, "code": "SEL2_LOW_MEMORY"})
    row = runner.execute("CANDIDATE_TRAIN", "CANDIDATE_TRAIN:2026-10-26", "SCHEDULE", None, {"origin": "2026-10-26"})
    assert row["status"] == "RETRY_WAIT" and row["reason_code"] == "SEL2_LOW_MEMORY"
    _child(calls, {"ok": False, "code": "SEL2_TRAIN_FAILED"})
    row = runner.execute("CANDIDATE_TRAIN", "CANDIDATE_TRAIN:2026-10-19", "SCHEDULE", None, {"origin": "2026-10-19"})
    assert row["status"] == "FAILED" and row["reason_code"] == "SEL2_TRAIN_FAILED"


def test_scheduled_train_publish_skipped_while_sel2_is_on(env):
    row = runner.execute("TRAIN_PUBLISH", f"TRAIN_PUBLISH:{TUE}", "SCHEDULE", None, {})
    assert row["status"] == "SKIPPED" and row["reason_code"] == "SEL2_PIPELINE_ACTIVE"


def test_sel2_job_types_skipped_with_the_switch_off(monkeypatch):
    monkeypatch.setattr(ss, "get", _patched_get(_sched(refresh_enabled=True)))
    calls = []
    _child(calls, PUBLISHED)
    row = runner.execute("CANDIDATE_TRAIN", "CANDIDATE_TRAIN:2026-11-02", "SCHEDULE", None, {"origin": "2026-11-02"})
    assert row["status"] == "SKIPPED" and row["reason_code"] == "SEL2_DISABLED" and calls == []
    row = runner.execute("FORECAST_EXPORT", f"FORECAST_EXPORT:{TUE}:STALE", "SCHEDULE", None,
                         {"business_date": str(TUE), "mode": "STALE"})
    assert row["status"] == "SKIPPED" and row["reason_code"] == "SEL2_DISABLED"


# ================================================================== FORECAST_EXPORT
def test_stale_export_job_writes_once_and_is_not_needed_after_a_publication(env, monkeypatch):
    written = []
    monkeypatch.setattr(export, "write_daily_export", lambda d, trigger="SCHEDULE", job_id=None, scope_key=None:
                        written.append((str(d), trigger)) or {"version": 1, "is_stale": True})
    _freeze(_at(TUE, "06:30"))
    key = f"FORECAST_EXPORT:{TUE}:STALE"
    row = runner.execute("FORECAST_EXPORT", key, "SCHEDULE", None, {"business_date": str(TUE), "mode": "STALE"})
    assert row["status"] == "SUCCEEDED" and written == [(str(TUE), "STALE")] and env == [str(TUE)]
    assert runner.execute("FORECAST_EXPORT", key, "SCHEDULE")["note"] == "ALREADY_SUCCEEDED" and len(written) == 1
    _sel2_run(TUE)
    row = runner.execute("FORECAST_EXPORT", key + "2", "SCHEDULE", None, {"business_date": str(TUE), "mode": "STALE"})
    assert row["status"] == "SKIPPED" and row["reason_code"] == "SEL2_STALE_EXPORT_NOT_NEEDED" and len(written) == 1


def test_avg_reexport_job_waits_until_the_table_changed_then_writes_a_new_version(env, monkeypatch):
    written, mod = [], {"v": "2026-11-02T22:00:00+00:00"}
    monkeypatch.setattr(export, "write_daily_export", lambda d, trigger="SCHEDULE", job_id=None, scope_key=None:
                        written.append(trigger) or {"version": 2})
    monkeypatch.setattr(avg_demand, "source_modified_now", lambda table=None, cfg=None, bq=None: mod["v"])
    _freeze(_at(TUE, "10:15"))
    _export(TUE, source_modified="2026-11-02T22:00:00+00:00")
    key, p = f"FORECAST_EXPORT:{TUE}:AVG", {"business_date": str(TUE), "mode": "AVG"}
    row = runner.execute("FORECAST_EXPORT", key, "SCHEDULE", None, p)
    assert row["status"] == "RETRY_WAIT" and row["reason_code"] == "SEL2_AVG_UNCHANGED" and written == []
    mod["v"] = "2026-11-03T03:15:00+00:00"                            # 10:15 Vietnam: the table was refreshed
    _freeze(_at(TUE, "10:26"))
    row = runner.execute("FORECAST_EXPORT", key, "RETRY")
    assert row["status"] == "SUCCEEDED" and written == ["AVG_REEXPORT"] and env == [str(TUE)]
    _freeze(datetime(2026, 11, 4, 0, 30, tzinfo=VN_TZ))                # a waiting job of a past day ends
    row = runner.execute("FORECAST_EXPORT", f"FORECAST_EXPORT:{TUE}:AVG2", "SCHEDULE", None, p)
    assert row["status"] == "SKIPPED" and row["reason_code"] == "SEL2_AVG_REEXPORT_DAY_PASSED"


# ================================================================== overlap with a running CANDIDATE_TRAIN
def test_refresh_may_start_next_to_training_only_after_prev_week_deadline_with_free_commit(sel2_on, monkeypatch):
    stop = threading.Event()
    th = threading.Thread(target=stop.wait, daemon=True)
    th.start()
    with runner._live_lock:
        runner._live["JOB-TRAIN"] = ("CANDIDATE_TRAIN", True, th)
    commit = {"v": 8192 * resources.MB}
    monkeypatch.setattr(resources, "snapshot", lambda: {"commit_avail": commit["v"], "phys_avail": None})
    try:
        _freeze(_at(TUE, "06:10"))
        assert runner._busy_reason("FORECAST_REFRESH", True)
        _freeze(_at(TUE, "06:20"))
        assert runner._busy_reason("FORECAST_REFRESH", True) is None
        assert runner._busy_reason("TRAIN_PUBLISH", True)              # any other heavy job still waits
        commit["v"] = 1024 * resources.MB
        assert runner._busy_reason("FORECAST_REFRESH", True)
        commit["v"] = 8192 * resources.MB
        ss.update("sel2_pipeline", {"enabled": False})
        assert runner._busy_reason("FORECAST_REFRESH", True)           # 1.3.1: one heavy job at a time
    finally:
        stop.set()
        th.join(5)
        with runner._live_lock:
            runner._live.pop("JOB-TRAIN", None)


# ================================================================== child-process wrapper (tiny python -c children)
def _py(code):
    return [sys.executable, "-c", code]


def test_child_command_uses_this_interpreter_and_the_cli_module():
    assert sel2_jobs.child_command(["sel2-day", "--yes"]) == [sys.executable, "-m", "app.cli", "sel2-day", "--yes"]


def test_child_json_result_is_parsed_with_vietnamese_text_and_exit_code():
    code = ("import json,sys; print('note'); print(json.dumps({'ok': False, 'code': 'X', 'vi': 'Không chạy'}, "
            "indent=2, ensure_ascii=False)); sys.exit(1)")
    res = sel2_jobs.run_child(["x"], 30, cmd=_py(code))
    assert res["ok"] is False and res["code"] == "X" and res["vi"] == "Không chạy" and res["exit_code"] == 1


def test_child_without_json_is_a_retryable_failure():
    with pytest.raises(sel2_jobs.ChildError) as e:
        sel2_jobs.run_child(["x"], 30, cmd=_py("import sys; sys.stderr.write('Traceback boom'); sys.exit(3)"))
    assert e.value.code == "SEL2_CHILD_FAILED" and e.value.retryable and "boom" in e.value.detail


def test_child_timeout_kills_it():
    t = time.monotonic()
    with pytest.raises(sel2_jobs.ChildError) as e:
        sel2_jobs.run_child(["x"], 1, cmd=_py("import time; time.sleep(60)"))
    assert e.value.code == "SEL2_CHILD_TIMEOUT" and time.monotonic() - t < 30


def _alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


@pytest.mark.skipif(os.name != "nt", reason="process tree check uses tasklist")
def test_cancellation_kills_the_child_process_tree(tmp_path):
    pidfile = tmp_path / "pids.txt"
    code = ("import os, subprocess, sys, time\n"
            "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], stdout=subprocess.DEVNULL, "
            "stderr=subprocess.DEVNULL)\n"
            f"open({str(pidfile)!r}, 'w').write(f'{{os.getpid()}} {{g.pid}}')\n"
            "time.sleep(120)\n")
    flag = threading.Event()
    threading.Timer(1.5, lambda: flag.set() if pidfile.exists() else threading.Timer(1, flag.set).start()).start()
    t = time.monotonic()
    with pytest.raises(sel2_jobs.ChildError) as e:
        sel2_jobs.run_child(["x"], 300, cancel=flag.is_set, cmd=_py(code))
    assert e.value.code == "SEL2_CHILD_CANCELLED" and time.monotonic() - t < 60
    pids = [int(x) for x in Path(pidfile).read_text().split()]
    deadline = time.monotonic() + 10
    while any(_alive(p) for p in pids) and time.monotonic() < deadline:
        time.sleep(0.5)
    assert not any(_alive(p) for p in pids)
