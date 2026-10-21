"""Master audit (21/10/2026): grain SKU x FC and pending orders without order code.

* Grain: the warehouse is ONLY the source FC column (fc_code -> fc_id). An item code `<sku_code>.<n>` never tells the FC
  (its suffix is the order the SKU opened for sale in the regions, owner rule 20/10/2026): the D-1 query groups by day,
  SKU and FC only, and the Excel / demo path groups the stored lines the same way, without touching the SKU text.
* Owner rule 21/10/2026: an order WAITING FOR CONFIRMATION has no order code yet (so_code NULL is normal for
  WAIT_TO_CONFIRM). Fix 7.1 (21/10/2026): such rows are compared on their WHOLE source row (every column, mapped or
  not): rows that differ in any source column are separate orders - the duplicate gate, the full-period validation and
  the D-1 control rows do not count them, DROP_EXACT keeps them, they are counted apart; rows identical in every source
  column cannot be told from a real duplicate or a join fan-out and stay exact duplicates (blocking). Every other row
  keeps the exact-duplicate rule on the mapped columns. No column (customer_id included) is used as an order key. The
  real-BigQuery check of the same rules on inline rows is test_v129h_real_bq_pending_grain.py (opt-in).

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
PEND = ("COALESCE(order_id IS NULL AND UPPER(TRIM(CAST(ref_order_status AS STRING))) IN ('WAIT_TO_CONFIRM'), FALSE)")
# the same condition on the source columns, deciding whether the whole source row is compared (fix 7.1)
RAW = ("IF(COALESCE(`so_code` IS NULL AND UPPER(TRIM(CAST(`order_status` AS STRING))) IN ('WAIT_TO_CONFIRM'), FALSE), "
       "TO_JSON_STRING(_src_row), NULL) AS _praw")


def _bq(field_mapping=FM, reference_mapping=REF, policy="BLOCK"):
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders", "location": "asia-southeast1",
                           "partition_column": "", "field_mapping": field_mapping,
                           "reference_mapping": reference_mapping, "exact_duplicate_policy": policy})
    return ss.get("bigquery")


# ------------------------------------------------------------------ pending orders without order code
def test_pending_rule_needs_both_the_order_code_and_the_status_mapped():
    assert connector._pending_expr(_bq()) == PEND
    assert connector.PENDING_STATUSES == ("WAIT_TO_CONFIRM",)
    no_status = {k: v for k, v in REF.items() if k != "order_status"}
    assert connector._pending_expr(_bq(reference_mapping=no_status)) == "FALSE"
    no_order = {**FM, "order_id": {"column": None, "usage": "OPTIONAL"}}
    assert connector._pending_expr(_bq(field_mapping=no_order)) == "FALSE"


def test_duplicate_gate_sql_compares_pending_orders_on_the_whole_source_row():
    bq = _bq()
    sql = connector._dup_sql(bq, None)
    cols = ", ".join(c["alias"] for c in connector.dup_columns(bq))
    # the whole source row of a pending order without order code is read in the source relation ...
    assert f"{RAW} FROM {connector._table_ref(bq)} AS _src_row WHERE" in sql
    # ... and joins the grouping: such a row forms a group only with rows identical in every SOURCE column; every other
    # row has _praw NULL and is grouped on the mapped columns exactly as before
    assert f"FROM src GROUP BY {cols}, _praw\n), pm AS (" in sql
    assert f"{PEND} AS _pending" in sql
    assert "COUNTIF(_n > 1) AS duplicate_groups" in sql and "SUM(IF(_n > 1, _n - 1, 0)) AS extra_duplicate_rows" in sql
    assert "COUNTIF(_n > 1 AND _pending) AS pending_duplicate_groups" in sql
    assert f"ARRAY_AGG(IF(_n > 1, STRUCT({cols}, _n AS _occurrences, _pending AS _pending), NULL)" in sql
    # identical in the mapped columns only (separate orders): counted apart, informative
    assert f"FROM (SELECT SUM(_n) AS _m FROM g WHERE _pending GROUP BY {cols})" in sql
    for c in ("pending_rows", "pending_qty", "pending_identical_groups", "pending_identical_rows",
              "pending_duplicate_groups", "pending_duplicate_rows"):
        assert f" AS {c}" in sql
    # every row is still read and counted (no WHERE on the status / order code); no column is named as an order key
    assert "SUM(_n) AS rows_checked, SUM(_q) AS qty_checked" in sql
    assert "WHERE order_id" not in sql and "so_code IS NOT NULL" not in sql and "customer" not in sql


def test_without_the_status_mapped_the_gate_sql_is_the_exact_rule_on_every_row():
    sql = connector._dup_sql(_bq(reference_mapping={k: v for k, v in REF.items() if k != "order_status"}), None)
    assert "FALSE AS _pending" in sql
    assert "CAST(NULL AS STRING) AS _praw" in sql and "TO_JSON_STRING(_src_row)" not in sql   # no extra column read
    assert "COUNTIF(_n > 1) AS duplicate_groups" in sql                    # every group counts


def test_d1_control_rows_and_validation_use_the_same_pending_rule():
    bq = _bq()
    sql, _ = connector._daily_sql(bq, date(2026, 10, 1), date(2026, 10, 2))
    # the serialised row carries _praw: NULL for every row except a pending order without order code (whole row)
    assert "SELECT 'TOTAL_READ', CAST(COUNT(*) - COUNT(DISTINCT TO_JSON_STRING(s)) AS STRING)" in sql
    assert f"{RAW} FROM" in sql
    assert re.search(r"kept AS \(\n  SELECT order_id, .*, _order_date, _key FROM src\n\)", sql)     # BLOCK: all kept
    summary = connector._validation_sqls(bq, date(2026, 10, 1), date(2026, 10, 2))["validate_summary"]
    assert "COUNT(*) - COUNT(DISTINCT TO_JSON_STRING(c0)) AS exact_duplicate_rows" in summary
    assert ", _order_date, _key, _praw, CASE WHEN sku_id IS NULL" in summary and f"{RAW} FROM" in summary


def test_drop_exact_drops_a_pending_row_only_when_identical_in_every_source_column():
    bq = _bq(policy="DROP_EXACT")
    sql, _ = connector._daily_sql(bq, date(2026, 10, 1), date(2026, 10, 2))
    kept = sql.split("), kept AS (\n", 1)[1].split("\n), checked AS (", 1)[0]
    cols = ", ".join(connector._aliases(bq, with_refs=True)) + ", _order_date, _key"
    # DISTINCT over the mapped columns + _praw: non-pending rows exactly as before (_praw NULL), pending rows only
    # when their whole source row is the same
    assert kept == f"  SELECT {cols} FROM (SELECT DISTINCT {cols}, _praw FROM src)"


def test_drop_exact_sql_is_unchanged_when_the_rule_does_not_apply():
    sql, _ = connector._daily_sql(_bq(reference_mapping={}, policy="DROP_EXACT"), date(2026, 10, 1), date(2026, 10, 2))
    kept = sql.split("), kept AS (\n", 1)[1].split("\n), checked AS (", 1)[0]
    assert kept == "  SELECT DISTINCT order_id, order_date, sku_id, fc_id, order_qty, unit_price, _order_date, _key FROM src"
    # the same count as before (COUNTIF(NOT FALSE) - COUNT(DISTINCT IF(FALSE, NULL, x)) == COUNT(*) - COUNT(DISTINCT x));
    # _praw is a constant NULL and no extra column is read
    assert "SELECT 'TOTAL_READ', CAST(COUNT(*) - COUNT(DISTINCT TO_JSON_STRING(s)) AS STRING)" in sql
    assert "CAST(NULL AS STRING) AS _praw" in sql and "TO_JSON_STRING(_src_row)" not in sql


def _finish(row: dict):
    bq = _bq()
    cols = [{"name": c} for c in ("so_code", "created_date", "sku_code", "fc_code", "demand_quantity", "sales_price",
                                  "order_status", "item_code", "total_open_hours", "customer_id")]
    return connector._dup_finish(bq, None, date(2026, 1, 1), date(2026, 10, 19), [row], cols, "test", 0)


def test_pending_identical_rows_alone_pass_the_gate_and_write_no_report(data_dir):
    # the shape of the 21/10/2026 source: 18 groups / 67 rows identical in every mapped column, all WAIT_TO_CONFIRM
    # without so_code, and no other duplicate
    chk = _finish({"rows_checked": 8961545, "qty_checked": 42009962, "duplicate_groups": 0, "duplicate_rows": 0,
                   "extra_duplicate_rows": 0, "pending_rows": 307, "pending_qty": 6505, "pending_identical_groups": 18,
                   "pending_identical_rows": 67, "_groups": []})
    assert chk["ingest_status"] == "PASSED" and "report" not in chk
    assert chk["pending_no_order_code"] == {"applies": True, "statuses": ["WAIT_TO_CONFIRM"], "rows": 307,
                                            "qty": 6505.0, "identical_groups": 18, "identical_rows": 67,
                                            "duplicate_groups": 0, "duplicate_rows": 0}
    assert connector.dup_state()["pending_no_order_code"]["identical_rows"] == 67      # shown on the BigQuery page
    assert "customer_id" in chk["not_compared"]                                       # still not compared, not a key


def test_a_real_duplicate_still_blocks_and_the_report_states_the_pending_rule(data_dir):
    g = {"order_id": "SO1", "order_date": "2026-10-19", "sku_id": "S", "fc_id": "BD", "order_qty": 2, "unit_price": 1.0,
         "ref_order_status": "COMPLETED", "ref_item_code": "S.1", "ref_open_hours": 24.0, "_occurrences": 2}
    chk = _finish({"rows_checked": 10, "qty_checked": 20, "duplicate_groups": 1, "duplicate_rows": 2,
                   "extra_duplicate_rows": 1, "pending_rows": 3, "pending_qty": 3, "pending_identical_groups": 1,
                   "pending_identical_rows": 3, "_groups": [g]})
    assert chk["ingest_status"] == "BLOCKED" and chk["report"]["format"] == "xlsx"
    summary = dup_report.tables(chk)["Summary"]
    text = " ".join(str(v) for v in summary["Giá trị / Value"])
    assert dup_report.PENDING_VI in text and dup_report.PENDING_EN in text and "1 / 3" in text
    rows = dup_report.tables(chk)["Duplicate_Rows"]
    assert len(rows) == 2                                                # only the real duplicate group is listed
    assert list(rows["compared_on"]) == [dup_report.MAPPED] * 2


def test_pending_rows_identical_in_every_source_column_block_and_are_reported(data_dir):
    # fix 7.1: no source column tells the two rows apart (same customer, same everything) - a real duplicate or a
    # join fan-out cannot be excluded, so the gate blocks and the report says the whole source row was compared
    g = {"order_id": None, "order_date": "2026-10-20", "sku_id": "S", "fc_id": "BD", "order_qty": 1, "unit_price": 1.0,
         "ref_order_status": "WAIT_TO_CONFIRM", "ref_item_code": "S.1", "ref_open_hours": 24.0, "_occurrences": 2,
         "_pending": True}
    chk = _finish({"rows_checked": 10, "qty_checked": 10, "duplicate_groups": 1, "duplicate_rows": 2,
                   "extra_duplicate_rows": 1, "pending_rows": 5, "pending_qty": 5, "pending_identical_groups": 1,
                   "pending_identical_rows": 4, "pending_duplicate_groups": 1, "pending_duplicate_rows": 2,
                   "_groups": [g]})
    assert chk["ingest_status"] == "BLOCKED" and chk["report"]["format"] == "xlsx"
    assert chk["groups"][0]["pending_whole_row"] is True
    assert (chk["pending_no_order_code"]["duplicate_groups"], chk["pending_no_order_code"]["duplicate_rows"]) == (1, 2)
    t = dup_report.tables(chk)
    assert list(t["Duplicate_Rows"]["compared_on"]) == [dup_report.WHOLE_ROW] * 2
    assert list(t["Duplicate_Groups"]["compared_on"]) == [dup_report.WHOLE_ROW]
    assert "1 / 2" in " ".join(str(v) for v in t["Summary"]["Giá trị / Value"])
    assert connector.dup_state()["pending_no_order_code"]["duplicate_rows"] == 2


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
    assert "JOIN" not in gate.replace("FROM g CROSS JOIN pm", "")      # pm: one row of pending counts
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
    # 3: the same per-item values give the same status whatever the items are called (counts only reach cell())
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
    assert list(t["Duplicate_Rows"]["compared_on"]) == [dup_report.MAPPED] * 3     # a group from before fix 7.1
    assert isinstance(t["Summary"], pd.DataFrame)
