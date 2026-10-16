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


def data_window(conn=None, today: date | None = None) -> dict:
    """The model-input window (one rule for training, backtest, forecast and the data-quality report)."""
    pol = ss.get("data_policy", conn)
    end = (today or today_vn()) - timedelta(days=1)
    return {"start": pol.window_start_date, "end": str(end), "rule": WINDOW_RULE}


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
    sql = ("SELECT order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, avg_discount_rate, promo_share, "
           "voucher_share FROM demand_daily WHERE scope_key=?")
    params: list = [scope_key]
    if start:
        sql += " AND order_date>=?"
        params.append(start)
    if end:
        sql += " AND order_date<=?"
        params.append(end)
    def _q(c):
        return pd.read_sql_query(sql, c, params=params)
    if conn is not None:
        return _q(conn)
    with db.read() as c:
        return _q(c)


def fingerprint(scope_key: str, conn) -> str:
    r = conn.execute("SELECT COUNT(*), COALESCE(SUM(qty),0), MIN(order_date), MAX(order_date), MAX(loaded_at) "
                     "FROM demand_daily WHERE scope_key=?", (scope_key,)).fetchone()
    return hashlib.sha256(repr(tuple(r)).encode()).hexdigest()[:16]
