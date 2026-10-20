"""REAL BigQuery check (1.2.9, fifth batch) of the owner's rule on item codes, on INLINE rows through the history-SQL
path (0 bytes, nothing read from a table, nothing written): the D-1 query gives the same open-hours status whatever the
item suffixes are - .1/.2, swapped, other numbers, codes without any suffix - because it only counts distinct items.
The suffix is the order in which the SKU was opened for sale in the regions, not a region code. Opt-in: ADC of this
Windows account and `DF_REAL_BQ=1`.

    cd backend; $env:DF_REAL_BQ = "1"; ..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider tests\\test_v129e_real_bq_item_suffix.py
"""
import os
from datetime import date

import pytest

from app import settings_service as ss
from app.bq import connector
from app.data import open_hours

pytestmark = pytest.mark.skipif(os.environ.get("DF_REAL_BQ") != "1",
                                reason="real BigQuery (ADC of this Windows account): set DF_REAL_BQ=1")

COLS = "so_code STRING, created_date DATE, sku_code STRING, fc_code STRING, item_code STRING, demand_quantity FLOAT64, " \
       "sales_price FLOAT64, total_open_hours FLOAT64"
D = "DATE '2026-10-02'"
# (so_code, sku, fc, item, qty, hours): every SKU has two items with different hours, named differently
ROWS = [("O01", "A", "F1", "A.1", 2, 5.0), ("O02", "A", "F1", "A.2", 1, 24.0),          # usual suffixes
        ("O03", "B", "F1", "B.2", 2, 5.0), ("O04", "B", "F1", "B.1", 1, 24.0),          # swapped suffixes
        ("O05", "C", "F1", "C.7", 2, 5.0), ("O06", "C", "F1", "C.3", 1, 24.0),          # other numbers
        ("O07", "D", "F1", "ITEM-X", 2, 5.0), ("O08", "D", "F1", "ITEM-Y", 1, 24.0),    # no suffix at all
        ("O09", "E", "F1", "E.1", 2, 24.0), ("O10", "E", "F2", "E.2", 1, 5.0),          # one item per FC: OK in both
        ("O11", "G", "F1", "G.1", 2, 5.0), ("O12", "G", "F1", "G.1", 1, 24.0)]          # one item, two values


def _sql() -> str:
    body = ",\n  ".join(f"('{so}', {D}, '{s}', '{f}', '{i}', {q}, 10.0, {h})" for so, s, f, i, q, h in ROWS)
    return f"SELECT * FROM UNNEST(ARRAY<STRUCT<{COLS}>>[\n  {body}\n])"


def test_real_bigquery_status_is_the_same_whatever_the_item_suffix():
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm",
                           "location": "asia-southeast1", "partition_column": "", "maximum_bytes_billed": 10 * 1024 ** 2})
    ss.update("data_policy", {"window_start_date": "2026-01-01"})
    sql = _sql()
    cols = connector.sql_dry_run(sql)["columns"]
    sug = connector.suggest_mapping(cols)
    ref = sug["reference_mapping"]
    ref["item_code"] = {"column": "item_code", "usage": "OPTIONAL"}
    ss.update("bigquery", {"field_mapping": sug["field_mapping"], "reference_mapping": ref})
    snap = {"mode": "SQL", "kind": "history", "version_id": 0, "sha256": "inline-test", "sql": sql,
            "key_columns": ["so_code", "sku_code", "fc_code", "created_date"], "key_duplicate_policy": "SUM_ALL"}
    res = connector.fetch_daily(date(2026, 10, 2), date(2026, 10, 2), snap)
    assert res["estimated_bytes"] == 0
    got = {(r["sku_id"], r["fc_id"]): r for r in res["rows"]}
    st = {k: open_hours.row_cell(r) for k, r in got.items()}
    for sku in ("A", "B", "C", "D"):
        assert st[(sku, "F1")] == (None, "MULTI_ITEM"), sku
        assert (got[(sku, "F1")]["open_hours_items"], got[(sku, "F1")]["open_hours_item_values"]) == (2, 2)
        assert float(got[(sku, "F1")]["qty"]) == 3.0
    assert st[("E", "F1")] == (24.0, "OK") and st[("E", "F2")] == (5.0, "OK")
    assert st[("G", "F1")] == (None, "CONFLICT")
    assert "ITEM-X" not in repr(res["rows"]) and "A.1" not in repr(res["rows"])    # no item code leaves BigQuery
