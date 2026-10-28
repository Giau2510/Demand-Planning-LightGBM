"""1.3.1 C3-T2 tests (B3-B8): daily forecast refresh with the model in use (ml/daily_refresh.py), the open-hours read
(bq/aux_sources.py), the groups A / B / C in the DB (ml/sku_group.py), actual_daily and the log retention
(docs/ke_hoach_lgbm_chot.md sections 1-3 and 6.3). The jobs / scheduler / flows part is in test_v131_refresh_jobs.py.

Isolated databases (conftest), synthetic demo data copied into a BIGQUERY scope, a real small LightGBM model trained and
published by pipeline.train_and_publish (fast_model settings) and a fake BigQuery client (fake_bq.FakeBQ; every test
gets one, so no query can ever reach the real library): unit tests and integration with fakes only - no BigQuery, no
real data, no secret."""
import json
import sqlite3
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from app import db, paths
from app import settings_service as ss
from app import timeutil
from app.bq import aux_sources, connector
from app.data.demand import resolve_scope
from app.ml import daily_refresh as dr
from app.ml import model, pipeline, sku_group
from app.timeutil import VN_TZ
from fake_bq import FakeBQ

D = date(2026, 10, 28)                                   # forecast day (Wednesday, Vietnam)
# 06:30 in Vietnam = 23:30 UTC of 27/10: the UTC day of every timestamp written now is the day BEFORE the business day
NOW = datetime(2026, 10, 28, 6, 30, tzinfo=VN_TZ)
FM = {"order_id": {"column": "so_code", "usage": "OPTIONAL"}, "order_date": {"column": "created_date", "usage": "REQUIRED"},
      "created_at": {"column": None, "usage": "UNUSED"},
      "sku_id": {"column": "sku_code", "usage": "REQUIRED"}, "fc_id": {"column": "fc_code", "usage": "REQUIRED"},
      "order_qty": {"column": "demand_quantity", "usage": "REQUIRED"},
      "unit_price": {"column": "sales_price", "usage": "OPTIONAL"}}
REF = {"product_id": {"column": "product_id", "usage": "OPTIONAL"}, "sales_price": {"column": "sales_price", "usage": "OPTIONAL"},
       "open_hours": {"column": "total_open_hours", "usage": "OPTIONAL"},
       "open_days": {"column": "total_open_days", "usage": "OPTIONAL"}}
BQ_SCOPE = "BIGQUERY:lakehouse-prod-394907.sales.orders"
OH_TABLE = "lakehouse-prod-394907.gold_buymed_vn2.openhours_by_sku"
NEW_SKU = "SKU-NEW-1"                                   # 10 days of history: FALLBACK_NEW_SERIES under the 1.2.14 rules
NEW_TABLES = ("forecast_refresh_runs", "forecast_refresh_values", "open_hours_daily", "aux_source_reads", "actual_daily",
              "sku_group", "accuracy_report_runs", "training_feature_importance")
OLD_TABLES = ("forecast_runs", "forecast_values", "training_runs", "backtest_runs")
# fix F2b: the FULL open-hours range of D (27/07..27/10, 93 days) is read as sub-ranges of <= 15 days aligned on D-1
FULL_SUBS = [(date(2026, 7, 27), date(2026, 7, 29))] + [
    (date(2026, 7, 30) + timedelta(days=15 * i), date(2026, 8, 13) + timedelta(days=15 * i)) for i in range(6)]


# ------------------------------------------------------------------ helpers (also used by test_v131_refresh_jobs.py)
def _freeze(dt):
    timeutil.set_now_override(lambda: dt)


@pytest.fixture(autouse=True)
def _no_real_bigquery():
    """Every test starts with an empty fake client: nothing can reach google.cloud.bigquery (conftest resets it)."""
    connector.set_client_factory(FakeBQ())


class OhBQ(FakeBQ):
    """Fake client answering the open-hours query (kind daily_open_hours) for `keys` (default: every stored series of
    the scope) and every day of the requested range up to oh_end; `modified` = last-modified time of the table."""

    def __init__(self, keys=None, hours=10.0, oh_end=None, modified=None, skip=(), **kw):
        super().__init__(responses={"daily_open_hours": self._rows}, **kw)
        self.keys, self.hours, self.oh_end, self.modified, self.skip = keys, hours, oh_end, modified, set(skip)

    def _rows(self, cfg):
        p = {n: v for n, _t, v in cfg["params"]}
        out, d = [], p["start"]
        while d <= min(p["end"], self.oh_end or p["end"]):
            for fc, sku in self.keys or _keys():
                if (fc, sku) not in self.skip:
                    out.append({"fc_code": fc, "sku_code": sku, "open_date": d.isoformat(), "total_open_hours": self.hours,
                                "n_items": 1})
            d += timedelta(days=1)
        return out

    def get_table(self, name):
        t = super().get_table(name)
        t.modified = self.modified
        return t


def _fake_oh(**kw) -> OhBQ:
    fake = OhBQ(**kw)
    connector.set_client_factory(fake)
    return fake


def _real(fake, kind="daily_open_hours"):
    """Parameters of the non-dry-run queries of one kind."""
    return [{n: v for n, _t, v in cfg["params"]} for sql, cfg in fake.queries
            if sql.startswith(f"-- df:{kind}") and not cfg.get("dry_run")]


def _keys(scope=BQ_SCOPE):
    with db.read() as c:
        return [(r[0], r[1]) for r in c.execute("SELECT DISTINCT fc_id, sku_id FROM demand_daily WHERE scope_key=? "
                                                "ORDER BY 1, 2", (scope,))]


def _d1_ok(day=D, finished=None, window_end=None, status="SUCCEEDED", result_status=None, key=None):
    """A D1_SYNC job row (default: succeeded now, regular load of `day` ending day-1)."""
    res = {"window_end": str(window_end or (day - timedelta(days=1)))}
    if result_status:
        res["status"] = result_status
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, created_at, "
                  "finished_at, result_json) VALUES (?, 'D1_SYNC', ?, 'SCHEDULE', ?, 1, 4, ?, ?, ?)",
                  (db.new_id("JOB"), key or f"D1_SYNC:{day}:{db.new_id('K')}", status, timeutil.now_iso(),
                   finished or timeutil.now_iso(), json.dumps({"result": res})))


def _bq_settings():
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders", "location": "asia-southeast1",
                           "partition_column": "", "field_mapping": {k: ss.FieldMapping(**v) for k, v in FM.items()},
                           "reference_mapping": {k: ss.FieldMapping(**v) for k, v in REF.items()}})


def _demand_row(c, day, sku, fc, qty, hours=10.0, scope=BQ_SCOPE):
    c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at, "
              "open_hours, open_hours_status) VALUES (?, 'BIGQUERY', ?, ?, ?, ?, 1, 'x', ?, 'OK')",
              (scope, str(day), sku, fc, qty, hours))


def train_bq_model(monkeypatch, new_series=True, **model_kw) -> dict:
    """A BIGQUERY scope (demo data ending D-1 with open hours, plus NEW_SKU with 10 days of history) and a model in use
    trained and published on it with the given model settings."""
    _freeze(NOW)
    from app.data.demo import create_demo_batch
    from app.jobs import flows
    demo = create_demo_batch(days=150, n_skus=8, seed=3)
    _bq_settings()
    with db.tx() as c:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, "
                  "avg_discount_rate, promo_share, voucher_share, loaded_at, open_hours, open_hours_status) SELECT ?, "
                  "'BIGQUERY', order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, avg_discount_rate, promo_share, "
                  "voucher_share, loaded_at, 8 + (julianday(order_date) % 17), 'OK' FROM demand_daily WHERE scope_key=?",
                  (BQ_SCOPE, demo["batch_id"]))
        if new_series:
            fc = c.execute("SELECT MIN(fc_id) FROM demand_daily WHERE scope_key=?", (BQ_SCOPE,)).fetchone()[0]
            for i in range(1, 11):
                _demand_row(c, D - timedelta(days=i), NEW_SKU, fc, 3 + i % 4)
    if model_kw:
        ss.update("model", model_kw)
    monkeypatch.setattr(flows, "_bq_ready", lambda c, blockers: None)
    res = pipeline.train_and_publish(force=True, source="BIGQUERY")
    assert res["status"] == "PUBLISHED", res
    ss.update("general", {"active_source": "BIGQUERY"})
    return res


@pytest.fixture
def bq_model(fast_model, monkeypatch):
    return train_bq_model(monkeypatch)


def _enable(**kw):
    ss.update("daily_forecast", {"enabled": True, **kw})


def _count(c, t, where="", p=()):
    return c.execute(f"SELECT COUNT(*) FROM {t} {where}", p).fetchone()[0]


def _counts():
    with db.read() as c:
        return {t: _count(c, t) for t in NEW_TABLES + OLD_TABLES + ("job_runs", "alerts", "audit_log", "settings_history")}


def _values(run_id):
    with db.read() as c:
        return [tuple(r) for r in c.execute(
            "SELECT fc_code, sku_code, horizon, target_date, lgb_raw, final_qty, method, group_code, flags "
            "FROM forecast_refresh_values WHERE run_id=? ORDER BY fc_code, sku_code, horizon", (run_id,))]


def _run_row(run_id):
    with db.read() as c:
        return db.one(c, "SELECT * FROM forecast_refresh_runs WHERE id=?", (run_id,))


def _model_in_use():
    with db.read() as c:
        scope = resolve_scope(c)
        inc = pipeline.incumbent(scope["scope_key"], c)
    tr = inc["training_run"]
    fcj = json.loads(tr["feature_config_json"])
    return scope, inc, tr, fcj, ss.ModelSettings.model_validate(fcj["config"])


def _oh_row(c, fc, sku, day, hours, src=(OH_TABLE, "MEDX")):
    c.execute("INSERT INTO open_hours_daily VALUES (?, ?, ?, ?, ?, ?, 1, 'x')", (*src, fc, sku, str(day), hours))


# ================================================================== 1. refusals: nothing written
def test_run_switched_off_or_without_its_inputs_writes_nothing(bq_model):
    fake = _fake_oh()
    _d1_ok()
    base = _counts()
    out = dr.run(D)                                           # daily_forecast.enabled False (default)
    assert out == {"status": "SKIPPED", "reason_code": "DAILY_FORECAST_DISABLED", "business_date": "2026-10-28"}
    assert _counts() == base and fake.queries == []          # nothing read, nothing written, no job / alert / audit
    _enable()
    base = _counts()
    ss.update("general", {"active_source": "DEMO"})
    out = dr.run(D)
    assert (out["status"], out["reason_code"]) == ("NOT_READY", "NOT_APPLICABLE_FOR_SOURCE")
    ss.update("general", {"active_source": "BIGQUERY"})
    with db.tx() as c:                                        # the data ends at D-2
        c.execute("DELETE FROM demand_daily WHERE scope_key=? AND order_date=?", (BQ_SCOPE, str(D - timedelta(days=1))))
    out = dr.run(D)
    assert (out["status"], out["reason_code"], out["last_day"]) == ("NOT_READY", "DATA_NOT_UP_TO_DATE", "2026-10-26")
    # fix F2a: the open-hours read runs BEFORE the panel is built, so this refusal comes after the (FULL) read
    n_q = len(fake.queries)
    assert n_q == 14 and all(sql.startswith("-- df:daily_open_hours") for sql, _cfg in fake.queries)
    _, _, tr, _, _ = _model_in_use()
    mpath = paths.models_dir() / tr["model_path"]
    good = mpath.read_bytes()
    mpath.write_bytes(good + b"\n")                           # the model file changed after its training
    out = dr.run(D)
    assert (out["status"], out["reason_code"]) == ("FAILED", "MODEL_FILE_MISMATCH") and "modified" in out["error"]
    mpath.write_bytes(good)
    meta = mpath.with_suffix(".json")
    meta.rename(meta.with_suffix(".bak"))                     # the category codes saved with the model are missing
    out = dr.run(D)
    assert (out["status"], out["reason_code"]) == ("FAILED", "MODEL_FILE_MISMATCH") and "category codes" in out["error"]
    after = _counts()
    # (the two source switches of the test write settings_history + audit rows; nothing else changes)
    skip = ("settings_history", "audit_log", "open_hours_daily", "aux_source_reads")
    assert {t: after[t] for t in after if t not in skip} == {t: base[t] for t in base if t not in skip}
    assert after["aux_source_reads"] == base["aux_source_reads"] + 7 and after["open_hours_daily"] > 0   # F2a read
    with db.read() as c:
        assert _count(c, "audit_log", "WHERE action LIKE 'DAILY_FORECAST%'") == 0
    assert len(fake.queries) == n_q                           # the model refusals come before the BigQuery read
    with db.read() as c:
        assert all(_count(c, t) == 0 for t in ("forecast_refresh_runs", "forecast_refresh_values", "actual_daily",
                                               "sku_group"))


def test_refresh_waits_for_a_d1_of_the_vietnam_day_then_needs_a_model_in_use():
    """No training: the D-1 check is done in Vietnam time (NOW = 23:30 UTC of 27/10)."""
    _freeze(NOW)
    _bq_settings()
    ss.update("general", {"active_source": "BIGQUERY"})
    _enable()
    # finished 23:59:59 Vietnam of 27/10 = 16:59:59 UTC: the same UTC day as NOW, but yesterday in Vietnam
    _d1_ok(finished="2026-10-27T16:59:59+00:00")
    _d1_ok(status="FAILED")                                   # today, failed
    _d1_ok(window_end=D - timedelta(days=2))                  # today, but not a load ending D-1
    _d1_ok(result_status="BACKFILL_DONE")                     # today, not a regular result
    out = dr.run(D)
    assert (out["status"], out["reason_code"]) == ("NOT_READY", "REFRESH_WAITS_FOR_D1")
    _d1_ok(finished="2026-10-27T17:00:00+00:00")              # 00:00 Vietnam of 28/10: today's D-1
    out = dr.run(D)
    assert (out["status"], out["reason_code"]) == ("NOT_READY", "NO_MODEL_IN_USE")
    with db.read() as c:
        assert all(_count(c, t) == 0 for t in NEW_TABLES)


# ================================================================== 2. published path
def test_refresh_publishes_one_run_with_the_model_in_use_and_changes_nothing_of_1_2_14(bq_model):
    _enable()
    fake = _fake_oh()
    _d1_ok()
    base = _counts()
    with db.read() as c:
        fr_before = db.rows(c, "SELECT * FROM forecast_runs ORDER BY id")
        tr_before = db.rows(c, "SELECT * FROM training_runs ORDER BY id")
        settings_before = db.rows(c, "SELECT * FROM app_settings ORDER BY section")
    res = dr.run(D)
    assert (res["status"], res["reason_code"]) == ("PUBLISHED", "DAILY_FORECAST_PUBLISHED"), res
    scope, inc, tr, fcj, mcfg = _model_in_use()
    H = dr.refresh_horizon(ss.get("horizons").enabled, mcfg)
    assert H == 30 and mcfg.forecast_strategy == "RECURSIVE"   # max(7, max([7, 15, 30])); no DIRECT cap
    run = _run_row(res["refresh_run_id"])
    assert run["status"] == "PUBLISHED" and run["trigger"] == "SCHEDULE" and run["job_id"] is None
    assert (run["scope_key"], run["forecast_date"], run["data_as_of"]) == (BQ_SCOPE, "2026-10-28", "2026-10-27")
    assert (run["model_version"], run["training_run_id"]) == (bq_model["model_version"], tr["id"])
    assert run["model_fingerprint"] == fcj["config_fingerprint"] == pipeline.config_fingerprint(fcj["config"])
    assert run["config_version"] == dr.config_version(fcj["config_fingerprint"], 0.2, H) == res["config_version"]
    assert (run["trial_mode"], run["horizon"]) == (1, H)
    # the forecast of the model in use, recomputed independently: panel to D-1, the model's own codes
    booster, sc, fcc = dr._load_model(tr, False)
    panel, window = dr.build_refresh_panel(scope, D, mcfg)
    fc = model.forecast(panel, booster, mcfg, H, sku_codes=sc, fc_codes=fcc)
    S = panel.n_series
    exp = {(fcid, sku): s for s, (sku, fcid) in enumerate(panel.keys)}
    assert S == len(_keys()) == run["n_series"] == res["n_series"]
    vals = _values(res["refresh_run_id"])
    assert len(vals) == S * H == res["rows"]
    methods = {}
    for fcid, sku, h, td, raw, final, method, grp, flags in vals:
        s = exp[(fcid, sku)]
        assert td == str(D + timedelta(days=h - 1))
        assert isinstance(raw, float) and raw == float(fc["yhat"][s, h - 1])          # the model value, unrounded
        assert final == int(dr.published_qty(np.array([raw]), 0.2)[0])
        assert method == fc["methods"][s]
        methods.setdefault((fcid, sku), set()).add(method)
    assert all(len(m) == 1 for m in methods.values()) and len(methods) == S
    n_lgb = sum(1 for m in methods.values() if m == {model.METHOD_LGBM})
    assert (run["n_lightgbm"], run["n_fallback"]) == (n_lgb, S - n_lgb) and res["n_fallback"] == S - n_lgb
    new_key = next(k for k in methods if k[1] == NEW_SKU)
    assert methods[new_key] == {model.FB_NEW} and run["n_fallback"] >= 1          # 1.2.14 rules of a default model
    raws = np.array([v[4] for v in vals])
    assert np.any(np.abs(raws - np.round(raws)) > 1e-6)                            # stored unrounded
    finals = np.array([v[5] for v in vals])
    assert np.array_equal(finals, np.where(np.round(raws, 6) < 0.2, 0, np.ceil(np.round(raws, 6))))
    # nothing written into the 1.2.14 tables, no setting changed
    after = _counts()
    for t in OLD_TABLES:
        assert after[t] == base[t], t
    assert after["settings_history"] == base["settings_history"]
    with db.read() as c:
        assert db.rows(c, "SELECT * FROM forecast_runs ORDER BY id") == fr_before
        assert db.rows(c, "SELECT * FROM training_runs ORDER BY id") == tr_before
        assert db.rows(c, "SELECT * FROM app_settings ORDER BY section") == settings_before
        aud = db.rows(c, "SELECT * FROM audit_log WHERE action='DAILY_FORECAST_PUBLISHED'")
        act = db.one(c, "SELECT COUNT(*) AS n, MIN(date) AS lo, MAX(date) AS hi FROM actual_daily WHERE scope_key=?",
                     (BQ_SCOPE,))
        with_demand = _count(c, "demand_daily", "WHERE scope_key=? AND order_date BETWEEN '2026-10-14' AND '2026-10-27'",
                             (BQ_SCOPE,))
        zero = _count(c, "actual_daily", "WHERE demand = 0")
        zero_rows = _count(c, "demand_daily", "WHERE scope_key=? AND qty = 0 AND order_date BETWEEN '2026-10-14' AND "
                           "'2026-10-27'", (BQ_SCOPE,))
    assert len(aud) == 1 and aud[0]["entity_type"] == "forecast_refresh_run" and aud[0]["entity_id"] == run["id"]
    det_a = json.loads(aud[0]["details_json"])
    assert (det_a["forecast_date"], det_a["rows"], det_a["trial_mode"], det_a["trigger"]) == ("2026-10-28", S * H, True,
                                                                                               "SCHEDULE")
    det = json.loads(run["detail_json"])
    assert det["panel"]["end"] == "2026-10-27" and det["horizon"] == H and det["rounding_threshold"] == 0.2
    assert det["open_hours_read"]["mode"] == "FULL" and det["open_hours_read"]["last_day"] == "2026-10-27"
    assert det["unknown_category_codes"] == 0 and det["group_computed_for"] == "2026-10-28"
    # actual_daily D-14..D-1: every series is open 10 h every day (fake source), a day without a demand row = 0
    assert (act["n"], act["lo"], act["hi"]) == (14 * S, "2026-10-14", "2026-10-27") and res["actual_daily_rows"] == 14 * S
    assert zero == 14 * S - with_demand + zero_rows
    # the read went through a dry run first, with the seller filter, SELECT only, from the configured table
    # fix F2b: one dry run + one query + one completed read per sub-range, oldest first, the last one ending D-1
    assert [cfg.get("dry_run") for sql, cfg in fake.queries] == [True, False] * 7
    assert [(q["start"], q["end"]) for q in _real(fake)] == FULL_SUBS and {q["seller"] for q in _real(fake)} == {"MEDX"}
    for (dsql, dcfg), (sql, cfg) in zip(fake.queries[0::2], fake.queries[1::2]):
        assert dsql == sql and dcfg["params"] == cfg["params"] and "maximum_bytes_billed" in cfg
        assert f"FROM `{OH_TABLE}`" in sql and not any(w in sql.upper() for w in ("INSERT ", "UPDATE ", "DELETE ",
                                                                                  "MERGE "))
    with db.read() as c:
        reads = [tuple(r) for r in c.execute("SELECT range_start, range_end FROM aux_source_reads ORDER BY id")]
    assert reads == [(str(a), str(b)) for a, b in FULL_SUBS]
    # 9. a rerun with another threshold and trial mode OFF: a NEW run (the first kept), same raw values
    _enable(rounding_threshold=0.5)
    ss.update("daily_forecast", {"trial_mode": False})
    res2 = dr.run(D, trigger="MANUAL")                        # fix F1: only a MANUAL rerun publishes again
    run2 = _run_row(res2["refresh_run_id"])
    assert run2["trigger"] == "MANUAL"
    assert res2["status"] == "PUBLISHED" and run2["id"] != run["id"] and _run_row(run["id"])["status"] == "PUBLISHED"
    assert run2["trial_mode"] == 0 and run2["config_version"] == dr.config_version(fcj["config_fingerprint"], 0.5, H)
    assert run2["config_version"] != run["config_version"]
    v2 = _values(run2["id"])
    assert [v[4] for v in v2] == [v[4] for v in vals]
    assert [v[5] for v in v2] == dr.published_qty(np.array([v[4] for v in v2]), 0.5).tolist()


# ================================================================== 3 + 9. leakage, rerun of the same day
def test_refresh_reads_only_data_up_to_d_minus_1_and_a_rerun_is_a_new_current_run(bq_model):
    from app.ml import accuracy_report
    _enable()
    _fake_oh()
    _d1_ok()
    r1 = dr.run(D)
    assert r1["status"] == "PUBLISHED", r1
    v1 = _values(r1["refresh_run_id"])
    with db.read() as c:
        act1 = [tuple(r) for r in c.execute("SELECT date, fc_code, sku_code, demand, total_open_hours FROM actual_daily "
                                            "ORDER BY 1, 2, 3")]
    with db.tx() as c:          # rows of D and later appear (demand and open hours); the groups are computed again
        for fc, sku in _keys():
            for day in (D, D + timedelta(days=1)):
                _demand_row(c, day, sku, fc, 999)
                _oh_row(c, fc, sku, day, 0.0)
        c.execute("UPDATE demand_daily SET qty = 555 WHERE scope_key=? AND order_date=?", (BQ_SCOPE, str(D)))
        c.execute("DELETE FROM sku_group")
    r2 = dr.run(D, trigger="MANUAL")                          # fix F1: only a MANUAL rerun publishes again
    assert r2["status"] == "PUBLISHED" and r2["refresh_run_id"] != r1["refresh_run_id"]
    assert json.loads(_run_row(r2["refresh_run_id"])["detail_json"])["group_computed_now"] is True
    assert _values(r2["refresh_run_id"]) == v1                # byte-identical: lgb_raw, final, method, group, flags
    sk = dr.run(D)                    # fix F1: a SCHEDULE rerun of a published day writes nothing (runs checked below)
    assert (sk["status"], sk["reason_code"], sk["refresh_run_id"]) == ("SKIPPED", "ALREADY_PUBLISHED",
                                                                       r2["refresh_run_id"])   # the latest (rowid tie)
    with db.read() as c:
        act2 = [tuple(r) for r in c.execute("SELECT date, fc_code, sku_code, demand, total_open_hours FROM actual_daily "
                                            "ORDER BY 1, 2, 3")]
        runs = db.rows(c, "SELECT id, created_at FROM forecast_refresh_runs ORDER BY rowid")
        latest = db.one(c, accuracy_report._LATEST, (BQ_SCOPE, str(D)))
        n = dict(c.execute("SELECT run_id, COUNT(*) FROM forecast_refresh_values GROUP BY run_id").fetchall())
    assert act2 == act1
    # both runs kept; same created_at (frozen clock, one-second resolution): the later one is the current one
    assert [r["id"] for r in runs] == [r1["refresh_run_id"], r2["refresh_run_id"]] and runs[0]["created_at"] == \
        runs[1]["created_at"]
    assert latest["id"] == r2["refresh_run_id"]
    S, H = r1["n_series"], r1["horizon"]
    assert n == {r1["refresh_run_id"]: S * 7, r2["refresh_run_id"]: S * H}   # the superseded run keeps days 1-7
    # negative control: a change of D-1 changes the numbers
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET qty = qty * 5 + 50 WHERE scope_key=? AND order_date=?",
                  (BQ_SCOPE, str(D - timedelta(days=1))))
    r3 = dr.run(D, trigger="MANUAL")
    v3 = _values(r3["refresh_run_id"])
    assert len(v3) == len(v1) and [v[4] for v in v3] != [v[4] for v in v1]


# ================================================================== 4. fallback follows the model in use
def test_fallback_rules_follow_the_stored_configuration_of_the_model_in_use(fast_model, monkeypatch):
    res = train_bq_model(monkeypatch, fallback_enabled=False)
    ss.update("model", {"fallback_enabled": True})            # today's setting is never used by the refresh
    _enable()
    _fake_oh()
    _d1_ok()
    scope, inc, tr, fcj, mcfg = _model_in_use()
    assert fcj["config"]["fallback_enabled"] is False and mcfg.fallback_enabled is False
    r1 = dr.run(D)
    assert r1["status"] == "PUBLISHED", r1
    run1 = _run_row(r1["refresh_run_id"])
    assert (run1["n_fallback"], run1["n_lightgbm"]) == (0, run1["n_series"])
    assert {v[6] for v in _values(run1["id"])} == {model.METHOD_LGBM}           # NEW_SKU included
    # the same model with a 1.2.14 configuration (no 1.3.1 key stored): the rules INACTIVE / NEW_SERIES / INTERMITTENT
    old = {k: v for k, v in fcj["config"].items() if k not in ("horizon_weight_short", "horizon_weight_cutoff",
                                                               "feature_sku_code", "fallback_enabled", "feature_table")}
    with db.tx() as c:
        c.execute("UPDATE training_runs SET feature_config_json=? WHERE id=?",
                  (json.dumps({**fcj, "config": old}), tr["id"]))
    r2 = dr.run(D, trigger="MANUAL")                          # fix F1: a second run of the day is MANUAL
    run2 = _run_row(r2["refresh_run_id"])
    cfg14 = ss.ModelSettings.model_validate(old)
    panel, _w = dr.build_refresh_panel(scope, D, cfg14)
    exp = model.classification_details(panel, cfg14)["methods"]
    by_key = {(fcid, sku): str(exp[s]) for s, (sku, fcid) in enumerate(panel.keys)}
    got = {(v[0], v[1]): v[6] for v in _values(run2["id"])}
    assert got == by_key and got[next(k for k in got if k[1] == NEW_SKU)] == model.FB_NEW
    n_fb = sum(1 for m in got.values() if m != model.METHOD_LGBM)
    assert run2["n_fallback"] == n_fb >= 1 and run2["n_lightgbm"] == run2["n_series"] - n_fb


# ================================================================== 5. groups A / B / C
def test_groups_are_computed_on_the_first_refresh_of_the_month_reused_deferred_and_missing(bq_model):
    """r1: the source open hours stop at D-4 -> groups deferred, every series GROUP_MISSING. r2: the source reaches D-1
    (incremental read) -> groups computed from open_hours_daily + demand_daily, stored on the values; a series that the
    source never returns (and that the model never saw: CODE_UNKNOWN) has no group. r3: same month, reused."""
    _enable()
    with db.tx() as c:                                        # a series added after the training, absent from the source
        fc0 = c.execute("SELECT MIN(fc_id) FROM demand_daily WHERE scope_key=?", (BQ_SCOPE,)).fetchone()[0]
        for i in range(1, 41):
            _demand_row(c, D - timedelta(days=i), "SKU-LATE", fc0, 30 + i % 3, hours=8.0)
    late = (fc0, "SKU-LATE")
    known = [k for k in _keys() if k != late]
    fake = _fake_oh(keys=known, oh_end=D - timedelta(days=4))
    _d1_ok()
    r1 = dr.run(D)
    assert r1["status"] == "PUBLISHED", r1
    det1 = json.loads(_run_row(r1["refresh_run_id"])["detail_json"])
    assert det1["groups_deferred"] == sku_group.DEFERRED_OPEN_HOURS_LAG and det1["group_computed_for"] is None
    assert det1["open_hours_read"]["last_day"] == "2026-10-24" and det1["open_hours_last_day"] == "2026-10-24"
    assert _run_row(r1["refresh_run_id"])["group_computed_for"] is None
    v1 = _values(r1["refresh_run_id"])
    assert all(v[7] is None and "GROUP_MISSING" in v[8] for v in v1)
    with db.read() as c:
        assert _count(c, "sku_group") == 0
    oh1 = _real(fake)
    assert det1["open_hours_read"]["mode"] == "FULL" and [(q["start"], q["end"]) for q in oh1] == FULL_SUBS   # to D-1
    fake = _fake_oh(keys=known)
    r2 = dr.run(D, trigger="MANUAL")                          # fix F1: a second run of the day is MANUAL
    run2 = _run_row(r2["refresh_run_id"])
    det2 = json.loads(run2["detail_json"])
    # incremental: (last day of the last completed read 24/10) - 3 days .. D-1
    assert [(q["start"], q["end"]) for q in _real(fake)] == [(date(2026, 10, 21), date(2026, 10, 27))]
    assert det2["open_hours_read"]["mode"] == "INCREMENTAL" and "groups_deferred" not in det2
    assert det2["group_computed_for"] == run2["group_computed_for"] == "2026-10-28" and det2["group_computed_now"] is True
    _, _, _, _, mcfg = _model_in_use()
    with db.read() as c:
        window = dr.data_window(c, today=D, scope=resolve_scope(c))
        rows = {(r["fc_code"], r["sku_code"]): r for r in db.rows(c, "SELECT * FROM sku_group")}
        sums = {(r[0], r[1]): r[2] for r in c.execute(
            "SELECT fc_id, sku_id, SUM(qty) FROM demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ? "
            "GROUP BY 1, 2", (BQ_SCOPE, rows[known[0]]["window_start"], "2026-10-27"))}
    ws = max(date(2026, 7, 30), date.fromisoformat(window["start"]))
    assert set(rows) == set(known) and late not in rows
    for k, r in rows.items():
        assert (r["scope_key"], r["computed_for"], r["window_start"], r["window_end"]) == (BQ_SCOPE, "2026-10-28",
                                                                                         str(ws), "2026-10-27")
        assert r["n_open_days"] == (date(2026, 10, 27) - ws).days + 1                  # every day open (fake 10 h)
        assert r["qty"] == pytest.approx(sums.get(k, 0.0))                             # open day without demand = 0
        assert r["group_code"] == sku_group.classify([r["n_open_days"]], [r["avg_per_open_day"]], [r["zero_share"]])[0]
        assert r["rule_version"] == sku_group.RULE_VERSION
    new_key = next(k for k in known if k[1] == NEW_SKU)
    assert rows[new_key]["group_code"] == sku_group.GROUP_C                            # 10 sold days out of 90
    v2 = _values(run2["id"])
    for fcid, sku, h, td, raw, final, method, grp, flags in v2:
        if (fcid, sku) == late:
            assert grp is None and flags == "CODE_UNKNOWN,GROUP_MISSING"
        else:
            assert grp == rows[(fcid, sku)]["group_code"] and flags is None
    assert det2["groups"] == {**{g: sum(1 for r in rows.values() if r["group_code"] == g)
                                 for g in {r["group_code"] for r in rows.values()}}, "None": 1}
    assert det2["flags"] == {"CODE_UNKNOWN": 1, "GROUP_MISSING": 1} and det2["unknown_category_codes"] == 1
    # 7. the late series: demand rows without open hours in open_hours_daily -> NULL hours in actual_daily
    with db.read() as c:
        late_act = db.rows(c, "SELECT demand, total_open_hours FROM actual_daily WHERE sku_code='SKU-LATE'")
    assert len(late_act) == 14 and all(r["total_open_hours"] is None and r["demand"] > 0 for r in late_act)
    r3 = dr.run(D, trigger="MANUAL")                          # same month: reused, nothing stored again
    det3 = json.loads(_run_row(r3["refresh_run_id"])["detail_json"])
    assert det3["group_computed_for"] == "2026-10-28" and det3["group_computed_now"] is False
    with db.read() as c:
        assert _count(c, "sku_group") == len(rows)
    assert [v[7] for v in _values(r3["refresh_run_id"])] == [v[7] for v in v2]
    g = sku_group.ensure_groups(date(2026, 10, 30), BQ_SCOPE)                          # later day, same month
    assert (g["computed"], g["computed_for"]) == (False, "2026-10-28")
    # a new month while the stored open hours end at 27/10 (< D-2 = 31/10): deferred, October's groups stay in use
    g = sku_group.ensure_groups(date(2026, 11, 2), BQ_SCOPE)
    assert (g["deferred"], g["computed"], g["computed_for"]) == (sku_group.DEFERRED_OPEN_HOURS_LAG, False, "2026-10-28")
    assert g["groups"] == {k: r["group_code"] for k, r in rows.items()}
    with db.read() as c:
        assert _count(c, "sku_group") == len(rows)


def test_groups_count_open_days_only_and_never_mix_another_source():
    _freeze(NOW)
    with db.tx() as c:
        day = date(2026, 7, 30)
        while day <= date(2026, 10, 27):
            closed = day.day % 10 == 0                                        # 9 closed days (hours 0) in the window
            _oh_row(c, "HN", "FAST", day, 0.0 if closed else 10.0)
            _oh_row(c, "HN", "SLOW", day, 10.0)
            _oh_row(c, "HN", "SLOW", day, 0.0, src=("p.d.other_openhours", "MEDX"))     # another table: never read
            _oh_row(c, "HN", "SLOW", day, 0.0, src=(OH_TABLE, "OTHER"))                 # another seller: never read
            _demand_row(c, day, "FAST", "HN", 30)                                     # also on the closed days
            if day.day == 1:
                _demand_row(c, day, "SLOW", "HN", 2)
            day += timedelta(days=1)
        _oh_row(c, "HN", "NULLH", "2026-10-20", None)                           # unknown hours: not an open day
    g = sku_group.ensure_groups(D, BQ_SCOPE)
    assert g["computed"] and g["groups"] == {("HN", "FAST"): "A", ("HN", "SLOW"): "C"}
    with db.read() as c:
        fast = db.one(c, "SELECT * FROM sku_group WHERE sku_code='FAST'")
        slow = db.one(c, "SELECT * FROM sku_group WHERE sku_code='SLOW'")
    assert (fast["n_open_days"], fast["qty"], fast["zero_days"]) == (81, 81 * 30, 0)   # closed days excluded
    assert (slow["n_open_days"], slow["zero_days"]) == (90, 87)                         # open, no demand row = 0
    assert _count_scope_groups("BIGQUERY:p.d.other") == 0


def _count_scope_groups(scope):
    with db.read() as c:
        return _count(c, "sku_group", "WHERE scope_key=?", (scope,))


# ================================================================== 6. open hours read (fake BigQuery)
def test_open_hours_full_then_incremental_and_skipped_while_the_source_is_unchanged():
    _freeze(NOW)
    keys = [("HN", "A"), ("HCM", "B")]
    fake = _fake_oh(keys=keys)
    first = dr.sync_open_hours(D, "2026-01-01")
    assert (first["mode"], first["start"], first["end"]) == ("FULL", "2026-07-27", "2026-10-27")
    assert first["rows"] == 93 * 2 and first["source_modified"] is None and first["last_day"] == "2026-10-27"
    with db.read() as c:
        reads = db.rows(c, "SELECT * FROM aux_source_reads ORDER BY id")
    assert [(r["kind"], r["source_table"], r["seller_code"], r["range_start"], r["range_end"], r["n_rows"], r["last_day"])
            for r in reads] == [("OPEN_HOURS", OH_TABLE, "MEDX", str(a), str(b), 2 * ((b - a).days + 1), str(b))
                                for a, b in FULL_SUBS]           # fix F2b: one completed read per sub-range
    assert first["reads"] == 7
    again = dr.sync_open_hours(D, "2026-01-01")                       # modified unknown: read again, incremental
    assert (again["mode"], again["start"], again["end"]) == ("INCREMENTAL", "2026-10-24", "2026-10-27")
    assert "skipped" not in again and again["rows"] == 4 * 2
    fake.modified = datetime(2026, 10, 28, 4, 10, tzinfo=VN_TZ)       # 21:10 UTC of 27/10
    third = dr.sync_open_hours(D, "2026-01-01")
    assert third["source_modified"] == "2026-10-27T21:10:00+00:00" and third["rows"] == 8
    n = len(fake.queries)
    fourth = dr.sync_open_hours(D, "2026-01-01")                      # unchanged since the last completed read
    assert fourth["skipped"] == dr.SOURCE_NOT_REFRESHED == "OPEN_HOURS_SOURCE_NOT_REFRESHED"
    assert len(fake.queries) == n and fourth["rows"] == 0                # no query at all (not even a dry run)
    fake.modified = datetime(2026, 10, 28, 5, 0, tzinfo=VN_TZ)        # refreshed again: read
    fifth = dr.sync_open_hours(D, "2026-01-01")
    assert "skipped" not in fifth and fifth["rows"] == 8 and len(fake.queries) == n + 2
    with db.read() as c:
        assert _count(c, "aux_source_reads") == 7 + 3            # 7 FULL sub-ranges + 3 one-range incremental reads
        assert _count(c, "open_hours_daily") == 186
    # the next day: incremental from the last day read (27/10) - 3; a changed table / seller starts FULL again
    assert dr.open_hours_range(D + timedelta(days=1), "2026-01-01")[2] == "INCREMENTAL"
    other = ss.DailyForecastSettings(seller_code="OTHER")
    assert dr.open_hours_range(D, "2026-01-01", other) == (date(2026, 7, 27), date(2026, 10, 27), "FULL")


def test_open_hours_unchanged_source_is_still_read_when_no_completed_read_reaches_the_window():
    _freeze(NOW)
    fake = _fake_oh(keys=[("HN", "A")], modified=datetime(2026, 7, 1, 8, 0, tzinfo=VN_TZ))
    with db.tx() as c:          # an old completed read (before the group window) that saw the same modified time
        c.execute("INSERT INTO aux_source_reads(source_table, seller_code, kind, range_start, range_end, n_rows, "
                  "last_day, source_modified, completed_at) VALUES (?, 'MEDX', 'OPEN_HOURS', '2026-04-01', '2026-07-01', "
                  "1, '2026-07-01', '2026-07-01T01:00:00+00:00', '2026-07-02T00:00:00+00:00')", (OH_TABLE,))
    out = dr.sync_open_hours(D, "2026-01-01")
    assert out["mode"] == "FULL" and "skipped" not in out and out["rows"] == 93
    assert [(q["start"], q["end"]) for q in _real(fake)] == FULL_SUBS                 # fix F2b: sub-ranges


def test_open_hours_read_never_replaces_a_stored_value_with_null_and_counts_it_kept():
    _freeze(NOW)
    first = [{"fc_code": "HN", "sku_code": s, "open_date": "2026-10-26", "total_open_hours": h, "n_items": 1}
             for s, h in (("A", 10.0), ("B", None), ("C", 8.0))]
    again = [{"fc_code": "HN", "sku_code": s, "open_date": "2026-10-26", "total_open_hours": h, "n_items": 2}
             for s, h in (("A", None), ("B", 6.0), ("C", 0.0))]
    connector.set_client_factory(FakeBQ(responses={"daily_open_hours": first}))
    assert aux_sources.fetch_open_hours("2026-10-26", "2026-10-26")["kept_on_conflict"] == 0
    connector.set_client_factory(FakeBQ(responses={"daily_open_hours": again}))
    assert aux_sources.fetch_open_hours("2026-10-26", "2026-10-26")["kept_on_conflict"] == 1
    with db.read() as c:
        oh = {r[0]: (r[1], r[2]) for r in c.execute("SELECT sku_code, total_open_hours, n_items FROM open_hours_daily")}
    # A kept (NULL read); NULL -> value and value -> 0 (a real zero: closed) are changes
    assert oh == {"A": (10.0, 1), "B": (6.0, 2), "C": (0.0, 2)}


def test_open_hours_watermark_is_written_only_after_the_last_chunk(monkeypatch):
    _freeze(NOW)
    rows = [{"fc_code": "HN", "sku_code": "A", "open_date": f"2026-10-{d}", "total_open_hours": 10.0, "n_items": 1}
            for d in (21, 22, 23, 24, 25)]
    monkeypatch.setattr(aux_sources, "UPSERT_CHUNK_ROWS", 2)
    seen = []
    real = aux_sources._record_read

    def record(c, *a, **k):
        seen.append(c.execute("SELECT COUNT(*) FROM open_hours_daily").fetchone()[0])
        return real(c, *a, **k)
    monkeypatch.setattr(aux_sources, "_record_read", record)
    connector.set_client_factory(FakeBQ(responses={"daily_open_hours": rows}))
    out = aux_sources.fetch_open_hours("2026-10-21", "2026-10-25")
    assert seen == [5] and out["last_day"] == "2026-10-25"          # every chunk (2 + 2 + 1) committed before
    # a read that fails in its second chunk: the first chunk stays, no watermark, the next range is FULL again
    bad = rows[:2] + [{"fc_code": "HN", "sku_code": "B", "open_date": "2026-10-26", "total_open_hours": "x", "n_items": 1}]
    connector.set_client_factory(FakeBQ(responses={"daily_open_hours": [{**r, "sku_code": "B"} for r in bad]}))
    with db.tx() as c:
        c.execute("INSERT INTO aux_source_reads(source_table, seller_code, kind, range_start, range_end, n_rows, "
                  "last_day, completed_at) VALUES ('p.d.t', 'MEDX', 'OPEN_HOURS', '2026-10-01', '2026-10-27', 1, "
                  "'2026-10-27', '2026-10-27T00:00:00+00:00')")             # another table: never this watermark
    with pytest.raises(ValueError):
        aux_sources.fetch_open_hours("2026-07-27", "2026-10-27")
    with db.read() as c:
        assert _count(c, "open_hours_daily", "WHERE sku_code='B'") == 2
        assert _count(c, "aux_source_reads", "WHERE source_table=?", (OH_TABLE,)) == 1
    # the failed read recorded nothing: the watermark is still the first read's (25/10), another table's never counts
    assert dr.open_hours_range(D)[2] == "INCREMENTAL" and dr.open_hours_range(D)[0] == date(2026, 10, 22)


def test_open_hours_read_error_alerts_once_per_forecast_day():
    _freeze(NOW)
    connector.set_client_factory(FakeBQ(errors={"daily_open_hours": RuntimeError("boom")}))
    a = dr.sync_open_hours(D, "2026-01-01")
    b = dr.sync_open_hours(D, "2026-01-01")
    c2 = dr.sync_open_hours(D + timedelta(days=1), "2026-01-01")     # another forecast day: its own alert
    assert all("boom" in x["error"] and x["rows"] == 0 for x in (a, b, c2))
    with db.read() as c:
        alerts = db.rows(c, "SELECT level, entity_type, entity_id FROM alerts WHERE code='OPEN_HOURS_READ_FAILED' "
                            "ORDER BY id")
        assert _count(c, "aux_source_reads") == 0
    assert alerts == [{"level": "WARNING", "entity_type": "forecast_refresh_date", "entity_id": "2026-10-28"},
                      {"level": "WARNING", "entity_type": "forecast_refresh_date", "entity_id": "2026-10-29"}]


def test_a_failed_open_hours_read_and_a_failed_actual_step_keep_the_run_published(bq_model, monkeypatch):
    from app.jobs import runner
    _enable()
    connector.set_client_factory(FakeBQ(errors={"daily_open_hours": RuntimeError("boom")}))
    _d1_ok()
    r1 = dr.run(D)
    assert r1["status"] == "PUBLISHED", r1
    det = json.loads(_run_row(r1["refresh_run_id"])["detail_json"])
    assert "boom" in det["open_hours_read"]["error"] and "boom" in r1["open_hours"]["error"]
    assert det["groups_deferred"] == sku_group.DEFERRED_OPEN_HOURS_LAG             # nothing stored to group on

    def boom(*a, **k):
        raise RuntimeError("disk I/O error")
    monkeypatch.setattr(dr, "refresh_actual_daily", boom)
    r2 = dr.run(D, trigger="MANUAL")                                               # second attempt of the day
    assert r2["status"] == "PUBLISHED" and r2["actual_daily_error"] == "RuntimeError: disk I/O error"
    assert r2["actual_daily_rows"] is None and r2["retention"] is not None
    row = runner.run_refresh_now(str(D))                                           # the job is not FAILED either
    assert (row["status"], row["reason_code"]) == ("SUCCEEDED", "DAILY_FORECAST_PUBLISHED")
    assert "actual_daily_error" in json.loads(row["result_json"])["result"]
    with db.read() as c:
        oh_alerts = db.rows(c, "SELECT level FROM alerts WHERE code='OPEN_HOURS_READ_FAILED'")
        act_alerts = db.rows(c, "SELECT level, entity_type, entity_id FROM alerts WHERE code='DAILY_ACTUAL_FAILED' "
                                "ORDER BY id")
        runs = db.rows(c, "SELECT id, trigger, job_id FROM forecast_refresh_runs ORDER BY rowid")
    assert oh_alerts == [{"level": "WARNING"}]                                     # ONE per day after 3 attempts
    assert [a["entity_id"] for a in act_alerts] == [r2["refresh_run_id"], runs[2]["id"]]
    assert all(a["level"] == "WARNING" and a["entity_type"] == "forecast_refresh_run" for a in act_alerts)
    assert (runs[2]["trigger"], runs[2]["job_id"]) == ("MANUAL", row["id"])


# ================================================================== 7. actual_daily
def test_actual_daily_open_day_zero_closed_day_none_and_null_hours():
    _freeze(NOW)
    with db.tx() as c:
        for day, hours in (("2026-10-20", 10), ("2026-10-21", 8), ("2026-10-22", None), ("2026-10-23", 0),
                           ("2026-10-24", 6), ("2026-10-25", 0), ("2026-10-19", 9), ("2026-10-26", 7)):
            _oh_row(c, "HN", "A", day, hours)
        _oh_row(c, "HN", "A", "2026-10-23", 12, src=(OH_TABLE, "OTHER"))         # another seller: never used
        _oh_row(c, "HN", "A", "2026-10-23", 12, src=("p.d.other", "MEDX"))       # another table: never used
        for day, qty in (("2026-10-20", 5), ("2026-10-22", 3), ("2026-10-24", 0), ("2026-10-25", 4)):
            _demand_row(c, day, "A", "HN", qty)
        _demand_row(c, "2026-10-23", "Z", "HN", 2)                               # no open-hours row at all
        _demand_row(c, "2026-10-21", "A", "HN", 99, scope="BIGQUERY:p.d.other")  # another scope
    n = dr.refresh_actual_daily(BQ_SCOPE, date(2026, 10, 20), date(2026, 10, 25))
    with db.read() as c:
        rows = [tuple(r) for r in c.execute("SELECT scope_key, date, sku_code, demand, total_open_hours FROM actual_daily "
                                            "ORDER BY date, sku_code")]
    # 20 demand; 21 open but the scope has no demand row at all that day (fix F4: a data gap -> no row, never 0);
    # 22 unknown hours keeps its demand with NULL hours; 23 closed without demand: no row (Z: demand without open hours
    # -> NULL); 24 demand row 0 = 0; 25 closed with demand keeps it; 19 and 26 are outside the range
    assert rows == [(BQ_SCOPE, "2026-10-20", "A", 5.0, 10.0),
                    (BQ_SCOPE, "2026-10-22", "A", 3.0, None), (BQ_SCOPE, "2026-10-23", "Z", 2.0, None),
                    (BQ_SCOPE, "2026-10-24", "A", 0.0, 6.0), (BQ_SCOPE, "2026-10-25", "A", 4.0, 0.0)]
    assert n == 5
    with db.tx() as c:          # late data: the scope now has a demand row on 21/10 (Z) and a corrected 20/10
        c.execute("UPDATE demand_daily SET qty = 7 WHERE scope_key=? AND order_date='2026-10-20'", (BQ_SCOPE,))
        _demand_row(c, "2026-10-21", "Z", "HN", 1)
        c.executemany("INSERT INTO actual_daily(scope_key, date, fc_code, sku_code, demand, updated_at) VALUES "
                      "(?, ?, 'HN', 'A', 9, 'x')", [(BQ_SCOPE, "2026-10-23"), (BQ_SCOPE, "2026-10-19")])
    # fix F4: the range is replaced - 21/10 A open without demand = 0 (the day is no gap any more); the stale 23/10 A
    # row (closed, no demand) disappears; 19/10 (outside the range) is kept
    assert dr.refresh_actual_daily(BQ_SCOPE, date(2026, 10, 20), date(2026, 10, 25)) == 7
    with db.read() as c:
        rows = [tuple(r) for r in c.execute("SELECT date, sku_code, demand, total_open_hours FROM actual_daily "
                                            "ORDER BY date, sku_code")]
    assert rows == [("2026-10-19", "A", 9.0, None), ("2026-10-20", "A", 7.0, 10.0), ("2026-10-21", "A", 0.0, 8.0),
                    ("2026-10-21", "Z", 1.0, None), ("2026-10-22", "A", 3.0, None), ("2026-10-23", "Z", 2.0, None),
                    ("2026-10-24", "A", 0.0, 6.0), ("2026-10-25", "A", 4.0, 0.0)]
    assert dr.refresh_actual_daily("BIGQUERY:p.d.empty", date(2026, 10, 1), date(2026, 10, 2)) == 0


# ================================================================== 8. retention
def _ins_run(c, rid, fdate, h=15, created="2026-10-01T00:00:00+00:00", scope=BQ_SCOPE):
    c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, config_version, "
              "trial_mode, horizon, n_series, n_lightgbm, n_fallback, created_at) VALUES (?,?,?,?, 'PUBLISHED', 'cv', "
              "1, ?, 1, 1, 0, ?)", (rid, scope, fdate, fdate, h, created))
    c.executemany("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, lgb_raw, "
                  "final_qty, method) VALUES (?,?,?,?,?,?,?,?)",
                  [(rid, i, fdate, "F1", "S1", 1.0, 1, "LIGHTGBM") for i in range(1, h + 1)])


def test_retention_unit_ties_and_other_scopes():
    with db.tx() as c:
        _ins_run(c, "R-A", "2026-10-28", created="2026-10-27T23:30:00+00:00")
        _ins_run(c, "R-B", "2026-10-28", created="2026-10-27T23:30:00+00:00")    # same second: inserted later = latest
        _ins_run(c, "R-EARLIER-DAY-LATER-CLOCK", "2026-10-27", created="2026-10-28T01:00:00+00:00")
        _ins_run(c, "R-OTHER", "2026-01-01", scope="BIGQUERY:p.d.other")        # another scope: never touched
        c.executemany("INSERT INTO actual_daily(scope_key, date, fc_code, sku_code, demand, updated_at) VALUES "
                      "(?, ?, 'F1', 'S1', 1, 'x')", [(BQ_SCOPE, "2026-10-13"), (BQ_SCOPE, "2026-10-14"),
                                                     ("BIGQUERY:p.d.other", "2026-01-01")])
    out = dr.apply_retention(BQ_SCOPE, D, 14)
    assert out == {"cutoff": "2026-10-14", "superseded_values": 16, "old_values": 0, "actual_rows": 1}
    with db.read() as c:
        n = dict(c.execute("SELECT run_id, COUNT(*) FROM forecast_refresh_values GROUP BY run_id").fetchall())
        assert [r[0] for r in c.execute("SELECT date FROM actual_daily WHERE scope_key=?", (BQ_SCOPE,))] == ["2026-10-14"]
        assert _count(c, "actual_daily", "WHERE scope_key='BIGQUERY:p.d.other'") == 1
        assert _count(c, "forecast_refresh_runs") == 4
    assert n == {"R-A": 7, "R-B": 15, "R-EARLIER-DAY-LATER-CLOCK": 7, "R-OTHER": 15}
    assert dr.apply_retention(BQ_SCOPE, D, 14) == {"cutoff": "2026-10-14", "superseded_values": 0, "old_values": 0,
                                                   "actual_rows": 0}                       # idempotent


def test_retention_over_several_days_keeps_the_run_records(bq_model):
    _enable(log_retention_days=14)
    _fake_oh()
    days = [D - timedelta(days=15), D - timedelta(days=2), D - timedelta(days=1), D]   # 13/10, 26/10, 27/10, 28/10
    out = {}
    for d in days:
        _freeze(datetime(d.year, d.month, d.day, 6, 30, tzinfo=VN_TZ))
        _d1_ok(day=d)
        out[d] = dr.run(d)
        assert out[d]["status"] == "PUBLISHED", (d, out[d])
        if d == days[1]:
            with db.read() as c:            # cutoff 12/10: the 13/10 run is only superseded (days 1-7 kept)
                assert _count(c, "forecast_refresh_values", "WHERE run_id=?", (out[days[0]]["refresh_run_id"],)) == \
                    out[days[0]]["n_series"] * 7
    S, H = out[D]["n_series"], out[D]["horizon"]
    ids = [out[d]["refresh_run_id"] for d in days]
    with db.read() as c:
        n = dict(c.execute("SELECT run_id, COUNT(*) FROM forecast_refresh_values GROUP BY run_id").fetchall())
        hmax = dict(c.execute("SELECT run_id, MAX(horizon) FROM forecast_refresh_values GROUP BY run_id").fetchall())
        act = db.one(c, "SELECT MIN(date) AS lo, MAX(date) AS hi, COUNT(DISTINCT date) AS n FROM actual_daily")
        runs = [r[0] for r in c.execute("SELECT forecast_date FROM forecast_refresh_runs ORDER BY forecast_date")]
    assert n == {ids[1]: S * 7, ids[2]: S * 7, ids[3]: S * H}                 # 13/10 < 28/10 - 14: every value gone
    assert hmax == {ids[1]: 7, ids[2]: 7, ids[3]: H}
    assert (act["lo"], act["hi"], act["n"]) == ("2026-10-14", "2026-10-27", 14)
    assert runs == [str(d) for d in days]                                     # every run record kept
    ret = out[D]["retention"]
    S0 = out[days[0]]["n_series"]                # the series with a demand row up to 12/10 (NEW_SKU starts 18/10)
    with db.read() as c:
        assert S0 == c.execute("SELECT COUNT(*) FROM (SELECT DISTINCT fc_id, sku_id FROM demand_daily WHERE scope_key=? "
                               "AND order_date <= '2026-10-12')", (BQ_SCOPE,)).fetchone()[0] < S
    assert ret["cutoff"] == "2026-10-14" and ret["old_values"] == S0 * 7 and ret["superseded_values"] == S * (H - 7)
    with db.tx() as c:                                                        # the run records stay immutable
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            c.execute("DELETE FROM forecast_refresh_runs WHERE id=?", (ids[0],))
    with db.tx() as c:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            c.execute("UPDATE forecast_refresh_runs SET status='PUBLISHED' WHERE id=?", (ids[3],))
    with db.tx() as c:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            c.execute("UPDATE forecast_refresh_values SET final_qty = final_qty + 1 WHERE run_id=?", (ids[3],))
    with db.read() as c:
        assert _count(c, "forecast_refresh_runs") == 4
