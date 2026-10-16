"""Isolated model experiment 16/10/2026 - offline walk-forward comparison on the real BigQuery data.

Safety: reads ONLY an isolated copy of the database (EXP_DB, opened mode=ro, must be in the session scratchpad);
writes ONLY into this folder (results) and EXP_POINTS (per-point arrays, scratchpad). It imports the app's pure ML
functions (features / model / metrics) and never touches the app's database layer, settings, models or schedules.

Fold structure, target, features, fallback rules, baseline and metrics are the production ones (app.ml.model.backtest):
for every fold the model is trained on days < origin only and forecasts the 30 days from the origin. Variants change
only what their spec says. Usage:
    harness.py list
    harness.py run <name> [<name> ...] [--threads N]
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

REPO = Path(r"D:\Buymed\Lightgbm AI")
sys.path.insert(0, str(REPO / "backend"))
from app import settings_service as ss                                          # noqa: E402
from app.ml import metrics, model                                               # noqa: E402
from app.ml.features import _nanmean, build_panel, feature_names, features_at, static_codes  # noqa: E402

EXP = Path(__file__).resolve().parent
DB = Path(os.environ["EXP_DB"]).resolve()
POINTS = Path(os.environ["EXP_POINTS"]).resolve()
assert "scratchpad" in str(DB).lower() and DB != (REPO / "data" / "runtime" / "db" / "app.db").resolve(), DB
TRN = "TRN-20261016095451-697A11"                     # the production run rejected on 16/10 (reference)
SCOPE = "BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm"
METHODS = [model.METHOD_LGBM, model.FB_NEW, model.FB_INTERMITTENT, model.FB_INACTIVE, model.FB_MODEL_UNAVAILABLE]
SEGMENTS = ["LGBM_ZS_LT50", "LGBM_ZS_50_80", "INTERMITTENT", "NEW_SERIES", "INACTIVE"]
CAL_NAMES = ["dow", "dom", "month", "weekofyear", "is_weekend", "days_to_month_end"]
TREND_NAMES = ["ser_ratio_7_28", "ser_ratio_28_56", "glob_ratio_7_28", "glob_ratio_28_84"]
SEED = 7

# Fixed BEFORE any variant was run; each has one hypothesis (see experiment_config.json). Window = training ROWS from
# the last N days before the origin; features keep using the full history before the origin (never after).
SPECS: dict[str, dict] = {
    "R0_production": {"group": "reproduction", "app_path": True,
                      "hypothesis": "exact production configuration (app.ml.model.train / forecast)"},
    "W30": {"group": "window", "window": 30, "hypothesis": "only the newest regime (after the drop) is learned"},
    "W60": {"group": "window", "window": 60, "hypothesis": "recent regime, more rows"},
    "W90": {"group": "window", "window": 90, "hypothesis": "about one quarter of recent history"},
    "W180": {"group": "window", "window": 180, "hypothesis": "half a year"},
    "L1_no_sku": {"group": "lgbm", "drop_sku": True,
                  "hypothesis": "sku_code categorical with ~9.7k levels overfits SKU levels of the past"},
    "L2_regularized": {"group": "lgbm", "params": {"num_leaves": 15, "min_data_in_leaf": 200, "lambda_l2": 10.0,
                                                    "feature_fraction": 0.7, "bagging_fraction": 0.7},
                       "hypothesis": "simpler, more regularised trees generalise better across the level shift"},
    "L3_early_stop": {"group": "lgbm", "early_stopping": {"val_days": 30, "max_rounds": 2000, "patience": 50},
                      "hypothesis": "300 rounds is arbitrary; rounds chosen on the last 30 days BEFORE the origin "
                                    "(metric l1), then refit on the whole training window"},
    "L4_tweedie15": {"group": "lgbm", "params": {"tweedie_variance_power": 1.5},
                     "hypothesis": "heavier zero mass suits intermittent daily demand"},
    "L5_l1": {"group": "lgbm", "cfg": {"objective": "regression_l1"},
              "hypothesis": "WAPE numerator = absolute error: the median objective optimises it directly"},
    "L6_trend": {"group": "lgbm", "trend": True,
                 "hypothesis": "explicit recent-trend ratios (series and whole scope), from data < t only"},
    "L7_direct": {"group": "lgbm", "direct": {"origins": 12, "step": 7},
                  "hypothesis": "recursive feedback of predicted means into lags/zero-share/days-since-sale inflates "
                                "forecasts; a direct multi-horizon model (features at the origin + horizon) avoids it"},
    "L8_fallback14": {"group": "lgbm", "cfg": {"fallback_window_days": 14},
                      "hypothesis": "fallback rates (intermittent / no model) adapt faster with a 14-day window"},
    # added 16/10 18:10 (second session, before any variant was run): recency weighting requested by the user
    "L9_recency60": {"group": "lgbm", "recency": {"half_life_days": 60},
                     "hypothesis": "all history is kept but older training rows count less (weight halves every 60 "
                                   "days before the origin), so the model follows the current level"},
    "C1_w90_nosku_reg": {"group": "combined", "window": 90, "drop_sku": True,
                         "params": {"num_leaves": 15, "min_data_in_leaf": 200, "lambda_l2": 10.0,
                                    "feature_fraction": 0.7, "bagging_fraction": 0.7},
                         "hypothesis": "recent regime + no SKU identity + regularisation"},
    "C2_direct_nosku_reg": {"group": "combined", "direct": {"origins": 12, "step": 7}, "drop_sku": True,
                            "params": {"num_leaves": 15, "min_data_in_leaf": 200, "lambda_l2": 10.0,
                                       "feature_fraction": 0.7, "bagging_fraction": 0.7},
                            "hypothesis": "direct strategy + no SKU identity + regularisation"},
    "C3_w90_nosku_trend_es": {"group": "combined", "window": 90, "drop_sku": True, "trend": True,
                              "early_stopping": {"val_days": 30, "max_rounds": 2000, "patience": 50},
                              "hypothesis": "recent regime + no SKU identity + trend features + early stopping"},
}


def load():
    c = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)
    r = c.execute("SELECT feature_config_json, train_start, train_end, metrics_json, baseline_metrics_json "
                  "FROM training_runs WHERE id=?", (TRN,)).fetchone()
    fc = json.loads(r[0])
    cfg = ss.ModelSettings(**fc["config"])
    assert feature_names(cfg) == fc["features"], "resolved feature list differs from the production run"
    d = pd.read_sql_query("SELECT order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, avg_discount_rate, "
                          "promo_share, voucher_share FROM demand_daily WHERE scope_key=? AND order_date>=? AND "
                          "order_date<=?", c, params=[SCOPE, r[1], r[2]])
    c.close()
    p = build_panel(d, max_days=cfg.max_train_days)              # exactly as pipeline.train_and_publish
    return cfg, p, json.loads(r[3]), json.loads(r[4])


def origins(cfg, T):
    H, F, step = cfg.backtest_horizon_days, cfg.backtest_folds, cfg.backtest_step_days
    return [(k + 1, T - H - (F - 1 - k) * step) for k in range(F) if T - H - (F - 1 - k) * step >= cfg.min_total_history_days]


# ------------------------------------------------------------------ features of the variants
def trend_cols(Y, t):
    hist = Y[:, :t]
    eps = 0.1
    r7, r28, r56 = (_nanmean(hist[:, max(0, t - w):t]) for w in (7, 28, 56))
    with np.errstate(all="ignore"):
        tot = np.nansum(hist, axis=0)                              # whole-scope daily total (known values only)
        g7, g28, g84 = (np.nanmean(tot[max(0, t - w):t]) if t > 0 else np.nan for w in (7, 28, 84))
        S = Y.shape[0]
        return [(r7 + eps) / (r28 + eps), (r28 + eps) / (r56 + eps),
                np.full(S, g7 / g28 if g28 else np.nan), np.full(S, g28 / g84 if g84 else np.nan)]


def feats(p, Y, price, disc, promo, dates, t, cfg, sc, fcc, spec):
    X = features_at(p, Y, price, disc, promo, dates, t, cfg, sc, fcc)
    if spec.get("trend"):
        X = np.column_stack([X] + trend_cols(Y, t)).astype(np.float32)
    return X[:, 1:] if spec.get("drop_sku") else X


def names_of(cfg, spec, direct=False):
    n = feature_names(cfg) + (TREND_NAMES if spec.get("trend") else [])
    if direct:
        n = [x for x in n if x not in CAL_NAMES] + CAL_NAMES + ["horizon"]
    return n[1:] if spec.get("drop_sku") else n


def cats_of(names):
    return [c for c in ("sku_code", "fc_code") if c in names]


def cal_row(d):
    return [float(d.dayofweek), float(d.day), float(d.month), float(d.isocalendar()[1]),
            1.0 if d.dayofweek >= 5 else 0.0, float(d.days_in_month - d.day)]


# ------------------------------------------------------------------ training
def params_of(cfg, spec, threads):
    prm = model.lgb_params(cfg, seed=SEED)
    prm.update(spec.get("params", {}))
    if threads:
        prm["num_threads"] = threads
    return prm


def rec_matrix(p, cfg, spec):
    sc, fcc = static_codes(p)
    S, T = p.Y.shape
    t_from = max(7, T - max(1, 4_000_000 // max(S, 1)))          # same cap as features.training_matrix
    if spec.get("window"):
        t_from = max(t_from, T - spec["window"])
    Xs, ys, ts = [], [], []
    for t in range(t_from, T):
        target = p.Y[:, t]
        ok = ~np.isnan(target) & (t > p.start_idx)
        if ok.any():
            X = feats(p, p.Y, p.price, p.disc, p.promo, p.dates, t, cfg, sc, fcc, spec)
            Xs.append(X[ok]); ys.append(target[ok]); ts.append(np.full(int(ok.sum()), t, dtype=np.int32))
    return np.vstack(Xs), np.concatenate(ys), np.concatenate(ts)


def direct_matrix(p, cfg, spec, H):
    sc, fcc = static_codes(p)
    S, T = p.Y.shape
    nc = cfg.model_copy(update={"feature_calendar": False})
    d = spec["direct"]
    Xs, ys, ts = [], [], []
    for j in range(1, d["origins"] + 1):
        t0 = T - j * d["step"]
        if t0 < 7 or (spec.get("window") and t0 < T - spec["window"]):
            break
        Xb = feats(p, p.Y, p.price, p.disc, p.promo, p.dates, t0, nc, sc, fcc, spec)
        for h in range(1, H + 1):
            td = t0 + h - 1
            if td >= T:
                break
            target = p.Y[:, td]
            ok = ~np.isnan(target) & (t0 > p.start_idx)
            if ok.any():
                extra = np.tile(np.array(cal_row(p.dates[td]) + [float(h)], dtype=np.float32), (int(ok.sum()), 1))
                Xs.append(np.hstack([Xb[ok], extra])); ys.append(target[ok])
                ts.append(np.full(int(ok.sum()), td, dtype=np.int32))
    return np.vstack(Xs), np.concatenate(ys), np.concatenate(ts)


def train_variant(tp, cfg, spec, H, threads):
    direct = "direct" in spec
    X, y, ts = direct_matrix(tp, cfg, spec, H) if direct else rec_matrix(tp, cfg, spec)
    info = {"n_rows": int(len(y))}
    if len(y) < 100 or np.nansum(y) <= 0:
        return None, info
    names = names_of(cfg, spec, direct)
    assert X.shape[1] == len(names), (X.shape, len(names))
    prm = params_of(cfg, spec, threads)
    rounds = cfg.num_boost_round
    rc = spec.get("recency")
    w = 0.5 ** ((tp.T - 1 - ts) / rc["half_life_days"]) if rc else None   # age measured from the origin, past only
    es = spec.get("early_stopping")
    if es:
        vm = ts >= tp.T - es["val_days"]                          # inner validation: the last days BEFORE the origin
        dtr = lgb.Dataset(X[~vm], y[~vm], weight=None if w is None else w[~vm], feature_name=names,
                          categorical_feature=cats_of(names), free_raw_data=False)
        dva = lgb.Dataset(X[vm], y[vm], weight=None if w is None else w[vm], reference=dtr)
        b = lgb.train({**prm, "metric": "l1"}, dtr, num_boost_round=es["max_rounds"], valid_sets=[dva],
                      callbacks=[lgb.early_stopping(es["patience"], verbose=False)])
        rounds = int(b.best_iteration or es["max_rounds"])
        info["best_iteration"] = rounds
    ds = lgb.Dataset(X, y, weight=w, feature_name=names, categorical_feature=cats_of(names), free_raw_data=True)
    booster = lgb.train(prm, ds, num_boost_round=rounds)
    info["rounds"] = rounds
    return booster, info


# ------------------------------------------------------------------ forecasting (same fallback policy as production)
def _fallback(p, booster, cfg):
    S, T = p.Y.shape
    methods, rate = model.classify_series(p, cfg)
    if booster is None:
        methods = np.where(methods == model.METHOD_LGBM, model.FB_MODEL_UNAVAILABLE, methods)
        with np.errstate(all="ignore"):
            w = p.Y[:, max(0, T - cfg.fallback_window_days):]
            cnt = np.sum(~np.isnan(w), axis=1)
            mr = np.where(cnt > 0, np.nansum(w, axis=1) / np.maximum(cnt, 1), 0.0)
        rate = np.where(methods == model.FB_MODEL_UNAVAILABLE, mr, rate)
    return methods, rate


def forecast_variant(p, booster, cfg, spec, H):
    S, T = p.Y.shape
    methods, rate = _fallback(p, booster, cfg)
    lg = methods == model.METHOD_LGBM
    yhat = np.zeros((S, H))
    sc, fcc = static_codes(p)
    future = pd.date_range(p.dates[-1] + pd.Timedelta(days=1), periods=H, freq="D")
    if "direct" in spec:
        nc = cfg.model_copy(update={"feature_calendar": False})
        Xb = feats(p, p.Y, p.price, p.disc, p.promo, p.dates, T, nc, sc, fcc, spec) if booster is not None else None
        for h in range(H):
            pred = np.where(lg, 0.0, rate)
            if booster is not None and lg.any():
                extra = np.tile(np.array(cal_row(future[h]) + [float(h + 1)], dtype=np.float32), (int(lg.sum()), 1))
                pred[lg] = booster.predict(np.hstack([Xb[lg], extra]))
            yhat[:, h] = np.clip(pred, 0, None)
        return {"yhat": yhat, "methods": methods}
    dates = p.dates.append(future)
    Y = np.concatenate([p.Y, np.full((S, H), np.nan)], axis=1)
    price = np.concatenate([p.price, np.repeat(p.price[:, -1:], H, axis=1)], axis=1)
    disc = np.concatenate([p.disc, np.repeat(p.disc[:, -1:], H, axis=1)], axis=1)
    promo = np.concatenate([p.promo, np.zeros((S, H))], axis=1)
    for h in range(H):
        t = T + h
        pred = np.where(lg, 0.0, rate)
        if booster is not None and lg.any():
            X = feats(p, Y, price, disc, promo, dates, t, cfg, sc, fcc, spec)
            pred[lg] = booster.predict(X[lg])
        pred = np.clip(pred, 0, None)
        yhat[:, h] = pred
        Y[:, t] = pred
    return {"yhat": yhat, "methods": methods}


def segments(tp, cfg):
    d = model.classification_details(tp, cfg)
    seg = np.full(tp.n_series, 0, dtype=np.int8)
    m, zs = d["methods"], d["zero_share"]
    seg[(m == model.METHOD_LGBM) & (zs >= 0.5)] = 1
    seg[m == model.FB_INTERMITTENT] = 2
    seg[m == model.FB_NEW] = 3
    seg[m == model.FB_INACTIVE] = 4
    return seg


# ------------------------------------------------------------------ one configuration
def run(name, cfg0, p, threads):
    spec = SPECS[name]
    cfg = cfg0.model_copy(update=spec.get("cfg", {}))
    H = cfg0.backtest_horizon_days
    out = {"name": name, "spec": spec, "folds": [], "seed": SEED, "threads": threads or "all"}
    A, Fc, B, FO, SI, DI, MI, SG = [], [], [], [], [], [], [], []
    t_all = time.time()
    for k, origin in origins(cfg0, p.T):
        t0 = time.time()
        tp = p.truncate(origin)
        if spec.get("app_path"):
            prod = cfg if not threads else cfg.model_copy(update={"num_threads": threads})
            booster, info = model.train(tp, prod)
            fc = model.forecast(tp, booster, prod, H)
            info = {"n_rows": info["n_rows"], "rounds": cfg.num_boost_round}
        else:
            booster, info = train_variant(tp, cfg, spec, H, threads)
            fc = forecast_variant(tp, booster, cfg, spec, H)
        actual = p.Y[:, origin:origin + H]
        base = model.baseline_forecast(tp, H)                    # production baseline, unchanged
        valid = ~np.isnan(actual)
        si, di = np.nonzero(valid)
        a, f, b = actual[valid], fc["yhat"][valid], base[valid]
        mi = np.array([METHODS.index(str(x)) for x in fc["methods"]], dtype=np.int8)[si]
        A.append(a); Fc.append(f); B.append(b); FO.append(np.full(len(a), k, dtype=np.int8))
        SI.append(si.astype(np.int32)); DI.append(di.astype(np.int8)); MI.append(mi)
        SG.append(segments(tp, cfg0)[si])                        # production segmentation (same for every variant)
        out["folds"].append({"fold": k, "origin": str(p.dates[origin].date()),
                             "end": str(p.dates[min(origin + H, p.T) - 1].date()), "train_days": int(origin),
                             "metrics": metrics.compute(a, f), "baseline_metrics": metrics.compute(a, b),
                             "seconds": round(time.time() - t0, 1), **info})
        print(f"  {name} fold {k} {out['folds'][-1]['origin']} wape {out['folds'][-1]['metrics']['wape']:.4f} "
              f"bias {out['folds'][-1]['metrics']['bias']:+.4f} rows {info.get('n_rows')} rounds {info.get('rounds')} "
              f"{out['folds'][-1]['seconds']}s", flush=True)
    a, f, b = (np.concatenate(x) for x in (A, Fc, B))
    out["pooled"] = metrics.compute(a, f)
    out["baseline_pooled"] = metrics.compute(a, b)
    out["seconds"] = round(time.time() - t_all, 1)
    np.savez_compressed(POINTS / f"{name}.npz", forecast=f.astype(np.float32), method=np.concatenate(MI))
    if name == "R0_production":
        np.savez_compressed(POINTS / "_keys.npz", fold=np.concatenate(FO), s=np.concatenate(SI), d=np.concatenate(DI),
                            actual=a.astype(np.float32), baseline=b.astype(np.float32), seg=np.concatenate(SG),
                            fc=np.array([1 if p.keys[i][1] == "HN" else 0 for i in range(p.n_series)], dtype=np.int8),
                            dates=np.array([str(x.date()) for x in p.dates]))
    (EXP / "runs").mkdir(exist_ok=True)
    (EXP / "runs" / f"{name}.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(f"{name}: WAPE {out['pooled']['wape']:.6f} bias {out['pooled']['bias']:+.6f} | baseline "
          f"{out['baseline_pooled']['wape']:.6f} {out['baseline_pooled']['bias']:+.6f} | points {out['pooled']['n_points']} "
          f"| {out['seconds']}s", flush=True)
    return out


if __name__ == "__main__":
    if sys.argv[1] == "list":
        (EXP / "experiment_config.json").write_text(json.dumps(
            {"created": "2026-10-16", "reference_training_run": TRN, "scope": SCOPE, "seed": SEED,
             "fold_structure": "production (12 x 30 days, step 30, min 56 days of history -> 7 folds evaluated)",
             "window_meaning": "training rows from the last N days before each origin; features use history < t only",
             "selection_protocol": "per fold k: the configuration with the lowest pooled WAPE over the folds BEFORE k "
                                   "(their test days all precede origin k); fold 1 evaluated uses R0_production",
             "specs": SPECS}, indent=1), encoding="utf-8")
        print("\n".join(f"{k}: {v['hypothesis']}" for k, v in SPECS.items()))
        sys.exit(0)
    threads = 0
    args = sys.argv[2:]
    if "--threads" in args:
        i = args.index("--threads")
        threads = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    t = time.time()
    cfg0, p, stored, stored_base = load()
    print(f"panel {p.dates[0].date()}..{p.dates[-1].date()} series {p.n_series} T {p.T} loaded in "
          f"{time.time() - t:.0f}s; stored production WAPE {stored['wape']} bias {stored['bias']}", flush=True)
    for n in args:
        run(n, cfg0, p, threads)
