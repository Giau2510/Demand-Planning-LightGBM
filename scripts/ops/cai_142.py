"""1.4.2 chain (owner 04/11/2026: "LAM TRONG HOM NAY", run through the runner). Steps of
reports\\release-1.4.2-20261104\\plan.json; every step is resumable (a second run continues or redoes without harm).
Output json files in OUT.
  ohbackfill  (installed 1.4.0 / 1.4.1) sel2-openhours-backfill of the last 7 days (yesterday - 6 .. yesterday) with the
              installed code; open_hours_daily rows per day before / after (mode=ro), data-check -> ohbackfill.json
  release     scripts\\release.ps1 of the worktree ban-142 (ops_config.worktree; branch github/1.4.2: clean commit -> full QA -> package)
  backup      online backup with the INSTALLED 1.4.1 code (e1_backup.py, reason pre-1.4.2) + models\\sel2 in a second
              zip (1.4.1 backups hold only the top-level model files) -> backup.json, backup_sel2.json
  restore     restore test of that backup (e1_restore.py) + the models\\sel2 zip extracted and compared (SHA-256) -> restore.json
  deploy      as cai_141 (pre_deploy.json, hold flag, deploy-upgrade.ps1 -CheckOnly then -ConfirmToken UPGRADE-1.4.2)
  postcheck   health 1.4.2, schedule byte-identical, storage.json + forecast_source_config unchanged, data-check; the
              installed SEL2 daily refresh holds the open-hours read (open_hours_read called in refresh) -> postcheck.json
  export      (owner 05/11) the 04/11 AND 05/11 Excel written again with 1.4.2, every row checked against the rule
              -> export-<day>\\export.json
  nojobs      precondition of deploy (owner 05/11 "cai ngay"): exit 0 when production has no PENDING / RUNNING /
              RETRY_WAIT job, else 1
  sel2backup  backup.backup_database of the INSTALLED 1.4.2 into a temporary folder: models/sel2 members = live files
              (SHA-256); the temporary zip is deleted -> sel2backup.json
  verifyoh    05/11 morning: the day's FORECAST_REFRESH (SEL2) read the open hours (result open_hours without error) and
              open_hours_daily reaches yesterday; exit 3 (retry) while the job is not finished -> verifyoh.json
Every step except nojobs first checks the operations lock (runner\\common.ops_lock_block): exit 3 when another session
holds <project root>\\run\\OPS_LOCK (retried only by steps that list 3 in temporary_exit_codes; the others stop
FAILED: fail-safe).
usage: cai_142.py <step>"""
import hashlib
import json
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cai_141 as base  # noqa: E402  (helpers: health, current, run, sha_file, live, config_snapshot, data_check)
from common import ops_lock_block  # noqa: E402  (scripts\ops\runner is on sys.path through cai_141)
import ops_config  # noqa: E402

VERSION = "1.4.2"
BAN = ops_config.worktree("ban-142")
OPS = base.OPS
OUT = ops_config.REPORTS / "release-1.4.2-20261104"
TMP = ops_config.TMP / "bk142"
RUN_NAME = "CAI-142-20261104"       # the operations lock must be free or name this run
EXPORT_DAYS = ("2026-11-04", "2026-11-05")
OUT.mkdir(parents=True, exist_ok=True)
base.OUT = OUT                      # save / load / run of cai_141 write into this folder
base.VERSION = VERSION
base.BAN = BAN
notify = base.notify
save, load, health, current, run, sha_file, live = base.save, base.load, base.health, base.current, base.run, \
    base.sha_file, base.live


def today_vn():
    return date.fromisoformat(time.strftime("%Y-%m-%d"))     # the PC runs in Vietnam time


def oh_counts(c, start, end):
    return dict(c.execute("SELECT open_date, COUNT(*) FROM open_hours_daily WHERE open_date BETWEEN ? AND ? "
                          "GROUP BY open_date ORDER BY open_date", (str(start), str(end))))


def step_ohbackfill():
    v = current()
    # owner 04/11 19:50: no separate 1.4.1 install; the backfill command is the same code in 1.4.0 / 1.4.1 / 1.4.2
    if v not in ("1.4.0", "1.4.1", "1.4.2") or health().get("version") != v:
        print("the installed version is not running:", v, health())
        return 1
    inst = base.PROGS / v
    end = today_vn() - timedelta(days=1)
    start = end - timedelta(days=6)
    _, c = live()
    before = oh_counts(c, start - timedelta(days=7), end)
    reads_before = c.execute("SELECT COUNT(*) FROM aux_source_reads").fetchone()[0]
    c.close()
    py = [str(inst / "python" / "python.exe"), "-X", "utf8", "-m", "app.cli", "sel2-openhours-backfill",
          "--start", str(start), "--end", str(end)]
    run(py, inst / "backend", "ohbackfill.log", 600)                       # plan only (database path)
    rc = run(py + ["--yes"], inst / "backend", "ohbackfill.log", 3600)
    _, c = live()
    after = oh_counts(c, start - timedelta(days=7), end)
    last = c.execute("SELECT MAX(open_date) FROM open_hours_daily").fetchone()[0]
    reads = [dict(zip(("range_start", "range_end", "n_rows", "last_day", "source_modified", "completed_at"), r)) for r in
             c.execute("SELECT range_start, range_end, n_rows, last_day, source_modified, completed_at FROM "
                       "aux_source_reads ORDER BY completed_at DESC, rowid DESC LIMIT 3")]
    reads_after = c.execute("SELECT COUNT(*) FROM aux_source_reads").fetchone()[0]
    c.close()
    dc, bad = base.data_check(inst)
    new_days = [str(start + timedelta(days=i)) for i in range(7)]
    ref = sorted(after.get(d, 0) for d in after if d < str(start))
    med = ref[len(ref) // 2] if ref else 0
    low = [d for d in new_days if after.get(d, 0) < 0.8 * med]
    res = {"version": v, "start": str(start), "end": str(end), "exit": rc, "max_open_date": last,
           "rows_per_day_before": before, "rows_per_day_after": after, "median_7_days_before": med,
           "days_below_80pct_of_median": low, "aux_reads_added": reads_after - reads_before, "last_reads": reads,
           "data_check": dc["status"], "data_check_not_ok": bad}
    res["passed"] = rc == 0 and last == str(end) and not bad and all(after.get(d, 0) > 0 for d in new_days)
    save("ohbackfill.json", res)
    notify.send(f"1.4.2: gio mo ban {start}..{end} {'DAT' if res['passed'] else 'LOI'}",
                f"max open_date {last}; dong/ngay {[after.get(d, 0) for d in new_days]}; ngay < 80% trung vi: "
                f"{low or 'khong'}; data-check {dc['status']}", "default" if res["passed"] else "high")
    return 0 if res["passed"] else 1


def step_release():
    return base.step_release()


def step_backup():
    if not (OUT / "backup.json").exists():
        inst = base.PROGS / current()
        rc = subprocess.call([str(inst / "python" / "python.exe"), "-X", "utf8", str(OPS / "e1_backup.py"),
                              str(OUT / "backup.json"), "pre-1.4.2"], cwd=str(inst / "backend"), stdin=subprocess.DEVNULL)
        if rc != 0:
            return rc
    data, c = live()
    c.close()
    b = load("backup.json")
    src = data / "models" / "sel2"
    out = Path(b["backup"]).with_name(Path(b["backup"]).stem + "-models-sel2.zip")
    part = out.with_name(out.name + ".part")
    files = {f.relative_to(data / "models").as_posix(): sha_file(f) for f in sorted(src.rglob("*")) if f.is_file()}
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
        for n in files:
            z.write(data / "models" / n, "models/" + n)
    with zipfile.ZipFile(part) as z:
        bad = z.testzip()
    if bad is not None:
        part.unlink(missing_ok=True)
        print("sel2 zip verification failed", bad)
        return 1
    part.replace(out)
    save("backup_sel2.json", {"zip": str(out), "sha256": sha_file(out), "bytes": out.stat().st_size, "files": files})
    return 0


def step_restore():
    rc = subprocess.call([base.VENV, "-X", "utf8", str(OPS / "e1_restore.py"), str(OUT / "backup.json"),
                          str(OUT / "restore.json")], cwd=str(OPS), stdin=subprocess.DEVNULL)
    s = load("backup_sel2.json")
    rt = TMP / "rt_sel2"
    shutil.rmtree(rt, ignore_errors=True)
    rt.mkdir(parents=True)
    with zipfile.ZipFile(s["zip"]) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        assert all(n.startswith("models/sel2/") and ".." not in n.split("/") for n in names), "unsafe member"
        z.extractall(rt)
    got = {p.relative_to(rt / "models").as_posix(): sha_file(p) for p in (rt / "models").rglob("*") if p.is_file()}
    shutil.rmtree(rt, ignore_errors=True)
    ok = got == s["files"]
    res = load("restore.json")
    res.update(sel2_files=len(got), sel2_equal=ok)
    save("restore.json", res)
    return 0 if rc == 0 and ok else 1


def step_deploy():
    # owner 05/11: a real upgrade run that already finished without installing is never repeated automatically
    prev = load("deploy.json") if (OUT / "deploy.json").exists() else {}
    if "deploy_exit" in prev and not prev.get("installed") and current() != VERSION:
        print("a previous upgrade run ended without installing (deploy.json): no automatic second run", prev)
        return 1
    return base.step_deploy()


def step_postcheck():
    rc = base.step_postcheck()
    # owner 05/11: the installed daily SEL2 refresh reads the open hours itself (static check of the installed code; the
    # first real read is checked by verifyoh)
    src = (base.PROGS / VERSION / "backend" / "app" / "ml" / "sel2" / "jobs.py").read_text(encoding="utf-8")
    res = load("postcheck.json")
    res["daily_open_hours_read"] = "def open_hours_read(" in src and "oh = open_hours_read(d, scope)" in src
    res["passed"] = bool(res["passed"] and res["daily_open_hours_read"])
    save("postcheck.json", res)
    notify.send(f"1.4.2: kiem tra sau cai {'DAT' if res['passed'] else 'LOI'}",
                f"health {res['health'].get('version')}; lich trung {res['schedule_identical']}; storage.json "
                f"{res['storage_json_unchanged']}; data-check {res['data_check']} {res['data_check_not_ok'] or ''}; "
                f"tu doc gio mo ban {res['daily_open_hours_read']}", "default" if res["passed"] else "high")
    return 0 if rc == 0 and res["passed"] else 1


def step_export():
    # owner 04/11 19:50: the 1.4.1 rule ships in 1.4.2; owner 05/11: the 04/11 and 05/11 Excel are written again with
    # the installed 1.4.2 (sel2-export, no forecast run) and every DU_BAO row is checked against the rule
    # (cai_141.step_export, one output folder per day: a day already exported is only checked again)
    rcs = []
    for d in EXPORT_DAYS:
        base.DAY, base.OUT = d, OUT / f"export-{d.replace('-', '')}"
        base.OUT.mkdir(parents=True, exist_ok=True)
        rcs.append(base.step_export())
    base.OUT = OUT
    return 0 if not any(rcs) else 1


def step_nojobs():
    # also not in the 30 minutes before a D0 slot (saved schedule: every 2 h 08:00-18:00): deploy-upgrade.ps1 checks
    # for active jobs after storage-verify (about 20 min after its start)
    import urllib.request
    from datetime import datetime
    now = datetime.now()
    nxt = now.hour + 1 if now.minute >= 30 else None
    if nxt and nxt % 2 == 0 and 8 <= nxt <= 18:
        print(f"D0 slot {nxt:02d}:00 in less than 30 min")
        return 1
    # the scheduler creates the slot's job a little after the slot time (05/11: none yet at 10:00:17)
    if now.minute < 10 and now.hour % 2 == 0 and 8 <= now.hour <= 18:
        print(f"D0 slot {now.hour:02d}:00 started less than 10 min ago")
        return 1
    with urllib.request.urlopen(base.API + "/jobs?limit=50", timeout=30) as r:
        jobs = json.loads(r.read().decode("utf-8"))
    act = [f"{j.get('job_type')} {j.get('status')}" for j in jobs if j.get("status") in ("PENDING", "RUNNING", "RETRY_WAIT")]
    print("active jobs:", act or "none")
    return 1 if act else 0


SEL2CHECK = r'''
import hashlib, json, sys, zipfile
from pathlib import Path
from app import backup, paths
dest = Path(sys.argv[1]); dest.mkdir(parents=True, exist_ok=True)
out = backup.backup_database("check-1.4.2", dest_dir=dest)
live = {p.relative_to(paths.models_dir()).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths.models_dir().rglob("*") if p.is_file()}
with zipfile.ZipFile(out) as z:
    got = {n[len("models/"):]: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith("models/")}
    has_db = "db/app.db" in z.namelist()
size = out.stat().st_size
out.unlink()
print(json.dumps({"zip_bytes": size, "has_db": has_db, "live_model_files": len(live), "zip_model_files": len(got),
                  "sel2_live": sum(1 for n in live if n.startswith("sel2/")),
                  "sel2_zip": sum(1 for n in got if n.startswith("sel2/")),
                  "missing": sorted(set(live) - set(got))[:20],
                  "sha_mismatch": sorted(n for n in live if n in got and got[n] != live[n])[:20]}))
'''


def step_sel2backup():
    inst = base.PROGS / VERSION
    assert current() == VERSION, "1.4.2 is not installed"
    TMP.mkdir(parents=True, exist_ok=True)
    (TMP / "sel2check.py").write_text(SEL2CHECK, encoding="utf-8")
    p = subprocess.run([str(inst / "python" / "python.exe"), "-X", "utf8", str(TMP / "sel2check.py"), str(TMP / "zip")],
                       cwd=str(inst / "backend"), capture_output=True, text=True, encoding="utf-8",
                       stdin=subprocess.DEVNULL, timeout=3600)
    shutil.rmtree(TMP / "zip", ignore_errors=True)
    if p.returncode != 0:
        print(p.stderr[-3000:])
        return 1
    res = json.loads(p.stdout.strip().splitlines()[-1])
    res["passed"] = (res["has_db"] and res["sel2_zip"] == res["sel2_live"] > 0 and not res["missing"]
                     and not res["sha_mismatch"])
    save("sel2backup.json", res)
    notify.send(f"1.4.2: sao luu co models\\sel2 {'DAT' if res['passed'] else 'LOI'}",
                f"sel2 {res['sel2_zip']}/{res['sel2_live']} file, tong model {res['zip_model_files']}/"
                f"{res['live_model_files']}", "default" if res["passed"] else "high")
    return 0 if res["passed"] else 1


def step_verifyoh():
    # the first refresh STARTED AFTER the install (deploy.json written right after it) that reached the open-hours
    # read (the first attempts of a day are NOT_READY rows waiting for D-1: no read, open_hours absent / null)
    from datetime import datetime, timezone
    inst = datetime.fromtimestamp((OUT / "deploy.json").stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    _, c = live()
    rows = c.execute("SELECT id, status, reason_code, result_json, finished_at, idempotency_key FROM job_runs WHERE "
                     "job_type='FORECAST_REFRESH' AND started_at > ? AND status IN ('SUCCEEDED', 'FAILED') "
                     "ORDER BY created_at, rowid", (inst,)).fetchall()
    last = c.execute("SELECT MAX(open_date) FROM open_hours_daily").fetchone()[0]
    c.close()
    def res_of(x):          # job_runs.result_json = {"params", "result": {..., "open_hours"}} (1.4.x); older: flat
        o = json.loads(x[3] or "{}")
        return o["result"] if isinstance(o.get("result"), dict) else o
    j = next((x for x in rows if res_of(x).get("open_hours")), None)
    if j is None:
        print("no finished FORECAST_REFRESH with an open-hours read since the install", inst, "-", len(rows), "attempts")
        return 3
    r = res_of(j)
    oh = r.get("open_hours") or {}
    d = date.fromisoformat(r.get("business_date") or str(today_vn()))
    res = {"business_date": str(d), "job_id": j[0], "job_status": j[1], "reason_code": j[2], "finished_at": j[4],
           "result_status": r.get("status"), "open_hours": oh, "flags": r.get("flags"), "max_open_date": last}
    res["passed"] = bool(oh) and not oh.get("error") and last is not None and last >= str(d - timedelta(days=2))
    save("verifyoh.json", res)
    notify.send(f"1.4.2: lan chay {d} {'DA DOC' if res['passed'] else 'LOI DOC'} gio mo ban",
                f"job {j[1]} {r.get('status')}; doc {oh.get('mode')} {oh.get('start')}..{oh.get('end')} rows "
                f"{oh.get('rows')} {oh.get('skipped') or ''} {oh.get('error') or ''}; max open_date {last}",
                "default" if res["passed"] else "high")
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    lock = ops_lock_block(RUN_NAME)
    if lock and sys.argv[1] != "nojobs":
        print("waiting:", lock)
        sys.exit(3)
    sys.exit({"nojobs": step_nojobs, "ohbackfill": step_ohbackfill, "release": step_release, "backup": step_backup, "restore": step_restore,
              "deploy": step_deploy, "postcheck": step_postcheck, "export": step_export, "sel2backup": step_sel2backup,
              "verifyoh": step_verifyoh}[sys.argv[1]]())
