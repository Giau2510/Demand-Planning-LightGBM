"""Keep-awake only on AC power (owner 06/11/2026): isolated runner runs with a fake power state
(DF_OPS_FAKE_POWER_FILE, read at every call). Never touches production: temp run dirs, temp OPS_LOCK, notifications
off (no channel), no real power setting. Checks the runner.log lines written by runner.set_awake:
  1. start on battery -> "keep awake: off (battery, start)", the step still runs to DONE;
  2. start on AC -> "keep awake: on (AC, start)";
  3. AC -> battery -> AC during a step -> "off (battery, power change)" then "on (AC, power change)";
  4. common.power() reads the fake file (and an unreadable file = unknown) / keep_awake(False) clears the request."""
import json
import os
import shutil
import subprocess
import sys
import time

from ops_test_env import OPS, isolate  # noqa: E402

T = isolate("ops_awake_")
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


def runner(name, seconds, power):
    d = T / name
    d.mkdir()
    pf = d / "power.txt"
    pf.write_text(power, encoding="utf-8")
    plan = {"name": f"AWAKE-TEST-{name}", "notify_title": "awake test", "notify_channels": [], "status_every_s": 1,
            "defaults": {"min_free_commit_mb": 0, "stop_free_commit_mb": 0, "poll_s": 1, "wait_poll_s": 1,
                         "retries": 0, "eta_minutes": 1, "blocked_windows": []},
            "steps": [{"id": "s1", "title": "sleep", "command": [PY, "-c", f"import time; time.sleep({seconds})"]}]}
    (d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    p = subprocess.Popen([PY, str(OPS / "runner" / "runner.py"), "--plan", str(d / "plan.json"), "--run-dir",
                          str(d / "run")], env={**os.environ, "DF_OPS_FAKE_POWER_FILE": str(pf)},
                         stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    return d, pf, p


def rlog(d):
    f = d / "run" / "runner.log"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def wait_for(cond, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.5)
    return False


def state(d):
    return common.read_json(d / "run" / "state.json") or {}


# 1. start on battery
d, pf, p = runner("battery", 3, "0 40")
p.wait(120)
log = rlog(d)
ok("battery start: keep awake off", "keep awake: off (battery, start)" in log, log[-600:])
ok("battery start: never asks to stay awake", "keep awake: on" not in log, log[-600:])
ok("battery start: the step still runs (DONE)", state(d).get("state") == "DONE", state(d))

# 2. start on AC
d, pf, p = runner("ac", 3, "1 90")
p.wait(120)
log = rlog(d)
ok("AC start: keep awake on", "keep awake: on (AC, start)" in log, log[-600:])
ok("AC start: DONE", state(d).get("state") == "DONE", state(d))

# 3. AC -> battery -> AC while the step runs
d, pf, p = runner("change", 25, "1 90")
ok("change: started on AC", wait_for(lambda: "keep awake: on (AC, start)" in rlog(d), 30), rlog(d)[-600:])
pf.write_text("0 55", encoding="utf-8")
ok("change: battery -> keep awake off",
   wait_for(lambda: "keep awake: off (battery, power change)" in rlog(d), 30), rlog(d)[-600:])
pf.write_text("1 56", encoding="utf-8")
ok("change: AC again -> keep awake on",
   wait_for(lambda: "keep awake: on (AC, power change)" in rlog(d), 30), rlog(d)[-600:])
p.wait(120)
log = rlog(d)
ok("change: power changes logged once each", log.count("power change") == 2, log[-800:])
ok("change: on battery alert logged", "power: on battery (55%)" in log and "power: charger connected (56%)" in log,
   log[-800:])
ok("change: DONE", state(d).get("state") == "DONE", state(d))

# 4. helpers
pf = T / "p.txt"
pf.write_text("0 12", encoding="utf-8")
os.environ["DF_OPS_FAKE_POWER_FILE"] = str(pf)
ok("power() reads the fake file", common.power() == (False, 12), common.power())
pf.write_text("garbage", encoding="utf-8")
ok("power() unreadable fake file -> unknown", common.power() == (None, None), common.power())
os.environ.pop("DF_OPS_FAKE_POWER_FILE")
ok("keep_awake(False) clears the request (call succeeds)", common.keep_awake(False))

bad = [n for n, x in RESULTS if not x]
print(f"\n{len(RESULTS) - len(bad)} passed, {len(bad)} failed" + (f": {bad}" if bad else ""))
if not bad:
    shutil.rmtree(T, ignore_errors=True)  # kept on failure for the diagnosis
sys.exit(1 if bad else 0)
