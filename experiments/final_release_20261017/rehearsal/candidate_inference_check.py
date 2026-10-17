"""Independent inference check of the rehearsal candidate (DIRECT, price ON) on an EXTRACTED copy of the isolated
rehearsal DB (pre-restore safety backup, i.e. the state with the published exception release). Read-only on that copy.
  - model file hash = training run record; feature list = metadata = booster
  - published values: count = series x max horizon, no NaN / Inf / negative
  - the booster reloaded from file reproduces every published value (same artifact + same input -> same output)
  - price features are real inputs: changing only the last known price changes LightGBM forecasts
Usage (DF_DATA_DIR = extracted copy): candidate_inference_check.py <forecast run id> <out json>"""
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np

ISO = Path(os.environ["DF_DATA_DIR"]).resolve()
assert "scratchpad" in str(ISO).lower(), ISO
sys.path.insert(0, r"D:\Buymed\Lightgbm AI\backend")
from app import settings_service as ss                     # noqa: E402
from app.data.demand import load_demand                    # noqa: E402
from app.ml import model                                   # noqa: E402
from app.ml.features import build_panel                    # noqa: E402

c = sqlite3.connect(f"file:{(ISO / 'db' / 'app.db').as_posix()}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
fr = dict(c.execute("SELECT * FROM forecast_runs WHERE id=?", (sys.argv[1],)).fetchone())
tr = dict(c.execute("SELECT * FROM training_runs WHERE id=?", (fr["training_run_id"],)).fetchone())
fcj = json.loads(tr["feature_config_json"])
mfile = ISO / "models" / tr["model_path"]
out = {"forecast_run": fr["id"], "training_run": tr["id"], "model_version": tr["model_version"], "status": tr["status"],
       "model_sha256_matches": hashlib.sha256(mfile.read_bytes()).hexdigest() == tr["model_sha256"]}
booster = lgb.Booster(model_file=str(mfile))
meta = json.loads((ISO / "models" / tr["model_path"].replace(".txt", ".json")).read_text(encoding="utf-8"))
out["features_consistent"] = booster.feature_name() == fcj["features"] == meta["features"]
out["price_features"] = [n for n in booster.feature_name() if n.startswith("price")]
out["feature_groups"] = fcj["feature_groups"]
out["gate_exception"] = (json.loads(tr["quality_gate_json"]) or {}).get("exception", {}).get("scope")
mcfg = ss.ModelSettings.model_validate(fcj["config"])
p = build_panel(load_demand(tr["scope_key"], start=tr["train_start"], end=tr["train_end"]), start_date=tr["train_start"],
                end_date=tr["train_end"])
H = fr["max_horizon"]
fc = model.forecast(p, booster, mcfg, H)
vals = c.execute("SELECT sku_id, fc_id, horizon_day, yhat, method FROM forecast_values WHERE run_id=?", (fr["id"],)).fetchall()
y = np.array([v["yhat"] for v in vals], dtype=float)
out["published_values"] = len(vals)
out["expected_values"] = p.n_series * H
out["nan_inf_negative"] = int((~np.isfinite(y)).sum() + (y < 0).sum())
idx = {k: i for i, k in enumerate(p.keys)}
diff = max(abs(round(float(fc["yhat"][idx[(v["sku_id"], v["fc_id"])], v["horizon_day"] - 1]), 4) - v["yhat"]) for v in vals)
out["max_abs_diff_reproduced_vs_published"] = diff
again = model.forecast(p, lgb.Booster(model_file=str(mfile)), mcfg, H)
out["reload_identical"] = bool(np.array_equal(again["yhat"], fc["yhat"]))
lg = np.asarray(fc["methods"]) == model.METHOD_LGBM
q = p.truncate(p.T)
q.price[:, -1] = q.price[:, -1] * 1.10                       # +10 % on the last known price only
moved = np.abs(model.forecast(q, booster, mcfg, H)["yhat"] - fc["yhat"]) > 1e-9
out["lgbm_series"] = int(lg.sum())
out["lgbm_series_moved_by_price_plus10pct"] = int(moved[lg].any(axis=1).sum())
out["fallback_series_moved"] = int(moved[~lg].any(axis=1).sum())
out["methods"] = json.loads(fr["method_counts_json"])
Path(sys.argv[2]).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps(out, indent=1, default=str))
