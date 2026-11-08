"""1.4.8 C-2: scheduling of the SO-line step SPIKE_LINES (jobs/scheduler.py). Switch OFF (default): every other plan is
exactly the one of the 1.4.7 scheduler (loaded from git commit 5c45449 and compared tick by tick), SPIKE_LINES only
after today's refresh; switch ON: right after D-1, refresh and trainings wait at most 45 minutes.
Isolated databases (conftest), fixed Vietnam times, rows inserted directly: unit tests."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

from app import db
from app import settings_service as ss
from app.jobs import scheduler

from test_v131_refresh import _d1_ok, _freeze, _no_real_bigquery  # noqa: F401 (autouse fixture)
from test_v131_refresh_jobs import _bq_scope, _of, _plan, _sched
from test_v140_t4b_planning import MON, TUE, _at, _job, _sel2_run, _set_job

REF_COMMIT = "5c45449"          # Release 1.4.7


def _ref_scheduler():
    """The 1.4.7 jobs/scheduler.py as a module of the app.jobs package (same relative imports)."""
    root = Path(__file__).resolve().parents[2]
    try:
        src = subprocess.run(["git", "show", f"{REF_COMMIT}:backend/app/jobs/scheduler.py"], cwd=root,
                             capture_output=True, check=True).stdout.decode("utf-8")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git or the 1.4.7 commit is not available")
    spec = importlib.util.spec_from_loader("app.jobs._scheduler_147", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "app.jobs"
    exec(compile(src, "scheduler_147.py", "exec"), mod.__dict__)
    return mod


@pytest.fixture
def bq(sel2_on):
    _bq_scope()


def _both(ref, d, hhmm, sched):
    t = _at(d, hhmm)
    _freeze(t)
    new = _plan(t, sched)
    with db.read() as c:
        old = ref.plan(t, sched, "BIGQUERY", None, c)
    return new, old


def _strip(acts):
    return [a for a in acts if a["job_type"] != "SPIKE_LINES"]


# ------------------------------------------------------------------ switch OFF: 1.4.7 plans unchanged
def test_off_every_other_decision_is_the_147_one_over_a_monday_and_a_tuesday(bq):
    ref = _ref_scheduler()
    sched = _sched(refresh_enabled=True)
    spikes = []

    def step(d, hhmm):
        new, old = _both(ref, d, hhmm, sched)
        assert _strip(new) == old, (d, hhmm)
        spikes.extend(a for a in new if a["job_type"] == "SPIKE_LINES")
        return new
    # Monday (retraining weekday): no D-1, D-1, training planned / running, refresh waits, training done, refresh
    step(MON, "05:05")
    _d1_ok(day=MON)
    step(MON, "05:10")
    _job("CANDIDATE_TRAIN", f"CANDIDATE_TRAIN:{MON}", "RUNNING")
    step(MON, "05:20")
    step(MON, "07:30")                                               # after prev_week_deadline: refresh runs
    _job("FORECAST_REFRESH", f"FORECAST_REFRESH:{MON}:07:30", "RUNNING")
    step(MON, "07:45")
    _set_job(f"FORECAST_REFRESH:{MON}:07:30", "SUCCEEDED")
    _sel2_run(MON, flags=["MODEL_PREV_WEEK"])
    step(MON, "08:00")                                               # training still running: no SPIKE_LINES
    assert spikes == []
    _set_job(f"CANDIDATE_TRAIN:{MON}", "SUCCEEDED")
    step(MON, "08:30")                                               # forced re-run planned (1.4.7) ...
    _job("FORECAST_REFRESH", f"FORECAST_REFRESH:{MON}:RERUN", "RUNNING")
    step(MON, "08:40")
    assert spikes == []                                              # ... and the step waits for it
    _set_job(f"FORECAST_REFRESH:{MON}:RERUN", "SUCCEEDED")
    step(MON, "09:00")
    assert [a["key"] for a in spikes] == [f"SPIKE_LINES:{MON}"]
    # Tuesday: refresh after D-1, then SPIKE_LINES; a refresh past its deadline without publication: SPIKE_LINES too
    spikes.clear()
    step(TUE, "05:05")
    _d1_ok(day=TUE)
    step(TUE, "05:10")
    assert spikes == []
    _job("FORECAST_REFRESH", f"FORECAST_REFRESH:{TUE}:05:10", "SUCCEEDED")
    _sel2_run(TUE)
    step(TUE, "05:40")
    assert [a["key"] for a in spikes] == [f"SPIKE_LINES:{TUE}"]
    assert spikes[0]["params"] == {"business_date": str(TUE)}


def test_off_after_the_deadline_without_a_publication(bq):
    ref = _ref_scheduler()
    sched = _sched(refresh_enabled=True, train_enabled=False)     # (a training catch-up would go first)
    _freeze(_at(TUE, "05:00"))
    _d1_ok(day=TUE)
    _job("FORECAST_REFRESH", f"FORECAST_REFRESH:{TUE}:05:10", "FAILED")
    new, old = _both(ref, TUE, "23:00", sched)
    assert _strip(new) == old
    assert [a["key"] for a in _of(new, "SPIKE_LINES")] == [f"SPIKE_LINES:{TUE}"]
    _job("SPIKE_LINES", f"SPIKE_LINES:{TUE}", "FAILED")              # one job per day, never again
    new, old = _both(ref, TUE, "23:10", sched)
    assert _of(new, "SPIKE_LINES") == [] and _strip(new) == old


def test_off_nothing_without_refresh_flow_or_sel2(sel2_on):
    _bq_scope()
    _freeze(_at(TUE, "05:00"))
    _d1_ok(day=TUE)
    _sel2_run(TUE)
    assert _of(_plan(_at(TUE, "09:00"), _sched(refresh_enabled=False)), "SPIKE_LINES") == []
    ss.update("sel2_pipeline", {"enabled": False})
    assert _of(_plan(_at(TUE, "09:00"), _sched(refresh_enabled=True)), "SPIKE_LINES") == []


# ------------------------------------------------------------------ switch ON
@pytest.fixture
def on(bq):
    ss.update("sel2_pipeline", {"spike_cleaning": True})


def test_on_step_right_after_d1_refresh_waits_at_most_45_minutes(on):
    sched = _sched(refresh_enabled=True)
    _freeze(_at(TUE, "05:05"))
    assert _of(_plan(_at(TUE, "05:05"), sched), "SPIKE_LINES") == []          # no D-1 yet
    _d1_ok(day=TUE)
    acts = _plan(_at(TUE, "05:10"), sched)
    assert [a["key"] for a in _of(acts, "SPIKE_LINES")] == [f"SPIKE_LINES:{TUE}"] and _of(acts) == []
    _freeze(_at(TUE, "05:10"))
    _job("SPIKE_LINES", f"SPIKE_LINES:{TUE}", "RUNNING")                      # created 05:10
    _freeze(_at(TUE, "05:54"))
    assert _of(_plan(_at(TUE, "05:54"), sched)) == []                         # 44 min: still waiting
    _freeze(_at(TUE, "05:56"))
    [r] = _of(_plan(_at(TUE, "05:56"), sched))                                # 46 min: goes on
    assert r["key"] == f"FORECAST_REFRESH:{TUE}:05:56"


@pytest.mark.parametrize("status", ["SUCCEEDED", "FAILED", "SKIPPED"])
def test_on_refresh_goes_on_once_the_step_ended(on, status):
    sched = _sched(refresh_enabled=True)
    _freeze(_at(TUE, "05:10"))
    _d1_ok(day=TUE)
    _job("SPIKE_LINES", f"SPIKE_LINES:{TUE}", status)
    acts = _plan(_at(TUE, "05:12"), sched)
    assert len(_of(acts)) == 1 and _of(acts, "SPIKE_LINES") == []


def test_on_monday_training_waits_for_the_step_then_the_refresh_for_the_training(on):
    sched = _sched(refresh_enabled=True)
    _freeze(_at(MON, "05:10"))
    _d1_ok(day=MON)
    acts = _plan(_at(MON, "05:10"), sched)
    assert _of(acts, "CANDIDATE_TRAIN") == [] and _of(acts) == [] and len(_of(acts, "SPIKE_LINES")) == 1
    _job("SPIKE_LINES", f"SPIKE_LINES:{MON}", "RUNNING")
    acts = _plan(_at(MON, "05:20"), sched)
    assert _of(acts, "CANDIDATE_TRAIN") == [] and _of(acts) == []
    _set_job(f"SPIKE_LINES:{MON}", "SUCCEEDED")
    acts = _plan(_at(MON, "05:30"), sched)
    assert [a["key"] for a in _of(acts, "CANDIDATE_TRAIN")] == [f"CANDIDATE_TRAIN:{MON}"] and _of(acts) == []


def test_in_flight_step_without_row_keeps_the_refresh_waiting(on):
    sched = _sched(refresh_enabled=True)
    _freeze(_at(TUE, "05:10"))
    _d1_ok(day=TUE)
    t = _at(TUE, "05:11")
    with db.read() as c:
        acts = scheduler.plan(t, sched, "BIGQUERY", None, c, inflight=frozenset({f"SPIKE_LINES:{TUE}"}))
    assert _of(acts) == [] and _of(acts, "SPIKE_LINES") == []


def test_tick_runs_the_step_through_the_runner(monkeypatch):
    from app.jobs import runner
    seen = []
    monkeypatch.setattr(runner, "execute", lambda *a: seen.append(a))
    scheduler.Scheduler()._run({"job_type": "SPIKE_LINES", "key": "SPIKE_LINES:2026-11-03", "trigger": "SCHEDULE",
                                "scheduled_for": None, "params": {"business_date": "2026-11-03"}})
    assert seen == [("SPIKE_LINES", "SPIKE_LINES:2026-11-03", "SCHEDULE", None, {"business_date": "2026-11-03"})]
    assert "SPIKE_LINES" in runner.JOB_TYPES and runner.FLOW_FLAG["SPIKE_LINES"] == "refresh_enabled"
