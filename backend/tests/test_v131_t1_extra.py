"""1.3.1 T1 extra checks: B10 feature report (rows, groups, workbook, train_and_publish hook) and the explainer of a
model trained without sku_code. Isolated test data dir (conftest); no BigQuery, no network."""
import json

import pytest
from openpyxl import load_workbook

from app import db, paths
from app import settings_service as ss
from app.ml import feature_report, pipeline

from test_v1214_forecast_explainer import _get, _publish


def test_importance_rows_shares_ranks_and_groups():
    rows = feature_report.importance_rows(["fc_code", "lag_1", "lag_2", "dom"], [1.0, 6.0, 3.0, 0.0], [2, 5, 3, 0])
    assert [r["feature"] for r in rows] == ["lag_1", "lag_2", "fc_code", "dom"]
    assert [r["rank"] for r in rows] == [1, 2, 3, 4]
    by = {r["feature"]: r for r in rows}
    assert by["lag_1"]["gain_share"] == pytest.approx(0.6) and by["lag_1"]["split_share"] == pytest.approx(0.5)
    assert by["lag_1"]["feature_group"] == "LAG" and by["dom"]["feature_group"] == "CALENDAR"
    assert feature_report.feature_group("no_such_feature") == "OTHER"
    g = {d["feature_group"]: d for d in feature_report.group_rows(rows)}
    assert g["LAG"]["n_features"] == 2 and g["LAG"]["gain"] == 9.0 and g["LAG"]["split"] == 8
    assert g["LAG"]["gain_share"] == pytest.approx(0.9)
    zero = feature_report.importance_rows(["a_x", "b_y"], [0.0, 0.0], [0, 0])
    assert all(r["gain_share"] == 0.0 and r["split_share"] == 0.0 for r in zero)


def test_workbook_sheets_trial_label_and_never_overwritten(tmp_path):
    rows = feature_report.importance_rows(["lag_1", "dom"], [2.0, 1.0], [3, 1])
    p1 = feature_report.free_path(tmp_path, "TRN-1")
    feature_report.write_workbook(p1, "TRN-1", rows, {"trial_mode": True, "model_version": "MV-1"})
    p2 = feature_report.free_path(tmp_path, "TRN-1")
    assert p1.name == "ty-trong-bien-TRN-1.xlsx" and p2.name == "ty-trong-bien-TRN-1-2.xlsx"
    wb = load_workbook(p1)
    assert wb.sheetnames == ["Thông tin", "Theo biến", "Theo nhóm biến"]
    assert wb["Thông tin"]["A1"].value == feature_report.TRIAL_LABEL
    assert [c.value for c in wb["Theo biến"][2]][:2] == [1, "lag_1"]
    feature_report.write_workbook(p2, "TRN-1", rows, {"trial_mode": False})
    assert load_workbook(p2)["Thông tin"]["A1"].value != feature_report.TRIAL_LABEL


def _report_state(run_id):
    with db.read() as c:
        n = c.execute("SELECT COUNT(*) FROM training_feature_importance WHERE training_run_id=?", (run_id,)).fetchone()[0]
        alerts = c.execute("SELECT COUNT(*) FROM alerts WHERE code='FEATURE_REPORT_NOT_WRITTEN'").fetchone()[0]
    folder = paths.reports_dir() / "theo-doi"
    return n, alerts, sorted(p.name for p in folder.glob("ty-trong-bien-*.xlsx")) if folder.exists() else []


def test_training_writes_nothing_new_while_daily_forecast_is_off(small_demo):
    res = pipeline.train_and_publish()
    assert res["status"] == "PUBLISHED", res
    assert _report_state(res["training_run_id"]) == (0, 0, [])
    with db.read() as c:
        fcj = json.loads(db.one(c, "SELECT feature_config_json FROM training_runs WHERE id=?",
                                (res["training_run_id"],))["feature_config_json"])
    assert fcj["config_fingerprint"] == pipeline.config_fingerprint(fcj["config"])
    assert fcj["config"]["feature_table"] is None
    assert fcj["settings_switches"]["feature_sku_code"] is True and fcj["settings_switches"]["fallback_enabled"] is True


def test_training_records_and_writes_the_feature_report_when_enabled(small_demo):
    ss.update("daily_forecast", {"enabled": True})
    res = pipeline.train_and_publish()
    assert res["status"] == "PUBLISHED", res
    with db.read() as c:
        tr = db.one(c, "SELECT feature_config_json FROM training_runs WHERE id=?", (res["training_run_id"],))
    names = json.loads(tr["feature_config_json"])["features"]
    n, alerts, files = _report_state(res["training_run_id"])
    assert n == len(names) and alerts == 0
    assert files == [f"ty-trong-bien-{res['training_run_id']}.xlsx"]


def test_a_report_error_never_changes_the_training(small_demo, monkeypatch):
    ss.update("daily_forecast", {"enabled": True})

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(feature_report, "write_workbook", boom)
    res = pipeline.train_and_publish()
    assert res["status"] == "PUBLISHED", res
    n, alerts, files = _report_state(res["training_run_id"])
    assert alerts == 1 and files == []


def test_explainer_of_a_model_without_sku_code(client, fast_model):
    ss.update("model", {"feature_sku_code": False})
    pub = _publish(client)
    names = json.loads(pub["tr"]["feature_config_json"])["features"]
    assert "sku_code" not in names and "fc_code" in names
    r = _get(client)
    assert r["status"] == "OK" and r["verified"] is True, json.dumps(r.get("checks"), indent=1)
    assert [f["name"] for f in r["features"]] == names
    assert all(ch["ok"] for ch in r["checks"]), r["checks"]
