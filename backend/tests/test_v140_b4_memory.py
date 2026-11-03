"""1.4.0 B4 (memory / speed of the SEL2 production path): the open-hours read of data.load_inputs as one sequential scan
(NOT INDEXED, same inputs), FIXED groups of replay computed from a separate read up to the group window end, the
candidates.parquet export in row groups (same file content as the former one-frame DataFrame.to_parquet), the per-step
progress lines, the frame of lgbm.load_frame (same values and order as the string frame), the AVG_DEMAND_MULTI_SELLER
alert of avg_demand._save and the logging of the sel2-* CLI (stdout = one JSON document).

Isolated temporary database (conftest), synthetic rows, fake BigQuery client only, LightGBM trained for real on synthetic
rows (unit / integration with fakes)."""
import json
import logging
import math
import sqlite3
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from app import cli, db, paths
from app import settings_service as ss
from app.bq.aux_sources import open_hours_source
from app.data.demand import load_demand
from app.messages import CATALOG
from app.ml.sel2 import avg_demand, data, errors, lgbm, pipeline, store
from test_v140_t4a_pipeline import SCOPE, _cands, _plenty_of_memory, _seed
from test_v140_t5_avg_demand import CUR, CURRENT_ROWS, HIST, _reads, _row, _stored, fake  # noqa: F401 - fake: fixture


def _steps(caplog, run: str) -> list[dict]:
    return [r.ctx for r in caplog.records if r.getMessage() == f"sel2 {run} step"]


@pytest.fixture
def steps_log(caplog, monkeypatch):
    """The df.* loggers stop at "df" once logging_setup.setup_logging ran in this process (propagate False): let the
    records reach caplog for this test only."""
    monkeypatch.setattr(logging.getLogger("df"), "propagate", True)
    caplog.set_level(logging.INFO, logger="df.sel2")
    return caplog


def _assert_step_fields(ctx: dict):
    assert {"step", "seconds", "private_mb", "peak_private_mb"} <= set(ctx), ctx
    assert isinstance(ctx["seconds"], (int, float)) and ctx["seconds"] >= 0
    for k in ("private_mb", "peak_private_mb"):
        assert ctx[k] is None or (isinstance(ctx[k], int) and ctx[k] >= 0), (k, ctx[k])


# ------------------------------------------------------------------ 1. open hours: NOT INDEXED, same inputs
class _IndexedConn(sqlite3.Connection):
    """The former statement: the open-hours read without NOT INDEXED (SQLite may use idx_ohd_date)."""
    stripped = 0

    def execute(self, sql, params=(), /):
        if "open_hours_daily NOT INDEXED" in sql:
            type(self).stripped += 1
            sql = sql.replace("open_hours_daily NOT INDEXED", "open_hours_daily")
        return super().execute(sql, params)


def _seed_open_hours(window_start: str):
    """Demand of 3 keys 2025-06-01 .. 2025-06-20 (open hours known) and the open-hours calendar of the configured source
    from 2025-05-25 (with NULL hours), + rows that must not be read: another source table, another seller, a key
    without demand, days after the end (2025-06-21 / 06-25), before the window start and before DAY0."""
    tbl, seller = open_hours_source()
    keys = [("A1", "FC1"), ("a2", "FC1"), ("B", "FC2")]
    dem, oh = [], []
    for i in range(20):
        d = date(2025, 6, 1) + timedelta(days=i)
        for j, (s, f) in enumerate(keys):
            if (i + j) % 3:
                dem.append((SCOPE, "BIGQUERY", str(d), s, f, float(1 + (i * j) % 4), 1, "x", 8.0, "OK"))
    for i in range(27):
        d = date(2025, 5, 25) + timedelta(days=i)
        for j, (s, f) in enumerate(keys):
            h = None if (i + j) % 7 == 0 else float(1 + (i + 2 * j) % 9)
            oh.append((tbl, seller, f, s, str(d), h, 1, "x"))
            oh.append(("other.table", seller, f, s, str(d), 99.0, 1, "x"))
            oh.append((tbl, "OTHER_SELLER", f, s, str(d), 98.0, 1, "x"))
        oh.append((tbl, seller, "FC9", "ZZ", str(d), 5.0, 1, "x"))             # key without demand: ignored
    for d in ("2025-06-21", "2025-06-25", "2024-12-31", "2024-11-30"):        # after end / before DAY0 / before window
        for s, f in keys:
            oh.append((tbl, seller, f, s, d, 97.0, 1, "x"))
    with db.tx() as c:
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                      "loaded_at, open_hours, open_hours_status) VALUES (?,?,?,?,?,?,?,?,?,?)", dem)
        c.executemany("INSERT INTO open_hours_daily(source_table, seller_code, fc_code, sku_code, open_date, "
                      "total_open_hours, n_items, loaded_at) VALUES (?,?,?,?,?,?,?,?)", oh)
    return tbl, seller, keys


def _assert_same_inputs(a: data.Inputs, b: data.Inputs):
    assert a.oh.dtype == b.oh.dtype == np.float32 and a.oh.shape == b.oh.shape
    np.testing.assert_array_equal(a.oh, b.oh)                       # NaN cells compare equal
    assert np.array_equal(np.isnan(a.oh), np.isnan(b.oh))
    pd.testing.assert_frame_equal(a.keys, b.keys)
    pd.testing.assert_frame_equal(a.frame, b.frame)
    np.testing.assert_array_equal(a.daily, b.daily)
    np.testing.assert_array_equal(a.has_row, b.has_row)
    assert (a.end, a.window_start, a.flags, a.detail) == (b.end, b.window_start, b.flags, b.detail)


@pytest.mark.parametrize("window_start", ["2025-06-01", "2024-12-01"])
def test_open_hours_read_not_indexed_gives_the_same_inputs_and_filters(window_start, monkeypatch):
    tbl, seller, keys = _seed_open_hours(window_start)
    D = date(2025, 6, 21)
    with db.read() as c:
        seen = []
        c.set_trace_callback(seen.append)
        new = data.load_inputs(c, SCOPE, D, 2, window_start=window_start)
        c.set_trace_callback(None)
    # the statement sent is the sequential scan (fails on the former indexed statement)
    assert any("FROM open_hours_daily NOT INDEXED WHERE" in s for s in seen)
    monkeypatch.setattr(_IndexedConn, "stripped", 0)
    old_c = sqlite3.connect(str(paths.db_path()), factory=_IndexedConn)
    try:
        old_c.row_factory = sqlite3.Row
        old = data.load_inputs(old_c, SCOPE, D, 2, window_start=window_start)
    finally:
        old_c.close()
    assert _IndexedConn.stripped == 1
    _assert_same_inputs(new, old)
    # values: the configured source only, NULL -> NaN, nothing after the end, before DAY0 or before the window start
    assert list(zip(new.keys["sku_code"], new.keys["fc_code"])) == sorted(keys)
    assert new.oh.shape[1] == (D - data.DAY0).days
    assert not np.isin(new.oh, [99.0, 98.0, 97.0]).any()
    lo = max(date.fromisoformat(window_start), date(2025, 5, 25))
    with db.read() as c:
        src = {(r[0], r[1], r[2]): r[3] for r in c.execute(
            "SELECT sku_code, fc_code, open_date, total_open_hours FROM open_hours_daily WHERE source_table=? AND "
            "seller_code=? AND open_date BETWEEN ? AND ?", (tbl, seller, str(lo), "2025-06-20"))}
    kid = {k: i for i, k in enumerate(zip(new.keys["sku_code"], new.keys["fc_code"]))}
    n_nan = 0
    for g in range(new.oh.shape[1]):
        d = str(data.DAY0 + timedelta(days=g))
        for (s, f), k in kid.items():
            v = src.get((s, f, d), "absent")
            if v == "absent" or v is None:
                assert np.isnan(new.oh[k, g]), (s, f, d)
                n_nan += v is None
            else:
                assert new.oh[k, g] == np.float32(v), (s, f, d)
    assert n_nan > 0                                                # NULL hours exercised
    if window_start == "2025-06-01":
        assert np.isnan(new.oh[:, :new.g(date(2025, 6, 1))]).all()   # 2025-05-25 .. 05-31: before the window


def test_open_hours_statement_is_a_sequential_scan():
    tbl, seller = open_hours_source()
    with db.read() as c:
        plan = " ".join(str(r[3]) for r in c.execute(
            "EXPLAIN QUERY PLAN SELECT sku_code, fc_code, open_date, total_open_hours FROM open_hours_daily NOT INDEXED "
            "WHERE source_table=? AND seller_code=? AND open_date BETWEEN ? AND ?", (tbl, seller, "2025-01-01",
                                                                                    "2025-02-01")))
    assert "SCAN open_hours_daily" in plan and "INDEX" not in plan.upper()


# ------------------------------------------------------------------ 2. replay with FIXED groups ending after `end`
def _spy(monkeypatch):
    calls = {"load": [], "select": []}
    real_load, real_sel = pipeline.load, pipeline.select_and_publish

    def load(scope_key, d, s=None):
        calls["load"].append(d)
        return real_load(scope_key, d, s)

    def sel(d, **kw):
        r = real_sel(d, **kw)
        calls["select"].append((d, kw.get("fixed_groups"), r["selection"]))
        return r
    monkeypatch.setattr(pipeline, "load", load)
    monkeypatch.setattr(pipeline, "select_and_publish", sel)
    return calls


def _old_candidates(c, first, end, path):
    """The former export: one fetchall, one DataFrame, DataFrame.to_parquet."""
    rows = c.execute("SELECT forecast_date, sku_code, fc_code, model, horizon, target_date, value FROM "
                     "candidate_forecasts WHERE forecast_date BETWEEN ? AND ? ORDER BY forecast_date, sku_code, "
                     "fc_code, model, horizon", (str(first), str(end))).fetchall()
    pd.DataFrame(rows, columns=pipeline.CANDIDATE_COLUMNS).to_parquet(path, index=False)


def test_replay_fixed_groups_after_end_computed_from_a_full_read(sel2_on, monkeypatch, tmp_path, steps_log):
    monkeypatch.setattr(pipeline, "MIN_COMMIT_MB", 0)
    _plenty_of_memory(monkeypatch)
    _seed(end=date(2026, 6, 30))
    start, end, gs, ge = date(2026, 6, 15), date(2026, 6, 16), "2026-06-01", "2026-06-25"
    calls = _spy(monkeypatch)
    # before B4: SEL2_WINDOW_NOT_COVERED ("inputs end 2026-06-16, day 2026-06-26")
    r = pipeline.replay(start, end, tmp_path / "a", group_mode="FIXED", history_start_rule="BACKTEST",
                        group_start=gs, group_end=ge, scope_key=SCOPE)
    assert calls["load"] == [date(2026, 6, 26), date(2026, 6, 17)]          # group window read first, then the days
    s = ss.get("sel2_pipeline")
    with db.read() as c:
        full = data.load_inputs(c, SCOPE, date(2026, 6, 26), s.open_hours_lag_days)
    expected = full.groups(start, "FIXED", gs, ge)
    assert len(expected) == 10
    assert [d for d, _, _ in calls["select"]] == [start, end]
    for _, groups, _ in calls["select"]:
        pd.testing.assert_series_equal(groups, expected)
    # selected.parquet = the selections of the days, as before
    sel = pd.concat([x.assign(forecast_date=str(d)) for d, _, x in calls["select"]], ignore_index=True)
    sel["target_date"] = pd.to_datetime(sel["target_date"]).dt.strftime("%Y-%m-%d")
    got = pd.read_parquet(tmp_path / "a" / "selected.parquet")
    pd.testing.assert_frame_equal(got, sel)
    assert r["selected_rows"] == len(sel) == 2 * 10 * 7
    # candidates.parquet = the former one-frame export (columns, dtypes, order, values, schema)
    with db.read() as c:
        _old_candidates(c, date.fromisoformat(r["candidates_from"]), end, tmp_path / "old.parquet")
    pd.testing.assert_frame_equal(pd.read_parquet(tmp_path / "a" / "candidates.parquet"),
                                  pd.read_parquet(tmp_path / "old.parquet"))
    assert pq.read_schema(tmp_path / "a" / "candidates.parquet").equals(pq.read_schema(tmp_path / "old.parquet"))
    assert r["candidate_rows"] == pq.ParquetFile(tmp_path / "old.parquet").metadata.num_rows
    # one progress line per step, with seconds and private MB
    rep = _steps(steps_log, "replay")
    names = [x["step"] for x in rep]
    assert names[:3] == ["load_fixed_groups", "fixed_groups", "load"]
    assert names[-2:] == ["selected_parquet", "candidates_parquet"] and "train" in names and "candidates" in names
    assert names.count("select") == 2
    for x in rep:
        _assert_step_fields(x)
        assert x["start"] == str(start) and x["end"] == str(end)
    assert rep[1]["groups"] == 10 and rep[-1]["rows"] == r["candidate_rows"] and rep[-1]["row_groups"] == 1
    sel_steps = _steps(steps_log, "select")
    assert [x["step"] for x in sel_steps] == ["groups", "select"] * 2          # inputs given: no load, no publish
    assert all(x["fixed"] is True and x["publish"] is False for x in sel_steps if x["step"] == "groups")
    for x in sel_steps:
        _assert_step_fields(x)

    # a group window ending within the replay: no separate read, the groups come from the day's inputs (as before)
    calls["load"].clear()
    calls["select"].clear()
    r2 = pipeline.replay(start, end, tmp_path / "b", group_mode="FIXED", history_start_rule="BACKTEST",
                         group_start=gs, group_end="2026-06-14", scope_key=SCOPE)
    assert calls["load"] == [date(2026, 6, 17)] and r2["selected_rows"] == r["selected_rows"]
    assert all(g is None for _, g, _ in calls["select"])


def _store_days(days, keys, seed=0):
    rng = np.random.default_rng(seed)
    n = 0
    for d in days:
        cs = {m: f.assign(value=np.round(rng.gamma(1.0, 2.0, len(f)), 3)) for m, f in _cands(keys).items()}
        n += store.write_day(SCOPE, d, d - timedelta(days=1), cs, {}, {})
    return n


def test_select_and_publish_default_groups_unchanged_and_fixed_groups_used(sel2_on, steps_log):
    _seed(end=date(2026, 10, 31))
    d = date(2026, 10, 20)
    with db.read() as c:
        inp = data.load_inputs(c, SCOPE, d, 2)
    keys = list(zip(inp.scope_keys(d)["sku_code"], inp.scope_keys(d)["fc_code"]))
    _store_days([d], keys)
    base = pipeline.select_and_publish(d, publish=False, inputs=inp, scope_key=SCOPE)
    same = pipeline.select_and_publish(d, publish=False, inputs=inp, scope_key=SCOPE, fixed_groups=None)
    given = pipeline.select_and_publish(d, publish=False, inputs=inp, scope_key=SCOPE,
                                        fixed_groups=inp.groups(d, "ROLLING_B7"))
    pd.testing.assert_frame_equal(base["selection"], same["selection"])
    pd.testing.assert_frame_equal(base["selection"], given["selection"])
    # FIXED window after the inputs end without fixed_groups: still refused, as before
    with pytest.raises(errors.Sel2Error) as e:
        pipeline.select_and_publish(d, publish=False, inputs=inp, scope_key=SCOPE, group_mode="FIXED",
                                    group_start="2026-09-01", group_end="2026-10-25")
    assert e.value.code == "SEL2_WINDOW_NOT_COVERED" and "day 2026-10-26" in str(e.value.detail)
    # published with given groups (and inputs read by select_and_publish itself): the groups are those published
    fixed = pd.Series(["C"] * len(keys), index=pd.MultiIndex.from_tuples(keys))
    steps_log.clear()
    res = pipeline.select_and_publish(d, publish=True, scope_key=SCOPE, group_mode="FIXED", group_start="2026-09-01",
                                      group_end="2026-10-25", fixed_groups=fixed, trigger="test")
    with db.read() as c:
        g = {r[0] for r in c.execute("SELECT DISTINCT group_code FROM forecast_refresh_values WHERE run_id=?",
                                     (res["run_id"],))}
    assert g == {"C"} and res["values"] == len(keys) * 7
    st = _steps(steps_log, "select")
    assert [x["step"] for x in st] == ["load", "groups", "select", "publish"]
    for x in st:
        _assert_step_fields(x)
        assert x["forecast_date"] == str(d) and x["publish"] is True
    assert st[0]["rows"] == len(inp.frame) and st[1]["fixed"] is True and st[3]["values"] == len(keys) * 7


# ------------------------------------------------------------------ 3. candidates.parquet in row groups
def _compare_exports(tmp_path, first, end):
    with db.read() as c:
        n, groups = pipeline._write_candidates(c, first, end, tmp_path / "new.parquet")
        _old_candidates(c, first, end, tmp_path / "old.parquet")
    new, old = pd.read_parquet(tmp_path / "new.parquet"), pd.read_parquet(tmp_path / "old.parquet")
    pd.testing.assert_frame_equal(new, old)
    assert list(new.columns) == pipeline.CANDIDATE_COLUMNS
    assert pq.read_schema(tmp_path / "new.parquet").equals(pq.read_schema(tmp_path / "old.parquet"),
                                                           check_metadata=True)
    return n, groups, new


def test_write_candidates_no_row(tmp_path):
    n, groups, new = _compare_exports(tmp_path, date(2026, 10, 1), date(2026, 10, 5))
    assert (n, groups, len(new)) == (0, 0, 0)


def test_write_candidates_fewer_rows_than_one_read(tmp_path):
    keys = [("S2", "FC1"), ("S10", "FC1"), ("S1", "FC2")]
    days = [date(2026, 10, 1) + timedelta(days=i) for i in range(5)]
    _store_days(days, keys)
    n, groups, new = _compare_exports(tmp_path, days[1], days[3])            # range filter: 3 of the 5 days
    assert n == 3 * 3 * 6 * 7 < pipeline.CANDIDATE_READ_ROWS and groups == 1 == pq.ParquetFile(
        tmp_path / "new.parquet").metadata.num_row_groups
    assert sorted(new["forecast_date"].unique()) == [str(d) for d in days[1:4]]
    assert new["horizon"].dtype == np.int64 and new["value"].dtype == np.float64


@pytest.mark.parametrize("export_rows, read_rows", [(7, 5), (5, 7), (8, 3), (4, 4), (1000, 5)])
def test_write_candidates_many_reads_and_row_groups(tmp_path, monkeypatch, export_rows, read_rows):
    monkeypatch.setattr(pipeline, "CANDIDATE_EXPORT_ROWS", export_rows)
    monkeypatch.setattr(pipeline, "CANDIDATE_READ_ROWS", read_rows)
    keys = [("S2", "FC1"), ("S10", "FC1"), ("S1", "FC2"), ("A", "FC10")]
    days = [date(2026, 10, 1) + timedelta(days=i) for i in range(3)]
    total = _store_days(days, keys, seed=4)
    n, groups, new = _compare_exports(tmp_path, days[0], days[-1])
    assert n == total == 3 * 4 * 6 * 7 == 504
    meta = pq.ParquetFile(tmp_path / "new.parquet").metadata
    assert groups == meta.num_row_groups == math.ceil(n / export_rows)
    sizes = [meta.row_group(i).num_rows for i in range(meta.num_row_groups)]
    assert sum(sizes) == n and all(x == export_rows for x in sizes[:-1]) and 0 < sizes[-1] <= export_rows


@pytest.mark.parametrize("existing", [True, False])
def test_write_candidates_failure_keeps_the_complete_file_and_leaves_no_part(tmp_path, monkeypatch, existing):
    """B4-4: written to candidates.parquet.part then os.replace; an error unlinks the .part and never touches an
    existing complete candidates.parquet (fails on the direct write into candidates.parquet)."""
    monkeypatch.setattr(pipeline, "CANDIDATE_EXPORT_ROWS", 7)
    monkeypatch.setattr(pipeline, "CANDIDATE_READ_ROWS", 5)
    days = [date(2026, 10, 1) + timedelta(days=i) for i in range(2)]
    _store_days(days, [("S1", "FC1"), ("S2", "FC2")])
    out = tmp_path / "out"
    out.mkdir()
    path = out / "candidates.parquet"
    if existing:
        with db.read() as c:
            pipeline._write_candidates(c, days[0], days[-1], path)
        before = path.read_bytes()

    class Failing(pq.ParquetWriter):
        calls = 0

        def write_table(self, *a, **k):
            type(self).calls += 1
            if type(self).calls == 3:                                     # after two complete row groups
                raise OSError("disk full")
            return super().write_table(*a, **k)
    monkeypatch.setattr(pq, "ParquetWriter", Failing)
    with db.read() as c, pytest.raises(OSError):
        pipeline._write_candidates(c, days[0], days[-1], path)
    assert Failing.calls == 3
    assert sorted(p.name for p in out.iterdir()) == (["candidates.parquet"] if existing else [])
    if existing:
        assert path.read_bytes() == before
        assert len(pd.read_parquet(path)) == 2 * 2 * 6 * 7


# ------------------------------------------------------------------ 3b. progress lines of run_day, _memory_mb
def test_run_day_logs_one_line_per_step(sel2_on, monkeypatch, steps_log):
    from types import SimpleNamespace
    monkeypatch.setattr(pipeline, "_memory_gate", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "load", lambda *a, **k: SimpleNamespace(frame=[1, 2, 3], keys=[1, 2]))
    monkeypatch.setattr(pipeline, "candidates_for_day", lambda *a, **k: {"status": "STORED", "rows": 42})
    monkeypatch.setattr(pipeline, "select_and_publish", lambda *a, **k: {"rows": 14, "values": 14, "selection": None,
                                                                         "flags": [], "run_id": "R1"})
    monkeypatch.setattr(store, "apply_retention", lambda *a, **k: {"rows": 3})
    monkeypatch.setattr(pipeline, "_export_hook", lambda *a, **k: {"ok": True})
    out = pipeline.run_day(date(2026, 11, 1), scope_key=SCOPE, trigger="test")
    assert out["status"] == "PUBLISHED"
    st = _steps(steps_log, "day")
    assert [x["step"] for x in st] == ["load", "candidates", "select_and_publish", "retention", "export"]
    for x in st:
        _assert_step_fields(x)
        assert x["forecast_date"] == "2026-11-01" and x["trigger"] == "test"
    assert (st[0]["rows"], st[0]["keys"], st[1]["rows"], st[2]["values"], st[3]["rows"], st[4]["ok"]) == \
        (3, 2, 42, 14, 3, True)


def test_memory_mb_never_raises(monkeypatch):
    from app.jobs import resources
    real = pipeline._memory_mb()
    assert set(real) == {"private_mb", "peak_private_mb"}
    assert all(v is None or (isinstance(v, int) and v >= 0) for v in real.values())

    def boom():
        raise OSError("no reading")
    monkeypatch.setattr(resources, "_PMC", boom, raising=False)
    monkeypatch.setattr(resources, "snapshot", lambda: {})
    assert pipeline._memory_mb() == {"private_mb": None, "peak_private_mb": None}
    monkeypatch.setattr(resources, "snapshot", lambda: {"private": 5 * resources.MB, "ws_peak_lifetime": 9 * resources.MB})
    assert pipeline._memory_mb() == {"private_mb": 5, "peak_private_mb": 9}       # peak read failed: working-set peak
    monkeypatch.setattr(resources, "_PMC", None, raising=False)
    assert pipeline._memory_mb() == {"private_mb": 5, "peak_private_mb": 9}


# ------------------------------------------------------------------ 4. categorical sku_id / fc_id of load_frame
def test_load_frame_categories_keep_values_and_order():
    rows = []
    for i in range(6):
        d = str(date(2026, 3, 1) + timedelta(days=i))
        for s, f in [("S10", "FC2"), ("S9", "FC10"), ("s1", "FC2"), ("A", "FC10"), ("S9", "FC2"), ("Z0", "FC1")]:
            if (i + len(s) + len(f)) % 4:
                rows.append((SCOPE, "BIGQUERY", d, s, f, float(i + 1), 1, "x", 8.0, "OK"))
    with db.tx() as c:
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                      "loaded_at, open_hours, open_hours_status) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    with db.read() as c:
        frame, problems = lgbm.load_frame(c, SCOPE, "2026-03-01", "2026-03-06")
        ref = load_demand(SCOPE, c, start="2026-03-01", end="2026-03-06")
    assert problems == [] and len(frame) == len(rows)
    # dtype-neutral (B4-4 reverts the categorical sku_id / fc_id): the string frame sorted by (od, sku_id, fc_id)
    ref["od"] = pd.to_datetime(ref["order_date"])
    ref = ref.sort_values(["od", "sku_id", "fc_id"], kind="stable").reset_index(drop=True)
    as_str = frame.copy()
    for col in ("sku_id", "fc_id"):
        as_str[col] = as_str[col].astype(str).astype(ref[col].dtype)
    pd.testing.assert_frame_equal(as_str, ref)


# ------------------------------------------------------------------ 5. AVG_DEMAND_MULTI_SELLER
def _alerts():
    with db.read() as c:
        return db.rows(c, "SELECT * FROM alerts WHERE code='AVG_DEMAND_MULTI_SELLER' ORDER BY id")


@pytest.fixture
def avg_log(caplog, monkeypatch):
    monkeypatch.setattr(logging.getLogger("df"), "propagate", True)
    caplog.set_level(logging.WARNING, logger="df.sel2.avg")
    return caplog


def test_multi_seller_alert_with_the_read(fake, avg_log):  # noqa: F811
    out = avg_demand.read_current("2026-11-02")            # CURRENT_ROWS: S2 x F1 has sellers MEDX and MEDX_E
    assert out["multi_seller_keys"] == 1 and out["rows"] == 4
    al = _alerts()
    assert len(al) == 1 and al[0]["level"] == "WARNING"
    assert al[0]["entity_type"] == "avg_demand_reads" and al[0]["entity_id"] == out["read_id"] == _reads()[0]["id"]
    p = json.loads(al[0]["params_json"])
    assert {k: p.get(k) for k in ("business_date", "source_table", "keys", "examples")} == {
        "business_date": "2026-11-02", "source_table": CUR, "keys": 1, "examples": ["S2 x F1"]}
    # B4-4: the seller rule in force is part of the alert (key name not fixed by the contract: any "*rule*" key)
    assert [v for k, v in p.items() if "rule" in k] == ["PENDING"]
    w = [r for r in avg_log.records if r.name == "df.sel2.avg" and r.levelno == logging.WARNING]
    assert len(w) == 1 and w[0].ctx["keys"] == 1 and w[0].ctx["examples"] == ["S2 x F1"]
    assert w[0].ctx["business_date"] == "2026-11-02"
    # rule PENDING: still no value for the multi-seller key, the single-seller keys keep theirs
    res = avg_demand.avg_value("2026-11-02")
    assert res["rule"] == "PENDING"
    assert res["values"][("S2", "F1")] == {"value": None, "reason": "SELLER_RULE_PENDING", "n_sellers": 2}
    assert res["values"][("S1", "F1")]["value"] == 2.5
    assert avg_demand.apply_rule([("MEDX", 1.0), ("MEDX_E", 3.0)], "PENDING") == (None, "SELLER_RULE_PENDING")


def test_one_seller_per_key_no_alert(fake, avg_log):  # noqa: F811
    # same SKU in two FCs with different sellers and an exact repeat: never several sellers for one SKU x FC
    fake.responses["sel2_avg_demand_current"] = [_row("S1", "F1", "MEDX", 1.0), _row("S1", "F1", "MEDX", 1.0),
                                                 _row("S1", "F2", "MEDX_E", 2.0), _row("S2", "F1", "MEDX_E", None)]
    out = avg_demand.read_current("2026-11-02")
    assert out["multi_seller_keys"] == 0 and out["rows"] == 3 and out["exact_duplicates"] == 1
    assert _alerts() == []
    assert not [r for r in avg_log.records if r.name == "df.sel2.avg" and r.levelno >= logging.WARNING]


def test_multi_seller_examples_at_most_10_sorted(fake):  # noqa: F811
    rows = [_row(f"K{i:02d}", "F1", s, 1.0) for i in range(11, -1, -1) for s in ("MEDX", "MEDX_E")]
    fake.responses["sel2_avg_demand_current"] = rows + [_row("ONE", "F1", "MEDX", 1.0)]
    out = avg_demand.read_current("2026-11-02")
    assert out["multi_seller_keys"] == 12
    p = json.loads(_alerts()[0]["params_json"])
    assert p["keys"] == 12 and p["examples"] == [f"K{i:02d} x F1" for i in range(10)]


def test_multi_seller_alert_is_in_the_read_transaction(fake, monkeypatch):  # noqa: F811
    fake.responses["sel2_avg_demand_current"] = [_row("S1", "F1", "MEDX", 1.0)]
    avg_demand.read_current("2026-11-02")
    fake.responses["sel2_avg_demand_current"] = CURRENT_ROWS

    def boom(*a, **k):
        raise RuntimeError("alert insert failed")
    monkeypatch.setattr(db, "alert", boom)
    with pytest.raises(RuntimeError):
        avg_demand.read_current("2026-11-02")
    # rolled back: the former rows of the day, one read record, no alert
    assert [(r["sku_code"], r["avg_demand"]) for r in _stored("2026-11-02")] == [("S1", 1.0)]
    assert len(_reads()) == 1 and _alerts() == []


def test_multi_seller_historical_one_alert_per_day(fake):  # noqa: F811
    def hist(cfg):
        out = []
        for day in ("2026-10-30", "2026-10-31"):
            for s in ("MEDX", "MEDX_E"):
                out.append({**_row("S1", "F1", s, 1.0), "business_date": day, "transformed_at": f"{day} 08:10:00+00"})
        out.append({**_row("S2", "F1", "MEDX", 1.0), "business_date": "2026-11-01",
                    "transformed_at": "2026-11-01 08:10:00+00"})
        return out
    fake.responses["sel2_avg_demand_hist"] = hist
    out = avg_demand.read_historical("2026-10-30", "2026-11-01")
    assert [d["multi_seller_keys"] for d in out["days"]] == [1, 1, 0]
    al = _alerts()
    assert [json.loads(a["params_json"])["business_date"] for a in al] == ["2026-10-30", "2026-10-31"]
    assert all(json.loads(a["params_json"])["source_table"] == HIST for a in al)
    assert [a["entity_id"] for a in al] == [d["read_id"] for d in out["days"][:2]]


def test_multi_seller_message_is_bilingual():
    vi, en = CATALOG["AVG_DEMAND_MULTI_SELLER"]
    assert vi.strip() and en.strip() and vi != en and "seller" in en


# ------------------------------------------------------------------ cli: logging configured only to run
def test_sel2_cli_configures_logging_only_with_yes(monkeypatch, capsys):
    from app import logging_setup
    calls = []
    monkeypatch.setattr(logging_setup, "setup_logging", lambda *a, **k: calls.append(1))
    assert cli.main(["sel2-day", "--date", "2026-11-01"]) == 0                    # plan only
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] and out["code"] == "SEL2_CONFIRM_REQUIRED" and calls == []
    assert cli.main(["sel2-replay", "--from", "2026-10-10", "--to", "2026-10-01", "--out", "x", "--yes"]) == 2
    capsys.readouterr()
    assert calls == []                                                            # refused before running
    assert cli.main(["sel2-day", "--date", "2026-11-01", "--yes"]) == 0            # sel2 off: run_day SKIPPED
    out = json.loads(capsys.readouterr().out)
    assert out["result"] == {"status": "SKIPPED", "reason_code": "SEL2_DISABLED"} and calls == [1]


def test_sel2_cli_yes_stdout_is_one_json_document_with_step_lines(monkeypatch, capsys):
    """B4-4: a sel2-* command run with --yes logs the pipeline's INFO step lines to a file, never to stdout: stdout stays
    ONE JSON document for the job runner (jobs._parse). The real logging setup runs here; every handler it adds is
    removed afterwards (no process-wide console handler left on pytest's captured stdout)."""
    from app import logging_setup
    from app.ml.sel2 import jobs as sel2_jobs
    monkeypatch.setattr(logging_setup, "_configured", False)
    loggers = [logging.getLogger(n) for n in ("", "df", "df.sel2", "df.sel2.avg")]
    saved = {lg.name: (list(lg.handlers), lg.level, lg.propagate) for lg in loggers}

    def fake_run_day(d=None, trigger="manual", job_id=None, force=False, **kw):
        step = pipeline._progress("day", forecast_date=str(d), trigger=trigger)
        step("load", rows=3, keys=2)
        step("candidates", status="STORED", rows=42)
        pipeline.log.info("sel2 candidate trained", extra={"ctx": {"model": "MOC"}})
        return {"status": "PUBLISHED", "forecast_date": str(d)}
    monkeypatch.setattr(pipeline, "run_day", fake_run_day)
    try:
        rc = cli.main(["sel2-day", "--date", "2026-11-01", "--yes"])
        out = capsys.readouterr().out
    finally:
        for lg in loggers:
            handlers, level, prop = saved[lg.name]
            for h in [h for h in lg.handlers if h not in handlers]:
                lg.removeHandler(h)
                h.close()
            lg.setLevel(level)
            lg.propagate = prop
    assert rc == 0
    doc = json.loads(out)                                         # fails while step lines go to stdout
    assert doc["ok"] is True and doc["result"] == {"status": "PUBLISHED", "forecast_date": "2026-11-01"}
    assert sel2_jobs._parse(out) == doc
    # the step lines are kept in a log file of the configured storage
    logs = [p for p in paths.logs_dir().glob("*.log*") if "sel2 day step" in p.read_text(encoding="utf-8")]
    assert [p.name for p in logs] == ["sel2-day.log"], sorted(p.name for p in paths.logs_dir().iterdir())
