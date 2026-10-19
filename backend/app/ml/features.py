"""Panel construction + feature engineering.

ONE function (`features_at`) computes the features for day index t using ONLY columns < t of the
panel arrays. Training, walk-forward backtesting and recursive inference all call it, so features are
consistent and cannot see the future (the caller never passes data beyond the forecast origin).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

LAGS = [1, 2, 3, 4, 5, 6, 7, 14, 21, 28]
ROLL_WINDOWS = [7, 14, 28, 56]
LAST_SALE_WINDOW = 180
CALENDAR = ["dow", "dom", "month", "weekofyear", "is_weekend", "days_to_month_end"]


def is_direct(cfg) -> bool:
    """DIRECT multi-horizon strategy (1.2.0); configurations without the field are RECURSIVE (all models before)."""
    return getattr(cfg, "forecast_strategy", "RECURSIVE") == "DIRECT"


@dataclass
class Panel:
    keys: list[tuple[str, str]]          # (sku_id, fc_id) per row
    dates: pd.DatetimeIndex              # one column per calendar day
    Y: np.ndarray                        # S x T demand; NaN = series not started yet OR calendar day with no data at all
    price: np.ndarray                    # S x T avg unit price, forward-filled (NaN until first known)
    disc: np.ndarray                     # S x T discount rate, forward-filled
    promo: np.ndarray                    # S x T promo share (0..1), 0 where unknown
    start_idx: np.ndarray                # first day index with an order, per series
    missing_days: np.ndarray             # bool T: calendar days with no orders at all in the scope
    sku_codes: dict[str, int] = field(default_factory=dict)
    fc_codes: dict[str, int] = field(default_factory=dict)

    @property
    def n_series(self) -> int:
        return len(self.keys)

    @property
    def T(self) -> int:
        return len(self.dates)

    def truncate(self, t_end: int) -> "Panel":
        """Copy of the panel restricted to day indices < t_end (used by backtesting)."""
        return Panel(self.keys, self.dates[:t_end], self.Y[:, :t_end].copy(), self.price[:, :t_end].copy(),
                     self.disc[:, :t_end].copy(), self.promo[:, :t_end].copy(),
                     self.start_idx.copy(), self.missing_days[:t_end].copy(), self.sku_codes, self.fc_codes)


def _ffill_rows(a: np.ndarray) -> np.ndarray:
    mask = np.isnan(a)
    idx = np.where(~mask, np.arange(a.shape[1]), 0)
    np.maximum.accumulate(idx, axis=1, out=idx)
    out = a[np.arange(a.shape[0])[:, None], idx]
    out[mask & (np.cumsum(~mask, axis=1) == 0)] = np.nan
    return out


def build_panel(demand: pd.DataFrame, end_date: str | None = None, max_days: int | None = None,
                start_date: str | None = None) -> Panel:
    """start_date/end_date fix the calendar range exactly (used to rebuild the panel of an existing training run);
    without them the range is the data's first..last day, capped to the last max_days days."""
    if demand.empty:
        raise ValueError("empty demand")
    d = demand.copy()
    d["order_date"] = pd.to_datetime(d["order_date"])
    end = pd.Timestamp(end_date) if end_date else d["order_date"].max()
    start = pd.Timestamp(start_date) if start_date else d["order_date"].min()
    if max_days and (end - start).days + 1 > max_days:
        start = end - pd.Timedelta(days=max_days - 1)
    d = d[(d["order_date"] >= start) & (d["order_date"] <= end)]
    dates = pd.date_range(start, end, freq="D")
    keys_df = d[["sku_id", "fc_id"]].drop_duplicates().sort_values(["sku_id", "fc_id"]).reset_index(drop=True)
    keys = list(map(tuple, keys_df.values.tolist()))
    kidx = {k: i for i, k in enumerate(keys)}
    S, T = len(keys), len(dates)
    si = np.fromiter((kidx[(a, b)] for a, b in zip(d["sku_id"], d["fc_id"])), dtype=np.int64, count=len(d))
    ti = ((d["order_date"] - start).dt.days).to_numpy()
    Y = np.zeros((S, T))
    Y[si, ti] = d["qty"].to_numpy(dtype=float)
    present = np.zeros((S, T), dtype=bool)
    present[si, ti] = True
    price = np.full((S, T), np.nan)
    disc = np.full((S, T), np.nan)
    promo = np.zeros((S, T))
    if "avg_unit_price" in d:
        price[si, ti] = d["avg_unit_price"].to_numpy(dtype=float)
    if "avg_discount_rate" in d:
        disc[si, ti] = d["avg_discount_rate"].to_numpy(dtype=float)
    if "promo_share" in d:
        promo[si, ti] = np.nan_to_num(d["promo_share"].to_numpy(dtype=float))
    first = np.where(present.any(axis=1), present.argmax(axis=1), T)
    missing_days = ~present.any(axis=0)
    # not started yet -> NaN ; whole-calendar gaps -> NaN (unknown, not "zero demand")
    Y[np.arange(T)[None, :] < first[:, None]] = np.nan
    Y[:, missing_days] = np.nan
    skus = sorted({k[0] for k in keys})
    fcs = sorted({k[1] for k in keys})
    return Panel(keys, dates, Y, _ffill_rows(price), _ffill_rows(disc), promo, first, missing_days,
                 {s: i for i, s in enumerate(skus)}, {f: i for i, f in enumerate(fcs)})


def discount_on(cfg) -> bool:
    """disc_last switch. Configurations saved before 1.1.5 have no feature_discount: it followed feature_price."""
    v = getattr(cfg, "feature_discount", None)
    return cfg.feature_price if v is None else bool(v)


WEEKDAY = ("dow", "is_weekend")


def weekday_on(cfg) -> bool:
    """1.2.8 day-of-week switch (dow, is_weekend of the TARGET day). Configurations saved before 1.2.8 have no
    feature_weekday: the pair follows the calendar group, exactly as before."""
    v = getattr(cfg, "feature_weekday", None)
    return bool(cfg.feature_calendar) if v is None else bool(v)


def calendar_names(cfg) -> list[str]:
    """Calendar columns of the target day in model order: the weekday pair follows its own switch, the other calendar
    columns the calendar group. Both on = the order of every model trained before 1.2.8."""
    wk = weekday_on(cfg)
    return [n for n in CALENDAR if (wk if n in WEEKDAY else cfg.feature_calendar)]


def feature_names(cfg) -> list[str]:
    names = ["sku_code", "fc_code", "series_age"]
    if cfg.feature_lags:
        names += [f"lag_{k}" for k in LAGS]
    if cfg.feature_rolling:
        names += [f"roll_mean_{w}" for w in ROLL_WINDOWS] + ["roll_std_7", "roll_std_28", "zero_share_28",
                                                             "days_since_last_sale", "roll_max_28"]
    names += calendar_names(cfg)
    if cfg.feature_price:
        names += ["price_last", "price_rel_28"]
    if discount_on(cfg):
        names += ["disc_last"]
    if cfg.feature_promotion:
        names += ["promo_last", "promo_mean_7"]
    if is_direct(cfg):
        # features at the ORIGIN (calendar removed), then the calendar of the TARGET day and the horizon (1 = first
        # forecast day); same column order as the experiment harness (L7_direct)
        names = [n for n in names if n not in CALENDAR] + calendar_names(cfg) + ["horizon"]
    return names


def _nanmean(a):
    with np.errstate(all="ignore"):
        cnt = np.sum(~np.isnan(a), axis=1)
        s = np.nansum(a, axis=1)
        return np.where(cnt > 0, s / np.maximum(cnt, 1), np.nan)


def _nanstd(a):
    with np.errstate(all="ignore"):
        m = _nanmean(a)
        cnt = np.sum(~np.isnan(a), axis=1)
        v = np.nansum((a - m[:, None]) ** 2, axis=1) / np.maximum(cnt, 1)
        return np.where(cnt > 1, np.sqrt(v), np.nan)


def features_at(p: Panel, Y: np.ndarray, price: np.ndarray, disc: np.ndarray, promo: np.ndarray,
                dates: pd.DatetimeIndex, t: int, cfg, sku_code: np.ndarray, fc_code: np.ndarray) -> np.ndarray:
    """Features for target day index t, computed from columns [0, t) only."""
    S = Y.shape[0]
    cols = [sku_code, fc_code, (t - p.start_idx).astype(float)]
    hist = Y[:, :t]
    if cfg.feature_lags:
        for k in LAGS:
            cols.append(hist[:, t - k] if t - k >= 0 else np.full(S, np.nan))
    if cfg.feature_rolling:
        for w in ROLL_WINDOWS:
            cols.append(_nanmean(hist[:, max(0, t - w):t]) if t > 0 else np.full(S, np.nan))
        cols.append(_nanstd(hist[:, max(0, t - 7):t]) if t > 1 else np.full(S, np.nan))
        win28 = hist[:, max(0, t - 28):t]
        cols.append(_nanstd(win28) if t > 1 else np.full(S, np.nan))
        with np.errstate(all="ignore"):
            nn = np.sum(~np.isnan(win28), axis=1)
            cols.append(np.where(nn > 0, np.sum(win28 == 0, axis=1) / np.maximum(nn, 1), np.nan))
        w = hist[:, max(0, t - LAST_SALE_WINDOW):t]
        sold = np.nan_to_num(w) > 0.5
        any_sold = sold.any(axis=1)
        last = w.shape[1] - 1 - np.argmax(sold[:, ::-1], axis=1)
        cols.append(np.where(any_sold, w.shape[1] - last, float(LAST_SALE_WINDOW + 1)))
        if win28.shape[1]:
            filled = np.where(np.isnan(win28), -np.inf, win28).max(axis=1)
            cols.append(np.where(np.isinf(filled), np.nan, filled))
        else:
            cols.append(np.full(S, np.nan))
    cal = calendar_names(cfg)
    if cal:
        vals = dict(zip(CALENDAR, calendar_row(dates[t])))
        for n in cal:
            cols.append(np.full(S, vals[n]))
    if cfg.feature_price:
        pl = price[:, t - 1] if t > 0 else np.full(S, np.nan)
        with np.errstate(all="ignore"):
            pm = _nanmean(price[:, max(0, t - 28):t]) if t > 0 else np.full(S, np.nan)
            cols += [pl, np.where(pm > 0, pl / pm, np.nan)]
    if discount_on(cfg):
        cols.append(disc[:, t - 1] if t > 0 else np.full(S, np.nan))
    if cfg.feature_promotion:
        cols.append(promo[:, t - 1] if t > 0 else np.zeros(S))
        cols.append(promo[:, max(0, t - 7):t].mean(axis=1) if t > 0 else np.zeros(S))
    with np.errstate(all="ignore"):
        return np.column_stack(cols).astype(np.float32)


class _NoCalendar:
    """The same configuration with the calendar group off: DIRECT features at the origin (calendar is per target day)."""
    feature_calendar = False
    feature_weekday = False

    def __init__(self, cfg):
        self._cfg = cfg

    def __getattr__(self, name):
        return getattr(self._cfg, name)


def calendar_row(d) -> list[float]:
    """Calendar features of one day, identical to the calendar block of features_at."""
    return [float(d.dayofweek), float(d.day), float(d.month), float(d.isocalendar()[1]),
            1.0 if d.dayofweek >= 5 else 0.0, float(d.days_in_month - d.day)]


def direct_extra(cfg, target_day, h: int) -> list[float]:
    """Columns appended to the origin features of a DIRECT row: target-day calendar (if on) + horizon h (1-based)."""
    cal = calendar_names(cfg)
    return [v for n, v in zip(CALENDAR, calendar_row(target_day)) if n in cal] + [float(h)]


def origin_features(p: Panel, Y, price, disc, promo, dates, t0: int, cfg, sc, fcc) -> np.ndarray:
    """DIRECT: features of every series at origin t0, from columns [0, t0) only (calendar left out)."""
    return features_at(p, Y, price, disc, promo, dates, t0, _NoCalendar(cfg), sc, fcc)


def static_codes(p: Panel, sku_codes: dict | None = None, fc_codes: dict | None = None):
    sc = sku_codes or p.sku_codes
    fcc = fc_codes or p.fc_codes
    return (np.array([sc.get(k[0], -1) for k in p.keys], dtype=float),
            np.array([fcc.get(k[1], -1) for k in p.keys], dtype=float))


def training_matrix(p: Panel, cfg, min_t: int = 7, max_rows: int = 4_000_000):
    """Stack features/targets for every (series, day) with a known target, oldest days dropped if too big."""
    sc, fcc = static_codes(p)
    S, T = p.Y.shape
    t_from = max(min_t, 1)
    max_days = max(1, max_rows // max(S, 1))
    t_from = max(t_from, T - max_days)
    Xs, ys = [], []
    for t in range(t_from, T):
        target = p.Y[:, t]
        ok = ~np.isnan(target) & (t > p.start_idx)
        if not ok.any():
            continue
        X = features_at(p, p.Y, p.price, p.disc, p.promo, p.dates, t, cfg, sc, fcc)
        Xs.append(X[ok])
        ys.append(target[ok])
    if not Xs:
        return np.empty((0, len(feature_names(cfg))), dtype=np.float32), np.empty(0)
    return np.vstack(Xs), np.concatenate(ys)


def direct_training_matrix(p: Panel, cfg, horizon: int):
    """DIRECT training rows: for origins t0 = T - j * step (j = 1..direct_origins, t0 >= 7) and h = 1..horizon with
    t0 + h - 1 < T: features at t0 (data < t0), target-day calendar, h -> target Y[t0 + h - 1]. A series counts only if
    it started before t0 and its target day is known (NaN = not started / no data at all, never 0)."""
    sc, fcc = static_codes(p)
    S, T = p.Y.shape
    Xs, ys = [], []
    for j in range(1, cfg.direct_origins + 1):
        t0 = T - j * cfg.direct_origin_step_days
        if t0 < 7:
            break
        Xb = origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, t0, cfg, sc, fcc)
        for h in range(1, horizon + 1):
            td = t0 + h - 1
            if td >= T:
                break
            target = p.Y[:, td]
            ok = ~np.isnan(target) & (t0 > p.start_idx)
            if ok.any():
                extra = np.tile(np.array(direct_extra(cfg, p.dates[td], h), dtype=np.float32), (int(ok.sum()), 1))
                Xs.append(np.hstack([Xb[ok], extra]))
                ys.append(target[ok])
    if not Xs:
        return np.empty((0, len(feature_names(cfg))), dtype=np.float32), np.empty(0)
    return np.vstack(Xs), np.concatenate(ys)
