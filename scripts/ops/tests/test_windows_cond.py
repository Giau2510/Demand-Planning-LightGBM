"""Conditional blocked windows of the runner (owner 06/11/2026, heavy jobs that do not write production): isolated runner
runs (temp run dirs, temp OPS_LOCK, notifications off). Windows are placed around the real clock:
  1. release_command exit 0 -> the window opens (logged "released"), the step runs to DONE;
  2. release_command exit 1 -> the step waits inside the window (WAITING, "not released"), nothing runs;
  3. low_memory_only with impossible thresholds -> blocked (logged "low memory"), with 0 thresholds -> runs;
  4. a window without options still blocks as before."""
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time

from ops_test_env import OPS, isolate  # noqa: E402

T = isolate("ops_wincond_")
PY = sys.executable
RESULTS = []
CFG = T / "notify" / "notify_config.json"
CFG.parent.mkdir()
CFG.write_text(json.dumps({"toast": False, "ntfy": False}), encoding="utf-8")
os.environ["DF_NOTIFY_CONFIG"] = str(CFG)
os.environ.pop("RUNNER_CLOCK_OFFSET_S", None)
import common  # noqa: E402


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


def around_now():
    a = dt.datetime.now() - dt.timedelta(minutes=2)
    b = dt.datetime.now() + dt.timedelta(minutes=20)
    return a.strftime("%H:%M"), b.strftime("%H:%M")


def runner(name, window):
    d = T / name
    d.mkdir()
    plan = {"name": f"WINCOND-{name}", "notify_title": "wincond test", "notify_channels": [], "status_every_s": 1,
            "defaults": {"min_free_commit_mb": 0, "stop_free_commit_mb": 0, "poll_s": 1, "wait_poll_s": 1,
                         "retries": 0, "eta_minutes": 1, "blocked_windows": [window]},
            "steps": [{"id": "s1", "title": "sleep", "command": [PY, "-c", "import time; time.sleep(2)"]}]}
    (d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    p = subprocess.Popen([PY, str(OPS / "runner" / "runner.py"), "--plan", str(d / "plan.json"), "--run-dir",
                          str(d / "run")], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    return d, p


def rlog(d):
    f = d / "run" / "runner.log"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def state(d):
    return common.read_json(d / "run" / "state.json") or {}


def wait_for(cond, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.5)
    return False


a, b = around_now()
# 1. released
d, p = runner("released", [a, b, {"release_command": [PY, "-c", "print('DONE test night'); import sys; sys.exit(0)"]}])
p.wait(120)
ok("release exit 0: window released + logged", "released (DONE test night)" in rlog(d), rlog(d)[-500:])
ok("release exit 0: step DONE", state(d).get("state") == "DONE", state(d))

# 2. not released
d, p = runner("held", [a, b, {"release_command": [PY, "-c", "print('NOT YET: x'); import sys; sys.exit(1)"]}])
held = wait_for(lambda: "not released: NOT YET: x" in rlog(d), 40)
time.sleep(4)
ok("release exit 1: waiting in the window", held and state(d).get("state") == "WAITING", rlog(d)[-500:])
ok("release exit 1: the step never started", "start attempt" not in rlog(d), rlog(d)[-500:])
p.kill()
p.wait(30)

# 3. low memory only
d, p = runner("lowmem", [a, b, {"low_memory_only": {"free_ram_mb": 10 ** 9, "free_commit_mb": 10 ** 9}}])
blocked = wait_for(lambda: "low memory" in rlog(d), 40)
time.sleep(3)
ok("low memory: paused + logged", blocked and "start attempt" not in rlog(d), rlog(d)[-500:])
p.kill()
p.wait(30)
d, p = runner("enoughmem", [a, b, {"low_memory_only": {"free_ram_mb": 0, "free_commit_mb": 0}}])
p.wait(120)
ok("enough memory: runs to DONE", state(d).get("state") == "DONE" and "low memory" not in rlog(d), rlog(d)[-500:])

# 4. plain window
d, p = runner("plain", [a, b])
w = wait_for(lambda: f"waiting - window {a}-{b}" in rlog(d), 40)
ok("plain window still blocks", w and "start attempt" not in rlog(d), rlog(d)[-500:])
p.kill()
p.wait(30)

bad = [n for n, x in RESULTS if not x]
print(f"\n{len(RESULTS) - len(bad)} passed, {len(bad)} failed" + (f": {bad}" if bad else ""))
if not bad:
    shutil.rmtree(T, ignore_errors=True)  # kept on failure for the diagnosis
sys.exit(1 if bad else 0)
