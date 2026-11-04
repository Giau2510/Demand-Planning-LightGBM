"""1.3.1 daily forecast refresh, B7: SKU x FC groups A / B / C (docs/ke_hoach_lgbm_chot.md 1, 6.3), used by the
reports only (never to choose a formula). compute_metrics is pure (the caller loads the rows); the DB part at the end
(load_rows, ensure_groups) stores / looks up the groups.

Window: WINDOW_DAYS calendar days ending at D-1 of the computation day (window_for), its start clipped to the model data
window (clipped_window; the effective start is stored in sku_group.window_start). Only open days count: a day with
open hours > 0 (hours 0, negative or NaN = closed, excluded even if it has demand). An open day without a demand row
(NaN) is 0 demand.
  n_open_days, qty = sum(demand), avg_per_open_day = qty / n_open_days, zero_days = open days with demand 0,
  zero_share = zero_days / n_open_days
  n_open_days < MIN_OPEN_DAYS                    -> B
  avg > 20 and zero_share <= 0.20                -> A
  avg <= 5 and zero_share > 0.20                 -> C
  otherwise                                      -> B
A series without an open day in the window is not returned.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app import db
from app.timeutil import now_iso

GROUP_A = "A"                   # fast movers
GROUP_B = "B"                   # the others (also fewer than MIN_OPEN_DAYS open days)
GROUP_C = "C"                   # slow movers
RULE_VERSION = "B7-1"
WINDOW_DAYS = 90
MIN_OPEN_DAYS = 14
A_MIN_AVG = 20.0                # avg must be strictly above
A_MAX_ZERO_SHARE = 0.20         # zero_share must be at most
C_MAX_AVG = 5.0                 # avg must be at most
C_MIN_ZERO_SHARE = 0.20         # zero_share must be strictly above

OUTPUT_COLUMNS = ["fc_code", "sku_code", "n_open_days", "qty", "avg_per_open_day", "zero_days", "zero_share",
                  "group_code"]
_DTYPES = {"fc_code": object, "sku_code": object, "n_open_days": np.int64, "qty": float, "avg_per_open_day": float,
           "zero_days": np.int64, "zero_share": float, "group_code": object}


def window_for(computed_for: date) -> tuple[date, date]:
    """(window_start, window_end) of the WINDOW_DAYS days ending at D-1 of `computed_for` (Vietnam calendar date)."""
    end = computed_for - timedelta(days=1)
    return end - timedelta(days=WINDOW_DAYS - 1), end


def classify(n_open_days, avg, zero_share) -> np.ndarray:
    """Group codes A / B / C (object array) of the B7 rule, element-wise."""
    n = np.asarray(n_open_days)
    a = np.asarray(avg, dtype=float)
    z = np.asarray(zero_share, dtype=float)
    enough = n >= MIN_OPEN_DAYS
    grp_a = enough & (a > A_MIN_AVG) & (z <= A_MAX_ZERO_SHARE)
    grp_c = enough & (a <= C_MAX_AVG) & (z > C_MIN_ZERO_SHARE)
    return np.where(grp_a, GROUP_A, np.where(grp_c, GROUP_C, GROUP_B)).astype(object)


def compute_metrics(rows: pd.DataFrame, window_start, window_end) -> pd.DataFrame:
    """Metrics and group per (fc_code, sku_code).

    rows: columns fc_code, sku_code, date (ISO string, date or datetime), demand (NaN = no demand row), hours (open
    hours of the day); at most one row per series and day. window_start / window_end: inclusive bounds (ISO string or
    date). Returns OUTPUT_COLUMNS sorted by fc_code, sku_code (empty frame with these columns when nothing qualifies).
    Raises ValueError on a duplicated series-day inside the window.
    """
    ws = pd.Timestamp(window_start).normalize()
    we = pd.Timestamp(window_end).normalize()
    empty = pd.DataFrame({c: pd.Series(dtype=_DTYPES[c]) for c in OUTPUT_COLUMNS})
    if rows is None or len(rows) == 0:
        return empty
    days = pd.to_datetime(rows["date"]).dt.normalize()
    hours = pd.to_numeric(rows["hours"], errors="coerce")
    keep = (days >= ws) & (days <= we) & (hours > 0)
    if not keep.any():
        return empty
    df = pd.DataFrame({"fc_code": rows["fc_code"][keep].to_numpy(), "sku_code": rows["sku_code"][keep].to_numpy(),
                       "date": days[keep].to_numpy(),
                       "demand": pd.to_numeric(rows["demand"][keep], errors="coerce").fillna(0.0).to_numpy()})
    if df.duplicated(["fc_code", "sku_code", "date"]).any():
        raise ValueError("compute_metrics: more than one row for the same series and day")
    df["zero"] = (df["demand"] == 0).astype(np.int64)
    g = (df.groupby(["fc_code", "sku_code"], sort=True)
         .agg(n_open_days=("demand", "size"), qty=("demand", "sum"), zero_days=("zero", "sum"))
         .reset_index())
    g["n_open_days"] = g["n_open_days"].astype(np.int64)
    g["zero_days"] = g["zero_days"].astype(np.int64)
    g["qty"] = g["qty"].astype(float)
    g["avg_per_open_day"] = g["qty"] / g["n_open_days"]
    g["zero_share"] = g["zero_days"] / g["n_open_days"]
    g["group_code"] = classify(g["n_open_days"], g["avg_per_open_day"], g["zero_share"])
    return g[OUTPUT_COLUMNS]


# ------------------------------------------------------------------ DB part (B7): store / look up the groups
# The open-hours source is refreshed around 04:10 with the days up to D-2 only (1.3.0 analysis, kept in 1.3.1): a
# month's groups are computed only once the stored open hours reach at least D-(OPEN_HOURS_MAX_LAG_DAYS) of the
# computation day; before that the latest stored groups stay in use (GROUPS_DEFERRED_OPEN_HOURS_LAG, nothing stored).
OPEN_HOURS_MAX_LAG_DAYS = 2
DEFERRED_OPEN_HOURS_LAG = "GROUPS_DEFERRED_OPEN_HOURS_LAG"


def _month_start(d: date) -> date:
    return d.replace(day=1)


def clipped_window(computed_for: date, floor=None) -> tuple[date, date]:
    """window_for(computed_for) with its start clipped to `floor` (the model data window start, data_window()["start"]):
    no day before the data window is ever read (AGENTS.md section 4)."""
    ws, we = window_for(computed_for)
    if floor:
        ws = max(ws, date.fromisoformat(str(floor)[:10]))
    return ws, we


def load_rows(conn, scope_key: str, window_start, window_end, oh_source: tuple[str, str]) -> pd.DataFrame:
    """compute_metrics input from the stored tables: the open days of open_hours_daily (hours > 0) of the window read
    from oh_source = (source_table, seller_code), with the demand_daily quantity of the scope (no demand row = NaN,
    which compute_metrics counts as 0 demand). Only days on which the scope has at least one demand_daily row: a day
    without any demand row of the scope is a data gap (unknown), never 0 demand."""
    return pd.read_sql_query(
        "SELECT o.fc_code, o.sku_code, o.open_date AS date, o.total_open_hours AS hours, d.qty AS demand "
        "FROM open_hours_daily o LEFT JOIN demand_daily d ON d.scope_key=? AND d.order_date=o.open_date "
        "AND d.sku_id=o.sku_code AND d.fc_id=o.fc_code WHERE o.source_table=? AND o.seller_code=? "
        "AND o.open_date BETWEEN ? AND ? AND o.total_open_hours > 0 "
        "AND o.open_date IN (SELECT order_date FROM demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?)",
        conn, params=(scope_key, *oh_source, str(window_start), str(window_end), scope_key, str(window_start),
                      str(window_end)))


def open_hours_last_day(conn, d: date, oh_source: tuple[str, str]) -> str | None:
    """Last stored open_hours_daily day of oh_source = (source_table, seller_code) before forecast day d (None =
    nothing stored)."""
    return conn.execute("SELECT MAX(open_date) FROM open_hours_daily WHERE source_table=? AND seller_code=? "
                        "AND open_date <= ?", (*oh_source, str(d - timedelta(days=1)))).fetchone()[0]


def ensure_groups(d: date, scope_key: str, window_floor=None, oh_source: tuple[str, str] | None = None) -> dict:
    """Groups for forecast day d. When no group was computed in d's calendar month yet (first refresh of the month, or
    the first one after switching on) and the stored open hours reach D-OPEN_HOURS_MAX_LAG_DAYS, the groups are computed
    over clipped_window(d, window_floor) - read and computed on a read connection, then stored with computed_for = d in a
    short write transaction (the write lock is never held during the computation). Otherwise nothing is stored
    ("deferred" = DEFERRED_OPEN_HOURS_LAG). Returns {"computed_for", "computed": bool, "deferred", "window_start",
    "window_end", "open_hours_last_day", "groups": {(fc_code, sku_code): group}} of the latest computation with
    computed_for <= d of the scope (a series missing there has no group: GROUP_MISSING downstream). oh_source =
    (source_table, seller_code) of the open hours (default: the configured daily_forecast open-hours read)."""
    from app.bq.aux_sources import open_hours_source
    oh_source = oh_source or open_hours_source()
    g, deferred, ws, we = None, None, None, None
    with db.read() as c:
        last_oh = open_hours_last_day(c, d, oh_source)
        have = c.execute("SELECT 1 FROM sku_group WHERE scope_key=? AND computed_for BETWEEN ? AND ? LIMIT 1",
                         (scope_key, str(_month_start(d)), str(d))).fetchone()
        if not have:
            if last_oh is None or last_oh < str(d - timedelta(days=OPEN_HOURS_MAX_LAG_DAYS)):
                deferred = DEFERRED_OPEN_HOURS_LAG
            else:
                ws, we = clipped_window(d, window_floor)
                g = compute_metrics(load_rows(c, scope_key, ws, we, oh_source), ws, we)
    if g is not None and len(g):
        at = now_iso()
        vals = [(scope_key, r.fc_code, r.sku_code, r.group_code, str(d), str(ws), str(we), int(r.n_open_days),
                 float(r.qty), float(r.avg_per_open_day), int(r.zero_days), float(r.zero_share), RULE_VERSION, at)
                for r in g.itertuples(index=False)]
        with db.tx() as c:
            c.executemany(
                "INSERT INTO sku_group(scope_key, fc_code, sku_code, group_code, computed_for, window_start, window_end, "
                "n_open_days, qty, avg_per_open_day, zero_days, zero_share, rule_version, computed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(scope_key, fc_code, sku_code, computed_for) DO NOTHING",
                vals)
    with db.read() as c:
        last = c.execute("SELECT MAX(computed_for) FROM sku_group WHERE scope_key=? AND computed_for <= ?",
                         (scope_key, str(d))).fetchone()[0]
        groups = {} if last is None else {(r[0], r[1]): r[2] for r in c.execute(
            "SELECT fc_code, sku_code, group_code FROM sku_group WHERE scope_key=? AND computed_for=?", (scope_key, last))}
    return {"computed_for": last, "computed": g is not None and len(g) > 0, "deferred": deferred,
            "window_start": None if ws is None else str(ws), "window_end": None if we is None else str(we),
            "open_hours_last_day": last_oh, "groups": groups}

