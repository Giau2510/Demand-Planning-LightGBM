"""1.2.9 (fourth batch, 20/10/2026): standard over / under-forecast metrics, the normal-day split and walk-forward
calibration factors (app/ml/overforecast.py - evaluation / experiment code, not used by the application's training,
forecast or publication). Synthetic arrays only; no database, no BigQuery."""
from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pytest

from app import qty
from app import settings_service as ss
from app.ml import demand_patterns, model, overforecast


# ================================================================== metrics
def test_metrics_follow_the_agreed_formulas_and_wape_is_over_plus_under():
    a = np.array([10.0, 0.0, 5.0, 20.0])
    f = np.array([12.0, 3.0, 5.0, 14.0])          # +2, +3, 0, -6
    m = overforecast.metrics(a, f)
    assert m["n"] == 4 and m["sum_actual"] == 35 and m["sum_forecast"] == 34
    assert m["bias"] == pytest.approx(-1 / 35)
    assert m["over"] == pytest.approx(5 / 35)       # never offset by the -6 shortfall
    assert m["under"] == pytest.approx(6 / 35)
    assert m["wape"] == pytest.approx(11 / 35) == pytest.approx(m["over"] + m["under"])
    assert m["ratio"] == pytest.approx(34 / 35)


def test_metrics_are_undefined_when_the_actual_total_is_zero_and_refuse_unknown_values():
    m = overforecast.metrics(np.zeros(3), np.array([1.0, 0.0, 2.0]))
    assert m["n"] == 3 and m["sum_forecast"] == 3
    assert all(m[k] is None for k in overforecast.RATIOS)        # no division by 0, nothing dropped
    assert overforecast.metrics([], [])["bias"] is None
    with pytest.raises(ValueError):
        overforecast.metrics([1.0, np.nan], [1.0, 1.0])
    with pytest.raises(ValueError):
        overforecast.metrics([1.0], [1.0, 2.0])


def test_whole_units_is_the_published_rounding_and_zero_stays_a_valid_forecast():
    vals = [0.0, 0.2, 0.49, 0.5, 0.51, 1.5, 2.49, 7.0, -0.3]
    assert overforecast.whole_units(vals).tolist() == [qty.business_qty(v) for v in vals]
    assert overforecast.whole_units([0.0, 0.4])[0] == 0 and overforecast.whole_units([0.4])[0] == 0  # no minimum of 1
    assert np.isnan(overforecast.whole_units([np.nan])[0])


# ================================================================== normal days (evaluation label)
def _history(S=3, T=91, seed=1):
    rng = np.random.default_rng(seed)
    return rng.poisson(4.0, size=(S, T)).astype(float)


def test_normal_days_are_the_known_days_that_are_not_spikes_of_demand_patterns():
    h = _history()
    act = np.array([[4.0, 60.0, np.nan], [0.0, 3.0, 5.0], [5.0, 4.0, 200.0]])
    nd = overforecast.normal_days(act, h)
    spikes = demand_patterns.spike_flags(act, demand_patterns.spike_thresholds(h, h.shape[1]))
    assert nd.tolist() == (~np.isnan(act) & ~spikes).tolist()
    assert not nd[0, 1] and not nd[2, 2] and not nd[0, 2]       # two spikes and an unknown day
    assert nd[1].all()


def test_the_normal_day_label_reads_no_later_day_and_only_the_history_before_the_cutoff():
    h = _history()
    act = np.array([[4.0, 30.0, 4.0], [5.0, 5.0, 5.0], [3.0, 3.0, 50.0]])
    base = overforecast.normal_days(act, h)
    later = act.copy()
    later[:, 1:] = 999.0                                        # other evaluated days change: day 0 keeps its label
    assert overforecast.normal_days(later, h)[:, 0].tolist() == base[:, 0].tolist()
    longer = np.concatenate([np.full((3, 50), 500.0), h], axis=1)   # data older than the window: no effect
    assert overforecast.normal_days(act, longer).tolist() == base.tolist()


# ================================================================== walk-forward calibration
def test_calibration_factor_hits_the_target_bias_on_the_earlier_window():
    a, f = np.array([10.0, 20.0, 0.0]), np.array([12.0, 26.0, 2.0])
    k = overforecast.calibration_factor(a, f, target_bias=0.03)
    assert overforecast.metrics(a, k * f)["bias"] == pytest.approx(0.03)
    assert overforecast.calibration_factor(a, np.zeros(3)) is None     # nothing to learn from


def test_walk_forward_factors_use_only_the_earlier_windows():
    w = [(np.array([10.0, 10.0]), np.array([12.0, 12.0])), (np.array([5.0, 5.0]), np.array([8.0, 8.0])),
         (np.array([7.0]), np.array([7.0]))]
    k = overforecast.walk_forward_factors(w)
    assert k[0] is None
    assert k[1] == pytest.approx(20 / 24) and k[2] == pytest.approx(30 / 40)
    changed = [w[0], w[1], (np.array([100.0]), np.array([1.0]))]       # the last window's own data: no effect on it
    assert overforecast.walk_forward_factors(changed)[:3] == k
    changed_mid = [w[0], (np.array([50.0, 50.0]), np.array([8.0, 8.0])), w[2]]
    k2 = overforecast.walk_forward_factors(changed_mid)
    assert k2[1] == k[1] and k2[2] != k[2]                               # a window only affects LATER factors


def test_segment_factors_shrink_toward_the_global_factor_and_fall_back_for_small_segments():
    fac = overforecast.segment_factors({"big": 80_000.0, "small": 10.0, "none": 0.0},
                                       {"big": 100_000.0, "small": 400.0, "none": 0.0}, k_global=0.9)
    assert fac["small"] == 0.9 and fac["none"] == 0.9                    # below MIN_SEGMENT_UNITS: global factor
    assert fac["big"] == pytest.approx((80_000 + 5000 * 0.9) / (100_000 + 5000))
    assert 0.8 < fac["big"] < 0.9                                        # pulled toward the global factor
    zero = np.zeros(4)
    assert (overforecast.whole_units(fac["big"] * zero) == 0).all()     # a zero forecast stays zero


# ================================================================== the application is unchanged
def test_the_application_never_uses_the_overforecast_experiment_code():
    app_dir = Path(overforecast.__file__).resolve().parents[1]
    users = [p.relative_to(app_dir).as_posix() for p in app_dir.rglob("*.py")
             if p.name != "overforecast.py" and "overforecast" in p.read_text(encoding="utf-8")]
    assert users == []
    assert "weights=" not in inspect.getsource(model.backtest)


def test_defaults_keep_price_on_customer_off_and_the_sku_x_fc_grain():
    m = ss.ModelSettings()
    assert m.feature_price is True and m.feature_customer is False
    assert ss.BigQuerySettings().customer_id_column == ""
    from app.ml.features import feature_names
    names = feature_names(m)
    assert "sku_code" in names and "fc_code" in names and not any("status" in n for n in names)
