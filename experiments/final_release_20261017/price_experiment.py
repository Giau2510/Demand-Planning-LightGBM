"""Price-feature experiment (1.2.0) on an ISOLATED DB copy - never the live DB.
  phase load:  map unit_price <- sales_price (owner: the order-line price already includes the deal effect), full-period
               validation, then a BACKFILL load 2026-01-01..2026-10-15 through the app's own D-1 code (BigQuery read-only,
               dry run first, byte cap) -> demand_daily of the copy carries avg_unit_price (quantity-weighted)
  phase backtest: production DIRECT (L7_direct) walk-forward on the same 7 folds, demand-only vs demand+price; the
               price group goes through the production feature registry (coverage decision) exactly like a training.
Writes only into the isolated copy and OUT (scratchpad). Usage: price_experiment.py load|backtest <out dir>"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ISO = Path(os.environ["DF_DATA_DIR"]).resolve()
assert "scratchpad" in str(ISO).lower() and "lightgbm ai" not in str(ISO).lower(), ISO
sys.path.insert(0, r"D:\Buymed\Lightgbm AI\backend")
from app import db, paths                                    # noqa: E402
from app import settings_service as ss                       # noqa: E402
from app.bq import connector                                 # noqa: E402
from app.data.demand import bigquery_scope_key, load_demand  # noqa: E402
from app.ml import feature_registry as registry, metrics, model  # noqa: E402
from app.ml.features import build_panel, feature_names       # noqa: E402

assert paths.data_dir().resolve() == ISO
OUT = Path(sys.argv[2]).resolve()
OUT.mkdir(parents=True, exist_ok=True)
START, END = "2026-01-01", "2026-10-15"


def demand_facts(sk):
    with db.read() as c:     # plain list: a sqlite3.Row would be written to load.json as its repr (fixed 17/10/2026)
        return list(c.execute("SELECT COUNT(*), SUM(qty), COUNT(avg_unit_price), MIN(order_date), MAX(order_date) FROM "
                              "demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?", (sk, START, END)).fetchone())


bq = ss.get("bigquery")
sk = bigquery_scope_key(bq)
if sys.argv[1] == "load":
    from app.sync import run_d1_sync
    before = demand_facts(sk)
    fm = {k: v.model_dump() for k, v in bq.field_mapping.items()}
    if (fm.get("unit_price") or {}).get("column") != "sales_price":
        fm["unit_price"] = {"column": "sales_price", "usage": "OPTIONAL"}
        ss.update("bigquery", {"field_mapping": fm}, note="ISOLATED COPY: price experiment (unit_price <- sales_price)")
    if connector.validation_ok_for_current():
        v = connector.validation_state()
    else:
        v = connector.validate_source()
    print("validation", v["passed"], [b["code"] for b in v["blocking_issues"]], [w["code"] for w in v["warnings"]],
          "bytes", v["estimated_bytes"], flush=True)
    assert v["passed"]
    # ISOLATED COPY ONLY: simulated run time 16/10 15:00 (VN) so that "yesterday" = 15/10, a complete day in the source;
    # the new mapping needs a normal full reload first (the app refuses a backfill before it)
    from datetime import datetime, timedelta, timezone
    from app import timeutil
    sim = datetime(2026, 10, 16, 15, 0, tzinfo=timezone(timedelta(hours=7)))
    timeutil.set_now_override(lambda: sim)
    t = time.time()
    r = run_d1_sync("PRICE-EXP", fallback_mode=True)
    keys = ("mode", "window_start", "window_end", "rows_read", "qty_read", "qty_valid", "series_days_written",
            "series_days_updated", "series_days_unchanged", "exact_duplicate_rows")
    print("backfill", round(time.time() - t), "s", {k: r.get(k) for k in keys}, flush=True)
    after = demand_facts(sk)
    print("demand before (rows, qty, priced rows, first, last)", before)
    print("demand after                                      ", after)
    (OUT / "load.json").write_text(json.dumps({"before": before, "after": after, "validation_bytes": v["estimated_bytes"],
                                               "backfill": {k: r.get(k) for k in keys}}, default=str, indent=1))
    sys.exit(0)

# ---- backtest: demand-only vs demand + price, production DIRECT on the same folds
base = ss.ModelSettings(**{**ss.get("model").model_dump(), "forecast_strategy": "DIRECT", "num_threads": 0})
with db.read() as c:
    cov = registry.coverage(c, sk)
d = load_demand(sk, start=START, end=END)
panel = build_panel(d, max_days=base.max_train_days)
H = base.backtest_horizon_days
res = {"coverage": cov, "panel": [str(panel.dates[0].date()), str(panel.dates[-1].date()), panel.n_series]}
dates = panel.dates
fc_of = np.array([k[1] for k in panel.keys])
for name, on in (("demand_only", False), ("demand_price", True)):
    cfg, decisions = registry.resolve(base.model_copy(update={"feature_price": on}), cov)
    t = time.time()
    A, F, B, M, FC, FO = [], [], [], [], [], []
    for k in range(base.backtest_folds):
        origin = panel.T - H - (base.backtest_folds - 1 - k) * base.backtest_step_days
        if origin < base.min_total_history_days:
            continue
        tp = panel.truncate(origin)
        booster, _ = model.train(tp, cfg)
        fc = model.forecast(tp, booster, cfg, H)
        actual = panel.Y[:, origin:origin + H]
        base_fc = model.baseline_forecast(tp, H)
        valid = ~np.isnan(actual)
        si, di = np.nonzero(valid)
        A.append(actual[valid]); F.append(fc["yhat"][valid]); B.append(base_fc[valid])
        M.append(np.array([str(dates[origin + x].date())[:7] for x in di])); FC.append(fc_of[si])
        FO.append(np.full(len(si), k + 1))
    a, f, b, mo, fcs, fo = (np.concatenate(x) for x in (A, F, B, M, FC, FO))
    out = {"features": feature_names(cfg), "price_decision": decisions.get("price"), "seconds": round(time.time() - t, 1),
           "pooled": metrics.compute(a, f), "baseline": metrics.compute(a, b),
           "folds": {int(q): metrics.compute(a[fo == q], f[fo == q]) for q in np.unique(fo)},
           "fc": {s: metrics.compute(a[fcs == s], f[fcs == s]) for s in np.unique(fcs)},
           "period": {"before_2026-07": metrics.compute(a[mo < "2026-07"], f[mo < "2026-07"]),
                      "from_2026-07": metrics.compute(a[mo >= "2026-07"], f[mo >= "2026-07"])}}
    res[name] = out
    print(name, "WAPE", round(out["pooled"]["wape"], 6), "bias", round(out["pooled"]["bias"], 6), "seconds", out["seconds"],
          "price used", (decisions.get("price") or {}).get("used"), flush=True)
(OUT / "price_backtest.json").write_text(json.dumps(res, default=str, indent=1), encoding="utf-8")
