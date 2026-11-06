"""OPS-RES-A isolated tests (temporary folder, ops_test_env). Never touches production: temp run dirs, temp OPS_LOCK, fake ntfy server
on localhost, toast off, cai_143 helpers patched (no real deploy / backup / health / rollback)."""
import datetime as dt
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from ops_test_env import OPS, isolate  # noqa: E402

T = isolate("ops_resA_")
PY = sys.executable
RESULTS = []


def ok(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


# ------------------------------------------------------------------ fake ntfy
POSTS, NTFY_UP = [], [True]


class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
        if not NTFY_UP[0]:
            self.send_response(503)
            self.end_headers()
            return
        POSTS.append({"path": self.path, "title": self.headers.get("Title"), "priority": self.headers.get("Priority"),
                      "body": body})
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
CFG = T / "notify" / "notify_config.json"
CFG.parent.mkdir()
TOPIC = "resa-test-topic-x9"
CFG.write_text(json.dumps({"ntfy_server": f"http://127.0.0.1:{srv.server_address[1]}", "toast": False, "ntfy": True,
                           "ntfy_topic": TOPIC}), encoding="utf-8")
QUEUE = CFG.with_name("notify_queue.json")
os.environ["DF_NOTIFY_CONFIG"] = str(CFG)
os.environ["DF_OPS_LOCK"] = str(T / "OPS_LOCK_absent")
os.environ.pop("RUNNER_CLOCK_OFFSET_S", None)
sys.path.insert(0, str(OPS / "runner"))
sys.path.insert(0, str(OPS))
import common  # noqa: E402
import notify  # noqa: E402

assert notify.CONFIG == CFG and notify.QUEUE == QUEUE

# ------------------------------------------------------------------ 1. notify queue + single summary
log = T / "notify.log"
NTFY_UP[0] = False
for i in range(3):
    r = notify.send(f"T{i} title", f"text {i}", "high" if i == 1 else "default", log)
q = json.loads(QUEUE.read_text(encoding="utf-8"))["items"] if QUEUE.exists() else []
ok("queue: 3 failed sends queued", len(q) == 3 and r == {"ntfy": False}, q)
notify.send("not queued", "x", "default", log, queue=False)
ok("queue: queue=False not queued", len(json.loads(QUEUE.read_text(encoding="utf-8"))["items"]) == 3)
ok("flush offline keeps the queue", notify.flush_queue(log) == -1 and QUEUE.exists())
NTFY_UP[0] = True
n0 = len(POSTS)
r = notify.send("back online", "msg", "default", log)
new = POSTS[n0:]
ok("online send ok + exactly one summary after it", r == {"ntfy": True} and len(new) == 2
   and new[1]["body"].startswith("3 tin bi hoan khi mat mang:") and new[1]["body"].count("\n") == 3
   and new[1]["priority"] == "high", new)
ok("queue cleared", not QUEUE.exists())
ok("flush with no queue = 0, no post", notify.flush_queue(log) == 0 and len(POSTS) == n0 + 2)
NTFY_UP[0] = False
for i in range(80):
    notify.send("X" * 100 + f" {i}", "t", "default", log)
NTFY_UP[0] = True
n0 = len(POSTS)
k = notify.flush_queue(log)
ok("flush call: 80 queued -> one summary <= 1000 chars, truncated marker", k == 80 and len(POSTS) == n0 + 1
   and len(POSTS[-1]["body"]) <= 1000 and "... (+" in POSTS[-1]["body"], (k, len(POSTS[-1]["body"])))
ok("topic never in the log", TOPIC not in log.read_text(encoding="utf-8"))

# watchdog flushes each check (run dir without status.json: it exits after the flush)
NTFY_UP[0] = False
notify.send("wd queued", "t", "default", log)
NTFY_UP[0] = True
n0 = len(POSTS)
wd_run = T / "wd_run"
wd_run.mkdir()
rc = subprocess.call([PY, str(OPS / "runner" / "watchdog.py"), "--run-dir", str(wd_run), "--no-prod"], env=os.environ)
ok("watchdog check flushes the queue", rc == 0 and len(POSTS) == n0 + 1 and not QUEUE.exists()
   and POSTS[-1]["body"].startswith("1 tin bi hoan"), (rc, POSTS[n0:]))

# fix1 #6: queue lock busy -> flush does nothing; enqueue writes a side file; merged at the next flush
QL = CFG.with_name("notify_queue.lock")
NTFY_UP[0] = False
notify.send("main q", "t", "default", log)
QL.write_text("held")
n0 = len(POSTS)
NTFY_UP[0] = True
ok("flush with the lock held -> -1, nothing sent, queue kept", notify.flush_queue(log) == -1 and len(POSTS) == n0
   and QUEUE.exists())
NTFY_UP[0] = False
notify.send("side q", "t", "high", log)
side = list(CFG.parent.glob("notify_queue.*.json"))
ok("enqueue with the lock held -> side file, main queue untouched", len(side) == 1 and
   len(json.loads(QUEUE.read_text(encoding="utf-8"))["items"]) == 1)
QL.unlink()
NTFY_UP[0] = True
n0 = len(POSTS)
k = notify.flush_queue(log)
ok("next flush merges queue + side file in ONE summary, all cleared", k == 2 and len(POSTS) == n0 + 1
   and "main q" in POSTS[-1]["body"] and "side q" in POSTS[-1]["body"] and not notify.queued(), POSTS[n0:])
NTFY_UP[0] = False
notify.send("stale", "t", "default", log)
QL.write_text("old")
os.utime(QL, (time.time() - 120, time.time() - 120))
NTFY_UP[0] = True
ok("stale lock (> 60 s) is taken over", notify.flush_queue(log) == 1 and not QL.exists() and not notify.queued())

# ------------------------------------------------------------------ 2. network check
os.environ["DF_NET_CHECK_OVERRIDE"] = "down"
ok("net_up override down", common.net_up() is False)
os.environ["DF_NET_CHECK_OVERRIDE"] = "up"
ok("net_up override up", common.net_up() is True)
os.environ.pop("DF_NET_CHECK_OVERRIDE")
t0 = time.time()
real = common.net_up()
ok("net_up real check returns a bool within ~10 s", isinstance(real, bool) and time.time() - t0 < 12, (real, time.time() - t0))


# ------------------------------------------------------------------ runner helpers
def hm(t):
    return t.strftime("%H:%M")


def runner(name, steps, env=None, plan_extra=None):
    d = T / name
    d.mkdir()
    plan = {"name": f"RESA-TEST-{name}", "notify_title": "RESA test", "notify_channels": ["ntfy"], "status_every_s": 1,
            "defaults": {"min_free_commit_mb": 0, "stop_free_commit_mb": 0, "poll_s": 1, "wait_poll_s": 1,
                         "retries": 0, "eta_minutes": 1,
                         # no default blocked windows (23:45-00:15 / 00:45-03:00): a run at night must not wait;
                         # the window tests (3, 5) set their own windows on the step
                         "blocked_windows": []},
            "steps": steps, **(plan_extra or {})}
    (d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    e = {**os.environ, **(env or {})}
    p = subprocess.Popen([PY, str(OPS / "runner" / "runner.py"), "--plan", str(d / "plan.json"), "--run-dir",
                          str(d / "run")], env=e, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    return d, p


def wait_for(cond, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.5)
    return False


def rlog(d):
    f = d / "run" / "runner.log"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def rstate(d):
    return common.read_json(d / "run" / "state.json")


SLEEP = f"import time; time.sleep(%d)"

# ------------------------------------------------------------------ 3. gap detection + windows at resume + queue flush
off = T / "offset.txt"
off.write_text("0", encoding="utf-8")
now = dt.datetime.now()
win = [hm(now + dt.timedelta(minutes=30)), hm(now + dt.timedelta(minutes=90))]
NTFY_UP[0] = False
notify.send("pre-run queued", "t", "default", log)
NTFY_UP[0] = True
n0 = len(POSTS)
d, p = runner("gap", [{"id": "s1", "title": "sleep step", "command": [PY, "-c", SLEEP % 8],
                       "blocked_windows": [win]}],
              env={"RUNNER_CLOCK_OFFSET_FILE": str(off)}, plan_extra={"notify_all": True})
ok("runner tick flushes the queue (one summary)",
   wait_for(lambda: any(x["body"].startswith("1 tin bi hoan") for x in POSTS[n0:]), 20) and not QUEUE.exists())
ok("step running", wait_for(lambda: "s1: start attempt 1" in rlog(d), 20), rlog(d))
off.write_text("3600", encoding="utf-8")  # the PC "slept" one hour: now inside the blocked window
ok("gap logged 'resumed after sleep (gap 60 min)'", wait_for(lambda: "resumed after sleep (gap 60 min)" in rlog(d), 15),
   rlog(d)[-800:])
ok("window evaluated with the clock at resume: step killed", wait_for(lambda: "s1: killed (window" in rlog(d), 15))
ok("resume notified (notify_all)", any("TIEP TUC SAU KHI NGU" in (x["title"] or "") or "may thuc lai" in x["body"]
                                      for x in POSTS[n0:]))
ok("waiting in the window", wait_for(lambda: rstate(d).get("state") == "WAITING" and "window" in rstate(d).get("reason", ""), 10))
off.write_text("0", encoding="utf-8")  # back outside the window
ok("runs again from checkpoint and finishes", wait_for(lambda: p.poll() is not None, 40) and rstate(d).get("state") == "DONE"
   and rstate(d)["steps"]["s1"]["attempts"] == 2, rstate(d))

# ------------------------------------------------------------------ 4. sleep during a precondition wait not counted
off2 = T / "offset2.txt"
off2.write_text("0", encoding="utf-8")
d, p = runner("prewait", [{"id": "s1", "command": [PY, "-c", "pass"], "precondition": {"expr": "exists('go.txt')"},
                           "precondition_wait_minutes": 0.5}],
              env={"RUNNER_CLOCK_OFFSET_FILE": str(off2)})
ok("precondition waiting", wait_for(lambda: "precondition not met" in rstate(d).get("reason", ""), 15))
off2.write_text("7200", encoding="utf-8")
ok("gap during precondition wait detected", wait_for(lambda: "resumed after sleep (gap 120 min)" in rlog(d), 15))
time.sleep(3)
ok("2 h asleep not counted (not FAILED)", rstate(d).get("state") == "WAITING", rstate(d))
(d / "run" / "go.txt").write_text("x")
ok("precondition met -> DONE", wait_for(lambda: p.poll() is not None, 20) and rstate(d).get("state") == "DONE", rstate(d))

# fix1 #5: a sleep INSIDE a precondition command counts at most wait_poll_s + 60 s
off3 = T / "offset3.txt"
off3.write_text("0", encoding="utf-8")
cnt = T / "pre_count.txt"
pre = T / "pre.py"
pre.write_text(f"""import sys
from pathlib import Path
c = Path(r"{cnt}"); n = int(c.read_text()) + 1 if c.exists() else 1; c.write_text(str(n))
if n == 2:
    o = Path(r"{off3}"); o.write_text(str(float(o.read_text()) + 7200))  # the PC slept 2 h inside this command
sys.exit(0 if Path(r"{T / 'go_cap.txt'}").exists() else 1)
""", encoding="utf-8")
d, p = runner("precap", [{"id": "s1", "command": [PY, "-c", "pass"], "precondition": {"command": [PY, str(pre)]},
                          "precondition_wait_minutes": 2}], env={"RUNNER_CLOCK_OFFSET_FILE": str(off3)})
ok("precondition command ran twice (2 h jump inside it)", wait_for(lambda: cnt.exists() and int(cnt.read_text()) >= 3, 30))
time.sleep(2)
ok("2 h inside the command not counted: still WAITING", p.poll() is None and rstate(d).get("state") == "WAITING", rstate(d))
(T / "go_cap.txt").write_text("x")
ok("then DONE", wait_for(lambda: p.poll() is not None, 20) and rstate(d).get("state") == "DONE", rstate(d))

# ------------------------------------------------------------------ 5. blocked windows by RUNNER_CLOCK_OFFSET_S
now = dt.datetime.now()
target = now.replace(hour=23, minute=50, second=0, microsecond=0)
offs = (target - now).total_seconds()
d, p = runner("win2350", [{"id": "s1", "command": [PY, "-c", "pass"],
                           "blocked_windows": [["23:45", "00:15"], ["00:45", "03:45"]]}],
              env={"RUNNER_CLOCK_OFFSET_S": str(offs)})
ok("23:50 (offset clock) -> waiting window 23:45-00:15",
   wait_for(lambda: rstate(d).get("reason") == "window 23:45-00:15", 15), rstate(d))
subprocess.call(["taskkill", "/PID", str(p.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
target = now.replace(hour=3, minute=50, second=0, microsecond=0)
d, p = runner("win0350", [{"id": "s1", "command": [PY, "-c", "pass"],
                           "blocked_windows": [["23:45", "00:15"], ["00:45", "03:45"]]}],
              env={"RUNNER_CLOCK_OFFSET_S": str((target - now).total_seconds())})
ok("03:50 -> runs (window 00:45-03:45 over)", wait_for(lambda: p.poll() is not None, 20)
   and rstate(d).get("state") == "DONE", rstate(d))

# ------------------------------------------------------------------ 6. needs_network wait + resume
plan_steps = [{"id": "local", "command": [PY, "-c", "pass"]},
              {"id": "net", "command": [PY, "-c", "pass"], "needs_network": True, "precondition": {"expr": "True"},
               "precondition_wait_minutes": 0.01}]
d, p = runner("net", plan_steps, env={"DF_NET_CHECK_OVERRIDE": "down"})
ok("offline: step without the flag runs", wait_for(lambda: rstate(d).get("steps", {}).get("local", {}).get("status") == "DONE", 15))
ok("offline: needs_network step WAITING 'cho mang'",
   wait_for(lambda: rstate(d).get("reason") == "cho mang / waiting for network", 15), rstate(d))
time.sleep(3)
st_md = (d / "run" / "STATUS.md").read_text(encoding="utf-8")
ok("not failed after > precondition_wait_minutes, STATUS.md shows it",
   p.poll() is None and rstate(d).get("state") == "WAITING" and "cho mang / waiting for network" in st_md, st_md)
subprocess.call(["taskkill", "/PID", str(p.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
p.wait()
e = {**os.environ, "DF_NET_CHECK_OVERRIDE": "up"}
p = subprocess.Popen([PY, str(OPS / "runner" / "runner.py"), "--plan", str(d / "plan.json"), "--run-dir", str(d / "run")],
                     env=e, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
ok("network back: resumes from checkpoint, local not run again, DONE",
   wait_for(lambda: p.poll() is not None, 20) and rstate(d).get("state") == "DONE"
   and rstate(d)["steps"]["local"]["attempts"] == 1 and rstate(d)["steps"]["net"]["attempts"] == 1, rstate(d))

# ------------------------------------------------------------------ 7. on_ac expression
ac = common.power()[0]
d, p = runner("onac", [{"id": "s1", "command": [PY, "-c", "pass"], "precondition": {"expr": "on_ac"},
                        "precondition_wait_minutes": 0.03}])
p.wait(timeout=30)
ok(f"on_ac expr (power now ac={ac})", rstate(d).get("state") == ("DONE" if ac else "FAILED"), rstate(d))
d, p = runner("onac2", [{"id": "s1", "command": [PY, "-c", "pass"], "precondition": {"expr": "on_ac == (not False)"},
                         "precondition_wait_minutes": 0.03}])
p.wait(timeout=30)
ok("on_ac usable in comparisons", rstate(d).get("state") == ("DONE" if ac else "FAILED"), rstate(d))

# ------------------------------------------------------------------ 8. cai_143 (all helpers patched; fake clock)
import re  # noqa: E402

import cai_143 as c  # noqa: E402

OUT = T / "out143"
OUT.mkdir()
c.OUT = c.base.OUT = OUT
c.BAN = T
HOLD = T / "hold" / "watchdog-hold"
c.base.HOLD = HOLD
c.progress_time = lambda: time.time()          # never reads storage.json / the data logs in tests

# fix1 #1: the REAL process query (read-only Get-CimInstance)
ok("install_procs real query, dummy token -> [] (own query excluded)",
   c.install_procs(patterns=(r"-File\s+\S*zz-dummy-token-zz\.ps1",)) == [])
ok("install_procs real query, token that is in the query text itself -> []",
   c.install_procs(patterns=(r"Get-CimInstance Win32_Process",)) == [])
probe = T / "zz-resa-probe.ps1"
probe.write_text("Start-Sleep -Seconds 25\n", encoding="ascii")
pp = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(probe)])
time.sleep(3)
hit = c.install_procs(patterns=(r"-File\s+(?:\"[^\"]*[\\/]|[^\s\"]*[\\/])?zz-resa-probe\.ps1\b",))
ok("install_procs real query finds a real -File script (quoted path with a space)", [x[0] for x in hit] == [pp.pid], hit)
pp.kill()
pp.wait()
live_now = c.install_procs()
print(f"INFO install_procs() default patterns on this PC now: {len(live_now)} process(es) "
      f"{[re.sub(r'-Package.*', '-Package ...', x[1])[:120] for x in live_now]}")
rx = [re.compile(x, re.I) for x in c.INSTALL_PROC_RE]
samples = {r"powershell -NoProfile -ExecutionPolicy Bypass -File X:\work\ban-143\scripts\deploy-upgrade.ps1 -Package x": True,
           r'"powershell.exe" -File "C:\Users\Some One\AppData\Local\Programs\DemandForecast\1.4.3\scripts\install.ps1" -X': True,
           r"powershell -NoProfile -Command Get-CimInstance | ? { $_.CommandLine -like '*deploy-upgrade.ps1*' }": False,
           r"notepad D:\x\deploy-upgrade.ps1": False,
           r"C:\p\python.exe -X utf8 -m app.cli migrate": True,
           r'python.exe -m "app.cli" check-env': True,
           r"python.exe -m app.cli serve --port 8765": False,
           r"python.exe -m app.cli backup-list": False}
ok("install pattern samples", all(any(x.search(k) for x in rx) == v for k, v in samples.items()),
   {k: any(x.search(k) for x in rx) for k in samples})

CALLS = {}
APP = {"version": "1.4.2", "current": "1.4.2"}
CLOCK = [0.0]
real_sleep, real_time = time.sleep, time.time
c.health = lambda: {"ok": True, "version": APP["version"]}
c.current = lambda: APP["current"]
c.tell = lambda title, text, ok_=True: CALLS.setdefault("tell", []).append(title)
c.back_to_prev = lambda why: CALLS.setdefault("order", []).append("back") or CALLS.setdefault("back", []).append(why) \
    or {"ok": True, "version": "1.4.2"}
PROCS = []  # successive install_procs() answers (empty -> [])
c.install_procs = lambda patterns=None: (CALLS.setdefault("order", []).append(f"procs:{len(PROCS)}"),
                                         CALLS.setdefault("hold_seen", []).append(HOLD.exists()),
                                         PROCS.pop(0) if PROCS else [])[2]
c.alive = lambda pid, created: False
c.not_ready = lambda now=None, windows=False: CALLS.setdefault("ready_marker", []).append(
    (OUT / "deploy_started.json").exists()) or None


def fsleep(s):
    CLOCK[0] += s
    CALLS["slept"] = CALLS.get("slept", 0) + s


c.time.sleep = fsleep
c.time.time = lambda: real_time() + CLOCK[0]


def fake_run_deploy(cmd):
    CALLS.setdefault("run", []).append(cmd)
    CALLS["marker_before_run"] = (OUT / "deploy_started.json").exists()
    with open(OUT / "deploy.log", "a", encoding="utf-8") as f:
        f.write(f"\n==== fake {cmd}\nbackup: skipped, verified backup\n")
    if CALLS.get("deploy_fails"):
        return 1
    APP.update(version="1.4.3", current="1.4.3")
    return 0


real_run_deploy = c.run_deploy
c.run_deploy = fake_run_deploy


def reset(**files):
    for f in OUT.iterdir():
        f.unlink()
    CALLS.clear()
    PROCS.clear()
    HOLD.unlink(missing_ok=True)
    APP.update(version="1.4.2", current="1.4.2")
    for k, v in files.items():
        (OUT / k.replace("__", ".")).write_text(v if isinstance(v, str) else json.dumps(v), encoding="utf-8")


def bname(hours_ago):
    return rf"X:\fake\backup-{(dt.datetime.now() - dt.timedelta(hours=hours_ago)):%Y%m%d-%H%M%S}-pre-143.zip"


base_files = {"release__json": {"zip": "X:/fake/pkg.zip", "sha256": "AB"}, "pre_deploy__json": {"version": "1.4.2"}}
MK = {"at": "x", "pid": 1, "created": 1}

# a) marker, no deploy.json, 1.4.3 healthy -> installed (interrupted), no second upgrade
reset(deploy_started__json=MK, **base_files)
APP.update(version="1.4.3", current="1.4.3")
rc = c.step_deploy()
dj = json.loads((OUT / "deploy.json").read_text(encoding="utf-8"))
ok("interrupted + 1.4.3 healthy -> 0, deploy.json installed/interrupted, no deploy-upgrade",
   rc == 0 and dj["installed"] and dj["interrupted"] and "run" not in CALLS and "back" not in CALLS, (rc, dj, CALLS))
# b) marker, 1.4.3 not healthy -> back_to_prev, 1; then a later run does nothing
reset(deploy_started__json=MK, **base_files)
rc = c.step_deploy()
dj = json.loads((OUT / "deploy.json").read_text(encoding="utf-8"))
ok("interrupted + not 1.4.3 -> back_to_prev, 1, no deploy-upgrade",
   rc == 1 and not dj["installed"] and CALLS.get("back") and "run" not in CALLS, (rc, dj, CALLS))
CALLS.clear()
rc = c.step_deploy()
ok("next run after a failed interrupted run: no second upgrade", rc == 1 and "run" not in CALLS and "back" not in CALLS)
# c) legacy deploy.log (code before the marker) without deploy.json -> interrupted path
reset(deploy__log="\n==== 2026-11-05 17:08:10 ['powershell', ..., 'D:\\\\x\\\\deploy-upgrade.ps1']\n", **base_files)
APP.update(version="1.4.3", current="1.4.3")
rc = c.step_deploy()
ok("legacy deploy.log without deploy.json -> interrupted path, no upgrade",
   rc == 0 and "run" not in CALLS and json.loads((OUT / "deploy.json").read_text(encoding="utf-8"))["interrupted"])
# d) + fix1 #2: earlier cai_143 alive, then install processes alive -> wait (no limit), hold kept while waiting,
#    removed after, then rollback decision
reset(deploy_started__json=MK, **base_files)
HOLD.parent.mkdir(parents=True, exist_ok=True)
HOLD.write_text("deploy", encoding="utf-8")
seq = iter([True, True, False, False, False])
c.alive = lambda pid, created: next(seq)
PROCS[:] = [[(11, "install.ps1")], [(11, "install.ps1")], [(11, "install.ps1")]]
rc = c.step_deploy()
c.alive = lambda pid, created: False
ok("earlier run / install alive -> waited, hold kept while waiting then removed, back_to_prev after, no upgrade",
   rc == 1 and "run" not in CALLS and CALLS.get("slept", 0) >= 90 and all(CALLS["hold_seen"][:3])
   and not HOLD.exists() and CALLS["order"][-1] == "back", CALLS)
# fix1 #4: no time limit + 2 h no-progress alert while waiting (nothing killed)
reset(deploy_started__json=MK, **base_files)
c.progress_time = lambda: 0.0
PROCS[:] = [[(11, "deploy-upgrade.ps1")]] * 600  # 600 x 30 s = 5 h still running
APP.update(version="1.4.3", current="1.4.3")
rc = c.step_deploy()
c.progress_time = lambda: time.time()
ok("install running 5 h: no limit, alerted every 2 h (2 alerts), then decided", rc == 0
   and CALLS.get("tell", []).count("CAI KHONG CO TIEN DO") == 2 and CALLS.get("slept", 0) >= 18000, CALLS.get("tell"))
# e) fresh backup -> no refresh, readiness checked before the marker, marker before deploy-upgrade, installed
reset(verified_backup__json={"backup": bname(1)}, **base_files)
rc = c.step_deploy()
dj = json.loads((OUT / "deploy.json").read_text(encoding="utf-8"))
ok("fresh backup (1 h): no refresh, ready checked BEFORE the marker, marker before deploy-upgrade, installed",
   rc == 0 and len(CALLS.get("run", [])) == 1 and CALLS["marker_before_run"] and dj["installed"]
   and CALLS.get("ready_marker") == [False] and not list(OUT.glob("*.expired-*")), (rc, CALLS, dj))
# fix1 #3: never ready -> waits 5 h (60 s re-checks) then exit 3, nothing started
c.not_ready = lambda now=None, windows=False: CALLS.__setitem__("ready_n", CALLS.get("ready_n", 0) + 1) or \
    ("not on AC power" if windows else "?")
reset(verified_backup__json={"backup": bname(1)}, **base_files)
rc = c.step_deploy()
ok("not ready 5 h (windows=True asked) -> exit 3, no marker, no deploy-upgrade, no hold",
   rc == 3 and "run" not in CALLS and not (OUT / "deploy_started.json").exists() and not HOLD.exists()
   and 290 <= CALLS.get("ready_n", 0) <= 302 and not (OUT / "deploy.json").exists(), CALLS.get("ready_n"))
# fix1 #4: deploy-upgrade failed + install process still alive -> rollback only after it ended
c.not_ready = lambda now=None, windows=False: None
reset(verified_backup__json={"backup": bname(1)}, **base_files)
CALLS["deploy_fails"] = True
PROCS[:] = [[(12, "install.ps1")], [(12, "install.ps1")]]
rc = c.step_deploy()
o = CALLS.get("order", [])
ok("failed deploy: back_to_prev only after no install process", rc == 1 and o[-1] == "back" and o[-2] == "procs:0"
   and o.count("procs:2") + o.count("procs:1") == 2, o)
# f) old backup -> moved aside, backup + restore again, wait ready, deploy with the new backup
NEW = bname(0)


def fake_backup():
    CALLS["backup"] = CALLS.get("backup", 0) + 1
    if CALLS["backup"] == 1:
        return 3  # written during the backup -> taken again
    (OUT / "backup.json").write_text(json.dumps({"backup": NEW}), encoding="utf-8")
    return 0


def fake_restore():
    CALLS["restore"] = CALLS.get("restore", 0) + 1
    (OUT / "restore.json").write_text("{}", encoding="utf-8")
    (OUT / "verified_backup.json").write_text(json.dumps({"backup": NEW}), encoding="utf-8")
    return 0


c.step_backup, c.step_restore = fake_backup, fake_restore
rq = iter(["D0 slot 10:00 in less than 30 min", None])
c.not_ready = lambda now=None, windows=False: next(rq)
reset(verified_backup__json={"backup": bname(6)}, backup__json={"backup": bname(6)}, restore__json={}, **base_files)
rc = c.step_deploy()
exp = sorted(x.name.split(".expired-")[0] for x in OUT.glob("*.expired-*.json"))
argv = CALLS.get("run", [[]])[0]
ok("old backup (6 h): 3 json moved aside, backup retried on exit 3, restore, waited ready, deployed with NEW backup",
   rc == 0 and exp == ["backup", "restore", "verified_backup"] and CALLS.get("backup") == 2 and CALLS.get("restore")
   and NEW in argv and CALLS.get("slept", 0) >= 360 and "SAO LUU LAI TRUOC KHI CAI" in CALLS.get("tell", []),
   (rc, exp, CALLS))
# fix1 #8: backup fresh before the wait, too old after it -> taken again, then deployed
real_age = c.backup_age_hours
c.backup_age_hours = lambda path, now=None: 0.1 if CALLS.get("restore") else (5.8 if CALLS.get("waited") else 5.0)
c.not_ready = lambda now=None, windows=False: CALLS.__setitem__("waited", True)
CALLS_B = None
reset(verified_backup__json={"backup": bname(5)}, **base_files)
rc = c.step_deploy()
ok("backup aged past 5.5 h during the wait -> backup + restore again, then deployed",
   rc == 0 and CALLS.get("restore") == 1 and CALLS.get("backup") == 2 and len(CALLS.get("run", [])) == 1, CALLS)
c.backup_age_hours = real_age
c.not_ready = lambda now=None, windows=False: None
# g) refresh fails -> no deploy, no marker
c.step_restore = lambda: 1
reset(verified_backup__json={"backup": bname(6)}, **base_files)
rc = c.step_deploy()
ok("refresh failed -> 1, no deploy-upgrade, no marker", rc == 1 and "run" not in CALLS
   and not (OUT / "deploy_started.json").exists() and not (OUT / "deploy.json").exists(), CALLS)
ok("backup_age_hours parses / None", abs(c.backup_age_hours(bname(2)) - 2) < 0.01 and c.backup_age_hours("x.zip") is None)

# fix1 #4: the real run_deploy: no time limit, alert without kill (fake command, cwd temp)
c.time.sleep, c.time.time = real_sleep, real_time
reset()
c.PROGRESS_ALERT_S = 1
c.progress_time = lambda: 0.0
t0 = time.time()
rc = real_run_deploy([PY, "-c", "import time; time.sleep(34); print('done')"])
ok("run_deploy: waits for the end (34 s, no kill), no-progress alert sent, exit 0",
   rc == 0 and time.time() - t0 >= 33 and "CAI KHONG CO TIEN DO" in CALLS.get("tell", [])
   and "done" in (OUT / "deploy.log").read_text(encoding="utf-8"), (rc, CALLS))
c.PROGRESS_ALERT_S = 7200

# i) not_ready / ready (power + jobs patched; real ready() logic)
import importlib  # noqa: E402
c2 = importlib.reload(c)  # fresh functions; paths patched again
c2.OUT = c2.base.OUT = OUT
c2.power = lambda: (False, 50)
c2.active_jobs = lambda: []
D = dt.datetime(2026, 11, 5)
ok("not_ready: battery", "AC" in (c2.not_ready(D.replace(hour=11)) or ""))
c2.power = lambda: (True, 100)
ok("not_ready: 09:35 -> D0 10:00 soon", "10:00 in less" in (c2.not_ready(D.replace(hour=9, minute=35)) or ""))
ok("not_ready: 10:05 -> D0 just started", "started less" in (c2.not_ready(D.replace(hour=10, minute=5)) or ""))
ok("not_ready: 19:35 (no slot 20) -> ready", c2.not_ready(D.replace(hour=19, minute=35)) is None)
ok("not_ready: 11:00 no jobs -> ready", c2.not_ready(D.replace(hour=11)) is None)
ok("not_ready: windows only when asked", c2.not_ready(D.replace(hour=23, minute=50)) is None
   and "blocked" in (c2.not_ready(D.replace(hour=23, minute=50), windows=True) or "")
   and "blocked" in (c2.not_ready(D.replace(hour=2), windows=True) or "")
   and "blocked" in (c2.not_ready(D.replace(hour=0, minute=5), windows=True) or "")
   and c2.not_ready(D.replace(hour=3, minute=50), windows=True) is None
   and c2.not_ready(D.replace(hour=0, minute=20), windows=True) is None)
c2.active_jobs = lambda: ["FORECAST_REFRESH RUNNING"]
ok("not_ready: active job", "active jobs" in (c2.not_ready(D.replace(hour=11)) or ""))


def boom():
    raise OSError("down")


c2.active_jobs = boom
ok("not_ready: API down -> not ready", "jobs API not read" in (c2.not_ready(D.replace(hour=11)) or ""))
c2.not_ready = lambda: None
r1 = c2.step_ready()
c2.not_ready = lambda: "x"
ok("step_ready exit codes", r1 == 0 and c2.step_ready() == 1)

# ------------------------------------------------------------------ 9. night_catchup fail-closed (fix1 #2, #7)
import argparse  # noqa: E402

import night_catchup as nc  # noqa: E402

NC = T / "nc"
(NC / "remote" / "run").mkdir(parents=True)
(NC / "remote" / "run" / "watchdog-hold").write_text("x")
(NC / "state").mkdir()
fp = NC / "procs.json"
fp.write_text("[]", encoding="utf-8")
os.environ["DF_NC_FAKE_PROCS"] = str(fp)
os.environ["DF_NC_WATCHDOG_TASK"] = "Ready"
args = ["--base-url", "http://127.0.0.1:1", "--state-dir", str(NC / "state"), "--remote-dir", str(NC / "remote"),
        "--programs", str(NC / "progs")]
n0 = len(POSTS)
nc.main(args)
nc.main(args)
nc.main(args)
msgs = [x for x in POSTS[n0:] if "App khong chay" in (x["title"] or "")]
ok("app down + watchdog-hold: notified ONCE with the reason, not started",
   len(msgs) == 1 and "watchdog-hold" in msgs[0]["body"] and "starts" not in common.read_json(NC / "state" / "app.json"),
   POSTS[n0:])
fp.write_text("null", encoding="utf-8")
ok("processes() unreadable -> None", nc.processes() is None)
nc.O = argparse.Namespace(now="2026-11-05 02:00", dry_run=False, base_url="http://127.0.0.1:1", state_dir=str(NC / "state"),
                          remote_dir=str(NC / "remote2"), programs=str(NC / "progs"))
nc.LOG = NC / "state" / "t.log"
nc.network_up = lambda: True
nc.jobs = lambda **q: None
b = nc.blockers(None)
ok("blockers: window 00:45-03:45, process list unknown, job list unknown",
   any("window 00:45-03:45" in x for x in b) and any("process list unknown" in x for x in b)
   and "job list unknown" in b, b)
nc.O.now = "2026-11-05 23:50"
ok("blockers: window 23:45-00:15", any("window 23:45-00:15" in x for x in nc.blockers([])))
nc.O.now = "2026-11-05 10:00"
nc.jobs = lambda **q: []
ok("blockers: none at 10:00 with readable lists", nc.blockers([]) == [], nc.blockers([]))
# refresh fallback (~line 360): refresh job list unreadable -> no POST
TRIG = []
nc.trigger = lambda path, body=None: TRIG.append(path) or {"path": path}
nc.blockers = lambda procs: []  # blockers tested above; here only the refresh job list
nc.tell = lambda *a, **k: None
t = nc.now()
day = t.date()
d1rows = [{"id": "J1", "status": "SUCCEEDED", "created_at": (t - dt.timedelta(hours=1)).isoformat(),
           "finished_at": (t - dt.timedelta(hours=1)).isoformat(), "result": {}, "idempotency_key": "x"}]
nc.api = lambda path, body=None, timeout=15: (200, {"items": []})
st = {"catchup": True, "d1_triggered": {"job_id": "J1", "at": "x"}}
nc.jobs = lambda **q: d1rows if q.get("job_type") == "D1_SYNC" else None
nc._catchup(t, day, {"refresh_enabled": True}, {}, t - dt.timedelta(hours=8), t + dt.timedelta(hours=2), st)
ok("refresh job list unreadable -> no POST", TRIG == [] and "refresh_triggered" not in st, TRIG)
nc.jobs = lambda **q: d1rows if q.get("job_type") == "D1_SYNC" else []
nc._catchup(t, day, {"refresh_enabled": True}, {}, t - dt.timedelta(hours=8), t + dt.timedelta(hours=2), st)
ok("refresh job list readable + empty -> one POST (sanity)", TRIG == ["/api/schedules/refresh/run"], TRIG)
os.environ.pop("DF_NC_FAKE_PROCS")
os.environ.pop("DF_NC_WATCHDOG_TASK")

srv.shutdown()
bad = [n for n, x in RESULTS if not x]
print(f"\n{len(RESULTS) - len(bad)} passed, {len(bad)} failed" + (f": {bad}" if bad else ""))
if not bad:
    shutil.rmtree(T, ignore_errors=True)  # kept on failure for the diagnosis
sys.exit(1 if bad else 0)
