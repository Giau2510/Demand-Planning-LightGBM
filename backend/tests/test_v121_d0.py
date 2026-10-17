"""1.2.1: the D-0 feed has its own mapping and is validated by a real BigQuery round trip (here: the fake client), it
reads only TODAY (Vietnam), never writes history, never feeds training; the daily training follows today's D-1 success
(scheduled or manual). Kind of evidence: unit / integration with a FAKE BigQuery client (no Google call). The real
BigQuery checks of the same SQL are in test_v121_d0_real_bq.py (opt-in, DF_REAL_BQ=1)."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import db, timeutil
from app import settings_service as ss
from app.bq import connector, d0_feed, source_tables, sql_sources
from app.jobs import flows, runner
from app.jobs.scheduler import plan
from app.messages import AppError

from fake_bq import FakeBQ, Forbidden
from test_v116 import LAYOUT, _bq_ready, _d0_rows

D0 = "lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0"
# the real D-0 table (BigQuery metadata 17/10/2026): 12 columns, a subset of the 17 D-1 columns
REAL_D0 = [("fc_code", "STRING"), ("created_date", "DATE"), ("so_code", "STRING"), ("order_status", "STRING"),
           ("product_id", "INTEGER"), ("sku_code", "STRING"), ("item_code", "STRING"), ("seller_code", "STRING"),
           ("sku_system_status", "STRING"), ("demand_quantity", "INTEGER"), ("outbound_quantity", "INTEGER"),
           ("sales_price", "FLOAT")]
D0_SQL = f"SELECT * FROM `{D0}` WHERE created_date = CURRENT_DATE('Asia/Ho_Chi_Minh')"
BadRequest = type("BadRequest", (Exception,), {})
NotFound = type("NotFound", (Exception,), {})


def _prod(fake=None):
    fake = _bq_ready(fake or FakeBQ(schema=LAYOUT, tables={D0: REAL_D0}))
    # the D-1 mapping of production since 17/10/2026: price + reference columns the D-0 output may not have
    fm = {k: v.model_dump() for k, v in ss.get("bigquery").field_mapping.items()}
    fm["unit_price"] = {"column": "sales_price", "usage": "OPTIONAL"}
    ss.update("bigquery", {"field_mapping": fm, "production_enabled": True})
    ss.update("general", {"active_source": "BIGQUERY"})
    return fake


def _save(client, sql=D0_SQL):
    r = client.post("/api/sql-sources/d0/versions", json={"sql": sql, "note": "D-0 table, today"})
    assert r.status_code == 200, r.text
    return r.json()["saved_version_id"]


def _validate(client, fake, vid, dry=REAL_D0, rows=None):
    fake.dry_schema = dry
    fake.responses["d0_check"] = rows if rows is not None else _d0_rows(timeutil.today_vn())
    return client.post(f"/api/sql-sources/d0/versions/{vid}/validate").json()


def _codes(r):
    return [x["code"] for x in r["reasons"]]


# ------------------------------------------------------------------ 1. valid SQL, confirmed by BigQuery
def test_valid_d0_sql_is_active_only_after_dry_run_mapping_check_and_execution(client):
    fake = _prod()
    vid = _save(client)
    view = client.get("/api/sql-sources").json()["d0"]
    assert next(v for v in view["versions"] if v["id"] == vid)["validation"] is None    # saving never validates
    assert view["active_version_id"] is None and "SQL_NOT_VALIDATED" in _codes(flows.readiness("d0"))
    r = _validate(client, fake, vid)
    v = r["validation"]
    assert v["status"] == "VALID" and r["active_version_id"] == vid
    assert v["sql_sha256"] == ss._sha(D0_SQL) and v["d0_mapping_hash"] == d0_feed.mapping_hash()
    assert v["referenced_tables"] == [] and v["statement_type"] == "SELECT" and v["columns"]
    assert v["execution"]["rows_valid"] == 4 and v["execution"]["n_series"] == 2 and v["execution"]["day"]
    heads = [q[0].split("\n")[0] for q in fake.queries]
    assert "-- df:sql_dry_run" in heads and "-- df:d0_check" in heads            # dry run AND a real execution
    ex = [q for q in fake.queries if q[0].startswith("-- df:d0_check") and not q[1]["dry_run"]][-1]
    assert ("day", "DATE", timeutil.today_vn()) in ex[1]["params"] and ex[1]["maximum_bytes_billed"]
    assert flows.readiness("d0")["ready"] is True
    assert next(x for x in client.get("/api/sql-sources").json()["d0"]["versions"]
                if x["id"] == vid)["validated_for_current_mapping"] is True


# ------------------------------------------------------------------ 2. syntax error / no permission / not executable
@pytest.mark.parametrize("kind,err,code", [
    ("sql_dry_run", BadRequest("Syntax error: Unexpected keyword FROM at [1:10]"), "BQ_SQL_ERROR"),
    ("sql_dry_run", Forbidden("Access Denied: Table x: User does not have permission to query table x"),
     "BQ_PERMISSION_DENIED"),
    ("d0_check", NotFound("Not found: Dataset x was not found in location US"), "BQ_LOCATION_MISMATCH"),
])
def test_invalid_d0_sql_is_never_active_and_the_ui_reason_names_the_error(client, kind, err, code):
    fake = _prod()
    vid = _save(client)
    fake.errors[kind] = err
    r = _validate(client, fake, vid)
    assert r["validation"]["status"] == "INVALID" and r["validation"]["error"]["code"] == code
    assert r["active_version_id"] is None
    rd = client.get("/api/schedules").json()["flows"]["d0"]["readiness"]
    reason = next(x for x in rd["reasons"] if x["code"] == "SQL_NOT_VALIDATED")
    assert f"v{vid} INVALID {code}" in reason["detail"] and reason["vi"] and "Xác nhận" in reason["vi"]
    with pytest.raises(AppError) as e:
        sql_sources.snapshot("d0")
    assert e.value.code == "SQL_NOT_VALIDATED"


# ------------------------------------------------------------------ 3. fewer columns than D-1, essentials present
def test_d0_output_without_the_d1_only_columns_is_valid(client):
    fake = _prod()
    few = [("fc_code", "STRING"), ("created_date", "DATE"), ("so_code", "STRING"), ("sku_code", "STRING"),
           ("demand_quantity", "INTEGER")]
    assert not connector.validate_mapping([{"name": n, "type": t} for n, t in few])["ok"]   # D-1 rules reject it ...
    r = _validate(client, fake, _save(client, "SELECT fc_code, created_date, so_code, sku_code, demand_quantity FROM t"), dry=few)
    assert r["validation"]["status"] == "VALID", r["validation"]  # ... the D-0 rules accept it
    assert r["validation"]["mapping_check"]["ok"] and r["validation"]["mapping_check"]["ignored_columns"] == []
    # TABLE mode: a D-0 table with only these columns passes its metadata check too
    fake.tables[D0] = few
    assert source_tables.check("d0")["status"] == "PASSED"


# ------------------------------------------------------------------ 4. other column names, own D-0 mapping
def test_other_column_names_work_through_the_d0_mapping_only(client):
    fake = _prod()
    own = [("kho", "STRING"), ("ma_sku", "STRING"), ("sl", "FLOAT64"), ("tg_tao", "TIMESTAMP")]
    r = client.put("/api/bigquery/d0-mapping", json={"mapping": {
        "sku_id": {"column": "ma_sku"}, "fc_id": {"column": "kho"}, "order_qty": {"column": "sl"},
        "order_date": {"column": None, "usage": "UNUSED"}, "created_at": {"column": "tg_tao", "usage": "OPTIONAL"},
        "order_id": {"column": None}}})
    assert r.status_code == 200 and r.json()["missing"] == [] and r.json()["key_columns"] == ["ma_sku", "kho", "tg_tao"]
    d1_before = connector.mapping_hash(ss.get("bigquery"))
    assert ss.get("bigquery").production_enabled                      # the D-0 mapping never touches D-1
    vid = _save(client, "SELECT kho, ma_sku, sl, tg_tao FROM `p.d.orders_today`")
    v = _validate(client, fake, vid, dry=own)["validation"]
    assert v["status"] == "VALID", v
    from app.sync import run_d0_snapshot
    fake.responses["d0"] = _d0_rows(timeutil.today_vn())
    res = run_d0_snapshot("JOB-OWN", None, False)
    sql = [q[0] for q in fake.queries if q[0].startswith("-- df:d0\n")][-1]
    assert "t.`ma_sku`" in sql and "t.`kho`" in sql and "DATE(t.`tg_tao`, 'Asia/Ho_Chi_Minh')" in sql
    assert "sku_code" not in sql and "demand_quantity" not in sql and "created_date" not in sql
    assert res["series"] == 2 and res["sql_source"]["mapping"]["sku_id"] == "ma_sku"
    assert connector.mapping_hash(ss.get("bigquery")) == d1_before


# ------------------------------------------------------------------ 5. missing essential fields
def test_missing_sku_fc_or_quantity_is_reported_by_field(client):
    from app.sync import run_d0_snapshot
    fake = _prod()
    vid = _save(client)
    r = _validate(client, fake, vid, dry=[c for c in REAL_D0 if c[0] != "demand_quantity"])
    err = r["validation"]["error"]
    assert err["code"] == "SQL_OUTPUT_MISSING_COLUMNS" and r["active_version_id"] is None
    assert {"field": "order_qty", "code": "COLUMN_NOT_FOUND", "column": "demand_quantity"} in json.loads(err["detail"])
    bad = [("demand_quantity", "STRING") if c[0] == "demand_quantity" else c for c in REAL_D0]
    assert _validate(client, fake, vid, dry=bad)["validation"]["error"]["code"] == "D0_MAPPING_TYPE_INCOMPATIBLE"
    client.put("/api/bigquery/d0-mapping", json={"mapping": {"fc_id": {"column": None}}})
    rd = flows.readiness("d0")
    assert _codes(rd) == ["D0_MAPPING_INCOMPLETE"] and rd["reasons"][0]["detail"] == "fc_id"
    assert _validate(client, fake, vid)["validation"]["error"]["code"] == "D0_MAPPING_INCOMPLETE"
    j = runner.execute("D0_SYNC", "D0_SYNC:missing", "MANUAL", None, {})
    assert j["status"] == "SKIPPED" and j["reason_code"] == "D0_MAPPING_INCOMPLETE"   # a config gap, not a crash
    with pytest.raises(AppError):
        run_d0_snapshot("JOB-X", None, False)


# ------------------------------------------------------------------ 6. SKU without forecast / unmapped rows
def _publish_forecast(scope_key, day, pairs):
    now = timeutil.now_iso()
    with db.tx() as c:
        c.execute("INSERT INTO training_runs(id, scope_key, data_source, status, started_at) VALUES "
                  "('TRN-T1', ?, 'BIGQUERY', 'ACCEPTED', ?)", (scope_key, now))
        c.execute("INSERT INTO forecast_runs(id, training_run_id, model_version, scope_key, data_source, forecast_origin, "
                  "data_as_of, horizons_json, max_horizon, n_series, status, created_at) VALUES "
                  "('FCR-T1', 'TRN-T1', 'MV-T1', ?, 'BIGQUERY', ?, ?, '[7]', 7, ?, 'PUBLISHED', ?)",
                  (scope_key, str(day), str(day - timedelta(days=1)), len(pairs), "2000-01-01T00:00:00+00:00"))
        c.executemany("INSERT INTO forecast_values(run_id, sku_id, fc_id, target_date, horizon_day, yhat, method) "
                      "VALUES ('FCR-T1', ?, ?, ?, 1, 3.0, 'LIGHTGBM')", [(s, f, str(day)) for s, f in pairs])


def test_rows_without_forecast_are_kept_and_counted_and_null_keys_are_counted(client):
    from app.data.demand import bigquery_scope_key
    from app.sync import run_d0_snapshot, snapshot_detail
    fake = _prod()
    _validate(client, fake, _save(client))
    today = timeutil.today_vn()
    fake.responses["d0"] = _d0_rows(today)
    res = run_d0_snapshot("JOB-NOFC", None, False)
    assert res["forecast_match"]["forecast_run_id"] is None and res["forecast_match"]["series_without_forecast"] == 2
    assert {"code": "D0_NO_FORECAST_FOR_TODAY", "detail": str(today)} in res["warnings"]
    _publish_forecast(bigquery_scope_key(ss.get("bigquery")), today, [("S1", "F1"), ("S9", "F1")])
    res = run_d0_snapshot("JOB-FC", None, False)
    m = res["forecast_match"]
    assert m["forecast_run_id"] == "FCR-T1" and m["series_with_forecast"] == 1 and m["series_without_forecast"] == 1
    assert m["qty_without_forecast"] == 1.0 and m["sample_without_forecast"] == ["S2|F1"]
    assert m["forecast_series_without_d0_row"] == 1                                 # S9: no order so far today
    assert res["excluded_by_reason"]["NULL_FC"] == {"rows": 1, "qty": 2.0} and res["rows_error"] == 1
    det = snapshot_detail(res["snapshot_id"])
    vals = {(v["sku_id"], v["fc_id"]): v for v in det["values"]}
    assert set(vals) == {("S1", "F1"), ("S2", "F1")}                                 # kept, not silently dropped
    assert vals[("S1", "F1")]["full_day_forecast"] == 3.0 and vals[("S2", "F1")]["full_day_forecast"] is None


# ------------------------------------------------------------------ 7. rows of another day
def test_rows_of_another_day_never_count_for_today(client):
    from app.sync import run_d0_snapshot
    fake = _prod()
    _validate(client, fake, _save(client))
    today = timeutil.today_vn()
    fake.responses["d0"] = _d0_rows(today, other_date=str(today - timedelta(days=1)))
    res = run_d0_snapshot("JOB-DAY", None, False)
    assert res["rows_other_day"] == 1 and res["excluded_by_reason"]["OTHER_DAY"]["rows"] == 1
    assert res["rows_valid"] == 4 and sum(r["n_rows"] for r in res.get("rows", [])) == 0     # values stored separately
    with db.read() as c:
        assert c.execute("SELECT SUM(cumulative_qty) FROM d0_snapshot_values WHERE snapshot_id=?",
                         (res["snapshot_id"],)).fetchone()[0] == 7.0
        assert c.execute("SELECT order_date FROM d0_snapshots WHERE id=?", (res["snapshot_id"],)).fetchone()[0] == str(today)
    sql = d0_feed.build_sql({"mode": "TABLE", "table": D0, "mapping": d0_feed.used(ss.get("bigquery")),
                             "types": {"created_date": "DATE"}, "key_columns": ["so_code"]}, "BLOCK")
    assert "WHEN _d != @day THEN 'OTHER_DAY'" in sql and f"FROM `{D0}` AS t" in sql
    assert "COUNTIF(_d = @day) - COUNT(DISTINCT IF(_d = @day, _key, NULL))" in sql       # duplicates of TODAY only


# ------------------------------------------------------------------ 8-10. idempotent, no history, no training input
def test_rerun_creates_no_duplicate_and_d0_never_touches_history_or_training(client):
    from app.sync import run_d0_snapshot
    fake = _prod()
    _validate(client, fake, _save(client))
    fake.responses["d0"] = _d0_rows(timeutil.today_vn())
    with db.read() as c:
        before = c.execute("SELECT COUNT(*), COALESCE(SUM(qty), 0) FROM demand_daily").fetchone()
    j1 = runner.execute("D0_SYNC", "D0_SYNC:slot-x", "MANUAL", None, {})
    j2 = runner.execute("D0_SYNC", "D0_SYNC:slot-x", "MANUAL", None, {})            # same key: never runs twice
    assert j1["status"] == "SUCCEEDED" and j2["note"] == "ALREADY_SUCCEEDED"
    again = run_d0_snapshot(j1["id"], None, False)                                 # re-entered job: no second write
    assert again["already_written"]
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM d0_snapshots").fetchone()[0] == 1
        assert tuple(c.execute("SELECT COUNT(*), COALESCE(SUM(qty), 0) FROM demand_daily").fetchone()) == tuple(before)
        assert c.execute("SELECT COUNT(*) FROM job_runs WHERE job_type='TRAIN_PUBLISH'").fetchone()[0] == 0
    # nothing that builds training / backtest data reads the D-0 tables
    app_dir = Path(__file__).resolve().parents[1] / "app"
    for f in list((app_dir / "ml").glob("*.py")) + [app_dir / "data" / "demand.py", app_dir / "data" / "quality.py"]:
        assert "d0_snapshot" not in f.read_text(encoding="utf-8"), f


# ------------------------------------------------------------------ 11. a change needs a new validation
def test_sql_mapping_or_key_change_never_reuses_an_old_validation(client):
    fake = _prod()
    vid = _save(client)
    assert _validate(client, fake, vid)["validation"]["status"] == "VALID"
    v2 = _save(client, D0_SQL + " AND demand_quantity > 0")
    view = client.get("/api/sql-sources").json()["d0"]
    assert view["active_version_id"] == vid and next(v for v in view["versions"] if v["id"] == v2)["validation"] is None
    client.put("/api/bigquery/d0-mapping", json={"mapping": {"order_id": {"column": None}}})   # key changes too
    rd = flows.readiness("d0")
    assert _codes(rd) == ["D0_REVALIDATE_REQUIRED"]
    assert next(v for v in client.get("/api/sql-sources").json()["d0"]["versions"]
                if v["id"] == vid)["validated_for_current_mapping"] is False
    j = runner.execute("D0_SYNC", "D0_SYNC:stale", "MANUAL", None, {})
    assert j["status"] == "SKIPPED" and j["reason_code"] == "D0_REVALIDATE_REQUIRED"
    assert _validate(client, fake, vid)["validation"]["status"] == "VALID" and flows.readiness("d0")["ready"]
    client.put("/api/sql-sources/d0/options", json={"key_columns": ["so_code", "sku_code"]})
    assert _codes(flows.readiness("d0")) == ["D0_REVALIDATE_REQUIRED"]
    # TABLE mode: the table check is tied to the mapping it proved as well
    client.put("/api/sql-sources/d0/options", json={"mode": "TABLE", "key_columns": []})
    assert source_tables.check("d0")["status"] == "PASSED" and flows.readiness("d0")["ready"]
    client.put("/api/bigquery/d0-mapping", json={"mapping": {"order_id": {"column": "so_code"}}})
    assert _codes(flows.readiness("d0")) == ["D0_REVALIDATE_REQUIRED"] and not source_tables.is_ok("d0")


def test_a_validation_recorded_by_1_2_0_must_be_redone(client):
    _prod()
    cfg = ss.get("sql_sources")
    cfg.d0.versions[0].validation = {"status": "VALID", "checked_at": "2026-10-16T01:00:00+00:00",
                                     "columns": [{"name": n, "type": t} for n, t in REAL_D0]}
    cfg.d0.active_version_id = cfg.d0.versions[0].id
    ss.save("sql_sources", cfg)
    assert _codes(flows.readiness("d0")) == ["D0_REVALIDATE_REQUIRED"]


def test_settings_of_1_2_0_get_the_d0_mapping_and_d1_identity_is_unchanged():
    with db.tx() as c:
        c.execute("INSERT INTO app_settings(section, value_json, updated_at) VALUES ('bigquery', ?, ?)",
                  (json.dumps({"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm",
                               "d0_table_id": D0}), timeutil.now_iso()))
    bq = ss.get("bigquery")
    assert d0_feed.used(bq) == {"sku_id": "sku_code", "fc_id": "fc_code", "order_qty": "demand_quantity",
                                "order_date": "created_date", "order_id": "so_code"}
    h = connector.mapping_hash(bq)
    d0_feed.save_mapping({"order_id": {"column": None}})
    assert connector.mapping_hash(ss.get("bigquery")) == h                         # D-1 scope / validation untouched


def test_suggest_reads_the_real_d0_schema_and_saves_nothing(client):
    _prod()
    before = ss.get("bigquery").d0_mapping
    r = client.post("/api/bigquery/d0-mapping/suggest", json={"source": "table"}).json()
    assert r["mapping"]["sku_id"]["column"] == "sku_code" and r["mapping"]["order_date"]["column"] == "created_date"
    assert [c["name"] for c in r["columns"]] == [n for n, _ in REAL_D0]
    assert ss.get("bigquery").d0_mapping == before


# ------------------------------------------------------------------ 12-13. D-1 success / failure and the training
def _freeze(vn_hour=10):
    t = datetime(2026, 10, 17, vn_hour - 7, 0, tzinfo=timezone.utc)
    timeutil.set_now_override(lambda: t)
    return t.astimezone(timeutil.VN_TZ)


def _d1_job(key, status, finished_utc, trigger="MANUAL", result=None):
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, created_at, "
                  "started_at, finished_at, result_json) VALUES (?, 'D1_SYNC', ?, ?, ?, 1, 1, ?, ?, ?, ?)",
                  (f"JOB-{key[-12:]}", key, trigger, status, finished_utc, finished_utc, finished_utc,
                   json.dumps({"params": {}, "result": result or {}})))


def _train_actions(now):
    with db.read() as c:
        return [a for a in plan(now, ss.get("schedule"), "BIGQUERY", None, c) if a["job_type"] == "TRAIN_PUBLISH"]


REGULAR = {"status": "SUCCEEDED", "mode": "FALLBACK_TIME_VERIFIED", "backfill": False, "window_end": "2026-10-16"}


def test_training_follows_a_successful_d1_of_today_scheduled_or_manual(client):
    _prod()
    now = _freeze(10)
    ss.update("schedule", {"train_enabled": True, "train_time": "09:00", "d1_enabled": False})
    assert "TRAIN_WAITS_FOR_D1" in _codes(flows.readiness("train")) and _train_actions(now) == []
    # not today's regular D-1: a backfill, yesterday's run, a run that did not end yesterday
    _d1_job("D1_SYNC:BACKFILL:1", "SUCCEEDED", "2026-10-17T01:00:00+00:00", result={**REGULAR, "backfill": True, "mode": "BACKFILL"})
    _d1_job("D1_SYNC:MANUAL:old", "SUCCEEDED", "2026-10-16T16:59:59+00:00", result={**REGULAR, "window_end": "2026-10-15"})
    _d1_job("D1_SYNC:MANUAL:short", "SUCCEEDED", "2026-10-17T01:10:00+00:00", result={**REGULAR, "window_end": "2026-10-15"})
    assert "TRAIN_WAITS_FOR_D1" in _codes(flows.readiness("train")) and _train_actions(now) == []
    # the manual D-1 of this morning (as on production 17/10/2026, JOB-20261017012623-2A31B7)
    _d1_job("D1_SYNC:MANUAL:a572b00c1fc7", "SUCCEEDED", "2026-10-17T01:30:21+00:00", result=REGULAR)
    rd = flows.readiness("train")
    assert "TRAIN_WAITS_FOR_D1" not in _codes(rd)
    note = next(n for n in rd["notes"] if n["code"] == "D1_TODAY_SUCCEEDED")
    assert "MANUAL" in note["detail"] and "08:30" in note["detail"] and "2026-10-16" in note["detail"]
    acts = _train_actions(now)
    assert len(acts) == 1 and acts[0]["action"] == "run" and acts[0]["trigger"] == "CATCH_UP"   # RUN_ONCE policy
    assert ss.get("schedule").d1_enabled is False                                # nothing switched D-1 on


def test_training_never_runs_when_todays_d1_failed(client):
    _prod()
    now = _freeze(10)
    ss.update("schedule", {"train_enabled": True, "train_time": "09:00", "d1_enabled": True})
    _d1_job("D1_SYNC:2026-10-17", "FAILED", "2026-10-16T23:08:00+00:00", trigger="SCHEDULE")
    assert _train_actions(now) == []
    rd = flows.readiness("train")
    wait = next(n for n in rd["notes"] if n["code"] == "TRAIN_WAITING_FOR_TODAY_D1")
    assert "FAILED" in wait["detail"]
    with db.read() as c:
        assert flows.d1_success_today(c, now) is None


# ------------------------------------------------------------------ 14-15. switches untouched, causes visible
def test_d0_stays_off_and_the_ui_shows_the_precise_cause(client):
    fake = _prod()
    sched_before = ss.get("schedule").model_dump()
    d0 = client.get("/api/schedules").json()["flows"]["d0"]
    assert d0["enabled"] is False and d0["state"] == "OFF"
    r = next(x for x in d0["readiness"]["reasons"] if x["code"] == "SQL_NOT_VALIDATED")
    assert r["detail"] == "d0: v2 UNCHECKED, v1 UNCHECKED" and r["vi"] and r["en"]   # the two seeded 15/10 versions
    _validate(client, fake, _save(client))
    source_tables.check("d0")
    client.put("/api/bigquery/d0-mapping", json={"mapping": {"source_updated_at": {"column": None}}})
    from app.sync import run_d0_snapshot
    fake.responses["d0"] = _d0_rows(timeutil.today_vn())
    run_d0_snapshot("JOB-OFF", None, False)
    assert ss.get("schedule").model_dump() == sched_before                        # D-0 still OFF, no time changed
    d0 = client.get("/api/schedules").json()["flows"]["d0"]
    assert d0["enabled"] is False and d0["readiness"]["ready"] is True and d0["next_runs"] == []
