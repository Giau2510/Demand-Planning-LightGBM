"""End-to-end smoke test against a RUNNING app (real HTTP, real SQLite, real LightGBM).

Usage:  python scripts/smoke_test.py [--base http://127.0.0.1:8765] [--phase full|after-restart]
Exit code 0 = all checks passed.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import requests

H = {"X-DF-Client": "web"}
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, info: str = "") -> None:
    results.append((name, bool(cond), info))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""), flush=True)


def full(base: str) -> None:
    s = requests.Session()
    r = s.get(f"{base}/api/health")
    check("health", r.ok and r.json()["ok"], r.text[:80])
    r = s.get(f"{base}/")
    check("ui served at /", r.ok and "<div id=\"root\">" in r.text)
    r = s.get(f"{base}/assets/" + r.text.split("/assets/")[1].split('"')[0]) if "/assets/" in r.text else None
    check("ui assets served", bool(r is not None and r.ok))
    r = s.post(f"{base}/api/demo/generate", json={})
    check("csrf: POST without header refused", r.status_code == 403)
    r = s.put(f"{base}/api/active-source", json={"source": "DEMO"}, headers=H)
    check("active source DEMO", r.ok)
    r = s.post(f"{base}/api/demo/generate", json={"days": 400, "n_skus": 20}, headers=H)
    check("demo generated", r.ok and r.json()["valid_rows"] > 1000, str(r.json().get("valid_rows")))
    r2 = s.post(f"{base}/api/demo/generate", json={"days": 400, "n_skus": 20}, headers=H)
    check("demo generated 2nd time (v1.0.0 FK bug)", r2.ok, r2.text[:120])
    st = s.get(f"{base}/api/system/status").json()
    check("dashboard follows newest demo", st["scope"] and st["scope"]["scope_key"] == r2.json().get("batch_id"))
    hc = s.get(f"{base}/api/system/health-check").json()
    check("db integrity + FK after demo x2", hc["integrity"] == "ok" and hc["foreign_key_violations"] == 0, str(hc))
    pth = s.get(f"{base}/api/system/paths").json()
    check("paths API", pth["db_exists"] and "runtime_file" not in pth, pth["db_path"])
    t0 = time.time()
    r = s.post(f"{base}/api/training/run", json={"force": True}, headers=H)
    job = r.json()
    for _ in range(300):
        j = s.get(f"{base}/api/jobs?job_type=TRAIN_PUBLISH&limit=5").json()
        job = next((x for x in j if x["id"] == job["id"]), job)
        if job["status"] in ("SUCCEEDED", "FAILED", "SKIPPED"):
            break
        time.sleep(1)
    check("train + publish (DEMO)", job["status"] == "SUCCEEDED" and job["reason_code"] == "FORECAST_PUBLISHED",
          f"{job['status']} {job.get('reason_code')} {time.time() - t0:.1f}s")
    d = s.get(f"{base}/api/dashboard?horizon=7").json()
    f = d.get("forecast") or {}
    check("dashboard forecast 7d", f.get("horizon") == 7 and len(f.get("daily", [])) == 7 and f.get("data_source") == "DEMO")
    run_id = d["system"]["latest_forecast_run"]["id"]
    for h in d["system"]["latest_forecast_run"]["horizons"]:
        sm = s.get(f"{base}/api/forecast-runs/{run_id}/summary?horizon={h}").json()
        check(f"summary {h}d", len(sm["daily"]) == h and sm["grand_total"] > 0)
    r = s.get(f"{base}/api/forecast-runs/{run_id}/export.xlsx?horizon=7")
    check("export xlsx", r.ok and r.content[:2] == b"PK")
    r = s.post(f"{base}/api/jobs/run", json={"job_type": "D0_SYNC"}, headers=H)
    time.sleep(2)
    snaps = s.get(f"{base}/api/snapshots").json()
    check("D0 snapshot (DEMO)", len(snaps) >= 1 and snaps[0]["data_source"] == "DEMO")
    # Excel import flow with the downloadable sample
    content = s.get(f"{base}/api/templates/sample-history.xlsx").content
    up = s.post(f"{base}/api/imports/upload", files={"file": ("sample.xlsx", content)}, headers=H).json()
    b = s.post(f"{base}/api/imports/uploads/{up['upload_id']}/validate",
               json={"sheet": up["suggested_sheet"], "mapping": up["suggested_mapping"]}, headers=H).json()
    check("import validate", b["status"] == "PENDING_REVIEW" and b["valid_rows"] > 1000)
    c = s.post(f"{base}/api/imports/{b['id']}/confirm", json={}, headers=H).json()
    check("import confirm", c["status"] == "ACTIVE")
    r = s.post(f"{base}/api/imports/upload", files={"file": ("x.csv", b"a,b\n1,2\n")}, headers=H)
    check("csv rejected", r.status_code == 415 and r.json()["code"] == "NOT_XLSX")
    s.put(f"{base}/api/active-source", json={"source": "MANUAL_IMPORT"}, headers=H)
    r = s.post(f"{base}/api/training/run", json={}, headers=H).json()
    for _ in range(300):
        j = s.get(f"{base}/api/jobs?job_type=TRAIN_PUBLISH&limit=5").json()
        r = next((x for x in j if x["id"] == r["id"]), r)
        if r["status"] in ("SUCCEEDED", "FAILED", "SKIPPED"):
            break
        time.sleep(1)
    check("train + publish (MANUAL_IMPORT)", r["status"] == "SUCCEEDED", f"{r['status']} {r.get('reason_code')}")
    st = s.get(f"{base}/api/system/status").json()
    check("forecast tied to import scope", st["latest_forecast_run"] and st["latest_forecast_run"]["scope_key"] == c["id"])
    s.put(f"{base}/api/active-source", json={"source": "DEMO"}, headers=H)
    r = s.put(f"{base}/api/active-source", json={"source": "BIGQUERY"}, headers=H)
    check("BigQuery refused until verified", r.status_code == 409)
    r = s.post(f"{base}/api/system/backups", headers=H)
    check("backup", r.ok and r.json()["file"].endswith(".zip"))
    s.put(f"{base}/api/settings/quality", json={**s.get(f"{base}/api/settings").json()["quality"], "wape_max": 0.77},
          headers=H)


def after_restart(base: str) -> None:
    s = requests.Session()
    st = s.get(f"{base}/api/system/status").json()
    check("data persisted after restart", st["scope"] is not None and st["latest_forecast_run"] is not None)
    check("settings persisted after restart", s.get(f"{base}/api/settings").json()["quality"]["wape_max"] == 0.77)
    check("scheduler running after restart", st["scheduler"]["running"] is True)
    runs = s.get(f"{base}/api/forecast-runs").json()
    check("forecast history kept", len(runs) >= 2, str(len(runs)))


def readonly(base: str, expect_db: str | None, expect_scope: str | None, expect_runs: int | None) -> None:
    """Verification against REAL user data: GET requests only, nothing is written."""
    s = requests.Session()
    check("health", s.get(f"{base}/api/health").json()["ok"])
    p = s.get(f"{base}/api/system/paths").json()
    if expect_db:
        check("app uses the expected database", p["db_path"].lower() == expect_db.lower(), p["db_path"])
    hc = s.get(f"{base}/api/system/health-check?full=true").json()
    check("integrity_check + foreign_key_check", hc["integrity"] == "ok" and hc["foreign_key_violations"] == 0, str(hc))
    st = s.get(f"{base}/api/system/status").json()
    if expect_scope:
        check("active dataset unchanged", (st["scope"] or {}).get("scope_key") == expect_scope, str(st.get("scope")))
    if expect_runs is not None:
        check("forecast history unchanged", len(s.get(f"{base}/api/forecast-runs").json()) == expect_runs)
    d = s.get(f"{base}/api/system/diagnostics").json()
    check("diagnostics", d["database"]["connected"] and d["database"]["integrity"] == "ok")
    check("ui served", "<div id=\"root\">" in s.get(f"{base}/").text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--phase", default="full", choices=["full", "after-restart", "readonly"])
    ap.add_argument("--expect-db")
    ap.add_argument("--expect-scope")
    ap.add_argument("--expect-runs", type=int)
    ap.add_argument("--test-data-dir", help="required for full/after-restart: the app's data_dir must equal this "
                                            "(guard against writing into a real database)")
    a = ap.parse_args()
    if a.phase != "readonly":
        actual = requests.get(f"{a.base.rstrip('/')}/api/system/paths").json()["data_dir"]
        if not a.test_data_dir or os.path.normcase(os.path.abspath(a.test_data_dir)) != os.path.normcase(actual):
            print(f"REFUSED: phase '{a.phase}' writes data, but the app uses {actual}. "
                  "Pass --test-data-dir <that folder> only if it is a disposable test folder.")
            sys.exit(2)
    if a.phase == "readonly":
        readonly(a.base.rstrip("/"), a.expect_db, a.expect_scope, a.expect_runs)
    else:
        (full if a.phase == "full" else after_restart)(a.base.rstrip("/"))
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)
