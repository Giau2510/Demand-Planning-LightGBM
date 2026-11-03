"""1.4.0 T2a edge cases of app/ml/sel2 (scope, TSB, DOW4, AVG7, ROBUST, DAYPROF): input validation, shape / dtype
contracts, determinism and row independence, no leak per function (day D and later never read, D-1 read where the
formula reads it, nothing read before the window), NaN handling, scope / window boundaries and hand-computed values on
small synthetic arrays. Synthetic data and the existing fixtures tests/fixtures/sel2 only."""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.ml.sel2 import extras, scope, simple

FIX = Path(__file__).parent / "fixtures" / "sel2"
MON = date(2026, 3, 2)                                    # a Monday


@pytest.fixture(scope="module")
def sf():
    with np.load(FIX / "simple.npz", allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    d["day0"] = date.fromisoformat(str(d["day0"]))
    d["daily"] = d["daily"].astype(np.float64)
    d["oh"] = d["oh"].astype(np.float64)
    return d


@pytest.fixture(scope="module")
def xf():
    with np.load(FIX / "extras.npz", allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    d["dates"] = pd.date_range(str(d["day0"]), periods=d["Y"].shape[1], freq="D")
    return d


def _simple_all(daily, oh, g, day0, g_start):
    om = simple.open_mask(oh)
    return {"scope": scope.scope_mask(daily, oh, g), "tsb": simple.tsb(daily, om, g, g_start),
            "dow4": simple.dow4(daily, om, g, day0), "avg7": simple.avg7(daily, g)}


def _rand(K=12, G=200, seed=7):
    rng = np.random.default_rng(seed)
    daily = rng.integers(0, 6, (K, G)).astype(np.float64) * (rng.random((K, G)) < 0.5)
    oh = rng.choice([np.nan, 0.0, 4.0, 10.5], (K, G))
    return daily, oh


# ------------------------------------------------------------------ input validation
def test_windows_must_be_covered():
    daily, oh = np.zeros((2, 100)), np.full((2, 100), 8.0)
    om = simple.open_mask(oh)
    with pytest.raises(ValueError, match="not covered"):
        scope.scope_mask(daily, oh, scope.SCOPE_DAYS - 1)
    assert scope.scope_mask(daily, oh, scope.SCOPE_DAYS).shape == (2,)          # exactly D-90 = day 0
    with pytest.raises(ValueError, match="not covered"):
        simple.dow4(daily, om, simple.DOW4_DAYS - 1, MON)
    assert simple.dow4(daily, om, simple.DOW4_DAYS, MON).shape == (2, 7)
    with pytest.raises(ValueError, match="not covered"):
        simple.avg7(daily, simple.AVG7_DAYS - 1)
    assert simple.avg7(daily, simple.AVG7_DAYS).shape == (2,)


@pytest.mark.parametrize("g_start, g_d", [(-1, 50), (51, 50), (0, -1)])
def test_tsb_start_must_be_within_the_arrays_and_not_after_d(g_start, g_d):
    with pytest.raises(ValueError, match="TSB start"):
        simple.tsb(np.ones((1, 60)), np.ones((1, 60), dtype=bool), g_d, g_start)


def test_tsb_start_equal_to_d_reads_nothing():
    assert simple.tsb(np.ones((2, 60)), np.ones((2, 60), dtype=bool), 50, 50).tolist() == [0.0, 0.0]
    assert simple.tsb(np.ones((2, 60)), np.ones((2, 60), dtype=bool), 0, 0).tolist() == [0.0, 0.0]


# ------------------------------------------------------------------ shape / dtype contracts
def test_simple_shapes_and_dtypes_with_integer_inputs():
    daily = np.arange(3 * 100, dtype=np.int64).reshape(3, 100) % 5
    oh = np.full((3, 100), 8, dtype=np.int64)
    om = simple.open_mask(oh)
    assert om.dtype == bool and om.shape == (3, 100)
    sc = scope.scope_mask(daily, oh, 95)
    assert sc.dtype == bool and sc.shape == (3,)
    for got, shape in ((simple.tsb(daily, om, 95, 0), (3,)), (simple.dow4(daily, om, 95, MON), (3, 7)),
                       (simple.dow4(daily, om, 95, MON, horizons=3), (3, 3)), (simple.avg7(daily, 95), (3,))):
        assert got.dtype == np.float64 and got.shape == shape and np.isfinite(got).all() and (got >= 0).all()
    assert np.array_equal(simple.dow4(daily, om, 95, MON, horizons=3), simple.dow4(daily, om, 95, MON)[:, :3])


def test_simple_functions_accept_zero_keys():
    daily, oh = np.zeros((0, 100)), np.zeros((0, 100))
    om = simple.open_mask(oh)
    assert scope.scope_mask(daily, oh, 95).shape == (0,)
    assert simple.tsb(daily, om, 95, 0).shape == (0,)
    assert simple.dow4(daily, om, 95, MON).shape == (0, 7)
    assert simple.avg7(daily, 95).shape == (0,)


def test_dayprof_accepts_zero_series():
    dates = pd.date_range(str(MON), periods=100, freq="D")
    got = extras.dayprof(np.zeros((0, 100)), dates, 90, dates[90])
    assert got.shape == (0, len(extras.DAYPROF_NAMES)) and got.dtype == np.float64


def test_robust_accepts_zero_series():
    # an empty set of series (no key in scope) must give an empty block, not an exception
    got = extras.robust(np.zeros((0, 100)), 90)
    assert got.shape == (0, len(extras.ROBUST_NAMES)) and got.dtype == np.float64


def test_inputs_are_not_modified(xf):
    daily, oh = _rand()
    om = simple.open_mask(oh)
    keep = daily.copy(), oh.copy(), om.copy()
    _simple_all(daily, oh, 150, MON, 10)
    assert np.array_equal(daily, keep[0]) and np.array_equal(oh, keep[1], equal_nan=True)
    assert np.array_equal(om, keep[2])
    Y = xf["Y"].copy()
    extras.robust(Y, 150)
    extras.dayprof(Y, xf["dates"], 150, xf["dates"][152])
    assert np.array_equal(Y, xf["Y"], equal_nan=True)


# ------------------------------------------------------------------ determinism, row independence
def test_simple_deterministic_and_row_independent(sf):
    g, g_start = 250, 0
    a = _simple_all(sf["daily"], sf["oh"], g, sf["day0"], g_start)
    b = _simple_all(sf["daily"], sf["oh"], g, sf["day0"], g_start)
    perm = np.random.default_rng(3).permutation(sf["daily"].shape[0])
    c = _simple_all(sf["daily"][perm], sf["oh"][perm], g, sf["day0"], g_start)
    for k in a:
        assert np.array_equal(a[k], b[k]), k
        assert np.array_equal(a[k][perm], c[k]), k


def test_extras_deterministic_and_row_independent(xf):
    Y, dates = xf["Y"], xf["dates"]
    perm = np.random.default_rng(4).permutation(Y.shape[0])
    for t0 in (13, 85, 240):
        td = dates[t0] + pd.Timedelta(days=2)
        r1, r2, rp = extras.robust(Y, t0), extras.robust(Y, t0), extras.robust(Y[perm], t0)
        d1, d2, dp = (extras.dayprof(Y, dates, t0, td), extras.dayprof(Y, dates, t0, td),
                      extras.dayprof(Y[perm], dates, t0, td))
        assert np.array_equal(r1, r2, equal_nan=True) and np.array_equal(r1[perm], rp, equal_nan=True)
        assert np.array_equal(d1, d2, equal_nan=True) and np.array_equal(d1[perm], dp, equal_nan=True)


# ------------------------------------------------------------------ no leak, per function
@pytest.mark.parametrize("g", [90, 120, 199])
@pytest.mark.parametrize("name", ["scope", "tsb", "dow4", "avg7"])
def test_simple_never_read_day_d_or_later(name, g):
    daily, oh = _rand(G=230)
    base = _simple_all(daily, oh, g, MON, 5)[name]
    rng = np.random.default_rng(g)
    for fill_d, fill_oh in ((rng.integers(0, 900, (12, 230 - g)).astype(float), rng.choice([np.nan, 0.0, 24.0], (12, 230 - g))),
                            (np.full((12, 230 - g), np.nan), np.full((12, 230 - g), np.nan)),
                            (np.full((12, 230 - g), -50.0), np.full((12, 230 - g), -3.0))):
        d2, o2 = daily.copy(), oh.copy()
        d2[:, g:], o2[:, g:] = fill_d, fill_oh
        assert np.array_equal(base, _simple_all(d2, o2, g, MON, 5)[name]), (name, g)


def test_simple_read_d_minus_1_where_the_formula_does():
    K, G, g = 3, 120, 110
    daily = np.full((K, G), 2.0)
    oh = np.full((K, G), 8.0)
    base = _simple_all(daily, oh, g, MON, 0)
    d2 = daily.copy()
    d2[:, g - 1] = 30.0                                   # more demand on D-1 (open)
    got = _simple_all(d2, oh, g, MON, 0)
    assert (got["tsb"] != base["tsb"]).all() and (got["avg7"] != base["avg7"]).all()
    # D-1 has the weekday of D+6 only: horizon 7 changes, horizons 1..6 do not
    assert (got["dow4"][:, 6] != base["dow4"][:, 6]).all()
    assert np.array_equal(got["dow4"][:, :6], base["dow4"][:, :6])
    # closing D-1 changes TSB and DOW4 (no observation) but not AVG7 (a calendar-day mean)
    o2 = oh.copy()
    o2[:, g - 1] = np.nan
    got = _simple_all(d2, o2, g, MON, 0)
    assert np.array_equal(got["avg7"], _simple_all(d2, oh, g, MON, 0)["avg7"])
    closed = _simple_all(daily, o2, g, MON, 0)            # the demand of a closed D-1 is not read by TSB / DOW4
    assert np.array_equal(got["tsb"], closed["tsb"]) and np.array_equal(got["dow4"], closed["dow4"])


def test_simple_never_read_before_their_window():
    K, G, g = 2, 150, 140                                 # D = MON + 140 days = a Monday
    daily, oh = np.full((K, G), 2.0), np.full((K, G), 8.0)
    base = _simple_all(daily, oh, g, MON, 20)
    d2, o2 = daily.copy(), oh.copy()
    d2[:, :g - 90], o2[:, :g - 90] = 500.0, np.nan       # before D-90 (scope), D-84 (DOW4) and D-7 (AVG7)
    d2[:, g - 84:g - 28:7] = 0.0                          # open Mondays older than the 4 newest ones
    d2[:, g - 90:g - 7] = np.where(np.arange(g - 90, g - 7) % 7 == 0, d2[:, g - 90:g - 7], 77.0)
    got = _simple_all(d2, o2, g, MON, 20)
    assert np.array_equal(got["scope"], base["scope"]) and np.array_equal(got["avg7"], base["avg7"])
    assert np.array_equal(got["dow4"][:, 0], base["dow4"][:, 0])
    # TSB: days before g_start are never read
    d3, o3 = daily.copy(), oh.copy()
    d3[:, :20], o3[:, :20] = 999.0, np.nan
    assert np.array_equal(simple.tsb(d3, simple.open_mask(o3), g, 20), simple.tsb(daily, simple.open_mask(oh), g, 20))


@pytest.mark.parametrize("t0", [1, 13, 57, 85, 150, 291])
def test_extras_never_read_column_t0_or_later(xf, t0):
    Y, dates = xf["Y"], xf["dates"]
    T = Y.shape[1]
    r = extras.robust(Y, t0)
    prof = extras.dayprof_profile(Y, dates, t0)
    tds = [dates[t0 - 1] + pd.Timedelta(days=h) for h in range(1, 8)]
    d = [extras.dayprof_columns(prof, td) for td in tds]
    for fill in (999.0, np.nan, -7.0, 0.0):
        Y2 = Y.copy()
        Y2[:, t0:] = fill
        assert np.array_equal(r, extras.robust(Y2, t0), equal_nan=True), (t0, fill)
        p2 = extras.dayprof_profile(Y2, dates, t0)
        assert all(np.array_equal(prof[k], p2[k], equal_nan=True) for k in prof), (t0, fill)
        for td, x in zip(tds, d):
            assert np.array_equal(x, extras.dayprof(Y2, dates, t0, td), equal_nan=True), (t0, fill, td)
    assert T > t0


def test_extras_read_column_t0_minus_1():
    S, T, t0 = 2, 120, 100
    ramp = np.arange(T, dtype=float)[None, :].repeat(S, axis=0)
    R2 = ramp.copy()
    R2[:, t0 - 1] = -50.0
    assert (extras.robust(R2, t0) != extras.robust(ramp, t0)).all()    # every ROBUST window ends at t0-1
    Y = np.ones((S, T))
    dates = pd.date_range(str(MON), periods=T, freq="D")
    Y2 = Y.copy()
    Y2[:, t0 - 1] = 50.0
    td = dates[t0 - 1] + pd.Timedelta(days=7)                          # same weekday as t0-1
    d, d2 = extras.dayprof(Y, dates, t0, td), extras.dayprof(Y2, dates, t0, td)
    j = extras.DAYPROF_NAMES.index
    assert (d2[:, j("dow_share_8w")] > d[:, j("dow_share_8w")]).all()
    assert (d2[:, j("same_dow_mean_4")] == (3 + 50) / 4).all()


def test_extras_never_read_before_their_windows():
    S, T, t0 = 2, 200, 180
    rng = np.random.default_rng(9)
    Y = rng.integers(0, 5, (S, T)).astype(float)
    dates = pd.date_range(str(MON), periods=T, freq="D")
    Y2 = Y.copy()
    Y2[:, :t0 - 84] = np.nan                              # older than the 84-column window and the last 4 weekdays
    for td in dates[t0:t0 + 7]:
        assert np.array_equal(extras.dayprof(Y, dates, t0, td), extras.dayprof(Y2, dates, t0, td), equal_nan=True)
    Y3 = Y.copy()
    Y3[:, :t0 - 56] = 999.0                               # older than the longest ROBUST window
    assert np.array_equal(extras.robust(Y, t0), extras.robust(Y3, t0), equal_nan=True)


# ------------------------------------------------------------------ NaN handling, closed keys
def test_simple_nan_demand_days():
    K, G, g = 1, 120, 112                                 # g = 112: D is a Monday (MON + 16 weeks)
    daily = np.full((K, G), 2.0)
    oh = np.full((K, G), 8.0)
    om = simple.open_mask(oh)
    nan_d = daily.copy()
    nan_d[0, g - 1] = np.nan
    zero_d = daily.copy()
    zero_d[0, g - 1] = 0.0
    # scope: a NaN day is never a sale
    only_nan = np.zeros((K, G))
    only_nan[0, g - 10] = np.nan
    assert not scope.scope_mask(only_nan, oh, g).any()
    # TSB: a NaN demand on an open day is an observation without demand (same as 0), the value stays finite
    assert np.isfinite(simple.tsb(nan_d, om, g, 0)).all()
    assert simple.tsb(nan_d, om, g, 0)[0] == simple.tsb(zero_d, om, g, 0)[0]
    # DOW4: a NaN open day is skipped like a closed day (horizon 7 = weekday of D-1 = Sunday)
    nan_d[0, g - 8] = 9.0                                 # previous Sunday
    zero_d[0, g - 8] = 9.0
    assert simple.dow4(nan_d, om, g, MON)[0, 6] == pytest.approx((9 + 2 + 2 + 2) / 4)
    assert simple.dow4(zero_d, om, g, MON)[0, 6] == pytest.approx((0 + 9 + 2 + 2) / 4)
    # AVG7: a NaN day in the 7-day window gives NaN, never a silent 0
    assert np.isnan(simple.avg7(nan_d, g)[0])


def test_all_closed_keys():
    K, G, g = 2, 120, 112
    daily = np.zeros((K, G))
    daily[:, g - 7:g] = [7, 0, 0, 0, 0, 0, 0]            # demand recorded on closed days
    oh = np.full((K, G), np.nan)
    oh[1, :] = 0.0                                        # rows with 0 h are closed too
    om = simple.open_mask(oh)
    assert not om.any()
    assert not scope.scope_mask(daily, oh, g).any()      # sold, but no open hour
    assert simple.tsb(daily, om, g, 0).tolist() == [0.0, 0.0]
    assert (simple.dow4(daily, om, g, MON) == 0).all()
    assert simple.avg7(daily, g).tolist() == [1.0, 1.0]   # calendar days, closed days included


def test_extras_nan_heavy_rows():
    T, t0 = 120, 112                                      # dates from a Monday: t0 is a Monday
    dates = pd.date_range(str(MON), periods=T, freq="D")
    Y = np.full((3, T), np.nan)
    Y[0, [t0 - 1, t0 - 3, t0 - 5]] = [1.0, 5.0, 3.0]     # 3 known values in the last 7
    Y[1, :] = 0.0                                         # known, all zero
    Y[2, :t0 - 28] = 4.0                                  # known only before the last 28 columns
    r = extras.robust(Y, t0)
    i = extras.ROBUST_NAMES.index
    assert r[0, i("med_7")] == 3.0 and r[0, i("p25_7")] == 2.0 and r[0, i("p75_7")] == 4.0
    assert r[0, i("med_56")] == 3.0 and r[0, i("tmean_28")] == 2.0      # drop ceil(0.3) = 1 highest (5)
    assert (r[1] == 0.0).all()
    assert np.isnan(r[2, :i("med_56")]).all() and r[2, i("med_56")] == 4.0
    assert np.isnan(r[2, i("tmean_28")]) and r[2, i("tmean_56")] == 4.0
    j = extras.DAYPROF_NAMES.index
    sun = extras.dayprof(Y, dates, t0, dates[t0 - 1] + pd.Timedelta(days=7))
    # zero total -> NaN shares; known zeros -> rate 0 and mean 0
    assert np.isnan(sun[1, [j("dow_share_8w"), j("dow_share_12w"), j("dom_share_12w")]]).all()
    assert sun[1, j("same_dow_mean_4")] == 0.0 and sun[1, j("dow_order_rate_12w")] == 0.0
    # row 2: the last 4 Sundays are unknown -> NaN even though older Sundays are known; rate on the known ones
    assert np.isnan(sun[2, j("same_dow_mean_4")]) and sun[2, j("dow_order_rate_12w")] == 1.0
    # row 0: one known Sunday (t0-1 = 1.0) among the last 4 Sundays
    assert sun[0, j("same_dow_mean_4")] == 1.0 and sun[0, j("dow_share_8w")] == pytest.approx(1 / 9)


# ------------------------------------------------------------------ boundaries, hand-computed values
def test_scope_boundaries():
    K, G, g = 7, 130, 120
    daily, oh = np.zeros((K, G)), np.full((K, G), np.nan)
    daily[:, 60] = 1.0
    oh[0, 60] = 1.0                                       # exactly 1.0 h -> in
    oh[1, 60:64] = 0.25                                   # 4 x 0.25 h = 1.0 -> in
    oh[2, 60], oh[2, 61] = 0.5, 0.49                      # 0.99 h -> out
    oh[3, g - 90] = 8.0                                   # hours on D-90 exactly -> counted
    daily[3, 60] = 0.0
    daily[3, g - 90] = 1.0                                # and the sale of D-90 -> in
    oh[4, g - 91] = 8.0                                   # hours on D-91 only -> out
    oh[5, 60], oh[5, 61] = 3.0, -5.0                      # negative hours count as 0 (not -5) -> in
    oh[6, g] = 8.0                                        # hours on D itself are not read -> out
    assert scope.scope_mask(daily, oh, g).tolist() == [True, True, False, True, False, True, False]
    daily2 = daily.copy()
    daily2[3, g - 90], daily2[3, g - 91] = 0.0, 5.0       # sale on D-91 only -> out
    assert not scope.scope_mask(daily2, oh, g)[3]


def test_tsb_28th_open_day_is_d_minus_1():
    G = 120
    daily = np.zeros((1, G))
    om = np.zeros((1, G), dtype=bool)
    opened = list(range(10, 94, 3))                       # 28 open days, every 3rd day; the 28th is day 91
    assert len(opened) == 28 and opened[-1] == 91
    om[0, opened] = True
    daily[0, opened[-7:]] = 4.0                           # 7 of 28 open days with demand 4, the 28th included
    daily[0, 11] = 100.0                                  # demand on a closed day: not an observation
    assert simple.tsb(daily, om, 91, 0)[0] == 0.0          # D = the 28th open day: only 27 read
    assert simple.tsb(daily, om, 92, 0)[0] == pytest.approx(0.25 * 4.0, abs=1e-12)   # p = 7/28, z = 4
    assert simple.tsb(daily, om, G, 0)[0] == pytest.approx(1.0, abs=1e-12)          # no later open day: frozen
    # a start after the first open day leaves fewer than 28 open days -> 0
    assert simple.tsb(daily, om, G, 11)[0] == 0.0


def test_tsb_updates_by_hand():
    G = 40
    daily = np.full((1, G), 2.0)
    om = np.zeros((1, G), dtype=bool)
    om[0, :28] = True                                     # start: p = 1, z = 2
    om[0, 28], daily[0, 28] = True, 4.0                   # p = 1, z = 2 + 0.1 (4 - 2) = 2.2
    om[0, 29], daily[0, 29] = True, 0.0                   # p = 0.9, z = 2.2
    daily[0, 30] = 80.0                                   # closed day: nothing moves
    assert simple.tsb(daily, om, 29, 0)[0] == pytest.approx(2.2, abs=1e-12)
    assert simple.tsb(daily, om, 31, 0)[0] == pytest.approx(0.9 * 2.2, abs=1e-12)
    assert simple.tsb(daily, om, 31, 0, alpha=0.5, beta=0.5)[0] == pytest.approx(0.5 * 3.0, abs=1e-12)
    neg = np.full((1, G), -3.0)
    assert simple.tsb(neg, om, 31, 0)[0] == 0.0           # no demand > 0 -> z = 0


def test_dow4_fewer_than_four_open_same_weekday_days():
    K, G, g = 4, 120, 112                                 # D = Monday; window D-84 .. D-1 has 12 Mondays
    daily = np.arange(G, dtype=float)[None, :].repeat(K, axis=0)
    om = np.zeros((K, G), dtype=bool)
    om[0, [105, 98]] = True                               # 2 open Mondays -> mean of 2
    om[1, [105, 98, 91]] = True                           # 3 -> mean of 3
    om[2, [105, 98, 91, 84, 77]] = True                   # 5 -> the newest 4
    om[3, [105, 28]] = True                               # Monday 28 = D-84: first day of the window, included
    daily[3, 105] = 0.0                                   # an open day with 0 demand counts as a known 0
    got = simple.dow4(daily, om, g, MON)
    assert got[:, 0].tolist() == pytest.approx([(105 + 98) / 2, (105 + 98 + 91) / 3, (105 + 98 + 91 + 84) / 4, 14.0])
    assert (got[:, 1:] == 0).all()                        # no open Tuesday .. Sunday -> 0
    om[3, [28, 105]], om[3, 21] = False, True             # only Monday 21 = D-91 open: outside the window -> 0
    assert simple.dow4(daily, om, g, MON)[3, 0] == 0.0


def test_dow4_horizon_weekday_follows_d():
    G, g = 120, 114                                       # D = MON + 114 days = a Wednesday
    assert (MON + timedelta(days=g)).weekday() == 2
    daily = np.zeros((1, G))
    om = np.ones((1, G), dtype=bool)
    for x in range(g - 84, g):
        daily[0, x] = (MON + timedelta(days=x)).weekday() + 1     # value = weekday + 1
    got = simple.dow4(daily, om, g, MON)[0]
    assert got.tolist() == [3.0, 4.0, 5.0, 6.0, 7.0, 1.0, 2.0]   # Wed, Thu, .., Tue


def test_avg7_by_hand():
    daily = np.zeros((3, 30))
    daily[0, 20:27] = [1, 2, 3, 4, 5, 6, 7]
    daily[1, 20:27] = [-10, 0, 0, 0, 0, 0, 3]             # negative mean -> clipped at 0
    daily[2, 19] = 70.0                                   # D-8: outside the window
    got = simple.avg7(daily, 27)
    assert got.tolist() == [4.0, 0.0, 0.0]
    assert simple.avg7(daily, 7).tolist() == [0.0, 0.0, 0.0]


def test_robust_by_hand():
    Y = np.arange(1, 57, dtype=float)[None, :]
    r = dict(zip(extras.ROBUST_NAMES, extras.robust(Y, 56)[0]))
    assert (r["med_7"], r["p25_7"], r["p75_7"]) == (53.0, 51.5, 54.5)
    assert (r["med_14"], r["p25_14"], r["p75_14"]) == (49.5, 46.25, 52.75)
    assert r["med_56"] == 28.5
    assert r["tmean_28"] == pytest.approx(41.0)           # 29..56 without the 3 highest -> 29..53
    assert r["tmean_56"] == pytest.approx(25.5)           # 1..56 without the 6 highest -> 1..50
    short = dict(zip(extras.ROBUST_NAMES, extras.robust(Y, 3)[0]))   # fewer columns than every window
    assert short["med_7"] == short["med_56"] == 2.0 and short["tmean_28"] == 1.5


def test_dayprof_by_hand():
    T = 84
    dates = pd.date_range(str(MON), periods=T, freq="D")
    Y = np.zeros((1, T))
    Y[0, ::7] = 1.0                                       # demand on Mondays only
    j = extras.DAYPROF_NAMES.index
    prof = extras.dayprof_profile(Y, dates, T)
    for td in pd.date_range(dates[-1] + pd.Timedelta(days=1), periods=14, freq="D"):
        got = extras.dayprof_columns(prof, td)[0]
        mon = td.dayofweek == 0
        b = extras.bucket(td.day)
        dom = sum(1 for x in dates[::7] if extras.bucket(x.day) == b) / 12
        assert got[j("dow_share_8w")] == got[j("dow_share_12w")] == (1.0 if mon else 0.0)
        assert got[j("same_dow_mean_4")] == got[j("dow_order_rate_12w")] == (1.0 if mon else 0.0)
        assert got[j("dom_share_12w")] == pytest.approx(dom)
    assert [extras.bucket(d) for d in (1, 5, 6, 25, 26, 31)] == [0, 0, 1, 4, 5, 5]
