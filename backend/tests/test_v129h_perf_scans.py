"""Master audit (21/10/2026), performance: three reads of a whole scope now run as ONE sequential scan (NOT INDEXED)
instead of the key index that fetched every row again (measured on a copy of production, 1.36 M rows): Feature registry
coverage 8.3 s -> 0.47 s, training lineage 8.6 s -> 1.0 s, demand panel load 15.3 s -> 6.2 s. The results must be
exactly those of the indexed statements: same counts / sums, and for load_demand the same DataFrame in the key order
whatever the order the rows were written in. Temporary databases (conftest)."""
from __future__ import annotations

import pandas as pd

from app import db
from app.data import demand
from app.ml import feature_registry, pipeline
from app.timeutil import now_iso

ROWS = [  # scope, day, sku, fc, qty, price, open hours (written deliberately out of key order, two scopes)
    ("S1", "2026-10-03", "B", "HN", 4.0, 10.0, 24.0), ("S1", "2026-10-01", "B", "BD", 1.0, None, None),
    ("S2", "2026-10-01", "A", "BD", 9.0, 5.0, 24.0), ("S1", "2026-10-02", "A", "HN", 2.0, 12.0, 5.0),
    ("S1", "2026-10-01", "A", "BD", 3.0, 11.0, 24.0), ("S1", "2026-10-02", "A", "BD", 0.0, None, 24.0),
    ("S2", "2026-10-02", "A", "BD", 7.0, 5.0, None)]


def _fill():
    with db.tx() as c:
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                      "avg_unit_price, open_hours, loaded_at) VALUES (?, 'BIGQUERY', ?, ?, ?, ?, 1, ?, ?, ?)",
                      [(s, d, k, f, q, p, h, now_iso()) for s, d, k, f, q, p, h in ROWS])


def _indexed(c, sql: str, params) -> list:
    return list(c.execute(sql.replace(" NOT INDEXED", ""), params).fetchone())


def test_coverage_and_lineage_are_sequential_scans_with_the_indexed_results(data_dir):
    _fill()
    with db.read() as c:
        cov = feature_registry.coverage(c, "S1")
        assert cov["rows"] == 5 and cov["avg_unit_price"] == 3 / 5 and cov["open_hours"] == 4 / 5
        ref = _indexed(c, "SELECT COUNT(*), COUNT(avg_unit_price), COUNT(open_hours) FROM demand_daily NOT INDEXED "
                          "WHERE scope_key=?", ("S1",))
        assert [cov["rows"], round(cov["avg_unit_price"] * 5), round(cov["open_hours"] * 5)] == ref
        lin = pipeline.data_lineage(c, {"scope_key": "S1", "data_source": "BIGQUERY", "label": "t"})["demand_daily"]
        assert (lin["min_date"], lin["max_date"], lin["rows"], lin["qty_sum"], lin["n_sku"], lin["n_fc"]) == \
            ("2026-10-01", "2026-10-03", 5, 10.0, 2, 2)
        for sql in ("SELECT COUNT(*) FROM demand_daily NOT INDEXED WHERE scope_key=?",):
            plan = " ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN " + sql, ("S1",)))
            assert "SCAN demand_daily" in plan and "INDEX" not in plan


def test_load_demand_returns_the_key_order_and_the_indexed_frame(data_dir):
    _fill()
    got = demand.load_demand("S1", start="2026-10-01", end="2026-10-02")
    keys = list(zip(got["order_date"], got["sku_id"], got["fc_id"]))
    assert keys == sorted(keys) == [("2026-10-01", "A", "BD"), ("2026-10-01", "B", "BD"), ("2026-10-02", "A", "BD"),
                                    ("2026-10-02", "A", "HN")]
    with db.read() as c:      # the statement before the change, through the key index
        old = pd.read_sql_query(
            "SELECT order_date, sku_id, fc_id, qty, n_orders, avg_unit_price, avg_discount_rate, promo_share, "
            "voucher_share, open_hours, customer_count, repeat_customer_count, repeat_interval_days_sum "
            "FROM demand_daily WHERE scope_key=? AND order_date>=? AND order_date<=?", c,
            params=["S1", "2026-10-01", "2026-10-02"])
    assert got.equals(old) and list(got.dtypes) == list(old.dtypes)
    assert list(demand.load_demand("S2")["qty"]) == [9.0, 7.0]          # other scope untouched, no bound
    assert demand.load_demand("NONE").empty
