"""Real job stages (no invented percentages). Each stage transition is stored on the job row."""
from __future__ import annotations

import json
import logging

from .. import db
from ..timeutil import now_iso

log = logging.getLogger("df.jobs")

# Stages that actually exist in the code paths (see ml/pipeline.py, sync.py). Order = display order.
STAGES = {
    "TRAIN_PUBLISH": ["QUEUED", "STARTED", "VALIDATING_DATA", "PREPARING_DATA", "BACKTESTING", "TRAINING",
                      "QUALITY_GATE", "FORECASTING", "PUBLISHING", "DONE"],
    "FORECAST_EXTEND": ["QUEUED", "STARTED", "VERIFYING_MODEL", "PREPARING_DATA", "FORECASTING", "PUBLISHING", "DONE"],
    "D0_SYNC": ["QUEUED", "STARTED", "SYNCING", "DONE"],
    "D1_SYNC": ["QUEUED", "STARTED", "SYNCING", "DONE"],
    "EOD_FORECAST_SNAPSHOT": ["QUEUED", "STARTED", "SNAPSHOTTING", "DONE"],
    "ACTUAL_CLOSE": ["QUEUED", "STARTED", "CLOSING", "DONE"],
}
TERMINAL_STAGES = ("DONE", "FAILED", "SKIPPED", "INTERRUPTED")


def set_stage(job_id: str | None, stage: str, message: str | None = None) -> None:
    if not job_id:
        return
    at = now_iso()
    with db.tx() as c:
        r = c.execute("SELECT stage_history_json FROM job_runs WHERE id=?", (job_id,)).fetchone()
        if r is None:
            return
        hist = json.loads(r[0] or "[]")
        hist.append({"stage": stage, "at": at, **({"message": message} if message else {})})
        c.execute("UPDATE job_runs SET stage=?, stage_updated_at=?, stage_history_json=? WHERE id=?",
                  (stage, at, json.dumps(hist), job_id))
    log.info("job stage", extra={"ctx": {"job_id": job_id, "stage": stage}})


def reporter(job_id: str | None):
    """Callable passed to long-running handlers: progress("TRAINING")."""
    return lambda stage, message=None: set_stage(job_id, stage, message)
