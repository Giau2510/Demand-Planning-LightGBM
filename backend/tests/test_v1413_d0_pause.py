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
    assert jobs[_k("08:00")]["reason_code"] == "MISSED_SLOT_NO_BACKFILL"     # missed BEFORE the pause: stays missed
    # 10:00 was still inside its grace when the pause was set: the scheduled run reaches the runner and is skipped there
    assert jobs[_k("10:00")]["status"] == "SKIPPED" and jobs[_k("10:00")]["reason_code"] == "PAUSED_FOR_MAINTENANCE"
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
    assert any(a["action"] == "run" for a in d0_before)                 # the usual single catch-up of the day
    d0_pause.pause(6, "owner")
    paused, d0_after = others()
    assert paused == base                                           # D-1 / EOD / ACTUAL_CLOSE / refresh: identical
    # every slot is before the window: stays MISSED, and no catch-up is queued while the pause is active
    assert d0_after and all(a["action"] == "skip" and a["reason"] == "MISSED_SLOT_NO_BACKFILL" for a in d0_after)


def test_manual_d0_run_is_refused_while_paused_other_jobs_are_not(client, small_demo):
    _freeze(_at(10, 0))
    assert client.post("/api/d0/pause", json={"hours": 2, "by": "owner"}).status_code == 200
    r = client.post("/api/jobs/run", json={"job_type": "D0_SYNC"})
    assert r.status_code == 409 and r.json()["code"] == "D0_PAUSED" and r.json()["vi"] and r.json()["en"]
    r2 = client.post("/api/schedules/d0/run")                   # the schedule page's "run now" button
    assert r2.status_code == 409 and r2.json()["code"] == "D0_PAUSED"
    # another job type is not looked at by the pause (it is not refused with D0_PAUSED)
    assert client.post("/api/jobs/run", json={"job_type": "ACTUAL_CLOSE"}).json().get("code") != "D0_PAUSED"
    client.post("/api/d0/resume", json={"by": "owner"})
    assert client.post("/api/jobs/run", json={"job_type": "D0_SYNC"}).json()["status"] == "SUCCEEDED"


# ---------------------------------------------------------------- slots of past days, retries, running job
def test_slot_inside_a_past_pause_is_recorded_paused_after_restart_next_day(small_demo):
    _freeze(_at(17, 0))
    sch = Scheduler()
    sch.tick(_at(17, 0), wait=True)                          # heartbeat of the evening (D-0 still off: no run yet)
    ss.update("schedule", {"d0_enabled": True, "d0_times": ["08:00", "18:00", "23:30"]})
    d0_pause.pause(6, "CAI-1413-20261115")                   # 17:00 - 23:00
    next_day = DAY + timedelta(days=1)
    now = next_day.replace(hour=9, minute=0)                 # the app was closed all night and starts again
    _freeze(now)
    assert d0_pause.status()["paused"] is False
    sch.tick(now, wait=True)
    jobs = _jobs()
    inside, after = _k("18:00"), _k("23:30")                 # 18:00 inside the pause, 23:30 after its expiry
    assert jobs[inside]["status"] == "SKIPPED" and jobs[inside]["reason_code"] == "PAUSED_FOR_MAINTENANCE"
    assert jobs[after]["reason_code"] == "MISSED_SLOT_NO_BACKFILL"
    assert f"D0_SYNC:{DAY.date()}:CATCHUP" not in jobs        # nothing of yesterday is caught up
    with db.read() as c:                                      # (only the usual single catch-up of the new day)
        snaps = db.rows(c, "SELECT scheduled_slot FROM d0_snapshots")
    assert all(x["scheduled_slot"].startswith(str(next_day.date())) for x in snaps)


def _gate_missed(jobs, day, hhmm):
    """The install gate's rule (scripts\ops\cai_1412.py missed(), R-I148 S2/S3) on the scheduler's own records: no
    job row; SKIPPED MISSED_SLOT_NO_BACKFILL; FAILED unless the day's CATCHUP SUCCEEDED after the slot -> counted as
    missed (reason text), else None. Rows are (status, reason_code, finished_at) like d0_slot_status."""
    def st(key):
        r = jobs.get(key)
        return (r["status"], r["reason_code"], r["finished_at"]) if r else None
    row, catchup = st(f"D0_SYNC:{day}T{hhmm}"), st(f"D0_SYNC:{day}:CATCHUP")
    if row is None:
        return "no job row"
    if row[0] == "SKIPPED" and row[1] == "MISSED_SLOT_NO_BACKFILL":
        return f"SKIPPED {row[1]}"
    if row[0] == "FAILED":
        slot = timeutil.vn_slot(day, hhmm)
        later = bool(catchup and catchup[0] == "SUCCEEDED" and catchup[2] and timeutil.parse_iso(catchup[2]) > slot)
        return None if later else "FAILED (no later catch-up SUCCEEDED)"
    return None


def test_pause_slots_after_midnight_restart_are_not_counted_missed_by_the_install_gate(small_demo):
    _freeze(_at(17, 0))
    sch = Scheduler()
    sch.tick(_at(17, 0), wait=True)
    ss.update("schedule", {"d0_enabled": True, "d0_times": ["08:00", "18:00", "20:00", "23:30"]})
    d0_pause.pause(6, "CAI-1413-20261115")                    # 17:00 - 23:00: slots 18:00 and 20:00 inside
    now = (DAY + timedelta(days=1)).replace(hour=0, minute=20)    # the app starts again after midnight
    _freeze(now)
    sch.tick(now, wait=True)
    jobs = _jobs()
    for hhmm in ("18:00", "20:00"):
        assert jobs[_k(hhmm)]["reason_code"] == "PAUSED_FOR_MAINTENANCE"
        assert _gate_missed(jobs, DAY.date(), hhmm) is None   # not a missed slot for the gate
    assert _gate_missed(jobs, DAY.date(), "23:30") == "SKIPPED MISSED_SLOT_NO_BACKFILL"   # after expiry: normal


def test_genuinely_missed_slot_without_pause_is_still_recorded_and_counted(small_demo):
    _freeze(_at(17, 0))
    sch = Scheduler()
    sch.tick(_at(17, 0), wait=True)
    ss.update("schedule", {"d0_enabled": True, "d0_times": ["08:00", "18:00", "23:30"]})
    now = (DAY + timedelta(days=1)).replace(hour=0, minute=20)    # app down all evening, no pause
    _freeze(now)
    sch.tick(now, wait=True)
    jobs = _jobs()
    for hhmm in ("18:00", "23:30"):
        assert jobs[_k(hhmm)]["reason_code"] == "MISSED_SLOT_NO_BACKFILL"
        assert _gate_missed(jobs, DAY.date(), hhmm) == "SKIPPED MISSED_SLOT_NO_BACKFILL"
    assert _gate_missed(jobs, DAY.date(), "09:00") == "no job row"


def test_missed_before_the_pause_stay_missed_and_are_counted_by_the_gate(small_demo):
    _freeze(_at(7, 0))
    sch = Scheduler()
    sch.tick(_at(7, 0), wait=True)                           # heartbeat of the early morning (D-0 off)
    ss.update("schedule", {"d0_enabled": True, "d0_times": ["08:00", "10:00", "12:00", "14:00"]})
    _freeze(_at(11, 0))                                      # app was down 08:00 and 10:00; pause set at 11:00 for 2 h
    d0_pause.pause(2, "owner")                               # window 11:00 - 13:00
    sch.tick(_at(11, 1), wait=True)
    jobs = _jobs()
    for hhmm in ("08:00", "10:00"):
        assert jobs[_k(hhmm)]["reason_code"] == "MISSED_SLOT_NO_BACKFILL"
        assert _gate_missed(jobs, DAY.date(), hhmm) == "SKIPPED MISSED_SLOT_NO_BACKFILL"
    assert not any(k.endswith(":CATCHUP") for k in jobs)     # no catch-up queued while paused
    _freeze(_at(12, 1))
    sch.tick(_at(12, 1), wait=True)
    jobs = _jobs()
    assert jobs[_k("12:00")]["reason_code"] == "PAUSED_FOR_MAINTENANCE"      # inside the window
    assert _gate_missed(jobs, DAY.date(), "12:00") is None
    _freeze(_at(13, 30))                                     # expired: the old missed slots are not caught up either
    sch.tick(_at(13, 30), wait=True)
    assert not any(k.endswith(":CATCHUP") for k in _jobs())


def test_windows_are_merged_extended_and_capped(data_dir):
    _freeze(_at(10, 0))
    d0_pause.pause(2, "owner")                               # 10:00 - 12:00
    _freeze(_at(11, 0))
    d0_pause.pause(3, "owner")                               # extends the open window: 10:00 - 14:00, no second one
    assert ss.get("schedule").d0_pause_windows == [[timeutil.iso(_at(10, 0)), timeutil.iso(_at(14, 0))]]
    d0_pause.resume("owner")                                 # closes it at 11:00
    _freeze(_at(11, 0))
    d0_pause.pause(1, "owner")                               # adjacent to the closed window: merged
    assert len(ss.get("schedule").d0_pause_windows) == 1
    # many separate windows: pruned to the last 15 days and capped at 50
    ss.update("schedule", {"d0_pause_windows": []})
    for i in range(60):
        _freeze(_at(0, 0) + timedelta(hours=8 * i))
        d0_pause.pause(1, "owner")
    ws = ss.get("schedule").d0_pause_windows
    assert len(ws) <= 50
    assert all(timeutil.parse_iso(w[1]) > timeutil.parse_iso(ws[-1][1]) - timedelta(days=16) for w in ws)


def test_resume_ends_the_window_so_later_slots_are_not_paused(small_demo):
    ss.update("schedule", {"d0_enabled": True})
    _freeze(_at(9, 0))
    d0_pause.pause(6, "owner")
    _freeze(_at(11, 0))
    d0_pause.resume("owner")
    w = ss.get("schedule").d0_pause_windows
    assert len(w) == 1 and timeutil.parse_iso(w[0][1]) == _at(11, 0)
    sched = ss.get("schedule")
    assert d0_pause.in_window(sched, _at(10, 0)) and not d0_pause.in_window(sched, _at(12, 0))


def test_retry_wait_d0_job_does_not_run_inside_the_pause_even_when_manual(small_demo):
    ss.update("schedule", {"d0_enabled": True})
    _freeze(_at(11, 0))
    row, _c = runner.get_or_create("D0_SYNC", "D0_SYNC:MANUAL:retrywait", "MANUAL", None, {}, 4)
    runner._update(row["id"], status="RETRY_WAIT", reason_code="LOCKED", next_attempt_at=(_at(10, 0)).isoformat())
    d0_pause.pause(1, "owner")
    out = runner.execute("D0_SYNC", "D0_SYNC:MANUAL:retrywait", "MANUAL", None, {})
    assert out["status"] == "SKIPPED" and out["reason_code"] == "PAUSED_FOR_MAINTENANCE"


def test_running_d0_job_is_not_cancelled_when_the_pause_is_set(small_demo):
    ss.update("schedule", {"d0_enabled": True})
    _freeze(_at(10, 5))
    row, _c = runner.get_or_create("D0_SYNC", _k("10:00"), "SCHEDULE", _at(10).isoformat(), {}, 4)
    runner._update(row["id"], status="RUNNING", started_at=_at(10, 1).isoformat())
    d0_pause.pause(2, "owner")
    Scheduler().tick(_at(10, 6), wait=True)
    assert _jobs()[_k("10:00")]["status"] == "RUNNING"       # left to finish; install gates wait for active jobs


def test_stored_pause_is_not_rejected_by_other_schedule_saves(data_dir):
    _freeze(_at(10, 0))
    d0_pause.pause(6, "owner")
    _freeze(_at(10, 0) - timedelta(days=2))                  # clock moved back: the stored pause is now > 6 h ahead
    ss.update("schedule", {"slot_grace_minutes": 25})        # an unrelated save still works
    assert ss.get("schedule").slot_grace_minutes == 25
    far = (_at(10, 0) + timedelta(hours=5)).isoformat()      # but CHANGING the value is checked against the limit
    with pytest.raises(ValueError):
        ss.update("schedule", {"d0_paused_until": far})


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


# ---------------------------------------------------------------- conditional resume (expect_by)
def test_resume_with_expect_by_only_ends_the_pause_set_by_the_same_text(client, capsys):
    _freeze(_at(10, 0))
    client.post("/api/d0/pause", json={"hours": 2, "by": "owner"})
    n = len(_history())
    r = client.post("/api/d0/resume", json={"by": "CAI-1413", "expect_by": "CAI-1413"})
    assert r.status_code == 409 and r.json()["code"] == "D0_PAUSE_NOT_OWNER" and r.json()["vi"] and r.json()["en"]
    assert d0_pause.status()["paused"] is True and d0_pause.status()["by"] == "owner" and len(_history()) == n
    assert cli.main(["d0-resume", "--by", "CAI-1413", "--expect-by", "CAI-1413"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["code"] == "D0_PAUSE_NOT_OWNER" and d0_pause.status()["paused"] is True
    ok = client.post("/api/d0/resume", json={"by": "owner", "expect_by": "owner"})
    assert ok.status_code == 200 and ok.json()["paused"] is False


def test_resume_without_expect_by_is_the_owners_manual_resume_and_cli_expect_by_matches(client, capsys):
    _freeze(_at(10, 0))
    client.post("/api/d0/pause", json={"hours": 2, "by": "CAI-1413"})
    assert client.post("/api/d0/resume", json={"by": "owner"}).json()["paused"] is False      # no expect_by: always
    assert cli.main(["d0-pause", "--hours", "1", "--by", "CAI-1413"]) == 0
    capsys.readouterr()
    assert cli.main(["d0-resume", "--by", "CAI-1413", "--expect-by", "CAI-1413"]) == 0
    assert json.loads(capsys.readouterr().out)["paused"] is False
    # nothing paused: expect_by is a harmless no-op (nothing to protect)
    assert client.post("/api/d0/resume", json={"expect_by": "someone"}).json()["paused"] is False
