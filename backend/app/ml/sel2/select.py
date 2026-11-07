"""Per-series model choice SEL2 of a forecast day D (backtest reports/cai-tien-20261031/code/ct_select.py, run as FINAL2
by ct_step5.py, with the cells of scoring.py). Pure function on frames; reading the data is the caller's job.

For every series (sku x fc) in scope of D:
  * cells of each candidate = its stored forecasts (horizons 1..7) whose target day is in D-28 .. D-1 (made before D,
    actual known at D), the series in scope of the forecast day (history_scope), target day open (open hours > 0),
    forecast day >= history_start when given; actual = demand of the target day, no row = 0 (no order);
  * published = daily_refresh.published_qty(value, 0.2), category = accuracy_report._category_index with the series'
    group A / B / C (missing -> B), dev = published - actual;
  * per candidate: n_cells, n_dung (category DUNG), shortage = sum(-dev, dev < 0); rate = n_dung / n_cells (-1 without
    cells); a candidate without a forecast of D scores -2; order: rate desc, shortage asc, candidate index asc;
  * nday = MIN over the candidates of the target days with >= 1 cell; ok = nday >= 14;
  * value of every horizon = mean of the 2 best when ok and the second has a forecast of D ("<first>+<second>"),
    otherwise the value of the best LightGBM configuration ("FALLBACK:V33_L112").
The history is scored one candidate at a time (memory: at production size the 28-day history is ~17.6 M rows): either
a frame (split per candidate) or a reader callable(candidate) -> (keys, arrays) with integer key ids (sel2.store)."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..accuracy_report import _category_index, _group_index
from ..daily_refresh import published_qty

CANDIDATES = ("MOC", "V33_L112", "V36_two_stage@0.6", "TSB", "DOW4", "AVG7")
BEST = "V33_L112"
TWO_STAGE_P = 0.6
WINDOW_DAYS, MIN_DAYS, HORIZONS = 28, 14, 7
THRESHOLD = 0.2
K = ["sku_code", "fc_code"]
OUT_COLS = K + ["horizon", "target_date", "raw_value", "published", "model_used", "ok"]


def two_stage_value(prob, qty, p: float = TWO_STAGE_P) -> np.ndarray:
    """Candidate "<two-stage>@p": qty where prob >= p, else 0. A missing prob is below p (0), the backtest's rule
    (ct_select.py / scoring.py np.where(prob >= p, qty, 0), as lgbm.forecast); a missing qty with prob >= p stays
    missing (NaN)."""
    prob = np.asarray(prob, dtype=float)
    qty = np.asarray(qty, dtype=float)
    with np.errstate(invalid="ignore"):
        return np.where(prob >= p, qty, 0.0)


def _days(col, day: date) -> np.ndarray:
    """Day offsets (int64) of a date column relative to day."""
    d = pd.to_datetime(pd.Series(col)).to_numpy().astype("datetime64[D]")
    return (d - np.datetime64(day, "D")).astype(np.int64)


def _key_index(idx: pd.MultiIndex, df: pd.DataFrame) -> np.ndarray:
    return idx.get_indexer(pd.MultiIndex.from_arrays([df["sku_code"].to_numpy(), df["fc_code"].to_numpy()]))


def _groups_of(groups, idx: pd.MultiIndex) -> np.ndarray:
    if isinstance(groups, pd.Series):
        return groups.reindex(idx).to_numpy(dtype=object)
    return np.array([groups.get(k) for k in idx], dtype=object)


def _history_parts(day, idx, candidates, history, history_start, W=WINDOW_DAYS):
    """Per candidate index c: (k scope index, f forecast-day offset, t target index 0..27, horizon, value) of its
    history rows in the window (horizons 1..HORIZONS, forecast day >= history_start), series in scope_keys only."""
    hs = None if history_start is None else int((np.datetime64(history_start, "D")
                                                  - np.datetime64(day, "D")).astype(np.int64))
    if callable(history):
        for c, name in enumerate(candidates):
            keys, a = history(name)
            f = np.asarray(a["f"], dtype=np.int64)
            hz = np.asarray(a["horizon"], dtype=np.int64)
            t = f + hz - 1 + W
            m = (t >= 0) & (t < W) & (hz >= 1) & (hz <= HORIZONS)
            if hs is not None:
                m &= f >= hs
            kmap = _key_index(idx, keys) if len(keys) else np.zeros(0, dtype=np.int64)
            k = kmap[np.asarray(a["kid"], dtype=np.int64)[m]] if m.any() else np.zeros(0, dtype=np.int64)
            val = np.asarray(a["value"], dtype=float)[m]
            f, t, hz = f[m], t[m], hz[m]
            m = k >= 0
            yield c, k[m], f[m], t[m], hz[m], val[m]
        return
    t = _days(history["target_date"], day) + W
    f = _days(history["forecast_date"], day)
    hz = history["horizon"].to_numpy().astype(np.int64)
    m = (t >= 0) & (t < W) & (hz >= 1) & (hz <= HORIZONS)
    if hs is not None:
        m &= f >= hs
    h = history[m]                                   # the window first: the key lookup is the slow part
    t, f, hz = t[m], f[m], hz[m]
    ci = pd.Index(candidates).get_indexer(h["model"].to_numpy())
    k = _key_index(idx, h)
    val = h["value"].to_numpy(dtype=float)
    del h
    for c in range(len(candidates)):
        m = (ci == c) & (k >= 0)
        yield c, k[m], f[m], t[m], hz[m], val[m]


def _scores(day, idx, candidates, history, actuals, open_days, groups, history_start, history_scope,
            W=WINDOW_DAYS, counts: dict | None = None):
    """rate[C, S], shortage[C, S] (float32 sums like ct_select), nday[S]; one candidate at a time. counts (1.4.6): when
    given, receives n_cells[C, S] and n_dung[C, S] (the cells and the DUNG cells behind rate)."""
    C, S = len(candidates), len(idx)
    # day grids of the window D-28 .. D-1 (index 0 .. 27)
    is_open = np.zeros((S, W), dtype=bool)
    o_k = _key_index(idx, open_days)
    o_t = _days(open_days["date"], day) + W
    m = (o_k >= 0) & (o_t >= 0) & (o_t < W)
    is_open[o_k[m], o_t[m]] = True
    actual = np.zeros((S, W), dtype=float)
    a_k = _key_index(idx, actuals)
    a_t = _days(actuals["date"], day) + W
    m = (a_k >= 0) & (a_t >= 0) & (a_t < W)
    if pd.Series(a_k[m] * W + a_t[m]).duplicated().any():
        raise ValueError("actuals: more than one row for a series and day")
    actual[a_k[m], a_t[m]] = actuals["qty"].to_numpy(dtype=float)[m]
    if history_scope is not None:
        s_k = _key_index(idx, history_scope)
        s_f = _days(history_scope["forecast_date"], day)
        s_k, s_f = s_k[s_k >= 0], s_f[s_k >= 0]
    gidx = _group_index(_groups_of(groups, idx))

    n_cells = np.zeros((C, S), dtype=np.int64)
    n_dung = np.zeros((C, S))
    under = np.zeros((C, S), dtype=np.float32)
    nday = np.full(S, np.iinfo(np.int64).max, dtype=np.int64)
    for c, k, f, t, hz, val in _history_parts(day, idx, candidates, history, history_start, W):
        if pd.DataFrame({"k": k, "f": f, "h": hz}).duplicated().any():
            raise ValueError("history: more than one forecast row for a candidate, series, forecast day and horizon")
        if history_scope is not None:
            lo = min(f.min(initial=0), s_f.min(initial=0))
            span = max(f.max(initial=0), s_f.max(initial=0)) - lo + 1
            keep = np.isin(k * span + (f - lo), s_k * span + (s_f - lo))   # (series, forecast day) in scope
            k, t, val = k[keep], t[keep], val[keep]
        keep = is_open[k, t]
        k, t, val = k[keep], t[keep], val[keep]
        act = actual[k, t]
        pub = published_qty(val, THRESHOLD).astype(float)
        cat = _category_index(pub, act, gidx[k])
        dev = pub - act
        n_cells[c] = np.bincount(k, minlength=S)
        n_dung[c] = np.bincount(k, weights=(cat == 0).astype(float), minlength=S)
        np.add.at(under[c], k, np.where(dev < 0, -dev, 0.0))
        nday = np.minimum(nday, np.bincount(np.unique(k * W + t) // W, minlength=S))
    with np.errstate(all="ignore"):
        rate = np.where(n_cells > 0, n_dung / n_cells, -1.0)
    if counts is not None:
        counts.update(n_cells=n_cells, n_dung=n_dung.astype(np.int64))
    return rate, under.astype(np.float64), nday


def select_day(day: date, scope_keys: pd.DataFrame, cand_today: dict, history, actuals: pd.DataFrame,
               open_days: pd.DataFrame, groups, history_start: date | None = None,
               history_scope: pd.DataFrame | None = None, candidates=CANDIDATES, best: str = BEST,
               window_days: int = WINDOW_DAYS, min_days: int = MIN_DAYS, detail: dict | None = None) -> pd.DataFrame:
    """SEL2 forecast of D for the series of scope_keys (sku_code, fc_code; the scope of D).

    cand_today: candidate -> frame (sku_code, fc_code, horizon, value) of its forecast of D (horizons 1..7);
    history: the stored candidate forecasts (rows outside D-28 .. D-1 or horizons 1..7 are ignored), either a frame
    (model, sku_code, fc_code, forecast_date, horizon, target_date, value) or a callable(candidate) -> (keys frame
    (sku_code, fc_code; row = key id), arrays {"kid", "f" = forecast day - D in days, "horizon", "value"}; target day =
    forecast day + horizon - 1); actuals: (sku_code, fc_code, date, qty), no row = 0; open_days: (sku_code, fc_code,
    date) of the days with open hours > 0; groups: mapping or Series (sku_code, fc_code) -> "A" / "B" / "C" (missing ->
    B); history_start: forecasts made before it are ignored; history_scope: (sku_code, fc_code, forecast_date) of the
    series in scope of each forecast day (None = every history row counts); window_days / min_days: the selection
    window (target days D-window_days .. D-1) and the days needed for ok (sel2_pipeline; defaults 28 / 14).
    Returns OUT_COLS, one row per series x horizon (series in the order of scope_keys); raises ValueError when the
    chosen value is missing (a missing forecast is never published as a number).
    detail (1.4.6, sheet GIAI_THICH): when given, receives the arrays of this selection (series in the order of
    scope_keys): candidates, keys (MultiIndex), value_h1[C, S] (forecast of D at horizon 1, NaN = none), n_cells /
    n_dung / rate / shortage[C, S], nday, ok, first / second (candidate index), second_ok[S]. The selection is
    unchanged."""
    day = pd.Timestamp(day).date()
    candidates = list(candidates)
    C, H = len(candidates), HORIZONS
    if C < 2 or best not in candidates:
        raise ValueError("at least two candidates, including the best one, are required")
    idx = pd.MultiIndex.from_frame(scope_keys[K].reset_index(drop=True))
    if idx.has_duplicates:
        raise ValueError("scope_keys: duplicated series")
    S = len(idx)
    val = np.full((C, S, H), np.nan)
    for c, fr in cand_today.items():
        if c not in candidates:
            continue
        k = _key_index(idx, fr)
        hz = fr["horizon"].to_numpy().astype(np.int64)
        m = (k >= 0) & (hz >= 1) & (hz <= H)
        if pd.Series(k[m] * H + hz[m]).duplicated().any():
            raise ValueError(f"{c}: more than one forecast row of D for a series and horizon")
        val[candidates.index(c), k[m], hz[m] - 1] = fr["value"].to_numpy(dtype=float)[m]
    counts = {} if detail is not None else None
    rate, under, nday = _scores(day, idx, candidates, history, actuals, open_days, groups, history_start, history_scope,
                                window_days, counts)

    have = ~np.isnan(val[:, :, 0])                   # candidate has a forecast of D for the series (horizon 1)
    score = np.where(have, rate, -2.0)
    order = np.lexsort((np.broadcast_to(np.arange(C)[:, None], (C, S)), under, -score), axis=0)
    first, second = order[0], order[1]
    bi = candidates.index(best)
    sr = np.arange(S)
    ok = nday >= min_days
    second_ok = ok & have[second, sr]
    value = np.where(second_ok[:, None], (val[first, sr, :] + val[second, sr, :]) / 2, val[bi, sr, :])
    if np.isnan(value).any():
        n = int(np.isnan(value).any(axis=1).sum())
        raise ValueError(f"{day}: {n} series in scope without a forecast of the chosen candidates")
    names = np.array(candidates, dtype=object)
    model = np.where(second_ok, names[first] + "+" + names[second], "FALLBACK:" + best)
    if detail is not None:
        detail.update(candidates=list(candidates), keys=idx, value_h1=val[:, :, 0].copy(), rate=rate, shortage=under,
                      nday=nday, ok=ok, first=first, second=second, second_ok=second_ok, **counts)
    out = pd.DataFrame({
        "sku_code": np.repeat(idx.get_level_values(0).to_numpy(dtype=object), H),
        "fc_code": np.repeat(idx.get_level_values(1).to_numpy(dtype=object), H),
        "horizon": np.tile(np.arange(1, H + 1), S),
        "target_date": np.tile(np.array([day + timedelta(days=h) for h in range(H)], dtype="datetime64[D]"), S),
        "raw_value": value.reshape(-1),
        "model_used": np.repeat(model, H),
        "ok": np.repeat(ok, H)})
    out["published"] = published_qty(out["raw_value"].to_numpy(), THRESHOLD)
    return out[OUT_COLS]
