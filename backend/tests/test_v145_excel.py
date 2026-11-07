"""1.4.5 (owner decisions 06/11/2026 21:20 and 07/11 00:55) on the daily Excel (ml/sel2/export.py) and the history
sidecars (ml/sel2/published.py): C2 lightgbm_forecast rounded at every horizon 1..20 with forecast_used / fallback_reason
identical to the 1.4.4 code path; A1 history horizon 1; C6 earlier versions renamed _bo with their paths updated (and a
rename failure that never fails the export); C7 FALLBACK shares in TOM_TAT; C5 the OPEN_HOURS_LAG line of TOM_TAT.
Integration with fakes (isolated temporary database and data folder, rows inserted directly)."""
import json
import os
from datetime import timedelta

import pytest
from openpyxl import load_workbook

from app import data_checks, db, paths
from app.ml.sel2 import export, published
from test_v140_t6_export import D, SCOPE, _run
from test_v144_excel20 import COLS20, scenario  # noqa: F401  (fixture)


def _book(rel):
    wb = load_workbook(paths.data_dir() / rel, read_only=True)
    sheets = {n: list(wb[n].iter_rows(values_only=True)) for n in wb.sheetnames}
    wb.close()
    rows = [dict(zip(COLS20, r)) for n, v in sheets.items() if n.startswith("DU_BAO_") for r in v[1:]]
    summary = {r[0]: r[1] for r in sheets["TOM_TAT"][1:]}
    return rows, summary


# ------------------------------------------------------------------ C2
def test_lightgbm_forecast_is_an_int_at_every_horizon_and_forecast_used_unchanged(scenario, monkeypatch):
    rnd = export.round_lgbm
    new = export.write_daily_export(D, scope_key=SCOPE)
    rows, _ = _book(new["path"])
    assert len(rows) == new["n_rows"] == 11 * 20
    assert all(r["lightgbm_forecast"] is None or type(r["lightgbm_forecast"]) is int for r in rows)
    assert any(r["horizon"] > 7 and r["lightgbm_forecast"] is not None for r in rows)
    # the 1.4.4 code path: lightgbm_forecast written as given (unrounded); everything else must be identical
    monkeypatch.setattr(export, "round_lgbm", lambda x: x)
    old = export.write_daily_export(D, scope_key=SCOPE)
    rows_old, _ = _book(old["path"])
    key = lambda r: (r["sku_code"], r["fc_code"], r["horizon"])
    by_old = {key(r): r for r in rows_old}
    assert set(by_old) == {key(r) for r in rows}
    for r in rows:
        o = by_old[key(r)]
        assert (r["forecast_used"], r["fallback_reason"], r["raw_value"], r["flags"]) == \
            (o["forecast_used"], o["fallback_reason"], o["raw_value"], o["flags"]), key(r)
        assert r["lightgbm_forecast"] == rnd(o["lightgbm_forecast"]), key(r)
    assert any(isinstance(o["lightgbm_forecast"], float) and not o["lightgbm_forecast"].is_integer()
               for o in rows_old)                                     # the case really occurs (h8..20 raw values)


@pytest.mark.parametrize("x, want", [(None, None), (0, 0), (0.19999, 0), (0.2, 1), (1.0000001, 1), (1.000002, 2),
                                     (-3, 0), (7, 7), (float("nan"), None), ("abc", None)])
def test_round_lgbm(x, want):
    got = export.round_lgbm(x)
    assert got == want and (got is None or type(got) is int)


# ------------------------------------------------------------------ A1
def test_history_sidecar_keeps_horizon_1_target_is_the_forecast_day(scenario):
    res = export.write_daily_export(D, scope_key=SCOPE)
    rows, _ = _book(res["path"])
    want = {(r["sku_code"], r["fc_code"]): r["forecast_used"] for r in rows if r["horizon"] == 1}
    got = published.load({"id": res["id"], "forecast_date": D.isoformat(), "path": res["path"], "sha256": res["sha256"]})
    assert published.HISTORY_HORIZONS == (1,)
    assert {(r[0], r[1]): r[3] for r in got} == want and {r[2] for r in got} == {D.isoformat()}


def test_a_144_sidecar_of_horizon_2_is_rebuilt_as_horizon_1(scenario):
    res = export.write_daily_export(D, scope_key=SCOPE)
    rec = {"id": res["id"], "forecast_date": D.isoformat(), "path": res["path"], "sha256": res["sha256"]}
    vf = paths.data_dir() / res["path"]
    doc = published.sidecar_path(vf)
    with pytest.MonkeyPatch.context() as mp:                   # pretend the stored file is a 1.4.4 sidecar (horizons [2])
        mp.setattr(published, "HISTORY_HORIZONS", (2,))
        published.write(vf, res["id"], D, res["sha256"], [("S1", "BD", (D + timedelta(days=1)).isoformat(), 9, "X", None)])
    published.clear_cache()
    st = published.ensure(rec)
    assert st["status"] == "CREATED" and {r[2] for r in st["_rows"]} == {D.isoformat()}
    assert published.ensure(rec)["status"] == "PRESENT" and doc.is_file()


# ------------------------------------------------------------------ C6
def _recs():
    with db.read() as c:
        return db.rows(c, "SELECT id, version, path, flags FROM export_runs ORDER BY version")


def test_earlier_versions_renamed_bo_paths_updated_and_data_check_ok(scenario):
    r1 = export.write_daily_export(D, scope_key=SCOPE)
    r2 = export.write_daily_export(D, scope_key=SCOPE)
    r3 = export.write_daily_export(D, scope_key=SCOPE)
    folder = (paths.data_dir() / r3["path"]).parent
    ymd = D.strftime("%Y%m%d")
    assert sorted(p.name for p in folder.iterdir()) == [f"du_bao_{ymd}.xlsx", f"du_bao_{ymd}_v1_bo.xlsx",
                                                        f"du_bao_{ymd}_v2_bo.xlsx", f"du_bao_{ymd}_v3.xlsx"]
    recs = _recs()
    assert [r["path"].rsplit("/", 1)[1] for r in recs] == [f"du_bao_{ymd}_v1_bo.xlsx", f"du_bao_{ymd}_v2_bo.xlsx",
                                                          f"du_bao_{ymd}_v3.xlsx"]
    assert r2["retired"] == [recs[0]["path"]] and r3["retired"] == [recs[1]["path"]]
    for r, res in zip(recs, (r1, r2, r3)):                     # content (sha256) unchanged by the rename
        assert export._sha256(paths.data_dir() / r["path"]) == res["sha256"]
    # the latest copy and the newest version are unchanged behaviour
    assert (folder / f"du_bao_{ymd}.xlsx").read_bytes() == (paths.data_dir() / r3["path"]).read_bytes()
    assert export.latest_file(D)[1]["version"] == 3
    chk = {x["check"]: x for x in data_checks.run(paths.db_path(), paths.models_dir())["checks"]}
    assert chk["export_files_exist"]["status"] == "OK", chk["export_files_exist"]
    # the sidecar of a renamed version keeps its name and is found again (no rebuild)
    with db.read() as c:
        r = db.one(c, "SELECT id, forecast_date, path, sha256 FROM export_runs WHERE version=1")
    published.clear_cache()
    assert published.ensure(r, create=False)["status"] == "PRESENT"
    assert published.sidecar_path(paths.data_dir() / r["path"]).name == f"du_bao_{ymd}_v1.h2.json.gz"


def test_rename_failure_keeps_the_old_name_and_flags_the_export(scenario, monkeypatch):
    r1 = export.write_daily_export(D, scope_key=SCOPE)
    real = os.rename

    def locked(a, b):
        if str(a).endswith("_v1.xlsx"):
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real(a, b)
    monkeypatch.setattr(export.os, "rename", locked)
    r2 = export.write_daily_export(D, scope_key=SCOPE)
    assert export.FLAG_RENAME_FAILED in r2["flags"] and r2["retired"] == []
    recs = _recs()
    assert recs[0]["path"] == r1["path"] and (paths.data_dir() / r1["path"]).is_file()
    assert export.FLAG_RENAME_FAILED in recs[1]["flags"].split(",")
    monkeypatch.setattr(export.os, "rename", real)
    r3 = export.write_daily_export(D, scope_key=SCOPE)            # Excel closed: the next export renames both
    assert [r["path"].endswith("_bo.xlsx") for r in _recs()] == [True, True, False]
    assert export.FLAG_RENAME_FAILED not in r3["flags"]


def test_failed_record_renames_back(scenario, monkeypatch):
    r1 = export.write_daily_export(D, scope_key=SCOPE)
    monkeypatch.setattr(export.db, "audit", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(export.AppError):
        export.write_daily_export(D, scope_key=SCOPE)
    assert [r["path"] for r in _recs()] == [r1["path"]] and (paths.data_dir() / r1["path"]).is_file()


def test_record_left_on_the_old_name_after_a_crash_is_repaired(scenario):
    r1 = export.write_daily_export(D, scope_key=SCOPE)
    p1 = paths.data_dir() / r1["path"]
    os.rename(p1, export.retired_path(p1))                     # renamed, record not updated (crash in between)
    r2 = export.write_daily_export(D, scope_key=SCOPE)
    assert _recs()[0]["path"] == r2["retired"][0] and (paths.data_dir() / r2["retired"][0]).is_file()


# ------------------------------------------------------------------ C7 / C5
def _open_hours(rows):
    from app.bq import aux_sources
    tbl, seller = aux_sources.open_hours_source()
    with db.tx() as c:
        c.executemany("INSERT INTO open_hours_daily(source_table, seller_code, fc_code, sku_code, open_date, "
                      "total_open_hours, n_items, loaded_at) VALUES (?,?,?,?,?,?,1,'2026-11-01T00:00:00+00:00')",
                      [(tbl, seller, fc, sku, d, h) for sku, fc, d, h in rows])
    return tbl


def test_fallback_shares_two_denominators(scenario):
    """R1 of D: 7 SKU x FC in scope, S3 x HN is FALLBACK. Open days in D-28 .. D-1: S1, S3 (hours > 0); S2 only
    0 hours; S3 x HN open -> FALLBACK with open days; then a run where the FALLBACK has no open day."""
    d1 = (D - timedelta(days=1)).isoformat()
    _open_hours([("S1", "BD", d1, 8.0), ("S3", "HN", d1, 4.0), ("S2", "BD", d1, 0.0),
                 ("S4", "HN", (D - timedelta(days=29)).isoformat(), 8.0)])           # S4: outside the window
    res = export.write_daily_export(D, scope_key=SCOPE)
    fb = res["summary"]["fallback"]
    w0, w1 = (D - timedelta(days=28)).isoformat(), d1
    assert fb == {"window_days": 28, "window": f"{w0}..{w1}", "sku_fc_in_scope": 7, "sku_fc_open_in_window": 2,
                  "sku_fc_fallback": 1, "fallback_no_open_day": 0, "fallback_with_open_day": 1,
                  "pct_all": round(100 / 7, 2), "pct_open": 50.0}
    _, s = _book(res["path"])
    assert (s["fallback_window"], s["sku_fc_fallback"], s["fallback_pct_all_sku_fc"], s["sku_fc_open_in_window"],
            s["fallback_pct_open_sku_fc"], s["sku_fc_fallback:khong_mo_ban_28_ngay"],
            s["sku_fc_fallback:co_mo_ban_thieu_ngay"]) == (f"{w0}..{w1}", 1, round(100 / 7, 2), 2, 50.0, 0, 1)
    keys = list(s)
    assert keys.index("fallback_window") > max(i for i, k in enumerate(keys) if k.startswith("sku_fc_model_used:"))
    assert keys.index("sku_fc_fallback:co_mo_ban_thieu_ngay") < keys.index("avg_source_kind")
    # a new run of D where S1 x BD (open) and S4 x HN (no open day in the window) are FALLBACK
    _run("R2", D, {("S1", "BD"): ("A", "FALLBACK:V33_L112", {h: (1, 1.0) for h in range(1, 8)}),
                   ("S4", "HN"): ("A", "FALLBACK:V33_L112", {h: (1, 1.0) for h in range(1, 8)}),
                   ("S5", "HN"): ("A", "MOC+DOW4", {h: (1, 1.0) for h in range(1, 8)})},
         created="2026-11-02T01:00:00+00:00")
    fb2 = export.write_daily_export(D, scope_key=SCOPE)["summary"]["fallback"]
    assert (fb2["sku_fc_in_scope"], fb2["sku_fc_open_in_window"], fb2["sku_fc_fallback"], fb2["fallback_no_open_day"],
            fb2["fallback_with_open_day"], fb2["pct_all"], fb2["pct_open"]) == (3, 1, 2, 1, 1, 66.67, 100.0)


def test_open_hours_lag_line_with_build_times(scenario):
    tbl = _open_hours([("S1", "BD", "2026-10-30", 8.0), ("S1", "BD", "2026-10-31", 8.0)])
    from app.bq import aux_sources
    with db.tx() as c:
        c.execute("INSERT INTO aux_source_reads(source_table, seller_code, kind, range_start, range_end, n_rows, last_day, "
                  "source_modified, completed_at) VALUES (?,?,?,?,?,1,?,?,?)",
                  (tbl, aux_sources.open_hours_source()[1], aux_sources.KIND_OPEN_HOURS, "2026-10-01", "2026-11-01",
                   "2026-10-31", "2026-11-01T18:20:00+00:00", "2026-11-01T22:00:00+00:00"))
        c.execute("INSERT INTO demand_sync_runs(id, kind, status, scope_key, source_version, started_at, finished_at, "
                  "summary_json) VALUES ('D1L-1', 'D1_SYNC', 'COMMITTED', ?, '2026-11-01T17:40:00+00:00', "
                  "'2026-11-01T22:10:00+00:00', '2026-11-01T22:15:00+00:00', '{}')", (SCOPE,))
    res = export.write_daily_export(D, scope_key=SCOPE)          # R1 carries the flag OPEN_HOURS_LAG
    sb = res["summary"]["source_build"]
    assert "OPEN_HOURS_LAG" in res["flags"]
    assert (sb["open_hours_last_day"], sb["open_hours_built_at"], sb["demand_built_at"]) == \
        ("2026-10-31", "2026-11-01T18:20:00+00:00", "2026-11-01T17:40:00+00:00")
    assert sb["built_first"] != tbl and sb["built_first"] != export.UNKNOWN     # the demand table was built first
    _, s = _book(res["path"])
    line = s["open_hours_lag_note"]
    assert line == sb["text"] and "2026-10-31" in line and "2026-11-02 01:20:00" in line and "2026-11-02 00:40:00" in line
    with db.read() as c:
        assert json.loads(db.one(c, "SELECT summary_json FROM export_runs WHERE id=?", (res["id"],))["summary_json"])[
            "source_build"]["text"] == line


def test_open_hours_lag_line_unknown_and_absent_without_the_flag(scenario):
    res = export.write_daily_export(D, scope_key=SCOPE)
    sb = res["summary"]["source_build"]
    assert sb["built_first"] == export.UNKNOWN and sb["open_hours_built_at"] is None
    _, s = _book(res["path"])
    assert "khong ro" in s["open_hours_lag_note"]
    # a run without the flag: no line
    _run("R9", D, {("S1", "BD"): ("A", "MOC", {h: (1, 1.0) for h in range(1, 8)})}, created="2026-11-02T02:00:00+00:00")
    r2 = export.write_daily_export(D, scope_key=SCOPE)
    _, s2 = _book(r2["path"])
    assert "OPEN_HOURS_LAG" not in r2["flags"] and "open_hours_lag_note" not in s2


# ------------------------------------------------------------------ C8 (owner decision 07/11/2026 01:10)
def _config_rows():
    with db.read() as c:
        conf = {(r["sku_code"], r["fc_code"]): r for r in db.rows(c, "SELECT * FROM forecast_source_config")}
        hist = db.rows(c, "SELECT * FROM forecast_source_config_history ORDER BY id")
    return conf, hist


def test_default_codes_with_a_number_switch_to_lightgbm_with_history(scenario):
    from app.ml.sel2 import source_config
    source_config.set_one("S4", "HN", "AVG_DEMAND", ghi_chu="giu Avg", confirm=True, changed_by="nguoi_dung")
    conf0, hist0 = _config_rows()
    hc = lambda: next(x for x in data_checks.run(paths.db_path())["checks"]
                      if x["check"] == "forecast_source_config_history")
    chk0 = hc()                                    # the fixture writes configuration rows without history (direct SQL)
    out = export.auto_switch_new_codes(D, SCOPE)
    conf, hist = _config_rows()
    # R1 of D: S3 x HN is the only code in the run without any configuration row / history (default AVG_DEMAND)
    assert out["switched"] == 1 and out["batch_id"]
    assert conf[("S3", "HN")]["forecast_source"] == "LIGHTGBM" and conf[("S3", "HN")]["updated_by"] == "system"
    assert conf[("S3", "HN")]["ghi_chu"] == "AUTO_LIGHTGBM_KHI_CO_SO"
    new = hist[len(hist0):]
    assert [(h["sku_code"], h["fc_code"], h["old_source"], h["new_source"], h["changed_by"], h["ghi_chu"],
             h["batch_id"]) for h in new] == [("S3", "HN", None, "LIGHTGBM", "system", "AUTO_LIGHTGBM_KHI_CO_SO",
                                               out["batch_id"])]
    assert conf[("S4", "HN")]["forecast_source"] == "AVG_DEMAND"          # set by a user: untouched
    assert ("S10", "BD") not in conf and ("S9", "HN") not in conf           # no number in the run: untouched
    assert {k: v for k, v in conf.items() if k != ("S3", "HN")} == conf0     # nothing else changed
    with db.read() as c:
        assert db.one(c, "SELECT COUNT(*) AS n FROM audit_log WHERE action='FORECAST_SOURCE_AUTO_LIGHTGBM'")["n"] == 1
    # idempotent: a second run switches nothing and writes no history
    assert export.auto_switch_new_codes(D, SCOPE) == {"switched": 0, "batch_id": None}
    assert _config_rows() == (conf, hist)
    assert hc()["count"] == chk0["count"]          # the switched row equals its history row (no new mismatch)


def test_no_run_of_the_day_switches_nothing(scenario):
    assert export.auto_switch_new_codes(D + timedelta(days=1), SCOPE) == {"switched": 0, "batch_id": None}


def test_pipeline_hook_switches_before_the_export(scenario, monkeypatch):
    from app.ml.sel2 import pipeline
    monkeypatch.setattr(export, "_scope_key", lambda conn: (SCOPE, None))
    out = pipeline._export_hook(D, "SCHEDULE", None)
    assert out["ok"] is True and out["auto_lightgbm"]["switched"] == 2            # S3 x HN and S4 x HN (default)
    rows, _ = _book(out["result"]["path"])
    s3 = {r["horizon"]: r for r in rows if (r["sku_code"], r["fc_code"]) == ("S3", "HN")}
    assert s3[1]["forecast_source"] == "LIGHTGBM" and s3[1]["forecast_used"] == 1 and s3[1]["fallback_reason"] is None
    # write_daily_export itself never changes the configuration (a default code of a newer run stays default)
    _run("R5", D, {("S77", "HN"): ("A", "MOC", {h: (2, 2.0) for h in range(1, 8)})}, created="2026-11-02T03:00:00+00:00")
    before = _config_rows()
    export.write_daily_export(D, scope_key=SCOPE, trigger="MANUAL")
    assert _config_rows() == before and ("S77", "HN") not in before[0]


# ------------------------------------------------------------------ fix round: F2 / F3 / F4
@pytest.mark.parametrize("channel", ["UI", "API"])
def test_user_set_avg_without_note_is_recorded_and_never_switched(scenario, channel):
    from app.ml.sel2 import source_config
    out = source_config.set_one("S3", "HN", "AVG_DEMAND", confirm=True, changed_by="nguoi_dung", channel=channel)
    assert out["changed"] is True and out["after"]["configured"] is True
    conf, hist = _config_rows()
    assert conf[("S3", "HN")]["forecast_source"] == "AVG_DEMAND"
    assert [(h["old_source"], h["new_source"], h["channel"]) for h in hist if h["sku_code"] == "S3"] == \
        [(None, "AVG_DEMAND", channel)]
    out = export.auto_switch_new_codes(D, SCOPE)
    assert out["switched"] == 1 and _config_rows()[0][("S3", "HN")]["forecast_source"] == "AVG_DEMAND"   # S4 only
    assert _config_rows()[0][("S4", "HN")]["forecast_source"] == "LIGHTGBM"


def test_upload_of_avg_on_an_unconfigured_code_is_recorded_and_never_switched(scenario):
    import io
    from openpyxl import Workbook
    from app.ml.sel2 import source_config
    wb = Workbook()
    ws = wb.active
    ws.append(["sku_code", "fc_code", "forecast_source"])
    ws.append(["S3", "HN", "AVG_DEMAND"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    p = source_config.preview_upload(buf, "x.xlsx")
    assert p["counts"]["changed"] == 1 and p["can_apply"] is True
    assert source_config.apply_upload(p["preview_id"], confirm=True, changed_by="nguoi_dung")["applied"] == 1
    export.auto_switch_new_codes(D, SCOPE)
    assert _config_rows()[0][("S3", "HN")]["forecast_source"] == "AVG_DEMAND"


@pytest.mark.parametrize("bad", ["fallback", "source_build", "time"])
def test_summary_information_errors_never_fail_the_export(scenario, monkeypatch, bad):
    def boom(*a, **k):
        raise ValueError("unexpected")
    if bad == "fallback":
        monkeypatch.setattr(export, "_fallback_info", boom)
    elif bad == "source_build":
        monkeypatch.setattr(export, "_source_build", boom)
    else:                                       # an unreadable stored time: "khong ro", no flag needed
        from app.bq import aux_sources
        with db.tx() as c:
            c.execute("INSERT INTO aux_source_reads(source_table, seller_code, kind, range_start, range_end, n_rows, "
                      "last_day, source_modified, completed_at) VALUES (?,?,?,?,?,1,NULL,'not-a-time',"
                      "'2026-11-01T22:00:00+00:00')", (*aux_sources.open_hours_source(), aux_sources.KIND_OPEN_HOURS,
                                                       "2026-10-01", "2026-11-01"))
    res = export.write_daily_export(D, scope_key=SCOPE)
    rows, s = _book(res["path"])
    assert len(rows) == res["n_rows"] and "khong ro" in s["open_hours_lag_note"]
    if bad == "time":
        assert export.FLAG_INFO_FAILED not in res["flags"] and res["summary"]["source_build"]["built_first"] == "khong ro"
    else:
        assert export.FLAG_INFO_FAILED in res["flags"] and export.FLAG_INFO_FAILED in s["file_flags"]
    if bad == "fallback":
        assert res["summary"]["fallback"] is None and "fallback_window" not in s


def test_auto_switch_reads_the_key_sets_once(scenario, monkeypatch):
    """F4: no per-row subquery on the history; same result and idempotence as before."""
    calls = []
    real = export._set_keys
    monkeypatch.setattr(export, "_set_keys", lambda c: calls.append(1) or real(c))
    assert export.auto_switch_new_codes(D, SCOPE)["switched"] == 2 and len(calls) == 2
    calls.clear()
    assert export.auto_switch_new_codes(D, SCOPE)["switched"] == 0 and len(calls) == 1   # nothing to do: no write tx


def test_crash_state_newest_record_on_a_renamed_file_still_readable(scenario):
    """Killed between the _bo rename and the commit: the newest record keeps vN.xlsx, only vN_bo.xlsx exists. The app
    reads the _bo file (read-only, nothing renamed back), the history sidecar is found / rebuilt, the next export repairs."""
    r1 = export.write_daily_export(D, scope_key=SCOPE)
    p1 = paths.data_dir() / r1["path"]
    bo = export.retired_path(p1)
    os.rename(p1, bo)
    p, rec = export.latest_file(D)
    assert p == bo and rec["path"] == r1["path"] and not p1.exists()
    rd = {"id": r1["id"], "forecast_date": D.isoformat(), "path": r1["path"], "sha256": r1["sha256"]}
    published.clear_cache()
    assert published.ensure(rd, create=False)["status"] == "PRESENT"
    published.sidecar_path(bo).unlink()                                    # sidecar lost too: rebuilt from the _bo xlsx
    published.clear_cache()
    st = published.ensure(rd)
    assert st["status"] == "CREATED" and st["rows"] > 0 and not p1.exists() and bo.is_file()
    assert published.load(rd)
