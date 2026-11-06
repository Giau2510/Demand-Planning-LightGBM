"""Night catch-up + app watch (owner 05/11/2026 evening, items 7-8 "chong gian doan do gap may / ngu / mat mang").
One pass, run every 10 minutes by the Scheduled Task "DemandForecastNightCatchup" (register-night-catchup.ps1).
 7 app watch: GET /api/health. Down at 2 passes in a row -> notify once (high); back up -> notify once. The task
   DemandForecastLinkWatchdog (link-watchdog.ps1) already starts the app when no 'app.cli serve' process exists and no
   deploy / install / stop script runs (after 2 failed checks of 5 min): this script starts it ONLY when that watchdog
   cannot (run\\watchdog-hold, run\\paused, config\\link.json unreadable, task missing / disabled) and no install runs
   (no hold flag, no OPS_LOCK of another run, no deploy / rollback / install / stop script or cai_*.py deploy step):
   <Programs>\\<current.txt>\\scripts\\start.ps1 -NoBrowser, at most every 30 min and 3 times a day. App down while an
   install / hold / lock blocks any start: notified once (high) with the reasons, never started.
 8 night catch-up: the app scheduler itself runs today's D1_SYNC at the first tick after d1_signal_poll_start (a slot
   missed while the PC slept runs at wake), retries it max_attempts times (backoff 1, 2, 4 min) and then leaves it
   FAILED for the day. The SEL2 refresh (every refresh_retry_minutes until refresh_deadline once a D-1 of today
   SUCCEEDED, manual runs included) and the Excel export (inside the refresh job) follow by themselves. So: when
   today's scheduled D-1 ended FAILED and no D-1 of today succeeded or is under way, before refresh_deadline, network
   up (TCP 1.1.1.1:443), no blocking OPS_LOCK (run NIGHT-CATCHUP), no install, no job PENDING / RUNNING: ONE manual
   D-1 (POST /api/schedules/d1/run). After its own D-1, once each: POST /api/schedules/refresh/run when the scheduler
   made no refresh attempt 20 min after the D-1 success, POST /api/sel2/export when the refresh published but no
   non-stale Excel exists 20 min later. A D-1 the app ran late (PC asleep) is only reported. Notifies start / done /
   error. Never twice: state file <state dir>\\<day>.json. Other calls are GET only; never stops the app.
   Fail closed (reviewer 05/11): no POST when the job list or the process list cannot be read, nor inside the blocked
   windows 23:45-00:15 / 00:45-03:45 (Vietnam time); the next pass decides again.
usage: night_catchup.py [--base-url URL] [--state-dir DIR] [--remote-dir DIR] [--programs DIR] [--now "YYYY-MM-DD HH:MM"]
                        [--dry-run]"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "runner"))
import notify  # noqa: E402
from common import NO_WINDOW, append_log, ops_lock_block, read_json, write_json  # noqa: E402
import ops_config  # noqa: E402

VN = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh, no daylight saving
RUN_NAME = "NIGHT-CATCHUP"
TITLE = "[NIGHT-CATCHUP]"
WATCHDOG_TASK = "DemandForecastLinkWatchdog"
FOLLOW_UP = timedelta(minutes=20)  # wait for the scheduler before a refresh / export fallback
LATE_D1 = timedelta(minutes=30)    # scheduled D-1 started this long after its slot: the PC slept / the app was down
INSTALL_RE = re.compile(r"(deploy-upgrade|rollback-version|install|stop)\.ps1|Install\.bat|Stop\.bat|cai_\d+\.py\S*\s+deploy",
                        re.I)
SERVE_RE = re.compile(r"app\.cli[\"']?\s+serve", re.I)
BLOCKED = (("23:45", "00:15"), ("00:45", "03:45"))  # no POST inside these windows (Vietnam time)
O = None  # parsed arguments
LOG = None


def log(msg):
    append_log(LOG, msg)


def tell(key, st, title, text, high=False):
    """notify once per key and state file"""
    if key in st.setdefault("notified", {}):
        return
    st["notified"][key] = now().isoformat(timespec="seconds")
    notify.send(f"{TITLE} {title}", text, "high" if high else "default", log=LOG)


def now():
    return datetime.strptime(O.now, "%Y-%m-%d %H:%M").replace(tzinfo=VN) if O.now else datetime.now(VN)


def at(day, hhmm):
    h, m = (int(x) for x in str(hhmm).split(":")[:2])
    return datetime(day.year, day.month, day.day, h, m, tzinfo=VN)


def ts(s):
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def hm(t):
    return t.astimezone(VN).strftime("%H:%M") if t else "?"


# ------------------------------------------------------------------ app API (GET; POST only for the catch-up triggers)
def api(path, body=None, timeout=15):
    """(HTTP status, parsed JSON or None); status 0 = no answer"""
    req = urllib.request.Request(O.base_url.rstrip("/") + path, method="GET" if body is None else "POST",
                                 data=None if body is None else json.dumps(body).encode("utf-8"),
                                 headers={} if body is None else {"X-DF-Client": "web",
                                                                  "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None
    except (OSError, ValueError):
        return 0, None


def trigger(path, body=None):
    """POST once; returns a short record for the state file (never the response body)"""
    if O.dry_run:
        log(f"DRY-RUN: would POST {path}")
        return {"dry_run": True, "path": path, "at": now().isoformat(timespec="seconds")}
    code, r = api(path, body if body is not None else {}, timeout=60)
    r = r if isinstance(r, dict) else {}
    rec = {"path": path, "http": code, "job_id": r.get("id"), "already_active": r.get("already_active"),
           "error_code": None if 200 <= code < 300 else (r.get("code") or "NO_ANSWER"),
           "at": now().isoformat(timespec="seconds")}
    log(f"POST {path} -> {rec}")
    return rec


def health():
    code, r = api("/api/health", timeout=10)
    return code == 200 and isinstance(r, dict) and r.get("ok") is True


def jobs(**q):
    code, r = api("/api/jobs?" + "&".join(f"{k}={v}" for k, v in q.items()))
    return r if code == 200 and isinstance(r, list) else None


def today_rows(rows, day):
    start = at(day, "00:00")
    return [r for r in rows or [] if (ts(r.get("created_at")) or start - timedelta(1)) >= start]


def d1_ok(r, day):
    """a D-1 of today the refresh may follow (same rule as flows.d1_success_today)"""
    if r.get("status") != "SUCCEEDED":
        return False
    res = ((r.get("result") or {}).get("result") or {}) if isinstance(r.get("result"), dict) else {}
    if res.get("backfill") or res.get("mode") == "BACKFILL" or res.get("status") not in (None, "SUCCEEDED"):
        return False
    return str(res.get("window_end")) == str(day - timedelta(days=1)) if "window_end" in res else True


# ------------------------------------------------------------------ machine state
def processes():
    """command lines of the running processes, None when the list cannot be read (DF_NC_FAKE_PROCS = JSON list file,
    "null" = unreadable: tests only)"""
    fake = os.environ.get("DF_NC_FAKE_PROCS")
    if fake:
        return json.loads(Path(fake).read_text(encoding="utf-8"))
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | "
                              "Select-Object -ExpandProperty CommandLine | ConvertTo-Json -Compress"],
                             capture_output=True, text=True, timeout=90, creationflags=NO_WINDOW).stdout
        rows = json.loads(out)  # empty output = the query failed (there is always a process)
        return [x for x in (rows if isinstance(rows, list) else [rows]) if x]
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def install_blockers(procs):
    """reasons an install / maintenance may run (the app must not be started or used then)"""
    out = []
    if (Path(O.remote_dir) / "run" / "watchdog-hold").exists():
        out.append("watchdog-hold")
    lk = ops_lock_block(RUN_NAME)
    if lk:
        out.append(lk)
    if procs is None:
        out.append("process list unknown (install possibly running)")
    elif any(INSTALL_RE.search(p) for p in procs):
        out.append("deploy/install script running")
    return out


def window_block(t):
    """the blocked window holding t (Vietnam time), else None"""
    m = t.hour * 60 + t.minute
    for a, b in BLOCKED:
        a0, b0 = (int(x[:2]) * 60 + int(x[3:]) for x in (a, b))
        if (a0 <= m < b0) if a0 <= b0 else (m >= a0 or m < b0):
            return f"window {a}-{b}"
    return None


def watchdog_restarts():
    """None when link-watchdog.ps1 starts a stopped app by itself, else the reason it does not"""
    rd = Path(O.remote_dir)
    if (rd / "run" / "paused").exists():
        return "link paused (run\\paused)"
    if not isinstance(read_json(rd / "config" / "link.json"), dict) or not read_json(rd / "config" / "link.json"):
        return "config\\link.json unreadable"
    state = os.environ.get("DF_NC_WATCHDOG_TASK")  # tests only
    if state is None:
        try:
            state = subprocess.run(["powershell", "-NoProfile", "-Command",
                                    f"(Get-ScheduledTask -TaskName {WATCHDOG_TASK} -ErrorAction SilentlyContinue).State"],
                                   capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            state = ""
    if state not in ("Ready", "Running", "Queued"):
        return f"task {WATCHDOG_TASK} {state or 'missing'}"
    return None


def network_up():
    host, port = (os.environ.get("DF_NC_NET") or "1.1.1.1:443").rsplit(":", 1)  # env: tests only
    try:
        with socket.create_connection((host, int(port)), timeout=5):
            return True
    except OSError:
        return False


def start_app():
    prog = Path(O.programs)
    try:
        ver = (prog / "current.txt").read_text(encoding="utf-8").split()[0]
    except (OSError, IndexError):
        return "current.txt unreadable"
    start = prog / ver / "scripts" / "start.ps1"
    if not start.exists():
        return f"start.ps1 of {ver} not found"
    if O.dry_run:
        log(f"DRY-RUN: would start {ver}")
        return None
    log(f"starting app {ver}: start.ps1 -NoBrowser")
    try:
        rc = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(start), "-NoBrowser"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            timeout=300, creationflags=NO_WINDOW).returncode
    except (OSError, subprocess.SubprocessError) as e:
        return f"start.ps1 error {type(e).__name__}"
    return None if rc == 0 else f"start.ps1 exit {rc}"


# ------------------------------------------------------------------ 7: app watch
def app_watch(up):
    p = Path(O.state_dir) / "app.json"
    st = read_json(p) or {}
    t = now()
    if up:
        if st.get("down_since"):
            log(f"app answers again (down since {st['down_since']})")
            if st.get("notified_down"):
                notify.send(f"{TITLE} App chay lai", f"App tra loi lai luc {hm(t)} (ngung tu {st['down_since'][11:16]}"
                            f"{', da tu khoi dong' if st.get('started') else ''}).", log=LOG)
        if st:
            write_json(p, {})
        return
    st.setdefault("down_since", t.isoformat(timespec="seconds"))
    st["fails"] = st.get("fails", 0) + 1
    log(f"app does not answer /api/health (pass {st['fails']})")
    if st["fails"] < 2:  # one pass can be the wake-up itself
        write_json(p, st)
        return
    procs = processes()
    inst = install_blockers(procs)
    if inst:
        log("app down while an install / hold is active - left alone: " + "; ".join(inst))
        if not st.get("notified_down"):
            st["notified_down"] = True
            notify.send(f"{TITLE} App khong chay", f"App khong tra loi tu {st['down_since'][11:16]}; KHONG tu khoi dong vi: "
                        + "; ".join(x if not x.startswith("OPS_LOCK") else "OPS_LOCK" for x in inst) + ".", "high",
                        log=LOG)
        write_json(p, st)
        return
    if not st.get("notified_down"):
        st["notified_down"] = True
        notify.send(f"{TITLE} App khong chay", f"App khong tra loi tu {st['down_since'][11:16]}.", "high", log=LOG)
    serve = any(SERVE_RE.search(x) for x in procs)
    why = watchdog_restarts()
    if serve:
        log("an app.cli serve process exists but does not answer - not restarted (AGENTS.md 8)")
    elif why is None:
        log("app start left to DemandForecastLinkWatchdog (it restarts a stopped app)")
    else:
        starts = [x for x in st.get("starts", []) if x[:10] == t.date().isoformat()]
        last = ts(starts[-1]) if starts else None
        if len(starts) >= 3 or (last and t - last < timedelta(minutes=30)):
            log(f"watchdog cannot start the app ({why}); start limit reached / too recent - waiting")
        else:
            st["starts"] = starts + [t.isoformat(timespec="seconds")]
            err = start_app()
            ok = err is None and (O.dry_run or health())
            st["started"] = st.get("started") or ok
            log(f"app start ({why}): {'OK' if ok else err or 'still not answering'}")
            notify.send(f"{TITLE} {'Da khoi dong app' if ok else 'Khoi dong app LOI'}",
                        f"Lan {len(st['starts'])}/3 hom nay: {'app tra loi' if ok else err or 'app chua tra loi'}.",
                        "default" if ok else "high", log=LOG)
    write_json(p, st)


# ------------------------------------------------------------------ 8: night catch-up
def blockers(procs):
    out = install_blockers(procs)
    w = window_block(now())
    if w:
        out.append(w)
    if not network_up():
        out.append("no network")
    run_, pend = jobs(status="RUNNING", limit=20), jobs(status="PENDING", limit=20)
    if run_ is None or pend is None:
        out.append("job list unknown")
    active = (run_ or []) + (pend or [])
    if active:
        out.append("job active: " + ", ".join(sorted({str(r.get("job_type")) for r in active})))
    return out


def catchup():
    code, s = api("/api/scheduler/status")
    if code != 200 or not isinstance(s, dict):
        log(f"scheduler status unreadable (HTTP {code})")
        return
    cfg = s.get("config") or {}
    t = now()
    day = t.date()
    poll, deadline = at(day, cfg.get("d1_signal_poll_start", "01:00")), at(day, cfg.get("refresh_deadline", "12:00"))
    if not cfg.get("d1_enabled") or t < poll:
        return
    p = Path(O.state_dir) / f"{day.isoformat()}.json"
    st = read_json(p) or {"day": day.isoformat()}
    try:
        _catchup(t, day, cfg, s, poll, deadline, st)
    finally:
        write_json(p, st)


def _catchup(t, day, cfg, s, poll, deadline, st):
    d1 = jobs(job_type="D1_SYNC", limit=50)
    if d1 is None:
        log("job list unreadable")
        return
    d1 = today_rows(d1, day)
    sched = next((r for r in d1 if r.get("idempotency_key") == f"D1_SYNC:{day.isoformat()}"), None)
    ok_rows = [r for r in d1 if d1_ok(r, day)]
    busy = any(r.get("status") in ("PENDING", "RUNNING", "RETRY_WAIT") for r in d1)
    if sched and (ts(sched.get("created_at")) or t) - poll > LATE_D1:
        st["catchup"] = True
        tell("late", st, "App chay bu D-1", f"D-1 hom nay bat dau luc {hm(ts(sched.get('created_at')))} (lich "
             f"{cfg.get('d1_signal_poll_start')}): may ngu / tat / app dung luc do; app tu chay bu.")
    if sched is None and not ok_rows and not busy and t - poll > timedelta(hours=1):
        tell("d1_missing", st, "Chua co D-1", f"Den {hm(t)} chua co D-1 hom nay (bo lich chay: "
             f"{'co' if s.get('running') else 'KHONG'}). Khong tu chay thay bo lich.", high=True)
    if not ok_rows and not busy and sched and sched.get("status") == "FAILED" and not st.get("d1_triggered"):
        if t > deadline:
            tell("d1_failed_late", st, "D-1 loi", f"D-1 hom nay loi ({sched.get('reason_code')}); qua "
                 f"{cfg.get('refresh_deadline')}: khong chay bu.", high=True)
            return
        b = blockers(processes())
        if b:
            log("D-1 FAILED, catch-up waits: " + "; ".join(b))
            tell("d1_wait", st, "D-1 loi - cho chay bu", f"D-1 hom nay loi ({sched.get('reason_code')}); cho: "
                 + "; ".join(x if not x.startswith("OPS_LOCK") else "OPS_LOCK" for x in b) + ".")
            return
        st["catchup"] = True
        st["d1_triggered"] = rec = trigger("/api/schedules/d1/run")
        ok = O.dry_run or rec.get("error_code") is None
        tell("d1_start", st, "Bat dau chay bu D-1" if ok else "Chay bu D-1 LOI",
             f"D-1 da loi luc {hm(ts(sched.get('finished_at')))} ({sched.get('reason_code')}); chay bu 1 lan luc "
             f"{hm(t)}" + ("." if ok else f": {rec.get('error_code')}."), high=not ok)
        return
    mine = st.get("d1_triggered")
    if mine and not mine.get("dry_run") and not mine.get("error_code") and not ok_rows and not busy:
        job = next((r for r in d1 if r.get("id") == mine.get("job_id")), None)
        tell("d1_catchup_failed", st, "Chay bu D-1 LOI", f"Lan chay bu D-1 ket thuc "
             f"{(job or {}).get('status', '?')} {(job or {}).get('reason_code') or ''}; khong chay lai.", high=True)
        return
    if not st.get("catchup") or not ok_rows:
        return
    code, ex = api(f"/api/sel2/export/{day.isoformat()}/runs")
    items = (ex or {}).get("items") if code == 200 and isinstance(ex, dict) else None
    good = [x for x in items or [] if x.get("refresh_run_id") and not x.get("is_stale")]
    if good:
        tell("done", st, "Xong chay bu", f"D-1 + du bao + Excel hom nay xong (Excel v{good[0].get('version')}, "
             f"{hm(ts(good[0].get('created_at')))}).")
        return
    if t > deadline:
        tell("deadline", st, "Chua co Excel", f"Qua {cfg.get('refresh_deadline')} chua co Excel du bao moi hom nay "
             "(sau chay bu D-1).", high=True)
        return
    if not mine:
        return  # the app caught up by itself: its scheduler does the refresh + export, reported above
    d1_done = max((ts(r.get("finished_at")) for r in ok_rows if ts(r.get("finished_at"))), default=t)
    ref = jobs(job_type="FORECAST_REFRESH", limit=50)
    if ref is None:
        log("refresh job list unreadable - decided at the next pass")
        return
    ref = today_rows(ref, day)
    if not ref and cfg.get("refresh_enabled") and t - d1_done >= FOLLOW_UP and not st.get("refresh_triggered"):
        b = blockers(processes())
        if b:
            log("refresh fallback waits: " + "; ".join(b))
            return
        st["refresh_triggered"] = rec = trigger("/api/schedules/refresh/run")
        tell("refresh_start", st, "Chay du bao (du phong)", f"Bo lich chua chay du bao {FOLLOW_UP.seconds // 60} phut "
             f"sau D-1: chay 1 lan luc {hm(t)}" + (f" - LOI {rec['error_code']}" if rec.get("error_code") else "") + ".",
             high=bool(rec.get("error_code")))
        return
    pub = [r for r in ref if r.get("status") == "SUCCEEDED"]
    pub_at = max((ts(r.get("finished_at")) for r in pub if ts(r.get("finished_at"))), default=t)
    if pub and items is not None and t - pub_at >= FOLLOW_UP and not st.get("export_triggered"):
        b = blockers(processes())
        if b:
            log("export fallback waits: " + "; ".join(b))
            return
        st["export_triggered"] = rec = trigger("/api/sel2/export", {"date": day.isoformat(), "confirm": True})
        tell("export_start", st, "Xuat Excel (du phong)", f"Du bao xong nhung chua co Excel {FOLLOW_UP.seconds // 60} "
             f"phut sau: xuat 1 lan luc {hm(t)}" + (f" - LOI {rec['error_code']}" if rec.get("error_code") else "")
             + ".", high=bool(rec.get("error_code")))


def main(argv=None):
    global O, LOG
    a = argparse.ArgumentParser()
    a.add_argument("--base-url", default="http://127.0.0.1:8765")
    a.add_argument("--state-dir", default=str(ops_config.REPORTS / "night-catchup"))
    a.add_argument("--remote-dir", default=str(ops_config.REMOTE_DIR))
    a.add_argument("--programs", default=str(ops_config.PROGS))
    a.add_argument("--now", help="tests only: Vietnam time YYYY-MM-DD HH:MM")
    a.add_argument("--dry-run", action="store_true", help="decide and log, never POST / start the app")
    O = a.parse_args(argv)
    Path(O.state_dir).mkdir(parents=True, exist_ok=True)
    LOG = Path(O.state_dir) / "night-catchup.log"
    try:
        up = health()
        app_watch(up)
        if up:
            catchup()
    except Exception as e:  # noqa: BLE001 - the next pass tries again; the type only (no data, no secrets)
        log(f"ERROR {type(e).__name__}: {str(e)[:200]}")
        p = Path(O.state_dir) / "errors.json"
        key = f"{now().date()} {type(e).__name__}"
        if (read_json(p) or {}).get("notified") != key:  # once per day and error type, never every 10 minutes
            write_json(p, {"notified": key})
            notify.send(f"{TITLE} Loi script", f"night_catchup.py: {type(e).__name__}", "high", log=LOG)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
