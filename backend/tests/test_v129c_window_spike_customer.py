"""1.2.9 (third batch, 20/10/2026): open hours per item (MULTI_ITEM), open hours lost by a reload (source retention), the
model-input start rule OPEN_HOURS_COVERAGE, spike-aware training weights (experiment code) and the optional customer_id
feature group (OFF by default).

All on temporary databases (conftest) with SYNTHETIC data (demo generator, hand-made rows); BigQuery is the FakeBQ client.
The real-BigQuery check of the new SQL (inline rows, 0 bytes) is test_v129c_real_bq_items_customers.py (opt-in)."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from app import db, paths, timeutil
from app import settings_service as ss
from app.bq import connector
from app.data import customers, identity, open_hours
from app.data.demand import data_window, excluded_summary, load_demand
from app.messages import AppError
from app.ml import feature_registry as registry
from app.ml import model, spike_weights
from app.ml.features import (CUSTOMER, OPEN_HOURS, Panel, build_panel, customer_on, direct_training_matrix,
                             feature_names, features_at, static_codes, training_matrix)
from fake_bq import FakeBQ

BQ_SCOPE = "BIGQUERY:lakehouse-prod-394907.sales.orders"
FM = {"order_id": {"column": "so_code", "usage": "OPTIONAL"}, "order_date": {"column": "created_date", "usage": "REQUIRED"},
      "created_at": {"column": None, "usage": "UNUSED"},
      "sku_id": {"column": "sku_code", "usage": "REQUIRED"}, "fc_id": {"column": "fc_code", "usage": "REQUIRED"},
      "order_qty": {"column": "demand_quantity", "usage": "REQUIRED"},
      "unit_price": {"column": "sales_price", "usage": "OPTIONAL"}}
REF = {"open_hours": {"column": "total_open_hours", "usage": "OPTIONAL"}}
REF_ITEM = {**REF, "item_code": {"column": "item_code", "usage": "OPTIONAL"}}


def _bq(**extra):
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders", "location": "asia-southeast1",
                           "partition_column": "", "field_mapping": FM, "reference_mapping": REF, **extra})


def _n_cols(sel: str) -> int:
    depth, n = 0, 1
    for ch in sel:
        depth += ch == "("
        depth -= ch == ")"
        n += ch == "," and depth == 0
    return n


def _union_widths(sql: str) -> list[int]:
    parts = sql.split("UNION ALL")
    return [_n_cols(p.rsplit("SELECT", 1)[1].rsplit("FROM", 1)[0]) for p in parts]


# ================================================================== A. open hours are measured per item: MULTI_ITEM
@pytest.mark.parametrize("args, out", [
    ((0, 18.22, 22.85, 2, 2, 0), (None, "MULTI_ITEM")),      # two items, one value each (26/08/2026 FC BD case)
    ((0, 18.22, 22.85, 2, 3, 0), (None, "CONFLICT")),        # one item with two values: not explained by the items
    ((0, 18.22, 22.85, 1, 2, 0), (None, "CONFLICT")),        # a single item that disagrees with itself
    ((0, 18.22, 22.85, 2, 2, 1), (None, "CONFLICT")),        # a line without item code: cannot be attributed
    ((0, 18.22, 22.85, None, None, None), (None, "CONFLICT")),   # item_code not mapped: as before 1.2.9b
    ((0, 24.0, 24.0, 2, 2, 0), (24.0, "OK")),                # several items with the same value: one value
    ((1, 18.0, 22.0, 2, 2, 0), (None, "MISSING")),           # a missing value still wins
])
def test_open_hours_that_differ_only_between_items_are_multi_item_not_conflict(args, out):
    assert open_hours.cell(*args) == out
    keys = ("open_hours_null_rows", "open_hours_min", "open_hours_max", "open_hours_items", "open_hours_item_values",
            "open_hours_no_item_rows")
    assert open_hours.row_cell(dict(zip(keys, args))) == out
    assert "MULTI_ITEM" in open_hours.STATUSES


def test_daily_sql_counts_items_only_when_the_item_code_is_mapped():
    _bq()
    sql, _ = connector._daily_sql(ss.get("bigquery"), date(2026, 10, 1), date(2026, 10, 2))
    assert "CAST(NULL AS INT64) AS open_hours_items" in sql and "ref_item_code" not in sql
    w = _union_widths(sql)
    assert w == [w[0]] * 4 and w[0] == 20
    _bq(reference_mapping=REF_ITEM)
    sql, _ = connector._daily_sql(ss.get("bigquery"), date(2026, 10, 1), date(2026, 10, 2))
    assert "COUNT(DISTINCT IF(ref_open_hours IS NULL, NULL, CAST(ref_item_code AS STRING))) AS open_hours_items" in sql
    assert "AS open_hours_item_values" in sql and "AS open_hours_no_item_rows" in sql
    w = _union_widths(sql)
    assert w == [w[0]] * 4 and w[0] == 20


def _row(day, sku, q, lo=24.0, hi=24.0, nulls=0, **extra):
    return {"order_date": day, "sku_id": sku, "fc_id": "F1", "qty": q, "n_rows": 1, "n_orders": 1, "avg_unit_price": 10.0,
            "avg_discount_rate": None, "promo_share": None, "voucher_share": None, "max_source_updated_at": None,
            "max_batch_id": None, "open_hours_null_rows": nulls, "open_hours_min": lo, "open_hours_max": hi, **extra}


def test_d1_stores_multi_item_without_a_value_and_the_training_still_waits_for_a_rule(client):
    from test_v129_backfill_history_patterns import _production
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    _production([_row(y, "TWO", 5, 18.22, 22.85, open_hours_items=2, open_hours_item_values=2, open_hours_no_item_rows=0),
                 _row(y, "SAME", 3, 24.0, 24.0, open_hours_items=2, open_hours_item_values=2, open_hours_no_item_rows=0),
                 _row(y, "BAD", 2, 5.0, 9.0, open_hours_items=1, open_hours_item_values=2, open_hours_no_item_rows=0)])
    res = sync.run_d1_sync("J1")
    assert res["open_hours_status_rows"] == {"OK": 1, "MISSING": 0, "OUT_OF_RANGE": 0, "CONFLICT": 1, "MULTI_ITEM": 1,
                                             "NOT_READ": 0}
    with db.read() as c:
        got = {r[0]: (r[1], r[2], r[3]) for r in c.execute(
            "SELECT sku_id, open_hours, open_hours_status, qty FROM demand_daily WHERE scope_key=?", (BQ_SCOPE,))}
        chk = open_hours.window_check(c, BQ_SCOPE, str(y), str(y))
    assert got == {"TWO": (None, "MULTI_ITEM", 5.0), "SAME": (24.0, "OK", 3.0), "BAD": (None, "CONFLICT", 2.0)}
    assert not chk["ok"] and set(chk["not_ok"]) == {"MULTI_ITEM", "CONFLICT"}     # no aggregation rule is invented
    from app import data_checks
    by = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
    assert by["open_hours_status_values"]["status"] == "OK" and by["open_hours_value_matches_status"]["status"] == "OK"


def test_a_reload_that_would_lose_stored_open_hours_is_announced_and_counted(client):
    """The source keeps open hours for its last months only: re-reading an older day turns a stored OK value into
    MISSING. The preview warns (with counts and days), the load counts what it did not keep."""
    from test_v129_backfill_history_patterns import _production
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    fake = _production([_row(y, "A", 5), _row(y, "B", 1), _row(y, "C", 2)])
    first = sync.run_d1_sync("J1")
    assert first["open_hours_lost"]["rows"] == 0
    fake.responses["daily"] = [_row(y, "A", 5), _row(y, "B", 1, None, None, 1)]       # B lost its hours, C is gone
    pv = sync.backfill_preview(str(y), str(y))
    assert pv["status"] == "READY"
    lost = pv["open_hours"]["stored_ok_not_kept"]
    assert lost == {"rows": 2, "first_day": str(y), "last_day": str(y), "now_missing": 1, "removed": 1}
    assert {"code": "OPEN_HOURS_WOULD_BE_LOST", **lost} in pv["warnings"]
    out = sync.run_d1_sync("J2", backfill_start=str(y), backfill_end=str(y), backfill_preview_id=pv["preview_id"])
    assert out["open_hours_lost"] == lost
    assert sync._open_hours_lost(set(), [], []) == {"rows": 0, "first_day": None, "last_day": None, "now_missing": 0,
                                                     "removed": 0}


# ================================================================== B. model-input start rule OPEN_HOURS_COVERAGE
def _bq_scope_with_hours_from(first_ok: str, monkeypatch):
    """BIGQUERY scope made from a demo batch (synthetic): open hours stored (status OK) from `first_ok` on, MISSING
    before - the shape of the real source (open hours for its last months only)."""
    from app.data.demo import create_demo_batch
    from app.jobs import flows
    demo = create_demo_batch(days=150, n_skus=8, seed=3)
    _bq()
    with db.tx() as c:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, "
                  "avg_discount_rate, promo_share, voucher_share, loaded_at) SELECT ?, 'BIGQUERY', order_date, sku_id, fc_id, qty, "
                  "n_orders, avg_unit_price, avg_discount_rate, promo_share, voucher_share, loaded_at FROM demand_daily "
                  "WHERE scope_key=?", (BQ_SCOPE, demo["batch_id"]))
        c.execute("UPDATE demand_daily SET open_hours = 8 + (julianday(order_date) % 17), open_hours_status='OK' "
                  "WHERE scope_key=? AND order_date >= ?", (BQ_SCOPE, first_ok))
        c.execute("UPDATE demand_daily SET open_hours = NULL, open_hours_status='MISSING' WHERE scope_key=? AND order_date < ?",
                  (BQ_SCOPE, first_ok))
        lo, hi = c.execute("SELECT MIN(order_date), MAX(order_date) FROM demand_daily WHERE scope_key=?", (BQ_SCOPE,)).fetchone()
    ss.update("data_policy", {"window_start_date": lo})
    monkeypatch.setattr(flows, "_bq_ready", lambda c, blockers: None)     # production state is not under test here
    return lo, hi


def _scope():
    return {"scope_key": BQ_SCOPE, "data_source": "BIGQUERY"}


def _freeze_day_after(last_day: str) -> None:
    """Today = the day after the last stored day (10:00 Vietnam time), so the data window ends with the data."""
    d = date.fromisoformat(last_day) + timedelta(days=1)
    timeutil.set_now_override(lambda: datetime(d.year, d.month, d.day, 10, 0, tzinfo=timeutil.VN_TZ))


def test_the_default_rule_is_unchanged_and_needs_no_scan(monkeypatch):
    assert ss.DataPolicySettings().training_start_rule == "WINDOW_START"
    with db.read() as c:
        w = data_window(c, scope=_scope())
    assert w["start"] == w["configured_start"] == ss.get("data_policy").window_start_date and "excluded" not in w
    calls = []
    monkeypatch.setattr(open_hours, "coverage_start", lambda *a: calls.append(a))
    ss.update("data_policy", {"training_start_rule": "OPEN_HOURS_COVERAGE"})
    with db.read() as c:
        assert data_window(c)["start_rule"] == "OPEN_HOURS_COVERAGE"            # status pages: no scope, no scan
        data_window(c, scope={"scope_key": "B1", "data_source": "DEMO"})       # sources without open hours: no scan
    assert calls == []


def test_coverage_rule_starts_at_the_first_stored_day_with_hours_and_counts_what_it_leaves_out(client, monkeypatch):
    with monkeypatch.context() as m:
        lo, hi = _bq_scope_with_hours_from("2026-01-01", m)
        first_ok = str(date.fromisoformat(lo) + timedelta(days=40))
        with db.tx() as c:
            c.execute("UPDATE demand_daily SET open_hours=NULL, open_hours_status='MISSING' WHERE scope_key=? AND order_date < ?",
                      (BQ_SCOPE, first_ok))
            before = c.execute("SELECT COUNT(*), SUM(qty) FROM demand_daily WHERE scope_key=?", (BQ_SCOPE,)).fetchone()
            ex_rows, ex_qty = c.execute("SELECT COUNT(*), SUM(qty) FROM demand_daily WHERE scope_key=? AND order_date < ?",
                                        (BQ_SCOPE, first_ok)).fetchone()
        ss.update("data_policy", {"training_start_rule": "OPEN_HOURS_COVERAGE"})
        today = date.fromisoformat(hi) + timedelta(days=1)
        with db.read() as c:
            w = data_window(c, today=today, scope=_scope())
            s = excluded_summary(c, BQ_SCOPE, w)
            after = c.execute("SELECT COUNT(*), SUM(qty) FROM demand_daily WHERE scope_key=?", (BQ_SCOPE,)).fetchone()
        assert w["start"] == first_ok and w["coverage_start"] == first_ok and w["configured_start"] == lo
        assert w["excluded"] == {"start": lo, "end": str(date.fromisoformat(first_ok) - timedelta(days=1))}
        assert s["rows"] == ex_rows and s["qty"] == ex_qty and s["calendar_days"] == 40 and s["days_with_rows"] == 40
        assert s["rows_in_window"] == before[0] - ex_rows and abs(s["qty_share_excluded"] - ex_qty / before[1]) < 1e-12
        assert s["series"] >= 1 and 0 <= s["series_only_in_excluded_days"] <= s["series"]
        assert after == before                                                  # counted, never deleted
        # nothing stored with open hours: the configured start stays (the open-hours check then reports MISSING)
        with db.tx() as c:
            c.execute("UPDATE demand_daily SET open_hours=NULL, open_hours_status='MISSING' WHERE scope_key=?", (BQ_SCOPE,))
        with db.read() as c:
            w = data_window(c, today=today, scope=_scope())
        assert w["start"] == lo and w["coverage_start"] is None and "excluded" not in w


def test_training_backtest_and_report_use_the_same_shortened_window(client, fast_model, monkeypatch):
    from app.ml import pipeline
    with monkeypatch.context() as m:
        lo, hi = _bq_scope_with_hours_from("2026-01-01", m)
        first_ok = str(date.fromisoformat(lo) + timedelta(days=30))
        with db.tx() as c:
            c.execute("UPDATE demand_daily SET open_hours=NULL, open_hours_status='MISSING' WHERE scope_key=? AND order_date < ?",
                      (BQ_SCOPE, first_ok))
            n_before = c.execute("SELECT COUNT(*) FROM demand_daily WHERE scope_key=? AND order_date < ?",
                                 (BQ_SCOPE, first_ok)).fetchone()[0]
        _freeze_day_after(hi)
        with pytest.raises(AppError) as e:                       # default rule: the MISSING days block the training
            pipeline.train_and_publish(force=True, source="BIGQUERY")
        assert e.value.code == "OPEN_HOURS_INVALID" and "MISSING" in e.value.detail
        ss.update("data_policy", {"training_start_rule": "OPEN_HOURS_COVERAGE"})
        res = pipeline.train_and_publish(force=True, source="BIGQUERY")
        assert res["status"] == "PUBLISHED", res
        with db.read() as c:
            tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (res["training_run_id"],))
            bt = db.one(c, "SELECT folds_json FROM backtest_runs WHERE training_run_id=?", (tr["id"],))
            n_after = c.execute("SELECT COUNT(*) FROM demand_daily WHERE scope_key=? AND order_date < ?",
                                (BQ_SCOPE, first_ok)).fetchone()[0]
        fc = json.loads(tr["feature_config_json"])
        assert tr["train_start"] == first_ok                                  # training panel
        win = fc["data_window"]
        assert win["start"] == first_ok and win["start_rule"] == "OPEN_HOURS_COVERAGE"
        assert win["excluded_summary"]["rows"] == n_before and win["excluded_summary"]["calendar_days"] == 30
        assert fc["feature_decisions"]["open_hours"]["window_check"]["ok"]    # the check covers the same window
        folds = json.loads(bt["folds_json"])
        assert folds and all(f["origin"] > first_ok for f in folds)            # backtest folds inside the same panel
        assert n_after == n_before                                            # the excluded days stay stored
        ss.update("general", {"active_source": "BIGQUERY"})
        rep = client.get("/api/data-quality?refresh=false").json()            # the report of the training
        assert rep["stats"]["data_window"]["start"] == first_ok
        from app import data_checks
        by = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
        assert by["open_hours_window_ready"]["status"] == "OK" and "OPEN_HOURS_COVERAGE" in by["open_hours_window_ready"]["rule"]


# ================================================================== D. spike-aware training weights (experiment code)
W3 = {"SINGLE": 0.25, "OPEN_SINGLE": 0.25, "DOUBLE_OPEN": 0.6, "DOUBLE_CLOSED": 0.25, "LONG": 1.0}


def _spiky():
    Y = np.full((1, 40), 5.0)
    Y[0, 10] = 60                                   # one day, the next day normal
    Y[0, 20], Y[0, 21] = 60, 70                     # two days, the third day normal
    Y[0, 30:33] = 80                                # three days: a level change
    Y[0, 38], Y[0, 39] = 90, 90                     # two days at the cutoff: the third day is not known
    return Y


def test_spike_episodes_are_classified_with_what_is_known_at_the_cutoff():
    Y = _spiky()
    W, s = spike_weights.weights(Y, W3)
    assert list(np.nonzero(W[0] < 1)[0]) == [10, 20, 21, 38, 39]
    assert W[0, [10, 20, 21, 30, 31, 32, 38, 39]].tolist() == [0.25, 0.25, 0.25, 1.0, 1.0, 1.0, 0.6, 0.6]
    assert s["episodes_by_class"] == {"SINGLE": 1, "OPEN_SINGLE": 0, "DOUBLE_OPEN": 1, "DOUBLE_CLOSED": 1, "LONG": 1}
    assert s["days_down_weighted"] == 5 and s["days_kept_full_weight"] == 3 and s["spike_days"] == 8
    # time-updated: one day earlier the last spike is a one-day spike seen today (OPEN_SINGLE)
    W39, _ = spike_weights.weights(Y[:, :39], W3)
    assert W39[0, 38] == 0.25 and spike_weights.episodes(*spike_weights.spike_days(Y[:, :39])[:1],
                                                         ~np.isnan(Y[:, :39]))[0, 38] == "OPEN_SINGLE"
    # a day without data after a spike leaves it open (never read as "the spike stopped")
    Yg = Y.copy()
    Yg[0, 11] = np.nan
    cls = spike_weights.episodes(spike_weights.spike_days(Yg)[0], ~np.isnan(Yg))
    assert cls[0, 10] == "OPEN_SINGLE"
    soft, _ = spike_weights.weights(Y, {"soft": True})
    thr = spike_weights.rolling_thresholds(Y)
    assert soft[0, 10] == pytest.approx(thr[0, 10] / 60) and soft[0, 0] == 1.0
    assert np.array_equal(Y, _spiky())                                       # the demand is never changed


def test_spike_thresholds_and_weights_never_read_a_later_day():
    rng = np.random.default_rng(1)
    Y = rng.poisson(4, size=(30, 120)).astype(float)
    Y[rng.random(Y.shape) < 0.02] *= 15
    thr = spike_weights.rolling_thresholds(Y)
    for t in (20, 60, 100):
        Y2 = Y.copy()
        Y2[:, t:] = rng.poisson(50, size=Y2[:, t:].shape)                    # anything from day t on
        assert np.array_equal(spike_weights.rolling_thresholds(Y2)[:, :t + 1], thr[:, :t + 1])
        # a training panel that ends at the cutoff t gets the same weights whatever happens from t on
        assert np.array_equal(spike_weights.weights(Y[:, :t], W3)[0], spike_weights.weights(Y2[:, :t], W3)[0])
    cut = spike_weights.spike_days(Y, "cutoff")[1]
    assert np.allclose(cut[:, 0], cut[:, -1])                                # one threshold per series, from the panel


def _panel(S=12, T=110, seed=4):
    rng = np.random.default_rng(seed)
    import pandas as pd
    days = pd.date_range("2026-03-01", periods=T)
    rows = [{"order_date": str(d.date()), "sku_id": f"S{s}", "fc_id": "F1", "qty": float(rng.poisson(3 + s)),
             "n_orders": 1, "avg_unit_price": 10.0, "avg_discount_rate": None, "promo_share": None, "voucher_share": None,
             "open_hours": None} for s in range(S) for d in days]
    return build_panel(pd.DataFrame(rows))


def test_training_rows_carry_their_series_and_target_day_and_weights_change_only_the_loss():
    p = _panel()
    cfg = ss.ModelSettings(num_boost_round=20, forecast_strategy="DIRECT", direct_origins=4, backtest_horizon_days=7,
                           feature_price=False, feature_promotion=False)
    X, y = direct_training_matrix(p, cfg, 7)
    X2, y2, ix = direct_training_matrix(p, cfg, 7, with_index=True)
    assert np.array_equal(X, X2, equal_nan=True) and np.array_equal(y, y2) and np.array_equal(y, p.Y[ix[:, 0], ix[:, 1]])
    cfg_r = cfg.model_copy(update={"forecast_strategy": "RECURSIVE"})
    Xr, yr, ixr = training_matrix(p, cfg_r, with_index=True)
    assert np.array_equal(yr, p.Y[ixr[:, 0], ixr[:, 1]]) and np.array_equal(Xr, training_matrix(p, cfg_r)[0], equal_nan=True)
    Y0 = p.Y.copy()
    b0, i0 = model.train(p, cfg)
    b1, i1 = model.train(p, cfg, weights=np.ones(p.Y.shape))
    f0 = model.forecast(p, b0, cfg, 7)["yhat"]
    assert np.allclose(f0, model.forecast(p, b1, cfg, 7)["yhat"])           # weight 1 everywhere = the training as before
    assert "weights" not in i0 and i1["weights"]["rows_below_1"] == 0
    W = np.ones(p.Y.shape)
    W[:, -20:] = 0.1
    b2, i2 = model.train(p, cfg, weights=W)
    assert i2["weights"]["rows_below_1"] > 0 and not np.allclose(f0, model.forecast(p, b2, cfg, 7)["yhat"])
    assert np.array_equal(p.Y, Y0, equal_nan=True)                           # targets untouched
    for bad in (np.ones((2, 2)), np.full(p.Y.shape, -1.0), np.full(p.Y.shape, np.inf)):
        with pytest.raises(ValueError):
            model.train(p, cfg, weights=bad)


def test_the_application_training_never_passes_spike_weights():
    import inspect
    from app.ml import pipeline
    src = inspect.getsource(pipeline) + inspect.getsource(model.backtest)
    assert "weights=" not in src and "spike_weights" not in src


# ================================================================== E. customer_id: OFF by default, aggregates only
def test_customer_features_are_off_by_default_and_never_used_without_data():
    m = ss.ModelSettings()
    assert m.feature_customer is False and not customer_on(m) and not set(CUSTOMER) & set(feature_names(m))
    assert ss.BigQuerySettings().customer_id_column == ""
    cfg, dec = registry.resolve(m, {"rows": 100, "avg_unit_price": 1.0, "customer_count": 1.0})
    assert dec["customer"]["used"] is False and dec["customer"]["reason"] == "TOGGLE_OFF" and not customer_on(cfg)
    cfg, dec = registry.resolve(m.model_copy(update={"feature_customer": True}), {"rows": 100, "avg_unit_price": 1.0,
                                                                                    "customer_count": None})
    assert dec["customer"]["reason"] == "NO_DATA" and not customer_on(cfg)    # switched on, no data: left out
    cfg, dec = registry.resolve(m.model_copy(update={"feature_customer": True}), {"rows": 100, "avg_unit_price": 1.0,
                                                                                    "customer_count": 0.9})
    assert dec["customer"]["used"] and customer_on(cfg) and feature_names(cfg)[-3:] == CUSTOMER
    assert set(CUSTOMER) <= set(registry.all_model_features())


def test_an_unmapped_customer_column_changes_neither_the_query_nor_the_mapping_hash():
    _bq()
    bq = ss.get("bigquery")
    h0 = connector.mapping_hash(bq)
    sql0, prm0 = connector._daily_sql(bq, date(2026, 10, 1), date(2026, 10, 2))
    assert "cust" not in sql0 and [p[0] for p in prm0] == ["start", "end"]
    _bq(customer_id_column="customer_code")
    bq = ss.get("bigquery")
    assert connector.mapping_hash(bq) != h0                                  # mapping it is a new validated state
    sql, prm = connector._daily_sql(bq, date(2026, 10, 1), date(2026, 10, 2))
    assert dict((p[0], p[2]) for p in prm)["cust_start"] == date(2026, 10, 1) - timedelta(days=customers.REPEAT_LOOKBACK_DAYS)
    assert "NULLIF(TRIM(CAST(`customer_code` AS STRING)), '') AS cid" in sql and "LEFT JOIN cust" in sql
    head = sql.split("SELECT valid.*", 1)[1].split("UNION ALL", 1)[0]
    assert "cid" not in head and "customer_code" not in head                 # only counts leave BigQuery
    w = _union_widths(sql.split("valid AS (", 1)[0] + sql.split("SELECT valid.*", 1)[1].replace(
        ", cust.customer_count, cust.repeat_customer_count, cust.repeat_interval_days_sum ", "SELECT a, b, c, d, e, f, g, "
        "h, i, j, k, l, m, n, o, p, q, r, s, t, u, v, w ", 1))
    assert len(set(w[1:])) == 1 and w[1] == 23                               # 20 columns + 3 customer counts
    _bq(customer_id_column="")
    assert connector.mapping_hash(ss.get("bigquery")) == h0                  # unmapped again: the old hash
    with pytest.raises(Exception):
        _bq(customer_id_column="bad name;")


@pytest.mark.parametrize("cols, name, codes", [
    ([{"name": "c", "type": "STRING"}], "", []), ([{"name": "c", "type": "STRING"}], "c", []),
    ([{"name": "c", "type": "INTEGER"}], "c", []), ([{"name": "c", "type": "FLOAT"}], "c", ["TYPE_NOT_ALLOWED"]),
    ([{"name": "c", "type": "STRING"}], "x", ["COLUMN_NOT_FOUND"])])
def test_the_customer_column_must_exist_with_an_identifier_type(cols, name, codes):
    assert [e["code"] for e in customers.check_column(cols, name)] == codes


def test_d1_stores_customer_counts_null_when_unknown_and_data_checks_guard_them(client):
    from test_v129_backfill_history_patterns import _production
    from app import data_checks, sync
    y = timeutil.today_vn() - timedelta(days=1)
    _production([_row(y, "A", 5, customer_count=3, repeat_customer_count=2, repeat_interval_days_sum=17),
                 _row(y, "B", 1)])
    sync.run_d1_sync("J1")
    with db.read() as c:
        got = {r[0]: r[1:] for r in c.execute("SELECT sku_id, customer_count, repeat_customer_count, "
                                              "repeat_interval_days_sum FROM demand_daily WHERE scope_key=?", (BQ_SCOPE,))}
    assert got == {"A": (3, 2, 17.0), "B": (None, None, None)}             # unknown stays NULL, never 0
    by = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
    assert by["customer_counts_consistent"]["status"] == "OK" and by["customer_counts_source_scope"]["status"] == "OK"
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET repeat_customer_count = 9 WHERE sku_id='A'")
    by = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
    assert by["customer_counts_consistent"]["status"] == "FAIL"


def _cust_panel():
    p = _panel(S=3, T=60)
    rng = np.random.default_rng(7)
    p.customers = rng.integers(1, 6, size=p.Y.shape).astype(float)
    p.repeat_customers = np.minimum(p.customers, rng.integers(0, 4, size=p.Y.shape)).astype(float)
    p.repeat_interval = p.repeat_customers * 9.0
    p.customers[0, :] = np.nan                                               # a series without any identifier
    p.repeat_customers[0, :] = np.nan
    p.repeat_interval[0, :] = np.nan
    p.customers[1, 50] = p.repeat_customers[1, 50] = p.repeat_interval[1, 50] = np.nan
    return p


def test_customer_features_read_only_the_known_days_before_the_target():
    p = _cust_panel()
    cfg = ss.ModelSettings(feature_customer=True, feature_price=False, feature_promotion=False)
    sc, fcc = static_codes(p)
    names = feature_names(cfg)
    ix = [names.index(n) for n in CUSTOMER]
    t = 55
    X = features_at(p, p.Y, p.price, p.disc, p.promo, p.dates, t, cfg, sc, fcc)[:, ix]
    lo = t - 28
    n, r, iv = p.customers[1, lo:t], p.repeat_customers[1, lo:t], p.repeat_interval[1, lo:t]
    k = ~np.isnan(n)
    assert X[1, 0] == pytest.approx(n[k].mean()) and X[1, 1] == pytest.approx(r[k].sum() / n[k].sum())
    assert X[1, 2] == pytest.approx(9.0 if r[k].sum() else np.nan, nan_ok=True)
    assert np.isnan(X[0]).all()                                              # no identifier at all: unknown, not 0
    q = Panel(p.keys, p.dates, p.Y, p.price, p.disc, p.promo, p.start_idx, p.missing_days, p.sku_codes, p.fc_codes,
              hours=p.hours, customers=p.customers.copy(), repeat_customers=p.repeat_customers.copy(),
              repeat_interval=p.repeat_interval.copy())
    q.customers[:, t:] = 1000
    q.repeat_customers[:, t:] = 1000
    q.repeat_interval[:, t:] = 1
    X2 = features_at(q, q.Y, q.price, q.disc, q.promo, q.dates, t, cfg, sc, fcc)[:, ix]
    assert np.array_equal(X, X2, equal_nan=True)                             # the target day and later: never read
    q.customers[1, t - 1] = 1000
    assert features_at(q, q.Y, q.price, q.disc, q.promo, q.dates, t, cfg, sc, fcc)[1, ix[0]] != X[1, 0]
    with pytest.raises(ValueError):
        features_at(Panel(p.keys, p.dates, p.Y, p.price, p.disc, p.promo, p.start_idx, p.missing_days, p.sku_codes,
                          p.fc_codes), p.Y, p.price, p.disc, p.promo, p.dates, t, cfg, sc, fcc)
    trunc = p.truncate(40)
    assert trunc.customers.shape == (3, 40) and np.array_equal(trunc.customers, p.customers[:, :40], equal_nan=True)


def test_customer_group_on_keeps_the_sku_fc_grain_and_off_returns_exactly_to_the_baseline(client, fast_model, monkeypatch):
    """SYNTHETIC customer counts on a demo-derived BIGQUERY scope (labelled synthetic: no real customer data exists)."""
    from app.ml import pipeline
    with monkeypatch.context() as m:
        lo, hi = _bq_scope_with_hours_from("2026-01-01", m)
        _freeze_day_after(hi)
        off1 = pipeline.train_and_publish(force=True, source="BIGQUERY")
        with db.tx() as c:                                                   # synthetic aggregates, repeat <= customers
            c.execute("UPDATE demand_daily SET customer_count = 1 + (CAST(qty AS INTEGER) % 5), "
                      "repeat_customer_count = (CAST(qty AS INTEGER) % 5) / 2, "
                      "repeat_interval_days_sum = 7.0 * ((CAST(qty AS INTEGER) % 5) / 2) WHERE scope_key=?", (BQ_SCOPE,))
        off2 = pipeline.train_and_publish(force=True, source="BIGQUERY")
        ss.update("model", {"feature_customer": True})
        on = pipeline.train_and_publish(force=True, source="BIGQUERY")
        ss.update("model", {"feature_customer": False})
        off3 = pipeline.train_and_publish(force=True, source="BIGQUERY")
        assert off1["status"] == "PUBLISHED" and {r["status"] for r in (off2, on, off3)} == {"CANDIDATE"}  # kept for review
        for r in (on, off3):                       # explicit promotion (test database): ON first, then OFF again
            assert pipeline.promote_candidate(r["training_run_id"])["status"] == "PUBLISHED"
        with db.read() as c:
            runs = {k: db.one(c, "SELECT * FROM training_runs WHERE id=?", (r["training_run_id"],))
                    for k, r in (("off1", off1), ("off2", off2), ("on", on), ("off3", off3))}
            vals = {k: c.execute("SELECT sku_id, fc_id, target_date, yhat FROM forecast_values v JOIN forecast_runs f "
                                 "ON f.id = v.run_id WHERE f.training_run_id=? ORDER BY 1, 2, 3",
                                 (runs[k]["id"],)).fetchall() for k in ("off1", "on", "off3")}
            bt = {k: json.loads(db.one(c, "SELECT metrics_json FROM backtest_runs WHERE training_run_id=?",
                                       (runs[k]["id"],))["metrics_json"])["pooled"] for k in runs}
        fc = {k: json.loads(r["feature_config_json"]) for k, r in runs.items()}
        assert set(CUSTOMER) <= set(fc["on"]["features"]) and fc["on"]["config"]["feature_customer"] is True
        assert fc["on"]["feature_groups"]["customer"] == {"switch_on": True, "used": True}
        assert fc["on"]["data_identity"]["columns"][-3:] == list(identity.CUSTOMER_COLUMNS)
        for k in ("off1", "off2", "off3"):
            assert not set(CUSTOMER) & set(fc[k]["features"]) and fc[k]["config"]["feature_customer"] is False
        # one row per SKU x FC x day in every run, the same series and days with and without the group
        grain = {k: [(a, b, d) for a, b, d, _ in v] for k, v in vals.items()}
        assert all(len(g) == len(set(g)) for g in grain.values()) and grain["on"] == grain["off1"]
        # OFF: the stored customer counts are never read - the same backtest and forecast as before they existed
        assert bt["off1"] == bt["off2"] == bt["off3"]
        assert [v[3] for v in vals["off3"]] == pytest.approx([v[3] for v in vals["off1"]])
        assert grain["off3"] == grain["off1"]
        # the ON model is explained with its own feature list (artifact compatibility)
        run = db.one(db.connect(), "SELECT * FROM forecast_runs WHERE training_run_id=?", (runs["on"]["id"],))
        x = next(v for v in client.get(f"/api/forecast-runs/{run['id']}/values?limit=5000").json()["rows"]
                 if v["method"] == "LIGHTGBM")
        ex = client.get(f"/api/forecast-runs/{run['id']}/explain",
                        params={"sku_id": x["sku_id"], "fc_id": x["fc_id"], "target_date": x["target_date"]}).json()
        assert ex["reproduction"]["status"] == "OK" and ex["lightgbm"]["matches_published"]
        assert set(CUSTOMER) <= {f["name"] for f in ex["lightgbm"]["features"]}


def test_no_customer_identifier_reaches_the_app_logs_or_tables(client, caplog):
    """The identifier column is used only inside the query: the daily SELECT returns counts, the app stores counts."""
    from test_v129_backfill_history_patterns import _production
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    fake = _production([_row(y, "A", 5, customer_count=2, repeat_customer_count=1, repeat_interval_days_sum=4)])
    fake.schema = list(fake.schema) + [("customer_code", "STRING")]
    ss.update("bigquery", {"customer_id_column": "customer_code", "schema_snapshot": connector.read_schema()["columns"]})
    assert not connector.validation_ok_for_current()            # mapping it is a new state: validated again first
    assert connector.validate_source()["passed"]
    caplog.set_level("DEBUG")
    res = sync.run_d1_sync("J1")
    daily = [q for q, _ in fake.queries if q.startswith("-- df:daily")]
    assert daily and "LEFT JOIN cust" in daily[-1] and "`customer_code`" in daily[-1]
    out = daily[-1].split("SELECT valid.*", 1)[1]
    assert "customer_code" not in out and " cid" not in out                  # the final SELECT: counts only
    with db.read() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(demand_daily)")]
        got = c.execute("SELECT customer_count, repeat_customer_count, repeat_interval_days_sum FROM demand_daily "
                        "WHERE scope_key=?", (BQ_SCOPE,)).fetchall()
    assert [tuple(r) for r in got] == [(2, 1, 4.0)] and not {"customer_id", "customer_code", "cid"} & set(cols)
    assert "customer_code" not in json.dumps(res, default=str)               # the job result names no identifier
    fake.schema = [s for s in fake.schema if s[0] != "customer_code"]        # the column disappears from the source
    with pytest.raises(AppError) as e:
        sync.run_d1_sync("J2")
    assert e.value.code in ("BQ_MAPPING_INVALID", "BQ_VALIDATION_REQUIRED")


# ================================================================== E. migration 0008 (additive) on a database copy
def test_migration_0008_is_additive_and_reversible_on_a_copy(tmp_path):
    src = tmp_path / "v7.db"
    c = sqlite3.connect(src)
    c.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    for v, p in db.available_migrations():
        if v > 7:
            continue
        for stmt in db._split_sql(p.read_text(encoding="utf-8")):
            c.execute(stmt)
        c.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (v, p.name, "2026-10-20T00:00:00+00:00"))
    c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, "
                  "loaded_at, open_hours, open_hours_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  [("BIGQUERY:p.d.t", "BIGQUERY", f"2026-10-{d:02d}", f"S{s}", "F1", float(d * s), 1, 9.5, "2026-10-19",
                    24.0, "OK") for d in range(1, 11) for s in range(1, 4)])
    c.commit()
    before = c.execute("SELECT * FROM demand_daily ORDER BY rowid").fetchall()
    cols7 = [r[1] for r in c.execute("PRAGMA table_info(demand_daily)")]
    c.close()
    res = db.migrate(src)
    assert res["applied"] == ["0008_customer_aggregates.sql", "0009_actual_finalization.sql"] and res["to"] == 9
    again = db.migrate(src)
    assert again["applied"] == []                                            # idempotent
    c = sqlite3.connect(src)
    cols8 = [r[1] for r in c.execute("PRAGMA table_info(demand_daily)")]
    assert cols8 == cols7 + list(customers.COLUMNS)
    assert c.execute(f"SELECT {', '.join(cols7)} FROM demand_daily ORDER BY rowid").fetchall() == before
    assert c.execute("SELECT COUNT(*) FROM demand_daily WHERE customer_count IS NOT NULL OR repeat_customer_count "
                     "IS NOT NULL OR repeat_interval_days_sum IS NOT NULL").fetchone()[0] == 0
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    from test_v129g_actual_final import reverse_0009                         # 0009 (seventh batch) is undone first
    reverse_0009(c)
    for col in reversed(customers.COLUMNS):                                  # the reverse statements of the header
        c.execute(f"ALTER TABLE demand_daily DROP COLUMN {col}")
    c.execute("DELETE FROM schema_migrations WHERE version = 8")
    c.commit()
    assert [r[1] for r in c.execute("PRAGMA table_info(demand_daily)")] == cols7
    assert c.execute("SELECT * FROM demand_daily ORDER BY rowid").fetchall() == before
    c.close()


def test_load_demand_returns_the_new_columns_as_unknown_for_old_rows():
    from app.data.demo import create_demo_batch
    d = load_demand(create_demo_batch(days=30, n_skus=2, seed=1)["batch_id"])
    assert {"customer_count", "repeat_customer_count", "repeat_interval_days_sum"} <= set(d.columns)
    assert d["customer_count"].isna().all()
    p = build_panel(d)
    assert p.customers is None and p.repeat_customers is None and p.repeat_interval is None   # no memory for nothing
    assert p.truncate(10).customers is None
    d.loc[d.index[0], ["customer_count", "repeat_customer_count", "repeat_interval_days_sum"]] = [2, 1, 5.0]
    p = build_panel(d)
    assert np.nansum(p.customers) == 2 and np.isnan(p.customers).sum() == p.customers.size - 1
