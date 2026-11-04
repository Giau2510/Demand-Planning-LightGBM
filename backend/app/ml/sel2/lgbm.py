"""LightGBM candidates of SEL2 (backtest reports/cai-tien-20261031/code/ct_run.py names_of / plan_of / origin_block /
BlockSeq / SeqDataset / train_streamed / forecast / run_batch, on the application snapshot af835b8 through
reports/backtest-lgbm7-20261029/code: backtest_runner_original.py Data / cand_config / panel_before, prereg_runner.py
WEIGHT_HMAX / WEIGHT_HIGH). Same rows, same column order, same float32 values, same LightGBM parameters and bin sample:
the same model text and the same forecasts.

  MOC            G2 on the scope: the DIRECT model of the application without sku_code, 12 weekly origins
  V33_L112       MOC + ROBUST (origin columns) + DAYPROF (target-day columns), 16 origins (112 days of origins)
  V36_two_stage  V33_L112 rows; a binary classifier P(demand > 0) on every row and a tweedie quantity model on the rows
                 with demand; value = quantity where P >= 0.6, else 0 (scoring.py of the backtest)

One model per weekly origin c: trained on the frame rows < c of the keys in scope(c) (panel of the last max_train_days
days before c). A forecast day D (horizons 1..7, targets D .. D+6) uses the rows < D of the keys in scope(D) and the
sku / fc category codes of the training panel (ct_run.py:578). The configuration is pinned (PINNED_SETTINGS = the model
settings of the backtest's DB copy g1, + the 1.3.1 way to drop sku_code and weight horizons <= 7 by 3.0) and resolved on
the data available at the origin exactly like cand_config; the application's live settings are never read.

Differences of the application code since af835b8 (495384b) neutralised here:
  * features.feature_names / features_at drop sku_code natively with feature_sku_code=False (the backtest deleted the
    column from the origin block): same remaining columns, same order, same values;
  * model.lgb_params(cfg, names=...) adds feature_contri from a feature table: called without names (feature_table
    None), i.e. the af835b8 parameters;
  * the horizon weight is read from horizon_weight_short / horizon_weight_cutoff (3.0 / 7 = WEIGHT_HIGH / WEIGHT_HMAX);
  * features.static_codes(p, sku_codes, fc_codes) receives the training codes instead of overwriting the panel's.
Pure computation: the frame is given by the caller (load_frame builds it from an open connection like the backtest)."""
from __future__ import annotations

import ctypes
import hashlib
import json
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
import pandas as pd

from ... import settings_service as ss
from ...data import open_hours_override
from ...data.demand import load_demand
from ...jobs import resources
from .. import feature_registry as registry
from .. import model
from ..features import Panel, build_panel, direct_extra, feature_names, origin_features, static_codes
from .extras import DAYPROF_NAMES, ROBUST_NAMES, dayprof_columns, dayprof_profile, robust

H = 7

# model settings of the backtest (g1 copy, configuration fingerprint 8468ebe66d1706f7 at every origin), before the
# per-origin resolution; + 1.3.1 fields: sku_code left out, weight 3.0 for horizon <= 7
PINNED_SETTINGS = {
    "feature_lags": True, "feature_rolling": True, "feature_calendar": True, "feature_price": True,
    "feature_promotion": True, "feature_discount": None, "feature_weekday": None, "feature_open_hours": None,
    "weekday_encoding": None, "feature_customer": True, "feature_min_coverage": 0.5, "min_total_history_days": 56,
    "min_series_history_days": 28, "intermittent_zero_share": 0.8, "inactive_days": 60, "fallback_window_days": 28,
    "backtest_folds": 12, "backtest_horizon_days": 30, "backtest_step_days": 30, "num_boost_round": 300,
    "learning_rate": 0.05, "num_leaves": 31, "objective": "tweedie", "max_train_days": 730, "num_threads": 0,
    "forecast_strategy": "DIRECT", "direct_origins": 12, "direct_origin_step_days": 7,
    "feature_sku_code": False, "horizon_weight_short": 3.0, "horizon_weight_cutoff": 7, "feature_table": None,
}

CANDIDATE_SPECS = {
    "MOC": {"robust": False, "dayprof": False, "n_origins": 12, "model": "lgbm"},
    "V33_L112": {"robust": True, "dayprof": True, "n_origins": 16, "model": "lgbm"},
    "V36_two_stage": {"robust": True, "dayprof": True, "n_origins": 16, "model": "two_stage", "p_threshold": 0.6},
}


def pinned_settings() -> ss.ModelSettings:
    return ss.ModelSettings(**PINNED_SETTINGS)


# ------------------------------------------------------------------ frame
def load_frame(conn, scope_key: str, start: str, end: str) -> tuple[pd.DataFrame, list]:
    """(demand frame of [start, end], open hours override problems), as the backtest's Data: load_demand, the approved
    open hours override filled, "od" = order_date as Timestamp, stable sort by (od, sku_id, fc_id). Read-only."""
    frame = load_demand(scope_key, conn, start=start, end=end)
    ovr = open_hours_override.resolve(conn, scope_key, start, end)
    problems = []
    if ovr and ovr.get("applied"):
        frame, problems = open_hours_override.fill(frame, ovr["applied"])
    frame["od"] = pd.to_datetime(frame["order_date"])
    frame = frame.sort_values(["od", "sku_id", "fc_id"], kind="stable").reset_index(drop=True)
    return frame, problems


def rows_before(frame: pd.DataFrame, d: date) -> pd.DataFrame:
    """The rows with order day < d of a frame sorted by od (load_frame)."""
    if not frame["od"].is_monotonic_increasing:
        raise ValueError("frame not sorted by od")
    return frame.iloc[:int(frame["od"].searchsorted(pd.Timestamp(d), side="left"))]


def in_scope(frame: pd.DataFrame, scope_keys) -> pd.DataFrame:
    """The rows of the keys (sku_id, fc_id) in scope_keys, order kept."""
    ks = set(scope_keys)
    m = np.fromiter((k in ks for k in zip(frame["sku_id"], frame["fc_id"])), dtype=bool, count=len(frame))
    return frame[m]


def panel_of(frame_lt: pd.DataFrame, d: date, cfg) -> Panel:
    p = build_panel(frame_lt.drop(columns=[c for c in ("od", "kid") if c in frame_lt.columns]),
                    end_date=str(d - timedelta(days=1)), max_days=cfg.max_train_days)
    if p.dates[-1].date() != d - timedelta(days=1):
        raise ValueError(f"panel ends {p.dates[-1].date()}, expected {d - timedelta(days=1)}")
    return p


# fields of ModelSettings at af835b8 (the backtest's application snapshot) and the configuration fingerprint the
# backtest registered at every origin (backtest_runner_original.config_summary: sha256 of the sorted JSON dump, 16 hex)
AF835B8_FIELDS = (
    "backtest_folds", "backtest_horizon_days", "backtest_step_days", "direct_origin_step_days", "direct_origins",
    "fallback_window_days", "feature_calendar", "feature_customer", "feature_discount", "feature_lags",
    "feature_min_coverage", "feature_open_hours", "feature_price", "feature_promotion", "feature_rolling",
    "feature_weekday", "forecast_strategy", "inactive_days", "intermittent_zero_share", "learning_rate",
    "max_train_days", "min_series_history_days", "min_total_history_days", "num_boost_round", "num_leaves",
    "num_threads", "objective", "weekday_encoding")
V0_FINGERPRINT = "8468ebe66d1706f7"
FLAG_CONFIG_DRIFT = "CONFIG_DRIFT"


def config_fingerprint(cfg) -> str:
    """Fingerprint of the af835b8-equivalent dump of a resolved configuration (the fields added since are left out)."""
    dump = {k: v for k, v in cfg.model_dump().items() if k in AF835B8_FIELDS}
    return hashlib.sha256(json.dumps(dump, sort_keys=True, default=str).encode()).hexdigest()[:16]


def config_at(frame_c: pd.DataFrame, spec: dict, with_fingerprint: bool = False):
    """The application's resolution (registry.coverage_of_frame + registry.resolve) on the rows before the origin, the
    open hours and ISO weekday switches on, then the candidate's number of origins (cand_config + config_at). With
    with_fingerprint: + config_fingerprint() of the resolved configuration BEFORE the number of origins is set (as the
    backtest computed it; V0_FINGERPRINT expected)."""
    cov = registry.coverage_of_frame(frame_c)
    cfg, decisions = registry.resolve(pinned_settings(), cov)
    cfg = cfg.model_copy(update={"feature_open_hours": True, "weekday_encoding": "ISO"})
    fp = config_fingerprint(cfg)
    if spec["n_origins"] != cfg.direct_origins:
        cfg = cfg.model_copy(update={"direct_origins": int(spec["n_origins"])})
    dec = {g: {"used": d["used"], "reason": d["reason"], "coverage": d["coverage"]} for g, d in decisions.items()}
    return (cfg, dec, fp) if with_fingerprint else (cfg, dec)


# ------------------------------------------------------------------ columns
def names_of(cfg, spec: dict) -> tuple[list[str], int, int, int]:
    """(names, n origin base, n origin extra, n target extra): base origin columns, ROBUST, DAYPROF, calendar + horizon."""
    base = feature_names(cfg)
    if "sku_code" in base:
        raise ValueError("sku_code must be left out (feature_sku_code=False)")
    ncal = len(direct_extra(cfg, pd.Timestamp("2026-06-01"), 1))
    o = base[:-ncal]
    eo = list(ROBUST_NAMES) if spec.get("robust") else []
    et = list(DAYPROF_NAMES) if spec.get("dayprof") else []
    return o + eo + et + base[-ncal:], len(o), len(eo), len(et)


class _Extra:
    """ROBUST / DAYPROF columns of one panel as float32 (ct_feat.Features without capping); the day profile is computed
    once per origin."""

    def __init__(self, spec: dict):
        self.spec = spec
        self._prof = (None, None)

    def origin(self, p: Panel, t0: int) -> np.ndarray:
        if not self.spec.get("robust"):
            return np.zeros((p.Y.shape[0], 0), dtype=np.float32)
        return robust(p.Y, t0).astype(np.float32)

    def target(self, p: Panel, t0: int, td) -> np.ndarray:
        if not self.spec.get("dayprof"):
            return np.zeros((p.Y.shape[0], 0), dtype=np.float32)
        if self._prof[0] != t0:
            self._prof = (t0, dayprof_profile(p.Y, p.dates, t0))
        return dayprof_columns(self._prof[1], td).astype(np.float32)


def origin_block(p: Panel, cfg, t0: int, no: int, sku_codes=None, fc_codes=None) -> np.ndarray:
    sc, fcc = static_codes(p, sku_codes, fc_codes)
    Xb = origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, t0, cfg, sc, fcc)
    if Xb.shape[1] != no:
        raise ValueError(f"origin columns: {Xb.shape[1]} built, {no} names")
    return Xb


def plan_of(p: Panel, cfg, horizon: int) -> list:
    """DIRECT origins t0 = T - j x step (newest first, t0 >= 7), horizons 1..horizon ascending; rows = series with a known
    label on the target column and started before t0."""
    S, T = p.Y.shape
    plan = []
    for j in range(1, cfg.direct_origins + 1):
        t0 = T - j * cfg.direct_origin_step_days
        if t0 < 7:
            break
        plan.append((t0, [(h, t0 + h - 1, ok) for h in range(1, horizon + 1) if t0 + h - 1 < T
                          for ok in [~np.isnan(p.Y[:, t0 + h - 1]) & (t0 > p.start_idx)] if ok.any()]))
    return plan


# ------------------------------------------------------------------ streamed training rows
class BlockSeq(lgb.Sequence):
    """The training rows produced block by block for lgb.Dataset (the float32 matrix is never held): a block = (origin
    t0, horizon h), its rows = the series `ok` (optionally only those with label > 0). Origin columns are computed once
    per t0 and target columns once per (t0, h), on demand."""

    def __init__(self, p: Panel, cfg, fx: _Extra, plan: list, names: list[str], no: int, positive_only: bool = False,
                 batch_size: int = 65536):
        self.p, self.cfg, self.fx, self.names, self.no = p, cfg, fx, names, no
        self.blocks = []
        start = 0
        for t0, hs in plan:
            for h, td, ok in hs:
                sel = ok & (p.Y[:, td] > 0) if positive_only else ok
                idx = np.nonzero(sel)[0]
                if len(idx):
                    self.blocks.append((start, t0, h, td, idx))
                    start += len(idx)
        self.n = start
        self.starts = np.array([b[0] for b in self.blocks], dtype=np.int64)
        self.batch_size = batch_size
        self._o = (None, None)
        self._t = (None, None)

    def __len__(self) -> int:
        return self.n

    def labels(self) -> np.ndarray:
        return np.concatenate([self.p.Y[idx, td] for _, _, _, td, idx in self.blocks])

    def horizons(self) -> np.ndarray:
        return np.concatenate([np.full(len(idx), h, dtype=np.float32) for _, _, h, _, idx in self.blocks])

    def _block_rows(self, b: int, lo: int, hi: int) -> np.ndarray:
        _, t0, h, td, idx = self.blocks[b]
        if self._o[0] != t0:
            Xb = origin_block(self.p, self.cfg, t0, self.no)
            self._o = (t0, np.hstack([Xb, self.fx.origin(self.p, t0)]).astype(np.float32))
        if self._t[0] != (t0, h):
            et = self.fx.target(self.p, t0, self.p.dates[td])
            cal = np.tile(np.array(direct_extra(self.cfg, self.p.dates[td], h), dtype=np.float32), (et.shape[0], 1))
            self._t = ((t0, h), np.hstack([et, cal]).astype(np.float32))
        s = idx[lo:hi]
        # float32 values of the matrix, widened exactly to float64 (LightGBM's Sequence input type)
        return np.hstack([self._o[1][s], self._t[1][s]]).astype(np.float64)

    def __getitem__(self, i):
        if isinstance(i, slice):
            a, b, _ = i.indices(self.n)
            parts = []
            while a < b:
                k = int(np.searchsorted(self.starts, a, side="right")) - 1
                st = self.blocks[k][0]
                hi = min(b, st + len(self.blocks[k][4]))
                parts.append(self._block_rows(k, a - st, hi - st))
                a = hi
            return np.vstack(parts) if parts else np.empty((0, len(self.names)), dtype=np.float32)
        i = int(i)
        k = int(np.searchsorted(self.starts, i, side="right")) - 1
        return self._block_rows(k, i - self.blocks[k][0], i - self.blocks[k][0] + 1)[0]


class SeqDataset(lgb.Dataset):
    """lgb.Dataset of a Sequence whose bin-construction sample is drawn with the FULL training parameters, as the
    numpy-matrix path does in C++ (seed 7 also sets data_random_seed; Dataset.get_params drops `seed`, so the library's
    Sequence path would sample other rows). Same body as lightgbm.basic.Dataset._create_sample_indices."""

    def _create_sample_indices(self, *, total_nrow: int) -> np.ndarray:
        from lightgbm import basic as lb
        param_str = lb._param_dict_to_str(self.params)
        sample_cnt = lb._get_sample_count(total_nrow, param_str)
        indices = np.empty(sample_cnt, dtype=np.int32)
        ptr_data, _, _ = lb._c_int_array(indices)
        actual = ctypes.c_int32(0)
        lb._safe_call(lb._LIB.LGBM_SampleIndices(ctypes.c_int32(total_nrow), lb._c_str(param_str), ptr_data,
                                                 ctypes.byref(actual)))
        if sample_cnt != actual.value:
            raise RuntimeError(f"LightGBM sample: {actual.value} indices, {sample_cnt} expected")
        return indices


# ------------------------------------------------------------------ training / forecast
def train(frame: pd.DataFrame, origin: date, scope_keys, spec: dict, cancel=None) -> tuple[dict, dict]:
    """Models of one origin: {"reg"} (lgbm) or {"clf", "reg"} (two_stage), and the training info (resolved cfg, names,
    rows, series, the panel's sku / fc codes and keys). Only the frame rows < origin are read."""
    fr = rows_before(frame, origin)
    if fr.empty:
        raise ValueError(f"no demand row before {origin}")
    cfg, decisions, fp = config_at(fr, spec, with_fingerprint=True)
    if int(fr["open_hours"].isna().sum()):
        raise ValueError(f"OPEN_HOURS_INVALID before {origin}")
    p = panel_of(in_scope(fr, scope_keys), origin, cfg)
    del fr
    names, no, _, _ = names_of(cfg, spec)
    plan = plan_of(p, cfg, model.direct_max_horizon(cfg))
    fx = _Extra(spec)
    params = model.lgb_params(cfg)      # no names: no feature_contri (feature_table None) = the af835b8 parameters
    if spec["model"] not in ("lgbm", "two_stage"):
        raise ValueError(spec["model"])

    def fit(prm, positive_only: bool, binary: bool):
        if cancel and cancel():
            raise model.Cancelled()
        seq = BlockSeq(p, cfg, fx, plan, names, no, positive_only)
        y = seq.labels()
        w = np.where(seq.horizons() <= cfg.horizon_weight_cutoff, cfg.horizon_weight_short, 1.0)
        ds = SeqDataset([seq], (y > 0).astype(np.float64) if binary else y, weight=w, feature_name=names,
                        categorical_feature=["fc_code"], free_raw_data=True)
        b = lgb.train(prm, ds, num_boost_round=cfg.num_boost_round)
        b.free_dataset()                  # the binned data is not needed to predict; freed before the next model
        del ds
        resources.release_memory()
        return b, seq.n, float(y.sum())

    t0s = [t0 for t0, _ in plan]
    # a resolution that differs from the backtest's is recorded (CONFIG_DRIFT), never a failure
    info = {"n_series": p.n_series, "n_features": len(names), "names": names, "cfg": cfg, "decisions": decisions,
            "config_fingerprint": fp, "flags": [] if fp == V0_FINGERPRINT else [FLAG_CONFIG_DRIFT],
            "sku_codes": dict(p.sku_codes), "fc_codes": dict(p.fc_codes), "panel_keys": list(p.keys),
            "panel_last_day": str(p.dates[-1].date()), "n_origins": len(t0s),
            "label_start": str(p.dates[min(t0s)].date()) if t0s else None, "label_end": str(p.dates[-1].date())}
    models = {}
    if spec["model"] == "lgbm":
        models["reg"], info["n_rows"], info["label_sum"] = fit(params, False, False)
    else:
        pc = {k: v for k, v in params.items() if k != "tweedie_variance_power"}
        pc["objective"] = "binary"
        models["clf"], info["n_rows"], info["label_sum"] = fit(pc, False, True)
        models["reg"], info["n_rows_positive"], _ = fit(params, True, False)
    for m in models.values():
        if m.feature_name() != names:
            raise RuntimeError("model feature names differ from the training columns")
    return models, info


def forecast(frame: pd.DataFrame, D: date, scope_keys, models: dict, spec: dict, trained: dict) -> dict:
    """Forecast day D, targets D .. D+6, of the keys in scope(D): {"keys", "dates", "value" float64 S x 7} (+ "prob",
    "qty" for two_stage). trained = the info of train() (its cfg, names and the training panel's sku / fc codes).
    Only the frame rows < D are read; values clipped at 0, not rounded."""
    cfg = trained["cfg"]
    if not isinstance(cfg, ss.ModelSettings):
        cfg = ss.ModelSettings.model_validate(cfg)
    names, no, _, _ = names_of(cfg, spec)
    if names != list(trained["names"]):
        raise ValueError("forecast columns differ from the trained model's")
    future = pd.date_range(pd.Timestamp(D), periods=H, freq="D")
    fr = in_scope(rows_before(frame, D), scope_keys)
    if fr.empty:
        out = {"keys": [], "dates": future, "value": np.zeros((0, H))}
        if "clf" in models:
            out["prob"], out["qty"] = np.zeros((0, H)), np.zeros((0, H))
        return out
    p = panel_of(fr, D, cfg)
    del fr
    S, T = p.Y.shape
    fx = _Extra(spec)
    Xb = origin_block(p, cfg, T, no, trained["sku_codes"], trained["fc_codes"])
    Eo = fx.origin(p, T)
    out = {"keys": list(p.keys), "dates": future, "value": np.zeros((S, H))}
    if "clf" in models:
        out["prob"], out["qty"] = np.zeros((S, H)), np.zeros((S, H))
    for h in range(H):
        extra = np.tile(np.array(direct_extra(cfg, future[h], h + 1), dtype=np.float32), (S, 1))
        X = np.hstack([Xb, Eo, fx.target(p, T, future[h]), extra])
        q = np.clip(models["reg"].predict(X), 0, None)
        if "clf" in models:
            pb = models["clf"].predict(X)
            out["prob"][:, h], out["qty"][:, h] = pb, q
            q = np.where(pb >= spec.get("p_threshold", 0.5), q, 0.0)
        out["value"][:, h] = q
    return out
