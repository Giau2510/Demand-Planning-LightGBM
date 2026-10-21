"""Daily demand per scope. A scope is exactly one dataset — sources are never mixed.

scope_key:
  DEMO           -> the active DEMO batch id
  MANUAL_IMPORT  -> the import batch the user selected as active dataset
  BIGQUERY       -> 'BIGQUERY:<project>.<dataset>.<table>'
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

import pandas as pd

from .. import db
from .. import settings_service as ss
from ..messages import AppError
from ..timeutil import now_iso, today_vn

WINDOW_RULE = ("Model input = complete Vietnam days from data_policy.window_start_date to yesterday (Asia/Ho_Chi_Minh). "
               "Today's partial day is used only by D0 snapshots; future dates are never used. Stored rows outside "
               "the window are kept but not used.")


def data_window(conn=None, today: date | None = None, scope: dict | None = None) -> dict:
    """The model-input window (one rule for training, backtest, forecast and the data-quality report).

    1.2.9b: with data_policy.training_start_rule = OPEN_HOURS_COVERAGE and a BIGQUERY `scope`, the window starts at the
    first stored day with open hours (open_hours.coverage_start, read from the stored rows at each call); the days from
    window_start_date up to the day before are `excluded` - kept and still loaded, only not model input. No stored day
    with open hours = the configured start is kept (the open-hours check then reports the missing values; nothing is
    guessed). Without a scope (status pages) the configured window is returned, with its rule, and nothing is scanned."""
    pol = ss.get("data_policy", conn)
    end = (today or today_vn()) - timedelta(days=1)
    out = {"start": pol.window_start_date, "end": str(end), "rule": WINDOW_RULE,
           "configured_start": pol.window_start_date, "start_rule": pol.training_start_rule}
    if pol.training_start_rule == "OPEN_HOURS_COVERAGE" and scope is not None:
        from . import open_hours
        if open_hours.mandatory(scope.get("data_source")):
            def _first(c):
                return open_hours.coverage_start(c, scope["scope_key"], pol.window_start_date, str(end))
            if conn is not None:
                first = _first(conn)
            else:
                with db.read() as c:
                    first = _first(c)
            out["coverage_start"] = first
            if first and first > pol.window_start_date:
                out["start"] = first
                out["excluded"] = {"start": pol.window_start_date,
                                   "end": str(date.fromisoformat(first) - timedelta(days=1))}
    return out


def excluded_summary(conn, scope_key: str, window: dict) -> dict | None:
    """What a start rule leaves out of the model input (window['excluded']) next to what stays in: days, demand rows,
    SKU x FC series (and those with rows ONLY in the excluded days), quantity and its share. Counts only - no row is
    deleted or changed. Two sequential scans of the scope from the configured start to the end."""
    ex = window.get("excluded")
    if not ex:
        return None
    p = {"k": scope_key, "xs": ex["start"], "xe": ex["end"], "we": window["end"]}
    r = conn.execute(
        "SELECT COALESCE(SUM(order_date <= :xe), 0), COALESCE(SUM(CASE WHEN order_date <= :xe THEN qty END), 0), "
        "COUNT(DISTINCT CASE WHEN order_date <= :xe THEN order_date END), COALESCE(SUM(order_date > :xe), 0), "
        "COALESCE(SUM(CASE WHEN order_date > :xe THEN qty END), 0) "
        "FROM demand_daily NOT INDEXED WHERE scope_key=:k AND order_date BETWEEN :xs AND :we", p).fetchone()
    s = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(last_day <= :xe), 0) FROM (SELECT MIN(order_date) AS first_day, "
        "MAX(order_date) AS last_day FROM demand_daily NOT INDEXED WHERE scope_key=:k AND order_date BETWEEN :xs AND :we "
        "GROUP BY sku_id, fc_id) WHERE first_day <= :xe", p).fetchone()
    total_qty = float(r[1]) + float(r[4])
    return {"start": ex["start"], "end": ex["end"],
            "calendar_days": (date.fromisoformat(ex["end"]) - date.fromisoformat(ex["start"])).days + 1,
            "days_with_rows": int(r[2]), "rows": int(r[0]), "qty": float(r[1]),
            "series": int(s[0]), "series_only_in_excluded_days": int(s[1]),
            "rows_in_window": int(r[3]), "qty_in_window": float(r[4]),
            "qty_share_excluded": (float(r[1]) / total_qty) if total_qty else None,
            "rows_share_excluded": (int(r[0]) / (int(r[0]) + int(r[3]))) if (int(r[0]) + int(r[3])) else None}


def panel_for_run(tr: dict, conn=None):
    """Exactly the panel a training run used, rebuilt from its stored train_start..train_end (never from the CURRENT
    window or max_train_days settings, which may have changed since). None when the run has no stored range or the
    data is gone."""
    from ..ml.features import build_panel
    if not tr or not tr.get("train_start") or not tr.get("train_end"):
        return None
    d = load_demand(tr["scope_key"], conn, start=tr["train_start"], end=tr["train_end"])
    if d.empty:
        return None
    return build_panel(d, end_date=tr["train_end"], start_date=tr["train_start"])


def bigquery_scope_key(bq) -> str:
    return f"BIGQUERY:{bq.project_id}.{bq.dataset_id}.{bq.source_table}"


def active_demo_batch(conn) -> dict | None:
    return db.one(conn, "SELECT * FROM import_batches WHERE data_source='DEMO' AND status='ACTIVE' "
                        "ORDER BY created_at DESC, rowid DESC LIMIT 1")


def resolve_scope(conn=None, source: str | None = None) -> dict:
    """Return {scope_key, data_source, label} for the active (or given) source."""
    def _r(c):
        g = ss.get("general", c)
        src = source or g.active_source
        if src == "DEMO":
            b = active_demo_batch(c)
            if not b:
                raise AppError("NO_ACTIVE_DATASET", 409, detail="DEMO data not generated yet")
            return {"scope_key": b["id"], "data_source": "DEMO", "label": f"DEMO ({b['id']})"}
        if src == "MANUAL_IMPORT":
            bid = g.active_import_batch_id
            if not bid:
                raise AppError("NO_ACTIVE_DATASET", 409, detail="select an ACTIVE import batch as dataset")
            b = db.one(c, "SELECT * FROM import_batches WHERE id=?", (bid,))
            if not b or b["status"] != "ACTIVE" or b["data_source"] != "MANUAL_IMPORT":
                # settings point at a batch that is not usable: report it, never pick another batch silently
                raise AppError("ACTIVE_DATASET_INCONSISTENT", 409,
                               detail=f"{bid}: {b['status'] if b else 'not found'}", batch_id=bid)
            return {"scope_key": b["id"], "data_source": "MANUAL_IMPORT", "label": f"{b['file_name']} ({b['id']})"}
        bq = ss.get("bigquery", c)
        if not (bq.dataset_id and bq.source_table):
            raise AppError("BQ_NOT_CONFIGURED", 409)
        return {"scope_key": bigquery_scope_key(bq), "data_source": "BIGQUERY",
                "label": f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}"}
    if conn is not None:
        return _r(conn)
    with db.read() as c:
        return _r(c)


def aggregate_batch(conn, batch_id: str, data_source: str) -> int:
    conn.execute("DELETE FROM demand_daily WHERE scope_key=?", (batch_id,))
    conn.execute(
        """INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, avg_unit_price,
                                    avg_discount_rate, promo_share, voucher_share, loaded_at)
           SELECT ?, ?, order_date, sku_id, fc_id, SUM(order_qty),
                  COUNT(DISTINCT COALESCE(order_id, 'row' || id)),
                  SUM(CASE WHEN unit_price IS NOT NULL THEN unit_price * order_qty END)
                      / NULLIF(SUM(CASE WHEN unit_price IS NOT NULL THEN order_qty END), 0),
                  SUM(discount_amount) / NULLIF(SUM(CASE WHEN unit_price IS NOT NULL THEN unit_price * order_qty END), 0),
                  AVG(promotion_flag), AVG(voucher_flag), ?
           FROM order_lines WHERE batch_id=? GROUP BY order_date, sku_id, fc_id""",
        (batch_id, data_source, now_iso(), batch_id))
    return conn.execute("SELECT COUNT(*) FROM demand_daily WHERE scope_key=?", (batch_id,)).fetchone()[0]


def load_demand(scope_key: str, conn=None, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    # open_hours (1.2.9): value of status OK only (NULL otherwise, never replaced) - data/open_hours.py
    # customer counts (1.2.9b): NULL = unknown (no customer column mapped / no identifier that day) - data/customers.py
    # master audit 21/10/2026: ONE sequential scan (NOT INDEXED) sorted in the key order, instead of the key index that
    # fetched every row again for the non-key columns: 15.3 s -> 6.2 s for 1.36 M rows on a copy of production, the
    # same DataFrame (values, dtypes and row order: the ORDER BY is the order of the key index)
    sql = ("SELECT order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, avg_discount_rate, promo_share, "
           "voucher_share, open_hours, customer_count, repeat_customer_count, repeat_interval_days_sum "
           "FROM demand_daily NOT INDEXED WHERE scope_key=?")
    params: list = [scope_key]
    if start:
        sql += " AND order_date>=?"
        params.append(start)
    if end:
        sql += " AND order_date<=?"
        params.append(end)
    sql += " ORDER BY order_date, sku_id, fc_id"
    def _q(c):
        return pd.read_sql_query(sql, c, params=params)
    if conn is not None:
        return _q(conn)
    with db.read() as c:
        return _q(c)


def fingerprint(scope_key: str, conn) -> str:
    # 1.2.8: ONE sequential scan (NOT INDEXED). Through the key index SQLite fetched every row again for qty / loaded_at
    # (not in the index): 42 s for 1.35 M rows on a copy of production, paid by every "how is this calculated" request,
    # training and promotion check. Same aggregates, same hash, so stored training fingerprints keep matching: a sum of
    # whole numbers is exact in any order; a scope with fractional quantities is summed in the key order of the original
    # statement (its float sum could differ in the last bit in another order).
    r = conn.execute("SELECT COUNT(*), COALESCE(SUM(qty),0), MIN(order_date), MAX(order_date), MAX(loaded_at), "
                     "SUM(qty <> CAST(qty AS INTEGER)) FROM demand_daily NOT INDEXED WHERE scope_key=?",
                     (scope_key,)).fetchone()
    if r[5]:
        r = conn.execute("SELECT COUNT(*), COALESCE(SUM(qty),0), MIN(order_date), MAX(order_date), MAX(loaded_at) "
                         "FROM demand_daily WHERE scope_key=?", (scope_key,)).fetchone()
    return hashlib.sha256(repr(tuple(r)[:5]).encode()).hexdigest()[:16]
