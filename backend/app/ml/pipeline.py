"""Train -> backtest -> quality gate -> publish (immutable forecast run).

A new forecast is published ONLY when data checks and the configured quality gate pass. Otherwise the
previously published forecast stays the current one and the reason is recorded.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta

import numpy as np

from .. import db, paths
from .. import settings_service as ss
from ..data.demand import data_window, fingerprint, load_demand, panel_for_run, resolve_scope
from ..data.quality import build_report
from ..messages import AppError
from ..timeutil import now_iso, now_vn, today_vn
from . import feature_registry as registry
from . import model
from .features import build_panel, feature_names, is_direct

log = logging.getLogger("df.pipeline")


def quality_gate(bt: dict, q) -> dict:
    m, mb = bt["metrics"], bt["baseline_metrics"]
    checks = [
        {"check": "BACKTEST_RELIABLE", "passed": bool(bt["reliable"]), "value": len(bt["folds"]), "threshold": None},
        {"check": "MIN_BACKTEST_POINTS", "passed": m["n_points"] >= q.min_backtest_points, "value": m["n_points"],
         "threshold": q.min_backtest_points},
        {"check": "WAPE_MAX", "passed": m["wape"] is not None and m["wape"] <= q.wape_max, "value": m["wape"],
         "threshold": q.wape_max},
        {"check": "ABS_BIAS_MAX", "passed": m["bias"] is not None and abs(m["bias"]) <= q.abs_bias_max,
         "value": m["bias"], "threshold": q.abs_bias_max},
    ]
    if q.require_beat_baseline:
        checks.append({"check": "BEAT_BASELINE", "passed": (m["wape"] is not None and mb["wape"] is not None
                                                            and m["wape"] < mb["wape"]),
                       "value": m["wape"], "threshold": mb["wape"]})
    return {"passed": all(c["passed"] for c in checks), "checks": checks,
            "thresholds_approved_by_business": q.approved_by_business}


PENDING_REVIEW = "PROMOTION_REVIEW_REQUIRED"
EQUAL_TOLERANCE = 1e-9          # numerical tie only (floating point noise), NOT a business threshold
FOLD_KEYS = ("backtest_folds", "backtest_horizon_days", "backtest_step_days", "min_total_history_days")


def incumbent(scope_key: str, conn) -> dict | None:
    """The model in use for a scope = the training run behind the latest published forecast run of that scope."""
    fr = latest_published(scope_key, conn)
    if not fr:
        return None
    tr = db.one(conn, "SELECT * FROM training_runs WHERE id=?", (fr["training_run_id"],))
    return {"forecast_run": fr, "training_run": tr} if tr else None


def compare_with_incumbent(panel, cand_bt: dict, cand_cfg, inc_tr: dict, qcfg, cancel=None) -> dict:
    """Champion/challenger on the SAME validation set: the incumbent's own configuration (features, LightGBM parameters,
    fallback rules - stored with its training run) is re-fitted walk-forward on exactly the candidate's folds, panel
    (grain SKU x FC x day) and target. Both are scored on identical (series, day) points with the same metrics.
    Verdict: BETTER / WORSE / EQUAL by pooled WAPE (EQUAL = numerical tie only), INSUFFICIENT_DATA when the folds have
    fewer points than quality.min_backtest_points or the incumbent configuration cannot be rebuilt. No business
    threshold is applied here."""
    out = {"method": "WALK_FORWARD_SAME_FOLDS", "incumbent_training_run_id": inc_tr["id"],
           "incumbent_model_version": inc_tr.get("model_version"), "candidate": cand_bt["metrics"],
           "folds": len(cand_bt["folds"]), "fold_config": cand_bt.get("config"),
           "incumbent_metrics_at_its_training": json.loads(inc_tr.get("metrics_json") or "null"),
           "equal_tolerance": EQUAL_TOLERANCE}
    try:
        stored = json.loads(inc_tr.get("feature_config_json") or "{}")["config"]
        inc_cfg = ss.ModelSettings.model_validate({**stored, **{k: getattr(cand_cfg, k) for k in FOLD_KEYS}})
    except Exception as e:  # noqa: BLE001 - old/unknown configuration: no comparison, never a guess
        return {**out, "incumbent": None, "verdict": "INSUFFICIENT_DATA", "reason": "INCUMBENT_CONFIG_UNAVAILABLE",
                "detail": type(e).__name__}
    inc_bt = model.backtest(panel, inc_cfg, qcfg.mape_min_actual, cancel)
    c, i = cand_bt["metrics"], inc_bt["metrics"]
    out["incumbent"] = i
    n = c.get("n_points") or 0
    if not cand_bt["folds"] or not inc_bt["folds"] or n != (i.get("n_points") or 0) or n < qcfg.min_backtest_points \
            or c.get("wape") is None or i.get("wape") is None:
        return {**out, "verdict": "INSUFFICIENT_DATA", "reason": "TOO_FEW_EVALUATION_POINTS",
                "points": n, "required": qcfg.min_backtest_points}
    d = c["wape"] - i["wape"]
    out["delta"] = {"wape": d, "bias": (c.get("bias") or 0) - (i.get("bias") or 0),
                    "abs_bias": abs(c.get("bias") or 0) - abs(i.get("bias") or 0),
                    "mae": (c.get("mae") or 0) - (i.get("mae") or 0)}
    out["verdict"] = "EQUAL" if abs(d) <= EQUAL_TOLERANCE else ("BETTER" if d < 0 else "WORSE")
    return out


def latest_published(scope_key: str | None = None, conn=None) -> dict | None:
    sql = "SELECT * FROM forecast_runs"
    params: tuple = ()
    if scope_key:
        sql += " WHERE scope_key=?"
        params = (scope_key,)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT 1"
    if conn is not None:
        return db.one(conn, sql, params)
    with db.read() as c:
        return db.one(c, sql, params)


def _publish_run(c, *, fr_id: str, training_run_id: str, version: str, scope: dict, panel, fc, details: dict,
                 horizons: list[int], max_h: int, job_id: str | None, mcfg, derived_from: str | None = None) -> int:
    """Insert one immutable forecast run (values + per-series explanation metadata) inside transaction c."""
    origin = (panel.dates[-1] + timedelta(days=1)).date()
    methods = fc["methods"]
    counts = {str(k): int(v) for k, v in zip(*np.unique(methods, return_counts=True))}
    vals, metas = [], []
    for s, (sku, fcid) in enumerate(panel.keys):
        fb = None if methods[s] == model.METHOD_LGBM else methods[s]
        for h, dte in enumerate(fc["dates"]):
            vals.append((fr_id, sku, fcid, str(dte.date()), h + 1, float(round(fc["yhat"][s, h], 4)),
                         str(methods[s]), fb))
        m = model.series_meta(panel, mcfg, details, s)
        metas.append((fr_id, sku, fcid, m["method"], m["reason_code"], json.dumps(m)))
    c.execute("INSERT INTO forecast_runs(id, training_run_id, model_version, scope_key, data_source, "
              "forecast_origin, data_as_of, horizons_json, max_horizon, n_series, method_counts_json, status, "
              "created_at, job_id, derived_from_run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'PUBLISHED', ?, ?, ?)",
              (fr_id, training_run_id, version, scope["scope_key"], scope["data_source"], str(origin),
               str(panel.dates[-1].date()), json.dumps(sorted(horizons)), max_h, panel.n_series, json.dumps(counts),
               now_iso(), job_id, derived_from))
    c.executemany("INSERT INTO forecast_values(run_id, sku_id, fc_id, target_date, horizon_day, yhat, method, "
                  "fallback_reason) VALUES (?,?,?,?,?,?,?,?)", vals)
    c.executemany("INSERT INTO forecast_series_meta(run_id, sku_id, fc_id, method, reason_code, details_json) "
                  "VALUES (?,?,?,?,?,?)", metas)
    db.audit(c, "FORECAST_PUBLISHED", "forecast_run", fr_id,
             {"model_version": version, "rows": len(vals), "derived_from": derived_from})
    db.alert(c, "INFO", "FORECAST_PUBLISHED", {"forecast_run_id": fr_id, "model_version": version},
             "forecast_run", fr_id)
    return len(vals)


def data_lineage(c, scope: dict) -> dict:
    """Where the training data of a scope comes from. Metadata only: no credentials, no raw records."""
    sk = scope["scope_key"]
    r = c.execute("SELECT MIN(order_date), MAX(order_date), COUNT(*), COALESCE(SUM(qty), 0), COUNT(DISTINCT sku_id), "
                  "COUNT(DISTINCT fc_id), MAX(loaded_at) FROM demand_daily WHERE scope_key=?", (sk,)).fetchone()
    out = {"data_source": scope["data_source"], "scope_key": sk, "label": scope.get("label"),
           "grain": "SKU × FC × ngày (target = Σ order_qty của các dòng hợp lệ)",
           "demand_daily": {"min_date": r[0], "max_date": r[1], "rows": r[2], "qty_sum": r[3], "n_sku": r[4],
                            "n_fc": r[5], "loaded_at": r[6]}}
    if scope["data_source"] in ("DEMO", "MANUAL_IMPORT"):
        b = db.one(c, "SELECT id, file_name, file_sha256, sheet_name, total_rows, valid_rows, error_rows, duplicate_rows, "
                      "min_order_date, max_order_date, created_at, confirmed_at, column_mapping_json FROM import_batches "
                      "WHERE id=?", (sk,))
        if b:
            cm = json.loads(b.pop("column_mapping_json") or "null")
            out["source_ref"] = {**b, "column_mapping": cm}
            out["target_mapping"] = {"field": "order_qty",
                                     "column": (cm or {}).get("order_qty", "order_qty") if isinstance(cm, dict) else "order_qty"}
            out["fetched_at"] = b["created_at"]
    else:
        from ..bq import connector
        bq = ss.get("bigquery", c)
        st = db.one(c, "SELECT value_json FROM sync_state WHERE name=?", (f"last_d1_sync:{sk}",))
        st = json.loads(st["value_json"]) if st else None
        v = connector.validation_state(c) or {}
        out["source_ref"] = {
            "table": f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}", "location": bq.location,
            "mapping_hash": connector.mapping_hash(bq), "history_start_date": bq.history_start_date,
            "exact_duplicate_policy": bq.exact_duplicate_policy,
            "field_mapping": {k: m.column for k, m in bq.field_mapping.items() if m.column and m.usage != "UNUSED"},
            "reference_mapping": {k: m.column for k, m in bq.reference_mapping.items() if m.column and m.usage != "UNUSED"},
            "last_sync": st, "validation": {k: v.get(k) for k in ("checked_at", "passed", "mapping_hash", "range",
                                                                  "reconciliation", "exclusions")}}
        out["target_mapping"] = {"field": "order_qty", "column": bq.field_mapping["order_qty"].column}
        out["fetched_at"] = (st or {}).get("synced_at")
    return out


def train_and_publish(job_id: str | None = None, force: bool = False, cancel=None, source: str | None = None,
                      progress=None) -> dict:
    """Returns {status: PUBLISHED|REJECTED|SKIPPED|FAILED, reason_code, training_run_id, forecast_run_id}.

    progress(stage) is called at each real pipeline stage (see jobs/progress.py STAGES)."""
    stage = progress or (lambda *a, **k: None)
    stage("VALIDATING_DATA")
    with db.read() as c:
        scope = resolve_scope(c, source)
        mcfg_settings = ss.get("model", c)
        qcfg = ss.get("quality", c)
        hcfg = ss.get("horizons", c)
        fp = fingerprint(scope["scope_key"], c)
        # last model trained on this data: the accepted one in use OR a candidate still waiting for review
        last_ok = db.one(c, "SELECT id, data_fingerprint FROM training_runs WHERE scope_key=? AND (status='ACCEPTED' "
                            "OR (status='REJECTED' AND reject_reason=?)) ORDER BY started_at DESC, rowid DESC LIMIT 1",
                         (scope["scope_key"], PENDING_REVIEW))
        cov = registry.coverage(c, scope["scope_key"])
        window = data_window(c)
    if scope["data_source"] == "BIGQUERY":
        from ..bq import connector
        bq = ss.get("bigquery")
        if not bq.production_enabled:
            raise AppError("SOURCE_NOT_READY", 409)
        if not connector.validation_ok_for_current():
            raise AppError("BQ_VALIDATION_REQUIRED", 409, mapping_hash=connector.mapping_hash(bq))
    if not force and last_ok and last_ok["data_fingerprint"] == fp:
        return {"status": "SKIPPED", "reason_code": "NO_NEW_DATA", "training_run_id": last_ok["id"]}
    # feature groups without real data in this scope are removed (never filled with invented values); the RESOLVED
    # switches are stored with the run so the model is always rebuilt/explained with exactly its own feature list
    mcfg, decisions = registry.resolve(mcfg_settings, cov)
    names = feature_names(mcfg)
    if is_direct(mcfg) and max(hcfg.enabled) > model.direct_max_horizon(mcfg):
        raise AppError("DIRECT_HORIZON_EXCEEDS_TRAINING", 409,
                       detail=f"enabled horizon {max(hcfg.enabled)} > {model.direct_max_horizon(mcfg)} days")
    with db.read() as c:
        lineage = data_lineage(c, scope)

    with db.tx() as c:
        report = build_report(scope, c)
    run_id = db.new_id("TRN")
    started = now_iso()
    fcfg = mcfg.model_dump()
    with db.tx() as c:
        c.execute("INSERT INTO training_runs(id, scope_key, data_source, data_fingerprint, status, started_at, "
                  "feature_config_json, params_json, job_id) VALUES (?,?,?,?, 'RUNNING', ?,?,?,?)",
                  (run_id, scope["scope_key"], scope["data_source"], fp, started,
                   json.dumps({"features": names, "config": fcfg,
                               # 1.2.0: groups as chosen in the UI and as actually used, + identity of the configuration
                               "feature_groups": {
                                   "historical_demand": {"switch_on": bool(mcfg_settings.feature_lags or mcfg_settings.feature_rolling),
                                                         "used": bool(mcfg.feature_lags or mcfg.feature_rolling)},
                                   "price": {"switch_on": bool(mcfg_settings.feature_price),
                                             "used": bool(decisions.get("price", {}).get("used"))}},
                               "forecast_strategy": mcfg.forecast_strategy,
                               "config_fingerprint": hashlib.sha256(json.dumps(fcfg, sort_keys=True).encode()).hexdigest()[:16],
                               "feature_set_version": registry.feature_set_version(names),
                               "registry_version": registry.REGISTRY_VERSION,
                               "settings_switches": {k: getattr(mcfg_settings, k) for k in (
                                   "feature_lags", "feature_rolling", "feature_calendar", "feature_price",
                                   "feature_discount", "feature_promotion")},
                               "feature_decisions": decisions, "lineage": lineage, "data_window": window},
                              default=str),
                   json.dumps(model.lgb_params(mcfg)), job_id))

    def finish(status: str, reason: str | None, **cols):
        sets = ["status=?", "finished_at=?", "reject_reason=?"] + [f"{k}=?" for k in cols]
        with db.tx() as c:
            c.execute(f"UPDATE training_runs SET {', '.join(sets)} WHERE id=?",
                      (status, now_iso(), reason, *cols.values(), run_id))
            if status == "REJECTED":
                db.alert(c, "WARNING", reason or "QUALITY_GATE_FAILED", {"training_run_id": run_id},
                         "training_run", run_id)
            elif status == "FAILED":
                db.alert(c, "ERROR", reason or "TRAINING_FAILED",
                         {"training_run_id": run_id, "error": cols.get("error")}, "training_run", run_id)
            db.audit(c, f"TRAINING_{status}", "training_run", run_id, {"reason": reason})

    current = {"stage": "VALIDATING_DATA"}

    def at(s):
        current["stage"] = s
        stage(s)

    try:
        if not report["can_train"]:
            finish("REJECTED", "DATA_NOT_TRAINABLE", quality_gate_json=json.dumps({"data_report_id": report.get("id")}))
            return {"status": "REJECTED", "reason_code": "DATA_NOT_TRAINABLE", "training_run_id": run_id}
        if not report["can_publish"]:
            finish("REJECTED", "STALE_DATA_BLOCKED", quality_gate_json=json.dumps({"data_report_id": report.get("id")}))
            return {"status": "REJECTED", "reason_code": "STALE_DATA_BLOCKED", "training_run_id": run_id}

        at("PREPARING_DATA")
        # model input = the data window only (complete VN days from window_start_date to yesterday)
        demand = load_demand(scope["scope_key"], start=window["start"], end=window["end"])
        panel = build_panel(demand, max_days=mcfg.max_train_days)
        log.info("training window", extra={"ctx": {"training_run_id": run_id, "window": window["start"] + ".." +
                                                   window["end"], "panel": f"{panel.dates[0].date()}..{panel.dates[-1].date()}",
                                                   "series": panel.n_series}})
        at("BACKTESTING")
        bt = model.backtest(panel, mcfg, qcfg.mape_min_actual, cancel)
        at("TRAINING")
        booster, info = model.train(panel, mcfg, cancel)
        at("QUALITY_GATE")
        gate = quality_gate(bt, qcfg)
        if booster is None:
            gate["passed"] = False
            gate["checks"].append({"check": "MODEL_TRAINED", "passed": False, "value": info.get("error")})
        bt_id = db.new_id("BT")
        common = dict(train_start=str(panel.dates[0].date()), train_end=str(panel.dates[-1].date()),
                      n_series=panel.n_series, n_rows=info["n_rows"],
                      metrics_json=json.dumps(bt["metrics"]), baseline_metrics_json=json.dumps(bt["baseline_metrics"]),
                      quality_gate_json=json.dumps(gate),
                      feature_importance_json=json.dumps(info.get("feature_importance", [])[:30]))
        with db.tx() as c:
            c.execute("INSERT INTO backtest_runs(id, training_run_id, created_at, config_json, folds_json, metrics_json, "
                      "reliable, notes_json) VALUES (?,?,?,?,?,?,?,?)",
                      (bt_id, run_id, now_iso(), json.dumps(bt.get("config", {})), json.dumps(bt["folds"]),
                       json.dumps({"pooled": bt["metrics"], "baseline": bt["baseline_metrics"],
                                   "by_method": bt["by_method"]}), int(bt["reliable"]), json.dumps(bt["notes"])))
        if not gate["passed"]:
            if booster is not None:
                # model file kept (hash recorded) so the run can be reviewed; it is published only through an
                # explicit, documented gate exception for THIS run (release_with_gate_exception), never automatically
                version, mpath, sha = _save_model(booster, names, panel, common["train_end"], scope, run_id, mcfg)
                common.update(model_version=version, model_path=mpath.name, model_sha256=sha)
            finish("REJECTED", "QUALITY_GATE_FAILED", **common)
            return {"status": "REJECTED", "reason_code": "QUALITY_GATE_FAILED", "training_run_id": run_id,
                    "quality_gate": gate}

        # forecast for the longest enabled horizon, starting the day after the last data day
        max_h = max(hcfg.enabled)
        if panel.n_series * max_h > hcfg.max_forecast_rows:
            finish("REJECTED", "FORECAST_TOO_LARGE", **common)
            return {"status": "REJECTED", "reason_code": "FORECAST_TOO_LARGE", "training_run_id": run_id}
        # incumbent protection: a model already in use is never replaced automatically (no approved promotion rule)
        with db.read() as c:
            inc = incumbent(scope["scope_key"], c)
        promotion = {"policy": "MANUAL_REVIEW", "decided_at": now_iso()}
        if inc:
            promotion.update(compare_with_incumbent(panel, bt, mcfg, inc["training_run"], qcfg, cancel))
        else:
            promotion.update(decision="INITIAL_MODEL", note="no model in use for this scope: nothing to protect")
        gate["promotion"] = promotion
        common["quality_gate_json"] = json.dumps(gate)
        version, mpath, sha = _save_model(booster, names, panel, common["train_end"], scope, run_id, mcfg)
        if inc:
            promotion["decision"] = "REVIEW_REQUIRED"
            gate["promotion"] = promotion
            common["quality_gate_json"] = json.dumps(gate)
            with db.tx() as c:   # kept as a reviewable candidate: model file + metrics + comparison, NOT published
                c.execute("UPDATE training_runs SET status='REJECTED', finished_at=?, reject_reason=?, model_version=?, "
                          "model_path=?, model_sha256=?, train_start=?, train_end=?, n_series=?, n_rows=?, "
                          "metrics_json=?, baseline_metrics_json=?, quality_gate_json=?, feature_importance_json=? "
                          "WHERE id=?",
                          (now_iso(), PENDING_REVIEW, version, mpath.name, sha, common["train_start"],
                           common["train_end"], common["n_series"], common["n_rows"], common["metrics_json"],
                           common["baseline_metrics_json"], common["quality_gate_json"],
                           common["feature_importance_json"], run_id))
                db.alert(c, "INFO", "CANDIDATE_READY_FOR_REVIEW",
                         {"training_run_id": run_id, "verdict": promotion.get("verdict"),
                          "incumbent_training_run_id": inc["training_run"]["id"]}, "training_run", run_id)
                db.audit(c, "TRAINING_CANDIDATE", "training_run", run_id,
                         {"verdict": promotion.get("verdict"), "incumbent": inc["training_run"]["id"]})
            log.info("candidate kept for review", extra={"ctx": {"training_run_id": run_id,
                                                                 "verdict": promotion.get("verdict")}})
            return {"status": "CANDIDATE", "reason_code": PENDING_REVIEW, "training_run_id": run_id,
                    "model_version": version, "verdict": promotion.get("verdict"),
                    "incumbent_training_run_id": inc["training_run"]["id"],
                    "published_forecast_run_id": inc["forecast_run"]["id"]}
        at("FORECASTING")
        details = model.classification_details(panel, mcfg)
        fc = model.forecast(panel, booster, mcfg, max_h, cancel)
        if cancel and cancel():
            raise model.Cancelled()
        at("PUBLISHING")
        fr_id = db.new_id("FCR")
        with db.tx() as c:   # training acceptance and the new forecast run are committed together (or not at all)
            c.execute("UPDATE training_runs SET status='ACCEPTED', finished_at=?, model_version=?, model_path=?, "
                      "model_sha256=?, train_start=?, train_end=?, n_series=?, n_rows=?, metrics_json=?, "
                      "baseline_metrics_json=?, quality_gate_json=?, feature_importance_json=? WHERE id=?",
                      (now_iso(), version, mpath.name, sha, common["train_start"], common["train_end"],
                       common["n_series"], common["n_rows"], common["metrics_json"], common["baseline_metrics_json"],
                       common["quality_gate_json"], common["feature_importance_json"], run_id))
            n = _publish_run(c, fr_id=fr_id, training_run_id=run_id, version=version, scope=scope, panel=panel,
                             fc=fc, details=details, horizons=hcfg.enabled, max_h=max_h, job_id=job_id, mcfg=mcfg)
        log.info("forecast published", extra={"ctx": {"forecast_run_id": fr_id, "training_run_id": run_id,
                                                      "model_version": version, "rows": n}})
        return {"status": "PUBLISHED", "reason_code": "FORECAST_PUBLISHED", "training_run_id": run_id,
                "forecast_run_id": fr_id, "model_version": version, "training_status": "ACCEPTED"}
    except model.Cancelled:
        finish("FAILED", "TIMEOUT", error="cancelled (timeout)")
        raise
    except Exception as e:
        reason = "PUBLISH_FAILED" if current["stage"] == "PUBLISHING" else "TRAINING_FAILED"
        log.exception("training/publish failed", extra={"ctx": {"training_run_id": run_id, "stage": current["stage"]}})
        finish("FAILED", reason, error=f"{type(e).__name__}: {e}"[:2000])
        return {"status": "FAILED", "reason_code": reason, "failed_stage": current["stage"],
                "training_run_id": run_id, "error": f"{type(e).__name__}: {e}"}


def _save_model(booster, names: list[str], panel, train_end: str, scope: dict, run_id: str, mcfg):
    """Model file + metadata (feature list, codes, strategy) in the models folder; returns (version, path, sha256)."""
    version = f"MV-{now_vn():%Y%m%d-%H%M%S}-{run_id[-4:]}"
    mpath = paths.models_dir() / f"{version}.txt"
    booster.save_model(str(mpath))
    sha = hashlib.sha256(mpath.read_bytes()).hexdigest()
    meta = {"model_version": version, "features": names, "sku_codes": panel.sku_codes,
            "fc_codes": panel.fc_codes, "train_end": train_end,
            "feature_set_version": registry.feature_set_version(names), "training_run_id": run_id,
            "data_source": scope["data_source"], "scope_key": scope["scope_key"],
            "forecast_strategy": "DIRECT" if is_direct(mcfg) else "RECURSIVE",
            "max_horizon": model.direct_max_horizon(mcfg) if is_direct(mcfg) else None}
    (paths.models_dir() / f"{version}.json").write_text(json.dumps(meta), encoding="utf-8")
    return version, mpath, sha


def extend_forecast(run_id: str, job_id: str | None = None, cancel=None, progress=None) -> dict:
    """New immutable forecast run with the CURRENTLY configured horizons, produced by the SAME accepted model from
    the SAME data (no retraining). Refused unless the data fingerprint and the model file hash match the training
    run and the recomputed overlap reproduces the original run exactly. The original run is never modified."""
    stage = progress or (lambda *a, **k: None)
    stage("VERIFYING_MODEL")
    with db.read() as c:
        run = db.one(c, "SELECT * FROM forecast_runs WHERE id=?", (run_id,))
        if not run:
            raise AppError("BATCH_NOT_FOUND", 404, detail=run_id)
        tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (run["training_run_id"],))
        hcfg = ss.get("horizons", c)
        cur_fp = fingerprint(run["scope_key"], c)
    want = sorted(set(hcfg.enabled))
    have = json.loads(run["horizons_json"] or "[]")
    new_max = max(want)
    if new_max <= run["max_horizon"]:
        raise AppError("NOTHING_TO_EXTEND", 409, detail=f"run covers {run['max_horizon']} days; configured {want}")
    if not tr or tr["status"] != "ACCEPTED" or not tr["model_path"]:
        raise AppError("MODEL_ARTIFACT_MISSING", 409, detail="training run not accepted")
    if tr["data_fingerprint"] != cur_fp:
        raise AppError("DATA_CHANGED_SINCE_TRAINING", 409,
                       detail="the dataset changed after this model was trained - run Train & forecast instead")
    mpath = paths.models_dir() / tr["model_path"]
    if not mpath.exists() or hashlib.sha256(mpath.read_bytes()).hexdigest() != tr["model_sha256"]:
        raise AppError("MODEL_ARTIFACT_MISSING", 409, detail=f"{tr['model_path']} missing or modified")
    mcfg = ss.ModelSettings.model_validate(json.loads(tr["feature_config_json"])["config"])
    if is_direct(mcfg) and new_max > model.direct_max_horizon(mcfg):
        raise AppError("DIRECT_HORIZON_EXCEEDS_TRAINING", 409,
                       detail=f"{new_max} > {model.direct_max_horizon(mcfg)} days the model was trained for")
    if hcfg.max_forecast_rows < run["n_series"] * new_max:
        raise AppError("FORECAST_TOO_LARGE", 422)
    stage("PREPARING_DATA")
    panel = panel_for_run(tr)          # the training run's own range, whatever the current window settings are
    if panel is None or str(panel.dates[-1].date()) != run["data_as_of"]:
        raise AppError("DATA_CHANGED_SINCE_TRAINING", 409, detail="data_as_of differs")
    stage("FORECASTING")
    import lightgbm as lgb
    booster = lgb.Booster(model_file=str(mpath))
    details = model.classification_details(panel, mcfg)
    fc = model.forecast(panel, booster, mcfg, new_max, cancel)
    # reproduction check: every published value of the original run must be reproduced exactly
    with db.read() as c:
        old = db.rows(c, "SELECT sku_id, fc_id, horizon_day, yhat, method FROM forecast_values WHERE run_id=?",
                      (run_id,))
    idx = {k: i for i, k in enumerate(panel.keys)}
    bad = 0
    for r in old:
        s = idx.get((r["sku_id"], r["fc_id"]))
        if (s is None or str(fc["methods"][s]) != r["method"]
                or abs(round(float(fc["yhat"][s, r["horizon_day"] - 1]), 4) - r["yhat"]) > 1e-4):
            bad += 1
    if bad or len(old) != run["n_series"] * run["max_horizon"]:
        raise AppError("REPRODUCTION_MISMATCH", 409, detail=f"{bad} of {len(old)} published values not reproduced")
    stage("PUBLISHING")
    fr_id = db.new_id("FCR")
    scope = {"scope_key": run["scope_key"], "data_source": run["data_source"]}
    with db.tx() as c:
        _publish_run(c, fr_id=fr_id, training_run_id=tr["id"], version=run["model_version"], scope=scope,
                     panel=panel, fc=fc, details=details, horizons=want, max_h=new_max, job_id=job_id, mcfg=mcfg,
                     derived_from=run_id)
    return {"status": "PUBLISHED", "reason_code": "FORECAST_EXTENDED", "forecast_run_id": fr_id,
            "derived_from_run_id": run_id, "model_version": run["model_version"], "horizons": want,
            "previous_horizons": have, "reproduced_values": len(old)}


def promote_candidate(training_run_id: str, cancel=None) -> dict:
    """Explicit user decision: publish a candidate kept for review. Refused unless it is still a candidate, no newer
    model was accepted for its scope, its data fingerprint equals the current data and its model file is intact.
    The forecast is computed from the candidate's own panel (train_start..train_end) - exactly what would have been
    published at training time. The previous model and all its forecasts are kept unchanged."""
    with db.read() as c:
        tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (training_run_id,))
        if not tr:
            raise AppError("BATCH_NOT_FOUND", 404, detail=training_run_id)
        if tr["status"] != "REJECTED" or tr["reject_reason"] != PENDING_REVIEW:
            raise AppError("PROMOTION_NOT_ALLOWED", 409, detail=f"{tr['status']} {tr['reject_reason'] or ''}".strip())
        newer = db.one(c, "SELECT id FROM training_runs WHERE scope_key=? AND status='ACCEPTED' AND rowid > "
                          "(SELECT rowid FROM training_runs WHERE id=?)", (tr["scope_key"], training_run_id))
        if newer:
            raise AppError("PROMOTION_NOT_ALLOWED", 409, detail=f"superseded by {newer['id']}")
        busy = db.one(c, "SELECT id FROM job_runs WHERE job_type IN ('TRAIN_PUBLISH','FORECAST_EXTEND') AND "
                         "status IN ('PENDING','RUNNING')")
        if busy:
            raise AppError("LOCKED", 409, detail=busy["id"])
        cur_fp = fingerprint(tr["scope_key"], c)
        hcfg = ss.get("horizons", c)
        inc = incumbent(tr["scope_key"], c)
    if tr["data_fingerprint"] != cur_fp:
        raise AppError("DATA_CHANGED_SINCE_TRAINING", 409, detail="the data changed after this candidate was trained")
    mpath = paths.models_dir() / (tr["model_path"] or "")
    if not tr["model_path"] or not mpath.exists() or hashlib.sha256(mpath.read_bytes()).hexdigest() != tr["model_sha256"]:
        raise AppError("MODEL_ARTIFACT_MISSING", 409, detail=f"{tr['model_path']} missing or modified")
    mcfg = ss.ModelSettings.model_validate(json.loads(tr["feature_config_json"])["config"])
    panel = panel_for_run(tr)
    if panel is None:
        raise AppError("DATA_CHANGED_SINCE_TRAINING", 409, detail="training data no longer available")
    max_h = max(hcfg.enabled)
    if panel.n_series * max_h > hcfg.max_forecast_rows:
        raise AppError("FORECAST_TOO_LARGE", 422)
    import lightgbm as lgb
    booster = lgb.Booster(model_file=str(mpath))
    details = model.classification_details(panel, mcfg)
    fc = model.forecast(panel, booster, mcfg, max_h, cancel)
    gate = json.loads(tr["quality_gate_json"] or "{}")
    prom = gate.get("promotion") or {}
    prom.update(decision="PROMOTED_BY_USER", promoted_at=now_iso(),
                replaced_training_run_id=(inc or {}).get("training_run", {}).get("id"))
    gate["promotion"] = prom
    fr_id = db.new_id("FCR")
    scope = {"scope_key": tr["scope_key"], "data_source": tr["data_source"]}
    with db.tx() as c:
        cur = c.execute("UPDATE training_runs SET status='ACCEPTED', reject_reason=NULL, quality_gate_json=? "
                        "WHERE id=? AND status='REJECTED' AND reject_reason=?",
                        (json.dumps(gate), training_run_id, PENDING_REVIEW))
        if cur.rowcount != 1:
            raise AppError("PROMOTION_NOT_ALLOWED", 409, detail="state changed")
        n = _publish_run(c, fr_id=fr_id, training_run_id=training_run_id, version=tr["model_version"], scope=scope,
                         panel=panel, fc=fc, details=details, horizons=hcfg.enabled, max_h=max_h, job_id=None,
                         mcfg=mcfg)
        db.audit(c, "MODEL_PROMOTED", "training_run", training_run_id,
                 {"verdict": prom.get("verdict"), "replaced": prom.get("replaced_training_run_id"),
                  "forecast_run_id": fr_id})
    log.info("candidate promoted", extra={"ctx": {"training_run_id": training_run_id, "forecast_run_id": fr_id,
                                                  "rows": n}})
    return {"status": "PUBLISHED", "reason_code": "MODEL_PROMOTED", "training_run_id": training_run_id,
            "forecast_run_id": fr_id, "model_version": tr["model_version"], "verdict": prom.get("verdict"),
            "replaced_training_run_id": prom.get("replaced_training_run_id")}


GATE_METRIC_CHECKS = ("WAPE_MAX", "ABS_BIAS_MAX")


def exception_eligible(tr: dict | None) -> dict:
    """Can this training run be released through a documented quality-gate exception? Only a run REJECTED by the gate
    whose ONLY failed checks are the metric thresholds (WAPE_MAX / ABS_BIAS_MAX) and whose model file was kept."""
    if not tr:
        return {"eligible": False, "reason": "NOT_FOUND"}
    if tr["status"] != "REJECTED" or tr.get("reject_reason") != "QUALITY_GATE_FAILED":
        return {"eligible": False, "reason": f"{tr['status']} {tr.get('reject_reason') or ''}".strip()}
    if not tr.get("model_path"):
        return {"eligible": False, "reason": "NO_MODEL_FILE"}
    gate = json.loads(tr.get("quality_gate_json") or "{}")
    failed = [c["check"] for c in gate.get("checks", []) if not c.get("passed")]
    other = [c for c in failed if c not in GATE_METRIC_CHECKS]
    if not failed or other:
        return {"eligible": False, "reason": "NON_METRIC_CHECK_FAILED", "failed_checks": failed}
    return {"eligible": True, "failed_checks": failed}


def release_with_gate_exception(training_run_id: str, approval: dict, cancel=None) -> dict:
    """Documented, owner-approved exception for ONE training run (1.2.0). The standard quality gate and its thresholds
    are NOT changed and no other run is affected: every later run (scheduled or manual) goes through the normal gate
    and the incumbent protection. Refused unless the run is exception_eligible, its model file is intact, its data
    fingerprint equals the current data, no newer model was accepted for its scope and no training / extension job is
    running. The approval must give the approver, a business reason, a future review date, the confirmation text
    EXCEPTION-<run id> and restate the run's own backtest WAPE and bias (3 decimals): the approver signs the real
    numbers. The forecast is computed from the run's own panel, exactly as at training time."""
    approved_by = str(approval.get("approved_by") or "").strip()
    reason = str(approval.get("reason") or "").strip()
    if approval.get("confirm_text") != f"EXCEPTION-{training_run_id}":
        raise AppError("CONFIRMATION_MISMATCH", 422, detail=f"type EXCEPTION-{training_run_id}")
    if len(approved_by) < 3 or len(reason) < 20:
        raise AppError("VALIDATION_ERROR", 422, detail="approved_by (>= 3 characters) and a business reason "
                                                       "(>= 20 characters) are required")
    try:
        review_by = date.fromisoformat(str(approval.get("review_by")))
    except ValueError:
        raise AppError("VALIDATION_ERROR", 422, detail="review_by must be a date YYYY-MM-DD") from None
    if review_by <= today_vn():
        raise AppError("VALIDATION_ERROR", 422, detail="review_by must be a future date")
    with db.read() as c:
        tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (training_run_id,))
        if not tr:
            raise AppError("BATCH_NOT_FOUND", 404, detail=training_run_id)
        elig = exception_eligible(tr)
        if not elig["eligible"]:
            raise AppError("PROMOTION_NOT_ALLOWED", 409, detail=f"not eligible for a gate exception: {elig}")
        newer = db.one(c, "SELECT id FROM training_runs WHERE scope_key=? AND status='ACCEPTED' AND rowid > "
                          "(SELECT rowid FROM training_runs WHERE id=?)", (tr["scope_key"], training_run_id))
        if newer:
            raise AppError("PROMOTION_NOT_ALLOWED", 409, detail=f"superseded by {newer['id']}")
        busy = db.one(c, "SELECT id FROM job_runs WHERE job_type IN ('TRAIN_PUBLISH','FORECAST_EXTEND') AND "
                         "status IN ('PENDING','RUNNING')")
        if busy:
            raise AppError("LOCKED", 409, detail=busy["id"])
        cur_fp = fingerprint(tr["scope_key"], c)
        hcfg = ss.get("horizons", c)
        inc = incumbent(tr["scope_key"], c)
    m = json.loads(tr["metrics_json"] or "{}")
    try:
        ack = (round(float(approval.get("acknowledged_wape")), 3), round(float(approval.get("acknowledged_bias")), 3))
    except (TypeError, ValueError):
        raise AppError("VALIDATION_ERROR", 422, detail="acknowledged_wape / acknowledged_bias are required") from None
    if ack != (round(m["wape"], 3), round(m["bias"], 3)):
        raise AppError("VALIDATION_ERROR", 422, detail=f"acknowledged metrics {ack} differ from the run's backtest "
                                                       f"({round(m['wape'], 3)}, {round(m['bias'], 3)})")
    if tr["data_fingerprint"] != cur_fp:
        raise AppError("DATA_CHANGED_SINCE_TRAINING", 409, detail="the data changed after this run was trained")
    mpath = paths.models_dir() / tr["model_path"]
    if not mpath.exists() or hashlib.sha256(mpath.read_bytes()).hexdigest() != tr["model_sha256"]:
        raise AppError("MODEL_ARTIFACT_MISSING", 409, detail=f"{tr['model_path']} missing or modified")
    mcfg = ss.ModelSettings.model_validate(json.loads(tr["feature_config_json"])["config"])
    panel = panel_for_run(tr)
    if panel is None:
        raise AppError("DATA_CHANGED_SINCE_TRAINING", 409, detail="training data no longer available")
    max_h = max(hcfg.enabled)
    if panel.n_series * max_h > hcfg.max_forecast_rows:
        raise AppError("FORECAST_TOO_LARGE", 422)
    if is_direct(mcfg) and max_h > model.direct_max_horizon(mcfg):
        raise AppError("DIRECT_HORIZON_EXCEEDS_TRAINING", 409, detail=f"{max_h} > {model.direct_max_horizon(mcfg)}")
    import lightgbm as lgb
    booster = lgb.Booster(model_file=str(mpath))
    details = model.classification_details(panel, mcfg)
    fc = model.forecast(panel, booster, mcfg, max_h, cancel)
    gate = json.loads(tr["quality_gate_json"] or "{}")
    thresholds = {c["check"]: c.get("threshold") for c in gate.get("checks", []) if c["check"] in GATE_METRIC_CHECKS}
    exc = {"type": "QUALITY_GATE_EXCEPTION", "scope": "THIS_TRAINING_RUN_ONLY", "training_run_id": training_run_id,
           "model_version": tr["model_version"], "approved_by": approved_by, "reason": reason,
           "approved_at": now_iso(), "review_by": str(review_by), "failed_checks": elig["failed_checks"],
           "metrics": {"wape": m.get("wape"), "bias": m.get("bias"), "n_points": m.get("n_points")},
           "baseline_metrics": json.loads(tr["baseline_metrics_json"] or "null"),
           "standard_thresholds": thresholds, "standard_gate_changed": False,
           "forecast_strategy": "DIRECT" if is_direct(mcfg) else "RECURSIVE"}
    gate["exception"] = exc
    gate["promotion"] = {**(gate.get("promotion") or {}), "policy": "GATE_EXCEPTION",
                         "decision": "RELEASED_WITH_GATE_EXCEPTION", "decided_at": exc["approved_at"],
                         "replaced_training_run_id": (inc or {}).get("training_run", {}).get("id")}
    fr_id = db.new_id("FCR")
    scope = {"scope_key": tr["scope_key"], "data_source": tr["data_source"]}
    with db.tx() as c:
        cur = c.execute("UPDATE training_runs SET status='ACCEPTED', reject_reason=NULL, quality_gate_json=? "
                        "WHERE id=? AND status='REJECTED' AND reject_reason='QUALITY_GATE_FAILED'",
                        (json.dumps(gate), training_run_id))
        if cur.rowcount != 1:
            raise AppError("PROMOTION_NOT_ALLOWED", 409, detail="state changed")
        n = _publish_run(c, fr_id=fr_id, training_run_id=training_run_id, version=tr["model_version"], scope=scope,
                         panel=panel, fc=fc, details=details, horizons=hcfg.enabled, max_h=max_h, job_id=None,
                         mcfg=mcfg)
        db.audit(c, "MODEL_RELEASED_WITH_GATE_EXCEPTION", "training_run", training_run_id,
                 {k: exc[k] for k in ("approved_by", "reason", "review_by", "failed_checks", "metrics",
                                      "standard_thresholds")} | {"forecast_run_id": fr_id})
        db.alert(c, "WARNING", "QUALITY_GATE_EXCEPTION_ACTIVE",
                 {"training_run_id": training_run_id, "model_version": tr["model_version"],
                  "review_by": exc["review_by"]}, "training_run", training_run_id)
    log.info("released with gate exception", extra={"ctx": {"training_run_id": training_run_id,
                                                             "forecast_run_id": fr_id, "rows": n}})
    return {"status": "PUBLISHED", "reason_code": "RELEASED_WITH_GATE_EXCEPTION", "training_run_id": training_run_id,
            "forecast_run_id": fr_id, "model_version": tr["model_version"], "exception": exc,
            "replaced_training_run_id": gate["promotion"]["replaced_training_run_id"]}
