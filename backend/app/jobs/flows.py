"""Automatic data flows and their schedules (1.1.8), one switch per flow:

  d1     D-1 sync: closed Vietnam days (up to yesterday) from BigQuery          job D1_SYNC     schedule.d1_enabled
  d0     D-0 snapshot: today's partial day (DEMO synthetic or BigQuery)          job D0_SYNC     schedule.d0_enabled
  train  daily training on closed days (candidate / first publication)          job TRAIN_PUBLISH schedule.train_enabled

A flow can be switched ON only when it is READY for the active data source. Saving times never runs a job. The
in-process scheduler reads these settings at every tick (nothing is registered in memory), so a restart restores the
saved state from the database; `Scheduler.reload()` confirms right after a save that the running scheduler has loaded
it. Readiness is computed from local state only (settings, saved checks): no call to Google/BigQuery.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .. import db
from .. import settings_service as ss
from ..messages import AppError, msg
from ..timeutil import now_iso, now_vn, vn_slot

FLOWS = {"d1": {"job_type": "D1_SYNC", "flag": "d1_enabled"},
         "d0": {"job_type": "D0_SYNC", "flag": "d0_enabled"},
         "train": {"job_type": "TRAIN_PUBLISH", "flag": "train_enabled"}}
# editable fields per flow: API name -> schedule setting
FIELDS = {"d1": {"time": "d1_signal_poll_start", "fallback_time": "d1_fallback_time",
                 "poll_interval_minutes": "d1_poll_interval_minutes"},
          "d0": {"times": "d0_times", "catchup_policy": "d0_catchup_policy"},
          "train": {"time": "train_time", "catchup_policy": "train_catchup_policy"}}
TIMEZONE = "Asia/Ho_Chi_Minh"


def _check(flow: str) -> None:
    if flow not in FLOWS:
        raise AppError("BATCH_NOT_FOUND", 404, detail=f"unknown flow {flow}")


def _reason(code: str, detail: str | None = None) -> dict:
    return {**msg(code), "detail": detail}


def _bq_ready(conn, reasons: list) -> None:
    from ..bq import connector
    bq = ss.get("bigquery", conn)
    if not bq.production_enabled:
        reasons.append(_reason("SOURCE_NOT_READY", "bigquery.production_enabled=false"))
    elif not connector.validation_ok_for_current(conn):
        reasons.append(_reason("BQ_VALIDATION_REQUIRED"))


def readiness(flow: str, conn=None) -> dict:
    """Can this flow do real work for the active data source right now? Local state only."""
    _check(flow)
    own = conn is None
    c = conn or db.connect()
    try:
        g = ss.get("general", c)
        src = g.active_source
        reasons: list[dict] = []
        notes: list[dict] = []
        if flow == "d1":
            if src != "BIGQUERY":
                reasons.append(_reason("D1_SOURCE_NOT_BIGQUERY", src))
            else:
                _bq_ready(c, reasons)
                hist = ss.get("sql_sources", c).history
                if hist.mode == "SQL" and not _active_valid(hist):
                    reasons.append(_reason("SQL_NOT_VALIDATED", "history"))
        elif flow == "d0":
            if src == "MANUAL_IMPORT":
                reasons.append(_reason("D0_SOURCE_MANUAL_IMPORT"))
            elif src == "DEMO":
                from ..data.demand import active_demo_batch
                if not active_demo_batch(c):
                    reasons.append(_reason("NO_ACTIVE_DATASET"))
                notes.append(_reason("D0_DEMO_SYNTHETIC"))
            else:
                bq = ss.get("bigquery", c)
                if not bq.production_enabled:
                    reasons.append(_reason("SOURCE_NOT_READY", "bigquery.production_enabled=false"))
                d0 = ss.get("sql_sources", c).d0
                if d0.mode == "SQL" and not _active_valid(d0):
                    reasons.append(_reason("SQL_NOT_VALIDATED", "d0: no D-0 SQL version validated by BigQuery"))
                if d0.mode == "TABLE":
                    from ..bq import source_tables
                    if not source_tables.is_ok("d0", c):     # 1.2.0: the D-0 table must have passed its check
                        reasons.append(_reason("D0_TABLE_NOT_CHECKED", bq.d0_table_id or "-"))
        else:
            from ..data.demand import resolve_scope
            try:
                resolve_scope(c)
            except AppError as e:
                reasons.append(_reason(e.code, e.detail))
            if src == "BIGQUERY":
                _bq_ready(c, reasons)
                if not ss.get("schedule", c).d1_enabled:     # on BigQuery the daily training waits for today's D-1
                    reasons.append(_reason("TRAIN_WAITS_FOR_D1"))
        return {"ready": not reasons, "reasons": reasons, "notes": notes, "source": src}
    finally:
        if own:
            c.close()


def _active_valid(src) -> bool:
    act = next((v for v in src.versions if v.id == src.active_version_id), None)
    return bool(act and (act.validation or {}).get("status") == "VALID")


def _times(flow: str, sched) -> list[str]:
    return {"d1": [sched.d1_signal_poll_start], "d0": list(sched.d0_times), "train": [sched.train_time]}[flow]


def next_runs(times: list[str], now: datetime, n: int) -> list[str]:
    out: list[str] = []
    d = now.date()
    while len(out) < n and d <= now.date() + timedelta(days=2):
        for t in sorted(times):
            slot = vn_slot(d, t)
            if slot > now:
                out.append(slot.isoformat())
                if len(out) >= n:
                    break
        d += timedelta(days=1)
    return out


def _job_rows(c, job_type: str, limit: int) -> list[dict]:
    rows = db.rows(c, "SELECT id, idempotency_key, trigger, scheduled_for, status, attempt, max_attempts, created_at, "
                      "started_at, finished_at, reason_code, error, result_json FROM job_runs WHERE job_type=? "
                      "ORDER BY created_at DESC, rowid DESC LIMIT ?", (job_type, limit))
    for r in rows:
        res = (json.loads(r.pop("result_json") or "{}") or {}).get("result") or {}
        r["summary"] = {k: res[k] for k in ("rows_read", "rows_valid", "series", "series_days_written",
                                            "series_days_new", "series_days_updated", "window_start", "window_end",
                                            "snapshot_id", "verdict", "forecast_run_id", "training_run_id")
                        if k in res}
        r["result_status"] = res.get("status")     # e.g. a training job that SUCCEEDED as a job but REJECTED/FAILED the model
        r["error"] = (r["error"] or "")[:300] or None
    return rows


def _scheduler_view() -> dict:
    from . import scheduler as sched_mod
    s = sched_mod.SCHEDULER
    if not s:
        return {"running": False, "last_tick": None, "loaded": None}
    st = s.status()
    return {"running": st["running"], "last_tick": st["last_tick"], "loaded": st.get("loaded")}


def flow_view(flow: str, conn=None, now: datetime | None = None, sched_view: dict | None = None) -> dict:
    _check(flow)
    own = conn is None
    c = conn or db.connect()
    try:
        sched = ss.get("schedule", c)
        now = now or now_vn()
        f = FLOWS[flow]
        on = bool(getattr(sched, f["flag"]))
        ready = readiness(flow, c)
        sv = sched_view if sched_view is not None else _scheduler_view()
        loaded = ((sv.get("loaded") or {}).get("flows") or {}).get(flow)
        if not on:
            state = "OFF"
        elif not sv.get("running"):
            state = "ON_SCHEDULER_STOPPED"
        elif not ready["ready"]:
            state = "ON_NOT_READY"
        elif loaded is not True:
            state = "ON_NOT_LOADED"
        else:
            state = "ON"
        rows = _job_rows(c, f["job_type"], 6)
        config = {k: getattr(sched, s) for k, s in FIELDS[flow].items()}
        return {"flow": flow, "job_type": f["job_type"], "enabled": on, "state": state, "config": config,
                "enabled_at": getattr(sched, f"{flow}_enabled_at"),
                "timezone": TIMEZONE, "readiness": ready,
                "next_runs": next_runs(_times(flow, sched), now, 3) if on else [],
                "planned_times_if_enabled": next_runs(_times(flow, sched), now, 3),
                "last_run": next((r for r in rows if r["status"] != "SKIPPED"), None),
                "last_skipped": next((r for r in rows if r["status"] == "SKIPPED"), None),
                "history": rows, "loaded_by_scheduler": loaded}
    finally:
        if own:
            c.close()


def overview() -> dict:
    from ..data.demand import data_window
    sv = _scheduler_view()
    now = now_vn()
    with db.read() as c:
        flows = {k: flow_view(k, c, now, sv) for k in FLOWS}
        win = data_window(c)
        g = ss.get("general", c)
        sched = ss.get("schedule", c)
    return {"timezone": TIMEZONE, "now_vn": now.isoformat(timespec="seconds"), "active_source": g.active_source,
            "data_window": {"start": win["start"], "end": win["end"]}, "scheduler": sv,
            "policy": {"slot_grace_minutes": sched.slot_grace_minutes, "max_attempts": sched.max_attempts,
                       "timeout_seconds": sched.timeout_seconds},
            "flows": flows}


def update_flow(flow: str, body: dict) -> dict:
    """Save ONE flow: its times and/or its switch. Never touches the other flows, never runs a job.
    Switching ON is refused (FLOW_NOT_READY) unless the flow is ready; switching OFF is always allowed."""
    _check(flow)
    unknown = set(body) - set(FIELDS[flow]) - {"enabled"}
    if unknown:
        raise AppError("VALIDATION_ERROR", 422, detail=f"{flow}: unknown fields {sorted(unknown)}")
    patch = {FIELDS[flow][k]: v for k, v in body.items() if k in FIELDS[flow]}
    flag = FLOWS[flow]["flag"]
    cur = ss.get("schedule")
    turning_on = body.get("enabled") is True
    if "enabled" in body:
        if not isinstance(body["enabled"], bool):
            raise AppError("VALIDATION_ERROR", 422, detail="enabled must be true or false")
        patch[flag] = body["enabled"]
        if body["enabled"] and not getattr(cur, flag):      # slots before this moment are never run or "missed"
            patch[f"{flow}_enabled_at"] = now_vn().isoformat(timespec="seconds")
        elif not body["enabled"]:
            patch[f"{flow}_enabled_at"] = None
    ss.ScheduleSettings.model_validate({**cur.model_dump(), **patch})     # validation errors -> 422, nothing saved
    if turning_on:
        r = readiness(flow)
        if not r["ready"]:
            raise AppError("FLOW_NOT_READY", 409, detail="; ".join(x["code"] for x in r["reasons"]),
                           reasons=r["reasons"])
    if not patch:
        return {**flow_view(flow), "saved": False}
    ss.update("schedule", patch, note=f"schedule {flow}: {', '.join(sorted(patch))} (UI)")
    with db.tx() as c:
        db.audit(c, "SCHEDULE_CHANGED", "schedule", flow, {"changes": patch, "previous": {
            k: getattr(cur, k) for k in patch}})
    from . import scheduler as sched_mod
    registered = None
    if sched_mod.SCHEDULER:
        registered = sched_mod.SCHEDULER.reload().get("flows", {}).get(flow)
    out = flow_view(flow)
    out["saved"] = True
    if out["state"] == "ON_SCHEDULER_STOPPED":     # saved, but nothing will run in this process: say it clearly
        out["warning"] = msg("SCHEDULER_NOT_RUNNING")
    out["registered"] = registered
    return out


def run_now(flow: str) -> dict:
    """Manual run of one flow (same job and locks as the schedule); only when the flow is ready."""
    _check(flow)
    r = readiness(flow)
    if not r["ready"]:
        raise AppError("FLOW_NOT_READY", 409, detail="; ".join(x["code"] for x in r["reasons"]), reasons=r["reasons"])
    from ..api import background
    return background.submit(FLOWS[flow]["job_type"], {})
