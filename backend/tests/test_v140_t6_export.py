"""1.4.0 T6: daily Excel of the purchasing team (ml/sel2/export.py): sheets and columns, rows = union of SKU x FC x 7
days, forecast_used / fallback_reason, stale mode, versions + latest copy + relative path + sha256, TOM_TAT / CONFIG,
the /api/sel2/export routes and the sel2-export CLI. Integration with fakes (isolated temporary database, rows inserted
directly, TestClient)."""
import hashlib
import io
import json
from datetime import date, datetime, timedelta

import pytest
from openpyxl import load_workbook

from app import cli, db, paths
from app import settings_service as ss
from app.messages import AppError
from app.ml.sel2 import export

D = date(2026, 11, 2)
SCOPE = "SC-T6"
COLS = ["sku_code", "ten_san_pham", "seller_code", "product_code", "fc_code", "nhom", "forecast_date", "target_date",
        "horizon", "lightgbm_forecast", "avg_demand", "forecast_source", "forecast_used", "fallback_reason", "model_used", "raw_value", "model_version",
        "data_cutoff_date", "is_stale", "flags"]


def _run(run_id, fdate: date, series: dict, scope=SCOPE, created="2026-11-01T23:00:00+00:00", flags=None):
    """series {(sku, fc): (group, method, {horizon: (qty, raw)})}: one SEL2 run published for fdate."""
    with db.tx() as c:
        c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, trigger, "
                  "model_version, config_version, trial_mode, horizon, n_series, n_lightgbm, n_fallback, created_at, "
                  "detail_json) VALUES (?,?,?,?, 'PUBLISHED', 'test', ?, 'SEL2:abcdef012345', 1, 7, ?, ?, 0, ?, '{}')",
                  (run_id, scope, fdate.isoformat(), (fdate - timedelta(days=1)).isoformat(), f"MV-{run_id}",
                   len(series), len(series), created))
        for (sku, fc), (grp, method, hs) in series.items():
            for h, (qty, raw) in hs.items():
                c.execute("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, lgb_raw, "
                          "final_qty, method, group_code, flags) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (run_id, h, (fdate + timedelta(days=h - 1)).isoformat(), fc, sku, raw, qty, method, grp,
                           flags))


def _avg(day: date, rows):
    """rows [(sku, fc, seller, value, name)] stored as the CURRENT read of day."""
    table = ss.get("sel2_pipeline").avg_demand_table
    with db.tx() as c:
        c.executemany("INSERT INTO avg_demand_daily(business_date, sku_code, fc_code, seller_code, avg_demand, "
                      "product_name, source_table, source_modified, loaded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      [(day.isoformat(), s, f, sel, v, n, table, "2026-11-02T03:15:00+00:00",
                        "2026-11-02T03:20:00+00:00") for s, f, sel, v, n in rows])
        c.execute("INSERT INTO avg_demand_reads(id, source_table, business_date, kind, n_rows, source_modified, "
                  "completed_at) VALUES (?,?,?, 'CURRENT', ?, ?, ?)",
                  (db.new_id("ADR"), table, day.isoformat(), len(rows), "2026-11-02T03:15:00+00:00",
                   "2026-11-02T03:20:00+00:00"))


def _config(rows):
    """rows [(sku, fc, source, note)]."""
    with db.tx() as c:
        c.executemany("INSERT INTO forecast_source_config(sku_code, fc_code, forecast_source, ghi_chu, updated_by, "
                      "updated_at) VALUES (?,?,?,?, 'tester', '2026-11-01T01:00:00+00:00')", rows)


def _book(res, normal=True):
    return load_workbook(paths.data_dir() / res["path"], read_only=not normal)


def _main_rows(wb) -> list[dict]:
    rows = list(wb["DU_BAO"].iter_rows(values_only=True))
    assert list(rows[0]) == COLS
    return [dict(zip(COLS, r)) for r in rows[1:]]


def _summary(wb) -> dict:
    rows = list(wb["TOM_TAT"].iter_rows(values_only=True))
    assert list(rows[0]) == ["muc", "gia_tri"]
    return {r[0]: r[1] for r in rows[1:]}


def _by(rows):
    return {(r["sku_code"], r["fc_code"], r["horizon"]): r for r in rows}


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)


@pytest.fixture
def scenario(sel2_on):
    """Run of D: S1 (LIGHTGBM, 7 days), S2 (AVG_DEMAND default, 7 days), S3 (LIGHTGBM, horizons 1-5 only).
    AVG of D: S1 2.5, S2 4, S4 3 (LIGHTGBM, not in the run), S5 two sellers (rule PENDING -> no value).
    Config: S1, S3, S4, S9 LIGHTGBM (S9 nowhere). An older run of D-1 exists and is not used."""
    full = {h: (h, h - 0.4) for h in range(1, 8)}
    _run("R0", D - timedelta(days=1), {("S1", "F1"): ("A", "OLD", {h: (99, 99.0) for h in range(1, 8)})})
    _run("R1", D, {("S1", "F1"): ("A", "MOC+DOW4", full),
                   ("S2", "F1"): ("B", "FALLBACK:V33_L112", full),
                   ("S3", "F1"): ("C", "V36_two_stage@0.6+TSB", {h: (0, 0.1) for h in range(1, 6)})},
         created="2026-11-01T23:30:00+00:00", flags="OPEN_HOURS_LAG")
    _avg(D, [("S1", "F1", "SL1", 2.5, "Thuoc A"), ("S2", "F1", "SL1", 4.0, "Thuoc B"),
             ("S4", "F1", "SL1", 3.0, "Thuoc D"), ("S5", "F1", "SL1", 1.0, "Thuoc E"),
             ("S5", "F1", "SL2", 2.0, "Thuoc E")])
    _config([("S1", "F1", "LIGHTGBM", "chuyen LGBM"), ("S3", "F1", "LIGHTGBM", None), ("S4", "F1", "LIGHTGBM", None),
             ("S9", "F1", "LIGHTGBM", None)])


def test_sheets_columns_rows_and_truth_table(scenario):
    res = export.write_daily_export(D, scope_key=SCOPE)
    wb = _book(res)
    assert wb.sheetnames == ["DU_BAO", "TOM_TAT", "CONFIG"]
    rows = _main_rows(wb)
    assert len(rows) == res["n_rows"] == 5 * 7 and res["is_stale"] is False
    assert [(r["sku_code"], r["horizon"]) for r in rows[:8]] == [("S1", h) for h in range(1, 8)] + [("S2", 1)]
    by = _by(rows)
    s1 = by[("S1", "F1", 3)]
    assert s1["forecast_date"] == _dt(D) and s1["target_date"] == _dt(D + timedelta(days=2))
    assert (s1["lightgbm_forecast"], s1["avg_demand"], s1["forecast_source"], s1["forecast_used"],
            s1["fallback_reason"]) == (3, 2.5, "LIGHTGBM", 3, None)
    assert (s1["nhom"], s1["model_used"], s1["raw_value"], s1["model_version"], s1["ten_san_pham"]) == \
        ("A", "MOC+DOW4", pytest.approx(2.6), "MV-R1", "Thuoc A")
    assert s1["data_cutoff_date"] == _dt(D - timedelta(days=1)) and s1["is_stale"] == 0 and s1["flags"] == "OPEN_HOURS_LAG"
    # AVG_DEMAND (default, no config row): the AVG value even with a LightGBM number, no reason
    s2 = by[("S2", "F1", 1)]
    assert (s2["forecast_source"], s2["lightgbm_forecast"], s2["forecast_used"], s2["fallback_reason"]) == \
        ("AVG_DEMAND", 1, 4.0, None)
    # LIGHTGBM in the run without a number for the day -> AVG + KHONG_CO_SO; no AVG row either -> 0 + KHONG_CO_SO_NAO
    # (owner decision 05/11/2026: forecast_used never empty; avg_demand stays empty)
    s3a, s3b = by[("S3", "F1", 5)], by[("S3", "F1", 6)]
    assert (s3a["lightgbm_forecast"], s3a["forecast_used"], s3a["fallback_reason"]) == (0, 0, None)
    assert (s3b["lightgbm_forecast"], s3b["avg_demand"], s3b["forecast_used"], s3b["fallback_reason"]) == \
        (None, None, 0, "KHONG_CO_SO_NAO")
    assert s3b["model_used"] is None and "AVG_NO_ROW" in s3b["flags"]
    # LIGHTGBM not in the forecast scope -> 0 + NGOAI_PHAM_VI_GAN_0, any prefix (owner final rule 05/11/2026)
    s4 = by[("S4", "F1", 1)]
    assert (s4["lightgbm_forecast"], s4["avg_demand"], s4["forecast_used"], s4["fallback_reason"], s4["nhom"]) == \
        (None, 3.0, 0, "NGOAI_PHAM_VI_GAN_0", None)
    # AVG without a value (seller rule pending): avg_demand empty, forecast_used 0 + KHONG_CO_SO_NAO + reason flag
    s5 = by[("S5", "F1", 7)]
    assert (s5["avg_demand"], s5["forecast_used"], s5["fallback_reason"], s5["flags"]) == \
        (None, 0, "KHONG_CO_SO_NAO", "AVG_SELLER_RULE_PENDING")
    assert not any(r["lightgbm_forecast"] == 99 for r in rows)          # the older run is not used


def test_autofilter_freeze_summary_and_config(scenario):
    res = export.write_daily_export(D, scope_key=SCOPE, trigger="MANUAL")
    wb = _book(res)
    ws = wb["DU_BAO"]
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref == "A1:T36"
    s = _summary(wb)
    assert s["forecast_date"] == D.isoformat() and s["data_cutoff_date"] == "2026-11-01"
    assert s["export_version"] == 1 and s["trigger"] == "MANUAL" and s["is_stale"] == 0 and s["stale_reason"] is None
    assert s["refresh_run_id"] == "R1" and s["export_time_utc"] == res["summary"]["created_at"]
    assert (s["sku_fc_total"], s["sku_fc_in_forecast_scope"], s["sku_fc_configured_lightgbm"],
            s["sku_fc_configured_lightgbm_not_in_file"], s["rows_total"]) == (5, 3, 4, 1, 35)
    assert s["rows_fallback_reason:NGOAI_PHAM_VI_GAN_0"] == 7 and s["rows_fallback_reason:KHONG_CO_SO_NAO"] == 2 + 7
    assert s["rows_fallback_reason:(none)"] == 19 and "rows_fallback_reason:KHONG_CO_SO" not in s
    assert "rows_fallback_reason:KHONG_CO_DU_LIEU_DEMAND" not in s
    assert s["rows_flag:OPEN_HOURS_LAG"] == 3 * 7 - 2 and s["rows_flag:AVG_SELLER_RULE_PENDING"] == 7
    assert s["sku_fc_avg_reason:SELLER_RULE_PENDING"] == 1 and s["sku_fc_avg_reason:NO_ROW"] == 1
    assert s["sku_fc_model_used:MOC+DOW4"] == 1 and s["sku_fc_model_used:FALLBACK:V33_L112"] == 1
    assert s["avg_source_kind"] == "CURRENT" and s["avg_source_modified"] == "2026-11-02T03:15:00+00:00"
    assert s["avg_seller_rule"] == "PENDING"
    cfg = list(wb["CONFIG"].iter_rows(values_only=True))
    assert list(cfg[0]) == ["sku_code", "fc_code", "ten_san_pham", "seller_code", "product_code", "ghi_chu",
                            "updated_by", "updated_at"]
    assert [r[:3] + r[5:6] for r in cfg[1:]] == [("S1", "F1", "Thuoc A", "chuyen LGBM"), ("S3", "F1", None, None),
                                                  ("S4", "F1", "Thuoc D", None), ("S9", "F1", None, None)]
    assert wb["CONFIG"].freeze_panes == "A2"


def test_versions_latest_copy_relative_path_and_sha(scenario):
    r1 = export.write_daily_export(D, scope_key=SCOPE)
    assert r1["path"] == "exports/du_bao/20261102/du_bao_20261102_v1.xlsx"
    p1 = paths.data_dir() / r1["path"]
    first = p1.read_bytes()
    assert hashlib.sha256(first).hexdigest() == r1["sha256"]
    _config([("S2", "F1", "LIGHTGBM", None)])
    r2 = export.write_daily_export(D, scope_key=SCOPE, trigger="MANUAL", job_id="J1")
    assert r2["version"] == 2 and r2["path"].endswith("du_bao_20261102_v2.xlsx")
    assert p1.read_bytes() == first                                     # earlier version never changed
    latest = paths.data_dir() / "exports" / "du_bao" / "20261102" / "du_bao_20261102.xlsx"
    assert r2["latest_path"] == "exports/du_bao/20261102/du_bao_20261102.xlsx"
    assert hashlib.sha256(latest.read_bytes()).hexdigest() == r2["sha256"] != r1["sha256"]
    assert sorted(x.name for x in latest.parent.iterdir()) == ["du_bao_20261102.xlsx", "du_bao_20261102_v1.xlsx",
                                                               "du_bao_20261102_v2.xlsx"]
    with db.read() as c:
        recs = db.rows(c, "SELECT * FROM export_runs ORDER BY version")
    assert [(r["version"], r["path"], r["sha256"], r["n_rows"], r["is_stale"], r["trigger"], r["job_id"],
             r["refresh_run_id"]) for r in recs] == [
        (1, r1["path"], r1["sha256"], 35, 0, "SCHEDULE", None, "R1"),
        (2, r2["path"], r2["sha256"], 35, 0, "MANUAL", "J1", "R1")]
    assert not recs[0]["path"].startswith(("/", "\\")) and ":" not in recs[0]["path"]
    assert json.loads(recs[1]["summary_json"])["version"] == 2
    assert [r["version"] for r in export.runs(D)] == [2, 1]
    # a file without a record is never overwritten: the next version skips it
    (latest.parent / "du_bao_20261102_v3.xlsx").write_bytes(b"orphan")
    r4 = export.write_daily_export(D, scope_key=SCOPE)
    assert r4["version"] == 4 and (latest.parent / "du_bao_20261102_v3.xlsx").read_bytes() == b"orphan"


def test_stale_run_of_an_earlier_day(sel2_on):
    old = D - timedelta(days=2)
    _run("ROLD", old, {("S1", "F1"): ("A", "MOC+DOW4", {h: (h * 10, h * 10.0) for h in range(1, 8)}),
                       ("S2", "F1"): ("B", "MOC+DOW4", {1: (5, 5.0)})}, flags="MODEL_PREV_WEEK")
    _run("ROTHER", D, {("S1", "F1"): ("A", "X", {1: (77, 77.0)})}, scope="OTHER-SCOPE")   # another scope: ignored
    _avg(D, [("S1", "F1", "SL1", 2.0, None), ("S7", "F1", "SL1", 1.5, None)])
    _config([("S1", "F1", "LIGHTGBM", None), ("S2", "F1", "LIGHTGBM", None), ("S7", "F1", "LIGHTGBM", None)])
    res = export.write_daily_export(D, scope_key=SCOPE)
    assert res["is_stale"] is True
    wb = _book(res)
    rows = _main_rows(wb)
    assert len(rows) == 3 * 7 and all(r["is_stale"] == 1 for r in rows)
    by = _by(rows)
    # target D = horizon 3 of the old run -> horizon 1 of the file
    assert (by[("S1", "F1", 1)]["lightgbm_forecast"], by[("S1", "F1", 1)]["forecast_used"],
            by[("S1", "F1", 1)]["target_date"]) == (30, 30, _dt(D))
    # owner rule 05/11/2026 (R3'): numbers of the previous run (D-2, within D-3 .. D-1) with reason + run-day flag
    assert by[("S1", "F1", 5)]["forecast_used"] == 70
    assert by[("S1", "F1", 5)]["fallback_reason"] == "DUNG_SO_LAN_CHAY_TRUOC"
    assert by[("S1", "F1", 1)]["flags"] == f"MODEL_PREV_WEEK,LAN_CHAY_TRUOC:{old.isoformat()}"
    # days the old run does not cover -> AVG + STALE; no AVG value either -> 0 + KHONG_CO_SO_NAO
    assert (by[("S1", "F1", 6)]["lightgbm_forecast"], by[("S1", "F1", 6)]["forecast_used"],
            by[("S1", "F1", 6)]["fallback_reason"]) == (None, 2.0, "STALE")
    assert by[("S2", "F1", 1)]["fallback_reason"] == "KHONG_CO_SO_NAO" and by[("S2", "F1", 1)]["avg_demand"] is None
    assert by[("S2", "F1", 1)]["forecast_used"] == 0
    # LIGHTGBM outside the scope of the (stale) run used -> 0 + NGOAI_PHAM_VI_GAN_0 (owner final rule 05/11/2026)
    assert (by[("S7", "F1", 1)]["avg_demand"], by[("S7", "F1", 1)]["forecast_used"],
            by[("S7", "F1", 1)]["fallback_reason"]) == (1.5, 0, "NGOAI_PHAM_VI_GAN_0")
    assert by[("S1", "F1", 1)]["data_cutoff_date"] == _dt(old - timedelta(days=1))
    s = _summary(wb)
    assert s["is_stale"] == 1 and s["stale_reason"] == "NO_RUN_FOR_DAY" and s["run_forecast_date"] == old.isoformat()
    assert s["rows_fallback_reason:STALE"] == 2 and s["rows_fallback_reason:KHONG_CO_SO_NAO"] == 7
    assert s["rows_flag:MODEL_PREV_WEEK"] == 5
    assert s["rows_fallback_reason:DUNG_SO_LAN_CHAY_TRUOC"] == 5 and s[f"rows_flag:LAN_CHAY_TRUOC:{old.isoformat()}"] == 5
    with db.read() as c:
        rec = db.one(c, "SELECT is_stale, flags, refresh_run_id FROM export_runs")
    assert rec["is_stale"] == 1 and rec["refresh_run_id"] == "ROLD" and rec["flags"].startswith("STALE")


def test_no_run_at_all_every_row_from_avg(sel2_on):
    _avg(D, [("S1", "F1", "SL1", 2.0, None), ("S2", "F2", "SL1", None, None)])
    _config([("S1", "F1", "LIGHTGBM", None)])
    res = export.write_daily_export(D, scope_key=SCOPE)
    rows = _main_rows(_book(res, normal=False))
    assert len(rows) == 14 and all(r["is_stale"] == 1 and r["model_version"] is None for r in rows)
    by = _by(rows)
    assert (by[("S1", "F1", 1)]["forecast_used"], by[("S1", "F1", 1)]["fallback_reason"]) == (2.0, "KHONG_CO_SO")
    assert (by[("S2", "F2", 1)]["forecast_used"], by[("S2", "F2", 1)]["fallback_reason"],
            by[("S2", "F2", 1)]["flags"]) == (0, "KHONG_CO_SO_NAO", "AVG_AVG_DEMAND_NULL")
    assert res["summary"]["stale_reason"] == "NO_SEL2_RUN" and res["summary"]["refresh_run_id"] is None


def test_owner_rule_outside_the_scope_zero_for_every_prefix(sel2_on):
    """Owner final rule 05/11/2026, every SKU x FC LIGHTGBM: a LightGBM number (0 included) is used; outside the scope
    of the run -> 0 + NGOAI_PHAM_VI_GAN_0 for every sku_code prefix (MEDX, MEDX_E, BML_INT, ...), with or without an
    AVG value. In the run without a number keeps AVG + KHONG_CO_SO (never 0); AVG_DEMAND configured is unchanged."""
    _run("R1", D, {("MEDX.A", "F1"): ("A", "MOC+DOW4", {h: (0 if h == 1 else h, 0.1) for h in range(1, 8)}),
                   ("MEDX.C", "F1"): ("C", "MOC+DOW4", {h: (2, 2.0) for h in range(1, 6)})})
    _avg(D, [("MEDX.A", "F1", "SL1", 2.0, None), ("MEDX.B", "F1", "SL1", 5.0, None),
             ("MEDX_E.X", "F1", "SL1", 3.0, None), ("BML_INT.Y", "F2", "SL1", None, None),
             ("MEDX.C", "F1", "SL1", 1.0, None), ("MEDX.D", "F1", "SL1", 6.0, None)])
    _config([(s, f, "LIGHTGBM", None) for s, f in (("MEDX.A", "F1"), ("MEDX.B", "F1"), ("MEDX_E.X", "F1"),
                                                   ("BML_INT.Y", "F2"), ("MEDX.C", "F1"))])
    res = export.write_daily_export(D, scope_key=SCOPE)
    wb = _book(res)
    by = _by(_main_rows(wb))
    pick = lambda k: (by[k]["lightgbm_forecast"], by[k]["avg_demand"], by[k]["forecast_used"], by[k]["fallback_reason"])
    assert pick(("MEDX.A", "F1", 1)) == (0, 2.0, 0, None) and pick(("MEDX.A", "F1", 2)) == (2, 2.0, 2, None)
    assert all(pick(("MEDX.B", "F1", h)) == (None, 5.0, 0, "NGOAI_PHAM_VI_GAN_0") for h in range(1, 8))
    assert all(pick(("MEDX_E.X", "F1", h)) == (None, 3.0, 0, "NGOAI_PHAM_VI_GAN_0") for h in range(1, 8))
    assert all(pick(("BML_INT.Y", "F2", h)) == (None, None, 0, "NGOAI_PHAM_VI_GAN_0") for h in range(1, 8))
    assert pick(("MEDX.C", "F1", 5)) == (2, 1.0, 2, None) and pick(("MEDX.C", "F1", 6)) == (None, 1.0, 1.0, "KHONG_CO_SO")
    assert by[("MEDX.D", "F1", 1)]["forecast_source"] == "AVG_DEMAND" and pick(("MEDX.D", "F1", 1)) == (None, 6.0, 6.0, None)
    s = _summary(wb)
    assert s["rows_fallback_reason:NGOAI_PHAM_VI_GAN_0"] == 3 * 7
    assert "rows_fallback_reason:KHONG_CO_DU_LIEU_DEMAND" not in s and "rows_fallback_reason:KHONG_CO_SO_NAO" not in s
    assert s["rows_fallback_reason:KHONG_CO_SO"] == 2 and "rows_fallback_reason:NGOAI_PHAM_VI" not in s


def test_owner_rule_not_applied_without_any_run(sel2_on):
    """No SEL2 run at all: a MEDX SKU x FC is not set to 0 (nothing says it is outside the scope) -> AVG + KHONG_CO_SO."""
    _avg(D, [("MEDX.B", "F1", "SL1", 5.0, None)])
    _config([("MEDX.B", "F1", "LIGHTGBM", None)])
    res = export.write_daily_export(D, scope_key=SCOPE)
    by = _by(_main_rows(_book(res, normal=False)))
    assert (by[("MEDX.B", "F1", 1)]["forecast_used"], by[("MEDX.B", "F1", 1)]["fallback_reason"]) == (5.0, "KHONG_CO_SO")


def test_export_refused_while_the_pipeline_is_off(sel2_off):
    with pytest.raises(AppError) as e:
        export.write_daily_export(D, scope_key=SCOPE)
    assert e.value.code == "SEL2_PIPELINE_DISABLED"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM export_runs").fetchone()[0] == 0


def test_resolved_file_must_stay_in_the_export_folder(sel2_on):
    with pytest.raises(AppError) as e:
        export.resolve_file("exports/du_bao/../../db/app.db")
    assert e.value.code == "SEL2_EXPORT_PATH_INVALID"
    assert export.export_root() == (paths.data_dir() / "exports" / "du_bao").resolve()


def test_api_download_runs_and_post(scenario, client, monkeypatch):
    monkeypatch.setattr(export, "_scope_key", lambda conn: (SCOPE, None))
    r = client.get("/api/sel2/export/2026-11-02")
    assert r.status_code == 404 and r.json()["code"] == "SEL2_EXPORT_NOT_FOUND"
    r = client.post("/api/sel2/export", json={"date": "2026-11-02"})
    assert r.status_code == 409 and r.json()["code"] == "SEL2_EXPORT_CONFIRM_REQUIRED"
    r = client.post("/api/sel2/export", json={"date": "2026-11-02", "confirm": True}, headers={"X-DF-Client": ""})
    assert r.status_code == 403
    assert client.post("/api/sel2/export", json={"date": "02/11/2026", "confirm": True}).status_code == 422
    r = client.post("/api/sel2/export", json={"date": "2026-11-02", "confirm": True})
    # 1.4.0 S5: a FORECAST_EXPORT job (mode MANUAL); the client fixture runs it before the response returns
    job = r.json()
    assert r.status_code == 200 and job["job_type"] == "FORECAST_EXPORT" and job["status"] == "SUCCEEDED"
    res = json.loads(job["result_json"])["result"]
    assert res["mode"] == "MANUAL" and res["version"] == 1 and res["n_rows"] == 35
    sha = res["sha256"]
    r = client.get("/api/sel2/export/2026-11-02")
    assert r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == sha
    assert "du_bao_20261102.xlsx" in r.headers["content-disposition"] and r.headers["x-df-export-version"] == "1"
    assert load_workbook(io.BytesIO(r.content)).sheetnames == ["DU_BAO", "TOM_TAT", "CONFIG"]
    runs = client.get("/api/sel2/export/2026-11-02/runs").json()
    assert runs["forecast_date"] == "2026-11-02" and [x["version"] for x in runs["items"]] == [1]
    assert runs["items"][0]["summary"]["refresh_run_id"] == "R1"
    assert client.get("/api/sel2/export/2026-13-02/runs").status_code == 422


def test_cli_plan_without_yes_then_write(sel2_on, capsys):
    _avg(D, [("S1", "F1", "SL1", 2.0, None)])
    assert cli.main(["sel2-export", "--date", "2026-11-02"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["db"].endswith("app.db") and out["versions"] == []
    assert out["target_file"].endswith("du_bao_20261102.xlsx") and "exports" in out["target_file"]
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM export_runs").fetchone()[0] == 0
    assert not (paths.data_dir() / "exports").exists()
    assert cli.main(["sel2-export", "--date", "2026-11-31"]) == 2
    capsys.readouterr()
    # --yes: the test database has no active data scope -> stale export from AVG_DEMAND only
    assert cli.main(["sel2-export", "--date", "2026-11-02", "--yes"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["result"]["version"] == 1 and out["result"]["n_rows"] == 7 and out["result"]["is_stale"] is True
    assert out["result"]["summary"]["stale_reason"].startswith("SCOPE_UNRESOLVED")
