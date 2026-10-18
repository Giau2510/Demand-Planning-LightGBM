"""1.2.6 schedule configuration of the two day-end flows (end-of-day forecast backup `eod`, actual close `close`):
persistent time + timezone + switch through /api/schedules, central defaults, validation (time, timezone, same-minute
conflict), a switch ON confirmed by the running scheduler or not kept, runtime state, restart, one job per slot, the
read-only dry run, the 1.2.5 upgrade defaults and the read-only proxy rules. Every write goes to the isolated test DB."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

from app import db, forecast_history as fh, paths, settings_service as ss, timeutil
from app.jobs import scheduler as sched_mod
from app.jobs.scheduler import Scheduler, plan

import test_v126_eod_backup_close as t126
from test_v126_retention_defaults import STORED_125

VN = timeutil.VN_TZ
TZ = "Asia/Ho_Chi_Minh"
LIVE_DATA = Path(r"D:\Buymed\Lightgbm AI\data")
ROOT = Path(__file__).resolve().parents[2]
OLD_FLOWS = ("d1_enabled", "d0_enabled", "train_enabled", "d1_enabled_at", "d0_enabled_at", "train_enabled_at",
             "d0_times", "d1_signal_poll_start", "d1_fallback_time", "d1_poll_interval_minutes", "train_time",
             "d0_catchup_policy", "train_catchup_policy")


class RunningScheduler(Scheduler):
    """What a running app process exposes to /api/schedules: a scheduler that reports itself running and reloads the
    saved schedule on demand, without a thread, a tick or a job."""

    def status(self) -> dict:
        return {**super().status(), "running": True}


class SilentScheduler(RunningScheduler):
    """A running scheduler whose reload does not confirm what was saved (a broken / stale registration)."""

    def reload(self) -> dict:
        self.loaded = {"at": "x", "flows": {"d1": False, "d0": False, "train": False, "eod": False, "close": False}}
        return self.loaded


class FailingScheduler(RunningScheduler):
    def reload(self) -> dict:
        raise RuntimeError("scheduler registry unavailable")


@pytest.fixture(autouse=True)
def _isolated():
    p = paths.db_path().resolve()
    assert not p.is_relative_to(LIVE_DATA.resolve()) and ("pytest-" in str(p) or "df-tests-" in str(p)), p
    t126._at("2026-10-20 10:00")
    yield
    timeutil.set_now_override(None)


def _stored_schedule() -> str | None:
    with db.read() as c:
        r = db.one(c, "SELECT value_json FROM app_settings WHERE section='schedule'")
    return r["value_json"] if r else None


def _old_flows() -> dict:
    s = ss.get("schedule")
    return {k: getattr(s, k) for k in OLD_FLOWS}


def _audits(flow: str) -> list[dict]:
    with db.read() as c:
        return [json.loads(r[0]) for r in c.execute("SELECT details_json FROM audit_log WHERE action='SCHEDULE_CHANGED' "
                                                    "AND entity_id=? ORDER BY id", (flow,))]


def _all_tables() -> dict:
    """Row count + sha256 of EVERY table (a dry run must leave the whole database unchanged)."""
    out = {}
    with db.read() as c:
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            lines = sorted(repr(tuple(r)) for r in c.execute(f'SELECT * FROM "{t}"'))
            out[t] = (len(lines), hashlib.sha256("\n".join(lines).encode()).hexdigest())
    return out


# ------------------------------------------------------------------ cards: saved values, defaults, runtime state
def test_the_cards_show_the_saved_configuration_the_defaults_and_the_runtime_state(client, small_demo):
    ov = client.get("/api/schedules").json()
    for flow, hhmm in (("eod", "23:55"), ("close", "23:59")):
        v = ov["flows"][flow]
        assert v["config"] == {"time": hhmm, "timezone": TZ} and v["timezone"] == TZ
        assert v["defaults"] == {"enabled": False, "time": hhmm, "timezone": TZ}      # one central definition
        assert (v["enabled"], v["state"], v["runtime"]) == (False, "OFF", {"state": "NOT_REGISTERED", "job_id": None})
        assert v["next_runs"] == [] and v["planned_times_if_enabled"][0] == f"2026-10-20T{hhmm}:00+07:00"
        assert v["config_updated"] is None
    # the existing flows keep their exact view (no defaults / runtime block added to them)
    assert "runtime" not in ov["flows"]["d0"] and ov["flows"]["d0"]["config"]["times"][-1] == "18:00"


def test_each_flow_is_switched_and_timed_independently_and_the_old_flows_never_change(client, small_demo, monkeypatch):
    old = _old_flows()
    with monkeypatch.context() as m:          # never monkeypatch.undo(): conftest's isolation must stay in place
        m.setattr(sched_mod, "SCHEDULER", RunningScheduler())
        r = client.put("/api/schedules/eod", json={"enabled": True})
        assert r.status_code == 200, r.text
        v = r.json()
        assert (v["enabled"], v["state"], v["registered"], v["runtime"]["state"]) == (True, "ON", True, "REGISTERED")
        assert v["next_runs"][0] == "2026-10-20T23:55:00+07:00" and v["enabled_at"].startswith("2026-10-20T10:00")
        assert ss.get("schedule").close_enabled is False                          # the other flow is untouched
        r = client.put("/api/schedules/close", json={"time": "23:50"})
        assert r.status_code == 200 and r.json()["config"] == {"time": "23:50", "timezone": TZ}
        assert r.json()["enabled"] is False and r.json()["config_updated"]["fields"] == ["close_time"]
        assert ss.get("schedule").eod_time == "23:55" and ss.get("schedule").eod_enabled is True
        r = client.put("/api/schedules/close", json={"enabled": True, "time": "23:58"})
        assert r.status_code == 200 and (r.json()["state"], r.json()["config"]["time"]) == ("ON", "23:58")
        r = client.put("/api/schedules/eod", json={"enabled": False})
        assert r.status_code == 200 and r.json()["state"] == "OFF" and r.json()["runtime"]["state"] == "NOT_REGISTERED"
        assert ss.get("schedule").close_enabled is True                           # switching eod off leaves close on
    assert _old_flows() == old                                                     # D-1 / D-0 / training unchanged
    assert [sorted(a["changes"]) for a in _audits("close")] == [["close_time"], ["close_enabled", "close_enabled_at",
                                                                                  "close_time"]]


def test_saved_values_survive_a_reload_and_a_restart(client, small_demo, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(sched_mod, "SCHEDULER", RunningScheduler())
        assert client.put("/api/schedules/eod", json={"enabled": True, "time": "23:45"}).status_code == 200
        assert client.put("/api/schedules/close", json={"enabled": True}).status_code == 200
    # a new app process: a new scheduler reads the same saved state (nothing lives only in memory)
    fresh = RunningScheduler()
    assert fresh.reload()["flows"] == {"d1": False, "d0": False, "train": True, "eod": True, "close": True}
    from fastapi.testclient import TestClient
    from app.main import create_app
    with monkeypatch.context() as m:
        m.setattr(sched_mod, "SCHEDULER", fresh)
        with TestClient(create_app(), headers={"X-DF-Client": "web"}) as c2:
            f = c2.get("/api/schedules").json()["flows"]
    assert (f["eod"]["enabled"], f["eod"]["config"]["time"], f["close"]["enabled"]) == (True, "23:45", True)
    assert f["eod"]["state"] == "ON" and f["close"]["runtime"]["state"] == "REGISTERED"


@pytest.mark.parametrize("body", [{"time": "24:00"}, {"time": "7:00"}, {"time": "19:59"}, {"time": "23:59"},
                                  {"timezone": "UTC"}, {"timezone": "Asia/Bangkok"}, {"timezone": ""},
                                  {"enabled": "yes"}, {"run_at": "23:00"}])
def test_invalid_times_timezones_and_a_same_minute_conflict_are_refused_and_nothing_is_saved(client, small_demo, body):
    before, audits = _stored_schedule(), _audits("eod")
    r = client.put("/api/schedules/eod", json=body)          # 23:59 = the close's minute -> conflict
    assert r.status_code == 422, (body, r.text)
    assert _stored_schedule() == before and _audits("eod") == audits
    assert (ss.get("schedule").eod_time, ss.get("schedule").eod_timezone) == ("23:55", TZ)


def test_the_same_minute_is_refused_from_either_side():
    with pytest.raises(Exception) as e:
        ss.ScheduleSettings(eod_time="23:58", close_time="23:58")
    assert "must differ" in str(e.value)
    with pytest.raises(Exception):
        ss.update("schedule", {"close_time": "23:55"})
    assert ss.get("schedule").close_time == "23:59"


def test_without_a_running_scheduler_a_day_end_flow_is_never_switched_on(client, small_demo):
    assert sched_mod.SCHEDULER is None                       # the test app runs no scheduler (DF_DISABLE_SCHEDULER)
    for flow in ("eod", "close"):
        r = client.put(f"/api/schedules/{flow}", json={"enabled": True})
        assert r.status_code == 409 and r.json()["code"] == "SCHEDULE_NOT_REGISTERED"
        assert getattr(ss.get("schedule"), f"{flow}_enabled") is False and _audits(flow) == []
        assert client.get(f"/api/schedules/{flow}").json()["state"] == "OFF"


@pytest.mark.parametrize("broken", [SilentScheduler, FailingScheduler])
def test_a_scheduler_that_does_not_confirm_the_switch_leaves_the_flow_off(client, small_demo, monkeypatch, broken):
    with monkeypatch.context() as m:
        m.setattr(sched_mod, "SCHEDULER", broken())
        r = client.put("/api/schedules/eod", json={"enabled": True})
        assert r.status_code == 409 and r.json()["code"] == "SCHEDULE_NOT_REGISTERED"
        v = client.get("/api/schedules/eod").json()
    s = ss.get("schedule")
    assert (s.eod_enabled, s.eod_enabled_at) == (False, None)                   # no false ON is kept
    assert (v["enabled"], v["state"], v["runtime"]["state"]) == (False, "OFF", "NOT_REGISTERED")
    a = _audits("eod")
    assert [x["changes"].get("eod_enabled") for x in a] == [True, False] and a[1]["reason"] == "SCHEDULE_NOT_REGISTERED"


# ------------------------------------------------------------------ scheduler: one job per slot, OFF runs nothing
def test_on_plans_exactly_one_job_per_day_also_after_a_time_change_or_a_restart():
    seen = {"eod": "2026-10-18T00:00:00+07:00", "close": "2026-10-18T00:00:00+07:00"}
    on = ss.ScheduleSettings(train_enabled=False, eod_enabled=True, eod_enabled_at="2026-10-19T12:00:00+07:00")
    with db.read() as c:
        acts = plan(datetime(2026, 10, 19, 23, 56, tzinfo=VN), on, "BIGQUERY", None, c, seen)
    assert [(a["job_type"], a["key"]) for a in acts] == [("EOD_FORECAST_SNAPSHOT", "EOD_FORECAST_SNAPSHOT:2026-10-19")]
    with db.tx() as c:                                       # the slot's job exists (it ran)
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, created_at) "
                  "VALUES ('JOB-T1', 'EOD_FORECAST_SNAPSHOT', 'EOD_FORECAST_SNAPSHOT:2026-10-19', 'SCHEDULE', "
                  "'SUCCEEDED', 1, 4, ?)", (timeutil.now_iso(),))
    moved = on.model_copy(update={"eod_time": "23:57"})     # the operator moves the time after the run: same day key
    with db.read() as c:
        for s in (on, moved):
            for now in (datetime(2026, 10, 19, 23, 58, tzinfo=VN), datetime(2026, 10, 20, 0, 5, tzinfo=VN)):
                assert [a for a in plan(now, s, "BIGQUERY", None, c, seen) if a["job_type"] == "EOD_FORECAST_SNAPSHOT"] == []
        off = on.model_copy(update={"eod_enabled": False})
        assert plan(datetime(2026, 10, 20, 23, 56, tzinfo=VN), off, "BIGQUERY", None, c, seen) == []


# ------------------------------------------------------------------ dry run: computed like the job, writes nothing
def test_the_dry_run_previews_both_flows_and_writes_nothing(client):
    t126._bq_active()
    rid = t126._run("2026-10-20 09:00", origin="2026-10-20", horizon=15, keys=t126.KEYS, base=20)
    fh.capture(rid)
    t126._snapshot("2026-10-20", {("S1", "HN"): 4, ("S2", "HN"): 0}, "2026-10-20 08:00")   # S1|BD absent
    t126._at("2026-10-20 18:30")
    before = _all_tables()
    e = client.get("/api/schedules/eod/preview")
    assert e.status_code == 200, e.text
    e = e.json()
    assert (e["mode"], e["written"], e["business_date"], e["slot"]) == ("DRY_RUN", False, "2026-10-20",
                                                                         "2026-10-20T23:55:00+07:00")
    assert (e["snapshot_status"], e["source_run_id"], e["rows"], e["would_write"]) == ("COMPLETE", rid, 7 * 3, True)
    assert (e["first_target_date"], e["last_target_date"], e["missing_dates"]) == ("2026-10-21", "2026-10-27", [])
    cl = client.get("/api/schedules/close/preview").json()
    assert (cl["close_status"], cl["source"], cl["rows"], cl["total_qty"]) == ("CLOSED_UNVERIFIED", "D0", 2, 4.0)
    assert cl["would_write"] is True and cl["revisions_pending"] == [] and cl["written"] is False
    assert _all_tables() == before                            # not one row anywhere (no job, audit, alert, snapshot)
    assert client.get("/api/schedules/d0/preview").status_code == 422


def test_the_dry_run_of_a_day_without_actual_or_forecast_says_so_and_never_shows_zero(client):
    t126._bq_active()
    before = _all_tables()
    e = client.get("/api/schedules/eod/preview").json()
    assert (e["snapshot_status"], e["rows"], e["total_yhat"]) == ("NO_SOURCE", 0, None)
    cl = client.get("/api/schedules/close/preview").json()
    assert (cl["close_status"], cl["rows"], cl["total_qty"], cl["source"]) == ("CLOSED_NO_DATA", 0, None, None)
    assert _all_tables() == before


# ------------------------------------------------------------------ upgrade from 1.2.5 / read-only proxy
def test_a_stored_125_schedule_reads_the_central_day_end_defaults_and_keeps_the_old_flows():
    from test_v126_retention_defaults import _store_125_schedule
    _store_125_schedule()
    s = ss.get("schedule")
    assert (s.eod_enabled, s.eod_time, s.eod_timezone) == (False, "23:55", TZ)
    assert (s.close_enabled, s.close_time, s.close_timezone) == (False, "23:59", TZ)
    assert {k: getattr(s, k) for k in OLD_FLOWS} == {k: STORED_125[k] for k in OLD_FLOWS}
    assert json.loads(_stored_schedule()) == STORED_125                         # reading never rewrites the row


def test_the_read_only_proxy_still_refuses_every_schedule_write_and_the_dry_run():
    spec = importlib.util.spec_from_file_location("readonly_proxy", ROOT / "scripts" / "remote" / "readonly_proxy.py")
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    for method, path in (("PUT", "/api/schedules/eod"), ("PUT", "/api/schedules/close"),
                         ("POST", "/api/schedules/eod/run"), ("POST", "/api/schedules/close/run")):
        assert rp.classify(method, path) == (405, "REMOTE_READ_ONLY")
    assert rp.classify("GET", "/api/schedules") is None                          # the page itself stays readable
    for path in ("/api/schedules/eod/preview", "/api/schedules/close/preview", "/api/system/paths"):
        assert rp.classify("GET", path) == (403, "REMOTE_FORBIDDEN")
