"""Manual job submission from the UI (runs in a background thread, tracked in job_runs)."""
from __future__ import annotations

import json
import secrets
import threading
import time

from .. import db
from ..jobs import runner
from ..messages import AppError
from ..timeutil import now_iso

ACTIVE = ("PENDING", "RUNNING")
# job types that must never run twice at the same time (they share the forecast tables)
EXCLUSIVE_GROUP = {"TRAIN_PUBLISH": ("TRAIN_PUBLISH", "FORECAST_EXTEND"),
                   "FORECAST_EXTEND": ("TRAIN_PUBLISH", "FORECAST_EXTEND")}


def submit(job_type: str, params: dict | None = None, wait: bool | None = None) -> dict:
    """Create a manual job and start it. If an equivalent job is already queued/running, return THAT job
    (flag already_active) instead of creating a duplicate - repeated clicks never start a second run."""
    if job_type not in runner.JOB_TYPES:
        raise AppError("BATCH_NOT_FOUND", 404, detail=job_type)
    if job_type == "TRAIN_PUBLISH":
        # 1.2.3: a manual training on a BigQuery source that is not ready is refused at once with the exact reason
        # (never a job skipped later); the schedule switches play no part in a manual run
        from ..jobs import flows
        blockers = flows.source_blockers()
        if blockers:
            raise AppError(blockers[0]["code"], 409, detail=blockers[0]["detail"], reasons=blockers)
    params = params or {}
    group = EXCLUSIVE_GROUP.get(job_type, (job_type,))
    with db.tx() as c:   # check + insert atomically (IMMEDIATE transaction)
        busy = db.one(c, f"SELECT * FROM job_runs WHERE job_type IN ({','.join('?' * len(group))}) "
                         "AND status IN ('PENDING','RUNNING') ORDER BY created_at DESC, rowid DESC LIMIT 1", group)
        if busy:
            return {**busy, "already_active": True}
        jid = db.new_id("JOB")
        key = f"{job_type}:MANUAL:{secrets.token_hex(6)}"
        at = now_iso()
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, scheduled_for, status, attempt, "
                  "max_attempts, created_at, result_json, stage, stage_updated_at, stage_history_json) "
                  "VALUES (?,?,?, 'MANUAL', NULL, 'PENDING', 0, 1, ?, ?, 'QUEUED', ?, ?)",
                  (jid, job_type, key, at, json.dumps({"params": params}), at,
                   json.dumps([{"stage": "QUEUED", "at": at}])))
    t = threading.Thread(target=runner.execute, args=(job_type, key, "MANUAL", None, params), daemon=True,
                         name=f"manual-{jid}")
    t.start()
    if wait or (wait is None and SYNC_MODE):
        t.join()
    else:
        time.sleep(0.05)
    with db.read() as c:
        return {**db.one(c, "SELECT * FROM job_runs WHERE id=?", (jid,)), "already_active": False}


# Tests set this to True so manual jobs finish before the HTTP response returns.
SYNC_MODE = False
