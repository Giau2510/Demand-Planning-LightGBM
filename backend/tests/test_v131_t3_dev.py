"""1.3.1 T3 developer checks (B9 accuracy report run on an isolated DB). Integration with fakes (scope stubbed, synthetic
refresh runs / values / actuals); no BigQuery, no real data."""
import json
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app import db
from app import settings_service as ss
from app.messages import AppError
from app.ml import accuracy_report as ar
from app.timeutil import VN_TZ

SCOPE = {"scope_key": "K", "data_source": "BIGQUERY", "label": "p.d.t"}


@pytest.fixture
def enabled(monkeypatch):
    ss.save("daily_forecast", {**ss.get("daily_forecast").model_dump(), "enabled": True})
    monkeypatch.setattr(ar, "resolve_scope", lambda *a, **k: SCOPE)


def _run(c, rid, fdate, values, scope="K", created="2026-10-01T00:00:00+00:00"):
    c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, config_version, "
              "trial_mode, horizon, n_series, n_lightgbm, n_fallback, created_at) VALUES (?,?,?,?, 'PUBLISHED', 'cv', "
              "1, 7, 1, 1, 0, ?)", (rid, scope, fdate, fdate, created))
    c.executemany("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, lgb_raw, "
                  "final_qty, method, group_code) VALUES (?,?,?,?,?,?,?, 'LIGHTGBM', ?)",
                  [(rid, h, td, fc, sku, float(q), q, g) for h, td, fc, sku, q, g in values])


def _actual(c, rows, scope="K"):
    c.executemany("INSERT INTO actual_daily(scope_key, date, fc_code, sku_code, demand, total_open_hours, updated_at) "
                  "VALUES (?,?,?,?,?,?, 'x')", [(scope, *r) for r in rows])


def _count(t):
    with db.read() as c:
        return c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]


def test_disabled_writes_nothing():
    out = ar.run("2026-10-20")
    assert out["status"] == "SKIPPED" and out["reason_code"] == "DAILY_FORECAST_DISABLED"
    assert _count("accuracy_report_runs") == 0


def test_no_scope_is_skipped(monkeypatch):
    ss.save("daily_forecast", {**ss.get("daily_forecast").model_dump(), "enabled": True})

    def _no(*a, **k):
        raise AppError("NO_ACTIVE_DATASET", 409)
    monkeypatch.setattr(ar, "resolve_scope", _no)
    out = ar.run("2026-10-20")
    assert out["status"] == "SKIPPED" and out["reason_code"] == "NO_ACTIVE_DATASET"
    assert _count("accuracy_report_runs") == 0


def test_no_data_still_writes_the_info_sheet(enabled, tmp_path):
    out = ar.run("2026-10-20", job_id=None, trigger="MANUAL")
    assert out["status"] == "DONE" and out["reason_code"] == "ACCURACY_REPORT_NO_DATA"
    assert out["n_cells_d7"] == 0 and out["period_start"] is None
    p = Path(out["report_path"])
    assert p.exists() and str(p).startswith(str(tmp_path)) and p.parent.name == "theo-doi"
    wb = load_workbook(p)
    assert wb.sheetnames == ["Thông tin", "Ngày thứ 1", "7 ngày"]
    assert wb["Thông tin"]["A1"].value == "Chạy thử – chưa dùng để mua hàng"
    with db.read() as c:
        r = db.one(c, "SELECT * FROM accuracy_report_runs")
    assert r["run_kind"] == "MANUAL" and r["status"] == "DONE" and r["n_cells"] == 0 and r["report_path"] == str(p)


def test_latest_run_open_days_and_closed_targets(enabled):
    with db.tx() as c:
        # 18/10: two runs; the newer one (same created_at -> rowid DESC) wins
        _run(c, "R-OLD", "2026-10-18", [(1, "2026-10-18", "F1", "S1", 100, "A")])
        _run(c, "R-NEW", "2026-10-18", [(1, "2026-10-18", "F1", "S1", 10, "A"), (2, "2026-10-19", "F1", "S1", 12, "A"),
                                       (8, "2026-10-25", "F1", "S1", 99, "A")])
        # 19/10: h1 open; S2 closed (hours 0), S3 unknown hours; h2 targets the business day -> not closed yet
        _run(c, "R-19", "2026-10-19", [(1, "2026-10-19", "F1", "S2", 5, "C"), (1, "2026-10-19", "F1", "S3", 5, None),
                                      (1, "2026-10-19", "F2", "S1", 4, None), (2, "2026-10-20", "F2", "S1", 4, None)])
        _run(c, "R-OTHER", "2026-10-18", [(1, "2026-10-18", "F1", "S1", 50, "A")], scope="Z",
             created="2026-10-02T00:00:00+00:00")
        _actual(c, [("2026-10-18", "F1", "S1", 10, 8), ("2026-10-19", "F1", "S1", 20, 8),
                    ("2026-10-19", "F1", "S2", 5, 0), ("2026-10-19", "F1", "S3", 5, None),
                    ("2026-10-19", "F2", "S1", None, 8), ("2026-10-20", "F2", "S1", 4, 8)])
    out = ar.run("2026-10-20", trigger="CATCH_UP")
    assert out["status"] == "DONE" and out["reason_code"] == "ACCURACY_REPORT_WRITTEN"
    # D1: F1/S1 18/10 (10 vs 10, DUNG), F2/S1 19/10 (4 vs demand NULL -> 0, B tol 3 -> DU_NHIEU); D7 adds F1/S1 h2
    assert (out["n_cells_d1"], out["n_cells_d7"]) == (2, 3)
    assert (out["period_start"], out["period_end"]) == ("2026-10-18", "2026-10-19")
    d1, d7 = out["summary"]["D1"], out["summary"]["D7"]
    assert d1["slots"] == 2 and d7["slots"] == 3
    assert d1["qty_dev"]["DU_NHIEU"]["B"] == 4 and d1["qty_dev"]["DUNG"]["A"] == 0
    assert d7["qty_dev"]["THIEU_IT"]["A"] == 8 and d7["demand"]["TOTAL"] == 30
    with db.read() as c:
        r = db.one(c, "SELECT * FROM accuracy_report_runs")
    assert r["run_kind"] == "SCHEDULED" and r["n_cells"] == 3 and r["error"] is None
    assert json.loads(r["summary_json"])["D7"]["slots"] == 3
    wb = load_workbook(out["report_path"])
    col_a = [c.value for c in wb["7 ngày"]["A"]]
    assert "Kỳ: Tháng 2026-10 — 3 slot (ngày đích × h)" in col_a and "Tổng demand thực" in col_a
    assert col_a.count("(2) Tỷ trọng SKU") == 2      # the month, then the whole period


def test_file_name_never_overwrites(enabled, monkeypatch):
    monkeypatch.setattr(ar, "now_vn", lambda: datetime(2026, 10, 26, 9, 30, 5, tzinfo=VN_TZ))
    a, b = ar.run("2026-10-26"), ar.run("2026-10-26")
    assert Path(a["report_path"]).name == "bao-cao-do-chinh-xac-20261026-093005.xlsx"
    assert Path(b["report_path"]).name == "bao-cao-do-chinh-xac-20261026-093005-2.xlsx"
    assert _count("accuracy_report_runs") == 2


def test_workbook_error_keeps_the_result_and_alerts_once(enabled, monkeypatch):
    def _boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ar, "write_workbook", _boom)
    with db.tx() as c:
        _run(c, "R1", "2026-10-18", [(1, "2026-10-18", "F1", "S1", 10, "A")])
        _actual(c, [("2026-10-18", "F1", "S1", 10, 8)])
    out = ar.run("2026-10-20")
    assert out["status"] == "DONE" and out["reason_code"] == "ACCURACY_REPORT_NOT_WRITTEN"
    assert out["report_path"] is None and "disk full" in out["error"] and out["n_cells_d1"] == 1
    with db.read() as c:
        r = db.one(c, "SELECT * FROM accuracy_report_runs")
        alerts = db.rows(c, "SELECT level, code FROM alerts WHERE code='ACCURACY_REPORT_NOT_WRITTEN'")
    assert r["status"] == "DONE" and r["report_path"] is None and "disk full" in r["error"]
    assert json.loads(r["summary_json"])["D1"]["slots"] == 1
    assert alerts == [{"level": "WARNING", "code": "ACCURACY_REPORT_NOT_WRITTEN"}]


def test_other_error_is_failed(enabled, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("bad")
    monkeypatch.setattr(ar, "evaluate", _boom)
    out = ar.run("2026-10-20", trigger="MANUAL")
    assert out["status"] == "FAILED" and out["reason_code"] == ar.FAILED_CODE and "bad" in out["error"]
    with db.read() as c:
        r = db.one(c, "SELECT * FROM accuracy_report_runs")
    assert r["status"] == "FAILED" and r["run_kind"] == "MANUAL" and "bad" in r["error"]
