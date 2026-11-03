"""Simple per-series candidates of a forecast day D, horizons 1..HORIZONS (backtest
reports/cai-tien-20261031/code/ct_simple.py; same arithmetic, same order of operations).

Arrays: daily K x G demand (float, 0 = no order), open_mask K x G (open_mask(): open hours > 0, no row = closed); day
index g = days since day0 (a Vietnam calendar date); g_d = index of D. Only the days < D are read. Values are clipped at
0, float64, not rounded.
  TSB   Teunter-Syntetos-Babai on the open days from TSB_START: the first TSB_INIT_DAYS open days give the start
        p = days with demand / 28, z = mean demand of those days (0 without one); then every open day
        p += beta (I - p), and z += alpha (y - z) on the open days with demand (I = demand > 0 on an open day).
        Forecast p x z for every horizon; fewer than 28 open days -> 0.
  DOW4  per horizon h: mean of the first DOW4_N open days with the weekday of D+h-1 among D-84 .. D-1, newest first
        (weekday Monday = 0); no such open day -> 0.
  AVG7  mean of the 7 calendar days D-7 .. D-1 (closed days included as their demand, usually 0), every horizon."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

TSB_START = date(2026, 1, 1)
TSB_ALPHA = TSB_BETA = 0.1
TSB_INIT_DAYS = 28
DOW4_DAYS = 84
DOW4_N = 4
AVG7_DAYS = 7
HORIZONS = 7


def open_mask(oh: np.ndarray) -> np.ndarray:
    """Open days: open hours > 0 (NaN = no row = closed)."""
    return np.nan_to_num(oh) > 0


def tsb(daily: np.ndarray, open_mask: np.ndarray, g_d: int, g_start: int, alpha: float = TSB_ALPHA,
        beta: float = TSB_BETA) -> np.ndarray:
    """float[K]: TSB forecast of D (same value for every horizon). g_start = index of TSB_START; days g_start .. D-1."""
    if not 0 <= g_start <= g_d:
        raise ValueError(f"TSB start {g_start} must be within the arrays and not after D ({g_d})")
    daily = np.asarray(daily, dtype=np.float64)
    K = daily.shape[0]
    p = np.full(K, np.nan)
    z = np.full(K, np.nan)
    n_open = np.zeros(K)
    init_s = np.zeros(K)
    init_d = np.zeros(K)
    for g in range(g_start, g_d):                     # update with day g (< D) only
        o = open_mask[:, g]
        y = daily[:, g]
        I = (y > 0) & o
        warm = o & (n_open < TSB_INIT_DAYS)
        init_s += np.where(warm & I, y, 0)
        init_d += warm & I
        start = o & (n_open == TSB_INIT_DAYS - 1)
        with np.errstate(all="ignore"):
            p = np.where(start, init_d / float(TSB_INIT_DAYS), p)
            z = np.where(start, np.where(init_d > 0, init_s / np.maximum(init_d, 1), 0.0), z)
        run = o & (n_open >= TSB_INIT_DAYS)
        p = np.where(run, p + beta * (I - p), p)
        z = np.where(run & I, z + alpha * (y - z), z)
        n_open += o
    return np.clip(np.nan_to_num(p * z), 0, None)


def dow4(daily: np.ndarray, open_mask: np.ndarray, g_d: int, day0: date, horizons: int = HORIZONS) -> np.ndarray:
    """float[K, horizons]: column h-1 = DOW4 of target day D+h-1."""
    if g_d < DOW4_DAYS:
        raise ValueError(f"DOW4 window D-{DOW4_DAYS} .. D-1 is not covered (g_d={g_d})")
    daily = np.asarray(daily, dtype=np.float64)
    lo = g_d - DOW4_DAYS
    D = day0 + timedelta(days=g_d)
    out = np.zeros((daily.shape[0], horizons))
    for h in range(horizons):
        wd = (D + timedelta(days=h)).weekday()
        cols = [x for x in range(lo, g_d) if (day0 + timedelta(days=x)).weekday() == wd]
        v = np.where(open_mask[:, cols], daily[:, cols], np.nan)[:, ::-1]     # newest first
        known = ~np.isnan(v)
        take = known & (np.cumsum(known, axis=1) <= DOW4_N)
        n = take.sum(axis=1)
        out[:, h] = np.where(n > 0, np.where(take, v, 0).sum(axis=1) / np.maximum(n, 1), 0.0)
    return np.clip(out, 0, None)


def avg7(daily: np.ndarray, g_d: int) -> np.ndarray:
    """float[K]: mean of the 7 calendar days D-7 .. D-1 (same value for every horizon)."""
    if g_d < AVG7_DAYS:
        raise ValueError(f"AVG7 window D-{AVG7_DAYS} .. D-1 is not covered (g_d={g_d})")
    win = np.asarray(daily[:, g_d - AVG7_DAYS:g_d], dtype=np.float64)
    return np.clip(win.mean(axis=1), 0, None)
