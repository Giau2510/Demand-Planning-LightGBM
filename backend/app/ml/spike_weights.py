"""1.2.9b: spike-aware TRAINING WEIGHTS - experiment code. The application's training does not use it (model.train is
called without weights); a result can only become a model option after the owner decides (reports/).

Hypothesis of the owner (20/10/2026), tested on a database copy, NOT a business rule: a spike that lasts ONE day is
mostly noise for the next days and gets a lower weight in the training loss; a spike that repeats on the NEXT day is a
signal to learn (higher weight); if the two-day spike is gone on the THIRD day its weight is lowered again; three or more
spike days in a row are a level change and keep the full weight.

* No demand value is changed, clipped or removed: targets, features and stored data stay the real values. Only the
  weight of a training row (its series and TARGET day) in the LightGBM loss changes.
* Nothing after the cutoff is used. Weights are computed for a training panel that ends at the cutoff T (Y[:, :T], the
  first day NOT known is T): the threshold of day t comes from days before t only ("rolling", the default) or from the
  window before T ("cutoff", as the evaluation flags of demand_patterns); an episode whose next day is T or later (or a
  day without data) is still OPEN - it is classified with what is known at T, and the same day can get another weight in
  a later training, when the next days are known (time-updated, never looking ahead).
* The spike threshold is the one of demand_patterns (>= `spike_min_qty` and above both `spike_factor` x the median
  positive day and that median + `spike_mad` x 1.4826 x MAD of the series' own history). A flag says "unusually large for
  this series", not bulk order / promotion / data error: the source has no field that tells them apart.
"""
from __future__ import annotations

import warnings

import numpy as np

from . import demand_patterns

DETECTION = ("rolling", "cutoff")
# episode classes of a spike day (what is known at the cutoff)
SINGLE = "SINGLE"                # one spike day, the next day known and normal (or the cutoff right after: OPEN_SINGLE)
OPEN_SINGLE = "OPEN_SINGLE"      # spike on the last known day: nothing known yet about the next day
DOUBLE_OPEN = "DOUBLE_OPEN"      # two spike days, the third day not known yet
DOUBLE_CLOSED = "DOUBLE_CLOSED"  # two spike days, the third day known and normal
LONG = "LONG"                    # three or more spike days in a row
CLASSES = (SINGLE, OPEN_SINGLE, DOUBLE_OPEN, DOUBLE_CLOSED, LONG)


def rolling_thresholds(Y: np.ndarray, window: int = demand_patterns.DEFAULTS["window"],
                       spike_factor: float = demand_patterns.DEFAULTS["spike_factor"],
                       spike_mad: float = demand_patterns.DEFAULTS["spike_mad"],
                       spike_min_qty: float = demand_patterns.DEFAULTS["spike_min_qty"]) -> np.ndarray:
    """S x T threshold of every day t from the known days of [t - window, t) of the same series (never day t itself or
    a later day); inf where the series has no positive day in that window."""
    S, T = Y.shape
    thr = np.full((S, T), np.inf)
    for t in range(1, T):
        thr[:, t] = demand_patterns.spike_thresholds(Y, t, window, spike_factor, spike_mad, spike_min_qty)
    return thr


def spike_days(Y: np.ndarray, detection: str = "rolling", **params) -> tuple[np.ndarray, np.ndarray]:
    """(flags, thresholds), both S x T, for the training panel Y (= data before the cutoff only)."""
    if detection not in DETECTION:
        raise ValueError(f"detection must be one of {DETECTION}")
    if detection == "rolling":
        thr = rolling_thresholds(Y, **params)
    else:
        thr = np.repeat(demand_patterns.spike_thresholds(Y, Y.shape[1], **params)[:, None], Y.shape[1], axis=1)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        flags = np.nan_to_num(Y, nan=-np.inf) > thr
    return flags, thr


def episodes(flags: np.ndarray, known: np.ndarray) -> np.ndarray:
    """S x T class of every spike day ('' elsewhere). A run ends CLOSED when the day after it is known and not a spike,
    OPEN when that day is the cutoff (T) or a day without data."""
    S, T = flags.shape
    out = np.full((S, T), "", dtype=object)
    for s in range(S):
        row = flags[s]
        if not row.any():
            continue
        t = 0
        while t < T:
            if not row[t]:
                t += 1
                continue
            a = t
            while t < T and row[t]:
                t += 1
            b = t - 1                                  # run [a, b]
            n = b - a + 1
            closed = b + 1 < T and bool(known[s, b + 1])
            if n >= 3:
                c = LONG
            elif n == 2:
                c = DOUBLE_CLOSED if closed else DOUBLE_OPEN
            else:
                c = SINGLE if closed else OPEN_SINGLE
            out[s, a:b + 1] = c
    return out


def weights(Y: np.ndarray, w: dict, detection: str = "rolling", **params) -> tuple[np.ndarray, dict]:
    """S x T training weights for the panel Y (data before the cutoff only) and a summary.
    w: weight per class (CLASSES; a missing class keeps 1.0), or {"soft": True} for weight = threshold / value on every
    spike day (a spike counts like a day AT the threshold; the value itself is not changed)."""
    flags, thr = spike_days(Y, detection, **params)
    known = ~np.isnan(Y)
    cls = episodes(flags, known)
    W = np.ones(Y.shape)
    if w.get("soft"):
        with np.errstate(divide="ignore", invalid="ignore"):
            W = np.where(flags, np.minimum(1.0, thr / np.where(flags, Y, 1.0)), 1.0)
    else:
        for c in CLASSES:
            if c in w:
                W[cls == c] = float(w[c])
    days = {c: int(np.sum(cls == c)) for c in CLASSES}
    starts = flags & ~np.concatenate([np.zeros((Y.shape[0], 1), dtype=bool), flags[:, :-1]], axis=1)
    runs = {c: int(np.sum(starts & (cls == c))) for c in CLASSES}       # one count per episode (its first day)
    summary = {"detection": detection, "spike_days": int(flags.sum()), "spike_days_by_class": days,
               "episodes_by_class": runs, "series_with_spike": int(flags.any(axis=1).sum()),
               "days_down_weighted": int(np.sum(flags & (W < 1))), "days_kept_full_weight": int(np.sum(flags & (W >= 1))),
               "spike_qty": float(np.nansum(np.where(flags, Y, 0))), "known_qty": float(np.nansum(Y))}
    return W, summary
