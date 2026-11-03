"""1.4.0 T9: data-check invariants of migration 0012 (app/data_checks.py _sel2_checks) on the isolated test DB, rows
written by the SEL2 code (store.write_day, source_config.set_one) and broken on purpose in the test DB only (unit)."""
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from app import data_checks, db, paths
from app.ml.sel2 import select, source_config, store

SCOPE = "BIGQUERY:test.sel2"
D = date(2026, 10, 28)
SEL2 = ("sel2_protection_triggers", "candidate_runs_data_before_day", "candidate_forecasts_target_date",
        "candidate_forecasts_runs", "candidate_train_runs_stuck", "forecast_source_config_history", "export_files_exist")


def _cands(n_keys=3):
    keys = [(f"S{i:02d}", "FC1") for i in range(n_keys)]
    return {m: pd.DataFrame({"sku_code": np.repeat([k[0] for k in keys], 7), "fc_code": np.repeat([k[1] for k in keys], 7),
                             "horizon": np.tile(np.arange(1, 8), n_keys), "value": 1.0 + i})
            for i, m in enumerate(select.CANDIDATES)}


def _seed(data_dir, days=(D - timedelta(days=1), D)):
    for d in days:
        store.write_day(SCOPE, d, d - timedelta(days=1), _cands(), {}, {})
    source_config.set_one("S00", "FC1", "LIGHTGBM", "thu", confirm=True, changed_by="tester")
    source_config.set_one("S00", "FC1", "AVG_DEMAND", None, confirm=True, changed_by="tester")
    source_config.set_one("S01", "FC1", "LIGHTGBM", None, confirm=True, changed_by="tester")
    f = data_dir / "exports" / "du_bao" / "20261028" / "du_bao_20261028_v1.xlsx"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    with db.tx() as c:
        c.execute("INSERT INTO export_runs(id, forecast_date, version, path, created_at) VALUES "
                  "('EXP-1', ?, 1, 'exports/du_bao/20261028/du_bao_20261028_v1.xlsx', '2026-10-28T00:00:00+00:00')",
                  (str(D),))


def _run(models=True):
    res = data_checks.run(paths.db_path(), paths.models_dir() if models else None)
    return res, {x["check"]: x for x in res["checks"]}


def test_consistent_sel2_rows_pass(sel2_on, data_dir):
    _seed(data_dir)
    res, chk = _run()
    assert {k: chk[k]["status"] for k in SEL2} == dict.fromkeys(SEL2, "OK"), [chk[k] for k in SEL2]
    assert "newest day 2026-10-28" in chk["candidate_forecasts_target_date"]["rule"]
    assert "skipped" not in chk["export_files_exist"]["rule"]


def test_empty_sel2_tables_pass_and_export_check_is_skipped_without_folder():
    res, chk = _run(models=False)
    assert {k: chk[k]["status"] for k in SEL2} == dict.fromkeys(SEL2, "OK")
    assert "skipped" in chk["export_files_exist"]["rule"]


def test_broken_sel2_rows_are_reported(sel2_on, data_dir):
    _seed(data_dir)
    old = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat(timespec="seconds")
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
    with db.tx() as c:          # corruption the code must never produce (test DB only)
        c.execute("DROP TRIGGER trg_fsch_no_delete")
        c.execute("UPDATE candidate_runs SET data_as_of = forecast_date WHERE forecast_date = ? AND model = 'TSB'",
                  (str(D - timedelta(days=1)),))
        c.execute("UPDATE candidate_forecasts SET target_date = forecast_date WHERE forecast_date = ? AND horizon = 3",
                  (str(D),))
        c.execute("DELETE FROM candidate_runs WHERE forecast_date = ? AND model = 'DOW4'", (str(D),))
        c.execute("UPDATE candidate_runs SET scope_key = 'OTHER' WHERE forecast_date = ? AND model = 'AVG7'",
                  (str(D - timedelta(days=1)),))
        c.executemany("INSERT INTO candidate_train_runs(id, scope_key, model, origin_date, status, created_at) "
                      "VALUES (?, ?, 'MOC', '2026-10-26', 'RUNNING', ?)", [("CTR-OLD", SCOPE, old),
                                                                           ("CTR-NEW", SCOPE, recent)])
        c.execute("UPDATE forecast_source_config SET forecast_source = 'AVG_DEMAND' WHERE sku_code = 'S01'")
        c.execute("INSERT INTO forecast_source_config(sku_code, fc_code, forecast_source, updated_by, updated_at) "
                  "VALUES ('S02', 'FC1', 'LIGHTGBM', 'x', '2026-10-28T00:00:00+00:00')")      # no history row
        c.executemany("INSERT INTO export_runs(id, forecast_date, version, path, created_at) VALUES (?, ?, ?, ?, ?)",
                      [("EXP-2", str(D), 2, "exports/du_bao/20261028/du_bao_20261028_v2.xlsx", recent),
                       ("EXP-3", str(D), 3, "../outside.xlsx", recent)])
    res, chk = _run()
    assert res["status"] == "FAIL"
    assert chk["sel2_protection_triggers"]["status"] == "FAIL"
    assert chk["sel2_protection_triggers"]["examples"] == [["trg_fsch_no_delete"]]
    assert chk["candidate_runs_data_before_day"]["status"] == "FAIL" and chk["candidate_runs_data_before_day"]["count"] == 1
    t = chk["candidate_forecasts_target_date"]
    assert t["status"] == "FAIL" and t["count"] == 3 * 6 and t["examples"][0][4] == 3          # 3 keys x 6 models
    r = chk["candidate_forecasts_runs"]
    assert r["status"] == "FAIL" and sorted(x[:2] for x in r["examples"]) == [
        [str(D - timedelta(days=1)), "more than one scope"], [str(D), "no SUCCEEDED candidate_runs"]]
    assert chk["candidate_train_runs_stuck"]["status"] == "WARN" and chk["candidate_train_runs_stuck"]["examples"] == [
        ["CTR-OLD", "MOC", "2026-10-26", old]]
    s = chk["forecast_source_config_history"]
    assert s["status"] == "FAIL" and sorted(x[0] for x in s["examples"]) == ["S01", "S02"]
    e = chk["export_files_exist"]
    assert e["status"] == "WARN" and sorted((x[0], x[3]) for x in e["examples"]) == [
        ("EXP-2", "missing"), ("EXP-3", "path outside the data folder")]


def test_target_date_rule_reads_only_the_newest_day(sel2_on, data_dir):
    _seed(data_dir)
    with db.tx() as c:          # an older day is outside the bounded sample (the row checks stay cheap)
        c.execute("UPDATE candidate_forecasts SET target_date = '2000-01-01' WHERE forecast_date = ?",
                  (str(D - timedelta(days=1)),))
    _, chk = _run()
    assert chk["candidate_forecasts_target_date"]["status"] == "OK"
