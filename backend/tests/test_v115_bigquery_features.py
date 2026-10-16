"""v1.1.5: BigQuery source `demand_planing_lightgbm` (mapping, validation, errors, cost/retry limits, sync
reconciliation) and the feature registry (no invented features, versioned feature sets, lineage).
Everything runs on an isolated test DB with a fake BigQuery client: no real BigQuery access."""
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import db
from app import settings_service as ss
from app import timeutil
from app.bq import connector
from app.messages import AppError
from app.ml import feature_registry as reg
from app.ml import pipeline
from app.ml.features import feature_names
from fake_bq import FakeBQ

# column names given by the user; the TYPES are an assumption for the tests (the real schema could not be read)
LAYOUT = [("fc_code", "STRING"), ("created_date", "DATE"), ("product_id", "INT64"), ("sku_code", "STRING"),
          ("item_code", "STRING"), ("demand_quantity", "FLOAT64"), ("outbound_quantity", "FLOAT64"),
          ("order_status", "STRING"), ("sales_price", "FLOAT64"), ("price_after_discount", "FLOAT64"),
          ("seller_code", "STRING"), ("sku_system_status", "STRING"), ("open_date", "DATE"),
          ("total_open_hours", "FLOAT64"), ("total_open_days", "INT64"), ("so_code", "STRING"), ("refresh_time", "TIMESTAMP")]
COLS = [{"name": n, "type": t} for n, t in LAYOUT]
OLD_33 = ["sku_code", "fc_code", "series_age", "lag_1", "lag_2", "lag_3", "lag_4", "lag_5", "lag_6", "lag_7", "lag_14",
          "lag_21", "lag_28", "roll_mean_7", "roll_mean_14", "roll_mean_28", "roll_mean_56", "roll_std_7", "roll_std_28",
          "zero_share_28", "days_since_last_sale", "roll_max_28", "dow", "dom", "month", "weekofyear", "is_weekend",
          "days_to_month_end", "price_last", "price_rel_28", "disc_last", "promo_last", "promo_mean_7"]


def _summary(**kw):
    s = {"n_rows": 1000, "rows_valid": 1000, "qty_read": 5000.0, "qty_valid": 5000.0, "exact_duplicate_rows": 0,
         "duplicate_key_rows": 0, "min_date": date(2026, 1, 1), "max_date": date.today() - timedelta(days=1),
         "n_sku": 10, "n_fc": 2, "n_series": 20, "n_days": 280, "max_qty": 50.0, "p99_qty": 20.0,
         "ref_outbound_qty_non_null": 1000, "ref_outbound_qty_sum": 4900.0, "ref_outbound_qty_sum_valid": 4900.0}
    for f in ss.REFERENCE_FIELDS:
        s.setdefault(f"ref_{f}_non_null", 1000)
    s.update(kw)
    return s


def _fake(summary=None, **extra):
    resp = {"validate_summary": [summary or _summary()], "validate_days": [], "validate_null_date": [{"n": 0}],
            "validate_categories": [{"field": "order_status", "value": "DELIVERED", "n_rows": 900, "qty_valid": 4500.0},
                                    {"field": "order_status", "value": "CANCELLED", "n_rows": 100, "qty_valid": 500.0}],
            "profile": [{"n_rows": 100}], "completion": [{"n": 1}]}
    resp.update(extra)
    return FakeBQ(schema=LAYOUT, responses=resp)


def _configure(fake=None):
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm",
                           "location": "asia-southeast1", "partition_column": "created_date"})
    fake = fake or _fake()
    connector.set_client_factory(fake)
    sug = connector.suggest_mapping(connector.read_schema()["columns"])
    ss.update("bigquery", {"field_mapping": sug["field_mapping"], "reference_mapping": sug["reference_mapping"]})
    return fake


# ------------------------------------------------------------------ mapping
def test_suggestion_maps_confirmed_columns_without_saving_or_inventing():
    _configure_only = ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm"})
    before = ss.get("bigquery").model_dump()
    sug = connector.suggest_mapping(COLS)
    fm, ref = sug["field_mapping"], sug["reference_mapping"]
    assert {k: fm[k]["column"] for k in ("order_id", "order_date", "sku_id", "fc_id", "order_qty", "source_updated_at")} == {
        "order_id": "so_code", "order_date": "created_date", "sku_id": "sku_code", "fc_id": "fc_code",
        "order_qty": "demand_quantity", "source_updated_at": "refresh_time"}
    assert fm["order_qty"]["column"] == "demand_quantity" and ref["outbound_qty"]["column"] == "outbound_quantity"
    # price / discount / promotion are NOT mapped automatically: they need a confirmed business rule
    for f in ("unit_price", "discount_amount", "promotion_flag", "voucher_flag", "voucher_amount"):
        assert fm[f]["column"] is None
        assert {"field": f, "code": "LEFT_UNMAPPED_NEEDS_BUSINESS_RULE"} in sug["notes"]
    assert ref["sku_status"]["column"] == "sku_system_status" and ref["open_hours"]["column"] == "total_open_hours"
    assert connector.validate_mapping(COLS, fm, ref)["ok"]
    assert ss.get("bigquery").model_dump() == before                         # nothing saved
    # created_date as TIMESTAMP: never turned into a day silently -> proposed as created_at with an explicit time zone
    ts = [{"name": c["name"], "type": "TIMESTAMP" if c["name"] == "created_date" else c["type"]} for c in COLS]
    s2 = connector.suggest_mapping(ts)
    assert s2["field_mapping"]["order_date"]["column"] is None and s2["field_mapping"]["created_at"]["column"] == "created_date"
    assert any(n["code"] == "DATE_COLUMN_IS_TIMESTAMP_SET_TIMEZONE" for n in s2["notes"])
    # a missing column is reported, not guessed
    s3 = connector.suggest_mapping([c for c in COLS if c["name"] != "demand_quantity"])
    assert s3["field_mapping"]["order_qty"]["column"] is None
    assert {"field": "order_qty", "code": "SUGGESTED_COLUMN_MISSING", "column": "demand_quantity"} in s3["notes"]


def test_mapping_rules_timestamp_order_date_same_column_and_reference_types():
    bad = {"order_date": ss.FieldMapping(column="refresh_time", usage="REQUIRED"),
           "sku_id": ss.FieldMapping(column="sku_code", usage="REQUIRED"),
           "fc_id": ss.FieldMapping(column="sku_code", usage="REQUIRED"),
           "order_qty": ss.FieldMapping(column="demand_quantity", usage="REQUIRED")}
    ref = {"outbound_qty": ss.FieldMapping(column="order_status")}
    res = connector.validate_mapping(COLS, bad, ref)
    codes = {(e["field"], e["code"]) for e in res["errors"]}
    assert ("order_date", "ORDER_DATE_TIMESTAMP_NEEDS_TIMEZONE") in codes
    assert ("sku_id", "SAME_COLUMN_FOR_SEVERAL_KEYS") in codes
    assert ("outbound_qty", "TYPE_INCOMPATIBLE") in codes
    with pytest.raises(Exception):
        ss.update("bigquery", {"reference_mapping": {"unknown_field": {"column": "x"}}})
    with pytest.raises(Exception):
        ss.update("bigquery", {"reference_mapping": {"order_status": {"column": "x", "usage": "REQUIRED"}}})
    with pytest.raises(Exception):
        ss.update("bigquery", {"history_start_date": "01/01/2026"})


def test_settings_stay_readable_by_the_previous_version():
    """1.1.4 validates field_mapping keys strictly and ignores unknown top-level keys: the new options must be top-level
    and field_mapping must keep exactly the old 14 keys, so a rollback to 1.1.4 can still read the settings."""
    _configure()
    saved = json.loads(ss.get("bigquery").model_dump_json())
    assert set(saved["field_mapping"]) == set(ss.INTERNAL_FIELDS) and len(ss.INTERNAL_FIELDS) == 14
    for k in ("reference_mapping", "history_start_date", "exact_duplicate_policy", "max_retries", "max_null_share"):
        assert k in saved
    old = {k: v for k, v in saved.items() if k not in ("reference_mapping", "history_start_date", "exact_duplicate_policy",
                                                       "max_retries", "max_null_share")}
    again = ss.BigQuerySettings.model_validate(old)            # 1.1.4 JSON -> 1.1.5 defaults
    assert again.history_start_date == "2026-01-01" and again.exact_duplicate_policy == "BLOCK"
    # model config saved by 1.1.4 (no feature_discount) gives exactly the old 33 names in the old order
    assert feature_names(ss.ModelSettings.model_validate({})) == OLD_33
    assert "disc_last" not in feature_names(ss.ModelSettings.model_validate({"feature_price": False}))


# ------------------------------------------------------------------ errors, retries, limits
class _Err(Exception):
    def __init__(self, msg="", errors=None):
        super().__init__(msg)
        self.errors = errors or []


def _named(name):
    return type(name, (_Err,), {})


@pytest.mark.parametrize("name,msg,errors,code", [
    ("DefaultCredentialsError", "no creds", None, "BQ_AUTH_MISSING"),
    ("RefreshError", "invalid_grant: token expired", None, "BQ_AUTH_EXPIRED"),
    ("Forbidden", "Quota exceeded", [{"reason": "quotaExceeded"}], "BQ_QUOTA"),
    ("TooManyRequests", "slow down", None, "BQ_QUOTA"),
    ("Forbidden", "Access Denied: Table x", [{"reason": "accessDenied"}], "BQ_PERMISSION_DENIED"),
    ("NotFound", "Not found: Dataset p:d was not found in location US", None, "BQ_LOCATION_MISMATCH"),
    ("NotFound", "Not found: Table p:d.t", None, "BQ_NOT_FOUND"),
    ("BadRequest", "Unrecognized name: demand_quantity at [3:5]", None, "BQ_SCHEMA_CHANGED"),
    ("BadRequest", "Syntax error: Unexpected keyword FROM at [12:1]", None, "BQ_SQL_ERROR"),
    ("BadRequest", "Invalid table-valued function", None, "BQ_QUERY_INVALID"),
    ("TimeoutError", "", None, "BQ_TIMEOUT"),
    ("ServiceUnavailable", "backend error", None, "BQ_UNAVAILABLE"),
    ("Forbidden", "Query exceeded limit for bytes billed: 100", [{"reason": "bytesBilledLimitExceeded"}], "BQ_QUERY_TOO_EXPENSIVE"),
])
def test_error_classification(name, msg, errors, code):
    assert connector._map_error(_named(name)(msg, errors)).code == code


class _SeqClient:
    """Dry runs succeed; real runs follow a scripted sequence of errors / results."""
    def __init__(self, script):
        self.script = list(script)
        self.runs = 0
        self.cancelled = 0

    def __call__(self, settings):
        return self

    def query(self, sql, job_config=None):
        if job_config.get("dry_run"):
            return SimpleNamespace(total_bytes_processed=10)
        self.runs += 1
        step = self.script.pop(0)
        outer = self

        class Job:
            def result(self, timeout=None):
                if isinstance(step, Exception):
                    raise step
                return step

            def cancel(self):
                outer.cancelled += 1
        return Job()


def test_bounded_retry_only_for_transient_errors_and_timeout_cancels_without_retry():
    _configure()
    sleeps = []
    connector.set_sleep(sleeps.append)
    try:
        bq = ss.get("bigquery")
        c = _SeqClient([_named("ServiceUnavailable")("x"), _named("ServiceUnavailable")("x"), [{"n": 1}]])
        assert connector._run(c, bq, "t", "SELECT 1")["attempts"] == 3 and len(sleeps) == 2
        c = _SeqClient([_named("ServiceUnavailable")("x")] * 5)
        with pytest.raises(AppError) as e:
            connector._run(c, bq, "t", "SELECT 1")
        assert e.value.code == "BQ_UNAVAILABLE" and c.runs == bq.max_retries + 1        # never unbounded
        c = _SeqClient([_named("TimeoutError")("")])
        with pytest.raises(AppError) as e:
            connector._run(c, bq, "t", "SELECT 1")
        assert e.value.code == "BQ_TIMEOUT" and c.runs == 1 and c.cancelled == 1
        c = _SeqClient([_named("Forbidden")("Access Denied")])
        with pytest.raises(AppError) as e:
            connector._run(c, bq, "t", "SELECT 1")
        assert e.value.code == "BQ_PERMISSION_DENIED" and c.runs == 1
    finally:
        connector.set_sleep(__import__("time").sleep)


def test_cost_limit_preview_limit_and_no_select_star():
    fake = _configure()
    ss.update("bigquery", {"preview_rows": 500})
    connector.preview()
    sql = fake.queries[-1][0]
    assert "LIMIT 500" in sql and "SELECT *" not in sql and "`outbound_quantity` AS ref_outbound_qty" in sql
    assert "DATE(`created_date`) BETWEEN" in sql
    with pytest.raises(Exception):
        ss.update("bigquery", {"preview_rows": 5000})
    big = _fake()
    big.bytes = 50 * 1024 ** 3
    connector.set_client_factory(big)
    with pytest.raises(AppError) as e:
        connector.validate_source()
    assert e.value.code == "BQ_QUERY_TOO_EXPENSIVE"
    assert all(q[1]["dry_run"] for q in big.queries)                      # nothing was actually run
    assert connector.validation_state()["passed"] is False


def test_history_start_is_the_lower_bound_of_every_load():
    fake = _configure()
    connector.fetch_daily(date(2025, 6, 1), date(2026, 1, 10))
    params = fake.queries[-1][1]["params"]
    assert params[0][2] == date(2026, 1, 1)
    assert "SELECT *" not in fake.queries[-1][0].split("checked AS")[0]


# ------------------------------------------------------------------ validation
def test_validation_passes_reconciles_and_is_bound_to_the_mapping(client):
    _configure()
    v = client.post("/api/bigquery/validate").json()
    assert v["passed"], v["blocking_issues"]
    assert v["reconciliation"]["rows_ok"] and v["reconciliation"]["qty_ok"]
    assert v["range"]["start"] == "2026-01-01" and v["target"] == {"field": "order_qty", "column": "demand_quantity"}
    assert v["outbound_vs_demand"]["ratio_outbound_to_demand"] == pytest.approx(0.98)
    assert v["categories"]["order_status"][0]["value"] == "DELIVERED"
    assert {w["code"] for w in v["warnings"]} >= {"MISSING_DAYS"}                    # no day rows in the fake
    st = client.get("/api/bigquery/status").json()
    assert st["validation_current"] and st["activation"]["requirements"]["validation"]
    # any change to mapping / range / duplicate policy invalidates the result (and production mode)
    ss.update("bigquery", {"production_enabled": True})
    r = client.put("/api/settings/bigquery", json={"history_start_date": "2026-02-01"})
    assert r.status_code == 200 and r.json()["production_enabled"] is False
    st = client.get("/api/bigquery/status").json()
    assert not st["validation_current"] and not st["activation"]["requirements"]["validation"]


@pytest.mark.parametrize("summary,code", [
    (dict(n_rows=0, rows_valid=0, qty_read=0, qty_valid=0), "NO_DATA"),
    (dict(rows_valid=900, excl_rows_null_target=100, qty_read=5000.0), "NULL_TARGET"),
    (dict(rows_valid=900, excl_rows_negative_target=100, excl_qty_negative_target=-300.0, qty_read=4700.0), "NEGATIVE_TARGET"),
    (dict(exact_duplicate_rows=4), "EXACT_DUPLICATES"),
    (dict(qty_read=5100.0), "RECONCILIATION_FAILED"),
])
def test_validation_blocks_on_data_problems(summary, code):
    _configure(_fake(_summary(**summary)))
    v = connector.validate_source()
    assert not v["passed"] and code in {b["code"] for b in v["blocking_issues"]}
    assert not connector.activation_check()["ready"]


def test_validation_detects_schema_change_and_null_dates():
    fake = _configure(_fake(validate_null_date=[{"n": 3}]))
    ss.update("bigquery", {"schema_snapshot": COLS})
    fake.schema = [(n, "STRING" if n == "demand_quantity" else t) for n, t in LAYOUT]
    with pytest.raises(AppError) as e:                    # the mapped target became STRING: mapping invalid
        connector.validate_source()
    assert e.value.code == "BQ_MAPPING_INVALID"
    fake.schema = LAYOUT
    v = connector.validate_source()
    assert "NULL_DATE" in {w["code"] for w in v["warnings"]} and v["reconciliation"]["rows_null_date_outside_range"] == 3


def test_failed_bigquery_query_changes_nothing(client):
    assert client.post("/api/demo/generate", json={"days": 60, "n_skus": 3, "seed": 1}).status_code == 200
    _configure(FakeBQ(schema=LAYOUT, errors={"validate_summary": _named("Forbidden")("Access Denied")}))
    g_before = ss.get("general").model_dump()
    with db.read() as c:
        n_before = c.execute("SELECT COUNT(*), SUM(qty) FROM demand_daily").fetchone()
    r = client.post("/api/bigquery/validate")
    assert r.status_code == 403 and r.json()["code"] == "BQ_PERMISSION_DENIED"
    assert ss.get("general").model_dump() == g_before and g_before["active_source"] == "DEMO"   # no silent switch
    with db.read() as c:
        assert c.execute("SELECT COUNT(*), SUM(qty) FROM demand_daily").fetchone() == n_before
        assert c.execute("SELECT COUNT(*) FROM training_runs").fetchone()[0] == 0              # never triggers training
    assert client.put("/api/active-source", json={"source": "BIGQUERY"}).status_code == 409


def test_sync_and_training_require_validation_and_sync_reconciles(monkeypatch):
    fake = _configure()
    ss.update("bigquery", {"production_enabled": True, "completion_table": "done", "completion_date_column": "d"})
    ss.update("general", {"active_source": "BIGQUERY"})
    from app.sync import run_d1_sync
    with pytest.raises(AppError) as e:
        run_d1_sync("J")
    assert e.value.code == "BQ_VALIDATION_REQUIRED"
    with pytest.raises(AppError) as e:
        pipeline.train_and_publish(source="BIGQUERY", force=True)
    assert e.value.code == "BQ_VALIDATION_REQUIRED"
    assert connector.validate_source()["passed"]
    y = date.today() - timedelta(days=1)
    good = [{"_kind": "VALID", "order_date": y, "sku_id": "S1", "fc_id": "F1", "qty": 4.0, "n_orders": 2, "n_rows": 2},
            {"_kind": "EXCLUDED", "_reason": "NULL_SKU", "qty": 1.0, "n_rows": 1},
            {"_kind": "TOTAL_READ", "_reason": "0", "qty": 5.0, "n_rows": 3},
            {"_kind": "TOTAL_KEPT", "_reason": "0", "qty": 5.0, "n_rows": 3}]
    fake.responses["daily"] = good
    res = run_d1_sync("J1", fallback_mode=True)
    assert res["full_reload"] and res["excluded_by_reason"] == {"NULL_SKU": {"rows": 1, "qty": 1.0}}
    # a read that does not reconcile is refused and nothing is written
    fake.responses["daily"] = [dict(good[0]), good[1], {**good[2], "n_rows": 9}, {**good[3], "n_rows": 9}]
    with pytest.raises(AppError) as e:
        run_d1_sync("J2", fallback_mode=True)
    assert e.value.code == "BQ_SYNC_RECONCILIATION_FAILED"
    # BLOCK policy: duplicates found at load time stop the load
    fake.responses["daily"] = [good[0], good[1], {**good[2], "_reason": "2"}, good[3]]
    with pytest.raises(AppError) as e:
        run_d1_sync("J3", fallback_mode=True)
    assert e.value.code == "BQ_DATA_DUPLICATES"
    with db.read() as c:
        assert tuple(c.execute("SELECT COUNT(*), SUM(qty) FROM demand_daily WHERE data_source='BIGQUERY'").fetchone()) == (1, 4.0)


def test_bigquery_rows_never_mix_with_demo(client):
    assert client.post("/api/demo/generate", json={"days": 60, "n_skus": 3, "seed": 1}).status_code == 200
    with db.tx() as c:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
                  "VALUES ('BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm', 'BIGQUERY', "
                  "'2026-01-05', 'BQSKU', 'BQFC', 99, 1, '2026-01-06')")
    from app.data.demand import load_demand, resolve_scope
    scope = resolve_scope(source="DEMO")
    d = load_demand(scope["scope_key"])
    assert "BQSKU" not in set(d["sku_id"]) and len(d)


# ------------------------------------------------------------------ feature registry
def test_registry_metadata_and_planned_features_are_never_model_inputs():
    names = reg.all_model_features()
    assert names == OLD_33
    keys = [p["key"] for p in reg.PLANNED]
    assert len(set(keys)) == len(keys) and not set(keys) & set(names)
    with db.read() as c:
        v = reg.view(c, "DEMO")
    req = {"feature_key", "display_name", "description", "data_type", "source_name", "source_column", "feature_group",
           "availability_status", "required", "default_or_missing_policy", "aggregation_rule", "effective_from",
           "effective_to", "created_at", "updated_at", "registry_version"}
    for e in v["entries"]:
        assert req <= set(e), e["feature_key"]
        assert e["availability_status"] in reg.STATUSES
    planned = [e for e in v["entries"] if e["kind"] == "PLANNED"]
    assert {e["availability_status"] for e in planned} == {"PLANNED"}
    assert not any(e["availability_status"] == "ACTIVE" for e in planned)
    assert {g for g in (e["feature_group"] for e in v["entries"])} == set(reg.GROUPS)


def test_registry_statuses_for_bigquery_without_price_or_promotion(client):
    _configure()
    ss.update("bigquery", {"production_enabled": True})
    ss.update("general", {"active_source": "BIGQUERY"})
    v = client.get("/api/features/registry").json()
    st = {e["feature_key"]: e for e in v["entries"]}
    assert v["coverage"]["rows"] == 0 and st["lag_1"]["availability_status"] == "UNAVAILABLE"
    with db.tx() as c:   # synced BigQuery rows: no price / discount / promotion values in the source mapping
        for i in range(30):
            c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
                      "VALUES (?, 'BIGQUERY', ?, 'S1', 'F1', 3, 1, '2026-02-01')",
                      ("BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm", str(date(2026, 1, 1) + timedelta(days=i))))
    connector.validate_source()
    v = client.get("/api/features/registry").json()
    st = {e["feature_key"]: e for e in v["entries"]}
    assert st["lag_1"]["availability_status"] == "ACTIVE"
    for f in ("price_last", "price_rel_28", "disc_last", "promo_last", "promo_mean_7"):
        assert st[f]["availability_status"] == "UNAVAILABLE" and st[f]["reason"] == "NO_DATA", f
        assert f not in v["next_training"]["features"]
    assert v["next_training"]["n_features"] == 28
    # source columns that exist in BigQuery but have no approved rule: "available, not activated"
    assert st["open_hours"]["availability_status"] == "DISABLED" and st["open_hours"]["source_column"] == "total_open_hours"
    assert st["deal_flag"]["availability_status"] == "PLANNED"


def _null_optional(scope_key, promo_share_rows=0.0):
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET avg_unit_price=NULL, avg_discount_rate=NULL, promo_share=NULL WHERE scope_key=?",
                  (scope_key,))


def test_training_without_promotion_data_drops_the_group_and_stays_explainable(client, fast_model):
    from app.ml import shap_audit
    ss.update("horizons", {"enabled": [7]})
    assert client.post("/api/demo/generate", json={"days": 150, "n_skus": 8, "seed": 3}).status_code == 200
    from app.data.demand import resolve_scope
    scope = resolve_scope(source="DEMO")
    with db.tx() as c:                       # simulate a source without promotion and discount data
        c.execute("UPDATE demand_daily SET promo_share=NULL, avg_discount_rate=NULL WHERE scope_key=?", (scope["scope_key"],))
    res = pipeline.train_and_publish(force=True)
    assert res["status"] == "PUBLISHED", res
    with db.read() as c:
        tr = db.one(c, "SELECT feature_config_json, model_path FROM training_runs WHERE id=?", (res["training_run_id"],))
    fc = json.loads(tr["feature_config_json"])
    assert "promo_last" not in fc["features"] and "disc_last" not in fc["features"] and "price_last" in fc["features"]
    assert len(fc["features"]) == 30 and fc["feature_set_version"] == reg.feature_set_version(fc["features"])
    assert fc["feature_decisions"]["promotion"]["reason"] == "NO_DATA" and fc["config"]["feature_promotion"] is False
    assert fc["settings_switches"]["feature_promotion"] is True            # the user's setting itself is unchanged
    assert ss.get("model").feature_promotion is True
    lin = fc["lineage"]
    assert lin["data_source"] == "DEMO" and lin["source_ref"]["id"] == scope["scope_key"]
    assert lin["target_mapping"]["field"] == "order_qty" and lin["demand_daily"]["rows"] > 0
    meta = json.loads((__import__("app.paths", fromlist=["x"]).models_dir() / tr["model_path"].replace(".txt", ".json")).read_text())
    assert meta["features"] == fc["features"] and meta["feature_set_version"] == fc["feature_set_version"]
    # the model is explained with exactly its own 30 features
    with db.read() as c:
        row = db.one(c, "SELECT sku_id, fc_id, target_date FROM forecast_values WHERE run_id=? AND method='LIGHTGBM' "
                        "AND horizon_day=1 LIMIT 1", (res["forecast_run_id"],))
    a = shap_audit.audit(res["forecast_run_id"], row["sku_id"], row["fc_id"], row["target_date"])
    assert a["status"] == "VERIFIED", [c for c in a["checks"] if not c["passed"]]
    assert len(a["features"]) == 30
    # the registry shows the groups as missing data, and the active model's list
    v = client.get("/api/features/registry").json()
    st = {e["feature_key"]: e for e in v["entries"]}
    assert st["promo_last"]["availability_status"] == "UNAVAILABLE" and st["promo_last"]["in_active_model"] is False
    assert st["price_last"]["availability_status"] == "ACTIVE" and st["price_last"]["in_active_model"] is True
    assert v["active_model"]["feature_set_version"] == fc["feature_set_version"]


def test_low_coverage_is_not_used_and_demo_keeps_its_33_features(small_demo):
    with db.read() as c:
        cov = reg.coverage(c, small_demo["batch_id"])
    assert cov["promo_share"] == 1.0 and cov["avg_unit_price"] == 1.0
    resolved, dec = reg.resolve(ss.get("model"), cov)
    assert feature_names(resolved) == OLD_33 and all(d["used"] for d in dec.values())
    resolved, dec = reg.resolve(ss.get("model"), {**cov, "promo_share": 0.3})
    assert dec["promotion"]["reason"] == "LOW_COVERAGE" and "promo_last" not in feature_names(resolved)
    off = ss.get("model").model_copy(update={"feature_price": False})
    resolved, dec = reg.resolve(off, cov)
    assert dec["price"]["reason"] == "TOGGLE_OFF" and dec["discount"]["reason"] == "TOGGLE_OFF"   # legacy: discount follows price
