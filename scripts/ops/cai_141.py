"""1.4.1 install (owner 04/11/2026: "ok cài", run now through the runner). Steps of reports\\release-1.4.1-20261104\\plan.json;
every step is resumable (a second run continues or redoes without harm). Output json files in OUT.
  release   scripts\\release.ps1 of the worktree ban-1.4 (ops_config.worktree; branch github/1.4.1: clean commit -> full QA -> package -> verify)
            -> release.json {zip, sha256, commit}
  backup    online backup of the live DB + models with the INSTALLED code (e1_backup.py, reason pre-1.4.1) -> backup.json
  restore   restore test of that backup (e1_restore.py: isolated copy, deleted after) -> restore.json
  deploy    snapshot of the configuration (mode=ro) -> pre_deploy.json; link-watchdog hold flag; deploy-upgrade.ps1
            -CheckOnly, then -ConfirmToken UPGRADE-1.4.1; health 1.4.1; hold flag removed -> deploy.json
  postcheck health 1.4.1, schedule byte-identical to pre_deploy, storage.json unchanged, forecast_source_config
            unchanged, data-check without ERROR / FAIL (installed 1.4.1) -> postcheck.json
  export    sel2-export --date 2026-11-04 --yes with the installed 1.4.1 (no forecast run), then every DU_BAO row
            checked against the owner rule -> export.json (exit 1 when a row breaks the rule)
usage: cai_141.py <step>"""
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

VERSION = "1.4.1"
DAY = "2026-11-04"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ops_config  # noqa: E402  (machine paths)

BAN = ops_config.worktree("ban-1.4")
OPS = ops_config.HERE
OUT = ops_config.REPORTS / "release-1.4.1-20261104"
VENV = ops_config.VENV
PROGS = ops_config.PROGS
SJ = ops_config.STORAGE_JSON
HOLD = ops_config.REMOTE_DIR / "run" / "watchdog-hold"
API = "http://127.0.0.1:8765/api"
PS = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(OPS / "runner"))
import notify  # noqa: E402


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(name, json.dumps(obj, ensure_ascii=False, default=str)[:1500], flush=True)


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def current():
    return (PROGS / "current.txt").read_text(encoding="utf-8").strip()


def health():
    try:
        with urllib.request.urlopen(API + "/health", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": type(e).__name__}


def run(cmd, cwd, log, timeout):
    with open(OUT / log, "a", encoding="utf-8") as f:
        f.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} {cmd}\n")
        f.flush()
        p = subprocess.run(cmd, cwd=str(cwd), stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                           timeout=timeout)
    return p.returncode


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def live():
    data = Path(json.loads(SJ.read_text(encoding="utf-8"))["data_dir"])
    c = sqlite3.connect((data / "db" / "app.db").as_uri() + "?mode=ro", uri=True)
    c.execute("PRAGMA query_only=1")
    return data, c


def config_snapshot():
    data, c = live()
    settings = {k: v for k, v in c.execute("SELECT section, value_json FROM app_settings ORDER BY section")}
    fsc = dict(c.execute("SELECT forecast_source, COUNT(*) FROM forecast_source_config GROUP BY 1"))
    fsc_hist = c.execute("SELECT COUNT(*) FROM forecast_source_config_history").fetchone()[0]
    c.close()
    return {"schedule_sha": hashlib.sha256(settings["schedule"].encode()).hexdigest(),
            "settings_sha": {k: hashlib.sha256(v.encode()).hexdigest() for k, v in settings.items()},
            "storage_json_sha": sha_file(SJ), "forecast_source_config": fsc, "forecast_source_history": fsc_hist}


def data_check(inst):
    out = subprocess.run([str(inst / "python" / "python.exe"), "-X", "utf8", "-m", "app.cli", "data-check"],
                         cwd=str(inst / "backend"), capture_output=True, text=True, encoding="utf-8",
                         stdin=subprocess.DEVNULL).stdout
    d = json.loads(out[out.find("{"):])
    return d, {x["check"]: x["status"] for x in d["checks"] if x["status"] not in ("OK", "WARN")}


def step_release():
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=BAN, capture_output=True, text=True).stdout.strip()
    rc = run(PS + [str(BAN / "scripts" / "release.ps1")], BAN, "release.log", 5400)
    zip_ = BAN / "dist" / f"DemandForecast-{VERSION}-win64-portable.zip"
    if rc != 0 or not zip_.exists():
        print("release.ps1 failed, exit", rc, "(see release.log)")
        return 1
    rec = (Path(str(zip_) + ".sha256").read_text(encoding="utf-8").split()[0]).upper()
    sha = sha_file(zip_)
    save("release.json", {"zip": str(zip_), "sha256": sha, "sha256_file": rec, "commit": commit, "bytes": zip_.stat().st_size})
    return 0 if sha == rec else 1


def step_backup():
    inst = PROGS / current()
    return subprocess.call([str(inst / "python" / "python.exe"), "-X", "utf8", str(OPS / "e1_backup.py"),
                            str(OUT / "backup.json"), "pre-1.4.1"], cwd=str(inst / "backend"), stdin=subprocess.DEVNULL)


def step_restore():
    return subprocess.call([VENV, "-X", "utf8", str(OPS / "e1_restore.py"), str(OUT / "backup.json"),
                            str(OUT / "restore.json")], cwd=str(OPS), stdin=subprocess.DEVNULL)


def step_deploy():
    h = health()
    if h.get("version") == VERSION and current() == VERSION:
        print("already installed", h)
        HOLD.unlink(missing_ok=True)
        return 0
    if not (OUT / "pre_deploy.json").exists():
        save("pre_deploy.json", {"version": current(), "health": h, **config_snapshot()})
    rel = load("release.json")
    args = ["-Package", rel["zip"], "-ExpectedSha256", rel["sha256"]]
    script = str(BAN / "scripts" / "deploy-upgrade.ps1")
    HOLD.parent.mkdir(parents=True, exist_ok=True)
    HOLD.write_text("deploy 1.4.1 (owner 04/11)", encoding="utf-8")
    try:
        # the check-only run of this package already passed (04/11 17:25): the real run repeats the same prechecks
        prev = load("deploy.json") if (OUT / "deploy.json").exists() else {}
        if prev.get("checkonly_exit") != 0:
            rc = run(PS + [script] + args + ["-CheckOnly"], BAN, "deploy.log", 1800)
            if rc != 0:
                save("deploy.json", {"checkonly_exit": rc, "installed": False})
                return 1
        # 04/11: a 10 GB DB under low RAM needed > 1 h (storage-verify + online backup + install.ps1 backup); a timeout
        # kill inside install.ps1 could leave the app stopped, so the limit is generous (4 h)
        rc = run(PS + [script] + args + ["-ConfirmToken", f"UPGRADE-{VERSION}"], BAN, "deploy.log", 14400)
        for _ in range(60):
            h = health()
            if h.get("version") == VERSION:
                break
            time.sleep(5)
        ok = rc == 0 and h.get("version") == VERSION and current() == VERSION
        save("deploy.json", {"checkonly_exit": 0, "deploy_exit": rc, "health": h, "current": current(), "installed": ok})
        return 0 if ok else 1
    finally:
        HOLD.unlink(missing_ok=True)


def step_postcheck():
    pre = load("pre_deploy.json")
    h = health()
    now = config_snapshot()
    dc, bad = data_check(PROGS / VERSION)
    diff = sorted(k for k in set(pre["settings_sha"]) | set(now["settings_sha"])
                  if pre["settings_sha"].get(k) != now["settings_sha"].get(k))
    res = {"health": h, "current": current(), "schedule_identical": now["schedule_sha"] == pre["schedule_sha"],
           "schedule_sha": now["schedule_sha"][:16], "settings_sections_changed": diff,
           "storage_json_unchanged": now["storage_json_sha"] == pre["storage_json_sha"],
           "forecast_source_config_before": pre["forecast_source_config"], "forecast_source_config_after":
           now["forecast_source_config"], "data_check": dc["status"], "data_check_not_ok": bad,
           "data_check_warn": {x["check"]: x.get("count") for x in dc["checks"] if x["status"] == "WARN"}}
    res["passed"] = (h.get("ok") and h.get("version") == VERSION and current() == VERSION and res["schedule_identical"]
                     and res["storage_json_unchanged"] and now["forecast_source_config"] == pre["forecast_source_config"]
                     and not bad)
    save("postcheck.json", res)
    (OUT / "data-check-sau-cai.json").write_text(json.dumps(dc, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0 if res["passed"] else 1


def step_export():
    inst = PROGS / VERSION
    assert current() == VERSION and health().get("version") == VERSION, "1.4.1 is not the running version"
    done = OUT / "export.json"
    if not (done.exists() and json.loads(done.read_text(encoding="utf-8")).get("export_id")):
        rc = run([str(inst / "python" / "python.exe"), "-X", "utf8", "-m", "app.cli", "sel2-export", "--date", DAY,
                  "--yes"], inst / "backend", "export.log", 1800)
        if rc != 0:
            print("sel2-export failed, exit", rc)
            return 1
    data, c = live()
    rec = c.execute("SELECT id, version, path, sha256, n_rows, is_stale, flags, created_at FROM export_runs "
                    "WHERE forecast_date=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (DAY,)).fetchone()
    c.close()
    rid, ver, rel, sha, n_rows, stale, flags, created = rec
    import openpyxl
    path = data / rel
    latest = path.parent / f"du_bao_{DAY.replace('-', '')}.xlsx"
    wb = openpyxl.load_workbook(path, read_only=True)
    it = wb["DU_BAO"].iter_rows(values_only=True)
    hdr = next(it)
    ix = {k: i for i, k in enumerate(hdr)}
    bad, reasons, src = [], Counter(), Counter()
    pairs = defaultdict(set)
    rows = 0
    for r in it:
        rows += 1
        sku, fc = r[ix["sku_code"]], r[ix["fc_code"]]
        lg, av, used, why, s = (r[ix["lightgbm_forecast"]], r[ix["avg_demand"]], r[ix["forecast_used"]],
                                r[ix["fallback_reason"]], r[ix["forecast_source"]])
        src[s] += 1
        reasons[why or ""] += 1
        medx = str(sku).split(".", 1)[0] == "MEDX"
        if s != "LIGHTGBM":
            case, ok = "AVG_DEMAND_CONFIG", used == av and why is None
        elif lg is not None:
            case, ok = "LIGHTGBM", used == lg and why is None
        elif medx:
            case, ok = "MEDX_0", used == 0 and why == "NGOAI_PHAM_VI_GAN_0"
        else:
            case, ok = "KHAC_AVG", used == av and why == "KHONG_CO_DU_LIEU_DEMAND"
        pairs[(sku, fc)].add(case)
        if not ok and len(bad) < 50:
            bad.append({"sku": sku, "fc": fc, "h": r[ix["horizon"]], "lgbm": lg, "avg": av, "used": used, "reason": why})
        elif not ok:
            bad.append(None)
    wb.close()
    by_case = Counter(next(iter(v)) if len(v) == 1 else "MIXED" for v in pairs.values())
    res = {"export_id": rid, "version": ver, "file": str(path), "latest_copy": str(latest),
           "latest_copy_same": latest.exists() and sha_file(latest) == sha.upper(), "sha256": sha, "n_rows": n_rows,
           "rows_read": rows, "is_stale": stale, "flags": flags, "created_at": created, "rows_by_source": dict(src),
           "rows_by_reason": dict(reasons), "sku_fc_by_case": dict(by_case), "sku_fc": len(pairs),
           "rows_breaking_rule": len(bad), "examples": [b for b in bad if b][:20]}
    res["passed"] = not bad and rows == n_rows and not stale
    save("export.json", res)
    notify.send(f"Cai {VERSION}: Excel {DAY[8:10]}/{DAY[5:7]} xuat lai (v{ver})",
                f"{'DAT' if res['passed'] else 'LOI'}: {len(bad)} dong sai quy tac; SKUxkho LightGBM "
                f"{by_case.get('LIGHTGBM', 0)}, MEDX=0 {by_case.get('MEDX_0', 0)}, khac->avg {by_case.get('KHAC_AVG', 0)}. "
                f"File {path.name}", "high" if not res["passed"] else "default")
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit({"release": step_release, "backup": step_backup, "restore": step_restore, "deploy": step_deploy,
              "postcheck": step_postcheck, "export": step_export}[sys.argv[1]]())
