"""REAL BigQuery check (21/10/2026) of the open-hours aggregation on INLINE rows shaped like the 6 MULTI_ITEM keys of the
D-1 source (synthetic SKU codes, the real hours and line patterns; every item code is the SKU's listing in one sales
region, both listings fulfilled by the same FC). Goes through the history-SQL path: a literal UNNEST, 0 bytes, no table
read, nothing written. Opt-in: ADC of this Windows account and `DF_REAL_BQ=1`.

* the FC is fc_code: the same SKU and day in another FC, where one listing was sold, keeps that listing's value;
* several valid items of one key with different hours -> MULTI_ITEM, no value (no rule approved, owner 21/10/2026);
* several lines (orders) of one item, or items with equal hours -> exactly one value;
* inconsistent hours (one item with two values, a line without item code, out of range, missing) are detected;
* the customer-counts join (customer column mapped) never multiplies a line: same keys, quantities, line counts and
  open-hours statuses as without it; no quantity is lost or doubled.

    cd backend; $env:DF_REAL_BQ = "1"; ..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider tests\\test_v1210_real_bq_multi_item_regions.py
"""
import os
from datetime import date

import pytest

from app import settings_service as ss
from app.bq import connector
from app.data import open_hours

pytestmark = pytest.mark.skipif(os.environ.get("DF_REAL_BQ") != "1",
                                reason="real BigQuery (ADC of this Windows account): set DF_REAL_BQ=1")

COLS = ("so_code STRING, created_date DATE, sku_code STRING, fc_code STRING, item_code STRING, order_status STRING, "
        "demand_quantity FLOAT64, sales_price FLOAT64, total_open_hours FLOAT64, customer_id INT64")
DAY = date(2026, 10, 2)
ROWS = [  # sku, fc, item, qty, open hours - one line per order
    # K1 = 09/02 HN: .1 (1 line) + .2 (3 lines) in HN; .1 also sold through BD
    ("K1", "HN", "K1.1", 2, 23.92), ("K1", "HN", "K1.2", 2, 24.0), ("K1", "HN", "K1.2", 2, 24.0),
    ("K1", "HN", "K1.2", 2, 24.0), ("K1", "BD", "K1.1", 1, 23.92), ("K1", "BD", "K1.1", 3, 23.92),
    # K2 = 10/02 HN: items .1 and .3
    ("K2", "HN", "K2.1", 1, 21.16), ("K2", "HN", "K2.3", 10, 24.0), ("K2", "BD", "K2.1", 3, 21.16),
    # K3 = 02/03 BD: .1 (3 lines) + .2; .2 also in HN
    ("K3", "BD", "K3.1", 26, 5.0), ("K3", "BD", "K3.1", 26, 5.0), ("K3", "BD", "K3.1", 26, 5.0),
    ("K3", "BD", "K3.2", 10, 24.0), ("K3", "HN", "K3.2", 4, 24.0), ("K3", "HN", "K3.2", 5, 24.0),
    # K4 = 02/03 BD (second SKU)
    ("K4", "BD", "K4.1", 1, 1.7), ("K4", "BD", "K4.1", 1, 1.7), ("K4", "BD", "K4.2", 1, 24.0), ("K4", "HN", "K4.2", 2, 24.0),
    # K5 = 26/08 BD
    ("K5", "BD", "K5.1", 20, 23.72), ("K5", "BD", "K5.1", 20, 23.72), ("K5", "BD", "K5.2", 2, 24.0),
    # K6 = 26/08 BD: .1 (3 lines) + .2; .2 also in HN
    ("K6", "BD", "K6.1", 1, 22.85), ("K6", "BD", "K6.1", 1, 22.85), ("K6", "BD", "K6.1", 1, 22.85),
    ("K6", "BD", "K6.2", 1, 18.22), ("K6", "HN", "K6.2", 1, 18.22), ("K6", "HN", "K6.2", 2, 18.22),
    # valid single values
    ("V1", "BD", "V1.1", 1, 12.5), ("V1", "BD", "V1.1", 2, 12.5), ("V1", "BD", "V1.1", 3, 12.5),   # 3 orders, 1 item
    ("V2", "BD", "V2.1", 1, 24.0), ("V2", "BD", "V2.2", 4, 24.0),                                   # 2 items, same hours
    # inconsistent / not attributable
    ("X1", "BD", "X1.1", 1, 5.0), ("X1", "BD", "X1.1", 1, 6.0),          # one item, two values
    ("X2", "BD", "X2.1", 1, 5.0), ("X2", "BD", None, 1, 6.0),            # a line without item code
    ("X3", "BD", "X3.1", 1, 25.0),                                       # out of range
    ("X4", "BD", "X4.1", 1, None), ("X4", "BD", "X4.2", 1, 24.0),        # a line without hours
]
EXPECTED = {
    ("K1", "HN"): (None, "MULTI_ITEM"), ("K1", "BD"): (23.92, "OK"),
    ("K2", "HN"): (None, "MULTI_ITEM"), ("K2", "BD"): (21.16, "OK"),
    ("K3", "BD"): (None, "MULTI_ITEM"), ("K3", "HN"): (24.0, "OK"),
    ("K4", "BD"): (None, "MULTI_ITEM"), ("K4", "HN"): (24.0, "OK"),
    ("K5", "BD"): (None, "MULTI_ITEM"),
    ("K6", "BD"): (None, "MULTI_ITEM"), ("K6", "HN"): (18.22, "OK"),
    ("V1", "BD"): (12.5, "OK"), ("V2", "BD"): (24.0, "OK"),
    ("X1", "BD"): (None, "CONFLICT"), ("X2", "BD"): (None, "CONFLICT"), ("X3", "BD"): (None, "OUT_OF_RANGE"),
    ("X4", "BD"): (None, "MISSING"),
}


def _sql() -> str:
    def v(x):
        return "NULL" if x is None else repr(x)
    body = ",\n  ".join(f"('SO{n:03d}', DATE '{DAY}', '{s}', '{f}', {v(i)}, 'COMPLETED', {q}, 10.0, {v(h)}, {100 + n})"
                        for n, (s, f, i, q, h) in enumerate(ROWS))
    return f"SELECT * FROM UNNEST(ARRAY<STRUCT<{COLS}>>[\n  {body}\n])"


def _setup() -> dict:
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm",
                           "location": "asia-southeast1", "partition_column": "", "maximum_bytes_billed": 10 * 1024 ** 2,
                           "exact_duplicate_policy": "BLOCK", "customer_id_column": ""})
    ss.update("data_policy", {"window_start_date": "2026-01-01"})
    sql = _sql()
    sug = connector.suggest_mapping(connector.sql_dry_run(sql)["columns"])
    ref = sug["reference_mapping"]
    ref["item_code"] = {"column": "item_code", "usage": "OPTIONAL"}
    ref["order_status"] = {"column": "order_status", "usage": "OPTIONAL"}
    ss.update("bigquery", {"field_mapping": sug["field_mapping"], "reference_mapping": ref})
    bq = ss.get("bigquery")
    assert bq.field_mapping["fc_id"].column == "fc_code" and bq.field_mapping["sku_id"].column == "sku_code"
    assert bq.reference_mapping["open_hours"].column == "total_open_hours"
    return {"mode": "SQL", "kind": "history", "version_id": 0, "sha256": "inline-test", "sql": sql,
            "key_columns": ["so_code", "sku_code", "fc_code", "created_date"], "key_duplicate_policy": "SUM_ALL"}


def _by_key(res) -> dict:
    return {(r["sku_id"], r["fc_id"]): r for r in res["rows"]}


def test_real_bigquery_multi_item_keys_get_no_value_and_every_other_key_exactly_one():
    snap = _setup()
    res = connector.fetch_daily(DAY, DAY, snap)
    assert res["estimated_bytes"] == 0 and res["exact_duplicate_rows"] == 0
    got = _by_key(res)
    assert {k: open_hours.row_cell(r) for k, r in got.items()} == EXPECTED
    for k, (_, st) in EXPECTED.items():
        if st == "MULTI_ITEM":
            assert (got[k]["open_hours_items"], got[k]["open_hours_item_values"], got[k]["open_hours_no_item_rows"]) == (2, 2, 0)
    assert {f for _, f in got} == {"BD", "HN"}                                        # FCs from fc_code only
    qty = {}
    for s, f, _, q, _ in ROWS:
        qty[(s, f)] = qty.get((s, f), 0) + q
    assert {k: float(r["qty"]) for k, r in got.items()} == qty                       # nothing lost or doubled
    assert {k: r["n_rows"] for k, r in got.items()} == {k: sum(1 for s, f, *_ in ROWS if (s, f) == k) for k in qty}
    assert "K6.1" not in repr(res["rows"])                                            # no item code leaves BigQuery


def test_real_bigquery_customer_counts_join_never_changes_lines_quantities_or_open_hours():
    snap = _setup()
    plain = connector.fetch_daily(DAY, DAY, snap)
    ss.update("bigquery", {"customer_id_column": "customer_id"})
    joined = connector.fetch_daily(DAY, DAY, snap)
    a, b = _by_key(plain), _by_key(joined)
    assert set(a) == set(b) and len(joined["rows"]) == len(plain["rows"]) and joined["qty_read"] == plain["qty_read"]
    for k in a:
        assert (float(b[k]["qty"]), b[k]["n_rows"], open_hours.row_cell(b[k])) == \
               (float(a[k]["qty"]), a[k]["n_rows"], open_hours.row_cell(a[k])), k
        assert b[k]["customer_count"] == a[k]["n_rows"]                                 # one customer per line here
