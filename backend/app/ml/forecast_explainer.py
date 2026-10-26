"""1.2.14 LightGBM forecast explainer: how ONE stored forecast value of the forecast in use was computed, step by step.

Read-only. For one series (SKU x FC) and one forecast day of the forecast run in use (the latest published run of the
active scope, pipeline.incumbent):
1. inputs   - the series' own rows of the run's training window (train_start..train_end), the scope's calendar of days
              with data (a day without any row in the whole scope is 'unknown', exactly as in the full panel) and the
              owner's open-hours override recorded with the run; the panel is built by the production build_panel;
2. features - the production origin_features / direct_extra (DIRECT strategy) with the category codes stored with the
              model (sidecar .json); each feature is ALSO recomputed independently from the series' values for display;
3. trees    - every tree of the saved model file walked with LightGBM's own decision rule (treeshap_trace.Tree.decision);
4. sum      - raw score = sum of the leaf values; output = exp(raw) for log-link objectives (tweedie / poisson / gamma);
5. result   - the published post-processing (clip at 0, round to 4 decimals, pipeline._publish_run) and the whole-number
              quantity (qty.business_qty), compared with the STORED value.
Every model step is checked against LightGBM itself (pred_leaf, raw_score, prediction). Nothing is trained, written or
approximated; the full-scope panel (~200 MB) is never built - only one series and the list of days with data.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .. import db, paths, qty
from .. import settings_service as ss
from ..data import open_hours_override
from ..data.demand import resolve_scope
from ..messages import AppError
from ..timeutil import now_iso, today_vn
from . import features as ft
from . import model, pipeline
from . import treeshap_trace as tt

LOG_LINK = ("tweedie", "poisson", "gamma")
IDENTITY_LINK = ("regression", "regression_l2", "l2", "mean_squared_error", "mse", "regression_l1", "l1", "huber", "fair",
                 "quantile", "mape")
RAW_TOL = 1e-9            # sum of the leaf values vs LightGBM raw score (same doubles, same order: normally 0)
OUT_TOL = 1e-12           # relative: link(raw) vs LightGBM prediction
STORED_TOL = 1e-9         # published value (rounded to 4 decimals) vs the stored yhat
FEATURE_TOL = 1e-6        # relative: independent recomputation vs the model input (a float32)
HISTORY_DAYS = 56
CANDIDATES = 8
CAT_SAMPLE = 20
SENTINEL = ("￿~scope-days", "￿~")
COLS = ["order_date", "sku_id", "fc_id", "qty", "n_orders", "avg_unit_price", "avg_discount_rate", "promo_share",
        "voucher_share", "open_hours", "customer_count", "repeat_customer_count", "repeat_interval_days_sum"]
# the stored columns build_panel turns into model inputs (n_orders / voucher_share are not read by any feature)
INPUT_COLS = ("qty", "avg_unit_price", "avg_discount_rate", "promo_share", "open_hours", "customer_count",
              "repeat_customer_count", "repeat_interval_days_sum")
# the calendar days start..end: demand_daily and demand_change_log are keyed (scope_key, order_date, sku_id, fc_id), so
# one series is read by one key lookup per day; a range on order_date alone walks every row of the window (1.4 M rows,
# seconds when the file cache of the PC is cold)
DAYS_CTE = "WITH RECURSIVE d(x) AS (SELECT ? UNION ALL SELECT date(x, '+1 day') FROM d WHERE x < ?) "
IDLE_S = 1800
FRESH_S = 60

_lock = threading.Lock()                            # one computation at a time (memory of the production PC)
_cache: "OrderedDict[tuple, dict]" = OrderedDict()  # full key -> result (with tree paths)
_CACHE_MAX = 4
_recent: dict[tuple, tuple] = {}                    # (run, sku, fc, date) -> (full key, time.monotonic()) freshness memo
_models: dict[str, tuple] = {}                      # sha256 -> (parsed model, tree-0 shrinkage), one entry
_last = [0.0]


def _num(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) or math.isinf(x) else x


def _expire() -> None:
    """Results and the parsed model are dropped after IDLE_S without a request (nothing is kept while nobody looks)."""
    if _last[0] and time.monotonic() - _last[0] > IDLE_S:
        _cache.clear()
        _recent.clear()
        _models.clear()
    _last[0] = time.monotonic()


def release_idle(max_idle_s: float = IDLE_S) -> int:
    n = len(_cache) + len(_models)
    if n and time.monotonic() - _last[0] > max_idle_s and _lock.acquire(blocking=False):
        try:
            _cache.clear()
            _recent.clear()
            _models.clear()
        finally:
            _lock.release()
        return n
    return 0


# ---------------------------------------------------------------- selection
def _status(code: str, reason: str, **extra) -> dict:
    return {"status": code, "reason": reason, **extra}


def _in_use(c) -> tuple[dict, dict] | None:
    scope = resolve_scope(c)
    inc = pipeline.incumbent(scope["scope_key"], c)
    return (inc["forecast_run"], inc["training_run"]) if inc and inc.get("training_run") else None


def _default_date(fr: dict) -> str:
    first = date.fromisoformat(fr["forecast_origin"])
    last = first + timedelta(days=int(fr["max_horizon"]) - 1)
    return min(max(today_vn(), first), last).isoformat()


def _override_keys(tr: dict) -> set:
    return {(a.get("sku_id"), a.get("fc_id")) for a in open_hours_override.recorded(tr)}


def _candidates(c, fr: dict, target_date: str, exclude: set) -> list[tuple[str, str]]:
    """LIGHTGBM series of the run for that day: most days with data in the last 28 days of the run's data, then the largest
    forecast of that day (the day count is read from the key index alone, without a table lookup per row)."""
    lo = (date.fromisoformat(fr["data_as_of"]) - timedelta(days=27)).isoformat()
    rows = db.rows(c, "WITH d28 AS (SELECT sku_id, fc_id, COUNT(*) AS n28 FROM demand_daily "
                      "WHERE scope_key=? AND order_date BETWEEN ? AND ? GROUP BY sku_id, fc_id) "
                      "SELECT v.sku_id, v.fc_id FROM forecast_values v JOIN d28 ON d28.sku_id=v.sku_id AND d28.fc_id=v.fc_id "
                      "WHERE v.run_id=? AND v.target_date=? AND v.method=? "
                      "ORDER BY d28.n28 DESC, v.yhat DESC, v.sku_id, v.fc_id LIMIT ?",
                   (fr["scope_key"], lo, fr["data_as_of"], fr["id"], target_date, model.METHOD_LGBM,
                    CANDIDATES + len(exclude)))
    return [(r["sku_id"], r["fc_id"]) for r in rows if (r["sku_id"], r["fc_id"]) not in exclude][:CANDIDATES]


def _series_rows(c, scope_key: str, sku: str, fc: str, start: str, end: str) -> pd.DataFrame:
    return pd.read_sql_query(DAYS_CTE + f"SELECT {', '.join(f'r.{k} AS {k}' for k in COLS)}, r.loaded_at AS loaded_at "
                             "FROM d CROSS JOIN demand_daily r ON r.scope_key=? AND r.order_date=d.x AND r.sku_id=? "
                             "AND r.fc_id=? ORDER BY r.order_date", c, params=[start, end, scope_key, sku, fc])


def _changes_after(c, fr: dict, tr: dict, sku: str, fc: str, rows: pd.DataFrame) -> dict:
    """Did this series' rows of the window change after the run was published? 1.2.13 logs every stored change with the
    whole row before / after (demand_change_log): a change of a model input is reverted to its value at the run
    (as_of_run), a change of another column (e.g. n_orders) or a reload with identical values changes no input.
    status: UNCHANGED | SAME_INPUTS | REVERTED_TO_RUN | UNKNOWN (rows reloaded and no change log to tell what changed)."""
    have_log = True
    try:
        log = db.rows(c, DAYS_CTE + "SELECT l.id AS id, l.run_id AS run_id, l.order_date AS order_date, l.action AS action, "
                         "l.before_json AS before_json, l.after_json AS after_json, l.at AS at FROM d CROSS JOIN "
                         "demand_change_log l ON l.scope_key=? AND l.order_date=d.x AND l.sku_id=? AND l.fc_id=? "
                         "WHERE l.at>? ORDER BY l.id",
                      (tr["train_start"], tr["train_end"], fr["scope_key"], sku, fc, fr["created_at"]))
    except Exception:  # noqa: BLE001 - a schema before migration 0010 has no change log
        log, have_log = [], False
    records, revert = [], []
    for r in log:
        b = json.loads(r["before_json"] or "null") or {}
        a = json.loads(r["after_json"] or "null") or {}
        changed = sorted(k for k in set(a) | set(b) if k != "loaded_at" and b.get(k) != a.get(k))
        is_input = r["action"] != "UPDATE" or any(k in INPUT_COLS for k in changed)
        records.append({"date": r["order_date"], "action": r["action"], "sync_run": r["run_id"], "at": r["at"],
                        "model_input": is_input,
                        "changed": {k: {"before": b.get(k), "after": a.get(k)} for k in changed}})
        if is_input:
            revert.append((r, b))
    later = rows[rows["loaded_at"] > fr["created_at"]] if len(rows) else rows
    status = ("UNCHANGED" if later.empty and not log else "UNKNOWN" if not have_log
              else "REVERTED_TO_RUN" if revert else "SAME_INPUTS")
    return {"status": status, "unchanged": status in ("UNCHANGED", "SAME_INPUTS"), "records": records[:100],
            "rows_loaded_after_run": int(len(later)), "run_created_at": fr["created_at"], "_revert": revert}


def _as_of_run(rows: pd.DataFrame, revert: list) -> pd.DataFrame:
    """The series' rows as they were when the run was published: the logged changes after it undone, newest first."""
    if not revert:
        return rows
    d = rows.copy()
    for r, b in sorted(revert, key=lambda x: -x[0]["id"]):
        m = d["order_date"] == r["order_date"]
        if r["action"] == "INSERT":
            d = d[~m]
        elif r["action"] == "UPDATE":
            for k in COLS + ["loaded_at"]:
                if k in b:
                    d.loc[m, k] = b[k]
        else:   # DELETE: the row existed at the run
            d = pd.concat([d, pd.DataFrame([{k: b.get(k) for k in COLS + ["loaded_at"]}])], ignore_index=True)
    return d.sort_values("order_date").reset_index(drop=True)


def _scope_days(c, scope_key: str, start: str, end: str) -> list[str]:
    return [r[0] for r in c.execute(DAYS_CTE + "SELECT x FROM d WHERE EXISTS (SELECT 1 FROM demand_daily WHERE scope_key=? "
                                    "AND order_date=d.x) ORDER BY x", (start, end, scope_key))]


# ---------------------------------------------------------------- model file
def _model(tr: dict) -> tuple[tt.Model, float | None, bytes] | None:
    """(parsed model, shrinkage of tree 0, file bytes) after the SHA-256 recorded with the training run matched."""
    mpath = paths.models_dir() / (tr.get("model_path") or "")
    if not tr.get("model_path") or not mpath.exists():
        return None
    raw = mpath.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != tr.get("model_sha256"):
        return None
    hit = _models.get(sha)
    if hit is None:
        text = raw.decode("utf-8")
        parsed = tt.parse_model(text)
        shrink = None
        i = text.find("Tree=0")
        if i >= 0:
            for ln in text[i:].splitlines()[1:]:
                if ln.startswith("Tree="):
                    break
                if ln.startswith("shrinkage="):
                    shrink = float(ln.split("=", 1)[1])
                    break
        _models.clear()
        _models[sha] = hit = (parsed, shrink)
    return hit[0], hit[1], raw


def _link(objective: str) -> str | None:
    if objective in LOG_LINK:
        return "log"
    if objective in IDENTITY_LINK:
        return "identity"
    return None


# ---------------------------------------------------------------- the panel of one series
def _panel(rows: pd.DataFrame, days: list[str], tr: dict, sku: str, fc: str) -> tuple[ft.Panel, list[dict]]:
    """The production build_panel on the series' rows + one row per day of the scope that has data (a sentinel series
    that only marks the days: 'unknown' days and the category columns of the panel are then exactly the full panel's)."""
    d = rows[COLS].copy()
    sent = pd.DataFrame({"order_date": days, "sku_id": SENTINEL[0], "fc_id": SENTINEL[1], "qty": 0.0, "n_orders": 0,
                         "avg_unit_price": np.nan, "avg_discount_rate": np.nan, "promo_share": np.nan,
                         "voucher_share": np.nan, "open_hours": np.nan, "customer_count": 0.0,
                         "repeat_customer_count": 0.0, "repeat_interval_days_sum": 0.0})
    d = pd.concat([d, sent], ignore_index=True)
    problems: list[dict] = []
    applied = [a for a in open_hours_override.recorded(tr) if (a.get("sku_id"), a.get("fc_id")) == (sku, fc)]
    if applied:      # the same owner rule the run's panel received (data/demand.panel_for_run)
        d, problems = open_hours_override.fill(d, applied)
    return ft.build_panel(d, end_date=tr["train_end"], start_date=tr["train_start"]), problems


# ---------------------------------------------------------------- features (production value + independent recomputation)
def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= FEATURE_TOL * max(1.0, abs(a), abs(b))


def _mean(vals: list) -> float | None:
    k = [v for v in vals if v is not None]
    return sum(k) / len(k) if k else None


def _feature_rows(names: list[str], row: np.ndarray, p: ft.Panel, s: int, mcfg, codes: dict, raw: pd.DataFrame,
                  target: pd.Timestamp, h: int) -> list[dict]:
    T = p.T
    y = p.Y[s]

    def day(i: int) -> str:
        return str(p.dates[i].date())

    def win(arr, w: int) -> list[dict]:
        return [{"date": day(i), "value": _num(arr[i])} for i in range(max(0, T - w), T)]

    raw_price = {str(r.order_date)[:10]: _num(r.avg_unit_price) for r in raw.itertuples() if _num(r.avg_unit_price) is not None}
    cal = dict(zip(ft.CALENDAR, ft.calendar_row(target, mcfg)))
    out = []
    for j, name in enumerate(names):
        v = _num(row[j])
        e: dict = {"name": name, "index": j, "value": v, "inputs": [], "params": {}}
        rec: float | None = None
        if name in ("sku_code", "fc_code"):
            key = codes["sku"] if name == "sku_code" else codes["fc"]
            rec = codes["sku_code"] if name == "sku_code" else codes["fc_code"]
            e.update(kind="category_code", params={"key": key, "categorical": True})
        elif name == "series_age":
            first = int(p.start_idx[s])
            rec = float(T - first)
            e.update(kind="age", params={"first_order_date": day(first) if first < T else None, "origin": str(
                (p.dates[-1] + pd.Timedelta(days=1)).date())})
        elif name.startswith("lag_"):
            k = int(name[4:])
            i = T - k
            rec = _num(y[i]) if i >= 0 else None
            e.update(kind="lag", params={"k": k}, inputs=[{"date": day(i), "value": rec}] if i >= 0 else [])
        elif name.startswith("roll_mean_"):
            w = int(name[10:])
            ins = win(y, w)
            known = [x["value"] for x in ins if x["value"] is not None]
            rec = _mean(known)
            e.update(kind="mean", params={"w": w, "n_known": len(known), "sum": sum(known) if known else None}, inputs=ins)
        elif name in ("roll_std_7", "roll_std_28"):
            w = int(name[9:])
            ins = win(y, w)
            known = [x["value"] for x in ins if x["value"] is not None]
            m = _mean(known)
            ss_dev = sum((x - m) ** 2 for x in known) if known else None
            rec = math.sqrt(ss_dev / len(known)) if len(known) > 1 else None
            e.update(kind="std", params={"w": w, "n_known": len(known), "mean": m, "sum_sq_dev": ss_dev}, inputs=ins)
        elif name == "zero_share_28":
            ins = win(y, 28)
            known = [x["value"] for x in ins if x["value"] is not None]
            zeros = sum(1 for x in known if x == 0)
            rec = zeros / len(known) if known else None
            e.update(kind="zero_share", params={"w": 28, "n_known": len(known), "zeros": zeros}, inputs=ins)
        elif name == "days_since_last_sale":
            lo = max(0, T - ft.LAST_SALE_WINDOW)
            sold = [i for i in range(lo, T) if not math.isnan(y[i]) and y[i] > 0.5]
            rec = float(T - sold[-1]) if sold else float(ft.LAST_SALE_WINDOW + 1)
            e.update(kind="days_since", params={"window": T - lo, "cap": ft.LAST_SALE_WINDOW + 1, "threshold": 0.5,
                                                "last_sale_date": day(sold[-1]) if sold else None,
                                                "last_sale_qty": _num(y[sold[-1]]) if sold else None})
        elif name == "roll_max_28":
            ins = win(y, 28)
            known = [x["value"] for x in ins if x["value"] is not None]
            rec = max(known) if known else None
            e.update(kind="max", params={"w": 28, "n_known": len(known)}, inputs=ins)
        elif name == "price_last":
            rec = _num(p.price[s, T - 1])
            src = max((d for d in raw_price if d <= day(T - 1)), default=None)
            e.update(kind="last_known", params={"day": day(T - 1), "source_date": src, "column": "avg_unit_price",
                                                "forward_filled": src is not None and src != day(T - 1)})
        elif name == "price_rel_28":
            pl = _num(p.price[s, T - 1])
            ins = win(p.price[s], 28)
            pm = _mean([x["value"] for x in ins])
            rec = pl / pm if pl is not None and pm and pm > 0 else None
            e.update(kind="ratio_to_mean", params={"numerator": pl, "mean": pm, "w": 28}, inputs=ins)
        elif name == "disc_last":
            rec = _num(p.disc[s, T - 1])
            e.update(kind="last_known", params={"day": day(T - 1), "column": "avg_discount_rate"})
        elif name == "promo_last":
            rec = _num(p.promo[s, T - 1])
            e.update(kind="value", params={"day": day(T - 1), "column": "promo_share"})
        elif name == "promo_mean_7":
            ins = win(p.promo[s], 7)
            rec = _mean([x["value"] for x in ins])
            e.update(kind="mean", params={"w": 7, "n_known": len(ins), "unknown_is_zero": True}, inputs=ins)
        elif name == "open_hours_last":
            rec = _num(p.hours[s, T - 1]) if p.hours is not None else None
            e.update(kind="value", params={"day": day(T - 1), "column": "open_hours"})
        elif name == "open_hours_mean_7":
            ins = win(p.hours[s], 7) if p.hours is not None else []
            known = [x["value"] for x in ins if x["value"] is not None]
            rec = _mean(known)
            e.update(kind="mean", params={"w": 7, "n_known": len(known), "sum": sum(known) if known else None}, inputs=ins)
        elif name in ft.CUSTOMER:
            lo = max(0, T - ft.CUSTOMER_WINDOW)
            n, r, iv = (p.customers[s], p.repeat_customers[s], p.repeat_interval[s])
            ins = [{"date": day(i), "customers": _num(n[i]), "repeat": _num(r[i]), "interval_sum": _num(iv[i])}
                   for i in range(lo, T)]
            if name == "cust_mean_28":
                known = [x["customers"] for x in ins if x["customers"] is not None]
                rec = _mean(known)
                e.update(kind="mean", params={"w": 28, "n_known": len(known), "sum": sum(known) if known else None})
            else:
                a, b = ("repeat", "customers") if name == "cust_repeat_share_28" else ("interval_sum", "repeat")
                both = [x for x in ins if x[a] is not None and x[b] is not None]
                sa, sb = sum(x[a] for x in both), sum(x[b] for x in both)
                rec = sa / sb if both and sb > 0 else None
                e.update(kind="ratio_of_sums", params={"w": 28, "numerator": a, "denominator": b, "sum_numerator": sa,
                                                       "sum_denominator": sb, "n_days": len(both)})
            e["inputs"] = ins
        elif name in ft.CALENDAR:
            rec = _num(cal[name])
            e.update(kind="calendar", params={"target_date": str(target.date()), "weekday_encoding": ft.weekday_encoding(mcfg),
                                              "days_in_month": int(target.days_in_month)})
        elif name == "horizon":
            rec = float(h)
            e.update(kind="horizon", params={"origin": str((p.dates[-1] + pd.Timedelta(days=1)).date()),
                                             "target_date": str(target.date())})
        else:
            e.update(kind="unknown")
        e["recomputed"] = rec
        e["verified"] = e["kind"] != "unknown" and _close(v, rec)
        out.append(e)
    return out


def _history(p: ft.Panel, s: int, raw: pd.DataFrame) -> list[dict]:
    rows = {str(r.order_date)[:10]: r for r in raw.itertuples()}
    T = p.T
    out = []
    for i in range(max(0, T - HISTORY_DAYS), T):
        dte = str(p.dates[i].date())
        r = rows.get(dte)
        y = _num(p.Y[s, i])
        state = ("BEFORE_FIRST_ORDER" if i < p.start_idx[s] else "UNKNOWN_DAY" if p.missing_days[i]
                 else "ROW" if r is not None else "NO_ROW_ZERO")
        out.append({"date": dte, "state": state, "qty_row": _num(r.qty) if r is not None else None, "y": y,
                    "n_orders": _num(r.n_orders) if r is not None else None,
                    "price_row": _num(r.avg_unit_price) if r is not None else None, "price_used": _num(p.price[s, i]),
                    "open_hours": _num(p.hours[s, i]) if p.hours is not None else None,
                    "customers": _num(p.customers[s, i]) if p.customers is not None else None})
    return out


# ---------------------------------------------------------------- the trees
def _step(tree: tt.Tree, node: int, names: list[str], v: float, nxt: int) -> dict:
    f = tree.split_feature[node]
    dt = tree.decision_type[node]
    goes = "left" if nxt == tree.left_child[node] else "right"
    base = {"node": node, "feature": names[f], "feature_index": f, "value": _num(v), "goes": goes}
    if dt & tt.K_CATEGORICAL_MASK:
        cat_idx = int(tree.threshold[node])
        lo, hi = tree.cat_boundaries[cat_idx], tree.cat_boundaries[cat_idx + 1]
        cats = [w * 32 + b for w, word in enumerate(tree.cat_threshold[lo:hi]) for b in range(32) if (word >> b) & 1]
        ival = None if math.isnan(v) else int(v)
        rule = "MISSING_RIGHT" if ival is None or ival < 0 else ("IN_SET" if ival in cats else "NOT_IN_SET")
        return {**base, "kind": "categorical", "rule": rule, "n_categories": len(cats), "in_set": ival in cats,
                "categories_sample": cats[:CAT_SAMPLE]}
    missing = (dt >> 2) & 3
    default_left = bool(dt & tt.K_DEFAULT_LEFT_MASK)
    used = v
    nan_as_zero = math.isnan(v) and missing != tt.MISSING_NAN
    if nan_as_zero:
        used = 0.0
    if (missing == tt.MISSING_ZERO and -tt.K_ZERO_THRESHOLD <= used <= tt.K_ZERO_THRESHOLD) or \
            (missing == tt.MISSING_NAN and math.isnan(v)):
        rule = "DEFAULT"
    else:
        rule = "LE" if used <= tree.threshold[node] else "GT"
    return {**base, "kind": "numerical", "threshold": tree.threshold[node], "missing_type": ("None", "Zero", "NaN")[missing],
            "default_left": default_left, "nan_as_zero": nan_as_zero, "rule": rule}


def _walk(tree: tt.Tree, row: np.ndarray, names: list[str]) -> tuple[int, float, list[dict]]:
    if tree.num_leaves == 1:
        return 0, tree.leaf_value[0], []
    node, steps = 0, []
    while node >= 0:
        v = float(row[tree.split_feature[node]])
        nxt = tree.decision(v, node)
        steps.append(_step(tree, node, names, v, nxt))
        node = nxt
    return ~node, tree.leaf_value[~node], steps


# ---------------------------------------------------------------- main
def _params(sku_id, fc_id, target_date) -> str | None:
    if bool(sku_id) != bool(fc_id):
        return "sku_id and fc_id must be given together"
    if target_date:
        try:
            date.fromisoformat(target_date)
        except ValueError:
            return "target_date must be YYYY-MM-DD"
    return None


def explain(sku_id: str | None = None, fc_id: str | None = None, target_date: str | None = None) -> dict:
    """The explanation (without the per-tree paths: see trees_page)."""
    res = _result(sku_id, fc_id, target_date)
    if res.get("status") != "OK":
        return res
    return {k: v for k, v in res.items() if k != "_paths"}


def trees_page(offset: int = 0, limit: int = 20, sku_id: str | None = None, fc_id: str | None = None,
               target_date: str | None = None) -> dict:
    res = _result(sku_id, fc_id, target_date)
    if res.get("status") != "OK":
        return res
    paths_ = res["_paths"]
    page = paths_[offset:offset + limit]
    return {"status": "OK", "selection": res["selection"], "model_version": res["run"]["model_version"],
            "offset": offset, "limit": limit, "total": len(paths_), "trees": page}


def _result(sku_id, fc_id, target_date) -> dict:
    bad = _params(sku_id, fc_id, target_date)
    if bad:
        return _status("BAD_REQUEST", bad)
    with _lock:
        _expire()
        t0 = time.perf_counter()
        with db.read() as c:
            try:
                inuse = _in_use(c)
            except AppError as e:
                return _status("NO_FORECAST", e.code)
            if not inuse:
                return _status("NO_FORECAST", "no published forecast run for the active data source")
            fr, tr = inuse
            if fr["data_source"] == "DEMO":     # the explainer shows real forecasts only, never generated demo data
                return _status("NO_FORECAST", "DEMO_SOURCE: the forecast in use is built on demo data")
            day = target_date or _default_date(fr)
            # every stored change of a sync is logged: a new log id ends the freshness memo at once
            try:
                log_id = c.execute("SELECT MAX(id) FROM demand_change_log").fetchone()[0]
            except Exception:  # noqa: BLE001 - schema before migration 0010
                log_id = None
            memo_key = (fr["id"], sku_id, fc_id, day, log_id)
            memo = _recent.get(memo_key)
            if memo and time.monotonic() - memo[1] <= FRESH_S and memo[0] in _cache:
                hit = _cache[memo[0]]
                _cache.move_to_end(memo[0])
                return {**hit, "cache": "HIT"}
            res = _compute(c, fr, tr, sku_id, fc_id, day)
        if res.get("status") == "OK":
            key = res.pop("_key")
            if res.pop("cache", None) != "HIT":
                res["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
                _cache[key] = res
                if len(_cache) > _CACHE_MAX:
                    _cache.popitem(last=False)
                res = {**res, "cache": "MISS"}
            else:
                res = {**res, "cache": "HIT"}
            _recent[memo_key] = (key, time.monotonic())
        return res


def _compute(c, fr: dict, tr: dict, sku_id, fc_id, day: str) -> dict:
    mcfg = ss.ModelSettings.model_validate(json.loads(tr["feature_config_json"])["config"])
    run_info = {"forecast_run_id": fr["id"], "model_version": fr["model_version"], "training_run_id": tr["id"],
                "forecast_origin": fr["forecast_origin"], "data_as_of": fr["data_as_of"], "run_created_at": fr["created_at"],
                "max_horizon": fr["max_horizon"], "data_source": fr["data_source"], "train_start": tr["train_start"],
                "train_end": tr["train_end"], "strategy": "DIRECT" if ft.is_direct(mcfg) else "RECURSIVE",
                "objective": mcfg.objective}
    if not ft.is_direct(mcfg):
        return _status("UNSUPPORTED_STRATEGY", "only DIRECT models are explained step by step", run=run_info)
    if not (fr["forecast_origin"] <= day <= (date.fromisoformat(fr["forecast_origin"])
                                            + timedelta(days=int(fr["max_horizon"]) - 1)).isoformat()):
        return _status("NOT_FOUND", f"{day} is outside the forecast days of {fr['id']}", run=run_info)
    auto = not sku_id
    picked, rows, changes = None, None, None
    tried = [(sku_id, fc_id)] if not auto else _candidates(c, fr, day, _override_keys(tr))
    if not tried:
        return _status("NOT_FOUND", "no LIGHTGBM series with recent data in the forecast in use", run=run_info)
    for sku, fc in tried:
        r = _series_rows(c, fr["scope_key"], sku, fc, tr["train_start"], tr["train_end"])
        ch = _changes_after(c, fr, tr, sku, fc, r)
        if picked is None or (auto and ch["unchanged"] and not changes["unchanged"]):
            picked, rows, changes = (sku, fc), r, ch
        if ch["unchanged"] or not auto:
            break
    sku, fc = picked
    val = db.one(c, "SELECT * FROM forecast_values WHERE run_id=? AND sku_id=? AND fc_id=? AND target_date=?",
                 (fr["id"], sku, fc, day))
    sel = {"sku_id": sku, "fc_id": fc, "target_date": day, "auto": auto,
           "rule": "AUTO_MOST_COMPLETE_LIGHTGBM_SERIES" if auto else "REQUESTED"}
    if not val:
        return _status("NOT_FOUND", f"{sku} / {fc} / {day} is not in {fr['id']}", run=run_info, selection=sel)
    sel["horizon_day"] = h = int(val["horizon_day"])
    if val["method"] != model.METHOD_LGBM:
        return _status("NOT_LIGHTGBM", f"this value was published by the rule {val['method']}, not by the LightGBM model",
                       run=run_info, selection=sel, stored={"yhat": val["yhat"], "method": val["method"],
                                                            "forecast_qty": qty.business_qty(val["yhat"])})
    if rows is None or rows.empty:
        return _status("DATA_UNAVAILABLE", "the series has no stored row in the run's data window", run=run_info, selection=sel)
    days = _scope_days(c, fr["scope_key"], tr["train_start"], tr["train_end"])
    # the same run, model, series data and calendar of days = the same explanation: no recomputation
    key = (fr["id"], tr["id"], tr.get("model_sha256"), sku, fc, day, len(rows), str(rows["loaded_at"].max()), len(days),
           len(changes["records"]), changes["status"])
    last_loaded = str(rows["loaded_at"].max())
    rows = _as_of_run(rows, changes["_revert"])     # the inputs as they were when the run was published
    if key in _cache:
        _cache.move_to_end(key)
        return {**_cache[key], "_key": key, "cache": "HIT"}
    m = _model(tr)
    if m is None:
        return _status("MODEL_MISSING", "model file missing or its SHA-256 differs from the training run", run=run_info,
                       selection=sel)
    parsed, shrink0, model_bytes = m
    p, ov_problems = _panel(rows, days, tr, sku, fc)
    if str(p.dates[-1].date()) != fr["data_as_of"] or (sku, fc) not in p.keys:
        return _status("DATA_UNAVAILABLE", "the stored data window does not end on the run's data_as_of", run=run_info,
                       selection=sel)
    s = p.keys.index((sku, fc))
    names = ft.feature_names(mcfg)
    side = json.loads((paths.models_dir() / (Path(tr["model_path"]).stem + ".json")).read_text(encoding="utf-8"))
    codes = {"sku": sku, "fc": fc, "sku_code": float(side["sku_codes"].get(sku, -1)),
             "fc_code": float(side["fc_codes"].get(fc, -1))}
    sc = np.array([side["sku_codes"].get(k[0], -1) for k in p.keys], dtype=float)
    fcc = np.array([side["fc_codes"].get(k[1], -1) for k in p.keys], dtype=float)
    target = p.dates[-1] + pd.Timedelta(days=h)
    # exactly model._forecast_direct: origin features of the series (data < T) + target-day calendar + horizon, float32
    xb = ft.origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, p.T, mcfg, sc, fcc)
    extra = np.array(ft.direct_extra(mcfg, target, h), dtype=np.float32)
    X = np.hstack([xb[s:s + 1], np.tile(extra, (1, 1))])
    row = X[0]
    method_now = str(model.classification_details(p, mcfg)["methods"][s])
    feats = _feature_rows(names, row, p, s, mcfg, codes, rows, target, h)

    leaves, values, paths_ = [], [], []
    for t in parsed.trees:
        leaf, lv, steps = _walk(t, row, names)
        leaves.append(leaf)
        values.append(lv)
        paths_.append({"index": t.index, "leaf": leaf, "leaf_value": lv, "depth": len(steps), "steps": steps})
    raw_sum = 0.0
    for lv in values:                       # LightGBM adds the trees' outputs in this order
        raw_sum += lv
    link = _link(parsed.objective)
    pred = math.exp(raw_sum) if link == "log" else raw_sum if link == "identity" else None

    import lightgbm as lgb
    booster = lgb.Booster(model_str=model_bytes.decode("utf-8"))
    try:
        raw_lgb = float(booster.predict(X, raw_score=True)[0])
        pred_lgb = float(booster.predict(X)[0])
        leaf_lgb = [int(v) for v in booster.predict(X, pred_leaf=True)[0]]
    finally:
        del booster
    # model._forecast_direct: np.clip(pred, 0, None) on the float64 prediction; pipeline._publish_run: round() of that
    # numpy float64 to 4 decimals (numpy's rounding, applied to the same type here)
    clipped = np.clip(np.asarray([pred_lgb], dtype=np.float64), 0, None)[0]
    published = float(round(clipped, 4))
    stored = float(val["yhat"])
    checks = [
        {"check": "FEATURE_NAMES", "ok": names == list(side["features"]) == parsed.feature_names,
         "detail": f"{len(names)} features (settings = model sidecar = model file)"},
        {"check": "METHOD_LIGHTGBM", "ok": method_now == model.METHOD_LGBM, "detail": method_now},
        {"check": "FEATURES_RECOMPUTED", "ok": all(f["verified"] for f in feats),
         "detail": f"{sum(f['verified'] for f in feats)}/{len(feats)}"},
        {"check": "TREE_LEAVES_EQUAL_LIGHTGBM", "ok": leaves == leaf_lgb, "detail": f"{len(leaves)} trees"},
        {"check": "RAW_SUM_EQUALS_LIGHTGBM", "ok": abs(raw_sum - raw_lgb) <= RAW_TOL, "detail": raw_sum - raw_lgb},
        {"check": "OUTPUT_TRANSFORM_EQUALS_LIGHTGBM", "ok": pred is not None and abs(pred - pred_lgb) <= OUT_TOL * max(1.0, abs(pred_lgb)),
         "detail": None if pred is None else pred - pred_lgb},
        {"check": "PUBLISHED_EQUALS_STORED", "ok": abs(published - stored) <= STORED_TOL, "detail": published - stored},
        {"check": "INPUTS_AS_AT_RUN", "ok": changes["status"] in ("UNCHANGED", "SAME_INPUTS", "REVERTED_TO_RUN"),
         "detail": changes["status"]},
        {"check": "OPEN_HOURS_OVERRIDE", "ok": not ov_problems, "detail": ov_problems or None},
    ]
    pos = sum(v for v in values if v > 0)
    neg = sum(v for v in values if v < 0)
    top = sorted(range(len(values)), key=lambda i: -abs(values[i]))[:10]
    first_order = int(p.start_idx[s])
    return {
        "status": "OK",
        "reason": None,
        "_key": key,
        "_paths": paths_,
        "computed_at": now_iso(),
        "selection": sel,
        "run": run_info,
        "data": {"rows_in_window": int(len(rows)), "first_order_date": str(p.dates[first_order].date()) if first_order < p.T else None,
                 "last_loaded_at": last_loaded, "scope_days_with_data": len(days),
                 "unknown_days_in_window": int(p.missing_days.sum()), "history": _history(p, s, rows),
                 "changes_after_run": {k: v for k, v in changes.items() if not k.startswith("_")},
                 "override_applied": bool(_override_keys(tr) & {(sku, fc)}),
                 "origin": str((p.dates[-1] + pd.Timedelta(days=1)).date())},
        "features": feats,
        "trees": {"count": len(values), "tree0_shrinkage": shrink0, "tree0_value": values[0] if values else None,
                  "rest_sum": raw_sum - values[0] if values else None, "positive_sum": pos, "negative_sum": neg,
                  "top": [{"index": i, "leaf": leaves[i], "leaf_value": values[i]} for i in top],
                  "summary": [{"index": x["index"], "leaf": x["leaf"], "leaf_value": x["leaf_value"], "depth": x["depth"]}
                              for x in paths_]},
        "aggregation": {"objective": parsed.objective, "link": link, "raw_sum": raw_sum, "raw_lightgbm": raw_lgb,
                        "prediction": pred, "prediction_lightgbm": pred_lgb,
                        "tweedie_variance_power": json.loads(tr.get("params_json") or "{}").get("tweedie_variance_power")},
        "result": {"clipped": float(clipped), "published": published, "stored_yhat": stored,
                   "difference": published - stored, "match": abs(published - stored) <= STORED_TOL,
                   "forecast_qty": qty.business_qty(stored), "forecast_qty_recomputed": qty.business_qty(published),
                   "qty_rule": qty.RULE, "method": val["method"]},
        "checks": checks,
        "verified": all(ch["ok"] for ch in checks),
    }
