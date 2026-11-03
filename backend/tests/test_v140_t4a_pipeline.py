"""1.4.0 T4a: SEL2 daily pipeline (app/ml/sel2/data.py, store.py, pipeline.py, cli sel2-*) on the isolated test DB
with synthetic BIGQUERY-like rows (unit / integration with fakes; no BigQuery, no live data)."""
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app import cli, db
from app.bq.aux_sources import open_hours_source
from app.ml.sel2 import data, errors, pipeline, select, store

SCOPE = "BIGQUERY:test.sel2"
D = date(2026, 11, 1)


def _seed(start=date(2026, 1, 1), end=date(2026, 10, 31), n_keys=10, seed=1):
    tbl, seller = open_hours_source()
    rng = np.random.default_rng(seed)
    dem, oh = [], []
    d = start
    while d <= end:
        for i in range(n_keys):
            sku, fc = f"S{i:02d}", ("FC1" if i % 2 else "FC2")
            oh.append((tbl, seller, fc, sku, str(d), 10.0, 1, "x"))
            q = int(rng.poisson(1.0 + i % 3))
            if q > 0:
                dem.append((SCOPE, "BIGQUERY", str(d), sku, fc, float(q), 1, "x", 10.0, "OK"))
        d += timedelta(days=1)
    with db.tx() as c:
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                      "loaded_at, open_hours, open_hours_status) VALUES (?,?,?,?,?,?,?,?,?,?)", dem)
        c.executemany("INSERT INTO open_hours_daily(source_table, seller_code, fc_code, sku_code, open_date, "
                      "total_open_hours, n_items, loaded_at) VALUES (?,?,?,?,?,?,?,?)", oh)


def _lag(cal_missing=(), dem_missing=(), hours=None):
    tbl, seller = open_hours_source()
    with db.tx() as c:
        for d, h in (hours or {}).items():
            c.execute("UPDATE open_hours_daily SET total_open_hours=? WHERE open_date=?", (h, d))
            c.execute("UPDATE demand_daily SET open_hours=? WHERE order_date=?", (h, d))
        for d in cal_missing:
            c.execute("DELETE FROM open_hours_daily WHERE open_date=?", (d,))
        for d in dem_missing:
            c.execute("UPDATE demand_daily SET open_hours=NULL, open_hours_status='MISSING' WHERE order_date=?", (d,))


def _load(d=D, lag=2):
    with db.read() as c:
        return data.load_inputs(c, SCOPE, d, lag)


# ------------------------------------------------------------------ open-hours lag rule
def test_lag_d1_missing_is_filled_from_d2_and_flagged():
    _seed()
    _lag(cal_missing=["2026-10-31"], dem_missing=["2026-10-31"], hours={"2026-10-30": 7.0})
    inp = _load()
    f = inp.frame[inp.frame["order_date"].astype(str).str[:10] == "2026-10-31"]
    assert len(f) and (f["open_hours"] == 7.0).all()
    assert inp.flags == [data.FLAG_OPEN_HOURS_LAG]
    assert inp.detail["open_hours_lag"]["calendar_days"] == ["2026-10-31"]
    assert (inp.oh[:, inp.g(date(2026, 10, 31))] == 7.0).all()


def test_lag_d1_and_d2_missing_are_filled_from_d3():
    _seed()
    _lag(cal_missing=["2026-10-30", "2026-10-31"], dem_missing=["2026-10-30", "2026-10-31"],
         hours={"2026-10-29": 6.0})
    inp = _load()
    late = inp.frame[inp.frame["order_date"].astype(str).str[:10] >= "2026-10-30"]
    assert len(late) and (late["open_hours"] == 6.0).all()
    assert inp.detail["open_hours_lag"]["rows_filled"] == len(late)


@pytest.mark.parametrize("cal, dem", [
    (["2026-10-29", "2026-10-30", "2026-10-31"], ["2026-10-31"]),        # source more than 2 days late
    (["2026-10-31"], ["2026-10-29"]),                                    # missing before D-2
])
def test_lag_beyond_the_rule_is_open_hours_invalid(cal, dem):
    _seed()
    _lag(cal_missing=cal, dem_missing=dem)
    with pytest.raises(errors.Sel2Error) as e:
        _load()
    assert e.value.code == "OPEN_HOURS_INVALID"


def test_lag_zero_keeps_the_131_block():
    _seed()
    _lag(cal_missing=["2026-10-31"], dem_missing=["2026-10-31"])
    with pytest.raises(errors.Sel2Error) as e:
        _load(lag=0)
    assert e.value.code == "OPEN_HOURS_INVALID"


def test_arrays_day0_and_dtypes():
    _seed()
    inp = _load()
    assert inp.oh.dtype == np.float32 and inp.daily.dtype == np.float64
    assert inp.daily.shape[1] == (D - data.DAY0).days
    assert np.isnan(inp.oh[:, :inp.g(date(2026, 1, 1))]).all()          # nothing before the data window
    assert inp.scope_mask(D).sum() == 10


# ------------------------------------------------------------------ store
def _cands(keys, value=1.0, models=select.CANDIDATES):
    return {m: pd.DataFrame({"sku_code": np.repeat([k[0] for k in keys], 7), "fc_code": np.repeat([k[1] for k in keys], 7),
                             "horizon": np.tile(np.arange(1, 8), len(keys)), "value": value + i})
            for i, m in enumerate(models)}


def test_store_round_trip_idempotent_scope_conflict_and_retention():
    keys = [("S01", "FC1"), ("S00", "FC2")]
    d = date(2026, 10, 1)
    n = store.write_day(SCOPE, d, d - timedelta(days=1), _cands(keys), {}, {"MOC": ["MODEL_PREV_WEEK"]})
    assert n == 2 * 7 * 6
    n2 = store.write_day(SCOPE, d, d - timedelta(days=1), _cands(keys, 2.0), {}, {})        # re-run replaces
    with db.read() as c:
        assert n2 == n and c.execute("SELECT COUNT(*) FROM candidate_forecasts").fetchone()[0] == n
        assert c.execute("SELECT COUNT(*) FROM candidate_runs").fetchone()[0] == 6
        day = store.read_day(c, SCOPE, d)
        assert set(day) == set(select.CANDIDATES) and (day["MOC"]["value"] == 2.0).all()
        assert store.day_complete(c, SCOPE, d, select.CANDIDATES)
    with pytest.raises(errors.Sel2Error) as e:
        store.write_day("OTHER", d, d - timedelta(days=1), _cands(keys), {}, {})
    assert e.value.code == "SEL2_SCOPE_CONFLICT"
    with pytest.raises(ValueError):
        store.write_day(SCOPE, d, d, _cands(keys), {}, {})                    # data_as_of must be < D
    store.write_day(SCOPE, d + timedelta(days=100), d + timedelta(days=99), _cands(keys), {}, {})
    r = store.apply_retention(d + timedelta(days=121), 120)
    with db.read() as c:
        assert r["rows"] == n and c.execute("SELECT MIN(forecast_date) FROM candidate_forecasts").fetchone()[0] == \
            str(d + timedelta(days=100))


def test_history_reader_is_integer_keyed_and_select_matches_the_frame_path():
    rng = np.random.default_rng(3)
    keys = [(f"S{i:02d}", "FC1") for i in range(6)]
    d = date(2026, 10, 20)
    frames = []
    for j in range(1, 35):
        fd = d - timedelta(days=j)
        cs = {m: f.assign(value=rng.gamma(1.0, 2.0, len(f))) for m, f in _cands(keys).items()}
        store.write_day(SCOPE, fd, fd - timedelta(days=1), cs, {}, {})
        for m, f in cs.items():
            frames.append(f.assign(model=m, forecast_date=str(fd),
                                   target_date=[str(fd + timedelta(days=int(h) - 1)) for h in f["horizon"]]))
    hist = pd.concat(frames, ignore_index=True)
    sk = pd.DataFrame(keys, columns=["sku_code", "fc_code"])
    today = {m: f.assign(value=1.0 + i) for i, (m, f) in enumerate(_cands(keys).items())}
    days = [d - timedelta(days=i) for i in range(1, 29)]
    act = pd.DataFrame([(k[0], k[1], x, float(rng.poisson(2))) for k in keys for x in days],
                       columns=["sku_code", "fc_code", "date", "qty"])
    opn = act[["sku_code", "fc_code", "date"]]
    with db.read() as c:
        h = store.History(c, SCOPE, d)
        kf, arr = h("MOC")
        assert arr["kid"].dtype == np.int32 and arr["f"].dtype == np.int16 and arr["horizon"].dtype == np.int8
        assert len(arr["kid"]) == 34 * 6 * 7 and arr["f"].min() == -34
        a = select.select_day(d, sk, today, h, act, opn, {})
    b = select.select_day(d, sk, today, hist, act, opn, {})
    pd.testing.assert_frame_equal(a, b)


def test_publish_marks_the_run_sel2():
    sel = pd.DataFrame({"sku_code": ["S1"] * 7, "fc_code": ["FC1"] * 7, "horizon": range(1, 8),
                        "target_date": pd.date_range("2026-11-01", periods=7), "raw_value": [0.1, 1.2] + [2.0] * 5,
                        "published": [0, 2] + [2] * 5, "model_used": ["MOC+DOW4"] * 7, "ok": [True] * 7})
    grp = pd.Series(["A"], index=pd.MultiIndex.from_tuples([("S1", "FC1")]))
    rid, n = store.publish(SCOPE, D, sel, grp, ["OPEN_HOURS_LAG"], "SEL2 MOC=a V33_L112=b V36_two_stage=c",
                           "SEL2:abcdefabcdef", "test")
    with db.read() as c:
        run = db.one(c, "SELECT * FROM forecast_refresh_runs WHERE id=?", (rid,))
        vals = db.rows(c, "SELECT * FROM forecast_refresh_values WHERE run_id=? ORDER BY horizon", (rid,))
        assert store.published_run(c, SCOPE, D)["id"] == rid
    assert run["status"] == "PUBLISHED" and run["config_version"].startswith("SEL2:") and run["n_fallback"] == 0
    assert n == 7 and [v["final_qty"] for v in vals][:2] == [0, 2] and vals[1]["lgb_raw"] == 1.2
    assert {v["method"] for v in vals} == {"MOC+DOW4"} and vals[0]["group_code"] == "A"
    assert vals[0]["flags"] == "OPEN_HOURS_LAG" and vals[6]["target_date"] == "2026-11-07"


# ------------------------------------------------------------------ switch, CLI
def test_emergency_switch_off_runs_nothing():
    assert pipeline.run_day(D, scope_key=SCOPE) == {"status": "SKIPPED", "reason_code": "SEL2_DISABLED"}
    for call in (lambda: pipeline.train_week(date(2026, 10, 26), scope_key=SCOPE),
                 lambda: pipeline.candidates_for_day(D, scope_key=SCOPE), lambda: pipeline.openhours_backfill()):
        with pytest.raises(errors.Sel2Error) as e:
            call()
        assert e.value.code == "SEL2_DISABLED"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM candidate_train_runs").fetchone()[0] == 0


def test_cli_plans_without_yes_and_refuses_bad_arguments(capsys):
    assert cli.main(["sel2-day", "--date", "2026-11-01"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] and out["code"] == "SEL2_CONFIRM_REQUIRED" and out["db"].endswith("app.db")
    assert cli.main(["sel2-train", "--origin", "2026-13-01", "--yes"]) == 2
    capsys.readouterr()
    assert cli.main(["sel2-replay", "--from", "2026-10-10", "--to", "2026-10-01", "--out", "x", "--yes"]) == 2
    capsys.readouterr()
    assert cli.main(["sel2-bootstrap", "--days", "0", "--yes"]) == 2


def test_openhours_backfill_reads_15_day_ranges_oldest_first(sel2_on, monkeypatch):
    from app.bq import aux_sources
    calls = []
    monkeypatch.setattr(aux_sources, "source_modified", lambda cfg=None: "M")
    monkeypatch.setattr(aux_sources, "fetch_open_hours", lambda s, e, cfg=None, source_modified=None, last_day=None:
                        calls.append((s, e, source_modified)) or {"rows": 1, "last_day": str(e)})
    r = pipeline.openhours_backfill(date(2026, 1, 1), date(2026, 1, 31))
    assert calls == [(date(2026, 1, 1), date(2026, 1, 15), "M"), (date(2026, 1, 16), date(2026, 1, 30), "M"),
                     (date(2026, 1, 31), date(2026, 1, 31), "M")]
    assert r["reads"] == 3 and r["last_day"] == "2026-01-31"


# ------------------------------------------------------------------ pipeline (LightGBM on synthetic rows)
def _plenty_of_memory(monkeypatch):
    """The memory gates (training MIN_COMMIT_MB, day run DAY_MIN_COMMIT_MB) read a fake probe with ample free
    commit: the result never depends on this machine's free memory (the gate logic itself: test_v140_t4_fix1 /
    test_v140_t4_fix1_edges)."""
    from app.jobs import resources
    real = resources.snapshot
    monkeypatch.setattr(resources, "snapshot", lambda: {**real(), "commit_avail": 1 << 50})


def test_pipeline_prev_week_publish_no_leak_and_determinism(sel2_on, monkeypatch):
    monkeypatch.setattr(pipeline, "MIN_COMMIT_MB", 0)
    _plenty_of_memory(monkeypatch)
    _seed()
    d = date(2026, 10, 28)
    t = pipeline.train_week(date(2026, 10, 19), scope_key=SCOPE)
    assert t["trained"] == list(pipeline.TRAIN_ORDER)
    assert pipeline.train_week(date(2026, 10, 19), scope_key=SCOPE)["skipped"] == list(pipeline.TRAIN_ORDER)
    c1 = pipeline.candidates_for_day(d, scope_key=SCOPE)
    assert c1["status"] == "STORED" and "MODEL_PREV_WEEK" in c1["flags"]
    with db.read() as c:
        first = {m: f.sort_values(["sku_code", "fc_code", "horizon"]).reset_index(drop=True)
                 for m, f in store.read_day(c, SCOPE, d).items()}
    # rows of D and later change: same candidates; a change of D-1 changes AVG7
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET qty = qty * 10 WHERE order_date >= ?", (str(d),))
        c.execute("UPDATE open_hours_daily SET total_open_hours = 3 WHERE open_date >= ?", (str(d),))
    pipeline.candidates_for_day(d, scope_key=SCOPE, force=True)
    with db.read() as c:
        again = {m: f.sort_values(["sku_code", "fc_code", "horizon"]).reset_index(drop=True)
                 for m, f in store.read_day(c, SCOPE, d).items()}
    for m in first:
        pd.testing.assert_frame_equal(first[m], again[m])
    res = pipeline.run_day(d, scope_key=SCOPE, trigger="test")
    assert res["status"] == "PUBLISHED" and "MODEL_PREV_WEEK" in res["flags"]
    with db.read() as c:
        run = db.one(c, "SELECT * FROM forecast_refresh_runs WHERE id=?", (res["run_id"],))
        meth = {r[0] for r in c.execute("SELECT DISTINCT method FROM forecast_refresh_values WHERE run_id=?",
                                        (res["run_id"],))}
    assert run["config_version"].startswith("SEL2:") and meth == {"FALLBACK:V33_L112"}     # no history yet
    assert pipeline.run_day(d, scope_key=SCOPE)["status"] == "ALREADY_PUBLISHED"
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET qty = qty + 50 WHERE order_date = ?", (str(d - timedelta(days=1)),))
    pipeline.candidates_for_day(d, scope_key=SCOPE, force=True)
    with db.read() as c:
        changed = store.read_day(c, SCOPE, d)["AVG7"].sort_values(["sku_code", "fc_code", "horizon"])
    assert not np.allclose(changed["value"].to_numpy(), first["AVG7"]["value"].to_numpy())
