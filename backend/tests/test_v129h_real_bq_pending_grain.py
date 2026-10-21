"""REAL BigQuery check (master audit, fix 7.1 and the consolidated release 1.2.11, 21/10/2026) of the grain and the
duplicate rule by order status on INLINE rows through the history-SQL path (a literal `UNNEST(ARRAY<STRUCT<...>>[...])`:
0 bytes, no table read, nothing written anywhere). Opt-in: ADC of this Windows account and `DF_REAL_BQ=1`.

* grain day x SKU x FC: the FC is the fc_code column; item suffixes (.1/.2, swapped) never create or merge a key;
  different full SKU codes are never merged; no quantity is duplicated or lost;
* pending orders (WAIT_TO_CONFIRM, with or without so_code; owner rule 21/10/2026, 1.2.11) are EXEMPT: rows identical
  in every compared column - even in every source column, even with the same customer - pass the gate, are counted
  apart and all their quantity is kept (DROP_EXACT too);
* every other status keeps the protection: a real duplicate (an order code, or a NULL code with another status,
  whatever the customers) blocks; item_code is not compared, so an order line fanned out over the SKU's listings blocks;
  mixed statuses never form one group;
* join fan-out: the gate reads the raw rows; the customer counts join (customer column mapped) never multiplies a
  demand row.

    cd backend; $env:DF_REAL_BQ = "1"; ..\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider tests\\test_v129h_real_bq_pending_grain.py
"""
import os
from datetime import date

import pytest

from app import settings_service as ss
from app.bq import connector
from app.data import open_hours
from app.messages import AppError

pytestmark = pytest.mark.skipif(os.environ.get("DF_REAL_BQ") != "1",
                                reason="real BigQuery (ADC of this Windows account): set DF_REAL_BQ=1")

COLS = ("so_code STRING, created_date DATE, sku_code STRING, fc_code STRING, item_code STRING, order_status STRING, "
        "demand_quantity FLOAT64, sales_price FLOAT64, total_open_hours FLOAT64, customer_id INT64")
DAY = date(2026, 10, 2)
W = "WAIT_TO_CONFIRM"
BASE = [  # so_code, sku, fc, item, status, qty, open hours
    ("O01", "A", "F1", "A.1", "COMPLETED", 2, 24.0), ("O02", "A", "F2", "A.1", "COMPLETED", 3, 24.0),   # 1 SKU, 2 FCs
    ("O03", "B", "F1", "B.1", "COMPLETED", 1, 24.0), ("O04", "B", "F1", "B.2", "COMPLETED", 4, 24.0),   # .1/.2, 1 FC
    ("O05", "C", "F1", "C.2", "COMPLETED", 1, 24.0), ("O06", "C", "F1", "C.1", "COMPLETED", 4, 24.0),   # swapped
    ("O07", "D", "F1", "D.1", "COMPLETED", 1, 24.0), ("O08", "D.1", "F1", "D.1.1", "COMPLETED", 2, 24.0),  # 2 SKUs
    ("O09", "E", "F1", "E.1", "COMPLETED", 1, 5.0), ("O10", "E", "F1", "E.2", "COMPLETED", 1, 24.0),    # per item
    (None, "P", "F1", "P.1", W, 2, 24.0), (None, "P", "F1", "P.1", W, 2, 24.0), (None, "P", "F1", "P.1", W, 2, 24.0),
    (None, "Q", "F1", "Q.1", W, 1, 24.0),
]
REAL_DUP = [("O20", "R", "F1", "R.1", "COMPLETED", 1, 24.0)] * 2
NULL_CODE_OTHER_STATUS = [(None, "S", "F1", "S.1", "COMPLETED", 1, 24.0)] * 2
# two pending rows with nothing that tells them apart (same customer: identical in every source column) - exempt
PENDING_SAME_ROW = [(None, "T", "F1", "T.1", W, 2, 24.0, 900)] * 2
# 1.2.11: a pending order WITH an order code, twice identical, and a repeated customer on pending orders - exempt
PENDING_WITH_CODE = [("O30", "U", "F1", "U.1", W, 3, 24.0, 901)] * 2 + [(None, "U", "F1", "U.1", W, 1, 24.0, 901)]
# 1.2.11: an order line fanned out over the SKU's two listings (identical except item_code) - a duplicate
ITEM_FANOUT = [("O40", "V", "F1", "V.1", "COMPLETED", 2, 24.0, 902), ("O40", "V", "F1", "V.2", "COMPLETED", 2, 24.0, 902)]
# 1.2.11: the same order line seen as pending and as completed (a status transition): two statuses, never one group;
# lower case / spaces of the status are the same pending status
MIXED = [("O50", "M", "F1", "M.1", W, 4, 24.0, 903), ("O50", "M", "F1", "M.1", "COMPLETED", 4, 24.0, 903),
         ("O51", "N", "F1", "N.1", " wait_to_confirm ", 1, 24.0, 904), ("O51", "N", "F1", "N.1", " wait_to_confirm ", 1, 24.0, 904)]


def _sql(rows) -> str:
    def v(x):
        return "NULL" if x is None else repr(x)
    # every line has its own customer unless one is given (as in the source: one customer per order)
    rows = [r if len(r) == 8 else (*r, 100 + n) for n, r in enumerate(rows)]
    body = ",\n  ".join(f"({v(so)}, DATE '{DAY}', '{s}', '{f}', '{i}', '{st}', {q}, 10.0, {h}, {c})"
                        for so, s, f, i, st, q, h, c in rows)
    return f"SELECT * FROM UNNEST(ARRAY<STRUCT<{COLS}>>[\n  {body}\n])"


def _setup(rows, policy="BLOCK") -> dict:
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm",
                           "location": "asia-southeast1", "partition_column": "", "maximum_bytes_billed": 10 * 1024 ** 2,
                           "exact_duplicate_policy": policy})
    ss.update("data_policy", {"window_start_date": "2026-01-01"})
    sql = _sql(rows)
    sug = connector.suggest_mapping(connector.sql_dry_run(sql)["columns"])
    ref = sug["reference_mapping"]
    ref["item_code"] = {"column": "item_code", "usage": "OPTIONAL"}
    ref["order_status"] = {"column": "order_status", "usage": "OPTIONAL"}
    ss.update("bigquery", {"field_mapping": sug["field_mapping"], "reference_mapping": ref})
    assert ss.get("bigquery").field_mapping["order_id"].column == "so_code"
    return {"mode": "SQL", "kind": "history", "version_id": 0, "sha256": "inline-test", "sql": sql,
            "key_columns": ["so_code", "sku_code", "fc_code", "created_date"], "key_duplicate_policy": "SUM_ALL"}


def test_real_bigquery_grain_and_pending_orders_pass_with_every_unit_kept():
    snap = _setup(BASE)
    chk = connector.duplicate_check(DAY, DAY, snap, "test")
    assert (chk["duplicate_groups"], chk["extra_duplicate_rows"], chk["ingest_status"]) == (0, 0, "PASSED")
    assert chk["pending_orders"] == {"applies": True, "statuses": [W], "exempt": True, "rows": 4, "qty": 7.0,
                                     "without_order_code_rows": 4, "identical_groups": 1, "identical_rows": 3,
                                     "whole_row_groups": 0, "whole_row_rows": 0}
    res = connector.fetch_daily(DAY, DAY, snap)
    assert res["estimated_bytes"] == 0 and res["exact_duplicate_rows"] == 0 and res["rows_dropped_duplicates"] == 0
    got = {(r["sku_id"], r["fc_id"]): r for r in res["rows"]}
    assert {k: float(r["qty"]) for k, r in got.items()} == {
        ("A", "F1"): 2, ("A", "F2"): 3, ("B", "F1"): 5, ("C", "F1"): 5, ("D", "F1"): 1, ("D.1", "F1"): 2,
        ("E", "F1"): 2, ("P", "F1"): 6, ("Q", "F1"): 1}
    assert sum(float(r["qty"]) for r in res["rows"]) == sum(r[5] for r in BASE) == res["qty_read"]
    oh = {k: open_hours.row_cell(r) for k, r in got.items()}
    assert oh[("B", "F1")] == oh[("C", "F1")] == (24.0, "OK")          # suffix order never changes the status
    assert oh[("E", "F1")] == (None, "MULTI_ITEM")
    assert {f for _, f in got} == {"F1", "F2"}                           # FCs from fc_code only


def test_real_bigquery_a_real_duplicate_still_blocks():
    # an order code (or a NULL code of another status) identical in every mapped column blocks although each line has
    # its own customer: customer_id is never part of the comparison of those rows
    for extra in (REAL_DUP, NULL_CODE_OTHER_STATUS):
        snap = _setup(BASE + extra)
        with pytest.raises(AppError) as e:
            connector.fetch_daily(DAY, DAY, snap)
        assert e.value.code == "BQ_DATA_DUPLICATES"
        chk = connector.dup_state()
        assert (chk["duplicate_groups"], chk["extra_duplicate_rows"]) == (1, 1)
        assert chk["pending_orders"]["identical_rows"] == 3
        assert chk["pending_orders"]["whole_row_rows"] == 0


def test_real_bigquery_pending_rows_are_exempt_even_identical_in_every_source_column():
    # 1.2.11 (owner rule; fix 7.1 blocked these): kept, every unit summed, reported as identical in every source column
    snap = _setup(BASE + PENDING_SAME_ROW + PENDING_WITH_CODE)
    res = connector.fetch_daily(DAY, DAY, snap)                       # the gate passes
    chk = connector.dup_state()
    assert (chk["duplicate_groups"], chk["duplicate_rows"], chk["extra_duplicate_rows"]) == (0, 0, 0)
    assert chk["pending_orders"] == {"applies": True, "statuses": [W], "exempt": True, "rows": 9, "qty": 18.0,
                                     "without_order_code_rows": 7, "identical_groups": 3, "identical_rows": 7,
                                     "whole_row_groups": 2, "whole_row_rows": 4}
    got = {(r["sku_id"], r["fc_id"]): float(r["qty"]) for r in res["rows"]}
    assert got[("T", "F1")] == 4 and got[("U", "F1")] == 7 and got[("P", "F1")] == 6
    assert res["exact_duplicate_rows"] == 0 and res["qty_read"] == sum(r[5] for r in BASE + PENDING_SAME_ROW + PENDING_WITH_CODE)


def test_real_bigquery_an_order_line_fanned_out_over_item_codes_blocks():
    # item_code is never a uniqueness criterion: the two rows differ only in their item code -> one duplicate group
    snap = _setup(BASE + ITEM_FANOUT)
    with pytest.raises(AppError) as e:
        connector.fetch_daily(DAY, DAY, snap)
    assert e.value.code == "BQ_DATA_DUPLICATES"
    chk = connector.dup_state()
    assert (chk["duplicate_groups"], chk["duplicate_rows"], chk["extra_duplicate_rows"]) == (1, 2, 1)
    assert "item_code" in chk["not_compared"]
    ss.update("bigquery", {"exact_duplicate_policy": "KEEP"})        # the control row counts it the same way
    assert connector.fetch_daily(DAY, DAY, snap)["exact_duplicate_rows"] == 1


def test_real_bigquery_mixed_statuses_never_form_one_group_and_pending_spelling_is_normalised():
    snap = _setup(BASE + MIXED)
    res = connector.fetch_daily(DAY, DAY, snap)                       # no duplicate: O50 has two statuses, O51 pending
    chk = connector.dup_state()
    assert chk["duplicate_groups"] == 0 and chk["pending_orders"]["rows"] == 4 + 1 + 2
    got = {(r["sku_id"], r["fc_id"]): float(r["qty"]) for r in res["rows"]}
    assert got[("M", "F1")] == 8 and got[("N", "F1")] == 2            # every unit kept
    snap = _setup(BASE + MIXED + [MIXED[1]])                          # the completed line twice: blocks
    with pytest.raises(AppError) as e:
        connector.fetch_daily(DAY, DAY, snap)
    assert e.value.code == "BQ_DATA_DUPLICATES" and connector.dup_state()["duplicate_groups"] == 1


def test_real_bigquery_customer_counts_join_never_multiplies_demand():
    snap = _setup(BASE)
    plain = connector.fetch_daily(DAY, DAY, snap)
    ss.update("bigquery", {"customer_id_column": "customer_id"})
    res = connector.fetch_daily(DAY, DAY, snap)
    key = lambda r: (r["sku_id"], r["fc_id"])  # noqa: E731
    assert sorted((key(r), float(r["qty"]), r["n_rows"]) for r in res["rows"]) == \
        sorted((key(r), float(r["qty"]), r["n_rows"]) for r in plain["rows"])
    assert res["qty_read"] == plain["qty_read"] == sum(r[5] for r in BASE) and len(res["rows"]) == len(plain["rows"])
    got = {key(r): r["customer_count"] for r in res["rows"]}
    assert got[("P", "F1")] == 3 and got[("A", "F2")] == 1          # one customer per line in BASE


def test_real_bigquery_drop_exact_drops_the_real_duplicate_and_keeps_pending_orders():
    snap = _setup(BASE + REAL_DUP + PENDING_SAME_ROW + ITEM_FANOUT, policy="DROP_EXACT")
    res = connector.fetch_daily(DAY, DAY, snap)
    got = {(r["sku_id"], r["fc_id"]): float(r["qty"]) for r in res["rows"]}
    # the real duplicate and the fanned-out line keep one row each; both identical pending rows are kept (1.2.11)
    assert got[("R", "F1")] == 1 and got[("P", "F1")] == 6 and got[("T", "F1")] == 4 and got[("V", "F1")] == 2
    assert res["rows_dropped_duplicates"] == 2 and res["qty_dropped_duplicates"] == 3
