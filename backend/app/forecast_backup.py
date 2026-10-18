"""End-of-day forecast backup (1.2.6): a full, independent copy of the next 7 forecast days, kept so that the Forecast &
actual history is not interrupted when no new valid forecast is published. Full description in docs/LICH-SU-FORECAST.md.

  business date  S = the Vietnam date of the scheduled slot (schedule.eod_time, default 23:55), never "today" at run time:
                 a retry or a catch-up after midnight still snapshots S.
  source         the official session (forecast_history_days) of the NEWEST run date <= S - the existing session choice
                 (newest valid session of its day). A running training / extension is waited for (its run date may be
                 S); no training, forecast or publish is ever started here.
  coverage       target dates S+1 .. S+7 (D+1 = run date + 1, as in the D+1 history). COMPLETE only when the source run
                 holds every one of its SKU x FC series on each of the 7 dates; the copy is then verified (rows and
                 total) in the same transaction. Otherwise INCOMPLETE / NO_SOURCE is recorded with the reason and NO
                 values (triggers, migration 0005): a partial snapshot can never be read as a complete one.
  idempotent     one snapshot per scope and business date (UNIQUE). A COMPLETE snapshot is never changed (trigger); a
                 later attempt only completes an INCOMPLETE / NO_SOURCE record of the same day.
  use            forecast_history.fallback_days: only for a run date WITHOUT an official session of its own.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta

from . import db
from .messages import AppError
from .timeutil import now_iso, now_vn, today_vn, vn_slot

log = logging.getLogger("df.eod")

N_DAYS = 7
TIMEZONE = "Asia/Ho_Chi_Minh"
COMPLETE, INCOMPLETE, NO_SOURCE = "COMPLETE", "INCOMPLETE", "NO_SOURCE"
FORECAST_JOBS = ("TRAIN_PUBLISH", "FORECAST_EXTEND")
WAIT_SECONDS = 300
WAIT_UNTIL = "06:00"        # waiting for a running forecast job stops at S+1 06:00 (Vietnam time); then it proceeds


def fingerprint(rows) -> str:
    """sha256 over the sorted lines target|sku|fc|horizon|repr(yhat)|method (order independent)."""
    lines = sorted("|".join((str(r[0]), str(r[1]), str(r[2]), str(r[3]), repr(float(r[4])), str(r[5]))) for r in rows)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def source_session(c, scope_key: str, business_date: str) -> dict | None:
    """Official session of the newest run date <= business_date (one pointer per run date: no tie)."""
    return db.one(c, "SELECT d.run_date, d.forecast_run_id, s.session_started_at, s.published_at, s.model_version, "
                     "s.training_run_id, s.data_as_of, r.n_series FROM forecast_history_days d "
                     "JOIN forecast_history_sessions s ON s.forecast_run_id = d.forecast_run_id "
                     "JOIN forecast_runs r ON r.id = d.forecast_run_id "
                     "WHERE d.scope_key=? AND d.run_date<=? ORDER BY d.run_date DESC LIMIT 1", (scope_key, business_date))


def create(scope_key: str, data_source: str, business_date: str, job_id: str | None = None) -> dict:
    """One attempt for (scope, business date) in ONE immediate transaction (readers never see half a snapshot)."""
    day = date.fromisoformat(business_date)
    want = [str(day + timedelta(days=i)) for i in range(1, N_DAYS + 1)]
    with db.tx() as c:
        have = db.one(c, "SELECT * FROM forecast_eod_snapshots WHERE scope_key=? AND business_date=?",
                      (scope_key, business_date))
        if have and have["status"] == COMPLETE:
            return {**have, "already_complete": True}
        src = source_session(c, scope_key, business_date)
        values: list = []
        if not src:
            status, reason, missing = NO_SOURCE, "NO_VALID_FORECAST_SESSION", want
        else:
            counts = dict(c.execute("SELECT target_date, COUNT(*) FROM forecast_values WHERE run_id=? AND target_date "
                                    "BETWEEN ? AND ? GROUP BY target_date", (src["forecast_run_id"], want[0], want[-1])))
            missing = [d for d in want if counts.get(d, 0) != src["n_series"]]
            status, reason = ((INCOMPLETE, f"SOURCE_COVERS_{N_DAYS - len(missing)}_OF_{N_DAYS}_DAYS") if missing
                              else (COMPLETE, f"ALL_{N_DAYS}_DAYS"))
            if status == COMPLETE:
                values = c.execute("SELECT target_date, sku_id, fc_id, horizon_day, yhat, method FROM forecast_values "
                                   "WHERE run_id=? AND target_date BETWEEN ? AND ? ORDER BY target_date, sku_id, fc_id",
                                   (src["forecast_run_id"], want[0], want[-1])).fetchall()
        total = float(sum(v[4] for v in values)) if values else None
        at = now_iso()
        cols = {"data_source": data_source, "source_run_id": (src or {}).get("forecast_run_id"),
                "source_run_date": (src or {}).get("run_date"),
                "source_session_started_at": (src or {}).get("session_started_at"),
                "source_published_at": (src or {}).get("published_at"),
                "source_model_version": (src or {}).get("model_version"),
                "source_training_run_id": (src or {}).get("training_run_id"),
                "source_data_as_of": (src or {}).get("data_as_of"), "source_n_series": (src or {}).get("n_series"),
                "n_rows": len(values), "days_covered": N_DAYS - len(missing),
                "missing_dates_json": json.dumps(missing) if missing else None, "total_yhat": total,
                "values_sha256": fingerprint(values) if values else None, "status": status, "status_reason": reason,
                "timezone": TIMEZONE, "job_id": job_id, "updated_at": at}
        if have:     # an earlier INCOMPLETE / NO_SOURCE attempt of this day is completed or re-recorded, never doubled
            sid = have["id"]
            c.execute(f"UPDATE forecast_eod_snapshots SET {', '.join(f'{k}=?' for k in cols)}, attempts=attempts+1 "
                      "WHERE id=?", (*cols.values(), sid))
        else:
            sid = db.new_id("FES")
            row = {"id": sid, "scope_key": scope_key, "business_date": business_date, "first_target_date": want[0],
                   "last_target_date": want[-1], "n_days": N_DAYS, "created_at": at, **cols}
            c.execute(f"INSERT INTO forecast_eod_snapshots({', '.join(row)}) VALUES ({','.join('?' * len(row))})",
                      tuple(row.values()))
        if values:
            c.executemany("INSERT INTO forecast_eod_snapshot_values(snapshot_id, target_date, sku_id, fc_id, horizon_day, "
                          "yhat, method) VALUES (?,?,?,?,?,?,?)", [(sid, *v) for v in values])
            n, s = c.execute("SELECT COUNT(*), SUM(yhat) FROM forecast_eod_snapshot_values WHERE snapshot_id=?",
                             (sid,)).fetchone()
            if n != src["n_series"] * N_DAYS or abs(float(s) - total) > 1e-6 * max(1.0, abs(total)):
                raise AppError("EOD_SNAPSHOT_VERIFY_FAILED", 500,
                               detail=f"{sid}: stored {n} rows / {s}, expected {src['n_series'] * N_DAYS} / {total}")
        db.audit(c, "EOD_FORECAST_SNAPSHOT", "forecast_eod_snapshot", sid,
                 {"scope_key": scope_key, "business_date": business_date, "status": status, "reason": reason,
                  "source_run_id": cols["source_run_id"], "rows": len(values), "missing_dates": missing,
                  "attempt_of_existing": bool(have), "job_id": job_id})
        if status != COMPLETE:
            db.alert(c, "WARNING", "EOD_NO_VALID_FORECAST" if status == NO_SOURCE else "EOD_SNAPSHOT_INCOMPLETE",
                     {"business_date": business_date, "scope_key": scope_key, "source_run_id": cols["source_run_id"],
                      "missing_dates": missing}, "forecast_eod_snapshot", sid)
        out = db.one(c, "SELECT * FROM forecast_eod_snapshots WHERE id=?", (sid,))
    log.info("eod forecast snapshot", extra={"ctx": {k: out[k] for k in ("id", "business_date", "status", "n_rows",
                                                                           "source_run_id")}})
    return {**out, "already_complete": False}


def latest_due_day(hhmm: str) -> str:
    """Business date of the newest slot that has passed (a manual run never snapshots a day before its end-of-day slot)."""
    now = now_vn()
    return str(now.date() if now >= vn_slot(now.date(), hhmm) else now.date() - timedelta(days=1))


def run_job(job_id: str | None, params: dict) -> dict:
    """Job EOD_FORECAST_SNAPSHOT (scheduled, retried or manual). Writes only the snapshot tables (and records published
    runs missing from the history, which is idempotent); never trains, forecasts or publishes."""
    from . import forecast_history, settings_service as ss
    from .data.demand import resolve_scope
    from .sync import Wait
    sched = ss.get("schedule")
    business_date = params.get("business_date") or latest_due_day(sched.eod_time)
    day = date.fromisoformat(business_date)
    if day > today_vn():
        raise AppError("VALIDATION_ERROR", 422, detail=f"business date {business_date} is in the future")
    with db.read() as c:
        sc = resolve_scope(c)                 # NO_ACTIVE_DATASET etc. -> the runner records SKIPPED (needs config)
        busy = db.one(c, f"SELECT id, job_type, status FROM job_runs WHERE job_type IN ({','.join('?' * len(FORECAST_JOBS))}) "
                         "AND status IN ('PENDING','RUNNING') ORDER BY created_at DESC, rowid DESC LIMIT 1", FORECAST_JOBS)
    waited_for = None
    if busy:
        if now_vn() < vn_slot(day + timedelta(days=1), WAIT_UNTIL):
            raise Wait("WAITING_FOR_FORECAST_JOB", WAIT_SECONDS)     # its run may belong to this business date
        waited_for = busy["id"]                                       # still running after the limit: noted, not waited
    rec = forecast_history.reconcile()         # a published run whose recording failed is recorded first
    res = create(sc["scope_key"], sc["data_source"], business_date, job_id)
    out = {"business_date": business_date, "snapshot_id": res["id"], "snapshot_status": res["status"],
           "status_reason": res["status_reason"], "source_run_id": res["source_run_id"],
           "source_run_date": res["source_run_date"], "rows": res["n_rows"], "days_covered": res["days_covered"],
           "first_target_date": res["first_target_date"], "last_target_date": res["last_target_date"],
           "already_complete": res["already_complete"], "history_recorded_now": rec["missing"],
           "forecast_job_still_running": waited_for}
    if res["status"] == NO_SOURCE:
        return {**out, "status": "SKIPPED", "reason_code": "EOD_NO_VALID_FORECAST"}
    if res["status"] == INCOMPLETE:
        return {**out, "status": "INCOMPLETE", "reason_code": "EOD_SNAPSHOT_INCOMPLETE"}
    return {**out, "status": "SUCCEEDED", "reason_code": "ALREADY_COMPLETE" if res["already_complete"] else None}
