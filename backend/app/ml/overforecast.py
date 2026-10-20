"""1.2.9c: standard over / under-forecast metrics, the normal-day split and walk-forward calibration factors - EVALUATION
and EXPERIMENT code (reports/demandforecast_multi_item_overforecast_20261020.md). The application's training, forecast
and publication do not use it: no stored forecast is scaled and no accuracy figure of the app changes.

Metrics over one set of observations (one SKU x FC x day unless the caller aggregates first; F forecast, A actual):
  bias  = sum(F - A) / sum(A)            signed: > 0 the forecast total is above the actual total
  over  = sum(max(F - A, 0)) / sum(A)    the forecast in excess, never offset by a shortfall elsewhere
  under = sum(max(A - F, 0)) / sum(A)
  wape  = sum|F - A| / sum(A)            (= over + under)
  ratio = sum(F) / sum(A)
sum(A) = 0 or no observation: every ratio is None (undefined) - nothing is divided by 0 and no observation is dropped.

Normal day (an evaluation label, never a model input): a known evaluated day that is not a spike day of demand_patterns.
The threshold comes from the history BEFORE the cutoff only, but the label needs the day's actual: it can only be used
after the fact (accuracy reports, experiments), never at forecast time.

Walk-forward calibration (post-processing experiments): a factor comes from the actuals and forecasts of EARLIER
evaluation windows only (windows that ended before the origin that uses the factor). A segment with too little earlier
forecast volume falls back to the global factor; the others are shrunk toward it. A factor multiplies the raw forecast:
zero stays zero (there is no minimum forecast) and the whole-number rule of app/qty.py is applied afterwards.
"""
from __future__ import annotations

import numpy as np

from . import demand_patterns

RATIOS = ("bias", "over", "under", "wape", "ratio")
SHRINK_UNITS = 5000.0        # pseudo-volume (units of forecast) pulling a segment factor toward the global factor
MIN_SEGMENT_UNITS = 500.0    # below this earlier forecast volume a segment uses the global factor


def metrics(actual, forecast) -> dict:
    """The five ratios over paired, known observations (select them first: NaN is refused, not skipped)."""
    a = np.asarray(actual, dtype=float).ravel()
    f = np.asarray(forecast, dtype=float).ravel()
    if a.shape != f.shape:
        raise ValueError(f"actual {a.shape} and forecast {f.shape} differ")
    if np.isnan(a).any() or np.isnan(f).any():
        raise ValueError("observations must be known values")
    sa = float(a.sum())
    out = {"n": int(a.size), "sum_actual": sa, "sum_forecast": float(f.sum())}
    if a.size == 0 or sa <= 0:
        return out | dict.fromkeys(RATIOS)
    d = f - a
    return out | {"bias": float(d.sum() / sa), "over": float(np.clip(d, 0, None).sum() / sa),
                  "under": float(np.clip(-d, 0, None).sum() / sa), "wape": float(np.abs(d).sum() / sa),
                  "ratio": float(f.sum() / sa)}


def whole_units(yhat) -> np.ndarray:
    """app/qty.business_qty for an array: round half up, never below 0; NaN stays NaN."""
    y = np.asarray(yhat, dtype=float)
    with np.errstate(invalid="ignore"):
        return np.where(np.isnan(y), np.nan, np.floor(np.maximum(y, 0.0) + 0.5))


def normal_days(actual: np.ndarray, history: np.ndarray) -> np.ndarray:
    """S x H boolean: the evaluated day is known (not NaN) and not a spike day. history = the panel BEFORE the cutoff
    (S x T0); only its last demand_patterns window sets the thresholds."""
    flags = demand_patterns.spike_flags(actual, demand_patterns.spike_thresholds(history, history.shape[1]))
    return ~np.isnan(actual) & ~flags


def calibration_factor(prev_actual, prev_forecast, target_bias: float = 0.0) -> float | None:
    """k such that k x the earlier forecasts would have had the signed bias `target_bias` on the earlier actuals:
    (1 + target_bias) x sum(A) / sum(F). None when there is no earlier forecast volume to learn from."""
    sa, sf = float(np.nansum(prev_actual)), float(np.nansum(prev_forecast))
    if sf <= 0:
        return None
    return (1.0 + target_bias) * sa / sf


def walk_forward_factors(windows: list[tuple], target_bias: float = 0.0) -> list[float | None]:
    """windows = [(actual, forecast), ...] of consecutive evaluation windows in time order. Factor i uses windows 0..i-1
    only (the first one has none -> None)."""
    out = []
    for i in range(len(windows)):
        if i == 0:
            out.append(None)
            continue
        a = np.concatenate([np.asarray(w[0], dtype=float).ravel() for w in windows[:i]])
        f = np.concatenate([np.asarray(w[1], dtype=float).ravel() for w in windows[:i]])
        out.append(calibration_factor(a, f, target_bias))
    return out


def segment_factors(prev_actual: dict, prev_forecast: dict, k_global: float, shrink: float = SHRINK_UNITS,
                    min_units: float = MIN_SEGMENT_UNITS) -> dict:
    """Per segment from the earlier windows' sums: (sum A + shrink x k_global) / (sum F + shrink); a segment whose
    earlier forecast volume is below `min_units` (or absent) uses k_global."""
    out = {}
    for seg in set(prev_actual) | set(prev_forecast):
        sa, sf = float(prev_actual.get(seg, 0.0)), float(prev_forecast.get(seg, 0.0))
        out[seg] = k_global if sf < min_units else (sa + shrink * k_global) / (sf + shrink)
    return out
