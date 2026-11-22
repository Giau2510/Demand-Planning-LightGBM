"""1.4.15 lot 5: undo of one history-sync run (data/history_sync.rollback, CLI `sync-rollback --run`) from the UI - also
the undo path of the held-lines release (its result gives the sync_run_id) - behind the gates of the 1.4.15 write paths.

GET  /api/sync-runs                  the latest LIST_MAX runs of the BigQuery scope (demand_sync_runs, newest first) with
                                     `rollbackable` true / false / null (not checked: time budget or too large) and the
                                     reason. The check is rollback()'s own (history_sync._rollback_check): a COMMITTED
                                     D1_SYNC / BACKFILL / HOLD_RELEASE run whose every key is still exactly as the run left
                                     it (no later change-log entry on the key, the stored row equal to the run's `after`).
POST /api/sync-rollback/preview      read-only, rollback()'s dry run (the same _rollback_check): rows to restore (inserts /
                                     updates / deletes), units now and after, day range, finalized days, held lines to
                                     release / restore, `signature`; refused when a later write changed a key
                                     (SYNC_ROLLBACK_REFUSED, with the keys) or above MAX_ENTRIES change-log entries.
POST /api/sync-rollback              signature of the preview, typed text QUAY-LAI-DONG-BO-<today, Vietnam>, reason >= 10;
                                     202 at once, rollback(apply=True) runs in a background thread: its online backup
                                     (backup_database "pre-rollback") then ONE write transaction that checks the conflicts
                                     again under the write lock and calls before_write (this module's gate: the preview
                                     signature recomputed, operations locks, busy / windows / schedule times): any failure
                                     -> 409 / FAILED, nothing written. Audit: DEMAND_SYNC_ROLLBACK (rollback()) +
                                     SYNC_ROLLBACK_REQUESTED / _FAILED / _INTERRUPTED (here).
GET  /api/sync-rollback/status       the task (sync_state STATE, heartbeat, INTERRUPTED when its app stopped).
Consequences (`description`, vi / en): the stored demand rows of that run come back exactly as before it; models and
forecasts already trained / published on the changed data are NOT undone (a new training is the owner's decision).
Shared with held_lines_routes (imported, not copied): the busy state + schedule times (_soon), the operations locks, the
disk figures (_disk: 1.5 x (database + WAL + zip estimate)) and the task heartbeat timings. The task-state helpers are a
minimal copy (their state key and error codes differ) - a shared module was not split out so the reviewed lots 3 / 4 stay
unchanged.
Known limits (as the CLI): the backup runs in the app process without the operations HEAVY_LOCK; a rollback of a large
run holds the write lock for its whole transaction (MAX_ENTRIES caps it here; the CLI has no cap).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from .. import db, paths
from .. import settings_service as ss
from ..data import history_sync
from ..data.demand import bigquery_scope_key
from ..jobs import runner
from ..messages import AppError, msg
from ..timeutil import now_iso, now_utc, parse_iso, today_vn
from . import background
from . import held_lines_routes as hl
from .data_policy_routes import REASON_MAX, REASON_MIN, _busy_state

log = logging.getLogger("df.sync_rollback")
router = APIRouter(prefix="/api")

LIST_MAX = 50
LIST_TIMEOUT_S = 15         # the rollbackable checks of the list stop here (the rest: null, NOT_CHECKED)
PREVIEW_TIMEOUT_S = 60
# change-log entries of one run rolled back from the UI (data-reviewer: the write lock is held for the whole rollback
# transaction, not measured yet, and the other writers wait at most busy_timeout = 30 s; measure on a DB copy, then
# revise; the CLI has no cap)
MAX_ENTRIES = 20_000
ROLLBACK_KINDS = ("D1_SYNC", "BACKFILL", "HOLD_RELEASE")
STATE = "sync_rollback"
BY_PREFIX = "API "
DESCRIPTION_CODES = ("SYNC_ROLLBACK_RESTORES_DEMAND", "SYNC_ROLLBACK_NOT_MODELS", "SYNC_ROLLBACK_LATER_WRITES",
                     "ROLLBACK_ONLY_BEFORE_NEXT_WRITE")

_proc_lock = threading.Lock()
_current: dict = {"task_id": None, "thread": None}


# ------------------------------------------------------------------ helpers
def _confirm_text() -> str:
    return f"QUAY-LAI-DONG-BO-{today_vn().isoformat()}"


def _description() -> list[dict]:
    return [msg(c) for c in DESCRIPTION_CODES]


def _scope_key_or_none() -> str | None:
    bq = ss.get("bigquery")
    return bigquery_scope_key(bq) if bq.dataset_id and bq.source_table else None


def _signature(check: tuple) -> str:
    run, entries, conflicts, new_holds, gone_holds, released = check
    return hashlib.sha256(json.dumps({
        "run": run["id"], "status": run["status"], "entries": [e["id"] for e in entries], "conflicts": len(conflicts),
        "new_holds": sorted(h["id"] for h in new_holds), "gone_holds": sorted(h["id"] for h in gone_holds),
        "released": sorted(h["id"] for h in released)}, sort_keys=True).encode()).hexdigest()


def _entries(c, run_id: str) -> int:
    return c.execute("SELECT COUNT(*) FROM demand_change_log WHERE run_id=?", (run_id,)).fetchone()[0]


def _check(c, run_id: str) -> tuple:
    """rollback()'s own check; a missing run -> SYNC_RUN_NOT_FOUND (rollback says BATCH_NOT_FOUND)."""
    if not c.execute("SELECT 1 FROM demand_sync_runs WHERE id=?", (run_id,)).fetchone():
        raise AppError("SYNC_RUN_NOT_FOUND", 404, detail=run_id)
    n = _entries(c, run_id)
    if n > MAX_ENTRIES:
        raise AppError("SYNC_ROLLBACK_TOO_LARGE", 422, detail=f"{n} change-log entries > {MAX_ENTRIES}", entries=n,
                       max_entries=MAX_ENTRIES)
    return history_sync._rollback_check(c, run_id)


def _summary(check: tuple) -> dict:
    run, entries, conflicts, new_holds, gone_holds, released = check
    acts = {"INSERT": 0, "UPDATE": 0, "DELETE": 0}
    for e in entries:
        acts[e["action"]] = acts.get(e["action"], 0) + 1
    days = sorted({e["order_date"] for e in entries})
    return {"sync_run_id": run["id"], "kind": run["kind"], "status": run["status"], "started_at": run["started_at"],
            "entries": len(entries),
            # the run inserted / updated / deleted these rows: the rollback deletes / restores / re-inserts them
            "rows_inserted_by_run": acts["INSERT"], "rows_updated_by_run": acts["UPDATE"],
            "rows_deleted_by_run": acts["DELETE"],
            "units_now": round(sum(e["qty_after"] or 0.0 for e in entries), 6),
            "units_after_rollback": round(sum(e["qty_before"] or 0.0 for e in entries), 6),
            "first_day": days[0] if days else None, "last_day": days[-1] if days else None, "days": len(days),
            "finalized_days": len({e["order_date"] for e in entries if e["finalized"]}),
            "holds_to_release": len(new_holds), "holds_to_restore": len(released),
            "holds_of_run_already_released": len(gone_holds), "conflicts": len(conflicts)}


def _busy_info(c) -> dict:
    st = _busy_state(c, hl.RELEASE_BUSY_JOB_TYPES)
    soon = hl._soon(c)
    win = None if st["window"] else soon["window_soon"]
    return {**st, "window_soon": win, "schedule_times": soon["schedule_times"],
            "busy": bool(st["busy"] or win or soon["schedule_times"])}


def _check_busy(c) -> dict:
    b = _busy_info(c)
    if b["busy"]:
        detail = ", ".join(x for x in (
            b["detail"],
            f"production window {b['window_soon']} (Vietnam) starts in {hl.START_MARGIN_MIN} minutes or less"
            if b["window_soon"] else None,
            *(f"{x['setting']} {x['time']} (Vietnam) within -{hl.SCHEDULE_BEHIND_MIN}..+{hl.SCHEDULE_AHEAD_MIN} minutes"
              for x in b["schedule_times"])) if x)
        raise AppError("SYNC_ROLLBACK_BUSY", 409, detail=detail, window=b["window"], window_soon=b["window_soon"],
                       schedule_times=b["schedule_times"], jobs=b["jobs"], stale_ignored=b["stale_ignored"],
                       stale_ignored_total=b["stale_ignored_total"])
    return b


def _guard(c) -> dict:
    hl.check_ops_locks()
    hl.check_other_running(c, STATE)
    return _check_busy(c)


def _check_disk() -> dict:
    d = hl._disk()
    if not d["ok"]:
        raise AppError("SYNC_ROLLBACK_DISK_SPACE", 409,
                       detail=f"need {d['need_bytes']} B, free {d['free_bytes']} B, missing {d['missing_bytes']} B in "
                              f"{d['backup_dir']} ({hl.BACKUP_SPACE_FACTOR} x (database {d['db_bytes']} B + WAL "
                              f"{d['wal_bytes']} B + zip estimate {d['zip_estimate_bytes']} B, {d['zip_estimate_from']}); "
                              f"floor {d['floor_bytes']} B)", **d)
    return d


def _deadline(c, seconds: float):
    end = time.monotonic() + seconds
    c.set_progress_handler(lambda: 1 if time.monotonic() > end else 0, 1_000)


# ------------------------------------------------------------------ task state (sync_state STATE; as held_lines_routes)
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


def _committed_run(c, st: dict) -> dict | None:
    if not (st.get("task_id") and st.get("started_at")):
        return None
    return db.one(c, "SELECT id, backup FROM demand_sync_runs WHERE kind='ROLLBACK' AND started_at >= ? AND "
                     "summary_json LIKE ? ORDER BY started_at DESC, rowid DESC LIMIT 1",
                  (st["started_at"], f'%"by": "{BY_PREFIX}{st["task_id"]}%'))


def _view_state(c) -> dict | None:
    st = _read_state(c)
    if not st or st.get("status") != "RUNNING" or _alive(st):
        return st
    run = _committed_run(c, st)
    return {**st, "status": "INTERRUPTED", "error": {"code": "SYNC_ROLLBACK_INTERRUPTED",
                                                     "detail": "the app stopped during the rollback"},
            "committed": run is not None, "rollback_run": run["id"] if run else None}


def _heartbeat(task_id: str, done: threading.Event) -> None:
    while not done.wait(hl.HEARTBEAT_S):
        try:
            with db.tx() as c:
                st = _read_state(c)
                if not st or st.get("task_id") != task_id or st.get("status") != "RUNNING":
                    return
                _write_state(c, {**st, "heartbeat_at": now_iso()})
        except Exception:  # noqa: BLE001 - a missed heartbeat only makes another process see the task as stopped later
            log.warning("sync rollback heartbeat failed", exc_info=True, extra={"ctx": {"task_id": task_id}})


# ------------------------------------------------------------------ the background rollback
def _worker(st: dict, done: threading.Event) -> None:
    task_id, run_id, sig = st["task_id"], st["sync_run_id"], st["signature"]
    result = error = None

    def before_write(c, check):  # inside rollback()'s write transaction, after its backup and conflict check
        _guard(c)
        # `check` is rollback()'s own _rollback_check, computed in this transaction under the write lock just before:
        # the same result as computing it again here, at half the cost
        if _signature(check) != sig:
            raise AppError("SYNC_ROLLBACK_PREVIEW_STALE", 409, detail=f"{run_id} changed since the preview")
    try:
        with db.read() as c:
            _guard(c)                           # before the backup
        out = history_sync.rollback(run_id, apply=True, by=st["by"], before_write=before_write)
        bk = out.get("backup")
        p = paths.backups_dir() / bk if bk else None
        result = {"sync_run_id": run_id, "rollback_run": out.get("rollback_run"), "entries": out.get("entries"),
                  "holds_released": out.get("holds_to_release"), "holds_restored": out.get("holds_to_restore"),
                  "backup_file": bk, "backup_path": str(p) if p else None,
                  "backup_bytes": p.stat().st_size if p is not None and p.exists() else None}
    except AppError as e:
        error = {"code": e.code, "detail": e.detail, "status": e.status}
    except Exception as e:  # noqa: BLE001 - recorded in the task state; SQLite rolled the write back
        log.error("sync rollback failed", exc_info=True, extra={"ctx": {"task_id": task_id}})
        error = {"code": "SYNC_ROLLBACK_FAILED", "detail": f"{type(e).__name__}: {e}"[:500]}
    finally:
        done.set()
        try:
            with db.tx() as c:
                cur = _read_state(c) or {}
                if cur.get("task_id") == task_id:
                    _write_state(c, {**cur, "status": "FAILED" if error else "SUCCEEDED", "finished_at": now_iso(),
                                     "heartbeat_at": now_iso(), "result": result, "error": error})
                if error:
                    db.audit(c, "SYNC_ROLLBACK_FAILED", "sync_run", run_id, {"task_id": task_id, "error": error})
        except Exception:  # noqa: BLE001 - the state stays RUNNING: shown INTERRUPTED once the lock is free
            log.error("sync rollback state not written", exc_info=True, extra={"ctx": {"task_id": task_id}})
        finally:
            _current.update(task_id=None, thread=None)
            _proc_lock.release()


# ------------------------------------------------------------------ routes
@router.get("/sync-runs")
def sync_runs():
    """Read-only: the latest runs of the BigQuery scope with `rollbackable` (never writes)."""
    scope_key = _scope_key_or_none()
    base = {"description_codes": list(DESCRIPTION_CODES), "description": _description(), "max_entries": MAX_ENTRIES}
    if scope_key is None:
        return {**base, "configured": False, "runs": []}
    out = []
    with db.read() as c:
        runs = db.rows(c, "SELECT id, kind, status, window_start, window_end, policy, started_at, finished_at, "
                          "summary_json, backup, rolled_back_by, rolled_back_at FROM demand_sync_runs WHERE scope_key=? "
                          "AND kind != 'PREVIEW' ORDER BY started_at DESC, rowid DESC LIMIT ?", (scope_key, LIST_MAX))
        end = time.monotonic() + LIST_TIMEOUT_S
        for r in runs:
            try:
                s = json.loads(r.pop("summary_json") or "{}")
            except (TypeError, ValueError):
                s = {}
            item = {**r, "summary": {k: s.get(k) for k in ("rows_written", "qty_written", "rows_logged", "holds", "units",
                                                           "keys", "by", "rolled_back_run", "entries") if k in s},
                    "rollbackable": False, "reason": None}
            if r["status"] != "COMMITTED":
                item["reason"] = "ALREADY_ROLLED_BACK" if r["status"] == "ROLLED_BACK" else r["status"]
            elif r["kind"] not in ROLLBACK_KINDS:
                item["reason"] = "KIND_NOT_ROLLBACKABLE"
            elif _entries(c, r["id"]) > MAX_ENTRIES:
                item["reason"] = "TOO_LARGE_FOR_THE_UI"
            elif time.monotonic() > end:
                item.update(rollbackable=None, reason="NOT_CHECKED")
            else:
                _deadline(c, max(0.1, end - time.monotonic()))
                try:
                    chk = history_sync._rollback_check(c, r["id"])
                    item.update(rollbackable=not chk[2], reason="CHANGED_BY_A_LATER_WRITE" if chk[2] else None,
                                conflicts=len(chk[2]))
                except sqlite3.OperationalError as e:
                    if "interrupted" not in str(e).lower():
                        raise
                    item.update(rollbackable=None, reason="NOT_CHECKED")
                finally:
                    c.set_progress_handler(None, 0)
            out.append(item)
        task = _view_state(c)
    return {**base, "configured": True, "scope_key": scope_key, "runs": out, "task": task}


class RunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sync_run_id: str


@router.post("/sync-rollback/preview")
def preview(body: RunBody):
    """rollback()'s dry run (no write, no backup) + its signature."""
    with db.read() as c:
        _deadline(c, PREVIEW_TIMEOUT_S)
        try:
            chk = _check(c, body.sync_run_id)
        except sqlite3.OperationalError as e:
            if "interrupted" not in str(e).lower():
                raise
            raise AppError("SYNC_ROLLBACK_TOO_LARGE", 422, detail=f"the check ran over {PREVIEW_TIMEOUT_S} s") from None
        finally:
            c.set_progress_handler(None, 0)
        busy = _busy_info(c)
        task = _view_state(c)
        other = hl.other_running(c, STATE)
    if chk[2]:
        raise AppError("SYNC_ROLLBACK_REFUSED", 409, detail=f"{len(chk[2])} keys changed by a later write since "
                       f"{body.sync_run_id}", conflicts=chk[2][:20], n_conflicts=len(chk[2]))
    return {**_summary(chk), "signature": _signature(chk), "confirm_text": _confirm_text(),
            "reason_min_length": REASON_MIN, "busy": busy, "disk": hl._disk(), "task": task,
            "ops_lock_checked": hl.ops_lock_checked(), "ops_lock_source": hl.ops_lock_source(),
            "ops_locks": hl.ops_locks(), "busy_other_task": other, "backup_before": True,
            "runs_in_background": True, "description_codes": list(DESCRIPTION_CODES), "description": _description()}


class RollbackBody(RunBody):
    signature: str
    confirm_text: str | None = None
    reason: str | None = None


@router.post("/sync-rollback", status_code=202)
def rollback(body: RollbackBody):
    reason = " ".join((body.reason or "").split())
    if len(reason) > REASON_MAX:
        raise AppError("SYNC_ROLLBACK_CONFIRM_REQUIRED", 422, detail=f"reason longer than {REASON_MAX} characters")
    expected_text = _confirm_text()
    if (body.confirm_text or "").strip() != expected_text or len(reason) < REASON_MIN:
        raise AppError("SYNC_ROLLBACK_CONFIRM_REQUIRED", 409,
                       detail=f"type {expected_text} and a reason of at least {REASON_MIN} characters",
                       confirm_text=expected_text, reason_min_length=REASON_MIN)
    if not _proc_lock.acquire(blocking=False):
        raise AppError("SYNC_ROLLBACK_RUNNING", 409, detail=f"rollback {_current['task_id']} is running",
                       task_id=_current["task_id"])
    claimed, started = None, False
    try:
        with db.read() as c:
            _guard(c)
            _deadline(c, PREVIEW_TIMEOUT_S)
            try:
                chk = _check(c, body.sync_run_id)
            except sqlite3.OperationalError as e:
                if "interrupted" not in str(e).lower():
                    raise
                raise AppError("SYNC_ROLLBACK_TOO_LARGE", 422,
                               detail=f"the check ran over {PREVIEW_TIMEOUT_S} s") from None
            finally:
                c.set_progress_handler(None, 0)
        if chk[2]:
            raise AppError("SYNC_ROLLBACK_REFUSED", 409, detail=f"{len(chk[2])} keys changed by a later write",
                           conflicts=chk[2][:20], n_conflicts=len(chk[2]))
        sig = _signature(chk)
        if sig != body.signature:
            raise AppError("SYNC_ROLLBACK_PREVIEW_STALE", 409, detail=f"{body.sync_run_id} changed since the preview")
        disk = _check_disk()
        task_id = db.new_id("SRB")
        _current.update(task_id=task_id)
        with db.tx() as c:   # gate, task state and request audit in ONE write transaction
            busy = _guard(c)
            old = _read_state(c)
            if old and old.get("status") == "RUNNING":
                if _alive(old):
                    raise AppError("SYNC_ROLLBACK_RUNNING", 409, detail=f"rollback {old.get('task_id')} is running",
                                   task_id=old.get("task_id"))
                run = _committed_run(c, old)
                db.audit(c, "SYNC_ROLLBACK_INTERRUPTED", "sync_run", old.get("sync_run_id"),
                         {"task_id": old.get("task_id"), "owner": old.get("owner"),
                          "committed_rollback_run": run["id"] if run else None})
            at = now_iso()
            st = {"task_id": task_id, "status": "RUNNING", "owner": runner.OWNER, "sync_run_id": body.sync_run_id,
                  "signature": sig, "summary": _summary(chk), "reason": reason, "by": f"{BY_PREFIX}{task_id}: {reason}",
                  "started_at": at, "heartbeat_at": at, "finished_at": None, "result": None, "error": None,
                  "disk": disk}
            _write_state(c, st)
            db.audit(c, "SYNC_ROLLBACK_REQUESTED", "sync_run", body.sync_run_id,
                     {"task_id": task_id, "signature": sig, "summary": st["summary"], "reason": reason, "disk": disk,
                      "stale_ignored_total": busy["stale_ignored_total"]})
        claimed = st
        done = threading.Event()
        th = threading.Thread(target=_worker, args=(st, done), name=f"sync-rollback-{task_id}", daemon=True)
        _current.update(thread=th)
        th.start()
        started = True
        threading.Thread(target=_heartbeat, args=(task_id, done), name=f"sync-rollback-hb-{task_id}",
                         daemon=True).start()
    except BaseException as e:
        if not started:
            try:
                if claimed is not None:
                    with db.tx() as c:
                        _write_state(c, {**claimed, "status": "FAILED", "finished_at": now_iso(),
                                         "error": {"code": "SYNC_ROLLBACK_FAILED",
                                                   "detail": f"{type(e).__name__}: {e}"[:500]}})
            finally:
                _current.update(task_id=None, thread=None)
                _proc_lock.release()
        raise
    if background.SYNC_MODE:
        th.join()
    with db.read() as c:
        return {"accepted": True, "task": _view_state(c), "description_codes": list(DESCRIPTION_CODES),
                "description": _description()}


@router.get("/sync-rollback/status")
def status():
    with db.read() as c:
        task = _view_state(c)
    return {"task": task, "running": bool(task and task.get("status") == "RUNNING"),
            "description_codes": list(DESCRIPTION_CODES), "description": _description()}


hl.register_task(STATE, _alive)
