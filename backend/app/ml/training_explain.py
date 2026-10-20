"""Read-only explanation of how the model behind a forecast was trained and evaluated.

Every number comes from the database (training_runs, backtest_runs, forecast_runs), the saved model file (sha256
checked) or the code's own constants. Nothing is written. Backtest points are RECOMPUTED in memory with the training
run's configuration on the same data (fingerprint checked) and only returned when the recomputed metrics equal the
stored ones - so the file really is the set of pairs the published metrics were computed from.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter

from .. import db, paths
from .. import settings_service as ss
from ..data import identity
from ..data.demand import panel_for_run, resolve_scope
from ..messages import AppError
from . import feature_catalog, feature_registry, model

SKIP_FAIL_RULES = [  # conditions in ml/pipeline.py::train_and_publish, in the order they are checked
    ("NO_NEW_DATA", "SKIPPED"), ("DATA_NOT_TRAINABLE", "REJECTED"), ("STALE_DATA_BLOCKED", "REJECTED"),
    ("QUALITY_GATE_FAILED", "REJECTED"), ("FORECAST_TOO_LARGE", "REJECTED"), ("TRAINING_FAILED", "FAILED"),
    ("PUBLISH_FAILED", "FAILED"), ("TIMEOUT", "FAILED"),
]


def _json(v, default=None):
    try:
        return json.loads(v) if v else default
    except (TypeError, ValueError):
        return default


def overview(training_run_id: str | None = None) -> dict:
    with db.read() as c:
        runs = db.rows(c, "SELECT id, status, data_source, scope_key, started_at, finished_at, model_version, "
                          "reject_reason FROM training_runs ORDER BY started_at DESC, rowid DESC LIMIT 50")
        if training_run_id is None:
            acc = next((r for r in runs if r["status"] == "ACCEPTED"), None)
            training_run_id = acc["id"] if acc else None
        try:
            scope = resolve_scope(c)
            active = {"active_source": scope["data_source"], "scope_key": scope["scope_key"], "has_dataset": True}
        except AppError as e:
            g = ss.get("general", c)
            active = {"active_source": g.active_source, "scope_key": None, "has_dataset": False, "reason_code": e.code}
        if not training_run_id:
            return {"active": active, "runs": runs, "training_run": None}
        tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (training_run_id,))
        if not tr:
            raise AppError("BATCH_NOT_FOUND", 404, detail=training_run_id)
        bt = db.one(c, "SELECT * FROM backtest_runs WHERE training_run_id=?", (training_run_id,))
        frs = db.rows(c, "SELECT id, created_at, horizons_json, max_horizon, forecast_origin, data_as_of, derived_from_run_id "
                         "FROM forecast_runs WHERE training_run_id=? ORDER BY created_at, rowid", (training_run_id,))
        methods = []
        if frs:
            methods = db.rows(c, "SELECT method, COUNT(DISTINCT sku_id || '|' || fc_id) AS n_series FROM forecast_values "
                                 "WHERE run_id=? GROUP BY method", (frs[0]["id"],))
        # 1.2.4: same data = same load OR identical values in the run's window (a reload does not count as a change)
        state = identity.data_state(tr, tr["scope_key"], c)
    fcfg = _json(tr["feature_config_json"], {}) or {}
    cfg = fcfg.get("config") or {}
    features = fcfg.get("features") or []
    params = _json(tr["params_json"], {}) or {}
    artifact = {"model_version": tr["model_version"], "file": tr["model_path"], "sha256": tr["model_sha256"],
                "exists": False, "sha256_matches": None, "n_trees": None, "n_sku": None, "n_fc": None}
    if tr["model_path"]:
        f = paths.models_dir() / tr["model_path"]
        if f.exists():
            artifact["exists"] = True
            artifact["sha256_matches"] = hashlib.sha256(f.read_bytes()).hexdigest() == tr["model_sha256"]
            if artifact["sha256_matches"]:
                import lightgbm as lgb
                artifact["n_trees"] = lgb.Booster(model_file=str(f)).num_trees()
        meta = paths.models_dir() / f"{tr['model_version']}.json"
        if meta.exists():
            m = _json(meta.read_text(encoding="utf-8"), {}) or {}
            artifact["n_sku"] = len(m.get("sku_codes") or {})
            artifact["n_fc"] = len(m.get("fc_codes") or {})
    out = {
        "active": active, "runs": runs,
        "training_run": {k: tr[k] for k in ("id", "status", "data_source", "scope_key", "started_at", "finished_at",
                                             "train_start", "train_end", "n_series", "n_rows", "reject_reason", "job_id")},
        "data_unchanged_since_training": state["status"] in ("SAME_LOAD", "SAME_CONTENT"),
        "data_check": {k: v for k, v in state.items() if k not in ("key", "changed_days")},
        "target": {"name": "qty", "unit": "order_qty",
                   "definition": "Σ order_qty per Vietnam calendar day × SKU × FC (demand_daily); cancellations not subtracted"},
        "config": {k: cfg.get(k) for k in ("objective", "num_boost_round", "learning_rate", "num_leaves", "max_train_days",
                                           "min_total_history_days", "min_series_history_days", "intermittent_zero_share",
                                           "inactive_days", "fallback_window_days", "backtest_folds",
                                           "backtest_horizon_days", "backtest_step_days")},
        "params": params,
        "link": "exp" if params.get("objective") in ("tweedie", "poisson") else "identity",
        "early_stopping": False, "validation_set": False,
        "features": [{"name": n, "group": feature_catalog.describe(n)["group"]} for n in features],
        "feature_set": {"version": fcfg.get("feature_set_version") or feature_registry.feature_set_version(features),
                        "stored": bool(fcfg.get("feature_set_version")), "registry_version": fcfg.get("registry_version"),
                        "decisions": fcfg.get("feature_decisions"), "settings_switches": fcfg.get("settings_switches")},
        "lineage": fcfg.get("lineage"),
        "artifact": artifact,
        "quality_gate": _json(tr["quality_gate_json"]),
        "metrics": _json(tr["metrics_json"]),
        "baseline_metrics": _json(tr["baseline_metrics_json"]),
        "feature_importance": (_json(tr["feature_importance_json"], []) or [])[:15],
        "forecast_runs": [{**r, "horizons": _json(r.pop("horizons_json"), [])} for r in frs],
        "method_counts": methods,
        "skip_fail_rules": [{"code": c_, "result": r_} for c_, r_ in SKIP_FAIL_RULES],
    }
    if bt:
        bm = _json(bt["metrics_json"], {}) or {}
        out["backtest"] = {"id": bt["id"], "config": _json(bt["config_json"], {}), "reliable": bool(bt["reliable"]),
                           "folds": _json(bt["folds_json"], []), "by_method": bm.get("by_method"),
                           # 1.2.9: per demand-pattern group / volume tier / spike day / horizon days / 7-15-30 day
                           # totals (None for runs trained before 1.2.9)
                           "segments": bm.get("segments"),
                           "notes": _json(bt["notes_json"], [])}
    return out


def backtest_points(training_run_id: str) -> dict:
    """Recompute the walk-forward backtest of a training run (in memory) and return its evaluation points."""
    with db.read() as c:
        tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (training_run_id,))
        if not tr:
            raise AppError("BATCH_NOT_FOUND", 404, detail=training_run_id)
        bt = db.one(c, "SELECT * FROM backtest_runs WHERE training_run_id=?", (training_run_id,))
        if not bt:
            raise AppError("BATCH_NOT_FOUND", 404, detail=f"no backtest for {training_run_id}")
        if identity.data_state(tr, tr["scope_key"], c)["status"] not in ("SAME_LOAD", "SAME_CONTENT"):
            raise AppError("DATA_CHANGED_SINCE_TRAINING", 409, detail="backtest points cannot be reproduced")
        mape_min = ss.get("quality", c).mape_min_actual
    mcfg = ss.ModelSettings.model_validate((_json(tr["feature_config_json"], {}) or {}).get("config") or {})
    panel = panel_for_run(tr)          # the run's own train_start..train_end
    if panel is None:
        raise AppError("DATA_CHANGED_SINCE_TRAINING", 409, detail="training data no longer available")
    res = model.backtest(panel, mcfg, mape_min, collect=True)
    stored = (_json(bt["metrics_json"], {}) or {}).get("pooled") or {}
    rec = res["metrics"]
    keys = ("n_points", "sum_actual", "sum_forecast", "wape", "bias")
    same = all((stored.get(k) is None and rec.get(k) is None)
               or (stored.get(k) is not None and rec.get(k) is not None and abs(stored[k] - rec[k]) <= 1e-9 * max(1.0, abs(stored[k])))
               for k in keys)
    if not same:
        raise AppError("REPRODUCTION_MISMATCH", 409, detail=f"stored {[(k, stored.get(k)) for k in keys]} "
                                                             f"recomputed {[(k, rec.get(k)) for k in keys]}")
    pts = res["points"]
    dup = Counter((p["sku_id"], p["fc_id"], p["date"]) for p in pts)
    return {"training_run_id": training_run_id, "backtest_id": bt["id"], "points": pts, "metrics": rec,
            "by_method": res["by_method"], "stored_metrics": stored, "folds": res["folds"], "config": res["config"],
            "unique_series_days": len(dup), "series_days_in_two_or_more_folds": sum(1 for v in dup.values() if v > 1)}
