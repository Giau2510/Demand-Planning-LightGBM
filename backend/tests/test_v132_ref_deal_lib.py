"""1.3.2 (G3-T2a): checks of the reference helper tests/ref_deal_lib.py against hand-computed values.

ref_deal_lib is the copy of the preregistered formulas (reports/backtest-2025-deal-20261030/code/deal_lib.py) that
tests/test_v132_extra_features.py compares app.ml.extra_features with; these tests pin it independently, on the tiny
hand case whose every value is worked out in ref_deal_lib.HAND_* (no import of the application module, so they run
before the implementation exists). Synthetic data only; no DB, no network.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import ref_deal_lib as rl

RTOL = 1e-6          # the reference is float64 cast once to float32; hand values are float64 literals


def _snap(case=None, **kw):
    case = case or rl.hand_case()
    return case, rl.ref_snapshot(case, **kw)


def _close(actual, expected):
    np.testing.assert_allclose(np.asarray(actual, dtype=float), np.asarray(expected, dtype=float), rtol=RTOL, atol=0,
                               equal_nan=True)


def test_ref_hand_same_period_last_year_at_D():
    case, s = _snap()
    out = s.ly_features(s.rows_of(case["keys"]), case["D"])
    assert out.dtype == np.float32 and out.shape == (len(case["keys"]), 4)
    for i, k in enumerate(case["keys"]):
        _close(out[i], rl.hand_ly(k))
    assert out[case["keys"].index(rl.SA)].tolist() == pytest.approx([14.0, 5.0, 1.5, 0.5])


def test_ref_hand_same_period_last_year_windows_before_day0():
    case, s = _snap()
    rows = s.rows_of(case["keys"])
    ia, ib = case["keys"].index(rl.SA), case["keys"].index(rl.SB)
    # D = 2025-12-31 (day index 364): only D-364 = day0 is inside; the row of 2024-12-31 (99) is never read
    out = s.ly_features(rows, date(2025, 12, 31))
    _close(out[ia], [3.0, np.nan, np.nan, np.nan])
    _close(out[ib], [0.0, np.nan, np.nan, np.nan])
    # D = 2026-02-05 (index 400): the 28 days of ly_mean_28 = 2025-01-10 .. 02-06 hold 1000 + 28; ly_trend needs D-419
    out = s.ly_features(rows, date(2026, 2, 5))
    _close(out[ia], [0.0, 0.0, 1028 / 28, np.nan])
    _close(out[ib], [0.0, 0.0, 0.0, np.nan])
    # D = 2025-12-30 (index 363): every window starts before day0
    assert np.isnan(s.ly_features(rows, date(2025, 12, 30))).all()


def test_ref_hand_deal_block_at_D():
    case, s = _snap()
    out = s.deal_features(s.rows_of(case["keys"]), case["D"])
    assert out.dtype == np.float32 and out.shape == (len(case["keys"]), 12)
    for i, k in enumerate(case["keys"]):
        _close(out[i], rl.HAND_DEAL[k])


def test_ref_hand_groups_at_first_day_of_month():
    case, s = _snap()
    g = dict(zip(s.keys, s.groups_at(case["D"]).tolist()))
    assert {k: g[k] for k in (rl.SA, rl.SG, rl.SH, rl.SJ, rl.SK, rl.SL, rl.SM, rl.SN, rl.ST, rl.SU)} == {
        rl.SA: 1, rl.SG: 1, rl.SH: 2, rl.SJ: 2, rl.SK: 0, rl.SL: -1, rl.SM: 1, rl.SN: 1, rl.ST: 0, rl.SU: 1}
    assert s.groups_at(date(2026, 3, 31)).tolist() == s.groups_at(date(2026, 3, 1)).tolist()


def test_ref_hand_active_on_target_days():
    case, s = _snap()
    rows = s.rows_of(case["keys"])
    for day, on in rl.HAND_ACTIVE.items():
        out = s.active_on(rows, day)
        assert out.dtype == np.int8
        assert {k for k, v in zip(case["keys"], out.tolist()) if v} == on, day


def test_ref_hand_negative_controls():
    case, s = _snap()
    D, ia = case["D"], case["keys"].index(rl.SA)
    rows = s.rows_of(case["keys"])
    ly0, deal0 = s.ly_features(rows, D), s.deal_features(rows, D)
    dem = case["demand"]

    def with_qty(day, qty):
        d = dem.copy()
        d.loc[(d["sku_id"] == "SA") & (d["order_date"] == day.isoformat()), "qty"] = qty
        return d
    # D-364: 14 -> 15 changes the three windows that hold it and the trend
    s1 = rl.ref_snapshot(case, demand=with_qty(D - timedelta(days=364), 15.0))
    _close(s1.ly_features(rows, D)[ia], [15.0, 36 / 7, 43 / 28, (43 / 28) / 3.0])
    # D-392: 56 -> 57 changes the trend only
    s2 = rl.ref_snapshot(case, demand=with_qty(D - timedelta(days=392), 57.0))
    _close(s2.ly_features(rows, D)[ia], [14.0, 5.0, 1.5, 1.5 / (85 / 28)])
    # D-1: the line of D1 4 -> 7 changes the used quantities of SA, nothing else
    ln = case["deal_lines"].copy()
    ln.loc[(ln["sku_id"] == "SA") & (ln["fc_id"] == "F1") & (ln["deal_code"] == "D1")
           & (ln["order_date"] == "2026-03-09"), "qty"] = 7.0
    s3 = rl.ref_snapshot(case, deal_lines=ln)
    deal3 = s3.deal_features(rows, D)
    exp = list(rl.HAND_DEAL[rl.SA])
    exp[4], exp[5], exp[6], exp[7] = 23.0, 1 - 23 / 150, 13.0, 18.0
    _close(deal3[ia], exp)
    np.testing.assert_array_equal(np.delete(deal3, ia, axis=0), np.delete(deal0, ia, axis=0))
    np.testing.assert_array_equal(s3.ly_features(rows, D), ly0)


def test_ref_cannot_take_duplicate_deal_keys_and_the_app_rule_picks_one_row():
    case = rl.hand_case()
    dup = pd.concat([case["deals"], case["deals"].iloc[[0]]], ignore_index=True)
    with pytest.raises(Exception):                       # deal_lib's line join needs unique deal keys
        rl.ref_snapshot(case, deals=dup)
    d = pd.DataFrame([
        ("K", "S1", "F1", "2026-03-01 00:00:00", "2026-03-10 00:00:00", 1.0, 0.0),
        ("K", "S1", "F1", "2026-03-01 00:00:00", "2026-03-20 00:00:00", 2.0, 0.0),   # latest end_time -> kept
        ("K", "S1", "F1", "2026-03-01 00:00:00", "2026-03-15 00:00:00", 3.0, 0.0),
        ("K", "S1", "F2", "2026-03-01 00:00:00", "2026-03-05 00:00:00", 4.0, 0.0),   # another key
        ("M", "S1", "F1", "2026-03-01 00:00:00", "2026-03-09 00:00:00", 5.0, 0.0),
        ("M", "S1", "F1", "2026-03-02 00:00:00", "2026-03-09 00:00:00", 6.0, 0.0),   # same end_time, last -> kept
    ], columns=rl.DEAL_COLS)
    assert rl.dedupe_like_app(d)["max_quantity"].tolist() == [2.0, 4.0, 6.0]


@pytest.mark.parametrize("seed", [11, 12])
def test_random_case_exercises_every_branch(seed):
    # the comparison of tests/test_v132_extra_features.py is only as good as the cases it meets
    case = rl.random_case(seed)
    s = rl.ref_snapshot(case)
    rows = s.rows_of(case["universe"])
    assert (rows >= 0).all() and s.keys == case["universe"]
    assert set(s.groups_at(date(2026, 3, 1)).tolist()) == {-1, 0, 1, 2}
    assert not s.deals["valid"].all()                                    # ready > end
    assert s.deals["maxq"].isna().any() and (s.deals["maxq"] == 0).any()
    assert s.line_info["matched"] < s.line_info["lines"]                  # unknown codes / wrong FC
    origins = [date(2026, 2, 28), date(2026, 3, 1), date(2026, 3, 17), date(2026, 4, 1)]
    f = np.vstack([s.deal_features(rows, o) for o in origins])
    assert f[:, 0].sum() >= 20 and (f[:, 8] >= 2).any()                 # active and overlapping deals
    assert (f[:, 5] < 0).any() and (f[:, 3] == 0).any()                 # used above max; max 0 / NaN only
    for j in (1, 2, 4, 6, 7, 9, 10, 11):
        assert (np.nan_to_num(f[:, j]) > 0).any(), j
    assert np.isnan(s.ly_features(rows, date(2025, 12, 15))).all()
    ly = s.ly_features(rows, date(2026, 2, 10))
    assert np.isnan(ly[:, 3]).all() and not np.isnan(ly[:, :3]).any()
    ly = s.ly_features(rows, date(2026, 3, 17))
    assert not np.isnan(ly).any() and (ly[:, 0] > 0).any() and (ly[:, 3] == 1).any() and (ly[:, 3] != 1).any()
