"""1.4.3 chain (owner 05/11/2026: no handoff ZIP, no rehearsal on a DB copy; the safety net is a backup restore-tested
right before the install). Steps of reports\\release-1.4.3-20261105\\plan.json, every step resumable; outputs in OUT.
  release   scripts\\release.ps1 of the worktree ban-143 (ops_config.worktree; branch github/1.4.3: clean commit -> full QA -> package)
  backup    online backup of the live DB + models (models\\sel2 included) with the INSTALLED 1.4.2 code (e1_backup.py,
            reason pre-1.4.3; exit 3 = written during the backup -> retried) -> backup.json
  restore   restore test of that backup into <TMP>\\rt143 (deleted after): DB integrity, row counts = live counts
            taken with the backup, every model file (sub folders included) SHA-256 = live, training_runs model SHA;
            then the restore report for deploy-upgrade -RestoreReport (backup, sha256, db_path, schema_version, passed)
            -> restore.json, verified_backup.json
  deploy    pre_deploy.json (configuration snapshot + table counts, mode=ro); deploy-upgrade.ps1 of 1.4.3 with
            -VerifiedBackup / -RestoreReport and -ConfirmToken UPGRADE-1.4.3. On ANY failure: back to 1.4.2
            (rollback-version.ps1 -To 1.4.2; app not answering -> start.ps1 of 1.4.2), app health checked, notified
            (high); the DB is never restored automatically (schema unchanged by 1.4.3: not needed) -> deploy.json.
            (owner 05/11 evening) The verified backup older than 5.5 h (stamp of its name backup-YYYYMMDD-HHMMSS-*,
            PC local time = Vietnam) is taken + restore-tested again first (backup.json / restore.json /
            verified_backup.json moved to *.expired-<stamp>.json; no backup zip is deleted), without the owner. Right
            before the app is stopped the step waits until "ready" AND outside 23:45-00:15 / 00:45-03:45 (re-checked
            every 60 s, at most 5 h, then exit 3, nothing started); a backup that grew older than 5.5 h meanwhile is
            taken again. deploy-upgrade.ps1 runs WITHOUT a time limit (never killed in the middle; high alert when its
            logs do not change for 2 h). Before any rollback no install process may still run (deploy-upgrade /
            install.ps1, app.cli migrate / backup / check-env). deploy_started.json (time, pid) is written right before
            deploy-upgrade.ps1 starts: a later run that finds it without deploy.json (the earlier run died: sleep,
            restart) NEVER starts a second upgrade; it waits while the earlier run / an install process still runs,
            removes the watchdog-hold flag, then 1.4.3 healthy -> deploy.json installed (interrupted), else back to
            1.4.2, exit 1
  ready     precondition of deploy (no ops lock check): exit 0 when the PC is on AC power, production has no PENDING /
            RUNNING / RETRY_WAIT job and it is not 30 min before / 10 min after an even-hour D0 slot 08-18, else 1
  postcheck health 1.4.3, schedule + every settings section byte-identical, storage.json + forecast_source_config
            unchanged, no table lost rows (counts after >= before), installed export.py holds the fixed rule
            -> postcheck.json
  export    sel2-export --date 2026-11-05 --yes with the installed 1.4.3 (no forecast run), every DU_BAO row checked
            against the owner's fixed forecast_used rule (CLAUDE.md) -> export.json
Every step first checks the operations lock (runner\\common.ops_lock_block): exit 3 when another session holds it.
usage: cai_143.py <step>"""
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cai_141 as base  # noqa: E402  (helpers: health, current, run, sha_file, live, config_snapshot)
from common import NO_WINDOW, alive, ops_lock_block, power, proc_created  # noqa: E402
import ops_config  # noqa: E402

VERSION, PREV = "1.4.3", "1.4.2"
DAY = "2026-11-05"
BAN = ops_config.worktree("ban-143")
OPS = base.OPS
OUT = ops_config.REPORTS / "release-1.4.3-20261105"
RT = ops_config.TMP / "rt143"
RUN_NAME = "CAI-143-20261105"
OUT.mkdir(parents=True, exist_ok=True)
base.OUT, base.VERSION, base.BAN, base.DAY = OUT, VERSION, BAN, DAY
notify = base.notify
save, load, health, current, run, sha_file, live = base.save, base.load, base.health, base.current, base.run, \
    base.sha_file, base.live
TITLE = "[Phien 145cefda] Cai 1.4.3"
PS = base.PS
BACKUP_MAX_AGE_H = 5.5       # owner 05/11: an older verified backup is taken + restore-tested again before the install
MARKER = "deploy_started.json"
BLOCKED = (("23:45", "00:15"), ("00:45", "03:45"))
# install processes (matched in Python on the command line; the query's own process is excluded)
INSTALL_PROC_RE = (r"-File\s+(?:\"[^\"]*[\\/]|[^\s\"]*[\\/])?(?:deploy-upgrade|install)\.ps1\b",
                   r"app\.cli[\"']?\s+(?:migrate|backup|check-env)(?![\w-])")
PROGRESS_ALERT_S = 7200      # install logs unchanged this long -> high alert (again every 2 h), nothing is killed
READY_WAIT_S = 5 * 3600


def tell(title, text, ok=True):
    notify.send(f"{TITLE}: {title}", text, "default" if ok else "high")


def counts(c):
    return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}


def cli_paths(inst):
    out = subprocess.run([str(inst / "python" / "python.exe"), "-m", "app.cli", "paths"], cwd=str(inst / "backend"),
                         capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL).stdout
    return json.loads(out[out.find("{"):])


def step_release():
    return base.step_release()


def step_backup():
    if (OUT / "backup.json").exists() and Path(load("backup.json")["backup"]).exists():
        b = load("backup.json")
    else:
        inst = base.PROGS / current()
        rc = subprocess.call([str(inst / "python" / "python.exe"), "-X", "utf8", str(OPS / "e1_backup.py"),
                              str(OUT / "backup.json"), "pre-1.4.3"], cwd=str(inst / "backend"), stdin=subprocess.DEVNULL)
        if rc != 0:
            (OUT / "backup.json").unlink(missing_ok=True)       # a backup with writes during it is taken again
            return rc
        b = load("backup.json")
    with zipfile.ZipFile(b["backup"]) as z:
        names = z.namelist()
    sel2 = [n for n in names if n.startswith("models/sel2/") and not n.endswith("/")]
    data, c = live()
    c.close()
    # backup.backup_database skips .tmp / .lock files in sub folders (e.g. sel2/<scope>/train.lock): not compared
    live_sel2 = [p for p in (data / "models" / "sel2").rglob("*") if p.is_file() and p.suffix not in (".tmp", ".lock")]
    ok = "db/app.db" in names and len(sel2) == len(live_sel2) > 0
    tell(f"sao luu {'DAT' if ok else 'LOI'}", f"{Path(b['backup']).name}; models\\sel2 {len(sel2)}/{len(live_sel2)} file; "
         f"{round(b['seconds'] / 60)} phut", ok)
    return 0 if ok else 1


def step_restore():
    b = load("backup.json")
    inst = base.PROGS / current()
    if RT.exists():
        shutil.rmtree(RT)
    (RT / "data" / "db").mkdir(parents=True)
    with zipfile.ZipFile(b["backup"]) as z:
        for n in z.namelist():
            if n.endswith("/"):
                continue
            if n == "db/app.db":
                dst = RT / "data" / "db" / "app.db"
            elif n.startswith("models/"):
                rel = n.split("/", 1)[1]
                assert ".." not in rel.split("/"), "unsafe member"
                dst = RT / "data" / "models" / rel
            else:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            with z.open(n) as s, open(dst, "wb") as d:
                shutil.copyfileobj(s, d, 8 << 20)
    rc = subprocess.call([base.VENV, "-X", "utf8", str(OPS / "fs_restore_verify.py"), str(OUT / "backup.json"),
                          str(RT / "data"), str(OUT / "restore.json")])
    res = load("restore.json")
    data, c = live()
    schema = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    c.close()
    live_files = {p.relative_to(data / "models").as_posix(): sha_file(p) for p in (data / "models").rglob("*")
                  if p.is_file() and p.suffix not in (".tmp", ".lock")}
    got = {p.relative_to(RT / "data" / "models").as_posix(): sha_file(p) for p in (RT / "data" / "models").rglob("*")
           if p.is_file()}
    shutil.rmtree(RT)                      # temporary copy: deleted as soon as the check is done (owner rule 03/11)
    sel2_ok = {k: v for k, v in got.items() if k.startswith("sel2/")} == \
        {k: v for k, v in live_files.items() if k.startswith("sel2/")}
    passed = (rc == 0 and res["integrity"] == "ok" and not res["count_differences"] and res["models_equal_live_list"]
              and not res["model_sha_mismatch"] and sel2_ok)
    res.update(sel2_files=sum(1 for k in got if k.startswith("sel2/")), sel2_equal=sel2_ok, passed=passed)
    save("restore.json", res)
    p = cli_paths(inst)
    save("verified_backup.json", {"backup": b["backup"], "sha256": b["sha256"], "integrity": res["integrity"],
                                  "count_differences": res["count_differences"],
                                  "models_equal_live_list": res["models_equal_live_list"],
                                  "model_sha_mismatch": res["model_sha_mismatch"], "sel2_equal": sel2_ok,
                                  "passed": passed, "db_path": p["db_path"], "schema_version": schema,
                                  "restore_tested_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    tell(f"thu khoi phuc {'DAT' if passed else 'LOI'}",
         f"integrity {res['integrity']}; {res['tables']} bang, {res['rows_total']:,} dong, lech {len(res['count_differences'])}; "
         f"model sha lech {len(res['model_sha_mismatch'])}; sel2 {res['sel2_files']} file {'khop' if sel2_ok else 'LECH'}",
         passed)
    return 0 if passed else 1


def backup_age_hours(path, now=None):
    """age of a backup from the stamp of its name (backup-YYYYMMDD-HHMMSS-*.zip, PC local time); None = no stamp"""
    m = re.match(r"backup-(\d{8})-(\d{6})", Path(str(path)).name)
    if not m:
        return None
    return ((now or datetime.now()) - datetime.strptime(m[1] + m[2], "%Y%m%d%H%M%S")).total_seconds() / 3600


def refresh_backup(why):
    """a new backup + restore test (the old json files are moved aside, the zips stay); 0 = verified"""
    tag = time.strftime("%Y%m%d-%H%M%S")
    for name in ("backup.json", "restore.json", "verified_backup.json"):
        if (OUT / name).exists():
            (OUT / name).replace(OUT / f"{Path(name).stem}.expired-{tag}.json")
    tell("SAO LUU LAI TRUOC KHI CAI", f"{why}: sao luu + thu khoi phuc lai, roi cai (khong cho chu du an)")
    for n in range(1, 4):
        rc = step_backup()
        if rc != 3:                            # 3 = written during the backup: taken again (as the backup step)
            break
        print(f"backup written during the backup, try {n}/3")
        time.sleep(300)
    rc = rc or step_restore()
    if rc != 0:
        tell("SAO LUU LAI LOI - CHUA CAI", f"sao luu / thu khoi phuc lai loi (exit {rc}); 1.4.2 van chay, khong cai", False)
    return rc


def active_jobs():
    import urllib.request
    with urllib.request.urlopen(base.API + "/jobs?limit=50", timeout=30) as r:
        jobs = json.loads(r.read().decode("utf-8"))
    return [f"{j.get('job_type')} {j.get('status')}" for j in jobs if j.get("status") in ("PENDING", "RUNNING", "RETRY_WAIT")]


def not_ready(now=None, windows=False):
    """None when the install may start now, else the reason: AC power, the D0 slots (as cai_142.step_nojobs: not in
    the 30 min before / 10 min after an even-hour slot 08-18), no active production job; windows=True also the
    blocked windows 23:45-00:15 / 00:45-03:45 (the runner checks them itself before the step)"""
    now = now or datetime.now()
    ac, pct = power()
    if ac is not True:
        return f"not on AC power (ac {ac}, battery {pct}%)"
    mins = now.hour * 60 + now.minute
    for a, b in BLOCKED if windows else ():
        a, b = (int(x[:2]) * 60 + int(x[3:]) for x in (a, b))
        if (a <= mins < b) if a <= b else (mins >= a or mins < b):
            return f"blocked window {now:%H:%M}"
    nxt = now.hour + 1 if now.minute >= 30 else None
    if nxt and nxt % 2 == 0 and 8 <= nxt <= 18:
        return f"D0 slot {nxt:02d}:00 in less than 30 min"
    if now.minute < 10 and now.hour % 2 == 0 and 8 <= now.hour <= 18:
        return f"D0 slot {now.hour:02d}:00 started less than 10 min ago"
    try:
        act = active_jobs()
    except Exception as e:  # noqa: BLE001 - app not answering: not ready
        return f"jobs API not read ({type(e).__name__})"
    return f"active jobs: {act}" if act else None


def step_ready():
    why = not_ready()
    print("ready" if why is None else f"not ready: {why}")
    return 0 if why is None else 1


def install_procs(patterns=INSTALL_PROC_RE):
    """[(pid, command line)] of running install processes: powershell -File ...deploy-upgrade.ps1 / install.ps1 and
    app.cli migrate / backup / check-env. The patterns are matched here (the PowerShell query holds none of them) and
    the query's own process ($PID) is excluded. [("?", "")] when the list cannot be read (taken as running)"""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine } | "
                              "Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"],
                             capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
                             creationflags=NO_WINDOW, timeout=120)
        if out.returncode != 0:
            return [("?", "")]
        rows = json.loads(out.stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return [("?", "")]
    rows = [rows] if isinstance(rows, dict) else rows
    rx = [re.compile(x, re.I) for x in patterns]
    return [(r.get("ProcessId"), r.get("CommandLine") or "") for r in rows if r.get("ProcessId") != os.getpid()
            and any(x.search(r.get("CommandLine") or "") for x in rx)]


def progress_time():
    """newest change of the install logs: deploy.log here and <data>\\logs\\deploy-*.log (deploy-upgrade transcript)"""
    t = []
    try:
        t.append((OUT / "deploy.log").stat().st_mtime)
    except OSError:
        pass
    try:
        logs = Path(json.loads(base.SJ.read_text(encoding="utf-8"))["data_dir"]) / "logs"
        t += [f.stat().st_mtime for f in logs.glob("deploy-*.log")]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return max(t, default=0.0)


def no_progress(since):
    """True (and a high alert) when the install logs did not change for 2 h and no alert came in the last 2 h"""
    if time.time() - max(progress_time(), since) <= PROGRESS_ALERT_S:
        return False
    tell("CAI KHONG CO TIEN DO", "cai 1.4.3: log cai khong doi 2 gio, tien trinh cai van chay; KHONG dung tien trinh, "
         "CAN KIEM TRA", False)
    return True


def wait_install_idle(marker=None):
    """wait, without a time limit and without killing anything, while an install process (or the cai_143 process of
    the marker) runs; high alert every 2 h without progress"""
    since = time.time()
    while True:
        procs = install_procs()
        if not procs and not (marker and alive(marker.get("pid"), marker.get("created"))):
            return
        if no_progress(since):
            since = time.time()
        print("install still running, wait:", [x[0] for x in procs] or "earlier cai_143 process")
        time.sleep(30)


def wait_ready(limit_s=READY_WAIT_S):
    """None when ready (AC power, no job, no D0 slot, outside the blocked windows), else the last reason after limit_s"""
    t0 = time.time()
    while (why := not_ready(windows=True)) and time.time() - t0 < limit_s:
        print("not ready:", why)
        time.sleep(60)
    return why


def run_deploy(cmd):
    """deploy-upgrade.ps1 without a time limit (an install is never killed in the middle); its exit code"""
    with open(OUT / "deploy.log", "a", encoding="utf-8") as f:
        f.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} {cmd}\n")
        f.flush()
        p = subprocess.Popen(cmd, cwd=str(BAN), stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        since = time.time()
        while True:
            try:
                return p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                if no_progress(since):
                    since = time.time()


def interrupted_deploy():
    """an earlier deploy-upgrade run started (deploy_started.json, or a deploy.log of the code before 05/11 evening)
    and ended without deploy.json: never a second upgrade run. Waits while it / an install process still runs, removes
    the watchdog-hold flag it left; 1.4.3 healthy -> installed; else back to 1.4.2"""
    m = load(MARKER) if (OUT / MARKER).exists() else {"source": "deploy.log without deploy.json"}
    wait_install_idle(m)
    base.HOLD.unlink(missing_ok=True)      # left by the dead run: the link watchdog may start the app again
    for _ in range(60):
        h = health()
        if h.get("version") == VERSION:
            break
        time.sleep(5)
    ok = bool(h.get("ok") and h.get("version") == VERSION and current() == VERSION)
    save("deploy.json", {"deploy_exit": "interrupted", "health": h, "current": current(), "installed": ok,
                         "interrupted": True, "marker": m,
                         "note": "earlier deploy run ended without deploy.json (sleep / restart): no second upgrade run"})
    if ok:
        tell("DA CAI 1.4.3 (lan cai bi gian doan)", f"health {h.get('version')}; lan cai truoc da xong truoc khi bi ngat")
        return 0
    back_to_prev(f"lan cai bi gian doan (ngu / khoi dong lai); health {h.get('version') or h.get('error')}")
    return 1


def back_to_prev(why):
    """1.4.3 failed: back to 1.4.2 (DB unchanged: 1.4.3 adds no migration); returns the final health"""
    log = []
    h = health()
    if h.get("version") == VERSION or current() == VERSION:
        rc = run(PS + [str(BAN / "scripts" / "rollback-version.ps1"), "-To", PREV, "-ConfirmToken", f"ROLLBACK-{PREV}"],
                 BAN, "rollback.log", 3600)
        log.append(f"rollback-version exit {rc}")
    for _ in range(24):
        h = health()
        if h.get("version") == PREV:
            break
        time.sleep(5)
    if h.get("version") != PREV:
        rc = run(PS + [str(base.PROGS / PREV / "scripts" / "start.ps1"), "-NoBrowser"], base.PROGS / PREV,
                 "rollback.log", 1800)
        log.append(f"start.ps1 {PREV} exit {rc}")
        for _ in range(60):
            h = health()
            if h.get("version") == PREV:
                break
            time.sleep(5)
    ok = h.get("ok") and h.get("version") == PREV
    tell("LOI CAI - DA QUAY VE 1.4.2" if ok else "LOI CAI - APP CHUA CHAY LAI",
         f"{why}; {'; '.join(log) or 'khong can rollback'}; health {h.get('version') or h}; "
         f"{'app 1.4.2 dang chay' if ok else 'CAN XU LY NGAY (khoi phuc tu ban sao luu buoc 2 neu can)'}", False)
    return h


def step_deploy():
    dl = OUT / "deploy.log"
    started = (OUT / MARKER).exists() or (dl.exists() and "deploy-upgrade.ps1" in dl.read_text(encoding="utf-8",
                                                                                                 errors="replace"))
    if started and not (OUT / "deploy.json").exists():
        return interrupted_deploy()
    h = health()
    if h.get("version") == VERSION and current() == VERSION:
        print("already installed", h)
        return 0
    prev = load("deploy.json") if (OUT / "deploy.json").exists() else {}
    if "deploy_exit" in prev and not prev.get("installed"):
        print("a previous upgrade run ended without installing: no automatic second run", prev)
        return 1
    for _ in range(3):
        age = backup_age_hours(load("verified_backup.json")["backup"]) if (OUT / "verified_backup.json").exists() else None
        if age is None or age > BACKUP_MAX_AGE_H:
            why = f"ban sao luu {'khong ro tuoi' if age is None else f'{age:.1f} gio'} > {BACKUP_MAX_AGE_H} gio"
            print(why)
            if refresh_backup(why) != 0:
                return 1
        wait = wait_ready()                    # AC power + windows + jobs + D0 slots, right before the app is stopped
        if wait:
            tell("CHUA CAI", f"5 gio chua du dieu kien cai ({wait}); chua bat dau gi", False)
            return 3
        age = backup_age_hours(load("verified_backup.json")["backup"])
        if age is not None and age <= BACKUP_MAX_AGE_H:
            break
        print(f"backup {age} h old after the wait: taken again")
    else:
        tell("CHUA CAI", "ban sao luu lai qua cu sau 3 lan cho dieu kien cai; chua bat dau gi", False)
        return 1
    h = health()
    if not (OUT / "pre_deploy.json").exists():
        data, c = live()
        n = counts(c)
        c.close()
        save("pre_deploy.json", {"version": current(), "health": h, "table_counts": n, **base.config_snapshot()})
    rel, vb = load("release.json"), OUT / "verified_backup.json"
    args = ["-Package", rel["zip"], "-ExpectedSha256", rel["sha256"], "-VerifiedBackup", load("verified_backup.json")["backup"],
            "-RestoreReport", str(vb), "-ConfirmToken", f"UPGRADE-{VERSION}"]
    base.HOLD.parent.mkdir(parents=True, exist_ok=True)
    base.HOLD.write_text("deploy 1.4.3 (owner 05/11)", encoding="utf-8")
    save(MARKER, {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "pid": os.getpid(), "created": proc_created(os.getpid())})
    try:
        rc = run_deploy(PS + [str(BAN / "scripts" / "deploy-upgrade.ps1")] + args)
    finally:
        base.HOLD.unlink(missing_ok=True)
    for _ in range(60):
        h = health()
        if h.get("version") == VERSION:
            break
        time.sleep(5)
    text = (OUT / "deploy.log").read_text(encoding="utf-8", errors="replace")
    skipped = "backup: skipped, verified backup" in text
    ok = rc == 0 and h.get("version") == VERSION and current() == VERSION
    save("deploy.json", {"deploy_exit": rc, "health": h, "current": current(), "installed": ok,
                         "verified_backup_used": skipped})
    if not ok:
        wait_install_idle()                    # no rollback while an install process still runs
        back_to_prev(f"deploy-upgrade exit {rc}, health {h.get('version')}")
        return 1
    tell("DA CAI 1.4.3", f"health {h.get('version')}; bo sao luu lap lai: {'CO' if skipped else 'KHONG (sao luu thuong)'}")
    return 0


def step_postcheck():
    pre = load("pre_deploy.json")
    h = health()
    now = base.config_snapshot()
    data, c = live()
    n = counts(c)
    c.close()
    lost = {t: (pre["table_counts"].get(t), n.get(t)) for t in pre["table_counts"] if n.get(t, -1) < pre["table_counts"][t]}
    grown = {t: (pre["table_counts"].get(t), n.get(t)) for t in n if n.get(t) != pre["table_counts"].get(t) and t not in lost}
    diff = sorted(k for k in set(pre["settings_sha"]) | set(now["settings_sha"])
                  if pre["settings_sha"].get(k) != now["settings_sha"].get(k))
    src = (base.PROGS / VERSION / "backend" / "app" / "ml" / "sel2" / "export.py").read_text(encoding="utf-8")
    res = {"health": h, "current": current(), "schedule_identical": now["schedule_sha"] == pre["schedule_sha"],
           "settings_sections_changed": diff, "storage_json_unchanged": now["storage_json_sha"] == pre["storage_json_sha"],
           "forecast_source_config_unchanged": now["forecast_source_config"] == pre["forecast_source_config"],
           "tables": len(n), "tables_with_fewer_rows": lost, "tables_changed_by_jobs": grown,
           "fixed_rule_in_code": all(x in src for x in ("DUNG_SO_LAN_CHAY_TRUOC", "KHONG_CO_SO_NAO",
                                                         "KHONG_CO_AVG_DUNG_LIGHTGBM", "PREVIOUS_RUN_DAYS = 3"))}
    res["passed"] = bool(h.get("ok") and h.get("version") == VERSION and current() == VERSION and res["schedule_identical"]
                         and not diff and res["storage_json_unchanged"] and res["forecast_source_config_unchanged"]
                         and not lost and res["fixed_rule_in_code"])
    save("postcheck.json", res)
    tell(f"kiem tra sau cai {'DAT' if res['passed'] else 'LOI'}",
         f"health {h.get('version')}; lich trung {res['schedule_identical']}; cai dat doi {diff or 'khong'}; "
         f"storage.json {res['storage_json_unchanged']}; bang mat dong {len(lost)}; bang tang (job) {len(grown)}",
         res["passed"])
    return 0 if res["passed"] else 1


def roundup(x):
    return 0 if x is None or not math.isfinite(x) or round(float(x), 6) < 0.2 else math.ceil(round(float(x), 6))


def step_export():
    inst = base.PROGS / VERSION
    assert current() == VERSION and health().get("version") == VERSION, "1.4.3 is not the running version"
    done = OUT / "export.json"
    if not (done.exists() and json.loads(done.read_text(encoding="utf-8")).get("export_id")):
        rc = run([str(inst / "python" / "python.exe"), "-X", "utf8", "-m", "app.cli", "sel2-export", "--date", DAY,
                  "--yes"], inst / "backend", "export.log", 1800)
        if rc != 0:
            print("sel2-export failed, exit", rc)
            return 1
    data, c = live()
    rid, ver, rel, sha, n_rows, stale, flags = c.execute(
        "SELECT id, version, path, sha256, n_rows, is_stale, flags FROM export_runs WHERE forecast_date=? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1", (DAY,)).fetchone()
    c.close()
    import openpyxl
    path = data / rel
    wb = openpyxl.load_workbook(path, read_only=True)
    it = wb["DU_BAO"].iter_rows(values_only=True)
    ix = {k: i for i, k in enumerate(next(it))}
    bad, reasons, rows, split_bad = [], Counter(), 0, 0
    hdr_ok = list(ix)[:4] == ["sku_code", "ten_san_pham", "seller_code", "product_code"]
    allowed = {None, "NGOAI_PHAM_VI_GAN_0", "DUNG_SO_LAN_CHAY_TRUOC", "STALE", "KHONG_CO_SO",
               "KHONG_CO_AVG_DUNG_LIGHTGBM", "KHONG_CO_SO_NAO"}
    for r in it:
        rows += 1
        lg, av, used, why, s, fl = (r[ix["lightgbm_forecast"]], r[ix["avg_demand"]], r[ix["forecast_used"]],
                                    r[ix["fallback_reason"]], r[ix["forecast_source"]], r[ix["flags"]] or "")
        reasons[why or ""] += 1
        prevflag = "LAN_CHAY_TRUOC:" in fl
        # owner 05/11: seller_code / product_code = sku_code split at its first dot (no dot: seller empty, product = sku)
        sku, sel, prod = r[ix["sku_code"]], r[ix["seller_code"]], r[ix["product_code"]]
        # (an empty cell = empty part: ".X" -> empty / X, "X." -> X / empty still join back to sku_code)
        if ("." in str(sku) and f"{sel or ''}.{prod or ''}" != sku) or ("." not in str(sku) and (sel or prod != sku)):
            split_bad += 1
        if not isinstance(used, int) or isinstance(used, bool) or used < 0 or why not in allowed:
            ok = False
        elif why is None:
            ok = (used == roundup(lg) and lg is not None and not prevflag) if s == "LIGHTGBM" else \
                (av is not None and used == roundup(av))
        elif why == "NGOAI_PHAM_VI_GAN_0":
            ok = s == "LIGHTGBM" and lg is None and used == 0
        elif why == "DUNG_SO_LAN_CHAY_TRUOC":
            ok = s == "LIGHTGBM" and prevflag and lg is not None and used == roundup(lg)
        elif why in ("STALE", "KHONG_CO_SO"):
            ok = s == "LIGHTGBM" and lg is None and av is not None and used == roundup(av)
        elif why == "KHONG_CO_AVG_DUNG_LIGHTGBM":
            ok = s != "LIGHTGBM" and av is None and lg is not None and used == roundup(lg)
        else:                                                   # KHONG_CO_SO_NAO
            ok = used == 0 and lg is None and av is None
        if not ok:
            if len(bad) < 20:
                bad.append({"sku": r[ix["sku_code"]], "fc": r[ix["fc_code"]], "h": r[ix["horizon"]], "src": s,
                            "lgbm": lg, "avg": av, "used": used, "reason": why})
            else:
                bad.append(None)
    wb.close()
    latest = path.parent / f"du_bao_{DAY.replace('-', '')}.xlsx"
    res = {"export_id": rid, "version": ver, "file": str(path), "latest_copy": str(latest),
           "latest_copy_same": latest.exists() and sha_file(latest) == sha.upper(), "sha256": sha, "n_rows": n_rows,
           "rows_read": rows, "is_stale": stale, "flags": flags, "rows_by_reason": dict(reasons),
           "rows_breaking_rule": len(bad), "examples": [b for b in bad if b], "header_order_ok": hdr_ok,
           "rows_seller_product_wrong": split_bad}
    res["passed"] = not bad and rows == n_rows and hdr_ok and not split_bad
    save("export.json", res)
    tell(f"Excel 05/11 xuat lai {'DAT' if res['passed'] else 'LOI'} (v{ver})",
         f"{len(bad)} dong sai quy tac / {rows:,} dong; seller/product sai {split_bad}; ly do {dict(reasons)}; "
         f"file {path.name}", res["passed"])
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    lock = ops_lock_block(RUN_NAME)
    if lock and sys.argv[1] != "ready":
        print("waiting:", lock)
        sys.exit(3)
    sys.exit({"release": step_release, "backup": step_backup, "restore": step_restore, "deploy": step_deploy,
              "postcheck": step_postcheck, "export": step_export, "ready": step_ready}[sys.argv[1]]())
