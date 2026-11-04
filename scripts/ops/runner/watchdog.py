"""Watchdog of the step runner (owner 03/11), Scheduled Task "DemandForecastRunnerWatchdog" every 5 minutes
(register-watchdog.ps1); one check per start, then exit. Read-only: it changes nothing but its own files in the run
dir (watchdog_state.json, watchdog.log). Notifies (notify.py, same title / channels as the run) when:
  * the runner is dead (its named mutex is free) while the run is RUNNING / WAITING; one grace check when the runner
    task (--runner-task) starts again within 6 minutes (it restarts the runner), the next check alerts;
  * status.json has not changed for more than --stale-minutes (15);
  * while the run is RUNNING / WAITING, production shows another job: GET <api>/api/jobs?limit=20 with status PENDING /
    RUNNING / RETRY_WAIT and trigger MANUAL or a heavy type (--heavy), unless the type is in the current step's
    "expected_jobs";
  * a python process whose command line contains "app.cli sel2-", "pytest" or "sel2-replay", that is not a descendant
    of the runner and whose command line is not under an --ignore-path (default: the runner test folder).
The same alert is sent at most once per --debounce-minutes (30). Final alerts of the runner whose ntfy send failed
(status.json "pending_alerts") are resent once per check, also for a finished run, until ntfy accepts them (only while
no runner holds the mutex: then only this watchdog writes status.json).
usage: watchdog.py --run-dir <dir> [--stale-minutes 15] [--debounce-minutes 30] [--api http://127.0.0.1:8765]
                   [--heavy TRAIN_PUBLISH,FORECAST_EXTEND,FORECAST_REFRESH] [--runner-task DemandForecastRunner]
                   [--ignore-path <dir> ...] [--no-prod]"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ACTIVE, NO_WINDOW, alive, append_log, mutex_held, read_json, stamp, write_json  # noqa: E402
import notify  # noqa: E402

PATTERNS = ("app.cli sel2-", "pytest", "sel2-replay")
JOB_ACTIVE = ("PENDING", "RUNNING", "RETRY_WAIT")  # job_runs.status (QUEUED is a stage, not a status)

a = argparse.ArgumentParser()
a.add_argument("--run-dir", required=True)
a.add_argument("--stale-minutes", type=float, default=15)
a.add_argument("--debounce-minutes", type=float, default=30)
a.add_argument("--api", default="http://127.0.0.1:8765")
a.add_argument("--heavy", default="TRAIN_PUBLISH,FORECAST_EXTEND,FORECAST_REFRESH")
a.add_argument("--runner-task", default="DemandForecastRunner")
a.add_argument("--ignore-path", action="append", default=None)
a.add_argument("--no-prod", action="store_true", help="skip the production API / process checks")
A = a.parse_args()
RUN = Path(A.run_dir).resolve()
LOG, WST = RUN / "watchdog.log", RUN / "watchdog_state.json"
IGNORE = [x.lower() for x in (A.ignore_path or [r"D:\Buymed\tmp\runner_test"])]


def ps(cmd):
    return subprocess.run(["powershell", "-NoProfile", "-Command", cmd], stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, creationflags=NO_WINDOW, timeout=120).stdout.strip()


def processes():
    """[(pid, parent pid, command line)] of the python processes"""
    out = ps("Get-CimInstance Win32_Process -Filter \"Name LIKE 'python%'\" | Select-Object ProcessId, ParentProcessId, "
             "CommandLine | ConvertTo-Json -Compress")
    rows = json.loads(out) if out else []
    rows = [rows] if isinstance(rows, dict) else rows
    return [(r["ProcessId"], r["ParentProcessId"], r.get("CommandLine") or "") for r in rows]


def next_start_minutes():
    """minutes to the next start of the runner task, None when it is not registered / disabled / unknown"""
    try:
        out = ps(f"$t = Get-ScheduledTask -TaskName '{A.runner_task}' -ErrorAction SilentlyContinue; if ($t -and "
                 "$t.State -ne 'Disabled') { $n = ($t | Get-ScheduledTaskInfo).NextRunTime; if ($n) { "
                 "[math]::Round(($n - (Get-Date)).TotalMinutes, 2) } }")
        return float(out) if out else None
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def descendants(root, procs):
    kids, todo = set(), [root]
    while todo:
        p = todo.pop()
        for pid, ppid, _ in procs:
            if ppid == p and pid not in kids and pid != root:
                kids.add(pid)
                todo.append(pid)
    return kids


st = read_json(RUN / "status.json")
if not st:
    sys.exit(0)  # no run in this dir yet
ws = read_json(WST)
state = st.get("state")
runner_up = mutex_held(st["mutex"]) if st.get("mutex") else False
where = f"{st.get('run')} {st.get('x')}/{st.get('y')} {st.get('step_id')} {st.get('step_title', '')} [{state}]"
pend = st.get("pending_alerts") or []
if pend and not runner_up:
    left = []
    for p in pend:
        r = notify.send(p.get("title", "Demand Forecast"), f"{p.get('text', '')} (gui lai / resent {stamp()})",
                        p.get("priority", "high"), LOG, toast=False, ntfy=True)
        if not r.get("ntfy"):
            left.append({**p, "tries": int(p.get("tries", 0)) + 1})
    try:
        write_json(RUN / "status.json", {**st, "pending_alerts": left})  # only this field changes
    except OSError as e:
        append_log(LOG, f"status.json not written: {type(e).__name__}")
    append_log(LOG, f"pending final alerts: {len(pend)} resent, {len(left)} still pending")
alerts = []  # (key, event, text)
if state in ACTIVE:
    if runner_up:
        ws.pop("dead_since", None)
    else:
        nxt = next_start_minutes()
        if not ws.get("dead_since") and nxt is not None and 0 <= nxt < 6:
            ws["dead_since"] = time.time()  # single grace: the runner task starts it again within 6 minutes
            append_log(LOG, f"runner not running; task starts it in {nxt:.1f} min (grace, alert at the next check)")
        else:
            alerts.append(("runner_dead", "RUNNER DUNG / runner dead", f"{where}: tien trinh runner khong con chay"))
    age = (time.time() - float(st.get("updated_epoch", 0))) / 60
    if age > A.stale_minutes:
        alerts.append(("stale", "KHONG CAP NHAT / stuck", f"{where}: status.json khong doi {age:.0f} phut"))
    if not A.no_prod:
        heavy, expected = set(A.heavy.split(",")), set(st.get("expected_jobs") or [])
        try:
            with urllib.request.urlopen(f"{A.api.rstrip('/')}/api/jobs?limit=20", timeout=15) as r:
                jobs = json.loads(r.read().decode("utf-8"))
            for j in jobs if isinstance(jobs, list) else []:
                if j.get("status") in JOB_ACTIVE and j.get("job_type") not in expected and \
                        (j.get("trigger") == "MANUAL" or j.get("job_type") in heavy):
                    alerts.append((f"job:{j.get('id')}", "JOB KHAC / other job",
                                   f"{where}: production {j.get('job_type')} {j.get('status')} trigger {j.get('trigger')}"))
        except Exception as e:  # noqa: BLE001 - app not reachable: logged, not an alert of this watchdog
            append_log(LOG, f"jobs API not read: {type(e).__name__}")
        try:
            procs = processes()
            rp = st.get("runner_pid")
            mine = descendants(rp, procs) if runner_up and alive(rp, st.get("runner_created")) else set()
            hits = {pid: next((x for x in PATTERNS if x in cmd), None) for pid, _, cmd in procs}
            for pid, ppid, cmd in procs:
                hit = hits[pid]
                # a venv launcher and its interpreter share the command line: one alert, for the outer process
                if hit and pid not in mine and not hits.get(ppid) and not any(x in cmd.lower() for x in IGNORE):
                    alerts.append((f"proc:{pid}", "JOB KHAC / other job", f"{where}: python '{hit}' pid {pid} ngoai runner"))
        except Exception as e:  # noqa: BLE001
            append_log(LOG, f"process list not read: {type(e).__name__}")
sent = ws.get("sent", {})
for key, event, text in alerts:
    if time.time() - float(sent.get(key, 0)) < A.debounce_minutes * 60:
        append_log(LOG, f"debounced {key}")
        continue
    ch = st.get("notify_channels", ["toast", "ntfy"])
    notify.send(f"{st.get('notify_title', 'Demand Forecast')}: {event}", f"{text} ({stamp()})", "high", LOG,
                toast="toast" in ch, ntfy="ntfy" in ch)
    sent[key] = time.time()
write_json(WST, {**ws, "sent": sent, "last_check": stamp(), "last_alerts": [k for k, _, _ in alerts],
                 "runner_up": runner_up})
