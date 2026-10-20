"""SKU open hours of the day (1.2.9): BigQuery D-1 column total_open_hours, a MANDATORY model input for the BIGQUERY
source (mapping field `open_hours`, role REQUIRED_FEATURE).

Business definition (owner, 19/10/2026): the number of hours of one day during which the SKU was open for sale. The
domain 0..24 follows from that definition and is what the real table holds (read-only profile of 01/01-18/10/2026:
min 0, max 24, no negative value, nothing above 24).

D-1 aggregation to the model grain (day x SKU x FC), per group of valid order lines (connector._daily_sql):
  OK            every line has a value, all values are equal and within 0..24 -> that value
  MISSING       at least one line has no value (NULL)                        -> no value
  OUT_OF_RANGE  a value below 0 or above 24                                  -> no value
  MULTI_ITEM    (1.2.9b) the values differ only BETWEEN items: every item (item_code <sku_code>.<n> of the SKU) has one
                value, several items of the SKU sold through the same FC that day -> no value (no aggregation rule
                approved). Open hours are measured per item and day (read-only checks of 20/10/2026: the same item has
                the same hours in every FC that day). The suffix <n> is the order in which the SKU was opened for sale
                in the regions (owner, 20/10/2026): it is NOT a region code and never tells the FC, the region or the
                hours. Only with the item_code reference column mapped; without it -> CONFLICT
  CONFLICT      lines of the same day x SKU x FC disagree and it cannot be explained by different items (the same item
                with two values, or lines without an item code)          -> no value, to be investigated
No value is ever replaced by 0, by a neighbour day or by an estimate. A row without a status was loaded before 1.2.9
(NOT_LOADED: a D-1 full reload reads the column) or comes from a source without the column (DEMO / Excel import, where
the input does not apply).

Training on the BIGQUERY source stops with OPEN_HOURS_INVALID while ANY demand row of the model window is not OK: the
pipeline never continues as if the input existed. Until a rule for missing / conflicting / multi-item values is approved,
the owner's options are a later model-input start (data_policy.window_start_date, or 1.2.9b training_start_rule =
OPEN_HOURS_COVERAGE: the first stored day with open hours) or a corrected source + a D-1 full reload.

Source history (read-only checks of 19/10 and 20/10/2026): up to the 20/10 07:10 refresh the source had open hours only
from 19/03 or 20/03 (the first day moved between two refreshes); the owner then filled the history and the 20/10 15:05
refresh has a value on every line from 01/01/2026. Whether older days keep their value at later refreshes is not known,
so a reload / backfill that would replace a stored OK value by MISSING is still warned by the backfill preview
(OPEN_HOURS_WOULD_BE_LOST) and counted by every D-1 / backfill result (open_hours_lost).
"""
from __future__ import annotations

import json

MIN_HOURS, MAX_HOURS = 0.0, 24.0
STATUSES = ("OK", "MISSING", "OUT_OF_RANGE", "CONFLICT", "MULTI_ITEM")
FIELD = "open_hours"           # reference_mapping field (column total_open_hours on the real table)


def mandatory(data_source: str | None) -> bool:
    """Mandatory for the D-1 BigQuery source only; DEMO / MANUAL_IMPORT data has no such column."""
    return data_source == "BIGQUERY"


def cell(null_rows, lo, hi, items=None, item_values=None, no_item_rows=None) -> tuple[float | None, str | None]:
    """(value, status) of one day x SKU x FC group from the count of lines without a value and MIN / MAX of the lines.
    All three None = the column was not read (not mapped): no value, no status.
    1.2.9b: items / item_values / no_item_rows = distinct items, distinct (item, value) pairs and lines with a value but
    no item code (None when item_code is not mapped): differing values that are one value per item -> MULTI_ITEM."""
    if null_rows is None and lo is None and hi is None:
        return None, None
    if int(null_rows or 0) > 0 or lo is None or hi is None:
        return None, "MISSING"
    lo, hi = float(lo), float(hi)
    if lo < MIN_HOURS or hi > MAX_HOURS:
        return None, "OUT_OF_RANGE"
    if hi != lo:
        if (items is not None and item_values is not None and int(items) > 1 and int(item_values) == int(items)
                and not int(no_item_rows or 0)):
            return None, "MULTI_ITEM"
        return None, "CONFLICT"
    return lo, "OK"


def row_cell(r: dict) -> tuple[float | None, str | None]:
    """cell() of one aggregated D-1 row (connector._daily_sql columns)."""
    return cell(r.get("open_hours_null_rows"), r.get("open_hours_min"), r.get("open_hours_max"),
                r.get("open_hours_items"), r.get("open_hours_item_values"), r.get("open_hours_no_item_rows"))


def window_check(conn, scope_key: str, start: str, end: str) -> dict:
    """Status of every demand row of [start, end] (the model window): rows, first / last day per status. ok = at least
    one row and every row OK. One sequential scan (the key index has no open_hours_status)."""
    by = {}
    for st, n, lo, hi in conn.execute(
            "SELECT COALESCE(open_hours_status, 'NOT_LOADED'), COUNT(*), MIN(order_date), MAX(order_date) "
            "FROM demand_daily NOT INDEXED WHERE scope_key=? AND order_date BETWEEN ? AND ? GROUP BY 1",
            (scope_key, start, end)):
        by[st] = {"rows": int(n), "first": lo, "last": hi}
    rows = sum(v["rows"] for v in by.values())
    bad = {k: v for k, v in by.items() if k != "OK"}
    return {"window": [start, end], "rows": rows, "ok_rows": by.get("OK", {}).get("rows", 0),
            "not_ok": bad, "ok": rows > 0 and not bad}


def coverage_start(conn, scope_key: str, start: str, end: str) -> str | None:
    """First day of [start, end] with a stored row that carries the open-hours column (any status except MISSING /
    not loaded): where the source's open hours begin. None = no such row. One sequential scan, like window_check."""
    r = conn.execute("SELECT MIN(order_date) FROM demand_daily NOT INDEXED WHERE scope_key=? AND order_date BETWEEN ? "
                     "AND ? AND open_hours_status IS NOT NULL AND open_hours_status <> 'MISSING'",
                     (scope_key, start, end)).fetchone()
    return r[0] if r and r[0] else None


def blocking_detail(chk: dict) -> str:
    """Detail of OPEN_HOURS_INVALID: counts and day ranges per status (no row values)."""
    return json.dumps({"window": chk["window"], "rows": chk["rows"], "ok_rows": chk["ok_rows"], "not_ok": chk["not_ok"]})
