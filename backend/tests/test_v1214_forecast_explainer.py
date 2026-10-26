"""1.2.14: LightGBM forecast explainer (app/ml/forecast_explainer.py, GET /api/forecast-explainer).

A real DIRECT LightGBM model is trained and published on an imported (MANUAL_IMPORT) dataset in the isolated test
database; the explanation must reproduce the published value exactly through the production code path (features), the
saved model file (every tree's path and leaf = LightGBM's pred_leaf), the sum of the leaves (= LightGBM raw score), the
objective's link (= LightGBM prediction) and the published post-processing (= stored yhat, whole number of qty.py)."""
import json
import math
import time
import tracemalloc
from datetime import date

import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest

from app import db, paths, qty
from app import settings_service as ss
from app.data.demand import panel_for_run
from app.ml import forecast_explainer as fe
from app.ml import model, pipeline

from test_v117 import _dataset, _freeze, _insert_demand, _tr

URL = "/api/forecast-explainer"


def _publish(client, horizons=(7,), extra_series: bool = True, gap_day: str | None = "2026-03-08") -> dict:
    """gap_day 08/03 = origin 15/03 - 7: lag_7 of every series is an unknown (NaN) input."""
    _freeze(2026, 3, 15)
    bid = _dataset(client, date(2026, 1, 1), date(2026, 3, 14))
    if extra_series:                       # a series too young for the model: published by a fallback rule
        for d in ("2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13", "2026-03-14"):
            _insert_demand(bid, d, qty=3.0, sku="S9", fc="F1")
    if gap_day:                            # a day without any row in the whole scope: 'unknown' (NaN) inputs
        with db.tx() as c:
            c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date=?", (bid, gap_day))
    ss.update("model", {"forecast_strategy": "DIRECT", "direct_origins": 4, "direct_origin_step_days": 7})
    ss.update("horizons", {"enabled": list(horizons)})
    fe._cache.clear()
    fe._recent.clear()
    r = pipeline.train_and_publish(force=True)
    assert r["status"] == "PUBLISHED", r
    with db.read() as c:
        fr = pipeline.latest_published(conn=c)
    return {"bid": bid, "fr": fr, "tr": _tr(fr["training_run_id"])}


def _get(client, **params):
    r = client.get(URL, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _all_trees(client, sel, total):
    out = []
    for off in range(0, total, 50):
        p = client.get(URL + "/trees", params={"offset": off, "limit": 50, **sel}).json()
        assert p["status"] == "OK" and p["total"] == total
        out += p["trees"]
    return out


# ---------------------------------------------------------------- 1, 2: the series and the run in use
def test_auto_selection_explains_a_lightgbm_value_of_the_run_in_use(client, fast_model):
    pub = _publish(client)
    r = _get(client)
    assert r["status"] == "OK" and r["verified"] is True, json.dumps(r.get("checks"), indent=1)
    sel, run = r["selection"], r["run"]
    assert sel["auto"] and sel["target_date"] == "2026-03-15" and sel["horizon_day"] == 1     # today = first forecast day
    assert run["forecast_run_id"] == pub["fr"]["id"] and run["model_version"] == pub["fr"]["model_version"]
    assert run["training_run_id"] == pub["tr"]["id"] and run["strategy"] == "DIRECT" and run["objective"] == "tweedie"
    with db.read() as c:
        v = db.one(c, "SELECT * FROM forecast_values WHERE run_id=? AND sku_id=? AND fc_id=? AND target_date=?",
                   (pub["fr"]["id"], sel["sku_id"], sel["fc_id"], sel["target_date"]))
    assert v and v["method"] == model.METHOD_LGBM and sel["sku_id"] != "S9"
    assert all(ch["ok"] for ch in r["checks"]), r["checks"]


# ---------------------------------------------------------------- 3: features = the production inference row
def test_feature_values_equal_the_production_inference_row(client, fast_model):
    pub = _publish(client)
    r = _get(client)
    sel = r["selection"]
    tr, fr = pub["tr"], pub["fr"]
    mcfg = ss.ModelSettings.model_validate(json.loads(tr["feature_config_json"])["config"])
    panel = panel_for_run(tr)                                   # the FULL panel of the run (production path)
    s = panel.keys.index((sel["sku_id"], sel["fc_id"]))
    booster = lgb.Booster(model_file=str(paths.models_dir() / tr["model_path"]))
    fc = model.forecast(panel, booster, mcfg, fr["max_horizon"], capture=s)
    want = fc["captured"][sel["horizon_day"] - 1]
    got = np.array([np.nan if f["value"] is None else f["value"] for f in r["features"]], dtype=np.float32)
    assert np.array_equal(got, want.astype(np.float32), equal_nan=True)
    assert [f["name"] for f in r["features"]] == json.loads((paths.models_dir() / tr["model_path"].replace(".txt", ".json"))
                                                            .read_text(encoding="utf-8"))["features"]
    assert all(f["verified"] for f in r["features"]), [f for f in r["features"] if not f["verified"]]
    assert any(f["value"] is None for f in r["features"])      # the gap day gives unknown (NaN) inputs, shown as such
    lag = next(f for f in r["features"] if f["name"] == "lag_1")
    assert lag["inputs"][0]["date"] == "2026-03-14"


# ---------------------------------------------------------------- 4: tree paths and leaves = the saved model
def test_every_tree_path_ends_in_lightgbms_leaf_with_the_saved_leaf_value(client, fast_model):
    pub = _publish(client)
    r = _get(client)
    sel = {k: r["selection"][k] for k in ("sku_id", "fc_id", "target_date")}
    trees = _all_trees(client, sel, r["trees"]["count"])
    booster = lgb.Booster(model_file=str(paths.models_dir() / pub["tr"]["model_path"]))
    X = np.array([[np.nan if f["value"] is None else f["value"] for f in r["features"]]], dtype=np.float32)
    leaves = booster.predict(X, pred_leaf=True)[0]
    dump = booster.dump_model()["tree_info"]

    def leaf_value(node, leaf):
        if "leaf_index" in node:
            return node["leaf_value"] if node["leaf_index"] == leaf else None
        return leaf_value(node["left_child"], leaf) if leaf_value(node["left_child"], leaf) is not None \
            else leaf_value(node["right_child"], leaf)

    assert len(trees) == len(dump) == booster.num_trees()
    for t, lv in zip(trees, leaves):
        assert t["leaf"] == int(lv)
        assert abs(t["leaf_value"] - leaf_value(dump[t["index"]]["tree_structure"], t["leaf"])) <= 1e-12
        for st in t["steps"]:
            if st["kind"] == "numerical" and st["rule"] in ("LE", "GT"):
                used = 0.0 if st["value"] is None else st["value"]
                assert (used <= st["threshold"]) == (st["goes"] == "left") == (st["rule"] == "LE")
            elif st["kind"] == "numerical":                              # missing value -> the default direction
                assert st["goes"] == ("left" if st["default_left"] else "right")


# ---------------------------------------------------------------- 5, 6, 7: sum, link, post-processing, rounding
def test_sum_link_post_processing_and_whole_number_match_lightgbm_and_the_stored_value(client, fast_model):
    pub = _publish(client)
    r = _get(client)
    sel = r["selection"]
    booster = lgb.Booster(model_file=str(paths.models_dir() / pub["tr"]["model_path"]))
    X = np.array([[np.nan if f["value"] is None else f["value"] for f in r["features"]]], dtype=np.float32)
    a, res = r["aggregation"], r["result"]
    assert a["link"] == "log" and abs(a["raw_sum"] - booster.predict(X, raw_score=True)[0]) <= 1e-9
    assert a["raw_sum"] == pytest.approx(sum(t["leaf_value"] for t in r["trees"]["summary"]), abs=1e-9)
    assert abs(a["prediction"] - math.exp(a["raw_sum"])) <= 1e-12 * max(1.0, a["prediction"])
    assert a["prediction_lightgbm"] == booster.predict(X)[0]
    with db.read() as c:
        stored = db.one(c, "SELECT yhat FROM forecast_values WHERE run_id=? AND sku_id=? AND fc_id=? AND target_date=?",
                        (pub["fr"]["id"], sel["sku_id"], sel["fc_id"], sel["target_date"]))["yhat"]
    assert res["stored_yhat"] == stored and res["published"] == stored and res["match"] is True
    assert res["forecast_qty"] == qty.business_qty(stored) == math.floor(max(stored, 0) + 0.5)
    shown = client.get(f"/api/forecast-runs/{pub['fr']['id']}/values",
                       params={"sku_id": sel["sku_id"], "fc_id": sel["fc_id"], "limit": 50}).json()
    row = next(x for x in shown["rows"] if x["target_date"] == sel["target_date"])
    assert row["forecast_qty"] == res["forecast_qty"]                    # the same whole number as the forecast screen


# ---------------------------------------------------------------- requested values, fallback, bad requests
def test_requested_value_fallback_series_and_bad_requests(client, fast_model):
    pub = _publish(client)
    one = _get(client, sku_id="S2", fc_id="F2", target_date="2026-03-18")
    assert one["status"] == "OK" and one["selection"]["horizon_day"] == 4 and not one["selection"]["auto"]
    assert one["verified"] is True
    fb = _get(client, sku_id="S9", fc_id="F1", target_date="2026-03-15")
    assert fb["status"] == "NOT_LIGHTGBM" and fb["stored"]["method"].startswith("FALLBACK")
    assert _get(client, sku_id="NOPE", fc_id="F1")["status"] == "NOT_FOUND"
    assert _get(client, sku_id="S1")["status"] == "BAD_REQUEST"
    assert _get(client, target_date="15/03/2026")["status"] == "BAD_REQUEST"
    assert _get(client, target_date="2026-04-30")["status"] == "NOT_FOUND"
    assert pub["fr"]["max_horizon"] == 7


# ---------------------------------------------------------------- 9: no data / demo
def test_no_forecast_and_demo_source_give_a_status_not_an_error(client, small_demo):
    r = _get(client)
    assert r["status"] == "NO_FORECAST" and r["reason"]
    ss.update("model", {"forecast_strategy": "DIRECT", "direct_origins": 4, "direct_origin_step_days": 7})
    ss.update("horizons", {"enabled": [7]})
    assert pipeline.train_and_publish(force=True)["status"] == "PUBLISHED"
    d = _get(client)
    assert d["status"] == "NO_FORECAST" and d["reason"].startswith("DEMO_SOURCE")


# ---------------------------------------------------------------- 10: never stale
def test_a_new_run_or_changed_data_is_never_explained_from_the_old_cache(client, fast_model):
    pub = _publish(client, horizons=(3,))
    a = _get(client)
    assert a["status"] == "OK" and a["run"]["forecast_run_id"] == pub["fr"]["id"] and a["cache"] == "MISS"
    assert _get(client)["cache"] == "HIT"
    ss.update("horizons", {"enabled": [3, 7]})
    ext = pipeline.extend_forecast(pub["fr"]["id"])                     # a NEW run in use (same model, same data)
    b = _get(client)
    assert b["run"]["forecast_run_id"] == ext["forecast_run_id"] != a["run"]["forecast_run_id"] and b["cache"] == "MISS"
    assert b["verified"] is True
    sel = b["selection"]
    q = {k: sel[k] for k in ("sku_id", "fc_id", "target_date")}
    lag1 = next(f for f in b["features"] if f["name"] == "lag_1")["value"]
    used = {st["feature"] for t in _all_trees(client, q, b["trees"]["count"]) for st in t["steps"]}
    assert used & {"lag_1", "lag_2", "lag_7", "lag_14", "roll_mean_7", "roll_mean_14", "roll_mean_28", "roll_max_28"}, used
    # every input of the series' window changes without a sync log (a write outside the application's own paths): the
    # explanation is recomputed from the data now in the database and says that it no longer gives the stored value
    # (x 0.01: every lag / average falls below the split thresholds learnt on values of 10..25; a larger value would
    # stay on the same side of a threshold it already exceeded)
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET qty=qty*0.01, loaded_at=? WHERE scope_key=? AND sku_id=? AND fc_id=?",
                  ("2099-01-01T00:00:00+00:00", pub["bid"], sel["sku_id"], sel["fc_id"]))
    fe._recent.clear()                     # no log id moved: as if the 60 s freshness memo had passed
    c2 = _get(client, **q)
    assert c2["cache"] == "MISS"
    assert next(f for f in c2["features"] if f["name"] == "lag_1")["value"] == pytest.approx(lag1 * 0.01, rel=1e-6)
    assert c2["result"]["match"] is False and c2["verified"] is False
    chk = {x["check"]: x for x in c2["checks"]}
    assert chk["PUBLISHED_EQUALS_STORED"]["ok"] is False and chk["RAW_SUM_EQUALS_LIGHTGBM"]["ok"] is True
    assert chk["TREE_LEAVES_EQUAL_LIGHTGBM"]["ok"] is True       # the model steps stay exact; only the inputs differ


def _log_change(bid, sel, day, run_id, **after):
    """A stored change the way a D-1 sync writes it: demand_daily updated AND logged with the whole row before/after."""
    with db.tx() as c:
        r = db.one(c, "SELECT * FROM demand_daily WHERE scope_key=? AND sku_id=? AND fc_id=? AND order_date=?",
                   (bid, sel["sku_id"], sel["fc_id"], day))
        new = {**r, **after, "loaded_at": "2099-01-01T00:00:00+00:00"}
        sets = ", ".join(f"{k}=?" for k in [*after, "loaded_at"])
        c.execute(f"UPDATE demand_daily SET {sets} WHERE scope_key=? AND sku_id=? AND fc_id=? AND order_date=?",
                  (*after.values(), new["loaded_at"], bid, sel["sku_id"], sel["fc_id"], day))
        c.execute("INSERT INTO demand_change_log(run_id, run_kind, scope_key, order_date, sku_id, fc_id, action, qty_before, "
                  "qty_after, held_after, before_json, after_json, finalized, at) VALUES (?,?,?,?,?,?,'UPDATE',?,?,0,?,?,0,?)",
                  (run_id, "D1_SYNC", bid, day, sel["sku_id"], sel["fc_id"], r["qty"], new["qty"], json.dumps(r),
                   json.dumps(new), "2099-01-01T00:00:00+00:00"))


def test_logged_changes_after_the_run_are_reverted_or_shown_as_not_an_input(client, fast_model):
    pub = _publish(client)
    a = _get(client)
    sel = a["selection"]
    q = {k: sel[k] for k in ("sku_id", "fc_id", "target_date")}
    _log_change(pub["bid"], sel, "2026-03-13", "D1L-TEST-1", n_orders=99)            # not a model input
    b = _get(client, **q)
    ch = b["data"]["changes_after_run"]
    assert ch["status"] == "SAME_INPUTS" and ch["records"][0]["changed"] == {"n_orders": {"before": 1, "after": 99}}
    assert ch["records"][0]["model_input"] is False and b["verified"] is True
    _log_change(pub["bid"], sel, "2026-03-14", "D1L-TEST-2", qty=12345.0)            # a model input, logged
    c3 = _get(client, **q)
    ch = c3["data"]["changes_after_run"]
    assert ch["status"] == "REVERTED_TO_RUN" and any(r["model_input"] for r in ch["records"])
    assert c3["result"]["match"] is True and c3["verified"] is True                    # the inputs as at the run
    lag1 = next(f for f in c3["features"] if f["name"] == "lag_1")
    assert lag1["value"] == next(f for f in a["features"] if f["name"] == "lag_1")["value"] != 12345.0
    hist = {h["date"]: h for h in c3["data"]["history"]}
    assert hist["2026-03-14"]["qty_row"] != 12345.0


def test_series_reads_by_key_lookup_return_the_rows_of_a_range_read(client, fast_model):
    """One key lookup per day (a cold first open on the production PC walked the whole window): the same rows, scope
    days and change records as plain range reads; the day without any row in the scope stays out of the scope days."""
    pub = _publish(client)
    sel = _get(client)["selection"]
    _log_change(pub["bid"], sel, "2026-03-13", "D1L-TEST-3", n_orders=7)
    sk, tr, sku, fc = pub["fr"]["scope_key"], pub["tr"], sel["sku_id"], sel["fc_id"]
    a, b = tr["train_start"], tr["train_end"]
    with db.read() as c:
        rng = pd.read_sql_query(f"SELECT {', '.join(fe.COLS)}, loaded_at FROM demand_daily WHERE scope_key=? AND sku_id=? "
                                "AND fc_id=? AND order_date BETWEEN ? AND ? ORDER BY order_date", c, params=[sk, sku, fc, a, b])
        got = fe._series_rows(c, sk, sku, fc, a, b)
        days = [r[0] for r in c.execute("SELECT DISTINCT order_date FROM demand_daily WHERE scope_key=? AND order_date "
                                        "BETWEEN ? AND ? ORDER BY order_date", (sk, a, b))]
        got_days = fe._scope_days(c, sk, a, b)
        log = [r[0] for r in c.execute("SELECT run_id FROM demand_change_log WHERE scope_key=? AND sku_id=? AND fc_id=? "
                                       "AND order_date BETWEEN ? AND ? ORDER BY id", (sk, sku, fc, a, b))]
        ch = fe._changes_after(c, pub["fr"], tr, sku, fc, got)
    assert len(got) > 50
    pd.testing.assert_frame_equal(got, rng)
    assert got_days == days and "2026-03-08" not in got_days and len(days) > 50
    assert log == ["D1L-TEST-3"] and [r["sync_run"] for r in ch["records"]] == log and ch["status"] == "SAME_INPUTS"


# ---------------------------------------------------------------- 11, 13, 14: no training, no history load, read-only, no secrets
def _db_state():
    with db.read() as c:
        tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tabs}, \
            c.execute("SELECT COALESCE(SUM(qty),0), MAX(loaded_at) FROM demand_daily").fetchone()


def test_read_only_no_training_no_full_history_load_and_no_internal_details(client, fast_model, monkeypatch):
    pub = _publish(client)

    def forbidden(*a, **k):
        raise AssertionError("the explainer must not call this")
    import app.data.demand as demand
    monkeypatch.setattr(demand, "load_demand", forbidden)
    monkeypatch.setattr(demand, "panel_for_run", forbidden)
    monkeypatch.setattr(model, "train", forbidden)
    monkeypatch.setattr(model, "backtest", forbidden)
    monkeypatch.setattr(pipeline, "train_and_publish", forbidden)
    monkeypatch.setattr(lgb, "train", forbidden)
    before = _db_state()
    r = _get(client)
    assert r["status"] == "OK"
    sel = {k: r["selection"][k] for k in ("sku_id", "fc_id", "target_date")}
    client.get(URL + "/trees", params={"offset": 0, "limit": 5, **sel})
    for m in ("post", "put", "delete", "patch"):
        assert getattr(client, m)(URL).status_code == 405
        assert getattr(client, m)(URL + "/trees").status_code == 405
    assert _db_state() == before
    text = json.dumps(r) + json.dumps(client.get(URL + "/trees", params=sel).json())
    assert "scope_key" not in text and pub["bid"] not in text and "model_path" not in text
    assert str(paths.models_dir()) not in text and str(paths.data_dir()) not in text and ":\\\\" not in text
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0] == before[0]["job_runs"]


# ---------------------------------------------------------------- 15: bounded memory and time
def test_memory_and_time_are_bounded_and_the_second_request_uses_the_cache(client, fast_model):
    _publish(client)
    tracemalloc.start()
    t0 = time.perf_counter()
    r = fe.explain()
    first = time.perf_counter() - t0
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert r["status"] == "OK" and peak < 50 * 2**20, peak
    t1 = time.perf_counter()
    again = fe.explain()
    assert again["cache"] == "HIT" and time.perf_counter() - t1 < max(1.0, first)
    assert len(fe._cache) <= fe._CACHE_MAX and len(fe._models) <= 1
    assert "_paths" not in r and len(json.dumps(r)) < 2_000_000


def test_the_existing_forecast_explanation_is_unchanged(client, fast_model):
    pub = _publish(client)
    sel = _get(client)["selection"]
    old = client.get(f"/api/forecast-runs/{pub['fr']['id']}/explain",
                     params={"sku_id": sel["sku_id"], "fc_id": sel["fc_id"], "target_date": sel["target_date"]})
    assert old.status_code == 200, old.text
    assert old.json()["result"]["forecast_qty"] == _get(client)["result"]["forecast_qty"]
