"""SHAP audit of one published LightGBM forecast value: reconciliation + per-feature / per-tree / per-leaf trace.

Chain verified for every request (nothing is assumed):
  forecast run -> training run -> model file (sha256 = stored) -> feature row (reproduced by ml/explain.py from the
  same data, data fingerprint checked, published value reproduced) -> LightGBM official outputs on that row
  (predict raw_score / pred_contrib / pred_leaf / default output) -> trace engine (ml/treeshap_trace.py) ->
  comparisons with explicit tolerances.

Status: VERIFIED only if every comparison passes; FAILED (with the failing checks) otherwise; NOT_REPRODUCIBLE when the
model file or the exact feature row cannot be obtained (no other model is ever used instead).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import OrderedDict

import numpy as np

from .. import db, paths
from ..messages import AppError
from . import feature_catalog, model
from . import treeshap_trace as T

TOL_SHAP_ABS = 1e-12          # engine vs LightGBM pred_contrib, per feature and base value (same double arithmetic)
TOL_RAW_ABS = 1e-9            # base + sum(SHAP) vs LightGBM raw score (sum of 33 doubles in a different order)
TOL_OUTPUT_REL = 1e-12        # link(raw) vs LightGBM default output
TOL_PUBLISHED_ABS = 1e-9      # round(max(output, 0), 4) vs the stored value (both doubles of a 4-decimal number)
TIME_LIMIT_S = 60.0
MAX_COMPONENTS = 3_000_000
_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_CACHE_MAX = 6
_last_used = [0.0]            # 1.2.13: time.monotonic() of the last audit request (release_idle)


def release_idle(max_idle_s: float) -> int:
    """1.2.13: drop the cached audits (each holds the parsed model and up to MAX_COMPONENTS trace terms) after max_idle_s
    without an audit request. Returns the number of entries dropped."""
    if not _cache or time.monotonic() - _last_used[0] <= max_idle_s:
        return 0
    n = len(_cache)
    _cache.clear()
    return n


def _check(name, ok, **kw):
    return {"check": name, "passed": bool(ok), **kw}


def audit(run_id: str, sku: str, fc_id: str, target_date: str) -> dict:
    """Full audit (all features, all terms) - cached by model sha256 + run + row + feature-row hash."""
    from .explain import _reproduce
    _last_used[0] = time.monotonic()
    with db.read() as c:
        run = db.one(c, "SELECT * FROM forecast_runs WHERE id=?", (run_id,))
        if not run:
            raise AppError("BATCH_NOT_FOUND", 404, detail=run_id)
        val = db.one(c, "SELECT * FROM forecast_values WHERE run_id=? AND sku_id=? AND fc_id=? AND target_date=?",
                     (run_id, sku, fc_id, target_date))
        if not val:
            raise AppError("BATCH_NOT_FOUND", 404, detail=f"{sku} / {fc_id} / {target_date} not in {run_id}")
        tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (run["training_run_id"],))
    if val["method"] != model.METHOD_LGBM:
        raise AppError("NOT_LIGHTGBM", 409, detail=val["method"])
    ident = {"run_id": run_id, "sku_id": sku, "fc_id": fc_id, "target_date": target_date, "horizon_day": val["horizon_day"],
             "training_run_id": run["training_run_id"], "model_version": run["model_version"],
             "model_file": tr.get("model_path") if tr else None, "model_sha256_stored": tr.get("model_sha256") if tr else None,
             "published_yhat": val["yhat"], "data_as_of": run["data_as_of"]}
    # ---- the exact model file of this run (never another model)
    mpath = paths.models_dir() / (tr.get("model_path") or "") if tr else None
    if not tr or not tr.get("model_path") or not mpath.exists():
        return {"status": "NOT_REPRODUCIBLE", "reason": "MODEL_ARTIFACT_MISSING", "identity": ident}
    text_bytes = mpath.read_bytes()
    sha = hashlib.sha256(text_bytes).hexdigest()
    if sha != tr["model_sha256"]:
        return {"status": "NOT_REPRODUCIBLE", "reason": "MODEL_ARTIFACT_CHANGED", "identity": {**ident, "model_sha256_file": sha}}
    # ---- the exact feature row used for this published value
    rep = _reproduce(run, tr, sku, fc_id)
    h = val["horizon_day"]
    if rep["status"] != "OK" or rep.get("booster") is None or len(rep.get("captured", [])) < h:
        return {"status": "NOT_REPRODUCIBLE", "reason": rep["status"], "identity": ident}
    x32 = np.asarray(rep["captured"][h - 1], dtype=np.float32)
    rhash = T.row_hash(x32)
    key = (sha, run_id, sku, fc_id, target_date, rhash)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    booster = rep["booster"]
    m = T.parse_model(text_bytes.decode("utf-8"))
    cfg_features = (json.loads(tr["feature_config_json"] or "{}") or {}).get("features") or []
    X = x32.astype(np.float64).reshape(1, -1)
    x = [float(v) for v in X[0]]
    checks = [
        _check("MODEL_SHA256", True, value=sha),
        _check("FEATURE_NAMES", m.feature_names == booster.feature_name() == cfg_features,
               detail=None if m.feature_names == cfg_features else {"model": m.feature_names, "training_run": cfg_features}),
        _check("FEATURE_COUNT", len(x) == len(m.feature_names), value=len(x), expected=len(m.feature_names)),
        _check("TREE_COUNT", len(m.trees) == booster.num_trees(), value=len(m.trees), expected=booster.num_trees()),
    ]
    if not all(c["passed"] for c in checks):
        res = {"status": "FAILED", "identity": {**ident, "model_sha256_file": sha, "feature_row_hash": rhash}, "checks": checks}
        return res
    official = booster.predict(X, pred_contrib=True)[0]
    raw_model = float(booster.predict(X, raw_score=True)[0])
    out_model = float(booster.predict(X)[0])
    leaf_model = [int(v) for v in booster.predict(X, pred_leaf=True)[0]]
    try:
        tr_res = T.trace_row(m, x, collect=True, time_limit_s=TIME_LIMIT_S, max_components=MAX_COMPONENTS)
    except T.TraceError as e:
        raise AppError(e.code if e.code in ("TRACE_TIMEOUT", "TRACE_TOO_LARGE", "UNSUPPORTED_MODEL") else "REPRODUCTION_MISMATCH", 422, detail=e.detail)
    phi, base = tr_res["phi"], tr_res["base_value"]
    nf = len(phi)
    phi_diff = [abs(phi[i] - float(official[i])) for i in range(nf)]
    sum_phi = float(np.sum(np.asarray(phi, dtype=np.float64)))
    raw_attr = base + sum_phi
    link = "exp" if m.objective in ("tweedie", "poisson") else "identity"
    out_link = math.exp(raw_model) if link == "exp" else raw_model
    clipped = max(out_model, 0.0)
    rounded = round(clipped, 4)
    checks += [
        _check("LEAF_PATHS", tr_res["leaves"] == leaf_model, detail=None if tr_res["leaves"] == leaf_model else
               [i for i, (a, b) in enumerate(zip(tr_res["leaves"], leaf_model)) if a != b][:20]),
        _check("SHAP_ENGINE_VS_LIGHTGBM", max(phi_diff) <= TOL_SHAP_ABS, max_abs_diff=max(phi_diff), tolerance=TOL_SHAP_ABS),
        _check("BASE_VALUE_ENGINE_VS_LIGHTGBM", abs(base - float(official[nf])) <= TOL_SHAP_ABS,
               engine=base, lightgbm=float(official[nf]), abs_diff=abs(base - float(official[nf])), tolerance=TOL_SHAP_ABS),
        _check("RAW_SCORE_ATTRIBUTION_VS_MODEL", abs(raw_attr - raw_model) <= TOL_RAW_ABS,
               from_attribution=raw_attr, from_model=raw_model, abs_diff=abs(raw_attr - raw_model), tolerance=TOL_RAW_ABS),
        _check("MODEL_OUTPUT_IS_LINK_OF_RAW", abs(out_link - out_model) <= TOL_OUTPUT_REL * max(1.0, abs(out_model)),
               link=link, link_of_raw=out_link, model_output=out_model, abs_diff=abs(out_link - out_model), tolerance=TOL_OUTPUT_REL),
        _check("PUBLISHED_VALUE", abs(rounded - val["yhat"]) <= TOL_PUBLISHED_ABS, clipped=clipped, rounded_4=rounded,
               published=val["yhat"], abs_diff=abs(rounded - val["yhat"]), tolerance=TOL_PUBLISHED_ABS),
        _check("COMPONENTS_SUM_TO_SHAP", True),   # filled below
    ]
    comps = tr_res["components"]
    per_feat = np.zeros(nf)
    for c in comps:
        per_feat[c[2]] += c[7]
    comp_diff = float(np.max(np.abs(per_feat - np.asarray(phi))))
    checks[-1] = _check("COMPONENTS_SUM_TO_SHAP", comp_diff <= TOL_RAW_ABS, max_abs_diff=comp_diff, tolerance=TOL_RAW_ABS,
                        note="sum of the recorded terms per feature, added in a different order than the recursion")
    status = "VERIFIED" if all(c["passed"] for c in checks) else "FAILED"
    res = {
        "status": status,
        "identity": {**ident, "model_sha256_file": sha, "feature_row_hash": rhash, "objective": m.objective, "link": link,
                     "n_trees": len(m.trees), "n_features": nf},
        "checks": checks,
        "values": {"base_value": base, "base_value_lightgbm": float(official[nf]), "sum_shap": sum_phi,
                   "raw_score_from_attribution": raw_attr, "raw_score_from_model": raw_model, "model_output": out_model,
                   "link_of_raw": out_link, "clipped": clipped, "rounded_4": rounded, "published": val["yhat"]},
        "features": [{"index": i, "name": m.feature_names[i], "value": None if math.isnan(x[i]) else x[i],
                      "shap_engine": phi[i], "shap_lightgbm": float(official[i]), "abs_diff": phi_diff[i]} for i in range(nf)],
        "seconds": tr_res["seconds"],
        "_model": m, "_x": x, "_comps": comps, "_routes": tr_res["routes"], "_leaves": tr_res["leaves"],
    }
    _cache[key] = res
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return res


def public(res: dict) -> dict:
    return {k: v for k, v in res.items() if not k.startswith("_")}


def _feature_index(res: dict, feature: str) -> int:
    names = res["_model"].feature_names
    if feature not in names:
        raise AppError("UNKNOWN_FEATURE", 404, detail=feature)
    return names.index(feature)


def feature_view(res: dict, feature: str, page: int = 1, page_size: int = 25, sort: str = "impact") -> dict:
    """Level A summary + level B per-tree table (paged) for one feature."""
    fi = _feature_index(res, feature)
    m: T.Model = res["_model"]
    by_tree: dict[int, dict] = {}
    for (ti, leaf, f, one, zero, w, v, term) in res["_comps"]:
        if f != fi:
            continue
        d = by_tree.setdefault(ti, {"tree": ti, "sum": 0.0, "positive": 0.0, "negative": 0.0, "n_terms": 0})
        d["sum"] += term
        d["n_terms"] += 1
        if term > 0:
            d["positive"] += term
        elif term < 0:
            d["negative"] += term
    trees_split = []
    for t in m.trees:
        nodes = [n for n in range(t.num_leaves - 1) if t.split_feature[n] == fi] if t.num_leaves > 1 else []
        if nodes:
            trees_split.append(t.index)
            d = by_tree.setdefault(t.index, {"tree": t.index, "sum": 0.0, "positive": 0.0, "negative": 0.0, "n_terms": 0})
            x = res["_x"][fi]
            d["splits"] = [{"node": n, "split": t.split_text(n, m.feature_names),
                            "row_goes": "left" if t.decision(x, n) == t.left_child[n] else "right"} for n in nodes]
            d["actual_leaf"] = res["_leaves"][t.index]
            d["actual_leaf_value"] = t.leaf_value[res["_leaves"][t.index]]
            d["expected_value"] = t.expected_value()
    rows = list(by_tree.values())
    rows.sort(key=(lambda r: -abs(r["sum"])) if sort == "impact" else (lambda r: r["tree"]))
    page_size = max(1, min(page_size, 200))
    total = len(rows)
    f = res["features"][fi]
    cat = feature_catalog.describe(feature, res["identity"]["target_date"])
    pos_trees = sum(r["sum"] for r in rows if r["sum"] > 0)
    neg_trees = sum(r["sum"] for r in rows if r["sum"] < 0)
    return {
        "status": res["status"], "identity": res["identity"],
        "feature": {**f, "catalog": {"vi": cat["vi"], "en": cat["en"]}, "window": cat["window"],
                    "includes_target_day": cat["includes_target_day"]},
        "summary": {"n_trees_model": len(m.trees), "n_trees_splitting_on_feature": len(trees_split),
                    "n_trees_with_terms": sum(1 for r in rows if r["n_terms"]),
                    "n_terms": sum(r["n_terms"] for r in rows),
                    "sum_positive_trees": pos_trees, "sum_negative_trees": neg_trees,
                    "sum_positive_terms": sum(r["positive"] for r in rows), "sum_negative_terms": sum(r["negative"] for r in rows),
                    "total": f["shap_engine"]},
        "trees": {"total": total, "page": page, "page_size": page_size,
                  "items": rows[(page - 1) * page_size: page * page_size]},
    }


def _route_text(m: T.Model, t: T.Tree, route: list, fi: int | None = None) -> list[dict]:
    return [{"node": n, "split": t.split_text(n, m.feature_names), "went": "left" if child == t.left_child[n] else "right",
             "row_goes_this_way": hot, "cover_fraction": frac, "is_feature": (fi is not None and t.split_feature[n] == fi)}
            for (n, child, hot, frac) in route]


def tree_terms(res: dict, feature: str, tree: int) -> dict:
    """Level B detail: every leaf term of one feature in one tree."""
    fi = _feature_index(res, feature)
    m: T.Model = res["_model"]
    t = m.trees[tree]
    items = []
    for (ti, leaf, f, one, zero, w, v, term) in res["_comps"]:
        if ti != tree or f != fi:
            continue
        route = res["_routes"][(ti, leaf)]
        items.append({"leaf": leaf, "leaf_value": v, "leaf_count": t.leaf_count[leaf], "row_reaches_leaf": res["_leaves"][ti] == leaf,
                      "one_fraction": one, "zero_fraction": zero, "weight": w, "one_minus_zero": one - zero, "term": term,
                      "route": _route_text(m, t, route, fi)})
    return {"tree": tree, "feature": feature, "expected_value": t.expected_value(), "root_count": t.internal_count[0] if t.num_leaves > 1 else None,
            "actual_leaf": res["_leaves"][tree], "items": items, "sum": sum(i["term"] for i in items)}


def export_rows(res: dict, feature: str | None):
    """Rows for CSV/Excel: per feature x tree x leaf term, plus summaries."""
    m: T.Model = res["_model"]
    fi = _feature_index(res, feature) if feature else None
    terms = []
    for (ti, leaf, f, one, zero, w, v, term) in res["_comps"]:
        if fi is not None and f != fi:
            continue
        route = res["_routes"][(ti, leaf)]
        t = m.trees[ti]
        terms.append((m.feature_names[f], ti, leaf, v, res["_leaves"][ti] == leaf, one, zero, w, one - zero, term,
                      " > ".join(f"n{n}:{t.split_text(n, m.feature_names)}→{'L' if c == t.left_child[n] else 'R'}{'' if hot else '*'}"
                                 for (n, c, hot, frac) in route)))
    return terms
