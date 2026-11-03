"""Extra LightGBM feature blocks of SEL2 (backtest reports/cai-tien-20261031/code/ct_feat.py, Features.origin /
Features.target / Features._dayprof / trimmed_mean, without capping: same formulas, same column order and names).

Y is a panel demand array S x T (app.ml.features.Panel.Y: NaN = series not started yet or calendar day without data);
t0 = origin column: only the columns < t0 are read. The values are float64; ct_feat casts the stacked columns to
float32 (the training matrix dtype), the caller does the same.
  ROBUST  origin columns: median / 25th / 75th percentile (np.nanpercentile, linear) of the known values of the last
          7, 14, 28, 56 columns, then the trimmed mean (TRIM_FRAC) of the last 28 and 56 columns; no known value -> NaN.
  DAYPROF target columns for a target day td (its weekday, Monday = 0, and its day-of-month bucket):
          dow_share_8w / dow_share_12w   share of the weekday in the demand of the last 56 / 84 columns (NaN = 0 total)
          dom_share_12w                  share of the day-of-month bucket (1-5, 6-10, .., 26-31) in the last 84 columns
          same_dow_mean_4                mean of the known values of the last 4 columns with the weekday (whole panel)
          dow_order_rate_12w             share of the known days of the weekday in the last 84 columns with demand > 0"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from ..features import _nanmean

ROBUST_WINDOWS = (7, 14, 28, 56)
TRIM_WINDOWS = (28, 56)
TRIM_FRAC = 0.10
ROBUST_NAMES = [f"{s}_{w}" for w in ROBUST_WINDOWS for s in ("med", "p25", "p75")] + [f"tmean_{w}" for w in TRIM_WINDOWS]
DAYPROF_NAMES = ["dow_share_8w", "dow_share_12w", "dom_share_12w", "same_dow_mean_4", "dow_order_rate_12w"]


def bucket(dom: int) -> int:
    """Day-of-month bucket 0..5: 1-5, 6-10, 11-15, 16-20, 21-25, 26-31."""
    return min((dom - 1) // 5, 5)


def trimmed_mean(win: np.ndarray, frac: float) -> np.ndarray:
    """Mean of the known values of each row without the ceil(frac x n) highest ones (n = known values of the row)."""
    S, W = win.shape
    if W == 0:
        return np.full(S, np.nan)
    v = np.where(np.isnan(win), -np.inf, win)
    v = -np.sort(-v, axis=1)                                          # descending, unknown (-inf) last
    n = (~np.isnan(win)).sum(axis=1)
    drop = np.ceil(frac * n).astype(int)
    j = np.arange(W)[None, :]
    keep = (j >= drop[:, None]) & (j < n[:, None])
    s = np.where(keep, v, 0.0).sum(axis=1)
    c = keep.sum(axis=1)
    with np.errstate(all="ignore"):
        return np.where(c > 0, s / np.maximum(c, 1), np.nan)


def robust(Y: np.ndarray, t0: int) -> np.ndarray:
    """float64[S, len(ROBUST_NAMES)] of origin t0."""
    S = Y.shape[0]
    if S == 0:
        return np.zeros((0, len(ROBUST_NAMES)))
    hist = Y[:, :t0]
    cols = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)               # all-NaN rows -> NaN
        for w in ROBUST_WINDOWS:
            win = hist[:, max(0, t0 - w):t0]
            if win.shape[1] == 0:
                cols += [np.full(S, np.nan)] * 3
                continue
            q = np.nanpercentile(win, [50, 25, 75], axis=1)
            cols += [q[0], q[1], q[2]]
        for w in TRIM_WINDOWS:
            cols.append(trimmed_mean(hist[:, max(0, t0 - w):t0], TRIM_FRAC))
    return np.column_stack(cols).astype(np.float64)


def dayprof_profile(Y: np.ndarray, dates, t0: int) -> dict:
    """Profiles of origin t0, computed once and read for every target day (dayprof_columns): s56 / s84 / rate / last4
    S x 7 (weekday), dom S x 6 (bucket). dates: the panel calendar (one date per column of Y)."""
    dates = pd.DatetimeIndex(dates)
    S = Y.shape[0]
    dows = dates.dayofweek.to_numpy()
    doms = dates.day.to_numpy()
    res = {}
    with np.errstate(all="ignore"):
        for W, nm in ((56, "s56"), (84, "s84")):
            lo = max(0, t0 - W)
            win = np.nan_to_num(Y[:, lo:t0])
            tot = win.sum(axis=1)
            res[nm] = np.column_stack([np.where(tot > 0, win[:, dows[lo:t0] == d].sum(axis=1) / tot, np.nan)
                                       for d in range(7)])
        lo = max(0, t0 - 84)
        win = Y[:, lo:t0]
        w0 = np.nan_to_num(win)
        tot = w0.sum(axis=1)
        bk = np.array([bucket(x) for x in doms[lo:t0]], dtype=int)
        res["dom"] = np.column_stack([np.where(tot > 0, w0[:, bk == b].sum(axis=1) / tot, np.nan) for b in range(6)])
        known = ~np.isnan(win)
        res["rate"] = np.column_stack([np.where(known[:, dows[lo:t0] == d].sum(axis=1) > 0,
                                                (np.nan_to_num(win[:, dows[lo:t0] == d]) > 0).sum(axis=1)
                                                / np.maximum(known[:, dows[lo:t0] == d].sum(axis=1), 1), np.nan)
                                       for d in range(7)])
        last4 = np.full((S, 7), np.nan)
        for d in range(7):
            idx = np.nonzero(dows[:t0] == d)[0][-4:]                  # last 4 columns of the weekday, known or not
            if len(idx):
                last4[:, d] = _nanmean(Y[:, idx])
        res["last4"] = last4
    return res


def dayprof_columns(profile: dict, td) -> np.ndarray:
    """float64[S, len(DAYPROF_NAMES)] of target day td (only its weekday and day of month are used)."""
    td = pd.Timestamp(td)
    dw, b = td.dayofweek, bucket(td.day)
    return np.column_stack([profile["s56"][:, dw], profile["s84"][:, dw], profile["dom"][:, b],
                            profile["last4"][:, dw], profile["rate"][:, dw]]).astype(np.float64)


def dayprof(Y: np.ndarray, dates, t0: int, td) -> np.ndarray:
    """float64[S, len(DAYPROF_NAMES)] of origin t0 and target day td."""
    return dayprof_columns(dayprof_profile(Y, dates, t0), td)
