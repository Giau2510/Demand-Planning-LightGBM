"""REAL BigQuery checks of the 1.2.1 D-0 feed (opt-in: DF_REAL_BQ=1 and Google credentials of this Windows account).

1. Inline rows (`UNNEST(ARRAY<STRUCT<...>>)`: 0 bytes, no table read) with column names that differ from D-1, run
   through the exact path of a D-0 validation (real dry run + D-0 mapping check + real execution of today's aggregate):
   the Vietnam-day filter, OTHER_DAY / NULL / negative rows, exact and key duplicates, the TIMESTAMP -> Vietnam day.
2. The real D-0 table `demand_planing_lightgbm_D0` (about 76 KB) with the default D-0 mapping.
3. Real BigQuery errors: syntax error, missing table.
Nothing is written anywhere (d0_feed._check_text records nothing; the test DB is a temporary copy).

    cd backend; $env:DF_REAL_BQ = "1"; ..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider tests\\test_v121_d0_real_bq.py
"""
import os
from datetime import timedelta

import pytest

from app import settings_service as ss
from app import timeutil
from app.bq import d0_feed
from app.messages import AppError

pytestmark = pytest.mark.skipif(os.environ.get("DF_REAL_BQ") != "1",
                                reason="real BigQuery (ADC of this Windows account): set DF_REAL_BQ=1")
D0 = "lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm_D0"


def _setup(mapping=None, exact="BLOCK"):
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm",
                           "location": "asia-southeast1", "partition_column": "created_date",
                           "maximum_bytes_billed": 10 * 1024 ** 2, "exact_duplicate_policy": exact,
                           **({"d0_mapping": mapping} if mapping else {})})
    cfg = ss.get("sql_sources")
    cfg.d0.key_duplicate_policy = "BLOCK"
    ss.save("sql_sources", cfg)


OWN = {"sku_id": {"column": "ma_sku"}, "fc_id": {"column": "kho"}, "order_qty": {"column": "sl"},
       "order_date": {"column": "ngay"}, "created_at": {"column": None, "usage": "UNUSED"},
       "order_id": {"column": "ma_don"}, "source_updated_at": {"column": None}}


def _inline(today):
    y = today - timedelta(days=1)
    t, d = f"DATE '{today}'", f"DATE '{y}'"
    rows = [("'O1'", t, "'A'", "'K1'", 5), ("'O2'", t, "'A'", "'K1'", 3),           # A|K1 = 8 (two orders)
            ("'O3'", t, "'B'", "'K2'", 2), ("'O3'", t, "'B'", "'K2'", 2),           # exact duplicate (and same key)
            ("'O4'", t, "'C'", "NULL", 4),                                           # NULL_FC
            ("'O5'", t, "'D'", "'K1'", -1),                                          # NEGATIVE_TARGET
            ("'O6'", d, "'A'", "'K1'", 100),                                         # OTHER_DAY (yesterday)
            ("'O7'", "NULL", "'A'", "'K1'", 7)]                                      # NULL_DATE
    body = ",\n  ".join(f"({a}, {b}, {c}, {e}, {q}, 1.5, 'x')" for a, b, c, e, q in rows)
    # no sales price / status / seller / open-date columns: the D-0 output only needs its own essentials
    return ("SELECT * FROM UNNEST(ARRAY<STRUCT<ma_don STRING, ngay DATE, ma_sku STRING, kho STRING, sl INT64, "
            f"gia FLOAT64, ghi_chu STRING>>[\n  {body}\n])")


def test_real_bigquery_d0_today_filter_exclusions_and_duplicates():
    _setup(OWN)
    today = timeutil.today_vn()
    out = d0_feed._check_text(_inline(today), today)
    assert out["statement_type"] == "SELECT" and out["mapping_check"]["ok"]
    assert out["mapping_check"]["ignored_columns"] == ["ghi_chu", "gia"] or \
        sorted(out["mapping_check"]["ignored_columns"]) == ["ghi_chu", "gia"]
    ex = out["execution"]
    rows = {(r["sku_id"], r["fc_id"]): (r["cumulative_qty"], r["n_rows"]) for r in out["_rows"]}
    assert rows == {("A", "K1"): (8.0, 2), ("B", "K2"): (4.0, 2)}
    assert ex["rows_read"] == 8 and ex["rows_valid"] == 4 and ex["rows_other_day"] == 1 and ex["rows_error"] == 3
    assert {k: v["rows"] for k, v in ex["excluded_by_reason"].items()} == {
        "NULL_FC": 1, "NEGATIVE_TARGET": 1, "OTHER_DAY": 1, "NULL_DATE": 1}
    assert ex["exact_duplicate_rows"] == 1 and ex["key_duplicate_rows"] == "1"
    assert {i["code"] for i in ex["blocking_issues"]} == {"EXACT_DUPLICATES", "KEY_NOT_UNIQUE"}
    assert ex["dates_in_output"][str(today)]["rows"] == 6 and ex["warnings"][0]["code"] == "D0_ROWS_OTHER_THAN_TODAY"
    # DROP_EXACT: the identical row is counted once, the key is then unique
    _setup(OWN, exact="DROP_EXACT")
    out = d0_feed._check_text(_inline(today), today)
    rows = {(r["sku_id"], r["fc_id"]): r["cumulative_qty"] for r in out["_rows"]}
    assert rows[("B", "K2")] == 2.0 and out["execution"]["rows_dropped_duplicates"] == 1
    assert out["execution"]["key_duplicate_rows"] == "0" and out["execution"]["blocking_issues"] == []


def test_real_bigquery_timestamp_is_turned_into_the_vietnam_day():
    today = timeutil.today_vn()
    y = today - timedelta(days=1)
    m = {**OWN, "order_date": {"column": None, "usage": "UNUSED"}, "created_at": {"column": "tg"}}
    _setup(m)
    # 17:30 UTC of yesterday = 00:30 today in Vietnam (counts); 16:30 UTC of yesterday = 23:30 yesterday (does not)
    sql = ("SELECT * FROM UNNEST(ARRAY<STRUCT<ma_don STRING, tg TIMESTAMP, ma_sku STRING, kho STRING, sl INT64>>["
           f"('T1', TIMESTAMP '{y} 17:30:00+00', 'A', 'K1', 2), ('T2', TIMESTAMP '{y} 16:30:00+00', 'A', 'K1', 9)])")
    out = d0_feed._check_text(sql, today)
    assert [(r["sku_id"], r["cumulative_qty"]) for r in out["_rows"]] == [("A", 2.0)]
    assert out["execution"]["rows_other_day"] == 1


def test_real_bigquery_the_d0_table_validates_with_the_default_d0_mapping():
    _setup()
    today = timeutil.today_vn()
    sql = f"SELECT * FROM `{D0}` WHERE created_date = CURRENT_DATE('Asia/Ho_Chi_Minh')"
    out = d0_feed._check_text(sql, today)
    names = [c["name"] for c in out["columns"]]
    assert {"sku_code", "fc_code", "demand_quantity", "created_date", "so_code"} <= set(names)
    assert "seller_class" not in names and "refresh_time" not in names         # fewer columns than D-1: fine
    assert out["mapping_check"]["ok"] and out["referenced_tables"]
    ex = out["execution"]
    assert ex["rows_other_day"] == 0 and set(ex["dates_in_output"]) <= {str(today)}
    print("REAL_D0", {k: ex[k] for k in ("day", "rows_read", "rows_valid", "rows_error", "n_series", "qty_valid",
                                         "key_duplicate_rows", "exact_duplicate_rows", "estimated_bytes")},
          [i["code"] for i in ex["blocking_issues"]])


@pytest.mark.parametrize("sql,code", [("SELECT sku_code FROM", "BQ_SQL_ERROR"),
                                      (f"SELECT * FROM `{D0}_does_not_exist`", "BQ_NOT_FOUND")])
def test_real_bigquery_errors_are_classified(sql, code):
    _setup()
    with pytest.raises(AppError) as e:
        d0_feed._check_text(sql, timeutil.today_vn())
    assert e.value.code == code, e.value.detail
