"""1.2.10 follow-up (21/10/2026): the 6 MULTI_ITEM keys of the D-1 source, re-verified on the 21/10 07:10 snapshot.

Read-only evidence (reports/multi-item-d1-20261021/): each of the 6 day x SKU x FC keys has two item codes of the SKU;
each item code is the SKU's listing in ONE sales region (source column sales_region_code of fact_sku_status_day_by_date,
never the suffix), its total_open_hours is the time the listing spent in a selling status that day (rebuilt to the
hundredth from the status intervals of 26/08), and both listings were fulfilled by the same FC (fc_code). One value per
item, the same in every FC; no JOIN fan-out (lines = orders); no inconsistent value; mapping correct. Neither the source
nor the repository defines how two regional listings make ONE SKU x FC value, and the owner decided (21/10/2026) to keep
these keys blocked: no value is invented, the demand is kept, and BIGQUERY training stops with OPEN_HOURS_INVALID.

Temporary databases (conftest), FakeBQ, synthetic SKU codes with the real hours / line patterns. The same patterns go
through the real D-1 SQL on inline rows in test_v1210_real_bq_multi_item_regions.py (opt-in)."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app import db, timeutil
from app.data import open_hours
from app.data.demand import load_demand
from app.messages import AppError

BQ_SCOPE = "BIGQUERY:lakehouse-prod-394907.sales.orders"
# the 6 keys: (day FC, hours of the two items) - every item has one value, the items differ
SIX = [("09/02 HN", 23.92, 24.0), ("10/02 HN", 21.16, 24.0), ("02/03 BD", 5.0, 24.0), ("02/03 BD", 1.7, 24.0),
       ("26/08 BD", 23.72, 24.0), ("26/08 BD", 18.22, 22.85)]
# the same SKUs on the same days in the OTHER FC, where only one of the two items was sold: one value
OTHER_FC = [("09/02 BD", 23.92), ("10/02 BD", 21.16), ("02/03 HN", 24.0), ("02/03 HN", 24.0), ("26/08 HN", 18.22)]


@pytest.mark.parametrize("key, lo, hi", SIX)
def test_the_six_real_keys_have_no_value_and_no_aggregate_of_the_items_comes_out(key, lo, hi):
    value, status = open_hours.cell(0, lo, hi, 2, 2, 0)
    assert (value, status) == (None, "MULTI_ITEM"), key
    assert value not in (lo, hi, (lo + hi) / 2)         # neither MIN, MAX nor a mean is chosen for the owner


@pytest.mark.parametrize("key, hours", OTHER_FC)
def test_the_other_fc_of_the_same_sku_and_day_keeps_its_one_item_value(key, hours):
    # the FC comes from fc_code: an item sold through two FCs gives two keys, each with that item's value
    assert open_hours.cell(0, hours, hours, 1, 1, 0) == (hours, "OK"), key


def test_valid_keys_give_exactly_one_value():
    assert open_hours.cell(0, 12.5, 12.5, 1, 1, 0) == (12.5, "OK")      # several orders (lines) of one item
    assert open_hours.cell(0, 24.0, 24.0, 2, 2, 0) == (24.0, "OK")      # two items with the same hours
    assert open_hours.cell(0, 0.0, 0.0, 2, 2, 0) == (0.0, "OK")         # 0 is a value, not a missing one


@pytest.mark.parametrize("args, status", [
    ((0, 5.0, 6.0, 1, 2, 0), "CONFLICT"),          # one item with two values that day
    ((0, 5.0, 6.0, 1, 1, 1), "CONFLICT"),          # a line with a value but without item code
    ((0, 5.0, 25.0, 2, 2, 0), "OUT_OF_RANGE"),     # above 24 h
    ((0, -1.0, 5.0, 2, 2, 0), "OUT_OF_RANGE"),     # below 0
    ((1, 5.0, 24.0, 2, 2, 0), "MISSING"),          # a line without value wins over MULTI_ITEM
    ((1, None, None, 1, 0, 0), "MISSING"),
])
def test_inconsistent_or_unattributable_hours_are_detected_and_get_no_value(args, status):
    assert open_hours.cell(*args) == (None, status)


def _row(day, sku, fc, q, lines, lo, hi, items, item_values):
    return {"order_date": day, "sku_id": sku, "fc_id": fc, "qty": q, "n_rows": lines, "n_orders": lines,
            "avg_unit_price": 10.0, "avg_discount_rate": None, "promo_share": None, "voucher_share": None,
            "max_source_updated_at": None, "max_batch_id": None, "open_hours_null_rows": 0, "open_hours_min": lo,
            "open_hours_max": hi, "open_hours_items": items, "open_hours_item_values": item_values,
            "open_hours_no_item_rows": 0}


def test_d1_keeps_the_demand_of_a_multi_item_key_and_each_fc_gets_its_own_status(client):
    from test_v129_backfill_history_patterns import _production
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    rows = [_row(y, "S6", "BD", 4.0, 4, 18.22, 22.85, 2, 2),       # 26/08 BD pattern: two regional listings
            _row(y, "S6", "HN", 3.0, 3, 18.22, 18.22, 1, 1),       # the same SKU and day in HN: one listing
            _row(y, "S1", "BD", 3.0, 3, 12.5, 12.5, 1, 1),         # three orders of one item
            _row(y, "S2", "BD", 5.0, 2, 24.0, 24.0, 2, 2)]         # two items, same hours
    _production(rows)
    res = sync.run_d1_sync("J1")
    assert res["open_hours_status_rows"] == {"OK": 3, "MISSING": 0, "OUT_OF_RANGE": 0, "CONFLICT": 0, "MULTI_ITEM": 1,
                                             "NOT_READ": 0}
    with db.read() as c:
        got = {(r[0], r[1]): (r[2], r[3], r[4]) for r in c.execute(
            "SELECT sku_id, fc_id, open_hours, open_hours_status, qty FROM demand_daily WHERE scope_key=?", (BQ_SCOPE,))}
        chk = open_hours.window_check(c, BQ_SCOPE, str(y), str(y))
    assert got == {("S6", "BD"): (None, "MULTI_ITEM", 4.0), ("S6", "HN"): (18.22, "OK", 3.0),
                   ("S1", "BD"): (12.5, "OK", 3.0), ("S2", "BD"): (24.0, "OK", 5.0)}
    assert sum(q for _, _, q in got.values()) == sum(r["qty"] for r in rows)       # nothing lost, nothing doubled
    assert chk["not_ok"] == {"MULTI_ITEM": {"rows": 1, "first": str(y), "last": str(y)}} and chk["ok_rows"] == 3


def test_training_stops_on_one_multi_item_row_and_nothing_is_trained_or_replaced(client, fast_model, monkeypatch):
    from test_v129_weekday_open_hours import _bq_scope_from_demo
    from app.ml import pipeline
    with monkeypatch.context() as m:
        _bq_scope_from_demo(m)
        with db.tx() as c:
            c.execute("UPDATE demand_daily SET open_hours = 8 + (julianday(order_date) % 17), open_hours_status='OK' "
                      "WHERE scope_key=?", (BQ_SCOPE,))
            day = c.execute("SELECT MIN(order_date) FROM demand_daily WHERE scope_key=? AND order_date > "
                            "(SELECT MIN(order_date) FROM demand_daily WHERE scope_key=?)", (BQ_SCOPE, BQ_SCOPE)).fetchone()[0]
            rid = c.execute("SELECT MIN(rowid) FROM demand_daily WHERE scope_key=? AND order_date=?", (BQ_SCOPE, day)).fetchone()[0]
            c.execute("UPDATE demand_daily SET open_hours=NULL, open_hours_status='MULTI_ITEM' WHERE rowid=?", (rid,))
            qty = c.execute("SELECT qty FROM demand_daily WHERE rowid=?", (rid,)).fetchone()[0]
            before = {t: c.execute(f"SELECT COUNT(*) FROM {t} WHERE scope_key=?", (BQ_SCOPE,)).fetchone()[0]
                      for t in ("training_runs", "forecast_runs")}
        with pytest.raises(AppError) as e:                    # force=True does not pass the gate either
            pipeline.train_and_publish(force=True, source="BIGQUERY")
        assert e.value.code == "OPEN_HOURS_INVALID"
        det = json.loads(e.value.detail)
        assert det["not_ok"] == {"MULTI_ITEM": {"rows": 1, "first": day, "last": day}} and det["ok_rows"] == det["rows"] - 1
        with db.read() as c:
            after = {t: c.execute(f"SELECT COUNT(*) FROM {t} WHERE scope_key=?", (BQ_SCOPE,)).fetchone()[0]
                     for t in ("training_runs", "forecast_runs")}
            kept = c.execute("SELECT qty, open_hours, open_hours_status FROM demand_daily WHERE rowid=?", (rid,)).fetchone()
        assert after == before                                # no run, no forecast: the model in use stays
        assert tuple(kept) == (qty, None, "MULTI_ITEM")      # the demand of the key is kept, no hours invented
        d = load_demand(BQ_SCOPE, start=day, end=day)
        assert float(d["qty"].sum()) > 0 and d["open_hours"].isna().sum() == 1
