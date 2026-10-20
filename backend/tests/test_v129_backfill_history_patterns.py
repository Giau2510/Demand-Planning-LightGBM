"""1.2.9 (second batch): controlled backfill (mandatory read-only preview, preview id, online backup before the write),
whole-number forecasts on the Forecast & actual history page, demand-pattern groups / spike flags and the backtest
accuracy per group. All on temporary data (conftest); BigQuery is the FakeBQ client."""
from __future__ import annotations

import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

import numpy as np
import pytest
from openpyxl import load_workbook

from app import db, paths, qty, timeutil
from app import settings_service as ss
from app.bq import connector
from app.messages import AppError
from app.ml import demand_patterns as dp
from fake_bq import FakeBQ


# ================================================================== demand-pattern groups and spike flags
def _series(*rows, T=91):
    Y = np.zeros((len(rows), T))
    for i, r in enumerate(rows):
        Y[i] = r(np.arange(T))
    return Y


def test_groups_follow_the_syntetos_boylan_rules_on_the_history_before_the_cutoff():
    Y = _series(lambda t: np.full(t.shape, 10.0),                         # every day the same
                lambda t: np.where(t % 2 == 0, 1.0, 20.0),                 # every day, very different sizes
                lambda t: np.where(t % 3 == 0, 5.0, 0.0),                  # every 3rd day, same size
                lambda t: np.where(t % 3 == 0, np.where(t % 2 == 0, 1.0, 30.0), 0.0),
                lambda t: np.zeros(t.shape),                               # nothing sold
                lambda t: np.where(t < 81, np.nan, 3.0))                   # only 10 known days
    g = dp.classify(Y, 91)
    assert list(g["group"]) == ["SMOOTH", "ERRATIC", "INTERMITTENT", "LUMPY", "INACTIVE", "SHORT_HISTORY"]
    assert g["adi"][2] == pytest.approx(91 / 31) and g["cv2"][0] == 0         # 31 demand days out of 91
    # the group at a cutoff never looks at a later day
    Y2 = np.concatenate([Y, np.full((6, 30), 999.0)], axis=1)
    assert list(dp.classify(Y2, 91)["group"]) == list(g["group"])


def test_spike_flags_compare_a_day_with_its_own_series_and_change_nothing():
    T = 91
    Y = np.vstack([np.where(np.arange(T) % 2 == 0, 20.0, 50.0),           # usual 20-50 a day
                   np.zeros(T)])                                          # never sold: no reference
    before = Y.copy()
    thr = dp.spike_thresholds(Y, T)
    assert 50 < thr[0] < 300 and np.isinf(thr[1])
    actual = np.array([[35.0, 300.0, 400.0, np.nan], [500.0, 0.0, 1.0, 2.0]])
    flags = dp.spike_flags(actual, thr)
    assert flags.tolist() == [[False, True, True, False], [False, False, False, False]]
    assert np.array_equal(Y, before)                                      # flags never modify the data


def test_volume_tier_marks_the_series_that_make_most_of_the_demand():
    Y = np.vstack([np.full(91, 100.0), np.full(91, 10.0), np.full(91, 1.0), np.zeros(91)])
    assert list(dp.volume_tier(Y, 91)) == ["HIGH_VOLUME", "LOW_VOLUME", "LOW_VOLUME", "NO_VOLUME"]


def test_backtest_reports_the_same_points_per_group_horizon_and_period_total(small_demo):
    from app.data.demand import load_demand
    from app.ml import model
    from app.ml.features import build_panel
    cfg = ss.get("model")
    p = build_panel(load_demand(small_demo["batch_id"]), max_days=cfg.max_train_days)
    Y0 = p.Y.copy()
    bt = model.backtest(p, cfg, collect=True)
    seg = bt["segments"]
    n = bt["metrics"]["n_points"]
    assert np.array_equal(p.Y, Y0, equal_nan=True)                       # evaluation only: data unchanged
    for key in ("by_pattern", "by_volume", "by_spike_day", "by_horizon_days"):
        assert sum(v["model"]["n_points"] for v in seg[key].values()) == n, key
        assert sum(v["model"]["sum_actual"] for v in seg[key].values()) == pytest.approx(bt["metrics"]["sum_actual"])
    assert set(seg["by_pattern"]) <= set(dp.GROUPS) and set(seg["by_horizon_days"]) == {"1-7"}
    # period total of the first 7 days = per (fold, series) sums of the very points the pooled metric uses
    tot: dict = {}
    for pt in bt["points"]:
        k = (pt["fold"], pt["sku_id"], pt["fc_id"])
        a, f = tot.get(k, (0.0, 0.0))
        tot[k] = (a + pt["actual"], f + pt["forecast"])
    A = np.array([v[0] for v in tot.values()])
    F = np.array([v[1] for v in tot.values()])
    assert seg["period_totals"]["7"]["model"]["wape"] == pytest.approx(np.abs(A - F).sum() / A.sum())
    assert seg["period_totals"]["7"]["model"]["wape"] <= bt["metrics"]["wape"] + 1e-9    # daily errors can cancel out


def test_training_stores_the_segments_and_the_training_page_shows_them(client, small_demo):
    from app.ml import pipeline, training_explain
    run_id = pipeline.train_and_publish(force=True)["training_run_id"]
    with db.read() as c:
        m = json.loads(c.execute("SELECT metrics_json FROM backtest_runs WHERE training_run_id=?", (run_id,)).fetchone()[0])
    assert m["segments"]["by_pattern"] and m["segments"]["rules"]["adi_cut"] == dp.ADI_CUT
    assert m["segments"]["by_horizon_days"]["1-7"]["model"]["n_points"] == m["pooled"]["n_points"]
    assert training_explain.overview(run_id)["backtest"]["segments"] == m["segments"]


# ================================================================== whole-number forecasts on the history page
def test_history_shows_sums_compares_and_exports_the_whole_number_forecast(client):
    import test_v125_forecast_history as h
    from app import forecast_history as fh
    from app.ml import metrics as mt
    timeutil.set_now_override(lambda: h.NOW)
    a = h._run("2026-10-17 09:00", origin="2026-10-17")                 # D+1 values 10.5 / 11.5 / 12.5
    b = h._run("2026-10-18 09:00", origin="2026-10-18", base=0.2)        # 0.7 / 1.7 / 2.7 -> 1 / 2 / 3
    zero = h._run("2026-10-19 09:00", origin="2026-10-19", base=-0.3)    # 0.2 / 1.2 / 2.2 -> 0 (never forced to 1)
    for r in (a, b, zero):
        fh.capture(r)
    h._demand("2026-10-18", {("S1", "HN"): 5, ("S2", "HN"): 30, ("S1", "BD"): 2})
    h._demand("2026-10-19", {("S1", "HN"): 1, ("S2", "HN"): 2, ("S1", "BD"): 4})
    h._d1_audit("2026-10-19", "FALLBACK_TIME_VERIFIED")
    k, daily, rows, n = h._q(run_from="2026-10-17", run_to="2026-10-19")
    for r in rows:
        assert r["forecast_qty"] == qty.business_qty(r["yhat"]) and isinstance(r["forecast_qty"], int)
        if r["actual"] is not None:
            assert r["deviation"] == r["forecast_qty"] - r["actual"]
            if r["actual"] > 0:
                assert r["row_wape"] == pytest.approx(abs(r["forecast_qty"] - r["actual"]) / r["actual"])
    assert sorted(r["forecast_qty"] for r in rows if r["run_date"] == "2026-10-19") == [0, 1, 2]
    assert sorted(r["forecast_qty"] for r in rows if r["run_date"] == "2026-10-17") == [11, 12, 13]   # half up
    comp = [r for r in rows if r["actual"] is not None]
    ref = mt.compute([r["actual"] for r in comp], [r["forecast_qty"] for r in comp])
    kp = k["provisional"]           # 1.2.9 (seventh batch): days not finalized -> the provisional group of the KPI
    assert kp["wape"] == pytest.approx(ref["wape"]) and kp["bias"] == pytest.approx(ref["bias"])
    assert k["forecast_total"] == sum(r["forecast_qty"] for r in rows)
    assert kp["deviation"] == sum(r["forecast_qty"] for r in comp) - sum(r["actual"] for r in comp)
    for d in daily:
        if d["has_history"]:
            assert d["forecast"] == sum(r["forecast_qty"] for r in rows if r["run_date"] == d["run_date"])
    with db.read() as c:                                                 # the stored model values are not changed
        assert {r[0] for r in c.execute("SELECT yhat FROM forecast_history_values")} >= {10.5, 0.7, 0.2}
    # API rows carry both, the Excel holds the whole numbers (format H3)
    api = client.get("/api/history/rows", params={"scope_key": h.SCOPE, "run_from": "2026-10-17", "run_to": "2026-10-19",
                                                  "limit": 50})
    got = api.json()["rows"]
    assert len(got) == n and all(isinstance(x["forecast_qty"], int) and "yhat" in x for x in got)
    with db.read() as c:
        qy = fh.Query(c, h.SCOPE, run_from="2026-10-17", run_to="2026-10-19")
        from app.export_i18n import history_labels
        wb = load_workbook(BytesIO(fh.export_xlsx(qy, history_labels("vi")[1])))
    info = {r[0]: r[1] for r in wb[wb.sheetnames[0]].iter_rows(min_row=2, values_only=True)}
    assert info["Phiên bản định dạng file"] == "H4" and "số nguyên" in info["Cách tính"]       # H4: seventh batch
    det = list(wb[wb.sheetnames[-1]].iter_rows(values_only=True))
    col = det[0].index("Forecast")
    assert sorted(r[col] for r in det[1:]) == sorted(r["forecast_qty"] for r in rows)
    assert all(isinstance(r[col], int) for r in det[1:])
    timeutil.set_now_override(None)


# ================================================================== controlled backfill
SCHEMA = [("so_code", "STRING"), ("created_date", "DATE"), ("sku_code", "STRING"), ("fc_code", "STRING"),
          ("demand_quantity", "INT64"), ("sales_price", "FLOAT64"), ("total_open_hours", "FLOAT64")]
FM = {"order_id": {"column": "so_code", "usage": "OPTIONAL"}, "order_date": {"column": "created_date", "usage": "REQUIRED"},
      "created_at": {"column": None, "usage": "UNUSED"},
      "sku_id": {"column": "sku_code", "usage": "REQUIRED"}, "fc_id": {"column": "fc_code", "usage": "REQUIRED"},
      "order_qty": {"column": "demand_quantity", "usage": "REQUIRED"},
      "unit_price": {"column": "sales_price", "usage": "OPTIONAL"}}
REF = {"open_hours": {"column": "total_open_hours", "usage": "OPTIONAL"}}
SCOPE = "BIGQUERY:lakehouse-prod-394907.sales.orders"


def _row(day, sku, q, lo=24.0, hi=24.0, nulls=0):
    return {"order_date": day, "sku_id": sku, "fc_id": "F1", "qty": q, "n_rows": 1, "n_orders": 1, "avg_unit_price": 10.0,
            "avg_discount_rate": None, "promo_share": None, "voucher_share": None, "max_source_updated_at": None,
            "max_batch_id": None, "open_hours_null_rows": nulls, "open_hours_min": lo, "open_hours_max": hi}


def _production(rows):
    from test_bigquery import PASSING_VALIDATION
    y = timeutil.today_vn() - timedelta(days=1)
    fake = FakeBQ(schema=SCHEMA, responses={"daily": rows, "completion": [{"n": 1}],
                                            "profile": [{"n_rows": 100, "min_date": date(2026, 1, 1), "max_date": y}],
                                            **PASSING_VALIDATION})
    connector.set_client_factory(fake)
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders", "location": "asia-southeast1",
                           "partition_column": "", "field_mapping": FM, "reference_mapping": REF,
                           "completion_table": "done", "completion_date_column": "d"})
    connector.test_connection()
    ss.update("bigquery", {"schema_snapshot": connector.read_schema()["columns"]})
    connector.profile(7)
    assert connector.validate_source()["passed"]
    ss.update("bigquery", {"production_enabled": True})
    ss.update("general", {"active_source": "BIGQUERY"})
    return fake


def _demand_rows():
    with db.read() as c:
        return sorted(tuple(r) for r in c.execute(
            "SELECT order_date, sku_id, fc_id, qty, open_hours, open_hours_status FROM demand_daily WHERE scope_key=?",
            (SCOPE,)))


def _counts():
    with db.read() as c:
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in (
            "d0_snapshots", "forecast_runs", "forecast_values", "training_runs", "forecast_history_values",
            "forecast_eod_snapshots", "actual_closes")}


def test_backfill_needs_a_matching_preview_backs_up_first_and_replaces_only_its_window(client):
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    old = y - timedelta(days=5)
    fake = _production([_row(y, "A", 5), _row(y, "B", 1), _row(y, "GONE", 4), _row(y, "MISS", 2, None, None, 1)])
    sync.run_d1_sync("J1")                                               # regular load: the baseline
    with db.tx() as c:                                                   # a stored day outside the backfill window
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at, "
                  "open_hours, open_hours_status) VALUES (?, 'BIGQUERY', ?, 'A', 'F1', 7, 1, 'x', NULL, NULL)", (SCOPE, str(old)))
    with db.read() as c:
        watermark = json.loads(c.execute("SELECT value_json FROM sync_state WHERE name=?",
                                         (f"last_d1_sync:{SCOPE}",)).fetchone()[0])["watermark"]
    before, counts = _demand_rows(), _counts()

    # no preview -> refused by the API and by the job itself; nothing written
    r = client.post("/api/sync/backfill", json={"start": str(y), "end": str(y)})
    assert r.status_code == 409 and r.json()["code"] == "BACKFILL_PREVIEW_REQUIRED"
    with pytest.raises(AppError) as e:
        sync.run_d1_sync("J2", backfill_start=str(y), backfill_end=str(y))
    assert e.value.code == "BACKFILL_PREVIEW_REQUIRED"

    # the source changed: A 5 -> 6, GONE removed, NEW added, B's lines now disagree on the open hours
    fake.responses["daily"] = [_row(y, "A", 6), _row(y, "B", 1, 20.0, 24.0), _row(y, "MISS", 2, None, None, 1),
                               _row(y, "NEW", 3, 12.5, 12.5)]
    pv = client.post("/api/sync/backfill/preview", json={"start": str(y), "end": str(y)}).json()
    assert pv["status"] == "READY" and pv["written"] is False and pv["window"] == {"start": str(y), "end": str(y), "days": 1}
    assert pv["compare"] | {} == {**pv["compare"], "series_days_new": 1, "series_days_updated": 1, "series_days_unchanged": 2,
                                  "series_days_removed": 1, "rows_stored_in_window": 4, "days_with_changes": 1}
    assert pv["open_hours"]["would_write"] == {"OK": 2, "MISSING": 1, "OUT_OF_RANGE": 0, "CONFLICT": 1, "MULTI_ITEM": 0,
                                               "NOT_READ": 0}
    assert pv["open_hours"]["stored_now"] == {"OK": 3, "MISSING": 1}
    # 1.2.9b: B (stored OK, now CONFLICT) and GONE (stored OK, removed) would lose their stored open hours
    assert pv["open_hours"]["stored_ok_not_kept"] == {"rows": 2, "first_day": str(y), "last_day": str(y), "now_missing": 0,
                                                      "removed": 1}
    assert any(w["code"] == "OPEN_HOURS_WOULD_BE_LOST" and w["rows"] == 2 for w in pv["warnings"])
    assert "d0_snapshots" in pv["effects"]["not_written"]
    assert _demand_rows() == before and _counts() == counts               # a preview writes no demand
    assert client.get("/api/sync/backfill/preview").json()["preview_id"] == pv["preview_id"]

    # a preview of another window does not allow this one
    other = sync.backfill_preview(str(y - timedelta(days=1)), str(y))
    r = client.post("/api/sync/backfill", json={"start": str(y), "end": str(y), "preview_id": other["preview_id"]})
    assert r.status_code == 409 and "window" in r.json()["detail"]
    pv = sync.backfill_preview(str(y), str(y))

    # the backup failing stops the backfill before anything is written; the preview stays usable
    import app.backup as backup_mod
    real = backup_mod.backup_database
    backup_mod.backup_database = lambda reason="manual", dest_dir=None: (_ for _ in ()).throw(OSError("disk full"))
    try:
        with pytest.raises(AppError) as e:
            sync.run_d1_sync("J3", backfill_start=str(y), backfill_end=str(y), backfill_preview_id=pv["preview_id"])
        assert e.value.code == "BACKFILL_BACKUP_FAILED"
    finally:
        backup_mod.backup_database = real
    assert _demand_rows() == before

    # with the preview: backup first, then exactly the window is replaced
    assert client.post("/api/sync/backfill", json={"start": str(y), "end": str(y), "preview_id": pv["preview_id"]}).status_code == 200
    with db.read() as c:
        job = db.one(c, "SELECT status, result_json FROM job_runs WHERE job_type='D1_SYNC' ORDER BY created_at DESC, rowid DESC LIMIT 1")
    out = json.loads(job["result_json"])["result"]
    assert job["status"] == "SUCCEEDED" and out["backfill"] and out["preview_id"] == pv["preview_id"]
    assert (out["series_days_new"], out["series_days_updated"], out["series_days_removed"]) == (1, 1, 1)
    bk = paths.backups_dir() / out["pre_backfill_backup"]["file"]
    assert bk.exists() and "pre-backfill" in bk.name
    with zipfile.ZipFile(bk) as z:                                      # the backup holds the data BEFORE the write
        z.extract("db/app.db", bk.parent / "x")
    import sqlite3
    kept = sqlite3.connect(bk.parent / "x" / "db" / "app.db")
    assert kept.execute("SELECT qty FROM demand_daily WHERE scope_key=? AND sku_id='A' AND order_date=?",
                        (SCOPE, str(y))).fetchone()[0] == 5
    kept.close()
    after = {(r[1]): r for r in _demand_rows() if r[0] == str(y)}
    assert after["A"][3] == 6 and "GONE" not in after and after["NEW"][4:] == (12.5, "OK")
    assert after["B"][4:] == (None, "CONFLICT") and after["MISS"][4:] == (None, "MISSING")
    assert [r for r in _demand_rows() if r[0] == str(old)] == [r for r in before if r[0] == str(old)]   # outside: kept
    assert _counts() == counts                                            # D-0, forecasts, models, history untouched
    with db.read() as c:
        st = json.loads(c.execute("SELECT value_json FROM sync_state WHERE name=?", (f"last_d1_sync:{SCOPE}",)).fetchone()[0])
        used = json.loads(c.execute("SELECT value_json FROM sync_state WHERE name=?", (sync.BACKFILL_PREVIEW_STATE,)).fetchone()[0])
    assert st["watermark"] == watermark and not st["backfill"]           # the regular D-1 state is not moved
    assert used["status"] == "USED" and used["used_by_job"]

    # a preview is used once
    r = client.post("/api/sync/backfill", json={"start": str(y), "end": str(y), "preview_id": pv["preview_id"]})
    assert r.status_code == 409 and r.json()["code"] == "BACKFILL_PREVIEW_REQUIRED"


def test_an_old_preview_does_not_allow_a_backfill(client):
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    _production([_row(y, "A", 5)])
    sync.run_d1_sync("J1")
    pv = sync.backfill_preview(str(y), str(y))
    later = datetime.now(timezone.utc) + timedelta(hours=sync.BACKFILL_PREVIEW_MAX_AGE_HOURS, minutes=5)
    timeutil.set_now_override(lambda: later)
    try:
        with pytest.raises(AppError) as e:
            sync.check_backfill_preview(pv["preview_id"], date.fromisoformat(pv["window"]["start"]),
                                        date.fromisoformat(pv["window"]["end"]), pv["mapping_hash"],
                                        {"mode": pv["sql"]["mode"], "version_id": pv["sql"]["version_id"],
                                         "sha256": pv["sql"]["sha256"]})
        assert e.value.code == "BACKFILL_PREVIEW_REQUIRED" and "old" in e.value.detail
    finally:
        timeutil.set_now_override(None)


def test_a_preview_with_duplicate_source_rows_is_blocked_and_never_writes(client):
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    fake = _production([_row(y, "A", 5)])
    sync.run_d1_sync("J1")
    before = _demand_rows()
    fake.responses["daily"] = [_row(y, "A", 5), _row(y, "A", 6)]          # two output rows for one key
    pv = sync.backfill_preview(str(y), str(y))
    assert pv["status"] == "FAILED" and pv["error"]["code"] == "BQ_AGGREGATE_INVALID"
    assert _demand_rows() == before
    with pytest.raises(AppError) as e:
        sync.run_d1_sync("J2", backfill_start=str(y), backfill_end=str(y), backfill_preview_id=pv["preview_id"])
    assert e.value.code == "BACKFILL_PREVIEW_REQUIRED"


# ================================================================== weekday switch vs a trained model
def test_switching_the_weekday_off_after_training_never_changes_how_that_model_is_used(client, fast_model):
    """The switch only affects the NEXT training: an existing model keeps its own feature list and dow encoding for its
    explanation (and any extension), whatever the current setting says."""
    from app import weekday as wd
    assert client.post("/api/demo/generate", json={"days": 150, "n_skus": 8, "seed": 3}).status_code == 200
    assert client.post("/api/training/run", json={}).json()["status"] == "SUCCEEDED"
    run = client.get("/api/system/status").json()["latest_forecast_run"]
    r = client.put("/api/settings/model", json={**client.get("/api/settings").json()["model"], "feature_weekday": False})
    assert r.status_code == 200 and r.json()["feature_weekday"] is False
    x = next(v for v in client.get(f"/api/forecast-runs/{run['id']}/values?limit=5000").json()["rows"] if v["method"] == "LIGHTGBM")
    ex = client.get(f"/api/forecast-runs/{run['id']}/explain",
                    params={"sku_id": x["sku_id"], "fc_id": x["fc_id"], "target_date": x["target_date"]}).json()
    assert ex["reproduction"]["status"] == "OK" and ex["lightgbm"]["matches_published"]
    feats = {f["name"]: f["value"] for f in ex["lightgbm"]["features"]}
    assert feats["dow"] == wd.iso_weekday(x["target_date"])               # still the model's own ISO dow
    from app.ml.features import feature_names
    assert "dow" not in feature_names(ss.get("model"))                   # ... while the next training would drop it


# ================================================================== data-review findings (1.2.9 second batch)
def test_the_preview_is_checked_again_under_the_write_lock(client, monkeypatch):
    """A preview used meanwhile (another job), a D-1 load after the preview, or source data that changed after it:
    the load stops before the DELETE and writes nothing."""
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    fake = _production([_row(y, "A", 5), _row(y, "B", 1)])
    sync.run_d1_sync("J1")
    before = _demand_rows()

    def run(pv):
        with pytest.raises(AppError) as e:
            sync.run_d1_sync("JX", backfill_start=str(y), backfill_end=str(y), backfill_preview_id=pv["preview_id"])
        assert e.value.code == "BACKFILL_PREVIEW_REQUIRED"
        assert _demand_rows() == before
        return e.value.detail

    # 1. another job marks the preview USED while this one reads BigQuery
    pv = sync.backfill_preview(str(y), str(y))
    real = connector.fetch_daily

    def fetch_and_race(*a, **k):
        out = real(*a, **k)
        with db.tx() as c:
            sync._state_set(c, sync.BACKFILL_PREVIEW_STATE, {**pv, "status": "USED", "used_by_job": "OTHER"})
        return out
    monkeypatch.setattr(connector, "fetch_daily", fetch_and_race)
    assert "no longer READY" in run(pv)
    monkeypatch.setattr(connector, "fetch_daily", real)
    # 2. a regular D-1 load after the preview
    pv = sync.backfill_preview(str(y), str(y))
    sync.run_d1_sync("J2")
    before = _demand_rows()
    assert "D-1 load" in run(pv)
    # 3. the source changed after the preview
    pv = sync.backfill_preview(str(y), str(y))
    fake.responses["daily"] = [_row(y, "A", 9), _row(y, "B", 1)]
    assert "changed since the preview" in run(pv)
    # the same data as previewed: written
    pv = sync.backfill_preview(str(y), str(y))
    assert sync.run_d1_sync("J3", backfill_start=str(y), backfill_end=str(y), backfill_preview_id=pv["preview_id"])["backfill"]


def test_a_d1_load_in_the_same_second_as_the_previous_one_still_makes_the_preview_stale(client):
    """1.2.9 (fourth batch): the last regular D-1 load is identified by a unique load id, not only by its one-second
    timestamp - two loads in the same second let the stale preview through (seen once in a fast full-suite run)."""
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    _production([_row(y, "A", 5), _row(y, "B", 1)])
    frozen = timeutil.now_utc()
    timeutil.set_now_override(lambda: frozen)
    try:
        sync.run_d1_sync("J1")
        pv = sync.backfill_preview(str(y), str(y))
        sync.run_d1_sync("J2")                      # the same second: the same synced_at as J1
        with db.read() as c:
            st = sync._state_get(c, f"last_d1_sync:{pv['scope_key']}")
        assert st["synced_at"] == pv["last_d1_synced_at"]       # the timestamp alone cannot tell J1 and J2 apart
        assert st["load_id"] != pv["last_d1_load_id"] and st["job_id"] == "J2"
        before = _demand_rows()
        with pytest.raises(AppError) as e:
            sync.run_d1_sync("JX", backfill_start=str(y), backfill_end=str(y), backfill_preview_id=pv["preview_id"])
        assert e.value.code == "BACKFILL_PREVIEW_REQUIRED" and "D-1 load" in e.value.detail
        assert _demand_rows() == before
    finally:
        timeutil.set_now_override(None)


def test_preview_blocks_an_empty_read_warns_on_an_unconfirmed_yesterday_and_refuses_a_future_time(client):
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    fake = _production([_row(y, "A", 5)])
    sync.run_d1_sync("J1")
    fake.responses["daily"] = []
    pv = sync.backfill_preview(str(y), str(y))
    assert pv["status"] == "BLOCKED" and pv["error"]["code"] == "SOURCE_INCOMPLETE"
    fake.responses["daily"] = [_row(y, "A", 5)]
    fake.responses["completion"] = [{"n": 0}]
    pv = sync.backfill_preview(str(y), str(y))
    assert pv["status"] == "READY" and pv["warnings"] == [{"code": "YESTERDAY_NOT_CONFIRMED", "day": str(y)}]
    with db.tx() as c:
        sync._state_set(c, sync.BACKFILL_PREVIEW_STATE, {**pv, "checked_at": "2099-01-01T00:00:00+00:00"})
    with pytest.raises(AppError) as e:
        sync.run_d1_sync("J2", backfill_start=str(y), backfill_end=str(y), backfill_preview_id=pv["preview_id"])
    assert e.value.code == "BACKFILL_PREVIEW_REQUIRED" and "future" in e.value.detail


def test_a_backup_that_fails_while_writing_leaves_no_file_that_looks_like_a_backup(monkeypatch):
    import zipfile as zf
    from app import backup
    real = zf.ZipFile.write

    def boom(self, filename, arcname=None, *a, **k):
        if str(arcname).startswith("db/"):
            real(self, filename, arcname, *a, **k)
            raise OSError("disk full")
        return real(self, filename, arcname, *a, **k)
    monkeypatch.setattr(zf.ZipFile, "write", boom)
    with pytest.raises(OSError):
        backup.backup_database(reason="pre-backfill")
    left = sorted(p.name for p in paths.backups_dir().iterdir())
    assert not [n for n in left if n.endswith(".zip") or n.endswith(".part") or n.endswith(".db")], left
    monkeypatch.setattr(zf.ZipFile, "write", real)
    ok = backup.backup_database(reason="pre-backfill")
    assert ok.name.endswith("-pre-backfill.zip") and [b["file"] for b in backup.list_backups()] == [ok.name]


def test_a_failure_in_the_evaluation_groups_never_stops_the_backtest(small_demo, monkeypatch):
    from app.data.demand import load_demand
    from app.ml import model
    from app.ml.features import build_panel
    cfg = ss.get("model")
    p = build_panel(load_demand(small_demo["batch_id"]), max_days=cfg.max_train_days)
    ref = model.backtest(p, cfg)
    monkeypatch.setattr(dp, "classify", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    bt = model.backtest(p, cfg)
    assert bt["segments"] == {"error": "SEGMENTS_NOT_COMPUTED"} and bt["metrics"] == ref["metrics"]
