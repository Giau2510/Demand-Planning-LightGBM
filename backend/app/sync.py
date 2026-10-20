"""D-1 history sync (BigQuery -> demand_daily) and D0 intraday snapshots.

Snapshots are written ONLY after a successful read. A failed sync leaves no snapshot (the failure is
visible in the job history). Snapshots carry the real read time (`snapshot_at`); a catch-up run after a
restart is flagged `is_catch_up` and is never back-dated to the missed slot time.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta

import pandas as pd

from . import db
from . import settings_service as ss
from .bq import connector, sql_sources
from .data import customers, open_hours
from .data.demand import active_demo_batch, bigquery_scope_key, resolve_scope
from .messages import AppError
from .timeutil import now_iso, now_utc, now_vn, today_vn

log = logging.getLogger("df.sync")


class NotApplicable(Exception):
    pass


class Retryable(Exception):
    def __init__(self, code: str, detail: str | None = None):
        super().__init__(f"{code}: {detail or ''}")
        self.code = code


class Wait(Exception):
    """Not an error: the job should be re-checked later without consuming a retry attempt."""

    def __init__(self, code: str, seconds: int):
        super().__init__(code)
        self.code = code
        self.seconds = seconds


def _state_set(c, name: str, value: dict) -> None:
    c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(name) DO UPDATE "
              "SET value_json=excluded.value_json, updated_at=excluded.updated_at",
              (name, json.dumps(value, default=str), now_iso()))


def _state_get(c, name: str) -> dict | None:
    r = db.one(c, "SELECT value_json FROM sync_state WHERE name=?", (name,))
    return json.loads(r["value_json"]) if r else None


# ---------------------------------------------------------------- D-1
MAX_BACKFILL_DAYS = 400
# 1.2.9: a backfill (re-read of a past window, explicit user request) needs the id of a READY preview of exactly the same
# window, mapping and SQL, at most this old - the preview is the same read without any write (backfill_preview)
BACKFILL_PREVIEW_STATE = "bq_backfill_preview"
BACKFILL_PREVIEW_MAX_AGE_HOURS = 6
D1_STEPS = ("auth", "window", "completeness", "mapping", "duplicates", "aggregate", "output_checks", "reconciliation",
            "compare", "write")


def _d1_window(bq, st: dict | None, day: date, mhash: str) -> tuple[date, bool, date]:
    """Next regular D-1 load: incremental (watermark minus the late-data look-back) when the previous load used the
    SAME mapping/range/SQL, otherwise a full reload from the read floor. It always ends at `day` (yesterday, Vietnam
    time): today is never loaded by D-1."""
    floor = connector.read_range(bq, day)[0]
    full = not (st and st.get("watermark") and st.get("mapping_hash") == mhash)
    start = floor if full else max(floor, date.fromisoformat(st["watermark"])
                                   - timedelta(days=ss.get("data_policy").late_data_lookback_days))
    return start, full, floor


def check_output(rows: list[dict]) -> dict:
    """The aggregated rows before anything is written: exactly one row per day x SKU x FC, a valid date, a SKU and FC,
    a real quantity (not NULL / NaN / negative). Nothing is turned into zero: one bad row stops the load."""
    seen: set = set()
    bad: list[dict] = []
    total = 0.0
    for r in rows:
        d = r.get("order_date")
        key = (str(d)[:10] if d is not None else None, r.get("sku_id"), r.get("fc_id"))
        try:
            date.fromisoformat(key[0])
        except (TypeError, ValueError):
            bad.append({"code": "INVALID_DATE", "key": key})
            continue
        if key[1] is None or key[2] is None:
            bad.append({"code": "NULL_SKU_OR_FC", "key": key})
            continue
        if key in seen:
            bad.append({"code": "DUPLICATE_OUTPUT_KEY", "key": key})
            continue
        seen.add(key)
        try:
            q = float(r.get("qty"))
        except (TypeError, ValueError):
            q = float("nan")
        if not math.isfinite(q) or q < 0:
            bad.append({"code": "INVALID_QTY", "key": key, "qty": r.get("qty")})
            continue
        total += q
    if bad:
        raise AppError("BQ_AGGREGATE_INVALID", 409, detail=json.dumps(bad[:20], default=str), rows_invalid=len(bad))
    return {"rows": len(rows), "qty": total}


def _production_off() -> AppError:
    """SOURCE_NOT_READY with since when / by which change production mode is off and how to fix it (1.2.3)."""
    from .jobs import flows
    with db.read() as c:
        return AppError("SOURCE_NOT_READY", 409, detail=flows.production_off_detail(c))


def _after_d1(scope_key: str, job_id: str | None) -> None:
    """1.2.4, display side only - never fails the sync: product names refreshed (one small read of the name table)
    and the content identity of the new data version computed once, so the first explanation after a load is fast."""
    from .bq import product_names
    from .data import identity
    product_names.refresh_quietly(f"D-1 job {job_id or '-'}")
    try:
        with db.read() as c:
            identity.day_hashes(scope_key, c)
    except Exception:  # noqa: BLE001
        log.warning("data identity not computed after D-1", exc_info=True, extra={"ctx": {"job_id": job_id}})
    # 1.2.9 (seventh batch): completed days written by this (or an earlier verified) load are finalized - frozen,
    # never changed again (actual_final.py); a failure never fails the load and is retried by the next run
    from . import actual_final
    actual_final.finalize_quietly(scope_key, "BIGQUERY", f"D-1 job {job_id or '-'}", job_id)
    # 1.2.6: days already closed at 23:59 whose actual this load changed get a new close revision (late data)
    from . import actual_close
    actual_close.reconcile_quietly(scope_key, "BIGQUERY", f"D-1 job {job_id or '-'}")


def _backfill_window(start: str | None, end: str | None, floor: date, day: date) -> tuple[date, date]:
    """[start, end] bounded by the read range (floor .. yesterday), at most MAX_BACKFILL_DAYS days."""
    s = max(date.fromisoformat(start or str(floor)), floor)
    e = min(date.fromisoformat(end or str(day)), day)
    if e < s or (e - s).days + 1 > MAX_BACKFILL_DAYS:
        raise AppError("VALIDATION_ERROR", 422, detail=f"backfill window {s}..{e} (max {MAX_BACKFILL_DAYS} days, "
                                                       f"from {floor} to {day})")
    return s, e


def check_backfill_preview(preview_id: str | None, start: date, end: date, mhash: str, snap: dict) -> dict:
    """The stored preview a backfill of [start, end] must follow (BACKFILL_PREVIEW_REQUIRED otherwise): same id, READY,
    same window, same mapping hash, same SQL (mode / version / sha256), not used yet, at most
    BACKFILL_PREVIEW_MAX_AGE_HOURS old."""
    with db.read() as c:
        pv = _state_get(c, BACKFILL_PREVIEW_STATE)
    why = None
    if not preview_id:
        why = "no preview id: run 'Preview' for this window first"
    elif not pv or pv.get("preview_id") != preview_id:
        why = "the preview is not the latest one: run 'Preview' again"
    elif pv.get("status") != "READY":
        why = f"preview status {pv.get('status')}"
    elif (pv.get("window") or {}).get("start") != str(start) or (pv.get("window") or {}).get("end") != str(end):
        why = f"preview window {(pv.get('window') or {}).get('start')}..{(pv.get('window') or {}).get('end')} != {start}..{end}"
    elif pv.get("mapping_hash") != mhash:
        why = "the mapping changed since the preview"
    elif pv.get("sql") != _sql_identity(snap):
        why = "the history SQL source changed since the preview"
    else:
        try:
            age = (now_utc() - datetime.fromisoformat(pv["checked_at"])).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            age = None
        if age is None or age < -0.1:
            why = "the preview time is missing or in the future: run 'Preview' again"
        elif age > BACKFILL_PREVIEW_MAX_AGE_HOURS:
            why = f"preview is {age:.1f} h old (max {BACKFILL_PREVIEW_MAX_AGE_HOURS} h)"
    if why:
        raise AppError("BACKFILL_PREVIEW_REQUIRED", 409, detail=why)
    return pv


def _changes(before: dict, after: dict) -> tuple[set, set, set]:
    """(new, updated, removed) day x SKU x FC keys between the stored and the read rows."""
    same = set(after) & set(before)
    return set(after) - set(before), {k for k in same if abs(before[k] - after[k]) > 1e-9}, set(before) - set(after)


def _d1_load_marker(st: dict | None) -> tuple:
    """Identity of the last regular D-1 load: its time has one-second resolution, so two loads in the same second (seen
    in a fast test) could not be told apart by it alone; load_id is unique per load (None for loads stored before it)."""
    st = st or {}
    return st.get("synced_at"), st.get("load_id")


def _recheck_preview(c, preview: dict, scope_key: str, before: dict, rows: list[dict]) -> None:
    """Under the write lock, right before the stored days are replaced (findings 1-2 of the 1.2.9 data review): the
    preview is still the latest and READY (not used by another job meanwhile), no regular D-1 load changed the stored
    data since, and what this load would change is exactly what the preview showed. Otherwise nothing is written."""
    cur = _state_get(c, BACKFILL_PREVIEW_STATE) or {}
    why = None
    if cur.get("preview_id") != preview.get("preview_id") or cur.get("status") != "READY":
        why = f"the preview is no longer READY ({cur.get('preview_id')} {cur.get('status')})"
    elif _d1_load_marker(_state_get(c, f"last_d1_sync:{scope_key}")) != (preview.get("last_d1_synced_at"),
                                                                          preview.get("last_d1_load_id")):
        why = "a D-1 load changed the stored data since the preview"
    else:
        after = {(str(r["order_date"])[:10], r["sku_id"], r["fc_id"]): float(r["qty"]) for r in rows}
        n, u, r_ = (len(x) for x in _changes(before, after))
        pc = preview.get("compare") or {}
        seen = (pc.get("series_days_new"), pc.get("series_days_updated"), pc.get("series_days_removed"))
        if (n, u, r_) != seen:
            why = f"the data changed since the preview: new/updated/removed now {n}/{u}/{r_}, previewed {seen[0]}/{seen[1]}/{seen[2]}"
    if why:
        raise AppError("BACKFILL_PREVIEW_REQUIRED", 409, detail=why)


def _sql_identity(snap: dict) -> dict:
    return {"mode": snap.get("mode"), "version_id": snap.get("version_id"), "sha256": snap.get("sha256")}


def _stored_ok_keys(c, scope_key: str, start: str, end: str | None) -> set:
    """Days x SKU x FC of [start, end] (end None = no upper bound) whose stored open hours are OK."""
    q = ("SELECT order_date, sku_id, fc_id FROM demand_daily WHERE scope_key=? AND order_date >= ? "
         + ("AND order_date <= ? " if end else "") + "AND open_hours_status = 'OK'")
    return {(r[0], r[1], r[2]) for r in c.execute(q, (scope_key, start, end) if end else (scope_key, start))}


def _open_hours_lost(stored_ok: set, rows: list[dict], statuses: list) -> dict:
    """1.2.9b: stored OK open hours that a reload would NOT keep OK (the row gets another status, or is removed). The
    source keeps open hours for about its last 7 months only (data/open_hours.py): re-reading an older day turns a
    stored value into MISSING."""
    new = {(str(r["order_date"])[:10], r["sku_id"], r["fc_id"]): s for r, s in zip(rows, statuses)}
    lost = sorted(k for k in stored_ok if new.get(k) != "OK")
    return {"rows": len(lost), "first_day": lost[0][0] if lost else None, "last_day": lost[-1][0] if lost else None,
            "now_missing": sum(1 for k in lost if new.get(k) == "MISSING"), "removed": sum(1 for k in lost if k not in new)}


def backfill_preview(start: str, end: str) -> dict:
    """1.2.9 'Preview' of a controlled backfill of [start, end]: the same checks and the same BigQuery read as the load
    (read-only, dry run first, bytes cap, exact-duplicate gate), then what the load WOULD change - per day x SKU x FC new
    / updated / unchanged / removed, the open-hours status each row would get, the closed days (23:59 actual close) whose
    actual would change. demand_daily is never written; only this result is kept (sync_state BACKFILL_PREVIEW_STATE)."""
    g = ss.get("general")
    if g.active_source != "BIGQUERY":
        raise AppError("VALIDATION_ERROR", 422, detail=f"active source is {g.active_source}, not BIGQUERY")
    bq = ss.get("bigquery")
    if not bq.production_enabled:
        raise _production_off()
    if not connector.validation_ok_for_current():
        raise AppError("BQ_VALIDATION_REQUIRED", 409, mapping_hash=connector.mapping_hash(bq))
    snap = sql_sources.snapshot("history")
    day = today_vn() - timedelta(days=1)
    floor = connector.read_range(bq, day)[0]
    s, e = _backfill_window(start, end, floor, day)
    scope_key, mhash = bigquery_scope_key(bq), connector.mapping_hash(bq)
    with db.read() as c:
        st = _state_get(c, f"last_d1_sync:{scope_key}")
    if not (st and st.get("mapping_hash") == mhash):
        raise AppError("VALIDATION_ERROR", 422, detail="run a normal D-1 sync with the current mapping first")
    out: dict = {"preview_id": db.new_id("BFP"), "checked_at": now_iso(), "written": False, "scope_key": scope_key,
                 "window": {"start": str(s), "end": str(e), "days": (e - s).days + 1}, "mapping_hash": mhash,
                 "sql": _sql_identity(snap), "max_age_hours": BACKFILL_PREVIEW_MAX_AGE_HOURS,
                 # the stored data the comparison was made with: a regular D-1 load after the preview makes it stale
                 "last_d1_synced_at": st.get("synced_at"), "last_d1_load_id": st.get("load_id"), "warnings": []}
    if e == day and not connector.completion_signal(day):
        # finding 6: yesterday may still be incomplete in the source (the regular D-1 waits for the signal)
        out["warnings"].append({"code": "YESTERDAY_NOT_CONFIRMED", "day": str(day)})
    try:
        res = connector.fetch_daily(s, e, snap, context="backfill preview")
        check_output(res["rows"])
        with db.read() as c:
            before = {(r[0], r[1], r[2]): r[3] for r in c.execute(
                "SELECT order_date, sku_id, fc_id, qty FROM demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?",
                (scope_key, str(s), str(e)))}
            stored_oh = {k: n for k, n in c.execute(
                "SELECT COALESCE(open_hours_status, 'NOT_LOADED'), COUNT(*) FROM demand_daily NOT INDEXED WHERE "
                "scope_key=? AND order_date BETWEEN ? AND ? GROUP BY 1", (scope_key, str(s), str(e)))}
            closed = {r[0] for r in c.execute("SELECT DISTINCT business_date FROM actual_closes WHERE scope_key=? AND "
                                              "business_date BETWEEN ? AND ?", (scope_key, str(s), str(e)))}
            stored_ok = _stored_ok_keys(c, scope_key, str(s), str(e))
        if not res["rows"] and before:
            raise AppError("SOURCE_INCOMPLETE", 409, detail=json.dumps(
                {"reason": "EMPTY_READ", "rows_read": res["rows_read"], "rows_stored": len(before)}))
        after = {(str(r["order_date"])[:10], r["sku_id"], r["fc_id"]): float(r["qty"]) for r in res["rows"]}
        new, updated, removed = _changes(before, after)
        same = set(after) & set(before)
        changed_days = sorted({k[0] for k in new | removed | updated})
        oh = [open_hours.row_cell(r)[1] for r in res["rows"]]
        lost = _open_hours_lost(stored_ok, res["rows"], oh)
        if lost["rows"]:
            out["warnings"].append({"code": "OPEN_HOURS_WOULD_BE_LOST", **lost})
        not_ok_days = sorted({str(r["order_date"])[:10] for r, h in zip(res["rows"], oh) if h != "OK"})
        out.update({
            "status": "READY",
            "read": {k: res.get(k) for k in ("rows_read", "rows_valid", "rows_error", "excluded_by_reason",
                                             "key_duplicate_rows", "exact_duplicate_rows", "qty_read", "qty_valid",
                                             "qty_excluded", "estimated_bytes")},
            "rows_aggregated": len(res["rows"]),
            "compare": {"rows_stored_in_window": len(before), "qty_stored_in_window": float(sum(before.values())),
                        "series_days_new": len(new), "series_days_updated": len(updated),
                        "series_days_unchanged": len(same) - len(updated), "series_days_removed": len(removed),
                        "qty_change": float(sum(after.values()) - sum(before.values())),
                        "days_with_changes": len(changed_days),
                        "first_changed_day": changed_days[0] if changed_days else None,
                        "last_changed_day": changed_days[-1] if changed_days else None},
            "open_hours": {"would_write": {**{x: oh.count(x) for x in open_hours.STATUSES}, "NOT_READ": oh.count(None)},
                           "stored_now": stored_oh, "days_with_rows_not_ok": len(not_ok_days),
                           "stored_ok_not_kept": lost,
                           "first_day_not_ok": not_ok_days[0] if not_ok_days else None,
                           "last_day_not_ok": not_ok_days[-1] if not_ok_days else None},
            "effects": {"writes": "demand_daily rows of this scope inside the window only (replaced by what the source "
                                  "holds now); an online backup of the database is made first",
                        "closed_days_in_window": len(closed),
                        "closed_days_with_changes": len(closed & set(changed_days)),
                        "not_written": ["d0_snapshots", "forecast_runs", "forecast_values", "training_runs",
                                        "model files", "forecast_history", "forecast_eod_snapshots",
                                        "sync watermark (last_d1_sync)"],
                        "notes": ["a closed day (23:59 close) of the last days whose actual changes gets a NEW close "
                                  "revision; earlier revisions are never changed",
                                  "a backfill is never followed by a training (flows.d1_success_today ignores it)"]}})
    except AppError as ex:
        out.update(status="BLOCKED" if ex.code in ("BQ_DATA_DUPLICATES", "SOURCE_INCOMPLETE") else "FAILED",
                   error=ex.to_dict())
        if ex.code == "BQ_DATA_DUPLICATES":
            out["duplicate_check"] = ex.params.get("duplicate_check")
    with db.tx() as c:
        _state_set(c, BACKFILL_PREVIEW_STATE, out)
        db.audit(c, "D1_BACKFILL_PREVIEW", "scope", scope_key,
                 {k: out.get(k) for k in ("preview_id", "status", "window", "compare", "open_hours")})
    return out


def run_d1_sync(job_id: str | None = None, fallback_mode: bool | None = None, backfill_start: str | None = None,
                backfill_end: str | None = None, backfill_preview_id: str | None = None) -> dict:
    """Daily history load (D-1 and older). Never touches today's data (D0 is a separate job and table).
    A backfill (explicit user request) re-reads exactly [backfill_start, backfill_end], bounded by the read range; 1.2.9:
    only after a READY preview of the same window (check_backfill_preview) and after an online backup of the database."""
    g = ss.get("general")
    if g.active_source != "BIGQUERY":
        raise NotApplicable(g.active_source)
    bq = ss.get("bigquery")
    if not bq.production_enabled:
        raise _production_off()
    if not connector.validation_ok_for_current():
        raise AppError("BQ_VALIDATION_REQUIRED", 409, mapping_hash=connector.mapping_hash(bq))
    snap = sql_sources.snapshot("history")     # the SQL text used from start to end of THIS job
    sched = ss.get("schedule")
    day = today_vn() - timedelta(days=1)
    backfill = bool(backfill_start or backfill_end)
    mode = "BACKFILL" if backfill else "SIGNAL"
    if not backfill:
        signal = connector.completion_signal(day)
        now = now_vn()
        fb_h, fb_m = (int(x) for x in sched.d1_fallback_time.split(":"))
        after_fallback = (now.hour, now.minute) >= (fb_h, fb_m) if fallback_mode is None else fallback_mode
        if not signal:
            if not after_fallback:
                raise Wait("WAITING_FOR_SIGNAL", sched.d1_poll_interval_minutes * 60)
            suff = connector.sufficiency_check(day)
            if not suff["ok"]:
                raise Retryable("SOURCE_INCOMPLETE", json.dumps(suff))
            mode = "FALLBACK_TIME_VERIFIED"
    scope_key = bigquery_scope_key(bq)
    with db.read() as c:
        st = _state_get(c, f"last_d1_sync:{scope_key}")
    mhash = connector.mapping_hash(bq)
    floor = connector.read_range(bq, day)[0]
    preview = None
    if backfill:
        start, end = _backfill_window(backfill_start, backfill_end, floor, day)
        if not (st and st.get("mapping_hash") == mhash):
            raise AppError("VALIDATION_ERROR", 422, detail="run a normal D-1 sync with the current mapping first")
        preview = check_backfill_preview(backfill_preview_id, start, end, mhash, snap)
        full = False
    else:
        end = day
        # incremental only when the previous load used the SAME mapping/range/SQL; otherwise reload the whole period
        start, full, _ = _d1_window(bq, st, day, mhash)
    # mapping vs live source, exact-duplicate gate on the raw rows (BLOCK: report, nothing written), aggregation
    res = connector.fetch_daily(start, end, snap, context=f"D-1 job {job_id or '-'}")
    check_output(res["rows"])
    backup = None
    if backfill:
        # 1.2.9: the recovery path of a backfill - a verified online backup of the database (and model files) taken
        # right before the stored days of the window are replaced; no backup, no write
        from .backup import backup_database
        try:
            bk = backup_database(reason="pre-backfill")
        except Exception as ex:  # noqa: BLE001
            raise AppError("BACKFILL_BACKUP_FAILED", 409, detail=str(ex)[:500]) from ex
        backup = {"file": bk.name, "bytes": bk.stat().st_size}
    loaded = now_iso()
    w0, w1 = (str(floor), str(end)) if full else (res["window"]["start"], str(end))
    # a full reload replaces the MODEL-INPUT part of the scope (from the data window start); rows stored before the
    # window are history that is no longer used and is kept untouched
    keep_before = ss.get("data_policy").window_start_date
    with db.tx() as c:
        if full:
            q, prm = ("SELECT order_date, sku_id, fc_id, qty FROM demand_daily WHERE scope_key=? AND order_date >= ?",
                      (scope_key, keep_before))
        else:
            q = "SELECT order_date, sku_id, fc_id, qty FROM demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?"
            prm = (scope_key, w0, w1)
        before = {(r[0], r[1], r[2]): r[3] for r in c.execute(q, prm)}
        stored_ok = _stored_ok_keys(c, scope_key, keep_before if full else w0, None if full else w1)
        if not res["rows"] and before:
            # an empty read (table being rebuilt, a view/SQL returning nothing, a lost permission) never replaces
            # stored days with nothing: nothing is deleted, the job retries and then fails with an alert
            raise Retryable("SOURCE_INCOMPLETE", json.dumps({"reason": "EMPTY_READ", "rows_read": res["rows_read"],
                                                              "window": [w0, w1], "rows_stored": len(before)}))
        if backfill:
            _recheck_preview(c, preview, scope_key, before, res["rows"])
        if full:
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date >= ?", (scope_key, keep_before))
        else:
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?", (scope_key, w0, w1))
        # 1.2.9: open hours of the day x SKU x FC (value only when every line agrees and is within 0..24, else a status
        # and no value - data/open_hours.py); the demand itself is written exactly as before
        oh = [open_hours.row_cell(r) for r in res["rows"]]
        # 1.2.9b: customer counts (data/customers.py) - NULL unless the owner mapped a customer column
        c.executemany(
            "INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, "
            "avg_discount_rate, promo_share, voucher_share, loaded_at, open_hours, open_hours_status, customer_count, "
            "repeat_customer_count, repeat_interval_days_sum) VALUES (?, 'BIGQUERY', ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(scope_key, str(r["order_date"])[:10], r["sku_id"], r["fc_id"], float(r["qty"]), int(r["n_orders"] or 0),
              r.get("avg_unit_price"), r.get("avg_discount_rate"), r.get("promo_share"), r.get("voucher_share"), loaded,
              h[0], h[1], *customers.stored(r))
             for r, h in zip(res["rows"], oh)])
        oh_counts = {s: sum(1 for h in oh if h[1] == s) for s in open_hours.STATUSES}
        oh_counts["NOT_READ"] = sum(1 for h in oh if h[1] is None)
        # what was written must equal the valid total read from BigQuery, otherwise nothing is committed
        w = c.execute("SELECT COUNT(*), COALESCE(SUM(qty), 0) FROM demand_daily WHERE scope_key=? AND order_date "
                      "BETWEEN ? AND ?", (scope_key, res["window"]["start"], str(end))).fetchone()
        if w[0] != len(res["rows"]) or abs(float(w[1]) - res["qty_valid"]) > 1e-6 * max(1.0, abs(res["qty_valid"])):
            raise AppError("BQ_SYNC_RECONCILIATION_FAILED", 409,
                           detail=f"written {w[0]} rows / {w[1]} qty; read {len(res['rows'])} rows / {res['qty_valid']} qty")
        after = {(str(r["order_date"])[:10], r["sku_id"], r["fc_id"]): float(r["qty"] or 0) for r in res["rows"]}
        same = set(after) & set(before)
        info = {"synced_at": loaded, "watermark": str(day) if not backfill else (st or {}).get("watermark"),
                "window_start": res["window"]["start"], "window_end": str(end), "mode": mode, "backfill": backfill,
                "rows_read": res["rows_read"], "rows_valid": res["rows_valid"], "rows_error": res["rows_error"],
                "excluded_by_reason": res["excluded_by_reason"], "rows_dropped_duplicates": res["rows_dropped_duplicates"],
                "exact_duplicate_rows": res["exact_duplicate_rows"], "key_duplicate_rows": res.get("key_duplicate_rows"),
                "qty_read": res["qty_read"], "qty_valid": res["qty_valid"], "qty_excluded": res["qty_excluded"],
                "series_days_written": int(w[0]), "series_days_new": len(set(after) - set(before)),
                "series_days_updated": sum(1 for k in same if abs(before[k] - after[k]) > 1e-9),
                "series_days_unchanged": sum(1 for k in same if abs(before[k] - after[k]) <= 1e-9),
                "series_days_removed": len(set(before) - set(after)),
                "mapping_hash": mhash, "full_reload": full, "duplicate_policy": bq.exact_duplicate_policy,
                "read_floor": str(floor), "window_start_date": keep_before,
                "rows_kept_before_window": c.execute("SELECT COUNT(*) FROM demand_daily WHERE scope_key=? AND "
                                                     "order_date < ?", (scope_key, keep_before)).fetchone()[0],
                "sql_source": sql_sources.public_snapshot(snap),
                "open_hours_status_rows": oh_counts,
                # 1.2.9b: stored OK open hours this load did not keep OK (source retention, data/open_hours.py)
                "open_hours_lost": _open_hours_lost(stored_ok, res["rows"], [h[1] for h in oh]),
                "preview_id": (preview or {}).get("preview_id"), "pre_backfill_backup": backup,
                "source_batch_id": res["source_batch_id"], "max_source_updated_at": res["max_source_updated_at"],
                "estimated_bytes": res["estimated_bytes"], "job_id": job_id, "load_id": db.new_id("D1L")}
        if not backfill:
            _state_set(c, f"last_d1_sync:{scope_key}", info)
        else:
            # a preview is used once: the next backfill needs a new preview of the then current data
            _state_set(c, BACKFILL_PREVIEW_STATE, {**preview, "status": "USED", "used_by_job": job_id, "used_at": loaded})
        db.audit(c, "D1_SYNC", "scope", scope_key, {k: v for k, v in info.items() if k != "excluded_by_reason"})
    _after_d1(scope_key, job_id)
    return {"status": "SUCCEEDED", "reason_code": "BACKFILL_DONE" if backfill else None, **info}


def d1_dry_run() -> dict:
    """'Check and aggregate WITHOUT writing' for the next regular D-1 load, step by step (D1_STEPS): sign-in, window,
    is yesterday complete (completion signal, else the row-count sufficiency check of the D-1 fallback; a WARNING here
    means a real D-1 would wait / retry and write nothing), mapping vs live source, exact-duplicate gate on the raw rows (duplicates: report file, BLOCKED), BigQuery
    aggregation to day x SKU x FC, output checks, reconciliation, then a READ-ONLY comparison with the stored days.
    demand_daily is never written; only this result is kept (sync_state 'bq_ingest_check'). Allowed before production
    mode is on: every BigQuery query is read-only, dry-run first and capped."""
    bq = ss.get("bigquery")
    steps: list[dict] = []
    out: dict = {"checked_at": now_iso(), "steps": steps, "written": False,
                 "table": f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}"}
    day = today_vn() - timedelta(days=1)
    cur = "auth"
    try:
        connector._require_config(bq)
        ident = connector.verify_auth(bq)
        steps.append({"step": "auth", "status": "PASSED", "account": ident.get("account"),
                      "verified": ident.get("verified")})
        cur = "window"
        snap = sql_sources.snapshot("history")
        scope_key, mhash = bigquery_scope_key(bq), connector.mapping_hash(bq)
        with db.read() as c:
            st = _state_get(c, f"last_d1_sync:{scope_key}")
        start, full, floor = _d1_window(bq, st, day, mhash)
        steps.append({"step": "window", "status": "PASSED", "start": str(start), "end": str(day), "full_reload": full,
                      "today_excluded": str(today_vn()), "timezone": "Asia/Ho_Chi_Minh", "scope_key": scope_key})
        cur = "completeness"
        signal = connector.completion_signal(day)
        suff = None if signal else connector.sufficiency_check(day)
        complete = bool(signal) or bool(suff and suff["ok"])
        steps.append({"step": "completeness", "status": "PASSED" if complete else "WARNING", "day": str(day),
                      "completion_signal": signal, "sufficiency": suff})
        cur = "mapping"
        sch = connector.require_mapping(bq, snap)
        cols = connector.dup_columns(bq)
        steps.append({"step": "mapping", "status": "PASSED", "compared_columns": [c["column"] for c in cols],
                      "not_compared": [c["name"] for c in sch["columns"] if c["name"] not in {x["column"] for x in cols}],
                      "warnings": sch["mapping_check"]["warnings"]})
        cur = "duplicates"
        dup = connector.duplicate_gate(start, day, snap, "d1_dry_run", sch["columns"])
        steps.append({"step": "duplicates", "status": "PASSED" if dup else "SKIPPED",
                      **(dup or {"policy": bq.exact_duplicate_policy})})
        cur = "aggregate"
        res = connector.fetch_daily(start, day, snap, "d1_dry_run", prechecked=True)
        oh = [open_hours.row_cell(r)[1] for r in res["rows"]]
        steps.append({"step": "aggregate", "status": "PASSED", "rows_aggregated": len(res["rows"]),
                      "qty_total": res["qty_valid"], "key_duplicate_rows": res["key_duplicate_rows"],
                      "estimated_bytes": res["estimated_bytes"], "window": res["window"],
                      # 1.2.9: what the write would store for the SKU open hours (mandatory BIGQUERY input)
                      "open_hours_status_rows": {**{s: oh.count(s) for s in open_hours.STATUSES}, "NOT_READ": oh.count(None)}})
        cur = "output_checks"
        oc = check_output(res["rows"])
        steps.append({"step": "output_checks", "status": "PASSED", **oc})
        steps.append({"step": "reconciliation", "status": "PASSED", "rows_read": res["rows_read"],
                      "rows_valid": res["rows_valid"], "rows_excluded": res["rows_error"],
                      "excluded_by_reason": res["excluded_by_reason"], "qty_read": res["qty_read"],
                      "qty_valid": res["qty_valid"], "qty_excluded": res["qty_excluded"]})
        cur = "compare"
        keep_before = ss.get("data_policy").window_start_date
        with db.read() as c:
            if full:
                q, prm = ("SELECT order_date, sku_id, fc_id, qty FROM demand_daily WHERE scope_key=? AND order_date >= ?",
                          (scope_key, keep_before))
            else:
                q = "SELECT order_date, sku_id, fc_id, qty FROM demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?"
                prm = (scope_key, res["window"]["start"], str(day))
            before = {(r[0], r[1], r[2]): r[3] for r in c.execute(q, prm)}
        after = {(str(r["order_date"])[:10], r["sku_id"], r["fc_id"]): float(r["qty"]) for r in res["rows"]}
        same = set(after) & set(before)
        steps.append({"step": "compare", "status": "PASSED", "rows_stored_in_window": len(before),
                      "qty_stored_in_window": float(sum(before.values())),
                      "series_days_new": len(set(after) - set(before)),
                      "series_days_updated": sum(1 for k in same if abs(before[k] - after[k]) > 1e-9),
                      "series_days_unchanged": sum(1 for k in same if abs(before[k] - after[k]) <= 1e-9),
                      "series_days_removed": len(set(before) - set(after))})
        steps.append({"step": "write", "status": "NOT_RUN", "reason": "DRY_RUN"})
        # yesterday not complete in the source: the rest is checked, but a real D-1 now would wait / retry, not write
        out["status"] = "READY" if complete else "SOURCE_INCOMPLETE"
    except AppError as e:
        if e.code == "BQ_SYNC_RECONCILIATION_FAILED":
            cur = "reconciliation"
        blocked = e.code == "BQ_DATA_DUPLICATES"
        steps.append({"step": cur, "status": "BLOCKED" if blocked else "FAILED", "error": e.to_dict()})
        if blocked:
            out["duplicate_check"] = e.params.get("duplicate_check")
        done = {s["step"] for s in steps}
        steps.extend({"step": s, "status": "NOT_RUN"} for s in D1_STEPS if s not in done)
        out["status"] = "BLOCKED" if blocked else "FAILED"
    out["readiness"] = {"active_source": ss.get("general").active_source, "production_enabled": bq.production_enabled,
                        "validation_current": connector.validation_ok_for_current(),
                        "d1_schedule_enabled": ss.get("schedule").d1_enabled}
    with db.tx() as c:
        _state_set(c, "bq_ingest_check", out)
    return out


def ingest_check_state() -> dict | None:
    with db.read() as c:
        return _state_get(c, "bq_ingest_check")


# ---------------------------------------------------------------- D0
def run_d0_snapshot(job_id: str | None = None, scheduled_slot: str | None = None, is_catch_up: bool = False) -> dict:
    if scheduled_slot and not ss.get("schedule").d0_enabled:
        # scheduled D-0 runs stay OFF until the user turns the D-0 flow on (manual runs remain possible)
        raise AppError("D0_SCHEDULE_DISABLED", 409)
    g = ss.get("general")
    src = g.active_source
    if src == "MANUAL_IMPORT":
        raise NotApplicable("MANUAL_IMPORT is static history; there is no live intraday source")
    day = today_vn()
    read_at = now_utc()
    extra: dict = {}
    if src == "DEMO":
        from .data.demo import demo_intraday_lines
        with db.read() as c:
            b = active_demo_batch(c)
        if not b:
            raise AppError("NO_ACTIVE_DATASET", 409)
        scope_key = b["id"]
        lines = demo_intraday_lines(day)
        lines = lines[lines["created_at"] <= pd.Timestamp(read_at)]
        agg = lines.groupby(["sku_id", "fc_id"], as_index=False)["order_qty"].sum()
        rows = [{"sku_id": r.sku_id, "fc_id": r.fc_id, "cumulative_qty": float(r.order_qty), "source_updated_at": None}
                for r in agg.itertuples()]
        stats = {"rows_read": len(lines), "rows_valid": len(lines), "rows_error": 0, "source_updated_max": None,
                 "source_batch_id": f"DEMO-B{day:%Y%m%d}"}
    else:
        bq = ss.get("bigquery")
        if not bq.production_enabled:
            raise _production_off()
        scope_key = bigquery_scope_key(bq)
        # the D0 SQL / table, D-0 mapping and key rules used from start to end of THIS job (1.2.1: refused when the
        # validation was made for another D-0 mapping); only TODAY's rows (Vietnam) are counted, never D-1 data
        snap = sql_sources.snapshot("d0")
        res = connector.fetch_d0(day, read_at, snap)
        rows = [{"sku_id": r["sku_id"], "fc_id": r["fc_id"], "cumulative_qty": float(r["cumulative_qty"] or 0),
                 "source_updated_at": str(r["source_updated_at"]) if r.get("source_updated_at") else None}
                for r in res["rows"]]
        ups = [r["source_updated_at"] for r in rows if r["source_updated_at"]]
        sqlid = (f"D0SQL-v{snap['version_id']}-{snap['sha256'][:12]}" if snap.get("mode") == "SQL"
                 else f"D0TABLE-{snap.get('table', '')}"[:200])
        stats = {"rows_read": res["rows_read"], "rows_valid": res["rows_valid"], "rows_error": res["rows_error"],
                 "source_updated_max": max(ups) if ups else None, "source_batch_id": sqlid}
        with db.read() as c:
            match = _forecast_match(c, scope_key, day, rows, read_at.isoformat(timespec="seconds"))
        extra = {"sql_source": sql_sources.public_snapshot(snap), "excluded_by_reason": res.get("excluded_by_reason"),
                 "key_duplicate_rows": res.get("key_duplicate_rows"), "dates_in_output": res.get("dates_in_output"),
                 "rows_other_day": res.get("rows_other_day"), "forecast_match": match,
                 "warnings": (res.get("warnings") or []) + ([{"code": "D0_NO_FORECAST_FOR_TODAY", "detail": str(day)}]
                                                            if not match["forecast_run_id"] else [])}
    sid = db.new_id("SNP")
    with db.tx() as c:
        if job_id:     # a retried / re-entered job never writes a second snapshot
            prev = db.one(c, "SELECT id, rows_read, rows_valid, rows_error FROM d0_snapshots WHERE job_id=?", (job_id,))
            if prev:
                return {"status": "SUCCEEDED", "snapshot_id": prev["id"], "already_written": True,
                        "rows_read": prev["rows_read"], "rows_valid": prev["rows_valid"], "rows_error": prev["rows_error"]}
        c.execute("INSERT INTO d0_snapshots(id, data_source, scope_key, order_date, snapshot_at, scheduled_slot, "
                  "is_catch_up, sync_status, rows_read, rows_valid, rows_error, source_updated_max, source_batch_id, "
                  "job_id, created_at) VALUES (?,?,?,?,?,?,?, 'SUCCEEDED', ?,?,?,?,?,?,?)",
                  (sid, src, scope_key, str(day), read_at.isoformat(timespec="seconds"), scheduled_slot,
                   int(is_catch_up), stats["rows_read"], stats["rows_valid"], stats["rows_error"],
                   stats["source_updated_max"], stats["source_batch_id"], job_id, now_iso()))
        c.executemany("INSERT INTO d0_snapshot_values(snapshot_id, sku_id, fc_id, cumulative_qty, source_updated_at) "
                      "VALUES (?,?,?,?,?)",
                      [(sid, r["sku_id"], r["fc_id"], r["cumulative_qty"], r["source_updated_at"]) for r in rows])
        db.audit(c, "D0_SNAPSHOT", "d0_snapshot", sid, {"slot": scheduled_slot, "catch_up": is_catch_up,
                                                         "rows": len(rows)})
    log.info("d0 snapshot", extra={"ctx": {"snapshot_id": sid, "job_id": job_id, "rows": len(rows)}})
    return {"status": "SUCCEEDED", "snapshot_id": sid, "series": len(rows), "series_rows_new": len(rows), **stats, **extra}


def _forecast_match(c, scope_key: str, day: date, rows: list[dict], snapshot_at: str) -> dict:
    """How today's D-0 rows line up with the forecast for today (latest published run of the same scope created before
    the read, as on the snapshot page). Rows without a forecast are KEPT in the snapshot and counted here."""
    fr = db.one(c, "SELECT id FROM forecast_runs WHERE scope_key=? AND forecast_origin<=? AND created_at<=? "
                   "ORDER BY created_at DESC, rowid DESC LIMIT 1", (scope_key, str(day), snapshot_at))
    fset = set()
    if fr:
        fset = {(r["sku_id"], r["fc_id"]) for r in db.rows(
            c, "SELECT sku_id, fc_id FROM forecast_values WHERE run_id=? AND target_date=?", (fr["id"], str(day)))}
    missing = [r for r in rows if (r["sku_id"], r["fc_id"]) not in fset]
    have = {(r["sku_id"], r["fc_id"]) for r in rows}
    return {"forecast_run_id": fr["id"] if fr else None, "series_d0": len(rows), "series_with_forecast": len(rows) - len(missing),
            "series_without_forecast": len(missing), "qty_without_forecast": sum(r["cumulative_qty"] for r in missing),
            "forecast_series_without_d0_row": len(fset - have),
            "sample_without_forecast": [f"{r['sku_id']}|{r['fc_id']}" for r in missing[:20]]}


def list_snapshots(filters: dict, limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM d0_snapshots WHERE 1=1"
    params: list = []
    for k, col in (("order_date", "order_date"), ("data_source", "data_source")):
        if filters.get(k):
            sql += f" AND {col}=?"
            params.append(filters[k])
    if filters.get("date_from"):
        sql += " AND order_date>=?"
        params.append(filters["date_from"])
    if filters.get("date_to"):
        sql += " AND order_date<=?"
        params.append(filters["date_to"])
    if filters.get("sku_id") or filters.get("fc_id"):
        sub = "SELECT 1 FROM d0_snapshot_values v WHERE v.snapshot_id=d0_snapshots.id"
        if filters.get("sku_id"):
            sub += " AND v.sku_id=?"
            params.append(filters["sku_id"])
        if filters.get("fc_id"):
            sub += " AND v.fc_id=?"
            params.append(filters["fc_id"])
        sql += f" AND EXISTS ({sub})"
    sql += " ORDER BY snapshot_at DESC, rowid DESC LIMIT ?"
    params.append(limit)
    with db.read() as c:
        return db.rows(c, sql, params)


def snapshot_detail(sid: str, sku_id: str | None = None, fc_id: str | None = None) -> dict:
    with db.read() as c:
        s = db.one(c, "SELECT * FROM d0_snapshots WHERE id=?", (sid,))
        if not s:
            raise AppError("BATCH_NOT_FOUND", 404, detail=sid)
        sql = "SELECT sku_id, fc_id, cumulative_qty, source_updated_at FROM d0_snapshot_values WHERE snapshot_id=?"
        params: list = [sid]
        if sku_id:
            sql += " AND sku_id=?"
            params.append(sku_id)
        if fc_id:
            sql += " AND fc_id=?"
            params.append(fc_id)
        vals = db.rows(c, sql + " ORDER BY sku_id, fc_id", params)
        # full-day forecast available for that date: latest published run of the same scope created before the snapshot
        fr = db.one(c, "SELECT id, model_version, created_at, forecast_origin FROM forecast_runs WHERE scope_key=? "
                       "AND forecast_origin<=? AND created_at<=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                    (s["scope_key"], s["order_date"], s["snapshot_at"]))
        fmap = {}
        if fr:
            fmap = {(r["sku_id"], r["fc_id"]): r["yhat"] for r in db.rows(
                c, "SELECT sku_id, fc_id, yhat FROM forecast_values WHERE run_id=? AND target_date=?",
                (fr["id"], s["order_date"]))}
        eod = {}
        if s["order_date"] < str(today_vn()):
            eod = {(r["sku_id"], r["fc_id"]): r["qty"] for r in db.rows(
                c, "SELECT sku_id, fc_id, qty FROM demand_daily WHERE scope_key=? AND order_date=?",
                (s["scope_key"], s["order_date"]))}
    for v in vals:
        k = (v["sku_id"], v["fc_id"])
        v["full_day_forecast"] = fmap.get(k)
        v["end_of_day_actual"] = eod.get(k)
    return {"snapshot": s, "values": vals, "forecast_run": fr,
            "measurement_note": {"vi": f"Thực tế lũy kế đến {s['snapshot_at']} (UTC) — KHÔNG phải số cả ngày; "
                                       "dự báo là cho cả ngày.",
                                 "en": f"Intraday cumulative actual up to {s['snapshot_at']} (UTC) — NOT a full-day "
                                       "figure; the forecast is for the full day."}}
