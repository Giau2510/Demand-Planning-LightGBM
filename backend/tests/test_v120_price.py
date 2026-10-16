"""1.2.0, owner decision of 17/10/2026: the price group stays ON for the release model. These tests prove that the
switch is not only shown as on: the mapped order-line price reaches demand_daily (a missing price stays NULL, never 0),
the feature registry uses it, a DIRECT training learns from it, the published forecast and its explanation read the
last known price (never the origin day or later), and the switch survives a restart, a BigQuery load, saves of other
settings and a settings row written by 1.1.9. Fake BigQuery client only: no real BigQuery access."""
import json
from datetime import timedelta

import lightgbm as lgb
import numpy as np

from app import db, paths, timeutil
from app import settings_service as ss
from app.bq import connector
from app.data.demand import bigquery_scope_key, load_demand
from app.ml import feature_registry as registry
from app.ml import model, pipeline
from app.ml.features import build_panel

from fake_bq import FakeBQ
from test_v116 import LAYOUT, _bq_ready, _hist_production

PRICE = ["price_last", "price_rel_28"]
NULL_PRICE = "SAFE_DIVIDE(SUM(CAST(NULL AS FLOAT64) * order_qty)"
MAPPED_PRICE = "SAFE_DIVIDE(SUM(unit_price * order_qty), SUM(IF(unit_price IS NULL, NULL, order_qty))) AS avg_unit_price"


def _map_price():
    """The owner's rule (17/10/2026): unit price = sales_price of the order line (already includes the deal)."""
    fm = {k: v.model_dump() for k, v in ss.get("bigquery").field_mapping.items()}
    fm["unit_price"] = {"column": "sales_price", "usage": "OPTIONAL"}
    ss.update("bigquery", {"field_mapping": fm})


def _daily(rows):
    q = sum(r["qty"] for r in rows)
    n = sum(r["n_rows"] for r in rows)
    return rows + [{"_kind": "TOTAL_READ", "_reason": "0", "qty": q, "n_rows": n},
                   {"_kind": "TOTAL_KEPT", "_reason": "0", "qty": q, "n_rows": n}]


def _row(day, sku, qty, price):
    return {"_kind": "VALID", "order_date": day, "sku_id": sku, "fc_id": "F1", "qty": float(qty), "n_orders": 1,
            "n_rows": 1, "avg_unit_price": price}


def _price_production():
    fake = _bq_ready(FakeBQ(schema=LAYOUT))
    unmapped = connector._daily_sql(ss.get("bigquery"), timeutil.today_vn(), timeutil.today_vn())[0]
    old_hash, old_scope = connector.mapping_hash(ss.get("bigquery")), bigquery_scope_key(ss.get("bigquery"))
    _map_price()
    _hist_production(fake)
    bq = ss.get("bigquery")
    # a new mapping = a new mapping hash (validation + full reload again), but the SAME data scope
    assert connector.mapping_hash(bq) != old_hash and bigquery_scope_key(bq) == old_scope
    assert NULL_PRICE in unmapped and MAPPED_PRICE not in unmapped
    return fake, bigquery_scope_key(bq)


# ------------------------------------------------------------------ source -> demand_daily -> registry
def test_mapped_order_line_price_reaches_demand_daily_and_missing_prices_stay_missing(client):
    from app import sync
    model_before = ss.get("model").model_dump()
    fake, sk = _price_production()
    y = timeutil.today_vn() - timedelta(days=1)
    fake.responses["daily"] = _daily([_row(y, "S1", 4, 12000.0), _row(y, "S2", 2, 30500.5), _row(y, "S3", 1, None)])
    r = sync.run_d1_sync("J1", fallback_mode=True)
    assert r["full_reload"] and r["series_days_written"] == 3
    sql = [q[0] for q in fake.queries if q[0].startswith("-- df:daily")][-1]
    assert MAPPED_PRICE in sql                                   # the load really reads the mapped price column
    with db.read() as c:
        got = {row[0]: row[1] for row in c.execute("SELECT sku_id, avg_unit_price FROM demand_daily WHERE scope_key=?", (sk,))}
        cov = registry.coverage(c, sk)
    assert got == {"S1": 12000.0, "S2": 30500.5, "S3": None}     # missing price kept missing (NULL), never 0
    assert abs(cov["avg_unit_price"] - 2 / 3) < 1e-12
    _, dec = registry.resolve(ss.get("model"), cov)
    assert dec["price"]["used"] and dec["price"]["reason"] == "DATA_OK"
    reg = client.get("/api/features/registry").json()
    assert reg["decisions"]["price"]["used"] and set(PRICE) <= set(reg["next_training"]["features"])
    assert ss.get("model").model_dump() == model_before          # a BigQuery load never touches the model settings


# ------------------------------------------------------------------ training + inference really use the price
def _price_driven_history(days=140, seed=7):
    """4 series; the price is set for blocks of 10 days (100 or 150, same levels for every SKU); demand depends on the
    price only (Poisson 12 at 100, 6 at 150) so the noisy demand lags carry less signal than the known price."""
    rng = np.random.default_rng(seed)
    y = timeutil.today_vn() - timedelta(days=1)
    start = y - timedelta(days=days - 1)
    rows = []
    for s in range(4):
        price = 100.0
        for t in range(days):
            if t % 10 == 0:
                price = 150.0 if rng.random() < 0.5 else 100.0
            rows.append(_row(start + timedelta(days=t), f"S{s}", rng.poisson(12.0 if price == 100.0 else 6.0), price))
    return rows


def test_direct_training_learns_from_the_price_and_inference_reads_the_last_known_price(client, fast_model):
    from app import sync
    fake, sk = _price_production()
    fake.responses["daily"] = _daily(_price_driven_history())
    assert sync.run_d1_sync("J1", fallback_mode=True)["series_days_written"] == 560
    ss.update("model", {"feature_price": True, "forecast_strategy": "DIRECT", "direct_origins": 12})   # explicit
    ss.update("horizons", {"enabled": [7]})
    ss.update("quality", {"wape_max": 10.0, "abs_bias_max": 10.0})
    res = pipeline.train_and_publish(force=True)
    assert res["status"] == "PUBLISHED", res
    with db.read() as c:
        tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (res["training_run_id"],))
    fc = json.loads(tr["feature_config_json"])
    # training: the switch as chosen AND as used, the resolved configuration, the model file and its metadata
    assert fc["feature_groups"]["price"] == {"switch_on": True, "used": True}
    assert fc["feature_decisions"]["price"]["reason"] == "DATA_OK" and fc["config"]["feature_price"] is True
    assert fc["forecast_strategy"] == "DIRECT" and set(PRICE) <= set(fc["features"])
    booster = lgb.Booster(model_file=str(paths.models_dir() / tr["model_path"]))
    names = booster.feature_name()
    assert names == fc["features"]
    meta = json.loads((paths.models_dir() / tr["model_path"].replace(".txt", ".json")).read_text(encoding="utf-8"))
    assert meta["features"] == names and meta["forecast_strategy"] == "DIRECT"
    splits = dict(zip(names, booster.feature_importance(importance_type="split")))
    assert splits["price_last"] + splits["price_rel_28"] > 0, splits          # the trees really split on the price
    # inference: the forecast reads the last known price; another last price gives another forecast
    mcfg = ss.ModelSettings.model_validate(fc["config"])
    p = build_panel(load_demand(sk, start=tr["train_start"], end=tr["train_end"]), start_date=tr["train_start"],
                    end_date=tr["train_end"])
    base = model.forecast(p, booster, mcfg, 7, capture=0)
    row = base["captured"][0]
    assert row[names.index("price_last")] == p.price[0, -1]
    q = p.truncate(p.T)
    q.price[:, -1] = np.where(q.price[:, -1] == 100.0, 150.0, 100.0)
    assert not np.allclose(model.forecast(q, booster, mcfg, 7)["yhat"], base["yhat"])
    q2 = p.truncate(p.T)
    q2.price[:, : p.T - 1] = 9e9                       # older prices only enter price_rel_28 (28-day mean), not price_last
    assert model.forecast(q2, booster, mcfg, 7, capture=0)["captured"][0][names.index("price_last")] == p.price[0, -1]
    # the published value is reproduced by its explanation with the price as an ACTUAL (known) input
    with db.read() as c:
        v = db.one(c, "SELECT sku_id, fc_id, target_date FROM forecast_values WHERE run_id=? AND method='LIGHTGBM' "
                      "AND sku_id='S0' ORDER BY target_date LIMIT 1", (res["forecast_run_id"],))
        last_price = c.execute("SELECT avg_unit_price FROM demand_daily WHERE scope_key=? AND sku_id='S0' "
                               "ORDER BY order_date DESC LIMIT 1", (sk,)).fetchone()[0]
    e = client.get(f"/api/forecast-runs/{res['forecast_run_id']}/explain",
                   params={"sku_id": v["sku_id"], "fc_id": v["fc_id"], "target_date": v["target_date"]}).json()
    lg_ = e["lightgbm"]
    assert lg_["status"] == "OK" and lg_["matches_published"] and lg_["forecast_strategy"] == "DIRECT"
    f = {x["name"]: x for x in lg_["features"]}
    assert f["price_last"]["value"] == last_price and f["price_last"]["source"] == "ACTUAL"
    assert f["price_rel_28"]["source"] == "ACTUAL" and not f["price_last"]["missing"]
    assert f["price_last"]["used_in_trees"] or f["price_rel_28"]["used_in_trees"]
    # control: the same data with the price group OFF gives a model that the price cannot move
    ss.update("model", {"feature_price": False})
    off = pipeline.train_and_publish(force=True)
    with db.read() as c:
        tr2 = db.one(c, "SELECT * FROM training_runs WHERE id=?", (off["training_run_id"],))
    fc2 = json.loads(tr2["feature_config_json"])
    assert fc2["feature_groups"]["price"] == {"switch_on": False, "used": False} and not set(PRICE) & set(fc2["features"])
    b2 = lgb.Booster(model_file=str(paths.models_dir() / tr2["model_path"]))
    m2 = ss.ModelSettings.model_validate(fc2["config"])
    assert np.array_equal(model.forecast(q, b2, m2, 7)["yhat"], model.forecast(p, b2, m2, 7)["yhat"])


# ------------------------------------------------------------------ the switch stays on
def test_price_switch_survives_restart_load_other_saves_and_a_1_1_9_settings_row(client):
    from fastapi.testclient import TestClient
    from app.main import create_app
    cur = client.get("/api/settings").json()["model"]
    r = client.put("/api/settings/model", json={**cur, "feature_price": True, "forecast_strategy": "DIRECT"})
    assert r.status_code == 200 and r.json()["feature_price"] is True
    # saving other sections (quality, horizons, BigQuery mapping) leaves the model switches alone
    assert client.put("/api/settings/quality", json={**ss.get("quality").model_dump(), "wape_max": 0.9}).status_code == 200
    ss.update("horizons", {"enabled": [7, 15]})
    _bq_ready()
    _map_price()
    # a restart of the app reads the same stored value
    with TestClient(create_app(), headers={"X-DF-Client": "web"}) as again:
        m = again.get("/api/settings").json()["model"]
    assert m["feature_price"] is True and m["forecast_strategy"] == "DIRECT"
    # a settings row written by 1.1.9 (no 1.2.0 fields): the upgrade reads it as stored and never rewrites it
    old = {k: v for k, v in ss.ModelSettings().model_dump().items()
           if k not in ("forecast_strategy", "direct_origins", "direct_origin_step_days")}
    for want in (True, False):
        raw = json.dumps({**old, "feature_price": want})
        with db.tx() as c:
            c.execute("UPDATE app_settings SET value_json=? WHERE section='model'", (raw,))
        got = client.get("/api/settings").json()["model"]
        assert got["feature_price"] is want and got["forecast_strategy"] == "RECURSIVE"
        with db.read() as c:
            assert c.execute("SELECT value_json FROM app_settings WHERE section='model'").fetchone()[0] == raw
