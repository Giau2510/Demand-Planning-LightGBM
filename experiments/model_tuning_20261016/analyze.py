"""Breakdowns of the experiment on the SAME evaluation points for every configuration (offline, read-only inputs).
Inputs: EXP_POINTS/_keys.npz (fold, series, day, actual, baseline, segment, FC of R0_production) + <config>.npz
(forecast, method) + runs/<config>.json. Outputs: CSV tables in this folder.

Metrics = app.ml.metrics definitions: WAPE = sum|A-F| / sum A ; bias = (sum F - sum A) / sum A (> 0 = over-forecast).
Walk-forward selection (no look-ahead): for fold k, pick the configuration with the lowest WAPE pooled over the folds
evaluated BEFORE k (all their test days precede origin k); the first evaluated fold uses R0_production."""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

EXP = Path(__file__).resolve().parent
POINTS = Path(os.environ["EXP_POINTS"]).resolve()
GATE_WAPE, GATE_BIAS = 0.60, 0.20                     # production quality gate (reference only, not changed)
SEGMENTS = ["LGBM_ZS_LT50", "LGBM_ZS_50_80", "INTERMITTENT", "NEW_SERIES", "INACTIVE"]
METHODS = ["LIGHTGBM", "FALLBACK_NEW_SERIES", "FALLBACK_INTERMITTENT", "FALLBACK_INACTIVE_ZERO",
           "FALLBACK_MODEL_UNAVAILABLE"]
H, F, STEP = 30, 12, 30
# Wall-clock time that is NOT computation: Windows Modern Standby (System log, Kernel-Power 506/507) 18:36:21-21:40:05
# on 16/10 = 7 + 7199 + 3817 s, entirely inside fold 12 of L7_direct (18:34-21:40). No other run overlapped a standby.
STANDBY = {("L7_direct", 12): 11023.0}

k = np.load(POINTS / "_keys.npz")
fold, s, d = k["fold"].astype(int), k["s"].astype(int), k["d"].astype(int)
A, B = k["actual"].astype(float), k["baseline"].astype(float)
seg, fcs, dates = k["seg"].astype(int), k["fc"].astype(int), pd.to_datetime(k["dates"])
T = len(dates)
origin_idx = {f: T - H - (F - f) * STEP for f in range(1, F + 1)}
tidx = np.array([origin_idx[f] for f in fold]) + d
tdate = dates[tidx]
month = tdate.strftime("%Y-%m").to_numpy()
period = np.where(tdate < pd.Timestamp("2026-07-01"), "before_2026-07", "from_2026-07")
hbucket = np.select([d < 7, d < 14], ["days_01_07", "days_08_14"], "days_15_30")
FOLDS = sorted(set(fold))


def m(a, f):
    sa = a.sum()
    return {"n_points": int(a.size), "sum_actual": float(sa), "sum_forecast": float(f.sum()),
            "wape": float(np.abs(a - f).sum() / sa) if sa > 0 else None,
            "bias": float((f.sum() - sa) / sa) if sa > 0 else None, "mae": float(np.abs(a - f).mean()) if a.size else None}


runs = {}
for fpath in sorted((EXP / "runs").glob("*.json")):
    j = json.loads(fpath.read_text(encoding="utf-8"))
    z = np.load(POINTS / f"{j['name']}.npz")
    runs[j["name"]] = {"json": j, "f": z["forecast"].astype(float), "method": z["method"].astype(int)}
names = list(runs)


def rows_by(key_arr, label):
    out = []
    for n in ["BASELINE"] + names:
        f = B if n == "BASELINE" else runs[n]["f"]
        for kv in pd.unique(key_arr):
            sel = key_arr == kv
            r = m(A[sel], f[sel])
            rb = m(A[sel], B[sel])
            out.append({"config": n, label: kv, **r, "baseline_wape": rb["wape"], "baseline_bias": rb["bias"],
                        "delta_wape_vs_baseline": (r["wape"] - rb["wape"]) if r["wape"] is not None else None})
    return pd.DataFrame(out)


summ = []
for n in ["BASELINE"] + names:
    f = B if n == "BASELINE" else runs[n]["f"]
    r = m(A, f)
    js = runs[n]["json"] if n != "BASELINE" else None
    lg = (runs[n]["method"] == 0) if n != "BASELINE" else np.zeros(A.size, bool)
    summ.append({"config": n, "group": js["spec"]["group"] if js else "baseline",
                 "hypothesis": js["spec"]["hypothesis"] if js else "production baseline: 28-day mean, flat",
                 **r, "abs_bias": abs(r["bias"]),
                 "delta_wape_vs_baseline": r["wape"] - m(A, B)["wape"],
                 "worst_fold_wape": max(m(A[fold == q], f[fold == q])["wape"] for q in FOLDS),
                 "passes_gate": bool(r["wape"] <= GATE_WAPE and abs(r["bias"]) <= GATE_BIAS),
                 "beats_baseline_wape": bool(r["wape"] < m(A, B)["wape"]),
                 "points": int(A.size), "series_evaluated": int(len(set(zip(fold, s)))),
                 "share_points_lightgbm": float(lg.mean()) if n != "BASELINE" else None,
                 "runtime_seconds": js["seconds"] if js else None,
                 "runtime_seconds_excl_standby": (js["seconds"] - sum(v for (c, _), v in STANDBY.items() if c == n))
                 if js else None,
                 "json_pooled_wape": js["pooled"]["wape"] if js else None})
summary = pd.DataFrame(summ).sort_values("wape").reset_index(drop=True)
summary.insert(0, "rank_by_wape", range(1, len(summary) + 1))
summary.to_csv(EXP / "ranking.csv", index=False)

fold_rows = []
for n in ["BASELINE"] + names:
    f = B if n == "BASELINE" else runs[n]["f"]
    for q in FOLDS:
        sel = fold == q
        fold_rows.append({"config": n, "fold": q, "origin": str(dates[origin_idx[q]].date()), **m(A[sel], f[sel]),
                          **({"seconds": next(x["seconds"] for x in runs[n]["json"]["folds"] if x["fold"] == q),
                              "seconds_excl_standby": next(x["seconds"] for x in runs[n]["json"]["folds"]
                                                           if x["fold"] == q) - STANDBY.get((n, q), 0.0),
                              "train_rows": next(x.get("n_rows") for x in runs[n]["json"]["folds"] if x["fold"] == q),
                              "rounds": next(x.get("rounds") for x in runs[n]["json"]["folds"] if x["fold"] == q)}
                             if n != "BASELINE" else {})})
fold_df = pd.DataFrame(fold_rows)
fold_df.to_csv(EXP / "fold_results.csv", index=False)
fold_df[fold_df.config == "BASELINE"].to_csv(EXP / "baseline_results.csv", index=False)
grp = {n: runs[n]["json"]["spec"]["group"] for n in names}
summary[summary.config.isin(["BASELINE", "R0_production"] + [n for n in names if grp[n] == "window"])] \
    .to_csv(EXP / "window_comparison.csv", index=False)
summary[summary.config.isin(["BASELINE", "R0_production"] + [n for n in names if grp[n] in ("lgbm", "combined")])] \
    .to_csv(EXP / "lgbm_comparison.csv", index=False)
rows_by(month, "month").to_csv(EXP / "monthly_results.csv", index=False)
rows_by(period, "period").to_csv(EXP / "period_results.csv", index=False)
rows_by(np.where(fcs[s] == 1, "HN", "BD"), "fc").to_csv(EXP / "fc_results.csv", index=False)
rows_by(np.array([SEGMENTS[i] for i in seg]), "segment").to_csv(EXP / "segment_analysis.csv", index=False)
rows_by(hbucket, "horizon_days").to_csv(EXP / "horizon_results.csv", index=False)

# walk-forward selection (honest estimate of "pick the best configuration as you go")
cands = names
err = {n: {q: float(np.abs(A[fold == q] - runs[n]["f"][fold == q]).sum()) for q in FOLDS} for n in cands}
act = {q: float(A[fold == q].sum()) for q in FOLDS}
chosen, sel_f = [], np.zeros_like(A)
for i, q in enumerate(FOLDS):
    prev = FOLDS[:i]
    if not prev:
        pick = "R0_production"
    else:
        pick = min(cands, key=lambda n: sum(err[n][p] for p in prev) / sum(act[p] for p in prev))
    chosen.append({"fold": q, "origin": str(dates[origin_idx[q]].date()), "selected": pick,
                   "selected_on_folds": ",".join(map(str, prev)) or "(none: production default)",
                   **m(A[fold == q], runs[pick]["f"][fold == q])})
    sel_f[fold == q] = runs[pick]["f"][fold == q]
sel = pd.DataFrame(chosen)
tot = m(A, sel_f)
sel = pd.concat([sel, pd.DataFrame([{"fold": "ALL", "selected": "walk-forward selection", **tot}])], ignore_index=True)
sel.to_csv(EXP / "selection_walkforward.csv", index=False)
print(summary[["rank_by_wape", "config", "wape", "bias", "worst_fold_wape", "delta_wape_vs_baseline", "passes_gate",
               "share_points_lightgbm", "runtime_seconds"]].to_string(index=False))
print(sel[["fold", "selected", "wape", "bias"]].to_string(index=False))
