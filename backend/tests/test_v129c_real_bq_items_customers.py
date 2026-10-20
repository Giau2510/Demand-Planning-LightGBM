"""REAL BigQuery check (1.2.9b) of the two additions to the D-1 query, on INLINE rows: the source is a literal
`UNNEST(ARRAY<STRUCT<...>>[...])` run through the history-SQL path, so no table is read (0 bytes) and nothing is written
anywhere. Opt-in: needs Google credentials of this Windows account (ADC) and `DF_REAL_BQ=1`.

* open hours per item: values that differ only BETWEEN items -> MULTI_ITEM; the same item with two values, or a line
  without item code -> CONFLICT (data/open_hours.py);
* customer counts per day x SKU x FC from a customer column, with the 90-day look-back before the window, blank / NULL
  identifiers not counted, and NO identifier in what BigQuery returns (data/customers.py). The identifiers below are
  made up for this test.

    cd backend; $env:DF_REAL_BQ = "1"; ..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider tests\\test_v129c_real_bq_items_customers.py
"""
import json
import os
from datetime import date

import pytest

from app import settings_service as ss
from app.bq import connector
from app.data import customers, open_hours

pytestmark = pytest.mark.skipif(os.environ.get("DF_REAL_BQ") != "1",
                                reason="real BigQuery (ADC of this Windows account): set DF_REAL_BQ=1")

COLS = ("so_code STRING, created_date DATE, sku_code STRING, fc_code STRING, item_code STRING, customer_code STRING, "
        "demand_quantity FLOAT64, sales_price FLOAT64, total_open_hours FLOAT64")
D0, D1, D2 = "DATE '2026-08-01'", "DATE '2026-10-01'", "DATE '2026-10-02'"
OLD = "DATE '2026-06-01'"
ROWS = [  # so_code, day, sku, fc, item, customer, qty, open hours
    ("O01", D2, "TWO", "F1", "TWO.1", "CUST-A", 2, 18.22), ("O02", D2, "TWO", "F1", "TWO.1", "CUST-A", 1, 18.22),
    ("O03", D2, "TWO", "F1", "TWO.2", "CUST-B", 1, 22.85), ("O04", D2, "TWO", "F1", "TWO.2", "CUST-C", 3, 22.85),
    ("O05", D2, "SELF", "F1", "SELF.1", None, 1, 5.0), ("O06", D2, "SELF", "F1", "SELF.1", None, 1, 9.0),
    ("O07", D2, "SAME", "F1", "SAME.1", "CUST-D", 2, 24.0), ("O08", D2, "SAME", "F1", "SAME.2", "  ", 1, 24.0),
    ("O09", D2, "SAME", "F1", "SAME.2", None, 1, 24.0),
    ("O10", D2, "NOITEM", "F1", None, "CUST-E", 1, 5.0), ("O11", D2, "NOITEM", "F1", "NOITEM.1", "CUST-E", 1, 9.0),
    ("O12", D2, "TWO", "F2", "TWO.2", "CUST-A", 4, 22.85),          # same customer, other FC: not a repeat there
    ("O13", D1, "SAME", "F1", "SAME.1", "CUST-D", 1, 24.0),         # CUST-D again the next day: repeat, 1 day
    ("O14", D0, "TWO", "F1", "TWO.1", "CUST-A", 1, 24.0),           # before the window, inside the 90-day look-back
    ("O15", OLD, "TWO", "F1", "TWO.2", "CUST-B", 1, 24.0),          # 123 days before: outside the look-back
]


def _sql(rows) -> str:
    def v(x):
        return "NULL" if x is None else repr(x)
    body = ",\n  ".join(f"('{so}', {d}, '{sku}', '{fc}', {v(it)}, {v(cu)}, {q}, 10.0, {v(h)})"
                        for so, d, sku, fc, it, cu, q, h in rows)
    return f"SELECT * FROM UNNEST(ARRAY<STRUCT<{COLS}>>[\n  {body}\n])"


def test_real_bigquery_multi_item_and_customer_counts_with_no_identifier_returned():
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm",
                           "location": "asia-southeast1", "partition_column": "", "maximum_bytes_billed": 10 * 1024 ** 2})
    ss.update("data_policy", {"window_start_date": "2026-01-01"})
    sql = _sql(ROWS)
    cols = connector.sql_dry_run(sql)["columns"]
    sug = connector.suggest_mapping(cols)
    ref = sug["reference_mapping"]
    ref["item_code"] = {"column": "item_code", "usage": "OPTIONAL"}
    ss.update("bigquery", {"field_mapping": sug["field_mapping"], "reference_mapping": ref,
                           "customer_id_column": "customer_code"})
    assert connector.validate_mapping(cols)["ok"] and customers.check_column(cols, "customer_code") == []
    snap = {"mode": "SQL", "kind": "history", "version_id": 0, "sha256": "inline-test", "sql": sql,
            "key_columns": ["so_code", "sku_code", "fc_code", "created_date"], "key_duplicate_policy": "SUM_ALL"}
    res = connector.fetch_daily(date(2026, 10, 1), date(2026, 10, 2), snap)
    assert res["estimated_bytes"] == 0
    got = {(str(r["order_date"]), r["sku_id"], r["fc_id"]): r for r in res["rows"]}
    oh = {k: open_hours.row_cell(r) for k, r in got.items()}
    assert oh[("2026-10-02", "TWO", "F1")] == (None, "MULTI_ITEM")
    assert oh[("2026-10-02", "SELF", "F1")] == (None, "CONFLICT")
    assert oh[("2026-10-02", "SAME", "F1")] == (24.0, "OK")
    assert oh[("2026-10-02", "NOITEM", "F1")] == (None, "CONFLICT")
    cnt = {k: customers.stored(r) for k, r in got.items()}
    assert cnt[("2026-10-02", "TWO", "F1")] == (3, 1, 62.0)          # A (prev 01/08: 62 days), B (prev > 90 days), C
    assert cnt[("2026-10-02", "TWO", "F2")] == (1, 0, 0.0)           # A at another FC: not a repeat of THIS series
    assert cnt[("2026-10-02", "SAME", "F1")] == (1, 1, 1.0)          # D (prev 01/10); blank / NULL ids not counted
    assert cnt[("2026-10-01", "SAME", "F1")] == (1, 0, 0.0)
    assert cnt[("2026-10-02", "SELF", "F1")] == (None, None, None)   # no identifier at all: unknown, not 0
    assert float(got[("2026-10-02", "SAME", "F1")]["qty"]) == 4.0     # lines without identifier still count in demand
    assert "CUST-" not in json.dumps(res["rows"], default=str)       # no identifier leaves BigQuery
    assert ("2026-08-01", "TWO", "F1") not in got                    # the look-back is read, never returned
