"""1.4.8 nightly SO-line step (job SPIKE_LINES, key SPIKE_LINES:<day>), separate from D-1: D-1 (sync.run_d1_sync) is
never changed or delayed by it, and its failure only flags (job row FAILED + ONE WARNING alert SPIKE_LINES_FAILED);
D-1, the forecast refresh and the Excel export go on.

run(D) (child process `python -m app.cli spike-lines --date D --yes`, the server never holds its memory):
  a. SO lines of the BIGQUERY scope into so_lines_cache (read-only BigQuery, connector.fetch_so_lines: dry run first,
     each query < 5 GB): first run (empty cache, or --initial) the CACHE_DAYS days D-210 .. D-1, later from the last
     cached day - data_policy.late_data_lookback_days to D-1 (clipped to the read floor of the data window). The rows
     of the read days are replaced in short transactions of WRITE_DAYS days (staged in a TEMP table first, so no write
     lock is held while BigQuery streams), and the cache days before D-210 are pruned (a re-readable working copy of the source; owner
     08/11/2026). spike_flag_lines and demand_excess_daily are never pruned.
  b. spike flags (ml/sel2/spike.flag_lines, logic v3, H180), day0 = the first cached day, end = data_end = D-1. Until
     a full flag run of the scope has finished (sync_state marker spike_flags_full:<scope>; also with --reflag): every
     cached line, written for [first cached day, D-1] (a night whose cache load worked but whose flags failed is healed
     the next night). Later nights (orchestrator
     decision 08/11): only the lines of [D-30, D-1] recomputed and replaced (always the full 180-day history; after a
     gap of more than 30 nights without a flag run: from the day of the last flag run, marker last_computed_for); stored
     lines before D-30 keep every value, only their next purchase day (next_day NULL -> first later purchase of the
     same customer x SKU x FC in the cache) and computed_for are refreshed, so Excess decides T7 as of any later day.
     Series are processed in chunks of whole SKUs (exact: every statistic is per series or customer x series). Open
     days: open_hours_daily of the configured source (rows with hours > 0, one closed row per series without an open
     day, the source's last day). Groups (minimum quantity): ROLLING_B7 of data.Inputs.groups on every retraining weekday from the one on or
     before the first cached day to D-1 (a series without a group that week = B), as the research (bt17 weekly_groups).
  c. demand_excess_daily as of D, level 1, E4 N = sel2_pipeline.spike_e4_n.
job(...) (runner handler, jobs/runner.py): the free-commit gate, the child (timeout 45 min) and the alert. Customer
ids stay in so_lines_cache / spike_flag_lines only (never in logs, results or alerts)."""
from __future__ import annotations

import gc
import json
import logging
from datetime import date, timedelta

import pandas as pd

from . import db
from . import settings_service as ss
from .messages import AppError
from .timeutil import now_iso, today_vn

log = logging.getLogger("df.spike_lines")
JOB_TYPE = "SPIKE_LINES"
CACHE_DAYS = 210                # 180 days of history + the 30 days of the E4 rule
TIMEOUT_S = 45 * 60             # the child is killed after 45 minutes
WAIT_MAX = timedelta(minutes=45)    # switch ON: the refresh / training wait for today's step at most this long
MIN_COMMIT_MB = 3072            # free commit needed to start the child (= pipeline.MIN_COMMIT_MB, not imported)
RECENT_DAYS = 30                # later nights: flags of the lines of the last 30 days recomputed (full history)
CHUNK_LINES = 1_500_000         # SO lines per flag_lines call (whole SKUs)
ALERT = "SPIKE_LINES_FAILED"
WRITE_DAYS = 7                  # days per write transaction (cache replace, flag writes): no long write lock
FULL_MARK = "spike_flags_full:"     # sync_state name prefix: the first full flag run of the scope finished (+ scope)
_on_chunk = None                # tests: called between two write transactions
LEVEL = 1
_child_runner = None            # tests: fn(args, timeout) -> dict (the child's JSON), never a real child


def job_key(d: date) -> str:
    return f"{JOB_TYPE}:{d.isoformat()}"


def set_child_runner(fn) -> None:
    global _child_runner
    _child_runner = fn


# ------------------------------------------------------------------ child side
def _scope_key() -> str:
    from .data.demand import resolve_scope
    with db.read() as c:
        sc = resolve_scope(c)
    if sc["data_source"] != "BIGQUERY":
        raise AppError("NOT_APPLICABLE_FOR_SOURCE", 409, detail=f"active source {sc['data_source']}: SO lines are read "
                                                                 "for the BIGQUERY scope only")
    return sc["scope_key"]


def read_range(scope_key: str, d: date, initial: bool = False) -> tuple[date, date, date]:
    """(first cache day D-CACHE_DAYS, read start, read end D-1): full cache window when the cache of the scope is empty
    or initial, else from the last cached day minus the late-data look-back (never before the first cache day)."""
    first, end = d - timedelta(days=CACHE_DAYS), d - timedelta(days=1)
    with db.read() as c:
        last = c.execute("SELECT MAX(order_date) FROM so_lines_cache WHERE scope_key=?", (scope_key,)).fetchone()[0]
    if initial or last is None:
        return first, first, end
    lb = ss.get("data_policy").late_data_lookback_days
    return first, max(first, date.fromisoformat(last[:10]) - timedelta(days=lb)), end


def _day_chunks(start: date, end: date, days: int = WRITE_DAYS):
    a = start
    while a <= end:
        b = min(a + timedelta(days=days - 1), end)
        yield a, b
        a = b + timedelta(days=1)


def _between_chunks() -> None:
    if _on_chunk is not None:
        _on_chunk()


def load_lines(scope_key: str, start: date, end: date, first: date) -> dict:
    """a. read [start, end] from BigQuery into a TEMP table and group it there (no lock on the database), then replace
    the cache days in short transactions of WRITE_DAYS days, oldest first (a failure leaves whole days, old or new),
    then prune the days before first in its own transaction."""
    from .bq import connector
    c = db.connect()
    try:
        c.execute("CREATE TEMP TABLE _slc_stage (order_date TEXT, fc_code TEXT, sku_code TEXT, so_code TEXT, "
                  "customer_id TEXT, qty REAL, n_rows INTEGER)")

        def sink(batch):
            c.execute("BEGIN")
            c.executemany("INSERT INTO temp._slc_stage VALUES (?,?,?,?,?,?,?)", batch)
            c.execute("COMMIT")
        res = connector.fetch_so_lines(start, end, sink)
        ws, we = res["window"]["start"], res["window"]["end"]
        at = now_iso()
        # one cache row per line: a line the source returns twice (never expected: GROUP BY) is summed, not lost
        c.execute("CREATE TEMP TABLE _slc_lines AS SELECT order_date, fc_code, sku_code, so_code, customer_id, "
                  "SUM(qty) AS qty, SUM(n_rows) AS n_rows FROM temp._slc_stage GROUP BY order_date, fc_code, sku_code, "
                  "so_code, customer_id")
        c.execute("DROP TABLE temp._slc_stage")
        c.execute("CREATE INDEX temp._slc_lines_d ON _slc_lines(order_date)")
        deleted = inserted = 0
        for a, b in _day_chunks(date.fromisoformat(ws), date.fromisoformat(we)):
            with db.tx(c):
                deleted += c.execute("DELETE FROM so_lines_cache WHERE scope_key=? AND order_date BETWEEN ? AND ?",
                                     (scope_key, str(a), str(b))).rowcount
                inserted += c.execute(
                    "INSERT INTO so_lines_cache(scope_key, order_date, fc_code, sku_code, so_code, customer_id, qty, "
                    "n_rows, loaded_at) SELECT ?, order_date, fc_code, sku_code, so_code, customer_id, qty, n_rows, ? "
                    "FROM temp._slc_lines WHERE order_date BETWEEN ? AND ?", (scope_key, at, str(a), str(b))).rowcount
            _between_chunks()
        with db.tx(c):
            pruned = c.execute("DELETE FROM so_lines_cache WHERE scope_key=? AND order_date < ?",
                               (scope_key, str(first))).rowcount
        c.execute("DROP TABLE temp._slc_lines")
    finally:
        c.close()
    return {"window": res["window"], "estimated_bytes": res["estimated_bytes"], "cap_bytes": res["cap_bytes"],
            "lines_read": res["rows"], "source_rows": res["source_rows"], "qty_read": res["qty"],
            "cache_rows_replaced": deleted, "cache_rows_written": inserted, "cache_rows_pruned": pruned}


def _open_days(conn, start: date, end: date) -> pd.DataFrame:
    """open_days_df of flag_lines for [start, end], equivalent to the full calendar rows (bt820b.compact_open_days):
    the rows with hours > 0, one hours-0 row per series whose rows are all closed / NULL (covered, never open) and one
    row of no series on the source's last day (flag_lines takes the calendar end from it)."""
    from .bq.aux_sources import open_hours_source
    tbl, seller = open_hours_source()
    w = "source_table=? AND seller_code=? AND open_date BETWEEN ? AND ?"
    p = (tbl, seller, str(start), str(end))
    pos = conn.execute(f"SELECT fc_code, sku_code, open_date, total_open_hours FROM open_hours_daily WHERE {w} AND "
                       "total_open_hours > 0", p).fetchall()
    zero = conn.execute(f"SELECT fc_code, sku_code, MIN(open_date), 0.0 FROM open_hours_daily WHERE {w} GROUP BY 1, 2 "
                        "HAVING MAX(COALESCE(total_open_hours, 0) > 0) = 0", p).fetchall()
    last = conn.execute(f"SELECT MAX(open_date) FROM open_hours_daily WHERE {w}", p).fetchone()[0]
    rows = [tuple(r) for r in pos] + [tuple(r) for r in zero] + ([("\x00", "\x00", last, 0.0)] if last else [])
    df = pd.DataFrame(rows, columns=["fc_code", "sku_code", "open_date", "hours"])
    df["open_date"] = pd.to_datetime(df["open_date"].str[:10] if len(df) else df["open_date"])
    df["hours"] = df["hours"].astype(float)
    return df


def _groups(scope_key: str, d: date, first: date) -> pd.DataFrame:
    """fc_code, sku_code, group_code, computed_for: ROLLING_B7 groups (data.Inputs.groups) on every retraining weekday
    from the one on or before first to d-1; a series of the inputs without a group that week = B."""
    from .ml.sel2 import data, pipeline
    s = ss.get("sel2_pipeline")
    with db.read() as c:
        inputs = data.load_inputs(c, scope_key, d, s.open_hours_lag_days)
    keys = inputs.keys
    mi = pd.MultiIndex.from_arrays([keys["sku_code"].to_numpy(), keys["fc_code"].to_numpy()])
    parts = []
    m = pipeline.origin_of(first, s.retrain_weekday)
    while m < d:
        g = inputs.groups(m, "ROLLING_B7").reindex(mi).to_numpy(dtype=object)
        parts.append(pd.DataFrame({"fc_code": keys["fc_code"].to_numpy(), "sku_code": keys["sku_code"].to_numpy(),
                                   "group_code": [x if x in ("A", "B", "C") else "B" for x in g],
                                   "computed_for": pd.Timestamp(m)}))
        m += timedelta(days=7)
    del inputs
    gc.collect()
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=["fc_code", "sku_code", "group_code", "computed_for"])


def _sku_chunks(conn, scope_key: str) -> list[tuple[str, str]]:
    """Contiguous sku_code ranges [lo, hi] of about CHUNK_LINES cached lines each (a SKU never split)."""
    per = conn.execute("SELECT sku_code, COUNT(*) FROM so_lines_cache WHERE scope_key=? GROUP BY sku_code ORDER BY "
                       "sku_code", (scope_key,)).fetchall()
    out, lo, n = [], None, 0
    for sku, k in per:
        lo = sku if lo is None else lo
        n += k
        if n >= CHUNK_LINES:
            out.append((lo, sku))
            lo, n = None, 0
    if lo is not None:
        out.append((lo, per[-1][0]))
    return out


def _refresh_next_day(c, scope_key: str, first: date, before: date, d: date) -> int:
    """Stored flagged lines of days first (first cached day) .. before-1 whose next purchase was not seen yet (next_day
    NULL, known customer): the first later purchase day (qty > 0, < d) of the same customer x SKU x FC in the cache,
    and computed_for = d (the data end of next_day: Excess decides T7 as of a day from it). Every other column stays as
    stored. Lines of days before the cache never get a next_day from it; one still without a next purchase only gets
    computed_for = d when the cache holds no later purchase of its customer x SKU x FC either (its next purchase would
    have been found while its day was cached, so none happened before d): its T7 stays decidable after it left the
    cache. Returns the next_day updates. No commit."""
    from .ml.sel2 import spike
    n = c.execute(
        "UPDATE spike_flag_lines SET next_day = (SELECT MIN(l.order_date) FROM so_lines_cache l WHERE "
        "l.scope_key = spike_flag_lines.scope_key AND l.fc_code = spike_flag_lines.fc_code AND "
        "l.sku_code = spike_flag_lines.sku_code AND l.customer_id = spike_flag_lines.customer_id AND "
        "l.order_date > spike_flag_lines.d AND l.order_date < ? AND l.qty > 0), computed_for = ?, computed_at = ? "
        "WHERE scope_key = ? AND logic = ? AND history_days = ? AND d >= ? AND d < ? AND next_day IS NULL AND "
        "customer_id <> '' AND computed_for < ?",
        (str(d), str(d), now_iso(), scope_key, spike.LOGIC, spike.HISTORY_DAYS, str(first), str(before),
         str(d))).rowcount
    c.execute(
        "UPDATE spike_flag_lines SET computed_for = ?, computed_at = ? WHERE scope_key = ? AND logic = ? AND "
        "history_days = ? AND d < ? AND next_day IS NULL AND customer_id <> '' AND computed_for < ? AND NOT EXISTS ("
        "SELECT 1 FROM so_lines_cache l WHERE l.scope_key = spike_flag_lines.scope_key AND "
        "l.fc_code = spike_flag_lines.fc_code AND l.sku_code = spike_flag_lines.sku_code AND "
        "l.customer_id = spike_flag_lines.customer_id AND l.order_date > spike_flag_lines.d AND l.order_date < ? AND "
        "l.qty > 0)", (str(d), now_iso(), scope_key, spike.LOGIC, spike.HISTORY_DAYS, str(first), str(d), str(d)))
    return n


def full_done(conn, scope_key: str) -> dict | None:
    """The marker of the first full flag run of the scope (sync_state), None before it."""
    r = conn.execute("SELECT value_json FROM sync_state WHERE name=?", (FULL_MARK + scope_key,)).fetchone()
    return json.loads(r[0]) if r else None


def compute_flags(scope_key: str, d: date, full: bool | None = None) -> dict:
    """b. flags of the cached lines (data up to d-1), day0 = the first cached day. full (None = decided from the FLAG
    state: no finished full run of the scope yet, full_done; True = --reflag): every cached line, written for [first
    cached day, d-1] (the early days with a shorter history, as the research's fixed start), then the marker. Otherwise
    only the lines of [d-RECENT_DAYS, d-1] are recomputed and replaced (they have the full 180-day history in the 210-day
    cache); the stored lines of the cache days before only get their next purchase day (_refresh_next_day). Writes in
    transactions of WRITE_DAYS days. c. excess as of d."""
    from .ml.sel2 import spike
    s = ss.get("sel2_pipeline")
    end = d - timedelta(days=1)
    with db.read() as c:
        first = c.execute("SELECT MIN(order_date) FROM so_lines_cache WHERE scope_key=? AND order_date <= ?",
                          (scope_key, str(end))).fetchone()[0]
        if first is None:
            return {"flagged_lines": 0, "note": "no cached SO line"}
        first = date.fromisoformat(first[:10])
        mark = full_done(c, scope_key)
        if full is None:
            full = mark is None
        chunks = _sku_chunks(c, scope_key)
        od = _open_days(c, first, end)
    # a night after a gap (no flag run for > RECENT_DAYS days): from the day of the last flag run, so no cached line is
    # left without flags (review R-148b)
    last = date.fromisoformat(mark.get("last_computed_for", mark["computed_for"])) if mark else d
    w0 = first if full else max(first, min(d - timedelta(days=RECENT_DAYS), last))
    groups = _groups(scope_key, d, first)
    parts, n_lines = [], 0
    for lo, hi in chunks:
        with db.read() as c:
            rows = c.execute("SELECT order_date, so_code, customer_id, sku_code, fc_code, qty FROM so_lines_cache WHERE "
                             "scope_key=? AND sku_code BETWEEN ? AND ? AND order_date BETWEEN ? AND ?",
                             (scope_key, lo, hi, str(first), str(end))).fetchall()
        L = pd.DataFrame([tuple(r) for r in rows], columns=["d", "so_code", "customer_id", "sku_code", "fc_code", "qty"])
        del rows
        L["d"] = pd.to_datetime(L["d"])
        L["qty"] = L["qty"].astype(float)
        n_lines += len(L)
        fl = spike.flag_lines(L, od, groups, pd.Timestamp(w0), pd.Timestamp(end), spike.HISTORY_DAYS,
                              data_end=pd.Timestamp(end), day0=pd.Timestamp(first))
        parts.append(fl[fl["n_signals_raw"] >= 1])
        del L, fl
        gc.collect()
    fl = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=list(spike.OUT_COLS))
    written = next_days = 0
    for a, b in _day_chunks(w0, end):
        with db.tx() as c:
            written += spike.write_flags(c, scope_key, fl, d, a, b)
        _between_chunks()
    if not full:
        val = {**mark, "last_computed_for": str(max(d, last))}
        with db.tx() as c:
            next_days = _refresh_next_day(c, scope_key, first, w0, d)
    else:
        val = {"computed_for": str(d), "first_day": str(first), "last_computed_for": str(d)}
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(name) DO "
                  "UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                  (FULL_MARK + scope_key, json.dumps(val), now_iso()))
    del fl, parts
    gc.collect()
    with db.read() as c:
        stored = spike.read_flags(c, scope_key)
    ex = spike.Excess(stored)
    cells = ex.cells_frame(d, LEVEL, s.spike_e4_n)
    with db.tx() as c:
        n_ex = spike.write_excess_daily(c, scope_key, cells, LEVEL, s.spike_e4_n, d)
    return {"first_day": str(first), "written_from": str(w0), "full": full, "next_day_refreshed": next_days,
            "end": str(end), "chunks": len(chunks), "lines": n_lines, "flagged_lines": written,
            "stored_flag_rows": len(stored), "excess_rows": n_ex, "excess_total": round(float(cells["excess"].sum()), 3),
            "level": LEVEL, "e4_n": s.spike_e4_n, "groups_weeks": int(groups["computed_for"].nunique()) if len(groups) else 0}


def run(d: date | None = None, initial: bool = False, dry_run: bool = False, reflag: bool = False) -> dict:
    """The step of day d (default today, Vietnam): a + b + c; dry_run = the BigQuery dry run of a only (no write).
    initial = read the whole cache window again: refused (SPIKE_LINES_REFLAG_REQUIRED) when the scope already has
    flags, unless reflag. reflag = derive the flags of every cached line again (training data of the cleaning: the
    stored flags of the cache days are replaced)."""
    from .bq import connector
    d = d or today_vn()
    if not ss.get("sel2_pipeline").enabled:
        return {"status": "SKIPPED", "reason_code": "SEL2_DISABLED", "business_date": str(d)}
    bq = ss.get("bigquery")
    if not bq.customer_id_column:
        raise AppError("SPIKE_LINES_NO_CUSTOMER", 409, detail="bigquery.customer_id_column is not set")
    scope_key = _scope_key()
    if initial and not reflag and not dry_run:
        with db.read() as c:
            if c.execute("SELECT 1 FROM spike_flag_lines WHERE scope_key=? LIMIT 1", (scope_key,)).fetchone():
                raise AppError("SPIKE_LINES_REFLAG_REQUIRED", 409, detail="the scope already has spike flags: "
                               "--initial re-derives them only with --reflag")
    first, start, end = read_range(scope_key, d, initial)
    out = {"business_date": str(d), "scope_key": scope_key, "cache_first_day": str(first), "read_start": str(start),
           "read_end": str(end), "initial": initial, "reflag": reflag}
    if dry_run:
        r = connector.fetch_so_lines(start, end, None, dry_run_only=True)
        return {**out, "status": "DRY_RUN", "estimated_bytes": r["estimated_bytes"], "cap_bytes": r["cap_bytes"],
                "estimated_gb": round(r["estimated_bytes"] / 1e9, 3)}
    out["lines"] = load_lines(scope_key, start, end, first)
    out["flags"] = compute_flags(scope_key, d, full=True if reflag else None)
    out["status"] = "DONE"
    return out


# ------------------------------------------------------------------ server side (scheduler)
def _call_child(args: list[str], timeout: int) -> dict:
    from .ml.sel2 import jobs
    if _child_runner is not None:
        return _child_runner(args, timeout)
    return jobs.run_child(args, timeout, cmd=jobs.child_command(args))


def job(job_id, params: dict) -> dict:
    """runner handler of SPIKE_LINES (jobs/runner.py; key SPIKE_LINES:<day>): free commit below MIN_COMMIT_MB -> not
    started; else the child `spike-lines --date D --yes` (killed after TIMEOUT_S). Never raises: anything but a DONE /
    SKIPPED result is {"status": "FAILED"} (the runner records the row FAILED, no retry, no ERROR alert) + ONE WARNING
    alert SPIKE_LINES_FAILED written here (no customer id in it). D-1, the refresh and the export go on."""
    from .jobs import resources
    d = date.fromisoformat(str((params or {}).get("business_date") or today_vn())[:10])
    res, code, err = None, None, None
    try:
        avail = resources.snapshot().get("commit_avail")
        if avail is not None and avail / resources.MB < MIN_COMMIT_MB:
            code, err = "SEL2_LOW_MEMORY", f"free commit {avail / resources.MB:.0f} MB < {MIN_COMMIT_MB} MB"
        else:
            child = _call_child(["spike-lines", "--date", str(d), "--yes"], TIMEOUT_S)
            res = child.get("result")
            if not (child.get("ok") and child.get("exit_code", 0) == 0 and (res or {}).get("status") in ("DONE",
                                                                                                         "SKIPPED")):
                code = child.get("code") or "SEL2_CHILD_FAILED"
                err = str(child.get("detail") or child.get("refused") or code)[:1000]
    except Exception as e:  # noqa: BLE001 - only a flag: D-1, the refresh and the export go on
        code = getattr(e, "code", None) or type(e).__name__
        err = f"{type(e).__name__}: {e}"[:1000]
    if code is None:
        return {**res, "business_date": str(d)}
    with db.tx() as c:
        db.alert(c, "WARNING", ALERT, {"business_date": str(d), "cause": code, "job_id": job_id}, "job", job_id)
    log.warning("spike lines step failed", extra={"ctx": {"business_date": str(d), "code": code}})
    return {"status": "FAILED", "reason_code": ALERT, "cause": code, "error": err, "business_date": str(d)}


def today_row(conn, d: date) -> dict | None:
    return db.one(conn, "SELECT id, status, created_at, started_at FROM job_runs WHERE idempotency_key=?", (job_key(d),))
