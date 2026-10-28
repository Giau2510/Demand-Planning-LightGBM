"""1.3.1 T4a developer checks: API of the daily forecast refresh, accuracy reports, feature table, feature importance and
the CLI preset. Integration with fakes (TestClient on an isolated temporary database, fixture rows inserted directly,
background.submit replaced); no BigQuery, no real data."""
import io
import json
from datetime import datetime, timezone

import pytest
from openpyxl import load_workbook

from app import cli, db, paths, timeutil
from app import settings_service as ss
from app.api import background, daily_routes
from app.ml import feature_report

SK = {"scope_key": "SK1", "data_source": "DEMO", "label": "test scope"}
NOW = datetime(2026, 10, 29, 6, 0, tzinfo=timezone.utc)          # 13:00 Vietnam time, after the 12:00 deadline


@pytest.fixture
def scoped(monkeypatch):
    monkeypatch.setattr(daily_routes, "resolve_scope", lambda c=None, source=None: dict(SK))
    timeutil.set_now_override(lambda: NOW)


def _run(c, rid, scope, fd, created, trial=1):
    c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, trigger, "
              "training_run_id, model_version, model_fingerprint, config_version, trial_mode, horizon, n_series, "
              "n_lightgbm, n_fallback, created_at, detail_json) VALUES (?,?,?,?, 'PUBLISHED', 'MANUAL', 'TR-1', 'MV-1', "
              "'fp1', 'cv1', ?, 2, 2, 2, 0, ?, ?)",
              (rid, scope, fd, "2026-10-28" if fd == "2026-10-29" else "2026-10-27", trial, created,
               json.dumps({"rounding_threshold": 0.2})))
    for h, td in ((1, fd), (2, "2026-10-30")):
        for fc, sku, g in (("FC1", "S_A", "A"), ("FC2", "S%B", "C")):
            c.execute("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, lgb_raw, "
                      "final_qty, method, group_code, flags) VALUES (?,?,?,?,?,?,?, 'LIGHTGBM', ?, NULL)",
                      (rid, h, td, fc, sku, 0.19 * h, h - 1, g))


@pytest.fixture
def runs(scoped):
    with db.tx() as c:
        _run(c, "FRR-OLD", "SK1", "2026-10-28", "2026-10-28T02:00:00+00:00")
        _run(c, "FRR-NEW", "SK1", "2026-10-29", "2026-10-29T02:00:00+00:00")
        _run(c, "FRR-OTHER", "SK2", "2026-10-29", "2026-10-29T03:00:00+00:00")


def test_status_disabled_default(client, scoped):
    s = client.get("/api/daily-forecast/status").json()
    assert s["enabled"] is False and s["trial_mode"] is True and s["trial_label"] is None
    assert s["stale"] is False and s["stale_code"] is None and s["last_run"] is None and s["outdated"] is False
    assert s["today"] == "2026-10-29" and s["trial_confirm_text"] == "TAT-CHAY-THU-2026-10-29"
    assert s["refresh_deadline"] == "12:00" and s["message"] is None and s["last_report"] is None
    assert client.post("/api/daily-forecast/refresh").status_code == 409
    assert client.post("/api/daily-forecast/refresh").json()["code"] == "DAILY_FORECAST_DISABLED"
    assert client.post("/api/accuracy-reports/run").json()["code"] == "DAILY_FORECAST_DISABLED"


def test_no_scope_shows_nothing(client, monkeypatch):
    with db.tx() as c:
        _run(c, "FRR-X", "SK1", "2026-10-29", "2026-10-29T02:00:00+00:00")
    assert client.get("/api/daily-forecast/runs").json() == []
    assert client.get("/api/daily-forecast/values").json()["run"] is None
    assert client.get("/api/daily-forecast/status").json()["last_run"] is None
    assert client.get("/api/daily-forecast/export.xlsx").status_code == 404


def test_status_runs_values(client, runs):
    s = client.get("/api/daily-forecast/status").json()
    assert s["last_run"]["id"] == "FRR-NEW" and s["last_run"]["trial_mode"] is True
    assert s["made_on"] == "2026-10-29" and s["data_to"] == "2026-10-28" and s["outdated"] is False
    assert s["message"]["vi"] == "Số dự báo lập ngày 29/10/2026, dữ liệu đến ngày 28/10/2026"
    assert [r["id"] for r in client.get("/api/daily-forecast/runs").json()] == ["FRR-NEW", "FRR-OLD"]
    v = client.get("/api/daily-forecast/values").json()
    assert v["run"]["id"] == "FRR-NEW" and v["total"] == 4 and v["horizons"] == [1, 2] and v["page_size"] == 100
    assert v["rows"][0] == {"forecast_date": "2026-10-29", "target_date": "2026-10-29", "horizon": 1, "fc_code": "FC1",
                            "sku_code": "S_A", "product_name": None, "group_code": "A", "lgb_raw": 0.19,
                            "final_qty": 0, "method": "LIGHTGBM", "flags": None}
    assert client.get("/api/daily-forecast/values?group=C&horizon=2").json()["total"] == 1
    assert client.get("/api/daily-forecast/values?q=%25").json()["total"] == 2           # LIKE escaped: S%B only
    assert client.get("/api/daily-forecast/values?q=_").json()["total"] == 2             # S_A only
    assert client.get("/api/daily-forecast/values?forecast_date=2026-10-28").json()["run"]["id"] == "FRR-OLD"
    assert client.get("/api/daily-forecast/values?run_id=FRR-OTHER").json()["run"] is None   # other scope
    assert client.get("/api/daily-forecast/values?group=X").json()["code"] == "VALIDATION_ERROR"
    assert client.get("/api/daily-forecast/values?forecast_date=29-10").status_code == 422


def test_export(client, runs):
    r = client.get("/api/daily-forecast/export.xlsx?run_id=FRR-OLD")
    assert r.status_code == 200 and 'daily-forecast-2026-10-28-FRR-OLD.xlsx' in r.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Thông tin", "Dự báo"]
    info = [tuple(x) for x in wb["Thông tin"].iter_rows(values_only=True)]
    assert info[0] == ("Lưu ý", "Chạy thử – chưa dùng để mua hàng")
    assert ("Ngưỡng làm tròn (rounding_threshold)", 0.2) in info and ("Lập lúc (giờ VN)", "2026-10-28 09:00:00") in info
    rows = list(wb["Dự báo"].iter_rows(values_only=True))
    assert rows[0][:3] == ("Ngày lập dự báo", "Ngày", "Ngày thứ") and len(rows) == 5
    assert client.get("/api/daily-forecast/export.xlsx?run_id=FRR-OTHER").json()["code"] == "BATCH_NOT_FOUND"


def test_stale_rule(client, runs, monkeypatch):
    ss.update("daily_forecast", {"enabled": True})
    ss.update("schedule", {"refresh_enabled": True, "refresh_enabled_at": "2026-10-28T08:00:00+07:00"})
    ss.update("general", {"active_source": "BIGQUERY"})
    s = client.get("/api/daily-forecast/status").json()
    assert s["stale"] is False          # a PUBLISHED run of today exists (FRR-NEW)
    # a scope without a run of today (the run of SK2 never counts for it)
    monkeypatch.setattr(daily_routes, "resolve_scope", lambda c=None, source=None: {**SK, "scope_key": "SK3"})
    s = client.get("/api/daily-forecast/status").json()
    assert s["stale"] is True and s["stale_code"] == "STALE_FORECAST" and s["stale_since"].startswith("2026-10-29T05")
    assert s["trial_label"]["vi"] == "Chạy thử – chưa dùng để mua hàng"
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) "
                  "VALUES ('J1', 'FORECAST_REFRESH', 'k1', 'SCHEDULE', 'RUNNING', '2026-10-29T05:30:00+00:00')")
    assert client.get("/api/daily-forecast/status").json()["stale"] is False


def test_manual_jobs_and_csrf(client, scoped, monkeypatch):
    calls = []
    monkeypatch.setattr(background, "submit", lambda t, p=None, wait=None: calls.append((t, p)) or {"id": "J", "job_type": t})
    ss.update("daily_forecast", {"enabled": True})
    assert client.post("/api/daily-forecast/refresh").json()["job_type"] == "FORECAST_REFRESH"
    assert client.post("/api/accuracy-reports/run").json()["job_type"] == "ACCURACY_REPORT"
    assert calls == [("FORECAST_REFRESH", {"business_date": "2026-10-29"}),
                     ("ACCURACY_REPORT", {"business_date": "2026-10-29"})]
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as bare:
        assert bare.post("/api/daily-forecast/refresh").json()["code"] == "CSRF_BLOCKED"


def test_trial_mode_switch(client, scoped):
    r = client.post("/api/daily-forecast/trial-mode", json={"trial_mode": False, "confirm_text": "TAT-CHAY-THU"})
    assert r.status_code == 400 and r.json()["code"] == "TRIAL_MODE_CONFIRMATION_MISMATCH"
    r = client.post("/api/daily-forecast/trial-mode",
                    json={"trial_mode": False, "confirm_text": " TAT-CHAY-THU-2026-10-29 "}).json()
    assert r == {"changed": True, "trial_mode": False, "trial_label": None}
    assert ss.get("daily_forecast").trial_mode is False
    r = client.post("/api/daily-forecast/trial-mode",
                    json={"trial_mode": False, "confirm_text": "TAT-CHAY-THU-2026-10-29"}).json()
    assert r["changed"] is False
    ss.update("daily_forecast", {"enabled": True})
    r = client.post("/api/daily-forecast/trial-mode", json={"trial_mode": True}).json()
    assert r["changed"] is True and r["trial_label"]["en"] == "Trial run – not yet used for purchasing"
    with db.read() as c:
        notes = [x["note"] for x in db.rows(c, "SELECT note FROM settings_history WHERE section='daily_forecast' "
                                               "ORDER BY id")]
        alerts = db.rows(c, "SELECT level FROM alerts WHERE code='TRIAL_MODE_CHANGED' ORDER BY id")
        audit = db.rows(c, "SELECT details_json FROM audit_log WHERE action='TRIAL_MODE_CHANGED' ORDER BY id")
    assert "OWNER_CONFIRMED trial_mode=false" in notes and "OWNER_CONFIRMED trial_mode=true" in notes
    assert [a["level"] for a in alerts] == ["WARNING", "INFO"]
    assert json.loads(audit[0]["details_json"]) == {"from": True, "to": False}


def test_accuracy_reports(client, scoped, tmp_path):
    folder = paths.reports_dir() / "theo-doi"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "bao-cao-do-chinh-xac-1.xlsx").write_bytes(b"PK-test")
    outside = tmp_path / "outside.xlsx"
    outside.write_bytes(b"PK-out")
    with db.tx() as c:
        for rid, sk, p, at in (("AR-1", "SK1", str(folder / "bao-cao-do-chinh-xac-1.xlsx"), "2026-10-27T01:00:00+00:00"),
                               ("AR-2", "SK1", str(outside), "2026-10-28T01:00:00+00:00"),
                               ("AR-3", "SK2", str(folder / "bao-cao-do-chinh-xac-1.xlsx"), "2026-10-28T02:00:00+00:00")):
            c.execute("INSERT INTO accuracy_report_runs(id, scope_key, run_kind, run_date, status, report_path, "
                      "created_at) VALUES (?,?, 'MANUAL', '2026-10-28', 'WRITTEN', ?, ?)", (rid, sk, p, at))
    lst = client.get("/api/accuracy-reports").json()
    assert [r["id"] for r in lst] == ["AR-2", "AR-1"] and lst[1]["report_path_name"] == "bao-cao-do-chinh-xac-1.xlsx"
    assert "report_path" not in lst[0] and "error" in lst[0]
    assert client.get("/api/daily-forecast/status").json()["last_report"]["id"] == "AR-2"
    r = client.get("/api/accuracy-reports/AR-1/download")
    assert r.status_code == 200 and r.content == b"PK-test"
    assert client.get("/api/accuracy-reports/AR-2/download").status_code == 404      # outside the reports folder
    assert client.get("/api/accuracy-reports/AR-3/download").status_code == 404      # another scope


def test_feature_table(client, scoped):
    ss.update("model", {"forecast_strategy": "DIRECT", "feature_sku_code": False})
    g = client.get("/api/feature-table").json()
    names = [r["feature"] for r in g["rows"]]
    assert "horizon" in names and "sku_code" not in names and g["effective"] == "NEXT_TRAINING"
    assert all(r["is_default"] for r in g["rows"]) and g["history"] == [] and g["updated_at"] is None
    put = lambda body: client.put("/api/feature-table", json=body)
    assert put({"features": {"lag_1": {"enabled": False}}}).json()["code"] == "FEATURE_TABLE_CONFIRM_REQUIRED"
    assert put({"features": {"nope": {"enabled": False}}, "confirm": True}).json()["code"] == "FEATURE_UNKNOWN"
    assert put({"features": {"sku_code": {"enabled": False}}, "confirm": True}).json()["code"] == "FEATURE_NOT_IN_TABLE"
    r = put({"features": {"horizon": {"enabled": False}}, "confirm": True})
    assert r.status_code == 422 and r.json()["code"] == "FEATURE_REQUIRED"
    r = put({"features": {"lag_1": {"contri": 20}}, "confirm": True})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    body = {"features": {"lag_1": {"enabled": False}, "lag_7": {"enabled": True, "contri": 1.0},
                         "lag_2": {"contri": 2.5}}, "confirm": True, "note": "owner test"}
    r = put(body).json()
    assert r["saved"] is True
    assert ss.get("feature_table").model_dump() == {"features": {"lag_1": {"enabled": False, "contri": 1.0},
                                                                  "lag_2": {"enabled": True, "contri": 2.5}}}
    assert r["history"][0]["note"] == "OWNER_CONFIRMED owner test" and r["updated_at"]
    row = {x["feature"]: x for x in r["rows"]}
    assert row["lag_1"]["enabled"] is False and row["lag_2"]["contri"] == 2.5 and row["lag_7"]["is_default"] is True
    assert put(body).json()["saved"] is False                       # identical: nothing written again
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE action='FEATURE_TABLE_CHANGED'").fetchone()[0] == 1


def test_feature_importance(client, scoped):
    with db.tx() as c:
        c.execute("INSERT INTO training_runs(id, model_version, scope_key, data_source, status, started_at, "
                  "feature_importance_json) VALUES ('TR-L', 'MV-L', 'SK1', 'DEMO', 'ACCEPTED', '2026-10-01T00:00:00', ?)",
                  (json.dumps([{"feature": "lag_1", "gain": 30.0}, {"feature": "roll_mean_7", "gain": 10.0}]),))
        c.execute("INSERT INTO training_runs(id, model_version, scope_key, data_source, status, started_at) "
                  "VALUES ('TR-T', 'MV-T', 'SK1', 'DEMO', 'ACCEPTED', '2026-10-02T00:00:00')")
    feature_report.record("TR-T", feature_report.importance_rows(["lag_1", "dow", "price_last"], [5.0, 3.0, 2.0],
                                                                 [10, 6, 4]))
    leg = client.get("/api/training-runs/TR-L/feature-importance").json()
    assert leg["source"] == "LEGACY_GAIN" and leg["rows"][0]["split"] is None and leg["rows"][0]["gain_share"] == 0.75
    assert client.get("/api/training-runs/TR-L/feature-importance.xlsx").status_code == 404
    t = client.get("/api/training-runs/TR-T/feature-importance").json()
    assert t["source"] == "TABLE" and [r["rank"] for r in t["rows"]] == [1, 2, 3] and len(t["groups"]) >= 2
    r = client.get("/api/training-runs/TR-T/feature-importance.xlsx")
    assert r.status_code == 200 and "ty-trong-bien-TR-T.xlsx" in r.headers["content-disposition"]
    assert load_workbook(io.BytesIO(r.content)).sheetnames == ["Thông tin", "Theo biến", "Theo nhóm biến"]
    assert client.get("/api/training-runs/NOPE/feature-importance").status_code == 404
    assert not any(paths.uploads_dir().iterdir())                    # the temporary workbook is removed


def _counts():
    with db.read() as c:
        return (c.execute("SELECT COUNT(*) FROM settings_history").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
                [tuple(r) for r in c.execute("SELECT section, value_json FROM app_settings ORDER BY section")])


def test_cli_preset(small_demo, capsys):
    ss.update("model", {"forecast_strategy": "RECURSIVE"})
    before = _counts()
    assert cli.main(["apply-preset", "lgbm-chot", "--apply"]) == 2          # horizon weights need DIRECT: refused
    assert "HORIZON_WEIGHT_DIRECT_ONLY" in capsys.readouterr().out and _counts() == before
    ss.update("model", {"forecast_strategy": "DIRECT"})
    before = _counts()
    assert cli.main(["apply-preset", "lgbm-chot"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert _counts() == before                                             # the dry run wrote nothing
    assert {(x["section"], x["key"]) for x in dry["changes"]} == {
        ("model", "feature_sku_code"), ("model", "horizon_weight_short"), ("model", "horizon_weight_cutoff"),
        ("model", "fallback_enabled"), ("daily_forecast", "enabled")}
    fl = {f["flow"]: f for f in dry["flows"]}
    assert fl["report"]["ready"] is True and fl["refresh"]["ready"] is False
    assert fl["refresh"]["reasons"][0]["code"] == "NOT_APPLICABLE_FOR_SOURCE"
    d1 = ss.get("schedule").d1_enabled
    assert cli.main(["apply-preset", "lgbm-chot", "--apply"]) == 1           # refresh not ready on DEMO: reported
    out = json.loads(capsys.readouterr().out)
    assert out["changed"] is True and {f["flow"]: f["to"] for f in out["flows"]} == {"refresh": False, "report": True}
    m, dcfg, sch = ss.get("model"), ss.get("daily_forecast"), ss.get("schedule")
    assert (m.feature_sku_code, m.horizon_weight_short, m.horizon_weight_cutoff, m.fallback_enabled) == (False, 3.0, 7,
                                                                                                      False)
    assert dcfg.enabled is True and dcfg.trial_mode is True and dcfg.report_subdir == "theo-doi"
    assert sch.report_enabled is True and sch.report_enabled_at and sch.refresh_enabled is False
    assert sch.d1_enabled == d1
    with db.read() as c:
        notes = [r[0] for r in c.execute("SELECT note FROM settings_history WHERE section IN ('model', "
                                         "'daily_forecast') ORDER BY id DESC LIMIT 2")]
    assert notes == [cli.PRESET_NOTE, cli.PRESET_NOTE]
    before = _counts()
    assert cli.main(["apply-preset", "lgbm-chot", "--apply"]) == 1
    again = json.loads(capsys.readouterr().out)
    assert again["changed"] is False and again["changes"] == [] and "nothing to change" in again["message"]
    assert _counts() == before                                             # idempotent: nothing saved again
