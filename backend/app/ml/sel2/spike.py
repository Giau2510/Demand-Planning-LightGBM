"""1.4.8 spike cleaning, part 1 (owner 07-08/11/2026): spike flags per SO LINE (logic v3 + E4) and the spike EXCESS of a
SKU x FC x day as of a day D. Production port of the research code, same algorithm and same results
(backend/tests/test_v148_spike.py compares them): flag_lines = reports/don-dot-bien/code/flags.py flag_lines(logic="v3")
(the v1 / v2 paths and the report-only columns left out); Excess / clean_daily / clean_frame =
reports/backtest-ngay1-7-20261107/code/bt17.py. Pure numpy / pandas; the helpers at the end read / write the tables of
migration 0013 on a connection of the caller. The nightly SPIKE_LINES step (spike_lines.py) fills the cache and the
flag tables with it whatever the switch; SEL2 uses the excess only when sel2_pipeline.spike_cleaning is True (OFF by
default: the forecast path never calls this module and the numbers are those of 1.4.7).

One line = order day x so_code x customer x SKU x FC with quantity > 0 (so_lines_cache: the source rows of one line
summed). Same customer_id = same customer; a line without customer_id is its own unknown customer (no history -> new
customer). A "pair" = customer x SKU x FC, a "series" = SKU x FC, H = history_days (180). Unless stated, only data
BEFORE the order day is used (window [d-H, d-1]); lines of the same day are never history of each other.

Signals (each also needs qty >= the minimum quantity: 5, group C: 3; group = sku_group of the line's day, else the
oldest computed group, else not C):
  T1  n_prev >= 3 earlier lines of the pair in the window AND qty >= 3 x cust_med (median qty per line of those lines)
  T2  qty >= 10 x ser_line_med (median qty per line of ALL customers of the series in the window, >= 3 lines known)
  T4  day of the series with >= 10 lines: the line's rank by quantity (desc, ties by so_code, customer) <= max(1,
      floor(5 % x lines)) AND qty >= 3 x median qty of that day's lines
  T7  n_prev >= 3 AND >= 2 gaps known (gap = purchase day - previous purchase day of the pair, gaps of the purchase days
      in the window) AND the gap to the pair's NEXT purchase day >= 2 x median gap (uses data after the order, only up
      to data_end; no next purchase: T7 = 1 when data_end - d >= 2 x median gap)
n_signals_raw (v3): a regular customer (n_prev >= 3) counts only with T1 (then T1 + T2 + T4 + T7: T7 never alone), a new
customer T2 + T4. Frequent wholesale customer (n_prev >= 3 and >= 30 % of its earlier lines in the window are big lines
T1 / T2): only T1 counts (n_signals).
Exceptions (lines with n_signals_raw >= 1; all their demand kept):
  chu ky   the pair has >= 3 big lines (T1 or T2) with day in [d-H, d] (the line itself counts when big) AND (CV of the
           gaps between their distinct days <= 0.5 with >= 2 gaps, OR >= 50 % of them on one weekday, OR >= 50 % in one
           day-of-month bucket 1-5/6-10/11-15/16-20/21-25/26-31)
  nhu cau tang that   that day the series has lines >= 2 x med_lines (median daily line count over its open days in the
           window, >= 14 open days known) AND >= 3 distinct customers with a big line that day
  E4       the series has lines with n_signals_raw >= 1 on >= N distinct days of the e4_window (30) days before the
           as-of day -> no line of it is cleaned (N = sel2_pipeline.spike_e4_n)
Open day of a series: open hours > 0, or the series sold that day, or the series has no open-hours row at all (every
calendar day open), or the day is after the last day of the open-hours table.
Handling: kept = cust_med (n_prev >= 3) else ser_line_med else qty; excess = max(qty - kept, 0) removed at level k
(1, 2, 3) when n_signals >= k and no exception.

As of D (Excess): ONE flag_lines run on all the lines, the flagged lines (n_signals_raw >= 1) kept; the excess as of D
reads the lines of days < D only, T7 recomputed with the next purchase seen before D (else judged on D-1), E4 counted
on D-30 .. D-1; equal to a direct flag_lines(..., asof=D, data_end=D-1, e4_days=N) (test). Every other value of a line
of day t uses data <= t only."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ...timeutil import now_iso

LOGIC = "v3"
HISTORY_DAYS = 180
E4_WINDOW = 30
LEVELS = (1, 2, 3)
DAY0 = date(2025, 1, 1)         # day 0 of the SEL2 arrays (= data.DAY0)
SHIFT = 1 << 13                 # day index < 8192 (22 years)
SIGNALS = ("T1", "T2", "T4", "T7")
FLAGS = ("exc_wholesale", "exc_periodic", "exc_demand", "is_regular")
# the columns of spike_flag_lines kept per flagged line (everything Excess reads, + T2 / T4 / cust_med for the reports)
FLAG_COLS = ("d", "fc_code", "sku_code", "so_code", "customer_id", "qty", "group_code", "min_qty", "n_prev", "cust_med",
             "gap_med", "n_gaps", "next_day", "kept") + SIGNALS + ("n_signals_raw",) + FLAGS


def g_of(d) -> int:
    return (pd.Timestamp(d).date() - DAY0).days


def _g(values) -> np.ndarray:
    """day index (from DAY0) of dates / Timestamps; NaT -> -1."""
    t = pd.to_datetime(pd.Series(values)).to_numpy().astype("datetime64[D]")
    nat = np.isnat(t)
    out = np.where(nat, np.datetime64(DAY0, "D"), t) - np.datetime64(DAY0, "D")
    return np.where(nat, -1, out.astype(np.int64))


# ------------------------------------------------------------------ helpers
def window_median(code: np.ndarray, val: np.ndarray, qlo: np.ndarray, qhi: np.ndarray, budget: int = 6_000_000):
    """For every query i: median and count of val[j] over rows with qlo[i] <= code[j] < qhi[i] (code sorted ascending).
    Exact; windows expanded in chunks of ~budget values."""
    lo = np.searchsorted(code, qlo, "left")
    hi = np.searchsorted(code, qhi, "left")
    n = np.maximum(hi - lo, 0)
    out = np.full(len(lo), np.nan)
    i0 = 0
    while i0 < len(lo):
        cs = np.cumsum(n[i0:])
        i1 = i0 + max(1, int(np.searchsorted(cs, budget, "right")))
        i1 = min(i1, len(lo))
        nn = n[i0:i1]
        tot = int(nn.sum())
        if tot:
            st = np.cumsum(nn) - nn
            q = np.repeat(np.arange(i1 - i0), nn)
            j = np.repeat(lo[i0:i1], nn) + (np.arange(tot) - np.repeat(st, nn))
            v = val[j]
            o = np.lexsort((v, q))
            v = v[o]
            ok = nn > 0
            a = v[(st + (nn - 1) // 2)[ok]]
            b = v[(st + nn // 2)[ok]]
            seg = out[i0:i1]
            seg[ok] = (a + b) / 2
            out[i0:i1] = seg
        i0 = i1
    return out, n


def _lookup(code_tab: np.ndarray, val_tab: np.ndarray, code_q: np.ndarray, fill=np.nan) -> np.ndarray:
    """val_tab at the exact code (code_tab sorted unique); fill when absent."""
    ix = np.searchsorted(code_tab, code_q)
    ixc = np.minimum(ix, max(len(code_tab) - 1, 0))
    hit = (ix < len(code_tab)) & (code_tab[ixc] == code_q) if len(code_tab) else np.zeros(len(code_q), bool)
    out = np.full(len(code_q), fill, dtype=float)
    if len(code_tab):
        out[hit] = val_tab[ixc[hit]]
    return out


OUT_COLS = ("d", "fc_code", "sku_code", "so_code", "customer_id", "qty", "group_code", "min_qty", "n_prev", "cust_med",
            "gap_med", "n_gaps", "next_day", "med_lines", "day_lines", "day_qty", "day_med", "day_rank", "ser_line_med",
            "n_ser_lines", "big_prev", "big_share") + SIGNALS + (
            "n_signals_raw", "exc_wholesale", "n_signals", "is_regular", "e4_big_days", "exc_e4", "exc_periodic",
            "exc_demand", "kept", "n_big_cust_day", "excess_L1", "excess_L2", "excess_L3")


# ------------------------------------------------------------------ flags of the lines (flags.flag_lines, logic v3)
def flag_lines(lines_df: pd.DataFrame, open_days_df: pd.DataFrame, groups_df: pd.DataFrame, start, end,
               history_days: int = HISTORY_DAYS, *, data_end=None, e4_days: int | None = None,
               e4_window: int = E4_WINDOW, asof=None, day0=None, min_qty: float = 5, min_qty_c: float = 3,
               t1_mult: float = 3, t2_k: float = 10, t4_share: float = 0.05, t4_mult: float = 3, t4_min_lines: int = 10,
               t7_mult: float = 2, min_prev: int = 3, min_open_days: int = 14, per_cv: float = 0.5,
               per_share: float = 0.5, per_min_big: int = 3, exc_lines_mult: float = 2, exc_min_cust: int = 3,
               min_ser_lines: int = 3, ws_share: float = 0.3) -> pd.DataFrame:
    """lines_df: d (date), so_code, customer_id (str, NaN / '' = unknown), sku_code, fc_code, qty. open_days_df: fc_code,
    sku_code, open_date, hours. groups_df: fc_code, sku_code, group_code (A/B/C), computed_for. Returns one row per line
    with d in [start, end] (qty > 0) with every signal, exception, kept part and excess per level (OUT_COLS).
    asof: no line at or after it (data_end <= asof - 1), E4 counted on the e4_window days before it (e4_days None = no
    E4). day0: day 0 of the day statistics (the first day of the line data; the open-day grid of a series without
    open-hours rows starts there): chunks of series must pass the same day0. Deterministic."""
    H = int(history_days)
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    L = lines_df.loc[lines_df["qty"] > 0, ["d", "so_code", "customer_id", "sku_code", "fc_code", "qty"]].copy()
    L["d"] = pd.to_datetime(L["d"])
    asof = pd.Timestamp(asof) if asof is not None else None     # learning / forecast date: no line at or after it
    if asof is not None:
        L = L[L["d"] < asof]
    if not len(L):
        return pd.DataFrame(columns=list(OUT_COLS))
    data_end = pd.Timestamp(data_end) if data_end is not None else L["d"].max()
    if asof is not None:
        data_end = min(data_end, asof - pd.Timedelta(days=1))
    L = L[L["d"] <= data_end]
    if not len(L):
        return pd.DataFrame(columns=list(OUT_COLS))
    D0 = L["d"].min() if day0 is None else min(pd.Timestamp(day0), L["d"].min())
    L["day"] = (L["d"] - D0).dt.days.astype(np.int32)
    s_day, e_day, de_day = int((start - D0).days), int((end - D0).days), int((data_end - D0).days)
    L["so_code"] = L["so_code"].astype("string").fillna("")
    cu = L["customer_id"].astype("string")
    unknown = cu.isna() | (cu.str.strip() == "")
    L["cust"] = cu.where(~unknown, "?" + L["so_code"] + "#" + L["day"].astype(str))   # own unknown customer per order
    L["cust_unknown"] = unknown.to_numpy()
    L["key"] = L.groupby(["sku_code", "fc_code"], sort=True).ngroup().astype(np.int64)
    L["pair"] = L.groupby(["cust", "key"], sort=True).ngroup().astype(np.int64)
    L = L.sort_values(["pair", "day", "so_code"], kind="stable").reset_index(drop=True)
    keys = L.drop_duplicates("key")[["key", "sku_code", "fc_code"]].sort_values("key").reset_index(drop=True)
    day = L["day"].to_numpy(np.int64)
    pair = L["pair"].to_numpy(np.int64)
    key = L["key"].to_numpy(np.int64)
    qty = L["qty"].to_numpy(float)
    N = len(L)
    hist = L["day"].to_numpy() <= e_day            # lines used as history / day statistics (after end: T7 only)

    # ---- pair (customer x series) statistics, window [d-H, d-1]
    pcode = pair * SHIFT + day
    qlo = pair * SHIFT + np.maximum(day - H, 0)
    cust_med, n_prev = window_median(pcode, qty, qlo, pcode)
    first = np.r_[True, (pair[1:] != pair[:-1]) | (day[1:] != day[:-1])]
    pd_pair, pd_day = pair[first], day[first]
    newp = np.r_[True, pd_pair[1:] != pd_pair[:-1]]
    gap = np.where(newp, np.nan, pd_day - np.r_[0, pd_day[:-1]])
    gm = ~newp
    gap_med, n_gaps = window_median((pd_pair * SHIFT + pd_day)[gm], gap[gm], qlo, pcode)
    lastp = np.r_[pd_pair[1:] != pd_pair[:-1], True]
    nxt = np.where(lastp, -1, np.r_[pd_day[1:], 0])
    next_day = _lookup(pd_pair * SHIFT + pd_day, nxt.astype(float), pcode)
    next_day = np.where(next_day < 0, np.nan, next_day)

    # ---- T7
    elig7 = (n_prev >= min_prev) & (n_gaps >= 2) & (gap_med > 0)
    need = t7_mult * np.nan_to_num(gap_med, nan=np.inf)
    has_next = np.isfinite(next_day)
    t7 = elig7 & np.where(has_next, (next_day - day) >= need, (de_day - day) >= need)

    # ---- day statistics of the series (lines of the same key x day)
    so_rank = pd.factorize(L["so_code"], sort=True)[0]
    o = np.lexsort((pair, so_rank, -qty, day, key))      # pair order = customer order inside one series
    kd = key * SHIFT + day
    kd_o = kd[o]
    grp_start = np.r_[True, kd_o[1:] != kd_o[:-1]]
    gid = np.cumsum(grp_start) - 1
    gsz = np.bincount(gid)
    rank_o = np.arange(N) - (np.flatnonzero(grp_start))[gid] + 1
    rank = np.empty(N, np.int64)
    rank[o] = rank_o
    day_lines = np.empty(N, np.int64)
    day_lines[o] = gsz[gid]
    day_qty_g = np.bincount(gid, weights=qty[o])
    day_qty = np.empty(N)
    day_qty[o] = day_qty_g[gid]
    # median of the day's lines: values sorted desc inside each group
    qo = qty[o]
    st = np.flatnonzero(grp_start)
    dmed_g = (qo[st + (gsz - 1) // 2] + qo[st + gsz // 2]) / 2
    day_med = np.empty(N)
    day_med[o] = dmed_g[gid]
    t4_top = np.maximum(1, np.floor(t4_share * day_lines + 1e-9)).astype(np.int64)
    t4v = (day_lines >= t4_min_lines) & (rank <= t4_top) & (qty >= t4_mult * day_med)

    # ---- group and minimum quantity
    G = groups_df.copy()
    G["computed_for"] = pd.to_datetime(G["computed_for"])
    G = G.merge(keys, on=["sku_code", "fc_code"], how="inner")
    gcode = np.full(N, "", dtype=object)
    if len(G):
        cf = sorted(G["computed_for"].unique())
        dts = L["d"].to_numpy()
        for i, c in enumerate(cf):          # latest computed_for <= d; days before the oldest -> the oldest
            m = (dts >= c) if i else np.ones(N, bool)
            g = G[G["computed_for"] == c].set_index("key")["group_code"]
            val = g.reindex(key).to_numpy()
            fill = m & pd.notna(val)
            gcode[fill] = val[fill]
    minq = np.where(gcode == "C", min_qty_c, min_qty)
    big_enough = qty >= minq

    # ---- open-day grid of the series: daily line count
    keyday = pd.DataFrame({"key": key[hist], "day": day[hist], "qty": qty[hist]})
    sales = keyday.groupby(["key", "day"], sort=True).agg(y=("qty", "sum"), nl=("qty", "size")).reset_index()
    od = open_days_df.merge(keys, on=["sku_code", "fc_code"], how="inner")
    od = od.assign(day=(pd.to_datetime(od["open_date"]) - D0).dt.days)
    oh_last = (pd.to_datetime(open_days_df["open_date"]).max() - D0).days if len(open_days_df) else -1
    od = od[(od["day"] >= 0) & (od["day"] <= e_day)]
    covered = np.zeros(len(keys), bool)
    covered[od["key"].unique()] = True
    parts = [od.loc[od["hours"] > 0, ["key", "day"]], sales[["key", "day"]]]
    unc = np.flatnonzero(~covered)
    if len(unc):
        parts.append(pd.DataFrame({"key": np.repeat(unc, e_day + 1), "day": np.tile(np.arange(e_day + 1), len(unc))}))
    if oh_last < e_day:
        ck = np.flatnonzero(covered)
        nd = e_day - max(oh_last, -1)
        parts.append(pd.DataFrame({"key": np.repeat(ck, nd), "day": np.tile(np.arange(max(oh_last + 1, 0), e_day + 1), len(ck))}))
    grid = pd.concat(parts, ignore_index=True).astype(np.int64).drop_duplicates().sort_values(["key", "day"])
    grid = grid.merge(sales, on=["key", "day"], how="left").fillna({"y": 0.0, "nl": 0})
    grid = grid.reset_index(drop=True)
    del parts, od
    gk = grid["key"].to_numpy(np.int64)
    gcode_kd = gk * SHIFT + grid["day"].to_numpy(np.int64)
    gidx = pd.DatetimeIndex(D0 + pd.to_timedelta(grid["day"].to_numpy(), unit="D"))

    def roll_median(v: np.ndarray) -> np.ndarray:
        s = pd.Series(v, index=gidx)
        r = s.groupby(gk, sort=False).rolling(f"{H}D", closed="left", min_periods=min_open_days).median()
        return r.to_numpy()          # groups in key order, rows in day order = grid order

    med_lines = _lookup(gcode_kd, roll_median(grid["nl"].to_numpy(float)), kd)

    # ---- series normal order size (median qty per line of ALL customers in [d-H, d-1]), per key x day
    lkey_sorted = np.lexsort((qty, day, key))
    sk_code = (key * SHIFT + day)[lkey_sorted]
    sk_qty = qty[lkey_sorted]

    def ser_line_med(rows: np.ndarray):
        out = np.full(len(rows), np.nan)
        cnt = np.zeros(len(rows))
        if not len(rows):
            return out, cnt
        q = pd.DataFrame({"k": key[rows], "d": day[rows]})
        u = q.drop_duplicates().sort_values(["k", "d"]).to_numpy()      # sorted: _lookup needs a sorted table
        lo = np.searchsorted(sk_code, u[:, 0] * SHIFT + np.maximum(u[:, 1] - H, 0), "left")
        hi = np.searchsorted(sk_code, u[:, 0] * SHIFT + u[:, 1], "left")
        med = np.array([np.median(sk_qty[a:b]) if b > a else np.nan for a, b in zip(lo, hi)])
        uc = u[:, 0] * SHIFT + u[:, 1]
        qc = key[rows] * SHIFT + day[rows]
        return _lookup(uc, med, qc), _lookup(uc, (hi - lo).astype(float), qc)

    t1 = (n_prev >= min_prev) & (qty >= t1_mult * cust_med) & big_enough
    t4 = t4v & big_enough
    t7m = t7 & big_enough
    wd = (D0 + pd.to_timedelta(day, unit="D")).dayofweek.to_numpy()
    bk = np.minimum(((D0 + pd.to_timedelta(day, unit="D")).day.to_numpy() - 1) // 5, 5)

    def exceptions(q: np.ndarray, bigm: np.ndarray):
        """chu ky + nhu cau tang that for the query rows q; big lines = bigm (rows sorted by pair, day)."""
        bi = np.flatnonzero(bigm)
        bcode = pair[bi] * SHIFT + day[bi]
        lo = np.searchsorted(bcode, pair[q] * SHIFT + np.maximum(day[q] - H, 0), "left")
        hi = np.searchsorted(bcode, pair[q] * SHIFT + day[q], "right")
        nb = hi - lo
        tot = int(nb.sum())
        per = np.zeros(len(q), bool)
        if tot:
            qi = np.repeat(np.arange(len(q)), nb)
            j = bi[np.repeat(lo, nb) + (np.arange(tot) - np.repeat(np.cumsum(nb) - nb, nb))]
            mwd = np.zeros((len(q), 7), np.int32)
            np.add.at(mwd, (qi, wd[j]), 1)
            mbk = np.zeros((len(q), 6), np.int32)
            np.add.at(mbk, (qi, bk[j]), 1)
            dj = day[j]
            nd = np.r_[True, (qi[1:] != qi[:-1]) | (dj[1:] != dj[:-1])]
            hasg = nd & np.r_[False, qi[1:] == qi[:-1]]
            # the previous row of a new day belongs to the previous distinct day of the same query
            g = np.where(hasg, dj - np.r_[0, dj[:-1]], 0).astype(float)
            ng = np.bincount(qi, weights=hasg, minlength=len(q))
            s1 = np.bincount(qi, weights=g, minlength=len(q))
            s2 = np.bincount(qi, weights=g * g, minlength=len(q))
            with np.errstate(all="ignore"):
                mean = s1 / ng
                cv = np.sqrt(np.maximum(s2 / ng - mean ** 2, 0)) / mean
            per = (nb >= per_min_big) & (((ng >= 2) & (cv <= per_cv)) | (mwd.max(1) / np.maximum(nb, 1) >= per_share)
                                         | (mbk.max(1) / np.maximum(nb, 1) >= per_share))
        bdf = pd.DataFrame({"kd": kd[bi], "c": pair[bi]})
        nbc = bdf.drop_duplicates().groupby("kd")["c"].size()
        nbig_c = _lookup(nbc.index.to_numpy(np.int64), nbc.to_numpy(float), kd[q], fill=0)
        dem = (day_lines[q] >= exc_lines_mult * med_lines[q]) & np.isfinite(med_lines[q]) & (nbig_c >= exc_min_cust)
        return per, dem, nbig_c

    sel = np.flatnonzero((day >= s_day) & (day <= e_day))

    # ---- v3 (owner 07/11 ~23:10): compare with ORDER SIZE; regular customer (>= 3 earlier purchases) is a spike ONLY
    #      with T1 (T2 / T4 / T7 then add signals, T7 never alone); new customer: T2 + T4; wholesale customers: only T1;
    #      E4: series with spike lines (before exceptions) on >= e4_days distinct days in the e4_window days before
    #      asof -> no line of it flagged
    rows = np.flatnonzero(hist)
    slm = np.full(N, np.nan)
    nsl = np.zeros(N)
    slm[rows], nsl[rows] = ser_line_med(rows)
    t2 = (qty >= t2_k * slm) & (nsl >= min_ser_lines) & big_enough
    bigm = (t1 | t2) & hist
    reg = n_prev >= min_prev
    nraw = np.where(reg, np.where(t1, t1.astype(int) + t2 + t4 + t7m, 0), t2.astype(int) + t4)
    # frequent wholesale customer: >= ws_share of its earlier lines (pair, [d-H, d-1]) are big lines
    bi = np.flatnonzero(bigm)
    bcode = pair[bi] * SHIFT + day[bi]
    big_prev = (np.searchsorted(bcode, pcode, "left") - np.searchsorted(bcode, qlo, "left")).astype(float)
    with np.errstate(all="ignore"):
        big_share = np.where(n_prev > 0, big_prev / np.maximum(n_prev, 1), np.nan)
    ws = (n_prev >= min_prev) & (big_share >= ws_share)
    nsig = np.where(ws, t1.astype(int), nraw)
    q = np.flatnonzero((nraw >= 1) & hist & (day >= s_day))
    per, dem, nbig_c = exceptions(q, bigm)
    kept = np.where(n_prev[q] >= min_prev, cust_med[q], slm[q])
    kept = np.where(np.isfinite(kept), kept, qty[q])
    ex = np.where(per | dem, 0.0, np.maximum(qty[q] - kept, 0.0))
    a_day = (int((asof - D0).days) if asof is not None else de_day + 1)
    w = hist & (nraw >= 1) & (day >= a_day - e4_window) & (day < a_day)
    kdw = pd.DataFrame({"k": key[w], "d": day[w]}).drop_duplicates()["k"].value_counts()
    e4n = np.zeros(int(key.max()) + 1)
    e4n[kdw.index.to_numpy(np.int64)] = kdw.to_numpy()
    e4_big_days = e4n[key]
    e4 = (e4_big_days >= e4_days) if e4_days is not None else np.zeros(N, bool)
    ex = np.where(e4[q], 0.0, ex)

    out = pd.DataFrame({
        "d": L["d"].to_numpy()[sel], "fc_code": L["fc_code"].to_numpy()[sel], "sku_code": L["sku_code"].to_numpy()[sel],
        "so_code": L["so_code"].to_numpy()[sel],
        "customer_id": np.where(L["cust_unknown"].to_numpy()[sel], "", L["cust"].to_numpy()[sel]),
        "qty": qty[sel], "group_code": gcode[sel], "min_qty": minq[sel], "n_prev": n_prev[sel],
        "cust_med": cust_med[sel], "gap_med": gap_med[sel], "n_gaps": n_gaps[sel],
        "next_day": pd.to_timedelta(next_day[sel], unit="D") + D0, "med_lines": med_lines[sel],
        "day_lines": day_lines[sel], "day_qty": day_qty[sel], "day_med": day_med[sel], "day_rank": rank[sel]})
    out["ser_line_med"] = slm[sel]
    out["n_ser_lines"] = nsl[sel].astype(np.int64)
    out["big_prev"] = big_prev[sel].astype(np.int64)
    out["big_share"] = big_share[sel]
    out["T1"] = t1[sel]
    out["T2"] = t2[sel]
    out["T4"] = t4[sel]
    out["T7"] = t7m[sel]
    out["n_signals_raw"] = nraw[sel]
    out["exc_wholesale"] = ws[sel]
    out["n_signals"] = nsig[sel]
    out["is_regular"] = reg[sel]
    out["e4_big_days"] = e4_big_days[sel].astype(np.int64)
    out["exc_e4"] = e4[sel]
    pos = np.full(N, -1)
    pos[q] = np.arange(len(q))
    pq = pos[sel]
    hit = pq >= 0
    for name, (arr, fill) in {"exc_periodic": (per, False), "exc_demand": (dem, False), "kept": (kept, np.nan),
                              "excess": (ex, 0.0), "n_big_cust_day": (nbig_c, 0.0)}.items():
        v = np.full(len(sel), fill, dtype=arr.dtype if arr.dtype != bool else bool)
        v[hit] = arr[pq[hit]]
        out[name] = v
    exc = out["exc_periodic"] | out["exc_demand"]
    for k in LEVELS:                 # level k: >= k signals, no exception
        out[f"excess_L{k}"] = np.where((out["n_signals"] >= k) & ~exc, out["excess"], 0.0)
    for c in SIGNALS:
        out[c] = out[c].astype(np.int8)
    out = out.drop(columns="excess").sort_values(["d", "fc_code", "sku_code", "so_code", "customer_id"], kind="stable")
    return out[list(OUT_COLS)].reset_index(drop=True)


# ------------------------------------------------------------------ excess as of D (bt17.Excess)
class Excess:
    """Flagged lines (n_signals_raw >= 1) of one flag_lines run on all data (or spike_flag_lines rows); excess as of any
    day D (lines < D only).

    logic v3: a regular customer's line counts only with T1 (then T2 / T4 / T7 add signals), a new customer's line with
    T2 / T4 (T7 never counts); so T7 is recomputed as of D only on the regular T1 lines. E4 (e4 = N): a series with
    flagged lines on >= N distinct days in D-E4_WINDOW .. D-1 gets no excess at all as of D (= flag_lines(...,
    e4_days=N, asof=D)). keys: sku_code, fc_code; row = key index k (data.Inputs.keys; default the sorted keys of the
    lines); a line of another key is never counted. The next purchase of a line is known up to its data end
    (computed_for - 1 of a stored row, else data_end): a T7 that the days after it would decide raises ValueError."""

    def __init__(self, fl: pd.DataFrame, keys: pd.DataFrame | None = None, data_end=None):
        fl = fl.reset_index(drop=True)
        if keys is None:
            keys = fl[["sku_code", "fc_code"]].drop_duplicates().sort_values(["sku_code", "fc_code"])
        self.keys = keys[["sku_code", "fc_code"]].reset_index(drop=True)
        kidx = {x: i for i, x in enumerate(zip(self.keys["sku_code"], self.keys["fc_code"]))}
        self.k = np.fromiter((kidx.get(x, -1) for x in zip(fl["sku_code"], fl["fc_code"])), np.int64, len(fl))
        self.g = _g(fl["d"])
        self.next_g = _g(fl["next_day"])
        self.qty = fl["qty"].to_numpy(float)
        self.big = self.qty >= fl["min_qty"].to_numpy(float)
        gm = fl["gap_med"].to_numpy(float)
        self.need = 2.0 * np.nan_to_num(gm, nan=np.inf)
        self.elig7 = (fl["n_prev"].to_numpy(float) >= 3) & (fl["n_gaps"].to_numpy(float) >= 2) & (np.nan_to_num(gm) > 0)
        self.t1 = fl["T1"].to_numpy().astype(np.int64)
        self.t7 = fl["T7"].to_numpy().astype(np.int64)
        self.nraw = fl["n_signals_raw"].to_numpy().astype(np.int64)
        self.ws = fl["exc_wholesale"].to_numpy().astype(bool)
        self.exc = fl["exc_periodic"].to_numpy().astype(bool) | fl["exc_demand"].to_numpy().astype(bool)
        self.ex = np.maximum(self.qty - fl["kept"].to_numpy(float), 0.0)
        self.t7mask = (fl["is_regular"].to_numpy().astype(bool) & (self.t1 > 0)).astype(np.int64)
        if "computed_for" in fl.columns:
            self.end_g = _g(fl["computed_for"]) - 1
        elif data_end is not None:
            self.end_g = np.full(len(fl), g_of(data_end), np.int64)
        else:
            self.end_g = None
        self.frame = fl

    def signals_asof(self, D) -> np.ndarray:
        gD = g_of(D)
        last = gD - 1
        seen = (self.next_g >= 0) & (self.next_g <= last)
        t7 = self.elig7 & self.big & np.where(seen, (self.next_g - self.g) >= self.need, (last - self.g) >= self.need)
        if self.end_g is not None:
            # no next purchase up to the line's data end, D-1 after it, the gap not reached at the data end: unknown
            unknown = ((self.t7mask > 0) & self.elig7 & self.big & ~seen & (self.g < gD) & (self.end_g < last)
                       & ((self.end_g - self.g) < self.need))
            if unknown.any():
                i = int(np.flatnonzero(unknown)[0])
                raise ValueError(f"spike flags too old for {D}: line of {self.frame['d'].iloc[i]} computed with data "
                                 f"up to day {int(self.end_g[i])} ({int(unknown.sum())} lines)")
        return np.where(self.ws, self.t1, self.nraw + self.t7mask * (t7.astype(np.int64) - self.t7))

    def e4_days(self, D, window: int = E4_WINDOW) -> np.ndarray:
        """per key index (0 .. K-1): distinct days with a flagged line in D-window .. D-1."""
        gD = g_of(D)
        nk = len(self.keys)
        m = (self.k >= 0) & (self.g >= gD - window) & (self.g < gD)
        if not m.any():
            return np.zeros(nk, np.int64)
        u = np.unique(self.k[m] * SHIFT + self.g[m])
        return np.bincount(u // SHIFT, minlength=nk).astype(np.int64)

    def lines_asof(self, D, level: int, e4: int | None = None) -> np.ndarray:
        """excess per flagged line as of D at the level (0 for lines of days >= D; 0 for the series excluded by E4)."""
        gD = g_of(D)
        before = self.g < gD
        e = np.where(before & (self.signals_asof(D) >= level) & ~self.exc & (self.k >= 0), self.ex, 0.0)
        if e4 is not None:
            excl = self.e4_days(D) >= e4
            e = np.where((self.k >= 0) & excl[np.maximum(self.k, 0)], 0.0, e)
        return e

    def cells_asof(self, D, level: int, e4: int | None = None):
        """(k, g, excess) summed per series x day, days < D only."""
        e = self.lines_asof(D, level, e4)
        m = e > 0
        if not m.any():
            return np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0)
        code = self.k[m] * SHIFT + self.g[m]
        u, inv = np.unique(code, return_inverse=True)
        s = np.bincount(inv, weights=e[m])
        k, g = u // SHIFT, u % SHIFT
        if len(g) and g.max() >= g_of(D):
            raise RuntimeError("excess of a day >= D")
        return k, g, s

    def cells_frame(self, D, level: int, e4: int | None = None) -> pd.DataFrame:
        """cells_asof as sku_code, fc_code, d (date), excess (> 0)."""
        k, g, s = self.cells_asof(D, level, e4)
        return pd.DataFrame({"sku_code": self.keys["sku_code"].to_numpy()[k], "fc_code": self.keys["fc_code"].to_numpy()[k],
                             "d": [DAY0 + timedelta(days=int(x)) for x in g], "excess": s})


def clean_daily(daily: np.ndarray, k, g, e, D) -> np.ndarray:
    """K x G demand (data.Inputs.daily: day 0 = DAY0, rows = the keys of the Excess) minus the excess cells of days < D,
    clipped at 0 (a copy; the columns of days >= D unchanged)."""
    y = np.array(daily, dtype=np.float64, copy=True)
    gD = min(g_of(D), y.shape[1])
    m = (g < gD) & (k >= 0)
    np.subtract.at(y, (k[m], g[m]), e[m])
    y[:, :gD] = np.maximum(y[:, :gD], 0.0)
    return y


def clean_frame(frame: pd.DataFrame, cells: pd.DataFrame, D) -> pd.DataFrame:
    """demand frame (lgbm.load_frame: sku_id, fc_id, od, qty) with qty minus the excess of its SKU x FC x day
    (cells: sku_code, fc_code, d, excess) for days < D, clipped at 0; rows of days >= D and every other column as is."""
    if not len(cells) or not len(frame):
        return frame.copy()
    gD = g_of(D)
    cg = _g(cells["d"])
    c = pd.Series(cells["excess"].to_numpy(float)[cg < gD],
                  index=pd.MultiIndex.from_arrays([cells["sku_code"].to_numpy()[cg < gD],
                                                   cells["fc_code"].to_numpy()[cg < gD], cg[cg < gD]]))
    c = c.groupby(level=[0, 1, 2]).sum()
    fg = _g(frame["od"] if "od" in frame.columns else frame["order_date"])
    sub = c.reindex(pd.MultiIndex.from_arrays([frame["sku_id"].to_numpy(), frame["fc_id"].to_numpy(), fg])).to_numpy()
    sub = np.where((fg < gD) & np.isfinite(sub), sub, 0.0)
    q = frame["qty"].to_numpy(dtype=float)
    return frame.assign(qty=np.where(sub > 0, np.maximum(q - sub, 0.0), q))


# ------------------------------------------------------------------ tables of migration 0013 (caller's connection)
def read_lines(conn, scope_key: str, start, end) -> pd.DataFrame:
    """so_lines_cache rows of the scope with order_date in [start, end] as flag_lines input."""
    rows = conn.execute("SELECT order_date, so_code, customer_id, sku_code, fc_code, qty FROM so_lines_cache "
                        "WHERE scope_key=? AND order_date BETWEEN ? AND ?", (scope_key, str(start), str(end))).fetchall()
    df = pd.DataFrame([tuple(r) for r in rows], columns=["d", "so_code", "customer_id", "sku_code", "fc_code", "qty"])
    df["d"] = pd.to_datetime(df["d"])
    df["qty"] = df["qty"].astype(float)
    return df


def _opt(v):
    return None if v is None or pd.isna(v) else v


def write_flags(conn, scope_key: str, fl: pd.DataFrame, computed_for, start, end,
                history_days: int = HISTORY_DAYS) -> int:
    """Replace the spike_flag_lines rows of the scope (logic v3, history_days) with d in [start, end] by the flagged
    lines (n_signals_raw >= 1) of fl in that range (flag_lines output, data up to computed_for - 1). No commit."""
    start, end, cf = pd.Timestamp(start), pd.Timestamp(end), pd.Timestamp(computed_for)
    if end >= cf:
        raise ValueError(f"flags of {end.date()} cannot be computed for {cf.date()}")
    f = fl[(fl["n_signals_raw"] >= 1) & (pd.to_datetime(fl["d"]) >= start) & (pd.to_datetime(fl["d"]) <= end)]
    at = now_iso()
    conn.execute("DELETE FROM spike_flag_lines WHERE scope_key=? AND logic=? AND history_days=? AND d BETWEEN ? AND ?",
                 (scope_key, LOGIC, int(history_days), str(start.date()), str(end.date())))
    cols = [c for c in FLAG_COLS]
    rows = []
    for r in f[cols].itertuples(index=False, name=None):
        v = dict(zip(cols, r))
        nd = pd.Timestamp(v["next_day"]) if not pd.isna(v["next_day"]) else None
        rows.append((scope_key, LOGIC, int(history_days), str(pd.Timestamp(v["d"]).date()), v["fc_code"], v["sku_code"],
                     v["so_code"], v["customer_id"], float(v["qty"]), v["group_code"] or None, float(v["min_qty"]),
                     int(v["n_prev"]), _opt(v["cust_med"]), _opt(v["gap_med"]), int(v["n_gaps"]),
                     str(nd.date()) if nd is not None else None, float(v["kept"]),
                     *(int(v[s]) for s in SIGNALS), int(v["n_signals_raw"]), *(int(bool(v[x])) for x in FLAGS),
                     str(cf.date()), at))
    return conn.executemany(
        "INSERT INTO spike_flag_lines(scope_key, logic, history_days, d, fc_code, sku_code, so_code, customer_id, qty, "
        "group_code, min_qty, n_prev, cust_med, gap_med, n_gaps, next_day, kept, T1, T2, T4, T7, n_signals_raw, "
        "exc_wholesale, exc_periodic, exc_demand, is_regular, computed_for, computed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows).rowcount


def read_flags(conn, scope_key: str, start=None, end=None, history_days: int = HISTORY_DAYS) -> pd.DataFrame:
    """spike_flag_lines rows of the scope (logic v3, history_days; d in [start, end] when given) for Excess: FLAG_COLS
    + computed_for."""
    sql = ("SELECT " + ", ".join(FLAG_COLS) + ", computed_for FROM spike_flag_lines WHERE scope_key=? AND logic=? AND "
           "history_days=?")
    params = [scope_key, LOGIC, int(history_days)]
    if start is not None:
        sql += " AND d >= ?"
        params.append(str(pd.Timestamp(start).date()))
    if end is not None:
        sql += " AND d <= ?"
        params.append(str(pd.Timestamp(end).date()))
    rows = conn.execute(sql, params).fetchall()
    df = pd.DataFrame([tuple(r) for r in rows], columns=list(FLAG_COLS) + ["computed_for"])
    for c in ("d", "next_day", "computed_for"):
        df[c] = pd.to_datetime(df[c])
    df["group_code"] = df["group_code"].fillna("").astype(object)
    for c in ("qty", "min_qty", "cust_med", "gap_med", "kept"):
        df[c] = df[c].astype(float)
    return df


def write_excess_daily(conn, scope_key: str, cells: pd.DataFrame, level: int, e4_n: int, asof) -> int:
    """Replace the demand_excess_daily rows of the scope x level x e4_n by the cells (sku_code, fc_code, d, excess) as
    of asof (days < asof, excess > 0). No commit."""
    a = pd.Timestamp(asof)
    c = cells[(cells["excess"] > 0) & (pd.to_datetime(cells["d"]) < a)]
    at = now_iso()
    conn.execute("DELETE FROM demand_excess_daily WHERE scope_key=? AND level=? AND e4_n=?",
                 (scope_key, int(level), int(e4_n)))
    return conn.executemany(
        "INSERT INTO demand_excess_daily(scope_key, d, fc_code, sku_code, level, e4_n, excess, asof, computed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ((scope_key, str(pd.Timestamp(d).date()), f, s, int(level), int(e4_n), float(e), str(a.date()), at)
         for s, f, d, e in zip(c["sku_code"], c["fc_code"], c["d"], c["excess"]))).rowcount
