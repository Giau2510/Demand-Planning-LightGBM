"""1.4.0 T9 (D2): end-to-end leakage tests of the SEL2 pipeline on the isolated test DB with synthetic BIGQUERY-like
rows and real (small) LightGBM trainings (integration with fakes; no BigQuery, no live data).

  * forecast day D: the candidates and the selection of D are identical (exact) when the rows ON and AFTER D change
    (values x10, deletes, new rows, a new key, open hours, row order); a change of a D-1 row changes the forecast of D
  * weekly batch: the models of origin O are identical (model file sha256) when the rows >= O change, even when the
    inputs handed to the training hold those rows
  * per day: two days of the same week use the same trainings but their own data cut-off (D-1)"""
from datetime import date, timedelta

import json

import numpy as np
import pandas as pd

from app import db
from app.ml.sel2 import pipeline, select, store

from test_v140_t4a_pipeline import SCOPE, _seed   # tests/ is on sys.path (prepend import mode)

O = date(2026, 10, 26)          # Monday = training origin (retrain_weekday 1)
D = date(2026, 10, 28)          # Wednesday of the same week
NEW = "S99"                     # a key that appears only on and after the mutated day


def _sorted(f: pd.DataFrame) -> pd.DataFrame:
    return f.sort_values(["sku_code", "fc_code", "horizon"]).reset_index(drop=True)


def _day(d):
    with db.read() as c:
        return {m: _sorted(f) for m, f in store.read_day(c, SCOPE, d).items()}


def _runs(d):
    with db.read() as c:
        return {r["model"]: r for r in store.day_runs(c, SCOPE, d)}


def _mutate_from(day: date):
    """Rows on and after `day`: values x10, deletes, new rows (also a new key), open hours changed / deleted / added;
    then every demand and open-hours row is re-inserted in reverse order (rowid order changes for all rows)."""
    from app.bq.aux_sources import open_hours_source
    tbl, seller = open_hours_source()
    d0 = str(day)
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET qty = qty * 10 WHERE order_date >= ?", (d0,))
        c.execute("DELETE FROM demand_daily WHERE order_date >= ? AND sku_id IN ('S01', 'S02')", (d0,))
        c.execute("UPDATE open_hours_daily SET total_open_hours = 3 WHERE open_date >= ?", (d0,))
        c.execute("DELETE FROM open_hours_daily WHERE open_date >= ? AND sku_code = 'S03'", (d0,))
        last = c.execute("SELECT MAX(order_date) FROM demand_daily").fetchone()[0]
        t = day
        while str(t) <= last:
            for sku, fc in [(f"S{i:02d}", "FC1" if i % 2 else "FC2") for i in range(4, 10)] + [(NEW, "FC1")]:
                c.execute("INSERT OR IGNORE INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, "
                          "n_orders, loaded_at, open_hours, open_hours_status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (SCOPE, "BIGQUERY", str(t), sku, fc, 77.0, 3, "x", 10.0, "OK"))
            c.execute("INSERT OR IGNORE INTO open_hours_daily(source_table, seller_code, fc_code, sku_code, open_date, "
                      "total_open_hours, n_items, loaded_at) VALUES (?,?,?,?,?,?,?,?)",
                      (tbl, seller, "FC1", NEW, str(t), 12.0, 1, "x"))
            t += timedelta(days=1)
        for table in ("demand_daily", "open_hours_daily"):
            c.execute(f"CREATE TEMP TABLE t9_copy AS SELECT * FROM {table} ORDER BY rowid DESC")
            c.execute(f"DELETE FROM {table}")
            c.execute(f"INSERT INTO {table} SELECT * FROM t9_copy ORDER BY rowid")
            c.execute("DROP TABLE t9_copy")


def _fake_history(d: date, keys: pd.DataFrame):
    """Candidate days d-34 .. d-1 with deterministic synthetic values (different per model), so that the selection of
    d chooses between candidates instead of the < 14 days fallback."""
    rng = np.random.default_rng(11)
    base = rng.uniform(0.2, 4.0, len(keys))
    for i in range(34, 0, -1):
        day = d - timedelta(days=i)
        cands = {}
        for j, m in enumerate(select.CANDIDATES):
            v = np.repeat(base * (0.6 + 0.2 * j), 7) * rng.uniform(0.8, 1.2, 7 * len(keys))
            cands[m] = pd.DataFrame({"sku_code": np.repeat(keys["sku_code"].to_numpy(), 7),
                                     "fc_code": np.repeat(keys["fc_code"].to_numpy(), 7),
                                     "horizon": np.tile(np.arange(1, 8), len(keys)), "value": v})
        store.write_day(SCOPE, day, day - timedelta(days=1), cands, {}, {})


def _select(d):
    return pipeline.select_and_publish(d, publish=False, scope_key=SCOPE)["selection"].reset_index(drop=True)


def _train_files():
    with db.read() as c:
        return {r[0]: (r[1], r[2], r[3]) for r in c.execute(
            "SELECT model, model_files_json, fingerprint, data_as_of FROM candidate_train_runs WHERE status='SUCCEEDED' "
            "AND origin_date=?", (str(O),))}


def test_day_d_ignores_rows_on_and_after_d_and_follows_d_minus_1(sel2_on, monkeypatch):
    monkeypatch.setattr(pipeline, "MIN_COMMIT_MB", 0)
    _seed()
    pipeline.train_week(O, scope_key=SCOPE)
    keys = pipeline.load(SCOPE, D).scope_keys(D)
    _fake_history(D, keys)
    assert pipeline.candidates_for_day(D, scope_key=SCOPE)["status"] == "STORED"
    first, runs1, sel1 = _day(D), _runs(D), _select(D)
    assert set(first) == set(select.CANDIDATES) and all(r["data_as_of"] == str(D - timedelta(days=1))
                                                        for r in runs1.values())
    assert not sel1["model_used"].str.startswith("FALLBACK:").all()          # a real choice between candidates

    _mutate_from(D)
    with db.read() as c:                                                      # the mutation really happened
        assert c.execute("SELECT COUNT(*) FROM demand_daily WHERE sku_id=?", (NEW,)).fetchone()[0] > 0
    assert pipeline.candidates_for_day(D, scope_key=SCOPE, force=True)["status"] == "STORED"
    again, runs2 = _day(D), _runs(D)
    for m in first:
        pd.testing.assert_frame_equal(first[m], again[m], check_exact=True)
    assert {m: r["train_run_id"] for m, r in runs1.items()} == {m: r["train_run_id"] for m, r in runs2.items()}
    pd.testing.assert_frame_equal(sel1, _select(D), check_exact=True)

    # a D-1 row changes: the candidates (LightGBM and simple) and the selected raw values of D change
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET qty = qty + 50 WHERE order_date = ?", (str(D - timedelta(days=1)),))
    pipeline.candidates_for_day(D, scope_key=SCOPE, force=True)
    changed = _day(D)
    for m in ("MOC", "AVG7"):
        assert not np.array_equal(changed[m]["value"].to_numpy(), first[m]["value"].to_numpy()), m
    assert not np.array_equal(_select(D)["raw_value"].to_numpy(), sel1["raw_value"].to_numpy())


def test_weekly_models_ignore_rows_after_origin_and_days_keep_their_own_cutoff(sel2_on, monkeypatch):
    monkeypatch.setattr(pipeline, "MIN_COMMIT_MB", 0)
    _seed()
    t = pipeline.train_week(O, scope_key=SCOPE, inputs=pipeline.load(SCOPE, O))
    assert t["trained"] == list(pipeline.TRAIN_ORDER)
    trained = _train_files()
    assert all(v[2] == str(O - timedelta(days=1)) for v in trained.values())       # data_as_of = O-1

    # per day: D-1 and D of the same week, same trainings, their own cut-off
    d1 = D - timedelta(days=1)
    for d in (d1, D):
        pipeline.candidates_for_day(d, scope_key=SCOPE)
    r1, r2 = _runs(d1), _runs(D)
    for m in pipeline.TRAIN_ORDER:
        n = pipeline.NAME[m]
        assert r1[n]["train_run_id"] == r2[n]["train_run_id"] is not None
        assert "MODEL_PREV_WEEK" not in (r1[n]["flags"] or "")
    assert {r["data_as_of"] for r in r1.values()} == {str(d1 - timedelta(days=1))}
    assert {r["data_as_of"] for r in r2.values()} == {str(D - timedelta(days=1))}
    a1, a2 = _day(d1), _day(D)
    with db.tx() as c:                                    # a row of d1: inside the cut-off of D only
        c.execute("UPDATE demand_daily SET qty = qty + 50 WHERE order_date = ?", (str(d1),))
    for d in (d1, D):
        pipeline.candidates_for_day(d, scope_key=SCOPE, force=True)
    b1, b2 = _day(d1), _day(D)
    for m in a1:
        pd.testing.assert_frame_equal(a1[m], b1[m], check_exact=True)
    assert not np.array_equal(a2["MOC"]["value"].to_numpy(), b2["MOC"]["value"].to_numpy())

    # per batch: rows >= O change, the trainings are redone with inputs that hold those rows -> same model files
    _mutate_from(O)
    with db.tx() as c:                                    # test DB only: let train_week train the origin again
        c.execute("UPDATE candidate_train_runs SET status='FAILED' WHERE origin_date=?", (str(O),))
    later = pipeline.load(SCOPE, date(2026, 11, 1))
    assert NEW in set(later.keys["sku_code"])                                  # the inputs do hold the new rows
    t2 = pipeline.train_week(O, scope_key=SCOPE, inputs=later)
    assert t2["trained"] == list(pipeline.TRAIN_ORDER)
    again = _train_files()
    for m in pipeline.TRAIN_ORDER:
        f1, f2 = json.loads(trained[m][0]), json.loads(again[m][0])
        assert {p: x["sha256"] for p, x in f1.items()} == {p: x["sha256"] for p, x in f2.items()}, m
        assert trained[m][1:] == again[m][1:], m                                 # fingerprint, data_as_of
