"""1.4.0 SEL2 inputs of a day, read-only from an open connection (data window of data_policy, BIGQUERY scope).

load_inputs(conn, scope_key, D, lag_days) reads the demand frame of [window start, D-1] (lgbm.load_frame: approved open
hours override applied) and the open-hours calendar open_hours_daily of the configured source (table + seller), and
builds K x G arrays with day 0 = DAY0 (2025-01-01, the backtest's day 0; sel2.scope contract): daily demand (float64,
0 = no order), has_row (a demand row exists) and open hours (float32, NaN = no row); keys = the (sku_code, fc_code) of
the frame, sorted. Nothing before the data window start is read.

Open-hours lag rule (owner decision GIO_MO_BAN_TRE = CO, sel2_pipeline.open_hours_lag_days = L):
  * calendar: the days after the last day of the source (at most L days, up to D-1) get the source's last day
    (same SKU x FC; no row there = no row); a source ending more than L days before D-1 -> OPEN_HOURS_INVALID;
  * demand rows: a row without open hours (status MISSING) on one of the last L days (D-L .. D-1) gets the value of
    the same SKU x FC's latest day with a known value among the L days before it (its demand row, else the source
    calendar; filled values are never a source); none, another status, or a row before D-L -> OPEN_HOURS_INVALID.
  Every fill is flagged OPEN_HOURS_LAG (inputs.flags, counts in inputs.detail)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from ...bq.aux_sources import open_hours_source
from ...data.demand import data_window
from .. import sku_group
from . import lgbm, scope
from .errors import OPEN_HOURS_INVALID, WINDOW_NOT_COVERED, Sel2Error

DAY0 = date(2025, 1, 1)
FLAG_OPEN_HOURS_LAG = "OPEN_HOURS_LAG"
SELECT_WINDOW = 28
READ_ROWS = 200_000


@dataclass
class Inputs:
    scope_key: str
    end: date                       # last day read (the day before the first forecast day these inputs serve)
    window_start: str
    frame: pd.DataFrame
    keys: pd.DataFrame              # sku_code, fc_code; row = key index k
    daily: np.ndarray               # K x G float64
    has_row: np.ndarray             # K x G bool
    oh: np.ndarray                  # K x G float32 (lag filled)
    flags: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def g(self, d: date) -> int:
        return (d - DAY0).days

    def _check(self, d: date) -> int:
        g = self.g(d)
        if d > self.end + timedelta(days=1) or g < 0:
            raise Sel2Error(WINDOW_NOT_COVERED, detail=f"inputs end {self.end}, day {d}")
        return g

    def scope_mask(self, d: date) -> np.ndarray:
        g = self._check(d)
        try:
            return scope.scope_mask(self.daily, self.oh, g)
        except ValueError as e:
            raise Sel2Error(WINDOW_NOT_COVERED, detail=str(e)) from e

    def scope_keys(self, d: date) -> pd.DataFrame:
        return self.keys[self.scope_mask(d)].reset_index(drop=True)

    def _cells(self, d: date, days: int, m: np.ndarray):
        g = self._check(d)
        lo = max(g - days, 0)
        k, t = np.nonzero(m[:, lo:g])
        dates = np.array([DAY0 + timedelta(days=lo + int(x)) for x in range(g - lo)], dtype="datetime64[D]")
        return k, t + lo, dates[t] if len(t) else np.array([], dtype="datetime64[D]")

    def actuals(self, d: date, days: int = SELECT_WINDOW) -> pd.DataFrame:
        """(sku_code, fc_code, date, qty) of the demand rows of d-days .. d-1."""
        k, g, dt = self._cells(d, days, self.has_row)
        return pd.DataFrame({"sku_code": self.keys["sku_code"].to_numpy()[k], "fc_code": self.keys["fc_code"].to_numpy()[k],
                             "date": dt, "qty": self.daily[k, g]})

    def open_days(self, d: date, days: int = SELECT_WINDOW) -> pd.DataFrame:
        """(sku_code, fc_code, date) of the days with open hours > 0 in d-days .. d-1."""
        k, _, dt = self._cells(d, days, np.nan_to_num(self.oh) > 0)
        return pd.DataFrame({"sku_code": self.keys["sku_code"].to_numpy()[k], "fc_code": self.keys["fc_code"].to_numpy()[k],
                             "date": dt})

    def groups(self, d: date, mode: str = "ROLLING_B7", fixed_start=None, fixed_end=None) -> pd.Series:
        """Group A / B / C per (sku_code, fc_code): sku_group.compute_metrics over the open-hours days of d-90 .. d-1
        (ROLLING_B7) or of [fixed_start, fixed_end] (FIXED, reproduction of the backtest only)."""
        if mode == "FIXED":
            ws, we = date.fromisoformat(str(fixed_start)), date.fromisoformat(str(fixed_end))
        else:
            ws, we = d - timedelta(days=sku_group.WINDOW_DAYS), d - timedelta(days=1)
        gs, ge = self.g(ws), self._check(we + timedelta(days=1))
        oh = self.oh[:, max(gs, 0):ge]
        k, t = np.nonzero(np.nan_to_num(oh) > 0)
        g = t + max(gs, 0)
        rows = pd.DataFrame({"fc_code": self.keys["fc_code"].to_numpy()[k], "sku_code": self.keys["sku_code"].to_numpy()[k],
                             "date": np.datetime64(DAY0, "D") + g.astype("timedelta64[D]"),
                             "demand": np.where(self.has_row[k, g], self.daily[k, g], np.nan),
                             "hours": oh[k, t].astype(float)})
        m = sku_group.compute_metrics(rows, ws, we)
        return pd.Series(m["group_code"].to_numpy(dtype=object),
                         index=pd.MultiIndex.from_arrays([m["sku_code"].to_numpy(), m["fc_code"].to_numpy()]))


def _invalid(detail: str):
    raise Sel2Error(OPEN_HOURS_INVALID, detail=detail[:500])


def load_inputs(conn, scope_key: str, D: date, lag_days: int, window_start: str | None = None,
                oh_src: tuple[str, str] | None = None) -> Inputs:
    """Inputs for forecast days up to D (rows < D only); see the module text."""
    end = D - timedelta(days=1)
    window_start = str(window_start or data_window(conn, today=D)["start"])[:10]
    frame, problems = lgbm.load_frame(conn, scope_key, window_start, str(end))
    if frame.empty:
        raise Sel2Error("SEL2_EMPTY_SCOPE", detail=f"no demand row of {scope_key} in {window_start} .. {end}")
    keys = frame[["sku_id", "fc_id"]].drop_duplicates().sort_values(["sku_id", "fc_id"]).to_numpy()
    keys = pd.DataFrame({"sku_code": keys[:, 0].astype(object), "fc_code": keys[:, 1].astype(object)})
    kid = {(s, f): i for i, (s, f) in enumerate(zip(keys["sku_code"], keys["fc_code"]))}
    K, G = len(keys), (D - DAY0).days
    daily = np.zeros((K, G))
    has_row = np.zeros((K, G), dtype=bool)
    fk = np.fromiter((kid[x] for x in zip(frame["sku_id"], frame["fc_id"])), dtype=np.int64, count=len(frame))
    fg = ((frame["od"].to_numpy().astype("datetime64[D]") - np.datetime64(DAY0, "D")).astype(np.int64))
    m = fg >= 0
    daily[fk[m], fg[m]] = frame["qty"].to_numpy(dtype=float)[m]
    has_row[fk[m], fg[m]] = True

    # calendar of the open-hours source (float32, NaN = no row), from the data window start (never before DAY0)
    tbl, seller = oh_src or open_hours_source()
    oh = np.full((K, G), np.nan, dtype=np.float32)
    # NOT INDEXED: one sequential scan; the date index would fetch the rows one by one in date order (hours at ~15 M rows)
    lo = max(date.fromisoformat(window_start), DAY0)
    cur = conn.execute("SELECT sku_code, fc_code, open_date, total_open_hours FROM open_hours_daily NOT INDEXED WHERE "
                       "source_table=? AND seller_code=? AND open_date BETWEEN ? AND ?", (tbl, seller, str(lo), str(end)))
    while True:
        part = cur.fetchmany(READ_ROWS)
        if not part:
            break
        for s, f, d, h in part:
            k = kid.get((s, f))
            if k is not None:
                oh[k, (date.fromisoformat(d[:10]) - DAY0).days] = np.nan if h is None else h
    last = conn.execute("SELECT MAX(open_date) FROM open_hours_daily WHERE source_table=? AND seller_code=? AND "
                        "open_date <= ?", (tbl, seller, str(end))).fetchone()[0]
    if last is None:
        _invalid(f"no open hours of {tbl} / {seller} up to {end}")
    last = date.fromisoformat(last[:10])
    if (end - last).days > lag_days:
        _invalid(f"open hours of {tbl} / {seller} end {last}: more than {lag_days} days before {end}")
    filled_days = []
    for i in range(1, (end - last).days + 1):
        oh[:, (last - DAY0).days + i] = oh[:, (last - DAY0).days]
        filled_days.append(str(last + timedelta(days=i)))

    # demand rows without open hours
    nan = frame["open_hours"].isna().to_numpy()
    rows_filled = 0
    if nan.any():
        first_lag = end - timedelta(days=lag_days - 1) if lag_days else end + timedelta(days=1)
        early = nan & (frame["od"].to_numpy() < np.datetime64(first_lag))
        if early.any():
            days = pd.Series(frame["order_date"].to_numpy()[early]).value_counts().sort_index()
            _invalid(f"{int(early.sum())} demand rows without open hours before {first_lag}: "
                     + ", ".join(f"{d} {n}" for d, n in list(days.items())[:10]))
        status = {(r[0], r[1], r[2][:10]): r[3] for r in conn.execute(
            "SELECT sku_id, fc_id, order_date, open_hours_status FROM demand_daily WHERE scope_key=? AND "
            "order_date BETWEEN ? AND ? AND open_hours IS NULL", (scope_key, str(first_lag), str(end)))}
        known = {}
        lo_k = np.datetime64(first_lag - timedelta(days=lag_days))
        sub = frame[(frame["od"].to_numpy() >= lo_k) & ~nan]
        for s, f, d, h in zip(sub["sku_id"], sub["fc_id"], sub["order_date"], sub["open_hours"]):
            known[(s, f, str(d)[:10])] = float(h)
        vals = frame["open_hours"].to_numpy(dtype=float).copy()
        for i in np.nonzero(nan)[0]:
            s, f, d = frame.at[i, "sku_id"], frame.at[i, "fc_id"], str(frame.at[i, "order_date"])[:10]
            st = status.get((s, f, d))
            if st != "MISSING":
                _invalid(f"{s} x {f} on {d}: open hours status {st}")
            t = date.fromisoformat(d)
            v = None
            for j in range(1, lag_days + 1):
                p = t - timedelta(days=j)
                v = known.get((s, f, str(p)))
                if v is None and p <= last and p >= DAY0:
                    c = oh[kid[(s, f)], (p - DAY0).days]
                    v = None if np.isnan(c) else float(c)
                if v is not None:
                    break
            if v is None:
                _invalid(f"{s} x {f} on {d}: no open hours within the {lag_days} days before")
            vals[i] = v
            rows_filled += 1
        frame["open_hours"] = vals
    flags = [FLAG_OPEN_HOURS_LAG] if filled_days or rows_filled else []
    detail = {"open_hours_lag": {"calendar_days": filled_days, "rows_filled": rows_filled, "source_last_day": str(last),
                                 "lag_days": lag_days},
              "override_problems": len(problems), "window_start": window_start, "end": str(end), "keys": K}
    return Inputs(scope_key, end, window_start, frame, keys, daily, has_row, oh, flags, detail)
