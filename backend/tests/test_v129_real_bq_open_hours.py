"""REAL BigQuery check (1.2.9) of the SKU open-hours aggregation the D-1 load sends, on INLINE rows: the source is a
literal `UNNEST(ARRAY<STRUCT<...>>[...])` run through the history-SQL path, so no table is read (0 bytes) and nothing
is written anywhere. Opt-in: needs Google credentials of this Windows account (ADC) and `DF_REAL_BQ=1`.

    cd backend; $env:DF_REAL_BQ = "1"; ..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider tests\\test_v129_real_bq_open_hours.py
"""
import os
from datetime import date

import pytest

from app import settings_service as ss
from app.bq import connector
from app.data import open_hours

pytestmark = pytest.mark.skipif(os.environ.get("DF_REAL_BQ") != "1",
                                reason="real BigQuery (ADC of this Windows account): set DF_REAL_BQ=1")

COLS = ("so_code STRING, created_date DATE, sku_code STRING, fc_code STRING, demand_quantity FLOAT64, "
        "sales_price FLOAT64, total_open_hours FLOAT64, total_open_days FLOAT64")
D1, D2 = "DATE '2026-10-01'", "DATE '2026-10-02'"
ROWS = [  # so_code, day, sku, qty, open hours
    ("'O1'", D1, "ALL24", 5, 24.0), ("'O2'", D1, "ALL24", 3, 24.0),          # OK 24 (two lines agree)
    ("'O3'", D1, "ZERO", 1, 0.0),                                            # OK 0 (closed all day is a value)
    ("'O4'", D1, "PART", 2, 13.85),                                          # OK 13.85
    ("'O5'", D1, "NULL1", 4, None), ("'O6'", D1, "NULL1", 1, 24.0),          # MISSING (one line without a value)
    ("'O7'", D1, "NULLALL", 2, None),                                        # MISSING (no value at all)
    ("'O8'", D1, "DIFF", 1, 19.37), ("'O9'", D1, "DIFF", 1, 24.0),           # CONFLICT (lines disagree)
    ("'P1'", D1, "BIG", 3, 25.5), ("'P2'", D1, "NEG", 3, -1.0),              # OUT_OF_RANGE
    ("'P3'", D2, "ALL24", 7, 24.0),                                          # another day, same SKU
]


def _sql(rows) -> str:
    def v(x):
        return "NULL" if x is None else repr(x)
    body = ",\n  ".join(f"({so}, {d}, '{sku}', 'F1', {q}, 10.0, {v(h)}, {v(None if h is None else h / 24)})"
                        for so, d, sku, q, h in rows)
    return f"SELECT * FROM UNNEST(ARRAY<STRUCT<{COLS}>>[\n  {body}\n])"


def test_real_bigquery_open_hours_per_day_sku_fc():
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm",
                           "location": "asia-southeast1", "partition_column": "", "maximum_bytes_billed": 10 * 1024 ** 2})
    sql = _sql(ROWS)
    cols = connector.sql_dry_run(sql)["columns"]                  # real dry run: the output schema of the rows
    sug = connector.suggest_mapping(cols)
    assert sug["reference_mapping"]["open_hours"]["column"] == "total_open_hours"
    ss.update("bigquery", {"field_mapping": sug["field_mapping"], "reference_mapping": sug["reference_mapping"]})
    assert connector.validate_mapping(cols)["ok"]
    snap = {"mode": "SQL", "kind": "history", "version_id": 0, "sha256": "inline-test", "sql": sql,
            "key_columns": ["so_code", "sku_code", "fc_code", "created_date"], "key_duplicate_policy": "SUM_ALL"}
    res = connector.fetch_daily(date(2026, 10, 1), date(2026, 10, 2), snap)
    assert res["estimated_bytes"] == 0 and res["rows_valid"] == len(ROWS)
    got = {(str(r["order_date"]), r["sku_id"]): open_hours.cell(r["open_hours_null_rows"], r["open_hours_min"],
                                                                r["open_hours_max"]) for r in res["rows"]}
    assert got == {("2026-10-01", "ALL24"): (24.0, "OK"), ("2026-10-01", "ZERO"): (0.0, "OK"),
                   ("2026-10-01", "PART"): (13.85, "OK"), ("2026-10-01", "NULL1"): (None, "MISSING"),
                   ("2026-10-01", "NULLALL"): (None, "MISSING"), ("2026-10-01", "DIFF"): (None, "CONFLICT"),
                   ("2026-10-01", "BIG"): (None, "OUT_OF_RANGE"), ("2026-10-01", "NEG"): (None, "OUT_OF_RANGE"),
                   ("2026-10-02", "ALL24"): (24.0, "OK")}
    qty = {(str(r["order_date"]), r["sku_id"]): float(r["qty"]) for r in res["rows"]}
    assert qty[("2026-10-01", "ALL24")] == 8.0 and qty[("2026-10-01", "NULL1")] == 5.0     # demand unchanged by hours
