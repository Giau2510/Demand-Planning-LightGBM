"""v1.1.1: job stages, horizon coverage/extension, forecast explanations, intraday actual, localised Excel."""
import io
import json
import math
from datetime import date as date_cls, datetime, timedelta, timezone

import numpy as np
import pytest
from openpyxl import load_workbook

from app import db
from app import settings_service as ss
from app import timeutil
from app.jobs import runner
from app.ml import model, pipeline
from app.qty import business_qty
from app.timeutil import VN_TZ


def _job(client, jid):
    return client.get(f"/api/jobs/{jid}").json()


def _train(client, force=False):
    j = client.post("/api/training/run", json={"force": force}).json()
    return _job(client, j["id"])


@pytest.fixture
def demo_run(client, fast_model):
    ss.update("horizons", {"enabled": [7]})
    assert client.post("/api/demo/generate", json={"days": 150, "n_skus": 8, "seed": 3}).status_code == 200
    j = _train(client)
    assert j["reason_code"] == "FORECAST_PUBLISHED", j
    return j["result"]["result"]["forecast_run_id"]


# ------------------------------------------------------------------ K1 job status
def test_stage_history_follows_the_real_pipeline(client, demo_run):
    j = client.get("/api/jobs?job_type=TRAIN_PUBLISH").json()[0]
    stages = [h["stage"] for h in j["stage_history"]]
    expect = ["QUEUED", "STARTED", "VALIDATING_DATA", "PREPARING_DATA", "BACKTESTING", "TRAINING",
              "QUALITY_GATE", "FORECASTING", "PUBLISHING", "DONE"]
    assert stages == expect
    assert j["stage"] == "DONE" and j["elapsed_seconds"] is not None and j["stale"] is False
    res = j["result"]["result"]
    assert res["training_status"] == "ACCEPTED" and res["status"] == "PUBLISHED"   # both shown separately


def test_quality_gate_fail_and_training_failure_are_distinct(client, demo_run, monkeypatch):
    ss.update("quality", {"wape_max": 0.0001, "below_threshold_policy": "BLOCK"})     # 1.2.2: rejection = BLOCK only
    j = _train(client, force=True)
    assert j["status"] == "SUCCEEDED" and j["reason_code"] == "QUALITY_GATE_FAILED"
    assert [h["stage"] for h in j["stage_history"]][-2:] == ["QUALITY_GATE", "DONE"]
    ss.update("quality", {"wape_max": 0.6})

    def boom(*a, **k):
        raise RuntimeError("simulated")
    monkeypatch.setattr(model, "train", boom)        # model.train is first called inside the backtest
    j = _train(client, force=True)
    assert j["reason_code"] == "TRAINING_FAILED" and j["result"]["result"]["failed_stage"] == "BACKTESTING"
    assert j["status"] == "SUCCEEDED" and j["result"]["result"]["status"] == "FAILED"   # job ran; training failed


def _fail_publish(*a, **k):
    raise RuntimeError("disk full (simulated)")


def test_publish_failure_of_a_first_model_leaves_no_accepted_run(client, fast_model, monkeypatch):
    ss.update("horizons", {"enabled": [7]})
    assert client.post("/api/demo/generate", json={"days": 150, "n_skus": 8, "seed": 3}).status_code == 200
    monkeypatch.setattr(pipeline, "_publish_run", _fail_publish)
    j = _train(client)
    assert j["reason_code"] == "PUBLISH_FAILED" and j["result"]["result"]["failed_stage"] == "PUBLISHING"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM forecast_runs").fetchone()[0] == 0
        tr = db.one(c, "SELECT status, reject_reason FROM training_runs ORDER BY started_at DESC, rowid DESC LIMIT 1")
    assert tr == {"status": "FAILED", "reject_reason": "PUBLISH_FAILED"}   # never ACCEPTED without its run


def test_publish_failure_after_training_keeps_previous_forecast(client, demo_run, monkeypatch):
    # 1.1.7: a second model is a candidate; it is published only by an explicit promotion, which is atomic too
    j = _train(client, force=True)
    assert j["reason_code"] == "PROMOTION_REVIEW_REQUIRED", j
    cand = j["result"]["result"]["training_run_id"]
    monkeypatch.setattr(pipeline, "_publish_run", _fail_publish)
    with pytest.raises(RuntimeError):          # TestClient re-raises; the app answers INTERNAL_ERROR (500)
        client.post(f"/api/training-runs/{cand}/promote", json={"confirm": True})
    with db.read() as c:
        assert [r[0] for r in c.execute("SELECT id FROM forecast_runs")] == [demo_run]
        tr = db.one(c, "SELECT status, reject_reason FROM training_runs WHERE id=?", (cand,))
    assert tr == {"status": "REJECTED", "reject_reason": "PROMOTION_REVIEW_REQUIRED"}   # never ACCEPTED without its run


def test_no_duplicate_job_and_resume_after_reload(client):
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, "
                  "created_at, stage, stage_updated_at) VALUES ('J-RUN','TRAIN_PUBLISH','k-run','MANUAL','RUNNING',1,1,"
                  "'2026-01-01T00:00:00+00:00','TRAINING','2026-01-01T00:00:00+00:00')")
    r = client.post("/api/training/run", json={}).json()
    assert r["id"] == "J-RUN" and r["already_active"] is True                     # second click -> same job
    assert client.get("/api/jobs/active?job_type=TRAIN_PUBLISH").json()["id"] == "J-RUN"
    assert _job(client, "J-RUN")["stale"] is True                                  # no update for > timeout
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM job_runs WHERE job_type='TRAIN_PUBLISH'").fetchone()[0] == 1


def test_interrupted_manual_job_is_not_shown_running_forever(client):
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, "
                  "created_at, stage) VALUES ('J-INT','TRAIN_PUBLISH','k-int','MANUAL','RUNNING',1,1,'x','BACKTESTING')")
    runner.recover_interrupted()
    j = _job(client, "J-INT")
    assert j["status"] == "FAILED" and j["reason_code"] == "INTERRUPTED" and j["stage"] == "INTERRUPTED"
    assert j["stage_history"][-1]["message"] == "was BACKTESTING"


# ------------------------------------------------------------------ K2 horizons
def test_horizon_added_after_run_is_not_faked_and_can_be_extended(client, demo_run):
    old = client.get(f"/api/forecast-runs/{demo_run}").json()
    assert old["horizons"] == [7] and old["max_horizon"] == 7
    ss.update("horizons", {"enabled": [7, 15]})                                   # configured AFTER the run
    cov = client.get(f"/api/forecast-runs/{demo_run}").json()["horizon_coverage"]
    assert cov["run_horizons"] == [7] and cov["configured_missing_in_run"] == [15]
    assert cov["can_extend_without_retraining"] is True
    assert client.get(f"/api/forecast-runs/{demo_run}/summary?horizon=15").status_code == 422   # no fake 15d
    with db.read() as c:
        before = db.rows(c, "SELECT * FROM forecast_values WHERE run_id=? ORDER BY sku_id, fc_id, target_date", (demo_run,))
        n_train = c.execute("SELECT COUNT(*) FROM training_runs").fetchone()[0]
    j = client.post(f"/api/forecast-runs/{demo_run}/extend").json()
    j = _job(client, j["id"])
    assert j["reason_code"] == "FORECAST_EXTENDED", j
    assert [h["stage"] for h in j["stage_history"]] == ["QUEUED", "STARTED", "VERIFYING_MODEL", "PREPARING_DATA",
                                                        "FORECASTING", "PUBLISHING", "DONE"]
    new_id = j["result"]["result"]["forecast_run_id"]
    new = client.get(f"/api/forecast-runs/{new_id}").json()
    assert new["horizons"] == [7, 15] and new["max_horizon"] == 15 and new["derived_from_run_id"] == demo_run
    assert new["model_version"] == old["model_version"] and new["data_as_of"] == old["data_as_of"]
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM training_runs").fetchone()[0] == n_train      # no retraining
        after_old = db.rows(c, "SELECT * FROM forecast_values WHERE run_id=? ORDER BY sku_id, fc_id, target_date", (demo_run,))
        new7 = db.rows(c, "SELECT sku_id, fc_id, target_date, yhat, method FROM forecast_values WHERE run_id=? "
                          "AND horizon_day<=7 ORDER BY sku_id, fc_id, target_date", (new_id,))
    assert after_old == before                                                    # historical run untouched
    assert new7 == [{k: r[k] for k in ("sku_id", "fc_id", "target_date", "yhat", "method")} for r in before]
    s15 = client.get(f"/api/forecast-runs/{new_id}/summary?horizon=15").json()
    s7 = client.get(f"/api/forecast-runs/{demo_run}/summary?horizon=7").json()
    origin = datetime.fromisoformat(new["forecast_origin"]).date()
    assert s15["start_date"] == str(origin) and s15["end_date"] == str(origin + timedelta(days=14))
    assert s7["end_date"] == str(origin + timedelta(days=6)) and len(s15["daily"]) == 15
    # switching back to the old run still shows exactly its own data
    assert client.get(f"/api/forecast-runs/{demo_run}/summary?horizon=7").json()["grand_total"] == s7["grand_total"]
    assert client.post(f"/api/forecast-runs/{new_id}/extend").json()["code"] == "NOTHING_TO_EXTEND"


def test_extension_refused_when_data_changed(client, demo_run):
    ss.update("horizons", {"enabled": [7, 15]})
    client.post("/api/demo/generate", json={"days": 150, "n_skus": 8, "seed": 4})     # old dataset retired
    cov = client.get(f"/api/forecast-runs/{demo_run}").json()["horizon_coverage"]
    assert cov["can_extend_without_retraining"] is False and cov["cannot_extend_reason"] == "DATA_CHANGED_SINCE_TRAINING"
    r = client.post(f"/api/forecast-runs/{demo_run}/extend")
    assert r.status_code == 409 and r.json()["code"] == "DATA_CHANGED_SINCE_TRAINING"


def test_next_run_uses_new_configuration(client, demo_run):
    ss.update("horizons", {"enabled": [7, 15]})
    j = _train(client, force=True)
    assert j["reason_code"] == "PROMOTION_REVIEW_REQUIRED"            # 1.1.7: the user decides to replace the model
    p = client.post(f"/api/training-runs/{j['result']['result']['training_run_id']}/promote", json={"confirm": True}).json()
    run = client.get(f"/api/forecast-runs/{p['forecast_run_id']}").json()
    assert run["horizons"] == [7, 15] and run["max_horizon"] == 15


# ------------------------------------------------------------------ K3 explanations
def _rows_by_method(client, run_id):
    vals = client.get(f"/api/forecast-runs/{run_id}/values?limit=5000").json()["rows"]
    out = {}
    for r in vals:
        out.setdefault(r["method"], []).append(r)
    return out


def test_lightgbm_explanation_is_exact_and_leak_free(client, demo_run):
    rows = _rows_by_method(client, demo_run)["LIGHTGBM"]
    r1 = next(r for r in rows if r["horizon_day"] == 1)
    r3 = next(r for r in rows if r["horizon_day"] == 3 and r["sku_id"] == r1["sku_id"] and r["fc_id"] == r1["fc_id"])
    e1 = client.get(f"/api/forecast-runs/{demo_run}/explain", params={"sku_id": r1["sku_id"], "fc_id": r1["fc_id"],
                                                                       "target_date": r1["target_date"]}).json()
    lg = e1["lightgbm"]
    assert lg["status"] == "OK" and lg["matches_published"] and lg["reproduced_yhat"] == r1["yhat"]
    assert lg["link"] == "exp"                                                    # tweedie objective
    assert math.isclose(lg["prediction_before_clip"], math.exp(lg["bias"] + sum(f["contribution"] for f in lg["features"])),
                        rel_tol=1e-9)
    assert math.isclose(max(lg["prediction_before_clip"], 0), r1["yhat"], abs_tol=1e-4)
    from app.ml.features import feature_names
    assert sorted(f["name"] for f in lg["features"]) == sorted(feature_names(ss.get("model")))
    assert lg["uses_forecast_inputs"] is False                                   # day 1: actual history only
    assert all(d["date"] <= e1["identity"]["data_as_of"] for d in e1["history"]["days"])   # no future data
    assert e1["selection"]["reason_code"] == "LIGHTGBM_ELIGIBLE" and e1["selection"]["source"] == "STORED"
    e3 = client.get(f"/api/forecast-runs/{demo_run}/explain", params={"sku_id": r3["sku_id"], "fc_id": r3["fc_id"],
                                                                       "target_date": r3["target_date"]}).json()
    src = {f["name"]: f["source"] for f in e3["lightgbm"]["features"]}
    assert src["lag_1"] == "FORECAST" and src["lag_2"] == "FORECAST" and src["lag_3"] == "ACTUAL"
    assert e3["lightgbm"]["uses_forecast_inputs"] is True and e3["lightgbm"]["matches_published"]


def test_fallback_explanations_match_the_code(client, demo_run):
    from app.data.demand import load_demand
    from app.ml.features import build_panel
    by = _rows_by_method(client, demo_run)
    cfg = ss.get("model")
    run = client.get(f"/api/forecast-runs/{demo_run}").json()
    panel = build_panel(load_demand(run["scope_key"]), max_days=cfg.max_train_days)
    checked = 0
    for method in ("FALLBACK_NEW_SERIES", "FALLBACK_INTERMITTENT", "FALLBACK_INACTIVE_ZERO"):
        for r in by.get(method, [])[:1]:
            e = client.get(f"/api/forecast-runs/{demo_run}/explain",
                           params={"sku_id": r["sku_id"], "fc_id": r["fc_id"], "target_date": r["target_date"]}).json()
            fb = e["fallback"]
            assert fb["matches_published"] and fb["value_rounded"] == r["yhat"]
            s = panel.keys.index((r["sku_id"], r["fc_id"]))
            y = panel.Y[s]
            if method == "FALLBACK_NEW_SERIES":                  # independent recomputation from the panel
                known = y[~np.isnan(y)]
            elif method == "FALLBACK_INTERMITTENT":
                w = y[-cfg.fallback_window_days:]
                known = w[~np.isnan(w)]
            else:
                known = np.array([])
            if method != "FALLBACK_INACTIVE_ZERO":
                assert fb["known_days"] == len(known) and math.isclose(fb["sum"], known.sum())
                assert math.isclose(fb["rate"], known.sum() / len(known))
            else:
                assert fb["rate"] == 0.0 and r["yhat"] == 0.0
            assert "lightgbm" not in e                                           # a fallback is never "LightGBM"
            checked += 1
    assert checked >= 2


def test_old_run_without_metadata_is_recomputed_or_reported(client, demo_run):
    with db.tx() as c:   # simulate a pre-1.1.1 run: same values, no forecast_series_meta rows
        r = db.one(c, "SELECT * FROM forecast_runs WHERE id=?", (demo_run,))
        c.execute("INSERT INTO forecast_runs(id, training_run_id, model_version, scope_key, data_source, forecast_origin, "
                  "data_as_of, horizons_json, max_horizon, n_series, method_counts_json, status, created_at) "
                  "VALUES ('FCR-OLD',?,?,?,?,?,?,?,?,?,?, 'PUBLISHED', ?)",
                  (r["training_run_id"], r["model_version"], r["scope_key"], r["data_source"], r["forecast_origin"],
                   r["data_as_of"], r["horizons_json"], r["max_horizon"], r["n_series"], r["method_counts_json"],
                   r["created_at"]))
        c.execute("INSERT INTO forecast_values SELECT 'FCR-OLD', sku_id, fc_id, target_date, horizon_day, yhat, method, "
                  "fallback_reason FROM forecast_values WHERE run_id=?", (demo_run,))
    v = client.get("/api/forecast-runs/FCR-OLD/values?limit=1").json()["rows"][0]
    e = client.get("/api/forecast-runs/FCR-OLD/explain", params={k: v[k] for k in ("sku_id", "fc_id", "target_date")}).json()
    assert e["selection"]["source"] == "RECOMPUTED" and e["selection"]["method"] == v["method"]
    client.post("/api/demo/generate", json={"days": 150, "n_skus": 8, "seed": 9})   # data of that run is gone now
    e = client.get("/api/forecast-runs/FCR-OLD/explain", params={k: v[k] for k in ("sku_id", "fc_id", "target_date")}).json()
    assert e["selection"]["source"] == "MISSING" and e["history"]["status"] in ("DATA_CHANGED", "DATA_UNAVAILABLE")
    assert "SELECTION_METADATA_MISSING" in e["notes"]
    if v["method"] == "LIGHTGBM":
        assert "features" not in e["lightgbm"]                                    # nothing invented
    e2 = client.get(f"/api/forecast-runs/{demo_run}/explain", params={k: v[k] for k in ("sku_id", "fc_id", "target_date")}).json()
    assert e2["selection"]["source"] == "STORED"                                  # stored metadata survives data changes


# ------------------------------------------------------------------ K4 intraday actual
def test_actual_today_rules(client, demo_run):
    run = client.get(f"/api/forecast-runs/{demo_run}").json()
    today = timeutil.today_vn()
    assert run["forecast_origin"] == str(today)                                   # demo data ends yesterday
    s = client.get(f"/api/forecast-runs/{demo_run}/summary?horizon=7").json()
    assert s["actual"]["status"] == "NO_DATA_TODAY" and s["actual"]["total"] is None
    assert all(r["actual_today"] is None for r in s["series"])                    # unknown, not 0
    now = datetime.now(VN_TZ).replace(hour=10, minute=5, second=0, microsecond=0)
    timeutil.set_now_override(lambda: now)
    assert client.post("/api/jobs/run", json={"job_type": "D0_SYNC"}).json()["status"] == "SUCCEEDED"
    with db.read() as c:
        snap = db.one(c, "SELECT * FROM d0_snapshots ORDER BY snapshot_at DESC LIMIT 1")
        vals = {(r["sku_id"], r["fc_id"]): r["cumulative_qty"] for r in db.rows(
            c, "SELECT * FROM d0_snapshot_values WHERE snapshot_id=?", (snap["id"],))}
        keys = [(r["sku_id"], r["fc_id"]) for r in db.rows(c, "SELECT DISTINCT sku_id, fc_id FROM forecast_values "
                                                               "WHERE run_id=?", (demo_run,))]
    s = client.get(f"/api/forecast-runs/{demo_run}/summary?horizon=7").json()
    a = s["actual"]
    assert a["status"] == "PARTIAL_DAY" and a["as_of"] == snap["snapshot_at"] and a["is_demo"] is True
    assert a["total"] == pytest.approx(sum(vals.get(k, 0.0) for k in keys))      # each series once
    assert [d["actual_today"] is not None for d in s["daily"]] == [d["target_date"] == str(today) for d in s["daily"]]
    one = keys[0]
    f = client.get(f"/api/forecast-runs/{demo_run}/summary?horizon=7&sku_id={one[0]}&fc_id={one[1]}").json()
    assert f["actual"]["total"] == pytest.approx(vals.get(one, 0.0))             # filter applies to actual too
    rows = client.get(f"/api/forecast-runs/{demo_run}/values?horizon=7&sku_id={one[0]}&fc_id={one[1]}").json()["rows"]
    for r in rows:
        assert (r["actual_today"] is not None) == (r["target_date"] == str(today))  # future days stay empty
    # 5 hours later without a new read: STALE, timestamp unchanged (never "now")
    timeutil.set_now_override(lambda: now + timedelta(hours=5))
    a2 = client.get(f"/api/forecast-runs/{demo_run}/summary?horizon=7").json()["actual"]
    assert a2["status"] == "STALE" and a2["as_of"] == snap["snapshot_at"]
    # just after VN midnight the snapshot belongs to yesterday: not used for the new day
    tomorrow_0030 = (now + timedelta(days=1)).replace(hour=0, minute=30)
    timeutil.set_now_override(lambda: tomorrow_0030)
    a3 = client.get(f"/api/forecast-runs/{demo_run}/summary?horizon=7").json()["actual"]
    assert a3["status"] == "NO_DATA_TODAY" and a3["date"] == str(tomorrow_0030.date())


def test_two_snapshots_same_day_are_never_added_together(client, demo_run):
    """Several D0 reads on the same VN day are CUMULATIVE: summary, values and Excel use the latest read only."""
    base = datetime.now(VN_TZ).replace(hour=10, minute=5, second=0, microsecond=0)
    snaps = []
    for hours in (0, 2):                                                          # 10:05 and 12:05 VN, same day
        timeutil.set_now_override(lambda h=hours: base + timedelta(hours=h))
        assert client.post("/api/jobs/run", json={"job_type": "D0_SYNC"}).json()["status"] == "SUCCEEDED"
    with db.read() as c:
        snaps = db.rows(c, "SELECT * FROM d0_snapshots WHERE order_date=? ORDER BY snapshot_at", (str(base.date()),))
        per = {s["id"]: {(r["sku_id"], r["fc_id"]): r["cumulative_qty"] for r in db.rows(
            c, "SELECT * FROM d0_snapshot_values WHERE snapshot_id=?", (s["id"],))} for s in snaps}
        keys = [(r["sku_id"], r["fc_id"]) for r in db.rows(c, "SELECT DISTINCT sku_id, fc_id FROM forecast_values "
                                                               "WHERE run_id=?", (demo_run,))]
    assert len(snaps) == 2 and snaps[0]["snapshot_at"] < snaps[1]["snapshot_at"]
    latest, first = per[snaps[1]["id"]], per[snaps[0]["id"]]
    want = sum(latest.get(k, 0.0) for k in keys)
    both = want + sum(first.get(k, 0.0) for k in keys)
    assert want != both                                                           # the test can tell them apart
    s = client.get(f"/api/forecast-runs/{demo_run}/summary?horizon=7&limit=5000").json()
    a = s["actual"]
    assert a["snapshot_id"] == snaps[1]["id"] and a["as_of"] == snaps[1]["snapshot_at"]
    assert a["total"] == pytest.approx(want)                                     # system total: latest read only
    assert sum(r["actual_today"] for r in s["series"]) == pytest.approx(want)    # table rows add up to the same total
    assert [d["actual_today"] for d in s["daily"] if d["actual_today"] is not None] == [pytest.approx(want)]
    rows = client.get(f"/api/forecast-runs/{demo_run}/values?horizon=7&limit=5000").json()["rows"]
    today = str(base.date())
    for r in rows:
        if r["target_date"] == today:
            assert r["actual_today"] == pytest.approx(latest.get((r["sku_id"], r["fc_id"]), 0.0))
        else:
            assert r["actual_today"] is None
    wb = _xlsx(client, demo_run, "vi")
    xs = [r[5] for r in wb.worksheets[1].iter_rows(min_row=2, values_only=True)]   # 1.2.4: +1, product name after SKU
    assert sum(x for x in xs if x is not None) == pytest.approx(want)            # Excel: same rule


def test_actual_not_applicable_for_manual_import_and_never_mixes_datasets(client, demo_run):
    from app.data import intraday
    a = intraday.actual_today("IMP-x", "MANUAL_IMPORT")
    assert a["status"] == "NOT_APPLICABLE" and intraday.value_for(a, "s", "f", a["date"]) is None
    now = datetime.now(VN_TZ).replace(hour=10, minute=5, second=0, microsecond=0)
    timeutil.set_now_override(lambda: now)
    client.post("/api/demo/generate", json={"days": 150, "n_skus": 8, "seed": 5})   # new DEMO dataset
    client.post("/api/jobs/run", json={"job_type": "D0_SYNC"})                      # snapshot of the NEW dataset
    a = client.get(f"/api/forecast-runs/{demo_run}/summary?horizon=7").json()["actual"]
    assert a["status"] == "NO_DATA_TODAY"                                           # old run's dataset has none


# ------------------------------------------------------------------ K5 Excel / i18n
def _xlsx(client, run_id, lang):
    r = client.get(f"/api/forecast-runs/{run_id}/export.xlsx?horizon=7&lang={lang}")
    assert r.status_code == 200
    return load_workbook(io.BytesIO(r.content))


def test_excel_follows_ui_language_and_keeps_numbers(client, demo_run):
    now = datetime.now(VN_TZ).replace(hour=10, minute=5, second=0, microsecond=0)
    timeutil.set_now_override(lambda: now)
    client.post("/api/jobs/run", json={"job_type": "D0_SYNC"})
    with db.read() as c:
        stored = {(r["sku_id"], r["fc_id"], r["target_date"]): r["yhat"] for r in db.rows(
            c, "SELECT * FROM forecast_values WHERE run_id=?", (demo_run,))}
    vi, en = _xlsx(client, demo_run, "vi"), _xlsx(client, demo_run, "en")
    assert vi.sheetnames == ["Thông tin", "Tổng 7 ngày", "Chi tiết theo ngày"]
    assert en.sheetnames == ["Info", "Totals 7d", "Daily"]
    hv = [c.value for c in vi["Chi tiết theo ngày"][1]]
    he = [c.value for c in en["Daily"][1]]
    # 1.2.4 (format 5): product name after the SKU; a DEMO run has none -> the explicit "no name" text
    # 1.2.9 (format 6): weekday name of the date after the date; the numeric 'Ngày thứ' (position in the period) is kept
    assert hv == ["SKU", "Tên sản phẩm", "FC/kho", "Ngày", "Thứ trong tuần", "Ngày thứ", "Số lượng dự báo", "Thực tế đến hiện tại", "Phương pháp", "Mã kỹ thuật phương pháp (không dịch)"]
    assert he == ["SKU", "Product name", "FC/warehouse", "Date", "Weekday", "Day #", "Forecast qty", "Actual so far", "Method", "Technical method code (not translated)"]
    today = str(timeutil.today_vn())
    for ws, lab in ((vi["Chi tiết theo ngày"], "Dự phòng cho chuỗi SKU–FC mới"), (en["Daily"], "Fallback for a new SKU–FC series")):
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        assert len(rows) == len(stored)
        assert ws.cell(row=2, column=4).number_format == "DD/MM/YYYY"                # both languages
        for sku, pname, fc, d, wday, hday, q, act, mlabel, mcode in rows:
            assert pname == ("Chưa có tên sản phẩm" if lab.startswith("Dự") else "No product name yet")
            assert isinstance(d, datetime)                                          # a real Excel date
            assert wday == ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"][d.weekday()] \
                if lab.startswith("Dự") else wday == d.strftime("%A")
            assert isinstance(hday, int) and hday >= 1
            d = d.date().isoformat()
            # 1.2.8: the exported forecast is the whole number shown on the page (round half up of the stored value)
            assert isinstance(q, int) and q == business_qty(stored[(sku, fc, d)])
            assert (act is not None) == (d == today)                               # actual only today
            if mcode == "FALLBACK_NEW_SERIES":
                assert mlabel == lab
            if mcode == "LIGHTGBM":
                assert mlabel == ("Mô hình học máy (LightGBM)" if lab.startswith("Dự") else "Machine-learning model (LightGBM)")
    info_vi = {r[0]: r[1] for r in vi["Thông tin"].iter_rows(min_row=2, values_only=True)}
    info_en = {r[0]: r[1] for r in en["Info"].iter_rows(min_row=2, values_only=True)}
    assert info_vi["Phiên bản định dạng file"] == "6" and info_en["Language"] == "English"
    run = client.get(f"/api/forecast-runs/{demo_run}").json()
    o = date_cls.fromisoformat(run["forecast_origin"])
    assert info_vi["Ngày bắt đầu"] == o.strftime("%d/%m/%Y") and info_en["Start date"] == o.strftime("%d/%m/%Y")
    vn = timeutil.parse_iso(run["created_at"]).astimezone(VN_TZ)
    assert info_vi["Thời điểm chạy (giờ Việt Nam)"] == vn.strftime("%d/%m/%Y %H:%M") + " (giờ Việt Nam, UTC+7)"
    assert info_en["Run time (Vietnam time)"] == vn.strftime("%d/%m/%Y %H:%M") + " (Vietnam time, UTC+7)"
    assert info_vi["Thực tế đọc lúc (giờ Việt Nam)"].startswith(now.strftime("%d/%m/%Y"))
    assert info_en["Actual is simulated DEMO data"] == "Yes" and info_vi["Trạng thái thực tế trong ngày"] == "Đang cập nhật trong ngày"
    tot = list(en["Totals 7d"].iter_rows(min_row=2, values_only=True))
    daily_sum = {}
    for sku, pn, fc, d, wday, hday, q, act, ml, mc in en["Daily"].iter_rows(min_row=2, values_only=True):  # noqa: B007
        daily_sum[(sku, fc)] = daily_sum.get((sku, fc), 0) + q
    for sku, pn, fc, ml, total, act, mc in tot:                                       # totals == sum of daily sheet
        assert total == pytest.approx(daily_sum[(sku, fc)])


def test_method_registry_covers_every_code_in_model():
    from app.ml import methods
    codes = {v for k, v in vars(model).items() if k.startswith(("METHOD_", "FB_")) and isinstance(v, str)}
    assert codes == set(methods.METHODS)
    assert {k for k, v in methods.METHODS.items() if v["scope"] == "production"} == {
        "LIGHTGBM", "FALLBACK_NEW_SERIES", "FALLBACK_INTERMITTENT", "FALLBACK_INACTIVE_ZERO",
        "BASELINE_MOVING_AVERAGE"}          # 1.2.2: the selected 28-day baseline can be published
    for v in methods.METHODS.values():
        for lang in ("vi", "en"):
            assert all(v[lang][k] for k in ("name", "short", "meaning", "when", "how", "limits"))


def test_documented_examples_are_correct():
    """Numbers used on the Algorithm page (frontend/src/algorithms.ts) are computed by the real code."""
    import pandas as pd
    from app.data import intraday
    from app.ml import features, metrics
    m = metrics.compute([100, 120, 80], [110, 100, 90])
    assert m["mae"] == pytest.approx(40 / 3) and m["wape"] == pytest.approx(40 / 300) and m["bias"] == pytest.approx(0)
    assert m["mape"] == pytest.approx((0.1 + 20 / 120 + 0.125) / 3)
    m2 = metrics.compute([10, 0, 5], [8, 2, 5])
    assert m2["mape_points"] == 2 and m2["mape_excluded_points"] == 1 and m2["wape"] == pytest.approx(4 / 15)

    cfg = ss.ModelSettings()
    # method selection example: 3 units on day indices 75, 90, 105 of a 120-day history (another series keeps
    # every calendar day "known")
    days = pd.date_range("2026-01-01", periods=120, freq="D")
    rows = [{"order_date": d, "sku_id": "B", "fc_id": "F", "qty": 1.0} for d in days]
    rows += [{"order_date": days[0], "sku_id": "A", "fc_id": "F", "qty": 0.0}]
    rows += [{"order_date": days[i], "sku_id": "A", "fc_id": "F", "qty": 3.0} for i in (75, 90, 105)]
    p = features.build_panel(pd.DataFrame(rows))
    d = model.classification_details(p, cfg)
    a = p.keys.index(("A", "F"))
    assert d["zero_days"][a] == 53 and d["zero_known_days"][a] == 56
    assert d["methods"][a] == model.FB_INTERMITTENT and d["rate"][a] == pytest.approx(3 / 28)
    assert round(3 / 28, 4) == 0.1071 and round(53 / 56 * 100, 1) == 94.6

    # rolling-feature example: last 7 days 4, 6, 0, 5, 3, 7, 3 -> roll_mean_7 = 4, lag_1 = 3
    seq = [1.0] * 30 + [4, 6, 0, 5, 3, 7, 3]
    dd = pd.date_range("2026-01-01", periods=len(seq), freq="D")
    p2 = features.build_panel(pd.DataFrame({"order_date": dd, "sku_id": "A", "fc_id": "F", "qty": seq}))
    sc, fcc = features.static_codes(p2)
    names = features.feature_names(cfg)
    X = features.features_at(p2, p2.Y, p2.price, p2.disc, p2.promo,
                             p2.dates.append(pd.DatetimeIndex([dd[-1] + pd.Timedelta(days=1)])), p2.T, cfg, sc, fcc)
    assert X[0, names.index("roll_mean_7")] == pytest.approx(4) and X[0, names.index("lag_1")] == 3

    # backtest cutoffs (1.1.7 defaults): T=150, H=30, F=12, step 30 -> only 60, 90, 120 have >= 56 days of history;
    # 01/01..15/10/2026 (T=288) -> 7 folds = 210 days
    T, H, F, step = 150, cfg.backtest_horizon_days, cfg.backtest_folds, cfg.backtest_step_days
    assert (H, F, step, cfg.min_total_history_days) == (30, 12, 30, 56)
    assert [o for o in (T - H - (F - 1 - k) * step for k in range(F)) if o >= cfg.min_total_history_days] == [60, 90, 120]
    valid288 = [o for o in (288 - H - (F - 1 - k) * step for k in range(F)) if o >= cfg.min_total_history_days]
    assert len(valid288) == 7 and 288 - valid288[0] == 210
    # link function illustration and default stale threshold
    assert round(math.exp(1.45), 3) == 4.263
    assert intraday.stale_after_minutes(ss.ScheduleSettings()) == 140
    # Tweedie example (variance power fixed in lgb_params) and retry back-off example
    assert model.lgb_params(cfg)["tweedie_variance_power"] == 1.2 and round(4 ** 1.2, 3) == 5.278
    sched = ss.ScheduleSettings()
    assert [min(sched.retry_base_seconds * 2 ** (a - 1), sched.retry_max_seconds) for a in (1, 2, 3)] == [60, 120, 240]
    assert sched.max_attempts == 4 and sched.train_time == "07:00" and sched.d1_fallback_time == "06:00"


def test_method_registry_examples_are_computed_by_the_code():
    """Worked examples in ml/methods.py (shown in tooltips and on the Algorithm page) come out of the real code."""
    import pandas as pd
    from app.ml import features, methods
    cfg = ss.ModelSettings()
    for v in methods.METHODS.values():
        for lang in ("vi", "en"):
            assert v[lang]["example"] and v[lang]["read"]

    def panel(series: dict[str, list[float]]):
        n = max(len(q) for q in series.values())
        days = pd.date_range("2026-01-01", periods=n, freq="D")
        rows = [{"order_date": days[i], "sku_id": k, "fc_id": "F", "qty": float(q)}
                for k, qs in series.items() for i, q in enumerate(qs, start=n - len(qs))]
        rows += [{"order_date": d, "sku_id": "ZZ", "fc_id": "F", "qty": 1.0} for d in days]   # every day "known"
        return features.build_panel(pd.DataFrame(rows))

    # new series: first order 10 days before the origin, 10 known days totalling 56
    p = panel({"NEW": [5, 6, 4, 7, 5, 6, 5, 6, 5, 7], "OLD": [1.0] * 120})
    d = model.classification_details(p, cfg)
    s = p.keys.index(("NEW", "F"))
    assert d["methods"][s] == model.FB_NEW and d["hist_count"][s] == 10 and d["rate"][s] == pytest.approx(5.6)
    assert round(7 * 5.6, 1) == 39.2
    # inactive: 120 days old, last sale 75 days before the origin
    q = [0.0] * 120
    q[0] = 2.0
    q[120 - 75] = 4.0
    p = panel({"INA": q})
    d = model.classification_details(p, cfg)
    assert d["methods"][p.keys.index(("INA", "F"))] == model.FB_INACTIVE
    # intermittent: 7 days ~ 0.75
    assert round(7 * 3 / 28, 2) == 0.75
    # model unavailable (backtest only): no booster, last 28 days total 42 over 28 known days
    p = panel({"REG": [1.0, 2.0] * 60})
    fc = model.forecast(p, None, cfg, 3)
    s = p.keys.index(("REG", "F"))
    assert fc["methods"][s] == model.FB_MODEL_UNAVAILABLE and fc["yhat"][s, 0] == pytest.approx(1.5)
