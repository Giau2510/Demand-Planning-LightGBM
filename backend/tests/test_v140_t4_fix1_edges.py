"""1.4.0 T4 fix 1, edge cases next to test_v140_t4_fix1.py: the runner time limit of every job type with the emergency
switch on and off, the memory gates read through a fake probe (training 3072 MB, day run 1500 MB; exact threshold,
unknown reading, day run with given inputs), interrupted trainings never closed in another scope or while the recorded
process lives, two trainings of one origin (distinct files, newest SUCCEEDED run loaded and its sha256 checked, newest
first ties by rowid), a purged day computed again by candidates_for_day (retention boundary), SEL2_INTERNAL_ERROR ->
FAILED (never RETRY_WAIT) through the runner, and the sel2-replay plan with --copy-ok.

Isolated databases (conftest), fake children, fake memory probe, tiny LightGBM boosters on synthetic numbers: unit tests
and integration with fakes."""
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from app import cli, db, paths
from app import settings_service as ss
from app import timeutil
from app.jobs import resources, runner
from app.ml.sel2 import errors, pipeline, select, store
from app.ml.sel2 import jobs as sel2_jobs

from test_v131_refresh import _no_real_bigquery  # noqa: F401 (autouse fixture)
from test_v131_refresh_jobs import _bq_scope
from test_v140_t4b_jobs import _child, _refresh, env  # noqa: F401 (fixture)
from test_v140_t4b_planning import MON

SCOPE = "BIGQUERY:test.sel2"


@pytest.fixture(autouse=True)
def _reset_child():
    yield
    sel2_jobs.set_child_runner(None)


class Reached(Exception):
    pass


def _reach(*a, **k):
    raise Reached()


def _probe(monkeypatch, mb):
    """Fake memory probe: free commit `mb` MB (None = not readable on this platform)."""
    monkeypatch.setattr(resources, "snapshot",
                        lambda: {"commit_avail": None if mb is None else int(mb * resources.MB), "phys_avail": None})


# ================================================================== C1 job_timeout of every job type
@pytest.mark.parametrize("enabled", [False, True])
def test_job_timeout_of_every_type_only_candidate_train_differs(enabled):
    ss.update("schedule", {"timeout_seconds": 1800}, note="tests")
    ss.update("sel2_pipeline", {"enabled": enabled, "train_timeout_seconds": 7200}, note="tests")
    sched = ss.get("schedule")
    got = {jt: runner.job_timeout(jt, sched) for jt in runner.JOB_TYPES}
    assert runner.SEL2_TRAIN_MARGIN == 120
    assert got == {jt: (7200 + 120 if jt == "CANDIDATE_TRAIN" else 1800) for jt in runner.JOB_TYPES}
    assert set(runner.JOB_TYPES) >= {"CANDIDATE_TRAIN", "FORECAST_EXPORT", "FORECAST_REFRESH", "TRAIN_PUBLISH"}


def test_job_timeout_follows_the_saved_settings():
    ss.update("sel2_pipeline", {"train_timeout_seconds": 600}, note="tests")             # validated minimum
    ss.update("schedule", {"timeout_seconds": 30}, note="tests")
    assert runner.job_timeout("CANDIDATE_TRAIN", ss.get("schedule")) == 720
    assert runner.job_timeout("FORECAST_EXPORT", ss.get("schedule")) == 30              # the other SEL2 type unchanged
    ss.update("sel2_pipeline", {"train_timeout_seconds": 43200}, note="tests")           # validated maximum
    assert runner.job_timeout("CANDIDATE_TRAIN", ss.get("schedule")) == 43320


def test_candidate_train_with_the_switch_off_spawns_no_child():
    _bq_scope()
    calls = []
    _child(calls, {"ok": True, "result": {"trained": [], "skipped": []}})
    row = runner.execute("CANDIDATE_TRAIN", f"CANDIDATE_TRAIN:{MON}:OFF", "MANUAL", None, {"origin": str(MON)})
    assert row["status"] == "SKIPPED" and row["reason_code"] == "SEL2_DISABLED" and calls == []


# ================================================================== S5 memory gates with a fake probe
def test_training_gate_below_at_and_without_a_reading(sel2_on, monkeypatch):
    monkeypatch.setattr(pipeline, "load", _reach)
    _probe(monkeypatch, 3071)
    with pytest.raises(errors.Sel2Error) as e:
        pipeline.train_week(MON, scope_key=SCOPE)
    assert e.value.code == "SEL2_LOW_MEMORY" and e.value.retryable and "3072" in e.value.detail
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM candidate_train_runs").fetchone()[0] == 0     # no record started
    with pipeline.train_lock(SCOPE):                                  # the lock was released after the refusal
        pass
    for mb in (3072, None):                                           # exact threshold passes; no reading = not gated
        _probe(monkeypatch, mb)
        with pytest.raises(Reached):
            pipeline.train_week(MON, scope_key=SCOPE)


def test_day_gate_threshold_and_given_inputs(sel2_on, monkeypatch):
    monkeypatch.setattr(pipeline, "load", _reach)
    d = date(2026, 11, 1)
    _probe(monkeypatch, 1499.9)
    with pytest.raises(errors.Sel2Error) as e:
        pipeline.run_day(d, scope_key=SCOPE)
    assert e.value.code == "SEL2_LOW_MEMORY" and "1500" in e.value.detail
    for mb in (1500, None):
        _probe(monkeypatch, mb)
        with pytest.raises(Reached):
            pipeline.run_day(d, scope_key=SCOPE)
    _probe(monkeypatch, 10)                                           # bootstrap path: inputs already loaded
    monkeypatch.setattr(pipeline, "candidates_for_day", _reach)
    with pytest.raises(Reached):
        pipeline.run_day(d, scope_key=SCOPE, inputs=object())


def test_day_gate_is_not_reached_when_switch_off_or_already_published(sel2_on, monkeypatch):
    _probe(monkeypatch, 1)
    monkeypatch.setattr(store, "published_run", lambda c, s, d: {"id": "FRR-X"})
    r = pipeline.run_day(date(2026, 11, 1), scope_key=SCOPE)
    assert r == {"status": "ALREADY_PUBLISHED", "forecast_date": "2026-11-01", "run_id": "FRR-X"}
    ss.update("sel2_pipeline", {"enabled": False}, note="tests")
    assert pipeline.run_day(date(2026, 11, 1), scope_key=SCOPE)["reason_code"] == "SEL2_DISABLED"


# ================================================================== S3 mark_interrupted boundaries
def _running(scope, created_at, detail):
    rid = db.new_id("CTR")
    with db.tx() as c:
        c.execute("INSERT INTO candidate_train_runs(id, scope_key, model, origin_date, status, created_at, detail_json) "
                  "VALUES (?, ?, 'MOC', '2026-10-26', 'RUNNING', ?, ?)", (rid, scope, created_at, detail))
    return rid


def test_mark_interrupted_keeps_other_scopes_and_live_processes(sel2_on):
    limit = ss.get("sel2_pipeline").train_timeout_seconds + store.STALE_TRAIN_MARGIN_S
    now = timeutil.now_utc()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(30)
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert store.pid_alive(live.pid) and not store.pid_alive(dead.pid)
        other_old = _running("OTHER:scope", (now - timedelta(seconds=limit + 3600)).isoformat(), None)
        other_gone = _running("OTHER:scope", now.isoformat(), json.dumps({"pid": dead.pid}))
        alive = _running(SCOPE, now.isoformat(), json.dumps({"pid": live.pid}))
        alive_old = _running(SCOPE, (now - timedelta(seconds=limit + 60)).isoformat(), json.dumps({"pid": live.pid}))
        bad_json = _running(SCOPE, now.isoformat(), "{not json")
        no_pid = _running(SCOPE, (now - timedelta(seconds=limit - 60)).isoformat(), json.dumps({}))
        done = store.mark_interrupted(SCOPE)
        assert done == [alive_old]                                    # a live process still ends by age
        with db.read() as c:
            st = {r["id"]: r for r in db.rows(c, "SELECT id, status, detail_json, finished_at FROM candidate_train_runs")}
        for rid in (other_old, other_gone, alive, bad_json, no_pid):
            assert st[rid]["status"] == "RUNNING" and st[rid]["finished_at"] is None
        assert json.loads(st[alive_old]["detail_json"]) == {"error": "INTERRUPTED", "pid": live.pid, "reason": "AGE"}
        assert st[bad_json]["detail_json"] == "{not json"            # unreadable detail left as it was
        assert set(store.mark_interrupted("OTHER:scope")) == {other_old, other_gone}     # closed in their own scope
        assert store.mark_interrupted(SCOPE) == []                   # idempotent
    finally:
        live.kill()
        live.wait(10)


def test_mark_interrupted_never_touches_finished_rows(sel2_on):
    old = (timeutil.now_utc() - timedelta(days=3)).isoformat()
    with db.tx() as c:
        for st in ("SUCCEEDED", "FAILED"):
            c.execute("INSERT INTO candidate_train_runs(id, scope_key, model, origin_date, status, created_at, "
                      "detail_json) VALUES (?, ?, 'MOC', '2026-10-26', ?, ?, '{}')", (db.new_id("CTR"), SCOPE, st, old))
    assert store.mark_interrupted(SCOPE) == []
    with db.read() as c:
        assert sorted(r[0] for r in c.execute("SELECT status FROM candidate_train_runs")) == ["FAILED", "SUCCEEDED"]


# ================================================================== S2 two trainings of one origin, real boosters
X = np.arange(40, dtype=float).reshape(-1, 1)


def _booster(y):
    return lgb.train({"objective": "regression", "verbose": -1, "min_data_in_leaf": 1, "num_threads": 1,
                      "deterministic": True}, lgb.Dataset(X, y), num_boost_round=3)


def _info():
    return {"cfg": ss.ModelSettings(), "names": ["x"], "sku_codes": [], "fc_codes": [], "decisions": {},
            "n_rows": 40, "n_series": 1, "n_features": 1}


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_newest_succeeded_training_of_an_origin_is_loaded_with_its_hash(sel2_on):
    origin = date(2026, 10, 26)
    ba, bb = _booster(X[:, 0]), _booster(100.0 - X[:, 0])
    a = store.start_train(SCOPE, "MOC", origin)
    fa = store.finish_train(a, "MOC", origin, {"model": ba}, _info(), "2026-10-25", 1.0)
    b = store.start_train(SCOPE, "MOC", origin)
    fb = store.finish_train(b, "MOC", origin, {"model": bb}, _info(), "2026-10-25", 1.0)
    pa, pb = paths.models_dir() / fa["model"]["path"], paths.models_dir() / fb["model"]["path"]
    assert pa != pb and pa.exists() and pb.exists() and pa.parent == pb.parent == store.model_dir(origin, SCOPE)
    assert fa["model"]["sha256"] == _sha(pa) and fb["model"]["sha256"] == _sha(pb) and _sha(pa) != _sha(pb)
    assert not list(pa.parent.glob("*.tmp"))
    later = store.start_train(SCOPE, "MOC", origin)                   # a newer failed and a newer running record
    store.fail_train(later, RuntimeError("boom"))
    store.start_train(SCOPE, "MOC", origin)
    with db.read() as c:
        run = store.succeeded_train(c, SCOPE, "MOC", origin)
        run_a = db.one(c, "SELECT * FROM candidate_train_runs WHERE id=?", (a,))
        assert store.succeeded_train(c, "OTHER:scope", "MOC", origin) is None
        assert store.succeeded_train(c, SCOPE, "MOC", origin - timedelta(days=7)) is None
    assert run["id"] == b
    models, trained = store.load_train(run)
    np.testing.assert_allclose(models["model"].predict(X), bb.predict(X))
    old_models, _ = store.load_train(run_a)                           # the older file was not overwritten
    np.testing.assert_allclose(old_models["model"].predict(X), ba.predict(X))
    assert trained["names"] == ["x"]
    # newest first with equal timestamps (one-second resolution): rowid decides
    with db.tx() as c:
        c.execute("UPDATE candidate_train_runs SET created_at='2026-10-26T00:00:00+00:00' WHERE id IN (?, ?)", (a, b))
    with db.read() as c:
        assert store.succeeded_train(c, SCOPE, "MOC", origin)["id"] == b
    with db.tx() as c:
        c.execute("UPDATE candidate_train_runs SET created_at='2026-10-26T00:00:01+00:00' WHERE id=?", (a,))
    with db.read() as c:
        assert store.succeeded_train(c, SCOPE, "MOC", origin)["id"] == a


def test_missing_model_file_is_a_mismatch(sel2_on):
    origin = date(2026, 10, 26)
    a = store.start_train(SCOPE, "MOC", origin)
    f = store.finish_train(a, "MOC", origin, {"model": _booster(X[:, 0])}, _info(), "2026-10-25", 1.0)
    (paths.models_dir() / f["model"]["path"]).unlink()
    with db.read() as c:
        run = store.succeeded_train(c, SCOPE, "MOC", origin)
    with pytest.raises(errors.Sel2Error) as e:
        store.load_train(run)
    assert e.value.code == "SEL2_MODEL_FILE_MISMATCH"


# ================================================================== G7 purged day computed again by candidates_for_day
def _cands(keys, models=select.CANDIDATES):
    return {m: pd.DataFrame({"sku_code": np.repeat([k[0] for k in keys], 7), "fc_code": np.repeat([k[1] for k in keys], 7),
                             "horizon": np.tile(np.arange(1, 8), len(keys)), "value": 1.0 + i})
            for i, m in enumerate(models)}


def test_candidates_for_day_recomputes_a_purged_day(sel2_on, monkeypatch):
    monkeypatch.setattr(pipeline, "load", _reach)                     # reached only when the day is computed again
    d = date(2026, 6, 1)
    store.write_day(SCOPE, d, d - timedelta(days=1), _cands([("S01", "FC1"), ("S02", "FC2")]), {}, {})
    assert pipeline.candidates_for_day(d, scope_key=SCOPE) == {"forecast_date": str(d), "status": "SKIPPED_DONE"}
    r = store.apply_retention(d + timedelta(days=120), 120)           # cutoff = d: the day itself is kept
    assert r == {"cutoff": str(d), "days": 0, "rows": 0}
    assert pipeline.candidates_for_day(d, scope_key=SCOPE)["status"] == "SKIPPED_DONE"
    r = store.apply_retention(d + timedelta(days=121), 120)
    assert r["days"] == 1 and r["rows"] == 2 * 7 * len(select.CANDIDATES)
    with pytest.raises(Reached):
        pipeline.candidates_for_day(d, scope_key=SCOPE)
    with db.read() as c:                                              # run records kept, rows gone
        assert c.execute("SELECT COUNT(*) FROM candidate_runs WHERE forecast_date=?", (str(d),)).fetchone()[0] == \
            len(select.CANDIDATES)
        assert store.read_day(c, SCOPE, d) == {} or all(f.empty for f in store.read_day(c, SCOPE, d).values())


def test_day_with_one_model_purged_is_not_complete(sel2_on, monkeypatch):
    monkeypatch.setattr(pipeline, "load", _reach)
    d = date(2026, 6, 2)
    store.write_day(SCOPE, d, d - timedelta(days=1), _cands([("S01", "FC1")]), {}, {})
    with db.tx() as c:
        c.execute("DELETE FROM candidate_forecasts WHERE forecast_date=? AND model=?", (str(d), select.CANDIDATES[0]))
    with db.read() as c:
        assert not store.day_complete(c, SCOPE, d, select.CANDIDATES)
        assert not store.day_complete(c, "OTHER:scope", d, select.CANDIDATES)
    with pytest.raises(Reached):
        pipeline.candidates_for_day(d, scope_key=SCOPE)


# ================================================================== S4 SEL2_INTERNAL_ERROR through the runner
def test_refresh_internal_error_row_is_failed_without_retry(env):
    calls = []
    _child(calls, {"ok": False, "code": "SEL2_INTERNAL_ERROR", "detail": "RuntimeError: boom"})
    row = _refresh(key="FORECAST_REFRESH:2026-11-03:INT")
    assert row["status"] == "FAILED" and row["reason_code"] == "SEL2_INTERNAL_ERROR"
    assert row["next_attempt_at"] is None and len(calls) == 1


@pytest.mark.parametrize("trigger", ["SCHEDULE", "MANUAL"])
def test_train_internal_error_row_is_failed_without_retry(sel2_on, trigger):
    _bq_scope()
    calls = []
    _child(calls, {"ok": False, "code": "SEL2_INTERNAL_ERROR", "detail": "RuntimeError: boom"})
    row = runner.execute("CANDIDATE_TRAIN", f"CANDIDATE_TRAIN:{MON}:INT:{trigger}", trigger, None, {"origin": str(MON)})
    assert row["status"] == "FAILED" and row["reason_code"] == "SEL2_INTERNAL_ERROR"
    assert row["next_attempt_at"] is None and len(calls) == 1


# ================================================================== G8 sel2-replay plan with --copy-ok
def test_replay_dry_run_with_copy_ok_shows_the_check_and_runs_nothing(sel2_on, monkeypatch, capsys, data_dir):
    calls = []
    monkeypatch.setattr(pipeline, "replay", lambda *a, **k: calls.append(a) or {"ok": 1})
    marker = paths.db_path().parent / "copy_info.json"
    assert str(marker).startswith(str(data_dir)) and not marker.exists()          # isolated test DB, no marker
    base = ["sel2-replay", "--from", "2026-10-01", "--to", "2026-10-02", "--out", str(data_dir / "o")]
    assert cli.main(base + ["--copy-ok"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["code"] == "SEL2_CONFIRM_REQUIRED" and not calls
    assert out["copy_check"] == {"copy_info": str(marker), "marker_found": False, "copy_ok_flag": True}
    assert cli.main(base + ["--yes"]) == 2                            # without --copy-ok on a DB lacking the marker
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["code"] == "SEL2_REPLAY_NOT_A_COPY" and not calls
    assert out["copy_check"]["marker_found"] is False and out["copy_check"]["copy_ok_flag"] is False
    # a copy_info.json elsewhere (not next to app.db) does not count
    (paths.db_path().parent.parent / "copy_info.json").write_text("{}", encoding="utf-8")
    assert cli.main(base + ["--yes"]) == 2 and not calls
    capsys.readouterr()
    assert not (data_dir / "o").exists()
