"""1.4.0 T3 edge cases of the per-series model choice SEL2 (app/ml/sel2/select.py), beyond test_v140_t3_select.py:
scope of D (out-of-scope rows never output, scope order kept), history_start and history_scope boundaries, known days
counted by target day (several horizons on one day = one day), the full tie, refused inputs (duplicates, too few
candidates, missing / non-finite values), negative candidate values, and a 3,000-series performance smoke test.
Synthetic data only."""
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.ml.sel2 import select

K = ["sku_code", "fc_code"]
HCOLS = ["model"] + K + ["forecast_date", "horizon", "target_date", "value"]
D = date(2026, 9, 30)
TODAY = {"MOC": 1.0, "V33_L112": 2.0, "V36_two_stage@0.6": 3.0, "TSB": 4.0, "DOW4": 5.0, "AVG7": 6.0}
S1, S2, S3 = ("S1", "HN"), ("S2", "HN"), ("S3", "BD")


def _t(i: int) -> pd.Timestamp:
    return pd.Timestamp(D - timedelta(days=i))


def _hist(key, vals, days=28, horizons=(1,)):
    """History rows of one series: candidate -> value (or callable(target) -> value / None) of its forecast of every
    target day D-days .. D-1, at each horizon of `horizons` (forecast day = target - (horizon - 1))."""
    rows = []
    for i in range(1, days + 1):
        t = _t(i)
        for c, v in vals.items():
            v = v(t) if callable(v) else v
            if v is None:
                continue
            for h in horizons:
                rows.append((c, *key, t - pd.Timedelta(days=h - 1), h, t, v))
    return rows


def _today(key, vals):
    return {c: pd.DataFrame([(*key, h, v) for h in range(1, 8)], columns=K + ["horizon", "value"])
            for c, v in vals.items()}


def _merge_today(*parts):
    out = {}
    for p in parts:
        for c, f in p.items():
            out[c] = pd.concat([out[c], f], ignore_index=True) if c in out else f
    return out


def _env(keys, actual=10.0, days=28):
    acts = pd.DataFrame([(*k, _t(i), actual) for k in keys for i in range(1, days + 1)], columns=K + ["date", "qty"])
    opens = pd.DataFrame([(*k, _t(i)) for k in keys for i in range(1, days + 1)], columns=K + ["date"])
    return acts, opens


def _run(scope, today, hist_rows, keys=None, groups=None, **kw):
    acts, opens = _env(keys or scope)
    hist = pd.DataFrame(hist_rows, columns=HCOLS)
    return select.select_day(D, pd.DataFrame(scope, columns=K), today, hist, acts, opens,
                             groups if groups is not None else {k: "A" for k in (keys or scope)}, **kw)


ALL10 = {c: 10.0 for c in select.CANDIDATES}


# ------------------------------------------------------------------ scope of D
def test_series_out_of_scope_on_d_are_not_output_and_scope_order_is_kept():
    keys = [S1, S2, S3]
    hist = sum((_hist(k, ALL10) for k in keys), [])
    today = _merge_today(*(_today(k, TODAY) for k in keys))
    out = _run([S3, S1], today, hist, keys=keys)
    assert len(out) == 14
    assert list(zip(out["sku_code"], out["fc_code"])) == [S3] * 7 + [S1] * 7
    assert out["horizon"].tolist() == list(range(1, 8)) * 2
    assert out["target_date"].tolist() == [pd.Timestamp(D + timedelta(days=h)) for h in range(7)] * 2
    assert (out["model_used"] == "MOC+V33_L112").all()


def test_forecast_rows_of_d_outside_horizons_1_7_are_ignored():
    today = _today(S1, TODAY)
    extra = pd.DataFrame([(*S1, 0, 99.0), (*S1, 8, 99.0)], columns=K + ["horizon", "value"])
    today["MOC"] = pd.concat([today["MOC"], extra], ignore_index=True)
    out = _run([S1], today, _hist(S1, ALL10))
    assert np.allclose(out["raw_value"], (1.0 + 2.0) / 2)


def test_empty_scope_gives_an_empty_frame():
    out = _run([], {}, _hist(S1, ALL10), keys=[S1])
    assert out.empty and list(out.columns) == select.OUT_COLS


# ------------------------------------------------------------------ history_start / history_scope
@pytest.mark.parametrize("start, ok", [(D - timedelta(days=14), True), (D - timedelta(days=13), False)])
def test_history_start_is_inclusive_and_excludes_earlier_forecasts(start, ok):
    out = _run([S1], _today(S1, TODAY), _hist(S1, ALL10), history_start=start)
    assert out["ok"].all() == ok and (~out["ok"]).all() == (not ok)
    assert (out["model_used"] == ("MOC+V33_L112" if ok else "FALLBACK:V33_L112")).all()


def test_history_start_judges_the_forecast_day_not_the_target_day():
    # horizon-3 forecasts: target D-i made on D-i-2; history_start D-15 keeps the forecast days >= D-15, i.e. the
    # target days D-13 .. D-1 (13 days) -> fallback, although 15 target days are >= history_start
    out = _run([S1], _today(S1, TODAY), _hist(S1, ALL10, horizons=(3,)), history_start=D - timedelta(days=15))
    assert (out["model_used"] == "FALLBACK:V33_L112").all()
    out = _run([S1], _today(S1, TODAY), _hist(S1, ALL10, horizons=(3,)), history_start=D - timedelta(days=16))
    assert (out["model_used"] == "MOC+V33_L112").all()


def _hscope(key, first: int, last: int = 1):
    return [(*key, _t(i)) for i in range(last, first + 1)]


@pytest.mark.parametrize("first, ok", [(14, True), (13, False)])
def test_history_scope_drops_forecast_days_out_of_scope(first, ok):
    hs = pd.DataFrame(_hscope(S1, first) + _hscope(S2, 28), columns=K + ["forecast_date"])
    out = _run([S1], _today(S1, TODAY), _hist(S1, ALL10), keys=[S1, S2], history_scope=hs)
    assert (out["model_used"] == ("MOC+V33_L112" if ok else "FALLBACK:V33_L112")).all()


def test_history_scope_of_another_series_does_not_count():
    hs = pd.DataFrame(_hscope(S2, 28), columns=K + ["forecast_date"])
    out = _run([S1], _today(S1, TODAY), _hist(S1, ALL10) + _hist(S2, ALL10), keys=[S1, S2], history_scope=hs)
    assert (out["model_used"] == "FALLBACK:V33_L112").all() and not out["ok"].any()


def test_empty_history_scope_means_no_known_day():
    hs = pd.DataFrame(columns=K + ["forecast_date"])
    out = _run([S1], _today(S1, TODAY), _hist(S1, ALL10), history_scope=hs)
    assert (out["model_used"] == "FALLBACK:V33_L112").all()


def test_history_scope_changes_the_ranking():
    # actual 10. MOC right only on the old half (D-28 .. D-15), DOW4 only on the recent half; the rest over-forecast
    recent = lambda t: t >= _t(14)                                        # noqa: E731
    h = {c: 50.0 for c in select.CANDIDATES} | {"MOC": lambda t: 50.0 if recent(t) else 10.0,
                                                 "DOW4": lambda t: 10.0 if recent(t) else 50.0}
    out = _run([S1], _today(S1, TODAY), _hist(S1, h))
    assert (out["model_used"] == "MOC+DOW4").all()                       # rate 0.5 each, tie -> index
    hs = pd.DataFrame(_hscope(S1, 14), columns=K + ["forecast_date"])
    out = _run([S1], _today(S1, TODAY), _hist(S1, h), history_scope=hs)
    assert (out["model_used"] == "DOW4+MOC").all()                       # DOW4 1.0, the rest 0 -> index


# ------------------------------------------------------------------ known days, ties
@pytest.mark.parametrize("ndays, ok", [(7, False), (13, False), (14, True)])
def test_known_days_are_target_days_not_cells(ndays, ok):
    """AVG7 has 2 cells (horizons 1 and 2) on each of `ndays` target days: nday counts the days, not the cells."""
    rows = _hist(S1, {c: 10.0 for c in select.CANDIDATES if c != "AVG7"})
    rows += _hist(S1, {"AVG7": 10.0}, days=ndays, horizons=(1, 2))
    out = _run([S1], _today(S1, TODAY), rows)
    assert out["ok"].all() == ok
    assert (out["model_used"] == ("MOC+V33_L112" if ok else "FALLBACK:V33_L112")).all()


def test_nday_is_the_min_even_for_a_candidate_without_forecast_of_d():
    # AVG7 has 13 known days and no forecast of D: it cannot be chosen, but it still blocks ok (MIN over candidates)
    rows = _hist(S1, {c: 10.0 for c in select.CANDIDATES if c != "AVG7"}) + _hist(S1, {"AVG7": 10.0}, days=13)
    out = _run([S1], _today(S1, {c: v for c, v in TODAY.items() if c != "AVG7"}), rows)
    assert (out["model_used"] == "FALLBACK:V33_L112").all() and not out["ok"].any()


def test_full_tie_follows_candidate_index():
    out = _run([S1], _today(S1, TODAY), _hist(S1, ALL10))
    assert (out["model_used"] == "MOC+V33_L112").all()
    cands = ["AVG7", "TSB", "V33_L112", "MOC"]
    out = select.select_day(D, pd.DataFrame([S1], columns=K), _today(S1, TODAY),
                            pd.DataFrame(_hist(S1, ALL10), columns=HCOLS), *_env([S1]), {S1: "A"}, candidates=cands)
    assert (out["model_used"] == "AVG7+TSB").all()
    assert np.allclose(out["raw_value"], (6.0 + 4.0) / 2)


def test_explicit_nan_forecast_of_d_equals_no_row():
    h = {c: 50.0 for c in select.CANDIDATES} | {"AVG7": 10.0, "DOW4": 11.0}
    absent = _run([S1], _today(S1, {c: v for c, v in TODAY.items() if c != "AVG7"}), _hist(S1, h))
    nan = _run([S1], _today(S1, TODAY | {"AVG7": np.nan}), _hist(S1, h))
    pd.testing.assert_frame_equal(nan, absent)
    assert (nan["model_used"] == "DOW4+MOC").all()


# ------------------------------------------------------------------ values pinned / refused
def test_negative_candidate_values_are_kept_raw_and_published_as_zero():
    # nothing in select.py validates the sign: a negative mean is kept as raw_value and published as 0 (< 0.2)
    out = _run([S1], _today(S1, TODAY | {"MOC": -1.0, "V33_L112": -3.0}), _hist(S1, ALL10))
    assert (out["model_used"] == "MOC+V33_L112").all()
    assert (out["raw_value"] == -2.0).all() and (out["published"] == 0).all()


def test_negative_history_value_is_scored_as_zero_published():
    # actual 0, MOC -5 published 0 -> DUNG; others 50 -> not DUNG
    h = {c: 50.0 for c in select.CANDIDATES} | {"MOC": -5.0, "AVG7": 0.0}
    acts, opens = _env([S1], actual=0.0)
    out = select.select_day(D, pd.DataFrame([S1], columns=K), _today(S1, TODAY), pd.DataFrame(_hist(S1, h), columns=HCOLS),
                            acts, opens, {S1: "A"})
    assert (out["model_used"] == "MOC+AVG7").all()


def test_nan_in_a_later_horizon_of_the_chosen_pair_is_refused():
    today = _today(S1, TODAY)
    today["V33_L112"].loc[today["V33_L112"]["horizon"] == 3, "value"] = np.nan
    with pytest.raises(ValueError, match="without a forecast"):
        _run([S1], today, _hist(S1, ALL10))


@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_non_finite_history_value_in_the_window_is_refused(bad):
    rows = _hist(S1, ALL10)
    rows[5] = rows[5][:-1] + (bad,)
    with pytest.raises(ValueError):
        _run([S1], _today(S1, TODAY), rows)


def test_non_finite_history_value_outside_the_window_is_ignored():
    rows = _hist(S1, ALL10) + [("MOC", *S1, _t(40), 1, _t(40), np.nan)]
    out = _run([S1], _today(S1, TODAY), rows)
    assert (out["model_used"] == "MOC+V33_L112").all()


def test_duplicated_inputs_are_refused():
    hist = _hist(S1, ALL10)
    with pytest.raises(ValueError, match="history"):
        _run([S1], _today(S1, TODAY), hist + hist[:1])
    today = _today(S1, TODAY)
    today["TSB"] = pd.concat([today["TSB"], today["TSB"].iloc[:1]], ignore_index=True)
    with pytest.raises(ValueError, match="TSB"):
        _run([S1], today, hist)
    with pytest.raises(ValueError, match="scope_keys"):
        _run([S1, S1], _today(S1, TODAY), hist, keys=[S1])
    acts, opens = _env([S1])
    with pytest.raises(ValueError, match="actuals"):
        select.select_day(D, pd.DataFrame([S1], columns=K), _today(S1, TODAY), pd.DataFrame(hist, columns=HCOLS),
                          pd.concat([acts, acts.iloc[:1]], ignore_index=True), opens, {S1: "A"})


def test_duplicated_rows_outside_the_window_or_scope_are_ignored():
    hist = _hist(S1, ALL10)
    old = [("MOC", *S1, _t(40), 1, _t(40), 1.0)] * 2 + [("MOC", *S2, _t(1), 1, _t(1), 1.0)] * 2
    out = _run([S1], _today(S1, TODAY), hist + old)
    assert (out["model_used"] == "MOC+V33_L112").all()


@pytest.mark.parametrize("cands, best", [(["V33_L112"], "V33_L112"), (["MOC", "TSB"], "V33_L112")])
def test_candidate_list_is_checked(cands, best):
    with pytest.raises(ValueError, match="two candidates"):
        select.select_day(D, pd.DataFrame([S1], columns=K), _today(S1, TODAY),
                          pd.DataFrame(_hist(S1, ALL10), columns=HCOLS), *_env([S1]), {S1: "A"},
                          candidates=cands, best=best)


def test_unknown_candidate_names_are_ignored():
    today = _today(S1, TODAY) | _today(S1, {"OTHER": 99.0})
    out = _run([S1], today, _hist(S1, ALL10 | {"OTHER": 10.0}))
    assert (out["model_used"] == "MOC+V33_L112").all()


# ------------------------------------------------------------------ performance smoke
def test_performance_3000_series():
    """3,000 series x 6 candidates x horizons 1..7 over the 28-day window (about 3.5 M history rows) in < 20 s."""
    rng = np.random.default_rng(7)
    S, C, H, W = 3000, len(select.CANDIDATES), 7, 28
    skus = np.array([f"SKU{i:05d}" for i in range(S)], dtype=object)
    fcs = np.where(np.arange(S) % 2 == 0, "HN", "BD").astype(object)
    # one block (series, candidate) = every (target day D-28 .. D-1, horizon 1..7)
    ti = np.repeat(np.arange(1, W + 1), H)
    hz = np.tile(np.arange(1, H + 1), W)
    n = W * H
    tgt = np.datetime64(D, "D") - ti
    hist = pd.DataFrame({
        "model": np.repeat(np.array(select.CANDIDATES, dtype=object), S * n),
        "sku_code": np.tile(np.repeat(skus, n), C),
        "fc_code": np.tile(np.repeat(fcs, n), C),
        "forecast_date": np.tile(tgt - (hz - 1), S * C),
        "horizon": np.tile(hz, S * C),
        "target_date": np.tile(tgt, S * C),
        "value": rng.gamma(1.0, 3.0, S * C * n)})
    days = np.datetime64(D, "D") - np.arange(1, W + 1)
    acts = pd.DataFrame({"sku_code": np.repeat(skus, W), "fc_code": np.repeat(fcs, W), "date": np.tile(days, S),
                         "qty": rng.poisson(3.0, S * W).astype(float)})
    opens = acts[K + ["date"]]
    keys = pd.DataFrame({"sku_code": skus, "fc_code": fcs})
    today = {c: pd.DataFrame({"sku_code": np.repeat(skus, H), "fc_code": np.repeat(fcs, H),
                              "horizon": np.tile(np.arange(1, H + 1), S), "value": rng.gamma(1.0, 3.0, S * H)})
             for c in select.CANDIDATES}
    groups = pd.Series(np.array(["A", "B", "C"], dtype=object)[np.arange(S) % 3],
                       index=pd.MultiIndex.from_frame(keys))
    hs = pd.DataFrame({"sku_code": np.repeat(skus, W + H), "fc_code": np.repeat(fcs, W + H),
                       "forecast_date": np.tile(np.datetime64(D, "D") - np.arange(1, W + H + 1), S)})
    t = time.monotonic()
    out = select.select_day(D, keys, today, hist, acts, opens, groups, history_start=D - timedelta(days=40),
                            history_scope=hs)
    took = time.monotonic() - t
    assert len(out) == S * H and out["ok"].all()
    assert not out["model_used"].str.startswith("FALLBACK").any()
    assert out["raw_value"].notna().all() and (out["published"] >= 0).all()
    assert took < 20.0, f"select_day took {took:.1f} s for {S} series"
