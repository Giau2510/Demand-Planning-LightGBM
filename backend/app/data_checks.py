"""Read-only data invariants of the application database (`python -m app.cli data-check`).

Opens the database with mode=ro, so it is safe on the live database while the app runs and on copies. It checks rules
that the schema does not enforce by itself (they live in importer / demand / pipeline code) and reports violations;
it never repairs, deletes or merges anything. Status per check: OK | WARN (explainable, needs a look) | FAIL (an
invariant the code relies on is broken). Output contains ids and counts only, never settings values or secrets.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

CLOSED = ("REPLACED", "DELETED", "CANCELLED")
STUCK_AFTER = timedelta(hours=6)


def _q(c, sql, params=()):
    return [tuple(r) for r in c.execute(sql, params).fetchall()]


def _check(name, rule, bad, fail=True, examples=None):
    n = len(bad) if isinstance(bad, list) else int(bad)
    return {"check": name, "status": "OK" if n == 0 else ("FAIL" if fail else "WARN"), "count": n, "rule": rule,
            "examples": [list(x) if isinstance(x, tuple) else x for x in (examples or (bad if isinstance(bad, list) else []))[:5]]}


def run(db_path: Path, models_dir: Path | None = None) -> dict:
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(db_path)
    c = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        return _run(c, db_path, models_dir)
    finally:
        c.close()


def _run(c, db_path: Path, models_dir: Path | None) -> dict:
    out = []
    integ = [r[0] for r in c.execute("PRAGMA quick_check").fetchall()]
    out.append(_check("sqlite_integrity", "PRAGMA quick_check = ok", [] if integ == ["ok"] else integ))
    out.append(_check("foreign_keys", "PRAGMA foreign_key_check returns nothing", _q(c, "PRAGMA foreign_key_check")))
    out.append(_check("one_active_demo", "at most one ACTIVE DEMO batch (0002)",
                      _q(c, "SELECT id FROM import_batches WHERE data_source='DEMO' AND status='ACTIVE'")[1:]))
    ph = ",".join("?" * len(CLOSED))
    out.append(_check(
        "closed_batches_hold_no_rows",
        "REPLACED / DELETED / CANCELLED batches keep metadata only: no order_lines and no demand_daily rows",
        _q(c, f"SELECT b.id, b.status, (SELECT COUNT(*) FROM order_lines o WHERE o.batch_id=b.id), "
              f"(SELECT COUNT(*) FROM demand_daily d WHERE d.scope_key=b.id) FROM import_batches b "
              f"WHERE b.status IN ({ph}) AND (EXISTS (SELECT 1 FROM order_lines o WHERE o.batch_id=b.id) "
              f"OR EXISTS (SELECT 1 FROM demand_daily d WHERE d.scope_key=b.id))", CLOSED)))
    out.append(_check(
        "demand_matches_order_lines",
        "for every ACTIVE batch demand_daily = aggregate of its order_lines (row groups and total quantity)",
        _q(c, """SELECT b.id, o.groups, o.qty, d.n, d.qty FROM import_batches b
                 LEFT JOIN (SELECT batch_id, COUNT(*) AS groups, SUM(q) AS qty FROM (SELECT batch_id, SUM(order_qty) AS q
                            FROM order_lines GROUP BY batch_id, order_date, sku_id, fc_id) GROUP BY batch_id) o ON o.batch_id=b.id
                 LEFT JOIN (SELECT scope_key, COUNT(*) AS n, SUM(qty) AS qty FROM demand_daily GROUP BY scope_key) d
                        ON d.scope_key=b.id
                 WHERE b.status='ACTIVE' AND (IFNULL(o.groups,0) != IFNULL(d.n,0)
                       OR ABS(IFNULL(o.qty,0) - IFNULL(d.qty,0)) > 1e-6 * MAX(1, ABS(IFNULL(o.qty,0))))""")))
    out.append(_check(
        "demand_scope_owner",
        "every demand_daily scope is an ACTIVE batch or a BIGQUERY:<project>.<dataset>.<table> scope",
        _q(c, "SELECT d.scope_key, COUNT(*) FROM demand_daily d LEFT JOIN import_batches b ON b.id=d.scope_key "
              "WHERE d.scope_key NOT LIKE 'BIGQUERY:%' AND (b.id IS NULL OR b.status != 'ACTIVE') GROUP BY d.scope_key"),
        fail=False))
    g = c.execute("SELECT value_json FROM app_settings WHERE section='general'").fetchone()
    active_id = json.loads(g[0]).get("active_import_batch_id") if g else None
    bad = []
    if active_id:
        b = c.execute("SELECT status, data_source FROM import_batches WHERE id=?", (active_id,)).fetchone()
        if not b or tuple(b) != ("ACTIVE", "MANUAL_IMPORT"):
            bad = [(active_id, tuple(b) if b else "not found")]
    out.append(_check("active_dataset_setting", "general.active_import_batch_id is empty or an ACTIVE MANUAL_IMPORT batch",
                      bad))
    out.append(_check(
        "business_dates_and_quantities",
        "order_date is a valid YYYY-MM-DD date and quantities are >= 0 (order_lines, demand_daily)",
        _q(c, "SELECT 'order_lines', batch_id, order_date, order_qty FROM order_lines WHERE order_qty < 0 "
              "OR date(order_date) IS NULL OR date(order_date) != order_date LIMIT 50")
        + _q(c, "SELECT 'demand_daily', scope_key, order_date, qty FROM demand_daily WHERE qty < 0 "
                "OR date(order_date) IS NULL OR date(order_date) != order_date LIMIT 50")))
    out.append(_check(
        "order_grain_duplicates",
        "order_id x SKU x FC appears once per ACTIVE batch (several lines are kept only if the import policy summed them)",
        _q(c, "SELECT o.batch_id, COUNT(*) FROM (SELECT batch_id FROM order_lines WHERE order_id IS NOT NULL "
              "GROUP BY batch_id, order_id, sku_id, fc_id HAVING COUNT(*) > 1) o JOIN import_batches b ON b.id=o.batch_id "
              "WHERE b.status='ACTIVE' GROUP BY o.batch_id"), fail=False))
    out.append(_check(
        "forecast_runs_complete",
        "each published run holds n_series x max_horizon forecast values",
        _q(c, "SELECT r.id, r.n_series * r.max_horizon, (SELECT COUNT(*) FROM forecast_values v WHERE v.run_id=r.id) AS n "
              "FROM forecast_runs r WHERE n != r.n_series * r.max_horizon")))
    out.append(_check(
        "forecast_series_meta",
        "each run has one explanation row per series (runs published before migration 0003 have none)",
        _q(c, "SELECT r.id, r.n_series, (SELECT COUNT(*) FROM forecast_series_meta m WHERE m.run_id=r.id) AS n "
              "FROM forecast_runs r WHERE n != r.n_series"), fail=False))
    model_bad = []
    if models_dir is not None:
        for rid, mv, mp, sha in _q(c, "SELECT id, model_version, model_path, model_sha256 FROM training_runs "
                                      "WHERE status='ACCEPTED'"):
            f = Path(models_dir) / (mp or "")
            if not mp or not f.is_file():
                model_bad.append((rid, mv, "missing"))
            elif sha and hashlib.sha256(f.read_bytes()).hexdigest() != sha:
                model_bad.append((rid, mv, "sha256 differs"))
    out.append(_check("accepted_model_files", "every ACCEPTED training run has its model file with the recorded SHA-256"
                      + ("" if models_dir is not None else " (skipped: no models folder given)"), model_bad))
    now = datetime.now(timezone.utc)
    stuck = []
    for jid, jt, st, ts in _q(c, "SELECT id, job_type, status, COALESCE(started_at, created_at) FROM job_runs "
                                 "WHERE status IN ('PENDING','RUNNING')"):
        try:
            t = datetime.fromisoformat(ts)
            t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
            if now - t > STUCK_AFTER:
                stuck.append((jid, jt, st, ts))
        except (TypeError, ValueError):
            stuck.append((jid, jt, st, ts))
    out.append(_check("stuck_jobs", f"no job PENDING/RUNNING for more than {STUCK_AFTER}", stuck, fail=False))
    status = "FAIL" if any(x["status"] == "FAIL" for x in out) else ("WARN" if any(x["status"] == "WARN" for x in out)
                                                                       else "OK")
    ver = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    counts = {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in
              ("import_batches", "order_lines", "demand_daily", "training_runs", "forecast_runs", "forecast_values",
               "d0_snapshots", "job_runs")}
    return {"db": str(db_path), "schema_version": ver, "checked_at": now.isoformat(timespec="seconds"),
            "status": status, "row_counts": counts, "checks": out}
