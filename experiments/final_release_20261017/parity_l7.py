"""Parity of the PRODUCTION implementation of the DIRECT strategy (app.ml.model, 1.2.0 source) with the experiment
harness result L7_direct, on the same isolated DB copy (read-only), then the production training path on the full
panel: final model, 15-day forecast, artifact save + reload, peak memory and time. Writes only into OUT (scratchpad).
Usage: parity_l7.py <isolated app.db> <out dir>"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(r"D:\Buymed\Lightgbm AI")
sys.path.insert(0, str(REPO / "backend"))
from app import settings_service as ss               # noqa: E402
from app.ml import model                             # noqa: E402
from app.ml.features import build_panel, feature_names  # noqa: E402

DB, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
assert "scratchpad" in str(DB).lower() and "scratchpad" in str(OUT).lower()
OUT.mkdir(parents=True, exist_ok=True)
TRN = "TRN-20261016095451-697A11"
SCOPE = "BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm"


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def mem_gb():
    c = PMC()
    c.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb)
    return round(c.PeakWorkingSetSize / 2**30, 2), round(c.PeakPagefileUsage / 2**30, 2)


c = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)
r = c.execute("SELECT feature_config_json, train_start, train_end FROM training_runs WHERE id=?", (TRN,)).fetchone()
base = json.loads(r[0])["config"]
cfg = ss.ModelSettings(**{**base, "forecast_strategy": "DIRECT"})
d = pd.read_sql_query("SELECT order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, avg_discount_rate, promo_share, "
                      "voucher_share FROM demand_daily WHERE scope_key=? AND order_date>=? AND order_date<=?", c,
                      params=[SCOPE, r[1], r[2]])
c.close()
panel = build_panel(d, max_days=cfg.max_train_days)
del d
out = {"features": feature_names(cfg), "panel": [str(panel.dates[0].date()), str(panel.dates[-1].date()), panel.n_series]}
t0 = time.time()
bt = model.backtest(panel, cfg, 1.0)
out["backtest_seconds"] = round(time.time() - t0, 1)
out["backtest_pooled"], out["baseline_pooled"] = bt["metrics"], bt["baseline_metrics"]
out["folds"] = [{"fold": f["fold"], "origin": f["origin"], "metrics": f["metrics"]} for f in bt["folds"]]
h = json.loads((REPO / "experiments/model_tuning_20261016/runs/L7_direct.json").read_text(encoding="utf-8"))
diffs = {"pooled_wape": abs(h["pooled"]["wape"] - bt["metrics"]["wape"]),
         "pooled_bias": abs(h["pooled"]["bias"] - bt["metrics"]["bias"]),
         "pooled_sum_forecast": abs(h["pooled"]["sum_forecast"] - bt["metrics"]["sum_forecast"]),
         "n_points": h["pooled"]["n_points"] - bt["metrics"]["n_points"],
         "max_fold_wape": max(abs(a["metrics"]["wape"] - b["metrics"]["wape"]) for a, b in zip(h["folds"], bt["folds"])),
         "max_fold_sum_forecast": max(abs(a["metrics"]["sum_forecast"] - b["metrics"]["sum_forecast"])
                                      for a, b in zip(h["folds"], bt["folds"]))}
out["harness_vs_production"] = diffs
out["mem_after_backtest_gb"] = mem_gb()
print("backtest", out["backtest_seconds"], "s WAPE", bt["metrics"]["wape"], "bias", bt["metrics"]["bias"], "diffs", diffs,
      "mem", out["mem_after_backtest_gb"], flush=True)

t0 = time.time()
booster, info = model.train(panel, cfg)
out["train_seconds"], out["train_rows"] = round(time.time() - t0, 1), info["n_rows"]
t0 = time.time()
fc = model.forecast(panel, booster, cfg, 15)
out["forecast_seconds"] = round(time.time() - t0, 1)
y = fc["yhat"]
out["forecast_checks"] = {"shape": list(y.shape), "nan": int(np.isnan(y).sum()), "inf": int(np.isinf(y).sum()),
                          "negative": int((y < 0).sum()), "first_day": str(fc["dates"][0].date()),
                          "last_day": str(fc["dates"][-1].date()),
                          "consecutive_days": bool((np.diff(fc["dates"].values).astype("timedelta64[D]").astype(int) == 1).all()),
                          "series_order_equals_panel": len(fc["methods"]) == panel.n_series, "sum": float(y.sum()),
                          "methods": {k: int(v) for k, v in zip(*np.unique(fc["methods"], return_counts=True))}}
mp = OUT / "L7_parity_model.txt"
booster.save_model(str(mp))
import lightgbm as lgb                               # noqa: E402
re = lgb.Booster(model_file=str(mp))
fc2 = model.forecast(panel, re, cfg, 15)
out["reload_identical"] = bool(np.array_equal(fc2["yhat"], y))
out["reload_max_abs_diff"] = float(np.abs(fc2["yhat"] - y).max())
try:
    model.forecast(panel, re, cfg, 31)
    out["horizon_31_refused"] = False
except ValueError as e:
    out["horizon_31_refused"] = str(e)[:80]
out["mem_peak_gb"] = mem_gb()
(OUT / "parity_l7.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: v for k, v in out.items() if k not in ("features", "folds")}, indent=1, default=str))
