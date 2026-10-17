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


def run_d1_sync(job_id: str | None = None, fallback_mode: bool | None = None, backfill_start: str | None = None,
                backfill_end: str | None = None) -> dict:
    """Daily history load (D-1 and older). Never touches today's data (D0 is a separate job and table).
    A backfill (explicit user request) re-reads exactly [backfill_start, backfill_end], bounded by the read range."""
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
    if backfill:
        start = max(date.fromisoformat(backfill_start or str(floor)), floor)
        end = min(date.fromisoformat(backfill_end or str(day)), day)
        if end < start or (end - start).days + 1 > MAX_BACKFILL_DAYS:
            raise AppError("VALIDATION_ERROR", 422, detail=f"backfill window {start}..{end} (max {MAX_BACKFILL_DAYS} days, "
                                                           f"from {floor} to {day})")
        if not (st and st.get("mapping_hash") == mhash):
            raise AppError("VALIDATION_ERROR", 422, detail="run a normal D-1 sync with the current mapping first")
        full = False
    else:
        end = day
        # incremental only when the previous load used the SAME mapping/range/SQL; otherwise reload the whole period
        start, full, _ = _d1_window(bq, st, day, mhash)
    # mapping vs live source, exact-duplicate gate on the raw rows (BLOCK: report, nothing written), aggregation
    res = connector.fetch_daily(start, end, snap, context=f"D-1 job {job_id or '-'}")
    check_output(res["rows"])
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
        if not res["rows"] and before:
            # an empty read (table being rebuilt, a view/SQL returning nothing, a lost permission) never replaces
            # stored days with nothing: nothing is deleted, the job retries and then fails with an alert
            raise Retryable("SOURCE_INCOMPLETE", json.dumps({"reason": "EMPTY_READ", "rows_read": res["rows_read"],
                                                              "window": [w0, w1], "rows_stored": len(before)}))
        if full:
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date >= ?", (scope_key, keep_before))
        else:
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?", (scope_key, w0, w1))
        c.executemany(
            "INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, "
            "avg_discount_rate, promo_share, voucher_share, loaded_at) VALUES (?, 'BIGQUERY', ?,?,?,?,?,?,?,?,?,?)",
            [(scope_key, str(r["order_date"])[:10], r["sku_id"], r["fc_id"], float(r["qty"]), int(r["n_orders"] or 0),
              r.get("avg_unit_price"), r.get("avg_discount_rate"), r.get("promo_share"), r.get("voucher_share"), loaded)
             for r in res["rows"]])
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
                "source_batch_id": res["source_batch_id"], "max_source_updated_at": res["max_source_updated_at"],
                "estimated_bytes": res["estimated_bytes"], "job_id": job_id}
        if not backfill:
            _state_set(c, f"last_d1_sync:{scope_key}", info)
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
        steps.append({"step": "aggregate", "status": "PASSED", "rows_aggregated": len(res["rows"]),
                      "qty_total": res["qty_valid"], "key_duplicate_rows": res["key_duplicate_rows"],
                      "estimated_bytes": res["estimated_bytes"], "window": res["window"]})
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
