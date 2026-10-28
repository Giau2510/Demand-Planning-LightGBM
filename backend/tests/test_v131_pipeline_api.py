"""1.3.1 tester checks (C3-T134): the model switches B1 / B2 / B11 through pipeline.train_and_publish, the 1.2.14
fingerprint of a training run stored with every new setting at its default, the B10 feature report of a real training
and the B9 accuracy report job through the runner (hand-computed totals). Integration with fakes: isolated temporary
database (conftest), synthetic data only, fake BigQuery client (no network), data scope stubbed where noted."""
import io
import json
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import pytest
from openpyxl import load_workbook

from app import db, paths
from app import settings_service as ss
from app.api import daily_routes
from app.jobs import runner
from app.ml import accuracy_report as ar
from app.ml import feature_report, features, model, pipeline
from app.ml import forecast_explainer as fe
from app.timeutil import VN_TZ

from test_v1214_forecast_explainer import _get, _publish
from test_v131_model_config import B1_NAMES, FP_PROD_1214, NEW_MODEL_DEFAULTS, _prod, _sha16
from test_v131_refresh import BQ_SCOPE, _bq_settings, _freeze, _no_real_bigquery  # noqa: F401 (autouse fixture)
from test_v131_refresh import NOW as REFRESH_NOW


def _tr(run_id):
    with db.read() as c:
        return db.one(c, "SELECT * FROM training_runs WHERE id=?", (run_id,))


def _fcj(tr):
    return json.loads(tr["feature_config_json"])


def _booster(tr):
    return lgb.Booster(model_file=str(paths.models_dir() / tr["model_path"]))


def _methods(fr_id):
    with db.read() as c:
        return [(r["sku_id"], r["method"], r["fallback_reason"]) for r in db.rows(
            c, "SELECT sku_id, method, fallback_reason FROM forecast_values WHERE run_id=?", (fr_id,))]


def _explained_names(client):
    fe._cache.clear()
    fe._recent.clear()
    r = _get(client)
    assert r["status"] == "OK" and r["verified"] is True, json.dumps(r.get("checks"), indent=1)
    assert all(ch["ok"] for ch in r["checks"]), r["checks"]
    return r["run"]["training_run_id"], [f["name"] for f in r["features"]]


# ================================================================== 1. B1 / B2 / B11 through train_and_publish
def test_model_switches_and_feature_table_through_train_and_publish(client, fast_model):
    ss.update("model", {"forecast_strategy": "DIRECT", "feature_sku_code": False, "horizon_weight_short": 3.0,
                        "horizon_weight_cutoff": 7, "fallback_enabled": False})
    pub = _publish(client)                      # first model of the scope: published (series S9 is 5 days old)
    tr1 = pub["tr"]
    fcj1 = _fcj(tr1)
    cfg1, names1 = fcj1["config"], fcj1["features"]
    assert (cfg1["feature_sku_code"], cfg1["fallback_enabled"], cfg1["horizon_weight_short"],
            cfg1["horizon_weight_cutoff"], cfg1["feature_table"]) == (False, False, 3.0, 7, None)
    assert fcj1["settings_switches"]["feature_sku_code"] is False
    assert fcj1["settings_switches"]["fallback_enabled"] is False
    # B1: the 1.2.14 list of the same resolved configuration without sku_code, in order (a subset of the 35 B1 names)
    full = features.feature_names(ss.ModelSettings.model_validate({**cfg1, "feature_sku_code": True}))
    assert "sku_code" in full and names1 == [n for n in full if n != "sku_code"]
    assert "fc_code" in names1 and names1 == [n for n in B1_NAMES if n in names1]
    assert fcj1["config_fingerprint"] == pipeline.config_fingerprint(cfg1)
    assert fcj1["config_fingerprint"] != _sha16({k: v for k, v in cfg1.items() if k not in NEW_MODEL_DEFAULTS})
    assert "feature_contri" not in json.loads(tr1["params_json"])
    assert _booster(tr1).feature_name() == names1
    # B2: every series of the published forecast is LightGBM, also the 5-day-old S9 (a fallback rule in 1.2.14)
    m1 = _methods(pub["fr"]["id"])
    assert {m for _s, m, _f in m1} == {model.METHOD_LGBM} and {f for _s, _m, f in m1} == {None}
    assert "S9" in {s for s, _m, _f in m1}
    assert json.loads(pub["fr"]["method_counts_json"]) == {model.METHOD_LGBM: pub["fr"]["n_series"]}
    # B11: the rows of the feature table = the features a new training would use (table not applied)
    g = client.get("/api/feature-table").json()
    assert [r["feature"] for r in g["rows"]] == names1 and all(r["is_default"] for r in g["rows"])

    r2 = pipeline.train_and_publish(force=True)          # trained BEFORE the rule: a candidate with run 1's config
    assert r2["status"] == "CANDIDATE", r2
    before = {rid: _tr(rid)["feature_config_json"] for rid in (tr1["id"], r2["training_run_id"])}
    put = client.put("/api/feature-table", json={"features": {"lag_1": {"enabled": False},
                                                              "roll_mean_7": {"contri": 2.0}},
                                                 "confirm": True, "note": "C3 test"})
    assert put.status_code == 200 and put.json()["saved"] is True
    rows = {r["feature"]: r for r in put.json()["rows"]}
    assert list(rows) == names1                                       # a disabled row stays listed
    assert rows["lag_1"]["enabled"] is False and rows["roll_mean_7"]["contri"] == 2.0
    r3 = pipeline.train_and_publish(force=True)          # the NEXT training takes the table
    assert r3["status"] == "CANDIDATE", r3
    tr3 = _tr(r3["training_run_id"])
    fcj3 = _fcj(tr3)
    assert fcj3["config"]["feature_table"] == {"lag_1": {"enabled": False, "contri": 1.0},
                                               "roll_mean_7": {"enabled": True, "contri": 2.0}}
    names3 = fcj3["features"]
    assert names3 == [n for n in names1 if n != "lag_1"]
    assert json.loads(tr3["params_json"])["feature_contri"] == [2.0 if n == "roll_mean_7" else 1.0 for n in names3]
    assert _booster(tr3).feature_name() == names3
    assert fcj3["config_fingerprint"] == pipeline.config_fingerprint(fcj3["config"]) != fcj1["config_fingerprint"]
    assert _fcj(_tr(r2["training_run_id"]))["config_fingerprint"] == fcj1["config_fingerprint"]
    # the older runs keep their own stored configuration
    assert {rid: _tr(rid)["feature_config_json"] for rid in before} == before
    assert _explained_names(client) == (tr1["id"], names1)                 # run in use, trained before the rule
    p2 = pipeline.promote_candidate(r2["training_run_id"])                 # older candidate promoted after the rule
    assert p2["status"] == "PUBLISHED", p2
    assert {m for _s, m, _f in _methods(p2["forecast_run_id"])} == {model.METHOD_LGBM}
    assert _explained_names(client) == (r2["training_run_id"], names1)
    p3 = pipeline.promote_candidate(r3["training_run_id"])
    assert p3["status"] == "PUBLISHED", p3
    assert _explained_names(client) == (r3["training_run_id"], names3)
    with db.read() as c:      # daily_forecast is off: no B10 row for any of the runs
        assert c.execute("SELECT COUNT(*) FROM training_feature_importance").fetchone()[0] == 0


# ================================================================== 2. defaults keep the 1.2.14 fingerprint
def test_defaults_store_the_1_2_14_fingerprint_with_the_training_run(small_demo):
    res = pipeline.train_and_publish()
    assert res["status"] == "PUBLISHED", res
    tr = _tr(res["training_run_id"])
    fcj = _fcj(tr)
    cfg = fcj["config"]
    assert {k: cfg[k] for k in NEW_MODEL_DEFAULTS} == NEW_MODEL_DEFAULTS
    assert fcj["config_fingerprint"] == _sha16({k: v for k, v in cfg.items() if k not in NEW_MODEL_DEFAULTS})
    assert json.loads(tr["params_json"]) == model.lgb_params(ss.ModelSettings.model_validate(cfg))   # no feature_contri
    assert "sku_code" in fcj["features"] and fcj["features"] == features.feature_names(
        ss.ModelSettings.model_validate(cfg))


def test_production_like_defaults_store_8468ebe66d1706f7(monkeypatch):
    """The production configuration (DIRECT, open hours, customers, ISO weekday, default sizes) on a BIGQUERY scope:
    the run record is written before the backtest, which is stopped here (the default sizes would take minutes)."""
    _freeze(REFRESH_NOW)
    from app.data.demo import create_demo_batch
    from app.jobs import flows
    demo = create_demo_batch(days=150, n_skus=8, seed=3)
    _bq_settings()
    with db.tx() as c:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                  "avg_unit_price, loaded_at, open_hours, open_hours_status, customer_count, repeat_customer_count, "
                  "repeat_interval_days_sum) SELECT ?, 'BIGQUERY', order_date, sku_id, fc_id, qty, n_orders, "
                  "COALESCE(avg_unit_price, 10.0), loaded_at, 10.0, 'OK', n_orders, 0, 0 FROM demand_daily "
                  "WHERE scope_key=?", (BQ_SCOPE, demo["batch_id"]))
    ss.update("model", {"forecast_strategy": "DIRECT", "feature_customer": True, "feature_promotion": False,
                        "feature_discount": False})
    monkeypatch.setattr(flows, "_bq_ready", lambda c, blockers: None)

    def stop(*a, **k):
        raise RuntimeError("stopped after the run record (test)")
    monkeypatch.setattr(model, "backtest", stop)
    res = pipeline.train_and_publish(force=True, source="BIGQUERY")
    assert res["status"] == "FAILED" and res["failed_stage"] == "BACKTESTING", res
    fcj = _fcj(_tr(res["training_run_id"]))
    want = {k: v for k, v in _prod().model_dump().items() if k not in NEW_MODEL_DEFAULTS}
    assert {k: v for k, v in fcj["config"].items() if k not in NEW_MODEL_DEFAULTS} == want
    assert fcj["config_fingerprint"] == FP_PROD_1214 == "8468ebe66d1706f7"


# ================================================================== 3. B10 after a real training
def test_b10_rows_workbook_and_api_after_a_training(client, small_demo):
    ss.update("daily_forecast", {"enabled": True})
    res = pipeline.train_and_publish()
    assert res["status"] == "PUBLISHED", res
    run = res["training_run_id"]
    tr = _tr(run)
    names = _fcj(tr)["features"]
    with db.read() as c:
        rows = db.rows(c, "SELECT feature, feature_group, gain, split, gain_share, split_share, rank "
                          "FROM training_feature_importance WHERE training_run_id=? ORDER BY rank", (run,))
    assert len(rows) == len(names) and sorted(r["feature"] for r in rows) == sorted(names)
    assert [r["rank"] for r in rows] == list(range(1, len(names) + 1))
    gains = [r["gain"] for r in rows]
    assert gains == sorted(gains, reverse=True)
    assert sum(r["gain_share"] for r in rows) == pytest.approx(1.0)
    assert sum(r["split_share"] for r in rows) == pytest.approx(1.0)
    booster = _booster(tr)
    exp_gain = dict(zip(booster.feature_name(), booster.feature_importance("gain")))
    exp_split = dict(zip(booster.feature_name(), booster.feature_importance("split")))
    for r in rows:
        assert r["gain"] == pytest.approx(float(exp_gain[r["feature"]]), rel=1e-6)
        assert r["split"] == int(exp_split[r["feature"]])
        assert r["feature_group"] == feature_report.feature_group(r["feature"])
    p = paths.reports_dir() / "theo-doi" / f"ty-trong-bien-{run}.xlsx"
    assert p.is_file()
    wb = load_workbook(p)
    assert wb.sheetnames == ["Thông tin", "Theo biến", "Theo nhóm biến"]
    assert wb["Thông tin"]["A1"].value == "Chạy thử – chưa dùng để mua hàng"
    by_feature = list(wb["Theo biến"].iter_rows(min_row=2, values_only=True))
    assert [(x[0], x[1]) for x in by_feature] == [(r["rank"], r["feature"]) for r in rows]
    groups = list(wb["Theo nhóm biến"].iter_rows(min_row=2, values_only=True))
    assert sum(x[1] for x in groups) == len(names)
    # API: the stored rows (TABLE) and the workbook; the label follows the current trial mode
    api = client.get(f"/api/training-runs/{run}/feature-importance").json()
    assert api["source"] == "TABLE" and api["training_run_id"] == run
    assert [r["feature"] for r in api["rows"]] == [r["feature"] for r in rows]
    assert sum(gr["n_features"] for gr in api["groups"]) == len(names)
    x = client.get(f"/api/training-runs/{run}/feature-importance.xlsx")
    assert x.status_code == 200 and f"ty-trong-bien-{run}.xlsx" in x.headers["content-disposition"]
    assert load_workbook(io.BytesIO(x.content))["Thông tin"]["A1"].value == "Chạy thử – chưa dùng để mua hàng"
    off = client.post("/api/daily-forecast/trial-mode",
                      json={"trial_mode": False, "confirm_text": client.get("/api/daily-forecast/status")
                            .json()["trial_confirm_text"]})
    assert off.status_code == 200 and off.json()["changed"] is True
    x = client.get(f"/api/training-runs/{run}/feature-importance.xlsx")
    assert load_workbook(io.BytesIO(x.content))["Thông tin"]["A1"].value == "Lần huấn luyện"


# ================================================================== 4. B9 job through the runner
SCOPE = {"scope_key": "K9", "data_source": "DEMO", "label": "k9"}
F1S1, F1S2, F2S3 = ("F1", "S1", "A"), ("F1", "S2", "C"), ("F2", "S3", None)
# (series, h, final_qty) of the latest run of 12/10 (single run) and 18/10 (two runs, the newer one first)
VALUES_12 = [(F1S1, h, q) for h, q in ((1, 10), (2, 20), (3, 9), (4, 9), (5, 6), (6, 9), (7, 9), (8, 50))] + \
            [(F1S2, 1, 0), (F1S2, 2, 2), (F1S2, 7, 6)]
VALUES_18 = [(F1S1, 1, 13), (F1S1, 2, 14), (F1S1, 8, 9), (F2S3, 1, 30), (F2S3, 3, 30)]
# (series, date, demand, open hours)
ACTUALS = [(F1S1, "2026-10-12", 10, 8), (F1S1, "2026-10-13", 10, 8), (F1S1, "2026-10-14", 5, 0),
           (F1S1, "2026-10-15", 7, None), (F1S1, "2026-10-16", None, 8), (F1S1, "2026-10-18", 10, 8),
           (F1S1, "2026-10-19", 10, 8), (F1S2, "2026-10-12", 1, 8), (F1S2, "2026-10-13", 5, 8),
           (F1S2, "2026-10-18", 10, 8), (F2S3, "2026-10-18", 40, 8), (F2S3, "2026-10-20", 30, 8)]
# the evaluated cells, by hand: (target, h, group, final, demand, category). Not evaluated: 14/10 closed, 15/10 hours
# unknown, h = 8, 20/10 = the business day, the older run of 18/10 and the other scope.
CELLS = [("2026-10-12", 1, "A", 10, 10, "DUNG"), ("2026-10-13", 2, "A", 20, 10, "DU_NHIEU"),
         ("2026-10-16", 5, "A", 6, 0, "DU_NHIEU"), ("2026-10-12", 1, "C", 0, 1, "DUNG"),
         ("2026-10-13", 2, "C", 2, 5, "THIEU_NHIEU"), ("2026-10-18", 7, "C", 6, 10, "THIEU_IT"),
         ("2026-10-18", 7, "A", 9, 10, "DUNG"),
         ("2026-10-18", 1, "A", 13, 10, "DUNG"), ("2026-10-19", 2, "A", 14, 10, "DU_IT"),
         ("2026-10-18", 1, "B", 30, 40, "THIEU_IT")]
COLS = ("A", "B", "C", "TOTAL")


def _frr(c, rid, fdate, values, created, scope="K9"):
    c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, config_version, "
              "trial_mode, horizon, n_series, n_lightgbm, n_fallback, created_at) VALUES (?,?,?,?, 'PUBLISHED', 'cv', "
              "1, 8, 2, 2, 0, ?)", (rid, scope, fdate, fdate, created))
    d0 = datetime.fromisoformat(fdate).toordinal()
    c.executemany("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, lgb_raw, "
                  "final_qty, method, group_code) VALUES (?,?,?,?,?,?,?, 'LIGHTGBM', ?)",
                  [(rid, h, datetime.fromordinal(d0 + h - 1).date().isoformat(), s[0], s[1], float(q), q, s[2])
                   for s, h, q in values])


def _expected(cells) -> dict:
    """TOTAL entry of one view computed from the hand-classified cells (independent of the module)."""
    n = {k: {col: 0 for col in COLS} for k in ar.CATEGORIES}
    dev = {k: {col: 0.0 for col in COLS} for k in ar.CATEGORIES}
    dem = {col: 0.0 for col in COLS}
    for _t, _h, g, f, d, k in cells:
        for col in (g, "TOTAL"):
            n[k][col] += 1
            dev[k][col] += abs(f - d)
            dem[col] += d
    slots = len({(t, h) for t, h, *_ in cells})
    ncol = {col: sum(n[k][col] for k in ar.CATEGORIES) for col in COLS}
    dcol = {col: sum(dev[k][col] for k in ar.CATEGORIES) for col in COLS}

    def r(x, y):
        return x / y if y > 0 else 0.0
    return {"period": "TOTAL", "slots": slots,
            "sku_per_day": {k: {col: r(n[k][col], slots) for col in COLS} for k in ar.CATEGORIES},
            "sku_share": {k: {col: r(n[k][col], ncol[col]) for col in COLS} for k in ar.CATEGORIES},
            "qty_dev": {**{k: dict(dev[k]) for k in ar.CATEGORIES}, "TOTAL": dcol}, "demand": dem,
            "qty_dev_share": {**{k: {col: r(dev[k][col], dem[col]) for col in COLS} for k in ar.CATEGORIES},
                              "TOTAL": {col: r(dcol[col], dem[col]) for col in COLS}}}


def _flat(d, prefix=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        else:
            out[f"{prefix}{k}"] = v
    return out


def test_b9_report_job_through_the_runner_matches_the_hand_computation(client, monkeypatch):
    _freeze(datetime(2026, 10, 20, 9, 35, tzinfo=VN_TZ))
    ss.update("daily_forecast", {"enabled": True})
    ss.update("schedule", {"report_enabled": True})
    monkeypatch.setattr(ar, "resolve_scope", lambda *a, **k: dict(SCOPE))
    monkeypatch.setattr(daily_routes, "resolve_scope", lambda *a, **k: dict(SCOPE))
    with db.tx() as c:
        _frr(c, "R12", "2026-10-12", VALUES_12, "2026-10-12T01:00:00+00:00")
        # 18/10: the newer run is inserted FIRST (created_at decides, not the insertion order)
        _frr(c, "R18-NEW", "2026-10-18", VALUES_18, "2026-10-18T03:00:00+00:00")
        _frr(c, "R18-OLD", "2026-10-18", [(s, h, 99) for s, h, _q in VALUES_18], "2026-10-18T01:00:00+00:00")
        _frr(c, "R18-Z", "2026-10-18", [(s, h, 77) for s, h, _q in VALUES_18], "2026-10-18T05:00:00+00:00",
             scope="Z")
        c.executemany("INSERT INTO actual_daily(scope_key, date, fc_code, sku_code, demand, total_open_hours, "
                      "updated_at) VALUES ('K9',?,?,?,?,?, 'x')", [(d, s[0], s[1], q, h) for s, d, q, h in ACTUALS])
    job = runner.execute("ACCURACY_REPORT", "ACCURACY_REPORT:2026-10-20", "SCHEDULE", None,
                         {"business_date": "2026-10-20"})
    assert (job["status"], job["reason_code"]) == ("SUCCEEDED", "ACCURACY_REPORT_WRITTEN"), job
    with db.read() as c:
        sched = db.one(c, "SELECT * FROM accuracy_report_runs WHERE job_id=?", (job["id"],))
    assert (sched["run_kind"], sched["status"], sched["run_date"], sched["n_cells"]) == ("SCHEDULED", "DONE",
                                                                                         "2026-10-20", 10)
    assert (sched["period_start"], sched["period_end"]) == ("2026-10-12", "2026-10-19") and sched["error"] is None
    summary = json.loads(sched["summary_json"])
    for view, cells in (("D1", [x for x in CELLS if x[1] == 1]), ("D7", CELLS)):
        got, want = _flat(summary[view]), _flat(_expected(cells))
        assert set(got) == set(want), view
        for k in want:
            assert got[k] == pytest.approx(want[k]), (view, k, got[k], want[k])
    # spot values, literal
    assert (summary["D1"]["slots"], summary["D7"]["slots"]) == (2, 6)
    assert summary["D1"]["qty_dev"]["TOTAL"]["TOTAL"] == 14 and summary["D1"]["demand"]["TOTAL"] == 61
    assert summary["D7"]["qty_dev"]["TOTAL"]["TOTAL"] == 42 and summary["D7"]["demand"]["TOTAL"] == 106
    assert summary["D7"]["qty_dev_share"]["TOTAL"]["TOTAL"] == pytest.approx(42 / 106)
    assert summary["D7"]["sku_share"]["DU_NHIEU"]["A"] == pytest.approx(2 / 6)
    p1 = Path(sched["report_path"])
    assert p1.parent == paths.reports_dir() / "theo-doi" and p1.name == "bao-cao-do-chinh-xac-20261020-093500.xlsx"
    assert load_workbook(p1).sheetnames == ["Thông tin", "Ngày thứ 1", "7 ngày"]
    # the manual button: trigger MANUAL, same numbers, a new file (never overwritten), the same created_at second
    man = runner.run_report_now("2026-10-20")
    assert (man["status"], man["trigger"]) == ("SUCCEEDED", "MANUAL"), man
    with db.read() as c:
        mrow = db.one(c, "SELECT * FROM accuracy_report_runs WHERE job_id=?", (man["id"],))
    assert mrow["run_kind"] == "MANUAL" and json.loads(mrow["summary_json"]) == summary
    assert Path(mrow["report_path"]).name == "bao-cao-do-chinh-xac-20261020-093500-2.xlsx"
    assert mrow["created_at"] == sched["created_at"]
    lst = client.get("/api/accuracy-reports").json()
    assert [r["id"] for r in lst] == [mrow["id"], sched["id"]]          # newest first, tie -> rowid DESC
    d = client.get(f"/api/accuracy-reports/{sched['id']}/download")
    assert d.status_code == 200 and d.content == p1.read_bytes()
