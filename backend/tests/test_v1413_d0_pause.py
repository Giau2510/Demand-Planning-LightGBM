"""1.4.13 (owner order 14/11/2026, Task 10): maintenance pause of ONLY the D-0 slots (app/d0_pause.py).
Unit / integration with fakes on the isolated test database (DEMO source); the live database is never touched."""
import json
from datetime import datetime, timedelta

import pytest

from app import cli, d0_pause, db
from app import settings_service as ss
from app import timeutil
from app.jobs import runner
from app.jobs.scheduler import Scheduler, plan
from app.messages import AppError
from app.timeutil import VN_TZ

DAY = datetime(2026, 11, 16, tzinfo=VN_TZ)


def _at(h, m=0):
    return DAY.replace(hour=h, minute=m)


def _freeze(dt):
    timeutil.set_now_override(lambda: dt)


def _jobs():
    with db.read() as c:
        return {r["idempotency_key"]: r for r in db.rows(c, "SELECT * FROM job_runs")}


def _k(hhmm):
    return f"D0_SYNC:{DAY.date()}T{hhmm}"


def _history():
    return [h for h in ss.history("schedule", 50) if "D-0 maintenance pause" in (h["note"] or "")]


# ---------------------------------------------------------------- default: nothing changes
def test_default_is_not_paused_and_d0_runs_as_before(small_demo):
    s = ss.get("schedule")
    assert s.d0_paused_until == "" and s.d0_paused_by == ""
    assert d0_pause.status()["paused"] is False and d0_pause.status()["remaining_minutes"] == 0
    ss.update("schedule", {"d0_enabled": True})
    _freeze(_at(10, 5))
    Scheduler().tick(_at(10, 5), wait=True)
    jobs = _jobs()
    assert jobs[_k("10:00")]["status"] == "SUCCEEDED"
    assert jobs[_k("08:00")]["reason_code"] == "MISSED_SLOT_NO_BACKFILL"


# ---------------------------------------------------------------- paused: skipped, never backfilled
def test_paused_slots_are_skipped_not_backfilled_and_expiry_resumes(small_demo):
    ss.update("schedule", {"d0_enabled": True})
    _freeze(_at(10, 5))
    d0_pause.pause(2, "CAI-1413-20261115")           # until 12:05
    assert d0_pause.status()["paused"] is True
    sch = Scheduler()
    sch.tick(_at(10, 5), wait=True)
    jobs = _jobs()
    for hhmm in ("08:00", "10:00"):                  # the late 08:00 slot too: no catch-up of any slot
        assert jobs[_k(hhmm)]["status"] == "SKIPPED" and jobs[_k(hhmm)]["reason_code"] == "PAUSED_FOR_MAINTENANCE"
    assert jobs[_k("10:00")]["trigger"] == "SCHEDULE"
    assert not any(k.endswith(":CATCHUP") for k in jobs)
    _freeze(_at(12, 1))                              # still inside the pause
    sch.tick(_at(12, 1), wait=True)
    assert _jobs()[_k("12:00")]["reason_code"] == "PAUSED_FOR_MAINTENANCE"
    # after expiry: the slot that fell inside the pause is never run later, and no catch-up is made
    _freeze(_at(12, 10))
    assert d0_pause.status()["paused"] is False
    sch.tick(_at(12, 10), wait=True)
    jobs = _jobs()
    assert jobs[_k("12:00")]["status"] == "SKIPPED" and not any(k.endswith(":CATCHUP") for k in jobs)
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM d0_snapshots").fetchone()[0] == 0
    # the next slot runs normally, with no write needed to resume
    _freeze(_at(14, 3))
    sch.tick(_at(14, 3), wait=True)
    assert _jobs()[_k("14:00")]["status"] == "SUCCEEDED"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM d0_snapshots").fetchone()[0] == 1


def test_resume_now_lets_the_next_slot_run(small_demo):
    ss.update("schedule", {"d0_enabled": True})
    _freeze(_at(9, 0))
    d0_pause.pause(6, "owner")
    d0_pause.resume("owner")
    assert d0_pause.status()["paused"] is False
    _freeze(_at(10, 2))
    Scheduler().tick(_at(10, 2), wait=True)
    assert _jobs()[_k("10:00")]["status"] == "SUCCEEDED"


def test_runner_skips_a_scheduled_or_retried_d0_job_inside_the_pause(small_demo):
    ss.update("schedule", {"d0_enabled": True})
    _freeze(_at(11, 0))
    d0_pause.pause(1, "owner")
    row = runner.execute("D0_SYNC", "D0_SYNC:test-retry", "RETRY", None, {})
    assert row["status"] == "SKIPPED" and row["reason_code"] == "PAUSED_FOR_MAINTENANCE"


# ---------------------------------------------------------------- limits and validation
def test_longer_than_six_hours_is_refused_and_saves_nothing():
    _freeze(_at(10, 0))
    with pytest.raises(AppError) as e:
        d0_pause.pause(7, "owner")
    assert e.value.code == "D0_PAUSE_INVALID"
    for bad in (0, -1, "x"):
        with pytest.raises(AppError):
            d0_pause.pause(bad, "owner")
    far = (_at(10, 0) + timedelta(hours=7)).isoformat()
    with pytest.raises(ValueError):                  # the settings validator itself refuses it
        ss.update("schedule", {"d0_paused_until": far})
    with pytest.raises(ValueError):
        ss.update("schedule", {"d0_paused_until": "not a time"})
    with pytest.raises(AppError):
        d0_pause.pause(1, "x" * 61)
    assert ss.get("schedule").d0_paused_until == "" and _history() == []
    ss.update("schedule", {"d0_paused_until": (_at(10, 0) + timedelta(hours=6)).isoformat()})   # exactly 6 h is fine


def test_a_stored_value_is_always_readable(data_dir):
    """The limit is checked on save only: a clock that moved never makes the schedule unreadable."""
    _freeze(_at(10, 0))
    d0_pause.pause(6, "owner")
    _freeze(_at(10, 0) - timedelta(days=2))
    assert ss.get("schedule").d0_paused_by == "owner"


# ---------------------------------------------------------------- other flows never look at the pause
def test_other_flows_are_unaffected_while_paused(data_dir):
    now = _at(23, 59).replace(second=30)
    ss.update("schedule", {"d0_enabled": True, "d1_enabled": True, "eod_enabled": True, "close_enabled": True,
                           "refresh_enabled": True, "report_enabled": True,
                           "eod_enabled_at": _at(8).isoformat(), "close_enabled_at": _at(8).isoformat()})
    _freeze(now)

    def others():
        with db.read() as c:
            acts = plan(now, ss.get("schedule"), "DEMO", None, c, {})
        return [a for a in acts if a["job_type"] != "D0_SYNC"], [a for a in acts if a["job_type"] == "D0_SYNC"]

    base, d0_before = others()
    assert {"D1_SYNC", "EOD_FORECAST_SNAPSHOT", "ACTUAL_CLOSE"} <= {a["job_type"] for a in base}
    assert d0_before and all(a["reason"] != "PAUSED_FOR_MAINTENANCE" for a in d0_before if a["action"] == "skip")
    d0_pause.pause(6, "owner")
    paused, d0_after = others()
    assert paused == base                                           # D-1 / EOD / ACTUAL_CLOSE / refresh: identical
    assert d0_after and all(a["action"] == "skip" and a["reason"] == "PAUSED_FOR_MAINTENANCE" for a in d0_after)


def test_manual_d0_run_is_refused_while_paused_other_jobs_are_not(client, small_demo):
    _freeze(_at(10, 0))
    assert client.post("/api/d0/pause", json={"hours": 2, "by": "owner"}).status_code == 200
    r = client.post("/api/jobs/run", json={"job_type": "D0_SYNC"})
    assert r.status_code == 409 and r.json()["code"] == "D0_PAUSED" and r.json()["vi"] and r.json()["en"]
    r2 = client.post("/api/schedules/d0/run")                   # the schedule page's "run now" button
    assert r2.status_code == 409 and r2.json()["code"] == "D0_PAUSED"
    # a manual D-1 job is not looked at by the pause (it is not refused with D0_PAUSED)
    assert client.post("/api/jobs/run", json={"job_type": "ACTUAL_CLOSE"}).json().get("code") != "D0_PAUSED"
    client.post("/api/d0/resume", json={"by": "owner"})
    assert client.post("/api/jobs/run", json={"job_type": "D0_SYNC"}).json()["status"] == "SUCCEEDED"


# ---------------------------------------------------------------- API
def test_api_status_pause_resume_and_history(client):
    _freeze(_at(10, 0))
    st = client.get("/api/d0/pause").json()
    assert st["paused"] is False and st["until"] is None and st["max_hours"] == 6
    ok = client.post("/api/d0/pause", json={"hours": 3, "by": "CAI-1413"}).json()
    assert ok["paused"] is True and ok["by"] == "CAI-1413" and ok["until_vn"] == "16/11/2026 13:00"
    assert ok["remaining_minutes"] in (180, 181)
    assert client.get("/api/d0/pause").json()["paused"] is True
    assert client.post("/api/d0/pause", json={"hours": 7}).status_code == 422
    assert client.post("/api/d0/pause", json={"hours": 0}).json()["code"] == "D0_PAUSE_INVALID"
    assert client.post("/api/d0/pause", json={}).json()["remaining_minutes"] >= 359     # default = 6 h
    end = client.post("/api/d0/resume", json={"by": "owner"}).json()
    assert end["paused"] is False and end["by"] == ""
    notes = [h["note"] for h in _history()]
    assert len(notes) == 3 and "ended" in notes[0] and "by owner" in notes[0]      # newest first


def test_generic_settings_editor_never_changes_the_pause(client):
    _freeze(_at(10, 0))
    d0_pause.pause(2, "owner")
    body = ss.get("schedule").model_dump()
    body.update({"d0_paused_until": "", "d0_paused_by": "hacker"})
    client.put("/api/settings/schedule", json=body)
    assert ss.get("schedule").d0_paused_by == "owner" and d0_pause.status()["paused"] is True
    client.post("/api/settings/schedule/reset")
    assert d0_pause.status()["paused"] is True


# ---------------------------------------------------------------- CLI
def test_cli_pause_status_resume(capsys):
    _freeze(_at(10, 0))
    assert cli.main(["d0-status"]) == 0
    assert json.loads(capsys.readouterr().out)["paused"] is False
    assert cli.main(["d0-pause", "--hours", "2", "--by", "CAI-1413-20261115"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["paused"] and out["by"] == "CAI-1413-20261115" and out["until_vn"] == "16/11/2026 12:00"
    assert cli.main(["d0-status"]) == 0
    assert json.loads(capsys.readouterr().out)["remaining_minutes"] in (120, 121)
    assert cli.main(["d0-pause"]) == 0                               # default 6 hours
    assert json.loads(capsys.readouterr().out)["until_vn"] == "16/11/2026 16:00"
    assert cli.main(["d0-resume", "--by", "owner"]) == 0
    assert json.loads(capsys.readouterr().out)["paused"] is False
    assert len(_history()) == 3


@pytest.mark.parametrize("hours", ["0", "7", "-1"])
def test_cli_refuses_hours_outside_1_to_6(capsys, hours):
    assert cli.main(["d0-pause", "--hours", hours]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["code"] == "D0_PAUSE_INVALID"
    assert ss.get("schedule").d0_paused_until == "" and _history() == []
