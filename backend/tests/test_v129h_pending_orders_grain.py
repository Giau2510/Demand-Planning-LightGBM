"""Master audit (21/10/2026), fix 7.1 and the consolidated release 1.2.11: grain SKU x FC and the duplicate rule by order
status.

* Grain: the warehouse is ONLY the source FC column (fc_code -> fc_id). An item code `<sku_code>.<n>` never tells the FC
  (owner rules 20/10 and 21/10/2026): the D-1 query groups by day, SKU and FC only, and the Excel / demo path groups the
  stored lines the same way, without touching the SKU text.
* Owner rule 21/10/2026 (1.2.11, supersedes fix 7.1): rows of an order WAITING FOR CONFIRMATION (WAIT_TO_CONFIRM, with
  or without so_code) are EXEMPT from the duplicate rule - the gate, the full-period validation and the D-1 control
  rows never count them as duplicates, DROP_EXACT keeps all of them, they are counted apart (identical in the compared
  columns / in every source column: informative). Rows of every other status keep the exact-duplicate rule on the
  compared columns = the mapped columns except item_code (never a uniqueness criterion). No column (customer_id
  included) is used as an order key. The real-BigQuery check of the same rules on inline rows is
  test_v129h_real_bq_pending_grain.py (opt-in).

Temporary databases (conftest), no BigQuery call."""
from __future__ import annotations

import re
from datetime import date

import pandas as pd

from app import db
from app import settings_service as ss
from app.bq import connector, dup_report
from app.data import demand, open_hours
from app.timeutil import now_iso

FM = {"order_id": {"column": "so_code", "usage": "OPTIONAL"}, "order_date": {"column": "created_date", "usage": "REQUIRED"},
      "created_at": {"column": None, "usage": "UNUSED"},
      "sku_id": {"column": "sku_code", "usage": "REQUIRED"}, "fc_id": {"column": "fc_code", "usage": "REQUIRED"},
      "order_qty": {"column": "demand_quantity", "usage": "REQUIRED"},
      "unit_price": {"column": "sales_price", "usage": "OPTIONAL"}}
REF = {"order_status": {"column": "order_status", "usage": "OPTIONAL"},
       "item_code": {"column": "item_code", "usage": "OPTIONAL"},
       "open_hours": {"column": "total_open_hours", "usage": "OPTIONAL"}}
PEND = "COALESCE(UPPER(TRIM(CAST(ref_order_status AS STRING))) IN ('WAIT_TO_CONFIRM'), FALSE)"
# the same condition on the source column (no order code involved), and the whole source row of a pending order
# (read only by the duplicate check, to count pending rows identical in every source column - informative)
SRC_PEND = "COALESCE(UPPER(TRIM(CAST(`order_status` AS STRING))) IN ('WAIT_TO_CONFIRM'), FALSE) AS _pend"
RAW = ("IF(COALESCE(UPPER(TRIM(CAST(`order_status` AS STRING))) IN ('WAIT_TO_CONFIRM'), FALSE), "
       "TO_JSON_STRING(_src_row), NULL) AS _praw")


def _bq(field_mapping=FM, reference_mapping=REF, policy="BLOCK"):
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders", "location": "asia-southeast1",
                           "partition_column": "", "field_mapping": field_mapping,
                           "reference_mapping": reference_mapping, "exact_duplicate_policy": policy})
    return ss.get("bigquery")


def _cmp(bq) -> str:
    return ", ".join(c["alias"] for c in connector.dup_columns(bq))


# ------------------------------------------------------------------ pending orders exempt, item_code never compared
def test_pending_rule_needs_only_the_status_mapped_never_an_order_code():
    assert connector._pending_expr(_bq()) == PEND
    assert connector.PENDING_STATUSES == ("WAIT_TO_CONFIRM",)
    no_status = {k: v for k, v in REF.items() if k != "order_status"}
    assert connector._pending_expr(_bq(reference_mapping=no_status)) == "FALSE"
    no_order = {**FM, "order_id": {"column": None, "usage": "OPTIONAL"}}
    assert connector._pending_expr(_bq(field_mapping=no_order)) == PEND          # so_code is not required


def test_item_code_is_never_a_compared_column():
    bq = _bq()
    cols = connector.dup_columns(bq)
    assert "item_code" not in {c["field"] for c in cols} and "item_code" not in {c["column"] for c in cols}
    assert {"order_id", "sku_id", "fc_id", "order_qty", "ref_order_status", "ref_open_hours"} <= {c["alias"] for c in cols}
    assert connector.DUP_NOT_COMPARED_FIELDS == ("item_code",)


def test_duplicate_gate_sql_exempts_pending_orders_and_compares_the_rest():
    bq = _bq()
    sql = connector._dup_sql(bq, None)
    cols = _cmp(bq)
    assert f"{SRC_PEND}, {RAW} FROM {connector._table_ref(bq)} AS _src_row WHERE" in sql
    # one group per identical compared columns; the status is a compared column, so a group is all pending or all not
    assert f"FROM src GROUP BY {cols}\n), pw AS (" in sql and "ref_order_status" in cols
    assert "LOGICAL_OR(_pend) AS _pending" in sql
    # only non-pending groups are duplicates (and listed); pending groups are counted apart, never blocking
    assert "COUNTIF(_n > 1 AND NOT _pending) AS duplicate_groups" in sql
    assert "SUM(IF(_n > 1 AND NOT _pending, _n - 1, 0)) AS extra_duplicate_rows" in sql
    assert f"ARRAY_AGG(IF(_n > 1 AND NOT _pending, STRUCT({cols}, _n AS _occurrences), NULL)" in sql
    assert "COUNTIF(_n > 1 AND _pending) AS pending_identical_groups" in sql
    assert "FROM (SELECT COUNT(*) AS _m FROM src WHERE _praw IS NOT NULL GROUP BY _praw)" in sql      # whole row: info
    for c in ("pending_rows", "pending_qty", "pending_without_code_rows", "pending_identical_rows",
              "pending_whole_row_groups", "pending_whole_row_rows"):
        assert f" AS {c}" in sql
    # every row is still read and counted (no WHERE on the status / order code); no column is named as an order key
    assert "SUM(_n) AS rows_checked, SUM(_q) AS qty_checked" in sql
    assert "WHERE order_id" not in sql and "so_code IS NOT NULL" not in sql and "customer" not in sql
    assert "ref_item_code" not in sql.split("), g AS (", 1)[1]           # read in src, never grouped or compared


def test_without_the_status_mapped_every_row_is_compared():
    sql = connector._dup_sql(_bq(reference_mapping={k: v for k, v in REF.items() if k != "order_status"}), None)
    assert "FALSE AS _pend" in sql
    assert "CAST(NULL AS STRING) AS _praw" in sql and "TO_JSON_STRING(_src_row)" not in sql   # no extra column read
    assert "COUNTIF(_n > 1 AND NOT _pending) AS duplicate_groups" in sql     # _pending is FALSE: every group counts


def test_d1_control_rows_and_validation_use_the_same_rule():
    bq = _bq()
    sql, _ = connector._daily_sql(bq, date(2026, 10, 1), date(2026, 10, 2))
    expr = f"COUNTIF(NOT _pend) - COUNT(DISTINCT IF(_pend, NULL, TO_JSON_STRING(STRUCT({_cmp(bq)}))))"
    assert f"SELECT 'TOTAL_READ', CAST({expr} AS STRING)" in sql
    assert f"{SRC_PEND} FROM" in sql and "_praw" not in sql             # the aggregation never reads the whole row
    assert re.search(r"kept AS \(\n  SELECT order_id, .*, _order_date, _key FROM src\n\)", sql)     # BLOCK: all kept
    summary = connector._validation_sqls(bq, date(2026, 10, 1), date(2026, 10, 2))["validate_summary"]
    assert f"{expr} AS exact_duplicate_rows" in summary
    assert ", _order_date, _key, _pend, CASE WHEN sku_id IS NULL" in summary and "_praw" not in summary


def test_drop_exact_keeps_every_pending_row_and_one_row_per_non_pending_group():
    bq = _bq(policy="DROP_EXACT")
    sql, _ = connector._daily_sql(bq, date(2026, 10, 1), date(2026, 10, 2))
    kept = sql.split("), kept AS (\n", 1)[1].split("\n), checked AS (", 1)[0]
    cols = ", ".join(connector._aliases(bq, with_refs=True)) + ", _order_date, _key"
    assert kept == (f"  SELECT {cols} FROM src WHERE _pend UNION ALL SELECT {cols} FROM (SELECT {cols}, ROW_NUMBER() "
                    f"OVER (PARTITION BY TO_JSON_STRING(STRUCT({_cmp(bq)})) ORDER BY TO_JSON_STRING(STRUCT({cols}))) "
                    f"AS _rn FROM src WHERE NOT _pend) WHERE _rn = 1")


def test_drop_exact_without_the_status_mapped_dedups_every_row():
    bq = _bq(reference_mapping={}, policy="DROP_EXACT")
    sql, _ = connector._daily_sql(bq, date(2026, 10, 1), date(2026, 10, 2))
    plain = "order_id, order_date, sku_id, fc_id, order_qty, unit_price"
    assert "FALSE AS _pend" in sql and f"PARTITION BY TO_JSON_STRING(STRUCT({plain}))" in sql
    assert (f"SELECT 'TOTAL_READ', CAST(COUNTIF(NOT _pend) - COUNT(DISTINCT IF(_pend, NULL, TO_JSON_STRING(STRUCT("
            f"{plain})))) AS STRING)") in sql


def _finish(row: dict):
    bq = _bq()
    cols = [{"name": c} for c in ("so_code", "created_date", "sku_code", "fc_code", "demand_quantity", "sales_price",
                                  "order_status", "item_code", "total_open_hours", "customer_id")]
    return connector._dup_finish(bq, None, date(2026, 1, 1), date(2026, 10, 19), [row], cols, "test", 0)


PEND_ROW = {"pending_rows": 307, "pending_qty": 6505, "pending_without_code_rows": 300, "pending_identical_groups": 18,
            "pending_identical_rows": 67, "pending_whole_row_groups": 0, "pending_whole_row_rows": 0}


def test_pending_rows_pass_the_gate_and_write_no_report(data_dir):
    # the shape of the 21/10/2026 source: groups identical in every compared column, all WAIT_TO_CONFIRM; no other
    chk = _finish({"rows_checked": 8961545, "qty_checked": 42009962, "duplicate_groups": 0, "duplicate_rows": 0,
                   "extra_duplicate_rows": 0, **PEND_ROW, "_groups": []})
    assert chk["ingest_status"] == "PASSED" and "report" not in chk
    assert chk["pending_orders"] == {"applies": True, "statuses": ["WAIT_TO_CONFIRM"], "exempt": True, "rows": 307,
                                     "qty": 6505.0, "without_order_code_rows": 300, "identical_groups": 18,
                                     "identical_rows": 67, "whole_row_groups": 0, "whole_row_rows": 0}
    assert connector.dup_state()["pending_orders"]["identical_rows"] == 67           # shown on the BigQuery page
    assert {"customer_id", "item_code"} <= set(chk["not_compared"])                   # never compared, never a key


def test_pending_rows_identical_in_every_source_column_are_reported_but_never_block(data_dir):
    # the owner's exemption: even rows that no source column tells apart (a possible join fan-out) are kept; the
    # duplicate check reports them so they can be reviewed
    chk = _finish({"rows_checked": 10, "qty_checked": 10, "duplicate_groups": 0, "duplicate_rows": 0,
                   "extra_duplicate_rows": 0, **{**PEND_ROW, "pending_rows": 5, "pending_identical_groups": 1,
                                                 "pending_identical_rows": 4, "pending_whole_row_groups": 1,
                                                 "pending_whole_row_rows": 2}, "_groups": []})
    assert chk["ingest_status"] == "PASSED" and "report" not in chk
    assert (chk["pending_orders"]["whole_row_groups"], chk["pending_orders"]["whole_row_rows"]) == (1, 2)
    assert connector.dup_state()["pending_orders"]["whole_row_rows"] == 2


def test_a_real_duplicate_still_blocks_and_the_report_states_the_rules(data_dir):
    g = {"order_id": "SO1", "order_date": "2026-10-19", "sku_id": "S", "fc_id": "BD", "order_qty": 2, "unit_price": 1.0,
         "ref_order_status": "COMPLETED", "ref_open_hours": 24.0, "_occurrences": 2}
    chk = _finish({"rows_checked": 10, "qty_checked": 20, "duplicate_groups": 1, "duplicate_rows": 2,
                   "extra_duplicate_rows": 1, **{**PEND_ROW, "pending_rows": 3, "pending_qty": 3,
                                                 "pending_identical_groups": 1, "pending_identical_rows": 3},
                   "_groups": [g]})
    assert chk["ingest_status"] == "BLOCKED" and chk["report"]["format"] == "xlsx"
    t = dup_report.tables(chk)
    text = " ".join(str(v) for v in t["Summary"]["Giá trị / Value"])
    assert dup_report.PENDING_VI in text and dup_report.PENDING_EN in text and dup_report.ITEM_VI in text
    assert "1 / 3" in text
    assert len(t["Duplicate_Rows"]) == 2                                  # only the real duplicate group is listed
    assert list(t["Duplicate_Rows"]["compared_on"]) == [dup_report.MAPPED] * 2
    assert "item_code" not in t["Duplicate_Rows"].columns                 # not a compared column


def test_the_only_join_is_per_key_customer_counts_and_the_gate_reads_raw_rows():
    # join fan-out vs source duplicates: the duplicate gate groups the RAW source rows (no join); the D-1 query has one
    # join, only when a customer column is mapped: counts per day x SKU x FC (one row per key) on the full key, so a
    # demand row is never multiplied
    ss.update("bigquery", {"customer_id_column": "customer_id"})
    bq = _bq()
    sql, _ = connector._daily_sql(bq, date(2026, 10, 1), date(2026, 10, 2))
    assert sql.count(" JOIN ") == 1
    assert ("FROM valid LEFT JOIN cust ON cust.d = valid.order_date AND cust.sku_id = valid.sku_id "
            "AND cust.fc_id = valid.fc_id") in sql
    assert "FROM cust_seq WHERE d BETWEEN @start AND @end GROUP BY 1, 2, 3\n)" in sql      # one row per key
    gate = connector._dup_sql(bq, None)
    assert "JOIN" not in gate.replace("FROM g CROSS JOIN pw", "")      # pw: one row of pending counts
    assert "customer" not in gate                                      # never part of the duplicate key


# ------------------------------------------------------------------ grain SKU x FC: the FC comes from the FC column only
def test_d1_query_groups_by_day_sku_and_the_fc_column_only():
    bq = _bq()
    sql, _ = connector._daily_sql(bq, date(2026, 10, 1), date(2026, 10, 2))
    assert "`fc_code` AS fc_id" in sql and "`sku_code` AS sku_id" in sql and "`item_code` AS ref_item_code" in sql
    valid = sql.split("SELECT 'VALID'", 1)[1].split("UNION ALL", 1)[0]
    assert "CAST(sku_id AS STRING) AS sku_id" in valid and "CAST(fc_id AS STRING) AS fc_id" in valid
    assert valid.rstrip().endswith("FROM checked WHERE _reason IS NULL GROUP BY 3, 4, 5")     # day, SKU, FC
    assert "AS fc_id" not in valid.replace("CAST(fc_id AS STRING) AS fc_id", "")                # one FC expression only
    up = sql.upper()
    for f in ("SPLIT(", "REGEXP", "SUBSTR(", "LEFT(", "RIGHT(", "REPLACE(", "STRPOS("):
        assert f not in up, f


def _batch(conn, bid: str) -> None:
    conn.execute("INSERT INTO import_batches(id, data_source, status, created_at) VALUES (?, 'MANUAL_IMPORT', 'ACTIVE', ?)",
                 (bid, now_iso()))


def test_stored_grain_follows_the_fc_column_and_keeps_full_sku_codes(data_dir):
    lines = [  # order, day, sku (full code, suffix-like text kept as is), fc, qty
        ("O1", "2026-10-01", "MEDX.A", "BD", 2), ("O2", "2026-10-01", "MEDX.A", "HN", 3),     # 1: same SKU, 2 FCs
        ("O3", "2026-10-01", "MEDX.B", "BD", 1), ("O4", "2026-10-01", "MEDX.B", "BD", 4),     # 2: same FC, 1 key
        ("O5", "2026-10-01", "MEDX.C.1", "BD", 5), ("O6", "2026-10-01", "MEDX.C.2", "BD", 6),  # 4: two full codes
        ("O7", "2026-10-02", "MEDX.A", "HN", 1), ("O8", "2026-10-02", "MEDX.A", "HN", 1)]
    with db.tx() as c:
        _batch(c, "B1")
        c.executemany("INSERT INTO order_lines(batch_id, order_id, order_date, sku_id, fc_id, order_qty) "
                      "VALUES ('B1', ?, ?, ?, ?, ?)", lines)
        n = demand.aggregate_batch(c, "B1", "MANUAL_IMPORT")
    df = demand.load_demand("B1")
    got = {(r.order_date, r.sku_id, r.fc_id): (r.qty, r.n_orders) for r in df.itertuples()}
    assert n == 6 and got == {("2026-10-01", "MEDX.A", "BD"): (2, 1), ("2026-10-01", "MEDX.A", "HN"): (3, 1),
                              ("2026-10-01", "MEDX.B", "BD"): (5, 2), ("2026-10-01", "MEDX.C.1", "BD"): (5, 1),
                              ("2026-10-01", "MEDX.C.2", "BD"): (6, 1), ("2026-10-02", "MEDX.A", "HN"): (2, 2)}
    assert df["qty"].sum() == sum(q for *_, q in lines)          # 6: nothing duplicated or lost by the group-by
    assert set(df["fc_id"]) == {"BD", "HN"}                      # no FC made up from a SKU text


def test_open_hours_status_depends_on_the_key_and_per_item_values_only():
    # 3: the same per-item values give the same status whatever the items are called (counts only reach cell());
    # item counts only NAME a disagreement (MULTI_ITEM vs CONFLICT), they never decide whether a key is OK
    assert open_hours.cell(0, 24.0, 24.0, 2, 2, 0) == (24.0, "OK")            # two items, same hours: OK
    assert open_hours.cell(0, 5.0, 24.0, 2, 2, 0) == (None, "MULTI_ITEM")     # one value per item: no rule approved
    assert open_hours.cell(0, 5.0, 24.0, 1, 2, 0) == (None, "CONFLICT")       # one item, two values
    assert open_hours.cell(0, 5.0, 24.0, 2, 2, 1) == (None, "CONFLICT")       # a line without item code
    assert open_hours.cell(1, 5.0, 5.0, 1, 1, 0) == (None, "MISSING")         # never filled in
    assert open_hours.cell(0, 5.0, 25.0, 2, 2, 0) == (None, "OUT_OF_RANGE")


def test_dup_report_rows_keep_every_occurrence_of_a_group():
    chk = {"columns": [{"field": "sku_id", "alias": "sku_id", "column": "sku_code"}],
           "groups": [{"values": {"sku_id": "S"}, "occurrences": 3}], "range": {"start": "a", "end": "b"}}
    t = dup_report.tables(chk)
    assert list(t["Duplicate_Rows"]["duplicate_occurrence"]) == [1, 2, 3]
    assert list(t["Duplicate_Rows"]["compared_on"]) == [dup_report.MAPPED] * 3
    assert isinstance(t["Summary"], pd.DataFrame)


def test_whether_a_key_blocks_never_depends_on_its_item_codes():
    # 1.2.11 proof: for every value pattern, the key is OK (one value) or not OK exactly the same way whatever the item
    # counts are - several item codes never block by themselves, and dropping the item information never unblocks a
    # key whose lines disagree (the open hours of SKU x FC x day stay undefined without an approved rule)
    patterns = [(0, 24.0, 24.0), (0, 0.0, 0.0), (0, 5.0, 24.0), (0, 18.22, 22.85), (1, 5.0, 5.0), (0, 5.0, 25.0)]
    items = [(None, None, None), (1, 1, 0), (2, 2, 0), (3, 3, 0), (2, 3, 0), (2, 2, 1), (1, 2, 0)]
    for null, lo, hi in patterns:
        assert len({open_hours.cell(null, lo, hi, *i)[1] == "OK" for i in items}) == 1, (null, lo, hi)
        assert len({open_hours.cell(null, lo, hi, *i)[0] for i in items}) == 1, (null, lo, hi)
