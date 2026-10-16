import numpy as np
import pandas as pd
import pytest

from app import db
from app import settings_service as ss
from app.ml import metrics, model
from app.ml.features import build_panel, features_at, static_codes
from app.ml.pipeline import quality_gate, train_and_publish


def _demand(series: dict[tuple[str, str], list[float]], start="2025-01-01"):
    rows = []
    for (sku, fc), vals in series.items():
        for i, v in enumerate(vals):
            if v is None:
                continue
            rows.append({"order_date": str((pd.Timestamp(start) + pd.Timedelta(days=i)).date()), "sku_id": sku,
                         "fc_id": fc, "qty": float(v), "avg_unit_price": 10.0, "avg_discount_rate": 0.0,
                         "promo_share": 0.0})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ metrics
def test_metrics_definitions():
    m = metrics.compute([10, 0, 5], [8, 2, 5])
    assert m["mae"] == pytest.approx(4 / 3)
    assert m["wape"] == pytest.approx(4 / 15)
    assert m["bias"] == pytest.approx((15 - 15) / 15)
    assert m["mape_points"] == 2 and m["mape_excluded_points"] == 1    # actual 0 excluded from MAPE
    assert m["mape"] == pytest.approx((0.2 + 0) / 2)


def test_metrics_all_zero_actuals_are_not_hidden():
    m = metrics.compute([0, 0], [1, 0])
    assert m["wape"] is None and m["bias"] is None and m["mape"] is None
    assert "SUM_ACTUAL_ZERO" in m["notes"] and "MAPE_UNDEFINED" in m["notes"]
    assert metrics.compute([], [])["notes"] == ["NO_POINTS"]


# ------------------------------------------------------------------ features / leakage
def test_features_never_use_data_at_or_after_t():
    rng = np.random.default_rng(1)
    d = _demand({("A", "F"): list(rng.poisson(5, 120)), ("B", "F"): list(rng.poisson(2, 120))})
    p = build_panel(d)
    cfg = ss.get("model")
    sc, fc = static_codes(p)
    t = 100
    X1 = features_at(p, p.Y, p.price, p.disc, p.promo, p.dates, t, cfg, sc, fc)
    Y2 = p.Y.copy()
    Y2[:, t:] = 999.0                           # tamper with "future" data
    P2 = p.price.copy()
    P2[:, t:] = 1e6
    X2 = features_at(p, Y2, P2, p.disc, p.promo, p.dates, t, cfg, sc, fc)
    np.testing.assert_array_equal(np.nan_to_num(X1, nan=-1), np.nan_to_num(X2, nan=-1))


def test_backtest_forecast_unchanged_when_future_changes(fast_model):
    rng = np.random.default_rng(2)
    base = {("A", "F"): list(rng.poisson(6, 140)), ("B", "F"): list(rng.poisson(3, 140))}
    p = build_panel(_demand(base))
    cfg = ss.get("model")
    origin = 120
    tr = p.truncate(origin)
    b, _ = model.train(tr, cfg)
    f1 = model.forecast(tr, b, cfg, 7)["yhat"]
    p2 = build_panel(_demand(base))
    p2.Y[:, origin:] = 500.0                     # future data differs
    tr2 = p2.truncate(origin)
    b2, _ = model.train(tr2, cfg)
    f2 = model.forecast(tr2, b2, cfg, 7)["yhat"]
    np.testing.assert_allclose(f1, f2)


def test_calendar_gap_is_unknown_not_zero():
    d = _demand({("A", "F"): [3] * 10})
    d = d[d["order_date"] != "2025-01-05"]
    p = build_panel(d)
    assert p.missing_days.sum() == 1 and np.isnan(p.Y[0, 4])


# ------------------------------------------------------------------ fallbacks
def test_fallback_classification(fast_model):
    n = 120
    series = {
        ("STABLE", "F"): [5] * n,
        ("NEW", "F"): [None] * (n - 10) + [4] * 10,
        ("INTER", "F"): [3 if i % 15 == 0 else 0 for i in range(n)],
        ("DEAD", "F"): [5] * 40 + [0] * (n - 40),
    }
    p = build_panel(_demand(series))
    cfg = ss.get("model")
    methods, rate = model.classify_series(p, cfg)
    m = dict(zip([k[0] for k in p.keys], methods))
    assert m["STABLE"] == model.METHOD_LGBM
    assert m["NEW"] == model.FB_NEW
    assert m["INTER"] == model.FB_INTERMITTENT
    assert m["DEAD"] == model.FB_INACTIVE
    fc = model.forecast(p, None, cfg, 5)          # no model -> every LightGBM series falls back explicitly
    mm = dict(zip([k[0] for k in p.keys], fc["methods"]))
    assert mm["STABLE"] == model.FB_MODEL_UNAVAILABLE
    assert np.all(fc["yhat"] >= 0)
    assert fc["yhat"][[k[0] for k in p.keys].index("DEAD")].sum() == 0


def test_quality_gate_logic():
    q = ss.QualitySettings(wape_max=0.5, abs_bias_max=0.1, min_backtest_points=10)
    bt = {"reliable": True, "folds": [1, 2], "metrics": {"n_points": 50, "wape": 0.4, "bias": 0.05},
          "baseline_metrics": {"wape": 0.6}}
    assert quality_gate(bt, q)["passed"]
    bt["metrics"]["bias"] = -0.2
    g = quality_gate(bt, q)
    assert not g["passed"] and [c for c in g["checks"] if not c["passed"]][0]["check"] == "ABS_BIAS_MAX"
    bt["metrics"]["bias"] = 0.0
    bt["reliable"] = False
    assert not quality_gate(bt, q)["passed"]
    assert quality_gate(bt, q)["thresholds_approved_by_business"] is False


# ------------------------------------------------------------------ pipeline
def test_train_and_publish_end_to_end(small_demo):
    res = train_and_publish()
    assert res["status"] == "PUBLISHED", res
    with db.read() as c:
        run = db.one(c, "SELECT * FROM forecast_runs WHERE id=?", (res["forecast_run_id"],))
        tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (res["training_run_id"],))
        n = c.execute("SELECT COUNT(*) FROM forecast_values WHERE run_id=?", (run["id"],)).fetchone()[0]
        methods = {r[0] for r in c.execute("SELECT DISTINCT method FROM forecast_values WHERE run_id=?", (run["id"],))}
        bt = db.one(c, "SELECT * FROM backtest_runs WHERE training_run_id=?", (tr["id"],))
    assert tr["status"] == "ACCEPTED" and tr["model_version"] == run["model_version"]
    assert run["data_source"] == "DEMO" and run["max_horizon"] == 30
    assert n == run["n_series"] * 30
    assert "LIGHTGBM" in methods
    assert bt is not None
    # forecast origin = the day after the last data day
    assert pd.Timestamp(run["forecast_origin"]) == pd.Timestamp(run["data_as_of"]) + pd.Timedelta(days=1)
    # unchanged data -> no pointless retraining
    again = train_and_publish()
    assert again["status"] == "SKIPPED" and again["reason_code"] == "NO_NEW_DATA"


def test_quality_gate_failure_keeps_previous_forecast(small_demo):
    first = train_and_publish()
    assert first["status"] == "PUBLISHED"
    ss.update("quality", {"wape_max": 0.0001})
    second = train_and_publish(force=True)
    assert second["status"] == "REJECTED" and second["reason_code"] == "QUALITY_GATE_FAILED"
    with db.read() as c:
        runs = db.rows(c, "SELECT id FROM forecast_runs")
        tr = db.one(c, "SELECT status, reject_reason FROM training_runs WHERE id=?", (second["training_run_id"],))
        alerts = db.rows(c, "SELECT code FROM alerts WHERE code='QUALITY_GATE_FAILED'")
    assert [r["id"] for r in runs] == [first["forecast_run_id"]]
    assert tr["status"] == "REJECTED" and alerts


def test_training_crash_keeps_previous_forecast(small_demo, monkeypatch):
    first = train_and_publish()
    def boom(*a, **k):
        raise RuntimeError("simulated LightGBM failure")
    monkeypatch.setattr(model, "train", boom)
    res = train_and_publish(force=True)
    assert res["status"] == "FAILED"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM forecast_runs").fetchone()[0] == 1
        assert db.one(c, "SELECT status FROM training_runs WHERE id=?", (res["training_run_id"],))["status"] == "FAILED"
    assert first["status"] == "PUBLISHED"


def test_insufficient_history_is_rejected_not_forced(fast_model, client):
    import io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["created_at", "sku_id", "fc_id", "order_qty"])
    for i in range(20):
        ws.append([f"2026-09-{(i % 28) + 1:02d} 10:00", "S", "F", 2])
    buf = io.BytesIO()
    wb.save(buf)
    u = client.post("/api/imports/upload", files={"file": ("x.xlsx", buf.getvalue(), "application/octet-stream")}).json()
    b = client.post(f"/api/imports/uploads/{u['upload_id']}/validate",
                    json={"sheet": "Data", "mapping": u["suggested_mapping"]}).json()
    client.post(f"/api/imports/{b['id']}/confirm", json={"accept_row_errors": True})
    client.put("/api/active-source", json={"source": "MANUAL_IMPORT"})
    res = train_and_publish()
    assert res["status"] == "REJECTED" and res["reason_code"] == "DATA_NOT_TRAINABLE"


def test_stale_data_blocks_publish_when_enforced(small_demo):
    from app import timeutil
    from datetime import datetime, timedelta, timezone
    ss.update("data_policy", {"stale_check_sources": ["DEMO"], "max_data_lag_days": 2})
    timeutil.set_now_override(lambda: datetime.now(timezone.utc) + timedelta(days=10))
    res = train_and_publish()
    assert res["status"] == "REJECTED" and res["reason_code"] == "STALE_DATA_BLOCKED"


def test_sources_are_isolated(small_demo, client):
    """A model trained on DEMO uses DEMO rows only, even when import batches exist."""
    import io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["created_at", "sku_id", "fc_id", "order_qty"])
    ws.append(["2026-01-01 10:00", "IMPORTED-SKU", "F", 1000])
    buf = io.BytesIO()
    wb.save(buf)
    u = client.post("/api/imports/upload", files={"file": ("x.xlsx", buf.getvalue(), "application/octet-stream")}).json()
    b = client.post(f"/api/imports/uploads/{u['upload_id']}/validate",
                    json={"sheet": "Data", "mapping": u["suggested_mapping"]}).json()
    client.post(f"/api/imports/{b['id']}/confirm", json={"accept_row_errors": True})
    client.put("/api/active-source", json={"source": "DEMO"})
    res = train_and_publish()
    with db.read() as c:
        skus = {r[0] for r in c.execute("SELECT DISTINCT sku_id FROM forecast_values WHERE run_id=?",
                                        (res["forecast_run_id"],))}
    assert "IMPORTED-SKU" not in skus and all(s.startswith("DEMO-") for s in skus)
