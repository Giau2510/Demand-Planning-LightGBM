"""1.3.1 data-review fixes (C4-FIX2): the SKU groups never count a whole-scope data gap as 0 demand (S3), the
actual_daily refresh never reads or replaces a day before the data window (S4), and the accuracy report evaluates only
the forecast days inside the log retention (G4). Fakes only (no BigQuery, no live data)."""
from __future__ import annotations

import math
from datetime import date

from app import db
from app import settings_service as ss
from app.data.demand import data_window, resolve_scope
from app.ml import accuracy_report as ar
from app.ml import daily_refresh as dr
from app.ml import sku_group
from test_v131_refresh import (BQ_SCOPE, D, NOW, OH_TABLE, _d1_ok, _demand_row, _enable, _fake_oh, _freeze,
                               _no_real_bigquery, _oh_row, bq_model)  # noqa: F401 (fixtures)
from test_v131_t3_dev import SCOPE, _actual, _run, enabled  # noqa: F401 (fixture)

SRC = (OH_TABLE, "MEDX")


# ================================================================== S3: SKU groups
def test_group_rows_leave_out_the_days_without_any_demand_row_of_the_scope():
    _freeze(NOW)
    with db.tx() as c:
        for day in ("2026-10-20", "2026-10-21", "2026-10-22"):
            _oh_row(c, "HN", "A", day, 10)
            _oh_row(c, "HN", "B", day, 8)
        _oh_row(c, "HN", "A", "2026-10-23", 0)                            # closed: never a row
        _demand_row(c, "2026-10-20", "A", "HN", 5)
        _demand_row(c, "2026-10-22", "B", "HN", 2)                        # 21/10: no demand row of the scope = gap
        _demand_row(c, "2026-10-21", "A", "HN", 9, scope="BIGQUERY:p.d.other")   # another scope never counts
    with db.read() as c:
        df = sku_group.load_rows(c, BQ_SCOPE, "2026-10-19", "2026-10-23", SRC)
    got = sorted((r.date, r.sku_code, None if math.isnan(r.demand) else r.demand) for r in df.itertuples())
    # B on 20/10 and A on 22/10: open, the scope has demand that day, no row of the key -> NaN (= 0 demand)
    assert got == [("2026-10-20", "A", 5.0), ("2026-10-20", "B", None), ("2026-10-22", "A", None),
                   ("2026-10-22", "B", 2.0)]
    with db.tx() as c:                                                    # the gap day loaded later: counted
        _demand_row(c, "2026-10-21", "B", "HN", 1)
    with db.read() as c:
        df = sku_group.load_rows(c, BQ_SCOPE, "2026-10-19", "2026-10-23", SRC)
    assert sorted(set(df["date"])) == ["2026-10-20", "2026-10-21", "2026-10-22"] and len(df) == 6


# ================================================================== S4: actual_daily inside the data window
def _actual_rows():
    with db.read() as c:
        return [tuple(r) for r in c.execute("SELECT date, sku_code, demand FROM actual_daily WHERE scope_key=? "
                                            "ORDER BY date, sku_code", (BQ_SCOPE,))]


def test_actual_daily_is_clipped_to_the_data_window_start():
    _freeze(NOW)
    with db.tx() as c:
        for day in ("2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"):
            _oh_row(c, "HN", "A", day, 10)
            _demand_row(c, day, "A", "HN", 3)
        c.execute("INSERT INTO actual_daily VALUES (?, '2026-10-18', 'HN', 'A', 7, 10, 'x')", (BQ_SCOPE,))  # before
    n = dr.refresh_actual_daily(BQ_SCOPE, date(2026, 10, 17), date(2026, 10, 21), SRC, floor="2026-10-20")
    # 18/10 is before the window: neither read nor replaced (its stored row stays); 19/10 never written
    assert n == 2 and _actual_rows() == [("2026-10-18", "A", 7.0), ("2026-10-20", "A", 3.0), ("2026-10-21", "A", 3.0)]
    assert dr.refresh_actual_daily(BQ_SCOPE, date(2026, 10, 17), date(2026, 10, 21), SRC, floor="2026-10-22") == 0
    assert dr.refresh_actual_daily(BQ_SCOPE, date(2026, 10, 17), date(2026, 10, 21), SRC) == 4           # no floor


def test_the_refresh_passes_its_data_window_start_to_the_actual_daily_step(bq_model, monkeypatch):
    _enable()
    _fake_oh()
    _d1_ok()
    calls = []
    real = dr.refresh_actual_daily

    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)
    monkeypatch.setattr(dr, "refresh_actual_daily", spy)
    res = dr.run(D)
    assert res["status"] == "PUBLISHED", res
    with db.read() as c:
        start = data_window(c, today=D, scope=resolve_scope(c))["start"]
    (args, kw), = calls
    assert args[:3] == (BQ_SCOPE, date(2026, 10, 14), date(2026, 10, 27)) and kw == {"floor": start}
    assert res["actual_daily_rows"] is not None


# ================================================================== G4: accuracy report inside the log retention
def test_the_accuracy_report_evaluates_only_forecast_days_inside_the_log_retention(enabled):
    ss.save("daily_forecast", {**ss.get("daily_forecast").model_dump(), "log_retention_days": 14})
    with db.tx() as c:                                                    # report of 20/10: cutoff 06/10
        _run(c, "R-05", "2026-10-05", [(1, "2026-10-05", "F1", "S1", 9, "A")])     # older: values still stored
        _run(c, "R-06", "2026-10-06", [(1, "2026-10-06", "F1", "S1", 4, "A")])
        _run(c, "R-19", "2026-10-19", [(1, "2026-10-19", "F1", "S1", 5, "A")])
        _actual(c, [("2026-10-05", "F1", "S1", 9, 8.0), ("2026-10-06", "F1", "S1", 4, 8.0),
                    ("2026-10-19", "F1", "S1", 5, 8.0)])
    out = ar.run("2026-10-20", trigger="MANUAL")
    assert out["status"] == "DONE" and out["n_cells_d1"] == 2 and out["period_start"] == "2026-10-06"
    with db.read() as c:
        full = ar.evaluate(c, SCOPE["scope_key"], date(2026, 10, 19))                  # no lower bound
        cut = ar.evaluate(c, SCOPE["scope_key"], date(2026, 10, 19), since=date(2026, 10, 6))
    assert (full["n_runs"], full["period_start"]) == (3, "2026-10-05")
    assert (cut["n_runs"], cut["period_start"], cut["period_end"]) == (2, "2026-10-06", "2026-10-19")
