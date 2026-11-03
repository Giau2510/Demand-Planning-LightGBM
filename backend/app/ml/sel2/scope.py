"""Forecast scope of a forecast day D (backtest reports/cai-tien-20261031/code/ct_prep.py, "scope 0.3").

A key (sku x fc) is in scope of D when, over the SCOPE_DAYS calendar days D-90 .. D-1:
  * it has at least one day with demand > 0, and
  * the sum of its open hours, clip(hours, 0) with no row (NaN) = 0 h, is >= MIN_OPEN_HOURS.
Arrays: day index g = days since the array's day 0; g_d = index of D (D itself and later days are never read).
Day-0 contract: the open hours are summed as float32 running totals from the array's day 0, so the arrays must start on
the backtest's day 0 (sel2.data.DAY0 = 2025-01-01) with float32 open hours, as the backtest's oh.npy; the difference of
the two running totals is taken in float64 (ct_prep.py, scope 0.3)."""
from __future__ import annotations

import numpy as np

SCOPE_DAYS = 90
MIN_OPEN_HOURS = 1.0


def scope_mask(daily: np.ndarray, oh: np.ndarray, g_d: int) -> np.ndarray:
    """bool[K]. daily: K x G demand (0 = no order); oh: K x G open hours (NaN = no row). The arrays must cover the
    whole window (g_d >= SCOPE_DAYS): a shorter history would silently change the rule."""
    if g_d < SCOPE_DAYS:
        raise ValueError(f"scope window D-{SCOPE_DAYS} .. D-1 is not covered (g_d={g_d})")
    lo = g_d - SCOPE_DAYS
    sold = (daily[:, lo:g_d] > 0).sum(axis=1)
    # the backtest's float32 running total from the array's day 0, widened to float64 by its float64 zero column, then
    # the difference of two prefix sums in float64 (ct_prep.py:145): a window total within float rounding of 1.0 h
    # falls on the same side of the threshold
    run = np.concatenate([np.zeros((oh.shape[0], 1)),
                          np.cumsum(np.nan_to_num(np.clip(oh[:, :g_d].astype(np.float32), 0, None)), axis=1)], axis=1)
    hrs = run[:, g_d] - run[:, lo]
    return (sold >= 1) & (hrs >= MIN_OPEN_HOURS)
