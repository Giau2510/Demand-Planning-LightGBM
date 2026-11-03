"""1.4.0 T2b edge cases of the SEL2 LightGBM candidates (app/ml/sel2/lgbm.py), beyond test_v140_t2b_lgbm.py:
OPEN_HOURS_INVALID before the origin (any row, in scope or not; rows from the origin on are not checked), unsorted
frame, empty scope at the origin / at D, a series in scope at D with an FC code unknown to the training panel (code -1,
the other series keep the training codes, as ct_run.py:578 overwrites the forecast panel's codes), V33_L112 reads no
row from D on, the V36 threshold exactly at 0.6, and the pinned configuration (the live "model" / "feature_table"
settings are never read). Trainings use a 12-series subset of the fixture frame (a few seconds each)."""
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app import settings_service as ss
from app.ml.sel2 import lgbm

FIX = Path(__file__).parent / "fixtures" / "sel2"
ORIGIN = date(2026, 9, 7)
D2 = date(2026, 9, 10)


def sha(booster) -> str:
    return hashlib.sha256(booster.model_to_string().encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def fx():
    frame = pd.read_parquet(FIX / "lgbm_frame.parquet")
    with np.load(FIX / "lgbm_expected.npz", allow_pickle=False) as z:
        exp = json.loads(str(z["expected_json"]))
    scope = {date.fromisoformat(d): [tuple(k) for k in v] for d, v in exp["scope_keys"].items()}
    o = scope[ORIGIN]
    sub = [k for k in o if k[1] == "BD"][:6] + [k for k in o if k[1] == "HN"][:6]
    assert len(sub) == 12 and all(k in set(scope[D2]) for k in sub)
    return {"frame": frame, "scope": scope, "sub": sub}


@pytest.fixture(scope="module")
def tiny(fx):
    """MOC and V33_L112 trained on the 12-series subset at the origin."""
    return {v: lgbm.train(fx["frame"], ORIGIN, fx["sub"], lgbm.CANDIDATE_SPECS[v]) for v in ("MOC", "V33_L112")}


def _resort(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(["od", "sku_id", "fc_id"], kind="stable").reset_index(drop=True)


# ------------------------------------------------------------------ refused inputs (no training)
@pytest.mark.parametrize("in_scope", [True, False])
def test_open_hours_missing_before_the_origin_is_refused(fx, in_scope):
    f = fx["frame"].copy()
    sub = set(fx["sub"])
    keys = list(zip(f["sku_id"], f["fc_id"]))
    m = (f["od"] < pd.Timestamp(ORIGIN)).to_numpy() & np.array([(k in sub) == in_scope for k in keys])
    f.loc[np.nonzero(m)[0][-1], "open_hours"] = np.nan        # one row, the last one before the origin
    with pytest.raises(ValueError, match=f"OPEN_HOURS_INVALID before {ORIGIN}"):
        lgbm.train(f, ORIGIN, fx["sub"], lgbm.CANDIDATE_SPECS["MOC"])


def test_open_hours_missing_from_the_origin_on_is_not_read(fx, tiny):
    f = fx["frame"].copy()
    f.loc[(f["od"] >= pd.Timestamp(ORIGIN)).to_numpy(), "open_hours"] = np.nan
    models, _ = lgbm.train(f, ORIGIN, fx["sub"], lgbm.CANDIDATE_SPECS["MOC"])
    assert sha(models["reg"]) == sha(tiny["MOC"][0]["reg"])


def test_unsorted_frame_is_refused_by_train_and_forecast(fx, tiny):
    f = fx["frame"].copy()
    i = int(np.nonzero((f["od"] == f["od"].iloc[-1]).to_numpy())[0][0])
    f = pd.concat([f.iloc[i:i + 1], f.drop(index=i)], ignore_index=True)      # one late row moved to the top
    with pytest.raises(ValueError, match="not sorted"):
        lgbm.train(f, ORIGIN, fx["sub"], lgbm.CANDIDATE_SPECS["MOC"])
    models, info = tiny["MOC"]
    with pytest.raises(ValueError, match="not sorted"):
        lgbm.forecast(f, D2, fx["sub"], models, lgbm.CANDIDATE_SPECS["MOC"], info)


@pytest.mark.parametrize("scope", [[], [("NO.SUCH.SKU", "BD")]])
def test_empty_scope_at_the_origin_is_refused(fx, scope):
    with pytest.raises(ValueError):
        lgbm.train(fx["frame"], ORIGIN, scope, lgbm.CANDIDATE_SPECS["MOC"])


def test_no_demand_row_before_the_origin_is_refused(fx):
    with pytest.raises(ValueError, match="no demand row"):
        lgbm.train(fx["frame"], date(2026, 1, 1), fx["sub"], lgbm.CANDIDATE_SPECS["MOC"])


# ------------------------------------------------------------------ forecast scope
@pytest.mark.parametrize("v, spec", [("MOC", "MOC"), ("V33_L112", "V33_L112"), ("V33_L112", "V36_two_stage")])
def test_empty_scope_at_d_gives_an_empty_forecast(fx, tiny, v, spec):
    _, info = tiny[v]
    models = {"reg": None, "clf": None} if spec == "V36_two_stage" else {"reg": None}   # never called
    f = lgbm.forecast(fx["frame"], D2, [], models, lgbm.CANDIDATE_SPECS[spec], info)
    assert f["keys"] == [] and f["value"].shape == (0, 7)
    assert [x.date() for x in f["dates"]] == [D2 + timedelta(days=h) for h in range(7)]
    assert (("prob" in f) and ("qty" in f)) == (spec == "V36_two_stage")
    if spec == "V36_two_stage":
        assert f["prob"].shape == f["qty"].shape == (0, 7)


def test_scope_key_without_any_row_before_d_is_not_output(fx, tiny):
    models, info = tiny["MOC"]
    spec = lgbm.CANDIDATE_SPECS["MOC"]
    base = lgbm.forecast(fx["frame"], D2, fx["sub"], models, spec, info)
    f = lgbm.forecast(fx["frame"], D2, fx["sub"] + [("NO.SUCH.SKU", "HN")], models, spec, info)
    assert f["keys"] == base["keys"] and np.array_equal(f["value"], base["value"])


class _Spy:
    """Wraps a booster; records every matrix given to predict."""

    def __init__(self, booster):
        self.b, self.X = booster, []

    def predict(self, X):
        self.X.append(np.array(X))
        return self.b.predict(X)


def test_unknown_fc_code_at_d_uses_minus_one_and_keeps_the_training_codes(fx, tiny):
    """A series in scope at D whose FC ("CT", sorted between BD and HN) is absent from the training panel: its fc_code
    is -1, and HN keeps the training code 1 (the forecast panel alone would code BD 0 / CT 1 / HN 2)."""
    models, info = tiny["MOC"]
    spec = lgbm.CANDIDATE_SPECS["MOC"]
    assert info["fc_codes"] == {"BD": 0, "HN": 1}
    src = next(k for k in fx["sub"] if k[1] == "HN")
    new = (src[0], "CT")
    f = fx["frame"]
    extra = f[(f["sku_id"] == src[0]) & (f["fc_id"] == "HN")].assign(fc_id="CT")
    g = _resort(pd.concat([f, extra], ignore_index=True))

    spy_b = _Spy(models["reg"])
    base = lgbm.forecast(f, D2, fx["sub"], {"reg": spy_b}, spec, info)
    spy = _Spy(models["reg"])
    out = lgbm.forecast(g, D2, fx["sub"] + [new], {"reg": spy}, spec, info)
    keys = list(out["keys"])
    assert set(keys) == set(fx["sub"]) | {new}
    fci = info["names"].index("fc_code")
    pos = {k: i for i, k in enumerate(keys)}
    bpos = {k: i for i, k in enumerate(base["keys"])}
    for X, Xb in zip(spy.X, spy_b.X):
        assert X[pos[new], fci] == -1
        for k in fx["sub"]:
            assert X[pos[k], fci] == info["fc_codes"][k[1]]
            assert np.array_equal(X[pos[k]], Xb[bpos[k]], equal_nan=True)     # other series' rows unchanged
    for k in fx["sub"]:
        assert np.array_equal(out["value"][pos[k]], base["value"][bpos[k]])
    v = out["value"][pos[new]]
    assert np.isfinite(v).all() and (v >= 0).all()
    # the new series has the same history as its HN source: only the FC code differs in its rows
    for X in spy.X:
        a, b = X[pos[new]].copy(), X[pos[src]].copy()
        a[fci] = b[fci] = 0
        assert np.array_equal(a, b, equal_nan=True)


# ------------------------------------------------------------------ no leak (V33_L112)
def _changed(frame: pd.DataFrame, rows: np.ndarray) -> pd.DataFrame:
    g = frame.copy()
    g.loc[rows, "qty"] = g.loc[rows, "qty"] * 7 + 3
    g.loc[rows, "open_hours"] = g.loc[rows, "open_hours"] + 1.5
    g.loc[rows, "customer_count"] = g.loc[rows, "customer_count"] + 2
    return g


def test_v33_forecast_reads_no_row_from_the_forecast_day_on(fx, tiny):
    models, info = tiny["V33_L112"]
    spec = lgbm.CANDIDATE_SPECS["V33_L112"]
    od = fx["frame"]["od"]
    base = lgbm.forecast(fx["frame"], D2, fx["sub"], models, spec, info)
    after = _changed(fx["frame"], (od >= pd.Timestamp(D2)).to_numpy())
    after.loc[(od >= pd.Timestamp(D2)).to_numpy(), "open_hours"] = np.nan
    f = lgbm.forecast(after, D2, fx["sub"], models, spec, info)
    assert np.array_equal(f["value"], base["value"])
    prev = _changed(fx["frame"], (od == pd.Timestamp(D2 - timedelta(days=1))).to_numpy())
    g = lgbm.forecast(prev, D2, fx["sub"], models, spec, info)
    assert not np.array_equal(g["value"], base["value"])


# ------------------------------------------------------------------ V36 threshold
class _Const:
    def __init__(self, values):
        self.v = np.asarray(values, dtype=float)

    def predict(self, X):
        return np.resize(self.v, X.shape[0])


def test_v36_threshold_exactly_at_0_6(fx, tiny):
    """value = qty where prob >= 0.6 (0.6 itself included), 0 below; the regression output is clipped at 0 first."""
    _, info = tiny["V33_L112"]                       # V36 has the V33_L112 columns
    spec = lgbm.CANDIDATE_SPECS["V36_two_stage"]
    below = np.nextafter(0.6, 0.0)
    probs = [0.6, below, 0.61, 0.0, 1.0, 0.6]
    qtys = [5.0, 5.0, 2.5, 7.0, -3.0, 0.0]
    f = lgbm.forecast(fx["frame"], D2, fx["sub"], {"clf": _Const(probs), "reg": _Const(qtys)}, spec, info)
    S = len(f["keys"])
    p = np.resize(np.array(probs), S)
    q = np.clip(np.resize(np.array(qtys), S), 0, None)
    for h in range(7):
        assert np.array_equal(f["prob"][:, h], p)
        assert np.array_equal(f["qty"][:, h], q)
        assert np.array_equal(f["value"][:, h], np.where(p >= 0.6, q, 0.0))
    assert f["value"][0, 0] == 5.0 and f["value"][1, 0] == 0.0        # 0.6 kept, just below 0.6 dropped
    assert f["value"][4, 0] == 0.0 and (f["value"] >= 0).all()         # negative quantity clipped


def test_forecast_refuses_columns_of_another_candidate(fx, tiny):
    models, info = tiny["MOC"]
    with pytest.raises(ValueError, match="columns differ"):
        lgbm.forecast(fx["frame"], D2, fx["sub"], models, lgbm.CANDIDATE_SPECS["V33_L112"], info)


# ------------------------------------------------------------------ pinned configuration
def test_live_model_settings_do_not_change_the_trained_model(fx, tiny, monkeypatch):
    ss.update("model", {"num_boost_round": 20, "learning_rate": 0.3, "num_leaves": 7, "objective": "regression",
                        "forecast_strategy": "DIRECT", "feature_sku_code": True, "direct_origins": 3,
                        "max_train_days": 120, "horizon_weight_short": 1.5, "horizon_weight_cutoff": 14,
                        "feature_open_hours": False, "num_threads": 1})
    ss.save("feature_table", {"features": {"price_last": {"enabled": False, "contri": 1.0}}})
    assert ss.get("model").num_boost_round == 20

    def boom(*a, **k):
        raise AssertionError("lgbm read a live settings section")
    monkeypatch.setattr(ss, "get", boom)
    models, info = lgbm.train(fx["frame"], ORIGIN, fx["sub"], lgbm.CANDIDATE_SPECS["MOC"])
    ref_models, ref_info = tiny["MOC"]
    assert sha(models["reg"]) == sha(ref_models["reg"])
    assert info["names"] == ref_info["names"] and "sku_code" not in info["names"]
    assert info["cfg"].num_boost_round == 300 and info["cfg"].direct_origins == 12
    f = lgbm.forecast(fx["frame"], D2, fx["sub"], models, lgbm.CANDIDATE_SPECS["MOC"], info)
    g = lgbm.forecast(fx["frame"], D2, fx["sub"], ref_models, lgbm.CANDIDATE_SPECS["MOC"], ref_info)
    assert np.array_equal(f["value"], g["value"])
