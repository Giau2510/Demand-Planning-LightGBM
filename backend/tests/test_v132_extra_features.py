"""1.3.2 (G3-T2a): specification of the extra model features, written BEFORE the code (test-first).

Release 1.3.2 adds 4 same-period-last-year features (E1) and 12 deal features (E2) at the forecast origin of the DIRECT
model (docs/hoc_lai_2025_deal_20261030.md sections 1.2-1.4). Authoritative formulas: PREREGISTRATION.md (E1, E2),
README section 8 (D3-D7) and code/deal_lib.py of reports/backtest-2025-deal-20261030, copied faithfully in
tests/ref_deal_lib.py (pinned on hand values by tests/test_v132_ref_deal_lib.py). Interface under test:
  app.ml.extra_features: LY_NAMES, DEAL_NAMES, FEATURE_SETS, extra_names(cfg), ExtraContext(keys, day0, last_day,
      demand, deals=None, deal_lines=None, open_days=None) with ly_block / deal_block / block / active_on;
  app.ml.features: feature_names, Panel.extra, features_at / origin_features / direct_training_matrix;
  app.ml.pipeline.config_fingerprint.
The application module is imported inside each test so that every rule reports on its own. Synthetic data only; no DB
read (the autouse conftest isolation still applies), no network.

Comparison with the reference (_same): float32 result, same shape, assert_allclose rtol 1e-6, atol 0, NaN == NaN. Not
exact equality: the reference evaluates in float64 through prefix sums and casts once to float32; an implementation with
an equivalent but differently ordered sum may land one float32 ulp away (about 6e-8 relative). A formula difference is
orders of magnitude larger. The quantities are integers, so counts and sums are exact anyway. The leakage tests compare
the module with itself: exact equality there.
"""
import hashlib
import json
from collections import Counter
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import ref_deal_lib as rl
from app import settings_service as ss
from app.ml import features, pipeline
from app.ml.features import build_panel, static_codes

LY = ["ly_same_day", "ly_mean_7", "ly_mean_28", "ly_trend"]
DEAL = ["deal_active", "deal_days_since_start", "deal_days_to_end", "deal_max_qty", "deal_used_to_date",
        "deal_remaining_ratio", "deal_used_1", "deal_used_7", "n_active_deals", "sku_deal_uplift_hist",
        "sku_deal_usage_hist", "grp_deal_uplift_hist"]
ALL_EXTRA = LY + DEAL
NEW_132 = ("feature_set", "ly_history_start")
NEW_131 = ("horizon_weight_short", "horizon_weight_cutoff", "feature_sku_code", "fallback_enabled", "feature_table")
RTOL = 1e-6
FMT = "%Y-%m-%d %H:%M:%S"
D = rl.HAND_D                                                   # 2026-03-10
# origins of the reference comparison: every LY window before day0 / mean_28 and trend before day0 / trend before day0 /
# end of a month / 1st of a month / fixed deal boundaries / the forecast origin (last day + 1, also a 1st)
ORIGINS = [date(2025, 12, 15), date(2026, 1, 20), date(2026, 2, 10), date(2026, 2, 28), date(2026, 3, 1),
           date(2026, 3, 17), date(2026, 4, 1)]
# production-like 1.2.14 configuration and its fingerprint (tests/test_v131_model_config.py)
PROD = {"forecast_strategy": "DIRECT", "feature_customer": True, "feature_promotion": False, "feature_discount": False}
OH = {"feature_open_hours": True, "weekday_encoding": "ISO"}
FP_PROD_1214 = "8468ebe66d1706f7"
BASE_CFG = {"forecast_strategy": "DIRECT", "direct_origins": 3, "direct_origin_step_days": 7}


def _xf():
    from app.ml import extra_features
    return extra_features


_CASE = object()


def _ctx(case, keys=None, demand=None, deals=_CASE, deal_lines=_CASE, open_days=_CASE):
    """ExtraContext of a synthetic case; the frames of the case unless replaced (None is passed through)."""
    return _xf().ExtraContext(list(case["keys"] if keys is None else keys), case["day0"], case["last_day"],
                              case["demand"] if demand is None else demand,
                              deals=case["deals"] if deals is _CASE else deals,
                              deal_lines=case["deal_lines"] if deal_lines is _CASE else deal_lines,
                              open_days=case["open_days"] if open_days is _CASE else open_days)


def _same(actual, expected):
    assert isinstance(actual, np.ndarray) and actual.dtype == np.float32, getattr(actual, "dtype", type(actual))
    assert actual.shape == expected.shape, (actual.shape, expected.shape)
    np.testing.assert_allclose(actual, expected, rtol=RTOL, atol=0, equal_nan=True)


def _close(row, expected):
    np.testing.assert_allclose(np.asarray(row, dtype=float), np.asarray(expected, dtype=float), rtol=RTOL, atol=0,
                               equal_nan=True)


def _shuffled(keys, seed):
    order = np.random.default_rng(seed).permutation(len(keys))
    return [keys[i] for i in order]


def _deal_end_origin(case) -> date:
    """The end day of a valid deal of the case (the deal is active at that day's 00:00, days to end 0)."""
    r, e = pd.to_datetime(case["deals"]["ready_time"]), pd.to_datetime(case["deals"]["end_time"])
    ok = (r <= e) & (e > pd.Timestamp("2026-02-01")) & (e < pd.Timestamp("2026-03-31"))
    return e[ok].min().date()


# ------------------------------------------------------------------ 1. names
def test_names_and_feature_sets():
    xf = _xf()
    assert xf.LY_NAMES == LY == rl.LY_NAMES
    assert xf.DEAL_NAMES == DEAL == rl.DEAL_NAMES
    assert xf.FEATURE_SETS == {"CHOT": [], "CHOT_LY": LY, "CHOT_LY_DEAL": LY + DEAL}
    every_131 = features.feature_names(SimpleNamespace(**{**_cfg(feature_customer=True).model_dump(), **OH}))
    assert len(set(ALL_EXTRA)) == 16 and not set(ALL_EXTRA) & (set(every_131) | {"sku_code"})


def test_extra_names_follow_the_feature_set():
    xf = _xf()
    assert xf.extra_names(SimpleNamespace()) == []                       # a configuration stored before 1.3.2
    assert xf.extra_names(SimpleNamespace(feature_set=None)) == []
    assert xf.extra_names(_cfg()) == [] and xf.extra_names(_cfg("CHOT")) == []
    assert xf.extra_names(_cfg("CHOT_LY")) == LY
    assert xf.extra_names(_cfg("CHOT_LY_DEAL")) == LY + DEAL


# ------------------------------------------------------------------ 2. same values as the preregistered reference
@pytest.mark.parametrize("seed", [11, 12])
def test_blocks_match_the_reference_on_random_data(seed):
    case = rl.random_case(seed)
    keys = _shuffled(case["universe"], seed)                             # rows come back in the order of keys
    ctx = _ctx(case, keys=keys)
    snap = rl.ref_snapshot(case)
    rows = snap.rows_of(keys)
    assert (rows >= 0).all()
    for origin in ORIGINS + [_deal_end_origin(case)]:
        _same(ctx.ly_block(origin), snap.ly_features(rows, origin))
        _same(ctx.deal_block(origin), snap.deal_features(rows, origin))
    for day in sorted({o + timedelta(days=h) for o in ORIGINS for h in (0, 1, 6)}):
        a = ctx.active_on(day)
        assert isinstance(a, np.ndarray) and a.dtype == np.int8 and a.shape == (len(keys),)
        np.testing.assert_array_equal(a, snap.active_on(rows, day), err_msg=str(day))


def test_dates_and_timestamps_are_read_like_iso_strings():
    case = rl.random_case(11)
    keys = case["universe"]
    base = _ctx(case, keys=keys)
    as_date = {c: case[c].assign(order_date=pd.to_datetime(case[c]["order_date"]).dt.date)
               for c in ("demand", "deal_lines")}
    deals = case["deals"].assign(ready_time=pd.to_datetime(case["deals"]["ready_time"]),
                                 end_time=pd.to_datetime(case["deals"]["end_time"]))      # naive Timestamps
    other = _ctx(case, keys=keys, demand=as_date["demand"], deals=deals, deal_lines=as_date["deal_lines"])
    for origin in (date(2026, 3, 1), date(2026, 3, 17)):
        np.testing.assert_array_equal(other.ly_block(origin), base.ly_block(origin))
        np.testing.assert_array_equal(other.deal_block(origin), base.deal_block(origin))
        np.testing.assert_array_equal(other.active_on(origin), base.active_on(origin))


def test_a_later_day0_ignores_older_rows_and_its_windows_start_there():
    case = {**rl.random_case(12), "day0": date(2025, 3, 1)}
    snap = rl.ref_snapshot(case)
    keys = list(snap.keys)
    ctx = _ctx(case, keys=keys)
    for origin in (date(2026, 2, 10), date(2026, 3, 1), date(2026, 3, 26), date(2026, 4, 1)):
        _same(ctx.ly_block(origin), snap.ly_features(snap.rows_of(keys), origin))
        _same(ctx.deal_block(origin), snap.deal_features(snap.rows_of(keys), origin))
    ly = ctx.ly_block(date(2026, 3, 26))                                 # D-391 is before 2025-03-01
    assert np.isnan(ly[:, 2:]).all() and not np.isnan(ly[:, :2]).any()


def test_rows_outside_day0_and_last_day_are_never_read():
    case = rl.random_case(11)
    keys = case["universe"]
    lo, hi = case["day0"].isoformat(), case["last_day"].isoformat()

    def inside(df):
        return df[(df["order_date"] >= lo) & (df["order_date"] <= hi)]
    full = _ctx(case, keys=keys)
    cut = _ctx(case, keys=keys, demand=inside(case["demand"]), deal_lines=inside(case["deal_lines"]))
    assert len(inside(case["demand"])) < len(case["demand"]) and len(inside(case["deal_lines"])) < len(case["deal_lines"])
    for origin in (date(2025, 12, 31), date(2026, 3, 17), date(2026, 4, 1)):
        np.testing.assert_array_equal(cut.ly_block(origin), full.ly_block(origin))
        np.testing.assert_array_equal(cut.deal_block(origin), full.deal_block(origin))


def test_without_open_days_there_is_no_group_feature():
    case = rl.random_case(11)
    keys = case["universe"]
    ctx = _ctx(case, keys=keys, open_days=None)
    snap = rl.ref_snapshot(case, open_days=None)
    for origin in (date(2026, 3, 1), date(2026, 3, 17)):
        out = ctx.deal_block(origin)
        _same(out, snap.deal_features(snap.rows_of(keys), origin))
        assert np.isnan(out[:, DEAL.index("grp_deal_uplift_hist")]).all()


def test_a_key_outside_the_universe_gets_the_reference_defaults():
    # universe = demand series U deal series; (SA, F2) has deal lines only, (NOPE, F0) nothing at all
    case = rl.hand_case()
    keys = case["keys"] + [("SA", "F2"), ("NOPE", "F0")]
    ctx = _ctx(case, keys=keys)
    snap = rl.ref_snapshot(case)
    rows = snap.rows_of(keys)
    assert rows[-2:].tolist() == [-1, -1]
    for origin in (D, date(2026, 2, 5), date(2025, 12, 31)):
        _same(ctx.ly_block(origin), snap.ly_features(rows, origin))
        _same(ctx.deal_block(origin), snap.deal_features(rows, origin))
        np.testing.assert_array_equal(ctx.active_on(origin), snap.active_on(rows, origin))
    _close(ctx.ly_block(D)[-1], [0.0, 0.0, 0.0, 1.0])
    _close(ctx.ly_block(date(2026, 2, 5))[-1], [0.0, 0.0, 0.0, np.nan])
    _close(ctx.deal_block(D)[-1], rl._DEAL_NONE)


def test_empty_deal_table_and_empty_demand():
    case = rl.hand_case()
    ctx = _ctx(case, deals=pd.DataFrame(columns=rl.DEAL_COLS), deal_lines=pd.DataFrame(columns=rl.LINE_COLS))
    out = ctx.deal_block(D)
    assert out.shape == (len(case["keys"]), 12)
    for row in out:
        _close(row, rl._DEAL_NONE)
    assert ctx.active_on(D).tolist() == [0] * len(case["keys"])
    # no demand row at all: the universe is the deal series
    empty = pd.DataFrame(columns=rl.DEMAND_COLS)
    ctx = _ctx(case, demand=empty)
    snap = rl.ref_snapshot(case, demand=empty)
    rows = snap.rows_of(case["keys"])
    for origin in (D, date(2026, 2, 5)):
        _same(ctx.ly_block(origin), snap.ly_features(rows, origin))
        _same(ctx.deal_block(origin), snap.deal_features(rows, origin))


# ------------------------------------------------------------------ 3. hand-computed values (ref_deal_lib.HAND_*)
def test_hand_same_period_last_year():
    case = rl.hand_case()
    ctx = _ctx(case)
    out = ctx.ly_block(D)
    assert out.dtype == np.float32 and out.shape == (len(case["keys"]), 4)
    for i, k in enumerate(case["keys"]):
        _close(out[i], rl.hand_ly(k))
    ia, ib = case["keys"].index(rl.SA), case["keys"].index(rl.SB)
    # ly_same_day = D-364 (14); ly_mean_7 = D-367..D-361 (35 / 7); ly_mean_28 = D-391..D-364 (42 / 28);
    # ly_trend = 1.5 / (D-419..D-392: 84 / 28); SB: earlier mean 0 -> 1
    assert out[ia].tolist() == pytest.approx([14.0, 5.0, 1.5, 0.5])
    assert out[ib].tolist() == pytest.approx([0.0, 0.0, 1.0, 1.0])
    # windows starting before day0 -> NaN; the row of 2024-12-31 is never read; a day without a row counts 0
    _close(ctx.ly_block(date(2025, 12, 31))[ia], [3.0, np.nan, np.nan, np.nan])
    _close(ctx.ly_block(date(2026, 2, 5))[ia], [0.0, 0.0, 1028 / 28, np.nan])
    assert np.isnan(ctx.ly_block(date(2025, 12, 30))).all()


def test_hand_deal_block():
    case = rl.hand_case()
    out = _ctx(case).deal_block(D)
    assert out.dtype == np.float32 and out.shape == (len(case["keys"]), 12)
    for i, k in enumerate(case["keys"]):
        _close(out[i], rl.HAND_DEAL[k])


@pytest.mark.parametrize("name", DEAL)
def test_hand_deal_feature_by_feature(name):
    # the same values one column at a time, so that a failure names the feature
    case = rl.hand_case()
    j = DEAL.index(name)
    col = _ctx(case).deal_block(D)[:, j]
    _close(col, [rl.HAND_DEAL[k][j] for k in case["keys"]])


def test_hand_active_on_target_days():
    case = rl.hand_case()
    ctx = _ctx(case)
    for day, on in rl.HAND_ACTIVE.items():
        out = ctx.active_on(day)
        assert out.dtype == np.int8
        assert {k for k, v in zip(case["keys"], out.tolist()) if v} == on, day


def test_deal_times_are_vietnam_wall_clock():
    # X ends 23:30 on D-1 (Vietnam time, as stored): finished at D 00:00 (a +7 h reading would make it active);
    # Y is ready exactly at D 00:00: visible, 0 days since its start
    demand = pd.DataFrame([("S1", "F1", "2026-02-01", 10.0), ("S1", "F1", "2026-03-09", 4.0)], columns=rl.DEMAND_COLS)
    deals = pd.DataFrame([("X", "S1", "F1", "2026-03-09 18:00:00", "2026-03-09 23:30:00", 10.0, 4.0),
                          ("Y", "S1", "F1", "2026-03-10 00:00:00", "2026-03-12 00:00:00", 20.0, 0.0)],
                         columns=rl.DEAL_COLS)
    lines = pd.DataFrame([("S1", "F1", "2026-03-09", "X", 4.0)], columns=rl.LINE_COLS)
    case = {"keys": [("S1", "F1")], "day0": date(2025, 1, 1), "last_day": date(2026, 3, 31), "demand": demand,
            "deals": deals, "deal_lines": lines, "open_days": None}
    ctx = _ctx(case)
    # Y only: since 0, to_end 2, max 20, used 0 (X's line is not Y's), ratio 1; X: usage 4/10, uplift none (base 0)
    _close(ctx.deal_block(D)[0], [1.0, 0.0, 2.0, 20.0, 0.0, 1.0, 0.0, 0.0, 1.0, np.nan, 0.4, np.nan])
    # at 2026-03-09 00:00 X is not ready yet (18:00)
    _close(ctx.deal_block(date(2026, 3, 9))[0], rl._DEAL_NONE)
    assert ctx.active_on(date(2026, 3, 9)).tolist() == [1] and ctx.active_on(date(2026, 3, 13)).tolist() == [0]
    _same(ctx.deal_block(D), rl.ref_snapshot(case).deal_features(np.array([0]), D))


def test_block_returns_the_named_columns_in_order():
    case = rl.hand_case()
    ctx = _ctx(case)
    full = np.hstack([ctx.ly_block(D), ctx.deal_block(D)])
    names = ["deal_used_1", "ly_trend", "deal_active", "ly_same_day"]
    out = ctx.block(D, names)
    assert out.dtype == np.float32 and out.shape == (len(case["keys"]), 4)
    np.testing.assert_array_equal(out, full[:, [ALL_EXTRA.index(n) for n in names]])
    np.testing.assert_array_equal(ctx.block(D, ALL_EXTRA), full)
    np.testing.assert_array_equal(ctx.block(D, LY), ctx.ly_block(D))
    e = ctx.block(D, [])
    assert e.shape == (len(case["keys"]), 0) and e.dtype == np.float32
    none = _ctx(case, keys=[])                                            # a scope without series
    assert none.ly_block(D).shape == (0, 4) and none.deal_block(D).shape == (0, 12)
    assert none.block(D, ALL_EXTRA).shape == (0, 16) and none.active_on(D).shape == (0,)


def test_without_a_deal_source_only_the_ly_features():
    case = rl.hand_case()
    ctx = _ctx(case, deals=None, deal_lines=None)
    with pytest.raises(ValueError, match=r"^DEAL_SOURCE_NOT_CONFIGURED"):
        ctx.deal_block(D)
    with pytest.raises(ValueError, match=r"^DEAL_SOURCE_NOT_CONFIGURED"):
        ctx.block(D, ["ly_same_day", "deal_active"])
    np.testing.assert_array_equal(ctx.block(D, LY), _ctx(case).ly_block(D))
    for i, k in enumerate(case["keys"]):
        _close(ctx.ly_block(D)[i], rl.hand_ly(k))


# ------------------------------------------------------------------ 4. leakage (data_checks.md 2.7)
def _upsert(df: pd.DataFrame, key_cols: list[str], rows: list[tuple], add: float) -> pd.DataFrame:
    """Add `add` to the qty of each row key (rows: tuples of key_cols); a missing key becomes a new row of qty `add`.
    Keeps one row per key (the stored frames have unique keys)."""
    df = df.copy()
    idx = {k: i for i, k in enumerate(map(tuple, df[key_cols].astype(str).to_numpy().tolist()))}
    new = []
    for k in rows:
        i = idx.get(tuple(map(str, k)))
        if i is None:
            new.append((*k, add))
        else:
            df.iloc[i, df.columns.get_loc("qty")] += add
    if new:
        df = pd.concat([df, pd.DataFrame(new, columns=key_cols + ["qty"])[df.columns]], ignore_index=True)
    return df


def _changed_from(case, origin: date) -> dict:
    """Every input that is unknown at origin 00:00 changed: demand rows and deal lines from the origin on (values
    changed, rows added), every deal with ready_time > origin 00:00 (max and end changed, fake deals added) and
    quantity_used of every deal not finished before the origin."""
    t = pd.Timestamp(origin)
    dem = case["demand"].copy()
    fut = pd.to_datetime(dem["order_date"]) >= t
    dem.loc[fut, "qty"] = dem.loc[fut, "qty"] * 3 + 1
    days = [(origin + timedelta(days=i)).isoformat() for i in (0, 2)]
    dem = _upsert(dem, ["sku_id", "fc_id", "order_date"], [(*k, d) for k in case["universe"] for d in days], 42.0)
    deals = case["deals"].copy()
    ready, end = pd.to_datetime(deals["ready_time"]), pd.to_datetime(deals["end_time"])
    later = ready > t
    deals.loc[later, "max_quantity"] = 999.0
    deals.loc[later, "end_time"] = (end[later] + pd.Timedelta(days=3)).dt.strftime(FMT)
    deals.loc[end >= t, "quantity_used"] = 12345.0
    fake = [(f"FAKE{i}", s, f, (t + pd.Timedelta(minutes=1 + 37 * i)).strftime(FMT),
             (t + pd.Timedelta(days=6)).strftime(FMT), 5.0, 1.0) for i, (s, f) in enumerate(case["universe"])]
    deals = pd.concat([deals, pd.DataFrame(fake, columns=rl.DEAL_COLS)], ignore_index=True)
    ln = case["deal_lines"].copy()
    fut = pd.to_datetime(ln["order_date"]) >= t
    ln.loc[fut, "qty"] = ln.loc[fut, "qty"] + 5
    open_now = deals[pd.to_datetime(deals["end_time"]) >= t]
    ln = _upsert(ln, ["sku_id", "fc_id", "order_date", "deal_code"],
                 [(s, f, d, c) for c, s, f in zip(open_now["deal_code"], open_now["sku_code"], open_now["fc_code"])
                  for d in days], 8.0)
    return {**case, "demand": dem, "deals": deals, "deal_lines": ln}


@pytest.mark.parametrize("origin", [date(2026, 3, 1), date(2026, 3, 17)])
def test_no_leakage_from_the_origin_day_on(origin):
    case = rl.random_case(11)
    keys = case["universe"]
    changed = _changed_from(case, origin)
    base, new = _ctx(case, keys=keys), _ctx(changed, keys=keys)
    np.testing.assert_array_equal(new.ly_block(origin), base.ly_block(origin))
    np.testing.assert_array_equal(new.deal_block(origin), base.deal_block(origin))
    np.testing.assert_array_equal(new.block(origin, ALL_EXTRA), base.block(origin, ALL_EXTRA))
    # the change is real: a later origin sees it
    later = origin + timedelta(days=10)
    assert not np.array_equal(new.deal_block(later), base.deal_block(later), equal_nan=True)


def test_negative_control_the_day_before_changes_the_used_quantities():
    case = rl.random_case(11)
    keys = case["universe"]
    origin = date(2026, 3, 17)
    snap = rl.ref_snapshot(case)
    d = snap.day_index(origin)
    dd = snap.deals
    act = dd[dd["valid"] & (dd["ready_x"] <= d) & (dd["end_x"] >= d)]
    n_act = Counter(zip(act["sku_code"], act["fc_code"]))
    assert len(n_act) >= 3
    day = (origin - timedelta(days=1)).isoformat()
    ln = _upsert(case["deal_lines"], ["sku_id", "fc_id", "order_date", "deal_code"],
                 [(s, f, day, c) for c, s, f in zip(act["deal_code"], act["sku_code"], act["fc_code"])], 2.0)
    dem = case["demand"]
    for k, n in n_act.items():
        dem = _upsert(dem, ["sku_id", "fc_id", "order_date"], [(*k, day)], 2.0 * n)
    changed = {**case, "demand": dem, "deal_lines": ln}
    base, new = _ctx(case, keys=keys), _ctx(changed, keys=keys)
    b0, b1 = base.deal_block(origin), new.deal_block(origin)
    idx = [keys.index(k) for k in n_act]
    delta = 2.0 * np.array([n_act[k] for k in n_act])
    for name in ("deal_used_to_date", "deal_used_1", "deal_used_7"):
        j = DEAL.index(name)
        _close(b1[idx, j] - b0[idx, j], delta)
    j = DEAL.index("deal_remaining_ratio")
    assert (~np.isclose(b1[idx, j], b0[idx, j], equal_nan=True)).any()
    new_snap = rl.ref_snapshot(changed)
    _same(b1, new_snap.deal_features(new_snap.rows_of(keys), origin))
    np.testing.assert_array_equal(new.ly_block(origin), base.ly_block(origin))   # D-1 is no LY day


def test_negative_control_days_d_364_and_d_392_change_the_ly_features():
    case = rl.random_case(11)
    keys = case["universe"]
    origin = date(2026, 3, 17)
    days = [(origin - timedelta(days=n)).isoformat() for n in (364, 392)]
    dem = _upsert(case["demand"], ["sku_id", "fc_id", "order_date"], [(*k, d) for k in keys for d in days], 5.0)
    changed = {**case, "demand": dem}
    l0, l1 = _ctx(case, keys=keys).ly_block(origin), _ctx(changed, keys=keys).ly_block(origin)
    np.testing.assert_allclose(l1[:, 0] - l0[:, 0], 5.0, rtol=RTOL)
    np.testing.assert_allclose(l1[:, 1] - l0[:, 1], 5 / 7, rtol=1e-4)
    np.testing.assert_allclose(l1[:, 2] - l0[:, 2], 5 / 28, rtol=1e-4)
    assert (l1[:, 3] != l0[:, 3]).sum() > len(keys) // 2
    new_snap = rl.ref_snapshot(changed)
    _same(l1, new_snap.ly_features(new_snap.rows_of(keys), origin))


# ------------------------------------------------------------------ 5. duplicate deal keys (application rule)
def test_duplicate_deal_keys_use_the_row_with_the_latest_end_time():
    case = rl.hand_case()
    deals = case["deals"]
    d1 = deals[deals["deal_code"] == "D1"].assign(end_time="2026-03-25 23:00:00", max_quantity=300.0)  # latest end
    d2 = deals[deals["deal_code"] == "D2"].assign(max_quantity=60.0)                     # same end: last row wins
    d4 = deals[deals["deal_code"] == "D4"].assign(end_time="2026-02-05 00:00:00", max_quantity=1.0)    # earlier end
    dup = pd.concat([d1, deals, d2, d4], ignore_index=True)        # the D1 row that wins comes FIRST in input order
    ctx = _ctx(case, deals=dup)                                     # must not raise
    out = ctx.deal_block(D)
    exp = list(rl.HAND_DEAL[rl.SA])
    exp[2], exp[3], exp[5] = 15.0, 360.0, 1 - 20 / 360              # to_end 03-25, max 300 + 60
    _close(out[case["keys"].index(rl.SA)], exp)
    snap = rl.ref_snapshot(case, deals=rl.dedupe_like_app(dup))
    rows = snap.rows_of(case["keys"])
    _same(out, snap.deal_features(rows, D))
    _same(ctx.ly_block(D), snap.ly_features(rows, D))
    for day in (date(2026, 2, 7), date(2026, 3, 22)):              # D4 keeps 02-01..02-10; D1 now covers 03-22
        np.testing.assert_array_equal(ctx.active_on(day), snap.active_on(rows, day))
    assert ctx.active_on(date(2026, 3, 22))[case["keys"].index(rl.SA)] == 1


# ------------------------------------------------------------------ 6. hook in app/ml/features.py
def _cfg(feature_set=None, table=None, **kw):
    """DIRECT ModelSettings with small training sizes; feature_set / feature_table set as a training sets them."""
    cfg = ss.ModelSettings(**{**BASE_CFG, **kw})
    upd = {}
    if feature_set is not None:
        upd["feature_set"] = feature_set
    if table is not None:
        upd["feature_table"] = {k: ss.FeatureRule(**v) for k, v in table.items()}
    return cfg.model_copy(update=upd) if upd else cfg


def _legacy(cfg):
    """The same configuration as a 1.3.1 run stored it: no feature_set / ly_history_start attribute at all."""
    d = cfg.model_dump()
    for k in NEW_132:
        d.pop(k, None)
    return SimpleNamespace(**d)


def _panel(seed=11):
    """Panel of 2026-01-01 .. 2026-03-31 (T = 90) of the random case; its ExtraContext reads the whole history."""
    case = rl.random_case(seed)
    dem = case["demand"]
    win = dem[(dem["order_date"] >= "2026-01-01") & (dem["order_date"] <= "2026-03-31")]
    return case, build_panel(win, end_date="2026-03-31", start_date="2026-01-01")


def _with_extra(seed=11):
    case, p = _panel(seed)
    ctx = _ctx(case, keys=p.keys)
    p.extra = ctx
    return case, p, ctx


def _origin(p, cfg, t0):
    sc, fcc = static_codes(p)
    return features.origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, t0, cfg, sc, fcc)


def _day(p, t) -> date:
    return (p.dates[0] + pd.Timedelta(days=t)).date()


@pytest.mark.parametrize("kw", [{}, {"feature_sku_code": False}, {"feature_calendar": False, "feature_weekday": False},
                                {"feature_customer": True}])
@pytest.mark.parametrize("fs", ["CHOT_LY", "CHOT_LY_DEAL"])
def test_feature_names_put_the_extras_before_the_target_day_columns(fs, kw):
    cfg = _cfg(fs, **kw)
    old = features.feature_names(_legacy(cfg))
    tail = features.calendar_names(cfg) + ["horizon"]
    assert old[-len(tail):] == tail
    assert features.feature_names(cfg) == old[:-len(tail)] + (LY if fs == "CHOT_LY" else LY + DEAL) + tail


def test_feature_set_chot_gives_the_1_3_1_names_and_matrices():
    case, p = _panel()
    for cfg in (_cfg("CHOT"), _cfg()):
        assert features.feature_names(cfg) == features.feature_names(_legacy(cfg))
        for t0 in (45, p.T):                                              # no ExtraContext needed
            np.testing.assert_array_equal(_origin(p, cfg, t0), _origin(p, _legacy(cfg), t0))
        X1, y1 = features.direct_training_matrix(p, cfg, 7)
        X0, y0 = features.direct_training_matrix(p, _legacy(cfg), 7)
        np.testing.assert_array_equal(X1, X0)
        np.testing.assert_array_equal(y1, y0)
    p.extra = _ctx(case, keys=p.keys)                                     # attached but not used
    np.testing.assert_array_equal(_origin(p, _cfg("CHOT"), 45), _origin(p, _legacy(_cfg()), 45))


@pytest.mark.parametrize("fs", ["CHOT_LY", "CHOT_LY_DEAL"])
def test_origin_features_append_the_block_of_the_origin_day(fs):
    case, p, ctx = _with_extra()
    cfg = _cfg(fs)
    names = LY if fs == "CHOT_LY" else LY + DEAL
    assert p.T == 90 and _day(p, 0) == date(2026, 1, 1) and _day(p, p.T) == date(2026, 4, 1)
    n_target = len(features.direct_extra(cfg, p.dates[-1], 1))
    for t0 in (20, 45, p.T):                                              # t0 == T: the forecast origin
        X = _origin(p, cfg, t0)
        base = _origin(p, _legacy(cfg), t0)
        assert X.dtype == np.float32 and X.shape == (p.n_series, base.shape[1] + len(names))
        np.testing.assert_array_equal(X, np.hstack([base, ctx.block(_day(p, t0), names)]))
        assert X.shape[1] + n_target == len(features.feature_names(cfg))
    origin = _day(p, 45)                                                  # the fixture tells the day before apart
    assert not np.array_equal(ctx.block(origin, names), ctx.block(origin - timedelta(days=1), names), equal_nan=True)


def test_features_at_appends_the_block_after_every_other_column():
    case, p, ctx = _with_extra()
    cfg = _cfg("CHOT_LY_DEAL")
    sc, fcc = static_codes(p)
    t = 45
    X = features.features_at(p, p.Y, p.price, p.disc, p.promo, p.dates, t, cfg, sc, fcc)
    base = features.features_at(p, p.Y, p.price, p.disc, p.promo, p.dates, t, _legacy(cfg), sc, fcc)
    np.testing.assert_array_equal(X, np.hstack([base, ctx.block(_day(p, t), ALL_EXTRA)]))


def test_a_switched_off_extra_feature_is_left_out_of_names_and_columns():
    table = {"ly_trend": {"enabled": False}, "deal_used_7": {"enabled": False}, "dom": {"enabled": False}}
    cfg = _cfg("CHOT_LY_DEAL", table=table, feature_sku_code=False)
    kept = [n for n in ALL_EXTRA if n not in ("ly_trend", "deal_used_7")]
    old = features.feature_names(_legacy(cfg))
    tail = [n for n in features.calendar_names(cfg) if n != "dom"] + ["horizon"]
    names = features.feature_names(cfg)
    assert names == old[:-len(tail)] + kept + tail
    assert not {"sku_code", "dom", "ly_trend", "deal_used_7"} & set(names)
    case, p, ctx = _with_extra()
    for t0 in (45, p.T):
        X = _origin(p, cfg, t0)
        np.testing.assert_array_equal(X, np.hstack([_origin(p, _legacy(cfg), t0), ctx.block(_day(p, t0), kept)]))
        assert X.shape[1] + len(features.direct_extra(cfg, p.dates[-1], 1)) == len(names)


def test_a_panel_without_extra_context_refuses_the_extra_features():
    _, p = _panel()
    assert p.extra is None                                                # build_panel: no ExtraContext
    with pytest.raises(ValueError, match=r"^EXTRA_FEATURES_NOT_IN_PANEL"):
        _origin(p, _cfg("CHOT_LY"), 45)
    with pytest.raises(ValueError, match=r"^EXTRA_FEATURES_NOT_IN_PANEL"):
        features.direct_training_matrix(p, _cfg("CHOT_LY_DEAL"), 7)
    assert _origin(p, _cfg("CHOT"), 45).shape[0] == p.n_series


def test_truncate_keeps_the_extra_context():
    case, p, ctx = _with_extra()
    q = p.truncate(50)
    assert q.extra is ctx
    cfg = _cfg("CHOT_LY_DEAL")
    np.testing.assert_array_equal(_origin(q, cfg, 50), _origin(p, cfg, 50))


def test_direct_training_matrix_carries_the_extra_columns_of_each_origin():
    case, p, ctx = _with_extra()
    cfg = _cfg("CHOT_LY_DEAL")
    names = features.feature_names(cfg)
    X, y = features.direct_training_matrix(p, cfg, 7)
    X0, y0 = features.direct_training_matrix(p, _legacy(cfg), 7)
    assert X.shape == (X0.shape[0], len(names)) and X.dtype == np.float32
    np.testing.assert_array_equal(y, y0)
    i0 = names.index(ALL_EXTRA[0])
    np.testing.assert_array_equal(np.delete(X, np.arange(i0, i0 + 16), axis=1), X0)
    t0 = p.T - cfg.direct_origin_step_days                                # first origin, horizon 1 rows come first
    ok = ~np.isnan(p.Y[:, t0]) & (t0 > p.start_idx)
    k = int(ok.sum())
    np.testing.assert_array_equal(X[:k, i0:i0 + 16], ctx.block(_day(p, t0), ALL_EXTRA)[ok])


# ------------------------------------------------------------------ 7. config fingerprint
def _sha16(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def _dump_131(**kw) -> dict:
    """model_dump of the production-like configuration without the 1.3.2 keys (= a run stored by 1.3.1)."""
    d = ss.ModelSettings(**PROD, **kw).model_copy(update=OH).model_dump()
    return {k: v for k, v in d.items() if k not in NEW_132}


def test_fingerprint_unchanged_while_the_feature_set_is_chot():
    d = _dump_131()
    assert pipeline.config_fingerprint(d) == FP_PROD_1214
    for extra in ({"feature_set": "CHOT"}, {"ly_history_start": None}, {"feature_set": "CHOT", "ly_history_start": None}):
        assert pipeline.config_fingerprint({**d, **extra}) == FP_PROD_1214
    b1 = _dump_131(feature_sku_code=False, fallback_enabled=False, horizon_weight_short=3.0, horizon_weight_cutoff=7)
    fp = pipeline.config_fingerprint(b1)
    assert fp != FP_PROD_1214
    assert pipeline.config_fingerprint({**b1, "feature_set": "CHOT", "ly_history_start": None}) == fp


def test_fingerprint_changes_with_the_ly_feature_sets():
    d = _dump_131()
    old = {k: v for k, v in d.items() if k not in NEW_131}                # the 1.3.1 keys are at their defaults
    fps = set()
    for fs in ("CHOT_LY", "CHOT_LY_DEAL"):
        new = {"feature_set": fs, "ly_history_start": "2025-01-01"}
        fp = pipeline.config_fingerprint({**d, **new})
        assert fp != FP_PROD_1214
        assert fp == _sha16({**old, **new})                               # only the keys away from their default added
        fps.add(fp)
    assert len(fps) == 2
    assert pipeline.config_fingerprint({**d, "feature_set": "CHOT_LY", "ly_history_start": "2025-02-01"}) not in fps
