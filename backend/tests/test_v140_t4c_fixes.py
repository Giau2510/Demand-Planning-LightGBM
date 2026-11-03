"""1.4.0 T4c tests: the job's trigger and id passed through the CLI (sel2-day / sel2-train --trigger --job-id) and the
child command of the SEL2 jobs, the progress stages of CANDIDATE_TRAIN / FORECAST_EXPORT, the catch-up training of the
week's origin on another weekday (+ the forced re-run after it) and the training timeout
(sel2_pipeline.train_timeout_seconds).

Isolated databases (conftest), fixed Vietnam times, the pipeline and the heavy child replaced by fakes: unit tests and
integration with fakes."""
import json
from datetime import timedelta

import pytest

from app import cli, db
from app import settings_service as ss
from app import timeutil
from app.jobs import progress, runner
from app.ml.sel2 import jobs as sel2_jobs
from app.ml.sel2 import pipeline

from test_v131_refresh import BQ_SCOPE, _d1_ok, _freeze, _no_real_bigquery  # noqa: F401 (autouse fixture)
from test_v131_refresh_jobs import _bq_scope, _of, _patched_get, _sched
from test_v140_t4b_planning import MON, TUE, _at, _export, _job, _plan_at, _sel2_run, _set_job

CATCHUP = f"CANDIDATE_TRAIN:{MON}:CATCHUP"


@pytest.fixture(autouse=True)
def _reset_child():
    yield
    sel2_jobs.set_child_runner(None)


@pytest.fixture
def bq(sel2_on):
    _bq_scope()


def _trained(origin, models=sel2_jobs.TRAIN_MODELS, scope=BQ_SCOPE):
    with db.tx() as c:
        for m in models:
            c.execute("INSERT INTO candidate_train_runs(id, scope_key, model, origin_date, status, created_at) "
                      "VALUES (?, ?, ?, ?, 'SUCCEEDED', ?)",
                      (db.new_id("CTR"), scope, m, str(origin), timeutil.now_iso()))


# ================================================================== CLI: --trigger / --job-id
def test_cli_sel2_day_and_train_pass_trigger_and_job_id(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(pipeline, "run_day", lambda d, **kw: calls.append(("day", d, kw)) or {"status": "PUBLISHED"})
    monkeypatch.setattr(pipeline, "train_week", lambda o, **kw: calls.append(("train", o, kw)) or {"trained": []})
    assert cli.main(["sel2-day", "--date", str(TUE), "--yes", "--force", "--trigger", "RETRY",
                     "--job-id", "JOB-7"]) == 0
    assert cli.main(["sel2-train", "--origin", str(MON), "--yes", "--trigger", "SCHEDULE", "--job-id", "JOB-8"]) == 0
    assert calls == [("day", TUE, {"trigger": "RETRY", "job_id": "JOB-7", "force": True}),
                     ("train", MON, {"job_id": "JOB-8"})]
    assert cli.main(["sel2-day", "--date", str(TUE), "--yes"]) == 0          # defaults: trigger cli, no job id
    assert calls[-1] == ("day", TUE, {"trigger": "cli", "job_id": None, "force": False})
    capsys.readouterr()
    assert cli.main(["sel2-day", "--date", str(TUE), "--trigger", "MANUAL"]) == 0          # without --yes: plan only
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["args"]["trigger"] == "MANUAL" and len(calls) == 3


def test_jobs_pass_the_job_rows_trigger_and_id_to_the_child(bq, monkeypatch):
    _freeze(_at(TUE, "05:10"))
    _d1_ok(day=TUE)
    monkeypatch.setattr(ss, "get", _patched_get(_sched(refresh_enabled=True)))
    calls = []

    def run(args, timeout, cancel):
        calls.append((list(args), timeout))
        if args[0] == "sel2-train":
            return {"ok": True, "result": {"trained": [], "skipped": list(sel2_jobs.TRAIN_MODELS)}}
        return {"ok": True, "result": {"status": "ALREADY_PUBLISHED", "run_id": "FRR-1"}}
    sel2_jobs.set_child_runner(run)
    monkeypatch.setattr(sel2_jobs, "avg_read", lambda d: {"status": "ALREADY_READ"})
    row = runner.execute("CANDIDATE_TRAIN", CATCHUP, "SCHEDULE", None, {"origin": str(MON)})
    assert row["status"] == "SUCCEEDED"
    assert calls[0][0] == ["sel2-train", "--origin", str(MON), "--yes", "--trigger", "SCHEDULE", "--job-id", row["id"]]
    row = runner.execute("FORECAST_REFRESH", f"FORECAST_REFRESH:{TUE}:05:10", "MANUAL", None,
                         {"business_date": str(TUE)})
    assert calls[1][0] == ["sel2-day", "--date", str(TUE), "--yes", "--force", "--trigger", "MANUAL",
                           "--job-id", row["id"]]


# ================================================================== timeout
def test_training_child_uses_train_timeout_and_refresh_keeps_schedule_timeout(bq, monkeypatch):
    assert ss.get("sel2_pipeline").train_timeout_seconds == 10800
    ss.update("sel2_pipeline", {"train_timeout_seconds": 7200})
    for bad in (599, 43201):
        with pytest.raises(Exception):
            ss.update("sel2_pipeline", {"train_timeout_seconds": bad})
    seen = []
    sel2_jobs.set_child_runner(lambda args, timeout, cancel: seen.append((args[0], timeout)) or
                               {"ok": True, "result": {"status": "ALREADY_PUBLISHED"}})
    sel2_jobs.train(None, {"origin": str(MON)}, trigger="SCHEDULE")
    monkeypatch.setattr(sel2_jobs, "avg_read", lambda d: {"status": "ALREADY_READ"})
    sel2_jobs.refresh(None, {"business_date": "2026-10-01"})
    assert seen == [("sel2-train", 7200), ("sel2-day", ss.get("schedule").timeout_seconds)]


# ================================================================== progress stages
def test_progress_stages_of_the_sel2_job_types():
    assert progress.STAGES["CANDIDATE_TRAIN"] == ["QUEUED", "STARTED", "TRAINING", "DONE"]
    assert progress.STAGES["FORECAST_EXPORT"] == ["QUEUED", "STARTED", "EXPORTING", "DONE"]
    assert all(jt in progress.STAGES for jt in runner.JOB_TYPES)


# ================================================================== catch-up training
def test_tuesday_with_missing_monday_models_one_catchup_after_export_then_one_forced_rerun(bq):
    _freeze(_at(TUE, "05:10"))
    _d1_ok(day=TUE)
    _trained(MON, models=("MOC",))                                  # one model of Monday only: still missing
    assert _of(_plan_at(TUE, "05:30"), "CANDIDATE_TRAIN") == []     # no export of today yet, before export_deadline
    _sel2_run(TUE, flags=["MODEL_PREV_WEEK"])
    _export(TUE)
    [t] = _of(_plan_at(TUE, "05:40"), "CANDIDATE_TRAIN")
    assert t["action"] == "run" and t["key"] == CATCHUP and t["params"] == {"origin": str(MON)}
    assert t["trigger"] == "SCHEDULE"
    _job("CANDIDATE_TRAIN", CATCHUP, "RUNNING")
    acts = _plan_at(TUE, "05:50")
    assert _of(acts, "CANDIDATE_TRAIN") == [] and _of(acts) == []  # once; no re-run while it runs
    _set_job(CATCHUP, "SUCCEEDED")
    [rr] = _of(_plan_at(TUE, "07:30"))
    assert rr["key"] == f"FORECAST_REFRESH:{TUE}:RERUN" and rr["params"] == {"business_date": str(TUE), "force": True}
    _job("FORECAST_REFRESH", rr["key"], "SUCCEEDED")
    acts = _plan_at(TUE, "07:40")
    assert _of(acts) == [] and _of(acts, "CANDIDATE_TRAIN") == []


def test_catchup_from_export_deadline_without_an_export(bq):
    _freeze(_at(TUE, "06:00"))
    assert _of(_plan_at(TUE, "06:29"), "CANDIDATE_TRAIN") == []
    [t] = _of(_plan_at(TUE, "06:30"), "CANDIDATE_TRAIN")
    assert t["key"] == CATCHUP


def test_catchup_on_a_later_weekday_uses_the_weeks_origin(bq):
    thu = MON + timedelta(days=3)
    _freeze(_at(thu, "06:00"))
    _export(thu)
    [t] = _of(_plan_at(thu, "06:00"), "CANDIDATE_TRAIN")
    assert t["key"] == CATCHUP and t["params"] == {"origin": str(MON)}


def test_no_catchup_when_the_models_exist_or_the_weekly_training_runs(bq):
    _freeze(_at(TUE, "06:00"))
    _export(TUE)
    _trained(MON, scope="BIGQUERY:other.scope")                      # models of another scope do not count
    assert [a["key"] for a in _of(_plan_at(TUE, "06:40"), "CANDIDATE_TRAIN")] == [CATCHUP]
    _job("CANDIDATE_TRAIN", f"CANDIDATE_TRAIN:{MON}", "RETRY_WAIT")  # Monday's training still under way: its own
    keys = [a["key"] for a in _of(_plan_at(TUE, "06:40"), "CANDIDATE_TRAIN")]     # retry only, no catch-up
    assert CATCHUP not in keys and keys in ([], [f"CANDIDATE_TRAIN:{MON}"])
    _set_job(f"CANDIDATE_TRAIN:{MON}", "SUCCEEDED")
    _trained(MON)
    assert _of(_plan_at(TUE, "06:41"), "CANDIDATE_TRAIN") == []


def test_no_catchup_on_the_retraining_weekday_with_training_off_or_switch_off(bq):
    _freeze(_at(MON, "06:00"))
    _export(MON)
    assert [a["key"] for a in _of(_plan_at(MON, "06:40"), "CANDIDATE_TRAIN")] == []    # Monday: no D-1, no catch-up
    _freeze(_at(TUE, "06:00"))
    _export(TUE)
    assert _of(_plan_at(TUE, "06:40", _sched(refresh_enabled=True, train_enabled=False)), "CANDIDATE_TRAIN") == []
    assert _of(_plan_at(TUE, "06:40", _sched(refresh_enabled=False)), "CANDIDATE_TRAIN") != []
    ss.update("sel2_pipeline", {"enabled": False})
    acts = _plan_at(TUE, "06:40")
    assert _of(acts, "CANDIDATE_TRAIN") == [] and _of(acts, "FORECAST_EXPORT") == []
