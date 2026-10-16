"""Forecast accuracy metrics. Same definitions are documented in the UI glossary.

WAPE  = sum|actual - forecast| / sum(actual)           lower is better; undefined if sum(actual) == 0
MAE   = mean|actual - forecast|                         lower is better (units of quantity)
Bias  = (sum(forecast) - sum(actual)) / sum(actual)     0 is best; > 0 over-forecast, < 0 under-forecast
MAPE  = mean(|actual - forecast| / actual) over points with actual >= mape_min_actual only;
        the number of excluded points is reported; undefined if no point qualifies.
"""
from __future__ import annotations

import numpy as np


def compute(actual, forecast, mape_min_actual: float = 1.0) -> dict:
    a = np.asarray(actual, dtype=float)
    f = np.asarray(forecast, dtype=float)
    m = ~(np.isnan(a) | np.isnan(f))
    a, f = a[m], f[m]
    n = int(a.size)
    out: dict = {"n_points": n, "sum_actual": float(a.sum()), "sum_forecast": float(f.sum()),
                 "wape": None, "mae": None, "bias": None, "mape": None,
                 "mape_points": 0, "mape_excluded_points": n, "notes": []}
    if n == 0:
        out["notes"].append("NO_POINTS")
        return out
    err = np.abs(a - f)
    out["mae"] = float(err.mean())
    sa = a.sum()
    if sa > 0:
        out["wape"] = float(err.sum() / sa)
        out["bias"] = float((f.sum() - sa) / sa)
    else:
        out["notes"].append("SUM_ACTUAL_ZERO")
    q = a >= mape_min_actual
    out["mape_points"] = int(q.sum())
    out["mape_excluded_points"] = int(n - q.sum())
    if q.any():
        out["mape"] = float(np.mean(err[q] / a[q]))
    else:
        out["notes"].append("MAPE_UNDEFINED")
    return out
