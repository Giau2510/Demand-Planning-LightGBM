"""1.4.0 (T1): settings section "sel2_pipeline" and the additive migration 0012 of the per-SKU model selection SEL2,
written BEFORE the code (test-first).

The new pipeline is ON by default; sel2_pipeline.enabled = False is the emergency return to the exact 1.3.1 behaviour
(conftest keeps every older test in that mode; the opt-in fixture sel2_on switches it on). Synthetic data only, on the
temporary test database; no BigQuery, no network.
"""
import json
import sqlite3
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app import db, paths, timeutil
from app import settings_service as ss

NEW_TABLES = ("candidate_train_runs", "candidate_runs", "candidate_forecasts", "forecast_source_config",
              "forecast_source_config_history", "avg_demand_daily", "avg_demand_reads", "export_runs")
OLD_TABLES = ("demand_daily", "forecast_runs", "forecast_values", "training_runs", "job_runs", "open_hours_daily",
              "forecast_refresh_runs", "app_settings", "audit_log")
TS = "2026-11-01T00:00:00+00:00"


# ================================================================== A. settings section
def test_defaults_and_section():
    s = ss.Sel2PipelineSettings()
    assert s.enabled is True                                              # 1.4.0: the new pipeline is ON by default
    assert (s.p_threshold, s.window_days, s.min_days, s.fallback_model) == (0.6, 28, 14, "V33_L112")
    assert (s.group_mode, s.group_fixed_start, s.group_fixed_end) == ("ROLLING_B7", None, None)
    assert (s.retention_days, s.export_subdir) == (120, "exports\\du_bao")
    assert (s.export_deadline, s.prev_week_deadline, s.retrain_weekday) == ("06:30", "06:20", 1)
    assert (s.open_hours_lag_days, s.open_hours_history_start) == (2, "2026-01-01")
    assert (s.tsb_alpha, s.tsb_beta, s.tsb_start) == (0.1, 0.1, "2026-01-01")
    assert s.avg_demand_table == "lakehouse-prod-394907.gold_buymed_vn2.fact_avg_demand_sku"
    assert s.avg_demand_hist_table == "lakehouse-prod-394907.gold_buymed_vn2.fact_avg_demand_sku_historical"
    assert s.avg_seller_rule == "PENDING"                                 # the owner has not approved a rule yet
    assert ss.SECTIONS["sel2_pipeline"] is ss.Sel2PipelineSettings
    assert ss.CANDIDATE_MODELS == ("MOC", "V33_L112", "V36_two_stage@0.6", "TSB", "DOW4", "AVG7")


def test_older_tests_run_in_131_mode_and_sel2_on_opts_in():
    assert ss.get("sel2_pipeline").enabled is False                        # conftest: emergency switch = 1.3.1


def test_sel2_on_fixture(sel2_on):
    assert ss.get("sel2_pipeline").enabled is True


def test_valid_variants():
    s = ss.Sel2PipelineSettings(group_mode="FIXED", group_fixed_start="2026-09-01", group_fixed_end="2026-09-01",
                                avg_seller_rule="SELLER:MEDX", export_subdir="exports/du_bao", open_hours_lag_days=0,
                                fallback_model="AVG7", retention_days=35)
    assert (s.group_fixed_start, s.group_fixed_end, s.avg_seller_rule) == ("2026-09-01", "2026-09-01", "SELLER:MEDX")
    for rule in ("SUM", "MAX", "PENDING", "SELLER:MEDX_2-B"):
        assert ss.Sel2PipelineSettings(avg_seller_rule=rule).avg_seller_rule == rule
    for m in ss.CANDIDATE_MODELS:
        assert ss.Sel2PipelineSettings(fallback_model=m).fallback_model == m


@pytest.mark.parametrize("patch", [
    {"p_threshold": -0.01}, {"p_threshold": 1.01}, {"p_threshold": 0.5}, {"p_threshold": 0},   # fixed at 0.6
    {"window_days": 0}, {"min_days": 0}, {"min_days": 29},                                # min_days <= window_days
    {"window_days": 10, "min_days": 14},
    {"fallback_model": "LGBM"}, {"fallback_model": "V36_two_stage"}, {"fallback_model": ""},
    {"group_mode": "ROLLING"},
    {"group_mode": "FIXED"},                                                             # dates required
    {"group_mode": "FIXED", "group_fixed_start": "2026-09-01"},
    {"group_mode": "FIXED", "group_fixed_end": "2026-09-01"},
    {"group_mode": "FIXED", "group_fixed_start": "2026-13-01", "group_fixed_end": "2026-12-01"},
    {"group_mode": "FIXED", "group_fixed_start": "2026/09/01", "group_fixed_end": "2026-09-30"},
    {"group_mode": "FIXED", "group_fixed_start": "2026-09-30", "group_fixed_end": "2026-09-01"},   # start <= end
    {"group_fixed_start": "not-a-date"},
    {"retention_days": 34},
    {"window_days": 30, "retention_days": 36},                                # >= window + 7
    {"export_subdir": ""}, {"export_subdir": "..\\x"}, {"export_subdir": "exports\\..\\..\\x"},
    {"export_subdir": "a/../b"}, {"export_subdir": "C:\\x"}, {"export_subdir": "C:x"}, {"export_subdir": "\\x"},
    {"export_subdir": "/x"}, {"export_subdir": "\\\\server\\share"}, {"export_subdir": "a\\\\b"},
    {"export_subdir": "a:b"}, {"export_subdir": "a*b"},
    {"export_deadline": "6:30"}, {"export_deadline": "24:00"}, {"prev_week_deadline": "06:60"},
    {"prev_week_deadline": "06:30"},                                                     # must be before export_deadline
    {"prev_week_deadline": "07:00"},
    {"retrain_weekday": 0}, {"retrain_weekday": 8},
    {"open_hours_lag_days": -1}, {"open_hours_lag_days": 3},
    {"open_hours_history_start": "2026/01/01"}, {"open_hours_history_start": "2026-02-30"},
    {"open_hours_history_start": ""},
    {"tsb_alpha": 0}, {"tsb_alpha": 1.5}, {"tsb_beta": 0}, {"tsb_beta": -0.1},
    {"tsb_start": "01-01-2026"},
    {"avg_demand_table": "gold_buymed_vn2.fact_avg_demand_sku"}, {"avg_demand_table": ""},
    {"avg_demand_hist_table": "lakehouse-prod-394907.gold buymed.t"},
    {"avg_seller_rule": "AVG"}, {"avg_seller_rule": "sum"}, {"avg_seller_rule": "SELLER:"},
    {"avg_seller_rule": "SELLER:ME DX"}, {"avg_seller_rule": ""},
])
def test_validation_errors(patch):
    with pytest.raises(ValidationError):
        ss.Sel2PipelineSettings(**patch)
    before = ss.get("sel2_pipeline").model_dump()
    with pytest.raises(ValidationError):                                  # refused by save: nothing is stored
        ss.update("sel2_pipeline", patch, note="test")
    assert ss.get("sel2_pipeline").model_dump() == before


def test_save_round_trip_and_history():
    ss.update("sel2_pipeline", {"window_days": 21, "avg_seller_rule": "SUM"}, note="t1")
    g = ss.get("sel2_pipeline")
    assert (g.window_days, g.avg_seller_rule, g.enabled) == (21, "SUM", False)
    assert ss.history("sel2_pipeline")[0]["value"]["window_days"] == 21


def _audit_saves() -> list[dict]:
    with db.read() as c:
        return db.rows(c, "SELECT id, details_json FROM audit_log WHERE action='SETTINGS_SAVED' AND "
                          "entity_type='settings' AND entity_id='sel2_pipeline' ORDER BY id DESC")


def test_each_save_writes_one_history_row_and_one_audit_row_newest_first():
    hist0, audit0 = ss.history("sel2_pipeline"), _audit_saves()
    ss.update("sel2_pipeline", {"window_days": 21, "min_days": 7}, note="t1-a")
    ss.update("sel2_pipeline", {"retrain_weekday": 3}, note="t1-b")
    hist, audit = ss.history("sel2_pipeline"), _audit_saves()
    assert len(hist) == len(hist0) + 2 and len(audit) == len(audit0) + 2
    assert [h["note"] for h in hist[:2]] == ["t1-b", "t1-a"]               # newest first (id DESC, same second)
    assert hist[0]["id"] > hist[1]["id"]
    # each history row is the FULL section as saved (not only the patch); the earlier value is kept unchanged
    assert hist[1]["value"] == ss.Sel2PipelineSettings(enabled=False, window_days=21, min_days=7).model_dump()
    assert hist[0]["value"] == {**hist[1]["value"], "retrain_weekday": 3}
    assert hist[0]["value"] == ss.get("sel2_pipeline").model_dump()
    assert [json.loads(a["details_json"]) for a in audit[:2]] == [{"note": "t1-b"}, {"note": "t1-a"}]
    assert timeutil.parse_iso(hist[0]["changed_at"]).utcoffset() == timedelta(0)     # stored in UTC


def test_a_refused_save_writes_no_history_and_no_audit_row():
    hist0, audit0 = ss.history("sel2_pipeline"), _audit_saves()
    with pytest.raises(ValidationError):
        ss.update("sel2_pipeline", {"window_days": 10, "min_days": 14}, note="refused")
    assert ss.history("sel2_pipeline") == hist0 and _audit_saves() == audit0


def test_conftest_switch_is_stored_and_recorded_for_older_tests():
    # autouse sel2_off: the stored section has enabled = False, written through the normal save path (history kept)
    with db.read() as c:
        raw = c.execute("SELECT value_json FROM app_settings WHERE section='sel2_pipeline'").fetchone()[0]
    assert json.loads(raw)["enabled"] is False
    hist = ss.history("sel2_pipeline")
    assert [(h["note"], h["value"]["enabled"]) for h in hist] == [("tests: 1.3.1 mode", False)]
    # everything else is the 1.4.0 default: the switch changes only `enabled`
    assert {k: v for k, v in hist[0]["value"].items() if k != "enabled"} == \
           {k: v for k, v in ss.Sel2PipelineSettings().model_dump().items() if k != "enabled"}


def test_sel2_on_fixture_is_recorded_after_the_off_switch(sel2_on):
    assert isinstance(sel2_on, ss.Sel2PipelineSettings) and sel2_on.enabled is True
    hist = ss.history("sel2_pipeline")
    assert [(h["note"], h["value"]["enabled"]) for h in hist] == [("tests: 1.4.0 pipeline on", True),
                                                                   ("tests: 1.3.1 mode", False)]


def test_fresh_install_without_a_stored_section_reads_the_pipeline_on(tmp_path):
    # a fresh database (the conftest switch is not applied to it): migrations write no setting, get() = the default
    fresh = tmp_path / "fresh.db"
    res = db.migrate(fresh)
    assert res["from"] == 0 and res["to"] == 13 and res["applied"][-2:] == ["0012_sel2_pipeline.sql",   # 1.4.8: + 0013
                                                                         "0013_spike_lines.sql"]
    c = sqlite3.connect(fresh)
    try:
        assert c.execute("SELECT COUNT(*) FROM app_settings WHERE section='sel2_pipeline'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM settings_history WHERE section='sel2_pipeline'").fetchone()[0] == 0
        s = ss.get("sel2_pipeline", conn=c)
    finally:
        c.close()
    assert s.enabled is True and s == ss.Sel2PipelineSettings()


def test_reset_restores_the_default_pipeline_on_with_history():
    ss.update("sel2_pipeline", {"min_days": 10}, note="t1")
    ss.reset("sel2_pipeline")
    g = ss.get("sel2_pipeline")
    assert g.enabled is True and g == ss.Sel2PipelineSettings()
    h = ss.history("sel2_pipeline")[0]
    assert h["note"] == "reset to defaults" and h["value"] == ss.Sel2PipelineSettings().model_dump()


# ================================================================== B. migration 0012
def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(paths.db_path()), isolation_level=None)
    c.execute("PRAGMA foreign_keys = ON")
    return c


def _refused(c, sql, params=(), match=None):
    with pytest.raises((sqlite3.IntegrityError, sqlite3.DatabaseError), match=match):
        c.execute(sql, params)


def test_migration_creates_the_tables_and_writes_nothing():
    c = _conn()
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(NEW_TABLES) <= tables
    assert c.execute("SELECT name FROM schema_migrations WHERE version = 12").fetchone()[0] == "0012_sel2_pipeline.sql"
    for t in NEW_TABLES:
        assert c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
    sql = c.execute("SELECT sql FROM sqlite_master WHERE name='candidate_forecasts'").fetchone()[0]
    assert "WITHOUT ROWID" in sql.upper()                                 # narrow row, PK = the table
    pk = [r[1] for r in sorted(c.execute("PRAGMA table_info(candidate_forecasts)"), key=lambda r: r[5]) if r[5]]
    assert pk == ["forecast_date", "sku_code", "fc_code", "model", "horizon"]
    idx = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_ctr_model_origin", "idx_cr_date_model"} <= idx
    c.close()


def test_migrating_twice_is_idempotent():
    again = db.migrate()
    assert again["applied"] == [] and again["to"] == 13                  # 1.4.8: + 0013


def test_candidate_train_runs_and_runs_constraints():
    c = _conn()
    ins_t = ("INSERT INTO candidate_train_runs(id, scope_key, model, origin_date, status, created_at) "
             "VALUES (?,?,?,?,?,?)")
    for m in ("MOC", "V33_L112", "V36_two_stage"):
        c.execute(ins_t, (f"T-{m}", "BIGQUERY:p.d.t", m, "2026-11-01", "SUCCEEDED", TS))
    _refused(c, ins_t, ("T-x", "S", "TSB", "2026-11-01", "RUNNING", TS), "CHECK")        # not a LightGBM training
    _refused(c, ins_t, ("T-y", "S", "V36_two_stage@0.6", "2026-11-01", "RUNNING", TS), "CHECK")
    _refused(c, ins_t, ("T-z", "S", "MOC", "2026-11-01", "DONE", TS), "CHECK")
    _refused(c, ins_t, ("T-MOC", "S", "MOC", "2026-11-01", "RUNNING", TS), "UNIQUE")
    _refused(c, ins_t, ("T-n", "S", "MOC", None, "RUNNING", TS), "NOT NULL")
    ins_r = ("INSERT INTO candidate_runs(id, scope_key, forecast_date, model, train_run_id, status, created_at, "
             "data_as_of) VALUES (?,?,?,?,?,?,?, '2026-11-01')")
    _refused(c, "INSERT INTO candidate_runs(id, scope_key, forecast_date, model, status, created_at) "
                "VALUES ('R-n', 'S', '2026-11-02', 'TSB', 'SUCCEEDED', ?)", (TS,), "NOT NULL")    # data_as_of
    for m in ss.CANDIDATE_MODELS:
        c.execute(ins_r, (f"R-{m}", "BIGQUERY:p.d.t", "2026-11-02", m, "T-MOC" if m == "MOC" else None, "SUCCEEDED",
                          TS))
    _refused(c, ins_r, ("R-x", "S", "2026-11-02", "V36_two_stage", None, "SUCCEEDED", TS), "CHECK")
    _refused(c, ins_r, ("R-y", "S", "2026-11-02", "MOC", None, "RUNNING", TS), "CHECK")
    _refused(c, ins_r, ("R-z", "S", "2026-11-02", "MOC", "NO-SUCH-TRAIN", "SUCCEEDED", TS), "FOREIGN KEY")
    c.close()


def test_candidate_forecasts_constraints():
    c = _conn()
    assert "run_id" not in [r[1] for r in c.execute("PRAGMA table_info(candidate_forecasts)")]
    ins = ("INSERT INTO candidate_forecasts(forecast_date, sku_code, fc_code, model, horizon, target_date, value) "
           "VALUES (?,?,?,?,?,?,?)")
    for h in range(1, 8):
        c.execute(ins, ("2026-11-02", "SKU1", "FC1", "TSB", h, f"2026-11-{1 + h:02d}", 0.0))
    _refused(c, ins, ("2026-11-02", "SKU1", "FC1", "TSB", 1, "2026-11-02", 1.0), "UNIQUE")
    _refused(c, ins, ("2026-11-02", "SKU1", "FC1", "TSB", 0, "2026-11-01", 1.0), "CHECK")
    _refused(c, ins, ("2026-11-02", "SKU1", "FC1", "TSB", 8, "2026-11-09", 1.0), "CHECK")
    _refused(c, ins, ("2026-11-02", "SKU2", "FC1", "TSB", 1, "2026-11-02", -0.5), "CHECK")
    _refused(c, ins, ("2026-11-02", "SKU2", "FC1", "TSB", 1, "2026-11-02", None), "NOT NULL")   # never 0
    _refused(c, ins, ("2026-11-02", "SKU2", "FC1", "LGBM", 1, "2026-11-02", 1.0), "CHECK")
    assert c.execute("SELECT COUNT(*) FROM candidate_forecasts").fetchone()[0] == 7
    c.close()


def test_forecast_source_config_and_append_only_history():
    c = _conn()
    ins = ("INSERT INTO forecast_source_config(sku_code, fc_code, forecast_source, ghi_chu, updated_by, updated_at) "
           "VALUES (?,?,?,?,?,?)")
    c.execute(ins, ("SKU1", "FC1", "LIGHTGBM", "ok", "owner", TS))
    _refused(c, ins, ("SKU1", "FC1", "AVG_DEMAND", None, "owner", TS), "UNIQUE")
    _refused(c, ins, ("SKU2", "FC1", "SEL2", None, "owner", TS), "CHECK")
    _refused(c, ins, ("SKU2", "FC1", "LIGHTGBM", None, None, TS), "NOT NULL")
    c.execute("UPDATE forecast_source_config SET forecast_source='AVG_DEMAND' WHERE sku_code='SKU1'")   # current state
    hist = ("INSERT INTO forecast_source_config_history(sku_code, fc_code, old_source, new_source, ghi_chu, changed_by, "
            "changed_at, channel, batch_id) VALUES (?,?,?,?,?,?,?,?,?)")
    c.execute(hist, ("SKU1", "FC1", None, "LIGHTGBM", None, "owner", TS, "UI", None))
    c.execute(hist, ("SKU1", "FC1", "LIGHTGBM", "AVG_DEMAND", "x", "owner", TS, "UPLOAD", "B1"))
    _refused(c, hist, ("SKU1", "FC1", "LIGHTGBM", "OTHER", None, "owner", TS, "UI", None), "CHECK")
    _refused(c, hist, ("SKU1", "FC1", "OTHER", "LIGHTGBM", None, "owner", TS, "UI", None), "CHECK")
    _refused(c, hist, ("SKU1", "FC1", None, "LIGHTGBM", None, "owner", TS, "EMAIL", None), "CHECK")
    _refused(c, "UPDATE forecast_source_config_history SET ghi_chu='y'", match="append-only")
    _refused(c, "DELETE FROM forecast_source_config_history", match="append-only")
    assert c.execute("SELECT COUNT(*) FROM forecast_source_config_history").fetchone()[0] == 2
    c.close()


def test_avg_demand_daily_and_export_runs_constraints():
    c = _conn()
    ins = ("INSERT INTO avg_demand_daily(business_date, sku_code, fc_code, seller_code, avg_demand, product_name, "
           "source_table, source_modified, loaded_at) VALUES (?,?,?,?,?,?,?,?,?)")
    c.execute(ins, ("2026-11-01", "SKU1", "FC1", "MEDX", 2.5, "P", "p.d.t", None, TS))
    c.execute(ins, ("2026-11-01", "SKU1", "FC1", "OTHER", None, None, "p.d.t", None, TS))     # raw row per seller
    _refused(c, ins, ("2026-11-01", "SKU1", "FC1", "MEDX", 3.0, "P", "p.d.t", None, TS), "UNIQUE")
    _refused(c, ins, ("2026-11-01", "SKU1", "FC1", None, 3.0, "P", "p.d.t", None, TS), "NOT NULL")
    c.execute(ins, ("2026-11-01", "SKU1", "FC1", "MEDX", 2.0, "P", "p.d.hist", None, TS))      # other table: own row
    rd = ("INSERT INTO avg_demand_reads(id, source_table, business_date, kind, n_rows, source_modified, completed_at) "
          "VALUES (?,?,?,?,?,?,?)")
    c.execute(rd, ("A1", "p.d.t", "2026-11-01", "CURRENT", 2, None, TS))
    c.execute(rd, ("A2", "p.d.hist", "2026-11-01", "HISTORICAL", 0, None, TS))
    _refused(c, rd, ("A3", "p.d.t", "2026-11-01", "OTHER", 1, None, TS), "CHECK")
    _refused(c, rd, ("A4", "p.d.t", "2026-11-01", "CURRENT", None, None, TS), "NOT NULL")
    exp = ("INSERT INTO export_runs(id, forecast_date, version, path, created_at) VALUES (?,?,?,?,?)")
    c.execute(exp, ("E1", "2026-11-02", 1, "exports\\du_bao\\a.xlsx", TS))
    c.execute(exp, ("E2", "2026-11-02", 2, "exports\\du_bao\\b.xlsx", TS))
    c.execute(exp, ("E3", "2026-11-03", 1, "exports\\du_bao\\c.xlsx", TS))
    _refused(c, exp, ("E4", "2026-11-02", 2, "exports\\du_bao\\d.xlsx", TS), "UNIQUE")
    _refused(c, exp, ("E5", "2026-11-04", 1, None, TS), "NOT NULL")
    assert c.execute("SELECT is_stale FROM export_runs WHERE id='E1'").fetchone()[0] == 0
    c.close()


def _db_at(target, version: int) -> None:
    """A database built with the migrations up to `version` (as an installation of that version)."""
    c = sqlite3.connect(target)
    c.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    for v, p in db.available_migrations():
        if v > version:
            continue
        for stmt in db._split_sql(p.read_text(encoding="utf-8")):
            c.execute(stmt)
        c.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (v, p.name, TS))
    c.commit()
    c.close()


def test_migration_0012_on_a_131_database_keeps_every_existing_row(tmp_path):
    src = tmp_path / "v11.db"
    _db_at(src, 11)
    c = sqlite3.connect(src)
    c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                  "loaded_at) VALUES (?,?,?,?,?,?,?,?)",
                  [("BIGQUERY:p.d.t", "BIGQUERY", f"2026-10-{d:02d}", f"S{s}", "F1", float(d * s), 1, TS)
                   for d in range(1, 11) for s in range(1, 4)])
    c.executemany("INSERT INTO app_settings(section, value_json, updated_at) VALUES (?,?,?)",
                  [("daily_forecast", '{"enabled": true}', TS)])
    c.commit()
    before = {t: c.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in OLD_TABLES}
    schema_before = sorted(c.execute("SELECT type, name, sql FROM sqlite_master").fetchall(), key=str)
    c.close()
    res = db.migrate(src)
    assert res["applied"] == ["0012_sel2_pipeline.sql", "0013_spike_lines.sql"] and res["to"] == 13   # 1.4.8: + 0013
    assert db.migrate(src)["applied"] == []                                # idempotent
    c = sqlite3.connect(src)
    assert {t: c.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in OLD_TABLES} == before
    assert len(before["demand_daily"]) == 30
    assert c.execute("SELECT COUNT(*) FROM app_settings WHERE section='sel2_pipeline'").fetchone()[0] == 0
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    from test_v148_spike import reverse_0013
    reverse_0013(c)                                                        # 1.4.8: the newest migration first
    reverse_0012(c)                                                        # the reverse statements of the header
    c.commit()
    assert sorted(c.execute("SELECT type, name, sql FROM sqlite_master").fetchall(), key=str) == schema_before
    c.close()


def reverse_0012(c) -> None:
    """1.4.0: the reverse statements in the header of migration 0012 (copy only)."""
    for t in ("export_runs", "avg_demand_reads", "avg_demand_daily", "forecast_source_config_history", "forecast_source_config",
              "candidate_forecasts", "candidate_runs", "candidate_train_runs"):
        c.execute(f"DROP TABLE {t}")
    c.execute("DELETE FROM schema_migrations WHERE version = 12")
