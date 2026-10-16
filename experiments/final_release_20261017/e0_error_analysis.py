"""E0 - error analysis of the release model (DIRECT, price group ON) vs demand only, on an ISOLATED DB copy that holds
the real BigQuery data with prices (01/01-15/10/2026). Nothing new is tuned or selected here.

Same walk-forward as the production backtest (model.backtest) and price_experiment.py: 7 evaluated folds of 30 days,
step 30, each model trained only on days before its origin. Every evaluation point is kept and grouped by:
  FC, SKU, horizon (day 1..30 and 1-7 / 8-15 / 16-30), target month, forecast method (LightGBM / fallback),
  ex-ante groups computed at the origin from data BEFORE it (demand class, volume class, price vs its 28-day mean,
  how often the price changed in the 28 days before the origin), and one EX-POST, descriptive-only group (price on the
  target day vs the last price known at the origin; never a model input).
Analysis convention (not a business threshold): a group is "enough sample" with >= 5,000 points and >= 5,000 units.

Usage (DF_DATA_DIR = the isolated copy):  e0_error_analysis.py <out dir for results json> <points npz path>"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ISO = Path(os.environ["DF_DATA_DIR"]).resolve()
assert "scratchpad" in str(ISO).lower() and "lightgbm ai" not in str(ISO).lower(), ISO
sys.path.insert(0, r"D:\Buymed\Lightgbm AI\backend")
from app import db                                           # noqa: E402
from app import settings_service as ss                       # noqa: E402
from app.data.demand import bigquery_scope_key, load_demand  # noqa: E402
from app.ml import feature_registry as registry, model       # noqa: E402
from app.ml.features import build_panel, feature_names       # noqa: E402

OUT = Path(sys.argv[1]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
NPZ = Path(sys.argv[2]).resolve()
START, END = "2026-01-01", "2026-10-15"
MIN_N, MIN_UNITS = 5000, 5000
EXPECTED = {"demand_price": 0.808117, "demand_only": 0.805953}       # price_backtest.json (17/10/2026 00:59)

sk = bigquery_scope_key(ss.get("bigquery"))
base = ss.ModelSettings(**{**ss.get("model").model_dump(), "forecast_strategy": "DIRECT", "num_threads": 0})
with db.read() as c:
    cov = registry.coverage(c, sk)
t_load = time.time()
demand = load_demand(sk, start=START, end=END)
if os.environ.get("E0_SMOKE"):          # code check only: 200 SKUs, 10 boosting rounds; results are NOT E0 results
    demand = demand[demand["sku_id"].isin(sorted(demand["sku_id"].unique())[:200])]
    base = base.model_copy(update={"num_boost_round": 10})
panel = build_panel(demand, max_days=base.max_train_days)
H, S, T = base.backtest_horizon_days, panel.n_series, panel.T
dates = panel.dates
sku_of = np.array([k[0] for k in panel.keys])
fc_of = np.array([k[1] for k in panel.keys])
print("panel", dates[0].date(), dates[-1].date(), S, "series", round(time.time() - t_load), "s", flush=True)


def at_origin(o: int) -> dict:
    """Per-series descriptors at origin o from columns [0, o) only."""
    with np.errstate(all="ignore"):
        pr = panel.price[:, max(0, o - 28):o]
        pm = np.nanmean(pr, axis=1)                          # same 28-day mean as the feature price_rel_28
        rel = panel.price[:, o - 1] / pm
        ratio = pr[:, 1:] / pr[:, :-1]
        known = np.sum(~np.isnan(ratio), axis=1)
        chg = np.where(known > 0, np.sum(np.abs(ratio - 1) > 0.01, axis=1) / np.maximum(known, 1), np.nan)
        y28 = panel.Y[:, max(0, o - 28):o]
        nn = np.sum(~np.isnan(y28), axis=1)
        zs = np.where(nn > 0, np.sum(y28 == 0, axis=1) / np.maximum(nn, 1), np.nan)
        vol = np.nanmean(panel.Y[:, max(0, o - 56):o], axis=1)
    return {"rel": rel, "chg": chg, "zs": zs, "vol": vol, "last_price": panel.price[:, o - 1]}


folds = []
for k in range(base.backtest_folds):
    o = T - H - (base.backtest_folds - 1 - k) * base.backtest_step_days
    if o >= base.min_total_history_days:
        folds.append((k + 1, o))
points = None
results = {}
for name, on in (("demand_price", True), ("demand_only", False)):
    cfg, decisions = registry.resolve(base.model_copy(update={"feature_price": on}), cov)
    t0 = time.time()
    cols = {x: [] for x in ("fold", "o", "td", "si", "a", "f", "b", "lgbm", "rel", "chg", "zs", "vol", "expost")}
    for fold, o in folds:
        tp = panel.truncate(o)
        booster, _ = model.train(tp, cfg)
        fc = model.forecast(tp, booster, cfg, H)
        actual = panel.Y[:, o:o + H]
        valid = ~np.isnan(actual)
        si, di = np.nonzero(valid)
        d = at_origin(o)
        with np.errstate(all="ignore"):
            expost = panel.price[si, o + di] / d["last_price"][si]
        cols["fold"].append(np.full(len(si), fold, np.int8)); cols["o"].append(np.full(len(si), o, np.int16))
        cols["td"].append((o + di).astype(np.int16)); cols["si"].append(si.astype(np.int32))
        cols["a"].append(actual[valid].astype(np.float64)); cols["f"].append(fc["yhat"][valid].astype(np.float64))
        cols["b"].append(model.baseline_forecast(tp, H)[valid].astype(np.float64))
        cols["lgbm"].append((np.asarray(fc["methods"]) == model.METHOD_LGBM)[si])
        for x in ("rel", "chg", "zs", "vol"):
            cols[x].append(d[x][si].astype(np.float64))
        cols["expost"].append(expost.astype(np.float64))
        print(name, "fold", fold, "origin", dates[o].date(), "points", len(si), round(time.time() - t0), "s", flush=True)
    arr = {x: np.concatenate(v) for x, v in cols.items()}
    err = np.abs(arr["a"] - arr["f"])
    wape = float(err.sum() / arr["a"].sum())
    results[name] = {"seconds": round(time.time() - t0, 1), "features": feature_names(cfg),
                     "price_decision": decisions.get("price"), "pooled_wape": wape,
                     "parity_with_price_backtest": abs(wape - EXPECTED[name]) < 5e-7, "smoke": bool(os.environ.get("E0_SMOKE"))}
    print(name, "WAPE", round(wape, 6), "parity", results[name]["parity_with_price_backtest"], flush=True)
    if points is None:
        points = arr
    else:
        assert all(np.array_equal(points[x], arr[x]) for x in ("fold", "td", "si", "a")), "point sets differ"
        points["f_demand_only"] = arr["f"]
points["f_price"] = points.pop("f")

# ------------------------------------------------------------------ grouping
a, fp, fd, b = points["a"], points["f_price"], points["f_demand_only"], points["b"]
hz = points["td"].astype(int) - points["o"].astype(int) + 1
tot_abs = float(np.abs(a - fp).sum())


def m(mask, f):
    aa, ff = a[mask], f[mask]
    sa = float(aa.sum())
    e = np.abs(aa - ff)
    return {"wape": float(e.sum() / sa) if sa > 0 else None, "bias": float((ff.sum() - sa) / sa) if sa > 0 else None,
            "mae": float(e.mean()) if mask.any() else None}


def row(label, mask):
    n = int(mask.sum())
    sa = float(a[mask].sum())
    r = {"group": label, "n_points": n, "sum_actual": sa, "share_of_points": n / len(a),
         "share_of_abs_error": float(np.abs(a[mask] - fp[mask]).sum() / tot_abs) if n else 0.0,
         "enough_sample": n >= MIN_N and sa >= MIN_UNITS,
         "price": m(mask, fp) if n else None, "demand_only": m(mask, fd) if n else None,
         "baseline": m(mask, b) if n else None,
         "over_forecast_share": float((fp[mask] > a[mask]).mean()) if n else None,
         "under_forecast_share": float((fp[mask] < a[mask]).mean()) if n else None}
    if n and r["price"]["wape"] is not None and r["demand_only"]["wape"] is not None:
        r["delta_wape_price_minus_demand"] = r["price"]["wape"] - r["demand_only"]["wape"]
    return r


def classes(values, edges, labels, nan_label):
    out = []
    for lo, hi, lab in zip(edges[:-1], edges[1:], labels):
        out.append((lab, (values >= lo) & (values < hi)))
    out.append((nan_label, np.isnan(values)))
    return out


fc_pt = fc_of[points["si"]]
sku_pt = sku_of[points["si"]]
month = np.array([str(x)[:7] for x in dates.values.astype("datetime64[M]")])[points["td"]]
groups = {
    "all": [row("ALL", np.ones(len(a), bool))],
    "fc": [row(f, fc_pt == f) for f in sorted(set(fc_of))],
    "horizon_bucket": [row(lab, (hz >= lo) & (hz <= hi)) for lab, lo, hi in (("1-7", 1, 7), ("8-15", 8, 15), ("16-30", 16, 30))],
    "horizon_day": [row(str(h), hz == h) for h in range(1, H + 1)],
    "fc_x_horizon": [row(f"{f} {lab}", (fc_pt == f) & (hz >= lo) & (hz <= hi)) for f in sorted(set(fc_of))
                     for lab, lo, hi in (("1-7", 1, 7), ("8-15", 8, 15), ("16-30", 16, 30))],
    "target_month": [row(mo, month == mo) for mo in sorted(set(month))],
    "fold": [row(str(f), points["fold"] == f) for f, _ in folds],
    "method": [row("LIGHTGBM", points["lgbm"]), row("FALLBACK", ~points["lgbm"])],
    "demand_class_zero_share_28": [row(lab, msk) for lab, msk in classes(
        points["zs"], [0, 0.3, 0.7, 1.01], ["regular (<30% zero days)", "intermittent (30-70%)", "rare (>=70%)"], "no history")],
    "volume_class_mean_56d": [row(lab, msk) for lab, msk in classes(
        points["vol"], [0, 1, 5, 20, np.inf], ["<1/day", "1-5/day", "5-20/day", ">=20/day"], "no history")],
    "price_vs_28d_mean_at_origin": [row(lab, msk) for lab, msk in classes(
        points["rel"], [0, 0.97, 0.99, 1.01, 1.03, np.inf],
        ["<0.97 (cheaper)", "0.97-0.99", "0.99-1.01 (stable)", "1.01-1.03", ">=1.03 (dearer)"], "no price")],
    "price_change_frequency_28d": [row(lab, msk) for lab, msk in classes(
        points["chg"], [0, 1e-9, 0.25, 0.5, 1.01], ["no change", "<25% of days", "25-50%", ">=50%"], "no price")],
    "EXPOST_price_on_target_day_vs_origin": [row(lab, msk) for lab, msk in classes(
        points["expost"], [0, 0.97, 1.03, np.inf], ["dropped >3%", "within +-3%", "rose >3%"], "no price")],
}
# SKU concentration (all FCs of a SKU together)
skus, inv = np.unique(sku_pt, return_inverse=True)
abs_sku = np.bincount(inv, weights=np.abs(a - fp))
act_sku = np.bincount(inv, weights=a)
fc_sku = np.bincount(inv, weights=fp)
absd_sku = np.bincount(inv, weights=np.abs(a - fd))
n_sku = np.bincount(inv)
order = np.argsort(-abs_sku)
cum = np.cumsum(abs_sku[order]) / abs_sku.sum()
top = [{"sku": str(skus[i]), "n_points": int(n_sku[i]), "sum_actual": float(act_sku[i]),
        "share_of_abs_error": float(abs_sku[i] / abs_sku.sum()),
        "wape_price": float(abs_sku[i] / act_sku[i]) if act_sku[i] > 0 else None,
        "wape_demand_only": float(absd_sku[i] / act_sku[i]) if act_sku[i] > 0 else None,
        "bias_price": float((fc_sku[i] - act_sku[i]) / act_sku[i]) if act_sku[i] > 0 else None} for i in order[:25]]
sku_summary = {"n_skus": int(len(skus)),
               "share_of_abs_error_top_1pct_skus": float(cum[max(0, int(len(skus) * 0.01) - 1)]),
               "share_of_abs_error_top_10pct_skus": float(cum[max(0, int(len(skus) * 0.10) - 1)]),
               "skus_for_50pct_of_abs_error": int(np.searchsorted(cum, 0.5) + 1),
               "skus_with_zero_actual_but_forecast": int(((act_sku == 0) & (fc_sku > 0)).sum()),
               "top25": top}
res = {"generated_for": "E0 error analysis, release config (DIRECT, price ON) vs demand only", "scope_key": sk,
       "panel": [str(dates[0].date()), str(dates[-1].date()), S], "coverage": cov,
       "folds": [{"fold": f, "origin": str(dates[o].date()), "last_target": str(dates[min(o + H, T) - 1].date())} for f, o in folds],
       "n_points": int(len(a)), "analysis_convention": {"min_points": MIN_N, "min_units": MIN_UNITS},
       "runs": results, "groups": groups, "sku": sku_summary}
(OUT / "e0_results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
np.savez_compressed(NPZ, **{k: v for k, v in points.items()}, hz=hz)
print("written", OUT / "e0_results.json", NPZ, flush=True)
