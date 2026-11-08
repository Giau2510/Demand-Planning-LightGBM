"""Test helper of release 1.3.2 (extra model features E1 / E2): the PREREGISTERED reference formulas and the synthetic
fixtures shared by tests/test_v132_ref_deal_lib.py and tests/test_v132_extra_features.py. Never imported by the app.

PART 1 - reference copy.
Source: D:\\Buymed\\Lightgbm AI\\reports\\backtest-2025-deal-20261030\\code\\deal_lib.py (backtest of 29-30/10/2026,
PREREGISTRATION.md SHA 69B58C06..., README section 8 D3-D7): day_index, wall_clock, classify_groups and class Snapshot
(__init__, lines_between, _deal_metrics, groups_at, ly_features, deal_features, active_on, index_of, rows_of). The
arithmetic is kept identical, line by line. Adaptations, and nothing else:
  * inputs are in-memory DataFrames with the application's column names: demand (sku_id, fc_id, order_date, qty),
    deal_lines (sku_id, fc_id, order_date, deal_code, qty), deals (deal_code, sku_code, fc_code, ready_time, end_time,
    max_quantity, quantity_used), open_days (sku_id, fc_id, date, hours);
  * DAY0 is the parameter day0 (deal_lib: the constant 2025-01-01);
  * the demand of a series is the demand frame (deal_lib: every line of its one frame, deal or not) and the deal lines
    are the separate deal_lines frame (deal_lib: the rows of that frame carrying a deal_code); both are restricted to
    [day0, last_day] exactly as deal_lib restricted its frame;
  * series universe (keys=None) = demand series U deal series (deal_lib: frame series U deal series);
  * deal times are naive Vietnam wall clock only (deal_lib tz "VN"); the "UTC" (+7 h) reading is not offered;
  * open days = the open_days rows with hours > 0 (deal_lib read open_days.parquet, which held only those rows);
    load_open_days is replaced by the same mapping inside __init__.
deal_lib (and this copy) cannot take two deal rows with the same (deal_code, sku_code, fc_code): pandas raises in the
line join. The application keeps the row with the latest end_time (then the last row in input order); the tests apply
that rule with dedupe_like_app() before calling this copy.

PART 2 - synthetic fixtures (not from deal_lib): hand_case() with HAND_* expected values computed by hand (arithmetic in
the comments) and random_case(seed). Synthetic data only.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

LY_NAMES = ["ly_same_day", "ly_mean_7", "ly_mean_28", "ly_trend"]
DEAL_NAMES = ["deal_active", "deal_days_since_start", "deal_days_to_end", "deal_max_qty", "deal_used_to_date",
              "deal_remaining_ratio", "deal_used_1", "deal_used_7", "n_active_deals", "sku_deal_uplift_hist",
              "sku_deal_usage_hist", "grp_deal_uplift_hist"]
GROUP_CODES = {"A": 0, "B": 1, "C": 2}
# B7 rule of the application 1.3.1 (app/ml/sku_group.py)
G_WINDOW, G_MIN_OPEN, G_A_AVG, G_A_ZERO, G_C_AVG, G_C_ZERO = 90, 14, 20.0, 0.20, 5.0, 0.20


# ====================================================================== PART 1: reference copy of deal_lib.py
def wall_clock(ts: pd.Series) -> pd.Series:
    """Naive Vietnam wall-clock times (deal_lib tz "VN": the stored components are the Vietnam time)."""
    return pd.to_datetime(ts, utc=True).dt.tz_convert(None)


def classify_groups(n_open, avg, zero_share) -> np.ndarray:
    enough = n_open >= G_MIN_OPEN
    a = enough & (avg > G_A_AVG) & (zero_share <= G_A_ZERO)
    c = enough & (avg <= G_C_AVG) & (zero_share > G_C_ZERO)
    return np.where(a, 0, np.where(c, 2, 1)).astype(np.int8)


class Snapshot:
    def __init__(self, demand: pd.DataFrame, deals: pd.DataFrame, deal_lines: pd.DataFrame,
                 open_days: pd.DataFrame | None, day0, last_day, keys=None):
        self.day0 = pd.Timestamp(day0).date()
        DAY0 = self.day0
        self.last_day = pd.Timestamp(last_day).date()
        self.A = self.day_index(self.last_day) + 1

        def in_range(df):
            od = pd.to_datetime(df["order_date"])
            return df[(od >= pd.Timestamp(DAY0)) & (od <= pd.Timestamp(self.last_day))]
        dem_df = in_range(demand)
        if keys is None:
            keys = sorted(set(zip(dem_df["sku_id"], dem_df["fc_id"])) | set(zip(deals["sku_code"], deals["fc_code"])))
        self.keys = list(keys)
        self.kidx = {k: i for i, k in enumerate(self.keys)}
        self._kix = pd.Index([f"{s}\x1f{f}" for s, f in self.keys])
        S, A = len(self.keys), self.A
        si = self.index_of(dem_df["sku_id"], dem_df["fc_id"])
        di = (pd.to_datetime(dem_df["order_date"]) - pd.Timestamp(DAY0)).dt.days.to_numpy()
        q = dem_df["qty"].to_numpy(dtype=float)
        ok = si >= 0
        self.dem = np.zeros((S, A))
        np.add.at(self.dem, (si[ok], di[ok]), q[ok])
        self.cum = np.concatenate([np.zeros((S, 1)), np.cumsum(self.dem, axis=1)], axis=1)
        # deals
        d = deals.reset_index(drop=True).copy()
        d["s"] = self.index_of(d["sku_code"], d["fc_code"])
        r, e = wall_clock(d["ready_time"]), wall_clock(d["end_time"])
        d["ready_x"] = ((r - pd.Timestamp(DAY0)) / pd.Timedelta(days=1)).to_numpy()   # fractional day index
        d["end_x"] = ((e - pd.Timestamp(DAY0)) / pd.Timedelta(days=1)).to_numpy()
        d["start_day"] = np.floor(d["ready_x"]).astype(np.int64)
        d["end_day"] = np.floor(d["end_x"]).astype(np.int64)
        d["valid"] = (d["ready_x"] <= d["end_x"]) & (d["s"] >= 0)
        d["days"] = (d["end_day"] - d["start_day"] + 1).where(d["valid"])
        d["maxq"] = pd.to_numeric(d["max_quantity"], errors="coerce").astype(float)
        d["usedq"] = pd.to_numeric(d["quantity_used"], errors="coerce").astype(float)
        self.deals = d
        # deal lines: (deal index, day, qty), sorted, with prefix sums per deal
        dix = pd.Index(d["deal_code"].astype(str) + "\x1f" + d["sku_code"].astype(str) + "\x1f" + d["fc_code"].astype(str))
        lines = in_range(deal_lines)
        ln = lines[lines["deal_code"].notna()]
        j = dix.get_indexer(ln["deal_code"].astype(str) + "\x1f" + ln["sku_id"].astype(str) + "\x1f"
                            + ln["fc_id"].astype(str)).astype(np.int64)
        self.line_info = {"lines": int(len(ln)), "qty": float(ln["qty"].sum()), "matched": int((j >= 0).sum()),
                          "qty_matched": float(ln["qty"].to_numpy(dtype=float)[j >= 0].sum())}
        lday = (pd.to_datetime(ln["order_date"]) - pd.Timestamp(DAY0)).dt.days.to_numpy()
        lq = ln["qty"].to_numpy(dtype=float)
        m = j >= 0
        order = np.lexsort((lday[m], j[m]))
        self.l_deal, self.l_day, self.l_q = j[m][order], lday[m][order], lq[m][order]
        self.l_key = self.l_deal * 100000 + self.l_day
        self.l_cum = np.concatenate([[0.0], np.cumsum(self.l_q)])
        # per-deal constants that need only the deal's own days (and the 28 days before it)
        self._deal_metrics()
        # open days (deal_lib.load_open_days: s = series index, a = day index; rows with hours > 0 only)
        if open_days is None:
            self.open_days = None
        else:
            od = open_days[pd.to_numeric(open_days["hours"], errors="coerce") > 0]
            self.open_days = pd.DataFrame({
                "s": self.index_of(od["sku_id"], od["fc_id"]),
                "a": (pd.to_datetime(od["date"]) - pd.Timestamp(DAY0)).dt.days.to_numpy().astype(np.int64),
                "hours": od["hours"].to_numpy(dtype=float)})
        self._groups_cache: dict = {}

    def day_index(self, d) -> int:
        return (pd.Timestamp(d).date() - self.day0).days

    # ---------------------------------------------------------------- helpers
    def lines_between(self, deal_idx: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
        """qty of the lines of each deal on days lo .. hi-1 (half-open)."""
        a = np.searchsorted(self.l_key, deal_idx * 100000 + np.maximum(lo, -1), side="left")
        b = np.searchsorted(self.l_key, deal_idx * 100000 + np.maximum(hi, -1), side="left")
        return self.l_cum[b] - self.l_cum[a]

    def _deal_metrics(self) -> None:
        d = self.deals
        s = np.where(d["s"].to_numpy() >= 0, d["s"].to_numpy(), 0)
        a = d["start_day"].to_numpy()
        b = np.minimum(d["end_day"].to_numpy(), self.A - 1)          # ongoing deals: up to the snapshot's last day
        valid = d["valid"].to_numpy() & (a >= 0) & (a < self.A)
        aa, bb = np.clip(a, 0, self.A), np.clip(b + 1, 0, self.A)
        sales = np.where(valid & (bb > aa), self.cum[s, bb] - self.cum[s, aa], np.nan)
        base_ok = valid & (a - 28 >= 0)
        base = np.where(base_ok, (self.cum[s, np.clip(a, 0, self.A)] - self.cum[s, np.clip(a - 28, 0, self.A)]) / 28.0, np.nan)
        ndays = np.where(valid, np.maximum(bb - aa, 0), np.nan)
        with np.errstate(all="ignore"):
            uplift = np.where(base > 0, sales / (base * ndays), np.nan)
        used_lines = np.where(valid, self.lines_between(np.arange(len(d)), aa, bb), np.nan)
        d["sales_in_deal"], d["base28"], d["days_counted"], d["uplift"] = sales, base, ndays, uplift
        d["used_lines_in_window"] = used_lines
        d["used_lines_all"] = self.lines_between(np.arange(len(d)), np.full(len(d), 0), np.full(len(d), self.A + 1))
        with np.errstate(all="ignore"):
            d["usage_table"] = np.where(d["maxq"] > 0, d["usedq"] / d["maxq"], np.nan)
        d["ongoing"] = d["end_day"] >= self.A

    # ---------------------------------------------------------------- groups A/B/C (B7) at the 1st of D's month
    def groups_at(self, D: date) -> np.ndarray:
        """B7 groups computed for the first day of D's month (window: the 90 days before it): one code per series
        (0 A, 1 B, 2 C, -1 none: no open day in the window or no open-hours data)."""
        m0 = pd.Timestamp(D).date().replace(day=1)
        if m0 in self._groups_cache:
            return self._groups_cache[m0]
        we = self.day_index(m0) - 1
        ws = we - G_WINDOW + 1
        out = np.full(len(self.keys), -1, dtype=np.int8)
        od = self.open_days
        if od is not None and we >= 0:
            x = od[(od["a"] >= max(ws, 0)) & (od["a"] <= we) & (od["s"] >= 0)]
            if len(x):
                s, a = x["s"].to_numpy(), x["a"].to_numpy()
                dem = self.dem[s, a]
                n = np.bincount(s, minlength=len(self.keys))
                q = np.bincount(s, weights=dem, minlength=len(self.keys))
                z = np.bincount(s, weights=(dem == 0).astype(float), minlength=len(self.keys))
                has = n > 0
                with np.errstate(all="ignore"):
                    g = classify_groups(n, np.where(has, q / np.maximum(n, 1), 0), np.where(has, z / np.maximum(n, 1), 0))
                out = np.where(has, g, -1).astype(np.int8)
        self._groups_cache[m0] = out
        return out

    # ---------------------------------------------------------------- features of origin D
    def ly_features(self, rows: np.ndarray, D: date) -> np.ndarray:
        """E1: len(rows) x 4 from days < D only (D-364 .. D-419); rows -1 = series without any line (0, trend 1);
        a window starting before DAY0 = NaN."""
        d = self.day_index(D)
        has = rows >= 0
        r = np.where(has, rows, 0)
        c = self.cum

        def mean(lo, hi):        # days lo .. hi inclusive
            assert hi < d
            if lo < 0:
                return np.full(len(rows), np.nan)
            return (c[r, hi + 1] - c[r, lo]) / (hi - lo + 1)
        out = np.zeros((len(rows), 4))
        out[:, 0] = mean(d - 364, d - 364)
        out[:, 1] = mean(d - 367, d - 361)
        out[:, 2] = mean(d - 391, d - 364)
        prev = mean(d - 419, d - 392)
        with np.errstate(all="ignore"):
            out[:, 3] = np.where(np.isnan(prev), np.nan, np.where(prev > 0, out[:, 2] / np.where(prev > 0, prev, 1), 1.0))
        out[~has] = np.array([0.0, 0.0, 0.0, 1.0])
        if d - 419 < 0:
            out[~has, 3] = np.nan
        return out.astype(np.float32)

    def deal_features(self, rows: np.ndarray, D: date) -> np.ndarray:
        """E2 deal block: len(rows) x 12 of the deals visible at D 00:00 (ready <= D) and the lines of the days < D."""
        dd = self.deals
        d = self.day_index(D)
        S = len(self.keys)
        valid = dd["valid"].to_numpy()
        rx, ex = dd["ready_x"].to_numpy(), dd["end_x"].to_numpy()
        s = dd["s"].to_numpy()
        act = valid & (rx <= d) & (ex >= d)
        fin = valid & (ex < d)
        ia = np.flatnonzero(act)
        sa = s[ia]
        n_act = np.bincount(sa, minlength=S).astype(float)
        since = np.full(S, np.inf)
        np.minimum.at(since, sa, d - dd["start_day"].to_numpy()[ia])
        to_end = np.full(S, -np.inf)
        np.maximum.at(to_end, sa, dd["end_day"].to_numpy()[ia] - d)
        maxq = np.bincount(sa, weights=np.nan_to_num(dd["maxq"].to_numpy()[ia]), minlength=S)
        used = np.bincount(sa, weights=self.lines_between(ia, np.zeros(len(ia), np.int64), np.full(len(ia), d)), minlength=S)
        u1 = np.bincount(sa, weights=self.lines_between(ia, np.full(len(ia), d - 1), np.full(len(ia), d)), minlength=S)
        u7 = np.bincount(sa, weights=self.lines_between(ia, np.full(len(ia), d - 7), np.full(len(ia), d)), minlength=S)
        # history of the finished deals (end < D 00:00): their days and the 28 days before them are all < D
        jf = np.flatnonzero(fin)
        upl, usg = dd["uplift"].to_numpy()[jf], dd["usage_table"].to_numpy()[jf]
        sf = s[jf]
        okU, okG = ~np.isnan(upl), ~np.isnan(usg)
        nU = np.bincount(sf[okU], minlength=S)
        sU = np.bincount(sf[okU], weights=upl[okU], minlength=S)
        nG = np.bincount(sf[okG], minlength=S)
        sG = np.bincount(sf[okG], weights=usg[okG], minlength=S)
        grp = self.groups_at(D)
        gf = grp[sf[okU]]
        gU = np.array([upl[okU][gf == g].mean() if np.any(gf == g) else np.nan for g in range(3)])
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
            f[:, 9] = np.where(nU > 0, sU / np.maximum(nU, 1), np.nan)
            f[:, 10] = np.where(nG > 0, sG / np.maximum(nG, 1), np.nan)
            f[:, 11] = np.where((nU == 0) & (grp >= 0), gU[np.clip(grp, 0, 2)], np.nan)
        has = rows >= 0
        out = np.full((len(rows), len(DEAL_NAMES)), np.nan)
        out[has] = f[rows[has]]
        out[~has] = np.array([0, np.nan, np.nan, np.nan, 0, np.nan, 0, 0, 0, np.nan, np.nan, np.nan])
        return out.astype(np.float32)

    def active_on(self, rows: np.ndarray, D: date) -> np.ndarray:
        """Output column deal_active of a target day D (ex post, for the scoring only, never a model input): a valid
        deal of the series covers D (start day <= D <= end day)."""
        dd = self.deals
        d = self.day_index(D)
        act = dd["valid"].to_numpy() & (dd["start_day"].to_numpy() <= d) & (dd["end_day"].to_numpy() >= d)
        on = np.zeros(len(self.keys), dtype=np.int8)
        on[dd["s"].to_numpy()[act]] = 1
        out = np.zeros(len(rows), dtype=np.int8)
        out[rows >= 0] = on[rows[rows >= 0]]
        return out

    def index_of(self, sku, fc) -> np.ndarray:
        """Series index of each (sku, fc) pair (-1 = not a series of this snapshot)."""
        s = pd.Series(sku, copy=False).astype(str).to_numpy()
        f = pd.Series(fc, copy=False).astype(str).to_numpy()
        return self._kix.get_indexer(pd.Index(s + "\x1f" + f)).astype(np.int64)

    def rows_of(self, keys) -> np.ndarray:
        return np.array([self.kidx.get(tuple(k), -1) for k in keys], dtype=np.int64)


# ====================================================================== application-only rule (not in deal_lib)
def dedupe_like_app(deals: pd.DataFrame) -> pd.DataFrame:
    """The deal rows the application uses: per (deal_code, sku_code, fc_code) the row with the latest end_time, then
    the last row in input order (stable sort keeps input order among equal end_time)."""
    d = deals.reset_index(drop=True).copy()
    d["_end"] = pd.to_datetime(d["end_time"])
    d["_pos"] = np.arange(len(d))
    d = d.sort_values(["_end", "_pos"], kind="mergesort")
    d = d.drop_duplicates(["deal_code", "sku_code", "fc_code"], keep="last").sort_values("_pos")
    return d.drop(columns=["_end", "_pos"]).reset_index(drop=True)


# ====================================================================== PART 2: synthetic fixtures
DEMAND_COLS = ["sku_id", "fc_id", "order_date", "qty"]
LINE_COLS = ["sku_id", "fc_id", "order_date", "deal_code", "qty"]
DEAL_COLS = ["deal_code", "sku_code", "fc_code", "ready_time", "end_time", "max_quantity", "quantity_used"]
OPEN_COLS = ["sku_id", "fc_id", "date", "hours"]

HAND_DAY0, HAND_LAST, HAND_D = date(2025, 1, 1), date(2026, 3, 31), date(2026, 3, 10)
NAN = float("nan")
SA, SB, SC, SE, SG, SH, SJ = ("SA", "F1"), ("SB", "F1"), ("SC", "F1"), ("SE", "F1"), ("SG", "F1"), ("SH", "F1"), ("SJ", "F1")
SK, SL, SM, SN, SP, SQ, SR = ("SK", "F1"), ("SL", "F1"), ("SM", "F1"), ("SN", "F1"), ("SP", "F1"), ("SQ", "F1"), ("SR", "F1")
ST, SU = ("ST", "F1"), ("SU", "F1")
# panel order of the hand case (not sorted on purpose: rows come back in the order of keys)
HAND_KEYS = [SR, SA, SQ, SB, SC, SE, SG, SH, SJ, SK, SL, SM, SN, SP, ST, SU]


def _days(first: date, n: int) -> list[date]:
    return [first + timedelta(days=i) for i in range(n)]


def hand_case() -> dict:
    """Tiny fixture, day0 2025-01-01, last day 2026-03-31, origin D = 2026-03-10 (00:00 Vietnam time).
    Returns dict(day0, last_day, D, keys, demand, deals, deal_lines, open_days)."""
    D = HAND_D

    def back(n):
        return D - timedelta(days=n)
    dem = []
    # SA, same period last year: D-367 7, D-364 14, D-363 7, D-361 7 | D-391 21 | D-392 56, D-419 28 | outside: D-360,
    # D-420 1000 each; 2025-01-01 3 (day index 0); 2024-12-31 99 and 2026-04-02 77 are outside [day0, last_day]
    for n, q in ((367, 7), (364, 14), (363, 7), (361, 7), (360, 1000), (391, 21), (392, 56), (419, 28), (420, 1000)):
        dem.append((*SA, back(n), q))
    dem += [(*SA, date(2025, 1, 1), 3), (*SA, date(2024, 12, 31), 99), (*SA, date(2026, 4, 2), 77)]
    # SA, deal history: base of D4 (28 days before 2026-02-01) = 56 / 28 = 2; sales of D4 (02-01..02-10) = 30 + 10 = 40;
    # base of D5 (01-23..02-19) = 40 / 28; sales of D5 (02-20..02-21) = 20; D-1 500 (never read by a deal feature of D)
    dem += [(*SA, date(2026, 1, 10), 56), (*SA, date(2026, 2, 3), 30), (*SA, date(2026, 2, 7), 10),
            (*SA, date(2026, 2, 20), 20), (*SA, date(2026, 3, 9), 500)]
    dem += [(*SB, back(380), 28), (*SC, back(400), 28)]
    dem += [(*SE, date(2026, 3, 5), 25), (*SE, date(2026, 3, 9), 5)]
    dem += [(*SG, date(2026, 2, 2), 4)]
    dem += [(*SH, date(2025, 12, 20), 1), (*SH, date(2025, 12, 21), 1), (*SH, date(2026, 1, 10), 3)]
    dem += [(*SK, d, 30) for d in _days(date(2026, 2, 1), 14)]
    dem += [(*SL, date(2025, 11, 5), 5)]
    dem += [(*SM, date(2025, 12, 2), 0)]                         # a stored zero-demand row
    dem += [(*SN, date(2026, 2, 15), 5)]
    dem += [(*SR, date(2026, 2, 10), 14), (*SR, date(2026, 3, 5), 18)]
    dem += [(*ST, d, 30) for d in _days(date(2025, 12, 1), 14)] + [(*SU, d, 30) for d in _days(date(2026, 2, 16), 14)]
    demand = pd.DataFrame([(s, f, d.isoformat(), float(q)) for s, f, d, q in dem], columns=DEMAND_COLS)

    deals = pd.DataFrame([
        ("D1", *SA, "2026-03-01 08:00:00", "2026-03-20 23:59:59", 100, 999),   # active; used = current value
        ("D2", *SA, "2026-03-05 00:00:00", "2026-03-12 10:00:00", 50, 10),     # active
        ("D3", *SA, "2026-03-10 09:00:00", "2026-03-15 00:00:00", 1000, 0),    # ready after D 00:00: not visible
        ("D4", *SA, "2026-02-01 00:00:00", "2026-02-10 23:00:00", 40, 30),     # finished: uplift 2, usage 0.75
        ("D5", *SA, "2026-02-20 00:00:00", "2026-02-21 12:00:00", NAN, 5),     # finished: uplift 7, usage NaN
        ("E1", *SE, "2026-03-01 00:00:00", "2026-03-31 23:59:59", 10, 3),
        ("E2", *SE, "2026-03-02 00:00:00", "2026-03-15 00:00:00", NAN, 1),
        ("H1", *SH, "2026-01-10 00:00:00", "2026-01-11 23:00:00", 6, 3),       # finished: uplift 21, usage 0.5
        ("J1", *SJ, "2026-03-09 20:00:00", "2026-03-25 18:00:00", NAN, 0),     # VN 20:00 of D-1: visible (+7 h is not)
        ("N1", *SN, "2026-02-15 00:00:00", "2026-02-16 23:00:00", 10, 5),      # finished, base 0: no uplift; usage 0.5
        ("P1", *SP, "2026-03-05 00:00:00", "2026-03-01 00:00:00", 30, 4),      # ready > end: invalid, never used
        ("Q1", *SQ, "2026-03-10 09:00:00", "2026-03-12 08:00:00", 5, 0),       # starts on D after 00:00
        ("R0", *SR, "2026-03-01 00:00:00", "2026-03-09 23:59:59", 20, 18),     # finished 1 s before D: uplift 4, usage 0.9
        ("R1", *SR, "2026-03-08 00:00:00", "2026-03-10 00:00:00", 8, 2),       # ends exactly at D 00:00: active
    ], columns=DEAL_COLS)

    lines = [(*SA, "2026-03-02", "D1", 5), (*SA, "2026-03-08", "D1", 3), (*SA, "2026-03-09", "D1", 4),
             (*SA, "2026-03-10", "D1", 100),                      # day D: never read for D
             (*SA, "2026-03-05", "D2", 2), (*SA, "2026-03-09", "D2", 6),
             (*SA, "2026-03-09", "DX", 50),                       # code not in the deal table
             (*SA, "2026-03-09", "D3", 9),                        # deal not started at D 00:00
             (*SA, "2026-02-03", "D4", 30),                       # finished deal: not in used_*
             ("SA", "F2", "2026-03-09", "D1", 70),                # D1 exists for (SA, F1) only
             (*SE, "2026-03-05", "E1", 25), (*SE, "2026-03-09", "E2", 5),
             (*SP, "2026-03-08", "P1", 4),
             (*SR, "2026-03-05", "R0", 18), (*SR, "2026-03-09", "R1", 2)]
    deal_lines = pd.DataFrame([(s, f, d, c, float(q)) for s, f, d, c, q in lines], columns=LINE_COLS)

    od = []                                                       # B7 window of March: 2025-12-01 .. 2026-02-28
    od += [(*SA, d, 8.0) for d in (date(2026, 1, 10), date(2026, 2, 3), date(2026, 2, 7), date(2026, 2, 20))]  # 4 -> B
    od += [(*SG, d, 8.0) for d in _days(date(2026, 2, 2), 5)] + [(*SG, d, 0.0) for d in _days(date(2026, 2, 7), 3)]  # B
    od += [(*SH, d, 8.0) for d in _days(date(2025, 12, 5), 20)]   # 20 open, demand 2 -> avg 0.1, zero 0.9 -> C
    od += [(*SJ, d, 8.0) for d in _days(date(2026, 1, 5), 14)]    # 14 open, no demand -> C
    od += [(*SK, d, 12.0) for d in _days(date(2026, 2, 1), 14)]   # 14 open, 30 a day -> A
    od += [(*SL, d, 8.0) for d in _days(date(2025, 11, 1), 20)]   # before the window -> no group
    od += [(*SM, d, 0.0 if d == date(2025, 12, 7) else 8.0) for d in _days(date(2025, 12, 1), 14)]  # 13 open -> B
    od += [(*SN, d, 8.0) for d in _days(date(2026, 1, 20), 3)]    # 3 open -> B
    # window edges: ST 2025-12-01..12-14 (14 open, 30 a day: A only if the window starts on 12-01 - and A at the 1st
    # of March, B for a window ending at D-1); SU 2026-02-16..03-01 (13 open in the window: B; 14 with 03-01: A)
    od += [(*ST, d, 8.0) for d in _days(date(2025, 12, 1), 14)] + [(*SU, d, 8.0) for d in _days(date(2026, 2, 16), 14)]
    od += [("SZZ", "F1", d, 8.0) for d in _days(date(2026, 1, 1), 20)]   # not a series of the scope
    open_days = pd.DataFrame([(s, f, d.isoformat(), h) for s, f, d, h in od], columns=OPEN_COLS)
    return {"day0": HAND_DAY0, "last_day": HAND_LAST, "D": D, "keys": list(HAND_KEYS), "demand": demand,
            "deals": deals, "deal_lines": deal_lines, "open_days": open_days}


# same period last year at D = 2026-03-10 (ly_same_day, ly_mean_7, ly_mean_28, ly_trend)
_LY_ZERO = [0.0, 0.0, 0.0, 1.0]                                   # no demand in any window: trend 1 (earlier mean 0)
HAND_LY = {
    SA: [14.0, 35 / 7, 42 / 28, (42 / 28) / (84 / 28)],          # 14 | 7+14+7+7 | 21+7+14 | / (28+56): 0.5
    SB: [0.0, 0.0, 28 / 28, 1.0],                                 # earlier 28-day mean 0 -> trend 1
    SC: [0.0, 0.0, 0.0, 0.0],                                     # 0 / (28 / 28)
}
# deal block at D = 2026-03-10, columns of DEAL_NAMES:
# active, since, to_end, max_qty, used_to_date, remaining_ratio, used_1, used_7, n_active, sku_uplift, sku_usage, grp
_DEAL_NONE = [0.0, NAN, NAN, NAN, 0.0, NAN, 0.0, 0.0, 0.0, NAN, NAN, NAN]
_GRP_B = (2.0 + 7.0) / 2                                          # finished deals with an uplift in group B: SA D4, D5
_GRP_C = 21.0                                                     # group C: SH H1
HAND_DEAL = {
    # D1 (start 03-01, end 03-20) + D2 (start 03-05, end 03-12): since min(9, 5), to_end max(10, 2), max 100 + 50,
    # used (5+3+4) + (2+6), ratio 1 - 20/150, used_1 4 + 6, used_7 (3+4) + (2+6), uplift mean(2, 7), usage 0.75 (D5 NaN)
    SA: [1.0, 5.0, 10.0, 150.0, 20.0, 1 - 20 / 150, 10.0, 15.0, 2.0, 4.5, 0.75, NAN],
    # E1 (03-01..03-31, max 10) + E2 (03-02..03-15, max NaN -> 0): ratio 1 - 30/10 not clipped
    SE: [1.0, 8.0, 21.0, 10.0, 30.0, -2.0, 5.0, 30.0, 2.0, NAN, NAN, NAN],
    SG: _DEAL_NONE[:11] + [_GRP_B],
    SH: [0.0, NAN, NAN, NAN, 0.0, NAN, 0.0, 0.0, 0.0, 21.0, 0.5, NAN],
    # J1 ready 2026-03-09 20:00 (day D-1), end day 03-25, max NaN -> 0 and no ratio
    SJ: [1.0, 1.0, 15.0, 0.0, 0.0, NAN, 0.0, 0.0, 1.0, NAN, NAN, _GRP_C],
    SK: list(_DEAL_NONE),                                         # group A has no finished deal
    SL: list(_DEAL_NONE),                                         # no open day in the window: no group
    SM: _DEAL_NONE[:11] + [_GRP_B],                               # 13 open days (hours 0 is closed) -> B, not C
    SN: [0.0, NAN, NAN, NAN, 0.0, NAN, 0.0, 0.0, 0.0, NAN, 0.5, _GRP_B],
    SP: list(_DEAL_NONE),
    SQ: list(_DEAL_NONE),
    # R1 (03-08 .. 03-10 00:00): since 2, to_end 0, used 2, ratio 1 - 2/8; R0 finished: uplift 18 / (0.5 * 9), usage 18/20
    SR: [1.0, 2.0, 0.0, 8.0, 2.0, 0.75, 2.0, 2.0, 1.0, 4.0, 0.9, NAN],
    SB: list(_DEAL_NONE),
    SC: list(_DEAL_NONE),
    ST: list(_DEAL_NONE),                                         # A (no finished deal in A): no group value
    SU: _DEAL_NONE[:11] + [_GRP_B],                               # B
}
# active_on(target day): a valid deal covers the day (start day <= day <= end day)
HAND_ACTIVE = {
    date(2026, 3, 9): {SA, SE, SJ, SR},                           # Q1 starts on 03-10
    date(2026, 3, 10): {SA, SE, SJ, SQ, SR},                      # Q1 (09:00) counts for the day; R1 ends on it
    date(2026, 3, 13): {SA, SE, SJ},                              # Q1 ended 03-12, R1 03-10
    date(2026, 3, 3): {SA, SE, SR},                               # P1 (ready > end) never
}


def hand_ly(key) -> list[float]:
    return HAND_LY.get(key, _LY_ZERO)


def random_case(seed: int = 11) -> dict:
    """Random synthetic scope over 2025-01-01 .. 2026-03-31 (last day): 44 demand series of 4 kinds (fast / slow /
    medium / new in 2026; B7 groups A, B, C and none) with gaps and stored zeros, rows before day0 and after the last day, 4 deal-only series,
    0-7 deals per series from 2025-10 (overlapping, ready > end, NaN / 0 max, NaN used, codes shared by two series), deal lines
    (incl. unknown codes, a wrong FC, days outside the deal) and open days (hours 0 and > 0, an unknown series).
    Deal (deal_code, sku_code, fc_code) keys are unique (deal_lib cannot take duplicates)."""
    rng = np.random.default_rng(seed)
    day0, last = date(2025, 1, 1), date(2026, 3, 31)
    n_days = (last - day0).days + 1
    dem = []
    kinds = {}
    for i in range(44):
        key = (f"S{i:02d}", "F1" if i % 3 else "F2")
        kind = ("fast", "slow", "medium", "new")[i % 4]
        kinds[key] = kind
        first = 400 if kind == "new" else int(rng.integers(0, 60))
        p_present, lam = {"fast": (0.95, 30.0), "slow": (0.3, 0.6), "medium": (0.7, 10.0), "new": (0.8, 4.0)}[kind]
        for a in range(first, n_days):
            if rng.random() < p_present:
                dem.append((*key, day0 + timedelta(days=a), float(rng.poisson(lam))))   # Poisson: stored zeros too
        if i % 7 == 0:
            dem.append((*key, day0 - timedelta(days=int(rng.integers(1, 30))), 500.0))     # before day0
            dem.append((*key, last + timedelta(days=int(rng.integers(1, 5))), 500.0))      # after the last day
    demand = pd.DataFrame([(s, f, d.isoformat(), q) for s, f, d, q in dem], columns=DEMAND_COLS)
    series = list(kinds) + [(f"X{i}", "F1") for i in range(4)]                        # 4 deal-only series
    deals, lines = [], []
    n = 0
    t_lo = pd.Timestamp("2025-10-01")
    for key in series:
        for _ in range(0 if rng.random() < 0.25 else int(rng.integers(1, 8))):
            n += 1
            ready = t_lo + pd.Timedelta(seconds=int(rng.integers(0, 186 * 86400)))
            end = ready + pd.Timedelta(days=int(rng.integers(0, 40)), seconds=int(rng.integers(0, 86400)))
            if rng.random() < 0.08:
                ready, end = end + pd.Timedelta(hours=1), ready                         # ready > end
            mx = [NAN, 0.0][int(rng.integers(0, 2))] if rng.random() < 0.15 else float(rng.integers(5, 120))
            used = NAN if rng.random() < 0.05 else float(rng.integers(0, 250))
            code = f"K{n:04d}"
            deals.append((code, *key, ready.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"), mx, used))
            if rng.random() < 0.1:                                                     # same code, another series
                other = series[int(rng.integers(0, len(series)))]
                if other != key:
                    deals.append((code, *other, ready.strftime("%Y-%m-%d %H:%M:%S"),
                                  end.strftime("%Y-%m-%d %H:%M:%S"), mx, used))
            lo, hi = min(ready, end).normalize() - pd.Timedelta(days=3), max(ready, end).normalize() + pd.Timedelta(days=3)
            for _ in range(int(rng.integers(0, 3 + (hi - lo).days // 2))):
                day = lo + pd.Timedelta(days=int(rng.integers(0, (hi - lo).days + 1)))
                lines.append((*key, day.date().isoformat(), code, float(rng.integers(1, 20))))
            if rng.random() < 0.15:
                lines.append((key[0], "F9", ready.date().isoformat(), code, 7.0))      # wrong FC: unmatched
            if rng.random() < 0.15:
                lines.append((*key, ready.date().isoformat(), f"NOPE{n}", 9.0))       # unknown code
    # fixed deals around 2026-03-17 (an origin of the tests)
    fixed = [("FX1", "S01", "F1", "2026-03-10 00:00:00", "2026-03-17 00:00:00", 30.0, 5.0),   # ends at D 00:00
             ("FX2", "S01", "F1", "2026-03-17 00:00:00", "2026-03-20 00:00:00", 40.0, 5.0),   # ready at D 00:00
             ("FX3", "S02", "F1", "2026-03-17 00:00:01", "2026-03-20 00:00:00", 50.0, 5.0),   # ready 1 s after
             ("FX4", "S02", "F1", "2026-03-01 00:00:00", "2026-03-16 23:59:59", 60.0, 5.0)]   # ends 1 s before
    deals += fixed
    for code, s, f, *_ in fixed:
        lines += [(s, f, "2026-03-16", code, 3.0), (s, f, "2026-03-12", code, 2.0), (s, f, "2026-03-17", code, 4.0)]
    deals_df = pd.DataFrame(deals, columns=DEAL_COLS)
    lines_df = (pd.DataFrame(lines, columns=LINE_COLS).groupby(["sku_id", "fc_id", "order_date", "deal_code"],
                                                                as_index=False)["qty"].sum()[LINE_COLS])
    od = []
    for key, kind in kinds.items():
        if kind == "new" or rng.random() < 0.15:
            continue                                                                    # no open-hours data
        for a in range((date(2025, 9, 1) - day0).days, n_days):
            if rng.random() < 0.7:
                od.append((*key, (day0 + timedelta(days=a)).isoformat(), float(rng.choice([0.0, 4.0, 8.0, 24.0]))))
    od += [("ZZ", "F1", (date(2026, 1, 1) + timedelta(days=i)).isoformat(), 8.0) for i in range(30)]
    open_days = pd.DataFrame(od, columns=OPEN_COLS)
    in_range = demand[(demand["order_date"] >= day0.isoformat()) & (demand["order_date"] <= last.isoformat())]
    universe = sorted(set(zip(in_range["sku_id"], in_range["fc_id"])) | set(zip(deals_df["sku_code"], deals_df["fc_code"])))
    return {"day0": day0, "last_day": last, "demand": demand, "deals": deals_df, "deal_lines": lines_df,
            "open_days": open_days, "universe": universe}


def ref_snapshot(case: dict, deals: pd.DataFrame | None = None, demand: pd.DataFrame | None = None,
                 deal_lines: pd.DataFrame | None = None, open_days="case") -> Snapshot:
    """The reference snapshot of a case (keys = the universe, as in deal_lib); arguments replace the case's frames."""
    return Snapshot(case["demand"] if demand is None else demand, case["deals"] if deals is None else deals,
                    case["deal_lines"] if deal_lines is None else deal_lines,
                    case["open_days"] if isinstance(open_days, str) else open_days, case["day0"], case["last_day"])
