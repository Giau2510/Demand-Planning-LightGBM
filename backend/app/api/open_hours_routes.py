"""1.4.15 lot 4: "read the open hours again" from the UI - the open-hours history of the configured BigQuery source
(daily_forecast.openhours_table, seller daily_forecast.seller_code) for days the app has NOT stored, behind the gates of
the other 1.4.15 write paths.

Owner rule: open hours are never filled in. Only the real source values are read (read-only BigQuery through
connector._run: dry run, maximum_bytes_billed, SELECT only); nothing is inferred, no substitute value is written and
open_hours_override is never called. A source NULL is stored NULL and a day the source does not return gets no row: both
stay MISSING downstream, never 0.

Why not ml/sel2/pipeline.openhours_backfill (CLI sel2-openhours-backfill) as it is: its aux_sources.fetch_open_hours
(1) UPSERTS - a stored non-NULL value is REPLACED by the new source value and the old value is kept nowhere (no change
log; undo = restore a backup) - and (2) records every sub-range as a completed read in aux_source_reads: the newest one
is the watermark of the daily refresh (daily_refresh.open_hours_range / sync_open_hours) and of the export's TOM_TAT
line, so recording a read of OLD days would move that watermark back (a FULL re-read and a wrong "built at" next time).
So this path:
  * reads only the days of [start, end] that have NO stored row for the configured table / seller (FILL_MISSING_DAYS
    only; a day with any stored row is skipped, never re-read: a partly stored day cannot be completed here);
  * runs the same SELECT as aux_sources.fetch_open_hours (_sql; a test keeps both identical) per consecutive missing
    sub-range of at most READ_DAYS days, rechecking just before each read that the days are still missing;
  * INSERTs with ON CONFLICT DO NOTHING: a row stored meanwhile (e.g. by the refresh) is never overwritten (counted as
    skipped_existing);
  * records NO aux_source_reads entry (the refresh watermark is untouched); every run is in the audit
    (OPEN_HOURS_REREAD_REQUESTED, then _DONE or _FAILED with every read: days, rows read, inserted, skipped, bytes).
Undo: the inserted rows are exactly the rows of those days with loaded_at = the run's `loaded_at` (given in the result
and the audit); there is no delete endpoint (deleting data waits for the owner's approval).

GET  /api/open-hours-reread/plan?start=&end=[&estimate=true]  read-only plan (days, stored / missing days, reads, the
     dry-run bytes of each read when estimate - a BigQuery dry run bills nothing), `signature` of the missing days.
POST /api/open-hours-reread  {start, end, signature, confirm_text DOC-LAI-GIO-MO-BAN-<today, Vietnam>, reason >= 10}:
     202, runs in a background thread; at most MAX_DAYS days per run; refused when busy (the jobs and production
     windows of data_policy_routes._busy_state, the saved schedule times of held_lines_routes._soon), when the missing
     days changed since the plan, when another re-read runs.
GET  /api/open-hours-reread/status  the task (sync_state STATE, heartbeat; a task of a stopped app is INTERRUPTED and
     never blocks: SQLite rolled back its unfinished chunk, its committed chunks stay and are in its audit progress).
The day range must lie inside the data window (data_policy.window_start_date .. yesterday, Vietnam).
Write gate (as held_lines_routes): _guard (operations lock files named by DF_OPS_LOCK / DF_HEAVY_LOCK / DF_RUN_DIR -
not checked when none is set: ops_lock_checked = false -, busy / windows / schedule times) is checked at the request,
at the claim, before every BigQuery read and inside every write transaction: any failure stops the run (chunks already
written stay, audited). No backup is taken (only missing days are inserted; nothing stored is changed), so there is no
disk gate here.
The plan and the status give `description` (DESCRIPTION_CODES with their vi / en texts): what the button solves and
what it does not.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import date, timedelta

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from .. import db
from .. import settings_service as ss
from ..bq import aux_sources, connector
from ..jobs import runner
from ..messages import AppError, msg
from ..timeutil import now_iso, now_utc, parse_iso, today_vn
from . import background
from . import held_lines_routes as hl
from .data_policy_routes import REASON_MAX, REASON_MIN, _busy_state

log = logging.getLogger("df.open_hours_reread")
router = APIRouter(prefix="/api")

MAX_DAYS = 60               # days per run
READ_DAYS = 15              # days per BigQuery read (as ml/sel2/pipeline.OPEN_HOURS_READ_DAYS)
INSERT_CHUNK_ROWS = 200_000  # rows per write transaction (as aux_sources.UPSERT_CHUNK_ROWS)
STATE = "open_hours_reread"
MODE = "FILL_MISSING_DAYS_ONLY"
QUERY_KIND = "open_hours_reread"
DRY_KIND = "open_hours_reread_plan"
# what the button solves / does not solve (texts in messages.CATALOG), shown by the UI with the plan
DESCRIPTION_CODES = ("OH_REREAD_SOLVES_EMPTY_DAYS", "OH_REREAD_NOT_PARTIAL_DAYS", "OH_REREAD_NOT_SOURCE_MISSING",
                     "OH_REREAD_NEVER_OVERWRITES", "OH_REREAD_LIMITS", "OH_REREAD_CHANGES_SEL2_NUMBERS")

_proc_lock = threading.Lock()
_current: dict = {"task_id": None, "thread": None}


# ------------------------------------------------------------------ helpers
def _confirm_text() -> str:
    return f"DOC-LAI-GIO-MO-BAN-{today_vn().isoformat()}"


def _day(v: str | None, name: str) -> date:
    v = (v or "").strip()
    try:
        d = date.fromisoformat(v)
    except ValueError:
        d = None
    if d is None or d.isoformat() != v:
        raise AppError("OPEN_HOURS_REREAD_INVALID_RANGE", 422, detail=f"{name} must be YYYY-MM-DD")
    return d


def _range(start: str | None, end: str | None) -> tuple[date, date]:
    a, b = _day(start, "start"), _day(end, "end")
    floor = date.fromisoformat(ss.get("data_policy").window_start_date)
    yesterday = today_vn() - timedelta(days=1)
    if a > b or a < floor or b > yesterday:
        raise AppError("OPEN_HOURS_REREAD_INVALID_RANGE", 422, detail=f"need {floor} <= start <= end <= {yesterday} "
                       "(the data window)", window_start=str(floor), yesterday=str(yesterday))
    n = (b - a).days + 1
    if n > MAX_DAYS:
        raise AppError("OPEN_HOURS_REREAD_TOO_MANY_DAYS", 422, detail=f"{n} days > {MAX_DAYS} per run", days=n,
                       max_days=MAX_DAYS)
    return a, b


def _sql(table: str) -> str:
    """The SELECT of aux_sources.fetch_open_hours (kept identical by a test)."""
    return (f"SELECT fc_code, sku_code, CAST(open_date AS STRING) AS open_date, MAX(total_open_hours) AS total_open_hours, "
            f"COUNT(DISTINCT item_code) AS n_items FROM `{table}` "
            f"WHERE open_date BETWEEN @start AND @end AND seller_code = @seller "
            f"AND fc_code IS NOT NULL AND sku_code IS NOT NULL GROUP BY fc_code, sku_code, open_date "
            f"ORDER BY open_date, fc_code, sku_code")


def _query(a: date, b: date, dry_run_only: bool, table: str | None = None, seller: str | None = None) -> dict:
    """The SELECT of [a, b]; a running task passes its own table / seller (never read again from the settings)."""
    bq = ss.get("bigquery")
    if table is None or seller is None:
        table, seller = aux_sources.open_hours_source()
    return connector._run(connector._client(bq), bq, DRY_KIND if dry_run_only else QUERY_KIND, _sql(table),
                          [("start", "DATE", a), ("end", "DATE", b), ("seller", "STRING", seller)],
                          dry_run_only=dry_run_only)


def _stored_days(a: date, b: date, table: str | None = None, seller: str | None = None) -> dict[str, int]:
    """Stored rows per day of [a, b] for the configured table / seller - or the task's own (index idx_ohd_date only)."""
    if table is None or seller is None:
        table, seller = aux_sources.open_hours_source()
    with db.read() as c:
        return {r[0]: r[1] for r in c.execute(
            "SELECT open_date, COUNT(*) FROM open_hours_daily INDEXED BY idx_ohd_date WHERE source_table=? AND "
            "seller_code=? AND open_date BETWEEN ? AND ? GROUP BY open_date", (table, seller, str(a), str(b)))}


def _reads(missing: list[str]) -> list[tuple[str, str]]:
    """Consecutive runs of missing days, cut at READ_DAYS days."""
    out: list[tuple[str, str]] = []
    for d in missing:
        if out and date.fromisoformat(out[-1][1]) + timedelta(days=1) == date.fromisoformat(d) \
                and (date.fromisoformat(d) - date.fromisoformat(out[-1][0])).days < READ_DAYS:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def _plan(a: date, b: date, estimate: bool) -> dict:
    table, seller = aux_sources.open_hours_source()
    stored = _stored_days(a, b)
    days = [str(a + timedelta(days=i)) for i in range((b - a).days + 1)]
    missing = [d for d in days if not stored.get(d)]
    reads = _reads(missing)
    sig = hashlib.sha256(json.dumps({"table": table, "seller": seller, "start": str(a), "end": str(b),
                                     "missing": missing}).encode()).hexdigest()
    out = {"start": str(a), "end": str(b), "mode": MODE, "source_table": table, "seller_code": seller,
           "days": len(days), "days_stored": len(days) - len(missing), "days_missing": len(missing),
           "stored_rows": sum(stored.values()), "missing_days": missing,
           "per_day": [{"day": d, "stored_rows": stored.get(d, 0)} for d in days],
           "reads": [{"start": x, "end": y} for x, y in reads], "signature": sig if missing else None,
           "estimated_bytes": None, "estimate_error": None}
    if estimate and reads:
        try:
            total = 0
            for r, (x, y) in zip(out["reads"], reads):
                r["estimated_bytes"] = _query(date.fromisoformat(x), date.fromisoformat(y), True)["estimated_bytes"]
                total += r["estimated_bytes"]
            out["estimated_bytes"] = total
        except AppError as e:      # the plan stays usable; the run's own dry run + cap still apply
            out["estimate_error"] = {"code": e.code, "detail": e.detail}
    return out


def _check_busy(c) -> dict:
    st = _busy_state(c, hl.RELEASE_BUSY_JOB_TYPES)
    soon = hl._soon(c)
    win = None if st["window"] else soon["window_soon"]
    if st["busy"] or win or soon["schedule_times"]:
        detail = ", ".join(x for x in (
            st["detail"],
            f"production window {win} (Vietnam) starts in {hl.START_MARGIN_MIN} minutes or less" if win else None,
            *(f"{x['setting']} {x['time']} (Vietnam) within -{hl.SCHEDULE_BEHIND_MIN}..+{hl.SCHEDULE_AHEAD_MIN} minutes"
              for x in soon["schedule_times"])) if x)
        raise AppError("OPEN_HOURS_REREAD_BUSY", 409, detail=detail, window=st["window"], window_soon=win,
                       schedule_times=soon["schedule_times"], jobs=st["jobs"], stale_ignored=st["stale_ignored"],
                       stale_ignored_total=st["stale_ignored_total"])
    return st


def _description() -> list[dict]:
    return [msg(c) for c in DESCRIPTION_CODES]


def _guard(c) -> dict:
    """The write gate (operations locks, another background write, busy / windows / schedule times)."""
    hl.check_ops_locks()
    hl.check_other_running(c, STATE)
    return _check_busy(c)


# ------------------------------------------------------------------ task state (sync_state STATE)
def _read_state(c) -> dict | None:
    r = c.execute("SELECT value_json FROM sync_state WHERE name=?", (STATE,)).fetchone()
    if not r:
        return None
    try:
        v = json.loads(r[0])
    except (TypeError, ValueError):
        return {"status": "UNREADABLE"}
    return v if isinstance(v, dict) else {"status": "UNREADABLE"}


def _write_state(c, st: dict) -> None:
    c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET "
              "value_json=excluded.value_json, updated_at=excluded.updated_at", (STATE, json.dumps(st, default=str),
                                                                                  now_iso()))


def _alive(st: dict) -> bool:
    if st.get("status") != "RUNNING":
        return False
    if st.get("owner") == runner.OWNER:
        return _current["task_id"] == st.get("task_id")
    try:
        hb = parse_iso(st.get("heartbeat_at") or st.get("started_at"))
    except (TypeError, ValueError):
        hb = None
    return hb is not None and (now_utc() - hb).total_seconds() <= hl.STALE_AFTER_S


def _view_state(c) -> dict | None:
    st = _read_state(c)
    if not st or st.get("status") != "RUNNING" or _alive(st):
        return st
    return {**st, "status": "INTERRUPTED", "error": {"code": "OPEN_HOURS_REREAD_INTERRUPTED",
                                                     "detail": "the app stopped during the re-read"}}


def _update(task_id: str, **kw) -> dict | None:
    with db.tx() as c:
        st = _read_state(c) or {}
        if st.get("task_id") != task_id:
            return None
        st = {**st, **kw, "heartbeat_at": now_iso()}
        _write_state(c, st)
        return st


def _heartbeat(task_id: str, done: threading.Event) -> None:
    while not done.wait(hl.HEARTBEAT_S):
        try:
            if _update(task_id) is None:
                return
        except Exception:  # noqa: BLE001 - a missed heartbeat only makes another process see the task as stopped later
            log.warning("open-hours re-read heartbeat failed", exc_info=True, extra={"ctx": {"task_id": task_id}})


# ------------------------------------------------------------------ the background re-read
def _insert(table: str, seller: str, rows: list[dict], loaded: str) -> tuple[int, int, list[str]]:
    """(inserted, skipped_existing, skipped_days); a stored row is never replaced; a source NULL stays NULL (never 0).
    A day that got rows from another writer (loaded_at not this run's) since the plan is skipped WHOLE, checked inside
    each write transaction; a write transaction always holds WHOLE days (about INSERT_CHUNK_ROWS rows, never a day cut
    in two), so a partly stored day is never completed halfway (FILL_MISSING_DAYS_ONLY)."""
    inserted, skipped, skipped_days = 0, 0, []
    by_day: dict[str, list[tuple]] = {}
    for r in rows:
        v = (table, seller, str(r["fc_code"]), str(r["sku_code"]), str(r["open_date"])[:10],
             None if r.get("total_open_hours") is None else float(r["total_open_hours"]),
             None if r.get("n_items") is None else int(r["n_items"]), loaded)
        by_day.setdefault(v[4], []).append(v)
    batches: list[list[tuple]] = [[]]
    for d in sorted(by_day):
        if batches[-1] and len(batches[-1]) + len(by_day[d]) > INSERT_CHUNK_ROWS:
            batches.append([])
        batches[-1] += by_day[d]
    for vals in batches:
        if not vals:
            continue
        with db.tx() as c:
            _guard(c)                           # inside the write transaction: nothing written when it fails
            days = sorted({v[4] for v in vals})
            other = {r[0] for r in c.execute(
                f"SELECT DISTINCT open_date FROM open_hours_daily INDEXED BY idx_ohd_date WHERE source_table=? AND "
                f"seller_code=? AND open_date IN ({','.join('?' * len(days))}) AND loaded_at != ?",
                (table, seller, *days, loaded))} if days else set()
            if other:
                skipped_days += sorted(other)
                skipped += sum(1 for v in vals if v[4] in other)
                vals = [v for v in vals if v[4] not in other]
            cur = c.executemany("INSERT INTO open_hours_daily(source_table, seller_code, fc_code, sku_code, open_date, "
                                "total_open_hours, n_items, loaded_at) VALUES (?,?,?,?,?,?,?,?) "
                                "ON CONFLICT(source_table, seller_code, fc_code, sku_code, open_date) DO NOTHING", vals)
            inserted += cur.rowcount
    return inserted, len(rows) - inserted, skipped_days


def _worker(st: dict, done: threading.Event) -> None:
    task_id = st["task_id"]
    table, seller, loaded = st["source_table"], st["seller_code"], st["loaded_at"]
    progress: list[dict] = []
    error = None
    try:
        for r in st["reads"]:
            if aux_sources.open_hours_source() != (table, seller):
                raise AppError("OPEN_HOURS_REREAD_CONFIG_CHANGED", 409, detail="daily_forecast.openhours_table / "
                               "seller_code changed since the task started", task_source=[table, seller])
            a, b = date.fromisoformat(r["start"]), date.fromisoformat(r["end"])
            stored = _stored_days(a, b, table, seller)   # just before the read: a day stored meanwhile is not read
            todo = _reads([str(a + timedelta(days=i)) for i in range((b - a).days + 1)
                           if not stored.get(str(a + timedelta(days=i)))])
            if len(todo) != 1 or todo[0] != (r["start"], r["end"]):
                progress.append({**r, "skipped_days_stored_meanwhile": sorted(stored)})
            for x, y in todo:
                with db.read() as c:
                    _guard(c)                   # before every BigQuery read
                res = _query(date.fromisoformat(x), date.fromisoformat(y), False, table, seller)
                ins, skip, skip_days = _insert(table, seller, res["rows"], loaded)
                progress.append({"start": x, "end": y, "rows_read": len(res["rows"]), "inserted": ins,
                                 "skipped_existing": skip, "skipped_days_stored_meanwhile": skip_days,
                                 "estimated_bytes": res.get("estimated_bytes"),
                                 "days_with_rows": len({str(z["open_date"])[:10] for z in res["rows"]})})
                _update(task_id, progress=progress)
    except AppError as e:
        error = {"code": e.code, "detail": e.detail, "status": e.status}
    except Exception as e:  # noqa: BLE001 - recorded in the task state; an unfinished chunk was rolled back
        log.error("open-hours re-read failed", exc_info=True, extra={"ctx": {"task_id": task_id}})
        error = {"code": "OPEN_HOURS_REREAD_FAILED", "detail": f"{type(e).__name__}: {e}"[:500]}
    finally:
        done.set()
        try:
            reads = [p for p in progress if "rows_read" in p]
            result = {"loaded_at": loaded, "reads": progress, "rows_read": sum(p["rows_read"] for p in reads),
                      "inserted": sum(p["inserted"] for p in reads),
                      "skipped_existing": sum(p["skipped_existing"] for p in reads),
                      "estimated_bytes": sum(p["estimated_bytes"] or 0 for p in reads),
                      "undo": {"table": "open_hours_daily", "source_table": table, "seller_code": seller,
                               "loaded_at": loaded, "days": [st["start"], st["end"]]}}
            with db.tx() as c:
                cur = _read_state(c) or {}
                if cur.get("task_id") == task_id:
                    _write_state(c, {**cur, "status": "FAILED" if error else "SUCCEEDED", "finished_at": now_iso(),
                                     "heartbeat_at": now_iso(), "result": result, "error": error})
                db.audit(c, "OPEN_HOURS_REREAD_FAILED" if error else "OPEN_HOURS_REREAD_DONE", "open_hours", table,
                         {"task_id": task_id, "seller_code": seller, "start": st["start"], "end": st["end"],
                          "result": result, "error": error})
        except Exception:  # noqa: BLE001 - the state stays RUNNING: shown INTERRUPTED once the lock is free
            log.error("open-hours re-read state not written", exc_info=True, extra={"ctx": {"task_id": task_id}})
        finally:
            _current.update(task_id=None, thread=None)
            _proc_lock.release()


# ------------------------------------------------------------------ routes
@router.get("/open-hours-reread/plan")
def plan(start: str | None = None, end: str | None = None, estimate: bool = True):
    """Read-only (a BigQuery DRY RUN only when estimate: no byte billed, nothing written)."""
    a, b = _range(start, end)
    with db.read() as c:
        task = _view_state(c)
        other = hl.other_running(c, STATE)
    return {**_plan(a, b, estimate), "max_days": MAX_DAYS, "read_days": READ_DAYS, "confirm_text": _confirm_text(),
            "reason_min_length": REASON_MIN, "task": task, "ops_lock_checked": hl.ops_lock_checked(),
            "ops_locks": hl.ops_locks(), "ops_lock_source": hl.ops_lock_source(), "busy_other_task": other,
            "description_codes": list(DESCRIPTION_CODES), "description": _description()}


class RereadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str
    end: str
    signature: str
    confirm_text: str | None = None
    reason: str | None = None


@router.post("/open-hours-reread", status_code=202)
def reread(body: RereadBody):
    a, b = _range(body.start, body.end)
    reason = " ".join((body.reason or "").split())
    if len(reason) > REASON_MAX:
        raise AppError("OPEN_HOURS_REREAD_INVALID_RANGE", 422, detail=f"reason longer than {REASON_MAX} characters")
    expected_text = _confirm_text()
    if (body.confirm_text or "").strip() != expected_text or len(reason) < REASON_MIN:
        raise AppError("OPEN_HOURS_REREAD_CONFIRM_REQUIRED", 409,
                       detail=f"type {expected_text} and a reason of at least {REASON_MIN} characters",
                       confirm_text=expected_text, reason_min_length=REASON_MIN)
    if not _proc_lock.acquire(blocking=False):
        raise AppError("OPEN_HOURS_REREAD_RUNNING", 409, detail=f"re-read {_current['task_id']} is running",
                       task_id=_current["task_id"])
    claimed, started = None, False
    try:
        p = _plan(a, b, estimate=False)
        if not p["days_missing"]:
            raise AppError("OPEN_HOURS_REREAD_NOTHING", 409, detail="every day of the range has stored open hours")
        if p["signature"] != body.signature:
            raise AppError("OPEN_HOURS_REREAD_PLAN_STALE", 409, detail="the missing days changed since the plan",
                           days_missing=p["days_missing"])
        task_id = db.new_id("OHR")
        _current.update(task_id=task_id)
        with db.tx() as c:   # gate, task state and request audit in ONE write transaction
            busy = _guard(c)
            old = _read_state(c)
            if old and old.get("status") == "RUNNING":
                if _alive(old):
                    raise AppError("OPEN_HOURS_REREAD_RUNNING", 409, detail=f"re-read {old.get('task_id')} is running",
                                   task_id=old.get("task_id"))
                db.audit(c, "OPEN_HOURS_REREAD_INTERRUPTED", "open_hours", old.get("source_table"),
                         {"task_id": old.get("task_id"), "owner": old.get("owner"), "progress": old.get("progress")})
            at = now_iso()
            st = {"task_id": task_id, "status": "RUNNING", "owner": runner.OWNER, "mode": MODE,
                  "source_table": p["source_table"], "seller_code": p["seller_code"], "start": p["start"],
                  "end": p["end"], "reads": p["reads"], "days_missing": p["days_missing"], "signature": p["signature"],
                  "reason": reason, "loaded_at": at, "started_at": at, "heartbeat_at": at, "finished_at": None,
                  "progress": [], "result": None, "error": None}
            _write_state(c, st)
            db.audit(c, "OPEN_HOURS_REREAD_REQUESTED", "open_hours", p["source_table"],
                     {"task_id": task_id, "seller_code": p["seller_code"], "start": p["start"], "end": p["end"],
                      "missing_days": p["missing_days"], "reads": p["reads"], "reason": reason,
                      "stale_ignored_total": busy["stale_ignored_total"]})
        claimed = st
        done = threading.Event()
        th = threading.Thread(target=_worker, args=(st, done), name=f"oh-reread-{task_id}", daemon=True)
        _current.update(thread=th)
        th.start()
        started = True
        threading.Thread(target=_heartbeat, args=(task_id, done), name=f"oh-reread-hb-{task_id}", daemon=True).start()
    except BaseException as e:
        if not started:
            try:
                if claimed is not None:
                    _update(claimed["task_id"], status="FAILED", finished_at=now_iso(),
                            error={"code": "OPEN_HOURS_REREAD_FAILED", "detail": f"{type(e).__name__}: {e}"[:500]})
            finally:
                _current.update(task_id=None, thread=None)
                _proc_lock.release()
        raise
    if background.SYNC_MODE:
        th.join()
    with db.read() as c:
        return {"accepted": True, "task": _view_state(c)}


@router.get("/open-hours-reread/status")
def status():
    with db.read() as c:
        task = _view_state(c)
    return {"task": task, "running": bool(task and task.get("status") == "RUNNING"),
            "description_codes": list(DESCRIPTION_CODES), "description": _description()}


hl.register_task(STATE, _alive)
