"""Command line: python -m app.cli <command>

  serve [--port 8765] [--host 127.0.0.1]   start the web app (scheduler included)
  migrate                                   apply database migrations (backup taken first)
  backup                                    create a backup zip in <data>\\backups
  restore <file.zip>                        restore a backup (the app must be stopped)
  check-env                                 verify Python packages, LightGBM, data dir, DB
  demo                                      generate DEMO data
  info                                      print paths and versions
  paths [--check]                           effective storage paths as JSON (--check: validate/create safely)
  diagnose [--out DIR]                      write a diagnostic report (.md) to <reports_dir> or DIR
  storage-inventory                         schema version, row counts, integrity of the active database
  storage-migrate --to DIR [--logs-dir D] [--backups-dir D] [--reports-dir D] [--dry-run]
  storage-rollback                          undo the last storage migration
  storage-verify                            read-only: storage.json vs storage-id.json vs history vs database
  storage-repair [--apply]                  re-create a LOST storage.json from verified migration evidence
                                            (default: verify and show only; writes ONLY with --apply)
  data-check [--db FILE] [--models-dir DIR] read-only data invariants (batches, demand, forecasts, models, jobs)
  bq-check                                  Google sign-in + BigQuery access gates for THIS Windows account (reads
                                            metadata, runs SELECT 1; writes nothing to BigQuery; prints no secret)
Exit codes: 0 ok, 1 problems, 2 refused (app running / unsafe), 3 storage error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _check_env() -> int:
    ok = True
    report = {"python": sys.version.split()[0]}
    if sys.version_info < (3, 11):
        report["python_error"] = "Python 3.11+ required"
        ok = False
    for mod in ("fastapi", "uvicorn", "pydantic", "numpy", "pandas", "lightgbm", "openpyxl", "tzdata",
                "google.cloud.bigquery"):
        try:
            m = __import__(mod, fromlist=["x"])
            report[mod] = getattr(m, "__version__", "ok")
        except Exception as e:  # noqa: BLE001
            report[mod] = f"MISSING: {e}"
            ok = ok and mod == "google.cloud.bigquery"  # BigQuery is optional for DEMO / Excel
    try:
        import lightgbm as lgb
        import numpy as np
        X = np.random.default_rng(0).random((200, 3))
        b = lgb.train({"objective": "regression", "verbose": -1}, lgb.Dataset(X, X[:, 0]), 5)
        report["lightgbm_train_predict"] = bool(len(b.predict(X[:2])) == 2)
    except Exception as e:  # noqa: BLE001
        report["lightgbm_train_predict"] = f"FAILED: {e}"
        ok = False
    from zoneinfo import ZoneInfo
    try:
        ZoneInfo("Asia/Ho_Chi_Minh")
        report["timezone"] = "ok"
    except Exception as e:  # noqa: BLE001
        report["timezone"] = f"FAILED: {e}"
        ok = False
    from . import db, paths
    try:
        report["paths"] = paths.describe()
        paths.ensure_storage()
    except paths.StorageError as e:
        report["storage_error"] = f"{e.code}: {e.detail}"
        ok = False
    try:
        report["migrations"] = db.migrate()
    except Exception as e:  # noqa: BLE001
        report["migrations"] = f"FAILED: {e}"
        ok = False
    from . import paths as p
    report["frontend_built"] = (p.frontend_dist() / "index.html").exists()
    try:
        with db.read() as c:
            report["database_health"] = db.health_check(c, quick=True)
            if report["database_health"]["integrity"] != "ok" or report["database_health"]["foreign_key_violations"]:
                ok = False
    except Exception as e:  # noqa: BLE001
        report["database_health"] = f"FAILED: {type(e).__name__}: {e}"
        ok = False
    report["status"] = "OK" if ok else "PROBLEMS"
    print(json.dumps(report, indent=2, default=str))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=int(os.environ.get("DF_PORT", "8765")))
    s.add_argument("--host", default=os.environ.get("DF_HOST", "127.0.0.1"))
    sub.add_parser("migrate")
    sub.add_parser("backup")
    r = sub.add_parser("restore")
    r.add_argument("file")
    sub.add_parser("check-env")
    sub.add_parser("demo")
    sub.add_parser("info")
    pp = sub.add_parser("paths")
    pp.add_argument("--check", action="store_true")
    dg = sub.add_parser("diagnose")
    dg.add_argument("--out")
    sub.add_parser("storage-inventory")
    sm = sub.add_parser("storage-migrate")
    sm.add_argument("--to", required=True)
    sm.add_argument("--logs-dir")
    sm.add_argument("--backups-dir")
    sm.add_argument("--reports-dir")
    sm.add_argument("--dry-run", action="store_true")
    sub.add_parser("storage-rollback")
    sub.add_parser("storage-verify")
    sr = sub.add_parser("storage-repair")
    sr.add_argument("--apply", action="store_true", help="write storage.json (default: verify + show only)")
    sr.add_argument("--dry-run", action="store_true", help="kept for compatibility; dry run is the default")
    si = sub.add_parser("storage-init")
    si.add_argument("--data-dir", required=True)
    si.add_argument("--logs-dir")
    si.add_argument("--backups-dir")
    si.add_argument("--reports-dir")
    dc = sub.add_parser("data-check")
    dc.add_argument("--db", help="database file (default: the configured database, opened read-only)")
    dc.add_argument("--models-dir", help="models folder (default: the configured one when --db is not given)")
    sub.add_parser("bq-check")
    a = ap.parse_args(argv)
    from . import paths
    try:
        return _run(a)
    except paths.StorageError as e:
        print(json.dumps({"ok": False, "code": e.code, "detail": e.detail}, ensure_ascii=False))
        return 3


def _run(a) -> int:
    from . import paths
    if a.cmd == "paths":
        out = paths.describe()
        if a.check:
            paths.ensure_storage()
            out = paths.describe()
        out["ok"] = True
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    if a.cmd in ("storage-verify", "storage-repair"):
        from . import storage_migrate
        if a.cmd == "storage-verify":
            res = storage_migrate.verify_storage()
            print(json.dumps(res, indent=2, default=str, ensure_ascii=False))
            return 0 if res["ok"] else 1
        try:
            res = storage_migrate.repair_storage_config(dry_run=not a.apply)
        except storage_migrate.MigrationAborted as e:
            print(json.dumps({"ok": False, "refused": str(e)}, ensure_ascii=False))
            return 2
        print(json.dumps({"ok": True, **res}, indent=2, default=str, ensure_ascii=False))
        return 0
    if a.cmd == "data-check":
        from pathlib import Path
        from . import data_checks
        target = Path(a.db) if a.db else paths.db_path()
        models = Path(a.models_dir) if a.models_dir else (None if a.db else paths.models_dir())
        res = data_checks.run(target, models)
        print(json.dumps(res, indent=2, default=str, ensure_ascii=False))
        return 1 if res["status"] == "FAIL" else 0
    if a.cmd == "storage-init":
        cfg = paths.init_storage_config(a.data_dir, a.logs_dir, a.backups_dir, a.reports_dir)
        paths.ensure_storage()
        from . import db
        db.migrate()
        print(json.dumps({"ok": True, "config": cfg, "paths": paths.describe()}, indent=2, ensure_ascii=False))
        return 0

    from .logging_setup import setup_logging
    if a.cmd == "serve":
        import uvicorn
        from .security import write_runtime
        if a.host not in ("127.0.0.1", "localhost") and os.environ.get("DF_ALLOW_REMOTE") != "1":
            print("Refusing to bind to a non-local address. Set DF_ALLOW_REMOTE=1 only after a security review.")
            return 2
        r = paths.ensure_storage()   # fail fast with a clear message; never start on an unexpected database
        from .security import read_runtime
        rt = read_runtime()
        if rt and rt.get("pid") != os.getpid() and _pid_alive(rt.get("pid")):
            print(json.dumps({"ok": False, "code": "ALREADY_RUNNING",
                              "detail": f"another instance (pid {rt.get('pid')}, port {rt.get('port')}) uses {r['data_dir']}"}))
            return 2
        print(json.dumps({"data_dir": str(r["data_dir"]), "db": str(r["db_path"]), "logs": str(r["logs_dir"])}))
        write_runtime(a.port)
        uvicorn.run("app.main:app", host=a.host, port=a.port, log_level="warning", workers=1)
        return 0
    setup_logging()
    from . import backup, db, paths
    if a.cmd == "migrate":
        print(json.dumps(db.migrate(), indent=2))
    elif a.cmd == "backup":
        db.migrate()
        print(backup.backup_database("cli"))
    elif a.cmd == "restore":
        from .security import read_runtime
        rt = read_runtime()
        if rt and _pid_alive(rt.get("pid")):
            print("The app appears to be running (pid %s). Stop it first (scripts\\stop.ps1)." % rt.get("pid"))
            return 2
        print(json.dumps(backup.restore_backup(a.file), indent=2))
        print(json.dumps(db.migrate(), indent=2))
    elif a.cmd == "check-env":
        return _check_env()
    elif a.cmd == "demo":
        db.migrate()
        from .data.demo import create_demo_batch
        print(json.dumps(create_demo_batch(), indent=2, default=str)[:2000])
    elif a.cmd == "diagnose":
        from . import diagnostics
        from pathlib import Path
        out = Path(a.out) if a.out else None
        if out:
            out.mkdir(parents=True, exist_ok=True)
        print(diagnostics.save(out))
    elif a.cmd == "storage-inventory":
        from . import storage_migrate
        paths.ensure_storage()
        inv = storage_migrate.inventory(paths.db_path())
        inv.pop("objects")
        print(json.dumps(inv, indent=2))
    elif a.cmd in ("storage-migrate", "storage-rollback"):
        from . import storage_migrate
        try:
            res = (storage_migrate.migrate(a.to, a.logs_dir, a.backups_dir, a.reports_dir, a.dry_run)
                   if a.cmd == "storage-migrate" else storage_migrate.rollback())
        except storage_migrate.MigrationAborted as e:
            print(json.dumps({"ok": False, "refused": str(e)}, ensure_ascii=False))
            return 2
        print(json.dumps(res, indent=2, default=str, ensure_ascii=False))
    elif a.cmd == "bq-check":
        return _bq_check()
    elif a.cmd == "info":
        from . import __version__
        print(json.dumps({"version": __version__, "data_dir": str(paths.data_dir()), "db": str(paths.db_path()),
                          "frontend": str(paths.frontend_dist())}, indent=2))
    return 0


def _bq_check() -> int:
    """Same checks as the 'Check BigQuery access' button, from the command line of the SAME Windows account.
    Exit 0 = every gate passed, 1 = a gate failed (see first_failure), 3 = storage problem."""
    from . import settings_service as ss
    from .bq import connector, oauth
    from .messages import AppError, msg
    bq = ss.get("bigquery")
    st = oauth.status()
    out = {"identity": oauth.runtime_identity(),
           "oauth": {k: st.get(k) for k in ("configured", "client_id", "client_secret_set", "enabled", "status",
                                            "email", "signed_in_at", "verified_at", "error", "scopes")},
           "target": {"project": bq.project_id, "location": bq.location, "dataset": bq.dataset_id,
                      "table": bq.source_table}}
    try:
        res = connector.access_check()
    except AppError as e:
        res = {"passed": False, "first_failure": {"gate": "config", "code": e.code, "detail": e.detail}, "gates": []}
    out["access"] = res
    ff = res.get("first_failure")
    out["next_action"] = msg(ff["code"]) if ff and ff.get("code") else None
    print(json.dumps(out, indent=2, default=str, ensure_ascii=False))
    return 0 if res.get("passed") else 1


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    sys.exit(main())
