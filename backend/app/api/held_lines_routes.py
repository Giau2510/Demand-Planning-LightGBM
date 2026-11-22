"""1.4.15 lot 3: the owner's release of held lines (data/history_sync.release_holds, CLI `held-lines --release`) from
the UI, behind the gates of the other 1.4.15 write paths.

GET  /api/held-lines                  read-only: the ACTIVE held lines of the BigQuery scope (the one D-1 writes; the CLI
                                      uses the same key): lines, units, keys, per cause, groups per SKU x FC / day / cause
                                      or the lines themselves, PAGE_MAX rows per page at most. Read through the partial
                                      index idx_dhl_active only, stopped at SCAN_CAP lines (status CAPPED) or after
                                      SUMMARY_TIMEOUT_S (status TIMEOUT: partial figures); never the whole table.
POST /api/held-lines/release-preview  dry run of release_holds' own selection (cause, SKU, day range - release_holds has no
                                      FC filter): lines, units, keys, every stored row before / after, and `signature`
                                      (SHA-256 of the scope key, the filter and every selected line id and quantity).
                                      Refused above MAX_LINES lines or MAX_UNITS units per release (HELD_RELEASE_TOO_LARGE,
                                      with the largest groups to narrow the choice by SKU / days / cause), when busy
                                      (HELD_RELEASE_BUSY) and when a selected key has no stored row or fewer stored units
                                      than its held lines (HELD_RELEASE_ROW_INCONSISTENT: reported, never fixed here).
                                      Never writes, never backs up.
POST /api/held-lines/release          the selection read again must give the previewed signature (else
                                      HELD_RELEASE_PREVIEW_STALE), the typed text NHA-DONG-GIU-<today, Vietnam> and a reason
                                      of at least REASON_MIN characters, free space for the backup (HELD_RELEASE_DISK_SPACE),
                                      not busy, no other release running. Answers 202 at once: release_holds(apply=True)
                                      runs in a background thread - its online backup of the whole database (an
                                      uncompressed copy, an integrity check, a zip and its test: minutes on a large
                                      database) then ONE write transaction that checks the lines again under the write lock
                                      (409 when they changed), writes HOLD_RELEASE in demand_change_log / demand_sync_runs
                                      and the audit HELD_LINES_RELEASED.
GET  /api/held-lines/release-status   the release task and the latest HOLD_RELEASE runs.

One release at a time: an in-process lock + the task state in sync_state STATE (owner = runner.OWNER, heartbeat every
HEARTBEAT_S). A RUNNING task whose owner is this process but whose thread is gone, or whose owner is another process
with no heartbeat for STALE_AFTER_S (the app stopped or crashed during the release), is INTERRUPTED: shown as such,
never blocks the next release (which records it in the audit). Whether its write was committed is read from
demand_sync_runs (summary `by` = "API <task id>: <reason>"); SQLite rolls an unfinished write back. A backup cut by the
stop can leave its temporary files (app-*-pre-hold-release.db, *.zip.part): listed, never deleted here.
Busy: data_policy_routes._busy_state over RELEASE_BUSY_JOB_TYPES and the production windows; a release does not start
less than START_MARGIN_MIN minutes before a production window, nor when a saved schedule time (SCHEDULE_TIME_FIELDS)
falls in the next SCHEDULE_AHEAD_MIN minutes or the last SCHEDULE_BEHIND_MIN minutes (starting points: the backup time
on the real database is not measured yet; D-0 slots are not avoided, D-0 is a side task). The error names the blocking
window / setting and time.
Selection: the background thread passes the previewed line ids (expected_ids) to release_holds, which refuses
(HELD_RELEASE_PREVIEW_STALE, nothing written) when the ACTIVE lines of the filter differ - checked before its backup
and again under the write lock; the released set is therefore always the previewed one.
Known limits (behaviour of release_holds, the same as the CLI): the backup runs inside the app process and does NOT
take the operations HEAVY_LOCK (run/HEAVY_LOCK of the operations scripts); a D-1 the scheduler starts while the backup runs is not held back -
if it changes the selected lines first the release is refused after the backup (409, backup kept), if it writes after
the release its own marker check makes it retry.
Disk (owner 23/11/2026, this button's own gate - not the install chain's): backup_database (backup.py, shared with
deploy-upgrade, not changed here) has no space check of its own; it writes an uncompressed copy of the database (only
to run integrity_check on it), zips it (measured 17/11/2026: 13.27 GB -> 1.245 GB, 9.4 %) and then deletes the copy, so
its peak is about database + zip. The free space of the backup folder must reach BACKUP_SPACE_FACTOR x (database + WAL
+ estimated zip) - the zip estimated by the newest backup-*.zip there, else ZIP_RATIO_FALLBACK x the database - and
never less than BACKUP_SPACE_FACTOR x (database + WAL) (the raw copy always needs 1x, plus a reserve, whatever the zip
estimate). The refusal gives needed / free / missing bytes. Backups are never deleted here; the result gives the backup
file and its path.
Write gate (_guard): operations lock files absent, not busy, no window / schedule time near - checked at the request,
at the claim, before the backup and again INSIDE release_holds' write transaction (before_write, after the backup): any
failure -> 409, nothing written. Operations locks are files named by environment variables only (no path is hard-coded):
DF_OPS_LOCK / DF_HEAVY_LOCK (file paths) and DF_RUN_DIR (a folder: its OPS_LOCK and HEAVY_LOCK). When none is set,
the run folder derived from the app's data folder (paths.data_dir().parent.parent / "run") is used when it exists
(ops_lock_source "derived"); otherwise the locks are NOT checked: ops_lock_checked = false.
One background write at a time across the three buttons (release, open-hours re-read, sync rollback): a RUNNING task
of another button (alive: its own process's thread, or a fresh heartbeat) refuses with HEAVY_WRITE_ANOTHER_RUNNING, at
the request and inside the write transaction (_guard); previews give busy_other_task. An INTERRUPTED task never blocks.
Daily cap: at most DAILY_MAX_RELEASES releases and DAILY_MAX_LINES lines per Vietnam day (COMMITTED HOLD_RELEASE runs of
the scope), checked at the claim (HELD_RELEASE_DAILY_LIMIT); the preview gives `daily`.
A release may change demand_daily of days whose actual is already FINALIZED (actual_finals is only flagged in the
change log, the frozen KPI snapshot is not changed): DESCRIPTION_CODES warns about it (summary and preview).
Known (backlog, as the CLI, not changed here): the HOLD_RELEASE change-log row records held_after = 0.0 even when other
held lines of the same key stay ACTIVE.
Undo: the result's sync_run_id is a HOLD_RELEASE run that history_sync.rollback() restores: the "Undo a sync run"
button (api/sync_rollback_routes.py) or the CLI `sync-rollback --run`. It is sure only while no other write (e.g. the
next night's D-1) changed those keys: do the first release right after a D-1 and check it before the training.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from .. import db, paths
from .. import settings_service as ss
from ..data import history_sync
from ..data.demand import bigquery_scope_key
from ..jobs import runner
from ..messages import AppError, msg
from ..timeutil import VN_TZ, iso, now_iso, now_utc, now_vn, parse_iso, today_vn
from . import background
from .data_policy_routes import BLOCKED_WINDOWS_VN, BUSY_JOB_TYPES, REASON_MAX, REASON_MIN, _busy_state

log = logging.getLogger("df.held_lines")
router = APIRouter(prefix="/api")

MAX_LINES = 450             # per release (owner's example limit, KE_HOACH_GIAO_DIEN_1415 Q4)
MAX_UNITS = 6000.0
SCAN_CAP = 100_000          # lines read by a summary / a selection count at most (as data_policy_routes.HELD_COUNT_CAP)
SUMMARY_TIMEOUT_S = 15
PAGE_MAX = 200
LISTED = 200                # lines / keys listed in a preview
GROUPS_LISTED = 20          # largest groups listed with HELD_RELEASE_TOO_LARGE
HISTORY_ROWS = 10
# the data_policy jobs + the actual close (it reads the stored demand of the day it finalizes)
RELEASE_BUSY_JOB_TYPES = BUSY_JOB_TYPES + ("ACTUAL_CLOSE",)
START_MARGIN_MIN = 60
# saved schedule times (section, field; HH:MM Vietnam) a release must not start near: SCHEDULE_AHEAD_MIN before them up to
# SCHEDULE_BEHIND_MIN after them
SCHEDULE_TIME_FIELDS = (("schedule", "d1_signal_poll_start"), ("schedule", "d1_fallback_time"), ("schedule", "train_time"),
                        ("schedule", "eod_time"), ("schedule", "close_time"), ("schedule", "refresh_deadline"),
                        ("schedule", "report_time"), ("sel2_pipeline", "prev_week_deadline"),
                        ("sel2_pipeline", "export_deadline"), ("sel2_pipeline", "avg_reexport_time"))
SCHEDULE_AHEAD_MIN = 90
SCHEDULE_BEHIND_MIN = 15
BACKUP_SPACE_FACTOR = 1.5   # free space >= this x (database + WAL + estimated zip), never < this x (database + WAL)
ZIP_RATIO_FALLBACK = 0.15   # zip / database when no backup zip exists yet (measured 9.4 % on 17/11/2026)
LOCK_ENV = ("DF_OPS_LOCK", "DF_HEAVY_LOCK")  # environment variables naming operations lock files
RUN_DIR_ENV = "DF_RUN_DIR"                   # environment variable naming the operations run folder
RUN_DIR_LOCKS = ("OPS_LOCK", "HEAVY_LOCK")   # lock files of that folder
HEARTBEAT_S = 60
STALE_AFTER_S = 300
STATE = "held_lines_release"
BY_PREFIX = "API "
BACKUP_REASON = "pre-hold-release"      # history_sync.release_holds' backup reason (file names)
VIEWS = ("sku_fc", "day", "cause", "lines")
GB = 1024 ** 3
DESCRIPTION_CODES = ("HELD_RELEASE_TOUCHES_FINAL_ACTUALS", "ROLLBACK_ONLY_BEFORE_NEXT_WRITE")
DAILY_MAX_RELEASES = 3      # per Vietnam day and scope (co-van-opus CV-NOSWITCH)
DAILY_MAX_LINES = 1350
# the sync_state keys of the three background write buttons -> the button name (one at a time across them)
HEAVY_WRITE_STATES = {"held_lines_release": "HELD_LINES_RELEASE", "open_hours_reread": "OPEN_HOURS_REREAD",
                      "sync_rollback": "SYNC_ROLLBACK"}
_ALIVE: dict = {}           # state key -> alive(st) of its module (registered at import)

_proc_lock = threading.Lock()           # one release in this process; held from the request's checks to the thread's end
_current: dict = {"task_id": None, "thread": None}


# ------------------------------------------------------------------ helpers
def _confirm_text() -> str:
    return f"NHA-DONG-GIU-{today_vn().isoformat()}"


def _limits() -> dict:
    return {"max_lines": MAX_LINES, "max_units": MAX_UNITS, "page_max": PAGE_MAX, "scan_cap": SCAN_CAP}


def _scope_key_or_none() -> str | None:
    bq = ss.get("bigquery")
    return bigquery_scope_key(bq) if bq.dataset_id and bq.source_table else None


def _scope_key() -> str:
    k = _scope_key_or_none()
    if k is None:
        raise AppError("HELD_LINES_NO_SCOPE", 409, detail="bigquery.dataset_id / source_table not set")
    return k


class Selection(BaseModel):
    """The filters release_holds accepts (no FC: release_holds selects every FC of a SKU)."""
    model_config = ConfigDict(extra="forbid")
    cause: str | None = None
    sku_id: str | None = None
    start: str | None = None
    end: str | None = None


def _filter(s: Selection) -> dict:
    cause = (s.cause or "").strip() or None
    if cause and cause not in history_sync.HOLD_CAUSES:
        raise AppError("HELD_RELEASE_INVALID_FILTER", 422, detail=f"cause must be one of {history_sync.HOLD_CAUSES}")
    out = {"cause": cause, "sku_id": (s.sku_id or "").strip() or None, "start": None, "end": None}
    for k in ("start", "end"):
        v = (getattr(s, k) or "").strip()
        if v:
            try:
                d = date.fromisoformat(v)
            except ValueError:
                d = None
            if d is None or d.isoformat() != v:
                raise AppError("HELD_RELEASE_INVALID_FILTER", 422, detail=f"{k} must be YYYY-MM-DD")
            out[k] = v
    if out["start"] and out["end"] and out["start"] > out["end"]:
        raise AppError("HELD_RELEASE_INVALID_FILTER", 422, detail="start is after end")
    return out


def _where(scope_key: str, f: dict, fc_id: str | None = None) -> tuple[str, list]:
    """The WHERE of release_holds' own query (same columns, same order), + an FC for the read-only summary."""
    q = " WHERE scope_key=? AND status='ACTIVE'"
    p: list = [scope_key]
    for col, v in (("cause", f["cause"]), ("sku_id", f["sku_id"]), ("fc_id", fc_id)):
        if v:
            q += f" AND {col}=?"
            p.append(v)
    if f["start"]:
        q += " AND order_date >= ?"
        p.append(f["start"])
    if f["end"]:
        q += " AND order_date <= ?"
        p.append(f["end"])
    return q, p


def _signature(scope_key: str, f: dict, hs: list[dict]) -> str:
    h = hashlib.sha256(json.dumps({"scope_key": scope_key, "filter": f}, sort_keys=True).encode())
    for x in sorted(hs, key=lambda x: x["id"]):
        h.update(f"\n{x['id']}|{float(x['qty'])!r}".encode())
    return h.hexdigest()


def _groups(c, w: str, p: list) -> dict:
    """Largest groups of an over-limit selection (capped scan), to narrow it by SKU x FC / day."""
    by_key: dict = defaultdict(lambda: [0, 0.0])
    by_day: dict = defaultdict(lambda: [0, 0.0])
    for d, s, fc, q in c.execute(f"SELECT order_date, sku_id, fc_id, qty FROM demand_held_lines{w} LIMIT ?",
                                 (*p, SCAN_CAP)):
        for g, k in ((by_key, (s, fc)), (by_day, d)):
            g[k][0] += 1
            g[k][1] += q

    def top(g, name):
        rows = sorted(g.items(), key=lambda kv: (-kv[1][1], str(kv[0])))[:GROUPS_LISTED]
        return [{**({"sku_id": k[0], "fc_id": k[1]} if name == "sku_fc" else {"order_date": k}), "lines": v[0],
                 "units": round(v[1], 6)} for k, v in rows]
    return {"by_sku_fc": top(by_key, "sku_fc"), "by_day": top(by_day, "day")}


def _selection(scope_key: str, f: dict) -> dict:
    """The held lines release_holds would release now, with their stored rows; raises HELD_RELEASE_TOO_LARGE /
    HELD_RELEASE_ROW_INCONSISTENT. Read-only."""
    w, p = _where(scope_key, f)
    with db.read() as c:
        n, units = c.execute(f"SELECT COUNT(*), TOTAL(qty) FROM (SELECT qty FROM demand_held_lines{w} LIMIT ?)",
                             (*p, SCAN_CAP + 1)).fetchone()
        units = round(units, 6)
        if n > MAX_LINES or units > MAX_UNITS:
            capped = n > SCAN_CAP
            raise AppError("HELD_RELEASE_TOO_LARGE", 422,
                           detail=f"{min(n, SCAN_CAP)}{'+' if capped else ''} lines / {units} units; at most {MAX_LINES} "
                                  f"lines and {MAX_UNITS:g} units per release",
                           holds=min(n, SCAN_CAP), units=units, capped=capped, limits=_limits(), filter=f,
                           **_groups(c, w, p))
        hs = db.rows(c, f"SELECT id, order_date, sku_id, fc_id, order_id, product_id, item_code, cause, qty, detected_run, "
                        f"detected_at FROM demand_held_lines{w} ORDER BY order_date, sku_id, fc_id, id", p)
        by_key: dict[tuple, list[dict]] = defaultdict(list)
        for h in hs:
            by_key[(h["order_date"], h["sku_id"], h["fc_id"])].append(h)
        keys, bad = [], []
        for k, lst in sorted(by_key.items()):
            row = c.execute("SELECT qty, n_orders FROM demand_daily WHERE scope_key=? AND order_date=? AND sku_id=? "
                            "AND fc_id=?", (scope_key, *k)).fetchone()
            u = round(sum(h["qty"] for h in lst), 6)
            after = None if row is None else round(row[0] - u, 9)
            item = {"order_date": k[0], "sku_id": k[1], "fc_id": k[2], "lines": len(lst), "release_units": u,
                    "stored_qty": row[0] if row else None, "stored_orders": row[1] if row else None,
                    "qty_after": after if after is not None and after > history_sync.EPS else None,
                    "row_removed": after is not None and after <= history_sync.EPS}
            keys.append(item)
            if row is None or after < -history_sync.EPS:
                bad.append(item)
    if bad:
        raise AppError("HELD_RELEASE_ROW_INCONSISTENT", 409, detail=f"{len(bad)} keys: no stored row or fewer stored "
                       "units than their held lines (data check)", keys=bad[:GROUPS_LISTED], filter=f)
    return {"scope_key": scope_key, "filter": f, "holds": len(hs), "units": round(sum(h["qty"] for h in hs), 6),
            "keys": len(keys), "by_cause": dict(Counter(h["cause"] for h in hs)), "lines": hs[:LISTED],
            "keys_detail": keys[:LISTED], "signature": _signature(scope_key, f, hs) if hs else None,
            "ids": {h["id"] for h in hs}}


def _ahead(t: str, cur: int) -> int | None:
    """Minutes from `cur` (minute of the Vietnam day) to the next HH:MM `t`, 0..1439; None when `t` is not HH:MM."""
    try:
        h, m = (int(x) for x in t.split(":"))
    except (AttributeError, ValueError):
        return None
    return (h * 60 + m - cur) % 1440


def _soon(c) -> dict:
    """The production window starting in START_MARGIN_MIN minutes or less, and the saved schedule times in the next
    SCHEDULE_AHEAD_MIN / last SCHEDULE_BEHIND_MIN minutes (Vietnam)."""
    now = now_vn()
    cur = now.hour * 60 + now.minute
    win = next((a for a, _b in BLOCKED_WINDOWS_VN if (_ahead(a, cur) or 0) <= START_MARGIN_MIN), None)
    times = []
    for section, field in SCHEDULE_TIME_FIELDS:
        t = getattr(ss.get(section, c), field, None)
        d = _ahead(t, cur) if t else None
        if d is not None and (d <= SCHEDULE_AHEAD_MIN or d >= 1440 - SCHEDULE_BEHIND_MIN):
            times.append({"setting": f"{section}.{field}", "time": t})
    return {"window_soon": win, "schedule_times": times}


def _check_busy(c) -> dict:
    st = _busy_state(c, RELEASE_BUSY_JOB_TYPES)
    soon = _soon(c)
    win = None if st["window"] else soon["window_soon"]
    if st["busy"] or win or soon["schedule_times"]:
        detail = ", ".join(x for x in (
            st["detail"],
            f"production window {win} (Vietnam) starts in {START_MARGIN_MIN} minutes or less" if win else None,
            *(f"{x['setting']} {x['time']} (Vietnam) within -{SCHEDULE_BEHIND_MIN}..+{SCHEDULE_AHEAD_MIN} minutes"
              for x in soon["schedule_times"])) if x)
        raise AppError("HELD_RELEASE_BUSY", 409, detail=detail, window=st["window"], window_soon=win,
                       schedule_times=soon["schedule_times"], start_margin_minutes=START_MARGIN_MIN,
                       schedule_ahead_minutes=SCHEDULE_AHEAD_MIN, schedule_behind_minutes=SCHEDULE_BEHIND_MIN,
                       jobs=st["jobs"], stale_ignored=st["stale_ignored"], stale_ignored_total=st["stale_ignored_total"])
    return st


def _free_bytes(p) -> int:
    return shutil.disk_usage(p).free


def _disk() -> dict:
    dbf = paths.db_path()
    wal = dbf.with_name(dbf.name + "-wal")
    db_only = dbf.stat().st_size
    wal_bytes = wal.stat().st_size if wal.exists() else 0
    dest = paths.backups_dir()
    free = _free_bytes(dest)
    zips = []
    for x in dest.glob("backup-*.zip"):
        try:
            zips.append((x.stat().st_mtime, x.name, x.stat().st_size))
        except OSError:
            pass
    newest = max(zips) if zips else None
    zip_est = newest[2] if newest else int(ZIP_RATIO_FALLBACK * db_only)
    floor = int(BACKUP_SPACE_FACTOR * (db_only + wal_bytes))
    need = max(int(BACKUP_SPACE_FACTOR * (db_only + wal_bytes + zip_est)), floor)
    return {"backup_dir": str(dest), "free_bytes": free, "db_bytes": db_only, "wal_bytes": wal_bytes,
            "zip_estimate_bytes": zip_est,
            "zip_estimate_from": f"newest backup {newest[1]}" if newest else f"{ZIP_RATIO_FALLBACK} x the database",
            "factor": BACKUP_SPACE_FACTOR, "floor_bytes": floor, "need_bytes": need,
            "missing_bytes": max(0, need - free), "free_gb": round(free / GB, 2), "need_gb": round(need / GB, 2),
            "ok": free >= need}


def _check_disk() -> dict:
    d = _disk()
    if not d["ok"]:
        raise AppError("HELD_RELEASE_DISK_SPACE", 409,
                       detail=f"need {d['need_bytes']} B, free {d['free_bytes']} B, missing {d['missing_bytes']} B in "
                              f"{d['backup_dir']} ({BACKUP_SPACE_FACTOR} x (database {d['db_bytes']} B + WAL "
                              f"{d['wal_bytes']} B + zip estimate {d['zip_estimate_bytes']} B, {d['zip_estimate_from']}); "
                              f"floor {d['floor_bytes']} B)", **d)
    return d


def _app_data_dir() -> Path:
    return paths.data_dir()


def _derived_run_dir() -> Path | None:
    """<data folder>/../../run (the operations run folder next to the app's data), only when it exists."""
    try:
        run = Path(_app_data_dir()).parent.parent / "run"
    except Exception:  # noqa: BLE001 - no data folder: nothing derived
        return None
    return run if run.is_dir() else None


def _lock_files() -> list[tuple[str, Path]]:
    """(source, lock file) pairs to check: DF_OPS_LOCK / DF_HEAVY_LOCK and DF_RUN_DIR/<RUN_DIR_LOCKS>; none set -> the
    derived run folder's <RUN_DIR_LOCKS> (source DERIVED) when it exists."""
    out = [(k, Path(os.environ[k])) for k in LOCK_ENV if os.environ.get(k)]
    run = os.environ.get(RUN_DIR_ENV)
    if run:
        out += [(RUN_DIR_ENV, Path(run) / n) for n in RUN_DIR_LOCKS]
    if not out:
        d = _derived_run_dir()
        if d is not None:
            out = [("DERIVED", d / n) for n in RUN_DIR_LOCKS]
    return out


def ops_lock_checked() -> bool:
    """False when no lock variable is set and no run folder can be derived: the locks are then not checked."""
    return bool(_lock_files())


def ops_lock_source() -> str | None:
    files = _lock_files()
    return None if not files else "derived" if files[0][0] == "DERIVED" else "env"


def ops_locks() -> list[dict]:
    """Operations lock files that exist now (a variable not set is not checked)."""
    return [{"env": k, "path": str(f)} for k, f in _lock_files() if f.exists()]


def check_ops_locks() -> None:
    held = ops_locks()
    if held:
        raise AppError("OPERATIONS_LOCK_HELD", 409, detail=", ".join(f"{x['env']}={x['path']}" for x in held),
                       locks=held)


def register_task(state: str, alive) -> None:
    _ALIVE[state] = alive


def _fresh(st: dict) -> bool:
    try:
        hb = parse_iso(st.get("heartbeat_at") or st.get("started_at"))
    except (TypeError, ValueError):
        return False
    return hb is not None and (now_utc() - hb).total_seconds() <= STALE_AFTER_S


def other_running(c, own_state: str) -> dict | None:
    """The RUNNING, alive task of another background write button, or None (INTERRUPTED never blocks)."""
    for state, button in HEAVY_WRITE_STATES.items():
        if state == own_state:
            continue
        r = c.execute("SELECT value_json FROM sync_state WHERE name=?", (state,)).fetchone()
        try:
            st = json.loads(r[0]) if r else None
        except (TypeError, ValueError):
            st = None
        if not isinstance(st, dict) or st.get("status") != "RUNNING":
            continue
        if (_ALIVE[state](st) if state in _ALIVE else _fresh(st)):
            return {"button": button, "state": state, "task_id": st.get("task_id"), "started_at": st.get("started_at")}
    return None


def check_other_running(c, own_state: str) -> None:
    o = other_running(c, own_state)
    if o:
        raise AppError("HEAVY_WRITE_ANOTHER_RUNNING", 409, detail=f"{o['button']} {o['task_id']} is running", **o)


def _daily(c, scope_key: str) -> dict:
    """Releases / lines committed today (Vietnam day) for the scope, and what is left of DAILY_MAX_*."""
    d = today_vn()
    start = datetime(d.year, d.month, d.day, tzinfo=VN_TZ).astimezone(timezone.utc)
    rows = c.execute("SELECT summary_json FROM demand_sync_runs WHERE scope_key=? AND kind='HOLD_RELEASE' AND "
                     "status='COMMITTED' AND started_at >= ? AND started_at < ?",
                     (scope_key, iso(start), iso(start + timedelta(days=1)))).fetchall()
    lines = 0
    for (sj,) in rows:
        try:
            lines += int(json.loads(sj or "{}").get("holds") or 0)
        except (TypeError, ValueError):
            pass
    return {"releases_used": len(rows), "releases_left": max(0, DAILY_MAX_RELEASES - len(rows)),
            "lines_used": lines, "lines_left": max(0, DAILY_MAX_LINES - lines),
            "max_releases": DAILY_MAX_RELEASES, "max_lines": DAILY_MAX_LINES}


def _check_daily(c, scope_key: str, holds: int) -> dict:
    d = _daily(c, scope_key)
    if d["releases_left"] < 1 or holds > d["lines_left"]:
        raise AppError("HELD_RELEASE_DAILY_LIMIT", 409, detail=f"today: {d['releases_used']} releases / "
                       f"{d['lines_used']} lines used of {DAILY_MAX_RELEASES} / {DAILY_MAX_LINES}; this one: {holds} "
                       "lines", **d, holds=holds)
    return d


def _guard(c) -> dict:
    """The write gate (operations locks, another background write, busy / windows / schedule times)."""
    check_ops_locks()
    check_other_running(c, STATE)
    return _check_busy(c)


def _backup_files() -> dict:
    """Backups of earlier releases (kept, never deleted here) and temporary files a cut backup left (listed only)."""
    try:
        root = paths.backups_dir()
        done = [x for x in root.glob(f"backup-*-{BACKUP_REASON}.zip")]
        left = [x for p in (f"app-*-{BACKUP_REASON}.db", f"backup-*-{BACKUP_REASON}.zip.part") for x in root.glob(p)]
        running = _current["task_id"] is not None
        return {"release_backups": len(done), "release_backups_bytes": sum(x.stat().st_size for x in done),
                "temporary_files": [{"file": x.name, "size_bytes": x.stat().st_size,
                                     "note": "BACKUP_IN_PROGRESS" if running else "LEFT_BY_A_CUT_BACKUP"}
                                    for x in sorted(left)]}
    except OSError as e:
        return {"error": f"{type(e).__name__}"}


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


def _running_elsewhere(st: dict) -> bool:
    """A RUNNING task that is still alive: this process's own thread, or another process's with a fresh heartbeat."""
    if st.get("status") != "RUNNING":
        return False
    if st.get("owner") == runner.OWNER:
        return _current["task_id"] == st.get("task_id")
    try:
        hb = parse_iso(st.get("heartbeat_at") or st.get("started_at"))
    except (TypeError, ValueError):
        hb = None
    return hb is not None and (now_utc() - hb).total_seconds() <= STALE_AFTER_S


def _committed_run(c, st: dict) -> dict | None:
    if not (st.get("task_id") and st.get("scope_key") and st.get("started_at")):
        return None
    return db.one(c, "SELECT id, backup, finished_at FROM demand_sync_runs WHERE scope_key=? AND kind='HOLD_RELEASE' "
                     "AND started_at >= ? AND summary_json LIKE ? ORDER BY started_at DESC, rowid DESC LIMIT 1",
                  (st["scope_key"], st["started_at"], f'%"by": "{BY_PREFIX}{st["task_id"]}%'))


def _view_state(c) -> dict | None:
    """The stored task; a RUNNING one that is not alive any more is shown INTERRUPTED (nothing is written here)."""
    st = _read_state(c)
    if not st or st.get("status") != "RUNNING" or _running_elsewhere(st):
        return st
    run = _committed_run(c, st)
    return {**st, "status": "INTERRUPTED", "error": {"code": "HELD_RELEASE_INTERRUPTED",
                                                     "detail": "the app stopped during the release"},
            "committed": run is not None, "result": _result_of_run(run) if run else None}


def _result_of_run(run: dict) -> dict:
    try:
        bk = json.loads(run.get("backup") or "{}").get("file")
    except (TypeError, ValueError):
        bk = None
    return {"sync_run_id": run["id"], "backup_file": bk, "rollback": _rollback_hint(run["id"])}


def _rollback_hint(run_id: str) -> dict:
    return {"sync_run_id": run_id, "function": "history_sync.rollback", "cli": f"app.cli sync-rollback --run {run_id}"}


def _history(c, scope_key: str) -> list[dict]:
    out = []
    for r in db.rows(c, "SELECT id, status, started_at, finished_at, summary_json, backup, rolled_back_by, rolled_back_at "
                        "FROM demand_sync_runs WHERE scope_key=? AND kind='HOLD_RELEASE' "
                        "ORDER BY started_at DESC, rowid DESC LIMIT ?", (scope_key, HISTORY_ROWS)):
        try:
            s = json.loads(r["summary_json"] or "{}")
        except (TypeError, ValueError):
            s = {}
        res = _result_of_run(r)
        out.append({"sync_run_id": r["id"], "status": r["status"], "started_at": r["started_at"],
                    "finished_at": r["finished_at"], "holds": s.get("holds"), "units": s.get("units"),
                    "keys": s.get("keys"), "by_cause": s.get("by_cause"), "filter": s.get("filter"), "by": s.get("by"),
                    "rows_logged": s.get("rows_logged"), "backup_file": res["backup_file"],
                    "rolled_back_by": r["rolled_back_by"], "rolled_back_at": r["rolled_back_at"],
                    "rollback": res["rollback"] if r["status"] == "COMMITTED" else None})
    return out


# ------------------------------------------------------------------ the background release
def _heartbeat(task_id: str, done: threading.Event) -> None:
    while not done.wait(HEARTBEAT_S):
        try:
            with db.tx() as c:
                st = _read_state(c)
                if not st or st.get("task_id") != task_id or st.get("status") != "RUNNING":
                    return
                _write_state(c, {**st, "heartbeat_at": now_iso()})
        except Exception:  # noqa: BLE001 - a missed heartbeat only makes another process see the task as stopped later
            log.warning("held-lines release heartbeat failed", exc_info=True, extra={"ctx": {"task_id": task_id}})


def _finish(task_id: str, result: dict | None, error: dict | None) -> None:
    with db.tx() as c:
        st = _read_state(c) or {}
        if st.get("task_id") != task_id:
            log.error("held-lines release state replaced during the run", extra={"ctx": {"task_id": task_id}})
            return
        st = {**st, "status": "FAILED" if error else "SUCCEEDED", "finished_at": now_iso(), "heartbeat_at": now_iso(),
              "result": result, "error": error}
        _write_state(c, st)
        if error:
            db.audit(c, "HELD_LINES_RELEASE_FAILED", "scope", st.get("scope_key"),
                     {"task_id": task_id, "error": error, "filter": st.get("filter")})


def _worker(st: dict, ids: set, done: threading.Event) -> None:
    task_id, f = st["task_id"], st["filter"]
    result = error = None
    try:
        with db.read() as c:
            _guard(c)                           # before the backup
        out = history_sync.release_holds(st["scope_key"], f["cause"], f["sku_id"], f["start"], f["end"], apply=True,
                                         by=st["by"], expected_ids=ids, before_write=_guard)
        if not out.get("applied"):
            error = {"code": "HELD_RELEASE_PREVIEW_STALE", "detail": "no matching held line is ACTIVE any more"}
        else:
            bk = out.get("backup")
            p = paths.backups_dir() / bk if bk else None
            result = {"sync_run_id": out.get("run_id"), "holds": out.get("holds"), "units": out.get("units"),
                      "keys": out.get("keys"), "by_cause": out.get("by_cause"), "backup_file": bk,
                      "backup_path": str(p) if p else None,
                      "backup_bytes": p.stat().st_size if p is not None and p.exists() else None,
                      "rollback": _rollback_hint(out.get("run_id"))}
    except AppError as e:
        error = {"code": e.code, "detail": e.detail, "status": e.status}
    except Exception as e:  # noqa: BLE001 - recorded in the task state; SQLite rolled the write back
        log.error("held-lines release failed", exc_info=True, extra={"ctx": {"task_id": task_id}})
        error = {"code": "HELD_RELEASE_FAILED", "detail": f"{type(e).__name__}: {e}"[:500]}
    finally:
        done.set()
        try:
            _finish(task_id, result, error)
        except Exception:  # noqa: BLE001 - the state stays RUNNING: shown INTERRUPTED once the lock is free
            log.error("held-lines release state not written", exc_info=True, extra={"ctx": {"task_id": task_id}})
        finally:
            _current.update(task_id=None, thread=None)
            _proc_lock.release()


def _claim(task_id: str, scope_key: str, f: dict, sel: dict, reason: str, disk: dict) -> dict:
    """Busy check, task state and request audit in ONE write transaction (no job row is added between the check and the
    claim). A RUNNING task that is not alive any more is recorded as INTERRUPTED in the audit first."""
    with db.tx() as c:
        busy = _guard(c)
        _check_daily(c, scope_key, sel["holds"])
        old = _read_state(c)
        if old and old.get("status") == "RUNNING":
            if _running_elsewhere(old):
                raise AppError("HELD_RELEASE_RUNNING", 409, detail=f"release {old.get('task_id')} is running",
                               task_id=old.get("task_id"))
            run = _committed_run(c, old)
            db.audit(c, "HELD_LINES_RELEASE_INTERRUPTED", "scope", old.get("scope_key"),
                     {"task_id": old.get("task_id"), "owner": old.get("owner"), "started_at": old.get("started_at"),
                      "committed_run": run["id"] if run else None})
        at = now_iso()
        st = {"task_id": task_id, "status": "RUNNING", "owner": runner.OWNER, "scope_key": scope_key, "filter": f,
              "signature": sel["signature"], "expected": {"holds": sel["holds"], "units": sel["units"],
                                                          "keys": sel["keys"]},
              "reason": reason, "by": f"{BY_PREFIX}{task_id}: {reason}", "started_at": at, "heartbeat_at": at,
              "finished_at": None, "result": None, "error": None, "disk": disk}
        _write_state(c, st)
        db.audit(c, "HELD_LINES_RELEASE_REQUESTED", "scope", scope_key,
                 {"task_id": task_id, "filter": f, "signature": sel["signature"], "expected": st["expected"],
                  "reason": reason, "disk": disk,
                  "stale_ignored": [{k: j[k] for k in ("id", "job_type", "status")} for j in busy["stale_ignored"]],
                  "stale_ignored_total": busy["stale_ignored_total"]})
    return st


# ------------------------------------------------------------------ routes
@router.get("/held-lines")
def held_lines(view: str = "sku_fc", sku_id: str | None = None, fc_id: str | None = None, cause: str | None = None,
               start: str | None = None, end: str | None = None, limit: int = Query(50, ge=1, le=PAGE_MAX),
               offset: int = Query(0, ge=0, le=SCAN_CAP)):
    """Read-only summary (see the module doc); never writes."""
    if view not in VIEWS:
        raise AppError("HELD_RELEASE_INVALID_FILTER", 422, detail=f"view must be one of {VIEWS}")
    f = _filter(Selection(cause=cause, sku_id=sku_id, start=start, end=end))
    fc = (fc_id or "").strip() or None
    base = {"ops_lock_checked": ops_lock_checked(), "ops_lock_source": ops_lock_source(), "policy": history_sync.policy(), "limits": _limits(),
            "confirm_text": _confirm_text(),
            "reason_min_length": REASON_MIN, "view": view, "filter": {**f, "fc_id": fc},
            "description_codes": list(DESCRIPTION_CODES), "description": [msg(x) for x in DESCRIPTION_CODES]}
    scope_key = _scope_key_or_none()
    with db.read() as c:
        task = _view_state(c)
        if scope_key is None:
            return {**base, "configured": False, "scope_key": None, "summary": None, "rows": [], "task": task,
                    "recent_releases": []}
        hist = _history(c, scope_key)
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_dhl_active'").fetchone():
            return {**base, "configured": True, "scope_key": scope_key, "summary": {"status": "NO_INDEX"}, "rows": [],
                    "task": task, "recent_releases": hist}
        w, p = _where(scope_key, f, fc)
        n, units = 0, 0.0
        keys: set = set()
        days: set = set()
        causes: dict = defaultdict(lambda: [0, 0.0])
        groups: dict = defaultdict(lambda: [0, 0.0, None, None])
        status = "COMPLETE"
        rows: list[dict] = []
        deadline = time.monotonic() + SUMMARY_TIMEOUT_S
        c.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1_000)
        try:
            for d, s, fcv, cs, q in c.execute(f"SELECT order_date, sku_id, fc_id, cause, qty FROM demand_held_lines "
                                              f"INDEXED BY idx_dhl_active{w} LIMIT ?", (*p, SCAN_CAP + 1)):
                if n >= SCAN_CAP:
                    status = "CAPPED"
                    break
                n += 1
                units += q
                keys.add((d, s, fcv))
                days.add(d)
                causes[cs][0] += 1
                causes[cs][1] += q
                if view != "lines":
                    g = groups[(s, fcv) if view == "sku_fc" else d if view == "day" else cs]
                    g[0] += 1
                    g[1] += q
                    g[2] = d if g[2] is None or d < g[2] else g[2]
                    g[3] = d if g[3] is None or d > g[3] else g[3]
            if view == "lines":
                rows = db.rows(c, f"SELECT id, order_date, sku_id, fc_id, order_id, product_id, item_code, order_status, "
                                  f"cause, qty, detected_run, detected_at FROM demand_held_lines INDEXED BY idx_dhl_active"
                                  f"{w} ORDER BY order_date DESC, sku_id DESC, fc_id DESC, rowid DESC LIMIT ? OFFSET ?",
                               (*p, limit, offset))
        except sqlite3.OperationalError as e:
            if "interrupted" not in str(e).lower():
                raise
            status = "TIMEOUT"
        finally:
            c.set_progress_handler(None, 0)
    total_groups = None
    if view != "lines":
        if view == "day":       # newest day first
            items = sorted(groups.items(), key=lambda kv: kv[0], reverse=True)
        else:                   # most units first
            items = sorted(groups.items(), key=lambda kv: (-kv[1][1], str(kv[0])))
        total_groups = len(items)
        for k, v in items[offset:offset + limit]:
            key = ({"sku_id": k[0], "fc_id": k[1]} if view == "sku_fc" else {"order_date": k} if view == "day"
                   else {"cause": k})
            rows.append({**key, "lines": v[0], "units": round(v[1], 6), "first_day": v[2], "last_day": v[3]})
    summary = {"status": status, "active_lines": n, "units": round(units, 6), "keys": len(keys), "days": len(days),
               "first_day": min(days) if days else None, "last_day": max(days) if days else None,
               "by_cause": {k: {"lines": v[0], "units": round(v[1], 6)} for k, v in sorted(causes.items())}}
    return {**base, "configured": True, "scope_key": scope_key, "summary": summary, "rows": rows, "limit": limit,
            "offset": offset, "total_groups": total_groups, "task": task, "recent_releases": hist}


@router.post("/held-lines/release-preview")
def release_preview(body: Selection):
    """Dry run: what a release of this selection would change; never writes, never backs up."""
    f = _filter(body)
    scope_key = _scope_key()
    with db.read() as c:
        busy = _check_busy(c)
        task = _view_state(c)
        other = other_running(c, STATE)
        daily = _daily(c, scope_key)
    sel = _selection(scope_key, f)
    sel.pop("ids")
    return {**sel, "limits": _limits(), "confirm_text": _confirm_text(), "reason_min_length": REASON_MIN,
            "releasable": sel["holds"] > 0, "warnings": [] if sel["holds"] else ["HELD_RELEASE_NOTHING"],
            "busy": busy, "disk": _disk(), "task": task, "backup_before": True, "runs_in_background": True,
            "ops_lock_checked": ops_lock_checked(), "ops_lock_source": ops_lock_source(), "ops_locks": ops_locks(),
            "busy_other_task": other, "daily": daily,
            "description_codes": list(DESCRIPTION_CODES), "description": [msg(x) for x in DESCRIPTION_CODES]}


class ReleaseBody(Selection):
    signature: str
    confirm_text: str | None = None
    reason: str | None = None


@router.post("/held-lines/release", status_code=202)
def release(body: ReleaseBody):
    f = _filter(body)
    reason = " ".join((body.reason or "").split())
    if len(reason) > REASON_MAX:
        raise AppError("HELD_RELEASE_INVALID_FILTER", 422, detail=f"reason longer than {REASON_MAX} characters")
    expected_text = _confirm_text()
    if (body.confirm_text or "").strip() != expected_text or len(reason) < REASON_MIN:
        raise AppError("HELD_RELEASE_CONFIRM_REQUIRED", 409,
                       detail=f"type {expected_text} and a reason of at least {REASON_MIN} characters",
                       confirm_text=expected_text, reason_min_length=REASON_MIN)
    scope_key = _scope_key()
    if not _proc_lock.acquire(blocking=False):
        raise AppError("HELD_RELEASE_RUNNING", 409, detail=f"release {_current['task_id']} is running",
                       task_id=_current["task_id"])
    st = None
    started = False
    try:
        with db.read() as c:
            _guard(c)
        sel = _selection(scope_key, f)
        if not sel["holds"]:
            raise AppError("HELD_RELEASE_NOTHING", 409, filter=f)
        if sel["signature"] != body.signature:
            raise AppError("HELD_RELEASE_PREVIEW_STALE", 409, detail="the held lines of this selection changed since "
                           "the preview", holds=sel["holds"], units=sel["units"], keys=sel["keys"])
        disk = _check_disk()
        task_id = db.new_id("HLT")
        _current.update(task_id=task_id)       # this process's task from the claim on (seen alive, never INTERRUPTED)
        st = _claim(task_id, scope_key, f, sel, reason, disk)
        done = threading.Event()
        th = threading.Thread(target=_worker, args=(st, sel["ids"], done), name=f"held-release-{task_id}", daemon=True)
        _current.update(thread=th)
        th.start()
        started = True      # from here the worker owns the lock (released in its finally)
        threading.Thread(target=_heartbeat, args=(st["task_id"], done), name=f"held-release-hb-{st['task_id']}",
                         daemon=True).start()
    except BaseException as e:
        if not started:
            try:
                if st is not None:      # claimed but the thread did not start: the task is closed FAILED
                    _finish(st["task_id"], None, {"code": "HELD_RELEASE_FAILED", "detail": f"{type(e).__name__}: {e}"[:500]})
            finally:
                _current.update(task_id=None, thread=None)
                _proc_lock.release()
        raise
    log.info("held-lines release started", extra={"ctx": {"task_id": st["task_id"], "holds": sel["holds"]}})
    if background.SYNC_MODE:
        th.join()
    with db.read() as c:
        return {"accepted": True, "task": _view_state(c)}


@router.get("/held-lines/release-status")
def release_status():
    scope_key = _scope_key_or_none()
    with db.read() as c:
        task = _view_state(c)
        hist = _history(c, scope_key) if scope_key else []
    return {"task": task, "running": bool(task and task.get("status") == "RUNNING"), "recent_releases": hist,
            "backups": _backup_files(), "scope_key": scope_key}


register_task(STATE, _running_elsewhere)
