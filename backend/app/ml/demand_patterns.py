"""1.2.9: demand-pattern groups of SKU x FC series and spike flags - for EVALUATION and analysis only.

Nothing here changes, clips, down-weights or removes a demand value, and nothing is a model input: a group or a flag is
computed from the history BEFORE a cutoff (a backtest fold origin) and is used to report accuracy per group, so an
aggregate WAPE cannot hide a group that got worse. The thresholds are analysis parameters, not business rules.

Groups (Syntetos-Boylan classification over the last `window` known days before the cutoff; a known day is a day that is
not NaN - days before the series started and days without any data are not counted):
  SHORT_HISTORY  fewer than `min_known` known days
  INACTIVE       no positive day in the window
  SMOOTH         ADI < 1.32 and CV2 < 0.49
  ERRATIC        ADI < 1.32 and CV2 >= 0.49
  INTERMITTENT   ADI >= 1.32 and CV2 < 0.49
  LUMPY          ADI >= 1.32 and CV2 >= 0.49
ADI = known days / positive days (average interval between demand days); CV2 = (std / mean)^2 of the positive daily
quantities.

Spike day of an evaluated day d (series s, cutoff T): actual(s, d) >= `spike_min_qty` and greater than BOTH
`spike_factor` x the median positive daily quantity of s in the window before T and that median + `spike_mad` x 1.4826 x
MAD (robust z-score). It flags an unusually large day relative to the series' OWN history; it does not say whether the
day is a bulk order, an event, a data error or demand released after a stock-out - the source has no field that can tell
them apart (see docs/MO-HINH-VA-CHI-SO.md).

Volume tier (cutoff): HIGH_VOLUME = the series with the largest mean daily demand that together make `high_share` of the
window's demand; the others LOW_VOLUME; series without demand in the window NO_VOLUME.
"""
from __future__ import annotations

import warnings

import numpy as np

GROUPS = ("SMOOTH", "ERRATIC", "INTERMITTENT", "LUMPY", "INACTIVE", "SHORT_HISTORY")
TIERS = ("HIGH_VOLUME", "LOW_VOLUME", "NO_VOLUME")
ADI_CUT, CV2_CUT = 1.32, 0.49
DEFAULTS = {"window": 91, "min_known": 28, "spike_factor": 3.0, "spike_mad": 5.0, "spike_min_qty": 10.0,
            "high_share": 0.8}


def _window(Y: np.ndarray, cutoff: int, window: int) -> np.ndarray:
    return Y[:, max(0, cutoff - window):cutoff]


def classify(Y: np.ndarray, cutoff: int, window: int = DEFAULTS["window"],
             min_known: int = DEFAULTS["min_known"]) -> dict:
    """Group of every series at `cutoff` (column index of the first day NOT used) from Y[:, :cutoff] only."""
    W = _window(Y, cutoff, window)
    S = Y.shape[0]
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)      # series without a positive day: NaN mean / std, handled below
        known = np.sum(~np.isnan(W), axis=1)
        pos_mask = W > 0
        pos = np.sum(pos_mask, axis=1)
        Wp = np.where(pos_mask, W, np.nan)
        mean_p = np.nanmean(Wp, axis=1)
        std_p = np.nanstd(Wp, axis=1)
        adi = np.where(pos > 0, known / np.maximum(pos, 1), np.inf)
        cv2 = np.where(pos > 1, (std_p / mean_p) ** 2, 0.0)
    g = np.empty(S, dtype=object)
    g[:] = "SMOOTH"
    g[(adi < ADI_CUT) & (cv2 >= CV2_CUT)] = "ERRATIC"
    g[(adi >= ADI_CUT) & (cv2 < CV2_CUT)] = "INTERMITTENT"
    g[(adi >= ADI_CUT) & (cv2 >= CV2_CUT)] = "LUMPY"
    g[pos == 0] = "INACTIVE"
    g[known < min_known] = "SHORT_HISTORY"
    return {"group": g, "adi": adi, "cv2": cv2, "known_days": known, "positive_days": pos}


def volume_tier(Y: np.ndarray, cutoff: int, window: int = DEFAULTS["window"],
                high_share: float = DEFAULTS["high_share"]) -> np.ndarray:
    W = _window(Y, cutoff, window)
    with np.errstate(all="ignore"):
        tot = np.nansum(W, axis=1)
    tier = np.where(tot > 0, "LOW_VOLUME", "NO_VOLUME").astype(object)
    if tot.sum() > 0:
        order = np.argsort(-tot, kind="stable")
        cum = np.cumsum(tot[order]) / tot.sum()
        # the largest series up to and including the one that reaches high_share
        n_high = int(np.searchsorted(cum, high_share) + 1)
        tier[order[:n_high]] = "HIGH_VOLUME"
    return tier


def spike_thresholds(Y: np.ndarray, cutoff: int, window: int = DEFAULTS["window"],
                     spike_factor: float = DEFAULTS["spike_factor"], spike_mad: float = DEFAULTS["spike_mad"],
                     spike_min_qty: float = DEFAULTS["spike_min_qty"]) -> np.ndarray:
    """Per-series threshold above which an evaluated day counts as a spike (inf when the series has no positive day
    before the cutoff - nothing can be called unusual without a reference)."""
    W = _window(Y, cutoff, window)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)      # series without a positive day: NaN median -> inf below
        Wp = np.where(W > 0, W, np.nan)
        med = np.nanmedian(Wp, axis=1)
        mad = np.nanmedian(np.abs(Wp - med[:, None]), axis=1)
    thr = np.maximum(np.maximum(spike_factor * med, med + spike_mad * 1.4826 * mad), spike_min_qty)
    return np.where(np.isnan(med), np.inf, thr)


def spike_flags(actual: np.ndarray, thresholds: np.ndarray) -> np.ndarray:
    """actual: (S, H) evaluated days; True where the day exceeds its series' threshold (NaN actual = False)."""
    with np.errstate(invalid="ignore"):
        return np.nan_to_num(actual, nan=-np.inf) > thresholds[:, None]
