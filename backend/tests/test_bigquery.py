from datetime import date, datetime, timedelta, timezone

import pytest

from app import db
from app import settings_service as ss
from app.bq import connector
from app.messages import AppError
from fake_bq import FakeBQ, Forbidden, NotFound

MAPPING = {"order_id": {"column": "order_id", "usage": "OPTIONAL"},
           "created_at": {"column": "created_at", "usage": "REQUIRED"},
           "sku_id": {"column": "sku", "usage": "REQUIRED"}, "fc_id": {"column": "warehouse", "usage": "REQUIRED"},
           "order_qty": {"column": "qty", "usage": "REQUIRED"}, "unit_price": {"column": "price", "usage": "OPTIONAL"},
           "source_updated_at": {"column": "updated_at", "usage": "OPTIONAL"}}


def _configure(**extra):
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders", "location": "asia-southeast1",
                           "partition_column": "dt", **extra})


def test_defaults_prefilled_and_nothing_assumed():
    bq = ss.get("bigquery")
    assert bq.project_id == "lakehouse-prod-394907"
    assert bq.dataset_id == "" and bq.source_table == "" and bq.location == ""
    assert bq.production_enabled is False
    with pytest.raises(AppError) as e:
        connector.test_connection()
    assert e.value.code == "BQ_NOT_CONFIGURED"


def test_identifier_validation_blocks_injection():
    with pytest.raises(Exception):
        ss.update("bigquery", {"dataset_id": "sales`; DROP TABLE x; --"})
    with pytest.raises(Exception):
        ss.update("bigquery", {"field_mapping": {"sku_id": {"column": "a b", "usage": "REQUIRED"}}})


def test_connection_location_and_errors():
    _configure()
    connector.set_client_factory(FakeBQ())
    out = connector.test_connection()
    assert out["location"] == "asia-southeast1" and out["num_rows"] == 12345
    connector.set_client_factory(FakeBQ(location="US"))
    with pytest.raises(AppError) as e:
        connector.test_connection()
    assert e.value.code == "BQ_LOCATION_MISMATCH"
    connector.set_client_factory(FakeBQ(errors={"dataset": NotFound("x")}))
    with pytest.raises(AppError) as e:
        connector.test_connection()
    assert e.value.code == "BQ_NOT_FOUND"
    connector.set_client_factory(FakeBQ(errors={"table": Forbidden("no")}))
    with pytest.raises(AppError) as e:
        connector.test_connection()
    assert e.value.code == "BQ_PERMISSION_DENIED"
    st = connector.status()
    assert st["connection"]["ok"] is False


def test_schema_mapping_validation():
    _configure()
    connector.set_client_factory(FakeBQ())
    cols = connector.read_schema()["columns"]
    ok = connector.validate_mapping(cols, {k: ss.FieldMapping(**v) for k, v in MAPPING.items()})
    assert ok["ok"], ok
    bad = {**MAPPING, "order_qty": {"column": "sku", "usage": "REQUIRED"},
           "fc_id": {"column": "not_there", "usage": "REQUIRED"}}
    res = connector.validate_mapping(cols, {k: ss.FieldMapping(**v) for k, v in bad.items()})
    codes = {(e["field"], e["code"]) for e in res["errors"]}
    assert ("order_qty", "TYPE_INCOMPATIBLE") in codes and ("fc_id", "COLUMN_NOT_FOUND") in codes


def test_schema_drift_detected():
    d = connector.schema_drift([{"name": "a", "type": "STRING"}, {"name": "b", "type": "INT64"}],
                               [{"name": "a", "type": "INT64"}, {"name": "c", "type": "STRING"}])
    assert d == {"removed": ["b"], "added": ["c"], "type_changed": ["a"]}


def test_expensive_query_refused_before_running():
    _configure(field_mapping=MAPPING, maximum_bytes_billed=10 * 1024 ** 2)
    fake = FakeBQ(bytes_=50 * 1024 ** 3)
    connector.set_client_factory(fake)
    with pytest.raises(AppError) as e:
        connector.fetch_daily(date(2026, 1, 1), date(2026, 1, 2))
    assert e.value.code == "BQ_QUERY_TOO_EXPENSIVE"
    assert all(q[1]["dry_run"] for q in fake.queries)   # only the dry run happened


def test_daily_query_selects_mapped_columns_with_partition_filter():
    _configure(field_mapping=MAPPING)
    fake = FakeBQ()
    connector.set_client_factory(fake)
    connector.fetch_daily(date(2026, 1, 1), date(2026, 1, 2))
    sql = fake.queries[-1][0]
    assert "`sku` AS sku_id" in sql and "SELECT *" not in sql.split("checked AS")[0]
    assert "DATE(`dt`) BETWEEN" in sql and "Asia/Ho_Chi_Minh" in sql
    # 1.1.5: exact duplicate rows are never dropped silently; only the explicit DROP_EXACT policy de-duplicates
    assert "SELECT DISTINCT" not in sql
    ss.update("bigquery", {"exact_duplicate_policy": "DROP_EXACT"})
    connector.fetch_daily(date(2026, 1, 1), date(2026, 1, 2))
    assert "SELECT DISTINCT" in fake.queries[-1][0]


PASSING_VALIDATION = {
    "validate_summary": [{"n_rows": 100, "rows_valid": 100, "qty_read": 500, "qty_valid": 500, "exact_duplicate_rows": 0,
                          "min_date": date(2026, 1, 1), "max_date": date.today() - timedelta(days=1), "n_sku": 1, "n_fc": 1}],
    "validate_days": [], "validate_null_date": [{"n": 0}]}


def _activate(fake):
    _configure(field_mapping=MAPPING)
    connector.set_client_factory(fake)
    for k, v in PASSING_VALIDATION.items():
        fake.responses.setdefault(k, v)
    connector.test_connection()
    cols = connector.read_schema()["columns"]
    ss.update("bigquery", {"schema_snapshot": cols})
    connector.profile(7)
    assert connector.validate_source()["passed"]
    act = connector.activation_check()
    assert act["ready"], act
    ss.update("bigquery", {"production_enabled": True})
    ss.update("general", {"active_source": "BIGQUERY"})


def test_d1_sync_incremental_and_late_data_window(client):
    yesterday = date.today() - timedelta(days=1)
    rows = [{"order_date": yesterday - timedelta(days=i), "sku_id": "S1", "fc_id": "F1", "qty": 5, "n_orders": 2,
             "avg_unit_price": 10.0, "avg_discount_rate": 0.0, "promo_share": 0.0, "voucher_share": None,
             "max_source_updated_at": "2026-01-01T00:00:00+00:00", "max_batch_id": None, "n_rows": 2}
            for i in range(3)] + [{"order_date": None, "sku_id": None, "fc_id": None, "n_rows": 4}]
    fake = FakeBQ(responses={"profile": [{"n_rows": 100, "null_sku": 0, "null_fc": 0, "null_qty": 0,
                                          "negative_qty": 0, "min_date": date(2026, 1, 1), "max_date": yesterday,
                                          "n_days": 7, "duplicate_grain_rows": 0, "max_source_updated_at": None}],
                             "daily": rows, "completion": [{"n": 1}]})
    _activate(fake)
    ss.update("bigquery", {"completion_table": "done", "completion_date_column": "d"})
    from app.sync import run_d1_sync
    res = run_d1_sync("J1")
    assert res["rows_error"] == 4 and res["rows_valid"] == 6 and res["mode"] == "SIGNAL"
    key = "BIGQUERY:lakehouse-prod-394907.sales.orders"
    with db.read() as c:
        assert c.execute("SELECT SUM(qty) FROM demand_daily WHERE scope_key=?", (key,)).fetchone()[0] == 15
    run_d1_sync("J2")      # second sync re-reads only the late-data window, no double counting
    with db.read() as c:
        assert c.execute("SELECT SUM(qty) FROM demand_daily WHERE scope_key=?", (key,)).fetchone()[0] == 15
    daily_q = [q for q in fake.queries if q[0].startswith("-- df:daily") and not q[1]["dry_run"]]
    first_start, second_start = daily_q[0][1]["params"][0][2], daily_q[1][1]["params"][0][2]
    assert second_start > first_start   # incremental


def test_d1_waits_for_signal_then_verifies_source_after_fallback():
    from app.sync import Retryable, Wait, run_d1_sync
    fake = FakeBQ(responses={"profile": [{"n_rows": 10}], "completion": [{"n": 0}],
                             "sufficiency": [{"d": date.today() - timedelta(days=1), "n": 1},
                                             {"d": date.today() - timedelta(days=2), "n": 100}]})
    _activate(fake)
    ss.update("bigquery", {"completion_table": "done", "completion_date_column": "d"})
    with pytest.raises(Wait):
        run_d1_sync("J", fallback_mode=False)
    with pytest.raises(Retryable) as e:
        run_d1_sync("J", fallback_mode=True)     # fallback time reached but the day looks incomplete
    assert e.value.code == "SOURCE_INCOMPLETE"


def test_d0_snapshot_from_bigquery_and_failure_creates_no_snapshot():
    from app.sync import run_d0_snapshot
    fake = FakeBQ(responses={"profile": [{"n_rows": 10}],
                             "d0": [{"sku_id": "S1", "fc_id": "F1", "cumulative_qty": 7, "source_updated_at": None,
                                     "n_rows": 3}, {"sku_id": None, "fc_id": None, "cumulative_qty": None,
                                                    "source_updated_at": None, "n_rows": 1}]})
    _activate(fake)
    from app.bq import sql_sources
    # 1.1.6: D0 defaults to the user's SQL feed and scheduled BigQuery D0 runs are OFF; this test covers TABLE mode
    sql_sources.set_options("d0", mode="TABLE", schedule_enabled=True)
    res = run_d0_snapshot("J", "slot", False)
    assert res["rows_error"] == 1 and res["series"] == 1
    fake.errors["d0"] = RuntimeError("backend unavailable")
    with pytest.raises(AppError):
        run_d0_snapshot("J2", "slot2", False)
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM d0_snapshots").fetchone()[0] == 1


def test_activation_requires_all_checks(client):
    r = client.put("/api/active-source", json={"source": "BIGQUERY"})
    assert r.status_code == 409 and r.json()["code"] == "SOURCE_NOT_READY"
    r = client.post("/api/bigquery/activate")
    assert r.status_code == 409
    _configure(field_mapping=MAPPING)
    connector.set_client_factory(FakeBQ(responses={"profile": [{"n_rows": 0}]}))
    client.post("/api/bigquery/test-connection")
    client.post("/api/bigquery/schema")
    r = client.post("/api/bigquery/mapping", json={"field_mapping": MAPPING})
    assert r.status_code == 200, r.text
    prof = client.post("/api/bigquery/profile", json={"days": 7}).json()
    assert prof["passed"] is False and "NO_DATA" in prof["blocking_issues"]
    assert connector.status()["profile"]["ok"] is False      # an empty table must not unlock production
    assert client.post("/api/bigquery/activate").status_code == 409


def test_profile_failure_marks_status_and_blocks_activation(client):
    _configure(field_mapping=MAPPING)
    connector.set_client_factory(FakeBQ(errors={"profile": Forbidden("denied")}))
    r = client.post("/api/bigquery/profile", json={"days": 7})
    assert r.status_code == 403 and r.json()["code"] == "BQ_PERMISSION_DENIED"
    assert client.post("/api/bigquery/activate").status_code == 409


def test_settings_change_disables_production(client):
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders", "production_enabled": True})
    r = client.put("/api/settings/bigquery", json={"source_table": "orders_v2"})
    assert r.status_code == 200 and r.json()["production_enabled"] is False
