"""Training runs, model performance, published forecast runs and the dashboard."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from .. import db
from .. import settings_service as ss
from ..data import intraday
from ..data.demand import resolve_scope
from ..data.excel_io import dataframe_to_xlsx
from ..messages import AppError
from ..ml import metrics as mt
from ..ml import pipeline
from ..timeutil import today_vn
from . import background

router = APIRouter(prefix="/api")
_JSON_COLS = ("feature_config_json", "params_json", "metrics_json", "baseline_metrics_json", "quality_gate_json",
              "feature_importance_json", "horizons_json", "method_counts_json", "config_json", "folds_json",
              "notes_json", "result_json")


def _decode(r: dict | None) -> dict | None:
    if r is None:
        return None
    for k in list(r):
        if k in _JSON_COLS:
            r[k[:-5]] = json.loads(r.pop(k) or "null")
    return r


# ------------------------------------------------------------------ training
class TrainBody(BaseModel):
    force: bool = False


@router.post("/training/run")
def run_training(body: TrainBody | None = None):
    return background.submit("TRAIN_PUBLISH", {"force": bool(body and body.force)})


def _assessment_summary(a: dict | None) -> dict | None:
    """The three statements of a training run in a compact form for lists (see pipeline.assess)."""
    if not a:
        return None
    return {"candidate": a.get("candidate"), "technical": (a.get("technical") or {}).get("status"),
            "quality": (a.get("quality") or {}).get("status"),
            "failed_checks": (a.get("quality") or {}).get("failed_checks"),
            "confidence": (a.get("confidence") or {}).get("level"), "usage": (a.get("usage") or {}).get("status"),
            "usage_reason": (a.get("usage") or {}).get("reason"), "policy": a.get("policy"),
            "exception": bool(a.get("exception"))}


@router.get("/training-runs")
def training_runs(limit: int = 50, scope_key: str | None = None):
    q = ss.get("quality")
    with db.read() as c:
        sql = ("SELECT id, model_version, scope_key, data_source, status, started_at, finished_at, train_start, "
               "train_end, n_series, n_rows, metrics_json, baseline_metrics_json, quality_gate_json, reject_reason, "
               "error, job_id, model_path FROM training_runs")
        params: list = []
        if scope_key:
            sql += " WHERE scope_key=?"
            params.append(scope_key)
        rows = db.rows(c, sql + " ORDER BY started_at DESC, rowid DESC LIMIT ?", (*params, limit))
    out = []
    for r in rows:
        a = _assessment_summary(pipeline.run_assessment(r, q))
        r.pop("model_path", None)
        out.append({**_decode(r), "assessment": a})
    return out


@router.get("/training-runs/{run_id}")
def training_run(run_id: str):
    with db.read() as c:
        r = _decode(db.one(c, "SELECT * FROM training_runs WHERE id=?", (run_id,)))
        if not r:
            raise AppError("BATCH_NOT_FOUND", 404, detail=run_id)
        r["backtest"] = _decode(db.one(c, "SELECT * FROM backtest_runs WHERE training_run_id=?", (run_id,)))
        r["forecast_runs"] = db.rows(c, "SELECT id, created_at FROM forecast_runs WHERE training_run_id=? "
                                        "ORDER BY created_at, rowid", (run_id,))
        inc = pipeline.incumbent(r["scope_key"], c)
        r["in_use"] = bool(inc and inc["training_run"]["id"] == run_id)
        r["incumbent_training_run_id"] = inc["training_run"]["id"] if inc else None
        raw = db.one(c, "SELECT * FROM training_runs WHERE id=?", (run_id,))
        r["promotable"] = pipeline.promotable(raw)
        r["can_promote"] = bool(r["promotable"]["ok"])
        r["gate_exception"] = pipeline.exception_eligible(raw)
        r["assessment"] = pipeline.run_assessment(raw)
    return r


class PromoteBody(BaseModel):
    confirm: bool = False


@router.post("/training-runs/{run_id}/promote")
def promote_training_run(run_id: str, body: PromoteBody):
    """User decision to put a reviewed candidate in use (there is no approved automatic promotion rule)."""
    if not body.confirm:
        raise AppError("CONFIRMATION_MISMATCH", 422, detail="confirm=true required")
    return pipeline.promote_candidate(run_id)


class GateExceptionBody(BaseModel):
    confirm_text: str = ""
    approved_by: str = ""
    reason: str = ""
    review_by: str = ""
    acknowledged_wape: float | None = None
    acknowledged_bias: float | None = None


@router.post("/training-runs/{run_id}/release-with-exception")
def release_with_exception(run_id: str, body: GateExceptionBody):
    """Owner-approved quality-gate exception for THIS training run only (standard thresholds unchanged)."""
    return pipeline.release_with_gate_exception(run_id, body.model_dump())


# ------------------------------------------------------------------ forecast runs
def _run(c, run_id: str) -> dict:
    r = _decode(db.one(c, "SELECT * FROM forecast_runs WHERE id=?", (run_id,)))
    if not r:
        raise AppError("BATCH_NOT_FOUND", 404, detail=run_id)
    return r


@router.get("/forecast-runs")
def forecast_runs(limit: int = 50, scope_key: str | None = None, data_source: str | None = None):
    """Published runs, newest first. Every row says whether it belongs to the ACTIVE source's scope and carries the
    assessment of its training run (quality / usage), so the UI never presents a run of another source (e.g. an
    old DEMO run) as the current one."""
    q = ss.get("quality")
    with db.read() as c:
        try:
            active = resolve_scope(c)["scope_key"]
        except AppError:
            active = None
        sql = "SELECT * FROM forecast_runs"
        where, params = [], []
        if scope_key:
            where.append("scope_key=?")
            params.append(scope_key)
        if data_source:
            where.append("data_source=?")
            params.append(data_source)
        if where:
            sql += " WHERE " + " AND ".join(where)
        rows = [_decode(r) for r in db.rows(c, sql + " ORDER BY created_at DESC, rowid DESC LIMIT ?", (*params, limit))]
        trs = {}
        for r in rows:
            if r["training_run_id"] not in trs:
                trs[r["training_run_id"]] = db.one(c, "SELECT * FROM training_runs WHERE id=?", (r["training_run_id"],))
    for r in rows:
        r["active_scope"] = r["scope_key"] == active
        r["assessment"] = _assessment_summary(pipeline.run_assessment(trs.get(r["training_run_id"]), q))
    return rows


def _lineage(tr: dict | None) -> dict | None:
    """Which data the run was trained on (stored with the training run; metadata only, no credentials)."""
    if not tr:
        return None
    fc = json.loads(tr.get("feature_config_json") or "{}") or {}
    lin = fc.get("lineage") or {}
    ref = lin.get("source_ref") or {}
    last = ref.get("last_sync") or {}
    return {"data_source": lin.get("data_source") or tr.get("data_source"), "scope_key": tr.get("scope_key"),
            "table": ref.get("table"), "location": ref.get("location"), "batch_id": ref.get("id"),
            "data_window": fc.get("data_window"), "demand_daily": lin.get("demand_daily"),
            "fetched_at": lin.get("fetched_at"), "data_fingerprint": tr.get("data_fingerprint"),
            "last_sync": {k: last.get(k) for k in ("synced_at", "watermark", "window_start", "window_end", "mode",
                                                   "rows_read", "series_days_written")} if last else None,
            "train_start": tr.get("train_start"), "train_end": tr.get("train_end")}


@router.get("/forecast-runs/{run_id}")
def forecast_run(run_id: str):
    with db.read() as c:
        r = _run(c, run_id)
        raw = db.one(c, "SELECT * FROM training_runs WHERE id=?", (r["training_run_id"],))
        r["training_run"] = _decode(db.one(c, "SELECT id, model_version, status, metrics_json, quality_gate_json, "
                                              "train_start, train_end FROM training_runs WHERE id=?",
                                           (r["training_run_id"],)))
        r["assessment"] = pipeline.run_assessment(raw)
        r["lineage"] = _lineage(raw)
        try:
            r["active_scope"] = r["scope_key"] == resolve_scope(c)["scope_key"]
        except AppError:
            r["active_scope"] = False
        r["skus"] = [x["sku_id"] for x in db.rows(c, "SELECT DISTINCT sku_id FROM forecast_values WHERE run_id=? "
                                                     "ORDER BY sku_id", (run_id,))]
        r["fcs"] = [x["fc_id"] for x in db.rows(c, "SELECT DISTINCT fc_id FROM forecast_values WHERE run_id=? "
                                                   "ORDER BY fc_id", (run_id,))]
        r["horizon_coverage"] = _coverage(c, r)
    return r


def _coverage(c, run: dict) -> dict:
    """Which horizons this run really contains vs. what is configured for the NEXT run, and whether the missing
    ones can be produced from the same accepted model without retraining (see pipeline.extend_forecast)."""
    import hashlib

    from .. import paths
    from ..data.demand import fingerprint
    configured = sorted(set(ss.get("horizons", c).enabled))
    have = sorted(set(run["horizons"] or []) | {run["max_horizon"]})
    missing = [h for h in configured if h > run["max_horizon"]]
    can, why = False, None
    if missing:
        tr = db.one(c, "SELECT status, model_path, model_sha256, data_fingerprint FROM training_runs WHERE id=?",
                    (run["training_run_id"],))
        mp = paths.models_dir() / (tr["model_path"] or "") if tr else None
        baseline = pipeline.is_baseline_run(run)       # 1.2.2: rebuilt from the data alone, no model file
        if not tr or tr["status"] != "ACCEPTED" or (not baseline and (not tr["model_path"] or not mp.exists())):
            why = "MODEL_ARTIFACT_MISSING"
        elif not baseline and hashlib.sha256(mp.read_bytes()).hexdigest() != tr["model_sha256"]:
            why = "MODEL_ARTIFACT_MISSING"
        elif fingerprint(run["scope_key"], c) != tr["data_fingerprint"]:
            why = "DATA_CHANGED_SINCE_TRAINING"
        else:
            can = True
    return {"run_horizons": have, "max_horizon": run["max_horizon"], "configured": configured,
            "configured_missing_in_run": missing, "can_extend_without_retraining": can, "cannot_extend_reason": why}


def _check_h(run: dict, horizon: int | None) -> int:
    h = horizon or (run["horizons"][0] if run["horizons"] else run["max_horizon"])
    if h < 1 or h > run["max_horizon"]:
        raise AppError("FORECAST_TOO_LARGE", 422, detail=f"horizon must be 1..{run['max_horizon']} for this run")
    return h


def _filters(sku_id, fc_id, date_from, date_to):
    sql, params = "", []
    for col, v in (("sku_id", sku_id), ("fc_id", fc_id)):
        if v:
            sql += f" AND {col}=?"
            params.append(v)
    if date_from:
        sql += " AND target_date>=?"
        params.append(date_from)
    if date_to:
        sql += " AND target_date<=?"
        params.append(date_to)
    return sql, params


@router.get("/forecast-runs/{run_id}/values")
def forecast_values(run_id: str, horizon: int | None = None, sku_id: str | None = None, fc_id: str | None = None,
                    date_from: str | None = None, date_to: str | None = None, limit: int = 500, offset: int = 0):
    with db.read() as c:
        run = _run(c, run_id)
        h = _check_h(run, horizon)
        f, p = _filters(sku_id, fc_id, date_from, date_to)
        base = f" FROM forecast_values WHERE run_id=? AND horizon_day<=?{f}"
        total = c.execute("SELECT COUNT(*)" + base, (run_id, h, *p)).fetchone()[0]
        rows = db.rows(c, "SELECT sku_id, fc_id, target_date, horizon_day, yhat, method, fallback_reason" + base +
                       " ORDER BY sku_id, fc_id, target_date LIMIT ? OFFSET ?", (run_id, h, *p, min(limit, 5000), offset))
        act = intraday.actual_today(run["scope_key"], run["data_source"], c)
    for r in rows:
        r["actual_today"] = intraday.value_for(act, r["sku_id"], r["fc_id"], r["target_date"])
    return {"total": total, "rows": rows, "horizon": h, "actual": intraday.public(act)}


@router.get("/forecast-runs/{run_id}/summary")
def forecast_summary(run_id: str, horizon: int | None = None, sku_id: str | None = None, fc_id: str | None = None,
                     limit: int = 200, offset: int = 0):
    with db.read() as c:
        run = _run(c, run_id)
        h = _check_h(run, horizon)
        f, p = _filters(sku_id, fc_id, None, None)
        start = run["forecast_origin"]
        end = str(date.fromisoformat(start) + timedelta(days=h - 1))
        series = db.rows(c, "SELECT sku_id, fc_id, SUM(yhat) AS total, MIN(method) AS method, "
                            "MAX(fallback_reason) AS fallback_reason FROM forecast_values WHERE run_id=? AND horizon_day<=?"
                            f"{f} GROUP BY sku_id, fc_id ORDER BY total DESC LIMIT ? OFFSET ?",
                         (run_id, h, *p, min(limit, 5000), offset))
        n_series = c.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM forecast_values WHERE run_id=? AND horizon_day<=?{f} "
                             "GROUP BY sku_id, fc_id)", (run_id, h, *p)).fetchone()[0]
        daily = db.rows(c, "SELECT target_date, SUM(yhat) AS total FROM forecast_values WHERE run_id=? AND horizon_day<=?"
                           f"{f} GROUP BY target_date ORDER BY target_date", (run_id, h, *p))
        methods = db.rows(c, "SELECT method, COUNT(DISTINCT sku_id || '|' || fc_id) AS n_series, SUM(yhat) AS total "
                             f"FROM forecast_values WHERE run_id=? AND horizon_day<=?{f} GROUP BY method",
                          (run_id, h, *p))
        act = intraday.actual_today(run["scope_key"], run["data_source"], c)
        keys = [(r["sku_id"], r["fc_id"]) for r in db.rows(
            c, f"SELECT DISTINCT sku_id, fc_id FROM forecast_values WHERE run_id=?{f}", (run_id, *p))]
    in_range = start <= act["date"] <= end
    actual = intraday.public(act)
    actual["in_horizon"] = in_range
    # each SKU x FC counted once, only the series of this run that pass the current filter
    actual["total"] = (sum(act["values"].get(k, 0.0) for k in keys)
                       if in_range and intraday.has_values(act) else None)
    actual["n_series"] = len(keys)
    for r in series:
        r["actual_today"] = intraday.value_for(act, r["sku_id"], r["fc_id"], act["date"]) if in_range else None
    for d in daily:
        d["actual_today"] = actual["total"] if d["target_date"] == act["date"] else None
    return {"run_id": run_id, "horizon": h, "start_date": start, "end_date": end, "actual": actual,
            "grand_total": sum(d["total"] for d in daily), "daily": daily, "series": series, "n_series": n_series,
            "methods": methods, "model_version": run["model_version"], "data_source": run["data_source"],
            "data_as_of": run["data_as_of"], "forecast_origin": run["forecast_origin"], "created_at": run["created_at"],
            "scope_key": run["scope_key"]}


@router.get("/forecast-runs/{run_id}/export.xlsx")
def forecast_export(run_id: str, horizon: int | None = None, lang: str = "vi"):
    """Excel in the UI language (lang=vi|en). Codes/IDs stay untranslated; numbers unchanged (yhat as stored)."""
    from ..export_i18n import EXPORT_FORMAT_VERSION, fmt_date, fmt_vn_time, labels
    from ..ml.methods import label as method_label
    lang, L = labels(lang)
    with db.read() as c:
        run = _run(c, run_id)
        h = _check_h(run, horizon)
        daily = pd.read_sql_query("SELECT sku_id, fc_id, target_date, horizon_day, yhat AS forecast_qty, method "
                                  "FROM forecast_values WHERE run_id=? AND horizon_day<=? "
                                  "ORDER BY sku_id, fc_id, target_date", c, params=(run_id, h))
        act = intraday.actual_today(run["scope_key"], run["data_source"], c)
    start = run["forecast_origin"]
    end = str(date.fromisoformat(start) + timedelta(days=h - 1))
    in_range = start <= act["date"] <= end
    daily["actual_today"] = [intraday.value_for(act, r.sku_id, r.fc_id, r.target_date)
                             for r in daily.itertuples()]
    daily["method_label"] = daily["method"].map(lambda m: method_label(m, lang))
    totals = daily.groupby(["sku_id", "fc_id", "method"], as_index=False)["forecast_qty"].sum()
    totals["method_label"] = totals["method"].map(lambda m: method_label(m, lang))
    totals["actual_today"] = [intraday.value_for(act, r.sku_id, r.fc_id, act["date"]) if in_range else None
                              for r in totals.itertuples()]
    totals = totals[list(L["cols_totals"])].rename(columns=L["cols_totals"])
    daily["target_date"] = pd.to_datetime(daily["target_date"]).dt.date      # real Excel dates, shown per language
    daily = daily[list(L["cols_daily"])].rename(columns=L["cols_daily"])
    I = L["info"]
    rows = [("export_format_version", EXPORT_FORMAT_VERSION), ("language", L["language_name"]),
            ("forecast_run_id", run_id), ("model_version", run["model_version"]), ("data_source", run["data_source"]),
            ("scope", run["scope_key"]), ("forecast_origin", fmt_date(start, L)),
            ("data_as_of", fmt_date(run["data_as_of"], L)), ("created_at_vn", fmt_vn_time(run["created_at"], L)),
            ("created_at_utc", run["created_at"]), ("horizon_days", h), ("start_date", fmt_date(start, L)),
            ("end_date", fmt_date(end, L)), ("derived_from_run_id", run.get("derived_from_run_id") or ""),
            ("actual_date", fmt_date(act["date"], L)),
            ("actual_status", L["actual_status"].get(act["status"], act["status"])),
            ("actual_as_of_vn", fmt_vn_time(act["as_of"], L)), ("actual_as_of_utc", act["as_of"] or ""), ("actual_source_updated_max", act["source_updated_max"] or ""),
            ("actual_snapshot_id", act["snapshot_id"] or ""), ("actual_is_demo", L["yes"] if act["is_demo"] else L["no"]),
            ("actual_note", L["actual_note"])]
    info = pd.DataFrame({L["field"]: [I[k] for k, _ in rows], L["value"]: [v for _, v in rows]})
    content = dataframe_to_xlsx({L["sheet_info"]: info, L["sheet_totals"].format(h=h): totals,
                                 L["sheet_daily"]: daily}, date_format=L["excel_date_fmt"])
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="forecast-{run_id}-{h}d-{lang}.xlsx"'})


# ------------------------------------------------------------------ explanations / extension / method registry
@router.get("/forecast-runs/{run_id}/explain")
def forecast_explain(run_id: str, sku_id: str, fc_id: str, target_date: str):
    from ..ml.explain import explain
    return explain(run_id, sku_id, fc_id, target_date)


@router.post("/forecast-runs/{run_id}/extend")
def forecast_extend(run_id: str):
    """Background job: new run with the configured horizons from the same accepted model (no retraining)."""
    with db.read() as c:
        run = _run(c, run_id)
        cov = _coverage(c, run)
    if not cov["configured_missing_in_run"]:
        raise AppError("NOTHING_TO_EXTEND", 409)
    if not cov["can_extend_without_retraining"]:
        raise AppError(cov["cannot_extend_reason"] or "MODEL_ARTIFACT_MISSING", 409)
    return background.submit("FORECAST_EXTEND", {"run_id": run_id})


@router.get("/methods")
def methods_registry():
    from ..ml.methods import registry
    return registry()


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/forecast-runs/{run_id}/explain/history.xlsx")
def forecast_explain_history(run_id: str, sku_id: str, fc_id: str, target_date: str, lang: str = "vi"):
    """Demand history of exactly the explained row (same data as the explanation panel), read-only."""
    from ..explain_export import history_xlsx
    from ..ml.explain import explain
    ex = explain(run_id, sku_id, fc_id, target_date)
    if ex["history"].get("status") != "OK":
        raise AppError(ex["history"].get("status") or "DATA_CHANGED_SINCE_TRAINING", 409)
    name = f"lich-su-demand-{run_id}-{sku_id}-{fc_id}-{target_date}.xlsx" if lang != "en" else f"demand-history-{run_id}-{sku_id}-{fc_id}-{target_date}.xlsx"
    return Response(history_xlsx(ex, lang), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/features/catalog")
def features_catalog(target_date: str | None = None):
    """Every feature of the current model configuration with its exact definition (ml/feature_catalog.py)."""
    from ..ml import feature_catalog
    from ..ml.features import feature_names
    names = feature_names(ss.get("model"))
    return {"features": [feature_catalog.describe(n, target_date) for n in names],
            "roles": {k: {"vi": v[0], "en": v[1]} for k, v in feature_catalog.ROLES.items()}}


@router.get("/features/registry")
def features_registry(source: str | None = None):
    """Feature registry with the real status of every feature (in use / available / planned / missing data) for the
    active (or given) source, and the feature set the next training would use. Read-only."""
    from ..ml import feature_registry
    if source is not None and source not in ("DEMO", "MANUAL_IMPORT", "BIGQUERY"):
        raise AppError("NO_ACTIVE_DATASET", 422, detail=source)
    with db.read() as c:
        return feature_registry.view(c, source)


@router.get("/model/training-explain")
def model_training_explain(training_run_id: str | None = None):
    """How the model behind the forecasts was trained and evaluated - read-only, from stored facts."""
    from ..ml.training_explain import overview
    return overview(training_run_id)


@router.get("/forecast-runs/{run_id}/shap-trace")
def forecast_shap_trace(run_id: str, sku_id: str, fc_id: str, target_date: str, feature: str | None = None,
                        page: int = 1, page_size: int = 25, sort: str = "impact"):
    """TreeSHAP audit of one published LightGBM value: reconciliation (+ one feature's per-tree trace). Read-only."""
    from ..ml import shap_audit
    res = shap_audit.audit(run_id, sku_id, fc_id, target_date)
    if res["status"] == "NOT_REPRODUCIBLE" or res["status"] == "FAILED" and "features" not in res:
        return res
    out = shap_audit.public(res)
    if feature:
        out["feature_view"] = shap_audit.feature_view(res, feature, page, page_size, sort)
    return out


@router.get("/forecast-runs/{run_id}/shap-trace/tree")
def forecast_shap_trace_tree(run_id: str, sku_id: str, fc_id: str, target_date: str, feature: str, tree: int):
    from ..ml import shap_audit
    res = shap_audit.audit(run_id, sku_id, fc_id, target_date)
    if "features" not in res:
        return res
    if not 0 <= tree < res["identity"]["n_trees"]:
        raise AppError("BATCH_NOT_FOUND", 404, detail=f"tree {tree}")
    return {"status": res["status"], **shap_audit.tree_terms(res, feature, tree)}


@router.get("/forecast-runs/{run_id}/shap-trace.{fmt}")
def forecast_shap_trace_export(run_id: str, fmt: str, sku_id: str, fc_id: str, target_date: str, feature: str | None = None,
                               lang: str = "vi"):
    from ..explain_export import shap_trace_csv, shap_trace_xlsx
    from ..ml import shap_audit
    res = shap_audit.audit(run_id, sku_id, fc_id, target_date)
    if "features" not in res:
        raise AppError("MODEL_ARTIFACT_MISSING" if res.get("reason", "").startswith("MODEL_") else "DATA_CHANGED_SINCE_TRAINING", 409,
                       detail=res.get("reason"))
    if feature:
        shap_audit._feature_index(res, feature)
    base = f"shap-trace-{run_id}-{sku_id}-{fc_id}-{target_date}-{feature or 'all'}"
    if fmt == "csv":
        return Response(shap_trace_csv(res, feature), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{base}.csv"'})
    if fmt == "xlsx":
        return Response(shap_trace_xlsx(res, feature, lang), media_type=XLSX,
                        headers={"Content-Disposition": f'attachment; filename="{base}.xlsx"'})
    raise AppError("BATCH_NOT_FOUND", 404, detail=fmt)


@router.get("/training-runs/{run_id}/backtest-points.xlsx")
def training_backtest_points(run_id: str, lang: str = "vi"):
    """Recomputes the backtest in memory (no write) and returns the points only if the metrics match."""
    from ..explain_export import backtest_points_xlsx
    from ..ml.training_explain import backtest_points
    res = backtest_points(run_id)
    return Response(backtest_points_xlsx(res, lang), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="backtest-points-{run_id}-{lang}.xlsx"'})


@router.get("/forecast-runs/{run_id}/accuracy")
def forecast_accuracy(run_id: str):
    """Compare a published run with end-of-day actuals that became available later (same scope only)."""
    q = ss.get("quality")
    with db.read() as c:
        run = _run(c, run_id)
        df = pd.read_sql_query(
            "SELECT f.horizon_day, f.yhat, d.qty FROM forecast_values f JOIN demand_daily d ON d.scope_key=? "
            "AND d.order_date=f.target_date AND d.sku_id=f.sku_id AND d.fc_id=f.fc_id WHERE f.run_id=? AND "
            "f.target_date < ?", c, params=(run["scope_key"], run_id, str(today_vn())))
    if df.empty:
        return {"available": False, "note": "NO_ACTUALS_YET"}
    out = {"available": True, "overall": mt.compute(df["qty"], df["yhat"], q.mape_min_actual), "by_horizon": []}
    for h in run["horizons"]:
        sub = df[df["horizon_day"] <= h]
        if len(sub):
            out["by_horizon"].append({"horizon": h, **mt.compute(sub["qty"], sub["yhat"], q.mape_min_actual)})
    return out


# ------------------------------------------------------------------ dashboard
@router.get("/dashboard")
def dashboard(horizon: int | None = None):
    from .ops_routes import system_status
    st = system_status()
    out = {"system": st, "forecast": None}
    run = st.get("latest_forecast_run")
    if run:
        h = horizon or ss.get("horizons").enabled[0]
        h = min(h, run["max_horizon"])
        s = forecast_summary(run["id"], h, limit=10)
        out["forecast"] = s
    return out
