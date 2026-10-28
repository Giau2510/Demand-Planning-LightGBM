"""1.3.1 tester checks (C3-T134): API of the daily forecast refresh (status around the Vietnam day and the deadline,
runs, values paging, export), the confirmed trial-mode switch, the guards of the generic settings PUT, the feature table
PUT and the accuracy report download guard; CLI apply-preset with the readiness of the flows decided by the test.
Integration with fakes (TestClient on the isolated temporary database, fixture rows inserted directly, data scope
stubbed); no BigQuery, no real data."""
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app import cli, db, paths, timeutil
from app import settings_service as ss
from app.api import daily_routes
from app.jobs import flows

SK = {"scope_key": "SK1", "data_source": "DEMO", "label": "test scope"}
LABEL = "Chạy thử – chưa dùng để mua hàng"


def _at(y, m, d, hh, mm):
    t = datetime(y, m, d, hh, mm, tzinfo=timezone.utc)
    timeutil.set_now_override(lambda: t)


@pytest.fixture
def scoped(monkeypatch):
    monkeypatch.setattr(daily_routes, "resolve_scope", lambda c=None, source=None: dict(SK))
    _at(2026, 10, 29, 6, 0)                               # 13:00 Vietnam


def _frr(c, rid, fd, created, values=(), trial=1, scope="SK1", data_as_of=None, threshold=0.2):
    c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, trigger, "
              "training_run_id, model_version, model_fingerprint, config_version, trial_mode, horizon, n_series, "
              "n_lightgbm, n_fallback, created_at, detail_json) VALUES (?,?,?,?, 'PUBLISHED', 'MANUAL', 'TR-1', 'MV-1', "
              "'fp1', 'cv1', ?, 7, 3, 3, 0, ?, ?)",
              (rid, scope, fd, data_as_of or fd, trial, created, json.dumps({"rounding_threshold": threshold})))
    c.executemany("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, lgb_raw, "
                  "final_qty, method, group_code, flags) VALUES (?,?,?,?,?,?,?, 'LIGHTGBM', ?, NULL)",
                  [(rid, *v) for v in values])


def _count(sql, p=()):
    with db.read() as c:
        return c.execute(sql, p).fetchone()[0]


# ================================================================== status
def test_status_vietnam_day_deadline_jobs_and_outdated(client, scoped):
    _at(2026, 10, 28, 17, 30)                             # 00:30 of 29/10 in Vietnam, still 28/10 in UTC
    s = client.get("/api/daily-forecast/status").json()
    assert s["today"] == "2026-10-29" and s["trial_confirm_text"] == "TAT-CHAY-THU-2026-10-29"
    ss.update("daily_forecast", {"enabled": True})
    ss.update("schedule", {"refresh_enabled": True, "refresh_enabled_at": "2026-10-28T08:00:00+07:00"})
    ss.update("general", {"active_source": "BIGQUERY"})
    st = lambda: client.get("/api/daily-forecast/status").json()      # noqa: E731
    _at(2026, 10, 29, 4, 59)                              # 11:59 Vietnam: before the 12:00 deadline
    assert st()["stale"] is False and st()["outdated"] is False and st()["last_run"] is None
    _at(2026, 10, 29, 5, 1)
    s = st()
    assert s["stale"] is True and s["stale_code"] == "STALE_FORECAST" and s["stale_since"] == "2026-10-29T05:00:00+00:00"
    assert s["trial_label"] == {"vi": LABEL, "en": "Trial run – not yet used for purchasing"}
    with db.tx() as c:                                    # a PENDING attempt of YESTERDAY (23:59 Vietnam) never counts
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) VALUES "
                  "('J0', 'FORECAST_REFRESH', 'k0', 'SCHEDULE', 'PENDING', '2026-10-28T16:59:00+00:00')")
    assert st()["stale"] is True
    with db.tx() as c:                                    # created at 00:00 Vietnam today: the verdict waits
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) VALUES "
                  "('J1', 'FORECAST_REFRESH', 'k1', 'SCHEDULE', 'PENDING', '2026-10-28T17:00:00+00:00')")
    assert st()["stale"] is False
    with db.tx() as c:
        c.execute("UPDATE job_runs SET status='SKIPPED' WHERE id='J1'")
    assert st()["stale"] is True                          # finished without a published run
    ss.update("schedule", {"refresh_enabled_at": "2026-10-29T12:00:30+07:00"})     # switched on after the deadline
    assert st()["stale"] is False
    ss.update("schedule", {"refresh_enabled_at": "2026-10-29T12:00:00+07:00"})     # exactly at the deadline
    assert st()["stale"] is True
    ss.update("general", {"active_source": "MANUAL_IMPORT"})
    assert st()["stale"] is False
    ss.update("general", {"active_source": "BIGQUERY"})
    # a run of yesterday, made at 23:30 Vietnam: made_on is the Vietnam day, outdated, still stale
    with db.tx() as c:
        _frr(c, "R-Y", "2026-10-28", "2026-10-28T16:30:00+00:00", data_as_of="2026-10-27")
    s = st()
    assert s["last_run"]["id"] == "R-Y" and s["made_on"] == "2026-10-28" and s["data_to"] == "2026-10-27"
    assert s["outdated"] is True and s["stale"] is True
    assert s["message"] == {"vi": "Số dự báo lập ngày 28/10/2026, dữ liệu đến ngày 27/10/2026",
                            "en": "Forecast made on 28/10/2026, data up to 27/10/2026"}
    # a run of today made at 00:10 Vietnam (still 28/10 in UTC)
    with db.tx() as c:
        _frr(c, "R-T", "2026-10-29", "2026-10-28T17:10:00+00:00", data_as_of="2026-10-28")
    s = st()
    assert s["last_run"]["id"] == "R-T" and s["made_on"] == "2026-10-29" and s["outdated"] is False
    assert s["stale"] is False and s["stale_since"] is None
    ss.update("daily_forecast", {"trial_mode": False})
    s = st()
    assert s["trial_mode"] is False and s["trial_label"] is None and s["enabled"] is True


# ================================================================== runs, values, export
def test_runs_limit_and_newest_first_ties(client, scoped):
    with db.tx() as c:
        _frr(c, "R-A", "2026-10-28", "2026-10-28T02:00:00+00:00")
        _frr(c, "R-B", "2026-10-29", "2026-10-29T02:00:00+00:00")
        _frr(c, "R-C", "2026-10-29", "2026-10-29T02:00:00+00:00")        # same second: inserted last wins
    assert [r["id"] for r in client.get("/api/daily-forecast/runs").json()] == ["R-C", "R-B", "R-A"]
    assert [r["id"] for r in client.get("/api/daily-forecast/runs?limit=1").json()] == ["R-C"]
    for bad in (0, 201):
        assert client.get(f"/api/daily-forecast/runs?limit={bad}").status_code == 422
    assert client.get("/api/daily-forecast/values").json()["run"]["id"] == "R-C"
    assert client.get("/api/daily-forecast/values?forecast_date=2026-10-29").json()["run"]["id"] == "R-C"
    assert client.get("/api/daily-forecast/status").json()["last_run"]["id"] == "R-C"


def test_values_paging_filters_and_validation(client, scoped):
    vals = [(1, "2026-10-29", "F1", f"S{i:03d}", 0.5, 1, "A" if i % 2 else "B") for i in range(120)]
    vals += [(2, "2026-10-30", "F1", f"S{i:03d}", 2.5, 3, "C") for i in range(30)]
    with db.tx() as c:
        _frr(c, "R-P", "2026-10-29", "2026-10-29T02:00:00+00:00", vals)
    get = lambda q="": client.get("/api/daily-forecast/values" + q).json()     # noqa: E731
    p0, p1, p2 = get("?page=0"), get("?page=1"), get("?page=2")
    assert (p0["total"], len(p0["rows"]), len(p1["rows"]), len(p2["rows"])) == (150, 100, 50, 0)
    keys = [(r["fc_code"], r["sku_code"], r["horizon"]) for r in p0["rows"] + p1["rows"]]
    assert keys == sorted(keys) and len(set(keys)) == 150 and p0["horizons"] == [1, 2]
    assert get("?horizon=2")["total"] == 30 and get("?group=C")["total"] == 30 and get("?group=A")["total"] == 60
    assert get("?q=S01")["total"] == 20                    # S010..S019, both horizons
    assert get("?q=S01&horizon=1&group=B")["total"] == 5
    for bad in ("?group=a", "?group=D", "?horizon=0", "?page=-1", "?forecast_date=2026-13-01"):
        r = client.get("/api/daily-forecast/values" + bad)
        assert r.status_code == 422, bad


INFO_KEYS = ["Mã lần làm mới", "Ngày lập dự báo", "Lập lúc (giờ VN)", "Dữ liệu đến ngày", "Mô hình (model id)",
             "Mã lần huấn luyện", "Fingerprint cấu hình model", "Phiên bản cấu hình (config_version)",
             "Ngưỡng làm tròn (rounding_threshold)", "Quy tắc số công bố", "Số chuỗi", "Số chuỗi LightGBM",
             "Số chuỗi dự phòng", "Số ngày dự báo"]
HEADERS = ("Ngày lập dự báo", "Ngày", "Ngày thứ", "FC/kho", "SKU", "Tên sản phẩm", "Nhóm", "LightGBM gốc",
           "Số công bố", "Phương pháp", "Cờ")


def _export(client, q):
    r = client.get("/api/daily-forecast/export.xlsx" + q)
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(r.content))
    return r, wb


def test_export_every_row_across_chunks_and_the_trial_label_rule(client, scoped, monkeypatch):
    monkeypatch.setattr(daily_routes, "EXPORT_CHUNK", 7)
    vals = [(h, f"2026-10-{28 + h:02d}", "F1", f"S{i:02d}", 0.123456 * i, i, "A") for i in range(1, 13)
            for h in (1, 2)]
    with db.tx() as c:
        _frr(c, "R-0", "2026-10-29", "2026-10-28T17:10:00+00:00", vals, trial=0, threshold=0.35)
        _frr(c, "R-1", "2026-10-28", "2026-10-28T02:00:00+00:00", vals[:2], trial=1)
    r, wb = _export(client, "?forecast_date=2026-10-29")
    assert 'filename="daily-forecast-2026-10-29-R-0.xlsx"' in r.headers["content-disposition"]
    assert wb.sheetnames == ["Thông tin", "Dự báo"]
    info = [tuple(x) for x in wb["Thông tin"].iter_rows(values_only=True)]
    assert info[0] == ("Lưu ý", LABEL)                    # run not in trial, the current setting is
    assert [k for k, _v in info[1:]] == INFO_KEYS
    d = dict(info[1:])
    assert d["Lập lúc (giờ VN)"] == "2026-10-29 00:10:00" and d["Ngưỡng làm tròn (rounding_threshold)"] == 0.35
    assert (d["Số chuỗi"], d["Số ngày dự báo"], d["Mô hình (model id)"]) == (3, 7, "MV-1")
    rows = list(wb["Dự báo"].iter_rows(values_only=True))
    assert rows[0] == HEADERS and len(rows) == 1 + len(vals)
    want = sorted(vals, key=lambda v: (v[2], v[3], v[0]))
    assert [(x[1], x[2], x[3], x[4], x[6], x[8]) for x in rows[1:]] == [(v[1], v[0], v[2], v[3], v[6], v[5])
                                                                           for v in want]
    assert all(x[0] == "2026-10-29" and x[5] is None and x[9] == "LIGHTGBM" for x in rows[1:])
    assert rows[2][7] == pytest.approx(0.123456)
    ok = client.post("/api/daily-forecast/trial-mode", json={"trial_mode": False, "confirm_text": "TAT-CHAY-THU-2026-10-29"})
    assert ok.json()["changed"] is True
    _r, wb = _export(client, "?run_id=R-0")               # neither the run nor the setting: no label row
    assert wb["Thông tin"]["A1"].value == "Mã lần làm mới"
    _r, wb = _export(client, "?run_id=R-1")               # the run was made in trial mode: label kept
    assert wb["Thông tin"]["A1"].value == "Lưu ý"
    assert client.get("/api/daily-forecast/export.xlsx?forecast_date=2026-10-27").json()["code"] == "BATCH_NOT_FOUND"


# ================================================================== manual jobs
def test_refresh_and_report_buttons_create_real_jobs_only_when_enabled(client, scoped):
    for url in ("/api/daily-forecast/refresh", "/api/accuracy-reports/run"):
        r = client.post(url)
        assert r.status_code == 409 and r.json()["code"] == "DAILY_FORECAST_DISABLED"
    assert _count("SELECT COUNT(*) FROM job_runs") == 0
    ss.update("daily_forecast", {"enabled": True})
    for url, jt in (("/api/daily-forecast/refresh", "FORECAST_REFRESH"), ("/api/accuracy-reports/run", "ACCURACY_REPORT")):
        j = client.post(url).json()
        assert j["job_type"] == jt and j["trigger"] == "MANUAL" and j["status"] not in ("PENDING", "RUNNING"), j
        assert json.loads(j["result_json"])["params"] == {"business_date": "2026-10-29"}
    assert _count("SELECT COUNT(*) FROM job_runs") == 2


# ================================================================== trial mode and the generic settings PUT
def _history(section):
    return _count("SELECT COUNT(*) FROM settings_history WHERE section=?", (section,))


def test_trial_mode_refusals_save_nothing_and_the_vietnam_date_is_required(client, scoped):
    _at(2026, 10, 28, 17, 30)                             # 29/10 00:30 Vietnam
    h0 = _history("daily_forecast")
    for body in ({"trial_mode": False}, {"trial_mode": False, "confirm_text": None},
                 {"trial_mode": False, "confirm_text": "TAT-CHAY-THU-2026-10-28"},       # the UTC date
                 {"trial_mode": False, "confirm_text": "tat-chay-thu-2026-10-29"}):
        r = client.post("/api/daily-forecast/trial-mode", json=body)
        assert r.status_code == 400 and r.json()["code"] == "TRIAL_MODE_CONFIRMATION_MISMATCH", body
    assert client.post("/api/daily-forecast/trial-mode", json={"trial_mode": True}).json()["changed"] is False
    assert ss.get("daily_forecast").trial_mode is True and _history("daily_forecast") == h0
    assert _count("SELECT COUNT(*) FROM audit_log WHERE action='TRIAL_MODE_CHANGED'") == 0
    assert _count("SELECT COUNT(*) FROM alerts WHERE code='TRIAL_MODE_CHANGED'") == 0
    r = client.post("/api/daily-forecast/trial-mode", json={"trial_mode": False, "confirm_text": "TAT-CHAY-THU-2026-10-29"})
    assert r.json() == {"changed": True, "trial_mode": False, "trial_label": None}
    assert _history("daily_forecast") == h0 + 1 and ss.get("daily_forecast").trial_mode is False


def test_generic_settings_put_guards(client, scoped):
    cur = ss.get("daily_forecast").model_dump()
    h0 = _history("daily_forecast")
    r = client.put("/api/settings/daily_forecast", json={**cur, "trial_mode": False})
    assert r.status_code == 409 and r.json()["code"] == "TRIAL_MODE_CONFIRM_REQUIRED"
    assert _history("daily_forecast") == h0 and ss.get("daily_forecast").trial_mode is True
    r = client.put("/api/settings/daily_forecast", json={**cur, "enabled": True, "rounding_threshold": 0.3})
    assert r.status_code == 200 and ss.get("daily_forecast").enabled is True
    client.post("/api/daily-forecast/trial-mode", json={"trial_mode": False, "confirm_text": "TAT-CHAY-THU-2026-10-29"})
    no_key = {k: v for k, v in ss.get("daily_forecast").model_dump().items() if k != "trial_mode"}
    assert client.put("/api/settings/daily_forecast", json=no_key).status_code == 200
    assert ss.get("daily_forecast").trial_mode is False              # a body without the key keeps it
    assert client.post("/api/settings/daily_forecast/reset").status_code == 200
    d = ss.get("daily_forecast")
    assert d.trial_mode is False and d.enabled is False and d.rounding_threshold == 0.2     # reset keeps the trial mode
    for method, url in (("put", "/api/settings/feature_table"), ("post", "/api/settings/feature_table/reset")):
        r = getattr(client, method)(url, json={"features": {"lag_1": {"enabled": False}}})
        assert r.status_code == 409 and r.json()["code"] == "FEATURE_TABLE_VIA_OWN_API", url
    assert ss.get("feature_table").features == {}
    m = ss.get("model").model_dump()
    r = client.put("/api/settings/model", json={**m, "feature_table": {"lag_1": {"enabled": False, "contri": 1.0}}})
    assert r.status_code == 409 and r.json()["code"] == "FEATURE_TABLE_SET_BY_TRAINING"
    assert ss.get("model").feature_table is None
    assert client.put("/api/settings/model", json={**m, "feature_table": None}).status_code == 200


# ================================================================== feature table
def test_feature_table_put_takes_the_whole_table(client, scoped):
    ss.update("model", {"forecast_strategy": "DIRECT", "feature_sku_code": False})
    put = lambda f, **kw: client.put("/api/feature-table", json={"features": f, "confirm": True, **kw})   # noqa: E731
    assert put({"lag_1": {"enabled": False}, "dom": {"contri": 10}}).json()["saved"] is True
    for bad, code in (({"Lag-1": {"enabled": False}}, "FEATURE_UNKNOWN"), ({"dom": {"contri": 0}}, "VALIDATION_ERROR"),
                      ({"sku_code": {"enabled": True, "contri": 1.0}}, "FEATURE_NOT_IN_TABLE")):
        r = put(bad)
        assert r.status_code == 422 and r.json()["code"] == code, bad
    assert set(ss.get("feature_table").features) == {"lag_1", "dom"}       # a refused PUT changes nothing
    r = put({}).json()                                    # a missing name = the default row: the table is emptied
    assert r["saved"] is True and ss.get("feature_table").features == {}
    assert all(x["is_default"] for x in r["rows"])
    assert json.loads(r["history"][0]["value_json"]) == {"features": {}}
    assert len(r["history"]) == 2 and r["history"][1]["note"] == "OWNER_CONFIRMED"
    assert _count("SELECT COUNT(*) FROM audit_log WHERE action='FEATURE_TABLE_CHANGED'") == 2
    # a stored rule for a feature the scope does not use (no price data) is still listed, after the model features
    ss.save("feature_table", {"features": {"price_last": {"enabled": False, "contri": 1.0}}})
    names = [x["feature"] for x in client.get("/api/feature-table").json()["rows"]]
    assert names[-1] == "price_last" and names.count("price_last") == 1 and "sku_code" not in names
    ss.update("model", {"feature_sku_code": True})
    assert "sku_code" in [x["feature"] for x in client.get("/api/feature-table").json()["rows"]]


def test_accuracy_report_download_refuses_every_file_outside_the_report_folder(client, scoped):
    folder = paths.reports_dir() / "theo-doi"
    (folder / "sub").mkdir(parents=True, exist_ok=True)
    (folder / "ok.xlsx").write_bytes(b"PK-ok")
    (folder / "sub" / "nested.xlsx").write_bytes(b"PK-nested")
    (folder / "note.txt").write_bytes(b"text")
    (paths.reports_dir().parent / "x.xlsx").write_bytes(b"PK-outside")
    rows = {"AR-OK": str(folder / "ok.xlsx"), "AR-NEST": str(folder / "sub" / "nested.xlsx"),
            "AR-UP": str(folder / ".." / ".." / "x.xlsx"), "AR-TXT": str(folder / "note.txt"),
            "AR-GONE": str(folder / "gone.xlsx"), "AR-NULL": None, "AR-BASE": str(paths.reports_dir() / "x.xlsx")}
    (paths.reports_dir() / "x.xlsx").write_bytes(b"PK-base")
    with db.tx() as c:
        for rid, p in rows.items():
            c.execute("INSERT INTO accuracy_report_runs(id, scope_key, run_kind, run_date, status, report_path, "
                      "created_at) VALUES (?, 'SK1', 'MANUAL', '2026-10-28', 'DONE', ?, '2026-10-28T01:00:00+00:00')",
                      (rid, p))
    assert client.get("/api/accuracy-reports/AR-OK/download").content == b"PK-ok"
    assert client.get("/api/accuracy-reports/AR-NEST/download").content == b"PK-nested"
    for rid in ("AR-UP", "AR-TXT", "AR-GONE", "AR-NULL", "AR-BASE", "NOPE"):
        r = client.get(f"/api/accuracy-reports/{rid}/download")
        assert r.status_code == 404 and r.json()["code"] == "BATCH_NOT_FOUND", rid


# ================================================================== CLI apply-preset
def _state():
    with db.read() as c:
        return (c.execute("SELECT COUNT(*) FROM settings_history").fetchone()[0],
                [tuple(r) for r in c.execute("SELECT section, value_json FROM app_settings ORDER BY section")])


OTHER_FLOW_KEYS = ("d1_enabled", "d0_enabled", "train_enabled", "eod_enabled", "close_enabled", "d1_enabled_at",
                   "d0_enabled_at", "train_enabled_at", "eod_enabled_at", "close_enabled_at")


@pytest.mark.parametrize("ready", [True, False])
def test_cli_preset_with_the_readiness_decided_and_nothing_else_touched(monkeypatch, capsys, ready):
    paths.ensure_storage()
    reasons = [] if ready else [{"code": "TEST_NOT_READY", "detail": "decided by the test"}]
    monkeypatch.setattr(flows, "readiness", lambda flow, conn=None: {"flow": flow, "ready": ready,
                                                                      "reasons": list(reasons), "notes": []})
    ss.update("model", {"forecast_strategy": "DIRECT"})
    ss.update("schedule", {"d1_fallback_time": "06:10", "train_time": "05:20", "d0_times": ["08:00", "10:00"]})
    sched0 = ss.get("schedule").model_dump()
    gen0 = ss.get("general").model_dump()
    storage = Path(os.environ["DF_STORAGE_CONFIG"])        # the per-test bootstrap file (conftest)
    s_bytes = lambda: storage.read_bytes() if storage.exists() else None          # noqa: E731
    sb0 = s_bytes()
    st0 = _state()
    assert cli.main(["apply-preset", "lgbm-chot"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert _state() == st0 and dry["dry_run"] is True
    assert {(x["section"], x["key"], x["from"], x["to"]) for x in dry["changes"]} == {
        ("model", "feature_sku_code", True, False), ("model", "horizon_weight_short", None, 3.0),
        ("model", "horizon_weight_cutoff", None, 7), ("model", "fallback_enabled", True, False),
        ("daily_forecast", "enabled", False, True)}
    assert {f["flow"]: (f["ready"], f["to"]) for f in dry["flows"]} == {"refresh": (ready, ready),
                                                                        "report": (ready, ready)}
    assert cli.main(["apply-preset", "lgbm-chot", "--apply"]) == (0 if ready else 1)
    out = json.loads(capsys.readouterr().out)
    assert out["changed"] is True and {f["flow"]: f["to"] for f in out["flows"]} == {"refresh": ready, "report": ready}
    if not ready:
        assert all(f["reasons"][0]["code"] == "TEST_NOT_READY" for f in out["flows"])
    m, d, s = ss.get("model"), ss.get("daily_forecast"), ss.get("schedule")
    assert (m.feature_sku_code, m.horizon_weight_short, m.horizon_weight_cutoff, m.fallback_enabled) == (False, 3.0, 7,
                                                                                                      False)
    assert d.enabled is True and d.trial_mode is True and d.rounding_threshold == 0.2 and d.log_retention_days == 120
    assert (s.refresh_enabled, s.report_enabled) == (ready, ready)
    assert bool(s.refresh_enabled_at) is ready and bool(s.report_enabled_at) is ready
    sd = s.model_dump()
    assert {k: sd[k] for k in OTHER_FLOW_KEYS} == {k: sched0[k] for k in OTHER_FLOW_KEYS}
    assert (sd["d1_fallback_time"], sd["train_time"], sd["d0_times"]) == ("06:10", "05:20", ["08:00", "10:00"])
    assert {k: v for k, v in sd.items() if not k.startswith(("refresh_enabled", "report_enabled"))} == \
        {k: v for k, v in sched0.items() if not k.startswith(("refresh_enabled", "report_enabled"))}
    assert ss.get("general").model_dump() == gen0 and s_bytes() == sb0
    st1 = _state()
    assert cli.main(["apply-preset", "lgbm-chot", "--apply"]) == (0 if ready else 1)
    again = json.loads(capsys.readouterr().out)
    assert again["changes"] == [] and _state() == st1
    assert again["changed"] is False and "nothing to change" in again["message"]


def test_cli_preset_leaves_a_stored_trial_mode_off(monkeypatch, capsys):
    monkeypatch.setattr(flows, "readiness", lambda flow, conn=None: {"flow": flow, "ready": True, "reasons": [],
                                                                      "notes": []})
    ss.update("model", {"forecast_strategy": "DIRECT"})
    ss.update("daily_forecast", {"trial_mode": False})
    assert cli.main(["apply-preset", "lgbm-chot", "--apply"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert "trial_mode" not in {x["key"] for x in out["changes"]}
    assert ss.get("daily_forecast").trial_mode is False and ss.get("daily_forecast").enabled is True
