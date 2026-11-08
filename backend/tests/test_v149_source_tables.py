"""1.4.9: the auxiliary BigQuery tables (open hours, AVG_DEMAND current / historical, product names) configured and
checked on the BigQuery page like the D-1 / D-0 tables, the product-names table as a full id (a stored short name keeps
working), and the six-key open-hours rule following the configured D-1 table."""
import pytest

from app import db
from app import settings_service as ss
from app.bq import product_names, source_tables
from app.data import open_hours_override as ovr
from app.data.demand import bigquery_scope_key

from fake_bq import FakeBQ
from test_v116 import _bq_ready
from test_v120_sources import D0, D0_OUT, D1, REAL_D1

OH = "lakehouse-prod-394907.gold_buymed_vn2.openhours_by_sku"
AVG = "lakehouse-prod-394907.gold_buymed_vn2.fact_avg_demand_sku"
AVG_H = "lakehouse-prod-394907.gold_buymed_vn2.fact_avg_demand_sku_historical"
NAMES = "lakehouse-prod-394907.gold_buymed_vn2.dim_sku"
# the real layouts (sheet COT of docs/ket_noi_du_lieu/DANH_MUC_DU_LIEU.xlsx, schema of 08/11/2026)
OH_COLS = [("fc_code", "STRING"), ("product_id", "INTEGER"), ("sku_code", "STRING"), ("item_code", "STRING"),
           ("product_name", "STRING"), ("seller_code", "STRING"), ("seller_class", "STRING"), ("open_date", "DATE"),
           ("total_open_hours", "FLOAT"), ("total_open_days", "FLOAT")]
AVG_COLS = [("fc_code", "STRING"), ("sku_code", "STRING"), ("product_id", "INTEGER"), ("product_name", "STRING"),
            ("avg_demand", "FLOAT"), ("seller_code", "STRING"), ("sku_system_status", "STRING"), ("ingest_time", "STRING")]
AVG_H_COLS = AVG_COLS + [("transformed_at", "TIMESTAMP")]
NAMES_COLS = [("transformed_at", "TIMESTAMP"), ("sku_code", "STRING"), ("product_id", "INTEGER"),
              ("product_name", "STRING"), ("seller_code", "STRING"), ("sku_active", "BOOLEAN")]
REAL = {D1: REAL_D1, D0: D0_OUT, OH: OH_COLS, AVG: AVG_COLS, AVG_H: AVG_H_COLS, NAMES: NAMES_COLS}
AUX = {"openhours": OH, "avg_demand": AVG, "avg_demand_hist": AVG_H, "product_names": NAMES}
SETTING = {"openhours": ("daily_forecast", "openhours_table"), "avg_demand": ("sel2_pipeline", "avg_demand_table"),
           "avg_demand_hist": ("sel2_pipeline", "avg_demand_hist_table"),
           "product_names": ("bigquery", "product_names_table")}


def _fake(extra=None, **kw):
    return FakeBQ(schema=REAL_D1, tables={**REAL, **(extra or {})}, **kw)


def test_defaults_are_exactly_the_tables_used_by_1_4_8():
    assert ss.get("daily_forecast").openhours_table == OH
    assert ss.get("sel2_pipeline").avg_demand_table == AVG
    assert ss.get("sel2_pipeline").avg_demand_hist_table == AVG_H
    assert ss.get("bigquery").product_names_table == NAMES
    st = source_tables.status()
    assert {k: st[k]["table_id"] for k in AUX} == AUX
    assert all(st[k]["last_check"] is None and not st[k]["ok"] for k in AUX)
    assert st["openhours"]["setting"] == "daily_forecast.openhours_table"


def test_a_stored_short_product_names_table_keeps_working_and_shows_its_full_id():
    # what 1.4.8 stored (the old default) on the production installation: joined with project / dataset of D-1
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm",
                           "product_names_table": "dim_sku"})
    bq = ss.get("bigquery")
    assert product_names.source_table(bq) == NAMES
    assert source_tables.current_id("product_names") == NAMES
    # a full id is used as is, whatever the D-1 dataset
    ss.update("bigquery", {"product_names_table": "other-project-1.ref.sku_names"})
    assert product_names.source_table(ss.get("bigquery")) == "other-project-1.ref.sku_names"


@pytest.mark.parametrize("kind", list(AUX))
def test_the_real_layouts_pass_the_check_metadata_only(client, kind):
    fake = _bq_ready(_fake())
    r = client.post(f"/api/bigquery/source-tables/{kind}/check", json={"table_id": AUX[kind]}).json()
    assert r["status"] == "PASSED", r
    assert fake.queries == []                                           # metadata only: no query, no cost
    st = client.get("/api/bigquery/source-tables").json()
    assert st[kind]["ok"] and st[kind]["last_check"]["table_id"] == AUX[kind]


@pytest.mark.parametrize("kind,missing", [("openhours", "total_open_hours"), ("openhours", "item_code"),
                                          ("avg_demand", "ingest_time"), ("avg_demand", "product_name"),
                                          ("avg_demand_hist", "transformed_at"), ("product_names", "product_name")])
def test_a_table_missing_a_column_the_code_reads_fails_and_is_never_saved(client, kind, missing):
    other = "lakehouse-prod-394907.gold_buymed_vn2.other_table"
    cols = [c for c in REAL[AUX[kind]] if c[0] != missing]
    _bq_ready(_fake({other: cols}))
    r = client.put(f"/api/bigquery/source-tables/{kind}", json={"table_id": other})
    assert r.status_code == 409 and r.json()["code"] == "BQ_TABLE_CHECK_FAILED"
    section, key = SETTING[kind]
    assert getattr(ss.get(section), key) == AUX[kind]                   # unchanged, no fallback
    lc = source_tables.last_check(kind)
    assert lc["status"] == "FAILED" and {"code": "COLUMN_NOT_FOUND", "field": kind, "column": missing} in lc["errors"]


@pytest.mark.parametrize("kind,col,typ", [("openhours", "open_date", "TIMESTAMP"), ("openhours", "seller_code", "INTEGER"),
                                          ("openhours", "total_open_hours", "STRING"), ("avg_demand", "avg_demand", "STRING"),
                                          ("avg_demand_hist", "transformed_at", "DATE")])
def test_an_incompatible_type_fails(client, kind, col, typ):
    other = "lakehouse-prod-394907.gold_buymed_vn2.other_table"
    cols = [(n, typ if n == col else t) for n, t in REAL[AUX[kind]]]
    _bq_ready(_fake({other: cols}))
    r = source_tables.check(kind, other)
    assert r["status"] == "FAILED" and [e["code"] for e in r["errors"]] == ["TYPE_INCOMPATIBLE"]
    assert r["errors"][0]["column"] == col


def test_wrong_location_and_invalid_id_fail(client):
    _bq_ready(_fake(location="US"))
    r = source_tables.check("openhours", OH)
    assert r["status"] == "FAILED" and r["errors"][0]["code"] == "BQ_LOCATION_MISMATCH"
    r = client.put("/api/bigquery/source-tables/avg_demand", json={"table_id": "fact_avg_demand_sku"})
    assert r.status_code == 422 and r.json()["code"] == "BQ_TABLE_ID_INVALID"
    assert client.post("/api/bigquery/source-tables/nope/check", json={"table_id": OH}).status_code == 422


@pytest.mark.parametrize("kind", list(AUX))
def test_a_passed_table_is_saved_with_settings_history(client, kind):
    new = "company-prod-01.sales_dw.new_table"
    _bq_ready(_fake({new: REAL[AUX[kind]]}))
    section, key = SETTING[kind]
    n0 = len(ss.history(section, 500))
    r = client.put(f"/api/bigquery/source-tables/{kind}", json={"table_id": new})
    assert r.status_code == 200, r.text
    assert getattr(ss.get(section), key) == new and r.json()[kind]["ok"] and r.json()[kind]["table_id"] == new
    h = ss.history(section, 500)
    assert len(h) == n0 + 1 and h[0]["value"][key] == new and new in h[0]["note"]
    again = client.put(f"/api/bigquery/source-tables/{kind}", json={"table_id": new})
    assert again.status_code == 200 and len(ss.history(section, 500)) == n0 + 1      # same id: nothing re-saved


def test_product_names_check_uses_the_configured_key_and_name_columns(client):
    other = "company-prod-01.ref.sku_names"
    _bq_ready(_fake({other: [("code", "STRING"), ("ten", "STRING")]}))
    assert source_tables.check("product_names", other)["status"] == "FAILED"
    ss.update("bigquery", {"product_names_key_column": "code", "product_names_name_column": "ten"})
    assert source_tables.check("product_names", other)["status"] == "PASSED"


# ------------------------------------------------------------------ the six-key open-hours rule follows the D-1 table
def _six(scope):
    return [(scope, "BIGQUERY", r["business_date"], r["sku_id"], r["fc_id"], r["approved_qty"], r["approved_orders"],
             ovr.APPROVED_LOADED_AT, None, "MULTI_ITEM") for r in ovr.approved()]


def _insert(rows):
    with db.tx() as c:
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at, "
                      "open_hours, open_hours_status) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)


def test_the_rule_scope_is_identical_with_the_production_d1_table():
    assert ovr.current_scope_key() == ovr.SCOPE_KEY                  # no D-1 table configured: the evidence scope
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm"})
    assert ovr.current_scope_key() == ovr.SCOPE_KEY == bigquery_scope_key(ss.get("bigquery"))
    _insert(_six(ovr.SCOPE_KEY))
    with db.read() as c:
        res = ovr.resolve(c, ovr.SCOPE_KEY, "2026-01-01", "2026-10-20")
    assert res["applies_to_scope"] and len(res["applied"]) == 6 and res["not_applied"] == []


def test_a_renamed_d1_table_keeps_the_rule_and_the_old_name_no_longer_applies():
    ss.update("bigquery", {"project_id": "company-prod-01", "dataset_id": "sales_dw", "source_table": "so_lines_daily"})
    new_scope = bigquery_scope_key(ss.get("bigquery"))
    assert ovr.current_scope_key() == new_scope != ovr.SCOPE_KEY
    _insert(_six(new_scope) + _six(ovr.SCOPE_KEY))
    with db.read() as c:
        res = ovr.resolve(c, new_scope, "2026-01-01", "2026-10-20")
        old = ovr.resolve(c, ovr.SCOPE_KEY, "2026-01-01", "2026-10-20")
    assert res["applies_to_scope"] and len(res["applied"]) == 6
    assert [a["selected_hours"] for a in res["applied"]] == [24.0, 24.0, 24.0, 24.0, 24.0, 22.85]
    assert not old["applies_to_scope"] and old["applied"] == []
    # the per-load verification follows the same scope
    assert ovr.verify_load(new_scope, [], "2026-01-01", "2026-10-20") is not None
    assert ovr.verify_load(ovr.SCOPE_KEY, [], "2026-01-01", "2026-10-20") is None


def test_data_check_keeps_the_six_key_result_with_a_renamed_d1_table():
    # data_checks._open_hours_checks resolves the rule with current_scope_key(c) on its read-only connection: with a
    # renamed D-1 table the six approved rows of that scope are covered (not counted as not ready), rows of the old
    # production name are not, and a changed approved row of the new scope is named with its reason
    from app import data_checks, paths
    ss.update("bigquery", {"project_id": "company-prod-01", "dataset_id": "sales_dw", "source_table": "so_lines_daily"})
    new_scope = bigquery_scope_key(ss.get("bigquery"))
    assert new_scope != ovr.SCOPE_KEY
    _insert(_six(new_scope))
    chk = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
    assert chk["open_hours_owner_override"]["status"] == "OK" and chk["open_hours_owner_override"]["count"] == 0
    assert [e[3] for e in chk["open_hours_owner_override"]["examples"]] == [24.0, 24.0, 24.0, 24.0, 24.0]
    assert chk["open_hours_window_ready"]["status"] == "OK" and chk["open_hours_window_ready"]["count"] == 0
    # the same six rows stored under the old production name are not covered any more (they block as before)
    _insert(_six(ovr.SCOPE_KEY))
    chk = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
    assert chk["open_hours_owner_override"]["count"] == 0
    assert chk["open_hours_window_ready"]["status"] == "WARN" and chk["open_hours_window_ready"]["count"] == 6
    assert {tuple(r[:2]) for r in chk["open_hours_window_ready"]["examples"]} == {(ovr.SCOPE_KEY, "MULTI_ITEM")}
    # a changed approved row of the configured scope is not covered and says why
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET n_orders = n_orders + 3 WHERE scope_key=? AND sku_id='MEDX.SOP-NEO-001'",
                  (new_scope,))
    chk = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
    assert chk["open_hours_owner_override"]["status"] == "WARN"
    assert chk["open_hours_owner_override"]["examples"] == [["2026-03-02", "MEDX.SOP-NEO-001", "BD", "CONTENT_CHANGED"]]
    assert chk["open_hours_window_ready"]["count"] == 7
