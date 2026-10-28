"""1.3.1 "LightGBM chot" (C3-A1): the agreed formulas, written BEFORE the code (test-first).

Authoritative rules: docs/ke_hoach_lgbm_chot.md section 6.3 (B3 published quantity, B7 groups A / B / C) and section 6.4
(B9 accuracy categories and tables). Pure functions on synthetic arrays / frames only: no DB, no network.
The modules are imported inside each test so that every rule reports on its own until its task (T2 / T3) lands.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest


def _published_qty():
    from app.ml.daily_refresh import published_qty
    return published_qty


def _sg():
    from app.ml import sku_group
    return sku_group


def _ar():
    from app.ml import accuracy_report
    return accuracy_report


# ------------------------------------------------------------------ B3 published quantity (plan 6.3)
# v = round(value, 6); 0 where v < threshold, ceil(v) elsewhere
@pytest.mark.parametrize("value, expected", [
    (0.19, 0), (0.2, 1), (1.000001, 2), (3.0, 3),            # the four owner cases
    (0.0, 0),
    (0.1999999, 1),        # rounds to 0.2 at 6 decimals -> not below the threshold -> ceil 1
    (0.19999949, 0),       # rounds to 0.199999 -> below the threshold
    (2.0000004, 2),        # rounds to 2.0 -> ceil 2 (floating noise never adds a unit)
    (2.0000006, 3),        # rounds to 2.000001 -> ceil 3
    (12.3, 13),
])
def test_published_qty_threshold_0_2(value, expected):
    out = _published_qty()(np.array([value]), 0.2)
    assert out.tolist() == [expected]


@pytest.mark.parametrize("threshold, values, expected", [
    (0.5, [0.45, 0.5, 0.49999949, 0.4999996, 1.2], [0, 1, 0, 1, 2]),
    (0.0, [0.0, 0.0000004, 0.0000006, 0.3], [0, 0, 1, 1]),       # threshold 0: plain ROUNDUP of the 6-decimal value
    (1.0, [0.9999, 0.9999996, 1.0, 1.2], [0, 1, 1, 2]),
])
def test_published_qty_respects_the_threshold(threshold, values, expected):
    assert _published_qty()(np.array(values), threshold).tolist() == expected


def test_published_qty_keeps_the_shape_and_returns_int64():
    raw = np.array([[0.19, 0.2, 1.000001], [3.0, 0.0, 7.5]])        # S x H
    out = _published_qty()(raw, 0.2)
    assert isinstance(out, np.ndarray)
    assert out.shape == (2, 3)
    assert out.dtype == np.int64
    assert out.tolist() == [[0, 1, 2], [3, 0, 8]]
    assert raw.tolist() == [[0.19, 0.2, 1.000001], [3.0, 0.0, 7.5]]  # the raw (float) values stay untouched


def test_published_qty_empty_input():
    out = _published_qty()(np.zeros((0, 7)), 0.2)
    assert out.shape == (0, 7) and out.dtype == np.int64


@pytest.mark.parametrize("raw", [np.array([1.0, np.nan]), np.array([[0.5, 2.0], [np.nan, 1.0]])])
def test_published_qty_refuses_missing_values(raw):
    # a missing raw value is never published as 0 (or as anything else)
    with pytest.raises(ValueError):
        _published_qty()(raw, 0.2)


# ------------------------------------------------------------------ B7 groups A / B / C (plan 6.3)
WS, WE = "2026-07-01", "2026-09-28"      # 90 calendar days ending at D-1 of 2026-09-29
OUT_COLS = ["fc_code", "sku_code", "n_open_days", "qty", "avg_per_open_day", "zero_days", "zero_share", "group_code"]


def test_group_codes_and_constants():
    sg = _sg()
    assert (sg.GROUP_A, sg.GROUP_B, sg.GROUP_C) == ("A", "B", "C")
    assert sg.WINDOW_DAYS == 90
    assert sg.MIN_OPEN_DAYS == 14
    assert (date.fromisoformat(WE) - date.fromisoformat(WS)).days + 1 == sg.WINDOW_DAYS


@pytest.mark.parametrize("n, avg, zero_share, group", [
    (30, 20.01, 0.20, "A"),     # avg > 20 and zero share <= 0.20
    (30, 20.0, 0.0, "B"),       # A needs avg strictly above 20
    (30, 25.0, 0.21, "B"),      # A needs zero share <= 0.20; avg too high for C
    (30, 5.0, 0.21, "C"),       # avg <= 5 and zero share > 0.20
    (30, 5.0, 0.20, "B"),       # C needs zero share strictly above 0.20
    (30, 5.01, 0.9, "B"),       # C needs avg <= 5
    (30, 0.0, 1.0, "C"),
    (30, 10.0, 0.0, "B"),       # the middle band
    (13, 50.0, 0.0, "B"),       # fewer than 14 open days -> B whatever the values
    (13, 1.0, 0.9, "B"),
    (14, 50.0, 0.0, "A"),       # 14 open days are enough
    (14, 1.0, 0.9, "C"),
])
def test_classify_boundaries(n, avg, zero_share, group):
    out = _sg().classify(np.array([n]), np.array([avg]), np.array([zero_share]))
    assert list(out) == [group]


def test_classify_is_element_wise():
    out = _sg().classify(np.array([30, 30, 13]), np.array([21.0, 1.0, 50.0]), np.array([0.1, 0.5, 0.0]))
    assert list(out) == ["A", "C", "B"]


def _rows(fc, sku, demands, *, start="2026-08-01", hours=8.0):
    """One row per consecutive day from `start`; a NaN demand = open day without a demand row."""
    d0 = date.fromisoformat(start)
    hs = hours if isinstance(hours, list) else [hours] * len(demands)
    return [{"fc_code": fc, "sku_code": sku, "date": (d0 + timedelta(days=i)).isoformat(), "demand": q, "hours": h}
            for i, (q, h) in enumerate(zip(demands, hs))]


def _metrics(rows, ws=WS, we=WE):
    out = _sg().compute_metrics(pd.DataFrame(rows), ws, we)
    return {(r.fc_code, r.sku_code): r for r in out.itertuples(index=False)}, out


def test_compute_metrics_columns_and_values():
    # 20 open days: 16 x 30 + 4 x 0 -> qty 480, avg 24, zero 4 / 20 = 0.20 -> A
    by, out = _metrics(_rows("FC1", "S1", [30.0] * 16 + [0.0] * 4))
    assert list(out.columns) == OUT_COLS
    assert len(out) == 1
    r = by[("FC1", "S1")]
    assert (r.n_open_days, r.zero_days) == (20, 4)
    assert r.qty == pytest.approx(480.0)
    assert r.avg_per_open_day == pytest.approx(24.0)
    assert r.zero_share == pytest.approx(0.20)
    assert r.group_code == "A"


@pytest.mark.parametrize("demands, group", [
    ([20.0] * 20, "B"),                               # avg exactly 20 -> not A
    ([20.0] * 19 + [21.0], "A"),                      # avg 20.05, no zero day
    ([32.0] * 15 + [0.0] * 5, "B"),                   # avg 24 but zero share 0.25
    ([7.0] * 10 + [6.0] * 5 + [0.0] * 5, "C"),        # avg exactly 5, zero share 0.25
    ([5.0] * 16 + [0.0] * 4, "B"),                    # avg 4, zero share exactly 0.20 -> not C
    ([10.0] * 9 + [11.0] + [0.0] * 10, "B"),          # avg 5.05, zero share 0.5
    ([0.0] * 20, "C"),                                # avg 0, zero share 1
])
def test_compute_metrics_group_boundaries(demands, group):
    by, _ = _metrics(_rows("FC1", "S1", demands))
    assert by[("FC1", "S1")].group_code == group


def test_fewer_than_14_open_days_is_b():
    by, _ = _metrics(_rows("FC1", "S13", [100.0] * 13) + _rows("FC1", "S14", [100.0] * 14)
                     + _rows("FC1", "Z13", [0.0] * 13))
    assert by[("FC1", "S13")].n_open_days == 13
    assert by[("FC1", "S13")].avg_per_open_day == pytest.approx(100.0)
    assert by[("FC1", "S13")].group_code == "B"
    assert by[("FC1", "S14")].group_code == "A"
    assert by[("FC1", "Z13")].group_code == "B"          # 13 zero days are not C either


def test_closed_days_are_excluded_even_with_demand():
    # 14 open days x 30; then hours 0 (one of them even sells 1000), negative and NaN hours: all closed
    demands = [30.0] * 14 + [0.0] * 4 + [1000.0] + [0.0] * 3 + [0.0] * 5
    hours = [8.0] * 14 + [0.0] * 5 + [-1.0] * 3 + [np.nan] * 5
    by, _ = _metrics(_rows("FC1", "S1", demands, hours=hours))
    r = by[("FC1", "S1")]
    assert (r.n_open_days, r.zero_days) == (14, 0)
    assert r.qty == pytest.approx(420.0)
    assert r.group_code == "A"


def test_open_day_without_demand_counts_as_zero_demand():
    # 20 open days: 16 x 30 + 4 open days without a demand row (NaN) -> 4 zero days, qty 480
    by, _ = _metrics(_rows("FC1", "S1", [30.0] * 16 + [np.nan] * 4))
    r = by[("FC1", "S1")]
    assert (r.n_open_days, r.zero_days) == (20, 4)
    assert r.qty == pytest.approx(480.0)
    assert r.avg_per_open_day == pytest.approx(24.0)
    assert r.zero_share == pytest.approx(0.20)
    assert r.group_code == "A"


def test_days_outside_the_window_are_ignored_both_bounds_inclusive():
    ws, we = "2026-08-10", "2026-08-23"          # 14 days
    # 2026-08-05 .. 2026-08-28: 5 days before (zero), 14 inside (30), 5 after (zero)
    rows = _rows("FC1", "S1", [0.0] * 5 + [30.0] * 14 + [0.0] * 5, start="2026-08-05")
    by, _ = _metrics(rows, ws, we)
    r = by[("FC1", "S1")]
    assert (r.n_open_days, r.zero_days, r.group_code) == (14, 0, "A")
    assert r.qty == pytest.approx(420.0)
    by_l, _ = _metrics(rows, "2026-08-11", we)
    by_r, _ = _metrics(rows, ws, "2026-08-22")
    assert (by_l[("FC1", "S1")].n_open_days, by_l[("FC1", "S1")].group_code) == (13, "B")
    assert (by_r[("FC1", "S1")].n_open_days, by_r[("FC1", "S1")].group_code) == (13, "B")


def test_series_without_open_day_is_not_returned():
    rows = (_rows("FC1", "S1", [30.0] * 14)
            + _rows("FC1", "NEVER_OPEN", [30.0] * 14, hours=0.0)
            + _rows("FC1", "BEFORE", [30.0] * 14, start="2026-06-01"))       # open, but before the window
    by, out = _metrics(rows)
    assert set(by) == {("FC1", "S1")}
    assert len(out) == 1


def test_same_sku_in_two_fcs_are_two_series():
    by, out = _metrics(_rows("FC1", "S1", [30.0] * 20) + _rows("FC2", "S1", [0.0] * 10 + [1.0] * 10))
    assert len(out) == 2
    assert by[("FC1", "S1")].group_code == "A"
    assert by[("FC2", "S1")].group_code == "C"            # avg 0.5, zero share 0.5
    assert by[("FC2", "S1")].qty == pytest.approx(10.0)


def test_duplicated_series_day_is_refused():
    rows = _rows("FC1", "S1", [30.0] * 20)
    rows.append(dict(rows[3]))                              # the same series and open day twice
    with pytest.raises(ValueError):
        _sg().compute_metrics(pd.DataFrame(rows), WS, WE)


def test_compute_metrics_empty_frame():
    out = _sg().compute_metrics(pd.DataFrame(columns=["fc_code", "sku_code", "date", "demand", "hours"]), WS, WE)
    assert len(out) == 0
    assert list(out.columns) == OUT_COLS


# ------------------------------------------------------------------ B9 categories (plan 6.4)
# dev = final - demand; tol = 1 for group C, 3 otherwise (missing group = B);
# DUNG when |dev| <= tol or (demand > 0 and |dev| / demand <= 0.20); otherwise ratio = |dev| / demand (inf when
# demand = 0): IT when <= 0.50, NHIEU above; DU when dev > 0, THIEU when dev < 0
CELL_CASES = [
    (10, 13, "A", "DUNG"),          # |dev| 3 <= 3
    (17, 13, "B", "DU_IT"),         # |dev| 4 > 3, 4 / 13 = 30.8 % -> above 20 %, at most 50 %
    (120, 100, "A", "DUNG"),        # exactly 20 %
    (125, 100, "A", "DU_IT"),
    (150, 100, "A", "DU_IT"),       # exactly 50 % is IT
    (151, 100, "A", "DU_NHIEU"),
    (70, 100, "B", "THIEU_IT"),
    (49, 100, "B", "THIEU_NHIEU"),
    (0, 0, "A", "DUNG"),
    (3, 0, "A", "DUNG"),            # within the unit tolerance
    (4, 0, "A", "DU_NHIEU"),        # demand 0 beyond the tolerance: ratio infinite -> NHIEU
    (1, 0, "C", "DUNG"),
    (2, 0, "C", "DU_NHIEU"),
    (3, 5, "C", "THIEU_IT"),        # |dev| 2 > 1, 40 %
    (4, 5, "C", "DUNG"),            # |dev| 1 <= 1
    (0, 1, "C", "DUNG"),
    (0, 2, "C", "THIEU_NHIEU"),     # 100 %
    (5, 8, None, "DUNG"),           # missing group behaves as B: |dev| 3 <= 3
    (5, 8, "C", "THIEU_IT"),        # the same cell in group C: |dev| 3 > 1, 37.5 %
    (106, 100, "C", "DUNG"),        # |dev| 6 > 1 but 6 % <= 20 %
    (130, 100, "C", "DU_IT"),
]


def test_categories_constant():
    assert _ar().CATEGORIES == ("DUNG", "DU_NHIEU", "DU_IT", "THIEU_NHIEU", "THIEU_IT")


@pytest.mark.parametrize("final, demand, group, expected", CELL_CASES)
def test_classify_cells_single(final, demand, group, expected):
    out = _ar().classify_cells(np.array([final]), np.array([float(demand)]), np.array([group], dtype=object))
    assert list(out) == [expected]


def test_classify_cells_vectorised():
    final = np.array([c[0] for c in CELL_CASES])
    demand = np.array([float(c[1]) for c in CELL_CASES])
    group = np.array([c[2] for c in CELL_CASES], dtype=object)
    out = _ar().classify_cells(final, demand, group)
    assert isinstance(out, np.ndarray)
    assert out.shape == (len(CELL_CASES),)
    assert list(out) == [c[3] for c in CELL_CASES]


def test_classify_cells_empty():
    out = _ar().classify_cells(np.array([], dtype=np.int64), np.array([], dtype=float), np.array([], dtype=object))
    assert len(out) == 0


# ------------------------------------------------------------------ B9 tables (plan 6.4)
# (forecast_date, horizon, fc, sku, group, final, demand, category by the rule above); target = forecast + h - 1.
# Forecast days 29/09, 30/09, 01/10 x horizons 1..2 -> targets in September and October; C1 is closed on 02/10 (its
# cell is filtered out before build_tables, so that slot has 3 cells instead of 4).
CELLS = [
    ("2026-09-29", 1, "F1", "A1", "A", 100, 100, "DUNG"),
    ("2026-09-29", 2, "F1", "A1", "A", 125, 100, "DU_IT"),
    ("2026-09-30", 1, "F1", "A1", "A", 160, 100, "DU_NHIEU"),
    ("2026-09-30", 2, "F1", "A1", "A", 70, 100, "THIEU_IT"),
    ("2026-10-01", 1, "F1", "A1", "A", 40, 100, "THIEU_NHIEU"),
    ("2026-10-01", 2, "F1", "A1", "A", 110, 100, "DUNG"),
    ("2026-09-29", 1, "F1", "A2", "A", 12, 10, "DUNG"),
    ("2026-09-29", 2, "F1", "A2", "A", 10, 10, "DUNG"),
    ("2026-09-30", 1, "F1", "A2", "A", 20, 10, "DU_NHIEU"),
    ("2026-09-30", 2, "F1", "A2", "A", 10, 10, "DUNG"),
    ("2026-10-01", 1, "F1", "A2", "A", 10, 10, "DUNG"),
    ("2026-10-01", 2, "F1", "A2", "A", 6, 10, "THIEU_IT"),
    ("2026-09-29", 1, "F2", "B1", "B", 0, 0, "DUNG"),
    ("2026-09-29", 2, "F2", "B1", "B", 5, 0, "DU_NHIEU"),
    ("2026-09-30", 1, "F2", "B1", "B", 2, 5, "DUNG"),
    ("2026-09-30", 2, "F2", "B1", "B", 0, 10, "THIEU_NHIEU"),
    ("2026-10-01", 1, "F2", "B1", "B", 8, 5, "DUNG"),
    ("2026-10-01", 2, "F2", "B1", "B", 14, 10, "DU_IT"),
    ("2026-09-29", 1, "F1", "C1", "C", 1, 0, "DUNG"),
    ("2026-09-29", 2, "F1", "C1", "C", 0, 2, "THIEU_NHIEU"),
    ("2026-09-30", 1, "F1", "C1", "C", 3, 2, "DUNG"),
    ("2026-09-30", 2, "F1", "C1", "C", 2, 0, "DU_NHIEU"),
    ("2026-10-01", 1, "F1", "C1", "C", 4, 3, "DUNG"),
]
# horizon 8 (target 30/09): outside both views (D1 = horizon 1, D7 = horizons 1..7), must change nothing
EXTRA_H8 = ("2026-09-23", 8, "F1", "A1", "A", 999, 0)

# hand-computed: (view, period) -> (slots, {group: ({category: (cells, sum |dev|)}, sum demand)})
EXPECTED = {
    ("D1", "2026-09"): (2, {"A": ({"DUNG": (2, 2), "DU_NHIEU": (2, 70)}, 220),
                            "B": ({"DUNG": (2, 3)}, 5),
                            "C": ({"DUNG": (2, 2)}, 2)}),
    ("D1", "2026-10"): (1, {"A": ({"DUNG": (1, 0), "THIEU_NHIEU": (1, 60)}, 110),
                            "B": ({"DUNG": (1, 3)}, 5),
                            "C": ({"DUNG": (1, 1)}, 3)}),
    ("D1", "TOTAL"): (3, {"A": ({"DUNG": (3, 2), "DU_NHIEU": (2, 70), "THIEU_NHIEU": (1, 60)}, 330),
                          "B": ({"DUNG": (3, 6)}, 10),
                          "C": ({"DUNG": (3, 3)}, 5)}),
    ("D7", "2026-09"): (3, {"A": ({"DUNG": (3, 2), "DU_IT": (1, 25), "DU_NHIEU": (2, 70)}, 330),
                            "B": ({"DUNG": (2, 3), "DU_NHIEU": (1, 5)}, 5),
                            "C": ({"DUNG": (2, 2), "THIEU_NHIEU": (1, 2)}, 4)}),
    ("D7", "2026-10"): (3, {"A": ({"DUNG": (3, 10), "THIEU_IT": (2, 34), "THIEU_NHIEU": (1, 60)}, 330),
                            "B": ({"DUNG": (1, 3), "DU_IT": (1, 4), "THIEU_NHIEU": (1, 10)}, 25),
                            "C": ({"DUNG": (1, 1), "DU_NHIEU": (1, 2)}, 3)}),
    ("D7", "TOTAL"): (6, {"A": ({"DUNG": (6, 12), "DU_IT": (1, 25), "DU_NHIEU": (2, 70), "THIEU_IT": (2, 34),
                                 "THIEU_NHIEU": (1, 60)}, 660),
                          "B": ({"DUNG": (3, 6), "DU_IT": (1, 4), "DU_NHIEU": (1, 5), "THIEU_NHIEU": (1, 10)}, 30),
                          "C": ({"DUNG": (3, 3), "DU_NHIEU": (1, 2), "THIEU_NHIEU": (1, 2)}, 7)}),
}
CATS = ("DUNG", "DU_NHIEU", "DU_IT", "THIEU_NHIEU", "THIEU_IT")
COLS = ("A", "B", "C", "TOTAL")


def _frame(rows):
    out = []
    for fd, h, fc, sku, grp, final, dem, *_ in rows:
        td = (date.fromisoformat(fd) + timedelta(days=h - 1)).isoformat()
        out.append({"forecast_date": fd, "target_date": td, "horizon": h, "fc_code": fc, "sku_code": sku,
                    "group_code": grp, "final_qty": final, "demand": float(dem)})
    return pd.DataFrame(out)


def _with_total(groups: dict) -> dict:
    """TOTAL column = the three groups pooled (cells, |dev| and demand summed)."""
    cats, dem = {}, 0
    for g in ("A", "B", "C"):
        gc, gd = groups[g]
        dem += gd
        for c, (n, dv) in gc.items():
            a = cats.get(c, (0, 0))
            cats[c] = (a[0] + n, a[1] + dv)
    return {**groups, "TOTAL": (cats, dem)}


def test_the_hand_made_cells_follow_the_category_rule():
    df = _frame(CELLS)
    out = _ar().classify_cells(df["final_qty"].to_numpy(), df["demand"].to_numpy(), df["group_code"].to_numpy())
    assert list(out) == [c[7] for c in CELLS]


def test_the_hand_totals_are_the_sum_of_the_months():
    # consistency of the expected numbers themselves (TOTAL period = September + October)
    for view in ("D1", "D7"):
        s_sep, g_sep = EXPECTED[(view, "2026-09")]
        s_oct, g_oct = EXPECTED[(view, "2026-10")]
        s_tot, g_tot = EXPECTED[(view, "TOTAL")]
        assert s_tot == s_sep + s_oct
        for g in ("A", "B", "C"):
            assert g_tot[g][1] == g_sep[g][1] + g_oct[g][1]
            for c in CATS:
                a, b, t = (x[g][0].get(c, (0, 0)) for x in (g_sep, g_oct, g_tot))
                assert t == (a[0] + b[0], a[1] + b[1]), (view, g, c)


@pytest.mark.parametrize("with_h8", [False, True])
def test_build_tables_views_periods_and_numbers(with_h8):
    rows = CELLS + ([EXTRA_H8] if with_h8 else [])
    tables = _ar().build_tables(_frame(rows))
    assert set(tables) == {"D1", "D7"}
    for view in ("D1", "D7"):
        by_period = {e["period"]: e for e in tables[view]}
        assert len(by_period) == len(tables[view])
        assert set(by_period) == {"2026-09", "2026-10", "TOTAL"}
        for period, e in by_period.items():
            slots, groups = EXPECTED[(view, period)]
            groups = _with_total(groups)
            where = (view, period)
            assert e["slots"] == slots, where
            assert set(e["sku_per_day"]) == set(CATS) and set(e["sku_share"]) == set(CATS)
            assert set(e["qty_dev"]) == set(CATS) | {"TOTAL"} and set(e["qty_dev_share"]) == set(CATS) | {"TOTAL"}
            assert set(e["demand"]) == set(COLS)
            for col in COLS:
                cats, dem = groups[col]
                n_col = sum(n for n, _ in cats.values())
                dev_col = sum(dv for _, dv in cats.values())
                assert e["demand"][col] == pytest.approx(dem), (where, col)
                assert e["qty_dev"]["TOTAL"][col] == pytest.approx(dev_col), (where, col)
                assert e["qty_dev_share"]["TOTAL"][col] == pytest.approx(dev_col / dem), (where, col)
                for c in CATS:
                    n, dv = cats.get(c, (0, 0))
                    assert e["sku_per_day"][c][col] == pytest.approx(n / slots), (where, c, col)
                    assert e["sku_share"][c][col] == pytest.approx(n / n_col), (where, c, col)
                    assert e["qty_dev"][c][col] == pytest.approx(dv), (where, c, col)
                    assert e["qty_dev_share"][c][col] == pytest.approx(dv / dem), (where, c, col)
                assert sum(e["sku_share"][c][col] for c in CATS) == pytest.approx(1.0), (where, col)


def test_build_tables_spot_values():
    # a few numbers written out in full (the general test above derives the ratios from the hand counts)
    t = _ar().build_tables(_frame(CELLS))
    d1 = {e["period"]: e for e in t["D1"]}
    d7 = {e["period"]: e for e in t["D7"]}
    assert d1["2026-09"]["sku_per_day"]["DUNG"]["TOTAL"] == pytest.approx(3.0)        # 6 cells / 2 slots
    assert d1["2026-09"]["sku_share"]["DU_NHIEU"]["A"] == pytest.approx(0.5)
    assert d1["2026-09"]["qty_dev_share"]["DU_NHIEU"]["TOTAL"] == pytest.approx(70 / 227)
    assert d7["2026-10"]["sku_per_day"]["DUNG"]["C"] == pytest.approx(1 / 3)           # C1 closed on 02/10
    assert d7["2026-10"]["sku_share"]["DUNG"]["C"] == pytest.approx(0.5)
    assert d7["TOTAL"]["slots"] == 6 and d1["TOTAL"]["slots"] == 3
    assert d7["TOTAL"]["qty_dev"]["TOTAL"]["TOTAL"] == pytest.approx(233)              # A 201 + B 25 + C 7
    assert d7["TOTAL"]["demand"]["TOTAL"] == pytest.approx(697)
    assert d7["TOTAL"]["qty_dev_share"]["TOTAL"]["A"] == pytest.approx(201 / 660)
    assert d7["TOTAL"]["sku_share"]["DUNG"]["TOTAL"] == pytest.approx(12 / 23)
