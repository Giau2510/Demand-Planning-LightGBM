"""LightGBM training, per-series fallback policy, recursive multi-day forecasting and walk-forward backtest."""
from __future__ import annotations

import logging

import lightgbm as lgb
import numpy as np
import pandas as pd

from . import demand_patterns, metrics
from .features import (Panel, direct_extra, direct_training_matrix, feature_names, features_at, is_direct,
                       origin_features, static_codes, training_matrix)

log = logging.getLogger("df.ml")

METHOD_LGBM = "LIGHTGBM"
FB_NEW = "FALLBACK_NEW_SERIES"            # too little history for lag features
FB_INTERMITTENT = "FALLBACK_INTERMITTENT"  # mostly-zero demand
FB_INACTIVE = "FALLBACK_INACTIVE_ZERO"     # no orders for a long time
FB_MODEL_UNAVAILABLE = "FALLBACK_MODEL_UNAVAILABLE"
# 1.2.2: the backtest baseline as a publishable candidate (chosen only when it scored better on the same points)
METHOD_BASELINE = "BASELINE_MOVING_AVERAGE"
BASELINE_WINDOW_DAYS = 28
SIX_MONTHS_DAYS = 182


class Cancelled(Exception):
    pass


def lgb_params(cfg, seed: int = 7) -> dict:
    p = {"objective": cfg.objective, "learning_rate": cfg.learning_rate, "num_leaves": cfg.num_leaves,
         "min_data_in_leaf": 20, "feature_fraction": 0.9, "bagging_fraction": 0.9, "bagging_freq": 1,
         "lambda_l2": 1.0, "verbose": -1, "seed": seed, "deterministic": True, "force_row_wise": True}
    if cfg.objective == "tweedie":
        p["tweedie_variance_power"] = 1.2
    if cfg.num_threads:
        p["num_threads"] = cfg.num_threads
    return p


def direct_max_horizon(cfg) -> int:
    """A DIRECT model is trained (and evaluated) for horizons 1..backtest_horizon_days only."""
    return int(cfg.backtest_horizon_days)


def train(p: Panel, cfg, cancel=None, weights: np.ndarray | None = None) -> tuple[lgb.Booster | None, dict]:
    """weights (1.2.9b, experiments only - the application's training never passes it): optional S x T matrix of the
    panel; each training row gets the weight of its (series, target day). The targets and features stay the real
    values. None = every row weight 1 (exactly the training as before)."""
    if weights is None:
        X, y = direct_training_matrix(p, cfg, direct_max_horizon(cfg)) if is_direct(cfg) else training_matrix(p, cfg)
        w = None
    else:
        if weights.shape != p.Y.shape:
            raise ValueError(f"weights {weights.shape} != panel {p.Y.shape}")
        X, y, ix = (direct_training_matrix(p, cfg, direct_max_horizon(cfg), with_index=True) if is_direct(cfg)
                    else training_matrix(p, cfg, with_index=True))
        w = weights[ix[:, 0], ix[:, 1]].astype(float)
        if not np.all(np.isfinite(w)) or np.any(w < 0):
            raise ValueError("training weights must be finite and >= 0")
    info = {"n_rows": int(len(y)), "n_series": p.n_series,
            "forecast_strategy": "DIRECT" if is_direct(cfg) else "RECURSIVE"}
    if w is not None:
        info["weights"] = {"rows_below_1": int(np.sum(w < 1)), "sum": float(w.sum()), "rows": int(len(w))}
    if len(y) < 100 or np.nansum(y) <= 0:
        info["error"] = "too few training rows"
        return None, info
    if cancel and cancel():
        raise Cancelled()
    names = feature_names(cfg)
    ds = lgb.Dataset(X, y, weight=w, feature_name=names, categorical_feature=["sku_code", "fc_code"], free_raw_data=True)
    booster = lgb.train(lgb_params(cfg), ds, num_boost_round=cfg.num_boost_round)
    imp = booster.feature_importance(importance_type="gain")
    info["feature_importance"] = sorted(({"feature": n, "gain": float(g)} for n, g in zip(names, imp)),
                                        key=lambda r: -r["gain"])
    return booster, info


def classify_series(p: Panel, cfg) -> tuple[np.ndarray, np.ndarray]:
    """Method + fallback rate per series, using history up to the end of `p` (= forecast origin)."""
    d = classification_details(p, cfg)
    return d["methods"], d["rate"]


def classification_details(p: Panel, cfg) -> dict:
    """Every quantity the method-selection rule uses (one source of truth for forecasting AND explanations).

    Rules, evaluated in this order at the forecast origin T:
      1. no order in the last `inactive_days` days and series age >= inactive_days  -> FALLBACK_INACTIVE_ZERO (0)
      2. series age < min_series_history_days                                     -> FALLBACK_NEW_SERIES
         (rate = sum / count of all known days since the series started)
      3. zero-day share over the last 2 x fallback_window_days >= intermittent_zero_share
                                                                                    -> FALLBACK_INTERMITTENT
         (rate = sum / count of known days in the last fallback_window_days)
      4. otherwise                                                                  -> LIGHTGBM
    Known day = not NaN (days before the series started and calendar days without any data are excluded).
    """
    S, T = p.Y.shape
    methods = np.array([METHOD_LGBM] * S, dtype=object)
    reasons = np.array(["LIGHTGBM_ELIGIBLE"] * S, dtype=object)
    rate = np.zeros(S)
    age = T - p.start_idx
    zs_win = cfg.fallback_window_days * 2
    win = p.Y[:, max(0, T - zs_win):]
    with np.errstate(all="ignore"):
        nn = np.sum(~np.isnan(win), axis=1)
        zeros = np.sum(win == 0, axis=1)
        zero_share = np.where(nn > 0, zeros / np.maximum(nn, 1), 1.0)
        recent = p.Y[:, max(0, T - cfg.inactive_days):]
        recent_sum = np.nansum(recent, axis=1)
        sold_recent = recent_sum > 0
        fb_win = p.Y[:, max(0, T - cfg.fallback_window_days):]
        cnt = np.sum(~np.isnan(fb_win), axis=1)
        fb_sum = np.nansum(fb_win, axis=1)
        fb_rate = np.where(cnt > 0, fb_sum / np.maximum(cnt, 1), 0.0)
        hist_cnt = np.sum(~np.isnan(p.Y), axis=1)
        hist_sum = np.nansum(p.Y, axis=1)
        hist_rate = np.where(hist_cnt > 0, hist_sum / np.maximum(hist_cnt, 1), 0.0)
    for s in range(S):
        if not sold_recent[s] and age[s] >= cfg.inactive_days:
            methods[s], rate[s], reasons[s] = FB_INACTIVE, 0.0, "INACTIVE"
        elif age[s] < cfg.min_series_history_days:
            methods[s], rate[s], reasons[s] = FB_NEW, hist_rate[s], "NEW_SERIES"
        elif zero_share[s] >= cfg.intermittent_zero_share:
            methods[s], rate[s], reasons[s] = FB_INTERMITTENT, fb_rate[s], "INTERMITTENT"
    return {"methods": methods, "reasons": reasons, "rate": rate, "age": age, "zero_share_window": zs_win,
            "zero_known_days": nn, "zero_days": zeros, "zero_share": zero_share, "recent_sum": recent_sum,
            "fb_count": cnt, "fb_sum": fb_sum, "fb_rate": fb_rate,
            "hist_count": hist_cnt, "hist_sum": hist_sum, "hist_rate": hist_rate}


def series_meta(p: Panel, cfg, details: dict, s: int) -> dict:
    """JSON-serialisable record of why series s got its method and how a fallback value was computed."""
    rule = {"inactive_days": cfg.inactive_days, "min_series_history_days": cfg.min_series_history_days,
            "intermittent_zero_share": cfg.intermittent_zero_share, "fallback_window_days": cfg.fallback_window_days,
            "zero_share_window_days": details["zero_share_window"]}
    start = int(p.start_idx[s])
    return {"method": str(details["methods"][s]), "reason_code": str(details["reasons"][s]),
            "series_start_date": str(p.dates[start].date()) if start < p.T else None,
            "age_days": int(details["age"][s]), "recent_sum": float(details["recent_sum"][s]),
            "zero_share": float(details["zero_share"][s]), "zero_days": int(details["zero_days"][s]),
            "zero_known_days": int(details["zero_known_days"][s]),
            "fallback_window": {"days": cfg.fallback_window_days, "known_days": int(details["fb_count"][s]),
                                "sum": float(details["fb_sum"][s]), "rate": float(details["fb_rate"][s])},
            "history": {"known_days": int(details["hist_count"][s]), "sum": float(details["hist_sum"][s]),
                        "rate": float(details["hist_rate"][s])},
            "rate_used": float(details["rate"][s]), "rule": rule}


def forecast(p: Panel, booster: lgb.Booster | None, cfg, horizon: int, cancel=None, capture: int | None = None) -> dict:
    """Recursive daily forecast for days T..T+horizon-1 (T = first day after the panel).

    capture: optional series index; the exact feature row fed to the model for that series at every step is
    returned in "captured" (used by explanations - nothing is approximated)."""
    S, T = p.Y.shape
    methods, rate = classify_series(p, cfg)
    if booster is None:
        methods = np.where(methods == METHOD_LGBM, FB_MODEL_UNAVAILABLE, methods)
        with np.errstate(all="ignore"):
            w = p.Y[:, max(0, T - cfg.fallback_window_days):]
            cnt = np.sum(~np.isnan(w), axis=1)
            mr = np.where(cnt > 0, np.nansum(w, axis=1) / np.maximum(cnt, 1), 0.0)
        rate = np.where(methods == FB_MODEL_UNAVAILABLE, mr, rate)
    if is_direct(cfg):
        return _forecast_direct(p, booster, cfg, horizon, methods, rate, cancel, capture)
    dates = p.dates.append(pd.date_range(p.dates[-1] + pd.Timedelta(days=1), periods=horizon, freq="D"))
    Y = np.concatenate([p.Y, np.full((S, horizon), np.nan)], axis=1)
    # unknown future: price held at last known value; no planned promotion information -> 0
    price = np.concatenate([p.price, np.repeat(p.price[:, -1:], horizon, axis=1)], axis=1)
    disc = np.concatenate([p.disc, np.repeat(p.disc[:, -1:], horizon, axis=1)], axis=1)
    promo = np.concatenate([p.promo, np.zeros((S, horizon))], axis=1)
    sc, fcc = static_codes(p)
    lgbm_mask = methods == METHOD_LGBM
    yhat = np.zeros((S, horizon))
    captured = []
    for h in range(horizon):
        if cancel and h % 10 == 0 and cancel():
            raise Cancelled()
        t = T + h
        pred = np.where(lgbm_mask, 0.0, rate)
        if booster is not None and lgbm_mask.any():
            X = features_at(p, Y, price, disc, promo, dates, t, cfg, sc, fcc)
            pred[lgbm_mask] = booster.predict(X[lgbm_mask])
            if capture is not None:
                captured.append(X[capture].copy())
        pred = np.clip(pred, 0, None)
        yhat[:, h] = pred
        Y[:, t] = pred
    return {"dates": dates[T:], "yhat": yhat, "methods": methods, "captured": captured}


def _forecast_direct(p: Panel, booster, cfg, horizon: int, methods, rate, cancel=None, capture=None) -> dict:
    """DIRECT: one prediction per horizon day from the features at the origin T (data < T only) + the target-day
    calendar + h. No forecast is fed back into any feature. Fallback series keep their constant rate."""
    S, T = p.Y.shape
    if horizon > direct_max_horizon(cfg):
        raise ValueError(f"DIRECT_HORIZON_EXCEEDS_TRAINING: {horizon} > {direct_max_horizon(cfg)} days")
    future = pd.date_range(p.dates[-1] + pd.Timedelta(days=1), periods=horizon, freq="D")
    sc, fcc = static_codes(p)
    lgbm_mask = methods == METHOD_LGBM
    Xb = (origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, T, cfg, sc, fcc)
          if booster is not None and lgbm_mask.any() else None)
    yhat = np.zeros((S, horizon))
    captured = []
    for h in range(horizon):
        if cancel and h % 10 == 0 and cancel():
            raise Cancelled()
        pred = np.where(lgbm_mask, 0.0, rate)
        if Xb is not None:
            extra = np.array(direct_extra(cfg, future[h], h + 1), dtype=np.float32)
            pred[lgbm_mask] = booster.predict(np.hstack([Xb[lgbm_mask], np.tile(extra, (int(lgbm_mask.sum()), 1))]))
            if capture is not None:
                captured.append(np.hstack([Xb[capture], extra]))
        yhat[:, h] = np.clip(pred, 0, None)
    return {"dates": future, "yhat": yhat, "methods": methods, "captured": captured}


def _baseline_window(p: Panel, window: int) -> tuple[np.ndarray, np.ndarray]:
    """(known days, sum) of every series over the last `window` days of the panel (NaN = unknown day, not 0)."""
    T = p.Y.shape[1]
    with np.errstate(all="ignore"):
        w = p.Y[:, max(0, T - window):]
        return np.sum(~np.isnan(w), axis=1), np.nansum(w, axis=1)


def baseline_forecast(p: Panel, horizon: int, window: int = BASELINE_WINDOW_DAYS) -> np.ndarray:
    cnt, tot = _baseline_window(p, window)
    with np.errstate(all="ignore"):
        r = np.where(cnt > 0, tot / np.maximum(cnt, 1), 0.0)
    return np.repeat(r[:, None], horizon, axis=1)


def baseline_run(p: Panel, horizon: int) -> dict:
    """The baseline candidate as a forecast: for every series the mean of the known days in the last
    BASELINE_WINDOW_DAYS days of the panel, the same value on every forecast day (exactly what backtest() scores as
    'baseline'; clipped at 0 like every published value). Same shape as forecast()."""
    cnt, tot = _baseline_window(p, BASELINE_WINDOW_DAYS)
    return {"dates": pd.date_range(p.dates[-1] + pd.Timedelta(days=1), periods=horizon, freq="D"),
            "yhat": np.clip(baseline_forecast(p, horizon), 0, None),
            "methods": np.array([METHOD_BASELINE] * p.n_series, dtype=object), "captured": [],
            "kind": "BASELINE", "window_count": cnt, "window_sum": tot}


def baseline_series_meta(p: Panel, fc: dict, s: int) -> dict:
    """series_meta() for a baseline run: the window, its known days and sum, and the resulting daily value."""
    start = int(p.start_idx[s])
    cnt, tot = int(fc["window_count"][s]), float(fc["window_sum"][s])
    rate = tot / cnt if cnt else 0.0
    return {"method": METHOD_BASELINE, "reason_code": "BASELINE_SELECTED",
            "series_start_date": str(p.dates[start].date()) if start < p.T else None, "age_days": int(p.T - start),
            "fallback_window": {"days": BASELINE_WINDOW_DAYS, "known_days": cnt, "sum": tot, "rate": rate},
            "rate_used": rate, "rule": {"baseline_window_days": BASELINE_WINDOW_DAYS}}


# 1.2.9: backtest accuracy is also reported per group (evaluation only - nothing is excluded, clipped or re-weighted)
PERIOD_TOTAL_DAYS = (7, 15, 30)
HORIZON_WINDOWS = ((1, 7), (8, 15), (16, 30), (31, 90))


def _codes(labels, names) -> np.ndarray:
    idx = {n: i for i, n in enumerate(names)}
    return np.array([idx[x] for x in labels], dtype=np.int8)


def _collect_segments(seg: dict, totals: dict, train_p: Panel, actual, yhat, base, valid) -> None:
    S, H = actual.shape
    cut = train_p.T
    group = _codes(demand_patterns.classify(train_p.Y, cut)["group"], demand_patterns.GROUPS)
    tier = _codes(demand_patterns.volume_tier(train_p.Y, cut), demand_patterns.TIERS)
    spike = demand_patterns.spike_flags(actual, demand_patterns.spike_thresholds(train_p.Y, cut))
    seg["group"].append(np.repeat(group[:, None], H, axis=1)[valid])
    seg["tier"].append(np.repeat(tier[:, None], H, axis=1)[valid])
    seg["spike"].append(spike[valid])
    seg["day"].append(np.tile(np.arange(1, H + 1), (S, 1))[valid])
    for n, acc in totals.items():
        v = valid[:, :n]
        has = v.any(axis=1)      # series with at least one known day among the first n days of the fold
        acc.append(np.stack([np.where(v, x[:, :n], 0.0).sum(axis=1)[has] for x in (actual, yhat, base)]))


def _segment_metrics(seg: dict, totals: dict, A, Fc, B, mape_min_actual: float) -> dict:
    G, V, K, D = (np.concatenate(seg[k]) for k in ("group", "tier", "spike", "day"))

    def pair(mask):
        return {"model": metrics.compute(A[mask], Fc[mask], mape_min_actual),
                "baseline": metrics.compute(A[mask], B[mask], mape_min_actual)}
    out = {"by_pattern": {g: pair(G == i) for i, g in enumerate(demand_patterns.GROUPS) if (G == i).any()},
           "by_volume": {t: pair(V == i) for i, t in enumerate(demand_patterns.TIERS) if (V == i).any()},
           "by_spike_day": {"SPIKE_DAY": pair(K), "OTHER_DAY": pair(~K)},
           "by_horizon_days": {f"{lo}-{hi}": pair((D >= lo) & (D <= hi)) for lo, hi in HORIZON_WINDOWS
                               if ((D >= lo) & (D <= hi)).any()},
           # WAPE of each series' TOTAL over the first n days of a fold (known days only): the error of a 7 / 15 / 30-day
           # order quantity, where day-to-day errors can cancel out
           "period_totals": {},
           "rules": {**demand_patterns.DEFAULTS, "adi_cut": demand_patterns.ADI_CUT, "cv2_cut": demand_patterns.CV2_CUT}}
    for n, acc in totals.items():
        if acc:
            X = np.concatenate(acc, axis=1)
            out["period_totals"][str(n)] = {"model": metrics.compute(X[0], X[1], mape_min_actual),
                                            "baseline": metrics.compute(X[0], X[2], mape_min_actual)}
    return out


def _segments_or_note(seg, totals, A, Fc, B, mape_min_actual) -> dict:
    if seg is None:
        return {"error": "SEGMENTS_NOT_COMPUTED"}
    try:
        return _segment_metrics(seg, totals, A, Fc, B, mape_min_actual)
    except Exception:  # noqa: BLE001
        log.warning("backtest segments not computed", exc_info=True)
        return {"error": "SEGMENTS_NOT_COMPUTED"}


def backtest(p: Panel, cfg, mape_min_actual: float = 1.0, cancel=None, collect: bool = False) -> dict:
    """Walk-forward: for each fold, train on days < origin only, forecast H days, score vs actuals.

    collect=True additionally returns every evaluation point (fold, date, series, day-of-fold, method, actual,
    forecast, baseline) - the exact pairs the metrics are computed from. It does not change any result."""
    H, F, step = cfg.backtest_horizon_days, cfg.backtest_folds, cfg.backtest_step_days
    T = p.T
    folds, all_a, all_f, all_b, all_m = [], [], [], [], []
    seg: dict[str, list] = {"group": [], "tier": [], "spike": [], "day": []}
    totals: dict[int, list] = {n: [] for n in PERIOD_TOTAL_DAYS if n <= H}
    notes = []
    points: list[dict] = []
    for k in range(F):
        origin = T - H - (F - 1 - k) * step
        if origin < cfg.min_total_history_days:
            notes.append({"code": "FOLD_SKIPPED_SHORT_HISTORY", "fold": k + 1, "origin_index": int(origin)})
            continue
        if cancel and cancel():
            raise Cancelled()
        train_p = p.truncate(origin)
        booster, _ = train(train_p, cfg, cancel)
        fc = forecast(train_p, booster, cfg, H, cancel)
        actual = p.Y[:, origin:origin + H]
        base = baseline_forecast(train_p, H)
        valid = ~np.isnan(actual)
        a, f, b = actual[valid], fc["yhat"][valid], base[valid]
        meth = np.repeat(fc["methods"][:, None], H, axis=1)[valid]
        if collect:
            si, di = np.nonzero(valid)
            for s_, d_, a_, f_, b_ in zip(si, di, a, f, b):
                points.append({"fold": k + 1, "origin": str(p.dates[origin].date()),
                               "date": str(p.dates[origin + d_].date()), "sku_id": p.keys[s_][0], "fc_id": p.keys[s_][1],
                               "day_of_fold": int(d_) + 1, "method": str(fc["methods"][s_]), "actual": float(a_),
                               "forecast": float(f_), "baseline": float(b_)})
        m = metrics.compute(a, f, mape_min_actual)
        mb = metrics.compute(a, b, mape_min_actual)
        folds.append({"fold": k + 1, "origin": str(p.dates[origin].date()),
                      "end": str(p.dates[min(origin + H, T) - 1].date()), "train_days": int(origin),
                      "metrics": m, "baseline_metrics": mb})
        all_a.append(a); all_f.append(f); all_b.append(b); all_m.append(meth)
        # 1.2.9: the same points per demand-pattern group / volume tier / spike day / horizon day (groups from the
        # history before the origin only), and per-series totals of the first 7 / 15 / 30 days. Evaluation only: a
        # failure here is logged and never stops the backtest or the training
        if seg is not None:
            try:
                _collect_segments(seg, totals, train_p, actual, fc["yhat"], base, valid)
            except Exception:  # noqa: BLE001
                log.warning("backtest segments not computed", exc_info=True)
                seg = None
    if not folds:
        return {"folds": [], "metrics": metrics.compute([], []), "baseline_metrics": metrics.compute([], []),
                "by_method": {}, "reliable": False, "notes": notes + [{"code": "NO_VALID_FOLD"}]}
    A, Fc, B, M = (np.concatenate(x) for x in (all_a, all_f, all_b, all_m))
    by_method = {str(mt): metrics.compute(A[M == mt], Fc[M == mt], mape_min_actual) for mt in np.unique(M)}
    pooled = metrics.compute(A, Fc, mape_min_actual)
    reliable = len(folds) >= min(2, F) and pooled["wape"] is not None
    if len(folds) < F:
        notes.append({"code": "FEWER_FOLDS_THAN_CONFIGURED", "folds": len(folds), "configured": F})
    # calendar span actually evaluated (first evaluated day .. last evaluated day), reported as measured - a 12-month
    # claim is only possible when the data really allows 12 months of folds
    first_day, last_day = pd.Timestamp(folds[0]["origin"]), pd.Timestamp(folds[-1]["end"])
    span = int((last_day - first_day).days) + 1
    if span < SIX_MONTHS_DAYS:
        notes.append({"code": "BACKTEST_SPAN_BELOW_6_MONTHS", "span_days": span, "folds": len(folds),
                      "history_days": int(T), "min_train_days": int(cfg.min_total_history_days)})
    out = {"folds": folds, "metrics": pooled, "baseline_metrics": metrics.compute(A, B, mape_min_actual),
           "by_method": by_method, "reliable": bool(reliable), "notes": notes,
           "segments": _segments_or_note(seg, totals, A, Fc, B, mape_min_actual),
           "config": {"horizon_days": H, "folds": F, "step_days": step, "folds_evaluated": len(folds),
                      "span_days": span, "first_day": str(first_day.date()), "last_day": str(last_day.date()),
                      "history_days": int(T), "min_train_days": int(cfg.min_total_history_days)}}
    if collect:
        out["points"] = points
    return out
