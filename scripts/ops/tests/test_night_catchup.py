"""fakes-only test of scripts/ops/night_catchup.py: fake app HTTP server on a random port, fake hold / lock / procs."""
import json, os, shutil, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ops_test_env import isolate  # noqa: E402

R = isolate("ops_nc_")
(R / "notify.json").write_text(json.dumps({"toast": False, "ntfy": False}), encoding="utf-8")
os.environ["DF_NOTIFY_CONFIG"] = str(R / "notify.json")
os.environ["DF_OPS_LOCK"] = str(R / "OPS_LOCK")
os.environ["DF_NC_FAKE_PROCS"] = str(R / "procs.json")
os.environ["DF_NC_WATCHDOG_TASK"] = "Ready"
(R / "procs.json").write_text("[]", encoding="utf-8")
import night_catchup as nc  # noqa: E402

DAY = "2026-11-06"
S = {}
POSTS = []


def reset():
    S.clear(); POSTS.clear()
    S.update(up=True, d1=[], ref=[], exp=[], active=[], cfg={"d1_enabled": True, "d1_signal_poll_start": "01:10",
             "refresh_enabled": True, "refresh_deadline": "12:00"}, running=True)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        p = self.path
        if p == "/api/health":
            return self.send(200, {"ok": True}) if S["up"] or (R / "started").exists() else self.send(503, {"ok": False})
        if p == "/api/scheduler/status": return self.send(200, {"running": S["running"], "config": S["cfg"]})
        if p.startswith("/api/jobs?job_type=D1_SYNC"): return self.send(200, S["d1"])
        if p.startswith("/api/jobs?job_type=FORECAST_REFRESH"): return self.send(200, S["ref"])
        if p.startswith("/api/jobs?status=RUNNING"): return self.send(200, S["active"])
        if p.startswith("/api/jobs?status=PENDING"): return self.send(200, [])
        if p == f"/api/sel2/export/{DAY}/runs": return self.send(200, {"forecast_date": DAY, "items": S["exp"]})
        self.send(404, {"code": "NF"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        POSTS.append((self.path, self.headers.get("X-DF-Client"), json.loads(self.rfile.read(n) or b"null")))
        self.send(200, {"id": f"JOB-{len(POSTS)}", "already_active": False, "status": "PENDING"})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}"
NET_UP, NET_DOWN = f"127.0.0.1:{srv.server_address[1]}", "127.0.0.1:1"
REMOTE, PROG = R / "remote", R / "prog"
(REMOTE / "run").mkdir(parents=True); (REMOTE / "config").mkdir()
(REMOTE / "config" / "link.json").write_text('{"hostname": "x"}', encoding="utf-8")
(PROG / "9.9.9" / "scripts").mkdir(parents=True)
(PROG / "current.txt").write_text("9.9.9\n", encoding="utf-8")
(PROG / "9.9.9" / "scripts" / "start.ps1").write_text(
    "param([switch]$NoBrowser)\r\nSet-Content -Path '%s' -Value $NoBrowser.IsPresent\r\nexit 0\r\n" % (R / "started"),
    encoding="ascii")
n_case = 0
STATE = None


def run(now, net=True):
    os.environ["DF_NC_NET"] = NET_UP if net else NET_DOWN
    return nc.main(["--base-url", URL, "--state-dir", str(STATE), "--remote-dir", str(REMOTE), "--programs", str(PROG),
                    "--now", f"{DAY} {now}"])


def notes():
    f = STATE / "night-catchup.log"
    return [l for l in f.read_text(encoding="utf-8").splitlines() if "NOTIFY" in l] if f.exists() else []


def case(name):
    global STATE, n_case
    n_case += 1; STATE = R / f"state{n_case}"; reset()
    for f in ("OPS_LOCK", "started"): (R / f).unlink(missing_ok=True)
    (REMOTE / "run" / "watchdog-hold").unlink(missing_ok=True)
    (R / "procs.json").write_text("[]", encoding="utf-8"); os.environ["DF_NC_WATCHDOG_TASK"] = "Ready"
    print(f"--- {name}")


def d1row(status, created="2026-11-05T18:10:00+00:00", key=f"D1_SYNC:{DAY}", jid="JOB-S", fin="2026-11-05T18:20:00+00:00",
          we="2026-11-05"):
    return {"id": jid, "idempotency_key": key, "status": status, "created_at": created, "started_at": created,
            "finished_at": fin, "reason_code": "BQ_ERROR" if status == "FAILED" else None,
            "result": {"params": {}, "result": {"status": "SUCCEEDED", "window_end": we}} if status == "SUCCEEDED" else None}


FAIL = 0


def check(cond, msg):
    global FAIL
    print(("PASS " if cond else "FAIL ") + msg); FAIL += 0 if cond else 1


case("1 scheduled D-1 FAILED, network up -> one manual D-1, never twice")
S["d1"] = [d1row("FAILED")]
run("07:00"); run("07:10")
check([p[0] for p in POSTS] == ["/api/schedules/d1/run"] and POSTS[0][1] == "web", f"one POST d1 with X-DF-Client {POSTS}")
check(any("Bat dau chay bu D-1" in l for l in notes()), "start notified")
S["d1"].append(d1row("FAILED", created="2026-11-06T00:00:00+00:00", key="D1_SYNC:MANUAL:x", jid="JOB-1"))
run("07:30"); run("07:40")
check(len(POSTS) == 1, "own D-1 failed -> no retry")
check(sum("Chay bu D-1 LOI" in l for l in notes()) == 1, "catch-up failure notified once")

case("2 network down -> wait, notified once; later network up -> trigger")
S["d1"] = [d1row("FAILED")]
run("07:00", net=False); run("07:10", net=False)
check(POSTS == [] and sum("cho chay bu" in l for l in notes()) == 1, "no POST, wait notified once")
run("07:20")
check(len(POSTS) == 1, "triggered once network up")

case("3 OPS_LOCK of another run / hold flag / install process / active job -> no trigger")
S["d1"] = [d1row("FAILED")]
(R / "OPS_LOCK").write_text(json.dumps({"session": "x", "job": "cai", "run": "CAI-143"}), encoding="utf-8")
run("07:00"); check(POSTS == [], "OPS_LOCK blocks")
(R / "OPS_LOCK").write_text(json.dumps({"session": "x", "run": "NIGHT-CATCHUP"}), encoding="utf-8")
(REMOTE / "run" / "watchdog-hold").write_text("deploy", encoding="utf-8")
run("07:10"); check(POSTS == [], "hold flag blocks")
(REMOTE / "run" / "watchdog-hold").unlink()
(R / "procs.json").write_text(json.dumps(["python cai_143.py deploy"]), encoding="utf-8")
run("07:20"); check(POSTS == [], "install step process blocks")
(R / "procs.json").write_text("[]", encoding="utf-8")
S["active"] = [{"job_type": "CANDIDATE_TRAIN", "status": "RUNNING"}]
run("07:30"); check(POSTS == [], "active job blocks")
S["active"] = []
run("07:40"); check(len(POSTS) == 1, "own-run OPS_LOCK allows")

case("4 after own D-1: refresh fallback, export fallback, done")
S["d1"] = [d1row("FAILED")]
run("07:00")
S["d1"].append(d1row("SUCCEEDED", created="2026-11-06T00:00:00+00:00", key="D1_SYNC:MANUAL:x", jid="JOB-1",
                     fin="2026-11-06T00:10:00+00:00"))
run("07:20"); check(len(POSTS) == 1, "no refresh fallback before 20 min")
run("07:31"); check([p[0] for p in POSTS][1:] == ["/api/schedules/refresh/run"], f"refresh fallback {POSTS[1:]}")
run("07:41"); check(len(POSTS) == 2, "refresh fallback once")
S["ref"] = [{"id": "JOB-2", "status": "SUCCEEDED", "created_at": "2026-11-06T00:31:00+00:00",
             "finished_at": "2026-11-06T00:50:00+00:00"}]
S["exp"] = [{"version": 1, "refresh_run_id": None, "is_stale": 1, "created_at": "2026-11-05T23:30:00+00:00"}]
run("08:00"); check(len(POSTS) == 2, "no export fallback before 20 min")
run("08:11"); check(POSTS[-1] == ("/api/sel2/export", "web", {"date": DAY, "confirm": True}), f"export fallback {POSTS[-1]}")
run("08:21"); check(len(POSTS) == 3, "export once")
S["exp"].insert(0, {"version": 2, "refresh_run_id": "R1", "is_stale": 0, "created_at": "2026-11-06T01:15:00+00:00"})
run("08:31"); run("08:41")
check(sum("Xong chay bu" in l for l in notes()) == 1 and len(POSTS) == 3, "done notified once, no more POST")

case("5 FAILED found after 12:00 -> no trigger, notified")
S["d1"] = [d1row("FAILED")]
run("12:30"); run("12:40")
check(POSTS == [] and sum("D-1 loi" in l for l in notes()) == 1, "no POST after deadline, notified once")

case("6 app ran D-1 late by itself (PC asleep) -> only reported, scheduler refresh/export, done")
S["d1"] = [d1row("SUCCEEDED", created="2026-11-06T00:05:00+00:00", fin="2026-11-06T00:20:00+00:00")]
run("07:30"); run("08:30")
check(POSTS == [] and sum("App chay bu D-1" in l for l in notes()) == 1, "late D-1 reported once, no POST")
S["exp"] = [{"version": 1, "refresh_run_id": "R1", "is_stale": 0, "created_at": "2026-11-06T01:15:00+00:00"}]
run("08:40"); check(sum("Xong chay bu" in l for l in notes()) == 1 and POSTS == [], "done notified, no POST")

case("7 normal night: D-1 on time, nothing to do; before poll start: nothing; D-1 flow off: nothing")
S["d1"] = [d1row("SUCCEEDED", created="2026-11-05T18:10:00+00:00")]
run("00:30"); run("07:00"); S["cfg"]["d1_enabled"] = False; S["d1"] = [d1row("FAILED")]; run("07:10")
check(POSTS == [] and notes() == [], "no POST, no notification")

case("8 RETRY_WAIT (scheduler retrying) -> wait")
S["d1"] = [d1row("RETRY_WAIT")]
run("07:00"); check(POSTS == [] and notes() == [], "no POST while the scheduler retries")

case("9 app down: watchdog active -> no start; watchdog disabled -> start once")
S["up"] = False
run("20:00"); run("20:10")
check(not (R / "started").exists() and sum("App khong chay" in l for l in notes()) == 1, "left to watchdog, notified once")
os.environ["DF_NC_WATCHDOG_TASK"] = "Disabled"
(R / "procs.json").write_text(json.dumps(["python -m app.cli serve --port 8765"]), encoding="utf-8")
run("20:20"); check(not (R / "started").exists(), "serve process exists -> not started")
(R / "procs.json").write_text("[]", encoding="utf-8")
run("20:30"); check((R / "started").exists() and (R / "started").read_text().strip() == "True", "started with -NoBrowser")
check(any("Da khoi dong app" in l for l in notes()), "start notified")
run("20:40"); check(sum("App chay lai" in l for l in notes()) == 1, "back-up notified")

case("9b hold flag during install -> no start, exactly one notification (owner-approved)")
S["up"] = False; os.environ["DF_NC_WATCHDOG_TASK"] = "Disabled"
(REMOTE / "run" / "watchdog-hold").write_text("deploy", encoding="utf-8")
run("20:00"); run("20:10"); run("20:20")
check(not (R / "started").exists() and sum("App khong chay" in l for l in notes()) == 1 and len(notes()) == 1,
      "no start, exactly one notification during install")

case("9c start limit: started app still down -> at most every 30 min")
S["up"] = False; os.environ["DF_NC_WATCHDOG_TASK"] = "Disabled"
(PROG / "9.9.9" / "scripts" / "start.ps1").write_text("param([switch]$NoBrowser)\r\nexit 0\r\n", encoding="ascii")
for t in ("20:00", "20:10", "20:20", "20:30", "20:40", "20:50"):
    run(t)
check(sum("Khoi dong app LOI" in l for l in notes()) == 2, "2 starts in 50 min (20:10, 20:40)")
srv.shutdown()
print("FAILED CHECKS:", FAIL)
if not FAIL:
    shutil.rmtree(R, ignore_errors=True)  # kept on failure for the diagnosis
sys.exit(1 if FAIL else 0)
