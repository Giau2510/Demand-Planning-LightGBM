"""1.2.0: feature groups (historical demand, price) chosen in the UI are exactly what the next training uses; a group
that is on without data is left out and recorded; price features never read data at or after the forecast origin; a
model in use keeps its own feature list when the switches change."""
import json
from datetime import date

import lightgbm as lgb
import numpy as np
import pandas as pd

from app import db, paths
from app import settings_service as ss
from app.ml import pipeline
from app.ml.features import build_panel, features_at, origin_features, static_codes

from test_v117 import _dataset, _freeze, _tr

PRICE = {"price_last", "price_rel_28"}
HIST = lambda names: {n for n in names if n.startswith(("lag_", "roll_")) or n in ("zero_share_28", "days_since_last_sale")}


def _booster_features(run_id):
    tr = _tr(run_id)
    return lgb.Booster(model_file=str(paths.models_dir() / tr["model_path"])).feature_name(), json.loads(tr["feature_config_json"])


def test_feature_group_switches_decide_the_trained_features(client, small_demo):
    ss.update("general", {"active_source": "DEMO"})
    ss.update("quality", {"wape_max": 10.0, "abs_bias_max": 10.0})
    r1 = pipeline.train_and_publish(force=True)
    assert r1["status"] == "PUBLISHED", r1
    names, fc = _booster_features(r1["training_run_id"])
    assert PRICE <= set(names) and HIST(names)
    assert fc["feature_groups"] == {"historical_demand": {"switch_on": True, "used": True},
                                    "price": {"switch_on": True, "used": True}}
    assert fc["forecast_strategy"] == "RECURSIVE" and len(fc["config_fingerprint"]) == 16
    # price off -> the next model has no price feature; the model in use keeps its own list
    r = client.put("/api/settings/model", json={**ss.get("model").model_dump(), "feature_price": False})
    assert r.status_code == 200, r.text
    r2 = pipeline.train_and_publish(force=True)
    names2, fc2 = _booster_features(r2["training_run_id"])
    assert not PRICE & set(names2) and fc2["feature_groups"]["price"] == {"switch_on": False, "used": False}
    assert fc2["config_fingerprint"] != fc["config_fingerprint"]
    assert _booster_features(r1["training_run_id"])[0] == names                      # unchanged model file
    # historical demand off, price on -> calendar, codes and price only
    ss.update("model", {"feature_price": True, "feature_lags": False, "feature_rolling": False})
    r3 = pipeline.train_and_publish(force=True)
    names3, fc3 = _booster_features(r3["training_run_id"])
    assert not HIST(names3) and PRICE <= set(names3)
    assert fc3["feature_groups"]["historical_demand"] == {"switch_on": False, "used": False}
    # every group off is refused with a clear code, nothing saved
    bad = client.put("/api/settings/model", json={**ss.get("model").model_dump(), "feature_price": False})
    assert bad.status_code == 422 and "FEATURE_GROUPS_EMPTY" in json.dumps(bad.json())
    assert ss.get("model").feature_price is True


def test_price_on_without_price_data_is_left_out_and_recorded(client, fast_model):
    _freeze(2026, 3, 15)
    _dataset(client, date(2026, 1, 1), date(2026, 3, 14))            # Excel rows without any price column
    ss.update("quality", {"wape_max": 10.0, "abs_bias_max": 10.0})
    assert ss.get("model").feature_price is True
    r = pipeline.train_and_publish(force=True)
    names, fc = _booster_features(r["training_run_id"])
    assert not PRICE & set(names)
    assert fc["feature_groups"]["price"] == {"switch_on": True, "used": False}
    assert fc["feature_decisions"]["price"]["reason"] == "NO_DATA"
    reg = client.get("/api/features/registry").json()
    assert reg["decisions"]["price"]["used"] is False


def _price_panel(days=120):
    rows = []
    for t in range(days):
        d = pd.Timestamp("2026-01-01") + pd.Timedelta(days=t)
        for s in range(3):
            rows.append({"order_date": str(d.date()), "sku_id": f"S{s}", "fc_id": "F1", "qty": float(5 + t % 7 + s),
                         "avg_unit_price": 1000.0 + 10 * s + (t % 5)})
    return build_panel(pd.DataFrame(rows))


def test_price_features_never_read_the_origin_day_or_later():
    p = _price_panel()
    cfg = ss.ModelSettings()
    rec = ss.ModelSettings(forecast_strategy="DIRECT")
    sc, fcc = static_codes(p)
    t = 100
    a = features_at(p, p.Y, p.price, p.disc, p.promo, p.dates, t, cfg, sc, fcc)
    b0 = origin_features(p, p.Y, p.price, p.disc, p.promo, p.dates, t, rec, sc, fcc)
    q = p.truncate(p.T)
    q.price[:, t:] = 9e9                                             # future prices must not matter
    b = features_at(q, q.Y, q.price, q.disc, q.promo, q.dates, t, cfg, sc, fcc)
    b1 = origin_features(q, q.Y, q.price, q.disc, q.promo, q.dates, t, rec, sc, fcc)
    assert np.array_equal(a, b, equal_nan=True) and np.array_equal(b0, b1, equal_nan=True)
    names = [n for n in ss.ModelSettings().model_dump()]                 # sanity: the switch exists
    assert "feature_price" in names
    with db.read() as c:
        assert c is not None
