"""Explain one published forecast value (SKU x FC x date) - only with facts that can be traced and verified.

* Method / reason: the per-series metadata stored at publish time (forecast_series_meta). Runs published before
  v1.1.1 have none; it is then RECOMPUTED with the same code (classification_details) - only if the data
  fingerprint still equals the training run's - and the recomputed method must equal the published one.
* History and LightGBM inputs: the run is REPRODUCED from the saved model file (sha256 checked) and the same data
  (fingerprint checked). The reproduced value must equal the published value, otherwise nothing is shown.
* LightGBM contributions: exact TreeSHAP values from booster.predict(pred_contrib=True), in the model's raw score
  space; the forecast is link(bias + sum(contributions)), link = exp for tweedie/poisson, identity otherwise.
No value is approximated or invented. Data after data_as_of is never read.
"""
from __future__ import annotations

import hashlib
import json
from collections import OrderedDict

import numpy as np

from .. import db, paths
from .. import settings_service as ss
from ..data.demand import fingerprint, panel_for_run
from ..messages import AppError
from . import model
from . import feature_catalog
from .features import LAGS, LAST_SALE_WINDOW, ROLL_WINDOWS, is_direct

HISTORY_WINDOW_DAYS = 56
_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_CACHE_MAX = 32

FEATURE_INFO = {
    "sku_code": ("Mã SKU dạng danh mục (categorical) để model phân biệt SKU.", "SKU as a categorical code."),
    "fc_code": ("Mã FC dạng danh mục (categorical).", "FC as a categorical code."),
    "series_age": ("Số ngày từ đơn đầu tiên của chuỗi đến ngày dự báo.", "Days from the series' first order to the target day."),
    "lag": ("Số lượng đúng {k} ngày trước ngày dự báo.", "Quantity exactly {k} days before the target day."),
    "roll_mean": ("Trung bình số lượng {k} ngày trước ngày dự báo (bỏ qua ngày không có dữ liệu).", "Mean quantity of the {k} days before the target day (unknown days ignored)."),
    "roll_std_7": ("Độ lệch chuẩn số lượng 7 ngày trước.", "Std. deviation of the previous 7 days."),
    "roll_std_28": ("Độ lệch chuẩn số lượng 28 ngày trước.", "Std. deviation of the previous 28 days."),
    "zero_share_28": ("Tỷ lệ ngày = 0 trong 28 ngày trước.", "Share of zero days in the previous 28 days."),
    "days_since_last_sale": (f"Số ngày từ lần có đơn gần nhất (tối đa {LAST_SALE_WINDOW + 1}).", f"Days since the last order (capped at {LAST_SALE_WINDOW + 1})."),
    "roll_max_28": ("Số lượng lớn nhất trong 28 ngày trước.", "Maximum quantity in the previous 28 days."),
    "dow": ("Thứ trong tuần của ngày dự báo (0 = Thứ Hai).", "Day of week of the target day (0 = Monday)."),
    "dom": ("Ngày trong tháng.", "Day of month."),
    "month": ("Tháng.", "Month."),
    "weekofyear": ("Tuần ISO trong năm.", "ISO week of year."),
    "is_weekend": ("1 nếu Thứ Bảy/Chủ Nhật.", "1 on Saturday/Sunday."),
    "days_to_month_end": ("Số ngày đến cuối tháng.", "Days to month end."),
    "price_last": ("Giá bình quân gần nhất đã biết (ngày hôm trước).", "Last known average price (previous day)."),
    "price_rel_28": ("Giá gần nhất ÷ giá trung bình 28 ngày.", "Last price ÷ 28-day mean price."),
    "disc_last": ("Tỷ lệ giảm giá gần nhất đã biết.", "Last known discount rate."),
    "promo_last": ("Tỷ lệ dòng có khuyến mãi hôm trước.", "Promotion share on the previous day."),
    "promo_mean_7": ("Tỷ lệ khuyến mãi trung bình 7 ngày trước.", "Mean promotion share over the previous 7 days."),
}


def _feature_info(name: str) -> tuple[str, str]:
    for prefix in ("lag", "roll_mean"):
        if name.startswith(prefix + "_") and name[len(prefix) + 1:].isdigit():
            k = name[len(prefix) + 1:]
            vi, en = FEATURE_INFO[prefix]
            return vi.format(k=k), en.format(k=k)
    return FEATURE_INFO.get(name, (name, name))


def _input_source(name: str, t: int, T: int, direct: bool = False) -> str:
    """Where a feature value at target index t comes from: ACTUAL history, FORECAST values (recursion), MIXED,
    TARGET_DATE (calendar), HELD_CONSTANT (price after origin), ASSUMED_ZERO (promotion after origin), STATIC.
    DIRECT models compute every history feature at the origin T from actual data only (no forecast is fed back)."""
    if name in ("sku_code", "fc_code", "series_age", "horizon"):
        return "STATIC"
    if name in ("dow", "dom", "month", "weekofyear", "is_weekend", "days_to_month_end"):
        return "TARGET_DATE"
    if direct:
        return "ACTUAL"
    if name.startswith("lag_"):
        return "FORECAST" if t - int(name[4:]) >= T else "ACTUAL"
    if name in ("price_last", "disc_last"):
        return "HELD_CONSTANT" if t - 1 >= T else "ACTUAL"
    if name == "promo_last":
        return "ASSUMED_ZERO" if t - 1 >= T else "ACTUAL"
    windows = {"roll_std_7": 7, "promo_mean_7": 7, "roll_std_28": 28, "zero_share_28": 28, "roll_max_28": 28,
               "price_rel_28": 28, "days_since_last_sale": LAST_SALE_WINDOW}
    w = int(name.rsplit("_", 1)[1]) if name.startswith("roll_mean_") else windows.get(name, 0)
    if t <= T:
        return "ACTUAL"
    return "FORECAST" if t - w >= T else "MIXED"


def _reproduce(run: dict, tr: dict, sku: str, fc_id: str) -> dict:
    """Rebuild the panel + reload the model; return reproduction state for one series (cached)."""
    with db.read() as c:
        cur_fp = fingerprint(run["scope_key"], c)
    key = (run["id"], sku, fc_id, cur_fp)          # data change -> different key -> no stale explanation
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    out: dict = {"status": "OK"}
    if not tr or tr.get("data_fingerprint") != cur_fp:
        out = {"status": "DATA_CHANGED"}
    else:
        mcfg = ss.ModelSettings.model_validate(json.loads(tr["feature_config_json"])["config"])
        panel = panel_for_run(tr)      # the run's own train_start..train_end: never beyond data_as_of
        if panel is None:
            out = {"status": "DATA_UNAVAILABLE"}
        else:
            if str(panel.dates[-1].date()) != run["data_as_of"] or (sku, fc_id) not in panel.keys:
                out = {"status": "DATA_CHANGED"}
            else:
                s = panel.keys.index((sku, fc_id))
                details = model.classification_details(panel, mcfg)
                out.update(panel=panel, s=s, mcfg=mcfg, details=details, booster=None)
                if details["methods"][s] == model.METHOD_LGBM:
                    mpath = paths.models_dir() / (tr.get("model_path") or "")
                    if not tr.get("model_path") or not mpath.exists() or \
                            hashlib.sha256(mpath.read_bytes()).hexdigest() != tr.get("model_sha256"):
                        out["status"] = "MODEL_MISSING"
                    else:
                        import lightgbm as lgb
                        booster = lgb.Booster(model_file=str(mpath))
                        fc = model.forecast(panel, booster, mcfg, run["max_horizon"], capture=s)
                        out.update(booster=booster, yhat=fc["yhat"][s], captured=fc["captured"])
                else:   # fallback: model.forecast uses the constant rate, clipped at 0
                    out.update(yhat=np.repeat(details["rate"][s], run["max_horizon"]).clip(0, None))
    _cache[key] = out
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return out


def explain(run_id: str, sku: str, fc_id: str, target_date: str) -> dict:
    with db.read() as c:
        run = db.one(c, "SELECT * FROM forecast_runs WHERE id=?", (run_id,))
        if not run:
            raise AppError("BATCH_NOT_FOUND", 404, detail=run_id)
        val = db.one(c, "SELECT * FROM forecast_values WHERE run_id=? AND sku_id=? AND fc_id=? AND target_date=?",
                     (run_id, sku, fc_id, target_date))
        if not val:
            raise AppError("BATCH_NOT_FOUND", 404, detail=f"{sku} / {fc_id} / {target_date} not in {run_id}")
        tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (run["training_run_id"],))
        meta_row = db.one(c, "SELECT details_json FROM forecast_series_meta WHERE run_id=? AND sku_id=? AND fc_id=?",
                          (run_id, sku, fc_id))
        bt = db.one(c, "SELECT id, metrics_json, reliable, config_json, folds_json FROM backtest_runs WHERE training_run_id=?",
                    (run["training_run_id"],))
    h = val["horizon_day"]
    method = val["method"]
    out: dict = {
        "identity": {"sku_id": sku, "fc_id": fc_id, "target_date": target_date, "horizon_day": h,
                     "data_as_of": run["data_as_of"], "forecast_origin": run["forecast_origin"], "run_id": run_id,
                     "model_version": run["model_version"], "data_source": run["data_source"],
                     "scope_key": run["scope_key"], "derived_from_run_id": run.get("derived_from_run_id"),
                     "run_created_at": run["created_at"], "training_run_id": run["training_run_id"]},
        "result": {"yhat": val["yhat"], "unit": "order_qty", "method": method}, "notes": []}
    rep = _reproduce(run, tr, sku, fc_id)
    out["reproduction"] = {"status": rep["status"]}

    # ---- method selection
    if meta_row:
        meta = json.loads(meta_row["details_json"])
        out["selection"] = {"source": "STORED", **meta}
    elif rep["status"] in ("OK", "MODEL_MISSING"):
        m = model.series_meta(rep["panel"], rep["mcfg"], rep["details"], rep["s"])
        out["selection"] = {"source": "RECOMPUTED", **m}
        if m["method"] != method:
            out["selection"] = {"source": "MISSING"}
            out["notes"].append("RECOMPUTED_METHOD_MISMATCH")
    else:
        out["selection"] = {"source": "MISSING"}
        out["notes"].append("SELECTION_METADATA_MISSING")

    # ---- history the model saw (from the reproduced panel only)
    if "panel" in rep:
        p, s, mc = rep["panel"], rep["s"], rep["mcfg"]
        T = p.T
        # long enough to contain every day a rule looks at (inactive rule: 60 days by default)
        window = max(HISTORY_WINDOW_DAYS, 2 * mc.fallback_window_days, mc.inactive_days)
        lo = max(0, T - window)
        # days the fallback calculation actually used (same windows as model.classification_details)
        calc_lo = {model.FB_NEW: int(p.start_idx[s]), model.FB_INTERMITTENT: T - mc.fallback_window_days,
                   model.FB_INACTIVE: T - mc.inactive_days}.get(method)
        t_idx = T + h - 1                      # target day index; days >= T are forecasts, not history
        direct = is_direct(mc)
        ref = T if direct else t_idx           # DIRECT: history features are read relative to the origin T
        feats = model_feature_names(rep)
        lgb_lo = ref - max(ROLL_WINDOWS) if method == model.METHOD_LGBM else None
        days = []
        for i in range(lo, T):
            y = p.Y[s, i]
            if i < p.start_idx[s]:
                st = "BEFORE_START"
            elif np.isnan(y):
                st = "NO_DATA"          # calendar day without any order in the whole dataset: unknown, not 0
            elif y == 0:
                st = "ZERO_ORDERS"
            else:
                st = "ORDERS"
            if method == model.METHOD_LGBM:
                used_by = _features_using_day(ref - i, feats)
                in_calc = bool(used_by)
            else:
                used_by = []
                in_calc = calc_lo is not None and i >= calc_lo and not np.isnan(y)
            days.append({"date": str(p.dates[i].date()), "weekday": int(p.dates[i].dayofweek),
                         "qty": None if np.isnan(y) else float(y), "status": st, "in_calc": bool(in_calc),
                         "used_by": used_by})
        summ = {k: sum(1 for d in days if d["status"] == k) for k in ("ORDERS", "ZERO_ORDERS", "NO_DATA", "BEFORE_START")}
        summ["total_qty"] = float(sum(d["qty"] or 0 for d in days))
        hist = {"status": "OK", "window_start": days[0]["date"] if days else None, "window_end": run["data_as_of"],
                "window_days": len(days), "days": days, "summary": summ}
        if method == model.METHOD_LGBM:
            used = [d for d in days if d["in_calc"] and d["qty"] is not None]
            hist["calc"] = {"kind": "LIGHTGBM_FEATURE_WINDOWS", "from": used[0]["date"] if used else None,
                            "rolling_from": str(p.dates[max(lgb_lo, lo)].date()),
                            "to": run["data_as_of"], "known_days": len(used), "sum": float(sum(d["qty"] for d in used)),
                            "recursive_days": 0 if direct else max(0, h - 1),
                            "recursive_from": run["forecast_origin"] if h > 1 and not direct else None,
                            "recursive_to": str(p.dates[T - 1].date() + __import__("datetime").timedelta(days=h - 1)) if h > 1 and not direct else None,
                            "forecast_strategy": "DIRECT" if direct else "RECURSIVE",
                            "last_sale_window_days": LAST_SALE_WINDOW}
        if calc_lo is not None:
            used = [d for d in days if d["in_calc"]]
            hist["calc"] = {"from": str(p.dates[max(calc_lo, 0)].date()) if calc_lo < T else None, "to": run["data_as_of"],
                            "known_days": len(used), "sum": float(sum(d["qty"] for d in used))}
        out["history"] = hist
    else:
        out["history"] = {"status": rep["status"]}

    # ---- how the value was obtained
    sel = out.get("selection", {})
    if method != model.METHOD_LGBM:
        calc: dict = {"kind": method}
        if sel.get("source") in ("STORED", "RECOMPUTED"):
            if method == model.FB_NEW:
                calc.update(window="SINCE_SERIES_START", known_days=sel["history"]["known_days"],
                            sum=sel["history"]["sum"], rate=sel["history"]["rate"])
            elif method == model.FB_INTERMITTENT:
                fw = sel["fallback_window"]
                calc.update(window=f"LAST_{fw['days']}_DAYS", known_days=fw["known_days"], sum=fw["sum"], rate=fw["rate"])
            elif method == model.FB_INACTIVE:
                calc.update(window=f"LAST_{sel['rule']['inactive_days']}_DAYS", sum=sel["recent_sum"], rate=0.0)
            calc["value_rounded"] = round(max(calc.get("rate", 0.0), 0.0), 4)
            calc["matches_published"] = abs(calc["value_rounded"] - val["yhat"]) <= 1e-4
            hc = out.get("history", {}).get("calc")
            if hc is not None:     # independent cross-check: the dated rows shown add up to the calculation's inputs
                calc["matches_history"] = (abs(hc["sum"] - calc.get("sum", 0.0)) < 1e-6
                                           and ("known_days" not in calc or hc["known_days"] == calc["known_days"]))
                if not calc["matches_history"]:
                    out["notes"].append("HISTORY_CALC_MISMATCH")
            if not calc["matches_published"]:
                out["notes"].append("FALLBACK_VALUE_MISMATCH")
        out["fallback"] = calc
    else:
        lg: dict = {"status": rep["status"]}
        if rep["status"] == "OK" and rep.get("booster") is not None and len(rep.get("captured", [])) >= h:
            booster, X = rep["booster"], rep["captured"][h - 1]
            names = booster.feature_name()
            contrib = booster.predict(X.reshape(1, -1), pred_contrib=True)[0]
            raw = float(contrib.sum())
            objective = rep["mcfg"].objective
            log_link = objective in ("tweedie", "poisson")
            pred = float(np.exp(raw)) if log_link else raw
            reproduced = round(max(float(rep["yhat"][h - 1]), 0.0), 4)
            model_output = float(booster.predict(X.reshape(1, -1))[0])      # LightGBM's own prediction (link applied)
            splits = booster.feature_importance(importance_type="split")
            T = rep["panel"].T
            t = T + h - 1
            direct = is_direct(rep["mcfg"])
            feats = []
            for i, n in enumerate(names):
                v = X[i]
                vi, en = _feature_info(n)
                cat = feature_catalog.describe(n, target_date)
                c = float(contrib[i])
                feats.append({"name": n, "value": None if np.isnan(v) else float(v), "contribution": c,
                              "effect": "NEGLIGIBLE" if abs(c) < 0.005 else ("UP" if c > 0 else "DOWN"),
                              "source": _input_source(n, t, T, direct), "used_in_trees": int(splits[i]) > 0,
                              "missing": bool(np.isnan(v)), "vi": vi, "en": en, "group": cat["group"],
                              "window": cat["window"], "includes_target_day": cat["includes_target_day"],
                              "catalog": {"vi": cat["vi"], "en": cat["en"]}})
            feats.sort(key=lambda f: -abs(f["contribution"]))
            contrib_sum = float(np.sum(contrib[:-1]))
            lg.update(objective=objective, link="exp" if log_link else "identity", bias=float(contrib[-1]),
                      contrib_sum=contrib_sum, raw_score=raw, model_output=model_output,
                      model_output_matches_link=abs(model_output - pred) <= 1e-9 * max(1.0, abs(pred)),
                      clipped=max(model_output, 0.0), clip_applied=model_output < 0,
                      n_features=len(names), n_features_used_in_trees=int(sum(1 for x in splits if x > 0)),
                      attribution_method="TREE_SHAP (LightGBM predict(pred_contrib=True))",
                      prediction_before_clip=pred, reproduced_yhat=reproduced,
                      published_yhat=val["yhat"], matches_published=abs(reproduced - val["yhat"]) <= 1e-4,
                      n_trees=booster.num_trees(), features=feats,
                      recursive_step=0 if direct else h, forecast_strategy="DIRECT" if direct else "RECURSIVE",
                      uses_forecast_inputs=any(f["source"] in ("FORECAST", "MIXED") for f in feats))
            if not lg["matches_published"]:
                lg = {"status": "NOT_REPRODUCED"}
                out["notes"].append("LIGHTGBM_NOT_REPRODUCED")
        if tr and tr.get("feature_importance_json"):
            lg["global_importance"] = json.loads(tr["feature_importance_json"])[:10]
        out["lightgbm"] = lg

    # ---- related quality checks
    q = {}
    if tr:
        q["training_status"] = tr["status"]
        q["quality_gate"] = json.loads(tr["quality_gate_json"] or "null")
    if bt:
        bm = json.loads(bt["metrics_json"] or "{}")
        q["backtest_reliable"] = bool(bt["reliable"])
        q["backtest_pooled"] = bm.get("pooled")
        q["backtest_this_method"] = _with_sums((bm.get("by_method") or {}).get(method))
        q["backtest_pooled"] = _with_sums(bm.get("pooled"))
        q["backtest_baseline"] = _with_sums(bm.get("baseline"))
        q["backtest_id"] = bt.get("id")
        cfg_bt = json.loads(bt.get("config_json") or "{}")
        folds = json.loads(bt.get("folds_json") or "[]")
        q["backtest_config"] = cfg_bt
        q["backtest_folds"] = [{"fold": f["fold"], "origin": f["origin"], "end": f["end"], "train_days": f["train_days"],
                                "n_points": (f.get("metrics") or {}).get("n_points")} for f in folds]
        q["folds_overlap"] = bool(cfg_bt and cfg_bt.get("step_days", 0) < cfg_bt.get("horizon_days", 0) and len(folds) > 1)
    out["quality"] = q
    return out


def model_feature_names(rep: dict) -> list[str]:
    b = rep.get("booster")
    if b is not None:
        return b.feature_name()
    from .features import feature_names
    return feature_names(rep["mcfg"]) if rep.get("mcfg") is not None else []


def _features_using_day(k: int, names: list[str]) -> list[str]:
    """Demand features of the target day that read the day k days before it (verified against features_at)."""
    out = []
    for n in names:
        if n.startswith("lag_") and int(n[4:]) == k:
            out.append(n)
        elif n.startswith("roll_mean_") and 1 <= k <= int(n[10:]):
            out.append(n)
        elif n == "roll_std_7" and 1 <= k <= 7:
            out.append(n)
        elif n in ("roll_std_28", "zero_share_28", "roll_max_28") and 1 <= k <= 28:
            out.append(n)
    if "days_since_last_sale" in names and 1 <= k <= LAST_SALE_WINDOW:     # scans the 180 days before the target
        out.append("days_since_last_sale")
    return out


def _with_sums(m: dict | None) -> dict | None:
    """Stored metrics + the sums they come from (sum|A-F| = MAE x n, exact by definition of MAE)."""
    if not m:
        return m
    m = dict(m)
    if m.get("mae") is not None and m.get("n_points"):
        m["sum_abs_error"] = float(m["mae"] * m["n_points"])
    return m
