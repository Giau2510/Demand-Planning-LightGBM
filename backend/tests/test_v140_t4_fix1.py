"""1.4.0 T4 fix 1 (review findings): CANDIDATE_TRAIN runs up to sel2_pipeline.train_timeout_seconds in the runner (not
schedule.timeout_seconds), model files named by training run under a per-scope folder, the cross-process training lock
(SEL2_TRAIN_BUSY), the Windows Job Object that ties the child to the server, interrupted RUNNING trainings closed,
unexpected CLI errors as JSON (SEL2_INTERNAL_ERROR / SEL2_LOW_MEMORY), the day run's memory gate, a purged day computed
again, sel2-replay refused on a database that is not a copy, the SEL2_PUBLISHED text.

Isolated databases (conftest), fake children / fake models, tiny `python -c` processes: unit tests and integration with
fakes."""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app import cli, db, messages, paths
from app import settings_service as ss
from app import timeutil
from app.jobs import resources, runner
from app.ml.sel2 import errors, pipeline, select, store
from app.ml.sel2 import jobs as sel2_jobs

from test_v131_refresh_jobs import _bq_scope
from test_v140_t4b_planning import MON, TUE

SCOPE = "BIGQUERY:test.sel2"


@pytest.fixture(autouse=True)
def _reset_child():
    yield
    sel2_jobs.set_child_runner(None)


@pytest.fixture
def bq(sel2_on):
    _bq_scope()


def _timeouts(monkeypatch, schedule_s: int, train_s: int):
    """schedule.timeout_seconds / sel2_pipeline.train_timeout_seconds below their validated minimum (test speed)."""
    real = ss.get

    def get(section, conn=None):
        v = real(section, conn)
        if section == "schedule":
            return v.model_copy(update={"timeout_seconds": schedule_s})
        if section == "sel2_pipeline":
            return v.model_copy(update={"train_timeout_seconds": train_s})
        return v
    monkeypatch.setattr(ss, "get", get)


def _lock_expiry_s(name="job:CANDIDATE_TRAIN"):
    with db.read() as c:
        r = c.execute("SELECT expires_at FROM job_locks WHERE lock_name=?", (name,)).fetchone()
    return (timeutil.parse_iso(r[0]) - timeutil.now_utc()).total_seconds() if r else None


# ================================================================== C1 runner timeout of CANDIDATE_TRAIN
def test_candidate_train_runs_past_the_schedule_timeout(bq, monkeypatch):
    _timeouts(monkeypatch, schedule_s=1, train_s=5)
    seen = {}

    def child(args, timeout, cancel):
        seen["timeout"], seen["ttl"] = timeout, _lock_expiry_s()
        end = time.monotonic() + 3                                    # longer than schedule.timeout_seconds
        while time.monotonic() < end:
            assert not cancel()
            time.sleep(0.1)
        return {"ok": True, "result": {"trained": list(sel2_jobs.TRAIN_MODELS), "skipped": []}}
    sel2_jobs.set_child_runner(child)
    row = runner.execute("CANDIDATE_TRAIN", f"CANDIDATE_TRAIN:{MON}:T1", "MANUAL", None, {"origin": str(MON)})
    assert row["status"] == "SUCCEEDED" and row["reason_code"] is None
    assert seen["timeout"] == 5
    assert seen["ttl"] > 5 + runner.SEL2_TRAIN_MARGIN + 100            # lock TTL from the training limit, not 1 + 120
    assert runner.job_timeout("CANDIDATE_TRAIN", ss.get("schedule")) == 5 + runner.SEL2_TRAIN_MARGIN
    for jt in ("FORECAST_REFRESH", "TRAIN_PUBLISH", "FORECAST_EXPORT", "D1_SYNC"):     # other types unchanged
        assert runner.job_timeout(jt, ss.get("schedule")) == 1


def test_candidate_train_is_stopped_past_the_training_timeout(bq, monkeypatch):
    _timeouts(monkeypatch, schedule_s=30, train_s=1)
    monkeypatch.setattr(runner, "SEL2_TRAIN_MARGIN", 0)
    seen = {"cancelled": False}

    def child(args, timeout, cancel):
        end = time.monotonic() + 10
        while time.monotonic() < end:
            if cancel():
                seen["cancelled"] = True
                raise sel2_jobs.ChildError(sel2_jobs.CHILD_CANCELLED, detail="killed")
            time.sleep(0.05)
        return {"ok": True, "result": {}}
    sel2_jobs.set_child_runner(child)
    t = time.monotonic()
    row = runner.execute("CANDIDATE_TRAIN", f"CANDIDATE_TRAIN:{MON}:T2", "MANUAL", None, {"origin": str(MON)})
    assert row["reason_code"] == "TIMEOUT" and "exceeded 1s" in row["error"]
    assert time.monotonic() - t < 8
    end = time.monotonic() + 10
    while not seen["cancelled"] and time.monotonic() < end:
        time.sleep(0.05)
    assert seen["cancelled"]                                          # the child was told to stop (tree killed)
    for th in threading.enumerate():                                  # the reaper releases the lock, then ends
        if th.name == f"reap-{row['id']}":
            th.join(15)
    assert _lock_expiry_s() is None


# ================================================================== S2 model files, training lock, Job Object
class _FakeBooster:
    def __init__(self, text):
        self.text = text

    def save_model(self, path):
        Path(path).write_text(self.text, encoding="utf-8")


def _info():
    return {"cfg": ss.ModelSettings(), "names": [], "sku_codes": [], "fc_codes": [], "decisions": {},
            "n_rows": 1, "n_series": 1, "n_features": 1}


def test_model_files_carry_the_run_id_under_the_scope_folder(sel2_on):
    origin = date(2026, 10, 26)
    a = store.start_train(SCOPE, "MOC", origin)
    b = store.start_train(SCOPE, "MOC", origin)
    fa = store.finish_train(a, "MOC", origin, {"model": _FakeBooster("A")}, _info(), "2026-10-25", 1.0)
    fb = store.finish_train(b, "MOC", origin, {"model": _FakeBooster("B")}, _info(), "2026-10-25", 1.0)
    pa, pb = paths.models_dir() / fa["model"]["path"], paths.models_dir() / fb["model"]["path"]
    assert pa != pb and pa.read_text() == "A" and pb.read_text() == "B"           # nothing overwritten
    assert pa.name == f"MOC_{a}.txt" and pa.parent == store.model_dir(origin, SCOPE)
    two = store.start_train(SCOPE, "V36_two_stage", origin)
    ft = store.finish_train(two, "V36_two_stage", origin, {"clf": _FakeBooster("c"), "reg": _FakeBooster("r")},
                            _info(), "2026-10-25", 1.0)
    assert {k: (paths.models_dir() / v["path"]).name for k, v in ft.items()} == \
        {"clf": f"V36_two_stage_clf_{two}.txt", "reg": f"V36_two_stage_reg_{two}.txt"}
    with db.read() as c:
        run = db.one(c, "SELECT * FROM candidate_train_runs WHERE id=?", (a,))
    pa.write_text("changed", encoding="utf-8")
    with pytest.raises(errors.Sel2Error) as e:
        store.load_train(run)                                         # recorded path + sha256 verified
    assert e.value.code == "SEL2_MODEL_FILE_MISMATCH"


def test_model_dir_is_keyed_by_scope():
    o = date(2026, 10, 26)
    a, b = store.model_dir(o, SCOPE), store.model_dir(o, "MANUAL_IMPORT:batch-1")
    assert a != b and a.name == b.name == str(o)
    assert a.parent.parent == paths.models_dir() / "sel2" and len(a.parent.name) == 12
    assert ":" not in a.parent.name


def test_training_lock_refuses_a_second_training_of_the_scope(sel2_on, monkeypatch):
    called = []
    monkeypatch.setattr(pipeline, "_train_week", lambda *a: called.append(a) or {"trained": []})
    with pipeline.train_lock(SCOPE):
        with pytest.raises(errors.Sel2Error) as e:
            pipeline.train_week(date(2026, 10, 26), scope_key=SCOPE)
        assert e.value.code == "SEL2_TRAIN_BUSY" and e.value.retryable
        pipeline.train_week(date(2026, 10, 26), scope_key="OTHER:scope")     # another scope is not blocked
    assert len(called) == 1
    pipeline.train_week(date(2026, 10, 26), scope_key=SCOPE)                  # released after the block
    assert len(called) == 2


def test_training_lock_is_held_across_processes(sel2_on, monkeypatch):
    lock = store.scope_dir(SCOPE) / "train.lock"
    code = ("import msvcrt, sys, time\n"
            "f = open(sys.argv[1], 'a+b'); f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)\n"
            "print('locked', flush=True); time.sleep(30)\n") if os.name == "nt" else \
           ("import fcntl, sys, time\n"
            "f = open(sys.argv[1], 'a+b'); fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "print('locked', flush=True); time.sleep(30)\n")
    lock.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen([sys.executable, "-c", code, str(lock)], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "locked"
        with pytest.raises(errors.Sel2Error) as e:
            with pipeline.train_lock(SCOPE):
                pass
        assert e.value.code == "SEL2_TRAIN_BUSY"
    finally:
        p.kill()
        p.wait(10)
    with pipeline.train_lock(SCOPE):                                  # the OS released it with the process
        pass


@pytest.mark.parametrize("code,status,retry", [("SEL2_TRAIN_BUSY", "RETRY_WAIT", True),
                                               ("SEL2_INTERNAL_ERROR", "FAILED", False),
                                               ("SEL2_LOW_MEMORY", "RETRY_WAIT", True)])
def test_train_job_maps_busy_internal_and_memory(bq, code, status, retry):
    sel2_jobs.set_child_runner(lambda args, timeout, cancel: {"ok": False, "code": code, "detail": "x"})
    with pytest.raises(sel2_jobs.ChildError) as e:
        sel2_jobs.train(None, {"origin": str(MON)}, trigger="SCHEDULE")
    assert e.value.code == code and e.value.retryable is retry
    row = runner.execute("CANDIDATE_TRAIN", f"CANDIDATE_TRAIN:{MON}:{code}", "SCHEDULE", None, {"origin": str(MON)})
    assert row["status"] == status and row["reason_code"] == code


def test_refresh_job_internal_error_is_failed_not_retried(bq, monkeypatch):
    monkeypatch.setattr(sel2_jobs, "avg_read", lambda d: {"status": "ALREADY_READ"})
    sel2_jobs.set_child_runner(lambda args, timeout, cancel: {"ok": False, "code": "SEL2_INTERNAL_ERROR",
                                                              "detail": "RuntimeError: boom"})
    r = sel2_jobs.refresh(None, {"business_date": "2026-10-01"})
    assert r["status"] == "FAILED" and r["reason_code"] == "SEL2_INTERNAL_ERROR"
    sel2_jobs.set_child_runner(lambda args, timeout, cancel: {"ok": False, "code": "SEL2_LOW_MEMORY"})
    with pytest.raises(sel2_jobs.ChildError) as e:
        sel2_jobs.refresh(None, {"business_date": "2026-10-01"})
    assert e.value.retryable


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object")
def test_job_object_kills_the_child_when_its_handle_closes():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        job = sel2_jobs._kill_on_close_job(p)
        assert job is not None
        assert p.poll() is None
        sel2_jobs._close_job(job)                                     # = the server process ending
        p.wait(15)
        assert p.returncode is not None
    finally:
        if p.poll() is None:
            p.kill()


def test_run_child_still_returns_the_json_with_the_job_object():
    res = sel2_jobs.run_child(["x"], 30, cmd=[sys.executable, "-c", "print('{\"ok\": true, \"result\": 1}')"])
    assert res["ok"] is True and res["result"] == 1 and res["exit_code"] == 0


# ================================================================== S3 interrupted RUNNING trainings
def _running(scope, created_at, pid=None):
    rid = db.new_id("CTR")
    with db.tx() as c:
        c.execute("INSERT INTO candidate_train_runs(id, scope_key, model, origin_date, status, created_at, detail_json) "
                  "VALUES (?, ?, 'MOC', '2026-10-26', 'RUNNING', ?, ?)",
                  (rid, scope, created_at, json.dumps({"pid": pid}) if pid is not None else None))
    return rid


def test_start_train_closes_interrupted_running_trainings(sel2_on):
    now = timeutil.now_utc()
    old = _running(SCOPE, (now - timedelta(seconds=10800 + 601)).isoformat())
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(30)
    gone = _running(SCOPE, now.isoformat(), pid=dead.pid)
    mine = _running(SCOPE, now.isoformat(), pid=os.getpid())
    recent = _running(SCOPE, (now - timedelta(seconds=10800)).isoformat())
    other = _running("OTHER:scope", (now - timedelta(days=2)).isoformat())
    rid = store.start_train(SCOPE, "MOC", date(2026, 10, 26))
    with db.read() as c:
        st = {r["id"]: (r["status"], json.loads(r["detail_json"] or "{}")) for r in
              db.rows(c, "SELECT id, status, detail_json FROM candidate_train_runs")}
    assert st[old][0] == "FAILED" and st[old][1]["error"] == "INTERRUPTED" and st[old][1]["reason"] == "AGE"
    assert st[gone][0] == "FAILED" and st[gone][1]["reason"] == "PROCESS_GONE"
    assert st[mine][0] == st[recent][0] == st[other][0] == "RUNNING"
    assert st[rid] == ("RUNNING", {"pid": os.getpid()})


# ================================================================== S4 unexpected CLI errors
def test_cli_unexpected_errors_are_json(sel2_on, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(pipeline, "run_day", boom)
    assert cli.main(["sel2-day", "--date", str(TUE), "--yes"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["code"] == "SEL2_INTERNAL_ERROR" and "RuntimeError: boom" in out["detail"]
    assert out["vi"] != "SEL2_INTERNAL_ERROR" and out["en"] != "SEL2_INTERNAL_ERROR"

    def oom(*a, **k):
        raise MemoryError()
    monkeypatch.setattr(pipeline, "train_week", oom)
    assert cli.main(["sel2-train", "--origin", str(MON), "--yes"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "SEL2_LOW_MEMORY"
    from app.ml.sel2 import export
    monkeypatch.setattr(export, "write_daily_export", boom)
    assert cli.main(["sel2-export", "--date", str(TUE), "--yes"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "SEL2_INTERNAL_ERROR"


def test_cli_py_keeps_crlf():
    b = Path(cli.__file__).read_bytes()
    assert b.count(b"\n") == b.count(b"\r\n")


# ================================================================== S5 memory gate of the day run
def test_day_run_needs_free_commit(sel2_on, monkeypatch):
    monkeypatch.setattr(resources, "snapshot", lambda: {"commit_avail": 1000 * resources.MB})
    with pytest.raises(errors.Sel2Error) as e:
        pipeline.run_day(date(2026, 11, 1), scope_key=SCOPE)
    assert e.value.code == "SEL2_LOW_MEMORY" and e.value.retryable and "1500" in e.value.detail
    monkeypatch.setattr(resources, "snapshot", lambda: {"commit_avail": 1600 * resources.MB})

    class Reached(Exception):
        pass
    monkeypatch.setattr(pipeline, "load", lambda *a, **k: (_ for _ in ()).throw(Reached()))
    with pytest.raises(Reached):
        pipeline.run_day(date(2026, 11, 1), scope_key=SCOPE)
    assert pipeline.DAY_MIN_COMMIT_MB == 1500 and pipeline.MIN_COMMIT_MB == 3072


# ================================================================== G6 text of SEL2_PUBLISHED (and the new codes)
@pytest.mark.parametrize("code", ["SEL2_PUBLISHED", "SEL2_TRAIN_BUSY", "SEL2_INTERNAL_ERROR", "SEL2_REPLAY_NOT_A_COPY"])
def test_new_codes_have_bilingual_texts(code):
    m = messages.msg(code)
    assert m["vi"] != code and m["en"] != code and m["vi"] != m["en"]


# ================================================================== G7 purged day computed again
def _cands(keys, models=select.CANDIDATES):
    return {m: pd.DataFrame({"sku_code": np.repeat([k[0] for k in keys], 7), "fc_code": np.repeat([k[1] for k in keys], 7),
                             "horizon": np.tile(np.arange(1, 8), len(keys)), "value": 1.0 + i})
            for i, m in enumerate(models)}


def test_purged_day_is_not_complete(sel2_on):
    d = date(2026, 6, 1)
    keys = [("S01", "FC1")]
    store.write_day(SCOPE, d, d - timedelta(days=1), _cands(keys), {}, {})
    with db.read() as c:
        assert store.day_complete(c, SCOPE, d, select.CANDIDATES)
    r = store.apply_retention(d + timedelta(days=121), 120)
    assert r["rows"] == 7 * 6
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM candidate_runs WHERE forecast_date=?", (str(d),)).fetchone()[0] == 6
        assert not store.day_complete(c, SCOPE, d, select.CANDIDATES)     # recomputed, never selected on empty rows
    store.write_day(SCOPE, d, d - timedelta(days=1), _cands(keys), {}, {})
    with db.read() as c:
        assert store.day_complete(c, SCOPE, d, select.CANDIDATES)


# ================================================================== G8 sel2-replay on a copy only
def test_replay_is_refused_without_a_copy_marker_or_flag(sel2_on, monkeypatch, capsys, tmp_path):
    calls = []
    monkeypatch.setattr(pipeline, "replay", lambda *a, **k: calls.append(a) or {"ok": 1})
    base = ["sel2-replay", "--from", "2026-10-01", "--to", "2026-10-02", "--out", str(tmp_path / "o")]
    assert cli.main(base + ["--yes"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["code"] == "SEL2_REPLAY_NOT_A_COPY" and not calls and out["copy_check"]["marker_found"] is False
    assert cli.main(base) == 0                                         # plan only, nothing run
    assert json.loads(capsys.readouterr().out)["copy_check"]["copy_ok_flag"] is False and not calls
    assert cli.main(base + ["--yes", "--copy-ok"]) == 0 and len(calls) == 1
    capsys.readouterr()
    marker = paths.db_path().parent / "copy_info.json"
    assert str(marker).startswith(str(tmp_path))                       # the isolated test database only
    marker.write_text("{}", encoding="utf-8")
    assert cli.main(base + ["--yes"]) == 0 and len(calls) == 2
