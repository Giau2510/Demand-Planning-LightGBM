"""1.4.0 T2b: the SEL2 LightGBM candidates MOC, V33_L112 and V36_two_stage (app/ml/sel2/lgbm.py) train the same models
and give the same forecasts as the research backtest reports/cai-tien-20261031 (ct_run.py train / forecast, streamed
path, application snapshot af835b8), and never read the forecast day or later.

Fixtures (tests/fixtures/sel2, generated outside the repository by running the backtest code on a read-only subset of
the g1 DB copy):
  lgbm_frame.parquet  demand frame of 172 keys (sku x fc: 140 in scope at the origin, 15 entering and 1 leaving scope on
                      the second forecast day, the others never in scope; 86 keys with < 30 rows), window 2026-01-01..2026-09-30, open hours override applied, "od" column,
                      sorted by (od, sku_id, fc_id) as the backtest's Data
  lgbm_expected.npz   expected_json: per candidate the resolved configuration (af835b8), feature names, training rows,
                      series, panel sku / fc codes and the sha256 of every model text (origin 2026-09-07); scope keys of
                      the origin and of the forecast days 2026-09-07 / 2026-09-10; arrays "<candidate>|<day>|value"
                      (+ prob / qty of V36; its value = qty where prob >= 0.6, as scoring.py applies it)"""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.ml.sel2 import lgbm

FIX = Path(__file__).parent / "fixtures" / "sel2"
ORIGIN = date(2026, 9, 7)
DAYS = [date(2026, 9, 7), date(2026, 9, 10)]
TOL = 0


def sha(booster) -> str:
    return hashlib.sha256(booster.model_to_string().encode("utf-8")).hexdigest()


def keys_of(rows) -> list[tuple[str, str]]:
    return [tuple(k) for k in rows]


@pytest.fixture(scope="module")
def fx():
    if not FIX.is_dir():   # real-data sample, kept outside Git (owner 04/11): a clone without it skips
        pytest.skip("tests/fixtures/sel2 is not in this checkout")
    frame = pd.read_parquet(FIX / "lgbm_frame.parquet")
    with np.load(FIX / "lgbm_expected.npz", allow_pickle=False) as z:
        arr = {k: z[k] for k in z.files}
    exp = json.loads(str(arr.pop("expected_json")))
    scope = {date.fromisoformat(d): set(keys_of(v)) for d, v in exp["scope_keys"].items()}
    return {"frame": frame, "exp": exp, "arr": arr, "scope": scope}


@pytest.fixture(scope="module")
def trained(fx):
    return {v: lgbm.train(fx["frame"], ORIGIN, fx["scope"][ORIGIN], lgbm.CANDIDATE_SPECS[v]) for v in lgbm.CANDIDATE_SPECS}


def test_candidate_specs():
    s = lgbm.CANDIDATE_SPECS
    assert set(s) == {"MOC", "V33_L112", "V36_two_stage"}
    assert (s["MOC"]["n_origins"], s["V33_L112"]["n_origins"], s["V36_two_stage"]["n_origins"]) == (12, 16, 16)
    assert not s["MOC"]["robust"] and not s["MOC"]["dayprof"] and s["MOC"]["model"] == "lgbm"
    assert s["V33_L112"]["robust"] and s["V33_L112"]["dayprof"] and s["V33_L112"]["model"] == "lgbm"
    assert s["V36_two_stage"]["model"] == "two_stage" and s["V36_two_stage"]["p_threshold"] == 0.6


def test_pinned_settings_do_not_read_live_settings(fx):
    """The pinned settings are the g1 copy's model settings of the backtest (+ the 1.3.1 way to drop sku_code and weight
    horizons <= 7 by 3.0); nothing is read from the application's settings."""
    p = lgbm.pinned_settings()
    for k, v in fx["exp"]["mcfg"].items():
        assert getattr(p, k) == v, k
    assert (p.feature_sku_code, p.horizon_weight_short, p.horizon_weight_cutoff, p.num_threads) == (False, 3.0, 7, 0)
    assert not p.feature_table


@pytest.mark.parametrize("v", ["MOC", "V33_L112", "V36_two_stage"])
def test_training_identical_to_backtest(fx, trained, v):
    models, info = trained[v]
    e = fx["exp"][v]
    assert info["names"] == e["names"] and "sku_code" not in info["names"]
    assert info["n_rows"] == e["n_rows"] and info["n_series"] == e["n_series"]
    assert info.get("n_rows_positive") == e["n_rows_positive"]
    assert info["label_sum"] == e["label_sum"]
    assert info["sku_codes"] == e["sku_codes"] and info["fc_codes"] == e["fc_codes"]
    assert info["decisions"] == e["decisions"]
    cfg = info["cfg"]
    for k, val in e["cfg"].items():                       # every af835b8 field resolved to the same value
        assert getattr(cfg, k) == val, k
    assert set(models) == set(e["models"])
    for nm, m in models.items():
        assert m.feature_name() == e["names"]
        assert sha(m) == e["models"][nm], f"{v} {nm}: model text differs from the backtest"


@pytest.mark.parametrize("v", ["MOC", "V33_L112", "V36_two_stage"])
@pytest.mark.parametrize("D", DAYS)
def test_forecast_identical_to_backtest(fx, trained, v, D):
    models, info = trained[v]
    f = lgbm.forecast(fx["frame"], D, fx["scope"][D], models, lgbm.CANDIDATE_SPECS[v], info)
    e = fx["exp"][v]["days"][str(D)]
    assert keys_of(f["keys"]) == keys_of(e["keys"])
    assert set(f["keys"]) == fx["scope"][D]
    assert [str(x.date()) for x in f["dates"]] == e["dates"] == [str(D + timedelta(days=h)) for h in range(7)]
    assert f["value"].dtype == np.float64 and f["value"].shape == (len(e["keys"]), 7)
    assert np.all(f["value"] >= 0)
    np.testing.assert_allclose(f["value"], fx["arr"][f"{v}|{D}|value"], rtol=0, atol=TOL)
    if v == "V36_two_stage":
        np.testing.assert_allclose(f["prob"], fx["arr"][f"{v}|{D}|prob"], rtol=0, atol=TOL)
        np.testing.assert_allclose(f["qty"], fx["arr"][f"{v}|{D}|qty"], rtol=0, atol=TOL)
        assert np.array_equal(f["value"], np.where(f["prob"] >= 0.6, f["qty"], 0.0))
        assert ((f["prob"] < 0.6) & (f["qty"] > 0)).any()          # the rule is exercised on the fixture
    else:
        assert "prob" not in f


def _changed(frame: pd.DataFrame, rows: np.ndarray) -> pd.DataFrame:
    g = frame.copy()
    g.loc[rows, "qty"] = g.loc[rows, "qty"] * 7 + 3
    g.loc[rows, "open_hours"] = g.loc[rows, "open_hours"] + 1.5
    g.loc[rows, "customer_count"] = g.loc[rows, "customer_count"] + 2
    return g


@pytest.mark.parametrize("v", ["MOC", "V36_two_stage"])
def test_forecast_reads_no_row_from_the_forecast_day_on(fx, trained, v):
    models, info = trained[v]
    D = DAYS[1]
    spec = lgbm.CANDIDATE_SPECS[v]
    base = lgbm.forecast(fx["frame"], D, fx["scope"][D], models, spec, info)
    od = fx["frame"]["od"]
    after = _changed(fx["frame"], (od >= pd.Timestamp(D)).to_numpy())
    f = lgbm.forecast(after, D, fx["scope"][D], models, spec, info)
    assert np.array_equal(f["value"], base["value"])
    prev = _changed(fx["frame"], (od == pd.Timestamp(D - timedelta(days=1))).to_numpy())
    g = lgbm.forecast(prev, D, fx["scope"][D], models, spec, info)
    assert not np.array_equal(g["value"], base["value"])


def test_training_is_deterministic_and_reads_no_row_from_the_origin_on(fx, trained):
    """A second training (frame rows from the origin on changed) gives the same model text as the first one."""
    od = fx["frame"]["od"]
    after = _changed(fx["frame"], (od >= pd.Timestamp(ORIGIN)).to_numpy())
    models, info = lgbm.train(after, ORIGIN, fx["scope"][ORIGIN], lgbm.CANDIDATE_SPECS["MOC"])
    assert sha(models["reg"]) == sha(trained["MOC"][0]["reg"]) == fx["exp"]["MOC"]["models"]["reg"]
    assert info["panel_last_day"] == str(ORIGIN - timedelta(days=1))
    assert info["label_end"] < str(ORIGIN)


def test_scope_filters_the_training_panel(fx, trained):
    _, info = trained["MOC"]
    assert set(keys_of(info["panel_keys"])) == fx["scope"][ORIGIN]
    assert keys_of(info["panel_keys"]) == keys_of(fx["exp"]["MOC"]["panel_keys"])


def test_unsorted_frame_is_refused(fx):
    bad = fx["frame"].iloc[::-1]
    with pytest.raises(ValueError):
        lgbm.rows_before(bad, ORIGIN)
