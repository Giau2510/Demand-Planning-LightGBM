"""1.2.0: DIRECT multi-horizon strategy (experiment L7_direct) in the production pipeline, and the documented
quality-gate exception for ONE training run (standard thresholds never changed, no general bypass)."""
import json
from datetime import date, timedelta

import lightgbm as lgb
import numpy as np
import pytest

from app import db, paths
from app import settings_service as ss
from app.messages import AppError
from app.ml import model, pipeline
from app.ml.features import CALENDAR, direct_training_matrix, feature_names, origin_features, static_codes

from test_v117 import _dataset, _freeze, _panel, _tr


def _cfg(**kw):
    return ss.ModelSettings(forecast_strategy="DIRECT", num_boost_round=20, backtest_folds=2, backtest_horizon_days=14,
                            backtest_step_days=14, direct_origins=4, direct_origin_step_days=7, **kw)


# ------------------------------------------------------------------ strategy
def test_direct_feature_layout_and_recursive_models_are_unchanged():
    rec = ss.ModelSettings()
    d = ss.ModelSettings(forecast_strategy="DIRECT")
    assert "horizon" not in feature_names(rec)
    names = feature_names(d)
    assert names[-1] == "horizon" and names[-7:-1] == CALENDAR
    assert sorted(names[:-7]) == sorted(n for n in feature_names(rec) if n not in CALENDAR)
    # a configuration stored before 1.2.0 has no strategy field: it stays RECURSIVE
    old = ss.ModelSettings.model_validate({k: v for k, v in rec.model_dump().items() if k != "forecast_strategy"})
    assert old.forecast_strategy == "RECURSIVE" and feature_names(old) == feature_names(rec)


def test_direct_features_use_only_data_before_the_origin():
    p = _panel(120)
    cfg = _cfg()
    sc, fcc = static_codes(p)
    t0 = 100
    a = origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, t0, cfg, sc, fcc)
    q = p.truncate(p.T)
    q.Y[:, t0:] = 9999.0                                      # anything at or after the origin must not matter
    b = origin_features(q, q.Y, q.price, q.disc, q.promo, q.dates, t0, cfg, sc, fcc)
    assert np.array_equal(a, b, equal_nan=True)
    X, y = direct_training_matrix(p, cfg, 14)
    assert X.shape[1] == len(feature_names(cfg))
    hz = X[:, -1]
    assert hz.min() == 1 and hz.max() == 14
    # rows: 4 origins (T-7, T-14, T-21, T-28) x horizons inside the data x 3 series
    T = p.T
    assert len(y) == 3 * sum(min(14, T - (T - 7 * j)) for j in range(1, 5))


def test_direct_forecast_is_not_recursive_well_formed_and_reloads_identically(tmp_path):
    p = _panel(150)
    cfg = _cfg()
    booster, info = model.train(p, cfg)
    assert info["forecast_strategy"] == "DIRECT" and booster.num_feature() == len(feature_names(cfg))
    fc = model.forecast(p, booster, cfg, 14, capture=0)
    y = fc["yhat"]
    assert y.shape == (3, 14) and np.isfinite(y).all() and (y >= 0).all()
    assert str(fc["dates"][0].date()) == str((p.dates[-1] + timedelta(days=1)).date())
    assert all((b - a).days == 1 for a, b in zip(fc["dates"][:-1], fc["dates"][1:]))
    rows = np.vstack(fc["captured"])
    n_origin = len(feature_names(cfg)) - 7
    assert all(np.array_equal(r[:n_origin], rows[0, :n_origin], equal_nan=True) for r in rows)   # same origin features
    assert list(rows[:, -1]) == list(range(1, 15))
    mp = tmp_path / "m.txt"
    booster.save_model(str(mp))
    again = model.forecast(p, lgb.Booster(model_file=str(mp)), cfg, 14)
    assert np.array_equal(again["yhat"], y)
    with pytest.raises(ValueError, match="DIRECT_HORIZON_EXCEEDS_TRAINING"):
        model.forecast(p, booster, cfg, 15)


def test_direct_backtest_never_sees_the_evaluated_window(monkeypatch):
    seen = []
    real = model.train

    def spy(p, c, cancel=None):
        seen.append(p.dates[-1])
        return real(p, c, cancel)
    monkeypatch.setattr(model, "train", spy)
    bt = model.backtest(_panel(150), _cfg(), collect=True)
    assert len(bt["folds"]) == 2
    for f, last in zip(bt["folds"], seen):
        assert (np.datetime64(f["origin"]) - np.datetime64(last.date())).astype(int) == 1
    assert all(pt["date"] >= pt["origin"] for pt in bt["points"])


# ------------------------------------------------------------------ pipeline + documented gate exception
def _direct_settings(**quality):
    ss.update("model", {"forecast_strategy": "DIRECT", "direct_origins": 4, "direct_origin_step_days": 7})
    ss.update("horizons", {"enabled": [7]})
    if quality:
        # 1.2.2: the documented gate exception belongs to the BLOCK policy (a failed gate rejects only under BLOCK)
        ss.update("quality", {"below_threshold_policy": "BLOCK", **quality})


def _approval(run_id, tr, **kw):
    m = json.loads(tr["metrics_json"])
    a = {"confirm_text": f"EXCEPTION-{run_id}", "approved_by": "Chu du an", "review_by": "2026-06-30",
         "reason": "Nhu cau bat on trong giai doan dieu chinh dong tien; chap nhan van hanh",
         "acknowledged_wape": round(m["wape"], 3), "acknowledged_bias": round(m["bias"], 3)}
    a.update(kw)
    return a


def test_gate_exception_releases_exactly_one_run_and_never_changes_the_gate(client, fast_model):
    _freeze(2026, 3, 15)
    _dataset(client, date(2026, 1, 1), date(2026, 3, 14))
    _direct_settings(wape_max=0.0001)                 # nothing can pass: the gate rejects on WAPE
    r = pipeline.train_and_publish(force=True)
    assert r["status"] == "REJECTED" and r["reason_code"] == "QUALITY_GATE_FAILED", r
    rid = r["training_run_id"]
    tr = _tr(rid)
    assert tr["model_path"] and (paths.models_dir() / tr["model_path"]).is_file()      # kept for review only
    meta = json.loads((paths.models_dir() / tr["model_path"].replace(".txt", ".json")).read_text(encoding="utf-8"))
    assert meta["forecast_strategy"] == "DIRECT" and meta["max_horizon"] == 7 and meta["features"][-1] == "horizon"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM forecast_runs").fetchone()[0] == 0
    d = client.get(f"/api/training-runs/{rid}").json()
    assert d["gate_exception"]["eligible"] and not d["can_promote"]
    url = f"/api/training-runs/{rid}/release-with-exception"
    bad = [({"confirm_text": "yes"}, "CONFIRMATION_MISMATCH"), ({"reason": "too short"}, "VALIDATION_ERROR"),
           ({"review_by": "2026-03-01"}, "VALIDATION_ERROR"), ({"acknowledged_wape": 0.0}, "VALIDATION_ERROR"),
           ({"approved_by": ""}, "VALIDATION_ERROR")]
    for patch_, code in bad:
        x = client.post(url, json=_approval(rid, tr, **patch_))
        assert x.status_code == 422 and x.json()["code"] == code, (patch_, x.text)
    ok = client.post(url, json=_approval(rid, tr))
    assert ok.status_code == 200, ok.text
    fr = ok.json()["forecast_run_id"]
    t2 = _tr(rid)
    gate = json.loads(t2["quality_gate_json"])
    assert t2["status"] == "ACCEPTED" and t2["reject_reason"] is None
    exc = gate["exception"]
    assert exc["scope"] == "THIS_TRAINING_RUN_ONLY" and exc["standard_gate_changed"] is False
    assert exc["failed_checks"] == ["WAPE_MAX"] and exc["standard_thresholds"]["WAPE_MAX"] == 0.0001
    assert ss.get("quality").wape_max == 0.0001                       # the standard gate itself is untouched
    a = client.get(f"/api/training-runs/{rid}").json()["assessment"]   # 1.2.2: shown as usable WITH a warning
    assert a["usage"] == {"status": "USABLE_WITH_WARNING", "reason": "QUALITY_GATE_EXCEPTION"} and a["exception"]
    with db.read() as c:
        assert pipeline.latest_published(conn=c)["id"] == fr
        assert c.execute("SELECT COUNT(*) FROM forecast_values WHERE run_id=?", (fr,)).fetchone()[0] > 0
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE action='MODEL_RELEASED_WITH_GATE_EXCEPTION'").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM alerts WHERE code='QUALITY_GATE_EXCEPTION_ACTIVE'").fetchone()[0] == 1
    again = client.post(url, json=_approval(rid, tr))
    assert again.status_code == 409 and again.json()["code"] == "PROMOTION_NOT_ALLOWED"
    # no general bypass: the next (scheduled or manual) run still meets the normal gate and is not published
    r2 = pipeline.train_and_publish(force=True)
    assert r2["status"] == "REJECTED" and r2["reason_code"] == "QUALITY_GATE_FAILED"
    with db.read() as c:
        assert pipeline.latest_published(conn=c)["id"] == fr
    # the released DIRECT model is explainable, without any recursion
    with db.read() as c:
        v = db.one(c, "SELECT sku_id, fc_id, target_date FROM forecast_values WHERE run_id=? AND method='LIGHTGBM' "
                      "ORDER BY target_date DESC LIMIT 1", (fr,))
    e = client.get(f"/api/forecast-runs/{fr}/explain", params={"sku_id": v["sku_id"], "fc_id": v["fc_id"],
                                                               "target_date": v["target_date"]}).json()
    lg = e["lightgbm"]
    assert lg["status"] == "OK" and lg["matches_published"] and lg["forecast_strategy"] == "DIRECT"
    assert not lg["uses_forecast_inputs"] and lg["recursive_step"] == 0
    assert {f["source"] for f in lg["features"]} <= {"ACTUAL", "STATIC", "TARGET_DATE"}
    assert any(f["name"] == "horizon" for f in lg["features"])
    assert e["history"]["calc"]["recursive_days"] == 0
    # a DIRECT model cannot be extended past the horizon it was trained for
    ss.update("horizons", {"enabled": [7, 15]})
    x = client.post(f"/api/forecast-runs/{fr}/extend")
    j = x.json()                        # background job (sync mode in tests): the job row carries the refusal
    assert x.status_code == 200 and j["status"] == "FAILED" and j["reason_code"] == "DIRECT_HORIZON_EXCEEDS_TRAINING", j


def test_gate_exception_is_refused_when_a_non_metric_check_failed(client, fast_model):
    _freeze(2026, 3, 15)
    _dataset(client, date(2026, 1, 1), date(2026, 3, 14))
    _direct_settings(min_backtest_points=10**9)
    r = pipeline.train_and_publish(force=True)
    assert r["status"] == "REJECTED" and r["reason_code"] == "QUALITY_GATE_FAILED"
    tr = _tr(r["training_run_id"])
    d = client.get(f"/api/training-runs/{tr['id']}").json()
    assert not d["gate_exception"]["eligible"] and d["gate_exception"]["reason"] == "NON_METRIC_CHECK_FAILED"
    x = client.post(f"/api/training-runs/{tr['id']}/release-with-exception", json=_approval(tr["id"], tr))
    assert x.status_code == 409 and x.json()["code"] == "PROMOTION_NOT_ALLOWED"


def test_direct_horizon_longer_than_the_backtest_is_refused_before_training(client, fast_model):
    _freeze(2026, 3, 15)
    _dataset(client, date(2026, 1, 1), date(2026, 3, 14))
    ss.update("model", {"forecast_strategy": "DIRECT"})              # fast_model: backtest horizon 7, horizons 7/15/30
    with pytest.raises(AppError) as e:
        pipeline.train_and_publish(force=True)
    assert e.value.code == "DIRECT_HORIZON_EXCEEDS_TRAINING"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM training_runs").fetchone()[0] == 0


def test_feature_groups_cannot_all_be_off():
    with pytest.raises(ValueError, match="FEATURE_GROUPS_EMPTY"):
        ss.ModelSettings(feature_lags=False, feature_rolling=False, feature_price=False)
    ss.ModelSettings(feature_lags=False, feature_rolling=False, feature_price=True)          # price alone is valid
