"""1.4.0 SEL2 jobs: the runner handlers (jobs/runner.py) and the scheduler helpers (jobs/scheduler.py) used while
sel2_pipeline.enabled is True; with False nothing here is called (exact 1.3.1 behaviour).

  FORECAST_REFRESH  (SEL2 mode) BigQuery scope: the open-hours read up to D-1 (1.4.2, daily_refresh.sync_open_hours:
                    incremental, skipped when the table did not change) and the AVG_DEMAND current read of D in this
                    process (light; a failure is a flag, never blocks)
                    -> `python -m app.cli sel2-day --date D --yes` in a CHILD process (candidates + SEL2 + publication +
                    the pipeline's export hook): the heavy memory is given back when the child ends
  CANDIDATE_TRAIN   `python -m app.cli sel2-train --origin <retraining weekday> --yes` in a child process (timeout
                    sel2_pipeline.train_timeout_seconds); the scheduled weekly one or ONE catch-up of the week's origin
  FORECAST_EXPORT   in this process (light): STALE = the day's Excel without a SEL2 run at export_deadline; AVG = a new
                    version after the AVG_DEMAND table refresh (sel2_pipeline.avg_reexport_time, None = off)
The child runs with the same interpreter and environment (DF_DATA_DIR, LOCALAPPDATA ... inherited); its JSON result is
read from stdout; timeout = schedule.timeout_seconds (CANDIDATE_TRAIN: sel2_pipeline.train_timeout_seconds); a
cancellation or a timeout kills the child process tree. The child gets `--trigger <job trigger> --job-id <job id>`: the
runs, trainings and exports record the job row that started them. On Windows the child is put into a Job Object with
KILL_ON_JOB_CLOSE: it ends with the server process (no orphan training after a crash / stop of the app)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from ... import db
from ... import settings_service as ss
from ...messages import AppError
from ...timeutil import now_vn, parse_iso, today_vn, vn_slot
from .errors import DISABLED, RETRYABLE

log = logging.getLogger("df.sel2.jobs")
PIPELINE_ACTIVE = "SEL2_PIPELINE_ACTIVE"         # a scheduled 1.3.1 TRAIN_PUBLISH while SEL2 is on: SKIPPED
CHILD_FAILED = "SEL2_CHILD_FAILED"               # crash / no readable JSON result (retryable: every step is resumable)
CHILD_TIMEOUT = "SEL2_CHILD_TIMEOUT"
CHILD_CANCELLED = "SEL2_CHILD_CANCELLED"
INTERNAL_ERROR = "SEL2_INTERNAL_ERROR"           # unexpected exception in the child (printed by the CLI): not retried
TRAIN_BUSY = "SEL2_TRAIN_BUSY"                   # another process trains the scope (= pipeline.TRAIN_BUSY): retryable
AVG_UNCHANGED = "SEL2_AVG_UNCHANGED"
AVG_DAY_PASSED = "SEL2_AVG_REEXPORT_DAY_PASSED"
STALE_NOT_NEEDED = "SEL2_STALE_EXPORT_NOT_NEEDED"
FLAG_AVG_READ_FAILED = "AVG_READ_FAILED"
FLAG_OPEN_HOURS_READ_FAILED = "OPEN_HOURS_READ_FAILED"   # = daily_refresh.OPEN_HOURS_ALERT
FLAG_ACTUAL_DAILY_FAILED = "DAILY_ACTUAL_FAILED"       # = daily_refresh.ACTUAL_DAILY_ALERT (1.4.4)
# 1.3.1 NOT_READY codes: the attempt is a SKIPPED row with its reason, the schedule makes the next attempt
NOT_READY_CODES = ("OPEN_HOURS_INVALID", "REFRESH_WAITS_FOR_D1", "NOT_APPLICABLE_FOR_SOURCE")
# free commit (MB) needed to start the day's run next to a running CANDIDATE_TRAIN (= pipeline.MIN_COMMIT_MB, not
# imported: the server does not load the training modules for a scheduling decision)
OVERLAP_MIN_COMMIT_MB = 3072
# the LightGBM candidates trained per weekly origin (= pipeline.TRAIN_ORDER, not imported for the same reason)
TRAIN_MODELS = ("MOC", "V33_L112", "V36_two_stage")
_PKG = __name__.split(".", 1)[0]
_BACKEND = Path(__file__).resolve().parents[3]          # folder holding the app package (cwd / PYTHONPATH of the child)
_child_runner = None                                    # tests: a fake replacing run_child (never a real heavy child)


class ChildError(AppError):
    """Failed child run mapped to a job status; retryable = the runner retries it with its backoff."""

    def __init__(self, code: str, detail: str | None = None, retryable: bool = False):
        super().__init__(code, status=500, detail=detail)
        self.retryable = retryable


def enabled(conn=None) -> bool:
    return bool(ss.get("sel2_pipeline", conn).enabled)


def set_child_runner(fn) -> None:
    """Tests: fn(args: list[str], timeout: int, cancel) -> dict (the child's JSON); None restores run_child."""
    global _child_runner
    _child_runner = fn


# ------------------------------------------------------------------ child process
def child_command(args: list[str]) -> list[str]:
    return [sys.executable, "-m", f"{_PKG}.cli", *args]


def _kill_tree(p: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            p.kill()
    except Exception:  # noqa: BLE001 - the direct kill below still applies
        log.warning("child tree kill failed", exc_info=True, extra={"ctx": {"pid": p.pid}})
    try:
        p.kill()
    except OSError:
        pass


def _kill_on_close_job(p: subprocess.Popen):
    """Windows: a Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE holding the child; its handle is closed when the
    child ended (or by the OS when this process ends, which kills the child). None elsewhere or on failure (logged)."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k32.CreateJobObjectW(None, None)
    if not h:
        log.warning("sel2 child: no job object", extra={"ctx": {"pid": p.pid, "winerror": ctypes.get_last_error()}})
        return None
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000                  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = (k32.SetInformationJobObject(h, 9, ctypes.byref(info), ctypes.sizeof(info))   # JobObjectExtendedLimitInformation
          and k32.AssignProcessToJobObject(h, wintypes.HANDLE(int(p._handle))))
    if not ok:
        log.warning("sel2 child: not assigned to a job object",
                    extra={"ctx": {"pid": p.pid, "winerror": ctypes.get_last_error()}})
        k32.CloseHandle(h)
        return None
    return (k32, h)


def _close_job(job) -> None:
    if job:
        try:
            job[0].CloseHandle(job[1])
        except Exception:  # noqa: BLE001
            pass


def _parse(out: str) -> dict | None:
    """The CLI prints one JSON document on stdout (indented); a stray line before it is tolerated."""
    text = (out or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        i = text.find("\n{")
        try:
            return json.loads(text[i + 1:]) if i >= 0 else None
        except ValueError:
            return None


def run_child(args: list[str], timeout: int, cancel=None, cmd: list[str] | None = None) -> dict:
    """Run `python -m app.cli <args>` and return its JSON result (+ "exit_code"). Timeout / cancel: the process tree is
    killed and ChildError raised; no readable JSON: ChildError SEL2_CHILD_FAILED (retryable)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"                   # Vietnamese texts in the JSON (a pipe is not the console)
    env["PYTHONPATH"] = os.pathsep.join(x for x in (str(_BACKEND), env.get("PYTHONPATH")) if x)
    cmd = cmd or child_command(args)
    started = time.monotonic()
    p = subprocess.Popen(cmd, cwd=str(_BACKEND), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        job = _kill_on_close_job(p)
    except Exception:  # noqa: BLE001 - the child still runs (without the tie to this process)
        log.warning("sel2 child: job object failed", exc_info=True, extra={"ctx": {"pid": p.pid}})
        job = None
    log.info("sel2 child started", extra={"ctx": {"pid": p.pid, "args": args, "job_object": job is not None}})
    try:
        while True:
            try:
                out, err = p.communicate(timeout=1)
                break
            except subprocess.TimeoutExpired:
                why = (CHILD_CANCELLED if cancel is not None and cancel() else
                       CHILD_TIMEOUT if time.monotonic() - started > timeout else None)
                if why:
                    _kill_tree(p)
                    try:
                        p.communicate(timeout=30)
                    except Exception:  # noqa: BLE001 - pipes of a killed process
                        pass
                    log.warning("sel2 child killed", extra={"ctx": {"pid": p.pid, "code": why, "args": args}})
                    raise ChildError(why, detail=f"{' '.join(args)}: pid {p.pid} killed", retryable=False)
    finally:
        _close_job(job)
    res = _parse(out.decode("utf-8", "replace"))
    tail = err.decode("utf-8", "replace")[-1500:]
    log.info("sel2 child ended", extra={"ctx": {"pid": p.pid, "exit_code": p.returncode,
                                                "seconds": round(time.monotonic() - started, 1)}})
    if not isinstance(res, dict):
        raise ChildError(CHILD_FAILED, detail=f"exit {p.returncode}, no JSON result; stderr: {tail}", retryable=True)
    return {**res, "exit_code": p.returncode}


def call_cli(args: list[str], cancel=None, timeout: int | None = None) -> dict:
    timeout = timeout or ss.get("schedule").timeout_seconds
    return (_child_runner or run_child)(args, timeout, cancel)


def _job_args(job_id, trigger: str | None) -> list[str]:
    """--trigger / --job-id of the child: the job row's trigger (SCHEDULE / CATCH_UP / RETRY / MANUAL) and id."""
    if trigger is None and job_id:
        with db.read() as c:
            r = c.execute("SELECT trigger FROM job_runs WHERE id=?", (job_id,)).fetchone()
        trigger = r[0] if r else None
    return ["--trigger", trigger or "SCHEDULE", *(["--job-id", str(job_id)] if job_id else [])]


def _failure(res: dict) -> tuple[str, str]:
    code = res.get("code") or (CHILD_FAILED if res.get("refused") else None) or CHILD_FAILED
    detail = res.get("detail") or res.get("refused") or res.get("en") or code
    return code, str(detail)[:2000]


# ------------------------------------------------------------------ AVG_DEMAND current read (light, in process)
def avg_read(d: date) -> dict:
    """The current AVG_DEMAND snapshot of D, read once per day (a completed CURRENT read of D is kept). Never raises."""
    from . import avg_demand
    try:
        cfg = ss.get("sel2_pipeline")
        with db.read() as c:
            done = db.one(c, "SELECT id, source_modified FROM avg_demand_reads WHERE business_date=? AND kind=? AND "
                             "source_table=? ORDER BY completed_at DESC, rowid DESC LIMIT 1",
                          (d.isoformat(), avg_demand.KIND_CURRENT, cfg.avg_demand_table))
        if done:
            return {"status": "ALREADY_READ", "read_id": done["id"]}
        r = avg_demand.read_current(d, cfg)
        return {"status": "READ", "read_id": r.get("read_id"), "rows": r.get("rows"),
                "source_modified": r.get("source_modified")}
    except Exception as e:  # noqa: BLE001 - the day's forecast never waits for the AVG_DEMAND read
        code = e.code if isinstance(e, AppError) else type(e).__name__
        log.warning("sel2 avg demand read failed", extra={"ctx": {"business_date": str(d), "code": code}})
        return {"status": "FAILED", "code": code, "error": f"{type(e).__name__}: {e}"[:300]}


# ------------------------------------------------------------------ open-hours read (light, in process)
def open_hours_read(d: date, scope: dict) -> dict:
    """1.4.2: the open hours of the BigQuery scope up to D-1, read before the day's run (sel2-day only checks them:
    OPEN_HOURS_INVALID stays the gate). The 1.3.1 read (daily_refresh.sync_open_hours: incremental from the last
    completed read, skipped when the table did not change, ONE WARNING alert per day on failure). Never raises."""
    from ...data.demand import data_window
    from .. import daily_refresh
    try:
        with db.read() as c:
            floor = data_window(c, today=d, scope=scope)["start"]
        return daily_refresh.sync_open_hours(d, floor, ss.get("daily_forecast"))
    except Exception as e:  # noqa: BLE001 - the day's forecast goes on with the stored open hours
        err = (f"{e.code}: {e.detail or ''}" if isinstance(e, AppError) else f"{type(e).__name__}: {e}")[:500]
        log.warning("sel2 open hours read failed", extra={"ctx": {"business_date": str(d), "error": err}})
        return {"error": err}


# ------------------------------------------------------------------ actual_daily (light, in process)
def actual_refresh(d: date, scope: dict) -> dict:
    """1.4.4: actual_daily of the scope for D-14 .. D-1 from demand_daily (daily_refresh.refresh_actual_daily, the
    1.3.1 step after its publication; the SEL2 child never ran it, so actual_daily stopped in SEL2 mode). The range is
    rewritten in one transaction (idempotent; no day outside it is touched), clipped to the data window. A failure is
    logged + ONE WARNING alert (daily_refresh.ACTUAL_DAILY_ALERT), never blocks the day's forecast."""
    from datetime import timedelta
    from ...data.demand import data_window
    from .. import daily_refresh
    start, end = d - timedelta(days=daily_refresh.ACTUAL_DAYS), d - timedelta(days=1)
    try:
        with db.read() as c:
            floor = data_window(c, today=d, scope=scope)["start"]
        n = daily_refresh.refresh_actual_daily(scope["scope_key"], start, end, floor=floor)
        return {"rows": n, "start": str(start), "end": str(end)}
    except Exception as e:  # noqa: BLE001 - the day's forecast goes on; done again at the next refresh
        err = (f"{e.code}: {e.detail or ''}" if isinstance(e, AppError) else f"{type(e).__name__}: {e}")[:500]
        log.warning("sel2 actual_daily refresh failed", extra={"ctx": {"business_date": str(d), "error": err}})
        daily_refresh._warn(daily_refresh.ACTUAL_DAILY_ALERT, {"business_date": str(d), "error": err},
                            "scope", scope["scope_key"])
        return {"rows": None, "error": err}


# ------------------------------------------------------------------ handlers
def _day(v) -> date:
    return date.fromisoformat(str(v)[:10]) if v else today_vn()


def refresh(job_id, params: dict, cancel=None, progress=None, trigger: str = "SCHEDULE") -> dict:
    """FORECAST_REFRESH in SEL2 mode. Result status PUBLISHED / FAILED / SKIPPED / NOT_READY (runner.REFRESH_STATUS);
    a retryable child error (SEL2_LOW_MEMORY, a crashed child) is raised for the runner's retry."""
    stage = progress or (lambda *a, **k: None)
    d = _day(params.get("business_date"))
    force = bool(params.get("force")) or trigger == "MANUAL"     # as 1.3.1: a manual run publishes a new run
    base = {"business_date": str(d), "pipeline": "SEL2", "force": force}
    stage("VALIDATING_DATA")
    from ...data.demand import resolve_scope
    with db.read() as c:
        try:
            scope = resolve_scope(c)
        except Exception:  # noqa: BLE001 - no active scope: the child reports its own error
            scope = None
        source = scope["data_source"] if scope else None
        if d == today_vn():
            from ...jobs import flows
            if source is not None and source != "BIGQUERY":
                return {**base, "status": "NOT_READY", "reason_code": "NOT_APPLICABLE_FOR_SOURCE"}
            if source == "BIGQUERY" and not flows.d1_success_today(c, vn_slot(d, "23:59")):
                return {**base, "status": "NOT_READY", "reason_code": "REFRESH_WAITS_FOR_D1"}
    flags = []
    stage("SYNCING")                                    # open hours (BigQuery scope) + AVG_DEMAND read
    # today's run only: a rerun of a past day never moves the last completed read back (the next read stays incremental)
    oh = open_hours_read(d, scope) if source == "BIGQUERY" and d == today_vn() else None
    if oh and oh.get("error"):
        flags.append(FLAG_OPEN_HOURS_READ_FAILED)
    avg = avg_read(d)
    if avg["status"] == "FAILED":
        flags.append(FLAG_AVG_READ_FAILED)
    # 1.4.4: actual_daily D-14 .. D-1 (after today's D-1 load, gate above); a past day rewrites the same range again
    act = actual_refresh(d, scope) if scope is not None else None
    if act and act.get("error"):
        flags.append(FLAG_ACTUAL_DAILY_FAILED)
    stage("FORECASTING")                                # candidates + SEL2 + publication + export (child)
    res = call_cli(["sel2-day", "--date", str(d), "--yes", *(["--force"] if force else []),
                    *_job_args(job_id, trigger)], cancel)
    base.update(open_hours=oh, avg_read=avg, actual_daily=act, flags=flags, exit_code=res.get("exit_code"))
    if res.get("ok"):
        r = res.get("result") or {}
        st = r.get("status")
        if st == "PUBLISHED":
            exp = r.get("export") or {}
            return {**base, "status": "PUBLISHED", "reason_code": "SEL2_PUBLISHED", "refresh_run_id": r.get("run_id"),
                    "model_version": r.get("model_version"), "flags": flags + list(r.get("flags") or []),
                    "series": r.get("series"), "rows": r.get("rows"),
                    "export": {"ok": exp.get("ok"), "version": (exp.get("result") or {}).get("version"),
                               "error": exp.get("error")}}
        if st == "ALREADY_PUBLISHED":
            return {**base, "status": "SKIPPED", "reason_code": "ALREADY_PUBLISHED", "refresh_run_id": r.get("run_id")}
        return {**base, "status": "SKIPPED", "reason_code": r.get("reason_code") or DISABLED}
    code, detail = _failure(res)
    if code in RETRYABLE and code != INTERNAL_ERROR:                 # SEL2_INTERNAL_ERROR: FAILED below, never retried
        raise ChildError(code, detail=detail, retryable=True)
    if code in NOT_READY_CODES:
        return {**base, "status": "NOT_READY", "reason_code": code, "detail": detail}
    return {**base, "status": "FAILED", "reason_code": code, "error": detail}


def train(job_id, params: dict, cancel=None, progress=None, trigger: str | None = None) -> dict:
    """CANDIDATE_TRAIN: the LightGBM candidates of the weekly origin (params.origin) in a child process (timeout
    sel2_pipeline.train_timeout_seconds); trigger None = the job row's trigger."""
    stage = progress or (lambda *a, **k: None)
    origin = _day(params.get("origin"))
    stage("TRAINING")
    res = call_cli(["sel2-train", "--origin", str(origin), "--yes", *_job_args(job_id, trigger)], cancel,
                   timeout=ss.get("sel2_pipeline").train_timeout_seconds)
    if res.get("ok"):
        r = res.get("result") or {}
        return {"status": "DONE", "origin": str(origin), "trained": r.get("trained"), "skipped": r.get("skipped"),
                "exit_code": res.get("exit_code")}
    code, detail = _failure(res)
    if code == DISABLED:
        return {"status": "SKIPPED", "reason_code": code, "origin": str(origin)}
    raise ChildError(code, detail=detail, retryable=code != INTERNAL_ERROR and (code in RETRYABLE or
                                                                                code in (CHILD_FAILED, TRAIN_BUSY)))


def export_job(job_id, params: dict) -> dict:
    """FORECAST_EXPORT (light, in process): mode STALE (export_deadline), AVG (after the AVG_DEMAND refresh) or MANUAL
    (POST /api/sel2/export: a new version of D's Excel now)."""
    from . import export
    d = _day(params.get("business_date"))
    mode = params.get("mode") or "STALE"
    if mode == "MANUAL":
        r = export.write_daily_export(d, trigger="MANUAL", job_id=job_id)
        return {"status": "DONE", "mode": mode, "business_date": str(d), "version": r["version"],
                "n_rows": r["n_rows"], "is_stale": r["is_stale"], "sha256": r.get("sha256"), "path": r.get("path"),
                "flags": r.get("flags", [])}
    if mode == "STALE":
        with db.read() as c:
            if published_run(c, d) or latest_export(c, d):
                return {"status": "SKIPPED", "reason_code": STALE_NOT_NEEDED, "business_date": str(d)}
        avg = avg_read(d)
        r = export.write_daily_export(d, trigger="STALE", job_id=job_id)
        return {"status": "DONE", "mode": mode, "business_date": str(d), "version": r.get("version"),
                "is_stale": r.get("is_stale"), "avg_read": avg,
                "flags": [FLAG_AVG_READ_FAILED] if avg["status"] == "FAILED" else []}
    if d != today_vn():
        return {"status": "SKIPPED", "reason_code": AVG_DAY_PASSED, "business_date": str(d)}
    from ...sync import Wait
    from . import avg_demand
    wait_s = 60 * ss.get("schedule").refresh_retry_minutes
    with db.read() as c:
        last = latest_export(c, d)
    used = ((json.loads(last["summary_json"] or "{}").get("avg") or {}).get("source_modified")) if last else None
    now_mod = avg_demand.source_modified_now()
    if last is None or now_mod is None or (used and parse_iso(now_mod) <= parse_iso(used)):
        raise Wait(AVG_UNCHANGED, wait_s)                 # checked again later the same day (one job row per day)
    r = avg_demand.read_current(d)
    e = export.write_daily_export(d, trigger="AVG_REEXPORT", job_id=job_id)
    return {"status": "DONE", "mode": mode, "business_date": str(d), "version": e.get("version"),
            "source_modified": now_mod, "previous_source_modified": used, "read_id": r.get("read_id")}


# ------------------------------------------------------------------ scheduler helpers (read only)
def published_run(conn, d: date) -> dict | None:
    """The latest SEL2 run published for D in the active scope (None without an active scope)."""
    from ...data.demand import resolve_scope
    from . import store
    try:
        sk = resolve_scope(conn)["scope_key"]
    except Exception:  # noqa: BLE001 - no active scope
        return None
    return store.published_run(conn, sk, d)


def run_flags(run: dict | None) -> list[str]:
    try:
        return list((json.loads((run or {}).get("detail_json") or "{}")).get("flags") or [])
    except ValueError:
        return []


def models_missing(conn, origin: date) -> bool:
    """True when a model of TRAIN_MODELS has no SUCCEEDED training of this origin in the active scope (no active scope:
    False, nothing can be trained)."""
    from ...data.demand import resolve_scope
    try:
        sk = resolve_scope(conn)["scope_key"]
    except Exception:  # noqa: BLE001 - no active scope
        return False
    done = {r["model"] for r in db.rows(conn, "SELECT DISTINCT model FROM candidate_train_runs WHERE scope_key=? AND "
                                              "origin_date=? AND status='SUCCEEDED'", (sk, origin.isoformat()))}
    return any(m not in done for m in TRAIN_MODELS)


def latest_export(conn, d: date) -> dict | None:
    return db.one(conn, "SELECT id, version, summary_json, created_at FROM export_runs WHERE forecast_date=? "
                        "ORDER BY version DESC, rowid DESC LIMIT 1", (d.isoformat(),))


def may_overlap_training() -> bool:
    """FORECAST_REFRESH may start while CANDIDATE_TRAIN runs: SEL2 on, at/after today's prev_week_deadline and the free
    commit at least OVERLAP_MIN_COMMIT_MB (unknown = allowed: the runner's memory check still applies)."""
    from ...jobs import resources
    s = ss.get("sel2_pipeline")
    now = now_vn()
    if not s.enabled or now < vn_slot(now.date(), s.prev_week_deadline):
        return False
    try:
        avail = resources.snapshot().get("commit_avail")
    except Exception:  # noqa: BLE001
        avail = None
    return avail is None or avail / resources.MB >= OVERLAP_MIN_COMMIT_MB
