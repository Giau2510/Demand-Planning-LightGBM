"""1.2.9 (sixth batch, 20/10/2026): a day with total_open_hours = 0 AND orders is a value, not a missing one.

The source has 931 such SKU x FC x day keys (15:05 refresh of 20/10); what they mean is the owner's review (workbook
reports/demandforecast_zero_open_hours_with_orders_20261020.xlsx). Until then the code must keep them exactly as read: stored
as 0 with status OK, no training stop because of them, and 0 in the two open-hours features - never NaN, never replaced,
never carried to the next day. Temporary databases (conftest), FakeBQ, synthetic rows."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from app import db, timeutil
from app import settings_service as ss
from app.data import open_hours
from app.ml.features import Panel, feature_names, features_at, static_codes


def test_zero_open_hours_with_orders_are_stored_as_zero_and_do_not_stop_the_training(client):
    from test_v129_backfill_history_patterns import _production
    from test_v129c_window_spike_customer import BQ_SCOPE, _row
    from app import sync
    y = timeutil.today_vn() - timedelta(days=1)
    _production([_row(y, "ZERO", 7, 0.0, 0.0, open_hours_items=1, open_hours_item_values=1, open_hours_no_item_rows=0),
                 # two items, both 0 (2 of the 931 keys): one value, not MULTI_ITEM
                 _row(y, "ZERO2", 4, 0.0, 0.0, open_hours_items=2, open_hours_item_values=2, open_hours_no_item_rows=0),
                 _row(y, "FULL", 3)])
    res = sync.run_d1_sync("J1")
    assert res["open_hours_status_rows"] == {"OK": 3, "MISSING": 0, "OUT_OF_RANGE": 0, "CONFLICT": 0, "MULTI_ITEM": 0,
                                             "NOT_READ": 0}
    with db.read() as c:
        got = {r[0]: (r[1], r[2], r[3]) for r in c.execute(
            "SELECT sku_id, open_hours, open_hours_status, qty FROM demand_daily WHERE scope_key=?", (BQ_SCOPE,))}
        chk = open_hours.window_check(c, BQ_SCOPE, str(y), str(y))
    assert got == {"ZERO": (0.0, "OK", 7.0), "ZERO2": (0.0, "OK", 4.0), "FULL": (24.0, "OK", 3.0)}
    assert chk["ok"] and chk["ok_rows"] == 3 and not chk["not_ok"]          # 0 is not a reason for OPEN_HOURS_INVALID


def test_zero_open_hours_enter_the_features_as_zero_and_are_never_carried():
    T = 8
    dates = pd.date_range("2026-09-01", periods=T, freq="D")
    hours = np.array([[24.0, 24.0, 0.0, 24.0, 0.0, np.nan, 24.0, 24.0]])        # day 5: no order -> unknown
    p = Panel([("A", "F")], dates, np.ones((1, T)), np.full((1, T), 10.0), np.full((1, T), np.nan), np.zeros((1, T)),
              np.zeros(1, dtype=int), np.zeros(T, dtype=bool), {"A": 0}, {"F": 0}, hours=hours)
    cfg = ss.ModelSettings(feature_open_hours=True)
    names = feature_names(cfg)
    sc, fcc = static_codes(p)

    def oh(t):
        x = features_at(p, p.Y, p.price, p.disc, p.promo, p.dates, t, cfg, sc, fcc)
        return x[0, names.index("open_hours_last")], x[0, names.index("open_hours_mean_7")]

    last, mean7 = oh(3)
    assert last == 0.0 and mean7 == 16.0                     # the 0 of day 2 is the value, and it counts in the mean
    last, mean7 = oh(6)
    assert np.isnan(last) and mean7 == 14.4                  # day 5 stays unknown: the 0 of day 4 is not carried
