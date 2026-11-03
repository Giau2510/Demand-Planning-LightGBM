"""1.4.0 T4a: SEL2 replay (reproduction on a DB copy), bootstrap (first start, resumable) and the selection window
settings (sel2_pipeline.window_days / min_days) - isolated test DB, synthetic rows, LightGBM trained for real (unit /
integration with fakes)."""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app import db
from app import settings_service as ss
from app.ml.sel2 import pipeline, select, store
from test_v140_t4a_pipeline import SCOPE, _cands, _seed


def test_backtest_history_start_rule():
    assert pipeline.backtest_history_start(date(2026, 10, 5)) == date(2026, 8, 27)
    assert pipeline.backtest_history_start(date(2026, 10, 22)) == date(2026, 8, 27)
    assert pipeline.backtest_history_start(date(2026, 6, 10)) == date(2026, 6, 1)       # floor 2026-06-01
    assert pipeline.backtest_history_start(date(2026, 7, 15)) == date(2026, 6, 1)


def test_replay_trains_the_monday_grid_writes_parquet_and_is_deterministic(sel2_on, monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "MIN_COMMIT_MB", 0)
    _seed(end=date(2026, 6, 30))
    r = pipeline.replay(date(2026, 6, 10), date(2026, 6, 23), tmp_path / "a", history_start_rule="BACKTEST",
                        scope_key=SCOPE)
    assert r["candidates_from"] == "2026-06-01"
    with db.read() as c:
        origins = sorted({x[0] for x in c.execute("SELECT origin_date FROM candidate_train_runs WHERE "
                                                  "status='SUCCEEDED'")})
        n_tr = c.execute("SELECT COUNT(*) FROM candidate_train_runs").fetchone()[0]
        assert c.execute("SELECT COUNT(*) FROM forecast_refresh_runs").fetchone()[0] == 0       # nothing published
    assert origins == ["2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22"] and n_tr == 12   # Mondays only
    sel = pd.read_parquet(tmp_path / "a" / "selected.parquet")
    cand = pd.read_parquet(tmp_path / "a" / "candidates.parquet")
    assert sorted(sel["forecast_date"].unique()) == [str(date(2026, 6, 10) + timedelta(days=i)) for i in range(14)]
    assert cand["forecast_date"].min() == "2026-06-01" and set(cand["model"]) == set(select.CANDIDATES)
    assert len(sel) == r["selected_rows"] and len(cand) == r["candidate_rows"]
    # with 22 days of history from 2026-06-01, the last days choose between candidates (ok >= 14 days)
    last = sel[sel["forecast_date"] == "2026-06-23"]
    assert last["ok"].any() and not last["model_used"].str.startswith("FALLBACK:").all()
    first = sel[sel["forecast_date"] == "2026-06-10"]
    assert (~first["ok"]).all()                                               # 9 days of history: fallback
    # the second run trains and computes nothing again and selects the same
    r2 = pipeline.replay(date(2026, 6, 10), date(2026, 6, 23), tmp_path / "b", history_start_rule="BACKTEST",
                         scope_key=SCOPE)
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM candidate_train_runs").fetchone()[0] == n_tr
    pd.testing.assert_frame_equal(sel, pd.read_parquet(tmp_path / "b" / "selected.parquet"))
    pd.testing.assert_frame_equal(cand, pd.read_parquet(tmp_path / "b" / "candidates.parquet"))
    assert r2["selected_rows"] == r["selected_rows"]


def test_bootstrap_is_resumable(sel2_on, monkeypatch):
    monkeypatch.setattr(pipeline, "MIN_COMMIT_MB", 0)
    _seed()
    today = date(2026, 10, 28)
    r = pipeline.bootstrap(8, scope_key=SCOPE, today=today)
    # 1.4.0 (owner 03/11): the origin of today is trained first (it brings the temporary Excel forward), then the others
    assert [t["origin"] for t in r["trainings"]] == ["2026-10-26", "2026-10-19"]
    assert all(t["trained"] == list(pipeline.TRAIN_ORDER) for t in r["trainings"])
    assert r["past_days"] == ["STORED"] * 8 and r["today"]["status"] == "PUBLISHED"
    with db.read() as c:
        days = [x[0] for x in c.execute("SELECT DISTINCT forecast_date FROM candidate_runs ORDER BY 1")]
        assert c.execute("SELECT COUNT(*) FROM forecast_refresh_runs").fetchone()[0] == 1          # today only
        n_cf = c.execute("SELECT COUNT(*) FROM candidate_forecasts").fetchone()[0]
    assert days == [str(today - timedelta(days=i)) for i in range(8, -1, -1)]
    again = pipeline.bootstrap(8, scope_key=SCOPE, today=today)
    assert all(t["skipped"] == list(pipeline.TRAIN_ORDER) and not t["trained"] for t in again["trainings"])
    assert again["past_days"] == ["SKIPPED_DONE"] * 8 and again["today"]["status"] == "ALREADY_PUBLISHED"
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM candidate_train_runs").fetchone()[0] == 6
        assert c.execute("SELECT COUNT(*) FROM candidate_forecasts").fetchone()[0] == n_cf


def _history_case():
    rng = np.random.default_rng(5)
    keys = [(f"S{i:02d}", "FC1") for i in range(8)]
    d = date(2026, 10, 20)
    rows = []
    for j in range(1, 35):
        fd = d - timedelta(days=j)
        for m, f in _cands(keys).items():
            rows.append(f.assign(value=rng.gamma(1.0, 2.0, len(f)), model=m, forecast_date=str(fd),
                                 target_date=[str(fd + timedelta(days=int(h) - 1)) for h in f["horizon"]]))
    hist = pd.concat(rows, ignore_index=True)
    sk = pd.DataFrame(keys, columns=["sku_code", "fc_code"])
    today = {m: f.assign(value=1.0 + i) for i, (m, f) in enumerate(_cands(keys).items())}
    act = pd.DataFrame([(k[0], k[1], d - timedelta(days=i), float(rng.poisson(2))) for k in keys for i in range(1, 29)],
                       columns=["sku_code", "fc_code", "date", "qty"])
    return d, sk, today, hist, act, act[["sku_code", "fc_code", "date"]]


def test_selection_window_settings_default_identical_and_wired():
    d, sk, today, hist, act, opn = _history_case()
    base = select.select_day(d, sk, today, hist, act, opn, {})
    s = ss.Sel2PipelineSettings()
    same = select.select_day(d, sk, today, hist, act, opn, {}, window_days=s.window_days, min_days=s.min_days)
    pd.testing.assert_frame_equal(base, same)
    assert base["ok"].all()
    strict = select.select_day(d, sk, today, hist, act, opn, {}, min_days=28)          # 28 target days: still ok
    assert strict["ok"].all()
    none_ok = select.select_day(d, sk, today, hist, act, opn, {}, window_days=10, min_days=11)
    assert (~none_ok["ok"]).all() and none_ok["model_used"].eq("FALLBACK:V33_L112").all()
    short = select.select_day(d, sk, today, hist, act, opn, {}, window_days=14, min_days=14)
    assert short["ok"].all()


def test_pipeline_passes_the_window_settings(sel2_on, monkeypatch):
    seen = {}
    real = select.select_day

    def spy(*a, **kw):
        seen.update(window_days=kw.get("window_days"), min_days=kw.get("min_days"))
        return real(*a, **kw)
    monkeypatch.setattr(select, "select_day", spy)
    monkeypatch.setattr(pipeline, "MIN_COMMIT_MB", 0)
    ss.update("sel2_pipeline", {"window_days": 21, "min_days": 7}, note="t4a")
    _seed()
    d = date(2026, 10, 28)
    pipeline.train_week(date(2026, 10, 26), scope_key=SCOPE)
    pipeline.candidates_for_day(d, scope_key=SCOPE)
    pipeline.select_and_publish(d, publish=False, scope_key=SCOPE)
    assert seen == {"window_days": 21, "min_days": 7}
