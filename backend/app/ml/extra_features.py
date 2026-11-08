"""1.3.2: extra inputs of the DIRECT model at the forecast origin D (docs/hoc_lai_2025_deal_20261030.md 1.2-1.4).
model.feature_set CHOT_LY adds the 4 same-period-last-year features (E1), CHOT_LY_DEAL those 4 and the 12 deal features
(E2); CHOT (the default, every model before 1.3.2) adds nothing. The formulas are the PREREGISTERED ones:
PREREGISTRATION.md E1 / E2, README section 8 (D3-D7) and code/deal_lib.py of reports/backtest-2025-deal-20261030
(copied for the tests in tests/ref_deal_lib.py), with the same float64 arithmetic (prefix sums) and one float32 cast.

ExtraContext (pure, no DB) holds what the features of an origin D in [day0, last_day + 1] read; d = day index of D from
day0 (= model.ly_history_start). Only what is known at D 00:00 (Vietnam) enters a feature of D: demand and deal lines of
the days before D, the deals with ready_time <= D 00:00 (the deal table stores the Vietnam wall clock), the groups A / B /
C of D's month (B7 rule of sku_group over the 90 days before its first day, open day = hours > 0, a day without demand
= 0, as deal_lib). A day without a demand row is 0 and a window that starts before day0 is NaN (E1). active_on(day) is
the output column deal_active of a target day (ex post, never a model input).

Series universe = demand series U deal series (deal_lib); only the series a feature of `keys` can read are kept in
memory: those of `keys` and every deal series (grp_deal_uplift_hist averages the finished deals of every series of a
group) - the values are the same. A key outside the universe gets deal_lib's defaults.

The DB part at the end (load_context, attach, for_config, check_sources, deal_active_matrix) reads demand_daily,
demand_deal_daily, deals and open_hours_daily of [day0, last_day] only: nothing after last_day is ever read.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .sku_group import A_MAX_ZERO_SHARE, A_MIN_AVG, C_MAX_AVG, C_MIN_ZERO_SHARE, MIN_OPEN_DAYS, WINDOW_DAYS

LY_NAMES = ["ly_same_day", "ly_mean_7", "ly_mean_28", "ly_trend"]
DEAL_NAMES = ["deal_active", "deal_days_since_start", "deal_days_to_end", "deal_max_qty", "deal_used_to_date",
              "deal_remaining_ratio", "deal_used_1", "deal_used_7", "n_active_deals", "sku_deal_uplift_hist",
              "sku_deal_usage_hist", "grp_deal_uplift_hist"]
ALL_NAMES = LY_NAMES + DEAL_NAMES
FEATURE_SETS = {"CHOT": [], "CHOT_LY": LY_NAMES, "CHOT_LY_DEAL": LY_NAMES + DEAL_NAMES}
BASE_DAYS = 28                  # deal_lib: the base of a deal's uplift = mean demand of the 28 days before its start
_LINE_KEY = 100_000             # deal_lib: sort key of a deal line = deal index * 100000 + day index
_SEP = "\x1f"
_CUMSUM_ROWS = 4096             # rows of the prefix-sum matrix accumulated per step (bounded temporary memory)
_READ_CHUNK = 200_000           # rows fetched per step by the DB readers
_LY_NONE = [0.0, 0.0, 0.0, 1.0]                     # deal_lib: a series without any row
_DEAL_NONE = [0.0, np.nan, np.nan, np.nan, 0.0, np.nan, 0.0, 0.0, 0.0, np.nan, np.nan, np.nan]


def extra_names(cfg) -> list[str]:
    """Extra feature names of a model configuration, in model order (a configuration stored before 1.3.2 has no
    feature_set: none)."""
    return list(FEATURE_SETS[getattr(cfg, "feature_set", None) or "CHOT"])


def needs_deals(cfg) -> bool:
    return any(n in DEAL_NAMES for n in extra_names(cfg))


@dataclass
class Rows:
    """Rows already read: keys[si[i]] = (sku_id, fc_id) of row i, di[i] = its day index from day0, val[i] its value
    (demand qty / open hours). The DB readers build it chunk by chunk (no frame of strings for millions of rows)."""
    keys: list
    si: np.ndarray
    di: np.ndarray
    val: np.ndarray


@dataclass
class OpenDays:
    """Open days already read: open[i, a] = series keys[i] open (hours > 0) on day index a (from day0)."""
    keys: list
    open: np.ndarray


@dataclass
class DealLines:
    """Deal lines already read and matched to a deal key: keys[ki[i]] = (deal_code, sku_code, fc_code) of line i, di[i]
    its day index from day0, qty[i] its quantity; n_lines = every line of the window with a deal code (matched or not)."""
    keys: list
    ki: np.ndarray
    di: np.ndarray
    qty: np.ndarray
    n_lines: int


def _no_rows() -> Rows:
    return Rows([], np.empty(0, np.int64), np.empty(0, np.int64), np.empty(0))


def _frame_rows(df: pd.DataFrame | None, date_col: str, val_col: str, day0: date, last_day: date) -> Rows:
    """Rows of a frame (sku_id, fc_id, date_col, val_col) inside [day0, last_day] (deal_lib in_range)."""
    if df is None or not len(df):
        return _no_rows()
    od = pd.to_datetime(df[date_col], format="ISO8601")
    ok = ((od >= pd.Timestamp(day0)) & (od <= pd.Timestamp(last_day))).to_numpy()
    if not ok.any():
        return _no_rows()
    x = df[ok]
    k = x["sku_id"].astype(str).to_numpy(dtype=object) + _SEP + x["fc_id"].astype(str).to_numpy(dtype=object)
    codes, uniq = pd.factorize(k)
    return Rows([tuple(u.split(_SEP, 1)) for u in uniq], codes.astype(np.int64),
                (od[ok] - pd.Timestamp(day0)).dt.days.to_numpy().astype(np.int64),
                pd.to_numeric(x[val_col], errors="coerce").to_numpy(dtype=float))


def _wall_clock(ts) -> pd.Series:
    """Naive Vietnam wall clock of the deal times as stored (deal_lib tz "VN"; never shifted by 7 hours). A missing or
    unreadable time is NaT: the deal cannot be placed in time and is never used."""
    return pd.to_datetime(pd.Series(ts), utc=True, format="ISO8601", errors="coerce").dt.tz_convert(None)


def _dedupe(deals: pd.DataFrame) -> pd.DataFrame:
    """The deal rows used: per (deal_code, sku_code, fc_code) the row with the latest end_time, then the last row in
    input order (deal_lib cannot take two rows with the same key: its line join fails). Input order kept."""
    d = deals.reset_index(drop=True).copy()
    d["_end"] = _wall_clock(d["end_time"]).to_numpy()
    d["_pos"] = np.arange(len(d))
    d = d.sort_values(["_end", "_pos"], kind="mergesort")
    d = d.drop_duplicates(["deal_code", "sku_code", "fc_code"], keep="last").sort_values("_pos")
    return d.drop(columns=["_end", "_pos"]).reset_index(drop=True)


def _classify(n, avg, zero_share) -> np.ndarray:
    """B7 group codes (0 A, 1 B, 2 C) with the thresholds of sku_group.classify."""
    enough = n >= MIN_OPEN_DAYS
    a = enough & (avg > A_MIN_AVG) & (zero_share <= A_MAX_ZERO_SHARE)
    c = enough & (avg <= C_MAX_AVG) & (zero_share > C_MIN_ZERO_SHARE)
    return np.where(a, 0, np.where(c, 2, 1)).astype(np.int8)


class ExtraContext:
    """The data of the extra features of one panel (rows of `keys`, in that order) over [day0, last_day].

    demand: sku_id, fc_id, order_date, qty (or Rows); deals: deal_code, sku_code, fc_code, ready_time, end_time,
    max_quantity, quantity_used (None = no deal source: the deal block is refused); deal_lines: sku_id, fc_id, order_date,
    deal_code, qty; open_days: sku_id, fc_id, date, hours (or Rows; None = no group). open_days_from: first day of the
    open days given (None = day0); a group window that needs earlier days is refused, never computed from missing days.
    Rows outside [day0, last_day] are ignored. The input frames are not kept."""

    def __init__(self, keys, day0, last_day, demand, deals=None, deal_lines=None, open_days=None,
                 open_days_from=None):
        self.keys = [tuple(k) for k in keys]
        self.day0 = pd.Timestamp(day0).date()
        self.last_day = pd.Timestamp(last_day).date()
        self.A = A = (self.last_day - self.day0).days + 1
        if A < 1:
            raise ValueError(f"EXTRA_CONTEXT_RANGE: last day {self.last_day} before day0 {self.day0}")
        dem = demand if isinstance(demand, Rows) else _frame_rows(demand, "order_date", "qty", self.day0, self.last_day)
        d = None if deals is None else _dedupe(deals)
        # application rule for duplicate deal keys (latest end_time, then the last row): counted, never silent
        self.n_deal_rows_dropped = 0 if d is None else len(deals) - len(d)
        self.sources: dict | None = None        # the input checks of the DB part (check_sources), when attached
        deal_keys = [] if d is None else list(zip(d["sku_code"].astype(str), d["fc_code"].astype(str)))
        want = set(self.keys) | set(deal_keys)
        present = np.bincount(dem.si, minlength=len(dem.keys)) > 0
        universe = [k for k, p in zip(dem.keys, present) if p and k in want]
        seen = set(universe)
        universe += [k for k in dict.fromkeys(deal_keys) if k not in seen]
        self._uidx = {k: i for i, k in enumerate(universe)}
        self.n_universe = S = len(universe)
        # demand: ONE float64 prefix-sum matrix S x (A + 1), cum[s, a] = demand of days 0 .. a-1 (a day without a row = 0)
        lmap = np.array([self._uidx.get(tuple(k), -1) for k in dem.keys], dtype=np.int64)
        s = lmap[dem.si] if len(dem.si) else np.empty(0, np.int64)
        ok = (s >= 0) & (dem.di >= 0) & (dem.di < A)
        self.cum = np.zeros((S, A + 1))
        np.add.at(self.cum, (s[ok], dem.di[ok] + 1), dem.val[ok])
        del dem, s, ok, lmap
        for i in range(0, S, _CUMSUM_ROWS):
            blk = self.cum[i:i + _CUMSUM_ROWS]
            np.cumsum(blk, axis=1, out=blk)
        self.deals = d is not None
        self.n_deals = self.n_deal_lines = self.n_deal_lines_matched = 0
        if d is not None:
            self._init_deals(d, deal_lines)
        self._init_open_days(open_days, open_days_from)
        self._groups: dict = {}
        self._rows = np.array([self._uidx.get(k, -1) for k in self.keys], dtype=np.int64)

    # ---------------------------------------------------------------- construction
    def _init_deals(self, d: pd.DataFrame, deal_lines) -> None:
        A, t0 = self.A, pd.Timestamp(self.day0)
        self.n_deals = len(d)
        self._s = np.array([self._uidx.get(k, -1) for k in zip(d["sku_code"].astype(str), d["fc_code"].astype(str))],
                           dtype=np.int64)
        rx = ((_wall_clock(d["ready_time"]) - t0) / pd.Timedelta(days=1)).to_numpy(dtype=float)  # fractional day index
        ex = ((_wall_clock(d["end_time"]) - t0) / pd.Timedelta(days=1)).to_numpy(dtype=float)
        known = np.isfinite(rx) & np.isfinite(ex)
        self._rx, self._ex = rx, ex
        self._start = np.where(known, np.floor(np.where(known, rx, 0.0)), 0.0).astype(np.int64)
        self._end = np.where(known, np.floor(np.where(known, ex, 0.0)), 0.0).astype(np.int64)
        self._valid = known & (rx <= ex) & (self._s >= 0)
        self._maxq = pd.to_numeric(d["max_quantity"], errors="coerce").to_numpy(dtype=float)
        usedq = pd.to_numeric(d["quantity_used"], errors="coerce").to_numpy(dtype=float)
        # deal lines of [day0, last_day] matched to a deal (code, SKU, FC): sorted (deal, day) with prefix sums
        j = lday = lq = np.empty(0)
        if isinstance(deal_lines, DealLines):
            # read and matched in SQL (load_context): the key of each line mapped to the deal row used
            pos = {k: i for i, k in enumerate(zip(d["deal_code"].astype(str), d["sku_code"].astype(str),
                                                  d["fc_code"].astype(str)))}
            kmap = np.array([pos.get(tuple(map(str, k)), -1) for k in deal_lines.keys], dtype=np.int64)
            ok = (deal_lines.di >= 0) & (deal_lines.di < A)
            self.n_deal_lines = int(deal_lines.n_lines)
            j = kmap[deal_lines.ki[ok]] if len(kmap) else np.empty(0, np.int64)
            lday, lq = deal_lines.di[ok].astype(np.int64), deal_lines.qty[ok]
        elif deal_lines is not None and len(deal_lines):
            ln = deal_lines[deal_lines["deal_code"].notna()]
            od = pd.to_datetime(ln["order_date"], format="ISO8601")
            ln = ln[((od >= t0) & (od <= pd.Timestamp(self.last_day))).to_numpy()]
            self.n_deal_lines = len(ln)
            dix = pd.Index(d["deal_code"].astype(str) + _SEP + d["sku_code"].astype(str) + _SEP
                           + d["fc_code"].astype(str))
            j = dix.get_indexer(ln["deal_code"].astype(str) + _SEP + ln["sku_id"].astype(str) + _SEP
                                + ln["fc_id"].astype(str)).astype(np.int64)
            lday = (pd.to_datetime(ln["order_date"], format="ISO8601") - t0).dt.days.to_numpy().astype(np.int64)
            lq = ln["qty"].to_numpy(dtype=float)
        m = j >= 0
        self.n_deal_lines_matched = int(m.sum())
        order = np.lexsort((lday[m], j[m]))
        self._l_key = (j[m][order] * _LINE_KEY + lday[m][order]).astype(np.int64)
        self._l_cum = np.concatenate([[0.0], np.cumsum(lq[m][order])])
        # per-deal constants of the history features (deal_lib _deal_metrics): sales of the deal's days up to the last
        # day vs the mean of the 28 days before its start; read only for deals finished before the origin
        c = self.cum
        s = np.where(self._s >= 0, self._s, 0)
        a = self._start
        b = np.minimum(self._end, A - 1)
        valid = self._valid & (a >= 0) & (a < A)
        aa, bb = np.clip(a, 0, A), np.clip(b + 1, 0, A)
        if len(c):
            sales = np.where(valid & (bb > aa), c[s, bb] - c[s, aa], np.nan)
            base_ok = valid & (a - BASE_DAYS >= 0)
            base = np.where(base_ok, (c[s, np.clip(a, 0, A)] - c[s, np.clip(a - BASE_DAYS, 0, A)]) / float(BASE_DAYS),
                            np.nan)
        else:
            sales = base = np.full(len(a), np.nan)
        ndays = np.where(valid, np.maximum(bb - aa, 0), np.nan)
        with np.errstate(all="ignore"):
            self._uplift = np.where(base > 0, sales / (base * ndays), np.nan)
            self._usage = np.where(self._maxq > 0, usedq / self._maxq, np.nan)

    def _init_open_days(self, open_days, open_days_from) -> None:
        self._open = None
        self._open_from = 0 if open_days_from is None else (pd.Timestamp(open_days_from).date() - self.day0).days
        if open_days is None:
            return
        self._open = np.zeros((self.n_universe, self.A), dtype=bool)
        if isinstance(open_days, OpenDays):
            pos = {tuple(k): i for i, k in enumerate(open_days.keys)}
            for u, k in enumerate(self._uidx):
                i = pos.get(k)
                if i is not None:
                    self._open[u] = open_days.open[i]
            return
        od = (open_days if isinstance(open_days, Rows)
              else _frame_rows(open_days, "date", "hours", self.day0, self.last_day))
        lmap = np.array([self._uidx.get(tuple(k), -1) for k in od.keys], dtype=np.int64)
        s = lmap[od.si] if len(od.si) else np.empty(0, np.int64)
        ok = (s >= 0) & (od.di >= 0) & (od.di < self.A) & (od.val > 0)       # open day = hours > 0
        self._open[s[ok], od.di[ok]] = True

    # ---------------------------------------------------------------- helpers
    @property
    def info(self) -> dict:
        return {"day0": str(self.day0), "last_day": str(self.last_day), "n_keys": len(self.keys),
                "n_universe": self.n_universe, "n_deals": self.n_deals if self.deals else None,
                "n_deal_lines": self.n_deal_lines if self.deals else None,
                "n_deal_lines_matched": self.n_deal_lines_matched if self.deals else None,
                "n_deal_rows_dropped_duplicate_key": self.n_deal_rows_dropped if self.deals else None,
                "open_days": self._open is not None,
                "groups_by_month": {str(m): {"A": int((g == 0).sum()), "B": int((g == 1).sum()), "C": int((g == 2).sum()),
                                             "none": int((g < 0).sum())} for m, g in sorted(self._groups.items())},
                "sources": self.sources}

    def _origin(self, D) -> int:
        d = (pd.Timestamp(D).date() - self.day0).days
        if d > self.A:
            raise ValueError(f"EXTRA_CONTEXT_RANGE: origin {D} is after the context's last day {self.last_day} + 1")
        return d

    def _need_deals(self) -> None:
        if not self.deals:
            raise ValueError("DEAL_SOURCE_NOT_CONFIGURED: the context has no deal table")

    def _lines_between(self, deal_idx: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
        """qty of the lines of each deal on days lo .. hi-1 (half-open)."""
        a = np.searchsorted(self._l_key, deal_idx * _LINE_KEY + np.maximum(lo, -1), side="left")
        b = np.searchsorted(self._l_key, deal_idx * _LINE_KEY + np.maximum(hi, -1), side="left")
        return self._l_cum[b] - self._l_cum[a]

    def groups_at(self, D) -> np.ndarray:
        """B7 groups at the first day of D's month over the 90 days before it, one code per universe series (0 A, 1 B,
        2 C, -1 none: no open day in the window or no open-hours data). Cached per month."""
        m0 = pd.Timestamp(D).date().replace(day=1)
        if m0 in self._groups:
            return self._groups[m0]
        we = (m0 - self.day0).days - 1
        ws = we - WINDOW_DAYS + 1
        out = np.full(self.n_universe, -1, dtype=np.int8)
        if self._open is not None and we >= 0:
            lo, hi = max(ws, 0), min(we, self.A - 1) + 1
            if lo < self._open_from:
                raise ValueError(f"EXTRA_CONTEXT_RANGE: the groups of {m0} need the open days from "
                                 f"{self.day0 + timedelta(days=lo)}, loaded from {self.day0 + timedelta(days=self._open_from)}")
            op = self._open[:, lo:hi]
            dem = np.diff(self.cum[:, lo:hi + 1], axis=1)
            n = op.sum(axis=1)
            q = np.where(op, dem, 0.0).sum(axis=1)
            z = (op & (dem == 0)).sum(axis=1)
            has = n > 0
            with np.errstate(all="ignore"):
                g = _classify(n, np.where(has, q / np.maximum(n, 1), 0), np.where(has, z / np.maximum(n, 1), 0))
            out = np.where(has, g, -1).astype(np.int8)
        self._groups[m0] = out
        return out

    def daily(self, key, first, last) -> list[tuple[str, float | None]]:
        """Demand of one series per day first..last (None = before day0; a day without a row = 0) - for explanations."""
        r = self._uidx.get(tuple(key))
        out = []
        for i in range((pd.Timestamp(first).date() - self.day0).days, (pd.Timestamp(last).date() - self.day0).days + 1):
            v = None if i < 0 or i >= self.A else (0.0 if r is None else float(self.cum[r, i + 1] - self.cum[r, i]))
            out.append((str(self.day0 + timedelta(days=i)), v))
        return out

    # ---------------------------------------------------------------- features of origin D
    def ly_block(self, D) -> np.ndarray:
        """E1: len(keys) x 4 (LY_NAMES) from the days before D only (D-419 .. D-361)."""
        d = self._origin(D)
        rows = self._rows
        has = rows >= 0
        r = np.where(has, rows, 0)
        c = self.cum

        def mean(lo, hi):        # days lo .. hi inclusive, hi < d
            if lo < 0:
                return np.full(len(rows), np.nan)
            if not len(c):
                return np.zeros(len(rows))
            return (c[r, hi + 1] - c[r, lo]) / (hi - lo + 1)
        out = np.zeros((len(rows), 4))
        out[:, 0] = mean(d - 364, d - 364)
        out[:, 1] = mean(d - 367, d - 361)
        out[:, 2] = mean(d - 391, d - 364)
        prev = mean(d - 419, d - 392)
        with np.errstate(all="ignore"):
            out[:, 3] = np.where(np.isnan(prev), np.nan,
                                 np.where(prev > 0, out[:, 2] / np.where(prev > 0, prev, 1), 1.0))
        out[~has] = np.array(_LY_NONE)
        if d - 419 < 0:
            out[~has, 3] = np.nan
        return out.astype(np.float32)

    def deal_block(self, D) -> np.ndarray:
        """E2: len(keys) x 12 (DEAL_NAMES) of the deals visible at D 00:00 (ready <= D) and the lines of the days < D."""
        self._need_deals()
        d = self._origin(D)
        S = self.n_universe
        s, valid, rx, ex = self._s, self._valid, self._rx, self._ex
        act = valid & (rx <= d) & (ex >= d)
        fin = valid & (ex < d)
        ia = np.flatnonzero(act)
        sa = s[ia]
        n_act = np.bincount(sa, minlength=S).astype(float)
        since = np.full(S, np.inf)
        np.minimum.at(since, sa, d - self._start[ia])
        to_end = np.full(S, -np.inf)
        np.maximum.at(to_end, sa, self._end[ia] - d)
        maxq = np.bincount(sa, weights=np.nan_to_num(self._maxq[ia]), minlength=S)
        k = len(ia)
        used = np.bincount(sa, weights=self._lines_between(ia, np.zeros(k, np.int64), np.full(k, d)), minlength=S)
        u1 = np.bincount(sa, weights=self._lines_between(ia, np.full(k, d - 1), np.full(k, d)), minlength=S)
        u7 = np.bincount(sa, weights=self._lines_between(ia, np.full(k, d - 7), np.full(k, d)), minlength=S)
        # history of the finished deals (end < D 00:00): their days and the 28 days before them are all < D
        jf = np.flatnonzero(fin)
        upl, usg = self._uplift[jf], self._usage[jf]
        sf = s[jf]
        ok_u, ok_g = ~np.isnan(upl), ~np.isnan(usg)
        n_u = np.bincount(sf[ok_u], minlength=S)
        s_u = np.bincount(sf[ok_u], weights=upl[ok_u], minlength=S)
        n_g = np.bincount(sf[ok_g], minlength=S)
        s_g = np.bincount(sf[ok_g], weights=usg[ok_g], minlength=S)
        grp = self.groups_at(D)
        gf = grp[sf[ok_u]]
        g_u = np.array([upl[ok_u][gf == g].mean() if np.any(gf == g) else np.nan for g in range(3)])
        with np.errstate(all="ignore"):
            f = np.full((S, len(DEAL_NAMES)), np.nan)
            on = n_act > 0
            f[:, 0] = on.astype(float)
            f[:, 1] = np.where(on, since, np.nan)
            f[:, 2] = np.where(on, to_end, np.nan)
            f[:, 3] = np.where(on, maxq, np.nan)
            f[:, 4] = np.where(on, used, 0.0)
            f[:, 5] = np.where(on & (maxq > 0), 1.0 - used / np.where(maxq > 0, maxq, 1), np.nan)
            f[:, 6] = np.where(on, u1, 0.0)
            f[:, 7] = np.where(on, u7, 0.0)
            f[:, 8] = n_act
            f[:, 9] = np.where(n_u > 0, s_u / np.maximum(n_u, 1), np.nan)
            f[:, 10] = np.where(n_g > 0, s_g / np.maximum(n_g, 1), np.nan)
            f[:, 11] = np.where((n_u == 0) & (grp >= 0), g_u[np.clip(grp, 0, 2)], np.nan)
        rows = self._rows
        has = rows >= 0
        out = np.full((len(rows), len(DEAL_NAMES)), np.nan)
        out[has] = f[rows[has]]
        out[~has] = np.array(_DEAL_NONE)
        return out.astype(np.float32)

    def block(self, D, names) -> np.ndarray:
        """len(keys) x len(names) float32: the named extra features of origin D, in the order of `names`."""
        names = list(names)
        bad = [n for n in names if n not in ALL_NAMES]
        if bad:
            raise ValueError(f"unknown extra feature(s): {bad}")
        out = np.empty((len(self.keys), len(names)), dtype=np.float32)
        if any(n in LY_NAMES for n in names):
            ly = self.ly_block(D)
            for i, n in enumerate(names):
                if n in LY_NAMES:
                    out[:, i] = ly[:, LY_NAMES.index(n)]
        if any(n in DEAL_NAMES for n in names):
            dl = self.deal_block(D)
            for i, n in enumerate(names):
                if n in DEAL_NAMES:
                    out[:, i] = dl[:, DEAL_NAMES.index(n)]
        return out

    def active_on(self, D) -> np.ndarray:
        """Output column deal_active of target day D (int8 per key): 1 when a valid deal of the series covers the day
        (start day <= D <= end day), else 0. Ex post: never a model input."""
        self._need_deals()
        d = (pd.Timestamp(D).date() - self.day0).days
        act = self._valid & (self._start <= d) & (self._end >= d)
        on = np.zeros(self.n_universe, dtype=np.int8)
        on[self._s[act]] = 1
        rows = self._rows
        out = np.zeros(len(rows), dtype=np.int8)
        out[rows >= 0] = on[rows[rows >= 0]]
        return out


# ---------------------------------------------------------------------------------------------------------- DB part
def _ly_start(cfg) -> date:
    v = getattr(cfg, "ly_history_start", None)
    if not v:
        from ..messages import AppError
        raise AppError("LY_HISTORY_NOT_CONFIGURED", 409,
                       detail=f"feature_set {getattr(cfg, 'feature_set', None)}: model.ly_history_start is not set")
    return date.fromisoformat(str(v)[:10])


def deal_source(conn) -> dict | None:
    """The configured deal table with its stored rows: {table, deal_code_column, snapshot_id, n_deals}; None when
    bigquery.deal_table_id is empty or no row of it is stored."""
    from .. import settings_service as ss
    bq = ss.get("bigquery", conn)
    if not bq.deal_table_id:
        return None
    snaps = conn.execute("SELECT snapshot_id, COUNT(*) FROM deals WHERE source_table=? GROUP BY snapshot_id "
                         "ORDER BY snapshot_id", (bq.deal_table_id,)).fetchall()
    if not snaps:
        return None
    ids = [r[0] for r in snaps]
    return {"table": bq.deal_table_id, "deal_code_column": bq.deal_code_column,
            "snapshot_id": ids[0] if len(ids) == 1 else ids, "n_deals": int(sum(r[1] for r in snaps))}


def _deal_source_or_refuse(conn) -> dict:
    src = deal_source(conn)
    if src is None or not src["deal_code_column"]:
        from ..messages import AppError
        raise AppError("DEAL_SOURCE_NOT_CONFIGURED", 409,
                       detail="bigquery.deal_table_id / deal_code_column empty or no deal-table row stored")
    return src


def _read_deals(conn, table: str) -> pd.DataFrame:
    return pd.read_sql_query("SELECT deal_code, sku_code, fc_code, ready_time, end_time, max_quantity, quantity_used "
                             "FROM deals WHERE source_table=? ORDER BY row_no", conn, params=(table,))


def _uncovered(windows, start: date, end: date) -> list[dict]:
    """Day ranges of [start, end] that none of the (first, last) ISO day windows covers."""
    out, cur = [], start
    for a, b in sorted((date.fromisoformat(str(a)[:10]), date.fromisoformat(str(b)[:10])) for a, b in windows if a and b):
        if b < cur:
            continue
        if a > cur:
            out.append((cur, min(a - timedelta(days=1), end)))
        cur = max(cur, b + timedelta(days=1))
        if cur > end:
            break
    if cur <= end:
        out.append((cur, end))
    return [{"start": str(a), "end": str(b)} for a, b in out if a <= b]


def _months(first: date, last: date) -> list[date]:
    m, out = first.replace(day=1), []
    while m <= last:
        out.append(m)
        m = (m + timedelta(days=32)).replace(day=1)
    return out


def _short(items: list, n: int = 12) -> str:
    txt = ", ".join(f"{r['start']}..{r['end']}" if isinstance(r, dict) else str(r) for r in items[:n])
    return txt + (f" (+{len(items) - n} more)" if len(items) > n else "")


def check_sources(conn, cfg, scope_key: str | None = None, last_day=None, window_start=None,
                  first_origin=None) -> dict | None:
    """The input checks of the extra features, recorded with the run (decisions["extra_features"]) and with a daily
    refresh. A day without a row counts 0 only where the history was really loaded (AGENTS.md 4: missing is not 0):
      * same period last year: every calendar month of [day0, window_start) has demand_daily rows of the scope and every
        day of it is inside the window of a COMMITTED BACKFILL / D1_SYNC run of the scope (demand_sync_runs) - else
        AppError LY_HISTORY_NOT_CONFIGURED listing the months / days;
      * deals: the deal table is configured and stored, and every day of [day0, last_day] is inside a deal_line_loads
        window of the scope - else AppError DEAL_SOURCE_NOT_CONFIGURED listing the uncovered days.
    Also recorded: the duplicate deal keys (rows dropped by the latest-end_time rule) and, per origin month from
    first_origin to last_day + 1, the days with open hours in its 90-day group window (grp_deal_uplift_hist). None for
    CHOT."""
    from ..messages import AppError
    names = extra_names(cfg)
    if not names:
        return None
    day0 = _ly_start(cfg)
    out = {"feature_set": cfg.feature_set, "names": names, "ly_history_start": str(day0)}
    last = pd.Timestamp(last_day).date() if last_day else None
    if scope_key and window_start and day0 < pd.Timestamp(window_start).date():
        hist_end = pd.Timestamp(window_start).date() - timedelta(days=1)
        with_rows = {r[0] for r in conn.execute(
            "SELECT DISTINCT substr(order_date, 1, 7) FROM demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?",
            (scope_key, str(day0), str(hist_end)))}
        no_rows = [m.strftime("%Y-%m") for m in _months(day0, hist_end) if m.strftime("%Y-%m") not in with_rows]
        runs = conn.execute("SELECT window_start, window_end FROM demand_sync_runs WHERE scope_key=? AND "
                            "status='COMMITTED' AND kind IN ('BACKFILL', 'D1_SYNC') AND window_start <= ? AND "
                            "window_end >= ?", (scope_key, str(hist_end), str(day0))).fetchall()
        gaps = _uncovered(runs, day0, hist_end)
        out["history"] = {"start": str(day0), "end": str(hist_end), "months_without_rows": no_rows,
                          "days_not_loaded": gaps, "runs": len(runs)}
        if no_rows or gaps:
            raise AppError("LY_HISTORY_NOT_CONFIGURED", 409, detail=(
                f"extended history {day0}..{hist_end} not loaded: months without demand rows [{_short(no_rows)}]; "
                f"days outside a committed BACKFILL / D1_SYNC run [{_short(gaps)}]"))
    if needs_deals(cfg):
        src = _deal_source_or_refuse(conn)
        dup = conn.execute("SELECT COUNT(*), COALESCE(SUM(n), 0) FROM (SELECT COUNT(*) AS n FROM deals WHERE "
                           "source_table=? GROUP BY deal_code, sku_code, fc_code HAVING COUNT(*) > 1)",
                           (src["table"],)).fetchone()
        out.update(deal_table=src["table"], deal_code_column=src["deal_code_column"],
                   deal_snapshot_id=src["snapshot_id"], n_deals=src["n_deals"],
                   duplicate_deal_keys={"keys": int(dup[0]), "rows": int(dup[1]),
                                        "rows_dropped": int(dup[1]) - int(dup[0]),
                                        "rule": "LATEST_END_TIME_THEN_LAST_ROW"})
        if scope_key and last:
            out["n_deal_lines"] = conn.execute("SELECT COUNT(*) FROM demand_deal_daily WHERE scope_key=? AND "
                                               "order_date BETWEEN ? AND ?",
                                               (scope_key, str(day0), str(last))).fetchone()[0]
            loads = conn.execute("SELECT range_start, range_end FROM deal_line_loads WHERE scope_key=? AND "
                                 "range_start <= ? AND range_end >= ?", (scope_key, str(last), str(day0))).fetchall()
            gaps = _uncovered(loads, day0, last)
            out["deal_lines_loaded"] = {"start": str(day0), "end": str(last), "loads": len(loads),
                                        "days_not_loaded": gaps}
            if gaps:
                raise AppError("DEAL_SOURCE_NOT_CONFIGURED", 409, detail=(
                    f"deal lines (demand_deal_daily) not loaded for {_short(gaps)} of {day0}..{last}"))
        if last and first_origin:
            from ..bq.aux_sources import open_hours_source
            tbl, seller = open_hours_source()
            cov = []
            for m0 in _months(pd.Timestamp(first_origin).date(), last + timedelta(days=1)):
                a, b = max(day0, m0 - timedelta(days=WINDOW_DAYS)), m0 - timedelta(days=1)
                r = conn.execute("SELECT COUNT(DISTINCT open_date), COUNT(*) FROM open_hours_daily WHERE source_table=? "
                                 "AND seller_code=? AND open_date BETWEEN ? AND ? AND total_open_hours > 0",
                                 (tbl, seller, str(a), str(b))).fetchone()
                cov.append({"month": str(m0), "window": [str(a), str(b)], "window_days": max((b - a).days + 1, 0),
                            "days_with_open_hours": int(r[0]), "open_rows": int(r[1])})
            out["group_open_hours"] = cov
    return out


def _chunks(conn, sql: str, params, want: set, day0: date):
    """(sorted want keys, iterator of (key index, day index, value) arrays) of a query (sku, fc, day, value) read in
    chunks, only the series in `want` (int32 indices: no frame of strings for millions of rows)."""
    keys = sorted(want)
    kix = pd.Index([s + _SEP + f for s, f in keys])

    def it():
        for ch in pd.read_sql_query(sql, conn, params=params, chunksize=_READ_CHUNK):
            k = kix.get_indexer(ch.iloc[:, 0].astype(str) + _SEP + ch.iloc[:, 1].astype(str))
            ok = k >= 0
            if ok.any():
                yield (k[ok].astype(np.int32),
                       (pd.to_datetime(ch.iloc[:, 2][ok], format="ISO8601") - pd.Timestamp(day0)).dt.days
                       .to_numpy().astype(np.int32),
                       pd.to_numeric(ch.iloc[:, 3][ok], errors="coerce").to_numpy(dtype=float))
    return keys, it()


def _read_rows(conn, sql: str, params, want: set, day0: date) -> Rows:
    keys, it = _chunks(conn, sql, params, want, day0)
    parts = list(zip(*it))
    if not parts:
        return Rows(keys, np.empty(0, np.int32), np.empty(0, np.int32), np.empty(0))
    return Rows(keys, *(np.concatenate(x) for x in parts))


def _read_deal_lines(conn, scope_key: str, deals: pd.DataFrame, day0: date, last: date) -> DealLines:
    """demand_deal_daily of [day0, last] in chunks, each mapped straight to (deal key index, day index, qty) and freed:
    the ~3 M lines are never one frame of strings. Lines whose (deal_code, SKU, FC) is not in the deal table drop out."""
    keys = list(dict.fromkeys(zip(deals["deal_code"].astype(str), deals["sku_code"].astype(str),
                                  deals["fc_code"].astype(str))))
    kix = pd.Index([_SEP.join(k) for k in keys])
    ki, di, qty, n = [], [], [], 0
    for ch in pd.read_sql_query("SELECT deal_code, sku_id, fc_id, order_date, qty FROM demand_deal_daily WHERE "
                                "scope_key=? AND order_date BETWEEN ? AND ?", conn,
                                params=(scope_key, str(day0), str(last)), chunksize=_READ_CHUNK):
        n += len(ch)
        k = kix.get_indexer(ch["deal_code"].astype(str) + _SEP + ch["sku_id"].astype(str) + _SEP
                            + ch["fc_id"].astype(str))
        ok = k >= 0
        if ok.any():
            ki.append(k[ok].astype(np.int32))
            di.append((pd.to_datetime(ch["order_date"][ok], format="ISO8601") - pd.Timestamp(day0)).dt.days
                      .to_numpy().astype(np.int32))
            qty.append(ch["qty"][ok].to_numpy(dtype=float))
        del ch, k, ok
    if not ki:
        return DealLines(keys, np.empty(0, np.int32), np.empty(0, np.int32), np.empty(0), n)
    return DealLines(keys, np.concatenate(ki), np.concatenate(di), np.concatenate(qty), n)


def _read_open_days(conn, sql: str, params, want: set, day0: date, n_days: int) -> OpenDays:
    """The open days (value > 0) of a query marked in a len(want) x n_days boolean matrix while read."""
    keys, it = _chunks(conn, sql, params, want, day0)
    m = np.zeros((len(keys), n_days), dtype=bool)
    for si, di, v in it:
        ok = (di >= 0) & (di < n_days) & (v > 0)
        m[si[ok], di[ok]] = True
    return OpenDays(keys, m)


def load_context(conn, scope_key: str, keys, cfg, last_day, first_day=None) -> ExtraContext:
    """ExtraContext of a model configuration for `keys` of scope_key, data of [day0 = cfg.ly_history_start, last_day]:
    demand_daily of the scope; for the deal features also the deal table (bigquery.deal_table_id), demand_deal_daily
    of the scope and the open days of the configured open-hours read (daily_forecast) from the group window of the first
    day an origin can have (first_day; None = day0). Refused (AppError) when the feature set needs a missing input."""
    if conn is None:
        from .. import db
        with db.read() as c:
            return load_context(c, scope_key, keys, cfg, last_day, first_day)
    day0 = _ly_start(cfg)
    last = pd.Timestamp(last_day).date()
    want = {tuple(k) for k in keys}
    deals = lines = od = None
    od_from = None
    if needs_deals(cfg):
        from ..bq.aux_sources import open_hours_source
        src = _deal_source_or_refuse(conn)
        deals = _read_deals(conn, src["table"])
        want |= set(zip(deals["sku_code"].astype(str), deals["fc_code"].astype(str)))
        lines = _read_deal_lines(conn, scope_key, deals, day0, last)
        od_from = day0
        if first_day is not None:      # groups of an origin D read the 90 days before the first day of D's month
            m0 = pd.Timestamp(first_day).date().replace(day=1)
            od_from = max(day0, m0 - timedelta(days=WINDOW_DAYS))
        tbl, seller = open_hours_source()
        od = _read_open_days(conn, "SELECT sku_code, fc_code, open_date, total_open_hours FROM open_hours_daily "
                                   "WHERE source_table=? AND seller_code=? AND open_date BETWEEN ? AND ? "
                                   "AND total_open_hours > 0", (tbl, seller, str(od_from), str(last)), want, day0,
                             (last - day0).days + 1)
    # NOT INDEXED: one sequential scan, as data/demand.load_demand (the key index fetches every row again for qty)
    dem = _read_rows(conn, "SELECT sku_id, fc_id, order_date, qty FROM demand_daily NOT INDEXED WHERE scope_key=? "
                           "AND order_date BETWEEN ? AND ?", (scope_key, str(day0), str(last)), want, day0)
    return ExtraContext(keys, day0, last, dem, deals=deals, deal_lines=lines, open_days=od, open_days_from=od_from)


def attach(panel, scope_key: str, cfg, conn=None, first_origin=None, sources: dict | None = None):
    """panel.extra = the ExtraContext cfg needs (keys = panel.keys, last day = the panel's last day); nothing for CHOT.
    first_origin: the earliest origin the caller computes (None = the panel's first day); sources: the result of
    check_sources, kept with the context (ExtraContext.info)."""
    if extra_names(cfg):
        panel.extra = load_context(conn, scope_key, panel.keys, cfg, panel.dates[-1].date(),
                                   first_day=first_origin or panel.dates[0].date())
        panel.extra.sources = sources
    return panel


def for_config(panel, scope_key: str, cfg, conn=None):
    """The panel for another configuration (e.g. the incumbent in a comparison): the panel itself when it carries the
    context cfg needs (or cfg needs none), else a shallow copy (same arrays) with cfg's own context."""
    if not extra_names(cfg):
        return panel
    x = panel.extra
    if (x is not None and x.day0 == _ly_start(cfg) and x.last_day == panel.dates[-1].date() and x.keys == panel.keys
            and (x.deals or not needs_deals(cfg))):
        return panel
    return attach(replace(panel, extra=None), scope_key, cfg, conn)


def config_of_run(tr: dict):
    """The stored model configuration of a training run, as attributes (extra_names / load_context read it)."""
    import json
    from types import SimpleNamespace
    cfg = (json.loads((tr or {}).get("feature_config_json") or "{}") or {}).get("config") or {}
    return SimpleNamespace(**cfg)


def deal_active_matrix(conn, keys, dates) -> tuple[np.ndarray | None, dict | None]:
    """(len(keys) x len(dates) int8 deal_active, deal source) of the daily refresh output: 1 when a valid deal of the
    configured deal table covers the target day (start day <= day <= end day), else 0. (None, None) when
    bigquery.deal_table_id is empty or no deal is stored."""
    src = deal_source(conn)
    if src is None:
        return None, None
    days = [pd.Timestamp(x).date() for x in dates]
    if not days:
        return np.zeros((len(keys), 0), dtype=np.int8), src
    ctx = ExtraContext(keys, days[0], days[0], _no_rows(), deals=_read_deals(conn, src["table"]))
    return np.column_stack([ctx.active_on(x) for x in days]).astype(np.int8), src
