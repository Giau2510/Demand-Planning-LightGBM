"""Automatic data flows and their schedules (1.1.8), one switch per flow:

  d1     D-1 sync: closed Vietnam days (up to yesterday) from BigQuery          job D1_SYNC     schedule.d1_enabled
  d0     D-0 snapshot: today's partial day (DEMO synthetic or BigQuery)          job D0_SYNC     schedule.d0_enabled
  train  daily training on closed days (candidate / first publication)          job TRAIN_PUBLISH schedule.train_enabled
  eod    1.2.6 end-of-day backup of the next 7 forecast days (local copy)       job EOD_FORECAST_SNAPSHOT schedule.eod_enabled
  close  1.2.6 actual close of the day at 23:59 + late-data revisions (local)   job ACTUAL_CLOSE  schedule.close_enabled

A flow can be switched ON only when it is READY for the active data source. Saving times never runs a job.
On BIGQUERY the daily training follows TODAY's D-1: a D1_SYNC that succeeded today (scheduled, retried or run by hand,
never a backfill) and loaded the closed days up to yesterday (1.2.1: a successful manual D-1 counts as well). The
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
from ..timeutil import VN_TZ, now_iso, now_vn, parse_iso, vn_slot

FLOWS = {"d1": {"job_type": "D1_SYNC", "flag": "d1_enabled"},
         "d0": {"job_type": "D0_SYNC", "flag": "d0_enabled"},
         "train": {"job_type": "TRAIN_PUBLISH", "flag": "train_enabled"},
         "eod": {"job_type": "EOD_FORECAST_SNAPSHOT", "flag": "eod_enabled"},
         "close": {"job_type": "ACTUAL_CLOSE", "flag": "close_enabled"}}
# editable fields per flow: API name -> schedule setting
FIELDS = {"d1": {"time": "d1_signal_poll_start", "fallback_time": "d1_fallback_time",
                 "poll_interval_minutes": "d1_poll_interval_minutes"},
          "d0": {"times": "d0_times", "catchup_policy": "d0_catchup_policy"},
          "train": {"time": "train_time", "catchup_policy": "train_catchup_policy"},
          "eod": {"time": "eod_time"},
          "close": {"time": "close_time"}}
TIMEZONE = "Asia/Ho_Chi_Minh"


def _check(flow: str) -> None:
    if flow not in FLOWS:
        raise AppError("BATCH_NOT_FOUND", 404, detail=f"unknown flow {flow}")


def _reason(code: str, detail: str | None = None) -> dict:
    return {**msg(code), "detail": detail}


def production_off_detail(conn) -> str:
    """Why BigQuery production mode is off, from the settings history: since when and which saved change turned it off
    (1.2.3 - a bare 'not ready' sent the user hunting; e.g. a mapping save always switches it off until re-validation)."""
    rows = conn.execute("SELECT value_json, changed_at, note FROM settings_history WHERE section='bigquery' "
                        "ORDER BY id DESC LIMIT 200").fetchall()
    off, was_on = None, False
    for value_json, at, note in rows:            # newest first: the oldest 'off' entry after the last 'on' one
        if json.loads(value_json).get("production_enabled"):
            was_on = True
            break
        off = (at, note)
    fix = "fix: BigQuery page -> run the full-period validation -> enable production mode"
    if off is None:
        return f"bigquery.production_enabled=false; {fix}"
    t = parse_iso(off[0])
    when = t.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M") if t else off[0]
    why = f"switched off by: {off[1] or 'a settings change'}" if was_on else "never enabled"
    return f"bigquery.production_enabled=false since {when} (Vietnam), {why}; {fix}"


def _bq_ready(conn, reasons: list) -> None:
    from ..bq import connector
    bq = ss.get("bigquery", conn)
    if not bq.production_enabled:
        reasons.append(_reason("SOURCE_NOT_READY", production_off_detail(conn)))
    elif not connector.validation_ok_for_current(conn):
        reasons.append(_reason("BQ_VALIDATION_REQUIRED", f"mapping {connector.mapping_hash(bq, conn)} has no passing "
                                                         "full-period validation; fix: BigQuery page -> validate"))


def source_blockers(conn=None) -> list[dict]:
    """1.2.3: what stops a MANUAL training on the active source right now - the BigQuery source state only. Never the
    schedule switches and never 'waits for today's D-1' (those decide when the SCHEDULE runs, not whether the user may
    train by hand). Checked before a manual job is created, so the user gets the exact reason at once instead of a job
    skipped after the data fingerprint was computed."""
    own = conn is None
    c = conn or db.connect()
    try:
        reasons: list[dict] = []
        if ss.get("general", c).active_source == "BIGQUERY":
            _bq_ready(c, reasons)
        return reasons
    finally:
        if own:
            c.close()


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
                    reasons.append(_reason("SOURCE_NOT_READY", production_off_detail(c)))
                # 1.2.1: the D-0 feed's own mapping + a BigQuery validation (SQL) / table check made for THAT mapping
                from ..bq import d0_feed
                r0, n0 = d0_feed.readiness(c)
                reasons += r0
                notes += n0
        elif flow in ("eod", "close"):
            # local copies of the active scope's own data: they need a dataset, never a BigQuery connection
            from ..data.demand import resolve_scope
            if flow == "close" and src == "MANUAL_IMPORT":
                reasons.append(_reason("CLOSE_SOURCE_MANUAL_IMPORT"))
            else:
                try:
                    resolve_scope(c)
                except AppError as e:
                    reasons.append(_reason(e.code, e.detail))
        else:
            from ..data.demand import resolve_scope
            try:
                resolve_scope(c)
            except AppError as e:
                reasons.append(_reason(e.code, e.detail))
            if src == "BIGQUERY":
                _bq_ready(c, reasons)
                d1 = d1_success_today(c)          # on BigQuery the daily training follows today's D-1
                if d1:
                    notes.append(_reason("D1_TODAY_SUCCEEDED", f"{d1['id']} ({d1['trigger']}, {d1['finished_vn']}, "
                                                                f"data to {d1['window_end']})"))
                elif not ss.get("schedule", c).d1_enabled:
                    reasons.append(_reason("TRAIN_WAITS_FOR_D1", "no successful D-1 today and the D-1 flow is OFF"))
                else:
                    notes.append(_reason("TRAIN_WAITING_FOR_TODAY_D1", _d1_today_state(c)))
        return {"ready": not reasons, "reasons": reasons, "notes": notes, "source": src}
    finally:
        if own:
            c.close()


# conditions that only decide WHEN the schedule runs a flow; a manual "run once now" is never refused for them
SCHEDULE_ONLY = {"train": ("TRAIN_WAITS_FOR_D1",)}


def _manual(flow: str, r: dict) -> dict:
    reasons = [x for x in r["reasons"] if x["code"] not in SCHEDULE_ONLY.get(flow, ())]
    return {**r, "ready": not reasons, "reasons": reasons}


def manual_readiness(flow: str, conn=None) -> dict:
    """1.2.3: can the user run this flow ONCE by hand now? The readiness of the flow without the schedule-only
    conditions (training: 'waits for today's D-1', which depends on the D-1 switch)."""
    return _manual(flow, readiness(flow, conn))


def _vn_day_start_utc(now: datetime) -> str:
    from datetime import timezone
    return vn_slot(now.date(), "00:00").astimezone(timezone.utc).isoformat(timespec="seconds")


def d1_success_today(c, now: datetime | None = None) -> dict | None:
    """Today's D-1 load the training may follow: a D1_SYNC job that SUCCEEDED today (Vietnam day; scheduled, retried
    or manual) whose result is a regular load (not a backfill) ending yesterday. A manual run goes through the same
    completion-signal / sufficiency check as the scheduled one (sync.run_d1_sync), so it proves the same thing."""
    now = now or now_vn()
    yesterday = str(now.date() - timedelta(days=1))
    rows = db.rows(c, "SELECT id, idempotency_key, trigger, finished_at, result_json FROM job_runs WHERE "
                      "job_type='D1_SYNC' AND status='SUCCEEDED' AND finished_at>=? ORDER BY finished_at DESC, rowid DESC",
                   (_vn_day_start_utc(now),))
    for r in rows:
        res = (json.loads(r["result_json"] or "{}") or {}).get("result") or {}
        if res.get("backfill") or res.get("mode") == "BACKFILL" or str(res.get("window_end")) != yesterday:
            continue
        if res.get("status") not in (None, "SUCCEEDED"):
            continue
        fin = parse_iso(r["finished_at"])
        return {"id": r["id"], "key": r["idempotency_key"], "trigger": r["trigger"], "finished_at": r["finished_at"],
                "finished_vn": fin.astimezone(now.tzinfo).strftime("%H:%M") if fin and now.tzinfo else r["finished_at"],
                "window_end": res.get("window_end")}
    return None


def _d1_today_state(c, now: datetime | None = None) -> str:
    now = now or now_vn()
    r = db.one(c, "SELECT id, status, reason_code FROM job_runs WHERE idempotency_key=?",
               (f"D1_SYNC:{now.date().isoformat()}",))
    if not r:
        return "D-1 of today has not run yet"
    return f"{r['id']}: {r['status']}{' ' + r['reason_code'] if r['reason_code'] else ''}"


def _active_valid(src) -> bool:
    act = next((v for v in src.versions if v.id == src.active_version_id), None)
    return bool(act and (act.validation or {}).get("status") == "VALID")


def _times(flow: str, sched) -> list[str]:
    return {"d1": [sched.d1_signal_poll_start], "d0": list(sched.d0_times), "train": [sched.train_time],
            "eod": [sched.eod_time], "close": [sched.close_time]}[flow]


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
                                            "snapshot_id", "verdict", "forecast_run_id", "training_run_id",
                                            "business_date", "snapshot_status", "days_covered", "rows", "close_status",
                                            "revision")
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
                "timezone": TIMEZONE, "readiness": ready, "manual_readiness": _manual(flow, ready),
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
    """Manual run of one flow (same job and locks as the schedule); only when the flow is ready for a manual run."""
    _check(flow)
    r = manual_readiness(flow)
    if not r["ready"]:
        raise AppError("FLOW_NOT_READY", 409, detail="; ".join(x["code"] for x in r["reasons"]), reasons=r["reasons"])
    from ..api import background
    return background.submit(FLOWS[flow]["job_type"], {})
