"""1.4.6 (owner decision 06/11/2026 21:20, C3): explanation of the SEL2 number of forecast day D, sheet GIAI_THICH of the
daily Excel (export.py). No database table: the pipeline writes one sidecar per published SEL2 run, the export reads it.

Sidecar (pipeline.run_day, after the publication and before the export, in a CHILD PROCESS: python -m
app.ml.sel2.giai_thich, child_main; the parent has freed the day's inputs, checks the free commit first and kills the
child after a timeout, pipeline._giai_thich_hook):
  <models dir>/sel2/<scope hash>/giai_thich/<D>_<run id>.json.gz, gzip JSON, written atomically (temporary file +
  os.replace). The selection arrays come from the parent (select_day(detail=...), a temporary .npz next to it); the
  child reads the day's inputs and the model files again. A skipped / failed / timed-out step writes
  <D>_<run id>.status.json (status, reason) and never fails the published run or its export: the file is then written
  without the sheet GIAI_THICH and with the file flag GIAI_THICH_SKIPPED (the other sheets are unchanged). A run
  published before 1.4.6 has neither file: no sheet, no flag. Derived data only: excluded from the backups
  (backup.py) and deleted with the candidate forecasts (apply_retention: forecast days before D - retention_days).
  Per series of the run's scope (sku_code, fc_code), columns in "cols":
    model_used, ok, nday, second (candidate ranked 2nd), fb (FALLBACK code: NO_OPEN_DAY / FEW_DAYS / SECOND_MISSING)
      = the arrays of select.select_day(detail=...) of the published selection (same scores, same order);
    val_<i> / dung_<i> / cham_<i> per candidate i (select.CANDIDATES order): the stored candidate forecast of D at
      horizon 1 (candidate_forecasts, read by store.read_day), the DUNG cells and the scored cells of the selection
      window D-W .. D-1 (select._scores: n_dung, n_cells);
    yday, mean7, mean28, med28, open28, sale28, last_sale, closed: history of the inputs (data.Inputs, rows < D):
      demand of D-1 (no row = 0, as select.py), means / median over the 28 calendar days D-28 .. D-1 (no row = 0), days
      with open hours > 0 (lag-filled calendar, as select.py) / with demand > 0 in those 28 days, last day with demand
      > 0 within the data window, consecutive days not open before D (up to CLOSED_SCAN days);
    p_v36: P(order) of the V36_two_stage classifier at horizon 1 (empty without that model);
    f_model, f_part, f_base, f_raw, f_pred, f_match, f_top: the 3 strongest factors (TreeSHAP, LightGBM
      predict(pred_contrib=True)) of the factor model of the series = the best-ranked LightGBM candidate of model_used
      (FALLBACK:<m> -> m); V36_two_stage: its quantity model when P >= p_threshold, else its classifier. f_base =
      expected value (bias column), f_raw = raw score = f_base + sum of every contribution (SHAP additivity), f_pred =
      the model's prediction, f_match = f_pred equals the stored candidate value (the inputs of the run's candidates);
      f_top = [name, feature value, contribution] x 3, by |contribution| descending.
  The design matrix of horizon 1 is rebuilt exactly as lgbm.forecast builds it (one panel per max_train_days, shared
  by the three models); pred_contrib runs only on the rows whose factor model it is (vectorised, one call per model
  part).

Sheet rows (export.py): one row per SKU x FC of the file whose lightgbm_forecast at horizon 1 is not empty, in the
order of the DU_BAO_* sheets; the explanation is that of the run whose number the row shows (today's run, or the
previous run of its flag LAN_CHAY_TRUOC:<day>). ly_do (forecast_used = 0 only) follows the rules of ly_do()."""
from __future__ import annotations

import gzip
import json
import logging
import math
import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ... import db
from ...export_i18n import giai_thich_labels
from ...timeutil import now_iso
from .. import feature_catalog
from ..features import direct_extra
from . import lgbm, select, store
from .data import DAY0
from .errors import Sel2Error

log = logging.getLogger("df.sel2.giai_thich")
FORMAT = 1
SUBDIR = "giai_thich"
SHEET = "GIAI_THICH"
HIST_DAYS = 28
CLOSED_SCAN = 365                          # consecutive closed days counted up to this many
CLOSED_MIN = 7                             # ly_do "khong mo ban N ngay" from this many closed days before D
TOP_K = 3
USED_THRESHOLD = 0.2                       # = export.USED_THRESHOLD / select.THRESHOLD
TRAIN_OF = {"MOC": "MOC", "V33_L112": "V33_L112", "V36_two_stage@0.6": "V36_two_stage"}   # pipeline.NAME inverse
TWO_STAGE = "V36_two_stage@0.6"
FB_NO_OPEN, FB_FEW, FB_SECOND = "NO_OPEN_DAY", "FEW_DAYS", "SECOND_MISSING"
REASON_OUT_ZERO, REASON_NO_NUMBER = "NGOAI_PHAM_VI_GAN_0", "KHONG_CO_SO_NAO"     # = export.REASON_*
REASON_AVG_MISSING_LGBM = "KHONG_CO_AVG_DUNG_LIGHTGBM"                         # = export.REASON_AVG_MISSING_LGBM
FLAG_SKIPPED = "GIAI_THICH_SKIPPED"        # file flag of the export: today's run has a status file, no sidecar
STATUS_OK = "OK"
FLAG_PREVIOUS = "LAN_CHAY_TRUOC"           # = export.FLAG_PREVIOUS
LIGHTGBM = "LIGHTGBM"


# ------------------------------------------------------------------ sidecar files
def sidecar_path(scope_key: str, d, run_id: str) -> Path:
    return store.scope_dir(scope_key) / SUBDIR / f"{str(d)[:10]}_{run_id}.json.gz"


def write(scope_key: str, d, run_id: str, payload: dict) -> Path:
    p = sidecar_path(scope_key, d, run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)
    return p


def status_path(scope_key: str, d, run_id: str) -> Path:
    return store.scope_dir(scope_key) / SUBDIR / f"{str(d)[:10]}_{run_id}.status.json"


def write_status(scope_key: str, d, run_id: str, status: dict) -> None:
    p = status_path(scope_key, d, run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(status, ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)


def read_status(scope_key: str | None, d, run_id: str | None) -> dict | None:
    if not scope_key or not run_id:
        return None
    try:
        return json.loads(status_path(scope_key, d, run_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def exists(scope_key: str | None, d, run_id: str | None) -> bool:
    return bool(scope_key and run_id) and sidecar_path(scope_key, d, run_id).is_file()


DETAIL_KEYS = ("value_h1", "n_cells", "n_dung", "rate", "shortage", "nday", "ok", "first", "second", "second_ok")


def save_detail(path: Path, det: dict) -> None:
    """The selection arrays of select_day(detail=...) for the child (numpy .npz, no pickle)."""
    keys = list(det["keys"])
    with open(path, "wb") as f:
        np.savez(f, sku=np.array([k[0] for k in keys], dtype=str), fc=np.array([k[1] for k in keys], dtype=str),
                 candidates=np.array(det["candidates"], dtype=str), **{k: np.asarray(det[k]) for k in DETAIL_KEYS})


def load_detail(path: Path) -> dict:
    with np.load(path, allow_pickle=False) as z:
        det = {k: z[k] for k in DETAIL_KEYS}
        det["candidates"] = z["candidates"].tolist()
        det["keys"] = list(zip(z["sku"].tolist(), z["fc"].tolist()))
    return det


def apply_retention(d: date, retention_days: int) -> dict:
    """Sidecar / status files of forecast days before d - retention_days deleted, every scope (the window of
    store.apply_retention for candidate_forecasts; the files are derived data)."""
    cutoff = str(d - timedelta(days=int(retention_days)))
    root = store.scope_dir("x").parent
    n = 0
    for f in sorted(root.glob(f"*/{SUBDIR}/*")):
        day = f.name[:10]
        if f.is_file() and len(day) == 10 and day[4] == "-" and day < cutoff:
            f.unlink(missing_ok=True)
            n += 1
    return {"cutoff": cutoff, "files": n}


def load(scope_key: str | None, d, run_id: str | None) -> dict | None:
    """The sidecar of a run with its key index ("index": {(sku, fc): row}); None when missing / unreadable / of
    another format (logged)."""
    if not scope_key or not run_id:
        return None
    p = sidecar_path(scope_key, d, run_id)
    if not p.is_file():
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            doc = json.load(f)
        if doc.get("format") != FORMAT or doc.get("run_id") != run_id:
            raise ValueError(f"format {doc.get('format')} / run {doc.get('run_id')}")
        doc["index"] = {k: i for i, k in enumerate(zip(doc["sku"], doc["fc"]))}
        return doc
    except (OSError, ValueError, KeyError, TypeError, EOFError) as e:
        log.warning("sel2 giai_thich sidecar not read", extra={"ctx": {"path": str(p), "error": f"{type(e).__name__}: {e}"[:300]}})
        return None


# ------------------------------------------------------------------ pure parts
def _col(a) -> list:
    """JSON list of an array: NaN / inf -> None, numpy scalars -> Python."""
    a = np.asarray(a)
    if a.dtype.kind == "f":
        return [None if not math.isfinite(x) else x for x in a.astype(float).tolist()]
    return a.tolist()


def history_stats(daily: np.ndarray, oh: np.ndarray, g: int, days: int = HIST_DAYS,
                  closed_scan: int = CLOSED_SCAN) -> dict:
    """History of the series (rows of daily / oh: K x G day arrays from DAY0, data.Inputs) before day index g (= D):
    yday, mean7, mean28, med28 (calendar days, no row = 0), open28 (open hours > 0), sale28 (demand > 0), last (day
    index of the last demand > 0 before g, -1 = none), closed (consecutive days before g not open, up to closed_scan)."""
    K = daily.shape[0]
    lo, lo7 = max(g - days, 0), max(g - 7, 0)
    win = daily[:, lo:g]
    out = {"yday": daily[:, g - 1].astype(float) if g >= 1 else np.full(K, np.nan),
           "mean7": daily[:, lo7:g].mean(axis=1) if g > lo7 else np.full(K, np.nan),
           "mean28": win.mean(axis=1) if g > lo else np.full(K, np.nan),
           "med28": np.median(win, axis=1) if g > lo else np.full(K, np.nan),
           "open28": (np.nan_to_num(oh[:, lo:g]) > 0).sum(axis=1),
           "sale28": (win > 0).sum(axis=1)}
    sold = daily[:, :g] > 0
    anyl = sold.any(axis=1)
    out["last"] = np.where(anyl, g - 1 - np.argmax(sold[:, ::-1], axis=1), -1) if g else np.full(K, -1)
    s0 = max(g - closed_scan, 0)
    closed = ~(np.nan_to_num(oh[:, s0:g]) > 0)[:, ::-1]
    width = g - s0
    out["closed"] = np.where(closed.all(axis=1), width, np.argmin(closed, axis=1)) if width else np.zeros(K, dtype=int)
    return out


def fallback_code(ok: bool, nday: int, open28: int, second_has: bool) -> str | None:
    """Why select.py fell back for a series (None when it did not): not ok -> NO_OPEN_DAY (no open day in the window,
    nothing scored) or FEW_DAYS (fewer than min_days target days with cells); ok but the second candidate without a
    forecast of D -> SECOND_MISSING."""
    if ok and second_has:
        return None
    if not ok:
        return FB_NO_OPEN if nday == 0 and open28 == 0 else FB_FEW
    return FB_SECOND


def factor_model(model_used: str) -> str | None:
    """The LightGBM candidate explained for a model_used: the best-ranked LightGBM candidate of 'A+B', or <m> of
    FALLBACK:<m>; None when no chosen candidate is a LightGBM one."""
    m = str(model_used or "")
    parts = [m.split(":", 1)[1]] if m.startswith("FALLBACK:") else m.split("+")
    for p in parts:
        if p in TRAIN_OF:
            return p
    return None


def top_contributions(contrib: np.ndarray, X: np.ndarray, names: list, k: int = TOP_K) -> list:
    """Per row [[name, value, contribution] x k] by |contribution| descending (contrib = pred_contrib output: n x
    (F + 1), last column = expected value)."""
    F = len(names)
    c = contrib[:, :F]
    order = np.argsort(-np.abs(c), axis=1, kind="stable")[:, :k]
    rows = np.arange(len(c))[:, None]
    vals, cons = X[rows, order], c[rows, order]
    out = []
    for o, v, cc in zip(order.tolist(), vals.tolist(), cons.tolist()):
        out.append([[names[j], None if not math.isfinite(x) else x, y] for j, x, y in zip(o, v, cc)])
    return out


def design_h1(p, d: date, spec: dict, trained: dict) -> np.ndarray:
    """The design matrix of horizon 1 (target D) of every series of panel p, built as lgbm.forecast builds it."""
    cfg = trained["cfg"]
    names, no, _, _ = lgbm.names_of(cfg, spec)
    if names != list(trained["names"]):
        raise ValueError("forecast columns differ from the trained model's")
    S, T = p.Y.shape
    fx = lgbm._Extra(spec)
    Xb = lgbm.origin_block(p, cfg, T, no, trained["sku_codes"], trained["fc_codes"])
    target = pd.Timestamp(d)
    extra = np.tile(np.array(direct_extra(cfg, target, 1), dtype=np.float32), (S, 1))
    return np.hstack([Xb, fx.origin(p, T), fx.target(p, T, target), extra])


# ------------------------------------------------------------------ build (pipeline)
def _close(a, b) -> np.ndarray:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return np.isclose(a, b, rtol=1e-6, atol=1e-9) | (np.isnan(a) & np.isnan(b))


def _factors(d: date, frame: pd.DataFrame, keys: list, fm: list, train_ids: dict, p_threshold: float,
             need_prob: np.ndarray, value_h1: dict) -> dict:
    """Factor columns (see the module text) for the series `keys` (sku, fc) with factor models fm."""
    S = len(keys)
    out = {"p_v36": np.full(S, np.nan), "f_model": [None] * S, "f_part": [None] * S, "f_base": np.full(S, np.nan),
           "f_raw": np.full(S, np.nan), "f_pred": np.full(S, np.nan), "f_match": [None] * S, "f_top": [None] * S,
           "f_err": [None] * S}
    fm_arr = np.array([x or "" for x in fm], dtype=object)
    wanted = [m for m in TRAIN_OF if (fm_arr == m).any() or (m == TWO_STAGE and need_prob.any())]
    if not wanted:
        return out
    fr = lgbm.in_scope(lgbm.rows_before(frame, d), keys)
    panels: dict = {}
    pos = {k: i for i, k in enumerate(keys)}
    for name in wanted:
        tid = train_ids.get(name)
        run = None
        if tid:
            with db.read() as c:
                run = db.one(c, "SELECT * FROM candidate_train_runs WHERE id=?", (tid,))
        try:
            if run is None:
                raise Sel2Error("SEL2_NO_MODEL", detail=f"{name}: training {tid} not found")
            models, trained = store.load_train(run)
        except Sel2Error as e:                     # model file gone / changed: those series get their own text
            log.warning("sel2 giai_thich: model not loaded", extra={"ctx": {"model": name, "error": str(e)[:300]}})
            for i in np.nonzero(fm_arr == name)[0].tolist():
                out["f_err"][i] = name
            continue
        spec = lgbm.CANDIDATE_SPECS[TRAIN_OF[name]]
        cfg = trained["cfg"]
        pk = int(cfg.max_train_days)
        if pk not in panels:
            panels[pk] = lgbm.panel_of(fr, d, cfg)
        p = panels[pk]
        X = design_h1(p, d, spec, trained)
        rows = np.array([pos.get(k, -1) for k in p.keys], dtype=np.int64)    # panel row -> series index
        ok_rows = rows >= 0
        X, rows = X[ok_rows], rows[ok_rows]
        names = list(trained["names"])
        prob = None
        if "clf" in models:
            prob = models["clf"].predict(X)
            out["p_v36"][rows] = prob
        mine = fm_arr[rows] == name
        if not mine.any():
            continue
        parts = {"reg": mine}
        if prob is not None:
            parts = {"reg": mine & (prob >= p_threshold), "clf": mine & (prob < p_threshold)}
        stored = value_h1[name][rows]
        for part, m in parts.items():
            if not m.any():
                continue
            b = models[part]
            Xm = X[m]
            contrib = b.predict(Xm, pred_contrib=True)
            pred = b.predict(Xm)
            idx = rows[m]
            out["f_base"][idx] = contrib[:, -1]
            out["f_raw"][idx] = contrib.sum(axis=1)
            out["f_pred"][idx] = pred
            if part == "reg":
                check = np.clip(pred, 0, None)
            else:                                              # value of the two-stage candidate below p is 0
                check = np.zeros(len(pred))
            match = _close(check, stored[m])
            for j, i in enumerate(idx.tolist()):
                out["f_model"][i], out["f_part"][i], out["f_match"][i] = name, part, bool(match[j])
            for j, top in zip(idx.tolist(), top_contributions(contrib, Xm, names)):
                out["f_top"][j] = top
            del contrib
        del X
    return out


def build(d: date, inputs, sk: pd.DataFrame, det: dict, train_ids: dict, cfg, run_id: str, scope_key: str) -> dict:
    """Sidecar payload of the published selection of D (det = select_day(detail=...)); see the module text."""
    cands = list(det["candidates"])
    S = len(sk)
    keys = list(zip(sk["sku_code"], sk["fc_code"]))
    if list(det["keys"]) != keys:
        raise ValueError("selection detail: series differ from the scope of the day")
    m = inputs.scope_mask(d)
    g = inputs.g(d)
    h = history_stats(inputs.daily[m], inputs.oh[m], g)
    first, second, second_ok, ok, nday = det["first"], det["second"], det["second_ok"], det["ok"], det["nday"]
    have = ~np.isnan(det["value_h1"])
    names = np.array(cands, dtype=object)
    model_used = np.where(second_ok, names[first] + "+" + names[second], "FALLBACK:" + str(cfg.fallback_model))
    sr = np.arange(S)
    fb = [fallback_code(bool(o), int(n), int(op), bool(hs))
          for o, n, op, hs in zip(ok, nday, h["open28"], have[second, sr])]
    cols = {"model_used": model_used.tolist(), "ok": [bool(x) for x in ok], "nday": [int(x) for x in nday],
            "second": names[second].tolist(), "fb": fb}
    for i in range(len(cands)):
        cols[f"val_{i}"] = _col(det["value_h1"][i])
        cols[f"dung_{i}"] = _col(det["n_dung"][i])
        cols[f"cham_{i}"] = _col(det["n_cells"][i])
    last = [None if x < 0 else (DAY0 + timedelta(days=int(x))).isoformat() for x in h["last"].tolist()]
    cols.update(yday=_col(h["yday"]), mean7=_col(h["mean7"]), mean28=_col(h["mean28"]), med28=_col(h["med28"]),
                open28=_col(h["open28"]), sale28=_col(h["sale28"]), last_sale=last, closed=_col(h["closed"]))
    fm = [factor_model(x) for x in cols["model_used"]]
    need_prob = np.array([TWO_STAGE in str(x).replace("FALLBACK:", "").split("+") for x in cols["model_used"]])
    vh = {c: det["value_h1"][i] for i, c in enumerate(cands)}
    f = _factors(d, inputs.frame, keys, fm, train_ids, float(cfg.p_threshold), need_prob, vh)
    cols.update(p_v36=_col(f["p_v36"]), f_model=f["f_model"], f_part=f["f_part"], f_base=_col(f["f_base"]),
                f_raw=_col(f["f_raw"]), f_pred=_col(f["f_pred"]), f_match=f["f_match"], f_top=f["f_top"],
                f_err=f["f_err"])
    n_fact = sum(1 for x in f["f_model"] if x)
    return {"format": FORMAT, "run_id": run_id, "forecast_date": str(d), "scope_key": scope_key,
            "created_at": now_iso(), "window_days": int(cfg.window_days), "min_days": int(cfg.min_days),
            "p_threshold": float(cfg.p_threshold), "hist_days": HIST_DAYS, "candidates": cands,
            "sku": [k[0] for k in keys], "fc": [k[1] for k in keys], "cols": cols,
            "counts": {"series": S, "with_factors": n_fact,
                       "factor_mismatch": sum(1 for x in f["f_match"] if x is False)}}


# ------------------------------------------------------------------ sheet (export)
def _fmt(x, nd: int = 2) -> str:
    """Vietnamese number text (decimal comma, at most nd decimals, no trailing zeros)."""
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return ""
    s = f"{float(x):.{nd}f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") if s not in ("-0", "") else "0"


def feature_label(name: str, L: dict) -> str:
    """Easy Vietnamese name of a LightGBM feature (feature_catalog, plus the SEL2 ROBUST / DAYPROF columns)."""
    fl = L["features"]
    if name in fl:
        return fl[name]
    head, _, w = name.rpartition("_")
    if head in ("med", "p25", "p75", "tmean") and w.isdigit():
        return fl[head].format(w=w)
    try:
        return feature_catalog.describe(name)["vi"]["name"]
    except Exception:  # noqa: BLE001 - an unknown name keeps its code
        return name


def ly_do(used, reason, src, raw, avg, model_used, p_v36, val_v36, p_threshold, closed, sale28, L: dict,
          hist_days: int = HIST_DAYS) -> str | None:
    """Reason in words when forecast_used = 0 (None otherwise), first rule that applies:
    1 fallback_reason NGOAI_PHAM_VI_GAN_0 -> outside the run scope; 2 KHONG_CO_SO_NAO -> no number at all;
    3 KHONG_CO_AVG_DUNG_LIGHTGBM -> the LightGBM number is used, + the reason of rules 4..8; source AVG_DEMAND ->
    avg_demand used; 4 not open the last >= CLOSED_MIN days -> not open N days;
    5 V36_two_stage in model_used, its value 0 and P(order) < p -> low order probability;
    6 0 < raw value < 0.2 -> sparse sales; 7 no order in the 28 days -> no order; 8 otherwise the chosen models gave 0."""
    if used is None or used != 0:
        return None
    t = L["ly_do"]
    if reason == REASON_OUT_ZERO:
        return t["out"]
    if reason == REASON_NO_NUMBER:
        return t["no_number"]
    if reason == REASON_AVG_MISSING_LGBM:          # AVG_DEMAND without avg_demand: the LightGBM number (0) is used
        return t["avg_lgbm"] + "; " + ly_do(used, None, LIGHTGBM, raw, avg, model_used, p_v36, val_v36, p_threshold,
                                            closed, sale28, L, hist_days)
    if src is not None and src != LIGHTGBM:
        return t["avg"].format(v=_fmt(avg) or L["empty"])
    if closed is not None and closed >= CLOSED_MIN:
        return (t["closed_long"] if closed >= CLOSED_SCAN else t["closed"]).format(n=int(closed))
    parts = str(model_used or "").replace("FALLBACK:", "").split("+")
    if (TWO_STAGE in parts and p_v36 is not None and p_v36 < p_threshold
            and val_v36 is not None and val_v36 == 0):
        return t["prob"].format(p=_fmt(p_v36), t=_fmt(p_threshold))
    r = None if raw is None else round(float(raw), 6)
    if r is not None and 0 < r < USED_THRESHOLD:
        return t["sparse"].format(v=_fmt(r), t=_fmt(USED_THRESHOLD))
    if sale28 is not None and sale28 == 0:
        return t["no_sale"].format(n=hist_days)
    return t["zero"]


def columns(cands) -> list[str]:
    cand_cols = [f"{c}_{x}" for c in cands for x in ("du_bao", "dung", "cham")]
    return (["sku_code", "ten_san_pham", "fc_code", "forecast_date", "lightgbm_forecast", "forecast_used",
             "fallback_reason", "forecast_source", "raw_value", "model_used", "ly_do", "ly_do_fallback", "so_ngay_cham"]
            + cand_cols
            + ["ban_hom_qua", "tb_7_ngay", "tb_28_ngay", "trung_vi_28_ngay", "so_ngay_mo_ban_28", "so_ngay_co_ban_28",
               "ngay_ban_gan_nhat", "mo_hinh_yeu_to", "muc_nen", "yeu_to_1", "tac_dong_1", "yeu_to_2", "tac_dong_2",
               "yeu_to_3", "tac_dong_3", "lan_chay_giai_thich"])


def _num(x, nd: int = 4):
    return None if x is None else round(float(x), nd)


def _mult(c):
    """Multiplier of a raw-score contribution (log link of tweedie / logit of the classifier)."""
    try:
        return round(math.exp(float(c)), 3)
    except (OverflowError, TypeError, ValueError):
        return None


def sheet_rows(d: date, keys: list, h1: dict, docs, run_of, names: dict, L: dict, stats: dict):
    """_sheet_rows guarded: an unexpected error ends the sheet early (counted in rows_error, logged), never fails the
    file. docs: {run id: sidecar | None} or a callable(run id) -> sidecar | None (loaded on first use)."""
    get = docs if callable(docs) else docs.get
    stats.setdefault("rows_error", 0)
    try:
        yield from _sheet_rows(d, keys, h1, get, run_of, names, L, stats)
    except Exception as e:  # noqa: BLE001 - explanation only
        stats["rows_error"] = stats.get("rows_error", 0) + 1
        stats["stopped"] = f"{type(e).__name__}: {e}"[:300]
        log.warning("sel2 giai_thich sheet stopped early", extra={"ctx": {"error": stats["stopped"]}})


def _sheet_rows(d: date, keys: list, h1: dict, get, run_of, names: dict, L: dict, stats: dict):
    """Rows of GIAI_THICH (columns(select.CANDIDATES) order) for the SKU x FC `keys` (file order) whose horizon-1 row
    (h1[(sku, fc)] = (lightgbm_forecast, forecast_used, fallback_reason, forecast_source, raw_value, model_used,
    flags, avg_demand)) has a lightgbm_forecast. docs = {run id: sidecar | None}; run_of(flags) -> (run day, run id)
    of the number shown. stats receives rows / rows_without_detail."""
    cands = list(select.CANDIDATES)
    blank = [None] * (3 + 3 * len(cands) + 15)
    n = n_missing = n_error = 0
    for k in keys:
        r = h1.get(k)
        if r is None or r[0] is None:
            continue
        lg, used, reason, src, raw, mu, fl, avg = r
        day, rid = run_of(fl)
        doc = get(rid) if rid else None
        i = doc["index"].get(k) if doc else None
        n += 1
        stats["rows"], stats["rows_without_detail"] = n, n_missing
        base = [k[0], names.get(k[0]), k[1], d, lg, used, reason, src, raw, mu]
        tag = f"{day}:{rid}" if rid else None
        if i is not None:
            try:
                yield base + _detail(k, i, doc, cands, used, reason, src, raw, avg, mu, L) + [tag]
                continue
            except Exception as e:  # noqa: BLE001 - one unreadable entry never fails the file: row without detail
                n_error += 1
                if n_error == 1:
                    log.warning("sel2 giai_thich row not built", extra={"ctx": {"key": list(k), "run_id": rid,
                                                                             "error": f"{type(e).__name__}: {e}"[:300]}})
        n_missing += 1
        stats["rows_without_detail"] = n_missing
        row = base + blank + [L["no_detail"].format(r=tag or "")]
        row[len(base)] = ly_do(used, reason, src, raw, avg, mu, None, None, 0.6, None, None, L)
        yield row
    stats["rows"], stats["rows_without_detail"], stats["rows_error"] = n, n_missing, n_error


def _detail(k, i, doc, cands, used, reason, src, raw, avg, mu, L) -> list:
    """Columns ly_do .. tac_dong_3 of a row explained by the sidecar entry i."""
    c = doc["cols"]
    dc = doc["candidates"]
    cv = []
    for cn in cands:
        j = dc.index(cn) if cn in dc else None
        cv += [None, None, None] if j is None else [c[f"val_{j}"][i], c[f"dung_{j}"][i], c[f"cham_{j}"][i]]
    j36 = dc.index(TWO_STAGE) if TWO_STAGE in dc else None
    why = ly_do(used, reason, src, raw, avg, mu, c["p_v36"][i], c[f"val_{j36}"][i] if j36 is not None else None,
                doc["p_threshold"], c["closed"][i], c["sale28"][i], L, doc["hist_days"])
    fbc = c["fb"][i] if str(mu or "").startswith("FALLBACK") else None
    fbt = None
    if fbc:
        fbt = L["fallback"][fbc].format(w=doc["window_days"], m=doc["min_days"], n=c["nday"][i], c=c["second"][i])
    fmod, part, top = c["f_model"][i], c["f_part"][i], c["f_top"][i]
    if fmod:
        mtxt = L["part"][part].format(m=fmod)
        base_v = _num(math.exp(c["f_base"][i]), 4) if part == "reg" and c["f_base"][i] is not None else None
        fac = []
        for name, val, con in top:
            fac += [f"{feature_label(name, L)} = {_fmt(val) if val is not None else L['empty']}", _mult(con)]
        fac += [None, None] * (TOP_K - len(top))
    elif (c.get("f_err") or [None] * (i + 1))[i]:
        mtxt, base_v, fac = L["no_model"].format(m=c["f_err"][i]), None, [None, None] * TOP_K
    else:
        mtxt, base_v, fac = L["not_lgbm"], None, [None, None] * TOP_K
    last = c["last_sale"][i]
    return ([why, fbt, c["nday"][i]] + cv
            + [c["yday"][i], _num(c["mean7"][i]), _num(c["mean28"][i]), _num(c["med28"][i]), c["open28"][i],
               c["sale28"][i], date.fromisoformat(last) if last else None, mtxt, base_v] + fac)


def summary_rows(info: dict, L: dict) -> list:
    """TOM_TAT lines of the sheet (how to read it), then its counts."""
    w, m = info.get("window_days") or HIST_DAYS, info.get("min_days") or select.MIN_DAYS
    out = [[k, v.format(w=w, m=m)] for k, v in L["summary"]]
    out += [["giai_thich_rows", info.get("rows")], ["giai_thich_rows_without_detail", info.get("rows_without_detail")],
            ["giai_thich_runs", ",".join(info.get("runs") or []) or None]]
    return out


def labels(lang: str = "vi") -> dict:
    return giai_thich_labels(lang)[1]


# ------------------------------------------------------------------ child process (pipeline._giai_thich_hook)
def child_main(argv: list[str]) -> int:
    """python -m app.ml.sel2.giai_thich <scope_key> <D> <run id> <detail .npz>: the day's inputs read again (rows < D),
    the sidecar built from the parent's selection arrays and written; one JSON line on stdout (ok, counts, seconds,
    peak private MB). Exit 0 when written, 1 otherwise."""
    import time
    t = time.monotonic()
    scope_key, d, run_id, det_path = argv[0], date.fromisoformat(argv[1]), argv[2], Path(argv[3])
    try:
        from . import pipeline
        s = pipeline.settings()
        det = load_detail(det_path)
        inputs = pipeline.load(scope_key, d, s)
        sk = inputs.scope_keys(d)
        with db.read() as c:
            train_ids = {r["model"]: r["train_run_id"] for r in store.day_runs(c, scope_key, d) if r["train_run_id"]}
        payload = build(d, inputs, sk, det, train_ids, s, run_id, scope_key)
        del inputs
        write(scope_key, d, run_id, payload)
        res = {"ok": True, **payload["counts"]}
    except Exception as e:  # noqa: BLE001 - reported to the parent
        log.warning("sel2 giai_thich child failed", exc_info=True, extra={"ctx": {"forecast_date": str(d)}})
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    try:
        from .pipeline import _memory_mb
        res.update(_memory_mb())
    except Exception:  # noqa: BLE001
        pass
    res["seconds"] = round(time.monotonic() - t, 1)
    print(json.dumps(res, ensure_ascii=False, default=str), flush=True)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    import sys
    raise SystemExit(child_main(sys.argv[1:]))
