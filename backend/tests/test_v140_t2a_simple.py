"""1.4.0 T2a: the scope rule, the simple candidates TSB / DOW4 / AVG7 and the extra LightGBM blocks DAYPROF / ROBUST
(app/ml/sel2) give the values of the research backtest reports/cai-tien-20261031 (ct_prep.py scope, ct_simple.py,
ct_feat.py) to 1e-9, and never read the forecast day or later.

Fixtures (tests/fixtures/sel2, generated outside the repository from the backtest arrays and its stored outputs):
  simple.npz  60 keys (groups A/B/C, keys entering/leaving scope, no demand, no open hours, many closed days, demand on
              closed days, late first open day), demand + open hours 2026-01-01..2026-10-28, expected scope and
              TSB / DOW4 / AVG7 (horizons 1..7, NaN = key out of scope) of 6 forecast days from 2026-06-01 to 2026-10-22
  extras.npz  panel of those keys + 4 synthetic rows (all NaN, NaN-heavy, constant, late start), 11 origins t0 (0 .. T),
              ROBUST columns and DAYPROF columns of the 7 following target days, float64 and float32 as ct_feat gives
              them"""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.ml.sel2 import extras, scope, simple

FIX = Path(__file__).parent / "fixtures" / "sel2"
TOL = 1e-9


@pytest.fixture(scope="module")
def sf():
    with np.load(FIX / "simple.npz", allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    d["day0"] = date.fromisoformat(str(d["day0"]))
    d["days"] = [date.fromisoformat(str(x)) for x in d["days"]]
    d["daily"] = d["daily"].astype(np.float64)
    d["oh"] = d["oh"].astype(np.float64)
    d["open"] = simple.open_mask(d["oh"])
    return d


@pytest.fixture(scope="module")
def xf():
    with np.load(FIX / "extras.npz", allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    d["dates"] = pd.date_range(str(d["day0"]), periods=d["Y"].shape[1], freq="D")
    return d


def _g(sf, D) -> int:
    return (D - sf["day0"]).days


def _all_simple(sf, daily, oh, D):
    g = _g(sf, D)
    om = simple.open_mask(oh)
    return (scope.scope_mask(daily, oh, g), simple.tsb(daily, om, g, _g(sf, simple.TSB_START)),
            simple.dow4(daily, om, g, sf["day0"]), simple.avg7(daily, g))


def _maxdiff(a, b) -> float:
    assert np.array_equal(np.isnan(a), np.isnan(b))
    m = ~np.isnan(a)
    return float(np.max(np.abs(a[m] - b[m]), initial=0.0))


# ------------------------------------------------------------------ equality with the backtest
def test_fixture_covers_the_cases(sf, xf):
    assert sf["daily"].shape == sf["oh"].shape == (60, 301) and sf["day0"] == date(2026, 1, 1)
    assert date(2026, 6, 1) in sf["days"] and date(2026, 10, 22) in sf["days"]
    sc = sf["scope"]
    assert sc.all(axis=0).any() and (~sc).all(axis=0).any() and (sc.any(axis=0) & ~sc.all(axis=0)).any()
    assert set(sf["group"]) == {"A", "B", "C"}
    assert (np.isnan(xf["Y"]).all(axis=1)).any() and 0 in xf["t0"] and xf["Y"].shape[1] in xf["t0"]


def test_scope_matches_backtest(sf):
    for j, D in enumerate(sf["days"]):
        got = scope.scope_mask(sf["daily"], sf["oh"], _g(sf, D))
        assert got.dtype == bool and np.array_equal(got, sf["scope"][j]), D


@pytest.mark.parametrize("name", ["tsb", "dow4", "avg7"])
def test_simple_candidates_match_backtest(sf, name):
    worst = 0.0
    for j, D in enumerate(sf["days"]):
        sc, t, d4, a7 = _all_simple(sf, sf["daily"], sf["oh"], D)
        got = {"tsb": np.tile(t[:, None], (1, 7)), "dow4": d4, "avg7": np.tile(a7[:, None], (1, 7))}[name]
        assert got.shape == (60, 7) and got.dtype == np.float64 and not np.isnan(got).any()
        exp = sf[name][j]
        inside = sf["scope"][j]
        worst = max(worst, _maxdiff(got[inside], exp[inside]))
    assert worst <= TOL, worst


def test_robust_matches_backtest(xf):
    assert extras.ROBUST_NAMES == [str(x) for x in xf["robust_names"]]
    assert extras.ROBUST_NAMES == [f"{s}_{w}" for w in (7, 14, 28, 56) for s in ("med", "p25", "p75")] + \
        ["tmean_28", "tmean_56"]
    for i, t0 in enumerate(xf["t0"]):
        got = extras.robust(xf["Y"], int(t0))
        assert got.shape == (xf["Y"].shape[0], 14) and got.dtype == np.float64
        assert _maxdiff(got, xf["robust_f64"][i]) <= TOL, t0
        assert np.array_equal(got.astype(np.float32), xf["robust_f32"][i], equal_nan=True), t0


def test_dayprof_matches_backtest(xf):
    assert extras.DAYPROF_NAMES == [str(x) for x in xf["dayprof_names"]]
    for i, t0 in enumerate(xf["t0"]):
        prof = extras.dayprof_profile(xf["Y"], xf["dates"], int(t0))
        for h, td in enumerate(xf["td"][i]):
            td = pd.Timestamp(str(td))
            got = extras.dayprof(xf["Y"], xf["dates"], int(t0), td)
            assert got.shape == (xf["Y"].shape[0], 5) and got.dtype == np.float64
            assert np.array_equal(got, extras.dayprof_columns(prof, td), equal_nan=True)
            assert _maxdiff(got, xf["dayprof_f64"][i, h]) <= TOL, (t0, td)
            assert np.array_equal(got.astype(np.float32), xf["dayprof_f32"][i, h], equal_nan=True), (t0, td)


# ------------------------------------------------------------------ edge cases
def test_scope_needs_a_sale_and_one_open_hour():
    K, G = 4, 120
    daily, oh = np.zeros((K, G)), np.full((K, G), np.nan)
    daily[0, 100], oh[0, 50] = 3, 1.0                     # sold + 1 h -> in scope
    daily[1, 100], oh[1, 50:52] = 3, 0.4                  # 0.8 h -> out
    oh[2, :] = 8.0                                        # open, never sold -> out
    daily[3, 100], oh[3, 5:10] = 3, 8.0                   # hours only before D-90 -> out
    oh[3, 100] = -5.0                                     # negative hours count as 0
    assert scope.scope_mask(daily, oh, 110).tolist() == [True, False, False, False]
    assert scope.scope_mask(daily, oh, 101).tolist() == [True, False, False, False]
    assert scope.scope_mask(daily, oh, 100).tolist() == [False] * 4      # the sale of day D itself is not read
    with pytest.raises(ValueError):
        scope.scope_mask(daily, oh, scope.SCOPE_DAYS - 1)


def test_tsb_needs_28_open_days():
    K, G = 3, 60
    daily = np.full((K, G), 2.0)
    om = np.zeros((K, G), dtype=bool)
    om[0, :27] = True                                     # 27 open days -> no state -> 0
    om[1, :28] = True                                     # 28 -> p = 1, z = 2 -> 2
    om[2, :28] = True
    daily[2, :28:2] = 0                                   # 14 days with demand of 28 -> 0.5 x 2
    got = simple.tsb(daily, om, G, 0)
    assert got.tolist() == [0.0, 2.0, 1.0]
    assert simple.tsb(daily, np.zeros((K, G), dtype=bool), G, 0).tolist() == [0.0] * 3   # no open day
    # after the start, an open day without demand moves p only: p = 1 + 0.1 (0 - 1)
    om[1, 28] = True
    daily[1, 28] = 0
    assert simple.tsb(daily, om, 29, 0)[1] == pytest.approx(0.9 * 2.0, abs=1e-12)
    # demand on a closed day is not an observation
    daily[1, 30] = 50.0
    assert simple.tsb(daily, om, 31, 0)[1] == pytest.approx(0.9 * 2.0, abs=1e-12)


def test_dow4_same_weekday_open_days_only():
    day0 = date(2026, 1, 5)                               # a Monday
    K, G = 2, 100
    daily = np.arange(G, dtype=float)[None, :].repeat(K, axis=0)
    om = np.ones((K, G), dtype=bool)
    om[1, :] = False                                      # never open -> 0 for every horizon
    g = 98                                                # D = Monday + 98 days = a Monday
    got = simple.dow4(daily, om, g, day0)
    assert got.shape == (2, 7) and (got[1] == 0).all()
    # horizon 1 = Monday: Mondays 91, 84, 77, 70 (newest first, within D-84 .. D-1)
    assert got[0, 0] == pytest.approx((91 + 84 + 77 + 70) / 4)
    assert got[0, 6] == pytest.approx((97 + 90 + 83 + 76) / 4)  # Sunday
    om[0, 91] = om[0, 84] = False                         # closed Mondays are skipped
    assert simple.dow4(daily, om, g, day0)[0, 0] == pytest.approx((77 + 70 + 63 + 56) / 4)
    om[0, :] = False
    om[0, 14] = True                                      # only one open Monday in the 12 weeks -> its value
    assert simple.dow4(daily, om, g, day0)[0, 0] == 14.0
    om[0, 14], om[0, 7] = False, True                     # Monday 7 < D-84 is outside the window -> 0
    assert simple.dow4(daily, om, g, day0)[0, 0] == 0.0


def test_avg7_is_the_mean_of_seven_calendar_days():
    daily = np.zeros((1, 20))
    daily[0, 12:19] = [7, 0, 0, 0, 0, 0, 0]
    assert simple.avg7(daily, 19).tolist() == [1.0]
    assert simple.avg7(daily, 20).tolist() == [0.0]       # day 12 left the window
    with pytest.raises(ValueError):
        simple.avg7(daily, 6)


def test_extras_all_nan_windows_give_nan():
    S, T = 2, 70
    Y = np.full((S, T), np.nan)
    Y[1, :] = 4.0
    dates = pd.date_range("2026-03-02", periods=T, freq="D")
    r = extras.robust(Y, T)
    assert np.isnan(r[0]).all() and (r[1] == 4.0).all()
    assert np.isnan(extras.robust(Y, 0)).all()
    d = extras.dayprof(Y, dates, T, dates[-1] + pd.Timedelta(days=1))
    assert np.isnan(d[0]).all()
    assert d[1].tolist() == pytest.approx([1 / 7, 1 / 7, d[1, 2], 4.0, 1.0])
    assert np.isnan(extras.dayprof(Y, dates, 0, dates[0])).all()
    # the trimmed mean drops ceil(10 % of the known values) highest values
    w = np.array([[1.0, 2.0, 3.0, 100.0, np.nan], [np.nan] * 5])
    assert extras.trimmed_mean(w, 0.10)[0] == 2.0 and np.isnan(extras.trimmed_mean(w, 0.10)[1])


# ------------------------------------------------------------------ no leak
def test_no_value_reads_the_forecast_day_or_later(sf):
    D = date(2026, 9, 15)
    g = _g(sf, D)
    base = _all_simple(sf, sf["daily"], sf["oh"], D)
    rng = np.random.default_rng(1)
    daily, oh = sf["daily"].copy(), sf["oh"].copy()
    daily[:, g:] = rng.integers(0, 500, daily[:, g:].shape)
    oh[:, g:] = rng.choice([np.nan, 0.0, 9.0], oh[:, g:].shape)
    for a, b in zip(base, _all_simple(sf, daily, oh, D)):
        assert np.array_equal(a, b)
    # day D-1 is read by every formula
    daily, oh = sf["daily"].copy(), sf["oh"].copy()
    k = int(np.nonzero(sf["scope"][sf["days"].index(D)] & sf["open"][:, g - 1])[0][0])
    daily[k, g - 1] += 1000
    got = _all_simple(sf, daily, oh, D)
    assert got[1][k] != base[1][k] and got[3][k] != base[3][k]
    assert got[2][k, 6] != base[2][k, 6]                  # D-1 has the weekday of horizon 7 (D+6)
    daily = np.zeros_like(sf["daily"])
    oh = np.full_like(sf["oh"], np.nan)
    daily[:, g - 1], oh[:, g - 1] = 1.0, 1.0              # a sale and one open hour on D-1 only -> in scope
    assert scope.scope_mask(daily, oh, g).all() and not scope.scope_mask(daily, oh, g - 1).any()


def test_extras_no_leak(xf):
    Y, dates = xf["Y"], xf["dates"]
    t0 = 150
    td = dates[t0 + 3]
    r, d = extras.robust(Y, t0), extras.dayprof(Y, dates, t0, td)
    Y2 = Y.copy()
    Y2[:, t0:] = 999.0
    assert np.array_equal(r, extras.robust(Y2, t0), equal_nan=True)
    assert np.array_equal(d, extras.dayprof(Y2, dates, t0, td), equal_nan=True)
    Y3 = Y.copy()
    Y3[:, t0 - 1] = 999.0
    assert not np.array_equal(r, extras.robust(Y3, t0), equal_nan=True)
    assert not np.array_equal(extras.dayprof(Y, dates, t0, dates[t0 - 1] + timedelta(days=7)),
                              extras.dayprof(Y3, dates, t0, dates[t0 - 1] + timedelta(days=7)), equal_nan=True)
