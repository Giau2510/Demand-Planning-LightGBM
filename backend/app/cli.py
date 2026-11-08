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
  eod-retention [--db FILE] [--apply --plan ID]   1.2.6: 90-day retention of the end-of-day forecast backup. Default:
                                            dry run (read-only) printing the plan and its plan_id; --apply deletes
                                            exactly that reviewed plan after a verified backup
  apply-preset lgbm-chot [--apply]          1.3.1: settings of PHUONG AN CHOT (model, daily_forecast, flows refresh +
                                            report). Default: dry run (read-only) printing the changes; --apply saves
                                            them through settings_service / the schedule flows (idempotent)
    [--feature-set CHOT|CHOT_LY|CHOT_LY_DEAL] 1.3.2: + model.feature_set (CHOT = the 1.3.1 preset unchanged); the
                                            CHOT_LY* sets need data_policy.extended_history_start_date; CHOT_LY_DEAL
                                            also sets the deal source keys of bigquery
  deal-lines-load --start D --end D [--apply] [--max-bytes N] [--allow-empty]
                                            1.3.2: order-line deal codes -> demand_deal_daily per calendar month,
                                            [backfill floor .. yesterday]; default: dry run (bytes per month only)
  deal-refresh [--apply] [--max-bytes N]    1.3.2: deal table -> one snapshot + deals (default: dry run, bytes only)
  deal-check [--start D] [--end D]          1.3.2: read-only checks of the stored deals and deal lines
  open-hours-load --start D --end D [--apply] [--max-bytes N]
                                            1.3.2: historical open_hours_daily in reads of at most 15 days, oldest
                                            first (the daily refresh watermark never moves back); default: dry run
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
    at = sub.add_parser("attest-training-data", help="1.2.4: content identity of an older training run's data, "
                                                     "from a backup that provably holds it")
    at.add_argument("--training-run", required=True)
    at.add_argument("--backup", required=True, help="full path of the backup .zip taken while the data was unchanged")
    sub.add_parser("product-names-refresh", help="1.2.4: read the product names of the local SKUs from BigQuery")
    sub.add_parser("history-reconcile", help="1.2.5: record published forecast runs missing from the forecast history "
                                             "(idempotent; reads the stored runs, creates no forecast)")
    er = sub.add_parser("eod-retention", help="1.2.6: 90-day retention of the end-of-day forecast backup (dry run unless "
                                              "--apply)")
    er.add_argument("--db", help="dry run on this database file (read-only); default: the configured database")
    er.add_argument("--apply", action="store_true", help="delete the snapshots of the reviewed plan (needs --plan)")
    er.add_argument("--plan", help="plan_id printed by the dry run that was reviewed")
    af = sub.add_parser("actual-finalize", help="1.2.9: finalize (freeze) the actual of completed days written by a "
                                                "verified D-1 load (dry run unless --apply)")
    af.add_argument("--db", help="dry run on this database file (read-only); default: the configured database")
    af.add_argument("--apply", action="store_true", help="finalize the eligible days in the configured database")
    af.add_argument("--summary", action="store_true", help="dry run: counts only, without the per-day list")
    # 1.2.13: history sync (data/history_sync.py)
    sr_ = sub.add_parser("sync-runs", help="1.2.13: the latest D-1 / backfill / rollback / release runs with their counts")
    sr_.add_argument("--limit", type=int, default=20)
    rb = sub.add_parser("sync-rollback", help="1.2.13: restore the stored rows of one run as they were before it (dry run "
                                             "unless --apply; an online backup first)")
    rb.add_argument("--run", required=True, help="run id (D1L-... / HRL-...) from sync-runs")
    rb.add_argument("--apply", action="store_true")
    hl = sub.add_parser("held-lines", help="1.2.13: order lines kept although the source dropped them - summary, or an "
                                          "explicit owner release (dry run unless --apply)")
    hl.add_argument("--release", action="store_true", help="release the matching ACTIVE held lines (owner decision)")
    hl.add_argument("--cause", choices=["ORDER_GONE", "LINE_GONE", "PENDING_GONE", "QTY_REDUCED", "NO_EVIDENCE"])
    hl.add_argument("--sku")
    hl.add_argument("--from", dest="start")
    hl.add_argument("--to", dest="end")
    hl.add_argument("--apply", action="store_true")
    sub.add_parser("history-check", help="1.2.13: compare the stored history before the D-1 window with the source now "
                                         "(read-only BigQuery; records the day checks)")
    ap_ = sub.add_parser("apply-preset", help="1.3.1: settings of a release preset (dry run unless --apply)")
    ap_.add_argument("name", choices=sorted(PRESETS))
    ap_.add_argument("--apply", action="store_true", help="save the settings and switch the preset's flows ON")
    ap_.add_argument("--feature-set", dest="feature_set", choices=sorted(FEATURE_SETS), default="CHOT",
                     help="1.3.2: model.feature_set of the preset (CHOT = the 1.3.1 preset unchanged)")
    # 1.3.2: deal source and historical open hours (docs/hoc_lai_2025_deal_20261030.md); dry run unless --apply
    dl = sub.add_parser("deal-lines-load", help="1.3.2: order-line deal codes into demand_deal_daily, per calendar month")
    dl.add_argument("--start", required=True)
    dl.add_argument("--end", required=True)
    dl.add_argument("--apply", action="store_true")
    dl.add_argument("--max-bytes", dest="max_bytes", type=int)
    dl.add_argument("--allow-empty", dest="allow_empty", action="store_true",
                    help="replace stored lines of a month by a read without any deal-code line (default: refused)")
    dr = sub.add_parser("deal-refresh", help="1.3.2: read the deal table into one snapshot + deals")
    dr.add_argument("--apply", action="store_true")
    dr.add_argument("--max-bytes", dest="max_bytes", type=int)
    dk = sub.add_parser("deal-check", help="1.3.2: read-only checks of the stored deals and deal lines")
    dk.add_argument("--start")
    dk.add_argument("--end")
    oh = sub.add_parser("open-hours-load", help="1.3.2: historical open hours in reads of at most 15 days")
    oh.add_argument("--start", required=True)
    oh.add_argument("--end", required=True)
    oh.add_argument("--apply", action="store_true")
    oh.add_argument("--max-bytes", dest="max_bytes", type=int)
    a = ap.parse_args(argv)
    from . import paths
    try:
        return _run(a)
    except paths.StorageError as e:
        print(json.dumps({"ok": False, "code": e.code, "detail": e.detail}, ensure_ascii=False))
        return 3


def _history_cmd(a) -> int:
    """1.2.13 history-sync commands on the configured database (data/history_sync.py)."""
    from . import db, paths
    from . import settings_service as ss
    from .data import history_sync
    from .data.demand import bigquery_scope_key
    from .messages import AppError
    paths.ensure_storage()
    # never migrates: run from a newer source tree against an older installation, a migration would make the installed
    # version refuse its own database. The commands need the history-sync tables (schema 10, 1.2.13).
    with db.read() as c:
        ver = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] \
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone() else None
    if (ver or 0) < 10:
        print(json.dumps({"ok": False, "refused": f"database schema {ver}: the history-sync commands need schema 10 "
                                                  "(release 1.2.13 installed); nothing was changed"}, ensure_ascii=False))
        return 2
    scope_key = bigquery_scope_key(ss.get("bigquery"))
    try:
        if a.cmd == "sync-runs":
            with db.read() as c:
                runs = db.rows(c, "SELECT id, kind, status, window_start, window_end, policy, source_version, started_at, "
                                  "finished_at, summary_json, backup, rolled_back_by FROM demand_sync_runs WHERE scope_key=? "
                                  "ORDER BY started_at DESC, rowid DESC LIMIT ?", (scope_key, a.limit))
            for r in runs:
                r["summary"] = json.loads(r.pop("summary_json") or "{}")
            res = {"ok": True, "scope_key": scope_key, "runs": runs}
        elif a.cmd == "sync-rollback":
            res = {"ok": True, **history_sync.rollback(a.run, apply=a.apply)}
        elif a.cmd == "held-lines":
            if a.release:
                res = {"ok": True, **history_sync.release_holds(scope_key, a.cause, a.sku, a.start, a.end, apply=a.apply)}
            else:
                with db.read() as c:
                    rows = db.rows(c, "SELECT cause, status, COUNT(*) AS lines, TOTAL(qty) AS units, COUNT(DISTINCT "
                                      "order_date || '|' || sku_id || '|' || fc_id) AS keys, MIN(order_date) AS first_day, "
                                      "MAX(order_date) AS last_day FROM demand_held_lines WHERE scope_key=? GROUP BY 1, 2 "
                                      "ORDER BY 1, 2", (scope_key,))
                res = {"ok": True, "scope_key": scope_key, "policy": history_sync.policy(), "held_lines": rows}
        else:
            from datetime import date, timedelta
            from .bq import connector, sql_sources
            bq = ss.get("bigquery")
            with db.read() as c:
                st = c.execute("SELECT value_json FROM sync_state WHERE name=?", (f"last_d1_sync:{scope_key}",)).fetchone()
            ws = json.loads(st[0]).get("window_start") if st else None
            if not ws:
                print(json.dumps({"ok": False, "refused": "no D-1 load recorded yet"}, ensure_ascii=False))
                return 2
            floor = connector.read_range(bq)[0]
            end = date.fromisoformat(ws) - timedelta(days=1)
            res = {"ok": True, **history_sync.day_check(scope_key, str(floor), str(end), sql_sources.snapshot("history"),
                                                        "CLI")}
    except AppError as e:
        print(json.dumps({"ok": False, "code": e.code, "detail": e.detail, "params": e.params}, indent=2, default=str,
                         ensure_ascii=False))
        return 2
    print(json.dumps(res, indent=2, default=str, ensure_ascii=False))
    return 0


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
    if a.cmd == "eod-retention" and not a.apply:
        from pathlib import Path
        from . import eod_retention
        target = Path(a.db) if a.db else paths.db_path()
        if not target.exists():
            print(json.dumps({"ok": False, "code": "STORAGE_NOT_FOUND", "detail": str(target)}, ensure_ascii=False))
            return 3
        res = eod_retention.dry_run(target)
        print(json.dumps({"ok": not res["refused"], **res}, indent=2, default=str, ensure_ascii=False))
        return 2 if res["refused"] else 0
    if a.cmd == "actual-finalize" and not a.apply:
        from pathlib import Path
        from . import actual_final
        target = Path(a.db) if a.db else paths.db_path()
        if not target.exists():
            print(json.dumps({"ok": False, "code": "STORAGE_NOT_FOUND", "detail": str(target)}, ensure_ascii=False))
            return 3
        res = actual_final.dry_run(target, items=not a.summary)
        print(json.dumps({"ok": True, "dry_run": True, **res}, indent=2, default=str, ensure_ascii=False))
        return 0
    if a.cmd == "storage-init":
        cfg = paths.init_storage_config(a.data_dir, a.logs_dir, a.backups_dir, a.reports_dir)
        paths.ensure_storage()
        from . import db
        db.migrate()
        print(json.dumps({"ok": True, "config": cfg, "paths": paths.describe()}, indent=2, ensure_ascii=False))
        return 0
    if a.cmd == "apply-preset":
        return _apply_preset(a)
    if a.cmd in ("deal-lines-load", "deal-refresh", "deal-check", "open-hours-load"):
        return _deal_cmd(a)

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
    elif a.cmd in ("attest-training-data", "product-names-refresh"):
        from .messages import AppError
        try:
            if a.cmd == "attest-training-data":
                from .data import identity
                res = identity.attest_from_backup(a.training_run, a.backup)
            else:
                from .bq import product_names
                res = product_names.refresh()
        except AppError as e:
            print(json.dumps({"ok": False, "code": e.code, "detail": e.detail}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, **res}, indent=2, ensure_ascii=False, default=str))
    elif a.cmd == "history-reconcile":
        db.migrate()
        from . import forecast_history
        res = forecast_history.reconcile()
        print(json.dumps({"ok": not res["errors"], **res}, indent=2, ensure_ascii=False, default=str))
        return 1 if res["errors"] else 0
    elif a.cmd == "actual-finalize":               # --apply (the dry run is handled above, read-only)
        if a.db:
            print(json.dumps({"ok": False, "refused": "--apply works on the configured database only"},
                             ensure_ascii=False))
            return 2
        db.migrate()
        from . import actual_final
        with db.read() as c:
            scopes = actual_final.d1_scopes(c)
        res = [actual_final.finalize(sk, "BIGQUERY", by="CLI") for sk in scopes]
        print(json.dumps({"ok": not any(r["errors"] for r in res), "scopes": res}, indent=2, default=str,
                         ensure_ascii=False))
        return 1 if any(r["errors"] for r in res) else 0
    elif a.cmd == "eod-retention":                 # --apply (the dry run is handled above, read-only)
        from . import eod_retention
        from .messages import AppError
        if a.db or not a.plan:
            print(json.dumps({"ok": False, "refused": "--apply works on the configured database only and needs "
                                                      "--plan <plan_id> from a reviewed dry run"}, ensure_ascii=False))
            return 2
        paths.ensure_storage()
        try:
            res = eod_retention.apply(a.plan)
        except AppError as e:
            print(json.dumps({"ok": False, "code": e.code, "detail": e.detail}, ensure_ascii=False))
            return 2
        print(json.dumps({"ok": not res["error"], **res}, indent=2, ensure_ascii=False, default=str))
        return 1 if res["error"] else 0
    elif a.cmd in ("sync-runs", "sync-rollback", "held-lines", "history-check"):
        return _history_cmd(a)
    elif a.cmd == "info":
        from . import __version__
        print(json.dumps({"version": __version__, "data_dir": str(paths.data_dir()), "db": str(paths.db_path()),
                          "frontend": str(paths.frontend_dist())}, indent=2))
    return 0


# 1.3.1 PHUONG AN CHOT (docs/ke_hoach_lgbm_chot.md section 1): the settings a release sets once at deployment
PRESET_NOTE = "PRESET lgbm-chot 1.3.1 (PHUONG AN CHOT)"
PRESETS = {"lgbm-chot": {
    "sections": {
        "model": {"feature_sku_code": False, "horizon_weight_short": 3.0, "horizon_weight_cutoff": 7,
                  "fallback_enabled": False},
        # trial_mode is left as stored (True by default): only its own confirmed endpoint changes it
        "daily_forecast": {"enabled": True, "rounding_threshold": 0.2, "log_retention_days": 120,
                           "report_subdir": "theo-doi"}},
    "flows": ("refresh", "report")}}
# 1.3.2 (docs/hoc_lai_2025_deal_20261030.md 1.2): --feature-set of lgbm-chot, merged into the preset sections. CHOT adds
# nothing (the 1.3.1 preset); the CHOT_LY* sets need data_policy.extended_history_start_date (refused otherwise)
DEAL_TABLE_ID = "lakehouse-prod-394907.gold_buymed_vn2.demand_planing_deal"
FEATURE_SETS = {"CHOT": {},
                "CHOT_LY": {"model": {"feature_set": "CHOT_LY"}},
                "CHOT_LY_DEAL": {"model": {"feature_set": "CHOT_LY_DEAL"},
                                 "bigquery": {"deal_code_column": "deal_code", "deal_table_id": DEAL_TABLE_ID}}}


def _codes(reasons) -> list[dict]:
    return [{"code": x.get("code"), "detail": x.get("detail")} for x in reasons or []]


def _apply_preset(a) -> int:
    """1.3.1 `apply-preset <name> [--apply]`. Dry run (default): the planned changes and the readiness of the flows,
    read-only. --apply: each section saved once through settings_service (validated, history note PRESET_NOTE), then
    the flows switched ON through flows.update_flow exactly as PUT /api/schedules/{flow} (readiness, *_enabled_at); a
    flow that is not ready is reported, never forced. Idempotent: a second --apply saves nothing. Never touches
    storage.json, the active source or the other flows. Exit 0 ok, 1 a flow not ready, 2 refused."""
    from . import db, paths
    from . import settings_service as ss
    from .jobs import flows
    from .messages import AppError
    fs = getattr(a, "feature_set", None) or "CHOT"
    preset = {**PRESETS[a.name], "sections": {s: dict(v) for s, v in PRESETS[a.name]["sections"].items()}}
    for s, vals in FEATURE_SETS[fs].items():          # 1.3.2: --feature-set (CHOT: nothing added)
        preset["sections"][s] = {**preset["sections"].get(s, {}), **vals}
    warnings: list[dict] = []
    with db.read() as c:
        try:
            schema = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
        except Exception:  # noqa: BLE001 - no migration table: an empty or foreign database
            schema = 0
        cur = {s: ss.get(s, c) for s in preset["sections"]}
        ext = ss.get("data_policy", c).extended_history_start_date
        if fs == "CHOT_LY_DEAL":
            # the deal refresh needs deal_table_id saved first: an empty deals table is reported, never refused
            try:
                n_deals = c.execute("SELECT COUNT(*) FROM deals WHERE source_table=?", (DEAL_TABLE_ID,)).fetchone()[0]
            except Exception:  # noqa: BLE001 - database before schema 12 (refused below at --apply)
                n_deals = 0
            if not n_deals:
                warnings.append({"code": "DEAL_SOURCE_EMPTY", "source_table": DEAL_TABLE_ID,
                                 "detail": "no deal stored yet: run 'deal-refresh --apply' (and 'deal-lines-load') "
                                           "before training with CHOT_LY_DEAL"})
    latest = max(v for v, _ in db.available_migrations())
    changes = [{"section": s, "key": k, "from": getattr(cur[s], k), "to": v}
               for s, vals in preset["sections"].items() for k, v in vals.items() if getattr(cur[s], k) != v]
    new = {s: {**cur[s].model_dump(), **vals} for s, vals in preset["sections"].items()}
    out = {"preset": a.name, "feature_set": fs, "dry_run": not a.apply, "schema_version": schema,
           "schema_required": latest, "warnings": warnings}

    def _refuse(why: str) -> int:
        print(json.dumps({"ok": False, **out, "refused": why, "changes": changes}, indent=2, ensure_ascii=False,
                         default=str))
        return 2
    if fs != "CHOT" and not ext:
        return _refuse(f"feature set {fs} needs data_policy.extended_history_start_date (the same-period-last-year "
                       "features read the stored demand from it): set it first; nothing was saved")
    try:
        for s, v in new.items():
            ss.SECTIONS[s].model_validate(v)        # nothing is saved unless every section is valid
    except ValueError as e:
        return _refuse(f"{type(e).__name__}: {e}"[:800])
    if not a.apply:
        res = []
        for f in preset["flows"]:
            on = bool(getattr(ss.get("schedule"), flows.FLOWS[f]["flag"]))
            # the preset switches daily_forecast ON before its flows: that reason goes away with it
            reasons = [x for x in flows.readiness(f)["reasons"]
                       if not (x.get("code") == "DAILY_FORECAST_DISABLED" and new["daily_forecast"]["enabled"])]
            res.append({"flow": f, "from": on, "to": on or not reasons, "ready": not reasons, "reasons": _codes(reasons)})
        print(json.dumps({"ok": True, **out, "changes": changes, "flows": res,
                          "changed": bool(changes or any(r["to"] != r["from"] for r in res))},
                         indent=2, ensure_ascii=False, default=str))
        return 0
    from .logging_setup import setup_logging
    setup_logging()
    paths.ensure_storage()
    if schema < latest:
        return _refuse(f"database schema {schema} is older than {latest}: start the new version once (it migrates) "
                       "before applying the preset")
    if changes:
        with db.tx() as c:
            for s in preset["sections"]:
                if any(ch["section"] == s for ch in changes):
                    ss.save(s, new[s], note=PRESET_NOTE, conn=c)
            db.audit(c, "PRESET_APPLIED", "settings", a.name, {"changes": changes})
    res = []
    for f in preset["flows"]:
        if getattr(ss.get("schedule"), flows.FLOWS[f]["flag"]):
            r = flows.readiness(f)
            res.append({"flow": f, "from": True, "to": True, "ready": r["ready"], "reasons": _codes(r["reasons"])})
            continue
        try:
            flows.update_flow(f, {"enabled": True})
            res.append({"flow": f, "from": False, "to": True, "ready": True, "reasons": []})
        except AppError as e:
            res.append({"flow": f, "from": False, "to": False, "ready": False,
                        "reasons": _codes(e.params.get("reasons") or [{"code": e.code, "detail": e.detail}])})
    changed = bool(changes or any(r["to"] != r["from"] for r in res))
    print(json.dumps({"ok": True, **out, "changes": changes, "flows": res, "changed": changed,
                      "message": None if changed else "nothing to change: the preset is already applied"},
                     indent=2, ensure_ascii=False, default=str))
    return 1 if any(not r["to"] for r in res) else 0


def _spans(s, e, days: int) -> list[tuple]:
    """[s, e] split into chunks of at most `days` days, oldest first."""
    from datetime import timedelta
    out = []
    while s <= e:
        ce = min(e, s + timedelta(days=days - 1))
        out.append((s, ce))
        s = ce + timedelta(days=1)
    return out


OPEN_HOURS_LOAD_DAYS = 15


def _open_hours_sql(table: str) -> str:
    # the text of aux_sources.fetch_open_hours (dry run of a chunk only; the load itself goes through that function)
    return (f"SELECT fc_code, sku_code, CAST(open_date AS STRING) AS open_date, MAX(total_open_hours) AS total_open_hours, "
            f"COUNT(DISTINCT item_code) AS n_items FROM `{table}` "
            f"WHERE open_date BETWEEN @start AND @end AND seller_code = @seller "
            f"AND fc_code IS NOT NULL AND sku_code IS NOT NULL GROUP BY fc_code, sku_code, open_date "
            f"ORDER BY open_date, fc_code, sku_code")


def _chunk_failed(out: dict, cs, ce, est, code: str, detail) -> dict:
    out["chunks"].append({"start": str(cs), "end": str(ce), "status": "FAILED", "estimated_bytes": est,
                          "error": {"code": code, "detail": detail}})
    out.update(ok=False, stopped_at=str(cs))
    return out


def _deal_cmd(a) -> int:
    """1.3.2 deal source / historical open-hours commands on the configured database. One JSON object; exit 0 ok,
    1 a chunk / the read failed (the chunks before it stay written), 2 refused (nothing written; --apply while the app
    runs or a job is active is refused)."""
    from datetime import date, timedelta
    from . import db, paths, sync
    from . import settings_service as ss
    from .bq import aux_sources, connector, deal_lines, deal_source, sql_sources
    from .data.demand import bigquery_scope_key
    from .logging_setup import setup_logging
    from .messages import AppError
    from .timeutil import today_vn
    setup_logging()
    paths.ensure_storage()

    def _print(obj, rc: int) -> int:
        print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))
        return rc

    def _refuse(why: str) -> int:
        return _print({"ok": False, "command": a.cmd, "refused": why}, 2)
    # never migrates (as the history-sync commands): the tables of migration 0012 are needed
    with db.read() as c:
        ver = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] \
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone() else None
    if (ver or 0) < 12:
        return _refuse(f"database schema {ver}: these commands need schema 12 (release 1.3.2 installed); nothing was "
                       "changed")
    bq = ss.get("bigquery")
    scope_key = bigquery_scope_key(bq)
    if a.cmd == "deal-check":
        return _print(deal_source.checks(scope_key, a.start, a.end), 0)
    if a.apply:
        # a write runs only while the app is stopped and no job is active (as restore / storage-migrate): the app's
        # own D-1 / backfill writes the same tables
        from .jobs.flows import ACTIVE_STATUSES
        from .storage_migrate import app_running
        rt = app_running()
        if rt:
            return _refuse(f"the app appears to be running (pid {rt.get('pid')}, port {rt.get('port')}): stop it first; "
                           "nothing was changed")
        with db.read() as c:
            act = db.one(c, f"SELECT id, job_type, status FROM job_runs WHERE status IN "
                            f"({','.join('?' * len(ACTIVE_STATUSES))}) ORDER BY created_at DESC, rowid DESC LIMIT 1",
                         ACTIVE_STATUSES)
        if act:
            return _refuse(f"job {act['id']} ({act['job_type']}) is {act['status']}: wait until no job is active; "
                           "nothing was changed")
    try:
        if a.cmd == "deal-refresh":
            if not bq.deal_table_id:
                return _refuse("bigquery.deal_table_id is not set")
            if not a.apply:
                return _print({"ok": True, "command": a.cmd, "dry_run": True, **deal_source.estimate(a.max_bytes)}, 0)
            return _print({"ok": True, "command": a.cmd, "dry_run": False,
                           **deal_source.refresh("MANUAL", max_bytes=a.max_bytes)}, 0)
        try:
            s, e = date.fromisoformat(a.start), date.fromisoformat(a.end)
        except ValueError as ex:
            return _refuse(f"dates must be YYYY-MM-DD: {ex}")
        day = today_vn() - timedelta(days=1)          # yesterday on the Vietnam calendar: today is never read
        if a.cmd == "deal-lines-load":
            if not bq.deal_code_column:
                return _refuse("bigquery.deal_code_column is not set")
            if not connector.validation_ok_for_current():
                return _refuse("the BigQuery validation is not current for the saved mapping (BQ_VALIDATION_REQUIRED)")
            s, e = max(s, sync.backfill_floor(bq, day)), min(e, day)
            if e < s:
                return _refuse(f"empty window {s}..{e} (from the backfill floor to yesterday)")
            out = {"ok": True, "command": a.cmd, "dry_run": not a.apply, "scope_key": scope_key,
                   "window": {"start": str(s), "end": str(e)}, "chunks": []}
            snap = sql_sources.snapshot("history")
            for cs, ce in deal_lines.months(s, e):
                if not a.apply:
                    est = deal_lines.estimate(cs, ce, snap)
                    out["chunks"].append({"start": str(cs), "end": str(ce), "estimated_bytes": est,
                                          "above_max_bytes": a.max_bytes is not None and est > a.max_bytes})
                    continue
                try:
                    r = deal_lines.load_window(scope_key, cs, ce, "MANUAL", snap=snap,
                                               version=sync._source_version(snap), max_bytes=a.max_bytes,
                                               allow_empty=a.allow_empty)
                except AppError as ex:
                    return _print(_chunk_failed(out, cs, ce, ex.params.get("estimated_bytes"), ex.code, ex.detail), 1)
                out["chunks"].append({"start": str(cs), "end": str(ce), "status": "SUCCEEDED",
                                      **{k: r[k] for k in ("load_id", "estimated_bytes", "rows_written", "rows_removed",
                                                           "qty", "lines_read", "qty_read")}})
            return _print(out, 0)
        # open-hours-load
        cfg = ss.get("daily_forecast")
        table, seller = aux_sources.open_hours_source(cfg)
        if not table:
            return _refuse("daily_forecast.openhours_table is not set")
        e = min(e, day)
        if e < s:
            return _refuse(f"empty window {s}..{e} (at most yesterday)")
        out = {"ok": True, "command": a.cmd, "dry_run": not a.apply, "source_table": table, "seller_code": seller,
               "window": {"start": str(s), "end": str(e)}, "chunks": []}
        client = connector._client(bq)
        modified = aux_sources.source_modified(cfg, bq) if a.apply else None
        for cs, ce in _spans(s, e, OPEN_HOURS_LOAD_DAYS):
            params = [("start", "DATE", cs), ("end", "DATE", ce), ("seller", "STRING", seller)]
            if not a.apply or a.max_bytes is not None:
                est = connector._run(client, bq, "daily_open_hours", _open_hours_sql(table), params,
                                     dry_run_only=True)["estimated_bytes"]
                if not a.apply:
                    out["chunks"].append({"start": str(cs), "end": str(ce), "estimated_bytes": est,
                                          "above_max_bytes": a.max_bytes is not None and est > a.max_bytes})
                    continue
                if est > a.max_bytes:
                    return _print(_chunk_failed(out, cs, ce, est, "BQ_QUERY_TOO_EXPENSIVE",
                                                f"{est} bytes > --max-bytes {a.max_bytes}"), 1)
            # the incremental watermark of the daily refresh (last_day of the latest completed read) never moves back:
            # the recorded last_day is max(days of this chunk, that last_day)
            with db.read() as c:
                done = aux_sources.last_completed_read(c, aux_sources.KIND_OPEN_HOURS, table, seller)
            try:
                r = aux_sources.fetch_open_hours(cs, ce, cfg, bq, source_modified=modified,
                                                 last_day=done["last_day"] if done else None)
            except AppError as ex:
                return _print(_chunk_failed(out, cs, ce, ex.params.get("estimated_bytes"), ex.code, ex.detail), 1)
            out["chunks"].append({"start": str(cs), "end": str(ce), "status": "SUCCEEDED",
                                  **{k: r[k] for k in ("rows", "estimated_bytes", "last_day", "kept_on_conflict")}})
        return _print(out, 0)
    except AppError as ex:
        return _print({"ok": False, "command": a.cmd, "code": ex.code, "detail": ex.detail, "params": ex.params}, 1)


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
    if sys.platform != "win32":
        # Linux VPS (systemd): signal 0 only checks that the process exists. Never on Windows, where os.kill(pid, 0)
        # sends CTRL_C_EVENT.
        try:
            os.kill(int(pid), 0)
            return True
        except PermissionError:          # exists, owned by another user
            return True
        except (OSError, ValueError):
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
