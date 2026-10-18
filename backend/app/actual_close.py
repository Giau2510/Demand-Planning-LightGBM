"""Actual close of the day at 23:59 (1.2.6). Full description in docs/LICH-SU-FORECAST.md.

  business date  the Vietnam date of the scheduled slot (schedule.close_time, default 23:59) - never the UTC date and
                 never "today" at run time: a retry or catch-up after midnight still closes that day. Closing a day
                 before its cut-off is refused.
  revision 1     CLOSE: an independent copy of the actual that the history shows for that day at the close, read with
                 the same rule (forecast_history.actual_context): the D-1 load of the day if any, else the latest
                 successful D0 snapshot. Only the SKU x FC rows present in the source are copied; an absent row is never
                 stored as 0, and a day without any actual is closed as CLOSED_NO_DATA (total NULL).
  status         CLOSED_VERIFIED only when the D-1 load of that day ran on the source's completion signal (the existing
                 rule for COMPLETE); a D0 read or a D-1 load without the signal is CLOSED_UNVERIFIED - "closed by the
                 schedule, needs verification" - never "complete". No completion signal is invented here.
  late data      reconcile(): when the actual of a closed day changes afterwards (D-1 load, reload, a later D0 read, the
                 completion signal), a new revision is appended with the previous total, the new total and the changed /
                 added / removed SKU x FC counts. Revisions are immutable and consecutive (triggers, migration 0005); runs
                 after each D-1 load, in each close job (last RECONCILE_DAYS days) and is idempotent.
The close never writes a forecast, the D+1 history or the actual sources, and never starts a sync, training or forecast.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta

from . import db
from .messages import AppError
from .timeutil import now_iso, now_vn, today_vn, vn_slot

log = logging.getLogger("df.close")

TIMEZONE = "Asia/Ho_Chi_Minh"
VERIFIED, UNVERIFIED, NO_DATA = "CLOSED_VERIFIED", "CLOSED_UNVERIFIED", "CLOSED_NO_DATA"
RECONCILE_DAYS = 14
WAIT_SECONDS = 60
WAIT_LIMIT = timedelta(hours=1)        # a D-0 read still running is waited for at most 1 h after the cut-off


def _sha(values: dict) -> str | None:
    if not values:
        return None
    lines = sorted(f"{s}|{f}|{q!r}" for (s, f), q in values.items())
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def cutoff(business_date: str, hhmm: str) -> str:
    """business_date hh:mm Vietnam time as the stored UTC timestamp."""
    from .timeutil import iso
    return iso(vn_slot(date.fromisoformat(business_date), hhmm))


def read_actual(c, scope_key: str, data_source: str, day: str) -> dict:
    """The actual the history shows for `day` right now (same source rule, without the close overlay)."""
    from . import forecast_history as fh
    return _actual(c, scope_key, day, fh.actual_context(c, scope_key, data_source, [day], closes=False)[day])


def _actual(c, scope_key: str, day: str, x: dict) -> dict:
    from . import forecast_history as fh
    if x["source"] == "D1":
        rows = c.execute("SELECT sku_id, fc_id, qty FROM demand_daily WHERE scope_key=? AND order_date=?", (scope_key, day))
        ref = x["as_of"]
    elif x["source"] == "D0":
        rows = c.execute("SELECT sku_id, fc_id, cumulative_qty FROM d0_snapshot_values WHERE snapshot_id=?",
                         (x["snapshot_id"],))
        ref = x["snapshot_id"]
    else:
        rows, ref = [], None
    values = {(s, f): float(q) for s, f, q in rows}
    if x["source"] is None:
        status, why = NO_DATA, x["reason"]
    elif x["status"] == fh.COMPLETE:
        status, why = VERIFIED, "COMPLETION_SIGNAL"
    else:
        status, why = UNVERIFIED, f"{x['source']}_NO_COMPLETION_SIGNAL"
    return {"source": x["source"], "source_ref": ref, "source_as_of": x["as_of"], "source_reason": x["reason"],
            "values": values, "sha": _sha(values), "status": status, "status_reason": why}


def _insert(c, scope_key: str, data_source: str, day: str, rev: int, kind: str, reason: str, cur: dict, hhmm: str,
            prev: dict | None, prev_values: dict | None, job_id: str | None) -> dict:
    vals = cur["values"]
    old = prev_values or {}
    both = set(vals) & set(old)
    cid = db.new_id("ACL")
    row = {"id": cid, "scope_key": scope_key, "data_source": data_source, "business_date": day, "revision": rev,
           "kind": kind, "reason": reason, "source": cur["source"], "source_ref": cur["source_ref"],
           "source_as_of": cur["source_as_of"], "source_reason": cur["source_reason"], "n_rows": len(vals),
           "total_qty": float(sum(vals.values())) if vals else None, "values_sha256": cur["sha"],
           "status": cur["status"], "status_reason": cur["status_reason"],
           "previous_id": (prev or {}).get("id"), "previous_total": (prev or {}).get("total_qty"),
           "n_changed": sum(1 for k in both if abs(vals[k] - old[k]) > 1e-9) if prev else None,
           "n_added": len(set(vals) - set(old)) if prev else None,
           "n_removed": len(set(old) - set(vals)) if prev else None,
           "cutoff_at": cutoff(day, hhmm), "closed_at": now_iso(), "timezone": TIMEZONE, "job_id": job_id}
    c.execute(f"INSERT INTO actual_closes({', '.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
    c.executemany("INSERT INTO actual_close_values(close_id, sku_id, fc_id, qty) VALUES (?,?,?,?)",
                  [(cid, s, f, q) for (s, f), q in sorted(vals.items())])
    db.audit(c, "ACTUAL_CLOSED" if rev == 1 else "ACTUAL_CLOSE_REVISED", "actual_close", cid,
             {k: row[k] for k in ("scope_key", "business_date", "revision", "reason", "source", "source_ref", "n_rows",
                                  "total_qty", "status", "previous_total", "n_changed", "n_added", "n_removed")})
    return row


def close_day(scope_key: str, data_source: str, business_date: str, hhmm: str = "23:59", job_id: str | None = None,
              reason: str = "SCHEDULED_CLOSE") -> dict:
    """Revision 1 of the day, once (UNIQUE scope + day + revision; the check and the insert share one immediate
    transaction, so two concurrent closes write one revision)."""
    with db.tx() as c:
        have = db.one(c, "SELECT * FROM actual_closes WHERE scope_key=? AND business_date=? AND revision=1",
                      (scope_key, business_date))
        if have:
            return {**have, "already_closed": True}
        cur = read_actual(c, scope_key, data_source, business_date)
        row = _insert(c, scope_key, data_source, business_date, 1, "CLOSE", reason, cur, hhmm, None, None, job_id)
        if cur["status"] == NO_DATA:
            db.alert(c, "WARNING", "ACTUAL_CLOSE_NO_DATA", {"business_date": business_date, "scope_key": scope_key,
                                                             "reason": cur["source_reason"]}, "actual_close", row["id"])
    log.info("actual closed", extra={"ctx": {k: row[k] for k in ("id", "business_date", "source", "n_rows", "status")}})
    return {**row, "already_closed": False}


def _why(prev: dict, cur: dict) -> str:
    if cur["source"] != prev["source"]:
        return {"D1": "D1_LOADED", "D0": "D0_LATE_READ"}.get(cur["source"], "SOURCE_HAS_NO_DATA")
    if cur["sha"] != prev["values_sha256"]:
        return "D1_RELOADED" if cur["source"] == "D1" else "D0_LATE_READ"
    return "COMPLETION_SIGNAL_CONFIRMED" if cur["status"] == VERIFIED else "STATUS_CHANGED"


def reconcile(scope_key: str, data_source: str, today: date | None = None, days: int = RECONCILE_DAYS,
              hhmm: str = "23:59", job_id: str | None = None) -> dict:
    """Append a revision for every closed day of the last `days` days whose actual (source, values or verification)
    differs from its latest revision. Idempotent: nothing changed -> nothing written."""
    from . import forecast_history as fh
    today = today or today_vn()
    same = lambda cur, prev: (cur["source"], cur["sha"], cur["status"]) == (prev["source"], prev["values_sha256"],  # noqa: E731
                                                                            prev["status"])
    with db.read() as c:          # one pass over the sources (one completion-signal scan), outside any write lock
        latest = {r["business_date"]: r for r in db.rows(
            c, "SELECT a.* FROM actual_closes a WHERE a.scope_key=? AND a.business_date BETWEEN ? AND ? AND a.revision = "
               "(SELECT MAX(b.revision) FROM actual_closes b WHERE b.scope_key = a.scope_key "
               "AND b.business_date = a.business_date)", (scope_key, str(today - timedelta(days=days)), str(today)))}
        ctx = fh.actual_context(c, scope_key, data_source, list(latest), today, closes=False) if latest else {}
        changed = [d for d in sorted(latest) if not same(_actual(c, scope_key, d, ctx[d]), latest[d])]
    out = {"checked": len(latest), "revised": []}
    for day in changed:
        with db.tx() as c:        # re-read under the write lock: the revision records what is committed now
            prev = db.one(c, "SELECT * FROM actual_closes WHERE scope_key=? AND business_date=? ORDER BY revision DESC "
                             "LIMIT 1", (scope_key, day))
            cur = read_actual(c, scope_key, data_source, day)
            if same(cur, prev):
                continue
            pv = {(s, f): q for s, f, q in c.execute("SELECT sku_id, fc_id, qty FROM actual_close_values WHERE close_id=?",
                                                     (prev["id"],))}
            row = _insert(c, scope_key, data_source, day, prev["revision"] + 1, "RECONCILIATION", _why(prev, cur), cur,
                          hhmm, prev, pv, job_id)
        out["revised"].append({k: row[k] for k in ("business_date", "revision", "reason", "previous_total", "total_qty",
                                                   "status")})
        log.info("actual close revised", extra={"ctx": out["revised"][-1]})
    return out


def reconcile_quietly(scope_key: str, data_source: str, context: str) -> dict | None:
    """After a D-1 load (display side, never fails the load)."""
    try:
        from . import settings_service as ss
        return reconcile(scope_key, data_source, hhmm=ss.get("schedule").close_time)
    except Exception:  # noqa: BLE001
        log.warning("actual close not reconciled", exc_info=True, extra={"ctx": {"context": context}})
        return None


def latest_due_day(hhmm: str) -> str:
    now = now_vn()
    return str(now.date() if now >= vn_slot(now.date(), hhmm) else now.date() - timedelta(days=1))


def run_job(job_id: str | None, params: dict) -> dict:
    """Job ACTUAL_CLOSE (scheduled, retried or manual): close the business date of the slot, then reconcile the last
    RECONCILE_DAYS closed days. Reads only local data (no BigQuery call)."""
    from . import settings_service as ss
    from .data.demand import resolve_scope
    from .sync import NotApplicable, Wait
    sched = ss.get("schedule")
    hhmm = sched.close_time
    business_date = params.get("business_date") or latest_due_day(hhmm)
    day = date.fromisoformat(business_date)
    if now_vn() < vn_slot(day, hhmm):
        raise AppError("ACTUAL_CLOSE_TOO_EARLY", 409, detail=f"{business_date} closes at {hhmm} (Vietnam time)")
    with db.read() as c:
        if ss.get("general", c).active_source == "MANUAL_IMPORT":
            raise NotApplicable("MANUAL_IMPORT is static history; there is no day to close")
        sc = resolve_scope(c)
        busy = db.one(c, "SELECT id FROM job_runs WHERE job_type='D0_SYNC' AND status IN ('PENDING','RUNNING') "
                         "ORDER BY created_at DESC, rowid DESC LIMIT 1")
        trig = (db.one(c, "SELECT trigger FROM job_runs WHERE id=?", (job_id,)) or {}).get("trigger") if job_id else None
    if busy and now_vn() < vn_slot(day, hhmm) + WAIT_LIMIT:
        raise Wait("WAITING_FOR_D0_JOB", WAIT_SECONDS)      # a D-0 read of that day finishing now belongs to the close
    res = close_day(sc["scope_key"], sc["data_source"], business_date, hhmm, job_id,
                    {"MANUAL": "MANUAL_CLOSE", "CATCH_UP": "CATCH_UP_CLOSE"}.get(trig, "SCHEDULED_CLOSE"))
    rec = reconcile(sc["scope_key"], sc["data_source"], hhmm=hhmm, job_id=job_id)
    out = {"business_date": business_date, "close_id": res["id"], "revision": res["revision"],
           "close_status": res["status"], "source": res["source"], "source_ref": res["source_ref"],
           "rows": res["n_rows"], "total_qty": res["total_qty"], "already_closed": res["already_closed"],
           "cutoff_at": res["cutoff_at"], "reconciled_days": rec["checked"], "revisions_added": rec["revised"],
           "d0_job_still_running": busy["id"] if busy else None}
    if res["status"] == NO_DATA and not res["already_closed"]:
        return {**out, "status": "NO_DATA", "reason_code": "ACTUAL_CLOSE_NO_DATA"}
    return {**out, "status": "SUCCEEDED", "reason_code": "ALREADY_CLOSED" if res["already_closed"] else None}
