"""1.3.1 C3-T2 tests: the FORECAST_REFRESH / ACCURACY_REPORT jobs (jobs/runner.py), their planning (jobs/scheduler.py),
the flows "refresh" / "report" (jobs/flows.py, /api/schedules) and the 1.2.14 behaviour with the new settings at their
defaults (docs/ke_hoach_lgbm_chot.md sections 1, 2 and 6.1).

Isolated databases (conftest), fixed Vietnam times (timeutil.set_now_override), the refresh / report handlers replaced by
fakes where the job itself is not the subject: unit tests and integration with fakes only."""
import json
import threading
from datetime import date, datetime, timedelta

import pytest

from app import db
from app import settings_service as ss
from app import timeutil
from app.jobs import flows, runner
from app.jobs.scheduler import Scheduler, loaded_flows, plan
from app.messages import AppError
from app.ml import accuracy_report, pipeline
from app.ml import daily_refresh as dr
from app.timeutil import VN_TZ

from test_v131_refresh import BQ_SCOPE, _d1_ok, _enable, _freeze, _no_real_bigquery  # noqa: F401 (autouse fixture)

T0 = datetime(2026, 10, 28, 5, 10, tzinfo=VN_TZ)          # 22:10 UTC of 27/10
OLD_FLOW_KEYS = ["d1", "d0", "train", "eod", "close"]


def _sched(**kw):
    return ss.ScheduleSettings(**{"train_enabled": True, "train_time": "05:20", "d1_enabled": True,
                                  "d1_signal_poll_start": "05:00", **kw})


def _bq_scope():
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders"})   # a resolvable BIGQUERY scope
    ss.update("general", {"active_source": "BIGQUERY"})


def _of(acts, job_type="FORECAST_REFRESH"):
    return [a for a in acts if a["job_type"] == job_type]


def _plan(t, sched, source="BIGQUERY"):
    with db.read() as c:
        return plan(t, sched, source, None, c)


def _patched_get(sched):
    real = ss.get

    def get(section, conn=None):
        return sched if section == "schedule" else real(section, conn)
    return get


def _jobs(job_type="FORECAST_REFRESH"):
    with db.read() as c:
        return db.rows(c, "SELECT * FROM job_runs WHERE job_type=? ORDER BY created_at, rowid", (job_type,))


def _published(rid, scope=BQ_SCOPE, fdate="2026-10-28", created=None):
    with db.tx() as c:
        c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, config_version, "
                  "trial_mode, horizon, n_series, n_lightgbm, n_fallback, created_at) VALUES (?, ?, ?, ?, 'PUBLISHED', "
                  "'cv', 1, 7, 1, 1, 0, ?)", (rid, scope, fdate, fdate, created or timeutil.now_iso()))


def _fake_refresh(calls, result):
    def run(business_date=None, job_id=None, cancel=None, progress=None, trigger="SCHEDULE"):
        calls.append((business_date, trigger))
        return result
    return run


# ================================================================== refresh planning
def test_refresh_waits_for_d1_then_retries_every_n_minutes_until_the_deadline_then_one_stale(monkeypatch):
    _bq_scope()
    _enable()
    sched = _sched(refresh_enabled=True, train_enabled=False, refresh_deadline="06:00")
    _freeze(T0)
    assert not _of(_plan(T0, sched))                                    # today's D-1 has not succeeded yet
    _d1_ok()
    assert [(a["action"], a["key"], a["trigger"], a["params"]) for a in _of(_plan(T0, sched))] == \
        [("run", "FORECAST_REFRESH:2026-10-28:05:10", "SCHEDULE", {"business_date": "2026-10-28"})]
    calls = []
    monkeypatch.setattr(dr, "run", _fake_refresh(calls, {"status": "NOT_READY", "reason_code": "OPEN_HOURS_INVALID"}))
    monkeypatch.setattr(ss, "get", _patched_get(sched))
    s = Scheduler()
    s.tick(T0, wait=True)
    assert [(j["status"], j["reason_code"], j["trigger"]) for j in _jobs()] == [("SKIPPED", "OPEN_HOURS_INVALID",
                                                                                 "SCHEDULE")]
    for minutes, n in ((5, 1), (9, 1), (10, 2), (15, 2), (21, 3), (45, 4)):   # every 10 minutes after the last one
        t = T0 + timedelta(minutes=minutes)
        _freeze(t)
        s.tick(t, wait=True)
        assert len(_jobs()) == n, minutes
    late = datetime(2026, 10, 28, 6, 1, tzinfo=VN_TZ)                   # after the deadline: no attempt, ONE stale
    for t in (late, late + timedelta(minutes=30), late + timedelta(hours=5)):
        _freeze(t)
        acts = s.tick(t, wait=True)
        assert not [a for a in _of(acts) if a["action"] == "run"]
    jobs = _jobs()
    assert len(calls) == 4 and set(calls) == {("2026-10-28", "SCHEDULE")}
    assert [j["idempotency_key"] for j in jobs][-1] == "FORECAST_REFRESH:2026-10-28:STALE" and len(jobs) == 5
    stale = jobs[-1]
    assert (stale["status"], stale["reason_code"], stale["trigger"]) == ("FAILED", "STALE_FORECAST", "SCHEDULE")
    assert stale["scheduled_for"] == "2026-10-28T06:00:00+07:00"
    again = runner.record_stale("FORECAST_REFRESH:2026-10-28:STALE", "2026-10-28", "x")          # idempotent
    assert again["id"] == stale["id"]
    with db.read() as c:
        alerts = db.rows(c, "SELECT level, entity_type, entity_id, params_json FROM alerts WHERE code='STALE_FORECAST'")
    assert len(alerts) == 1 and alerts[0]["level"] == "ERROR" and alerts[0]["entity_id"] == stale["id"]
    assert json.loads(alerts[0]["params_json"])["business_date"] == "2026-10-28"
    # the next day starts again (waiting for its own D-1), never with yesterday's attempts
    nxt = datetime(2026, 10, 29, 5, 10, tzinfo=VN_TZ)
    _freeze(nxt)
    assert not _of(_plan(nxt, sched))
    _d1_ok(day=date(2026, 10, 29))
    assert [a["key"] for a in _of(_plan(nxt, sched))] == ["FORECAST_REFRESH:2026-10-29:05:10"]


def test_a_refresh_waiting_for_its_retry_is_never_doubled_and_is_closed_after_the_deadline(monkeypatch):
    _bq_scope()
    _enable()
    sched = _sched(refresh_enabled=True, train_enabled=False, refresh_deadline="06:00")
    monkeypatch.setattr(ss, "get", _patched_get(sched))
    calls = []
    monkeypatch.setattr(dr, "run", _fake_refresh(calls, {"status": "PUBLISHED", "reason_code": "DAILY_FORECAST_PUBLISHED"}))
    _freeze(T0)
    _d1_ok()
    with db.tx() as c:                                                 # another process holds the job lock
        c.execute("INSERT INTO job_locks(lock_name, owner, acquired_at, expires_at) VALUES ('job:FORECAST_REFRESH', "
                  "'other', ?, '2099-01-01T00:00:00+00:00')", (timeutil.now_iso(),))
    s = Scheduler()
    s.tick(T0, wait=True)
    assert [(j["status"], j["reason_code"]) for j in _jobs()] == [("RETRY_WAIT", "LOCKED")]
    for minutes in (11, 22, 40):                                       # retried on its key, never a second attempt
        t = T0 + timedelta(minutes=minutes)
        _freeze(t)
        s.tick(t, wait=True)
        assert len(_jobs()) == 1, minutes
    late = datetime(2026, 10, 28, 6, 1, tzinfo=VN_TZ)
    _freeze(late)
    s.tick(late, wait=True)
    jobs = _jobs()
    assert sorted((j["idempotency_key"], j["status"], j["reason_code"]) for j in jobs) == [
        ("FORECAST_REFRESH:2026-10-28:05:10", "SKIPPED", "REFRESH_DEADLINE_PASSED"),
        ("FORECAST_REFRESH:2026-10-28:STALE", "FAILED", "STALE_FORECAST")]
    closed = next(j for j in jobs if j["reason_code"] == "REFRESH_DEADLINE_PASSED")
    assert calls == [] and closed["next_attempt_at"] is None and closed["finished_at"]
    _freeze(late + timedelta(minutes=30))
    s.tick(late + timedelta(minutes=30), wait=True)
    assert len(_jobs()) == 2


def test_a_published_refresh_of_today_stops_the_attempts_and_the_refresh_goes_before_training():
    _bq_scope()
    _enable()
    sched = _sched(refresh_enabled=True)                              # TRAIN 05:20, deadline 12:00
    t = datetime(2026, 10, 28, 5, 25, tzinfo=VN_TZ)
    _freeze(t)
    _d1_ok()
    runs = [a["job_type"] for a in _plan(t, sched) if a["action"] == "run"]
    assert "FORECAST_REFRESH" in runs and "TRAIN_PUBLISH" not in runs          # both heavy: training next tick
    # published runs that do not count: another scope, and yesterday's day refreshed this morning
    _published("S-OTHER", scope="BIGQUERY:p.d.other")
    _published("S-YDAY", fdate="2026-10-27")
    assert [a["key"] for a in _of(_plan(t, sched))] == ["FORECAST_REFRESH:2026-10-28:05:25"]
    noon = datetime(2026, 10, 28, 12, 30, tzinfo=VN_TZ)
    assert [(a["action"], a["key"], a["reason"]) for a in _of(_plan(noon, sched))] == \
        [("stale", "FORECAST_REFRESH:2026-10-28:STALE", "STALE_FORECAST")]
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, created_at) "
                  "VALUES ('J1', 'FORECAST_REFRESH', 'FORECAST_REFRESH:2026-10-28:05:25', 'SCHEDULE', 'SUCCEEDED', 1, 1, ?)",
                  (timeutil.now_iso(),))
    _published("S-OWN")
    nxt = _plan(t + timedelta(minutes=11), sched)
    assert "TRAIN_PUBLISH" in [a["job_type"] for a in nxt if a["action"] == "run"] and not _of(nxt)
    assert not _of(_plan(noon, sched)) and not _of(_plan(noon + timedelta(hours=8), sched))    # no stale verdict


def test_refresh_switch_off_or_daily_forecast_off_plans_exactly_what_was_planned_before():
    _bq_scope()
    _freeze(T0)
    _d1_ok()
    noon = datetime(2026, 10, 28, 12, 30, tzinfo=VN_TZ)
    base, base_noon = _plan(T0, _sched()), _plan(noon, _sched())
    assert not _of(base) and not _of(base_noon) and not _of(base, "ACCURACY_REPORT")
    _enable()
    assert _plan(T0, _sched()) == base and _plan(noon, _sched()) == base_noon       # switches OFF (default)
    ss.update("daily_forecast", {"enabled": False})
    on = _sched(refresh_enabled=True, report_enabled=True, report_weekday=3, report_time="05:00")
    assert _plan(T0, on) == base and _plan(noon, on) == base_noon                   # daily_forecast OFF: no stale
    assert _plan(T0, on, "DEMO") == _plan(T0, _sched(), "DEMO")
    s = _sched()
    assert list(loaded_flows(s)) == OLD_FLOW_KEYS
    assert loaded_flows(s) == {"d1": s.d1_enabled, "d0": s.d0_enabled, "train": s.train_enabled, "eod": s.eod_enabled,
                               "close": s.close_enabled}
    assert list(Scheduler().reload()["flows"]) == OLD_FLOW_KEYS                    # stored defaults
    assert loaded_flows(on) == {**loaded_flows(s), "refresh": True, "report": True}


def test_refresh_switched_on_after_the_deadline_starts_tomorrow_without_a_stale_verdict():
    _bq_scope()
    _enable()
    sched = _sched(refresh_enabled=True, refresh_enabled_at="2026-10-28T05:30:00+00:00")     # 12:30 Vietnam
    t = datetime(2026, 10, 28, 12, 35, tzinfo=VN_TZ)
    _freeze(t)
    _d1_ok()
    assert not _of(_plan(t, sched)) and not _of(_plan(t + timedelta(hours=11), sched))
    tomorrow = datetime(2026, 10, 29, 5, 10, tzinfo=VN_TZ)
    _freeze(tomorrow)
    _d1_ok(day=date(2026, 10, 29))
    assert [a["action"] for a in _of(_plan(tomorrow, sched))] == ["run"]


def test_refresh_on_a_source_other_than_bigquery_is_recorded_skipped_once():
    _enable()
    sched = _sched(refresh_enabled=True)
    _freeze(T0)
    acts = _of(_plan(T0, sched, "DEMO"))
    assert [(a["action"], a["key"], a["reason"]) for a in acts] == [
        ("skip", "FORECAST_REFRESH:2026-10-28:NA", "NOT_APPLICABLE_FOR_SOURCE")]
    runner.record_skipped("FORECAST_REFRESH", acts[0]["key"], "SCHEDULE", None, acts[0]["reason"])
    assert not _of(_plan(T0 + timedelta(minutes=30), sched, "DEMO"))


# ================================================================== weekly report planning
def test_weekly_report_is_planned_on_its_weekday_once_with_a_same_day_catch_up_only():
    _enable()
    mon = datetime(2026, 11, 2, 9, 35, tzinfo=VN_TZ)                  # Monday, slot 09:30
    sched = _sched(report_enabled=True)
    _freeze(mon)
    acts = _of(_plan(mon, sched), "ACCURACY_REPORT")
    assert [(a["action"], a["key"], a["trigger"], a["scheduled_for"], a["params"]) for a in acts] == [
        ("run", "ACCURACY_REPORT:2026-11-02", "SCHEDULE", "2026-11-02T09:30:00+07:00", {"business_date": "2026-11-02"})]
    assert not _of(_plan(mon.replace(hour=9, minute=29), sched), "ACCURACY_REPORT")        # before the slot
    assert [a["trigger"] for a in _of(_plan(mon.replace(hour=15), sched), "ACCURACY_REPORT")] == ["CATCH_UP"]
    for other in (mon + timedelta(days=1), mon - timedelta(days=1), mon + timedelta(days=6)):  # Tue, Sun, Sun
        assert not _of(_plan(other, sched), "ACCURACY_REPORT")
    assert not _of(_plan(mon, _sched()), "ACCURACY_REPORT")                               # switch OFF
    after = _sched(report_enabled=True, report_enabled_at="2026-11-02T03:00:00+00:00")     # 10:00 Vietnam
    assert not _of(_plan(mon.replace(hour=15), after), "ACCURACY_REPORT")                  # next week only
    before = _sched(report_enabled=True, report_enabled_at="2026-11-02T02:00:00+00:00")    # 09:00 Vietnam
    assert len(_of(_plan(mon.replace(hour=15), before), "ACCURACY_REPORT")) == 1
    # the Vietnam weekday decides: Monday 06:05 Vietnam is still Sunday in UTC
    early = _sched(report_enabled=True, report_time="06:00")
    assert [a["key"] for a in _of(_plan(datetime(2026, 11, 2, 6, 5, tzinfo=VN_TZ), early), "ACCURACY_REPORT")] == \
        ["ACCURACY_REPORT:2026-11-02"]
    ss.update("daily_forecast", {"enabled": False})
    assert not _of(_plan(mon, sched), "ACCURACY_REPORT")
    _enable()
    runner.record_skipped("ACCURACY_REPORT", "ACCURACY_REPORT:2026-11-02", "SCHEDULE", None, "TEST")     # once a day
    assert not _of(_plan(mon.replace(hour=15), sched), "ACCURACY_REPORT")


def test_a_scheduled_report_runs_once_as_a_light_job(monkeypatch):
    _enable()
    mon = datetime(2026, 11, 2, 9, 35, tzinfo=VN_TZ)
    sched = _sched(report_enabled=True, train_enabled=False, d1_enabled=False)
    monkeypatch.setattr(ss, "get", _patched_get(sched))
    seen = []
    monkeypatch.setattr(accuracy_report, "run", lambda business_date=None, job_id=None, trigger="SCHEDULE", progress=None:
                        seen.append((business_date, trigger)) or {"status": "DONE", "reason_code": "REPORT_WRITTEN"})
    _freeze(mon)
    s = Scheduler()
    s.tick(mon, wait=True)
    s.tick(mon + timedelta(minutes=1), wait=True)
    jobs = _jobs("ACCURACY_REPORT")
    assert [(j["idempotency_key"], j["status"], j["reason_code"]) for j in jobs] == [
        ("ACCURACY_REPORT:2026-11-02", "SUCCEEDED", "REPORT_WRITTEN")]
    assert seen == [("2026-11-02", "SCHEDULE")] and not runner.is_heavy("ACCURACY_REPORT")


# ================================================================== runner
@pytest.mark.parametrize("result, status", [
    ({"status": "PUBLISHED", "reason_code": "DAILY_FORECAST_PUBLISHED"}, "SUCCEEDED"),
    ({"status": "NOT_READY", "reason_code": "REFRESH_WAITS_FOR_D1"}, "SKIPPED"),
    ({"status": "SKIPPED", "reason_code": "DAILY_FORECAST_DISABLED"}, "SKIPPED"),
    ({"status": "FAILED", "reason_code": "MODEL_FILE_MISMATCH"}, "FAILED")])
def test_runner_maps_the_refresh_result_and_never_retries_it(monkeypatch, result, status):
    seen = []

    def run(business_date=None, job_id=None, cancel=None, progress=None, trigger="SCHEDULE"):
        seen.append((business_date, job_id, trigger, callable(cancel), callable(progress)))
        return result
    monkeypatch.setattr(dr, "run", run)
    row = runner.run_refresh_now("2026-10-28")
    assert (row["status"], row["reason_code"], row["trigger"]) == (status, result["reason_code"], "MANUAL")
    assert row["next_attempt_at"] is None and row["idempotency_key"].startswith("FORECAST_REFRESH:2026-10-28:MANUAL-")
    assert seen == [("2026-10-28", row["id"], "MANUAL", True, True)]
    assert json.loads(row["result_json"])["result"]["status"] == result["status"]


@pytest.mark.parametrize("result, status", [({"status": "DONE"}, "SUCCEEDED"), ({"status": "SKIPPED"}, "SKIPPED"),
                                            ({"status": "FAILED"}, "FAILED"), ({"status": "WEIRD"}, "FAILED"),
                                            ({}, "FAILED")])
def test_runner_maps_the_report_result(monkeypatch, result, status):
    seen = []
    monkeypatch.setattr(accuracy_report, "run", lambda business_date=None, job_id=None, trigger="SCHEDULE", progress=None:
                        seen.append((business_date, job_id, trigger)) or result)
    row = runner.run_report_now("2026-11-02")
    assert row["status"] == status and row["trigger"] == "MANUAL" and seen == [("2026-11-02", row["id"], "MANUAL")]
    assert row["idempotency_key"].startswith("ACCURACY_REPORT:2026-11-02:MANUAL-")


def test_forecast_refresh_is_heavy_and_blocks_a_training_and_a_promotion(monkeypatch):
    assert "FORECAST_REFRESH" in runner.HEAVY_TYPES and runner.is_heavy("FORECAST_REFRESH")
    started, release = threading.Event(), threading.Event()

    def slow(business_date=None, job_id=None, cancel=None, progress=None, trigger="SCHEDULE"):
        started.set()
        release.wait(20)
        return {"status": "PUBLISHED", "reason_code": "DAILY_FORECAST_PUBLISHED"}
    monkeypatch.setattr(dr, "run", slow)
    monkeypatch.setattr(accuracy_report, "run", lambda **k: {"status": "DONE"})
    with db.tx() as c:                                  # a candidate kept for review (promotable)
        c.execute("INSERT INTO training_runs(id, scope_key, data_source, status, started_at, reject_reason) VALUES "
                  "('TR-CAND', ?, 'BIGQUERY', 'REJECTED', ?, ?)", (BQ_SCOPE, timeutil.now_iso(), pipeline.PENDING_REVIEW))
    t = threading.Thread(target=runner.run_refresh_now, args=("2026-10-28",))
    t.start()
    try:
        assert started.wait(10)
        refresh_id = _jobs()[0]["id"]
        r = runner.execute("TRAIN_PUBLISH", "TRAIN_PUBLISH:during", "MANUAL")
        assert r["note"] == "LOCKED" and "heavy job FORECAST_REFRESH" in r["busy"]
        assert runner.run_report_now("2026-10-28")["status"] == "SUCCEEDED"     # a light job runs meanwhile
        with pytest.raises(AppError) as e:
            pipeline.promote_candidate("TR-CAND")
        assert (e.value.code, e.value.detail) == ("LOCKED", refresh_id)
    finally:
        release.set()
        t.join(20)
    assert _jobs()[0]["status"] == "SUCCEEDED"
    with pytest.raises(AppError) as e:                  # refresh ended: the promotion goes on to its next check
        pipeline.promote_candidate("TR-CAND")
    assert e.value.code != "LOCKED"
    with db.tx() as c:                                  # a refresh waiting to start locks it too
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, created_at) "
                  "VALUES ('J-P', 'FORECAST_REFRESH', 'FORECAST_REFRESH:2026-10-28:09:00', 'SCHEDULE', 'PENDING', 0, 1, ?)",
                  (timeutil.now_iso(),))
    with pytest.raises(AppError) as e:
        pipeline.promote_candidate("TR-CAND")
    assert (e.value.code, e.value.detail) == ("LOCKED", "J-P")


# ================================================================== flows + API
def test_flows_readiness_overview_and_saving_the_refresh_and_report_times(client):
    _freeze(datetime(2026, 10, 28, 6, 30, tzinfo=VN_TZ))
    codes = lambda f: [r["code"] for r in flows.readiness(f)["reasons"]]       # noqa: E731
    assert {"DAILY_FORECAST_DISABLED", "NOT_APPLICABLE_FOR_SOURCE"} <= set(codes("refresh"))   # DEMO source
    assert "DAILY_FORECAST_DISABLED" in codes("report")
    ov = client.get("/api/schedules").json()
    assert set(ov["flows"]) == set(OLD_FLOW_KEYS) | {"refresh", "report"}
    ref, rep = ov["flows"]["refresh"], ov["flows"]["report"]
    assert (ref["job_type"], ref["enabled"], ref["state"], ref["config"]) == (
        "FORECAST_REFRESH", False, "OFF", {"deadline": "12:00", "retry_minutes": 10})
    assert ref["next_runs"] == [] and ref["planned_times_if_enabled"] == []          # no fixed slot (after D-1)
    assert (rep["job_type"], rep["enabled"], rep["state"], rep["config"]) == (
        "ACCURACY_REPORT", False, "OFF", {"weekday": 1, "time": "09:30"})
    assert rep["next_runs"] == [] and rep["planned_times_if_enabled"] == [
        "2026-11-02T09:30:00+07:00", "2026-11-09T09:30:00+07:00", "2026-11-16T09:30:00+07:00"]
    r = client.put("/api/schedules/refresh", json={"enabled": True})                 # not ready: nothing saved
    assert r.status_code == 409 and r.json()["code"] == "FLOW_NOT_READY"
    assert "DAILY_FORECAST_DISABLED" in r.json()["detail"] and ss.get("schedule").refresh_enabled is False
    r = client.put("/api/schedules/refresh", json={"deadline": "11:30", "retry_minutes": 15})
    assert r.status_code == 200 and r.json()["saved"] is True
    assert r.json()["config"] == {"deadline": "11:30", "retry_minutes": 15}
    for bad in ({"deadline": "25:00"}, {"deadline": "9:30"}, {"deadline": "11:30:00"}, {"retry_minutes": 0},
                {"retry_minutes": 61}, {"time": "10:00"}, {"enabled": "yes"}):
        assert client.put("/api/schedules/refresh", json=bad).status_code == 422, bad
    cur = ss.get("schedule")
    assert (cur.refresh_deadline, cur.refresh_retry_minutes, cur.refresh_enabled) == ("11:30", 15, False)
    r = client.put("/api/schedules/report", json={"weekday": 3, "time": "08:15"})
    assert r.status_code == 200 and r.json()["config"] == {"weekday": 3, "time": "08:15"}
    assert r.json()["planned_times_if_enabled"][0] == "2026-10-28T08:15:00+07:00"    # Wednesday, still ahead today
    for bad in ({"weekday": 0}, {"weekday": 8}, {"time": "8:15"}, {"deadline": "10:00"}):
        assert client.put("/api/schedules/report", json=bad).status_code == 422, bad
    assert (ss.get("schedule").report_weekday, ss.get("schedule").report_time) == (3, "08:15")
    with db.read() as c:
        aud = db.rows(c, "SELECT entity_id, details_json FROM audit_log WHERE action='SCHEDULE_CHANGED' ORDER BY id")
    assert [a["entity_id"] for a in aud] == ["refresh", "report"]
    assert json.loads(aud[0]["details_json"])["changes"] == {"refresh_deadline": "11:30", "refresh_retry_minutes": 15}
    for k in ("refresh_enabled", "report_enabled", "refresh_enabled_at"):             # never by the generic editor
        r = client.put("/api/settings/schedule", json={k: True if k.endswith("enabled") else "2026-10-28T00:00:00+00:00"})
        assert r.status_code == 409 and r.json()["code"] == "SCHEDULE_SWITCH_VIA_FLOW_API", k
    _enable()
    assert "DAILY_FORECAST_DISABLED" not in codes("report") and "DAILY_FORECAST_DISABLED" not in codes("refresh")


# ================================================================== 11. defaults = 1.2.14 over a whole day
def _record(a, t):
    """The planned action as if it ran at once (run -> SUCCEEDED; a D-1 load ending yesterday)."""
    status = {"run": "SUCCEEDED", "skip": "SKIPPED"}.get(a["action"], "FAILED")
    res = {"result": {"window_end": str(t.date() - timedelta(days=1))}} if a["job_type"] == "D1_SYNC" else {}
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, scheduled_for, status, attempt, "
                  "max_attempts, created_at, finished_at, reason_code, result_json) VALUES (?,?,?,?,?,?,1,1,?,?,?,?)",
                  (db.new_id("JOB"), a["job_type"], a["key"], a["trigger"], a.get("scheduled_for"), status,
                   timeutil.now_iso(), timeutil.now_iso(), a.get("reason"), json.dumps(res)))


def simulate_day(plan_fn, sched, source, day=date(2026, 10, 28), step_minutes=10):
    """Every tick of a Vietnam day: plan, then record each action as done. Returns (HH:MM, action, job type, key,
    trigger, scheduled_for, reason) of every planned action."""
    out = []
    t = datetime(day.year, day.month, day.day, 0, 0, tzinfo=VN_TZ)
    while t.date() == day:
        _freeze(t)
        with db.read() as c:
            acts = plan_fn(t, sched, source, None, c)
        for a in acts:
            out.append((t.strftime("%H:%M"), a["action"], a["job_type"], a["key"], a["trigger"], a.get("scheduled_for"),
                        a.get("reason")))
            _record(a, t)
        t += timedelta(minutes=step_minutes)
    with db.tx() as c:
        c.execute("DELETE FROM job_runs")
    return out


ALL_OLD_ON = {"d1_enabled": True, "d0_enabled": True, "train_enabled": True, "eod_enabled": True, "close_enabled": True,
              **{f"{f}_enabled_at": "2026-10-01T00:00:00+07:00" for f in ("d1", "d0", "train", "eod", "close")}}


def _expected_1214(source):
    """Recorded with the 1.2.14 scheduler (commit af835b8, jobs/scheduler.py plan) on the same simulation."""
    if source == "BIGQUERY":
        d1 = [("01:00", "run", "D1_SYNC", "D1_SYNC:2026-10-28", "SCHEDULE", "2026-10-28T01:00:00+07:00", None),
              ("07:00", "run", "TRAIN_PUBLISH", "TRAIN_PUBLISH:2026-10-28", "SCHEDULE", "2026-10-28T07:00:00+07:00", None)]
    else:
        d1 = [("01:00", "skip", "D1_SYNC", "D1_SYNC:2026-10-28", "SCHEDULE", "2026-10-28T01:00:00+07:00",
               "NOT_APPLICABLE_FOR_SOURCE"),
              ("07:00", "run", "TRAIN_PUBLISH", "TRAIN_PUBLISH:2026-10-28", "SCHEDULE", "2026-10-28T07:00:00+07:00", None)]
    d0 = [(t, "run", "D0_SYNC", f"D0_SYNC:2026-10-28T{t}", "SCHEDULE", f"2026-10-28T{t}:00+07:00", None)
          for t in ("08:00", "10:00", "12:00", "14:00", "16:00", "18:00")]
    # yesterday's day-end slots (23:55 / 23:59) are within the 20-minute grace at the 00:00 tick
    head = [("00:00", "run", "EOD_FORECAST_SNAPSHOT", "EOD_FORECAST_SNAPSHOT:2026-10-27", "SCHEDULE",
             "2026-10-27T23:55:00+07:00", None),
            ("00:00", "run", "ACTUAL_CLOSE", "ACTUAL_CLOSE:2026-10-27", "SCHEDULE", "2026-10-27T23:59:00+07:00", None)]
    return head + d1 + d0                     # today's 23:55 / 23:59 slots fall after the last tick (23:50)


def test_with_the_new_settings_at_their_defaults_a_whole_day_is_planned_as_in_1_2_14():
    for source in ("BIGQUERY", "DEMO"):
        if source == "BIGQUERY":
            _bq_scope()
        base = simulate_day(plan, ss.ScheduleSettings(**ALL_OLD_ON), source)
        assert base == _expected_1214(source), source
        _enable()                                              # daily forecast ON, its two switches OFF
        assert simulate_day(plan, ss.ScheduleSettings(**ALL_OLD_ON), source) == base, source
        ss.update("daily_forecast", {"enabled": False})        # switches ON, daily forecast OFF
        on = ss.ScheduleSettings(**ALL_OLD_ON, refresh_enabled=True, report_enabled=True, report_weekday=3)
        assert simulate_day(plan, on, source) == base, source
