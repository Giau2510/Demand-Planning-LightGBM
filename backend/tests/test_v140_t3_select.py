"""1.4.0 T3: the per-series model choice SEL2 (app/ml/sel2/select.py) gives the forecast FINAL2 of the research backtest
reports/cai-tien-20261031 (code/ct_select.py with the cells of scoring.py) exactly, and never reads the forecast day or
later.

Fixtures (tests/fixtures/sel2/select_*.parquet, generated outside the repository from the backtest outputs):
  select_keys      150 series (key_id, sku_code, fc_code, group of scoring.base_tables, "" = no group -> B): groups
                   A / B / C / none, series out of scope on some forecast days, series with fallbacks after June
  select_history   wide candidate forecasts (key_id, forecast_date, horizon, one column per candidate, NaN = no row;
                   V36_two_stage@0.6 already = qty if prob >= 0.6 else 0), rows whose target day is in D-28 .. D-1 of
                   a forecast day D or whose forecast day is D
  select_actuals   demand (no row = 0), select_open: target days with open hours > 0, select_scope: scope
                   (pham_vi.parquet) of every forecast day used, select_expected: FINAL2 rows of the forecast days
                   2026-06-20, 07-15, 09-15, 10-15 and 10-22"""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.ml.sel2 import select

FIX = Path(__file__).parent / "fixtures" / "sel2"
K = ["sku_code", "fc_code"]
DAYS = [date(2026, 6, 20), date(2026, 7, 15), date(2026, 9, 15), date(2026, 10, 15), date(2026, 10, 22)]


def _hist_from(d: date) -> date:
    # ct_step5.py FINAL2: --hist-from max(2026-06-01, month start - 35 days)
    return max(date(2026, 6, 1), d.replace(day=1) - timedelta(days=35))


@pytest.fixture(scope="module")
def fx():
    keys = pd.read_parquet(FIX / "select_keys.parquet")

    def dec(df):
        out = df.merge(keys[["key_id"] + K], on="key_id", how="left")
        assert out[K].notna().all().all()
        return out.drop(columns=["key_id"])

    wide = dec(pd.read_parquet(FIX / "select_history.parquet"))
    wide["forecast_date"] = pd.to_datetime(wide["forecast_date"])
    wide["target_date"] = wide["forecast_date"] + pd.to_timedelta(wide["horizon"].astype(int) - 1, unit="D")
    hist = []
    for c in select.CANDIDATES:
        h = wide[K + ["forecast_date", "horizon", "target_date", c]].rename(columns={c: "value"})
        h = h[h["value"].notna()].copy()
        h.insert(0, "model", c)
        hist.append(h)
    hist = pd.concat(hist, ignore_index=True)
    groups = {(r.sku_code, r.fc_code): r.group for r in keys.itertuples() if r.group}
    exp = dec(pd.read_parquet(FIX / "select_expected.parquet"))
    exp["forecast_date"] = pd.to_datetime(exp["forecast_date"])
    return {"keys": keys, "hist": hist, "groups": groups, "exp": exp,
            "act": dec(pd.read_parquet(FIX / "select_actuals.parquet")),
            "open": dec(pd.read_parquet(FIX / "select_open.parquet")),
            "scope": dec(pd.read_parquet(FIX / "select_scope.parquet"))}


def _run(fx, d, hist=None, act=None):
    hist = fx["hist"] if hist is None else hist
    today = hist[hist["forecast_date"] == pd.Timestamp(d)]
    cand_today = {c: today[today["model"] == c][K + ["horizon", "value"]] for c in select.CANDIDATES}
    scope_keys = fx["exp"][(fx["exp"]["forecast_date"] == pd.Timestamp(d)) & (fx["exp"]["horizon"] == 1)][K]
    return select.select_day(d, scope_keys, cand_today, hist, fx["act"] if act is None else act, fx["open"],
                             fx["groups"], history_start=_hist_from(d), history_scope=fx["scope"])


@pytest.mark.parametrize("d", DAYS)
def test_identical_to_final2(fx, d):
    got = _run(fx, d)
    exp = fx["exp"][fx["exp"]["forecast_date"] == pd.Timestamp(d)]
    assert len(got) == len(exp) > 0
    m = exp.merge(got, on=K + ["horizon"], how="left", validate="1:1")
    assert m["raw_value"].notna().all()
    assert float(np.abs(m["raw_value"] - m["value"]).max()) <= 1e-12
    assert (m["model_used"] == m["model"]).all(), m.loc[m["model_used"] != m["model"], K + ["model", "model_used"]]
    assert (pd.to_datetime(m["target_date_y"]) == pd.to_datetime(m["target_date_x"])).all()
    assert (m["published"].to_numpy() == select.published_qty(m["value"].to_numpy(), 0.2)).all()
    assert (m["ok"] | m["model"].str.startswith("FALLBACK")).all()   # not ok -> fallback


def test_fixture_coverage(fx):
    exp = fx["exp"]
    assert exp["model"].str.startswith("FALLBACK").any() and (~exp["model"].str.startswith("FALLBACK")).any()
    assert exp["model"].str.contains("@0.6").any()
    per = exp[exp["horizon"] == 1].groupby(K)["forecast_date"].nunique()
    assert (per < len(DAYS)).any()          # series out of scope on some forecast days
    assert set(fx["keys"]["group"]) >= {"A", "B", "C", ""}


def test_no_leak_on_fixture(fx):
    d = date(2026, 10, 15)
    base = _run(fx, d)
    act = fx["act"].copy()
    act.loc[pd.to_datetime(act["date"]) >= pd.Timestamp(d), "qty"] = 1e6
    hist = fx["hist"].copy()
    late = (hist["target_date"] >= pd.Timestamp(d)) & (hist["forecast_date"] < pd.Timestamp(d))
    hist.loc[late, "value"] = 777.0
    later = hist["forecast_date"] > pd.Timestamp(d)
    hist.loc[later, "value"] = 555.0
    old = hist[hist["forecast_date"] >= pd.Timestamp(d) - pd.Timedelta(days=7)].copy()
    old["forecast_date"] = pd.Timestamp(_hist_from(d)) - pd.Timedelta(days=1)   # before history_start: ignored
    old["target_date"] = pd.Timestamp(d) - pd.Timedelta(days=1)
    old["value"] = 999.0
    hist = pd.concat([hist, old.drop_duplicates(["model"] + K + ["horizon"])], ignore_index=True)
    got = _run(fx, d, hist=hist, act=act)
    pd.testing.assert_frame_equal(got, base)


# ------------------------------------------------------------------ hand-made cases
D = date(2026, 9, 30)


def _case(hist_vals, today_vals, actual=10.0, days=28, group="A", actual_overrides=None, open_last=None):
    """One series S1 x HN. hist_vals: candidate -> value of its horizon-1 forecast of every target day D-days .. D-1
    (a callable(target) -> value or None for a per-day value); today_vals: candidate -> value of D (all 7 horizons);
    open_last: only the target days D-open_last .. D-1 are open (default all)."""
    key = ("S1", "HN")
    rows, acts, opens = [], [], []
    for i in range(1, days + 1):
        t = pd.Timestamp(D - timedelta(days=i))
        if open_last is None or i <= open_last:
            opens.append((*key, t))
        acts.append((*key, t, (actual_overrides or {}).get(t, actual)))
        for c, v in hist_vals.items():
            v = v(t) if callable(v) else v
            if v is not None:
                rows.append((c, *key, t, 1, t, v))
    hist = pd.DataFrame(rows, columns=["model"] + K + ["forecast_date", "horizon", "target_date", "value"])
    cand_today = {c: pd.DataFrame([(*key, h, v) for h in range(1, 8)], columns=K + ["horizon", "value"])
                  for c, v in today_vals.items()}
    out = select.select_day(D, pd.DataFrame([key], columns=K), cand_today, hist,
                            pd.DataFrame(acts, columns=K + ["date", "qty"]), pd.DataFrame(opens, columns=K + ["date"]),
                            {key: group})
    assert len(out) == 7 and (out["horizon"].tolist() == list(range(1, 8)))
    return out


TODAY = {"MOC": 1.0, "V33_L112": 2.0, "V36_two_stage@0.6": 3.0, "TSB": 4.0, "DOW4": 5.0, "AVG7": 6.0}


def test_equal_rate_lower_shortage_wins():
    # TSB 8 vs actual 10: DUNG (|dev| 2 <= 3) with shortage 56; DOW4 12: DUNG, no shortage; the rest far off
    h = {c: 50.0 for c in select.CANDIDATES} | {"TSB": 8.0, "DOW4": 12.0}
    out = _case(h, TODAY)
    assert (out["model_used"] == "DOW4+TSB").all() and out["ok"].all()
    assert np.allclose(out["raw_value"], (5.0 + 4.0) / 2)


def test_equal_rate_and_shortage_lower_index_wins():
    h = {c: 50.0 for c in select.CANDIDATES} | {"AVG7": 10.0, "MOC": 10.0, "V36_two_stage@0.6": 10.0}
    out = _case(h, TODAY)
    assert (out["model_used"] == "MOC+V36_two_stage@0.6").all()
    assert np.allclose(out["raw_value"], (1.0 + 3.0) / 2)


def test_candidate_without_forecast_of_d_ranks_last():
    h = {c: 50.0 for c in select.CANDIDATES} | {"AVG7": 10.0, "DOW4": 11.0}
    today = {c: v for c, v in TODAY.items() if c != "AVG7"}
    out = _case(h, today)
    assert out["model_used"].iloc[0].startswith("DOW4+")
    assert out["model_used"].iloc[0] == "DOW4+MOC"     # rest tied at rate 0: lower shortage (none), lower index


def test_fallback_when_fewer_than_14_known_days():
    h = {c: 10.0 for c in select.CANDIDATES}
    h["AVG7"] = lambda t: 10.0 if t >= pd.Timestamp(D - timedelta(days=13)) else None   # 13 target days
    out = _case(h, TODAY)
    assert (out["model_used"] == "FALLBACK:V33_L112").all() and not out["ok"].any()
    assert (out["raw_value"] == 2.0).all()
    h["AVG7"] = lambda t: 10.0 if t >= pd.Timestamp(D - timedelta(days=14)) else None   # 14 target days
    out = _case(h, TODAY)
    assert (out["model_used"] == "MOC+V33_L112").all() and out["ok"].all()


def test_closed_target_days_are_not_known_days():
    h = {c: 10.0 for c in select.CANDIDATES}
    assert (_case(h, TODAY, open_last=13)["model_used"] == "FALLBACK:V33_L112").all()
    assert (_case(h, TODAY, open_last=14)["model_used"] == "MOC+V33_L112").all()


def test_second_without_value_falls_back_to_best():
    h = {c: 10.0 for c in select.CANDIDATES}
    out = _case(h, {"V33_L112": 2.5})
    assert (out["model_used"] == "FALLBACK:V33_L112").all() and out["ok"].all()
    assert (out["raw_value"] == 2.5).all()


def test_missing_best_value_is_refused():
    h = {c: 10.0 for c in select.CANDIDATES}
    with pytest.raises(ValueError):
        _case(h, {"MOC": 1.0})


def test_d_minus_1_actual_can_change_choice():
    last = pd.Timestamp(D - timedelta(days=1))
    h = {c: 50.0 for c in select.CANDIDATES} | {"MOC": 10.0, "DOW4": lambda t: 20.0 if t == last else 10.0}
    assert (_case(h, TODAY)["model_used"] == "MOC+DOW4").all()
    assert (_case(h, TODAY, actual_overrides={last: 20.0})["model_used"] == "DOW4+MOC").all()


def test_missing_group_is_b():
    # actual 0, forecast 3: DUNG for A / B (tolerance 3), not for C (tolerance 1)
    h = {c: 50.0 for c in select.CANDIDATES} | {"TSB": 3.0, "AVG7": 0.0}
    assert (_case(h, TODAY, actual=0.0, group=None)["model_used"] == "TSB+AVG7").all()
    assert (_case(h, TODAY, actual=0.0, group="C")["model_used"] == "AVG7+MOC").all()


@pytest.mark.parametrize("raw, pub", [(0.199999, 0), (0.2, 1), (1.0, 1), (1.0000001, 1), (1.000001, 2)])
def test_published_quantity(raw, pub):
    h = {c: 10.0 for c in select.CANDIDATES}
    out = _case(h, {"V33_L112": raw})
    assert (out["raw_value"] == raw).all() and (out["published"] == pub).all()


def test_two_stage_value():
    v = select.two_stage_value(np.array([0.59999, 0.6, 0.9, np.nan]), np.array([5.0, 6.0, 7.0, 8.0]))
    assert v.tolist() == [0.0, 6.0, 7.0, 0.0]          # a missing probability is below p (backtest np.where rule)
