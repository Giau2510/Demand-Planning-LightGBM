"""1.4.0 T4b tests: scheduler planning of the SEL2 pipeline (jobs/scheduler.py) - daily refresh after D-1, Monday
CANDIDATE_TRAIN with the prev_week_deadline wait and the forced re-run, stale export at export_deadline, AVG_DEMAND
re-export (off by default) and the emergency switch (sel2_pipeline.enabled False = 1.3.1 plans).

Isolated databases (conftest), fixed Vietnam times (timeutil.set_now_override), rows inserted directly: unit tests."""
import json
from datetime import datetime

import pytest

from app import db
from app import settings_service as ss
from app import timeutil
from app.jobs import runner
from app.timeutil import VN_TZ

from test_v131_refresh import BQ_SCOPE, _d1_ok, _enable, _freeze, _no_real_bigquery  # noqa: F401 (autouse fixture)
from test_v131_refresh_jobs import _bq_scope, _of, _plan, _sched

MON = datetime(2026, 11, 2, 5, 10, tzinfo=VN_TZ).date()     # ISO weekday 1 (retraining day)
TUE = datetime(2026, 11, 3, 5, 10, tzinfo=VN_TZ).date()


def _at(d, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=VN_TZ)


def _sel2_run(d, flags=(), rid=None):
    rid = rid or db.new_id("FRR")
    with db.tx() as c:
        c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, config_version, "
                  "trial_mode, horizon, n_series, n_lightgbm, n_fallback, created_at, detail_json) VALUES (?, ?, ?, ?, "
                  "'PUBLISHED', 'SEL2:abc', 1, 7, 1, 1, 0, ?, ?)",
                  (rid, BQ_SCOPE, str(d), str(d), timeutil.now_iso(), json.dumps({"flags": list(flags)})))
    return rid


def _export(d, version=1, source_modified=None):
    with db.tx() as c:
        c.execute("INSERT INTO export_runs(id, forecast_date, version, path, is_stale, created_at, summary_json) "
                  "VALUES (?, ?, ?, ?, 0, ?, ?)", (db.new_id("EXP"), str(d), version, f"x/v{version}.xlsx",
                                                   timeutil.now_iso(),
                                                   json.dumps({"avg": {"source_modified": source_modified}})))


def _job(job_type, key, status):
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, "
                  "created_at) VALUES (?, ?, ?, 'SCHEDULE', ?, 1, 4, ?)",
                  (db.new_id("JOB"), job_type, key, status, timeutil.now_iso()))


def _set_job(key, status):
    with db.tx() as c:
        c.execute("UPDATE job_runs SET status=? WHERE idempotency_key=?", (status, key))


def _plan_at(d, hhmm, sched=None):
    t = _at(d, hhmm)
    _freeze(t)
    return _plan(t, sched or _sched(refresh_enabled=True))


@pytest.fixture
def bq(sel2_on):
    _bq_scope()


# ================================================================== normal day
def test_normal_day_refresh_runs_after_d1_without_daily_forecast_switch_and_train_publish_is_skipped(bq):
    _freeze(_at(TUE, "05:05"))
    assert _of(_plan_at(TUE, "05:05")) == []                       # no D-1 yet: waits
    _d1_ok(day=TUE)
    acts = _plan_at(TUE, "05:10")
    [r] = _of(acts)
    assert r["action"] == "run" and r["key"] == f"FORECAST_REFRESH:{TUE}:05:10"
    assert r["params"] == {"business_date": str(TUE)}
    assert _of(acts, "CANDIDATE_TRAIN") == []                      # not the retraining weekday
    [t] = _of(_plan_at(TUE, "05:30"), "TRAIN_PUBLISH")
    assert t["action"] == "skip" and t["reason"] == "SEL2_PIPELINE_ACTIVE" and t["key"] == f"TRAIN_PUBLISH:{TUE}"


def test_published_sel2_run_stops_the_refresh_but_a_131_run_does_not(bq):
    _freeze(_at(TUE, "05:10"))
    _d1_ok(day=TUE)
    with db.tx() as c:                                              # a 1.3.1 run of the day is not a SEL2 publication
        c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, config_version, "
                  "trial_mode, horizon, n_series, n_lightgbm, n_fallback, created_at) VALUES ('FRR-OLD', ?, ?, ?, "
                  "'PUBLISHED', 'cv', 1, 7, 1, 1, 0, ?)", (BQ_SCOPE, str(TUE), str(TUE), timeutil.now_iso()))
    assert len(_of(_plan_at(TUE, "05:10"))) == 1
    _sel2_run(TUE)
    assert _of(_plan_at(TUE, "05:40")) == []


# ================================================================== Monday
def test_monday_training_first_refresh_waits_until_prev_week_deadline_then_one_forced_rerun(bq):
    _freeze(_at(MON, "05:10"))
    _d1_ok(day=MON)
    acts = _plan_at(MON, "05:10")
    [t] = _of(acts, "CANDIDATE_TRAIN")
    assert t["key"] == f"CANDIDATE_TRAIN:{MON}" and t["params"] == {"origin": str(MON)}
    assert _of(acts) == []                                          # planned in the same tick: refresh waits
    _job("CANDIDATE_TRAIN", f"CANDIDATE_TRAIN:{MON}", "RUNNING")
    assert _of(_plan_at(MON, "06:19")) == [] and _of(_plan_at(MON, "06:19"), "CANDIDATE_TRAIN") == []
    [r] = _of(_plan_at(MON, "06:20"))                               # prev_week_deadline: runs with last week's models
    assert r["key"] == f"FORECAST_REFRESH:{MON}:06:20" and "force" not in r["params"]
    _job("FORECAST_REFRESH", r["key"], "SUCCEEDED")
    _sel2_run(MON, flags=["MODEL_PREV_WEEK"])
    assert _of(_plan_at(MON, "07:00")) == []                        # training still running: no re-run yet
    _set_job(f"CANDIDATE_TRAIN:{MON}", "SUCCEEDED")
    [rr] = _of(_plan_at(MON, "07:30"))
    assert rr["key"] == f"FORECAST_REFRESH:{MON}:RERUN" and rr["params"] == {"business_date": str(MON), "force": True}
    _job("FORECAST_REFRESH", rr["key"], "SUCCEEDED")
    assert _of(_plan_at(MON, "07:40")) == []                        # once


def test_monday_no_rerun_when_the_run_used_this_weeks_models(bq):
    _freeze(_at(MON, "05:10"))
    _d1_ok(day=MON)
    _job("CANDIDATE_TRAIN", f"CANDIDATE_TRAIN:{MON}", "SUCCEEDED")
    [r] = _of(_plan_at(MON, "05:50"))                               # training done before 06:20: no wait
    assert r["action"] == "run"
    _job("FORECAST_REFRESH", r["key"], "SUCCEEDED")
    _sel2_run(MON, flags=[])
    assert _of(_plan_at(MON, "06:30")) == []


def test_monday_failed_training_does_not_hold_the_refresh_and_training_switch_off_plans_none(bq):
    _freeze(_at(MON, "05:10"))
    _d1_ok(day=MON)
    _job("CANDIDATE_TRAIN", f"CANDIDATE_TRAIN:{MON}", "FAILED")
    assert len(_of(_plan_at(MON, "05:30"))) == 1
    acts = _plan_at(MON, "05:30", _sched(refresh_enabled=True, train_enabled=False))
    assert _of(acts, "CANDIDATE_TRAIN") == [] and _of(acts, "TRAIN_PUBLISH") == []


# ================================================================== stale export
def test_stale_export_at_export_deadline_exactly_once(bq):
    _freeze(_at(TUE, "06:29"))
    assert _of(_plan_at(TUE, "06:29"), "FORECAST_EXPORT") == []
    [x] = _of(_plan_at(TUE, "06:30"), "FORECAST_EXPORT")
    assert x["key"] == f"FORECAST_EXPORT:{TUE}:STALE" and x["params"] == {"business_date": str(TUE), "mode": "STALE"}
    runner.record_skipped("FORECAST_EXPORT", x["key"], "SCHEDULE", None, "TEST")   # the job row exists
    assert _of(_plan_at(TUE, "06:31"), "FORECAST_EXPORT") == []


@pytest.mark.parametrize("what", ["published", "exported"])
def test_no_stale_export_when_published_or_exported(bq, what):
    _freeze(_at(TUE, "06:00"))
    _sel2_run(TUE) if what == "published" else _export(TUE)
    assert _of(_plan_at(TUE, "06:45"), "FORECAST_EXPORT") == []


# ================================================================== AVG_DEMAND re-export
def test_avg_reexport_off_by_default_and_planned_once_from_the_configured_time(bq):
    _freeze(_at(TUE, "06:00"))
    assert ss.get("sel2_pipeline").avg_reexport_time is None
    _sel2_run(TUE)
    _export(TUE)
    assert _of(_plan_at(TUE, "11:00"), "FORECAST_EXPORT") == []
    ss.update("sel2_pipeline", {"avg_reexport_time": "10:15"})
    assert _of(_plan_at(TUE, "10:14"), "FORECAST_EXPORT") == []
    [a] = _of(_plan_at(TUE, "10:15"), "FORECAST_EXPORT")
    assert a["key"] == f"FORECAST_EXPORT:{TUE}:AVG" and a["params"]["mode"] == "AVG"
    runner.record_skipped("FORECAST_EXPORT", a["key"], "SCHEDULE", None, "TEST")
    assert _of(_plan_at(TUE, "10:30"), "FORECAST_EXPORT") == []


def test_avg_reexport_waits_for_a_first_export_and_validates_the_time(bq):
    ss.update("sel2_pipeline", {"avg_reexport_time": "10:15"})
    _freeze(_at(TUE, "06:00"))
    _sel2_run(TUE)
    assert _of(_plan_at(TUE, "10:20"), "FORECAST_EXPORT") == []
    with pytest.raises(Exception):
        ss.update("sel2_pipeline", {"avg_reexport_time": "25:00"})
    ss.update("sel2_pipeline", {"avg_reexport_time": None})
    assert ss.get("sel2_pipeline").avg_reexport_time is None


# ================================================================== emergency switch
def test_switch_off_plans_exactly_131_on_monday():
    _bq_scope()
    _freeze(_at(MON, "05:10"))
    _d1_ok(day=MON)
    acts = _plan_at(MON, "05:30", _sched(refresh_enabled=False))
    [t] = _of(acts, "TRAIN_PUBLISH")
    assert t["action"] == "run" and t["key"] == f"TRAIN_PUBLISH:{MON}"
    assert _of(acts, "CANDIDATE_TRAIN") == [] and _of(acts, "FORECAST_EXPORT") == []
    acts = _plan_at(MON, "06:40")                                   # refresh flow ON but daily_forecast OFF: nothing
    assert _of(acts) == [] and _of(acts, "FORECAST_EXPORT") == [] and _of(acts, "CANDIDATE_TRAIN") == []
    _enable()
    [r] = _of(_plan_at(MON, "06:40"))
    assert r["key"] == f"FORECAST_REFRESH:{MON}:06:40" and r["params"] == {"business_date": str(MON)}
