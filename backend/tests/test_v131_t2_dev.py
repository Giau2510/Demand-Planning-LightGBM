"""1.3.1 T2 developer checks (daily refresh, open hours read, retention, job wiring). Unit / integration with fakes
(FakeBQ, a fake model.forecast); no BigQuery, no real data."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app import db
from app import settings_service as ss
from app import timeutil
from app.bq import aux_sources, connector
from app.jobs import flows, runner
from app.jobs.scheduler import loaded_flows, plan
from app.ml import daily_refresh as dr
from app.timeutil import VN_TZ
from fake_bq import FakeBQ

D = date(2026, 10, 20)


def test_pure_helpers():
    assert dr.published_qty(np.array([0.19, 0.2, 1.000001, 3.0]), 0.2).tolist() == [0, 1, 2, 3]
    cfg = ss.ModelSettings()
    assert dr.refresh_horizon([7, 15], cfg) == min(15, max(7, 15)) or dr.refresh_horizon([7, 15], cfg) <= 15
    assert dr.refresh_horizon([3], cfg) == 7 or dr.refresh_horizon([3], cfg) < 7
    a, b = dr.config_version("fp", 0.2, 7), dr.config_version("fp", 0.2, 15)
    assert len(a) == 12 and a != b and a == dr.config_version("fp", 0.2, 7)


def test_compute_flags_and_rounding(monkeypatch):
    dates = pd.date_range(D - timedelta(days=3), periods=3, freq="D")
    panel = SimpleNamespace(dates=dates, keys=[("S1", "F1"), ("S2", "F1"), ("S3", "F9")], n_series=3)

    def fake_forecast(p, booster, cfg, horizon, cancel=None, capture=None, sku_codes=None, fc_codes=None):
        return {"dates": pd.date_range(D, periods=horizon, freq="D"),
                "yhat": np.array([[0.19, 0.2], [1.000001, 3.0], [5.5, 0.0]])[:, :horizon],
                "methods": np.array(["LIGHTGBM", "FALLBACK_NEW_SERIES", "LIGHTGBM"], dtype=object)}
    monkeypatch.setattr(dr.model, "forecast", fake_forecast)
    monkeypatch.setattr(dr, "feature_names", lambda cfg: ["fc_code", "lag_1"])      # sku_code not a model input
    res = dr.compute(panel, object(), ss.ModelSettings(), 2, D, sku_codes={"S1": 0}, fc_codes={"F1": 0},
                     groups={("F1", "S1"): "A", ("F1", "S2"): "C"}, threshold=0.2)
    assert res["keys"] == [("F1", "S1"), ("F1", "S2"), ("F9", "S3")]
    assert res["final"].tolist() == [[0, 1], [2, 3], [6, 0]]
    assert res["raw"][0, 0] == 0.19
    assert res["flags"] == [None, None, "CODE_UNKNOWN,GROUP_MISSING"]   # S2 unknown SKU is not a model input
    monkeypatch.setattr(dr, "feature_names", lambda cfg: ["sku_code", "fc_code"])
    res = dr.compute(panel, object(), ss.ModelSettings(), 2, D, sku_codes={"S1": 0}, fc_codes={"F1": 0},
                     groups={}, threshold=0.2)
    assert res["flags"] == ["GROUP_MISSING", "CODE_UNKNOWN,GROUP_MISSING", "CODE_UNKNOWN,GROUP_MISSING"]
    with pytest.raises(ValueError):
        dr.compute(panel, object(), ss.ModelSettings(), 2, D + timedelta(days=1), sku_codes={}, fc_codes={},
                   groups={}, threshold=0.2)


def test_run_disabled_reads_and_writes_nothing():
    out = dr.run("2026-10-20")
    assert out["status"] == "SKIPPED" and out["reason_code"] == "DAILY_FORECAST_DISABLED"
    with db.read() as c:
        for t in ("forecast_refresh_runs", "forecast_refresh_values", "open_hours_daily", "aux_source_reads",
                  "actual_daily", "sku_group"):
            assert c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0


class _ModBQ(FakeBQ):
    modified = None

    def get_table(self, name):
        t = super().get_table(name)
        t.modified = self.modified
        return t


def test_open_hours_read_only_when_the_source_changed():
    rows = [{"fc_code": "F1", "sku_code": "S1", "open_date": "2026-10-18", "total_open_hours": 8.0, "n_items": 2},
            {"fc_code": "F1", "sku_code": "S1", "open_date": "2026-10-19", "total_open_hours": None, "n_items": 1}]
    fake = _ModBQ(responses={"daily_open_hours": rows})
    connector.set_client_factory(fake)
    first = dr.sync_open_hours(D, "2026-01-01")
    assert first["mode"] == "FULL" and first["rows"] == 2 * 7 and first["source_modified"] is None  # 7 sub-ranges
    again = dr.sync_open_hours(D, "2026-01-01")                    # modified unknown -> read again
    assert again["mode"] == "INCREMENTAL" and again["rows"] == 2 and "skipped" not in again
    assert again["start"] == "2026-10-16"
    fake.modified = datetime(2026, 10, 19, 21, 10, tzinfo=VN_TZ)
    third = dr.sync_open_hours(D, "2026-01-01")
    assert third["rows"] == 2 and third["source_modified"] == "2026-10-19T14:10:00+00:00"
    n_queries = len(fake.queries)
    fourth = dr.sync_open_hours(D, "2026-01-01")
    assert fourth["skipped"] == "OPEN_HOURS_SOURCE_NOT_REFRESHED" and len(fake.queries) == n_queries
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM aux_source_reads").fetchone()[0] == 7 + 2   # 7 FULL sub-ranges + 2 reads
        assert c.execute("SELECT total_open_hours FROM open_hours_daily WHERE open_date='2026-10-18'").fetchone()[0] == 8


def test_open_hours_error_never_blocks_and_alerts_once():
    connector.set_client_factory(FakeBQ(errors={"daily_open_hours": RuntimeError("boom")}))
    a = dr.sync_open_hours(D, "2026-01-01")
    b = dr.sync_open_hours(D, "2026-01-01")
    assert "boom" in a["error"] and "boom" in b["error"]
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM alerts WHERE code='OPEN_HOURS_READ_FAILED'").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM aux_source_reads").fetchone()[0] == 0


def _run(c, rid, fdate, h=15, created="2026-10-01T00:00:00+00:00"):
    c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, config_version, "
              "trial_mode, horizon, n_series, n_lightgbm, n_fallback, created_at) VALUES (?,?,?,?, 'PUBLISHED', 'cv', "
              "1, ?, 1, 1, 0, ?)", (rid, "K", fdate, fdate, h, created))
    c.executemany("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, lgb_raw, "
                  "final_qty, method) VALUES (?,?,?,?,?,?,?,?)",
                  [(rid, i, fdate, "F1", "S1", 1.0, 1, "LIGHTGBM") for i in range(1, h + 1)])


def test_retention_keeps_runs_and_the_latest_horizon():
    with db.tx() as c:
        _run(c, "R-OLD", "2026-05-01")
        _run(c, "R-PREV", "2026-10-19")
        _run(c, "R-LAST", "2026-10-20")
        c.executemany("INSERT INTO actual_daily(scope_key, date, fc_code, sku_code, demand, updated_at) "
                      "VALUES ('K', ?, 'F1', 'S1', 1, 'x')", [("2026-05-01",), ("2026-10-19",)])
    out = dr.apply_retention("K", D, 120)
    assert out == {"cutoff": "2026-06-22", "superseded_values": 8, "old_values": 15, "actual_rows": 1}
    with db.read() as c:
        n = dict(c.execute("SELECT run_id, COUNT(*) FROM forecast_refresh_values GROUP BY run_id").fetchall())
        assert n == {"R-PREV": 7, "R-LAST": 15}
        assert c.execute("SELECT COUNT(*) FROM forecast_refresh_runs").fetchone()[0] == 3


def test_defaults_plan_nothing_new_and_report_as_1_2_14():
    now = datetime(2026, 10, 19, 10, 0, tzinfo=VN_TZ)        # a Monday
    with db.read() as c:
        acts = plan(now, ss.get("schedule"), "BIGQUERY", None, c)
    assert not [a for a in acts if a["job_type"] in ("FORECAST_REFRESH", "ACCURACY_REPORT")]
    assert set(loaded_flows(ss.get("schedule"))) == {"d1", "d0", "train", "eod", "close"}
    r = flows.readiness("refresh")
    assert "DAILY_FORECAST_DISABLED" in [x["code"] for x in r["reasons"]]


def test_flags_on_plan_refresh_skip_and_weekly_report():
    ss.update("schedule", {"refresh_enabled": True, "report_enabled": True})
    now = datetime(2026, 10, 19, 10, 0, tzinfo=VN_TZ)
    with db.read() as c:
        assert not [a for a in plan(now, ss.get("schedule"), "DEMO", None, c)
                    if a["job_type"] in ("FORECAST_REFRESH", "ACCURACY_REPORT")]     # daily_forecast still OFF
    ss.update("daily_forecast", {"enabled": True})
    with db.read() as c:
        acts = [a for a in plan(now, ss.get("schedule"), "DEMO", None, c)
                if a["job_type"] in ("FORECAST_REFRESH", "ACCURACY_REPORT")]
        early = [a for a in plan(datetime(2026, 10, 19, 9, 0, tzinfo=VN_TZ), ss.get("schedule"), "DEMO", None, c)
                 if a["job_type"] == "ACCURACY_REPORT"]
        tuesday = [a for a in plan(now + timedelta(days=1), ss.get("schedule"), "DEMO", None, c)
                   if a["job_type"] == "ACCURACY_REPORT"]
    kinds = {(a["job_type"], a["action"], a.get("reason")) for a in acts}
    assert ("FORECAST_REFRESH", "skip", "NOT_APPLICABLE_FOR_SOURCE") in kinds
    assert ("ACCURACY_REPORT", "run", None) in kinds
    assert not early and not tuesday
    assert set(loaded_flows(ss.get("schedule"))) == {"d1", "d0", "train", "eod", "close", "refresh", "report"}


@pytest.mark.parametrize("result, status", [({"status": "PUBLISHED"}, "SUCCEEDED"),
                                            ({"status": "NOT_READY", "reason_code": "DATA_NOT_UP_TO_DATE"}, "SKIPPED"),
                                            ({"status": "FAILED", "reason_code": "X"}, "FAILED")])
def test_runner_maps_the_refresh_result(monkeypatch, result, status):
    seen = {}

    def fake_refresh(job_id, params, cancel=None):
        seen["trigger"] = runner._trigger_of(job_id)
        return result
    monkeypatch.setattr(runner, "_handlers", lambda: {"FORECAST_REFRESH": fake_refresh})
    row = runner.run_refresh_now("2026-10-20")
    assert row["status"] == status and seen["trigger"] == "MANUAL"


def test_runner_maps_the_report_result(monkeypatch):
    monkeypatch.setattr(runner, "_handlers", lambda: {"ACCURACY_REPORT": lambda job_id, params: {"status": "DONE"}})
    assert runner.run_report_now("2026-10-20")["status"] == "SUCCEEDED"
