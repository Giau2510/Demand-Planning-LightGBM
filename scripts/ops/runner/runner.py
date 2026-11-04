"""Step runner (owner 03/11): runs the ordered steps of a plan.json one after the other, as the Windows Scheduled Task
"DemandForecastRunner" (register-runner.ps1: at logon + every 5 minutes), independent of any chat session.
  * one instance per PLAN NAME: the named mutex Global\\DF-runner-<plan name> is held for the runner's lifetime (the
    OS frees it when the process ends, also on a kill); a second start exits at once (the 5-minute trigger is harmless);
  * checkpoint <run dir>\\state.json after every change (fsync + atomic replace; the last 2 good states are kept in
    state.json.bak / .bak2); a DONE step is never run again (restart of the PC / task). An unreadable / missing
    state.json of a started run is NEVER re-initialised: the runner notifies (high) and exits until the operator checks
    it. Restoring a .bak goes back one change: the last finished step can be run again (steps are resumable anyway);
  * state.json is written at every start and with the attempt marked STARTING BEFORE the step process is launched: an
    unwritable state.json stops the runner before any child starts (alert once per failure kind per 30 minutes);
  * final alerts (FAILED, STOPPED, WAITING_APPROVAL, DONE, state errors) whose ntfy send failed are kept in
    status.json "pending_alerts"; the watchdog resends them at each check until ntfy accepts them;
  * a step starts only outside its blocked windows (default 23:45-00:15 and 00:45-03:00; "allowed_windows" narrows it
    further), with free commit >= min_free_commit_mb and its precondition OK (waits up to precondition_wait_minutes);
  * a running step is killed (taskkill /T /F) at the start of a blocked window or when free commit < stop_free_commit_mb
    and is started AGAIN later: STEPS MUST BE RESUMABLE (a second run continues or redoes the work without harm); the
    same holds for a step interrupted by a restart of the PC or the runner;
  * exit code in temporary_exit_codes or a temporary_markers text in the output -> retried (retries, default 1);
  * stop for good (notified): a non-temporary failure after the retries (FAILED), a failed safety gate after the step
    (STOPPED); "needs_approval": true stops BEFORE the step (WAITING_APPROVAL) until <run dir>\\approve-<id>.txt exists;
  * STATUS.md + status.json in the run dir on every change and every status_every_s (300 s); STATUS.md is also copied to
    --status-copy (real use: D:\\Buymed\\Lightgbm AI\\STATUS.md). --clear-stop re-arms a FAILED / STOPPED run (the
    failed step runs again at the next start).
Precondition / gate: {"expr": "<python expression>"} over a small safe context (names: free_commit_mb, free_ram_mb,
hour, minute, weekday (0 = Monday), today ("YYYY-MM-DD"); functions: exists(path), file_contains(path, text),
step_done(id); only literals, comparisons, and/or/not, + - * / %; relative paths are taken from the step cwd), or
{"command": [argv], "cwd": ..., "timeout_s": 600} whose exit code 0 = OK.
Test clock: env RUNNER_CLOCK_OFFSET_S shifts the clock used for the windows (tests only).
usage: runner.py --plan <plan.json> --run-dir <dir> [--status-copy <file>] [--clear-stop]"""
import argparse
import ast
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (NO_WINDOW, TERMINAL, alive, append_log, kill_tree, load_json, mem, mutex_name,  # noqa: E402
                    proc_created, read_json, stamp, take_mutex, write_json)
import notify  # noqa: E402

DEFAULTS = {"blocked_windows": [["23:45", "00:15"], ["00:45", "03:00"]], "allowed_windows": [],
            "min_free_commit_mb": 3072, "stop_free_commit_mb": 1536, "max_memory_stops": 6,
            "retries": 1, "retry_delay_s": 60, "temporary_exit_codes": [],
            "temporary_markers": ["SEL2_LOW_MEMORY", "URLError", "ConnectionError", "ConnectionResetError", "TimeoutError",
                                  "getaddrinfo failed", "WinError 10054", "WinError 10060"],
            "precondition_wait_minutes": 60, "wait_poll_s": 60, "poll_s": 5, "status_every_s": 300,
            "eta_minutes": 10, "notify_done": True, "needs_approval": False, "expected_jobs": [], "env": {}}

a = argparse.ArgumentParser()
a.add_argument("--plan", required=True)
a.add_argument("--run-dir", required=True)
a.add_argument("--status-copy")
a.add_argument("--clear-stop", action="store_true")
A = a.parse_args()
PLAN_FILE = Path(A.plan).resolve()
RUN = Path(A.run_dir).resolve()
(RUN / "logs").mkdir(parents=True, exist_ok=True)
LOG, STATE = RUN / "runner.log", RUN / "state.json"
PLAN = read_json(PLAN_FILE)
if not PLAN.get("steps"):
    append_log(LOG, f"plan has no steps or cannot be read: {PLAN_FILE.name}")
    sys.exit(2)
STEPS = PLAN["steps"]
if len({s["id"] for s in STEPS}) != len(STEPS):
    append_log(LOG, "plan has duplicate step ids")
    sys.exit(2)
TITLE = PLAN.get("notify_title", "Demand Forecast")
CHANNELS = PLAN.get("notify_channels", ["toast", "ntfy"])
STATUS_COPY = A.status_copy or PLAN.get("status_copy")
RUN_NAME = PLAN.get("name", PLAN_FILE.stem)
MUTEX = mutex_name(RUN_NAME)
DEVNULL = subprocess.DEVNULL
CHILD = None  # the running step process (stopped cleanly when state.json cannot be written)
PENDING = []  # final alerts whose ntfy send failed (status.json "pending_alerts", resent by the watchdog)
LAST_KEY = None  # state content of the last good write (the .bak copies rotate only on a real change)
ALERTS = RUN / "runner_alerts.json"  # debounce of the state-write alerts (state.json itself cannot be written then)


def opt(step, key):
    return step.get(key, PLAN.get("defaults", {}).get(key, DEFAULTS[key]))


def clock():
    return dt.datetime.now() + dt.timedelta(seconds=float(os.environ.get("RUNNER_CLOCK_OFFSET_S", "0") or 0))


# ------------------------------------------------------------------ state, status, notifications
S = {}
last_status = 0.0


def stop_child(p):
    """taskkill /T /F + wait (twice); returns the exit code, None when the process survived"""
    for n in (1, 2):
        rc = kill_tree(p.pid)
        try:
            return p.wait(timeout=60)
        except subprocess.TimeoutExpired:
            append_log(LOG, f"pid {p.pid} still alive 60 s after taskkill (exit {rc}), try {n}/2")
    return None


def state_key():
    return json.dumps({k: v for k, v in S.items() if k != "updated_at"}, sort_keys=True, default=str)


def save():
    global LAST_KEY
    S["updated_at"] = stamp()
    key = state_key()
    rotate, err = key != LAST_KEY, None
    for n in range(1, 6):
        try:
            write_json(STATE, S, backup=rotate)
            LAST_KEY = key
            return
        except OSError as e:
            err, rotate = e, False  # the copies were already rotated by the first try
            append_log(LOG, f"state.json write failed ({type(e).__name__}), try {n}/5")
            time.sleep(2 * n)
    # no checkpoint possible: stop the step cleanly (it is resumable and runs again from the last saved state) and stop
    if CHILD is not None and CHILD.poll() is None:
        stop_child(CHILD)
    append_log(LOG, "RUN stopped: state.json cannot be written")
    sig = f"state.json write {type(err).__name__} {getattr(err, 'winerror', None) or getattr(err, 'errno', '')}"
    sent = read_json(ALERTS)
    if time.time() - float(sent.get(sig, 0)) >= 1800:
        sent[sig] = time.time()
        try:
            write_json(ALERTS, sent)
        except OSError as e:
            append_log(LOG, f"alert debounce file not written: {type(e).__name__}")
        tell("LOI / error", STEPS[counts()[1]], "state.json khong ghi duoc / cannot be written: runner dung, khong chay "
             "buoc nao; kiem tra o dia / file", True, final=True)
    else:
        append_log(LOG, f"alert debounced: {sig}")
    sys.exit(4)


def state_error(why):
    """state.json of a started run is unreadable / missing: never start over (DONE steps would run again)"""
    sig = f"{why}|{STATE.stat().st_mtime if STATE.exists() else '-'}"
    append_log(LOG, f"RUN NOT STARTED: state.json {why}; operator must check it (previous good state: state.json.bak)")
    old = read_json(RUN / "status.json")
    if old.get("state_error") != sig:  # once per broken file, not every 5-minute task start
        title = f"{TITLE}: LOI TRANG THAI / state error"
        text = (f"{RUN_NAME}: state.json {why}. Runner KHONG chay buoc nao; nguoi van hanh phai kiem tra state.json "
                f"(state.json.bak / .bak2 = trang thai tot truoc do) ({stamp()})")
        res = notify.send(title, text, "high", LOG, toast="toast" in CHANNELS, ntfy="ntfy" in CHANNELS)
        pend = old.get("pending_alerts") or []
        if "ntfy" in CHANNELS and not res.get("ntfy"):
            pend.append({"title": title, "text": text, "priority": "high", "at": stamp()})
        try:
            write_json(RUN / "status.json", {**old, "state": "STATE_ERROR", "state_error": sig, "updated_at": stamp(),
                                             "updated_epoch": time.time(), "reason": f"state.json {why}",
                                             "last_error": f"state.json {why}", "pending_alerts": pend})
        except OSError as e:
            append_log(LOG, f"status write failed: {type(e).__name__}")
    sys.exit(3)


def load_state():
    if not STATE.exists():
        if STATE.with_name("state.json.bak").exists() or STATE.with_name("state.json.bak2").exists():
            state_error("missing (state.json.bak exists)")
        return {}
    try:
        s = load_json(STATE)
        if not isinstance(s.get("steps"), dict) or "run" not in s:
            raise ValueError("no steps")
        return s
    except (OSError, ValueError) as e:
        state_error(f"unreadable ({type(e).__name__})")


def counts():
    done = sum(1 for s in STEPS if S["steps"][s["id"]]["status"] == "DONE")
    cur = next((i for i, s in enumerate(STEPS) if S["steps"][s["id"]]["status"] != "DONE"), len(STEPS) - 1)
    return done, cur


def expected_end():
    left = 0.0
    for s in STEPS:
        st = S["steps"][s["id"]]
        if st["status"] == "DONE":
            continue
        eta = float(opt(s, "eta_minutes")) * 60
        if st["status"] == "RUNNING" and st.get("run_started_epoch"):
            eta = max(60.0, eta - (time.time() - st["run_started_epoch"]))
        left += eta
    return None if S.get("state") in TERMINAL else stamp(time.time() + left)


def status(force=False):
    global last_status
    if not force and time.time() - last_status < float(PLAN.get("status_every_s", DEFAULTS["status_every_s"])):
        return
    last_status = time.time()
    ram, com = mem()
    done, cur = counts()
    step = STEPS[cur]
    st = S["steps"][step["id"]]
    js = {"run": S["run"], "state": S["state"], "reason": S.get("reason", ""), "step_id": step["id"],
          "step_title": step.get("title", ""), "step_status": st["status"], "x": cur + 1, "y": len(STEPS), "done": done,
          "started_at": S["started_at"], "expected_end": expected_end(), "finished_at": S.get("finished_at"),
          "free_ram_mb": ram, "free_commit_mb": com, "last_error": S.get("last_error", ""), "updated_at": stamp(),
          "updated_epoch": time.time(), "runner_pid": os.getpid(), "runner_created": proc_created(os.getpid()),
          "mutex": MUTEX,
          "child_pid": S.get("child_pid"), "expected_jobs": opt(step, "expected_jobs"), "notify_title": TITLE,
          "notify_channels": CHANNELS, "pending_alerts": PENDING, "steps": [{"id": s["id"], "status": S["steps"][s["id"]]["status"],
                                                   "attempts": S["steps"][s["id"]]["attempts"]} for s in STEPS]}
    lines = [f"# Trang thai chay nhieu buoc: {js['run']}", "",
             f"* Cap nhat: {js['updated_at']} (moi {int(float(PLAN.get('status_every_s', 300)) / 60)} phut va khi doi "
             "trang thai)",
             f"* Trang thai: {js['state']}" + (f" ({js['reason']})" if js["reason"] else ""),
             f"* Buoc hien tai: {js['x']}/{js['y']} {js['step_id']} - {js['step_title']} [{js['step_status']}]",
             f"* Da xong: {done}/{len(STEPS)} buoc",
             f"* Bat dau: {js['started_at']}",
             f"* Du kien xong: {js['expected_end'] or '-'}" + (f"; ket thuc: {js['finished_at']}" if js["finished_at"] else ""),
             f"* RAM trong {ram} MB, commit trong {com} MB",
             f"* Loi gan nhat: {js['last_error'] or '-'}", "",
             "| # | Buoc | Trang thai | Lan chay |", "|---|---|---|---|"]
    lines += [f"| {i + 1} | {s['id']} - {s.get('title', '')} | {S['steps'][s['id']]['status']} | "
              f"{S['steps'][s['id']]['attempts']} |" for i, s in enumerate(STEPS)]
    text = "\n".join(lines) + "\n"
    try:  # a failed status write never stops the runner: logged, written again at the next cycle
        write_json(RUN / "status.json", js)
        (RUN / "STATUS.md").write_text(text, encoding="utf-8")
    except OSError as e:
        append_log(LOG, f"status write failed: {type(e).__name__}")
        last_status = 0.0
    if STATUS_COPY:
        try:
            Path(STATUS_COPY).write_text(text, encoding="utf-8")
        except OSError as e:
            append_log(LOG, f"status copy failed: {type(e).__name__}")


def tell(event, step, text, high=False, final=False):
    msg = f"{S['run']} {STEPS.index(step) + 1}/{len(STEPS)} {step['id']} {step.get('title', '')}: {text} ({stamp()})"
    res = notify.send(f"{TITLE}: {event}", msg, "high" if high else "default", LOG, toast="toast" in CHANNELS,
                      ntfy="ntfy" in CHANNELS)
    if final and "ntfy" in CHANNELS and not res.get("ntfy"):
        PENDING.append({"title": f"{TITLE}: {event}", "text": msg, "priority": "high" if high else "default",
                        "at": stamp()})
        status(force=True)  # the watchdog resends it


def set_run(state, reason=""):
    S["state"], S["reason"] = state, reason
    if state in TERMINAL:
        S["finished_at"] = stamp()
    save()
    status(force=True)


def end(state, step, why, event, high=True):
    if state in ("FAILED", "STOPPED"):
        S["last_error"] = why
    S["approval_step"] = step["id"] if state == "WAITING_APPROVAL" else None
    set_run(state, why)
    append_log(LOG, f"RUN {state}: {step['id']} {why}")
    tell(event, step, why, high, final=True)
    sys.exit(0 if state in ("DONE", "WAITING_APPROVAL") else 1)


# ------------------------------------------------------------------ windows, checks
def secs(hms):
    p = [int(x) for x in hms.split(":")]
    return p[0] * 3600 + p[1] * 60 + (p[2] if len(p) > 2 else 0)


def inside(sec, w):
    a0, b0 = secs(w[0]), secs(w[1])
    return a0 <= sec < b0 if a0 <= b0 else sec >= a0 or sec < b0


def window_block(step):
    t = clock()
    sec = t.hour * 3600 + t.minute * 60 + t.second
    for w in opt(step, "blocked_windows"):
        if inside(sec, w):
            return f"window {w[0]}-{w[1]}"
    aw = opt(step, "allowed_windows")
    if aw and not any(inside(sec, w) for w in aw):
        return "outside allowed windows"
    return None


SAFE = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.USub, ast.Compare, ast.Eq, ast.NotEq,
        ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod,
        ast.Constant, ast.Name, ast.Load, ast.Call, ast.List, ast.Tuple)


def check(step, spec, kind):
    """(ok, detail) of a precondition / gate"""
    cwd = Path(step.get("cwd") or RUN)
    if "expr" in spec:
        def p(x):
            return Path(x) if Path(x).is_absolute() else cwd / x
        funcs = {"exists": lambda x: p(x).exists(),
                 "file_contains": lambda x, s: p(x).exists() and s in p(x).read_text(encoding="utf-8", errors="replace"),
                 "step_done": lambda i: S["steps"].get(i, {}).get("status") == "DONE"}
        ram, com = mem()
        t = clock()
        names = {"free_commit_mb": com, "free_ram_mb": ram, "hour": t.hour, "minute": t.minute, "weekday": t.weekday(),
                 "today": t.date().isoformat(), "True": True, "False": False, **funcs}
        try:
            tree = ast.parse(spec["expr"], mode="eval")
            called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
            for n in ast.walk(tree):
                # a function name only as the callee (a bare `step_done` would always be true)
                if not isinstance(n, SAFE) or (isinstance(n, ast.Name) and (n.id not in names or (n.id in funcs) !=
                                                                            (id(n) in called))) or \
                        (isinstance(n, ast.Call) and (not isinstance(n.func, ast.Name) or n.func.id not in funcs or n.keywords)):
                    return False, f"{kind} expression not allowed: {type(n).__name__}"
            return bool(eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, names)), f"{kind} expr"
        except Exception as e:  # noqa: BLE001
            return False, f"{kind} expression error {type(e).__name__}"
    out = RUN / "logs" / f"{step['id']}.{kind}.out"
    try:
        with open(out, "w", encoding="utf-8") as f:
            p = subprocess.Popen(spec["command"], cwd=str(spec.get("cwd") or cwd), env={**os.environ, **opt(step, "env")},
                                 stdin=DEVNULL, stdout=f, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        try:
            rc = p.wait(timeout=float(spec.get("timeout_s", 600)))
        except subprocess.TimeoutExpired:
            stop_child(p)  # whole tree: the venv launcher runs the real interpreter as its child
            return False, f"{kind} command timeout"
    except Exception as e:  # noqa: BLE001
        return False, f"{kind} command error {type(e).__name__}"
    return rc == 0, f"{kind} command exit {rc}"


# ------------------------------------------------------------------ one step
def run_step(i, step):
    global CHILD
    sid = step["id"]
    st = S["steps"][sid]
    if st["status"] in ("RUNNING", "STARTING"):
        old = st.get("child_pid"), st.get("child_created")
        orphan = alive(*old)
        krc = kill_tree(old[0]) if orphan else None  # child of a dead runner: stop it, the step runs again (resumable)
        append_log(LOG, f"{sid}: interrupted run (runner / PC restart) -> run again"
                        + (f"; leftover child pid {old[0]} killed (taskkill exit {krc})" if orphan else ""))
    if opt(step, "needs_approval") and not st.get("approved_at"):
        if not (RUN / f"approve-{sid}.txt").exists():
            if S.get("state") == "WAITING_APPROVAL" and S.get("approval_step") == sid:
                sys.exit(0)  # still waiting (5-minute restarts of the task): nothing new, no new notification
            st["status"] = "PENDING"
            end("WAITING_APPROVAL", step, f"approval needed: approve-{sid}.txt for {sid}", "CAN DUYET / approval needed")
        st["approved_at"] = stamp()
        append_log(LOG, f"{sid}: approval file found")
    pre_waited, pre_last = 0.0, None  # precondition wait time, without the time inside blocked windows
    while True:
        # ---- wait for the window, the precondition and the memory
        why = window_block(step)
        if why:
            pre_last = None
        elif step.get("precondition"):
            ok, det = check(step, step["precondition"], "precondition")
            if ok:
                pre_waited, pre_last = 0.0, None
            else:
                now = time.time()
                pre_waited += now - pre_last if pre_last else 0.0
                pre_last = now
                why = f"precondition not met ({det})"
                if pre_waited > float(opt(step, "precondition_wait_minutes")) * 60:
                    st["status"] = "FAILED"
                    end("FAILED", step, why, "LOI / error")
        if not why and mem()[1] < float(opt(step, "min_free_commit_mb")):
            why = f"free commit < {opt(step, 'min_free_commit_mb')} MB"
        if why:
            if S.get("reason") != why or S.get("state") != "WAITING":
                append_log(LOG, f"{sid}: waiting - {why}")
                set_run("WAITING", why)
            status()
            time.sleep(float(opt(step, "wait_poll_s")))
            continue
        # ---- run: the attempt is checkpointed BEFORE the launch (an unwritable state.json exits here, no child)
        st["attempts"] += 1
        st["status"] = "STARTING"
        save()
        out = RUN / "logs" / f"{sid}.{st['attempts']}.out"
        with open(out, "w", encoding="utf-8") as f:
            p = CHILD = subprocess.Popen(step["command"], cwd=str(step.get("cwd") or RUN),
                                         env={**os.environ, **opt(step, "env")}, stdin=DEVNULL, stdout=f,
                                         stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        st.update(status="RUNNING", child_pid=p.pid, child_created=proc_created(p.pid), run_started_epoch=time.time())
        st.setdefault("started_at", stamp())
        S["child_pid"] = p.pid
        append_log(LOG, f"{sid}: start attempt {st['attempts']} (pid {p.pid})")
        set_run("RUNNING", "")
        stop = None
        while p.poll() is None:
            stop = window_block(step) or (f"free commit < {opt(step, 'stop_free_commit_mb')} MB"
                                          if mem()[1] < float(opt(step, "stop_free_commit_mb")) else None)
            if stop:
                break
            status()
            time.sleep(float(opt(step, "poll_s")))
        rc = stop_child(p) if stop else p.wait()
        if stop and rc is None:
            st["status"] = "FAILED"
            end("FAILED", step, f"step process could not be stopped ({stop})", "LOI / error")
        CHILD = None
        S["child_pid"] = None
        st["last_rc"] = rc
        if stop:
            key = "memory_stops" if stop.startswith("free commit") else "window_stops"
            st[key] = st.get(key, 0) + 1
            append_log(LOG, f"{sid}: killed ({stop}); runs again later")
            if key == "memory_stops" and st[key] > int(opt(step, "max_memory_stops")):
                st["status"] = "FAILED"
                end("FAILED", step, f"{st[key]} memory stops", "LOI / error")
            st["status"] = "PENDING"
            save()
            continue
        if rc == 0:
            if step.get("gate"):
                ok, det = check(step, step["gate"], "gate")
                if not ok:
                    st["status"] = "GATE_FAILED"
                    end("STOPPED", step, f"safety gate failed ({det})", "DUNG / safety gate")
            st.update(status="DONE", finished_at=stamp())
            append_log(LOG, f"{sid}: DONE")
            save()
            status(force=True)
            if opt(step, "notify_done") and i < len(STEPS) - 1:
                tell("XONG BUOC / step done", step, "DONE")
            return
        text = out.read_text(encoding="utf-8", errors="replace")
        mark = next((m for m in opt(step, "temporary_markers") if m in text), None)
        temp = rc in opt(step, "temporary_exit_codes") or mark
        why = f"exit {rc}" + (f", marker {mark}" if mark else "")
        S["last_error"] = f"{sid}: {why}"
        if temp and st.get("retries_used", 0) < int(opt(step, "retries")):
            st["retries_used"] = st.get("retries_used", 0) + 1
            st["status"] = "PENDING"
            append_log(LOG, f"{sid}: temporary error ({why}) -> retry {st['retries_used']}/{opt(step, 'retries')}")
            set_run("WAITING", f"retry after temporary error ({why})")
            time.sleep(float(opt(step, "retry_delay_s")))
            continue
        st["status"] = "FAILED"
        end("FAILED", step, f"failed: {why}" + (" (retries used)" if temp else ""), "LOI / error")


# ------------------------------------------------------------------ main
MUTEX_HANDLE = take_mutex(MUTEX)  # kept for the process lifetime
if not MUTEX_HANDLE:
    sys.exit(0)  # another runner of this plan is alive
S.update(load_state())
LAST_KEY = state_key() if S else None
PENDING[:] = read_json(RUN / "status.json").get("pending_alerts") or []
sha = hashlib.sha256(PLAN_FILE.read_bytes()).hexdigest()[:16]
if not S:
    S.update(run=RUN_NAME, plan_sha=sha, state="RUNNING", reason="", started_at=stamp(),
             last_error="", steps={})
for s in STEPS:
    S["steps"].setdefault(s["id"], {"status": "PENDING", "attempts": 0})
if S.get("plan_sha") != sha:
    append_log(LOG, f"plan changed ({S.get('plan_sha')} -> {sha}); finished steps stay finished")
    S["plan_sha"] = sha
if A.clear_stop and S.get("state") in ("FAILED", "STOPPED"):
    for s in S["steps"].values():
        if s["status"] in ("FAILED", "GATE_FAILED"):
            s.update(status="PENDING", retries_used=0, memory_stops=0)
    append_log(LOG, "stop cleared by --clear-stop")
    set_run("RUNNING", "")
if S.get("state") in TERMINAL:
    sys.exit(0)  # finished or stopped for good: the 5-minute task start does nothing
if S.get("state") != "WAITING_APPROVAL":
    append_log(LOG, f"runner start pid {os.getpid()} ({S['run']}, state {S.get('state')})")
save()  # state.json writable? checked before any step process starts
for idx, step in enumerate(STEPS):
    if S["steps"][step["id"]]["status"] != "DONE":
        run_step(idx, step)
end("DONE", STEPS[-1], "all steps done", "HOAN TAT / run finished", high=False)
