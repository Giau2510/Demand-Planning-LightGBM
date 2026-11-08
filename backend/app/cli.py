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
  sel2-openhours-backfill [--start D] [--end D] [--yes]     1.4.0: open-hours history from BigQuery (read-only)
  sel2-train --origin D [--yes]             1.4.0: LightGBM candidates of a weekly origin (finished models skipped)
  sel2-day [--date D] [--force] [--yes]     1.4.0: candidates + SEL2 + publication of a forecast day
  sel2-replay --from D --to D --out DIR [--group-mode FIXED --group-start D --group-end D]
              [--history-start-rule BACKTEST] [--copy-ok] [--yes]   1.4.0: reproduction on a DB COPY (no
                                            publication); with --yes refused unless the database folder holds
                                            copy_info.json (copy marker) or --copy-ok states that it is a copy
  sel2-bootstrap [--days 28] [--yes]        1.4.0: first start (today's trainings, temporary Excel
                                            du_bao_YYYYMMDD_TAM.xlsx with V33_L112, other trainings, past
                                            candidates, today)
  sel2-export --date D [--yes]              1.4.0: a new version of the daily Excel of forecast day D
  sel2-published-backfill --start D --end D [--yes]   1.4.4: the history sidecar files (horizon 1) of days
                                            exported before 1.4.4, built from the newest recorded Excel of each
                                            day (xlsx only read, sha256 checked); without --yes only counted
                                            sel2-*: without --yes only the database path and the plan
                                            sel2-train / sel2-day: [--trigger T] [--job-id ID] recorded with the
                                            runs (default trigger cli; the app's jobs pass their own)
                                            sel2-* / sel2-export: an unexpected error prints {ok: false, code
                                            SEL2_INTERNAL_ERROR (SEL2_LOW_MEMORY for MemoryError), detail}, exit 1
  spike-lines --date D [--initial] [--dry-run] [--yes]   1.4.8: SO lines of the BIGQUERY scope into so_lines_cache
                                            (read-only BigQuery, < 5 GB per query), spike flags + excess of day D
                                            (spike_lines.py). --dry-run: the BigQuery dry run only (estimated bytes);
                                            without --yes: the database path and the read range only
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
    # 1.4.0 SEL2: AVG_DEMAND read from BigQuery (read-only) into avg_demand_daily (ml/sel2/avg_demand.py)
    sar = sub.add_parser("sel2-avg-read", help="1.4.0: read AVG_DEMAND from BigQuery (current snapshot for --date, or "
                                               "the historical days) into the configured database (plan only unless --yes)")
    sar.add_argument("--date", help="business day (Vietnam, YYYY-MM-DD) the current snapshot is stored as")
    sar.add_argument("--hist-from", help="first day of the historical table (YYYY-MM-DD)")
    sar.add_argument("--hist-to", help="last day of the historical table (YYYY-MM-DD)")
    sar.add_argument("--yes", action="store_true", help="read and store (without it: the plan only, nothing read)")
    # 1.4.0 SEL2 pipeline (ml/sel2/pipeline.py); every command writes: without --yes the database path and the plan
    s2o = sub.add_parser("sel2-openhours-backfill", help="1.4.0: read the open-hours history from BigQuery (read-only)")
    s2o.add_argument("--start", help="first day (default sel2_pipeline.open_hours_history_start)")
    s2o.add_argument("--end", help="last day (default yesterday)")
    s2t = sub.add_parser("sel2-train", help="1.4.0: train the LightGBM candidates of a weekly origin")
    s2t.add_argument("--origin", required=True, help="training origin (the retraining weekday, YYYY-MM-DD)")
    s2d = sub.add_parser("sel2-day", help="1.4.0: candidates + SEL2 + publication of a forecast day")
    s2d.add_argument("--date", help="forecast day (default today, Vietnam)")
    s2d.add_argument("--force", action="store_true", help="compute and publish again an already published day")
    s2r = sub.add_parser("sel2-replay", help="1.4.0: reproduction on a DB COPY (no publication, parquet files)")
    s2r.add_argument("--from", dest="date_from", required=True)
    s2r.add_argument("--to", dest="date_to", required=True)
    s2r.add_argument("--out", required=True, help="output folder of the parquet files")
    s2r.add_argument("--group-mode", choices=["ROLLING_B7", "FIXED"])
    s2r.add_argument("--group-start")
    s2r.add_argument("--group-end")
    s2r.add_argument("--history-start-rule", choices=["BACKTEST"])
    s2r.add_argument("--copy-ok", action="store_true",
                     help="the configured database is a COPY (needed with --yes when its folder has no copy_info.json)")
    s2b = sub.add_parser("sel2-bootstrap", help="1.4.0: first start (today's trainings + temporary V33_L112 Excel _TAM, "
                                                  "then trainings + candidates of the last days + today)")
    s2b.add_argument("--days", type=int, default=28, help="past days replayed (1..120, default 28)")
    for p_ in (s2o, s2t, s2d, s2r, s2b):
        p_.add_argument("--yes", action="store_true", help="run (without it: the database path and the plan only)")
    for p_ in (s2t, s2d):       # the app's jobs (ml/sel2/jobs.py) pass the job row's trigger and id
        p_.add_argument("--trigger", default="cli", help="trigger recorded with the runs / exports (default cli)")
        p_.add_argument("--job-id", default=None, help="job id recorded with the runs / trainings / exports")
    # 1.4.0 SEL2 daily Excel (ml/sel2/export.py)
    s2x = sub.add_parser("sel2-export", help="1.4.0: write a new version of the daily Excel of a forecast day")
    s2x.add_argument("--date", required=True, help="forecast day (Vietnam, YYYY-MM-DD)")
    s2x.add_argument("--yes", action="store_true", help="write (without it: the database path and the target file)")
    # 1.4.4 history rows of days exported before 1.4.4 (ml/sel2/published.py)
    s2p = sub.add_parser("sel2-published-backfill", help="1.4.4: create the missing history sidecars of past exports")
    s2p.add_argument("--start", required=True, help="first forecast day (YYYY-MM-DD)")
    s2p.add_argument("--end", required=True, help="last forecast day (YYYY-MM-DD)")
    s2p.add_argument("--yes", action="store_true", help="write (without it: counts only, nothing written)")
    # 1.4.8 SO-line cache + spike flags (spike_lines.py)
    spl = sub.add_parser("spike-lines", help="1.4.8: SO lines (BigQuery, read-only) + spike flags + excess of a day")
    spl.add_argument("--date", required=True, help="the run day D (data up to D-1, YYYY-MM-DD)")
    spl.add_argument("--initial", action="store_true", help="read the whole cache window (210 days) again")
    spl.add_argument("--dry-run", action="store_true", help="BigQuery dry run only: estimated bytes, nothing written")
    spl.add_argument("--yes", action="store_true", help="read and write (without it: the plan only)")
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
    if a.cmd == "sel2-export":
        return _sel2_export(a)
    if a.cmd == "sel2-published-backfill":
        return _sel2_published_backfill(a)
    if a.cmd == "spike-lines":
        return _spike_lines(a)
    if a.cmd.startswith("sel2-") and a.cmd != "sel2-avg-read":
        return _sel2(a)
    if a.cmd == "sel2-avg-read":
        return _sel2_avg_read(a)

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


def _codes(reasons) -> list[dict]:
    return [{"code": x.get("code"), "detail": x.get("detail")} for x in reasons or []]


def _sel2_avg_read(a) -> int:
    """1.4.0 `sel2-avg-read --date D | --hist-from D1 --hist-to D2 [--yes]` on the configured database. Without --yes:
    the database path and the plan, nothing read or written. Never migrates (needs schema 12). Exit 0 ok, 1 the read
    failed (nothing recorded), 2 refused."""
    from datetime import date
    from . import db, paths
    from . import settings_service as ss
    from .messages import AppError
    from .ml.sel2 import avg_demand
    paths.ensure_storage()
    out = {"db": str(paths.db_path()), "dry_run": not a.yes}

    def _refuse(why: str) -> int:
        print(json.dumps({"ok": False, **out, "refused": why}, indent=2, ensure_ascii=False, default=str))
        return 2
    hist = bool(a.hist_from or a.hist_to)
    if bool(a.date) == hist or (hist and not (a.hist_from and a.hist_to)):
        return _refuse("give either --date or both --hist-from and --hist-to")
    try:
        days = [date.fromisoformat(x) for x in ((a.hist_from, a.hist_to) if hist else (a.date,))]
    except ValueError:
        return _refuse("dates must be YYYY-MM-DD")
    if not hist:
        try:                                    # the current snapshot is today's table only
            avg_demand.require_today(days[0])
        except AppError as e:
            print(json.dumps({"ok": False, **out, "refused": "--date must be today (Vietnam); a past day: "
                              "--hist-from D1 --hist-to D2", **e.to_dict()}, indent=2, ensure_ascii=False, default=str))
            return 2
    with db.read() as c:
        try:
            schema = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
        except Exception:  # noqa: BLE001 - no migration table
            schema = 0
        cfg = ss.get("sel2_pipeline", c) if schema >= 12 else None
    out["schema_version"] = schema
    if schema < 12:
        return _refuse(f"database schema {schema}: the AVG_DEMAND tables need schema 12 (release 1.4.0); nothing was "
                       "changed")
    out.update(kind="HISTORICAL" if hist else "CURRENT",
               table=cfg.avg_demand_hist_table if hist else cfg.avg_demand_table,
               range=[d.isoformat() for d in days], seller_rule=cfg.avg_seller_rule)
    if not cfg.enabled:
        return _refuse("sel2_pipeline.enabled = False (1.3.1 mode): nothing is written")
    if not a.yes:
        print(json.dumps({"ok": True, **out, "note": "plan only: add --yes to read and store"}, indent=2,
                         ensure_ascii=False))
        return 0
    try:
        res = avg_demand.read_historical(days[0], days[1], cfg) if hist else avg_demand.read_current(days[0], cfg)
    except AppError as e:
        print(json.dumps({"ok": False, **out, **e.to_dict()}, indent=2, ensure_ascii=False, default=str))
        return 1
    print(json.dumps({"ok": True, **out, "result": res}, indent=2, ensure_ascii=False, default=str))
    return 0


def _sel2_export(a) -> int:
    """1.4.0 `sel2-export --date D [--yes]` on the configured database. Without --yes: the database path, the target
    file and the versions already written, nothing written. Never migrates (needs schema 12). Exit 0 ok, 1 failed
    (AppError printed), 2 refused."""
    from datetime import date
    from . import db, paths
    from . import settings_service as ss
    from .messages import AppError
    paths.ensure_storage()
    out = {"db": str(paths.db_path()), "dry_run": not a.yes}

    def _refuse(why: str) -> int:
        print(json.dumps({"ok": False, **out, "refused": why}, indent=2, ensure_ascii=False, default=str))
        return 2
    try:
        d = date.fromisoformat(a.date)
    except ValueError:
        return _refuse("--date must be YYYY-MM-DD")
    with db.read() as c:
        try:
            schema = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
        except Exception:  # noqa: BLE001 - no migration table
            schema = 0
        cfg = ss.get("sel2_pipeline", c) if schema >= 12 else None
    out["schema_version"] = schema
    if schema < 12:
        return _refuse(f"database schema {schema}: the export needs schema 12 (release 1.4.0); nothing was changed")
    from .ml.sel2 import export
    try:
        folder, latest = export.file_names(d)
        out.update(forecast_date=d.isoformat(), target_file=str(export.export_root(cfg) / folder / latest),
                   versions=[r["version"] for r in export.runs(d)])
    except AppError as e:
        print(json.dumps({"ok": False, **out, **e.to_dict()}, indent=2, ensure_ascii=False, default=str))
        return 1
    if not cfg.enabled:
        return _refuse("sel2_pipeline.enabled = False (1.3.1 mode): nothing is written")
    if not a.yes:
        print(json.dumps({"ok": True, **out, "code": "SEL2_CONFIRM_REQUIRED", "note": "plan only: add --yes to write"},
                         indent=2, ensure_ascii=False, default=str))
        return 0
    try:
        res = export.write_daily_export(d, trigger="CLI")
    except AppError as e:
        print(json.dumps({"ok": False, **out, **e.to_dict()}, indent=2, ensure_ascii=False, default=str))
        return 1
    except Exception as e:  # noqa: BLE001 - printed as JSON for the job (never a bare traceback only)
        return _sel2_unexpected(out, e)
    print(json.dumps({"ok": True, **out, "result": res}, indent=2, ensure_ascii=False, default=str))
    return 0


def _sel2_published_backfill(a) -> int:
    """1.4.4 `sel2-published-backfill --start D --end D [--yes]` on the configured database (never migrates, never
    writes the database; writes only the sidecar files of ml/sel2/published.py). Exit 0 ok, 1 failed, 2 refused."""
    from datetime import date
    from . import db, paths
    paths.ensure_storage()
    out = {"db": str(paths.db_path()), "dry_run": not a.yes}
    try:
        s, e = date.fromisoformat(a.start), date.fromisoformat(a.end)
    except ValueError:
        print(json.dumps({"ok": False, **out, "refused": "--start / --end must be YYYY-MM-DD"}, indent=2))
        return 2
    if s > e or (e - s).days > 400:
        print(json.dumps({"ok": False, **out, "refused": "--start must not be after --end (at most 400 days)"}, indent=2))
        return 2
    with db.read() as c:
        schema = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
    out["schema_version"] = schema
    if schema < 12:
        print(json.dumps({"ok": False, **out, "refused": f"database schema {schema}: needs schema 12 (export_runs)"},
                         indent=2))
        return 2
    from .ml.sel2 import published
    try:
        res = published.backfill(s, e, apply=bool(a.yes))
    except Exception as ex:  # noqa: BLE001 - printed as JSON
        return _sel2_unexpected(out, ex)
    print(json.dumps({"ok": True, **out, "result": res}, indent=2, ensure_ascii=False, default=str))
    return 0


def _sel2_unexpected(out: dict, e: BaseException) -> int:
    """An exception that is not an AppError in a sel2-* command: {ok: false, code, detail} on stdout (MemoryError ->
    SEL2_LOW_MEMORY, retryable; anything else -> SEL2_INTERNAL_ERROR, not retried by the jobs), traceback on stderr."""
    import traceback
    from .messages import AppError
    traceback.print_exc(file=sys.stderr)
    code = "SEL2_LOW_MEMORY" if isinstance(e, MemoryError) else "SEL2_INTERNAL_ERROR"
    err = AppError(code, status=500, detail=f"{type(e).__name__}: {e}"[:1000])
    print(json.dumps({"ok": False, **out, **err.to_dict(), "code": code}, indent=2, ensure_ascii=False, default=str))
    return 1


def _sel2(a) -> int:
    """1.4.0 sel2-* commands on the configured database. Without --yes: the database path and the plan, nothing read
    from BigQuery or written. sel2-replay --yes runs only on a DB copy (copy_info.json next to app.db, or --copy-ok).
    Exit 0 ok, 1 failed (AppError or unexpected error printed as JSON), 2 refused."""
    from datetime import date
    from . import paths
    from .messages import AppError
    from .ml.sel2 import pipeline
    paths.ensure_storage()
    out = {"db": str(paths.db_path()), "command": a.cmd, "dry_run": not a.yes}
    try:
        day = (lambda v: date.fromisoformat(v) if v else None)
        args = {"sel2-openhours-backfill": lambda: {"start": day(a.start), "end": day(a.end)},
                "sel2-train": lambda: {"origin": day(a.origin), "trigger": a.trigger, "job_id": a.job_id},
                "sel2-day": lambda: {"date": day(a.date), "force": a.force, "trigger": a.trigger,
                                     "job_id": a.job_id},
                "sel2-replay": lambda: {"from": day(a.date_from), "to": day(a.date_to), "out": a.out,
                                        "group_mode": a.group_mode, "group_start": a.group_start,
                                        "group_end": a.group_end, "history_start_rule": a.history_start_rule},
                "sel2-bootstrap": lambda: {"days": a.days}}[a.cmd]()
    except ValueError:
        print(json.dumps({"ok": False, **out, "refused": "dates must be YYYY-MM-DD"}, indent=2, ensure_ascii=False))
        return 2
    out["args"] = args
    if a.cmd == "sel2-replay" and args["from"] > args["to"]:
        print(json.dumps({"ok": False, **out, "refused": "--from must not be after --to"}, indent=2, ensure_ascii=False, default=str))
        return 2
    if a.cmd == "sel2-bootstrap" and not 1 <= args["days"] <= 120:
        print(json.dumps({"ok": False, **out, "refused": "--days must be 1..120"}, indent=2, ensure_ascii=False, default=str))
        return 2
    if a.cmd == "sel2-replay":
        marker = paths.db_path().parent / "copy_info.json"
        out["copy_check"] = {"copy_info": str(marker), "marker_found": marker.exists(), "copy_ok_flag": a.copy_ok}
        if a.yes and not (marker.exists() or a.copy_ok):
            print(json.dumps({"ok": False, **out, "code": "SEL2_REPLAY_NOT_A_COPY",
                              "refused": "sel2-replay writes trainings and candidates: run it on a DB COPY (copy_info.json "
                                         "next to app.db, or --copy-ok)"}, indent=2, ensure_ascii=False, default=str))
            return 2
    if not a.yes:
        print(json.dumps({"ok": True, **out, "code": "SEL2_CONFIRM_REQUIRED", "note": "plan only: add --yes to run"},
                         indent=2, ensure_ascii=False, default=str))
        return 0
    from .logging_setup import setup_logging
    # the step lines of pipeline (seconds, private MB) go to <command>.log (e.g. sel2-day.log): never to stdout (the job
    # reads one JSON document there) and never to a file another process rotates (app.log of the server, or a sel2-day
    # next to a sel2-train: two rotating handlers on one file break rollover on Windows)
    setup_logging(console=False, filename=f"{a.cmd}.log")
    try:
        if a.cmd == "sel2-openhours-backfill":
            res = pipeline.openhours_backfill(args["start"], args["end"])
        elif a.cmd == "sel2-train":
            res = pipeline.train_week(args["origin"], job_id=args["job_id"])
        elif a.cmd == "sel2-day":
            res = pipeline.run_day(args["date"], trigger=args["trigger"], job_id=args["job_id"], force=args["force"])
        elif a.cmd == "sel2-replay":
            res = pipeline.replay(args["from"], args["to"], args["out"], args["group_mode"], args["history_start_rule"],
                                  args["group_start"], args["group_end"])
        else:
            res = pipeline.bootstrap(args["days"])
    except AppError as e:
        print(json.dumps({"ok": False, **out, **e.to_dict()}, indent=2, ensure_ascii=False, default=str))
        return 1
    except Exception as e:  # noqa: BLE001 - printed as JSON for the job (never a bare traceback only)
        return _sel2_unexpected(out, e)
    print(json.dumps({"ok": True, **out, "result": res}, indent=2, ensure_ascii=False, default=str))
    return 0


def _spike_lines(a) -> int:
    """1.4.8 `spike-lines --date D [--initial] [--dry-run] [--yes]` on the configured database. --dry-run: the
    BigQuery dry run of the line read (estimated bytes), nothing written; without --yes (and without --dry-run): the
    database path and the read range, nothing read or written. Exit 0 ok, 1 failed, 2 refused."""
    from datetime import date
    from . import paths
    from . import spike_lines
    from .messages import AppError
    paths.ensure_storage()
    out = {"db": str(paths.db_path()), "command": a.cmd, "dry_run": bool(a.dry_run or not a.yes)}
    try:
        d = date.fromisoformat(a.date)
    except ValueError:
        print(json.dumps({"ok": False, **out, "refused": "--date must be YYYY-MM-DD"}, indent=2, ensure_ascii=False))
        return 2
    out["args"] = {"date": str(d), "initial": a.initial}
    try:
        if not a.yes and not a.dry_run:
            sk = spike_lines._scope_key()
            first, start, end = spike_lines.read_range(sk, d, a.initial)
            print(json.dumps({"ok": True, **out, "code": "SEL2_CONFIRM_REQUIRED", "scope_key": sk,
                              "plan": {"cache_first_day": str(first), "read_start": str(start), "read_end": str(end)},
                              "note": "plan only: add --yes to run (or --dry-run for the BigQuery estimate)"},
                             indent=2, ensure_ascii=False, default=str))
            return 0
        from .logging_setup import setup_logging
        setup_logging(console=False, filename=f"{a.cmd}.log")
        res = spike_lines.run(d, initial=a.initial, dry_run=a.dry_run)
    except AppError as e:
        print(json.dumps({"ok": False, **out, **e.to_dict()}, indent=2, ensure_ascii=False, default=str))
        return 1
    except Exception as e:  # noqa: BLE001 - printed as JSON for the job (never a bare traceback only)
        return _sel2_unexpected(out, e)
    print(json.dumps({"ok": True, **out, "result": res}, indent=2, ensure_ascii=False, default=str))
    return 0


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
    preset = PRESETS[a.name]
    with db.read() as c:
        try:
            schema = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0
        except Exception:  # noqa: BLE001 - no migration table: an empty or foreign database
            schema = 0
        cur = {s: ss.get(s, c) for s in preset["sections"]}
    latest = max(v for v, _ in db.available_migrations())
    changes = [{"section": s, "key": k, "from": getattr(cur[s], k), "to": v}
               for s, vals in preset["sections"].items() for k, v in vals.items() if getattr(cur[s], k) != v]
    new = {s: {**cur[s].model_dump(), **vals} for s, vals in preset["sections"].items()}
    out = {"preset": a.name, "dry_run": not a.apply, "schema_version": schema, "schema_required": latest}

    def _refuse(why: str) -> int:
        print(json.dumps({"ok": False, **out, "refused": why, "changes": changes}, indent=2, ensure_ascii=False,
                         default=str))
        return 2
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
