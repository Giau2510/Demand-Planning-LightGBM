"""Job execution: idempotency key, lease lock, timeout, retry with exponential backoff, structured history."""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from datetime import timedelta

from .. import db
from .. import settings_service as ss
from ..messages import AppError
from ..timeutil import now_iso, now_utc, parse_iso

from . import progress

log = logging.getLogger("df.jobs")
OWNER = f"pid{os.getpid()}-{secrets.token_hex(3)}"

JOB_TYPES = ("D1_SYNC", "D0_SYNC", "TRAIN_PUBLISH", "FORECAST_EXTEND", "EOD_FORECAST_SNAPSHOT", "ACTUAL_CLOSE")
# each automatic flow has its own switch (1.1.8); FORECAST_EXTEND is manual only
FLOW_FLAG = {"D1_SYNC": "d1_enabled", "D0_SYNC": "d0_enabled", "TRAIN_PUBLISH": "train_enabled",
             "EOD_FORECAST_SNAPSHOT": "eod_enabled", "ACTUAL_CLOSE": "close_enabled"}
FLOW_OFF_CODE = {"D1_SYNC": "D1_SCHEDULE_DISABLED", "D0_SYNC": "D0_SCHEDULE_DISABLED", "TRAIN_PUBLISH": "TRAIN_SCHEDULE_DISABLED",
                 "EOD_FORECAST_SNAPSHOT": "EOD_SCHEDULE_DISABLED", "ACTUAL_CLOSE": "CLOSE_SCHEDULE_DISABLED"}
_STATUS_STAGE = {"RUNNING": "STARTED", "SUCCEEDED": "DONE", "FAILED": "FAILED", "SKIPPED": "SKIPPED",
                 "RETRY_WAIT": "WAITING_RETRY"}
# "Nothing to do until the user configures something" -> SKIPPED with a reason, never FAILED + ERROR alert.
NEEDS_CONFIG_CODES = ("NO_ACTIVE_DATASET", "ACTIVE_DATASET_INCONSISTENT", "BQ_NOT_CONFIGURED", "SOURCE_NOT_READY",
                      "SQL_NOT_VALIDATED", "OAUTH_NOT_CONFIGURED", "D0_SCHEDULE_DISABLED",
                      "D0_MAPPING_INCOMPLETE", "D0_REVALIDATE_REQUIRED", "D0_TABLE_NOT_CHECKED")


def _handlers():
    from ..ml.pipeline import extend_forecast, train_and_publish
    from ..sync import run_d0_snapshot, run_d1_sync

    def d0(job_id, params):
        progress.set_stage(job_id, "SYNCING")
        return run_d0_snapshot(job_id, params.get("scheduled_slot"), bool(params.get("is_catch_up")))

    def d1(job_id, params):
        progress.set_stage(job_id, "SYNCING")
        return run_d1_sync(job_id, params.get("fallback_mode"), params.get("backfill_start"), params.get("backfill_end"),
                           params.get("backfill_preview_id"))

    def train(job_id, params, cancel=None):
        return train_and_publish(job_id, force=bool(params.get("force")), cancel=cancel,
                                 progress=progress.reporter(job_id))

    def extend(job_id, params, cancel=None):
        return extend_forecast(params["run_id"], job_id, cancel=cancel, progress=progress.reporter(job_id))

    def eod(job_id, params):
        from ..forecast_backup import run_job
        progress.set_stage(job_id, "SNAPSHOTTING")
        return run_job(job_id, params)

    def close(job_id, params):
        from ..actual_close import run_job
        progress.set_stage(job_id, "CLOSING")
        return run_job(job_id, params)
    return {"D0_SYNC": d0, "D1_SYNC": d1, "TRAIN_PUBLISH": train, "FORECAST_EXTEND": extend,
            "EOD_FORECAST_SNAPSHOT": eod, "ACTUAL_CLOSE": close}


# ---------------------------------------------------------------- locks
def acquire_lock(name: str, ttl_seconds: int) -> bool:
    now = now_utc()
    with db.tx() as c:
        c.execute("DELETE FROM job_locks WHERE lock_name=? AND expires_at<?", (name, now.isoformat()))
        try:
            c.execute("INSERT INTO job_locks(lock_name, owner, acquired_at, expires_at) VALUES (?,?,?,?)",
                      (name, OWNER, now.isoformat(), (now + timedelta(seconds=ttl_seconds)).isoformat()))
            return True
        except Exception:
            return False


def release_lock(name: str) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM job_locks WHERE lock_name=? AND owner=?", (name, OWNER))


# ---------------------------------------------------------------- job rows
def get_or_create(job_type: str, key: str, trigger: str, scheduled_for: str | None, params: dict,
                  max_attempts: int) -> tuple[dict, bool]:
    with db.tx() as c:
        r = db.one(c, "SELECT * FROM job_runs WHERE idempotency_key=?", (key,))
        if r:
            return r, False
        jid = db.new_id("JOB")
        at = now_iso()
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, scheduled_for, status, attempt, "
                  "max_attempts, created_at, result_json, stage, stage_updated_at, stage_history_json) "
                  "VALUES (?,?,?,?,?, 'PENDING', 0, ?, ?, ?, 'QUEUED', ?, ?)",
                  (jid, job_type, key, trigger, scheduled_for, max_attempts, at, json.dumps({"params": params}),
                   at, json.dumps([{"stage": "QUEUED", "at": at}])))
        return db.one(c, "SELECT * FROM job_runs WHERE id=?", (jid,)), True


def record_skipped(job_type: str, key: str, trigger: str, scheduled_for: str | None, reason: str,
                   detail: str | None = None) -> dict:
    with db.tx() as c:
        r = db.one(c, "SELECT * FROM job_runs WHERE idempotency_key=?", (key,))
        if r:
            return r
        jid = db.new_id("JOB")
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, scheduled_for, status, attempt, "
                  "max_attempts, created_at, finished_at, reason_code, error) VALUES (?,?,?,?,?, 'SKIPPED', 0, 0, ?, ?, ?, ?)",
                  (jid, job_type, key, trigger, scheduled_for, now_iso(), now_iso(), reason, detail))
        return db.one(c, "SELECT * FROM job_runs WHERE id=?", (jid,))


def _update(jid: str, **cols) -> None:
    sets = ", ".join(f"{k}=?" for k in cols)
    with db.tx() as c:
        c.execute(f"UPDATE job_runs SET {sets} WHERE id=?", (*cols.values(), jid))
    if cols.get("status") in _STATUS_STAGE:
        progress.set_stage(jid, _STATUS_STAGE[cols["status"]], cols.get("reason_code"))


def execute(job_type: str, key: str, trigger: str = "MANUAL", scheduled_for: str | None = None,
            params: dict | None = None) -> dict:
    """Run (or retry) the job identified by `key`. Safe to call repeatedly: never runs a succeeded job twice."""
    params = params or {}
    sched = ss.get("schedule")
    row, created = get_or_create(job_type, key, trigger, scheduled_for, params, sched.max_attempts)
    if row["status"] in ("SUCCEEDED", "SKIPPED"):
        return {**row, "note": "ALREADY_SUCCEEDED"}
    if row["status"] == "RUNNING":
        return {**row, "note": "LOCKED"}
    if row["status"] == "FAILED":
        return {**row, "note": "RETRIES_EXHAUSTED"}
    if row["status"] == "RETRY_WAIT" and row["next_attempt_at"] and parse_iso(row["next_attempt_at"]) > now_utc():
        return {**row, "note": "WAITING"}
    flag = FLOW_FLAG.get(job_type)
    if flag and row["trigger"] != "MANUAL" and not getattr(sched, flag):
        # a scheduled / catch-up / retried run of a flow that is switched OFF never executes
        _update(row["id"], status="SKIPPED", finished_at=now_iso(), reason_code=FLOW_OFF_CODE[job_type],
                error=f"schedule.{flag}=false")
        return _row(row["id"])
    params = (json.loads(row["result_json"] or "{}").get("params") or params)
    lock = f"job:{job_type}"
    if not acquire_lock(lock, sched.timeout_seconds + 120):
        if row["status"] == "PENDING":
            _update(row["id"], status="RETRY_WAIT", reason_code="LOCKED",
                    next_attempt_at=(now_utc() + timedelta(seconds=60)).isoformat())
        return {**row, "note": "LOCKED"}
    attempt = row["attempt"] + 1
    _update(row["id"], status="RUNNING", attempt=attempt, started_at=now_iso(), error=None)
    log.info("job started", extra={"ctx": {"job_id": row["id"], "type": job_type, "key": key, "attempt": attempt}})
    cancel_evt = threading.Event()
    box: dict = {}

    def target():
        try:
            fn = _handlers()[job_type]
            if job_type in ("TRAIN_PUBLISH", "FORECAST_EXTEND"):
                box["result"] = fn(row["id"], params, cancel=cancel_evt.is_set)
            else:
                box["result"] = fn(row["id"], params)
        except BaseException as e:  # noqa: BLE001 - recorded below
            box["error"] = e

    th = threading.Thread(target=target, name=f"job-{row['id']}", daemon=True)
    th.start()
    th.join(sched.timeout_seconds)
    try:
        if th.is_alive():
            cancel_evt.set()
            return _fail(row, attempt, sched, "TIMEOUT", f"exceeded {sched.timeout_seconds}s")
        err = box.get("error")
        if err is None:
            res = box.get("result") or {}
            status = "SKIPPED" if res.get("status") == "SKIPPED" else "SUCCEEDED"
            _update(row["id"], status=status, finished_at=now_iso(), reason_code=res.get("reason_code"),
                    result_json=json.dumps({"params": params, "result": res}, default=str), next_attempt_at=None)
            log.info("job finished", extra={"ctx": {"job_id": row["id"], "status": status,
                                                    "reason": res.get("reason_code")}})
            return _row(row["id"])
        from ..sync import NotApplicable, Retryable, Wait
        if isinstance(err, NotApplicable):
            _update(row["id"], status="SKIPPED", finished_at=now_iso(), reason_code="NOT_APPLICABLE_FOR_SOURCE",
                    error=str(err)[:500])
            return _row(row["id"])
        if isinstance(err, Wait):
            _update(row["id"], status="RETRY_WAIT", reason_code=err.code, attempt=row["attempt"],
                    next_attempt_at=(now_utc() + timedelta(seconds=err.seconds)).isoformat())
            return _row(row["id"])
        if isinstance(err, Retryable):
            return _fail(row, attempt, sched, err.code, str(err))
        if isinstance(err, AppError) and err.code in NEEDS_CONFIG_CODES:
            # Not an error: nothing to work on yet (e.g. no dataset at first start). Recorded, no ERROR alert.
            _update(row["id"], status="SKIPPED", finished_at=now_iso(), reason_code=err.code,
                    error=(err.detail or err.code)[:500])
            log.info("job skipped (needs configuration)", extra={"ctx": {"job_id": row["id"], "code": err.code}})
            return _row(row["id"])
        if isinstance(err, AppError):
            return _fail(row, attempt, sched, err.code, err.detail or err.code,
                         retry=err.code in ("BQ_ERROR", "BQ_AUTH_MISSING"))
        log.error("job error", exc_info=err, extra={"ctx": {"job_id": row["id"]}})
        return _fail(row, attempt, sched, "JOB_ERROR", f"{type(err).__name__}: {err}")
    finally:
        release_lock(lock)


def _fail(row: dict, attempt: int, sched, code: str, detail: str, retry: bool = True) -> dict:
    if retry and attempt < sched.max_attempts:
        delay = min(sched.retry_base_seconds * (2 ** (attempt - 1)), sched.retry_max_seconds)
        _update(row["id"], status="RETRY_WAIT", reason_code=code, error=detail[:2000],
                next_attempt_at=(now_utc() + timedelta(seconds=delay)).isoformat())
        log.warning("job retry scheduled", extra={"ctx": {"job_id": row["id"], "code": code, "delay_s": delay}})
    else:
        _update(row["id"], status="FAILED", reason_code=code, error=detail[:2000], finished_at=now_iso(),
                next_attempt_at=None)
        with db.tx() as c:
            db.alert(c, "ERROR", "RETRIES_EXHAUSTED" if retry else code,
                     {"job_id": row["id"], "job_type": row["job_type"], "cause": code}, "job", row["id"])
        log.error("job failed", extra={"ctx": {"job_id": row["id"], "code": code}})
    return _row(row["id"])


def _row(jid: str) -> dict:
    with db.read() as c:
        return db.one(c, "SELECT * FROM job_runs WHERE id=?", (jid,))


def recover_interrupted() -> int:
    """At startup: RUNNING rows belong to a previous (crashed/stopped) process -> retry later or fail."""
    sched = ss.get("schedule")
    n = 0
    with db.tx() as c:
        c.execute("DELETE FROM job_locks")
        for r in db.rows(c, "SELECT * FROM job_runs WHERE status IN ('RUNNING','PENDING')"):
            n += 1
            hist = json.loads(r.get("stage_history_json") or "[]")
            hist.append({"stage": "INTERRUPTED", "at": now_iso(), "message": f"was {r.get('stage') or r['status']}"})
            limit = min(r["max_attempts"] or 1, sched.max_attempts)   # manual jobs (max 1) are never re-run
            if r["attempt"] < limit:
                c.execute("UPDATE job_runs SET status='RETRY_WAIT', reason_code='INTERRUPTED', next_attempt_at=?, "
                          "stage='INTERRUPTED', stage_updated_at=?, stage_history_json=? WHERE id=?",
                          (now_iso(), now_iso(), json.dumps(hist), r["id"]))
            else:
                c.execute("UPDATE job_runs SET status='FAILED', reason_code='INTERRUPTED', finished_at=?, "
                          "stage='INTERRUPTED', stage_updated_at=?, stage_history_json=? WHERE id=?",
                          (now_iso(), now_iso(), json.dumps(hist), r["id"]))
    return n
