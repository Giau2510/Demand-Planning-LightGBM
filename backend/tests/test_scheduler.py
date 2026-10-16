import json
from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app import settings_service as ss
from app import timeutil
from app.jobs import runner
from app.jobs.scheduler import Scheduler, plan
from app.timeutil import VN_TZ


def _freeze(dt_vn: datetime):
    timeutil.set_now_override(lambda: dt_vn)


def _jobs():
    with db.read() as c:
        return {r["idempotency_key"]: r for r in db.rows(c, "SELECT * FROM job_runs")}


def test_d0_slot_runs_within_grace_and_creates_snapshot(small_demo):
    ss.update("schedule", {"d0_enabled": True})          # 1.1.8: every flow has its own switch, D-0 is OFF by default
    now = datetime.now(VN_TZ).replace(hour=10, minute=5, second=0, microsecond=0)
    _freeze(now)
    s = Scheduler()
    s.tick(now, wait=True)
    jobs = _jobs()
    k10 = f"D0_SYNC:{now.date()}T10:00"
    k08 = f"D0_SYNC:{now.date()}T08:00"
    assert jobs[k10]["status"] == "SUCCEEDED"
    assert jobs[k08]["status"] == "SKIPPED" and jobs[k08]["reason_code"] == "MISSED_SLOT_NO_BACKFILL"
    with db.read() as c:
        snaps = db.rows(c, "SELECT * FROM d0_snapshots")
    assert len(snaps) == 1 and snaps[0]["is_catch_up"] == 0 and snaps[0]["data_source"] == "DEMO"
    # running the tick again never re-runs a succeeded slot
    s.tick(now + timedelta(minutes=1), wait=True)
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM d0_snapshots").fetchone()[0] == 1


def test_catch_up_after_restart_is_single_and_not_backdated(small_demo):
    ss.update("schedule", {"d0_enabled": True})
    # app was off all morning: started at 13:00 (slots 08,10,12 missed)
    now = datetime.now(VN_TZ).replace(hour=13, minute=0, second=0, microsecond=0)
    _freeze(now)
    Scheduler().tick(now, wait=True)
    jobs = _jobs()
    skipped = [k for k, r in jobs.items() if k.startswith("D0_SYNC") and r["status"] == "SKIPPED"]
    assert len(skipped) == 3
    catch = jobs[f"D0_SYNC:{now.date()}:CATCHUP"]
    assert catch["status"] == "SUCCEEDED" and catch["trigger"] == "CATCH_UP"
    with db.read() as c:
        snaps = db.rows(c, "SELECT * FROM d0_snapshots")
    assert len(snaps) == 1                                   # no fake snapshots for 08:00 / 10:00
    assert snaps[0]["is_catch_up"] == 1
    assert snaps[0]["snapshot_at"].startswith(now.astimezone(timezone.utc).isoformat()[:16])  # real read time
    assert snaps[0]["scheduled_slot"].startswith(f"{now.date()}T12:00")


def test_missed_whole_days_recorded_as_skipped(small_demo):
    now = datetime.now(VN_TZ).replace(hour=7, minute=30, second=0, microsecond=0)
    last = now - timedelta(days=3)
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES ('scheduler_heartbeat', ?, 'x')",
                  (json.dumps({"at": last.isoformat()}),))
    _freeze(now)
    ss.update("schedule", {"d0_enabled": True, "d1_enabled": True})
    with db.read() as c:
        acts = plan(now, ss.get("schedule"), "DEMO", last, c)
    missed = [a for a in acts if a["action"] == "skip" and a["reason"] == "MISSED_SLOT_NO_BACKFILL"]
    assert len(missed) >= 12   # 2 full days x 6 D0 slots (+ D1/TRAIN)
    assert not any(a["action"] == "run" and a["job_type"] == "D0_SYNC" for a in acts)


def test_d1_not_applicable_for_demo_and_training_waits_for_d1_on_bigquery():
    now = datetime.now(VN_TZ).replace(hour=7, minute=5, second=0, microsecond=0)
    sched = ss.get("schedule").model_copy(update={"d1_enabled": True})
    with db.read() as c:
        acts = plan(now, sched, "DEMO", None, c)
        d1 = [a for a in acts if a["job_type"] == "D1_SYNC"]
        assert d1 and d1[0]["action"] == "skip" and d1[0]["reason"] == "NOT_APPLICABLE_FOR_SOURCE"
        assert any(a["job_type"] == "TRAIN_PUBLISH" and a["action"] == "run" for a in acts)
        acts_bq = plan(now, sched, "BIGQUERY", None, c)
    assert not any(a["job_type"] == "TRAIN_PUBLISH" for a in acts_bq)     # waits for D-1 success
    assert any(a["job_type"] == "D1_SYNC" and a["action"] == "run" for a in acts_bq)


def test_idempotency_key_prevents_duplicate_runs(small_demo):
    r1 = runner.execute("D0_SYNC", "D0_SYNC:test-key")
    r2 = runner.execute("D0_SYNC", "D0_SYNC:test-key")
    assert r1["status"] == "SUCCEEDED" and r2["note"] == "ALREADY_SUCCEEDED"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM d0_snapshots").fetchone()[0] == 1


def test_lock_prevents_overlap(small_demo):
    assert runner.acquire_lock("job:D0_SYNC", 60)
    r = runner.execute("D0_SYNC", "D0_SYNC:locked")
    assert r["note"] == "LOCKED"
    assert _jobs()["D0_SYNC:locked"]["status"] == "RETRY_WAIT"
    runner.release_lock("job:D0_SYNC")
    r = runner.execute("D0_SYNC", "D0_SYNC:locked")
    assert r["note"] == "WAITING"           # respects next_attempt_at


def test_retry_exponential_backoff_then_failed_with_alert(monkeypatch):
    ss.update("schedule", {"max_attempts": 3, "retry_base_seconds": 60, "retry_max_seconds": 1000})
    calls = {"n": 0}

    def boom(job_id, params):
        calls["n"] += 1
        raise RuntimeError("source down")
    monkeypatch.setattr(runner, "_handlers", lambda: {"D0_SYNC": boom})
    t0 = datetime.now(timezone.utc)
    r = runner.execute("D0_SYNC", "D0_SYNC:retry")
    assert r["status"] == "RETRY_WAIT" and r["attempt"] == 1
    d1 = (timeutil.parse_iso(r["next_attempt_at"]) - t0).total_seconds()
    _freeze(timeutil.parse_iso(r["next_attempt_at"]) + timedelta(seconds=1))
    r = runner.execute("D0_SYNC", "D0_SYNC:retry")
    d2 = (timeutil.parse_iso(r["next_attempt_at"]) - timeutil.now_utc()).total_seconds()
    assert r["attempt"] == 2 and 55 <= d1 <= 65 and 115 <= d2 <= 125
    _freeze(timeutil.parse_iso(r["next_attempt_at"]) + timedelta(seconds=1))
    r = runner.execute("D0_SYNC", "D0_SYNC:retry")
    assert r["status"] == "FAILED" and r["attempt"] == 3 and calls["n"] == 3
    with db.read() as c:
        assert db.one(c, "SELECT * FROM alerts WHERE code='RETRIES_EXHAUSTED'")


def test_manual_import_d0_is_skipped_not_faked():
    ss.update("general", {"active_source": "MANUAL_IMPORT"})
    r = runner.execute("D0_SYNC", "D0_SYNC:manual")
    assert r["status"] == "SKIPPED" and r["reason_code"] == "NOT_APPLICABLE_FOR_SOURCE"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM d0_snapshots").fetchone()[0] == 0


def test_interrupted_jobs_recovered_at_startup():
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, created_at) "
                  "VALUES ('J1','D0_SYNC','k1','SCHEDULE','RUNNING',1,4,'x')")
        c.execute("INSERT INTO job_locks VALUES ('job:D0_SYNC','other','x','2999-01-01')")
    assert runner.recover_interrupted() == 1
    j = _jobs()["k1"]
    assert j["status"] == "RETRY_WAIT" and j["reason_code"] == "INTERRUPTED"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM job_locks").fetchone()[0] == 0


def test_timeout_marks_job_and_cancels(monkeypatch):
    import time
    ss.update("schedule", {"timeout_seconds": 30, "max_attempts": 1})
    monkeypatch.setattr(runner, "_handlers", lambda: {"D0_SYNC": lambda j, p: time.sleep(5)})
    monkeypatch.setattr(runner.ss, "get", lambda s, conn=None: (
        ss.ScheduleSettings(timeout_seconds=30, max_attempts=1).model_copy(update={"timeout_seconds": 1})
        if s == "schedule" else ss.SECTIONS[s]()))
    r = runner.execute("D0_SYNC", "D0_SYNC:slow")
    assert r["status"] == "FAILED" and r["reason_code"] == "TIMEOUT"


def test_training_job_through_runner(small_demo):
    r = runner.execute("TRAIN_PUBLISH", "TRAIN_PUBLISH:test")
    assert r["status"] == "SUCCEEDED" and r["reason_code"] == "FORECAST_PUBLISHED"
    r2 = runner.execute("TRAIN_PUBLISH", "TRAIN_PUBLISH:test2")
    assert r2["status"] == "SKIPPED" and r2["reason_code"] == "NO_NEW_DATA"
