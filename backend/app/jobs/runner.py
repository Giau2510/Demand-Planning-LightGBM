"""Job execution: idempotency key, lease lock, timeout, retry with exponential backoff, structured history.
1.2.13: resource figures of every attempt (jobs/resources.py) stored with the job, a job thread that outlives its
timeout keeps its lock until it really ends, heavy jobs never run two at a time in this process, and a heavy job waits
(bounded retries) while the machine's commit headroom is below what the same job type measurably needed before."""
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

from . import progress, resources

log = logging.getLogger("df.jobs")
OWNER = f"pid{os.getpid()}-{secrets.token_hex(3)}"
# jobs that build the whole panel / train boosters: never two at the same time in this process (RAM of a desktop PC)
HEAVY_TYPES = ("TRAIN_PUBLISH", "FORECAST_EXTEND")
# memory guard: a heavy job starts when the commit headroom is at least this factor x the largest private-memory growth
# measured on the last runs of the same job type (no absolute threshold: the figure comes from this machine's own runs)
MEMORY_MARGIN = 1.25
MEMORY_HISTORY_RUNS = 10
_live: dict[str, tuple[str, bool, threading.Thread]] = {}     # job id -> (job type, heavy, thread) running in this process
_live_lock = threading.Lock()

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


def refresh_lock(name: str, ttl_seconds: int) -> None:
    with db.tx() as c:
        c.execute("UPDATE job_locks SET expires_at=? WHERE lock_name=? AND owner=?",
                  ((now_utc() + timedelta(seconds=ttl_seconds)).isoformat(), name, OWNER))


# ---------------------------------------------------------------- 1.2.13: live job threads, memory guard
def is_heavy(job_type: str, params: dict | None = None) -> bool:
    """Training / forecast extension, and a D-1 backfill of the history (a long range read and compared at once)."""
    return job_type in HEAVY_TYPES or (job_type == "D1_SYNC" and bool((params or {}).get("backfill_start")))


def live_jobs() -> list[dict]:
    """Job threads alive in this process (a timed-out thread stays listed until it really ends)."""
    with _live_lock:
        for jid in [j for j, (_t, _h, th) in _live.items() if not th.is_alive()]:
            _live.pop(jid, None)
        return [{"job_id": j, "job_type": t, "heavy": h} for j, (t, h, _th) in _live.items()]


def _busy_reason(job_type: str, heavy: bool) -> str | None:
    for j in live_jobs():
        if j["job_type"] == job_type:
            return f"{job_type} {j['job_id']} is still running"
        if heavy and j["heavy"]:
            return f"heavy job {j['job_type']} {j['job_id']} is running"
    return None


def memory_need_mb(job_type: str) -> float | None:
    """Largest private-memory growth (MB) measured on the last runs of this job type; None before the first measured run."""
    with db.read() as c:
        rows = db.rows(c, "SELECT result_json FROM job_runs WHERE job_type=? AND result_json LIKE '%\"resources\"%' "
                          "ORDER BY created_at DESC, rowid DESC LIMIT ?", (job_type, MEMORY_HISTORY_RUNS))
    growth = []
    for r in rows:
        try:
            g = resources.peak_growth_mb(json.loads(r["result_json"]).get("resources"))
        except (TypeError, ValueError):
            g = None
        if g:
            growth.append(g)
    return max(growth) if growth else None


def memory_check(job_type: str) -> dict:
    """OK / NO_BASELINE / PAGING_EXPECTED (runs; physical memory short, Windows pages other programs out) /
    INSUFFICIENT_MEMORY (the commit headroom - RAM + page file still free - is below the measured need x margin: the job
    would fail with an out-of-memory error, so it waits instead)."""
    need = memory_need_mb(job_type)
    snap = resources.snapshot()
    commit = None if snap.get("commit_avail") is None else round(snap["commit_avail"] / resources.MB, 1)
    phys = None if snap.get("phys_avail") is None else round(snap["phys_avail"] / resources.MB, 1)
    out = {"need_mb": need, "margin": MEMORY_MARGIN, "commit_avail_mb": commit, "phys_avail_mb": phys}
    if need is None:
        return {**out, "decision": "NO_BASELINE"}
    if commit is not None and commit < need * MEMORY_MARGIN:
        return {**out, "decision": "INSUFFICIENT_MEMORY"}
    if phys is not None and phys < need:
        return {**out, "decision": "PAGING_EXPECTED"}
    return {**out, "decision": "OK"}


def _reap(th: threading.Thread, lock: str, ttl: int, jid: str, job_type: str) -> None:
    """A job thread that outlived its timeout keeps the job type's lock (refreshed) until it ends; no second run of the
    same type starts meanwhile (two trainings at once would double the memory)."""
    while th.is_alive():
        th.join(60)
        if th.is_alive():
            try:
                refresh_lock(lock, ttl)
            except Exception:  # noqa: BLE001 - the in-process registry still blocks a second run
                log.warning("job lock refresh failed", exc_info=True, extra={"ctx": {"job_id": jid}})
    with _live_lock:
        _live.pop(jid, None)
    try:
        release_lock(lock)
    finally:
        log.warning("timed-out job thread ended", extra={"ctx": {"job_id": jid, "type": job_type}})


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
    heavy = is_heavy(job_type, params)
    busy = _busy_reason(job_type, heavy)
    lock = f"job:{job_type}"
    if busy or not acquire_lock(lock, sched.timeout_seconds + 120):
        if row["status"] == "PENDING":
            _update(row["id"], status="RETRY_WAIT", reason_code="LOCKED", error=busy,
                    next_attempt_at=(now_utc() + timedelta(seconds=60)).isoformat())
        return {**row, "note": "LOCKED", **({"busy": busy} if busy else {})}
    attempt = row["attempt"] + 1
    try:
        mcheck = memory_check(job_type) if heavy else None
    except Exception:  # noqa: BLE001 - a failed reading never blocks a job (nor leaves the lock taken)
        log.warning("memory check failed", exc_info=True, extra={"ctx": {"job_id": row["id"]}})
        mcheck = {"decision": "CHECK_FAILED"}
    if mcheck and mcheck["decision"] == "INSUFFICIENT_MEMORY":
        # not started: counted as an attempt so the waits stay bounded (retry backoff, then FAILED + alert)
        release_lock(lock)
        _update(row["id"], attempt=attempt, started_at=now_iso())
        log.warning("job deferred: not enough memory", extra={"ctx": {"job_id": row["id"], "type": job_type, **mcheck}})
        return _fail(row, attempt, sched, "INSUFFICIENT_MEMORY",
                     f"commit headroom {mcheck['commit_avail_mb']} MB < {MEMORY_MARGIN} x {mcheck['need_mb']} MB "
                     f"measured for {job_type}", result_json=_result_json(params, None, {"attempt": attempt,
                                                                                         "memory_check": mcheck}))
    _update(row["id"], status="RUNNING", attempt=attempt, started_at=now_iso(), error=None)
    log.info("job started", extra={"ctx": {"job_id": row["id"], "type": job_type, "key": key, "attempt": attempt}})
    if mcheck and mcheck["decision"] == "PAGING_EXPECTED":
        log.warning("job starts with little free physical memory", extra={"ctx": {"job_id": row["id"], **mcheck}})
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
    others = live_jobs()
    with _live_lock:
        _live[row["id"]] = (job_type, heavy, th)
    meter = resources.JobMeter()
    try:
        meter.start()
    except Exception:  # noqa: BLE001 - the job runs without figures rather than not at all
        log.warning("job meter not started", exc_info=True, extra={"ctx": {"job_id": row["id"]}})
    th.start()
    th.join(sched.timeout_seconds)
    alive = th.is_alive()
    try:
        res_info = {**meter.stop().result(), "attempt": attempt, "heavy": heavy,
                    "other_jobs": [f"{j['job_type']} {j['job_id']}" for j in others]}
    except Exception:  # noqa: BLE001
        res_info = {"attempt": attempt, "heavy": heavy, "readings": "FAILED"}
    if mcheck:
        res_info["memory_check"] = mcheck
    if alive:
        res_info["thread_alive_after_timeout"] = True
    else:
        with _live_lock:
            _live.pop(row["id"], None)
    # no forced gc / heap compaction after a job: measured on a copy of production (22/10/2026) it gave back 0 MB after a
    # training and 6 MB after a D-1 - the memory is returned by not keeping large data longer than needed instead
    _log_resources(row["id"], job_type, res_info)
    try:
        if alive:
            cancel_evt.set()
            return _fail(row, attempt, sched, "TIMEOUT", f"exceeded {sched.timeout_seconds}s",
                         result_json=_result_json(params, None, res_info))
        err = box.get("error")
        if err is None:
            res = box.get("result") or {}
            status = "SKIPPED" if res.get("status") == "SKIPPED" else "SUCCEEDED"
            _update(row["id"], status=status, finished_at=now_iso(), reason_code=res.get("reason_code"),
                    result_json=_result_json(params, res, res_info), next_attempt_at=None)
            log.info("job finished", extra={"ctx": {"job_id": row["id"], "status": status,
                                                    "reason": res.get("reason_code")}})
            return _row(row["id"])
        from ..sync import NotApplicable, Retryable, Wait
        if isinstance(err, NotApplicable):
            _update(row["id"], status="SKIPPED", finished_at=now_iso(), reason_code="NOT_APPLICABLE_FOR_SOURCE",
                    error=str(err)[:500], result_json=_result_json(params, None, res_info))
            return _row(row["id"])
        if isinstance(err, Wait):
            _update(row["id"], status="RETRY_WAIT", reason_code=err.code, attempt=row["attempt"],
                    next_attempt_at=(now_utc() + timedelta(seconds=err.seconds)).isoformat(),
                    result_json=_result_json(params, None, res_info))
            return _row(row["id"])
        if isinstance(err, Retryable):
            return _fail(row, attempt, sched, err.code, str(err), result_json=_result_json(params, None, res_info))
        if isinstance(err, AppError) and err.code in NEEDS_CONFIG_CODES:
            # Not an error: nothing to work on yet (e.g. no dataset at first start). Recorded, no ERROR alert.
            _update(row["id"], status="SKIPPED", finished_at=now_iso(), reason_code=err.code,
                    error=(err.detail or err.code)[:500], result_json=_result_json(params, None, res_info))
            log.info("job skipped (needs configuration)", extra={"ctx": {"job_id": row["id"], "code": err.code}})
            return _row(row["id"])
        if isinstance(err, AppError):
            return _fail(row, attempt, sched, err.code, err.detail or err.code,
                         retry=err.code in ("BQ_ERROR", "BQ_AUTH_MISSING"),
                         result_json=_result_json(params, None, res_info))
        log.error("job error", exc_info=err, extra={"ctx": {"job_id": row["id"]}})
        return _fail(row, attempt, sched, "JOB_ERROR", f"{type(err).__name__}: {err}",
                     result_json=_result_json(params, None, res_info))
    finally:
        if alive:   # the lock stays with the still running thread; released when it ends
            threading.Thread(target=_reap, args=(th, lock, sched.timeout_seconds + 120, row["id"], job_type),
                             name=f"reap-{row['id']}", daemon=True).start()
        else:
            release_lock(lock)


def _result_json(params: dict, result: dict | None, res_info: dict) -> str:
    return json.dumps({"params": params, **({"result": result} if result is not None else {}), "resources": res_info},
                      default=str)


def _log_resources(jid: str, job_type: str, r: dict) -> None:
    try:
        _log_resources_now(jid, job_type, r)
    except Exception:  # noqa: BLE001 - logging only
        pass


def _log_resources_now(jid: str, job_type: str, r: dict) -> None:
    pm, mm = r.get("private_mb") or {}, r.get("machine_mb") or {}
    log.info("job resources", extra={"ctx": {
        "job_id": jid, "type": job_type, "pid": r.get("pid"), "wall_s": r.get("wall_s"),
        "cpu_s": round((r.get("cpu_user_s") or 0) + (r.get("cpu_kernel_s") or 0), 1), "cpu_util_pct": r.get("cpu_util_pct"),
        "private_start_mb": pm.get("start"), "private_peak_mb": pm.get("peak"), "private_end_mb": pm.get("end"),
        "ws_peak_mb": (r.get("ws_mb") or {}).get("peak"), "page_faults": r.get("page_faults"),
        "io_read_mb": r.get("io_read_mb"), "io_write_mb": r.get("io_write_mb"),
        "phys_avail_min_mb": mm.get("phys_avail_min"), "commit_avail_min_mb": mm.get("commit_avail_min"),
        "memory_decision": (r.get("memory_check") or {}).get("decision"), "other_jobs": r.get("other_jobs") or None}})


def _fail(row: dict, attempt: int, sched, code: str, detail: str, retry: bool = True,
          result_json: str | None = None) -> dict:
    extra = {"result_json": result_json} if result_json is not None else {}
    if retry and attempt < sched.max_attempts:
        delay = min(sched.retry_base_seconds * (2 ** (attempt - 1)), sched.retry_max_seconds)
        _update(row["id"], status="RETRY_WAIT", reason_code=code, error=detail[:2000],
                next_attempt_at=(now_utc() + timedelta(seconds=delay)).isoformat(), **extra)
        log.warning("job retry scheduled", extra={"ctx": {"job_id": row["id"], "code": code, "delay_s": delay}})
    else:
        _update(row["id"], status="FAILED", reason_code=code, error=detail[:2000], finished_at=now_iso(),
                next_attempt_at=None, **extra)
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
