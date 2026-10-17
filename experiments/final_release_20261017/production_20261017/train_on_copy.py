"""TRAIN_CANDIDATE on an ISOLATED COPY of the current production DB (the live DB is only READ, through the SQLite backup
API with mode=ro). Production training is not authorised in this session: nothing here touches the live DB, models or
settings. Uses the official pipeline of the 1.2.0 code (commit 577b925 = the deployed package):
  1. copy the live DB + model files into <iso>  2. train_and_publish(force=True) on the copy (DIRECT, price ON, as saved)
  3. checks on the run  4. owner-approved gate exception on the COPY only (rehearsal of the release step)
Usage: train_on_copy.py <iso dir> <out json>   (DF_DATA_DIR must be <iso>\\data)"""
import json
import os
import shutil
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ISO = Path(sys.argv[1]).resolve()
assert "scratchpad" in str(ISO).lower() and Path(os.environ["DF_DATA_DIR"]).resolve() == ISO / "data", ISO
LIVE_DB = Path(r"D:\Buymed\Lightgbm AI\data\runtime\db\app.db")
LIVE_MODELS = Path(r"D:\Buymed\Lightgbm AI\data\runtime\models")
(ISO / "data" / "db").mkdir(parents=True, exist_ok=True)
(ISO / "data" / "models").mkdir(parents=True, exist_ok=True)
src = sqlite3.connect(f"file:{LIVE_DB.as_posix()}?mode=ro", uri=True)
dst = sqlite3.connect(ISO / "data" / "db" / "app.db")
src.backup(dst)
dst.close()
src.close()
for f in LIVE_MODELS.iterdir():
    shutil.copy2(f, ISO / "data" / "models" / f.name)

sys.path.insert(0, r"D:\Buymed\Lightgbm AI\backend")
from app import db, paths                        # noqa: E402
from app import settings_service as ss           # noqa: E402
from app.ml import pipeline                      # noqa: E402

assert paths.data_dir().resolve() == (ISO / "data").resolve()
out = {"copied_from": str(LIVE_DB), "model_settings": {k: getattr(ss.get("model"), k) for k in
                                                        ("feature_price", "forecast_strategy", "direct_origins",
                                                         "direct_origin_step_days", "feature_lags", "feature_rolling")}}
stages = []
t0 = time.time()
res = pipeline.train_and_publish(force=True, progress=lambda s, *a, **k: stages.append((s, round(time.time() - t0))))
out["train"] = {"result": res, "seconds": round(time.time() - t0), "stages": stages}
print("train", json.dumps(out["train"], default=str), flush=True)
rid = res["training_run_id"]
with db.read() as c:
    tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (rid,))
    bt = db.one(c, "SELECT config_json FROM backtest_runs WHERE training_run_id=?", (rid,))
fc = json.loads(tr["feature_config_json"])
m = json.loads(tr["metrics_json"] or "{}")
out["run"] = {"id": rid, "status": tr["status"], "reject_reason": tr["reject_reason"], "model_version": tr["model_version"],
              "model_path": tr["model_path"], "model_sha256": tr["model_sha256"], "train": [tr["train_start"], tr["train_end"]],
              "n_series": tr["n_series"], "n_rows": tr["n_rows"], "features": fc["features"],
              "feature_groups": fc["feature_groups"], "price_decision": fc["feature_decisions"]["price"],
              "config_fingerprint": fc["config_fingerprint"], "data_window": fc["data_window"],
              "metrics": {k: m.get(k) for k in ("wape", "bias", "mae", "n_points")},
              "baseline": {k: json.loads(tr["baseline_metrics_json"] or "{}").get(k) for k in ("wape", "bias", "mae")},
              "backtest": json.loads(bt["config_json"]) if bt else None,
              "gate": json.loads(tr["quality_gate_json"] or "{}"),
              "exception": pipeline.exception_eligible(tr)}
print("run", json.dumps({k: out["run"][k] for k in ("status", "model_version", "metrics", "feature_groups", "exception")},
                        default=str), flush=True)
if out["run"]["exception"]["eligible"]:
    t1 = time.time()
    rel = pipeline.release_with_gate_exception(rid, {
        "confirm_text": f"EXCEPTION-{rid}", "approved_by": "Chu du an (COPY rehearsal, not production)",
        "reason": "Isolated copy of production 17/10/2026: owner-approved exception for the DIRECT model with price",
        "review_by": str(date.today() + timedelta(days=30)),
        "acknowledged_wape": round(m["wape"], 3), "acknowledged_bias": round(m["bias"], 3)})
    out["release_on_copy"] = {"result": rel, "seconds": round(time.time() - t1)}
    print("release on copy", json.dumps(out["release_on_copy"], default=str), flush=True)
Path(sys.argv[2]).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
