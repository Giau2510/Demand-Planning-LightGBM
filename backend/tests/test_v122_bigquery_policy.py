"""1.2.2 (P0 2026-10-17): BigQuery is the real source end to end; the quality gate is an assessment, not a publish
switch (policy PUBLISH_WITH_WARNING, owner decision); the best evaluated candidate (LightGBM or the 28-day baseline, on
the SAME backtest points) is published with its warnings; a model in use is never replaced or deleted automatically;
nothing falls back to DEMO.

Kind of evidence: integration on an isolated database (conftest: temporary DF_DATA_DIR) with a FAKE BigQuery client
(no Google call). The BIGQUERY demand rows are written the way a D-1 sync writes them (scope 'BIGQUERY:<table>',
data_source BIGQUERY); the real D-1 / D-0 BigQuery reads are covered by test_v121_d0_real_bq.py and the reports."""
import json
from datetime import timedelta

import numpy as np
import pytest

from app import db, paths, timeutil
from app import settings_service as ss
from app.data.demand import panel_for_run, resolve_scope
from app.messages import AppError
from app.ml import model, pipeline

from fake_bq import FakeBQ
from test_v116 import LAYOUT, _d0_rows
from test_v117 import _tr
from test_v118 import _bq_ready_production


def _bq_history(days=140, n_sku=5, n_fc=2, seed=7, lam=1.0):
    """Noisy daily demand (Poisson, mean lam) for the BIGQUERY scope up to yesterday (Vietnam). With lam = 1 even a
    perfect mean predictor has WAPE ~ 0.74, i.e. above the 0.60 threshold: the 'not clean' real data case."""
    scope = resolve_scope()["scope_key"]
    assert scope.startswith("BIGQUERY:")
    rng = np.random.default_rng(seed)
    end = timeutil.today_vn() - timedelta(days=1)
    rows = []
    for t in range(days):
        d = end - timedelta(days=days - 1 - t)
        for s in range(n_sku):
            for f in range(n_fc):
                q = float(rng.poisson(lam))
                if q > 0:                       # like a sync: a day without orders has no row
                    # 1.2.9: a D-1 sync also writes the SKU open hours of the day (mandatory BIGQUERY input)
                    rows.append((scope, "BIGQUERY", str(d), f"S{s}", f"F{f}", q, 1, timeutil.now_iso(), 24.0, "OK"))
    with db.tx() as c:
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                      "loaded_at, open_hours, open_hours_status) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    return scope


def _bq_scope(**hist):
    fake = _bq_ready_production()          # fake BigQuery: production enabled, full validation passed, source BIGQUERY
    ss.update("horizons", {"enabled": [7]})
    return fake, _bq_history(**hist)


def _gate(run_id):
    return json.loads(_tr(run_id)["quality_gate_json"])


def _count(sql, params=()):
    with db.read() as c:
        return c.execute(sql, params).fetchone()[0]


def _demo_run_newer_than_everything():
    """An old DEMO forecast run with the NEWEST timestamp (the production situation on 17/10/2026)."""
    with db.tx() as c:
        c.execute("INSERT INTO training_runs(id, model_version, scope_key, data_source, status, started_at) "
                  "VALUES ('TRN-DEMO', 'MV-DEMO', 'DEMO-OLD', 'DEMO', 'ACCEPTED', '2099-01-01T00:00:00+00:00')")
        c.execute("INSERT INTO forecast_runs(id, training_run_id, model_version, scope_key, data_source, forecast_origin, "
                  "data_as_of, horizons_json, max_horizon, n_series, status, created_at) VALUES ('FCR-DEMO', 'TRN-DEMO', "
                  "'MV-DEMO', 'DEMO-OLD', 'DEMO', '2026-10-16', '2026-10-15', '[7]', 7, 1, 'PUBLISHED', "
                  "'2099-01-01T00:00:00+00:00')")


# ------------------------------------------------------------------ A. BigQuery end to end, low quality allowed
def test_low_quality_bigquery_data_is_published_with_a_warning_and_its_lineage(client, fast_model):
    _bq_scope()
    q_before = ss.get("quality").model_dump()
    assert q_before["wape_max"] == 0.6 and q_before["abs_bias_max"] == 0.2
    assert q_before["below_threshold_policy"] == "PUBLISH_WITH_WARNING"            # the default (owner decision)
    res = pipeline.train_and_publish(force=True)
    assert res["status"] == "PUBLISHED" and res["reason_code"] == "FORECAST_PUBLISHED_WITH_WARNING", res
    assert res["usage"] == "USABLE_WITH_WARNING" and res["quality"] == "BELOW_THRESHOLD"
    tr = _tr(res["training_run_id"])
    gate = json.loads(tr["quality_gate_json"])
    assert tr["status"] == "ACCEPTED" and tr["data_source"] == "BIGQUERY" and tr["scope_key"].startswith("BIGQUERY:")
    # the gate is still computed and reported honestly: WAPE above 0.60 is a failed check, never a pass
    sel = gate["selection"]
    chosen = sel["candidates"][sel["chosen"]]["metrics"]
    other = sel["candidates"][sel["rejected"][0]["candidate"]]["metrics"]
    assert chosen["wape"] > 0.6 and chosen["wape"] <= other["wape"]                # best candidate on the same points
    assert chosen["n_points"] == other["n_points"]
    a = gate["assessment"]
    assert "WAPE_MAX" in a["quality"]["failed_checks"] and a["usage"]["status"] == "USABLE_WITH_WARNING"
    assert a["technical"]["status"] == "OK" and a["policy"] == "PUBLISH_WITH_WARNING"
    assert ss.get("quality").model_dump() == q_before                              # thresholds untouched
    fr_id = res["forecast_run_id"]
    with db.read() as c:
        fr = db.one(c, "SELECT * FROM forecast_runs WHERE id=?", (fr_id,))
    assert fr["data_source"] == "BIGQUERY" and fr["scope_key"] == tr["scope_key"]
    assert _count("SELECT COUNT(*) FROM forecast_runs WHERE data_source<>'BIGQUERY'") == 0
    assert _count("SELECT COUNT(*) FROM alerts WHERE code='FORECAST_PUBLISHED_WITH_WARNING' AND entity_id=?", (fr_id,)) == 1
    d = client.get(f"/api/forecast-runs/{fr_id}").json()
    assert d["active_scope"] is True and d["assessment"]["usage"]["status"] == "USABLE_WITH_WARNING"
    assert d["lineage"]["data_source"] == "BIGQUERY" and d["lineage"]["table"] == tr["scope_key"].split(":", 1)[1]
    assert d["lineage"]["data_fingerprint"] == tr["data_fingerprint"] and d["lineage"]["train_end"] == fr["data_as_of"]
    dash = client.get("/api/dashboard").json()
    assert dash["forecast"]["data_source"] == "BIGQUERY" and dash["forecast"]["run_id"] == fr_id
    fs = dash["system"]["forecast_state"]
    assert fs["status"] == "OK" and fs["model_in_use"]["quality"]["status"] == "BELOW_THRESHOLD"
    # the job route records the warning code too (not a silent success)
    j = client.post("/api/training/run", json={"force": True}).json()
    assert j["status"] == "SUCCEEDED" and j["reason_code"] == "PROMOTION_REVIEW_REQUIRED", j   # model in use is kept


def test_bias_above_the_threshold_warns_and_never_blocks(fast_model):
    _bq_scope(seed=11)
    ss.update("quality", {"abs_bias_max": 0.0001, "wape_max": 10.0})            # only the bias check can fail
    res = pipeline.train_and_publish(force=True)
    assert res["status"] == "PUBLISHED" and res["reason_code"] == "FORECAST_PUBLISHED_WITH_WARNING", res
    a = _gate(res["training_run_id"])["assessment"]
    assert a["quality"]["failed_checks"] == ["ABS_BIAS_MAX"] and a["usage"]["reason"] == "BELOW_THRESHOLD"
    b = next(c for c in a["quality"]["checks"] if c["check"] == "ABS_BIAS_MAX")
    assert abs(b["value"]) > 0.0001 and b["passed"] is False


def test_a_dashboard_never_prefers_a_newer_demo_run_to_the_bigquery_one(client, fast_model):
    _bq_scope()
    res = pipeline.train_and_publish(force=True)
    _demo_run_newer_than_everything()
    st = client.get("/api/system/status").json()
    assert st["latest_forecast_run"]["id"] == res["forecast_run_id"] and st["forecast_state"]["other_source_runs"] == 1
    runs = client.get("/api/forecast-runs?limit=100").json()
    assert runs[0]["id"] == "FCR-DEMO" and runs[0]["active_scope"] is False     # newest, but another source
    first_active = next(r for r in runs if r["active_scope"])
    assert first_active["id"] == res["forecast_run_id"] and first_active["data_source"] == "BIGQUERY"
    assert first_active["assessment"]["usage"] == "USABLE_WITH_WARNING"
    assert client.get("/api/dashboard").json()["forecast"]["data_source"] == "BIGQUERY"
    assert [r["id"] for r in client.get("/api/forecast-runs?data_source=BIGQUERY").json()] == [res["forecast_run_id"]]


def test_without_a_bigquery_forecast_the_state_says_so_and_demo_is_not_shown(client):
    _bq_scope()
    _demo_run_newer_than_everything()
    st = client.get("/api/system/status").json()
    assert st["latest_forecast_run"] is None
    assert st["forecast_state"]["status"] == "NO_FORECAST_FOR_ACTIVE_SOURCE" and st["forecast_state"]["other_source_runs"] == 1
    assert client.get("/api/dashboard").json()["forecast"] is None
    assert all(r["active_scope"] is False for r in client.get("/api/forecast-runs").json())


def test_bigquery_not_ready_is_an_error_never_a_silent_demo_fallback(client, fast_model):
    assert client.post("/api/demo/generate", json={"days": 90, "n_skus": 3, "seed": 1}).status_code == 200
    _bq_scope()
    ss.update("bigquery", {"production_enabled": False})                        # e.g. access lost / re-validation
    with pytest.raises(AppError) as e:
        pipeline.train_and_publish(force=True)
    assert e.value.code == "SOURCE_NOT_READY"
    # 1.2.3: the manual route refuses at once with the reason (409) instead of creating a job skipped later - the
    # expectation changed with the behaviour, the point is the same: an error, never a DEMO fallback
    r = client.post("/api/training/run", json={"force": True})
    assert r.status_code == 409 and r.json()["code"] == "SOURCE_NOT_READY", r.text
    assert _count("SELECT COUNT(*) FROM training_runs") == 0 and _count("SELECT COUNT(*) FROM forecast_runs") == 0
    assert ss.get("general").active_source == "BIGQUERY"                        # never switched to DEMO
    ss.update("bigquery", {"dataset_id": "", "source_table": ""})
    with pytest.raises(AppError) as e:
        pipeline.train_and_publish(force=True)
    assert e.value.code == "BQ_NOT_CONFIGURED"


# ------------------------------------------------------------------ B. selection, incumbent, technical blocks
def test_a_model_in_use_is_kept_when_a_new_low_quality_model_arrives(client, fast_model):
    _bq_scope()
    first = pipeline.train_and_publish(force=True)
    files = sorted(p.name for p in paths.models_dir().iterdir())
    second = pipeline.train_and_publish(force=True)
    assert second["status"] == "CANDIDATE" and second["reason_code"] == "PROMOTION_REVIEW_REQUIRED", second
    assert second["usage"] == "USABLE_WITH_WARNING"
    with db.read() as c:
        assert pipeline.latest_published(resolve_scope(c)["scope_key"], c)["id"] == first["forecast_run_id"]
    assert _tr(first["training_run_id"])["status"] == "ACCEPTED"
    assert set(files) <= {p.name for p in paths.models_dir().iterdir()}       # nothing deleted or overwritten
    prom = _gate(second["training_run_id"])["promotion"]
    assert prom["decision"] == "REVIEW_REQUIRED" and prom["verdict"] in ("BETTER", "WORSE", "EQUAL", "INSUFFICIENT_DATA")
    assert prom["candidate_choice"] in (pipeline.CANDIDATE_LGBM, pipeline.CANDIDATE_BASELINE)


def test_the_baseline_is_published_when_it_beats_lightgbm_on_the_same_points(client, fast_model, monkeypatch):
    _bq_scope()
    real = model.backtest

    def lgbm_worse(p, cfg, mape_min_actual=1.0, cancel=None, collect=False):     # deterministic: LightGBM loses
        bt = real(p, cfg, mape_min_actual, cancel, collect)
        bt["metrics"] = {**bt["metrics"], "wape": bt["baseline_metrics"]["wape"] + 0.25}
        return bt
    monkeypatch.setattr(model, "backtest", lgbm_worse)
    res = pipeline.train_and_publish(force=True)
    assert res["status"] == "PUBLISHED" and res["candidate"] == pipeline.CANDIDATE_BASELINE, res
    tr = _tr(res["training_run_id"])
    sel = json.loads(tr["quality_gate_json"])["selection"]
    assert sel["reason"] == "BASELINE_LOWER_WAPE" and sel["rejected"] == [{"candidate": "LIGHTGBM", "reason": "HIGHER_WAPE"}]
    assert tr["model_path"]                                                      # the LightGBM file is kept for review
    fr = res["forecast_run_id"]
    with db.read() as c:
        run = db.one(c, "SELECT * FROM forecast_runs WHERE id=?", (fr,))
        vals = db.rows(c, "SELECT sku_id, fc_id, horizon_day, yhat, method FROM forecast_values WHERE run_id=?", (fr,))
    assert run["model_version"].startswith("BL28-") and json.loads(run["method_counts_json"]) == {"BASELINE_MOVING_AVERAGE": 10}
    panel = panel_for_run(tr)
    base = np.clip(model.baseline_forecast(panel, 7), 0, None)
    for v in vals:                                                              # exactly the evaluated baseline
        s = panel.keys.index((v["sku_id"], v["fc_id"]))
        assert v["method"] == "BASELINE_MOVING_AVERAGE" and v["yhat"] == pytest.approx(round(base[s, v["horizon_day"] - 1], 4))
    e = client.get(f"/api/forecast-runs/{fr}/explain", params={"sku_id": vals[0]["sku_id"], "fc_id": vals[0]["fc_id"],
                                                               "target_date": run["forecast_origin"]}).json()
    assert e["result"]["method"] == "BASELINE_MOVING_AVERAGE" and e["selection"]["source"] == "STORED"
    assert e["fallback"]["matches_published"] and e["fallback"]["matches_history"] and e["fallback"]["window"] == "LAST_28_DAYS"
    assert client.get("/api/methods").json()["methods"]["BASELINE_MOVING_AVERAGE"]["scope"] == "production"
    ss.update("horizons", {"enabled": [7, 15]})                                 # a baseline run extends without a model
    j = client.post(f"/api/forecast-runs/{fr}/extend").json()
    assert j["status"] == "SUCCEEDED" and j["reason_code"] == "FORECAST_EXTENDED", j


def test_lightgbm_that_cannot_be_trained_leaves_the_baseline_with_low_confidence(fast_model, monkeypatch):
    _bq_scope()
    monkeypatch.setattr(model, "train", lambda p, cfg, cancel=None: (None, {"n_rows": 0, "n_series": p.n_series,
                                                                           "error": "too few training rows"}))
    ss.update("quality", {"below_threshold_policy": "BLOCK"})
    r = pipeline.train_and_publish(force=True)
    assert r["status"] == "REJECTED" and r["reason_code"] == "QUALITY_GATE_FAILED"     # BLOCK = behaviour before 1.2.2
    ss.update("quality", {"below_threshold_policy": "PUBLISH_WITH_WARNING"})
    r = pipeline.train_and_publish(force=True)
    assert r["status"] == "PUBLISHED" and r["candidate"] == pipeline.CANDIDATE_BASELINE, r
    a = _gate(r["training_run_id"])["assessment"]
    assert a["confidence"]["level"] == "LOW" and "MODEL_TRAINED" in a["confidence"]["reasons"]
    assert _tr(r["training_run_id"])["model_path"] is None
    from app import data_checks                     # a baseline run without a model file is a valid state
    chk = {x["check"]: x for x in data_checks.run(paths.db_path(), paths.models_dir())["checks"]}
    assert chk["accepted_model_files"]["status"] == "OK", chk["accepted_model_files"]


def test_empty_or_too_short_data_is_a_specific_technical_block(fast_model):
    _bq_ready_production()
    r = pipeline.train_and_publish(force=True)
    assert r["status"] == "REJECTED" and r["reason_code"] == "DATA_NOT_TRAINABLE"
    with db.read() as c:
        rep = json.loads(db.one(c, "SELECT report_json FROM validation_reports ORDER BY rowid DESC LIMIT 1")["report_json"])
    assert [ch["code"] for ch in rep["checks"]] == ["NO_DATA"]
    _bq_history(days=20)
    r = pipeline.train_and_publish(force=True)
    assert r["status"] == "REJECTED" and r["reason_code"] == "DATA_NOT_TRAINABLE"
    assert _count("SELECT COUNT(*) FROM forecast_runs") == 0


def test_policy_block_rejects_and_the_same_run_is_usable_once_the_policy_allows_it(client, fast_model):
    """The production case of 17/10/2026: a run rejected by the old gate is put in use, without retraining, once the
    policy is PUBLISH_WITH_WARNING - and never when its data changed."""
    _bq_scope()
    ss.update("quality", {"below_threshold_policy": "BLOCK"})
    a = pipeline.train_and_publish(force=True)
    assert a["status"] == "REJECTED" and a["reason_code"] == "QUALITY_GATE_FAILED"
    d = client.get(f"/api/training-runs/{a['training_run_id']}").json()
    assert d["can_promote"] is False and d["promotable"]["reason"] == "POLICY_BLOCK"
    assert _count("SELECT COUNT(*) FROM forecast_runs") == 0
    ss.update("quality", {"below_threshold_policy": "PUBLISH_WITH_WARNING"})
    d = client.get(f"/api/training-runs/{a['training_run_id']}").json()
    assert d["can_promote"] is True and d["promotable"]["kind"] == "BELOW_THRESHOLD"
    assert d["assessment"]["usage"]["status"] == "USABLE_WITH_WARNING"
    st = client.get("/api/system/status").json()["forecast_state"]
    assert st["status"] == "NO_FORECAST_FOR_ACTIVE_SOURCE" and st["latest_attempt"]["promotable"]["ok"] is True
    p = client.post(f"/api/training-runs/{a['training_run_id']}/promote", json={"confirm": True})
    assert p.status_code == 200, p.text
    j = p.json()
    assert j["reason_code"] == "MODEL_PROMOTED" and j["usage"] == "USABLE_WITH_WARNING"
    t = _tr(a["training_run_id"])
    g = json.loads(t["quality_gate_json"])
    assert t["status"] == "ACCEPTED" and g["promotion"]["promoted_from"] == "QUALITY_GATE_FAILED"
    assert g["passed"] is False and g["assessment"]["policy"] == "PUBLISH_WITH_WARNING"     # still reported honestly
    with db.read() as c:
        fr = db.one(c, "SELECT * FROM forecast_runs WHERE id=?", (j["forecast_run_id"],))
    assert fr["data_source"] == "BIGQUERY" and fr["training_run_id"] == a["training_run_id"]
    assert _count("SELECT COUNT(*) FROM alerts WHERE code='FORECAST_PUBLISHED_WITH_WARNING'") == 1
    # a rejected run whose data changed is never published
    ss.update("quality", {"below_threshold_policy": "BLOCK"})
    b = pipeline.train_and_publish(force=True)
    assert b["status"] == "REJECTED"
    ss.update("quality", {"below_threshold_policy": "PUBLISH_WITH_WARNING"})
    scope = resolve_scope()["scope_key"]
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET qty = qty + 1 WHERE rowid = (SELECT MIN(rowid) FROM demand_daily WHERE scope_key=?)",
                  (scope,))
    x = client.post(f"/api/training-runs/{b['training_run_id']}/promote", json={"confirm": True})
    assert x.status_code == 409 and x.json()["code"] == "DATA_CHANGED_SINCE_TRAINING"


def test_selection_rule_and_assessment_units():
    q = ss.QualitySettings()
    s = pipeline.select_candidate({"wape": 0.8074, "n_points": 9}, {"wape": 0.8436, "n_points": 9}, 7, True)
    assert s["chosen"] == "LIGHTGBM" and s["rejected"][0] == {"candidate": "BASELINE_MOVING_AVERAGE", "reason": "NOT_LOWER_WAPE"}
    s = pipeline.select_candidate({"wape": 1.0173}, {"wape": 0.839}, 7, True)       # the 16/10 production runs
    assert s["chosen"] == "BASELINE_MOVING_AVERAGE" and s["reason"] == "BASELINE_LOWER_WAPE"
    assert pipeline.select_candidate({"wape": 0.5}, {"wape": 0.5}, 3, True)["chosen"] == "LIGHTGBM"   # tie keeps LightGBM
    assert pipeline.select_candidate({"wape": None}, {"wape": None}, 3, True)["reason"] == "WAPE_UNDEFINED"
    assert pipeline.select_candidate({"wape": 0.9}, {"wape": 0.1}, 0, True)["reason"] == "NO_BACKTEST_EVALUATION"
    assert pipeline.select_candidate({"wape": 0.1}, {"wape": 0.9}, 3, False)["chosen"] == "BASELINE_MOVING_AVERAGE"
    bt = {"metrics": {"wape": 0.5, "bias": 0.05, "n_points": 10}, "baseline_metrics": {"wape": 0.7, "bias": 0.1, "n_points": 10},
          "reliable": False, "folds": [1]}
    g = pipeline.quality_gate(bt, q)
    a = pipeline.assess(g, pipeline.select_candidate(bt["metrics"], bt["baseline_metrics"], 1, True), q, False, 1, True)
    assert a["quality"]["status"] == "PASS" and a["confidence"]["level"] == "LOW"
    assert set(a["confidence"]["reasons"]) == {"BACKTEST_RELIABLE", "MIN_BACKTEST_POINTS"}
    assert a["usage"] == {"status": "USABLE_WITH_WARNING", "reason": "LOW_CONFIDENCE"}
    blocked = pipeline.assess(g, pipeline.select_candidate(bt["metrics"], bt["baseline_metrics"], 1, True),
                              ss.QualitySettings(below_threshold_policy="BLOCK"), False, 1, True)
    assert blocked["usage"] == {"status": "NOT_USABLE", "reason": "QUALITY_GATE_FAILED"}


def test_a_run_from_before_1_2_2_gets_a_derived_assessment():
    gate = {"passed": False, "thresholds_approved_by_business": False, "checks": [
        {"check": "BACKTEST_RELIABLE", "passed": True, "value": 7, "threshold": None},
        {"check": "MIN_BACKTEST_POINTS", "passed": True, "value": 3351605, "threshold": 200},
        {"check": "WAPE_MAX", "passed": False, "value": 0.8074442313338153, "threshold": 0.6},
        {"check": "ABS_BIAS_MAX", "passed": True, "value": 0.05754006251813735, "threshold": 0.2}]}
    tr = {"status": "REJECTED", "reject_reason": "QUALITY_GATE_FAILED", "model_path": "MV-x.txt",
          "quality_gate_json": json.dumps(gate), "metrics_json": json.dumps({"wape": 0.8074442313338153, "n_points": 3351605}),
          "baseline_metrics_json": json.dumps({"wape": 0.843570680558171, "n_points": 3351605})}
    a = pipeline.run_assessment(tr)
    assert a["derived"] and a["candidate"] == "LIGHTGBM" and a["usage"]["status"] == "USABLE_WITH_WARNING"
    assert pipeline.promotable(tr) == {"ok": True, "kind": "BELOW_THRESHOLD", "candidate": "LIGHTGBM", "failed_checks": ["WAPE_MAX"]}
    assert pipeline.promotable({**tr, "model_path": None})["reason"] == "NO_MODEL_FILE"
    assert pipeline.promotable(tr, ss.QualitySettings(below_threshold_policy="BLOCK"))["reason"] == "POLICY_BLOCK"


def test_baseline_method_example_is_computed_by_the_code():
    import pandas as pd
    from app.ml import features
    days = pd.date_range("2026-01-01", periods=40, freq="D")
    rows = [{"order_date": d, "sku_id": "A", "fc_id": "F", "qty": 3.0} for d in days]
    p = features.build_panel(pd.DataFrame(rows))
    r = model.baseline_run(p, 7)
    assert float(r["window_sum"][0]) == 84.0 and int(r["window_count"][0]) == 28 and r["yhat"][0, 0] == pytest.approx(3.0)
    assert float(r["yhat"][0].sum()) == pytest.approx(21.0)
    assert model.baseline_series_meta(p, r, 0)["fallback_window"] == {"days": 28, "known_days": 28, "sum": 84.0, "rate": 3.0}


# ------------------------------------------------------------------ C. D-0 stays BigQuery-only
def test_d0_snapshot_is_bigquery_data_only_follows_the_key_policy_and_never_turns_the_schedule_on(client):
    from test_v121_d0 import D0, REAL_D0, _prod, _save, _validate
    from app.sync import run_d0_snapshot
    assert client.post("/api/demo/generate", json={"days": 60, "n_skus": 3, "seed": 1}).status_code == 200
    fake = _prod(FakeBQ(schema=LAYOUT, tables={D0: REAL_D0}))
    sched = ss.get("schedule").model_dump()
    demo_snaps = _count("SELECT COUNT(*) FROM d0_snapshots WHERE data_source='DEMO'")
    with db.read() as c:
        hist = c.execute("SELECT COUNT(*), COALESCE(SUM(qty), 0) FROM demand_daily").fetchone()
    vid = _save(client)
    today = timeutil.today_vn()
    assert _validate(client, fake, vid, rows=_d0_rows(today, key_dups="2"))["validation"]["status"] == "VALID"
    fake.responses["d0"] = _d0_rows(today, key_dups="2")
    with pytest.raises(AppError) as e:                                      # BLOCK + repeated keys: nothing written
        run_d0_snapshot("JOB-BLOCK", None, False)
    assert e.value.code == "BQ_KEY_NOT_UNIQUE"
    assert _count("SELECT COUNT(*) FROM d0_snapshots WHERE data_source='BIGQUERY'") == 0
    fake.errors["d0"] = type("ServiceUnavailable", (Exception,), {})("backend error")
    with pytest.raises(Exception):                                          # BigQuery down: no DEMO stand-in
        run_d0_snapshot("JOB-DOWN", None, False)
    del fake.errors["d0"]
    assert client.put("/api/sql-sources/d0/options", json={"key_duplicate_policy": "SUM_ALL"}).status_code == 200
    _validate(client, fake, vid, rows=_d0_rows(today, key_dups="2"))
    res = run_d0_snapshot("JOB-SUM", None, False)
    with db.read() as c:
        snap = db.one(c, "SELECT * FROM d0_snapshots WHERE id=?", (res["snapshot_id"],))
        total = c.execute("SELECT SUM(cumulative_qty) FROM d0_snapshot_values WHERE snapshot_id=?", (res["snapshot_id"],)).fetchone()[0]
        assert tuple(c.execute("SELECT COUNT(*), COALESCE(SUM(qty), 0) FROM demand_daily").fetchone()) == tuple(hist)
    assert snap["data_source"] == "BIGQUERY" and snap["scope_key"].startswith("BIGQUERY:") and snap["order_date"] == str(today)
    assert total == 7.0                                                     # the valid rows of the aggregate, summed
    assert _count("SELECT COUNT(*) FROM d0_snapshots WHERE data_source='DEMO'") == demo_snaps
    assert ss.get("schedule").model_dump() == sched and sched["d0_enabled"] is False
