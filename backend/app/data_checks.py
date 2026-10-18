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
# 1.2.6: triggers that make the end-of-day backup / actual closes immutable (0005) and allow only the 90-day retention
# to delete a backup (0006, which replaced trg_fes_no_delete / trg_fes_values_no_delete)
EOD_TRIGGERS = ("trg_fes_complete_fixed", "trg_fes_keys_fixed", "trg_fes_values_no_update", "trg_fes_values_complete_only",
                "trg_actual_closes_no_update", "trg_actual_closes_no_delete", "trg_actual_close_values_no_update",
                "trg_actual_close_values_no_delete", "trg_actual_closes_consecutive")
RETENTION_TRIGGERS = ("trg_fes_delete_retention_only", "trg_fes_values_delete_retention_only", "trg_fesr_insert_checked",
                      "trg_fesr_keys_fixed", "trg_fesr_finish_only", "trg_fesr_no_delete", "trg_fesr_no_replace",
                      "trg_fes_no_replace", "trg_fes_values_no_replace", "trg_actual_closes_no_replace",
                      "trg_actual_close_values_no_replace")


def _q(c, sql, params=()):
    return [tuple(r) for r in c.execute(sql, params).fetchall()]


def _baseline_only(c, training_run_id: str) -> bool:
    """Every forecast run of this training run was produced by the 28-day baseline only (1.2.2)."""
    runs = _q(c, "SELECT method_counts_json FROM forecast_runs WHERE training_run_id=?", (training_run_id,))
    return bool(runs) and all(set(json.loads(m or "{}")) == {"BASELINE_MOVING_AVERAGE"} for (m,) in runs)


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
    has_history = bool(_q(c, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forecast_history_days'"))
    if has_history:     # 1.2.5 (migration 0004): D+1 forecast history
        out.append(_check(
            "forecast_history_values_unchanged",
            "every stored D+1 value equals the published forecast value (same run, SKU, FC, date, quantity, method)",
            _q(c, "SELECT h.forecast_run_id, COUNT(*) FROM forecast_history_values h LEFT JOIN forecast_values v "
                  "ON v.run_id = h.forecast_run_id AND v.sku_id = h.sku_id AND v.fc_id = h.fc_id AND v.target_date = h.target_date "
                  "WHERE v.run_id IS NULL OR ABS(v.yhat - h.yhat) > 1e-9 OR v.method != h.method GROUP BY h.forecast_run_id")))
        out.append(_check(
            "forecast_history_d1_only",
            "history keeps only D+1: target_date = run_date + 1 (sessions and values)",
            _q(c, "SELECT 'session', forecast_run_id, run_date, target_date FROM forecast_history_sessions "
                  "WHERE target_date != date(run_date, '+1 day') UNION ALL SELECT 'value', forecast_run_id, run_date, "
                  "target_date FROM forecast_history_values WHERE target_date != date(run_date, '+1 day') LIMIT 50")))
        out.append(_check(
            "forecast_history_selected_complete",
            "a session selected when recorded holds all its D+1 rows (n_rows values)",
            _q(c, "SELECT s.forecast_run_id, s.n_rows, (SELECT COUNT(*) FROM forecast_history_values v "
                  "WHERE v.forecast_run_id = s.forecast_run_id) AS n FROM forecast_history_sessions s "
                  "WHERE s.decision = 'SELECTED' AND n != s.n_rows")))
        out.append(_check(
            "forecast_history_official_is_newest",
            "per scope and run date the official session is the newest eligible one (session time, publish time, run order)",
            _q(c, "SELECT d.scope_key, d.run_date, d.forecast_run_id, x.forecast_run_id FROM forecast_history_days d "
                  "JOIN forecast_history_sessions s ON s.forecast_run_id = d.forecast_run_id "
                  "JOIN forecast_runs fs ON fs.id = s.forecast_run_id "
                  "JOIN forecast_history_sessions x ON x.scope_key = d.scope_key AND x.run_date = d.run_date "
                  "AND x.eligible = 1 AND x.forecast_run_id != d.forecast_run_id "
                  "JOIN forecast_runs fx ON fx.id = x.forecast_run_id "
                  "WHERE x.session_started_at > s.session_started_at OR (x.session_started_at = s.session_started_at "
                  "AND (x.published_at > s.published_at OR (x.published_at = s.published_at AND fx.rowid > fs.rowid)))")))
        out.append(_check(
            "forecast_history_all_runs_recorded",
            "every published forecast run is recorded in the history (missing ones are recorded at the next publish, "
            "app start or 'app.cli history-reconcile')",
            _q(c, "SELECT r.id, r.created_at FROM forecast_runs r LEFT JOIN forecast_history_sessions s "
                  "ON s.forecast_run_id = r.id WHERE s.forecast_run_id IS NULL"), fail=False))
    has_eod = bool(_q(c, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forecast_eod_snapshots'"))
    if has_eod:         # 1.2.6 (migration 0005): end-of-day forecast backup + actual close
        out.append(_check(
            "eod_snapshot_complete",
            "a COMPLETE end-of-day snapshot covers every day with n_days x source series rows (values counted for the "
            "last 14 business days); any other snapshot holds no value",
            _q(c, "SELECT s.id, s.status, s.n_rows FROM forecast_eod_snapshots s WHERE s.status = 'COMPLETE' AND "
                  "(s.n_rows != s.n_days * s.source_n_series OR s.days_covered != s.n_days)")
            + _q(c, "SELECT s.id, s.status, s.n_rows, (SELECT COUNT(*) FROM forecast_eod_snapshot_values v "
                    "WHERE v.snapshot_id = s.id) AS n FROM forecast_eod_snapshots s "
                    "WHERE s.business_date >= date('now', '-14 days') AND s.status = 'COMPLETE' AND n != s.n_rows")
            + _q(c, "SELECT s.id, s.status FROM forecast_eod_snapshots s WHERE s.status != 'COMPLETE' "
                    "AND EXISTS (SELECT 1 FROM forecast_eod_snapshot_values v WHERE v.snapshot_id = s.id)")))
        out.append(_check(
            "eod_snapshot_values_match_source",
            "every value of the snapshots of the last 14 business days equals the published forecast value of its "
            "source run (same SKU, FC, date, quantity, method)",
            _q(c, "SELECT s.id, COUNT(*) FROM forecast_eod_snapshots s JOIN forecast_eod_snapshot_values v "
                  "ON v.snapshot_id = s.id LEFT JOIN forecast_values f ON f.run_id = s.source_run_id "
                  "AND f.sku_id = v.sku_id AND f.fc_id = v.fc_id AND f.target_date = v.target_date "
                  "WHERE s.business_date >= date('now', '-14 days') AND (f.run_id IS NULL OR ABS(f.yhat - v.yhat) > 1e-9 "
                  "OR f.method != v.method) GROUP BY s.id")))
        out.append(_check(
            "actual_close_revisions",
            "per scope and day the close revisions are 1..n without gap and each holds its n_rows values",
            _q(c, "SELECT scope_key, business_date, MIN(revision), MAX(revision), COUNT(*) FROM actual_closes "
                  "GROUP BY scope_key, business_date HAVING MIN(revision) != 1 OR MAX(revision) != COUNT(*)")
            + _q(c, "SELECT a.id, a.n_rows, (SELECT COUNT(*) FROM actual_close_values v WHERE v.close_id = a.id) AS n "
                    "FROM actual_closes a WHERE n != a.n_rows")))
        from .eod_retention import dry_run
        plan = dry_run(db_path)              # the same read-only plan as scripts\eod-retention.ps1 (held ones excluded)
        out.append(_check(
            "eod_snapshot_retention_due",
            "no end-of-day snapshot older than 90 days (Vietnam business date) waits for deletion: run "
            "scripts\\eod-retention.ps1 (dry run first, then -Apply -Plan <plan_id>); a snapshot still shown as backup "
            "inside the 90 days is held and not listed",
            [(i["id"], i["scope_key"], i["business_date"], i["status"]) for i in plan["delete"]["items"]], fail=False))
    has_ret = bool(_q(c, "SELECT 1 FROM sqlite_master WHERE type='table' AND name='forecast_eod_snapshot_retention'"))
    if has_eod:
        want = set(EOD_TRIGGERS) | (set(RETENTION_TRIGGERS) if has_ret else {"trg_fes_no_delete", "trg_fes_values_no_delete"})
        have = {r[0] for r in _q(c, "SELECT name FROM sqlite_master WHERE type='trigger'")}
        out.append(_check(
            "eod_backup_protection_triggers",
            "every trigger that protects the end-of-day backup, the actual closes and the retention records exists "
            "(migrations 0005 / 0006)", [(t,) for t in sorted(want - have)]))
    if has_ret:         # 1.2.6 (migration 0006): 90-day retention records
        out.append(_check(
            "eod_snapshot_retention_records",
            "every retention record is DELETED (an open DELETING permit never outlives its transaction), its snapshot "
            "and values are gone and its business date is before its cutoff",
            _q(c, "SELECT r.snapshot_id, r.state, r.business_date, r.cutoff_date FROM forecast_eod_snapshot_retention r "
                  "WHERE r.state != 'DELETED' OR r.business_date >= r.cutoff_date "
                  "OR EXISTS (SELECT 1 FROM forecast_eod_snapshots s WHERE s.id = r.snapshot_id) "
                  "OR EXISTS (SELECT 1 FROM forecast_eod_snapshot_values v WHERE v.snapshot_id = r.snapshot_id) "
                  "OR r.rows_deleted IS NOT r.n_rows")))
    model_bad = []
    if models_dir is not None:
        for rid, mv, mp, sha in _q(c, "SELECT id, model_version, model_path, model_sha256 FROM training_runs "
                                      "WHERE status='ACCEPTED'"):
            f = Path(models_dir) / (mp or "")
            if not mp and _baseline_only(c, rid):
                continue        # 1.2.2: a published 28-day baseline (LightGBM not trained) has no model file by design
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
               "d0_snapshots", "job_runs") + (("forecast_history_sessions", "forecast_history_values",
                                                "forecast_history_days") if has_history else ())
              + (("forecast_eod_snapshots", "forecast_eod_snapshot_values", "actual_closes", "actual_close_values")
                 if has_eod else ()) + (("forecast_eod_snapshot_retention",) if has_ret else ())}
    return {"db": str(db_path), "schema_version": ver, "checked_at": now.isoformat(timespec="seconds"),
            "status": status, "row_counts": counts, "checks": out}
