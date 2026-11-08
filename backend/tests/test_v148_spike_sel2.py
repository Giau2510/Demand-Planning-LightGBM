"""1.4.8 C-2: SEL2 wiring of the spike cleaning (ml/sel2/pipeline.py, store.py). Switch OFF: no spike code runs (the
module is poisoned) and the published values are identical with or without stored flags; ON: only the LightGBM frame
and the TSB / DOW4 / AVG7 daily demand are cleaned (spike.clean_frame / clean_daily as of the day, training as of the
origin), actuals / groups / scope stay raw; flags missing -> SPIKE_CLEANING_SKIPPED, never a failure.
Isolated test DB, synthetic BIGQUERY-like rows, real LightGBM on 10 series: integration with fakes."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app import db
from app import settings_service as ss
from app.ml.sel2 import lgbm, pipeline, spike, store

from test_v140_t4a_pipeline import SCOPE, _plenty_of_memory, _seed

ORIGIN = date(2026, 10, 26)
D = date(2026, 10, 28)
SPIKE_DAY = date(2026, 10, 20)


def _flag_row(day=SPIKE_DAY, sku="S01", fc="FC1", qty=50.0, kept=2.0, computed_for=D):
    """One stored flagged line: regular customer, T1 only, no T7 decision pending (gap median unknown)."""
    r = {"d": pd.Timestamp(day), "fc_code": fc, "sku_code": sku, "so_code": "SO1", "customer_id": "C1", "qty": qty,
         "group_code": "B", "min_qty": 5.0, "n_prev": 5, "cust_med": kept, "gap_med": np.nan, "n_gaps": 0,
         "next_day": pd.NaT, "kept": kept, "T1": 1, "T2": 0, "T4": 0, "T7": 0, "n_signals_raw": 1,
         "exc_wholesale": False, "exc_periodic": False, "exc_demand": False, "is_regular": True}
    with db.tx() as c:
        spike.write_flags(c, SCOPE, pd.DataFrame([r]), computed_for, day, day)


def _published(run_id):
    with db.read() as c:
        return pd.DataFrame(db.rows(c, "SELECT sku_code, fc_code, target_date, lgb_raw, final_qty, method FROM "
                                       "forecast_refresh_values WHERE run_id=? ORDER BY sku_code, fc_code, target_date",
                                    (run_id,)))


def _cands():
    with db.read() as c:
        return {m: f.sort_values(["sku_code", "fc_code", "horizon"]).reset_index(drop=True)
                for m, f in store.read_day(c, SCOPE, D).items()}


def _poison(monkeypatch):
    for name in ("read_flags", "Excess", "clean_frame", "clean_daily"):
        monkeypatch.setattr(spike, name, lambda *a, **k: pytest.fail("spike code ran with the switch OFF"))


@pytest.fixture
def ready(sel2_on, monkeypatch):
    monkeypatch.setattr(pipeline, "MIN_COMMIT_MB", 0)
    _plenty_of_memory(monkeypatch)
    _seed()
    with db.tx() as c:          # the spike line's day: 50 units of S01 x FC1
        c.execute("UPDATE demand_daily SET qty = 52 WHERE order_date=? AND sku_id='S01' AND fc_id='FC1'",
                  (str(SPIKE_DAY),))
        if not c.execute("SELECT changes()").fetchone()[0]:
            c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                      "loaded_at, open_hours, open_hours_status) VALUES (?, 'BIGQUERY', ?, 'S01', 'FC1', 52, 1, 'x', "
                      "10, 'OK')", (SCOPE, str(SPIKE_DAY)))


def test_off_nothing_of_spike_runs_and_flags_change_nothing(ready, monkeypatch):
    _poison(monkeypatch)
    pipeline.train_week(ORIGIN, scope_key=SCOPE)
    r1 = pipeline.run_day(D, scope_key=SCOPE, trigger="test")
    first, cands1 = _published(r1["run_id"]), _cands()
    _flag_row()                                   # flags stored (as SPIKE_LINES would with the switch OFF)
    r2 = pipeline.run_day(D, scope_key=SCOPE, trigger="test", force=True)
    pd.testing.assert_frame_equal(first, _published(r2["run_id"]))
    for m, f in _cands().items():
        pd.testing.assert_frame_equal(cands1[m], f)
    with db.read() as c:
        run = db.one(c, "SELECT config_version, detail_json FROM forecast_refresh_runs WHERE id=?", (r2["run_id"],))
        tr = db.rows(c, "SELECT detail_json FROM candidate_train_runs")
        cr = db.rows(c, "SELECT detail_json FROM candidate_runs")
    assert run["config_version"] == store.config_version(ss.get("sel2_pipeline"))
    assert "spike" not in run["detail_json"].lower()
    assert all("spike" not in r["detail_json"] for r in tr + cr)
    assert "spike_cleaning" not in r2["candidates"]


def test_on_cleans_frame_and_daily_as_of_the_day_actuals_raw(ready, monkeypatch):
    _flag_row()
    ss.update("sel2_pipeline", {"spike_cleaning": True})
    seen = {"train": [], "forecast": []}
    real_train, real_fc = lgbm.train, lgbm.forecast
    monkeypatch.setattr(lgbm, "train", lambda f, *a, **k: (seen["train"].append(f), real_train(f, *a, **k))[1])
    monkeypatch.setattr(lgbm, "forecast", lambda f, *a, **k: (seen["forecast"].append(f), real_fc(f, *a, **k))[1])
    t = pipeline.train_week(ORIGIN, scope_key=SCOPE)
    assert t["spike_cleaning"]["excess_total"] == 48.0 and not t["spike_cleaning"]["skipped"]
    inputs = pipeline.load(SCOPE, D)
    raw_daily = inputs.daily.copy()
    res = pipeline.run_day(D, scope_key=SCOPE, trigger="test", inputs=inputs)
    assert res["status"] == "PUBLISHED"
    # LightGBM frames: equal to spike.clean_frame of the raw frame (training as of the origin, forecast as of D)
    with db.read() as c:
        ex = spike.Excess(spike.read_flags(c, SCOPE), keys=inputs.keys)
    train_inputs = pipeline.load(SCOPE, ORIGIN)              # the training reads the data before its origin
    assert len(seen["train"]) == 3
    for f in seen["train"]:
        pd.testing.assert_frame_equal(f, spike.clean_frame(train_inputs.frame, ex.cells_frame(ORIGIN, 1, 4), ORIGIN))
    for f in seen["forecast"]:
        pd.testing.assert_frame_equal(f, spike.clean_frame(inputs.frame, ex.cells_frame(D, 1, 4), D))
    sel = seen["forecast"][0]
    row = sel[(sel["sku_id"] == "S01") & (sel["fc_id"] == "FC1") & (sel["od"] == pd.Timestamp(SPIKE_DAY))]
    assert row["qty"].tolist() == [4.0]                              # 52 - (50 - 2)
    # inputs (actuals, groups, scope) untouched; AVG7 / DOW4 / TSB from the cleaned daily
    np.testing.assert_array_equal(inputs.daily, raw_daily)
    from app.ml.sel2 import simple
    k, g, e = ex.cells_asof(D, 1, 4)
    y = spike.clean_daily(inputs.daily, k, g, e, D)
    m = inputs.scope_mask(D)
    gd = inputs.g(D)
    sk = inputs.scope_keys(D)
    avg7 = pd.DataFrame({"sku_code": sk["sku_code"], "fc_code": sk["fc_code"], "v": simple.avg7(y[m, :gd], gd)})
    got = _cands()["AVG7"].query("horizon == 1").merge(avg7, on=["sku_code", "fc_code"])
    np.testing.assert_allclose(got["value"], got["v"])
    with db.read() as c:
        run = db.one(c, "SELECT config_version, detail_json FROM forecast_refresh_runs WHERE id=?", (res["run_id"],))
    assert run["config_version"] != "SEL2:326f4ea688f6"             # ON runs are distinguishable
    assert '"spike_cleaning": true' in run["detail_json"] and '"excess_total": 48.0' in run["detail_json"]


def test_on_without_flags_skips_cleaning_with_a_flag_never_fails(ready):
    ss.update("sel2_pipeline", {"spike_cleaning": True})
    pipeline.train_week(ORIGIN, scope_key=SCOPE)
    res = pipeline.run_day(D, scope_key=SCOPE, trigger="test")
    assert res["status"] == "PUBLISHED" and "SPIKE_CLEANING_SKIPPED" in res["flags"]
    with db.read() as c:
        al = db.rows(c, "SELECT level, code FROM alerts WHERE code='SPIKE_CLEANING_SKIPPED'")
    assert al and {a["level"] for a in al} == {"WARNING"}


def test_on_flags_too_old_for_t7_skip(ready):
    """a pending T7 decision (median gap 10, no next purchase seen, flags computed long before D) -> Excess raises."""
    ss.update("sel2_pipeline", {"spike_cleaning": True})
    old = date(2026, 9, 1)
    r = {"d": pd.Timestamp(old - timedelta(days=1)), "fc_code": "FC1", "sku_code": "S01", "so_code": "SO1",
         "customer_id": "C1", "qty": 50.0, "group_code": "B", "min_qty": 5.0, "n_prev": 5, "cust_med": 2.0,
         "gap_med": 30.0, "n_gaps": 3, "next_day": pd.NaT, "kept": 2.0, "T1": 1, "T2": 0, "T4": 0, "T7": 0,
         "n_signals_raw": 1, "exc_wholesale": False, "exc_periodic": False, "exc_demand": False, "is_regular": True}
    with db.tx() as c:
        spike.write_flags(c, SCOPE, pd.DataFrame([r]), old, old - timedelta(days=1), old - timedelta(days=1))
    pipeline.train_week(ORIGIN, scope_key=SCOPE)
    c = pipeline.candidates_for_day(D, scope_key=SCOPE)
    assert "SPIKE_CLEANING_SKIPPED" in c["flags"] and c["spike_cleaning"]["skipped"]


def test_on_flags_of_an_earlier_run_still_clean_with_the_stale_flag(ready):
    _flag_row(computed_for=D - timedelta(days=2))
    ss.update("sel2_pipeline", {"spike_cleaning": True})
    pipeline.train_week(ORIGIN, scope_key=SCOPE)
    c = pipeline.candidates_for_day(D, scope_key=SCOPE)
    assert "SPIKE_FLAGS_STALE" in c["flags"] and "SPIKE_CLEANING_SKIPPED" not in c["flags"]
    assert c["spike_cleaning"]["stale"] and c["spike_cleaning"]["excess_total"] == 48.0


def test_on_stale_flags_use_the_excess_as_of_their_run_and_expire_after_7_days(ready):
    ss.update("sel2_pipeline", {"spike_cleaning": True})
    pipeline.train_week(ORIGIN, scope_key=SCOPE)
    inputs = pipeline.load(SCOPE, D)
    s = ss.get("sel2_pipeline")
    _flag_row(day=date(2026, 10, 10), computed_for=D - timedelta(days=8))
    sp = pipeline._spike(s, SCOPE, D, inputs, "day")
    assert sp["skipped"] and "more than 7 days" in sp["reason"]
    _flag_row(computed_for=D - timedelta(days=2))
    sp = pipeline._spike(s, SCOPE, D, inputs, "day")
    assert not sp["skipped"] and sp["stale"] and sp["excess_asof"] == str(D - timedelta(days=2))
    assert pipeline._spike_flags(sp) == ["SPIKE_FLAGS_STALE"]
    # the excess as of the flags' run day = a fresh Excess as of that day
    with db.read() as c:
        ex = spike.Excess(spike.read_flags(c, SCOPE), keys=inputs.keys)
    pd.testing.assert_frame_equal(sp["_clean"][3], ex.cells_frame(D - timedelta(days=2), 1, 4))


def test_on_flags_before_the_data_window_are_not_read(ready):
    """fix loop 1: _spike reads only the flags of days >= inputs.window_start. A flagged line before the window (one
    that would add excess, one whose T7 decision is still pending and would make Excess raise) changes nothing."""
    ss.update("sel2_pipeline", {"spike_cleaning": True})
    pipeline.train_week(ORIGIN, scope_key=SCOPE)
    inputs = pipeline.load(SCOPE, D)
    s = ss.get("sel2_pipeline")
    _flag_row()
    base = pipeline._spike(s, SCOPE, D, inputs, "day")
    assert not base["skipped"] and base["excess_total"] == 48.0
    out = date.fromisoformat(inputs.window_start) - timedelta(days=1)
    _flag_row(day=out, qty=80.0)                                         # would add 78 of excess if read
    pend = {"d": pd.Timestamp(out - timedelta(days=1)), "fc_code": "FC1", "sku_code": "S02", "so_code": "SO9",
            "customer_id": "C2", "qty": 50.0, "group_code": "B", "min_qty": 5.0, "n_prev": 5, "cust_med": 2.0,
            "gap_med": 30.0, "n_gaps": 3, "next_day": pd.NaT, "kept": 2.0, "T1": 1, "T2": 0, "T4": 0, "T7": 0,
            "n_signals_raw": 1, "exc_wholesale": False, "exc_periodic": False, "exc_demand": False,
            "is_regular": True}
    with db.tx() as c:                                                   # T7 pending, computed long before D
        spike.write_flags(c, SCOPE, pd.DataFrame([pend]), out, out - timedelta(days=1), out - timedelta(days=1))
    sp = pipeline._spike(s, SCOPE, D, inputs, "day")
    assert not sp["skipped"] and sp["excess_total"] == 48.0 and sp["excess_cells"] == base["excess_cells"]
    pd.testing.assert_frame_equal(sp["_clean"][3], base["_clean"][3])
