"""1.4.8 (C-1): spike cleaning core - ml/sel2/spike.py (port of the research flags.flag_lines logic v3 + bt17.Excess),
migration 0013 (so_lines_cache, spike_flag_lines, demand_excess_daily), the settings sel2_pipeline.spike_cleaning
(OFF) / spike_e4_n (4) and the data checks of the new tables.

Equivalence: on a synthetic multi-customer data set the excess per SKU x FC x day as of D (level 1, E4 N = 4 / 5) of
spike.py equals (a) a direct flag_lines(asof=D, data_end=D-1, e4_days=N) of the port and of the research flags.py, and
(b) the research Excess (bt17.py, class extracted from the source text: importing bt17 would change the process
environment) built from an all-data research run; the research files are used only when present (else skipped), and
a hard-coded golden result keeps the check without them. Temporary test database and synthetic data only.
"""
import ast
import importlib.util
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app import data_checks, db, paths
from app import settings_service as ss
from app.ml.sel2 import spike

RESEARCH = Path(r"D:\Buymed\Lightgbm AI\reports")
FLAGS_PY = RESEARCH / "don-dot-bien" / "code" / "flags.py"
BT17_PY = RESEARCH / "backtest-ngay1-7-20261107" / "code" / "bt17.py"
SCOPE = "BIGQUERY:p.d.t"
TS = "2026-11-01T00:00:00+00:00"
NEW_TABLES = ("so_lines_cache", "spike_flag_lines", "demand_excess_daily")
D0 = pd.Timestamp("2026-04-01")
NDAYS = 120
END = D0 + pd.Timedelta(days=NDAYS - 1)                 # last day of the lines (2026-07-29)
AS_OF = [D0 + pd.Timedelta(days=i) for i in (70, 95, 108, NDAYS)]   # NDAYS = END + 1
KEY = ["sku_code", "fc_code", "d", "so_code", "customer_id"]


# ================================================================== synthetic data
def day(i: int) -> pd.Timestamp:
    return D0 + pd.Timedelta(days=i)


def synth_lines() -> pd.DataFrame:
    rng = np.random.default_rng(148)
    rows = []
    n = [0]

    def add(sku, fc, i, cust, q, so=None):
        n[0] += 1
        rows.append({"d": day(i), "so_code": so or f"SO{n[0]:06d}", "customer_id": cust, "sku_code": sku,
                     "fc_code": fc, "qty": float(q)})

    for sku, fc in (("S1", "BD"), ("S2", "BD"), ("S5", "HN"), ("S8", "BD"), ("S9", "HN")):   # background: 2 a day
        for i in range(NDAYS):
            add(sku, fc, i, f"{sku}{fc}bg{i % 5}", 2)
    for i in range(10, 100, 3):
        add("S1", "BD", i, "A", 2)                      # regular customer A
    add("S1", "BD", 80, "A", 20)                        # T1 (+ T2), next purchase 20 days later: T7 as of D
    add("S1", "BD", 100, "A", 2)
    add("S2", "BD", 70, "N1", 30)                       # new customer: T2
    add("S2", "BD", 72, "N2", 4)                        # below the minimum quantity 5
    add("S2", "BD", 90, None, 40)                       # unknown customer (NULL): its own new customer
    add("S2", "BD", 91, "", 40)                         # unknown customer ('')
    for i in range(NDAYS):
        add("S3", "HN", i, f"S3bg{i % 4}", 1)           # group C (minimum 3)
    for i in (20, 30, 40, 50):
        add("S3", "HN", i, "CC", 1)
    add("S3", "HN", 60, "CC", 3)                        # T1 at the group C minimum
    for i in range(NDAYS):                              # S4: 12 lines of 1 a day
        for c in range(12):
            add("S4", "BD", i, f"c{c}", 1)
    add("S4", "BD", 60, "Z", 10)                        # T4 (+ T2)
    for i in (5, 9, 17, 22, 40, 46, 61, 77):
        add("S5", "HN", i, "W", 30)                     # frequent wholesale customer
    add("S5", "HN", 85, "W", 100)
    big = range(14, NDAYS, 7)
    for i in range(NDAYS):
        add("S6", "BD", i, "R", 10 if i in big else 1)  # weekly big orders: periodic exception
        add("S6", "BD", i, f"S6bg{i % 3}", 1)
    for i in range(NDAYS):                              # S7: 2 lines of 2 a day, then a real demand increase
        add("S7", "HN", i, f"S7bg{(2 * i) % 10}", 2)
        add("S7", "HN", i, f"S7bg{(2 * i + 1) % 10}", 2)
    for c in range(4):
        add("S7", "HN", 90, f"crowd{c}", 25)
    for i in (60, 66, 72, 84, 93, 96, 99, 102, 105, 111, 114, 117):
        add("S8", "BD", i, f"new8_{i}", 50)             # E4: spike lines of new customers on many days
    for i in range(NDAYS):                              # S9: closed every 4th day (calendar), regular buyers
        if i % 4 == 3:
            continue
        add("S9", "HN", i, f"S9r{i % 3}", 3)
    for i in (33, 66, 99):
        add("S9", "HN", i, "S9r0", 15)
    for s in range(3):                                  # random multi-customer series
        for i in range(NDAYS):
            for c in range(int(rng.integers(0, 6))):
                cu = f"R{s}c{int(rng.integers(0, 9))}"
                q = int(rng.poisson(3)) + 1
                if rng.random() < 0.03:
                    q *= int(rng.integers(5, 15))
                add(f"SR{s}", "BD" if s % 2 else "HN", i, cu, q, so=f"SR{s}-{i}-{c}")
    return pd.DataFrame(rows)


def calendar(before=None) -> pd.DataFrame:
    """open hours: S9 x HN closed every 4th day, S1 x BD every day (rows < before only); the other series have no row."""
    rows = [("HN", "S9", day(i), 0.0 if i % 4 == 3 else 10.0) for i in range(NDAYS)]
    rows += [("BD", "S1", day(i), 12.0) for i in range(NDAYS)]
    od = pd.DataFrame(rows, columns=["fc_code", "sku_code", "open_date", "hours"])
    return od if before is None else od[od["open_date"] < before]


def groups() -> pd.DataFrame:
    return pd.DataFrame({"fc_code": ["HN", "BD", "BD", "HN"], "sku_code": ["S3", "S1", "S1", "S3"],
                         "group_code": ["C", "A", "B", "C"],
                         "computed_for": [D0, D0, D0 + pd.Timedelta(days=56), D0 + pd.Timedelta(days=56)]})


def full_flags(lines=None) -> pd.DataFrame:
    lines = synth_lines() if lines is None else lines
    return spike.flag_lines(lines, calendar(), groups(), D0, END, data_end=END, day0=D0)


def direct(lines, D, e4) -> pd.DataFrame:
    end = D - pd.Timedelta(days=1)
    return spike.flag_lines(lines, calendar(D), groups(), D0, end, data_end=end, asof=D, e4_days=e4, day0=D0)


def per_cell(fl: pd.DataFrame, col: str = "excess_L1") -> dict:
    f = fl[fl[col] > 0]
    s = f.groupby(["sku_code", "fc_code", pd.to_datetime(f["d"]).dt.date])[col].sum()
    return {k: round(float(v), 9) for k, v in s.items()}


def cells_dict(cf: pd.DataFrame) -> dict:
    return {(s, f, d): round(float(e), 9) for s, f, d, e in zip(cf["sku_code"], cf["fc_code"], cf["d"], cf["excess"])}


# ------------------------------------------------------------------ research code (only when present)
def _research_flags():
    if not FLAGS_PY.is_file():
        pytest.skip("research flags.py not present")
    spec = importlib.util.spec_from_file_location("research_flags_v148", FLAGS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _research_excess_class():
    """bt17.Excess + g_of / DAY0 / E4_WINDOW / FLAG_COLS* from the source text (no import of bt17: it sets the process
    environment and sys.path at import)."""
    if not BT17_PY.is_file():
        pytest.skip("research bt17.py not present")
    tree = ast.parse(BT17_PY.read_text(encoding="utf-8"))
    want_fn, want_cls = {"g_of"}, {"Excess"}
    want_var = {"DAY0", "E4_WINDOW", "FLAG_COLS", "FLAG_COLS_V3"}
    body = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name in want_fn)
            or (isinstance(n, ast.ClassDef) and n.name in want_cls)
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in want_var for t in n.targets))]
    ns = {"np": np, "pd": pd, "date": date, "timedelta": timedelta, "__name__": "research_bt17_v148"}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(BT17_PY), "exec"), ns)
    return ns


def _research_lines(lines: pd.DataFrame) -> pd.DataFrame:
    return lines.rename(columns={"customer_id": "cust"})


# ================================================================== A. settings
def test_spike_settings_default_off_and_validated():
    s = ss.Sel2PipelineSettings()
    assert (s.spike_cleaning, s.spike_e4_n) == (False, 4)
    assert ss.get("sel2_pipeline").spike_cleaning is False
    for bad in ({"spike_e4_n": 0}, {"spike_e4_n": 31}, {"spike_e4_n": "x"}, {"spike_cleaning": "maybe"}):
        with pytest.raises(ValidationError):
            ss.Sel2PipelineSettings(**bad)
    ss.update("sel2_pipeline", {"spike_cleaning": True, "spike_e4_n": 5}, note="tests: spike on")
    g = ss.get("sel2_pipeline")
    assert (g.spike_cleaning, g.spike_e4_n) == (True, 5)
    assert ss.history("sel2_pipeline")[0]["value"]["spike_e4_n"] == 5


def test_a_stored_section_without_the_new_fields_reads_off():
    # a 1.4.7 installation has a stored sel2_pipeline section without the new fields
    old = {k: v for k, v in ss.Sel2PipelineSettings().model_dump().items() if not k.startswith("spike_")}
    s = ss.Sel2PipelineSettings.model_validate(old)
    assert (s.spike_cleaning, s.spike_e4_n) == (False, 4)


def test_config_version_identity_is_the_1_4_6_value_when_off():
    from app.ml.sel2 import store
    # values of the 1.4.6 store.config_version (git show github/1.4.6:backend/app/ml/sel2/store.py) on the same settings
    assert store.config_version(ss.Sel2PipelineSettings()) == "SEL2:326f4ea688f6"
    assert store.config_version(ss.Sel2PipelineSettings(spike_e4_n=9)) == "SEL2:326f4ea688f6"
    assert store.config_version(ss.Sel2PipelineSettings(window_days=35, min_days=10)) == "SEL2:e255b24a9b58"


# ================================================================== B. migration 0013
def _db_at(target, version: int) -> None:
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


def reverse_0013(c) -> None:
    """1.4.8: the reverse statements in the header of migration 0013 (copy only; the indexes go with the tables)."""
    for t in ("demand_excess_daily", "spike_flag_lines", "so_lines_cache"):
        c.execute(f"DROP TABLE {t}")
    c.execute("DELETE FROM schema_migrations WHERE version = 13")


def test_migration_0013_on_a_fresh_database(tmp_path):
    fresh = tmp_path / "fresh.db"
    res = db.migrate(fresh)
    assert res["from"] == 0 and res["to"] == 13 and res["applied"][-1] == "0013_spike_lines.sql"
    c = sqlite3.connect(fresh)
    try:
        for t in NEW_TABLES:
            assert c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0
            assert "WITHOUT ROWID" in c.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()[0].upper()
        pk = {t: [r[1] for r in sorted(c.execute(f"PRAGMA table_info({t})"), key=lambda r: r[5]) if r[5]] for t in NEW_TABLES}
        assert pk == {"so_lines_cache": ["scope_key", "order_date", "fc_code", "sku_code", "so_code", "customer_id"],
                      "spike_flag_lines": ["scope_key", "logic", "history_days", "d", "fc_code", "sku_code", "so_code",
                                           "customer_id"],
                      "demand_excess_daily": ["scope_key", "d", "fc_code", "sku_code", "level", "e4_n"]}
        assert c.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_slc_series'").fetchone()
    finally:
        c.close()
    assert db.migrate(fresh)["applied"] == []                             # idempotent


def test_migration_0013_on_a_schema_12_database_keeps_every_row_and_reverses(tmp_path):
    src = tmp_path / "v12.db"
    _db_at(src, 12)
    c = sqlite3.connect(src)
    c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
                  "VALUES (?,?,?,?,?,?,?,?)", [(SCOPE, "BIGQUERY", f"2026-10-{d:02d}", f"S{s}", "F1", float(d * s), 1, TS)
                                               for d in range(1, 11) for s in range(1, 4)])
    c.execute("INSERT INTO app_settings(section, value_json, updated_at) VALUES (?,?,?)",
              ("sel2_pipeline", '{"enabled": true}', TS))
    c.commit()
    old = ("demand_daily", "app_settings", "order_lines", "candidate_forecasts", "export_runs")
    before = {t: c.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3").fetchall() for t in old}
    schema_before = sorted(c.execute("SELECT type, name, sql FROM sqlite_master").fetchall(), key=str)
    c.close()
    res = db.migrate(src)
    assert res["from"] == 12 and res["applied"] == ["0013_spike_lines.sql"] and res["to"] == 13
    c = sqlite3.connect(src)
    assert {t: c.execute(f"SELECT * FROM {t} ORDER BY 1, 2, 3").fetchall() for t in old} == before
    assert len(before["demand_daily"]) == 30
    assert ss.get("sel2_pipeline", conn=c).spike_cleaning is False          # stored section without the field: OFF
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    reverse_0013(c)                                                         # the reverse statements of the header
    c.commit()
    assert sorted(c.execute("SELECT type, name, sql FROM sqlite_master").fetchall(), key=str) == schema_before
    c.close()


def _conn():
    return sqlite3.connect(str(paths.db_path()), isolation_level=None)


def _flag_row(**kw):
    r = {"scope_key": SCOPE, "logic": "v3", "history_days": 180, "d": "2026-10-01", "fc_code": "BD", "sku_code": "S1",
         "so_code": "SO1", "customer_id": "C1", "qty": 20.0, "group_code": None, "min_qty": 5.0, "n_prev": 3,
         "cust_med": 2.0, "gap_med": None, "n_gaps": 0, "next_day": None, "kept": 2.0, "T1": 1, "T2": 1, "T4": 0, "T7": 0,
         "n_signals_raw": 2, "exc_wholesale": 0, "exc_periodic": 0, "exc_demand": 0, "is_regular": 1,
         "computed_for": "2026-10-02", "computed_at": TS}
    r.update(kw)
    return r


def _ins(c, table, r):
    c.execute(f"INSERT INTO {table}({', '.join(r)}) VALUES ({', '.join('?' * len(r))})", tuple(r.values()))


@pytest.mark.parametrize("bad, match", [({"d": "2026-10-02"}, "CHECK"), ({"n_signals_raw": 0}, "CHECK"),
                                        ({"logic": "v2"}, "CHECK"), ({"T1": 2}, "CHECK"), ({"qty": 0.0}, "CHECK"),
                                        ({"group_code": "X"}, "CHECK"), ({"customer_id": None}, "NOT NULL")])
def test_spike_flag_lines_constraints(bad, match):
    c = _conn()
    _ins(c, "spike_flag_lines", _flag_row())
    with pytest.raises(sqlite3.IntegrityError, match=match):
        _ins(c, "spike_flag_lines", _flag_row(so_code="SO2", **bad))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _ins(c, "spike_flag_lines", _flag_row())
    c.close()


def test_so_lines_cache_and_excess_constraints():
    c = _conn()
    line = {"scope_key": SCOPE, "order_date": "2026-10-01", "fc_code": "BD", "sku_code": "S1", "so_code": "SO1",
            "customer_id": "", "qty": 3.0, "n_rows": 2, "loaded_at": TS}
    _ins(c, "so_lines_cache", line)
    _ins(c, "so_lines_cache", {**line, "customer_id": "C1"})             # same order, another customer: another line
    for bad, match in (({}, "UNIQUE"), ({"so_code": "SO2", "qty": -1.0}, "CHECK"), ({"so_code": "SO3", "n_rows": 0}, "CHECK"),
                       ({"so_code": "SO4", "customer_id": None}, "NOT NULL")):
        with pytest.raises(sqlite3.IntegrityError, match=match):
            _ins(c, "so_lines_cache", {**line, **bad})
    ex = {"scope_key": SCOPE, "d": "2026-10-01", "fc_code": "BD", "sku_code": "S1", "level": 1, "e4_n": 4,
          "excess": 5.0, "asof": "2026-10-02", "computed_at": TS}
    _ins(c, "demand_excess_daily", ex)
    for bad in ({"d": "2026-10-02"}, {"level": 4}, {"e4_n": 0}, {"excess": 0.0}):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            _ins(c, "demand_excess_daily", {**ex, "sku_code": "S9", **bad})
    c.close()


# ================================================================== C. data checks
def _spike_status(res) -> dict:
    return {x["check"]: (x["status"], x["count"]) for x in res["checks"] if x["check"].startswith(("spike_", "demand_ex"))}


def test_data_checks_clean_on_empty_tables():
    res = data_checks.run(paths.db_path())
    assert _spike_status(res) == {"spike_tables_scope": ("OK", 0), "demand_excess_one_run": ("OK", 0),
                                  "demand_excess_within_demand": ("OK", 0)}


def test_data_checks_report_mixed_scopes_runs_and_excess_above_demand():
    c = _conn()
    c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
              "VALUES (?,?,?,?,?,?,?,?)", (SCOPE, "BIGQUERY", "2026-10-01", "S1", "BD", 10.0, 1, TS))
    ex = {"scope_key": SCOPE, "d": "2026-10-01", "fc_code": "BD", "sku_code": "S1", "level": 1, "e4_n": 4,
          "excess": 5.0, "asof": "2026-10-03", "computed_at": TS}
    _ins(c, "demand_excess_daily", ex)
    assert _spike_status(data_checks.run(paths.db_path()))["demand_excess_within_demand"] == ("OK", 0)
    _ins(c, "demand_excess_daily", {**ex, "d": "2026-10-02", "asof": "2026-10-04"})     # other run, no demand row
    _ins(c, "so_lines_cache", {"scope_key": "IMPORT-1", "order_date": "2026-10-01", "fc_code": "BD", "sku_code": "S1",
                               "so_code": "SO1", "customer_id": "C1", "qty": 3.0, "n_rows": 1, "loaded_at": TS})
    _ins(c, "spike_flag_lines", _flag_row(scope_key="DEMO-x"))
    c.close()
    st = _spike_status(data_checks.run(paths.db_path()))
    assert st == {"spike_tables_scope": ("FAIL", 2), "demand_excess_one_run": ("FAIL", 1),
                  "demand_excess_within_demand": ("WARN", 1)}


# ================================================================== D. equivalence with the research logic
def test_port_as_of_D_equals_a_direct_run_of_the_port():
    lines = synth_lines()
    fl = full_flags(lines)
    ex = spike.Excess(fl[fl["n_signals_raw"] >= 1], data_end=END)
    seen = set()
    for D in AS_OF:
        for e4 in (None, 4, 5):
            dr = direct(lines, D, e4)
            for lv in spike.LEVELS:
                got = cells_dict(ex.cells_frame(D, lv, e4))
                assert got == per_cell(dr, f"excess_L{lv}"), (D, e4, lv)
                seen.add((lv, bool(got)))
            a = ex.frame[KEY].assign(e=ex.lines_asof(D, 1, e4))
            b = dr.loc[dr["excess_L1"] > 0, KEY + ["excess_L1"]]
            j = a[a["e"] > 0].merge(b, on=KEY, how="outer").fillna(0)
            assert np.allclose(j["e"], j["excess_L1"])                    # line by line too
    assert {(1, True), (2, True)} <= seen                                  # not an empty comparison


def test_port_flags_equal_the_research_flag_lines_line_by_line():
    rf = _research_flags()
    lines = synth_lines()
    mine = full_flags(lines)
    ref = rf.flag_lines(_research_lines(lines), calendar(), groups(), D0, END, history_days=180, data_end=END,
                        logic="v3").rename(columns={"cust": "customer_id", "group": "group_code"})
    assert len(mine) == len(ref) == (synth_lines()["qty"] > 0).sum()
    for c in ("d", "fc_code", "sku_code", "so_code", "customer_id", "group_code", "next_day"):
        assert mine[c].astype(str).tolist() == ref[c].astype(str).tolist(), c
    for c in ("qty", "min_qty", "n_prev", "cust_med", "gap_med", "n_gaps", "kept", "T1", "T2", "T4", "T7",
              "n_signals_raw", "exc_wholesale", "exc_periodic", "exc_demand", "is_regular", "n_signals", "med_lines",
              "ser_line_med", "e4_big_days", "excess_L1", "excess_L2", "excess_L3"):
        assert np.allclose(mine[c].to_numpy(float), ref[c].to_numpy(float), equal_nan=True), c
    assert int((mine["n_signals_raw"] >= 1).sum()) > 20


@pytest.mark.parametrize("e4", [4, 5])
def test_excess_as_of_D_equals_the_research_direct_run_and_research_excess(e4):
    rf = _research_flags()
    ns = _research_excess_class()
    lines = synth_lines()
    rl = _research_lines(lines)
    full = rf.flag_lines(rl, calendar(), groups(), D0, END, history_days=180, data_end=END, logic="v3")
    rex = ns["Excess"](full[full["n_signals_raw"] >= 1][ns["FLAG_COLS_V3"]],
                       {x: i for i, x in enumerate(sorted(set(zip(lines["sku_code"], lines["fc_code"]))))}, "v3")
    keys = sorted(set(zip(lines["sku_code"], lines["fc_code"])))
    fl = full_flags(lines)
    ex = spike.Excess(fl[fl["n_signals_raw"] >= 1], data_end=END)
    assert list(zip(ex.keys["sku_code"], ex.keys["fc_code"])) == keys
    for D in AS_OF:
        mine = cells_dict(ex.cells_frame(D, 1, e4))
        end = D - pd.Timedelta(days=1)
        dr = rf.flag_lines(rl, calendar(D), groups(), D0, end, history_days=180, data_end=end, logic="v3",
                           e4_days=e4, e4_window=30, asof=D)
        assert mine == per_cell(dr), (D, e4)                              # (a) research direct run as of D
        k, g, s = rex.cells_asof(D.date(), 1, e4)
        ref = {(keys[kk][0], keys[kk][1], ns["DAY0"] + timedelta(days=int(gg))): round(float(v), 9)
               for kk, gg, v in zip(k, g, s)}
        assert mine == ref, (D, e4)                                       # (b) research Excess of an all-data run


# golden result (computed by the research flags.py / bt17.Excess and the port, equal): excess level 1 as of D
GOLDEN = {
    ("2026-07-30", 4): {
        "S1|BD|2026-06-20": 18, "S2|BD|2026-06-10": 28, "S2|BD|2026-06-30": 38, "S2|BD|2026-07-01": 38,
        "S3|HN|2026-05-31": 2, "S4|BD|2026-05-31": 9, "S5|HN|2026-04-06": 28, "S5|HN|2026-04-10": 28,
        "S5|HN|2026-06-25": 70, "S9|HN|2026-05-04": 12, "S9|HN|2026-06-06": 12, "SR0|HN|2026-04-13": 5,
        "SR0|HN|2026-04-17": 26, "SR0|HN|2026-04-18": 4, "SR0|HN|2026-05-18": 8, "SR0|HN|2026-05-26": 32,
        "SR0|HN|2026-06-26": 52, "SR0|HN|2026-07-21": 38, "SR0|HN|2026-07-29": 24, "SR2|HN|2026-04-17": 25.5,
        "SR2|HN|2026-04-26": 47, "SR2|HN|2026-05-12": 20.5, "SR2|HN|2026-05-15": 30, "SR2|HN|2026-06-11": 6,
        "SR2|HN|2026-06-24": 48, "SR2|HN|2026-06-26": 9, "SR2|HN|2026-07-05": 56.5,
    },
    ("2026-07-30", 5): {
        "S1|BD|2026-06-20": 18, "S2|BD|2026-06-10": 28, "S2|BD|2026-06-30": 38, "S2|BD|2026-07-01": 38,
        "S3|HN|2026-05-31": 2, "S4|BD|2026-05-31": 9, "S5|HN|2026-04-06": 28, "S5|HN|2026-04-10": 28,
        "S5|HN|2026-06-25": 70, "S9|HN|2026-05-04": 12, "S9|HN|2026-06-06": 12, "SR0|HN|2026-04-13": 5,
        "SR0|HN|2026-04-17": 26, "SR0|HN|2026-04-18": 4, "SR0|HN|2026-05-18": 8, "SR0|HN|2026-05-26": 32,
        "SR0|HN|2026-06-26": 52, "SR0|HN|2026-07-21": 38, "SR0|HN|2026-07-29": 24, "SR1|BD|2026-04-29": 32,
        "SR1|BD|2026-05-10": 20, "SR1|BD|2026-05-11": 18, "SR1|BD|2026-06-02": 6, "SR1|BD|2026-06-07": 56,
        "SR1|BD|2026-06-19": 27, "SR1|BD|2026-07-03": 44, "SR1|BD|2026-07-12": 56, "SR1|BD|2026-07-21": 6,
        "SR1|BD|2026-07-23": 66, "SR2|HN|2026-04-17": 25.5, "SR2|HN|2026-04-26": 47, "SR2|HN|2026-05-12": 20.5,
        "SR2|HN|2026-05-15": 30, "SR2|HN|2026-06-11": 6, "SR2|HN|2026-06-24": 48, "SR2|HN|2026-06-26": 9,
        "SR2|HN|2026-07-05": 56.5,
    },
    ("2026-07-05", 4): {
        "S1|BD|2026-06-20": 18, "S2|BD|2026-06-10": 28, "S2|BD|2026-06-30": 38, "S2|BD|2026-07-01": 38,
        "S3|HN|2026-05-31": 2, "S4|BD|2026-05-31": 9, "S5|HN|2026-04-06": 28, "S5|HN|2026-04-10": 28,
        "S5|HN|2026-06-25": 70, "S9|HN|2026-05-04": 12, "S9|HN|2026-06-06": 12, "SR0|HN|2026-04-13": 5,
        "SR0|HN|2026-04-17": 26, "SR0|HN|2026-04-18": 4, "SR0|HN|2026-05-18": 8, "SR0|HN|2026-05-26": 32,
        "SR0|HN|2026-06-26": 52, "SR1|BD|2026-04-29": 32, "SR1|BD|2026-05-10": 20, "SR1|BD|2026-05-11": 18,
        "SR1|BD|2026-06-02": 6, "SR1|BD|2026-06-07": 56, "SR1|BD|2026-06-19": 27, "SR1|BD|2026-07-03": 44,
        "SR2|HN|2026-04-17": 25.5, "SR2|HN|2026-04-26": 47, "SR2|HN|2026-05-12": 20.5, "SR2|HN|2026-05-15": 30,
        "SR2|HN|2026-06-11": 6, "SR2|HN|2026-06-24": 48, "SR2|HN|2026-06-26": 9,
    },
    ("2026-07-05", 5): {
        "S1|BD|2026-06-20": 18, "S2|BD|2026-06-10": 28, "S2|BD|2026-06-30": 38, "S2|BD|2026-07-01": 38,
        "S3|HN|2026-05-31": 2, "S4|BD|2026-05-31": 9, "S5|HN|2026-04-06": 28, "S5|HN|2026-04-10": 28,
        "S5|HN|2026-06-25": 70, "S6|BD|2026-04-15": 9, "S6|BD|2026-04-22": 9, "S8|BD|2026-05-31": 48,
        "S8|BD|2026-06-06": 48, "S8|BD|2026-06-12": 48, "S8|BD|2026-06-24": 48, "S8|BD|2026-07-03": 48,
        "S9|HN|2026-05-04": 12, "S9|HN|2026-06-06": 12, "SR0|HN|2026-04-13": 5, "SR0|HN|2026-04-17": 26,
        "SR0|HN|2026-04-18": 4, "SR0|HN|2026-05-18": 8, "SR0|HN|2026-05-26": 32, "SR0|HN|2026-06-26": 52,
        "SR1|BD|2026-04-29": 32, "SR1|BD|2026-05-10": 20, "SR1|BD|2026-05-11": 18, "SR1|BD|2026-06-02": 6,
        "SR1|BD|2026-06-07": 56, "SR1|BD|2026-06-19": 27, "SR1|BD|2026-07-03": 44, "SR2|HN|2026-04-17": 25.5,
        "SR2|HN|2026-04-26": 47, "SR2|HN|2026-05-12": 20.5, "SR2|HN|2026-05-15": 30, "SR2|HN|2026-06-11": 6,
        "SR2|HN|2026-06-24": 48, "SR2|HN|2026-06-26": 9,
    },
}


@pytest.mark.parametrize("D, e4", list(GOLDEN))
def test_golden_excess_as_of_D(D, e4):
    lines = synth_lines()
    fl = full_flags(lines)
    ex = spike.Excess(fl[fl["n_signals_raw"] >= 1], data_end=END)
    got = {f"{s}|{f}|{d}": round(e, 6) for (s, f, d), e in cells_dict(ex.cells_frame(pd.Timestamp(D), 1, e4)).items()}
    assert got == GOLDEN[(D, e4)]


def test_e4_excludes_a_series_with_flagged_lines_on_n_days_before_D():
    lines = synth_lines()
    fl = full_flags(lines)
    ex = spike.Excess(fl[fl["n_signals_raw"] >= 1], data_end=END)
    D = AS_OF[-1]
    k8 = int(np.flatnonzero((ex.keys["sku_code"] == "S8") & (ex.keys["fc_code"] == "BD"))[0])
    n = ex.e4_days(D)
    assert n[k8] >= 5
    assert any(s == "S8" for s, _, _ in cells_dict(ex.cells_frame(D, 1, None)))
    assert not any(s == "S8" for s, _, _ in cells_dict(ex.cells_frame(D, 1, 4)))
    assert not any(s == "S8" for s, _, _ in cells_dict(ex.cells_frame(D, 1, int(n[k8]))))
    assert any(s == "S8" for s, _, _ in cells_dict(ex.cells_frame(D, 1, int(n[k8]) + 1)))


def test_lines_at_or_after_D_change_nothing_as_of_D():
    lines = synth_lines()
    D = AS_OF[1]
    later = pd.DataFrame([(D + pd.Timedelta(days=j), f"X{j}{c}", f"S8c{c}", "S8", "BD", 300.0)
                          for j in range(0, 5) for c in range(3)], columns=lines.columns)
    a = spike.Excess((f := full_flags(lines))[f["n_signals_raw"] >= 1], data_end=END)
    mod = pd.concat([lines, later], ignore_index=True)
    b = spike.Excess((g := full_flags(mod))[g["n_signals_raw"] >= 1], data_end=mod["d"].max())
    for e4 in (None, 4, 5):
        assert cells_dict(a.cells_frame(D, 1, e4)) == cells_dict(b.cells_frame(D, 1, e4))


# ================================================================== E. tables round trip + cleaning helpers
def test_lines_and_flags_round_trip_through_the_tables():
    lines = synth_lines()
    with db.tx() as c:
        c.executemany("INSERT INTO so_lines_cache(scope_key, order_date, fc_code, sku_code, so_code, customer_id, qty, "
                      "n_rows, loaded_at) VALUES (?,?,?,?,?,?,?,1,?)",
                      [(SCOPE, str(d.date()), f, s, so, "" if pd.isna(cu) else cu, q, TS)
                       for d, so, cu, s, f, q in lines[["d", "so_code", "customer_id", "sku_code", "fc_code",
                                                         "qty"]].itertuples(index=False, name=None)])
    with db.read() as c:
        back = spike.read_lines(c, SCOPE, D0.date(), END.date())
    assert len(back) == len(lines)
    fl = spike.flag_lines(back, calendar(), groups(), D0, END, data_end=END, day0=D0)
    ref = full_flags(lines)
    assert per_cell(fl) == per_cell(ref)
    cf = END + pd.Timedelta(days=1)
    with db.tx() as c:
        n = spike.write_flags(c, SCOPE, fl, cf, D0, END)
    assert n == int((fl["n_signals_raw"] >= 1).sum()) > 0
    with db.read() as c:
        st = spike.read_flags(c, SCOPE)
    ex_db = spike.Excess(st)
    ex_fr = spike.Excess(fl[fl["n_signals_raw"] >= 1], data_end=END)
    for D in AS_OF:
        for e4 in (4, 5):
            assert cells_dict(ex_db.cells_frame(D, 1, e4)) == cells_dict(ex_fr.cells_frame(D, 1, e4))
    # a re-run of the last days replaces only those days
    with db.tx() as c:
        spike.write_flags(c, SCOPE, fl, cf, END - pd.Timedelta(days=9), END)
    with db.read() as c:
        assert len(spike.read_flags(c, SCOPE)) == n
    with pytest.raises(ValueError):
        with db.tx() as c:
            spike.write_flags(c, SCOPE, fl, END, D0, END)                    # a day not before the run day
    cells = ex_db.cells_frame(AS_OF[-1], 1, 4)
    with db.tx() as c:
        assert spike.write_excess_daily(c, SCOPE, cells, 1, 4, AS_OF[-1]) == len(cells) > 0
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                      "loaded_at) SELECT ?, 'BIGQUERY', order_date, sku_code, fc_code, SUM(qty), COUNT(*), ? FROM "
                      "so_lines_cache WHERE scope_key=? GROUP BY order_date, sku_code, fc_code", [(SCOPE, TS, SCOPE)])
    assert set(_spike_status(data_checks.run(paths.db_path())).values()) == {("OK", 0)}


def test_old_flags_refuse_an_as_of_day_their_t7_cannot_decide():
    lines = synth_lines()
    early_end = day(85)
    fl = spike.flag_lines(lines, calendar(early_end + pd.Timedelta(days=1)), groups(), D0, early_end,
                          data_end=early_end, day0=D0)
    ex = spike.Excess(fl[fl["n_signals_raw"] >= 1], data_end=early_end)
    ex.cells_asof(early_end + pd.Timedelta(days=1), 1, 4)                  # as of the run day: fine
    with pytest.raises(ValueError, match="too old"):
        ex.cells_asof(AS_OF[-1], 1, 4)                                     # S1 x BD customer A: next purchase unknown


def test_clean_daily_and_clean_frame():
    keys = pd.DataFrame({"sku_code": ["S1", "S2"], "fc_code": ["BD", "BD"]})
    g0 = spike.g_of(date(2026, 7, 1))
    daily = np.zeros((2, g0 + 5))
    daily[0, g0:g0 + 5] = [10, 3, 8, 6, 9]
    daily[1, g0:g0 + 5] = [1, 2, 3, 4, 5]
    cells = pd.DataFrame({"sku_code": ["S1", "S1", "S2", "S1"], "fc_code": ["BD"] * 4,
                          "d": [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3), date(2026, 7, 4)],
                          "excess": [4.0, 5.0, 1.0, 2.0]})
    D = date(2026, 7, 4)
    k = np.array([0, 0, 1, 0])
    g = spike._g(cells["d"])
    y = spike.clean_daily(daily, k, g, cells["excess"].to_numpy(), D)
    assert y[0, g0:g0 + 5].tolist() == [6, 0, 8, 6, 9]                    # clipped at 0; the day D and after unchanged
    assert y[1, g0:g0 + 5].tolist() == [1, 2, 2, 4, 5]
    assert daily[0, g0] == 10                                              # a copy
    frame = pd.DataFrame({"order_date": ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-01"],
                          "sku_id": ["S1", "S1", "S2", "S1", "S9"], "fc_id": ["BD"] * 5, "qty": [10.0, 3.0, 3.0, 6.0, 7.0],
                          "n_orders": [3, 1, 2, 2, 1]})
    frame["od"] = pd.to_datetime(frame["order_date"])
    out = spike.clean_frame(frame, cells, D)
    assert out["qty"].tolist() == [6.0, 0.0, 2.0, 6.0, 7.0]
    assert out.drop(columns="qty").equals(frame.drop(columns="qty")) and frame["qty"].tolist()[0] == 10.0
    assert spike.clean_frame(frame, cells.iloc[:0], D)["qty"].tolist() == frame["qty"].tolist()


# ================================================================== F. edge cases (tester, 1.4.8 part 1)
def test_settings_update_refuses_e4_n_out_of_range_and_stores_nothing():
    for ok in (1, 30):                                                     # the bounds themselves are valid
        assert ss.update("sel2_pipeline", {"spike_e4_n": ok}, note=f"tests: e4 {ok}").spike_e4_n == ok
    n_hist = len(ss.history("sel2_pipeline"))
    for bad in (0, 31, -1):
        with pytest.raises(ValidationError):
            ss.update("sel2_pipeline", {"spike_e4_n": bad}, note="tests: refused")
    assert ss.get("sel2_pipeline").spike_e4_n == 30                        # refused by save: nothing is stored
    assert len(ss.history("sel2_pipeline")) == n_hist


def test_empty_inputs_and_an_empty_store_give_no_excess():
    lines = synth_lines()
    assert list(spike.flag_lines(lines.iloc[:0], calendar(), groups(), D0, END).columns) == list(spike.OUT_COLS)
    assert spike.flag_lines(lines.assign(qty=0.0), calendar(), groups(), D0, END).empty   # qty 0 = not a purchase
    assert spike.flag_lines(lines, calendar(), groups(), D0, END, asof=D0).empty         # no line before the as-of day
    with db.read() as c:                                                   # fresh database: nothing read, nothing flagged
        back = spike.read_lines(c, SCOPE, D0.date(), END.date())
        st = spike.read_flags(c, SCOPE)
    assert back.empty and list(back.columns) == ["d", "so_code", "customer_id", "sku_code", "fc_code", "qty"]
    assert st.empty
    ex = spike.Excess(st)
    for e4 in (None, 4):
        cf = ex.cells_frame(AS_OF[-1], 1, e4)
        assert cf.empty and list(cf.columns) == ["sku_code", "fc_code", "d", "excess"]
    assert len(ex.e4_days(AS_OF[-1])) == 0
    keys = pd.DataFrame({"sku_code": ["S1"], "fc_code": ["BD"]})
    assert spike.Excess(st, keys=keys).e4_days(AS_OF[-1]).tolist() == [0]


def test_a_series_outside_the_keys_is_never_cleaned():
    lines = synth_lines()
    fl = full_flags(lines)
    flagged = fl[fl["n_signals_raw"] >= 1]
    full = spike.Excess(flagged, data_end=END)
    keys = full.keys[full.keys["sku_code"] != "S2"].reset_index(drop=True)   # S2 x BD is not a key of the run
    part = spike.Excess(flagged, keys=keys, data_end=END)
    D = AS_OF[-1]
    a, b = cells_dict(full.cells_frame(D, 1, 4)), cells_dict(part.cells_frame(D, 1, 4))
    assert any(s == "S2" for s, _, _ in a) and not any(s == "S2" for s, _, _ in b)
    assert b == {k: v for k, v in a.items() if k[0] != "S2"}
    assert len(part.e4_days(D)) == len(keys)
    assert (part.lines_asof(D, 1, 4)[(part.frame["sku_code"] == "S2").to_numpy()] == 0).all()


def test_read_flags_keeps_scope_history_days_and_day_range_apart():
    fl = full_flags()
    cf = END + pd.Timedelta(days=1)
    other = "BIGQUERY:p.d.other"
    with db.tx() as c:
        n = spike.write_flags(c, SCOPE, fl, cf, D0, END)
        spike.write_flags(c, other, fl, cf, D0, END)
        spike.write_flags(c, SCOPE, fl, cf, D0, END, history_days=90)
    with db.read() as c:
        assert len(spike.read_flags(c, SCOPE)) == len(spike.read_flags(c, other)) == n
        assert len(spike.read_flags(c, SCOPE, history_days=90)) == n
        lo, hi = day(60), day(90)
        part = spike.read_flags(c, SCOPE, lo, hi)
        assert len(part) == int(((fl["n_signals_raw"] >= 1) & (fl["d"] >= lo) & (fl["d"] <= hi)).sum()) > 0
        assert part["d"].min() >= lo and part["d"].max() <= hi
        assert set(part["computed_for"]) == {cf}
    with db.tx() as c:                                                     # re-run of one scope: the other untouched
        spike.write_flags(c, SCOPE, fl.iloc[:0], cf, D0, END)
    with db.read() as c:
        assert spike.read_flags(c, SCOPE).empty and len(spike.read_flags(c, other)) == n
        assert len(spike.read_flags(c, SCOPE, history_days=90)) == n


def test_write_excess_daily_replaces_only_its_scope_level_and_e4():
    cells = pd.DataFrame({"sku_code": ["S1", "S1", "S2", "S3"], "fc_code": ["BD"] * 4,
                          "d": [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 2), date(2026, 10, 5)],
                          "excess": [4.0, 0.0, 2.5, 9.0]})              # 0 excess and a day >= asof are not written
    other = "BIGQUERY:p.d.other"
    with db.tx() as c:
        assert spike.write_excess_daily(c, SCOPE, cells, 1, 4, "2026-10-05") == 2
        assert spike.write_excess_daily(c, SCOPE, cells, 1, 5, "2026-10-05") == 2
        assert spike.write_excess_daily(c, other, cells, 1, 4, "2026-10-05") == 2
        assert spike.write_excess_daily(c, SCOPE, cells.iloc[[0]], 1, 4, "2026-10-06") == 1   # newer run of (1, 4)
    with db.read() as c:
        rows = c.execute("SELECT scope_key, level, e4_n, d, sku_code, excess, asof FROM demand_excess_daily "
                         "ORDER BY 1, 2, 3, 4, 5").fetchall()
    assert [tuple(r) for r in rows] == [
        (other, 1, 4, "2026-10-01", "S1", 4.0, "2026-10-05"), (other, 1, 4, "2026-10-02", "S2", 2.5, "2026-10-05"),
        (SCOPE, 1, 4, "2026-10-01", "S1", 4.0, "2026-10-06"),
        (SCOPE, 1, 5, "2026-10-01", "S1", 4.0, "2026-10-05"), (SCOPE, 1, 5, "2026-10-02", "S2", 2.5, "2026-10-05")]
    assert _spike_status(data_checks.run(paths.db_path()))["demand_excess_one_run"] == ("OK", 0)
    with db.tx() as c:                                                     # a run without excess clears its rows
        assert spike.write_excess_daily(c, SCOPE, cells.iloc[:0], 1, 4, "2026-10-07") == 0
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM demand_excess_daily WHERE scope_key=? AND e4_n=4", (SCOPE,)).fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM demand_excess_daily").fetchone()[0] == 4


def test_data_checks_skip_the_spike_checks_before_migration_0013(tmp_path):
    src = tmp_path / "v12.db"
    _db_at(src, 12)
    names = {x["check"] for x in data_checks.run(src)["checks"]}
    assert not {"spike_tables_scope", "demand_excess_one_run", "demand_excess_within_demand"} & names
