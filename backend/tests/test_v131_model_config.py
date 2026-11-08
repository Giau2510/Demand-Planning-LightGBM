"""1.3.1 "LightGBM chot" (C3-A1): configuration rules of the model, written BEFORE the code (test-first).

Authoritative rules: docs/ke_hoach_lgbm_chot.md sections 1, 2, 6.1 (settings, T0) and 6.2 (B1 35 features without
sku_code + horizon weights, B2 fallback switch, B11 feature table, fingerprint; T1). Every new key at its default must
give exactly the 1.2.14 behaviour (feature list, matrices, model, fingerprint 8468ebe66d1706f7 of the production model).
Synthetic data only (conftest isolation for the few settings writes); no BigQuery, no network.
"""
import hashlib
import json
from datetime import date, timedelta
from types import SimpleNamespace

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app import settings_service as ss
from app.ml import features, model, pipeline
from app.ml.features import build_panel, static_codes

# new ModelSettings keys and the value that means "as 1.2.14" (left out of the fingerprint at that value)
NEW_MODEL_DEFAULTS = {"horizon_weight_short": None, "horizon_weight_cutoff": None, "feature_sku_code": True,
                      "fallback_enabled": True, "feature_table": None,
                      # 1.3.2 (G3-T0): at their default they stay out of the fingerprint like the 1.3.1 keys
                      "feature_set": "CHOT", "ly_history_start": None}
# ModelSettings fields of 1.2.14 (af835b8), in declaration order
MODEL_FIELDS_1214 = [
    "feature_lags", "feature_rolling", "feature_calendar", "feature_price", "feature_promotion", "feature_discount",
    "feature_weekday", "feature_open_hours", "weekday_encoding", "feature_customer", "feature_min_coverage",
    "min_total_history_days", "min_series_history_days", "intermittent_zero_share", "inactive_days",
    "fallback_window_days", "backtest_folds", "backtest_horizon_days", "backtest_step_days", "num_boost_round",
    "learning_rate", "num_leaves", "objective", "max_train_days", "num_threads", "forecast_strategy", "direct_origins",
    "direct_origin_step_days"]
# fingerprints computed with the 1.2.14 code (sha256(json.dumps(model_dump, sort_keys=True))[:16]); the production one
# is the fingerprint of the model in use quoted by the plan (section 2)
FP_DEFAULT_1214 = "7134c10dd9b8dab0"
FP_PROD_1214 = "8468ebe66d1706f7"
PARAMS_1214 = {"objective": "tweedie", "learning_rate": 0.05, "num_leaves": 31, "min_data_in_leaf": 20,
               "feature_fraction": 0.9, "bagging_fraction": 0.9, "bagging_freq": 1, "lambda_l2": 1.0, "verbose": -1,
               "seed": 7, "deterministic": True, "force_row_wise": True, "tweedie_variance_power": 1.2}
# B1: the 35 features of the production configuration without sku_code, in model order (plan 6.2)
B1_NAMES = [
    "fc_code", "series_age", "lag_1", "lag_2", "lag_3", "lag_4", "lag_5", "lag_6", "lag_7", "lag_14", "lag_21", "lag_28",
    "roll_mean_7", "roll_mean_14", "roll_mean_28", "roll_mean_56", "roll_std_7", "roll_std_28", "zero_share_28",
    "days_since_last_sale", "roll_max_28", "price_last", "price_rel_28", "open_hours_last", "open_hours_mean_7",
    "cust_mean_28", "cust_repeat_share_28", "cust_repeat_interval_28", "dow", "dom", "month", "weekofyear",
    "is_weekend", "days_to_month_end", "horizon"]

OH = {"feature_open_hours": True, "weekday_encoding": "ISO"}        # set by the training, never by the user
PROD = {"forecast_strategy": "DIRECT", "feature_customer": True, "feature_promotion": False, "feature_discount": False}
FAST = {"num_boost_round": 20, "backtest_folds": 2, "backtest_horizon_days": 14, "backtest_step_days": 14,
        "direct_origins": 4, "direct_origin_step_days": 7}
H = 14                                                              # = backtest_horizon_days of FAST


def _sha16(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


def _prod(**kw):
    """Production-like configuration (DIRECT, open hours, customers, ISO weekday), default training sizes."""
    return ss.ModelSettings(**PROD, **kw).model_copy(update=OH)


def _fast(**kw):
    """The same configuration with small training sizes (seconds)."""
    return ss.ModelSettings(**PROD, **FAST, **kw).model_copy(update=OH)


def _with_table(cfg, rules: dict):
    return cfg.model_copy(update={"feature_table": {k: ss.FeatureRule(**v) for k, v in rules.items()}})


def _demand(days=84, seed=5):
    """4 SKUs x 2 FCs (S3 starts on day 30), with price, open hours and customer counts on every demand row."""
    rng = np.random.default_rng(seed)
    start = date(2026, 1, 1)
    rows = []
    for t in range(days):
        for s in range(4):
            for fc in ("F1", "F2"):
                if s == 3 and t < 30:
                    continue
                rows.append({"order_date": str(start + timedelta(days=t)), "sku_id": f"S{s}", "fc_id": fc,
                             "qty": float(rng.poisson(3 + 2 * s + (t % 7 == 5) * 4)), "avg_unit_price": 10.0 + s,
                             "open_hours": float(rng.choice([24.0, 12.0, 8.0])),
                             "customer_count": float(rng.integers(1, 5)),
                             "repeat_customer_count": float(rng.integers(0, 2)),
                             "repeat_interval_days_sum": float(rng.integers(0, 9))})
    return pd.DataFrame(rows)


def _panel(days=84):
    return build_panel(_demand(days))


def _categorical(booster) -> set[str]:
    """Features LightGBM treats as categorical (their feature_infos list category values, not a [min:max] range)."""
    line = next(x for x in booster.model_to_string().splitlines() if x.startswith("feature_infos="))
    infos = line.split("=", 1)[1].split(" ")
    return {n for n, i in zip(booster.feature_name(), infos) if i != "none" and not i.startswith("[")}


def _refused(code: str | None, fn):
    with pytest.raises(ValidationError) as e:
        fn()
    if code:
        assert code in str(e.value)


# ------------------------------------------------------------------ 6.1 settings (T0)
def test_model_settings_new_fields_default_to_1_2_14():
    m = ss.ModelSettings()
    assert m.feature_sku_code is True
    assert m.fallback_enabled is True
    assert (m.horizon_weight_short, m.horizon_weight_cutoff) == (None, None)
    assert m.feature_table is None
    assert set(m.model_dump()) == set(MODEL_FIELDS_1214) | set(NEW_MODEL_DEFAULTS)


def test_feature_rule_and_feature_table_defaults():
    r = ss.FeatureRule()
    assert (r.enabled, r.contri) == (True, 1.0)
    assert ss.FeatureTableSettings().features == {}
    assert ss.SECTIONS["feature_table"] is ss.FeatureTableSettings
    assert ss.get("feature_table").features == {}                   # nothing stored: the default


def test_daily_forecast_defaults_and_section():
    d = ss.DailyForecastSettings()
    assert (d.enabled, d.trial_mode, d.rounding_threshold, d.log_retention_days) == (False, True, 0.2, 120)
    assert d.openhours_table == "lakehouse-prod-394907.gold_buymed_vn2.openhours_by_sku"
    assert (d.seller_code, d.report_subdir) == ("MEDX", "theo-doi")
    assert ss.SECTIONS["daily_forecast"] is ss.DailyForecastSettings
    g = ss.get("daily_forecast")                                     # nothing stored: off, trial mode on
    assert (g.enabled, g.trial_mode) == (False, True)


NEW_SCHEDULE = {"refresh_enabled": False, "refresh_enabled_at": None, "refresh_deadline": "12:00",
                "refresh_retry_minutes": 10, "report_enabled": False, "report_enabled_at": None,
                "report_weekday": 1, "report_time": "09:30"}


def test_schedule_new_defaults_are_off():
    s = ss.ScheduleSettings()
    assert {k: getattr(s, k) for k in NEW_SCHEDULE} == NEW_SCHEDULE
    # the 1.2.14 flows keep their defaults
    assert (s.d1_enabled, s.d0_enabled, s.train_enabled, s.train_time) == (False, False, True, "07:00")


def test_stored_1_2_14_sections_read_the_new_keys_at_their_defaults():
    old_model = {k: v for k, v in _prod().model_dump().items() if k in MODEL_FIELDS_1214}
    m = ss.ModelSettings.model_validate(old_model)
    assert {k: getattr(m, k) for k in NEW_MODEL_DEFAULTS} == NEW_MODEL_DEFAULTS
    old_schedule = {k: v for k, v in ss.ScheduleSettings(d1_enabled=True, train_time="08:20").model_dump().items()
                    if k not in NEW_SCHEDULE}
    s = ss.ScheduleSettings.model_validate(old_schedule)
    assert (s.d1_enabled, s.train_time) == (True, "08:20")
    assert {k: getattr(s, k) for k in NEW_SCHEDULE} == NEW_SCHEDULE


@pytest.mark.parametrize("kw", [{"horizon_weight_short": 3.0}, {"horizon_weight_cutoff": 7}])
def test_one_horizon_weight_field_alone_is_refused(kw):
    _refused("HORIZON_WEIGHT_INCOMPLETE", lambda: ss.ModelSettings(forecast_strategy="DIRECT", **kw))


@pytest.mark.parametrize("strategy", [None, "RECURSIVE"])
def test_horizon_weights_need_the_direct_strategy(strategy):
    kw = {"horizon_weight_short": 3.0, "horizon_weight_cutoff": 7, **({"forecast_strategy": strategy} if strategy else {})}
    _refused("HORIZON_WEIGHT_DIRECT_ONLY", lambda: ss.ModelSettings(**kw))


@pytest.mark.parametrize("short, cutoff", [(0.0, 7), (-1.0, 7), (3.0, 0), (3.0, -2)])
def test_horizon_weight_out_of_range_is_refused(short, cutoff):
    _refused(None, lambda: ss.ModelSettings(forecast_strategy="DIRECT", horizon_weight_short=short,
                                            horizon_weight_cutoff=cutoff))


def test_horizon_weights_accepted_with_direct():
    m = ss.ModelSettings(forecast_strategy="DIRECT", horizon_weight_short=3.0, horizon_weight_cutoff=7)
    assert (m.horizon_weight_short, m.horizon_weight_cutoff) == (3.0, 7)
    m = ss.ModelSettings(forecast_strategy="DIRECT", horizon_weight_short=0.5, horizon_weight_cutoff=1)
    assert (m.horizon_weight_short, m.horizon_weight_cutoff) == (0.5, 1)


def test_a_settings_update_with_one_weight_field_stores_nothing():
    before = ss.get("model").model_dump()
    with pytest.raises(ValidationError, match="HORIZON_WEIGHT_INCOMPLETE"):
        ss.update("model", {"forecast_strategy": "DIRECT", "horizon_weight_short": 3.0})
    assert ss.get("model").model_dump() == before


@pytest.mark.parametrize("rule", [{"enabled": True}, {"enabled": False}, {"contri": 2.0}])
def test_feature_table_refuses_sku_code(rule):
    # B1 (model.feature_sku_code) controls sku_code, never the feature table
    _refused("FEATURE_NOT_IN_TABLE", lambda: ss.FeatureTableSettings(features={"sku_code": rule}))


def test_feature_table_refuses_turning_horizon_off():
    _refused("FEATURE_REQUIRED", lambda: ss.FeatureTableSettings(features={"horizon": {"enabled": False}}))
    ok = ss.FeatureTableSettings(features={"horizon": {"contri": 2.0}})          # only switching it off is refused
    assert ok.features["horizon"].contri == 2.0


@pytest.mark.parametrize("contri", [0.0, -1.0, 10.0001, 11.0])
def test_feature_rule_contri_out_of_range_is_refused(contri):
    _refused(None, lambda: ss.FeatureRule(contri=contri))
    _refused(None, lambda: ss.FeatureTableSettings(features={"lag_1": {"contri": contri}}))


@pytest.mark.parametrize("contri", [0.01, 1.0, 10.0])
def test_feature_rule_contri_in_range_is_accepted(contri):
    assert ss.FeatureTableSettings(features={"lag_1": {"contri": contri}}).features["lag_1"].contri == contri


@pytest.mark.parametrize("name", ["Lag-1", "Lag_1", "lag-1", "1lag", "_lag", "", "lag 1", "a" * 65])
def test_feature_table_bad_names_are_refused(name):
    _refused(None, lambda: ss.FeatureTableSettings(features={name: {"enabled": False}}))


@pytest.mark.parametrize("name", ["lag_1", "dom", "a" * 64])
def test_feature_table_good_names_are_accepted(name):
    assert name in ss.FeatureTableSettings(features={name: {"enabled": False}}).features


@pytest.mark.parametrize("kw", [{"rounding_threshold": -0.01}, {"rounding_threshold": 1.01},
                                {"log_retention_days": 13}, {"log_retention_days": 3651},
                                {"openhours_table": "gold_buymed_vn2.openhours_by_sku"}, {"openhours_table": "x"},
                                {"openhours_table": "p.d.t; DROP TABLE x"},
                                {"seller_code": "ME DX"}, {"seller_code": "a/b"},
                                {"report_subdir": "..\\up"}, {"report_subdir": "a/b"}, {"report_subdir": "a b"},
                                {"report_subdir": ".."}])
def test_daily_forecast_bad_values_are_refused(kw):
    _refused(None, lambda: ss.DailyForecastSettings(**kw))


def test_daily_forecast_edge_values_are_accepted():
    for kw in ({"rounding_threshold": 0.0}, {"rounding_threshold": 1.0}, {"log_retention_days": 14},
               {"log_retention_days": 3650}, {"report_subdir": "theo-doi_2"}, {"seller_code": "MEDX_2"},
               {"openhours_table": "my-project-1.ds.openhours_by_sku"}):
        d = ss.DailyForecastSettings(**kw)
        assert {k: getattr(d, k) for k in kw} == kw


@pytest.mark.parametrize("field, value", [("refresh_deadline", "25:00"), ("refresh_deadline", "24:00"),
                                          ("refresh_deadline", "5:55"), ("refresh_deadline", "12:60"),
                                          ("refresh_deadline", ""), ("report_time", "9h30"),
                                          ("report_time", "09:30:00"), ("report_weekday", 0), ("report_weekday", 8),
                                          ("refresh_retry_minutes", 0), ("refresh_retry_minutes", 61)])
def test_schedule_bad_new_values_are_refused(field, value):
    _refused(None, lambda: ss.ScheduleSettings(**{field: value}))


def test_schedule_edge_new_values_are_accepted():
    s = ss.ScheduleSettings(refresh_deadline="00:00", report_time="23:59", report_weekday=7, refresh_retry_minutes=60)
    assert (s.refresh_deadline, s.report_time, s.report_weekday, s.refresh_retry_minutes) == ("00:00", "23:59", 7, 60)
    s = ss.ScheduleSettings(report_weekday=1, refresh_retry_minutes=1)
    assert (s.report_weekday, s.refresh_retry_minutes) == (1, 1)


# ------------------------------------------------------------------ 6.2 B1 feature names (T1)
def test_b1_feature_names_with_and_without_sku_code():
    full = _prod()
    names = features.feature_names(full)
    assert len(names) == 36 and names[0] == "sku_code"              # unchanged 1.2.14 list
    assert names == ["sku_code"] + B1_NAMES
    assert features.dropped_features(full) == set()
    b1 = _prod(feature_sku_code=False)
    assert features.feature_names(b1) == B1_NAMES                   # exactly the 35 names, same order
    assert features.dropped_features(b1) == {"sku_code"}


def test_dropped_features_also_takes_the_disabled_rows_of_the_feature_table():
    assert features.dropped_features(SimpleNamespace()) == set()    # configurations without the new attributes
    b1 = _prod(feature_sku_code=False)
    cfg = _with_table(b1, {"lag_1": {"enabled": False}, "dom": {"contri": 2.0}})   # contri alone drops nothing
    assert features.dropped_features(cfg) == {"sku_code", "lag_1"}
    assert features.feature_names(cfg) == [n for n in B1_NAMES if n != "lag_1"]
    full = _with_table(_prod(), {"lag_1": {"enabled": False}})
    assert features.dropped_features(full) == {"lag_1"}
    assert features.feature_names(full) == ["sku_code"] + [n for n in B1_NAMES if n != "lag_1"]


def test_the_snapshot_of_the_table_drives_the_features_and_survives_a_reload():
    snap = pipeline.feature_table_snapshot(ss.FeatureTableSettings(
        features={"lag_1": {"enabled": False}, "dom": {"contri": 2.0}, "lag_2": {}}))
    cfg = _prod(feature_sku_code=False).model_copy()
    cfg.feature_table = snap                         # what train_and_publish does before the training (plan 6.2)
    names = features.feature_names(cfg)
    assert names == [n for n in B1_NAMES if n != "lag_1"]
    assert model.lgb_params(cfg, names=names)["feature_contri"] == [2.0 if n == "dom" else 1.0 for n in names]
    # the configuration stored with the run reloads to exactly the same feature list and fingerprint
    again = ss.ModelSettings.model_validate(json.loads(json.dumps(cfg.model_dump())))
    assert features.feature_names(again) == names
    assert pipeline.config_fingerprint(again.model_dump()) == pipeline.config_fingerprint(cfg.model_dump())


# ------------------------------------------------------------------ 6.2 B1 matrix values (T1)
def _without(X, names, drop):
    keep = [i for i, n in enumerate(names) if n not in drop]
    return X[:, keep]


def test_b1_direct_matrix_is_the_1_2_14_matrix_without_the_dropped_columns():
    p = _panel()
    full, b1 = _fast(), _fast(feature_sku_code=False)
    names = features.feature_names(full)
    Xf, yf = features.direct_training_matrix(p, full, H)
    Xb, yb = features.direct_training_matrix(p, b1, H)
    assert Xf.shape[1] == 36 and Xb.shape[1] == 35 == len(features.feature_names(b1))
    assert np.array_equal(Xb, _without(Xf, names, {"sku_code"}), equal_nan=True)
    assert np.array_equal(yb, yf)
    Xf2, yf2, ixf = features.direct_training_matrix(p, full, H, with_index=True)
    Xb2, yb2, ixb = features.direct_training_matrix(p, b1, H, with_index=True)
    assert np.array_equal(Xb2, _without(Xf2, names, {"sku_code"}), equal_nan=True)
    assert np.array_equal(yb2, yf2) and np.array_equal(ixb, ixf)
    # + rules of the feature table: an origin feature and a target-day calendar feature dropped
    tb = _with_table(b1, {"lag_1": {"enabled": False}, "dom": {"enabled": False}})
    Xt, yt = features.direct_training_matrix(p, tb, H)
    assert Xt.shape[1] == 33 == len(features.feature_names(tb))
    assert np.array_equal(Xt, _without(Xf, names, {"sku_code", "lag_1", "dom"}), equal_nan=True)
    assert np.array_equal(yt, yf)


def test_b1_origin_features_and_direct_extra_drop_only_their_columns():
    p = _panel()
    full, b1 = _fast(), _fast(feature_sku_code=False)
    sc, fcc = static_codes(p)
    t0 = p.T - 7
    of = features.origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, t0, full, sc, fcc)
    ob = features.origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, t0, b1, sc, fcc)
    assert np.array_equal(ob, of[:, 1:], equal_nan=True)            # sku_code is the first column
    day = p.dates[t0 + 2]
    ef = features.direct_extra(full, day, 3)
    assert features.direct_extra(b1, day, 3) == ef                  # target calendar + horizon: no sku_code there
    tail = features.calendar_names(full) + ["horizon"]
    tb = _with_table(b1, {"dom": {"enabled": False}})
    assert features.direct_extra(tb, day, 3) == [v for n, v in zip(tail, ef) if n != "dom"]
    # the extra columns are appended to the origin features of the same configuration: full width of the names
    assert ob.shape[1] + len(features.direct_extra(b1, day, 3)) == len(features.feature_names(b1))


def test_b1_recursive_matrix_drops_the_same_columns():
    p = _panel()
    full = ss.ModelSettings(feature_customer=True).model_copy(update=OH)
    b1 = ss.ModelSettings(feature_customer=True, feature_sku_code=False).model_copy(update=OH)
    names = features.feature_names(full)
    assert features.feature_names(b1) == names[1:]
    Xf, yf = features.training_matrix(p, full)
    Xb, yb = features.training_matrix(p, b1)
    assert np.array_equal(Xb, Xf[:, 1:], equal_nan=True) and np.array_equal(yb, yf)
    tb = _with_table(b1, {"dom": {"enabled": False}, "roll_std_7": {"enabled": False}})
    Xt, _ = features.training_matrix(p, tb)
    assert np.array_equal(Xt, _without(Xf, names, {"sku_code", "dom", "roll_std_7"}), equal_nan=True)


def test_an_empty_direct_matrix_has_the_reduced_width():
    p = _panel().truncate(10)                                       # no origin t0 >= 7 with t0 = T - 7 j
    X, y = features.direct_training_matrix(p, _fast(feature_sku_code=False), H)
    assert X.shape == (0, 35) and len(y) == 0


# ------------------------------------------------------------------ 6.2 B1 training (T1)
def test_default_configuration_trains_exactly_the_1_2_14_model():
    p = _panel()
    cfg = _fast()
    booster, info = model.train(p, cfg)
    X, y = features.direct_training_matrix(p, cfg, H)
    names = features.feature_names(cfg)
    ds = lgb.Dataset(X, y, feature_name=names, categorical_feature=["sku_code", "fc_code"], free_raw_data=True)
    manual = lgb.train(PARAMS_1214, ds, num_boost_round=cfg.num_boost_round)
    assert booster.model_to_string() == manual.model_to_string()
    assert _categorical(booster) == {"sku_code", "fc_code"}
    assert "feature_importance" in info                              # 1.2.14 key kept


def test_b1_training_without_sku_code_with_horizon_weights():
    p = _panel()
    cfg = _fast(feature_sku_code=False, horizon_weight_short=3.0, horizon_weight_cutoff=7)
    booster, info = model.train(p, cfg)
    names = features.feature_names(cfg)
    assert names == B1_NAMES
    assert booster.feature_name() == names
    assert _categorical(booster) == {"fc_code"}                     # only the code still in the features
    X, y = features.direct_training_matrix(p, cfg, H)
    hz = X[:, names.index("horizon")]
    assert hz.min() == 1 and hz.max() == H
    n_short = int(np.sum(hz <= 7))
    assert 0 < n_short < len(hz) == info["n_rows"]
    assert info["horizon_weight"] == {"short": 3.0, "cutoff": 7, "rows_weighted": n_short}
    # the same model as the recipe of plan 6.2: weight 3.0 where horizon <= 7 else 1.0, categorical = fc_code only
    w = np.where(hz <= 7, 3.0, 1.0)
    ds = lgb.Dataset(X, y, weight=w, feature_name=names, categorical_feature=["fc_code"], free_raw_data=True)
    manual = lgb.train(model.lgb_params(cfg), ds, num_boost_round=cfg.num_boost_round)
    assert booster.model_to_string() == manual.model_to_string()
    # every feature with its gain and split count
    full = info["feature_importance_full"]
    assert len(full) == len(names) and sorted(r["feature"] for r in full) == sorted(names)
    gain = dict(zip(names, booster.feature_importance(importance_type="gain")))
    split = dict(zip(names, booster.feature_importance(importance_type="split")))
    for r in full:
        assert r["gain"] == pytest.approx(float(gain[r["feature"]]))
        assert r["split"] == int(split[r["feature"]])
    # the model forecasts with its own (35-column) rows
    fc = model.forecast(p, booster, cfg, 7)
    assert fc["yhat"].shape == (p.n_series, 7) and np.isfinite(fc["yhat"]).all() and (fc["yhat"] >= 0).all()


# ------------------------------------------------------------------ 6.2 B11 identity, lgb_params, fingerprint (T1)
def test_default_feature_tables_train_the_same_model():
    p = _panel()
    base = _fast(feature_sku_code=False, fallback_enabled=False, horizon_weight_short=3.0, horizon_weight_cutoff=7)
    snap = pipeline.feature_table_snapshot(ss.FeatureTableSettings())
    assert snap is None
    ref, _ = model.train(p, base)
    s = ref.model_to_string()
    for cfg in (base.model_copy(update={"feature_table": {}}), base.model_copy(update={"feature_table": snap}),
                _with_table(base, {"lag_2": {}})):                   # an explicit default row changes nothing
        b, _ = model.train(p, cfg)
        assert b.model_to_string() == s
    fp = pipeline.config_fingerprint(base.model_dump())
    assert pipeline.config_fingerprint(base.model_copy(update={"feature_table": snap}).model_dump()) == fp


def test_a_contri_rule_reaches_lightgbm_aligned_with_the_names():
    p = _panel()
    cfg = _with_table(_fast(feature_sku_code=False), {"lag_1": {"contri": 2.0}})
    names = features.feature_names(cfg)
    booster, _ = model.train(p, cfg)
    want = "[feature_contri: " + ",".join("2" if n == "lag_1" else "1" for n in names) + "]"
    assert want in booster.model_to_string().splitlines()


def test_lgb_params_without_names_is_1_2_14_and_with_names_adds_feature_contri():
    assert model.lgb_params(ss.ModelSettings()) == PARAMS_1214
    assert model.lgb_params(_prod()) == PARAMS_1214
    b1 = _prod(feature_sku_code=False)
    names = features.feature_names(b1)
    assert model.lgb_params(b1, names=names) == PARAMS_1214                      # no rule: no feature_contri
    off = _with_table(b1, {"lag_2": {"enabled": False}})                         # contri 1 everywhere
    assert "feature_contri" not in model.lgb_params(off, names=features.feature_names(off))
    cfg = _with_table(b1, {"lag_1": {"contri": 2.0}})
    assert model.lgb_params(cfg) == PARAMS_1214                                  # names not given: as 1.2.14
    p = model.lgb_params(cfg, names=names)
    assert p["feature_contri"] == [2.0 if n == "lag_1" else 1.0 for n in names]
    assert {k: v for k, v in p.items() if k != "feature_contri"} == PARAMS_1214
    assert model.lgb_params(cfg, seed=11, names=names)["seed"] == 11


def test_config_fingerprint_keeps_the_1_2_14_formula():
    for cfg, golden in ((ss.ModelSettings(), FP_DEFAULT_1214), (_prod(), FP_PROD_1214)):
        d = cfg.model_dump()
        old = {k: v for k, v in d.items() if k not in NEW_MODEL_DEFAULTS}
        assert set(old) == set(MODEL_FIELDS_1214)
        assert _sha16(old) == golden                                 # the stored 1.2.14 value
        assert pipeline.config_fingerprint(d) == golden
        assert pipeline.config_fingerprint(old) == golden            # a run stored by 1.2.14 (no new key at all)


@pytest.mark.parametrize("change", [{"feature_sku_code": False}, {"fallback_enabled": False},
                                    {"horizon_weight_short": 3.0, "horizon_weight_cutoff": 7},
                                    {"feature_table": {"lag_1": {"enabled": False, "contri": 1.0}}},
                                    {"feature_sku_code": False, "fallback_enabled": False,
                                     "horizon_weight_short": 3.0, "horizon_weight_cutoff": 7}])
def test_a_non_default_new_key_enters_the_fingerprint(change):
    d = {**_prod().model_dump(), **change}
    old = {k: v for k, v in d.items() if k not in NEW_MODEL_DEFAULTS}
    fp = pipeline.config_fingerprint(d)
    assert fp == _sha16({**old, **change})                           # only the keys away from their default added
    assert fp != FP_PROD_1214


def test_feature_table_snapshot_keeps_only_the_non_default_rows():
    assert pipeline.feature_table_snapshot(ss.FeatureTableSettings()) is None
    assert pipeline.feature_table_snapshot(ss.FeatureTableSettings(
        features={"lag_1": {}, "dom": {"enabled": True, "contri": 1.0}})) is None
    snap = pipeline.feature_table_snapshot(ss.FeatureTableSettings(
        features={"lag_1": {"enabled": False}, "dom": {"contri": 2.0}, "lag_2": {}}))
    rows = {k: (v.model_dump() if hasattr(v, "model_dump") else dict(v)) for k, v in snap.items()}
    assert rows == {"lag_1": {"enabled": False, "contri": 1.0}, "dom": {"enabled": True, "contri": 2.0}}


# ------------------------------------------------------------------ 6.2 B2 fallback switch (T1)
def _series_panel(n=120):
    series = {
        ("STABLE", "F"): [5] * n,
        ("NEW", "F"): [None] * (n - 10) + [4] * 10,
        ("INTER", "F"): [3 if i % 15 == 0 else 0 for i in range(n)],
        ("DEAD", "F"): [5] * 40 + [0] * (n - 40),
    }
    rows = [{"order_date": str((pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)).date()), "sku_id": sku,
             "fc_id": fc, "qty": float(v), "avg_unit_price": 10.0, "avg_discount_rate": 0.0, "promo_share": 0.0}
            for (sku, fc), vals in series.items() for i, v in enumerate(vals) if v is not None]
    return build_panel(pd.DataFrame(rows))


def test_fallback_rules_unchanged_by_default():
    p = _series_panel()
    d = model.classification_details(p, ss.ModelSettings())
    sku = [k[0] for k in p.keys]
    assert dict(zip(sku, d["methods"])) == {"STABLE": model.METHOD_LGBM, "NEW": model.FB_NEW,
                                            "INTER": model.FB_INTERMITTENT, "DEAD": model.FB_INACTIVE}
    assert dict(zip(sku, d["reasons"])) == {"STABLE": "LIGHTGBM_ELIGIBLE", "NEW": "NEW_SERIES",
                                            "INTER": "INTERMITTENT", "DEAD": "INACTIVE"}
    rate = dict(zip(sku, d["rate"]))
    assert rate["STABLE"] == 0.0 and rate["DEAD"] == 0.0
    assert rate["NEW"] == pytest.approx(4.0)                         # all known days since the start
    assert rate["INTER"] == pytest.approx(3 / 28)                    # last 28 days: one order of 3 (day 105)


def test_fallback_disabled_sends_every_series_to_lightgbm():
    p = _series_panel()
    on = model.classification_details(p, ss.ModelSettings())
    off = model.classification_details(p, ss.ModelSettings(fallback_enabled=False))
    S = p.n_series
    assert list(off["methods"]) == [model.METHOD_LGBM] * S
    assert list(off["reasons"]) == ["LIGHTGBM_ELIGIBLE"] * S
    assert np.array_equal(off["rate"], np.zeros(S))
    # every explanatory quantity is still computed as before
    assert set(off) == set(on)
    for k in set(on) - {"methods", "reasons", "rate"}:
        assert np.array_equal(np.asarray(off[k]), np.asarray(on[k])), k
    methods, rate = model.classify_series(p, ss.ModelSettings(fallback_enabled=False))
    assert list(methods) == [model.METHOD_LGBM] * S and np.array_equal(rate, np.zeros(S))
    cfg = ss.ModelSettings(fallback_enabled=False, num_boost_round=20)
    booster, _ = model.train(p, cfg)
    assert booster is not None
    fc = model.forecast(p, booster, cfg, 5)
    assert list(fc["methods"]) == [model.METHOD_LGBM] * S
    assert np.isfinite(fc["yhat"]).all() and (fc["yhat"] >= 0).all()
