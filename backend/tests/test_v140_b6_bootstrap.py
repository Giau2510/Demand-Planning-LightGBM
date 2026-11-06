"""1.4.0 B6: first start (pipeline.bootstrap) trains the origin of TODAY first, then writes the temporary Excel
du_bao_YYYYMMDD_TAM.xlsx (export.write_temp_export: V33_L112 candidate of today for every SKU x FC, not published, not
in export_runs), then the other origins, the past days and run_day(today); sel2-bootstrap --days defaults to 28.
Isolated test DB, synthetic rows; the order / hook tests stub the trainings (unit), the end-to-end test trains LightGBM
for real on synthetic rows (integration with fakes; no BigQuery, no live data)."""
import inspect
import json
import os
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook

from app import cli, data_checks, db, paths, timeutil
from app import settings_service as ss
from app.messages import AppError
from app.ml.daily_refresh import published_qty
from app.ml.sel2 import errors, export, pipeline, select, source_config, store
from test_v140_t4a_pipeline import SCOPE as SEED_SCOPE, _plenty_of_memory, _seed
from test_v140_t6_export import COLS, _avg, _by, _main_rows, _run

SCOPE = "SC-B6"
D = date(2026, 11, 2)                       # Monday
WED = date(2026, 10, 28)                    # Wednesday: origin_of(WED) = 2026-10-26
NOTE = "b\u1ea3n t\u1ea1m \u2013 ch\u01b0a ch\u1ecdn m\xf4 h\xecnh theo SKU"
DAY_FOLDER = ("exports", "du_bao", "20261102")
TAM_REL = "exports/du_bao/20261102/du_bao_20261102_TAM.xlsx"
SEL2_CHECKS = ("sel2_protection_triggers", "candidate_runs_data_before_day", "candidate_forecasts_target_date",
               "candidate_forecasts_runs", "candidate_train_runs_stuck", "forecast_source_config_history",
               "export_files_exist")
V33 = {("S1", "F1"): [0.0, 0.19, 0.2, 1.0, 1.2, 2.5, 3.0000001],      # threshold edges, 6-decimal rounding
       ("S2", "F1"): [5.5] * 7,
       ("S3", "F1"): [0.1999999, 0.21, 7.0, 0.0, 0.0, 0.0, 0.5]}
GROUPS = {("S1", "F1"): "A", ("S2", "F1"): "B", ("S3", "F1"): float("nan")}


# ------------------------------------------------------------------ helpers
def _cands(v33: dict, other=1.0) -> dict:
    keys = list(v33)
    base = {"sku_code": np.repeat([k[0] for k in keys], 7), "fc_code": np.repeat([k[1] for k in keys], 7),
            "horizon": np.tile(np.arange(1, 8), len(keys))}
    out = {m: pd.DataFrame({**base, "value": other + i}) for i, m in enumerate(select.CANDIDATES)}
    out["V33_L112"] = pd.DataFrame({**base, "value": np.concatenate([np.asarray(v33[k], dtype=float) for k in keys])})
    return out


def _store_candidates(d=D, v33=V33, scope=SCOPE):
    """Candidates of d; their LightGBM runs reference SUCCEEDED training records (candidate_runs.train_run_id is a
    foreign key to candidate_train_runs)."""
    with db.tx() as c:
        c.executemany("INSERT OR IGNORE INTO candidate_train_runs(id, scope_key, model, origin_date, data_as_of, status, "
                      "created_at, finished_at) VALUES (?,?,?,?,?, 'SUCCEEDED', ?, ?)",
                      [(rid, scope, m, str(pipeline.origin_of(d)), str(pipeline.origin_of(d) - timedelta(days=1)),
                        "2026-11-01T00:00:00+00:00", "2026-11-01T00:10:00+00:00")
                       for rid, m in (("CTR-V33", "V33_L112"), ("CTR-MOC", "MOC"))])
    store.write_day(scope, d, d - timedelta(days=1), _cands(v33), {"V33_L112": "CTR-V33", "MOC": "CTR-MOC"},
                    {"V33_L112": ["MODEL_PREV_WEEK"]})


def _folder():
    return paths.data_dir().joinpath(*DAY_FOLDER)


def _summary_rows(wb) -> list:
    return [tuple(r) for r in wb["TOM_TAT"].iter_rows(values_only=True)]


def _audit(action="SEL2_EXPORT_TEMP_WRITTEN") -> list[dict]:
    with db.read() as c:
        return db.rows(c, "SELECT action, entity_type, entity_id, details_json FROM audit_log WHERE action=? "
                          "ORDER BY id", (action,))


def _n_export_runs() -> int:
    with db.read() as c:
        return c.execute("SELECT COUNT(*) FROM export_runs").fetchone()[0]


def _dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day)


@pytest.fixture
def tam(sel2_on):
    """Candidates of D (V33_L112 = V33, flags MODEL_PREV_WEEK, train run CTR-V33) for S1, S2, S3 x F1. AVG_DEMAND of D:
    S1 2.5, S2 4, S4 3. Configured LIGHTGBM (through source_config, history kept): S1, S3, S4; S2 default AVG_DEMAND."""
    _store_candidates()
    _avg(D, [("S1", "F1", "SL1", 2.5, "Thuoc A"), ("S2", "F1", "SL1", 4.0, "Thuoc B"),
             ("S4", "F1", "SL1", 3.0, "Thuoc D")])
    for sku in ("S1", "S3", "S4"):
        source_config.set_one(sku, "F1", "LIGHTGBM", None, confirm=True, changed_by="tester")


# ------------------------------------------------------------------ 1. order of the first start (trainings stubbed)
class _FakeInputs:
    frame = pd.DataFrame({"od": []})
    keys = pd.DataFrame({"sku_code": [], "fc_code": []})

    def groups(self, d, mode="ROLLING_B7", fixed_start=None, fixed_end=None):
        return pd.Series({("S1", "F1"): "A"})


def _stub(monkeypatch, events, temp=True, fail_cand_on=None):
    fake = _FakeInputs()
    monkeypatch.setattr(pipeline, "load", lambda scope_key, d, s=None: events.append(("load", d)) or fake)
    monkeypatch.setattr(pipeline, "train_week", lambda o, models=None, cancel=None, inputs=None, scope_key=None,
                        job_id=None: events.append(("train", o, inputs is fake)) or
                        {"origin": str(o), "trained": list(pipeline.TRAIN_ORDER), "skipped": []})

    def cand(d, inputs=None, scope_key=None, job_id=None, force=False):
        events.append(("cand", d))
        if d == fail_cand_on:
            raise errors.Sel2Error(errors.NO_MODEL, detail="stub")
        return {"forecast_date": str(d), "status": "STORED", "rows": 1}
    monkeypatch.setattr(pipeline, "candidates_for_day", cand)
    # True = run_day(today) reads its own inputs (bootstrap frees its frame before the publication and the export)
    monkeypatch.setattr(pipeline, "run_day", lambda d=None, trigger="manual", job_id=None, scope_key=None, force=False,
                        inputs=None: events.append(("day", d, trigger, inputs is None)) or {"status": "PUBLISHED"})
    if temp:
        monkeypatch.setattr(pipeline, "_temp_export_hook", lambda d, inputs, s, sk, job_id: events.append(("temp", d))
                            or {"ok": True, "result": {"path": "p.xlsx", "n_rows": 7}})
    return fake


def test_bootstrap_trains_today_origin_first_then_temp_then_ascending(sel2_on, monkeypatch):
    """Fails on the former behaviour (all origins ascending, no temporary file)."""
    ev = []
    _stub(monkeypatch, ev)
    r = pipeline.bootstrap(scope_key=SCOPE, today=WED)                                  # default days = 28
    first = WED - timedelta(days=28)
    others = [date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)]
    assert ev == ([("load", WED), ("train", date(2026, 10, 26), True), ("temp", WED)]
                  + [("train", o, True) for o in others]
                  + [("cand", first + timedelta(days=i)) for i in range(28)]
                  + [("day", WED, "bootstrap", True)])
    assert [t["origin"] for t in r["trainings"]] == ["2026-10-26"] + [str(o) for o in others]
    assert r["past_days"] == ["STORED"] * 28 and r["today"] == {"status": "PUBLISHED"}
    assert r["temp_export"] == {"ok": True, "result": {"path": "p.xlsx", "n_rows": 7}, "path": "p.xlsx", "n_rows": 7}
    t = r["timings"]
    assert list(t) == ["temp_export_after_s", "trainings_done_after_s", "past_days_done_after_s", "total_s"]
    assert t["temp_export_after_s"] <= t["trainings_done_after_s"] <= t["past_days_done_after_s"] <= t["total_s"]
    assert inspect.signature(pipeline.bootstrap).parameters["days"].default == 28


def test_bootstrap_today_monday_and_other_retrain_weekday(sel2_on, monkeypatch):
    ev = []
    _stub(monkeypatch, ev)
    pipeline.bootstrap(1, scope_key=SCOPE, today=date(2026, 10, 26))                  # today is the origin itself
    assert [e[1] for e in ev if e[0] == "train"] == [date(2026, 10, 26), date(2026, 10, 19)]
    ss.update("sel2_pipeline", {"retrain_weekday": 4}, note="tests: Thursday origins")
    ev.clear()
    pipeline.bootstrap(7, scope_key=SCOPE, today=WED)                                  # span 10-21 .. 10-28
    assert [e[1] for e in ev if e[0] == "train"] == [date(2026, 10, 22), date(2026, 10, 15)]
    assert ev.index(("temp", WED)) == 2


def test_bootstrap_default_today_is_the_vietnam_day(sel2_on, monkeypatch):
    """2026-10-25 18:00 UTC = Monday 2026-10-26 01:00 in Vietnam: today's origin is 10-26 (the UTC day would give 10-19)."""
    timeutil.set_now_override(lambda: datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc))
    ev = []
    _stub(monkeypatch, ev)
    pipeline.bootstrap(1, scope_key=SCOPE)
    assert ev[0] == ("load", date(2026, 10, 26)) and ev[1] == ("train", date(2026, 10, 26), True)
    assert ev[2] == ("temp", date(2026, 10, 26)) and ev[-1][:3] == ("day", date(2026, 10, 26), "bootstrap")


def test_bootstrap_refused_while_the_pipeline_is_off(monkeypatch):
    ev = []
    _stub(monkeypatch, ev)
    with pytest.raises(errors.Sel2Error) as e:
        pipeline.bootstrap(scope_key=SCOPE, today=WED)
    assert e.value.code == "SEL2_DISABLED" and ev == []


# ------------------------------------------------------------------ 2b. the hook inside the first start
def test_hook_skips_an_already_published_day(sel2_on, monkeypatch):
    ev = []
    _stub(monkeypatch, ev, temp=False)
    _run("RPUB", WED, {("S1", "F1"): ("A", "MOC+DOW4", {h: (1, 1.0) for h in range(1, 8)})}, scope=SCOPE)
    r = pipeline.bootstrap(1, scope_key=SCOPE, today=WED)
    assert r["temp_export"] == {"ok": True, "skipped": "ALREADY_PUBLISHED", "path": None, "n_rows": None}
    assert ("cand", WED) not in ev                                       # the hook computed nothing for today
    assert not (paths.data_dir() / "exports").exists() and _audit() == []


def test_hook_error_never_fails_the_bootstrap(sel2_on, monkeypatch):
    ev = []
    warned = []
    _stub(monkeypatch, ev, temp=False, fail_cand_on=WED)
    monkeypatch.setattr(pipeline.log, "warning", lambda msg, *a, **k: warned.append(msg))
    r = pipeline.bootstrap(1, scope_key=SCOPE, today=WED)
    assert r["temp_export"]["ok"] is False and "SEL2_NO_MODEL" in r["temp_export"]["error"]
    assert r["temp_export"]["path"] is None and r["today"] == {"status": "PUBLISHED"}
    assert ev[-1] == ("day", WED, "bootstrap", True)
    assert warned == ["sel2 temporary export failed"]


def test_hook_without_a_stored_candidate_reports_missing_forecast(sel2_on, monkeypatch):
    """candidates_for_day stubbed (stores nothing): the real write_temp_export finds no V33_L112 candidate."""
    ev = []
    _stub(monkeypatch, ev, temp=False)
    r = pipeline.bootstrap(1, scope_key=SCOPE, today=WED)
    assert r["temp_export"]["ok"] is False and "SEL2_MISSING_FORECAST" in r["temp_export"]["error"]
    assert ev[-1][0] == "day" and _audit() == []


def test_hook_write_error_is_reported_and_the_run_continues(sel2_on, monkeypatch):
    ev = []
    _stub(monkeypatch, ev, temp=False)

    def boom(*a, **k):
        raise AppError("SEL2_EXPORT_WRITE_FAILED", 500, detail="PermissionError: locked")
    monkeypatch.setattr(export, "write_temp_export", boom)
    r = pipeline.bootstrap(1, scope_key=SCOPE, today=WED)
    assert r["temp_export"] == {"ok": False, "error": "AppError: SEL2_EXPORT_WRITE_FAILED: PermissionError: locked",
                                "path": None, "n_rows": None}
    assert ev[-1] == ("day", WED, "bootstrap", True)


def test_hook_passes_the_groups_of_today(sel2_on, monkeypatch):
    seen = {}
    ev = []
    _stub(monkeypatch, ev, temp=False)
    monkeypatch.setattr(export, "write_temp_export", lambda d, groups=None, job_id=None, scope_key=None:
                        seen.update(d=d, groups=groups, job_id=job_id, scope_key=scope_key) or {"path": "x", "n_rows": 3})
    r = pipeline.bootstrap(1, scope_key=SCOPE, today=WED, job_id="J-B6")
    assert seen == {"d": WED, "groups": {("S1", "F1"): "A"}, "job_id": "J-B6", "scope_key": SCOPE}
    assert r["temp_export"]["ok"] is True and r["temp_export"]["candidates"] == "STORED"
    assert (r["temp_export"]["path"], r["temp_export"]["n_rows"]) == ("x", 3)


# ------------------------------------------------------------------ 2. the temporary file
def test_temp_file_name_location_rows_and_values(tam):
    res = export.write_temp_export(D, groups=GROUPS, job_id="J1", scope_key=SCOPE)
    assert res["path"] == TAM_REL and export.temp_file_name(D) == "du_bao_20261102_TAM.xlsx"
    assert (res["n_rows"], res["trigger"], res["model_used"], res["temporary"]) == (80, "BOOTSTRAP_TEMP", "V33_L112", True)
    wb = load_workbook(paths.data_dir() / res["path"])
    assert wb.sheetnames == ["DU_BAO_F1", "TOM_TAT", "CONFIG"]
    rows = _main_rows(wb)
    assert len(rows) == 28 and [r["sku_code"] for r in rows[::7]] == ["S1", "S2", "S3", "S4"]
    by = _by(rows)
    for k, vals in V33.items():
        exp = published_qty(vals, select.THRESHOLD).tolist()
        assert [by[(*k, h)]["lightgbm_forecast"] for h in range(1, 8)] == exp
        assert [by[(*k, h)]["raw_value"] for h in range(1, 8)] == pytest.approx(vals)
        assert {by[(*k, h)]["model_used"] for h in range(1, 8)} == {"V33_L112"}
    # 0 below 0.2, else rounded up (values rounded to 6 decimals first)
    assert [by[("S1", "F1", h)]["forecast_used"] for h in range(1, 8)] == [0, 0, 1, 1, 2, 3, 3]
    assert by[("S3", "F1", 1)]["forecast_used"] == 1
    s1 = by[("S1", "F1", 2)]
    assert (s1["forecast_source"], s1["avg_demand"], s1["fallback_reason"], s1["nhom"], s1["ten_san_pham"]) == \
        ("LIGHTGBM", 2.5, None, "A", "Thuoc A")
    assert (s1["model_version"], s1["data_cutoff_date"], s1["is_stale"], s1["flags"]) == \
        ("TAM V33_L112=CTR-V33", _dt(D - timedelta(days=1)), 0, "MODEL_PREV_WEEK")
    assert s1["forecast_date"] == _dt(D) and s1["target_date"] == _dt(D + timedelta(days=1))
    # AVG_DEMAND configured: AVG value used, the candidate number still shown
    s2 = by[("S2", "F1", 1)]
    assert (s2["forecast_source"], s2["lightgbm_forecast"], s2["forecast_used"], s2["fallback_reason"], s2["nhom"]) == \
        ("AVG_DEMAND", 6, 4.0, None, "B")
    # group NaN -> empty; no AVG row -> flag, never 0
    s3 = by[("S3", "F1", 3)]
    assert (s3["nhom"], s3["avg_demand"], s3["forecast_used"]) == (None, None, 7) and "AVG_NO_ROW" in s3["flags"]
    # LIGHTGBM without a candidate (outside the scope) -> 0 + NGOAI_PHAM_VI_GAN_0, any prefix (owner rule 05/11/2026)
    s4 = by[("S4", "F1", 1)]
    assert (s4["lightgbm_forecast"], s4["avg_demand"], s4["forecast_used"], s4["fallback_reason"], s4["model_used"],
            s4["nhom"]) == (None, 3.0, 0, "NGOAI_PHAM_VI_GAN_0", None, None)
    assert res["sku_fc"] == {"total": 4, "in_forecast_scope": 3, "configured_lightgbm": 3,
                             "configured_lightgbm_not_in_file": 0}


def test_temp_summary_note_trigger_and_config(tam):
    res = export.write_temp_export(D, groups=GROUPS, scope_key=SCOPE)
    wb = load_workbook(paths.data_dir() / res["path"])
    rows = _summary_rows(wb)
    assert rows[0] == ("muc", "gia_tri") and rows[1] == ("ghi_chu", NOTE) and rows[2] == ("trigger", "BOOTSTRAP_TEMP")
    assert export.TEMP_NOTE == NOTE and [r[0] for r in rows].count("trigger") == 1
    s = {r[0]: r[1] for r in rows[1:]}
    assert (s["export_version"], s["is_stale"], s["refresh_run_id"], s["run_forecast_date"]) == ("TAM", 0, None, "2026-11-02")
    assert (s["model_version"], s["data_cutoff_date"], s["rows_total"]) == ("TAM V33_L112=CTR-V33", "2026-11-01", 28)
    assert s["sku_fc_model_used:V33_L112"] == 3 and s["rows_fallback_reason:NGOAI_PHAM_VI_GAN_0"] == 7
    assert "rows_fallback_reason:KHONG_CO_DU_LIEU_DEMAND" not in s
    assert s["avg_source_kind"] == "CURRENT" and s.get("file_flags") is None
    cfg = list(wb["CONFIG"].iter_rows(values_only=True))
    assert [r[:2] for r in cfg[1:]] == [("S1", "F1"), ("S3", "F1"), ("S4", "F1")]


def test_temp_is_not_recorded_never_a_version_nor_the_latest_copy_and_audited(tam):
    """The official export of the same day first (v1 + latest copy), then the temporary file: v1, the latest copy and
    export_runs are untouched; AVG_DEMAND rows are identical to the official file."""
    full = {h: (9, 8.6) for h in range(1, 8)}
    _run("R1", D, {k: (GROUPS[k] if isinstance(GROUPS[k], str) else None, "MOC+DOW4", full) for k in V33},
         scope=SCOPE)
    off = export.write_daily_export(D, scope_key=SCOPE)
    folder = _folder()
    v1, latest = folder / "du_bao_20261102_v1.xlsx", folder / "du_bao_20261102.xlsx"
    before = (v1.read_bytes(), latest.read_bytes())
    res = export.write_temp_export(D, groups={k: v for k, v in GROUPS.items() if isinstance(v, str)}, job_id="J7",
                                   scope_key=SCOPE)
    assert (v1.read_bytes(), latest.read_bytes()) == before
    assert sorted(p.name for p in folder.iterdir()) == ["du_bao_20261102.xlsx", "du_bao_20261102_TAM.xlsx",
                                                        "du_bao_20261102_v1.xlsx"]
    with db.read() as c:
        recs = db.rows(c, "SELECT version, path, trigger FROM export_runs")
    assert recs == [{"version": 1, "path": off["path"], "trigger": "SCHEDULE"}]
    assert [r["version"] for r in export.runs(D)] == [1] and export.latest_file(D)[0] == v1.resolve()
    a = _audit()
    assert len(a) == 1 and (a[0]["entity_type"], a[0]["entity_id"]) == ("export_file", TAM_REL)
    det = json.loads(a[0]["details_json"])
    assert det == {"forecast_date": "2026-11-02", "rows": 80, "sha256": res["sha256"], "model": "V33_L112",
                   "trigger": "BOOTSTRAP_TEMP", "job_id": "J7"}
    assert len(_audit("SEL2_EXPORT_WRITTEN")) == 1                       # the official version only
    # AVG_DEMAND rows (configured AVG_DEMAND or fallen back to AVG) identical to the official file of the same day
    cols = ["sku_code", "ten_san_pham", "fc_code", "nhom", "forecast_date", "target_date", "horizon", "avg_demand",
            "forecast_source", "forecast_used", "fallback_reason"]
    o_rows = _main_rows(load_workbook(paths.data_dir() / off["path"]))
    t_rows = _main_rows(load_workbook(paths.data_dir() / res["path"]))
    assert [(r["sku_code"], r["fc_code"], r["horizon"]) for r in o_rows] == \
        [(r["sku_code"], r["fc_code"], r["horizon"]) for r in t_rows]
    o_avg = [[r[c] for c in cols] for r in o_rows if r["forecast_source"] != "LIGHTGBM" or r["fallback_reason"]]
    t_avg = [[r[c] for c in cols] for r in t_rows if r["forecast_source"] != "LIGHTGBM" or r["fallback_reason"]]
    assert len(o_avg) == 14 and o_avg == t_avg                           # S2 (AVG_DEMAND) + S4 (NGOAI_PHAM_VI_GAN_0)
    assert set(COLS) >= set(cols)


def test_temp_rerun_overwrites_the_same_file(tam):
    r1 = export.write_temp_export(D, groups=GROUPS, scope_key=SCOPE)
    p = paths.data_dir() / r1["path"]
    first = p.read_bytes()
    _store_candidates(v33={**V33, ("S1", "F1"): [4.0] * 7})
    r2 = export.write_temp_export(D, groups=GROUPS, scope_key=SCOPE)
    assert r2["path"] == r1["path"] and r2["sha256"] != r1["sha256"] and p.read_bytes() != first
    by = _by(_main_rows(load_workbook(p)))
    assert by[("S1", "F1", 1)]["forecast_used"] == 4
    assert [x.name for x in _folder().iterdir()] == ["du_bao_20261102_TAM.xlsx"]      # no vN, no latest, no .tmp
    assert _n_export_runs() == 0 and len(_audit()) == 2


@pytest.mark.skipif(os.name != "nt", reason="an open file blocks os.replace on Windows only")
def test_temp_locked_file_fails_and_keeps_the_old_file(tam):
    r1 = export.write_temp_export(D, groups=GROUPS, scope_key=SCOPE)
    p = paths.data_dir() / r1["path"]
    first = p.read_bytes()
    _store_candidates(v33={**V33, ("S1", "F1"): [4.0] * 7})
    with open(p, "rb"):                                                  # open in Excel
        with pytest.raises(AppError) as e:
            export.write_temp_export(D, groups=GROUPS, scope_key=SCOPE)
    assert e.value.code == "SEL2_EXPORT_WRITE_FAILED"
    assert p.read_bytes() == first and [x.name for x in _folder().iterdir()] == ["du_bao_20261102_TAM.xlsx"]
    assert len(_audit()) == 1 and _n_export_runs() == 0


@pytest.mark.parametrize("case", ["none", "other_models_only", "earlier_day_only", "other_scope"])
def test_temp_without_a_v33_candidate_of_the_day_is_missing_forecast(sel2_on, case):
    if case == "other_models_only":
        store.write_day(SCOPE, D, D - timedelta(days=1), {m: f for m, f in _cands(V33).items() if m != "V33_L112"},
                        {}, {})
    elif case == "earlier_day_only":
        _store_candidates(d=D - timedelta(days=1))
    elif case == "other_scope":
        _store_candidates(scope="OTHER-SCOPE")
    _avg(D, [("S1", "F1", "SL1", 2.5, None)])
    with pytest.raises(AppError) as e:
        export.write_temp_export(D, groups=GROUPS, scope_key=SCOPE)
    assert e.value.code == "SEL2_MISSING_FORECAST"
    assert not _folder().joinpath("du_bao_20261102_TAM.xlsx").exists() and _audit() == []


def test_temp_refused_while_the_pipeline_is_off():
    _store_candidates()
    with pytest.raises(AppError) as e:
        export.write_temp_export(D, scope_key=SCOPE)
    assert e.value.code == "SEL2_PIPELINE_DISABLED" and not (paths.data_dir() / "exports").exists()


# ------------------------------------------------------------------ 3. data-check with a _TAM file
def test_data_check_stays_ok_with_a_temp_file(tam):
    _run("R1", D, {k: ("A", "MOC+DOW4", {h: (1, 1.0) for h in range(1, 8)}) for k in V33}, scope=SCOPE)
    export.write_daily_export(D, scope_key=SCOPE)
    export.write_temp_export(D, groups=GROUPS, scope_key=SCOPE)
    (_folder() / "du_bao_20261103_TAM.xlsx").write_bytes(b"stray temporary file")     # any _TAM file, no record
    res = data_checks.run(paths.db_path(), paths.models_dir())
    chk = {x["check"]: x for x in res["checks"]}
    assert {k: chk[k]["status"] for k in SEL2_CHECKS} == dict.fromkeys(SEL2_CHECKS, "OK"), [chk[k] for k in SEL2_CHECKS]
    assert "skipped" not in chk["export_files_exist"]["rule"]


# ------------------------------------------------------------------ 4. CLI
def test_cli_bootstrap_days_default_28_and_range(sel2_on, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(pipeline, "bootstrap", lambda days=28, **k: calls.append((days, k)) or {"ok": 1})
    assert cli.main(["sel2-bootstrap"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["args"] == {"days": 28} and out["dry_run"] is True and out["code"] == "SEL2_CONFIRM_REQUIRED"
    assert not calls
    assert cli.main(["sel2-bootstrap", "--yes"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert calls == [(28, {})] and out["ok"] is True and out["args"] == {"days": 28}
    for days, rc in (("1", 0), ("120", 0), ("0", 2), ("121", 2), ("-3", 2)):
        assert cli.main(["sel2-bootstrap", "--days", days]) == rc, days
        capsys.readouterr()
    assert len(calls) == 1                                              # plans and refusals run nothing


# ------------------------------------------------------------------ 1 + 2 + 3 end to end (LightGBM trained for real)
def _model_shas(scope: str) -> dict:
    with db.read() as c:
        rows = c.execute("SELECT model, origin_date, model_files_json FROM candidate_train_runs WHERE scope_key=? AND "
                         "status='SUCCEEDED'", (scope,)).fetchall()
    return {(m, o): {p: f["sha256"] for p, f in json.loads(j).items()} for m, o, j in rows}


def test_bootstrap_end_to_end_models_identical_to_ascending_training(sel2_on, monkeypatch):
    """Today = Monday 2026-10-26, days = 1: origins 10-26 (today, trained first) and 10-19 (for 10-25). Every model file
    equals the one of an ascending training (10-19 then 10-26) of the same inputs in another scope, and V33_L112 of
    10-19 equals the training with inputs that end at 10-18 (a training reads only rows before its origin)."""
    monkeypatch.setattr(pipeline, "MIN_COMMIT_MB", 0)
    _plenty_of_memory(monkeypatch)
    _seed()
    source_config.set_one("S01", "FC1", "LIGHTGBM", None, confirm=True, changed_by="tester")
    today, prev = date(2026, 10, 26), date(2026, 10, 19)
    order = []
    real_train = pipeline.train_week
    monkeypatch.setattr(pipeline, "train_week", lambda o, **k: order.append(o) or real_train(o, **k))
    r = pipeline.bootstrap(1, scope_key=SEED_SCOPE, today=today)
    assert order == [today, prev]
    assert [t["trained"] for t in r["trainings"]] == [list(pipeline.TRAIN_ORDER)] * 2
    assert r["past_days"] == ["STORED"] and r["today"]["status"] == "PUBLISHED"
    assert r["today"]["candidates"]["status"] == "SKIPPED_DONE"          # stored by the temporary file's step
    assert r["today"]["export"]["ok"] is True
    # temporary file = published_qty of today's stored V33_L112 candidate
    te = r["temp_export"]
    assert te["ok"] is True and te["candidates"] == "STORED" and te["path"].endswith("20261026/du_bao_20261026_TAM.xlsx")
    assert te["n_rows"] == 10 * 20
    with db.read() as c:
        cand = {(s, f, h): v for s, f, h, v in c.execute(
            "SELECT sku_code, fc_code, horizon, value FROM candidate_forecasts WHERE forecast_date=? AND model='V33_L112'",
            (str(today),))}
        n_tr = c.execute("SELECT COUNT(*) FROM candidate_train_runs").fetchone()[0]
        recs = db.rows(c, "SELECT version, trigger FROM export_runs")
    rows = _main_rows(load_workbook(paths.data_dir() / te["path"]))
    assert len(rows) == 70 and len(cand) == 70
    keys = sorted(cand)
    exp = dict(zip(keys, published_qty([cand[k] for k in keys], select.THRESHOLD).tolist()))
    assert {(x["sku_code"], x["fc_code"], x["horizon"]): x["lightgbm_forecast"] for x in rows} == exp
    assert all(x["model_used"] == "V33_L112" for x in rows)
    s01 = [x for x in rows if x["sku_code"] == "S01"]
    assert [x["forecast_used"] for x in s01] == [exp[("S01", "FC1", h)] for h in range(1, 8)]
    assert n_tr == 6 and recs == [{"version": 1, "trigger": "bootstrap"}]
    assert sorted(p.name for p in (paths.data_dir() / "exports" / "du_bao" / "20261026").iterdir()) == \
        ["du_bao_20261026.xlsx", "du_bao_20261026_TAM.xlsx", "du_bao_20261026_v1.xlsx"]
    chk = {x["check"]: x for x in data_checks.run(paths.db_path(), paths.models_dir())["checks"]}
    assert {k: chk[k]["status"] for k in SEL2_CHECKS} == dict.fromkeys(SEL2_CHECKS, "OK")
    # the same trainings in ascending order (another scope = other model folder and records)
    inputs = pipeline.load(SEED_SCOPE, today)
    for o in (prev, today):
        assert real_train(o, inputs=inputs, scope_key="ASC-B6")["trained"] == list(pipeline.TRAIN_ORDER)
    boot, asc = _model_shas(SEED_SCOPE), _model_shas("ASC-B6")
    assert len(boot) == 6 and boot == asc
    # V33_L112 of 10-19 trained with inputs read up to 10-18 only: same model
    early = pipeline.load(SEED_SCOPE, prev)
    real_train(prev, models=("V33_L112",), inputs=early, scope_key="EARLY-B6")
    assert _model_shas("EARLY-B6") == {("V33_L112", str(prev)): boot[("V33_L112", str(prev))]}
