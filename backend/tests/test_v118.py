"""1.1.8: separate D-1 / D-0 (and daily training) schedules - one switch per flow, readiness, independence,
no run on save, restart, duplicates, overlap, failures, Vietnam day boundaries, upgrade of stored settings."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import db, timeutil
from app import settings_service as ss
from app.jobs import flows, runner
from app.jobs.scheduler import Scheduler, plan
from app.timeutil import VN_TZ

VN = timezone(timedelta(hours=7))


def _freeze(dt):
    timeutil.set_now_override(lambda: dt)


def _sched_row():
    with db.read() as c:
        r = db.one(c, "SELECT value_json, updated_at FROM app_settings WHERE section='schedule'")
    return r


def _jobs(prefix=""):
    with db.read() as c:
        return db.rows(c, "SELECT idempotency_key, job_type, status, reason_code, trigger FROM job_runs "
                          "WHERE idempotency_key LIKE ? ORDER BY rowid", (prefix + "%",))


def _bq_ready_production():
    from test_v116 import _bq_ready, _hist_production      # tests/ is on sys.path
    fake = _bq_ready()
    _hist_production(fake)          # production enabled + full-period validation passed (fake BigQuery)
    return fake


# ------------------------------------------------------------------ defaults and upgrade of stored settings
def test_defaults_d1_and_d0_off_training_keeps_the_old_global_switch():
    s = ss.ScheduleSettings()
    assert (s.d1_enabled, s.d0_enabled, s.train_enabled) == (False, False, True)
    # settings stored by 1.1.7 (no per-flow keys): nothing that was OFF becomes ON
    old_on = ss.ScheduleSettings.model_validate({"enabled": True, "d0_times": ["08:00"]})
    old_off = ss.ScheduleSettings.model_validate({"enabled": False, "d0_times": ["08:00"]})
    assert (old_on.d1_enabled, old_on.d0_enabled, old_on.train_enabled) == (False, False, True)
    assert (old_off.d1_enabled, old_off.d0_enabled, old_off.train_enabled) == (False, False, False)


def test_reading_schedules_writes_nothing_and_keeps_job_history(client):
    with db.tx() as c:          # a schedule section exactly as 1.1.7 stored it + an existing job row
        c.execute("INSERT OR REPLACE INTO app_settings(section, value_json, updated_at) VALUES ('schedule', ?, 'x')",
                  (json.dumps({"enabled": True, "d0_times": ["08:00", "10:00"], "train_time": "07:00"}),))
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) "
                  "VALUES ('J-OLD', 'D0_SYNC', 'D0_SYNC:old', 'SCHEDULE', 'SUCCEEDED', '2026-10-14T01:00:00+00:00')")
    before = (_sched_row(), _jobs())
    r = client.get("/api/schedules").json()
    assert r["flows"]["d0"]["enabled"] is False and r["flows"]["d1"]["enabled"] is False
    assert r["flows"]["train"]["enabled"] is True and r["timezone"] == "Asia/Ho_Chi_Minh"
    assert r["data_window"]["start"] == "2026-01-01"
    assert (_sched_row(), _jobs()) == before                      # read-only: no setting or job changed


# ------------------------------------------------------------------ independence, readiness, validation
def test_saving_one_flow_never_changes_the_other(client, small_demo):
    s0 = ss.get("schedule").model_dump()
    r = client.put("/api/schedules/d1", json={"time": "02:30", "fallback_time": "06:30"})
    assert r.status_code == 200, r.text
    s1 = ss.get("schedule").model_dump()
    assert (s1["d1_signal_poll_start"], s1["d1_fallback_time"]) == ("02:30", "06:30")
    assert {k: v for k, v in s1.items() if not k.startswith("d1_")} == {k: v for k, v in s0.items() if not k.startswith("d1_")}
    r = client.put("/api/schedules/d0", json={"times": ["15:00", "09:00"]})       # D-0 stays OFF
    assert r.status_code == 200 and r.json()["config"]["times"] == ["09:00", "15:00"] and r.json()["enabled"] is False
    s2 = ss.get("schedule").model_dump()
    assert (s2["d1_signal_poll_start"], s2["d1_enabled"]) == ("02:30", False)
    # switching D-0 on (DEMO is ready) leaves D-1 and training untouched
    r = client.put("/api/schedules/d0", json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["enabled_at"]
    s3 = ss.get("schedule")
    assert (s3.d0_enabled, s3.d1_enabled, s3.train_enabled) == (True, False, s2["train_enabled"])
    r = client.put("/api/schedules/d0", json={"enabled": False})
    assert r.json()["enabled"] is False and r.json()["enabled_at"] is None


def test_a_flow_that_is_not_ready_cannot_be_switched_on_or_run(client):
    r = client.put("/api/schedules/d1", json={"enabled": True})                # DEMO source: nothing to sync
    assert r.status_code == 409 and r.json()["code"] == "FLOW_NOT_READY"
    assert [x["code"] for x in r.json()["params"]["reasons"]] == ["D1_SOURCE_NOT_BIGQUERY"]
    ss.update("general", {"active_source": "MANUAL_IMPORT"})
    r = client.put("/api/schedules/d0", json={"enabled": True})
    assert r.status_code == 409 and r.json()["params"]["reasons"][0]["code"] == "D0_SOURCE_MANUAL_IMPORT"
    assert client.post("/api/schedules/d0/run").status_code == 409
    ss.update("general", {"active_source": "BIGQUERY"})                          # BigQuery not production-ready
    v = client.get("/api/schedules").json()["flows"]["d0"]
    assert not v["readiness"]["ready"] and {"SOURCE_NOT_READY", "SQL_NOT_VALIDATED"} <= {x["code"] for x in v["readiness"]["reasons"]}
    assert client.put("/api/schedules/d0", json={"enabled": True}).status_code == 409
    s = ss.get("schedule")
    assert (s.d0_enabled, s.d1_enabled) == (False, False)                       # nothing was saved
    # switching OFF is always allowed, and the old SQL-page switch follows the same rule
    assert client.put("/api/schedules/d0", json={"enabled": False}).status_code == 200
    assert client.put("/api/sql-sources/d0/options", json={"schedule_enabled": True}).status_code == 409


def test_d1_with_a_ready_bigquery_source_is_independent_of_d0(client):
    _bq_ready_production()
    v = client.get("/api/schedules").json()["flows"]
    assert v["d1"]["readiness"]["ready"], v["d1"]["readiness"]
    assert client.put("/api/schedules/d1", json={"enabled": True}).status_code == 200
    s = ss.get("schedule")
    assert (s.d1_enabled, s.d0_enabled) == (True, False)
    v = client.get("/api/schedules").json()["flows"]
    assert v["d0"]["enabled"] is False and v["d0"]["next_runs"] == [] and v["d1"]["next_runs"]
    # on BigQuery the daily training waits for D-1: readiness says so when D-1 is OFF
    client.put("/api/schedules/d1", json={"enabled": False})
    t = client.get("/api/schedules/train").json()
    assert "TRAIN_WAITS_FOR_D1" in {x["code"] for x in t["readiness"]["reasons"]}


@pytest.mark.parametrize("flow,body", [("d0", {"times": ["25:00"]}), ("d0", {"times": ["8:00"]}),
                                        ("d1", {"time": "7:00"}), ("train", {"time": "24:00"}),
                                        ("d0", {"enabled": "yes"}), ("d1", {"unknown": 1}),
                                        ("d0", {"catchup_policy": "ALWAYS"})])
def test_invalid_values_are_refused_and_nothing_is_saved(client, flow, body):
    before = ss.get("schedule").model_dump()
    r = client.put(f"/api/schedules/{flow}", json=body)
    assert r.status_code == 422, (body, r.text)
    assert ss.get("schedule").model_dump() == before


def test_d0_cannot_be_on_without_times(client, small_demo):
    client.put("/api/schedules/d0", json={"enabled": True})
    assert client.put("/api/schedules/d0", json={"times": []}).status_code == 422
    assert ss.get("schedule").d0_times


def test_generic_settings_editor_cannot_switch_flows(client):
    cur = ss.get("schedule").model_dump()
    r = client.put("/api/settings/schedule", json={**cur, "d0_enabled": True})
    assert r.status_code == 409 and r.json()["code"] == "SCHEDULE_SWITCH_VIA_FLOW_API"
    r = client.put("/api/settings/schedule", json={**cur, "slot_grace_minutes": 30})
    assert r.status_code == 200 and r.json()["slot_grace_minutes"] == 30
    ss.save("schedule", {**ss.get("schedule").model_dump(), "train_enabled": False})
    r = client.post("/api/settings/schedule/reset")
    assert r.status_code == 200 and r.json()["train_enabled"] is False          # reset never switches a flow on


# ------------------------------------------------------------------ scheduler behaviour
def test_scheduler_plans_only_flows_that_are_on():
    now = datetime(2026, 10, 15, 10, 5, tzinfo=VN_TZ)
    base = ss.ScheduleSettings(train_enabled=False)
    with db.read() as c:
        assert plan(now, base, "BIGQUERY", None, c) == []
        only_d0 = plan(now, base.model_copy(update={"d0_enabled": True}), "BIGQUERY", None, c)
        only_d1 = plan(now, base.model_copy(update={"d1_enabled": True}), "BIGQUERY", None, c)
    assert only_d0 and {a["job_type"] for a in only_d0} == {"D0_SYNC"}
    assert only_d1 and {a["job_type"] for a in only_d1} == {"D1_SYNC"}


def test_switching_on_never_runs_anything_and_only_later_slots_fire(client, small_demo):
    t13 = datetime.now(VN_TZ).replace(hour=13, minute=0, second=0, microsecond=0)
    _freeze(t13)
    s = Scheduler()
    s.tick(t13, wait=True)                                    # D-0 OFF: no D0 job at all
    assert not _jobs("D0_SYNC")
    r = client.put("/api/schedules/d0", json={"enabled": True})   # switched on at 13:00
    assert r.status_code == 200 and not _jobs("D0_SYNC")          # saving runs nothing
    s.tick(t13 + timedelta(seconds=30), wait=True)            # 08/10/12 were before the switch: not missed, no catch-up
    assert not _jobs("D0_SYNC")
    t14 = t13 + timedelta(hours=1, minutes=5)
    _freeze(t14)
    s.tick(t14, wait=True)
    s.tick(t14 + timedelta(minutes=1), wait=True)             # same slot twice -> one job, one snapshot
    rows = _jobs("D0_SYNC")
    assert [(r["idempotency_key"], r["status"]) for r in rows] == [(f"D0_SYNC:{t14.date()}T14:00", "SUCCEEDED")]
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM d0_snapshots").fetchone()[0] == 1


def test_restart_restores_the_saved_state(client, small_demo):
    client.put("/api/schedules/d0", json={"enabled": True, "times": ["09:00"]})
    fresh = Scheduler()                                       # a new process: nothing in memory
    assert fresh.status()["loaded"] is None
    assert fresh.reload()["flows"] == {"d1": False, "d0": True, "train": True}
    now = datetime.now(VN_TZ).replace(hour=9, minute=1, second=0, microsecond=0)
    _freeze(now)
    ss.update("schedule", {"d0_enabled_at": None})             # switched on long ago
    acts = fresh.tick(now, wait=True)
    assert [a["key"] for a in acts if a["job_type"] == "D0_SYNC"] == [f"D0_SYNC:{now.date()}T09:00"]
    assert fresh.status()["loaded"]["flows"]["d0"] is True


def test_view_reports_scheduler_not_running_clearly(client, small_demo):
    r = client.put("/api/schedules/d0", json={"enabled": True}).json()   # tests run without the scheduler thread
    assert r["state"] == "ON_SCHEDULER_STOPPED" and r["warning"]["code"] == "SCHEDULER_NOT_RUNNING"
    assert r["saved"] is True


def test_retries_and_scheduled_rows_of_a_flow_switched_off_never_execute(small_demo, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "_handlers", lambda: {"D0_SYNC": lambda j, p: calls.append(j) or {"status": "SUCCEEDED"}})
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, created_at, "
                  "next_attempt_at) VALUES ('J-R', 'D0_SYNC', 'D0_SYNC:2026-10-15T10:00', 'SCHEDULE', 'RETRY_WAIT', 1, 4, ?, ?)",
                  (timeutil.now_iso(), "2000-01-01T00:00:00+00:00"))
    with db.read() as c:
        acts = plan(datetime.now(VN_TZ), ss.get("schedule"), "DEMO", None, c)
    assert not any(a["trigger"] == "RETRY" for a in acts)                    # D-0 OFF -> not re-planned
    r = runner.execute("D0_SYNC", "D0_SYNC:2026-10-15T10:00", "RETRY")
    assert r["status"] == "SKIPPED" and r["reason_code"] == "D0_SCHEDULE_DISABLED" and calls == []
    r = runner.execute("D0_SYNC", "D0_SYNC:manual-1", "MANUAL")               # a manual run is still possible
    assert r["status"] == "SUCCEEDED" and calls


def test_locks_and_failures_are_per_flow(client, small_demo, monkeypatch):
    assert runner.acquire_lock("job:D0_SYNC", 60)                            # a D-0 run in progress...
    r = runner.execute("TRAIN_PUBLISH", "TRAIN_PUBLISH:manual-x")            # ...does not block training
    assert r["status"] in ("SUCCEEDED", "SKIPPED") and r.get("note") != "LOCKED"
    assert runner.execute("D0_SYNC", "D0_SYNC:manual-y")["note"] == "LOCKED"  # but blocks a second D-0
    runner.release_lock("job:D0_SYNC")

    def boom(j, p):
        raise RuntimeError("source down (simulated)")
    monkeypatch.setattr(runner, "_handlers", lambda: {"D0_SYNC": boom})
    ss.update("schedule", {"max_attempts": 1})
    r = runner.execute("D0_SYNC", "D0_SYNC:manual-z")
    assert r["status"] == "FAILED"
    v = client.get("/api/schedules").json()["flows"]
    assert v["d0"]["last_run"]["status"] == "FAILED" and v["d0"]["last_run"]["error"]
    assert (v["train"]["last_run"] or {}).get("job_type", "TRAIN_PUBLISH") and v["d1"]["last_run"] is None
    assert v["train"]["last_run"]["status"] in ("SUCCEEDED", "SKIPPED")


# ------------------------------------------------------------------ Vietnam day boundaries of the two flows
@pytest.mark.parametrize("utc,yesterday,today", [((2026, 10, 15, 16, 59, 59), "2026-10-14", "2026-10-15"),
                                                 ((2026, 10, 15, 17, 0, 0), "2026-10-15", "2026-10-16")])
def test_d1_reads_closed_days_only_and_d0_reads_today_vn(client, utc, yesterday, today):
    from app import sync
    from app.bq import sql_sources
    from test_v116 import _daily
    _freeze(datetime(*utc, tzinfo=timezone.utc))
    fake = _bq_ready_production()
    fake.responses["daily"] = _daily(timeutil.today_vn() - timedelta(days=1), 4.0)
    r = sync.run_d1_sync("J-D1", fallback_mode=True)
    assert r["window_end"] == yesterday                                       # never today's partial day
    daily = [q for q in fake.queries if q[0].startswith("-- df:daily") and not q[1]["dry_run"]][-1]
    assert max(str(v) for _, t, v in daily[1]["params"] if t == "DATE") == yesterday
    from app.bq import source_tables
    from test_v116 import _d0_rows
    sql_sources.set_options("d0", mode="TABLE")
    assert source_tables.check("d0")["status"] == "PASSED"           # 1.2.1: a D-0 table runs only after its check
    fake.responses["d0"] = _d0_rows(timeutil.today_vn())
    sync.run_d0_snapshot("J-D0", None, False)
    d0q = [q for q in fake.queries if q[0].startswith("-- df:d0") and not q[1]["dry_run"]][-1]
    assert ("day", "DATE", timeutil.today_vn()) in d0q[1]["params"] and str(timeutil.today_vn()) == today
    with db.read() as c:
        snap = db.one(c, "SELECT order_date FROM d0_snapshots ORDER BY rowid DESC LIMIT 1")
        d1_days = [x[0] for x in c.execute("SELECT DISTINCT order_date FROM demand_daily")]
    assert snap["order_date"] == today and today not in d1_days               # D-0 never writes closed-day history
