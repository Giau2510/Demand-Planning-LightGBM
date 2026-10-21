"""1.2.12 completion gate (owner requirement, weekday feature): dow = the ISO weekday of the TARGET date (Monday = 1 ...
Sunday = 7) and is_weekend, derived from the calendar date (created_date / order_date of the history, the forecast date at
inference), identical in the training rows, in every walk-forward fold, at inference, and in the fitted model's feature
names. Evidence from the real feature matrices and the real LightGBM booster (rows actually passed to predict), not from
schema declarations. No leakage: the target day contributes its calendar only, never its demand.
Synthetic panels, no database."""
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from app import settings_service as ss
from app import weekday as wd
from app.ml import model
from app.ml.features import (build_panel, calendar_row, direct_training_matrix, dow_value, feature_names,
                             origin_features, static_codes, training_matrix)

WEEK = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25"]   # Mon..Sun
BOUNDS = {"2026-10-31": 6, "2026-11-01": 7, "2026-12-31": 4, "2027-01-01": 5, "2028-02-28": 1, "2028-02-29": 2,
          "2028-03-01": 3, "2026-03-29": 7, "2026-03-30": 1}


def _cfg(**k):
    base = {**ss.ModelSettings().model_dump(), "forecast_strategy": "DIRECT", "weekday_encoding": "ISO",
            "num_boost_round": 30, "direct_origins": 6, "direct_origin_step_days": 7, "backtest_horizon_days": 14,
            "backtest_folds": 3, "backtest_step_days": 7, "min_total_history_days": 42, "min_series_history_days": 14}
    return ss.ModelSettings.model_validate({**base, **k})


def _panel(days=140, end="2026-10-20", n=8, seed=3):
    """Weekday-shaped demand (weekends higher) so a fitted model has a reason to use the weekday."""
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n):
        for d in pd.date_range(end=end, periods=days):
            lam = 6 + 6 * (d.isoweekday() >= 6) + s
            rows.append({"order_date": str(d.date()), "sku_id": f"S{s}", "fc_id": "HN" if s % 2 else "BD",
                         "qty": float(rng.poisson(lam)), "avg_unit_price": 10.0 + s, "avg_discount_rate": 0.0,
                         "promo_share": 0.0})
    return build_panel(pd.DataFrame(rows))


def _iso(ts) -> int:
    return wd.iso_weekday(pd.Timestamp(ts).date())


# ================================================================== the derivation itself
def test_all_seven_weekdays_monday_1_to_sunday_7_in_every_input_form():
    cfg = _cfg()
    for n, d in enumerate(WEEK, start=1):
        for form in (d, date.fromisoformat(d), datetime.fromisoformat(d + "T23:30:00"), pd.Timestamp(d)):
            assert wd.iso_weekday(form) == n
        row = calendar_row(pd.Timestamp(d), cfg)
        assert row[0] == float(n) and row[4] == (1.0 if n >= 6 else 0.0)      # dow, is_weekend of that very date
        assert wd.label(n) == ("Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật")[n - 1]


def test_date_boundaries_month_year_leap_and_a_late_evening_timestamp_keep_their_own_day():
    cfg = _cfg()
    for d, n in BOUNDS.items():
        assert wd.iso_weekday(d) == n and calendar_row(pd.Timestamp(d), cfg)[0] == float(n)
    assert wd.iso_weekday("2026-10-25T23:59:59+07:00") == 7                    # the calendar day itself, never shifted
    assert wd.iso_weekday(datetime(2026, 10, 25, 23, 59)) == 7


def test_models_from_1_2_9_use_1_to_7_and_older_models_keep_their_0_to_6_encoding():
    legacy = ss.ModelSettings.model_validate({k: v for k, v in _cfg().model_dump().items() if k != "weekday_encoding"})
    for n, d in enumerate(WEEK, start=1):
        assert dow_value(pd.Timestamp(d), _cfg()) == float(n)
        assert dow_value(pd.Timestamp(d), legacy) == float(n - 1)               # same day, the old model's own encoding


# ================================================================== training rows, folds, inference, fitted model
def _col(cfg, name):
    return feature_names(cfg).index(name)


@pytest.mark.parametrize("strategy", ["DIRECT", "RECURSIVE"])
def test_every_training_row_carries_the_weekday_of_its_target_day(strategy):
    p, cfg = _panel(), _cfg(forecast_strategy=strategy)
    if strategy == "DIRECT":
        X, _y, ix = direct_training_matrix(p, cfg, cfg.backtest_horizon_days, with_index=True)
    else:
        X, _y, ix = training_matrix(p, cfg, with_index=True)
    target = np.array([_iso(p.dates[t]) for t in ix[:, 1]], dtype=np.float32)
    assert len(X) > 500
    assert np.array_equal(X[:, _col(cfg, "dow")], target)
    assert np.array_equal(X[:, _col(cfg, "is_weekend")], (target >= 6).astype(np.float32))
    assert set(np.unique(X[:, _col(cfg, "dow")]).tolist()) == {1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0}


def test_origin_features_never_see_the_target_days_demand():
    p, cfg = _panel(), _cfg()
    sc, fcc = static_codes(p)
    t0 = p.T - 14
    before = origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, t0, cfg, sc, fcc)
    Y2 = p.Y.copy()
    Y2[:, t0:] = 999.0                                                          # any value on / after the origin
    after = origin_features(p, Y2, p.price, p.disc, p.promo, p.dates, t0, cfg, sc, fcc)
    assert np.array_equal(before, after, equal_nan=True)


class _Recorder:
    """Wraps the fitted booster: every matrix actually passed to predict() is kept (rows of the model input)."""
    def __init__(self, booster, sink):
        self._b, self._sink = booster, sink

    def predict(self, X, *a, **k):
        self._sink.append(np.array(X, copy=True))
        return self._b.predict(X, *a, **k)

    def __getattr__(self, name):
        return getattr(self._b, name)


def test_every_walk_forward_fold_trains_on_target_day_weekdays_and_forecasts_with_the_forecast_dates(monkeypatch):
    p, cfg = _panel(), _cfg()
    H, F, step = cfg.backtest_horizon_days, cfg.backtest_folds, cfg.backtest_step_days
    seen, fits = [], []
    real_train = model.train

    def train(tp, c, cancel=None, weights=None):
        X, _y, ix = direct_training_matrix(tp, c, model.direct_max_horizon(c), with_index=True)
        fits.append((tp.T, ix, X))                       # the fold's own training rows: targets before its origin only
        b, info = real_train(tp, c, cancel, weights)
        return (_Recorder(b, seen) if b is not None else None), info
    with monkeypatch.context() as m:
        m.setattr(model, "train", train)
        bt = model.backtest(p, cfg)
    assert len(bt["folds"]) == F and len(fits) == F
    for k, (origin, ix, X) in enumerate(fits):
        assert origin == p.T - H - (F - 1 - k) * step
        assert ix[:, 1].max() < origin                                          # no training target on / after the origin
        assert np.array_equal(X[:, _col(cfg, "dow")], np.array([_iso(p.dates[t]) for t in ix[:, 1]], dtype=np.float32))
    # forecasting inside each fold: one predict() per horizon day, dow = the weekday of that forecast date
    assert len(seen) == F * H
    for k, (origin, _ix, _X) in enumerate(fits):
        for h in range(H):
            Xh = seen[k * H + h]
            assert set(Xh[:, _col(cfg, "dow")].tolist()) == {float(_iso(p.dates[origin + h]))}
            assert set(Xh[:, _col(cfg, "horizon")].tolist()) == {float(h + 1)}


def test_inference_uses_the_weekday_of_each_forecast_date_and_the_fitted_model_has_the_declared_features():
    p, cfg = _panel(), _cfg()
    booster, info = model.train(p, cfg)
    names = feature_names(cfg)
    assert booster.feature_name() == names                                      # fitted model = declared order
    assert names.index("dow") == len(names) - 7 and names[-7:] == ["dow", "dom", "month", "weekofyear", "is_weekend",
                                                                   "days_to_month_end", "horizon"]
    split = dict(zip(booster.feature_name(), booster.feature_importance("split")))
    assert split["dow"] + split["is_weekend"] > 0                               # the model really uses the weekday
    fc = model.forecast(p, booster, cfg, 14, capture=0)
    future = pd.date_range(p.dates[-1] + pd.Timedelta(days=1), periods=14)
    assert list(fc["dates"]) == list(future)
    got = [float(r[names.index("dow")]) for r in fc["captured"]]
    assert got == [float(_iso(d)) for d in future]                              # the forecast date, never an order date
    assert [float(r[names.index("is_weekend")]) for r in fc["captured"]] == [1.0 if _iso(d) >= 6 else 0.0 for d in future]
    # parity: the captured inference row of day h equals the training-style row of the same origin / target day
    sc, fcc = static_codes(p)
    xb = origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, p.T, cfg, sc, fcc)[0]
    for h, d in enumerate(future):
        from app.ml.features import direct_extra
        expect = np.hstack([xb, np.array(direct_extra(cfg, d, h + 1), dtype=np.float32)])
        assert np.array_equal(fc["captured"][h], expect, equal_nan=True)
