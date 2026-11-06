"""1.4.3 owner final rule 05/11/2026 for forecast_used of the daily SEL2 Excel (ml/sel2/export.py, sheet DU_BAO):
R1 LIGHTGBM with a number (0 included) -> the number; R2 LIGHTGBM outside the run scope -> 0 + NGOAI_PHAM_VI_GAN_0 for
every prefix; R3' (supplement 05/11/2026) in the scope of the reference run (today's run, else the newest run of
D-3 .. D-1) without a number of today -> the newest run of D-3 .. D-1 with that number + DUNG_SO_LAN_CHAY_TRUOC + flag
LAN_CHAY_TRUOC:<day>; R3'' otherwise -> AVG + STALE / KHONG_CO_SO; R4 AVG_DEMAND -> AVG, without AVG and with a
LightGBM number -> the number + KHONG_CO_AVG_DUNG_LIGHTGBM; R5 every source is rounded (below 0.2 -> 0, else rounded up,
negative -> 0), the column is never empty (no number at all -> 0 + KHONG_CO_SO_NAO) and lightgbm_forecast / avg_demand
keep the original values. Unit (_rows with synthetic inputs) and integration with fakes (isolated temporary database,
rows inserted directly, workbook read back)."""
from datetime import timedelta

import pytest

from app.ml.sel2 import export
from test_v140_t6_export import D, SCOPE, _avg, _book, _by, _config, _dt, _main_rows, _run, _summary  # tests/ on path

COL = {c: i for i, c in enumerate(export.COLUMNS)}
RUN = {"id": "R1", "model_version": "MV-R1", "data_as_of": "2026-11-01"}


def _stats():
    return {"rows_by_fallback_reason": {}, "flag_rows": {}}


def _one(k, *, src=None, avg=None, qty=None, run=RUN, in_run=True, stale=False, stats=None):
    """Row of horizon 1 of SKU x FC k: source src (None = default AVG_DEMAND), AVG_DEMAND value avg, LightGBM qty of
    day D (None = no number), in_run = the SKU x FC is in the run used."""
    run_keys = {k: ("A", "MOC+DOW4")} if run is not None and in_run else {}
    vals = {k: [(qty, 1.234, "MOC+DOW4", None)] + [None] * (export.HORIZON - 1)} if qty is not None else {}
    a = {k: {"value": avg, "reason": None if avg is not None else "AVG_DEMAND_NULL"}}
    conf = {k: src} if src else {}
    rows = list(export._rows(D, [k], run, run_keys, vals, a, conf, {}, stale, stats or _stats()))
    assert len(rows) == export.HORIZON
    return {c: rows[0][i] for c, i in COL.items()}


@pytest.mark.parametrize("avg, used", [(0.15, 0), (0.2, 1), (1.01, 2), (3.0, 3), (2.0000000001, 2), (0.0, 0),
                                       (-1.5, 0), (0.19999999, 1)])
def test_avg_source_rounded(avg, used):
    r = _one(("S1", "F1"), avg=avg)
    assert r["forecast_source"] == "AVG_DEMAND" and r["forecast_used"] == used and type(r["forecast_used"]) is int
    assert r["avg_demand"] == avg and r["fallback_reason"] is None           # original value kept, no reason


def test_lightgbm_number_kept_as_int():
    r = _one(("S1", "F1"), src="LIGHTGBM", avg=2.5, qty=4)
    assert (r["lightgbm_forecast"], r["avg_demand"], r["forecast_used"], r["fallback_reason"]) == (4, 2.5, 4, None)
    assert type(r["forecast_used"]) is int
    r0 = _one(("S1", "F1"), src="LIGHTGBM", avg=2.5, qty=0)
    assert (r0["lightgbm_forecast"], r0["forecast_used"], r0["fallback_reason"]) == (0, 0, None)


def test_avg_source_without_any_number_is_zero_with_reason():
    r = _one(("S1", "F1"), avg=None)
    assert (r["avg_demand"], r["forecast_used"], r["fallback_reason"]) == (None, 0, export.REASON_NO_NUMBER)
    assert export.REASON_NO_NUMBER == "KHONG_CO_SO_NAO"


@pytest.mark.parametrize("stale, reason", [(False, "KHONG_CO_SO"), (True, "STALE")])
def test_lightgbm_without_number_takes_avg_rounded_up(stale, reason):
    r = _one(("S1", "F1"), src="LIGHTGBM", avg=2.4, stale=stale)
    assert (r["lightgbm_forecast"], r["avg_demand"], r["forecast_used"], r["fallback_reason"]) == (None, 2.4, 3, reason)
    n = _one(("S1", "F1"), src="LIGHTGBM", avg=None, stale=stale)
    assert (n["lightgbm_forecast"], n["avg_demand"], n["forecast_used"], n["fallback_reason"]) == \
        (None, None, 0, "KHONG_CO_SO_NAO")


def test_lightgbm_without_any_run_takes_avg_rounded_up():
    r = _one(("S1", "F1"), src="LIGHTGBM", avg=0.5, run=None)
    assert (r["forecast_used"], r["fallback_reason"]) == (1, "KHONG_CO_SO")


@pytest.mark.parametrize("sku", ["MEDX.B", "MEDX_E.X", "BML_INT.Y", "BML.Y", "TAYAU_E.Z", "S1"])
@pytest.mark.parametrize("avg", [4.0, 5.7, 0.5, None])
def test_r2_out_of_scope_zero_for_every_prefix(sku, avg):
    """R2: LIGHTGBM outside the scope of the run used -> 0 + NGOAI_PHAM_VI_GAN_0, whatever the prefix or AVG value."""
    r = _one((sku, "F1"), src="LIGHTGBM", avg=avg, in_run=False)
    assert (r["lightgbm_forecast"], r["avg_demand"], r["forecast_used"], r["fallback_reason"]) == \
        (None, avg, 0, "NGOAI_PHAM_VI_GAN_0")
    assert type(r["forecast_used"]) is int and export.REASON_OUT_ZERO == "NGOAI_PHAM_VI_GAN_0"
    assert not hasattr(export, "REASON_NO_DEMAND") and not hasattr(export, "DEMAND_PREFIX")


def test_r1_zero_is_never_replaced_by_avg():
    r = _one(("S1", "F1"), src="LIGHTGBM", avg=5.0, qty=0)
    assert (r["lightgbm_forecast"], r["avg_demand"], r["forecast_used"], r["fallback_reason"]) == (0, 5.0, 0, None)
    r3 = _one(("S1", "F1"), src="LIGHTGBM", avg=5.0, qty=3)
    assert (r3["lightgbm_forecast"], r3["forecast_used"], r3["fallback_reason"]) == (3, 3, None)
    s = _one(("MEDX.B", "F1"), src="LIGHTGBM", avg=5.0, qty=0, stale=True)        # stale run with a number of the day
    assert (s["forecast_used"], s["fallback_reason"]) == (0, None)


def test_r3_lightgbm_without_number_takes_avg():
    r = _one(("S1", "F1"), src="LIGHTGBM", avg=2.4, run=None)                     # SEL2 run failed / missing
    assert (r["lightgbm_forecast"], r["avg_demand"], r["forecast_used"], r["fallback_reason"]) == \
        (None, 2.4, 3, "KHONG_CO_SO")
    m = _one(("MEDX.B", "F1"), src="LIGHTGBM", avg=2.4, run=None)                 # no run: never 0 by R2
    assert (m["forecast_used"], m["fallback_reason"]) == (3, "KHONG_CO_SO")
    s = _one(("S1", "F1"), src="LIGHTGBM", avg=1.1, stale=True)                   # stale run, no number of the day
    assert (s["avg_demand"], s["forecast_used"], s["fallback_reason"]) == (1.1, 2, "STALE")
    n = _one(("S1", "F1"), src="LIGHTGBM", avg=None)                              # in the scope, no number, no AVG
    assert (n["lightgbm_forecast"], n["avg_demand"], n["forecast_used"], n["fallback_reason"]) == \
        (None, None, 0, "KHONG_CO_SO_NAO")


@pytest.mark.parametrize("src", [None, "AVG_DEMAND"])                            # None = default source (new SKU)
def test_r4_avg_source(src):
    k = ("S1", "F1")
    r = _one(k, src=src, avg=0.15, qty=2)                                         # AVG present: AVG rounded, never LGBM
    assert (r["forecast_source"], r["lightgbm_forecast"], r["avg_demand"], r["forecast_used"], r["fallback_reason"]) \
        == ("AVG_DEMAND", 2, 0.15, 0, None)
    p = _one(k, src=src, avg=2.4, qty=7)
    assert (p["lightgbm_forecast"], p["avg_demand"], p["forecast_used"], p["fallback_reason"]) == (7, 2.4, 3, None)
    g = _one(k, src=src, avg=None, qty=2)                                         # no AVG, LightGBM number of the day
    assert (g["lightgbm_forecast"], g["avg_demand"], g["forecast_used"], g["fallback_reason"]) == \
        (2, None, 2, "KHONG_CO_AVG_DUNG_LIGHTGBM")
    assert export.REASON_AVG_MISSING_LGBM == "KHONG_CO_AVG_DUNG_LIGHTGBM"
    z = _one(k, src=src, avg=None, qty=0)                                         # LightGBM 0 is a number
    assert (z["forecast_used"], z["fallback_reason"]) == (0, "KHONG_CO_AVG_DUNG_LIGHTGBM")
    n = _one(k, src=src, avg=None)                                                # no number at all
    assert (n["lightgbm_forecast"], n["avg_demand"], n["forecast_used"], n["fallback_reason"]) == \
        (None, None, 0, "KHONG_CO_SO_NAO")
    o = _one(k, src=src, avg=None, run=None)
    assert (o["forecast_used"], o["fallback_reason"]) == (0, "KHONG_CO_SO_NAO")
    nan = _one(k, src=src, avg=float("nan"), qty=4)                               # a NaN AVG is not a value
    assert (nan["forecast_used"], nan["fallback_reason"]) == (4, "KHONG_CO_AVG_DUNG_LIGHTGBM")


def test_reason_counts_follow_the_final_reason():
    stats = _stats()
    _one(("S1", "F1"), avg=None, stats=stats)
    _one(("S2", "F1"), avg=1.2, stats=stats)
    assert stats["rows_by_fallback_reason"] == {"KHONG_CO_SO_NAO": 7, "": 7}


def test_every_du_bao_row_has_an_int_forecast_used(sel2_on):
    """Workbook read back: every row has forecast_used an int >= 0; avg_demand / lightgbm_forecast unchanged."""
    _run("R1", D, {("S1", "F1"): ("A", "MOC+DOW4", {h: (h, h - 0.4) for h in range(1, 6)}),
                   ("S2", "F1"): ("B", "MOC+DOW4", {h: (h, h - 0.4) for h in range(1, 8)})})
    _avg(D, [("S1", "F1", "SL1", 2.4, None), ("S2", "F1", "SL1", 0.15, None), ("S3", "F1", "SL1", 1.01, None),
             ("S4", "F1", "SL1", None, None), ("S5", "F1", "SL1", 0.5, None), ("MEDX.Z", "F1", "SL1", 3.3, None)])
    _config([("S1", "F1", "LIGHTGBM", None), ("S5", "F1", "LIGHTGBM", None), ("MEDX.Z", "F1", "LIGHTGBM", None)])
    res = export.write_daily_export(D, scope_key=SCOPE)
    wb = _book(res)
    rows = _main_rows(wb)
    assert len(rows) == 6 * 7
    assert all(type(r["forecast_used"]) is int and r["forecast_used"] >= 0 for r in rows)
    by = _by(rows)
    pick = lambda k: (by[k]["lightgbm_forecast"], by[k]["avg_demand"], by[k]["forecast_used"], by[k]["fallback_reason"])
    assert pick(("S1", "F1", 2)) == (2, 2.4, 2, None)                      # LightGBM number kept
    assert pick(("S1", "F1", 6)) == (None, 2.4, 3, "KHONG_CO_SO")           # no number for the day -> AVG rounded up
    assert pick(("S2", "F1", 1)) == (1, 0.15, 0, None)                      # AVG_DEMAND source, below 0.2 -> 0
    assert pick(("S3", "F1", 1)) == (None, 1.01, 2, None)                   # new SKU, default AVG_DEMAND
    assert pick(("S4", "F1", 1)) == (None, None, 0, "KHONG_CO_SO_NAO")      # no number at all
    assert pick(("S5", "F1", 1)) == (None, 0.5, 0, "NGOAI_PHAM_VI_GAN_0")     # outside the scope, any prefix: 0
    assert pick(("MEDX.Z", "F1", 1)) == (None, 3.3, 0, "NGOAI_PHAM_VI_GAN_0")
    assert by[("S1", "F1", 2)]["raw_value"] == pytest.approx(1.6)
    s = _summary(wb)
    assert s["rows_fallback_reason:KHONG_CO_SO_NAO"] == 7 and s["rows_fallback_reason:KHONG_CO_SO"] == 2
    assert s["rows_fallback_reason:NGOAI_PHAM_VI_GAN_0"] == 14
    assert "rows_fallback_reason:KHONG_CO_DU_LIEU_DEMAND" not in s


# ------------------------------------------------------------------ tester additions (143-T1-test)
@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_avg_is_no_number(bad):
    """A NaN / infinite AVG_DEMAND value is not a number: forecast_used 0 + KHONG_CO_SO_NAO, avg_demand kept as read."""
    r = _one(("S1", "F1"), avg=bad)
    assert (r["forecast_used"], r["fallback_reason"]) == (0, "KHONG_CO_SO_NAO") and type(r["forecast_used"]) is int
    n = _one(("S1", "F1"), src="LIGHTGBM", avg=bad)                          # LIGHTGBM without a number, AVG not finite
    assert (n["forecast_used"], n["fallback_reason"]) == (0, "KHONG_CO_SO_NAO")


@pytest.mark.parametrize("qty, used", [(0.5, 1), (0.1, 0), (2.0000001, 2), (-3, 0), (7.0, 7)])
def test_lightgbm_number_rounded_and_original_kept(qty, used):
    """LIGHTGBM number of the day is rounded too (fractional / negative); lightgbm_forecast keeps the original value."""
    r = _one(("S1", "F1"), src="LIGHTGBM", avg=9.9, qty=qty)
    assert (r["lightgbm_forecast"], r["avg_demand"], r["forecast_used"], r["fallback_reason"]) == (qty, 9.9, used, None)
    assert type(r["forecast_used"]) is int


def test_every_horizon_follows_the_rule_and_counts_by_final_reason():
    """Horizons 1..7 of a LIGHTGBM SKU x FC with numbers for days 1-3 only and no AVG value: 3 rows kept, 4 rows 0 +
    KHONG_CO_SO_NAO (never KHONG_CO_SO / STALE); the stale variant counts the same way."""
    k = ("S1", "F1")
    for stale in (False, True):
        stats = _stats()
        vals = {k: [(h, h - 0.5, "MOC", None) for h in (1, 2, 3)] + [None] * (export.HORIZON - 3)}
        a = {k: {"value": None, "reason": "AVG_DEMAND_NULL"}}
        rows = list(export._rows(D, [k], RUN, {k: ("A", "MOC")}, vals, a, {k: "LIGHTGBM"}, {}, stale, stats))
        used = [r[COL["forecast_used"]] for r in rows]
        reasons = [r[COL["fallback_reason"]] for r in rows]
        assert used == [1, 2, 3, 0, 0, 0, 0] and reasons == [None] * 3 + ["KHONG_CO_SO_NAO"] * 4
        assert [r[COL["lightgbm_forecast"]] for r in rows] == [1, 2, 3, None, None, None, None]
        assert stats["rows_by_fallback_reason"] == {"": 3, "KHONG_CO_SO_NAO": 4}


def test_daily_summary_counts_match_rows_record_and_tom_tat(sel2_on):
    """rows_by_fallback_reason of the returned summary, export_runs.summary_json and TOM_TAT are the counts of the
    DU_BAO rows; no row has an empty forecast_used."""
    import json
    from app import db
    _run("R1", D, {("S1", "F1"): ("A", "MOC+DOW4", {1: (3, 2.6), 2: (1, 0.7)})})
    _avg(D, [("S1", "F1", "SL1", None, None), ("S2", "F1", "SL1", None, None), ("S3", "F1", "SL1", 0.19, None)])
    _config([("S1", "F1", "LIGHTGBM", None)])
    res = export.write_daily_export(D, scope_key=SCOPE)
    wb = _book(res)
    rows = _main_rows(wb)
    counts: dict = {}
    for r in rows:
        assert r["forecast_used"] is not None
        counts[r["fallback_reason"] or ""] = counts.get(r["fallback_reason"] or "", 0) + 1
    assert counts == {"": 2 + 7, "KHONG_CO_SO_NAO": 5 + 7}
    assert res["summary"]["rows_by_fallback_reason"] == counts
    with db.read() as c:
        stored = json.loads(db.one(c, "SELECT summary_json FROM export_runs")["summary_json"])
    assert stored["rows_by_fallback_reason"] == counts
    s = _summary(wb)
    assert (s["rows_fallback_reason:(none)"], s["rows_fallback_reason:KHONG_CO_SO_NAO"]) == (9, 12)
    assert not any(k.startswith("rows_fallback_reason:") and k[21:] in ("KHONG_CO_SO", "STALE") for k in s)
    by = _by(rows)
    assert [by[("S3", "F1", h)]["forecast_used"] for h in (1, 7)] == [0, 0]           # AVG 0.19 -> 0
    assert by[("S3", "F1", 1)]["avg_demand"] == pytest.approx(0.19)


def test_daily_export_owner_final_rule_every_case(sel2_on):
    """Workbook read back, one SKU x FC per rule: R1 (0 and 3 kept), R3 (in the scope without a number -> AVG +
    KHONG_CO_SO), R4 (AVG missing -> LightGBM; AVG below 0.2 -> 0; nothing -> 0 + KHONG_CO_SO_NAO), R2 (MEDX and other
    prefixes -> 0); R5 every row an int >= 0; TOM_TAT / summary / export_runs counts = the DU_BAO rows."""
    import json
    from app import db
    _run("R1", D, {("L1", "F1"): ("A", "MOC+DOW4", {1: (0, 0.1), 2: (3, 2.6)}),
                   ("A1", "F1"): ("B", "MOC+DOW4", {h: (2, 1.8) for h in range(1, 8)})})
    _avg(D, [("L1", "F1", "SL1", 5.0, None), ("A1", "F1", "SL1", None, None), ("A2", "F1", "SL1", 0.15, None),
             ("A3", "F1", "SL1", None, None), ("MEDX.B", "F1", "SL1", None, None),
             ("BML_INT.X", "F1", "SL1", 4.0, None)])
    _config([("L1", "F1", "LIGHTGBM", None), ("MEDX.B", "F1", "LIGHTGBM", None), ("BML_INT.X", "F1", "LIGHTGBM", None)])
    res = export.write_daily_export(D, scope_key=SCOPE)
    wb = _book(res)
    rows = _main_rows(wb)
    assert len(rows) == 6 * 7 and all(type(r["forecast_used"]) is int and r["forecast_used"] >= 0 for r in rows)
    by = _by(rows)
    pick = lambda k: (by[k]["lightgbm_forecast"], by[k]["avg_demand"], by[k]["forecast_used"], by[k]["fallback_reason"])
    assert pick(("L1", "F1", 1)) == (0, 5.0, 0, None) and pick(("L1", "F1", 2)) == (3, 5.0, 3, None)
    assert all(pick(("L1", "F1", h)) == (None, 5.0, 5, "KHONG_CO_SO") for h in range(3, 8))
    assert all(pick(("A1", "F1", h)) == (2, None, 2, "KHONG_CO_AVG_DUNG_LIGHTGBM") for h in range(1, 8))
    assert all(pick(("A2", "F1", h)) == (None, 0.15, 0, None) for h in range(1, 8))
    assert all(pick(("A3", "F1", h)) == (None, None, 0, "KHONG_CO_SO_NAO") for h in range(1, 8))
    assert all(pick(("MEDX.B", "F1", h)) == (None, None, 0, "NGOAI_PHAM_VI_GAN_0") for h in range(1, 8))
    assert all(pick(("BML_INT.X", "F1", h)) == (None, 4.0, 0, "NGOAI_PHAM_VI_GAN_0") for h in range(1, 8))
    counts: dict = {}
    for r in rows:
        counts[r["fallback_reason"] or ""] = counts.get(r["fallback_reason"] or "", 0) + 1
    assert counts == {"": 2 + 7, "KHONG_CO_SO": 5, "KHONG_CO_AVG_DUNG_LIGHTGBM": 7, "KHONG_CO_SO_NAO": 7,
                      "NGOAI_PHAM_VI_GAN_0": 14}
    assert res["summary"]["rows_by_fallback_reason"] == counts
    with db.read() as c:
        stored = json.loads(db.one(c, "SELECT summary_json FROM export_runs")["summary_json"])
    assert stored["rows_by_fallback_reason"] == counts
    s = _summary(wb)
    assert {k: v for k, v in s.items() if k.startswith("rows_fallback_reason:")} == \
        {f"rows_fallback_reason:{k or '(none)'}": v for k, v in counts.items()}


# ------------------------------------------------------------------ temporary file of the first start (_TAM.xlsx)
def test_temp_export_rows_follow_the_rule(sel2_on):
    """write_temp_export uses the same rule: AVG source rounded, AVG configured without a value -> the candidate number
    + KHONG_CO_AVG_DUNG_LIGHTGBM (R4), LIGHTGBM outside the candidate -> 0 + NGOAI_PHAM_VI_GAN_0 with or without AVG
    (R2); TOM_TAT counts."""
    from test_v140_b6_bootstrap import SCOPE as B6_SCOPE, _store_candidates
    _store_candidates(v33={("S1", "F1"): [2.3] * 7, ("S2", "F1"): [0.5] * 7, ("S3", "F1"): [1.0] * 7},
                      scope=B6_SCOPE)
    _avg(D, [("S1", "F1", "SL1", 0.15, None), ("S3", "F1", "SL1", None, None), ("S4", "F1", "SL1", 1.01, None),
             ("S5", "F1", "SL1", None, None), ("S6", "F1", "SL1", 0.5, None), ("MEDX.Z", "F1", "SL1", 3.3, None)])
    _config([("S3", "F1", "LIGHTGBM", None), ("S5", "F1", "LIGHTGBM", None), ("S6", "F1", "LIGHTGBM", None),
             ("MEDX.Z", "F1", "LIGHTGBM", None)])
    res = export.write_temp_export(D, groups={}, scope_key=B6_SCOPE)
    assert res["path"].endswith("du_bao_20261102_TAM.xlsx") and res["n_rows"] == 7 * 20
    wb = _book(res)
    rows = _main_rows(wb)
    assert len(rows) == 49 and all(type(r["forecast_used"]) is int and r["forecast_used"] >= 0 for r in rows)
    by = _by(rows)
    pick = lambda k: (by[k]["forecast_source"], by[k]["lightgbm_forecast"], by[k]["avg_demand"], by[k]["forecast_used"],
                      by[k]["fallback_reason"])
    assert pick(("S1", "F1", 1)) == ("AVG_DEMAND", 3, 0.15, 0, None)            # AVG source below 0.2 -> 0
    # AVG configured without an AVG row: the candidate number (R4)
    assert pick(("S2", "F1", 1)) == ("AVG_DEMAND", 1, None, 1, "KHONG_CO_AVG_DUNG_LIGHTGBM")
    assert pick(("S3", "F1", 1)) == ("LIGHTGBM", 1, None, 1, None)              # candidate number used
    assert pick(("S4", "F1", 1)) == ("AVG_DEMAND", None, 1.01, 2, None)         # new SKU, default AVG, rounded up
    assert pick(("S5", "F1", 1)) == ("LIGHTGBM", None, None, 0, "NGOAI_PHAM_VI_GAN_0")
    assert pick(("S6", "F1", 1)) == ("LIGHTGBM", None, 0.5, 0, "NGOAI_PHAM_VI_GAN_0")
    assert pick(("MEDX.Z", "F1", 1)) == ("LIGHTGBM", None, 3.3, 0, "NGOAI_PHAM_VI_GAN_0")
    assert by[("S2", "F1", 1)]["raw_value"] == pytest.approx(0.5)
    s = _summary(wb)
    assert (s["rows_fallback_reason:(none)"], s["rows_fallback_reason:KHONG_CO_AVG_DUNG_LIGHTGBM"],
            s["rows_fallback_reason:NGOAI_PHAM_VI_GAN_0"]) == (21, 7, 21)
    assert not any(k in s for k in ("rows_fallback_reason:KHONG_CO_SO_NAO",
                                    "rows_fallback_reason:KHONG_CO_DU_LIEU_DEMAND"))
    counts: dict = {}
    for r in rows:
        counts[r["fallback_reason"] or ""] = counts.get(r["fallback_reason"] or "", 0) + 1
    assert {f"rows_fallback_reason:{k or '(none)'}": v for k, v in counts.items()} == \
        {k: v for k, v in s.items() if k.startswith("rows_fallback_reason:")}
    assert s["trigger"] == "BOOTSTRAP_TEMP" and s["export_version"] == "TAM" and s["rows_total"] == 49
    cfg = list(wb["CONFIG"].iter_rows(values_only=True))
    assert [r[:2] for r in cfg[1:]] == [("MEDX.Z", "F1"), ("S3", "F1"), ("S5", "F1"), ("S6", "F1")]


# ------------------------------------------------------------------ owner rule 05/11/2026: previous runs (R3', 143-T1c)
PREV = "DUNG_SO_LAN_CHAY_TRUOC"


def _d(n: int) -> str:
    return (D - timedelta(days=n)).isoformat()


def _series(qty: dict, method="MOC+DOW4", grp="A"):
    """{horizon: qty} -> the series shape of _run (raw = qty - 0.25)."""
    return (grp, method, {h: (q, q - 0.25) for h, q in qty.items()})


def _flags(r) -> list:
    return (r["flags"] or "").split(",")


def _export():
    res = export.write_daily_export(D, scope_key=SCOPE)
    wb = _book(res)
    return res, _by(_main_rows(wb)), _summary(wb)


def _pick(by, k):
    return by[k]["lightgbm_forecast"], by[k]["avg_demand"], by[k]["forecast_used"], by[k]["fallback_reason"]


def test_failed_day_uses_the_run_of_d_minus_1(sel2_on):
    """(a) No run of D, run of D-1: its numbers for the matching target days (horizon + 1), reason
    DUNG_SO_LAN_CHAY_TRUOC + flag LAN_CHAY_TRUOC:<D-1>; a previous-run 0 is used (not AVG); raw_value / model_used come
    from that run; D+6 (beyond its horizon) -> AVG + STALE."""
    _run("RP1", D - timedelta(days=1), {("S1", "F1"): _series({h: 10 + h for h in range(1, 8)}),
                                        ("S2", "F1"): _series({h: 0 for h in range(1, 8)}, method="TSB")})
    _avg(D, [("S1", "F1", "SL1", 2.4, None), ("S2", "F1", "SL1", 5.0, None)])
    _config([("S1", "F1", "LIGHTGBM", None), ("S2", "F1", "LIGHTGBM", None)])
    res, by, s = _export()
    assert res["is_stale"] is True and res["summary"]["refresh_run_id"] == "RP1"
    for h in range(1, 7):                                  # file horizon h = horizon h + 1 of the run of D-1
        assert _pick(by, ("S1", "F1", h)) == (11 + h, 2.4, 11 + h, PREV)
        assert f"LAN_CHAY_TRUOC:{_d(1)}" in _flags(by[("S1", "F1", h)])
        assert _pick(by, ("S2", "F1", h)) == (0, 5.0, 0, PREV)                 # a 0 is a number: never AVG
    assert by[("S1", "F1", 1)]["raw_value"] == pytest.approx(11.75) and by[("S1", "F1", 1)]["model_used"] == "MOC+DOW4"
    assert by[("S2", "F1", 1)]["model_used"] == "TSB"
    assert _pick(by, ("S1", "F1", 7)) == (None, 2.4, 3, "STALE") and _pick(by, ("S2", "F1", 7)) == (None, 5.0, 5, "STALE")
    assert not any(x.startswith("LAN_CHAY_TRUOC") for x in _flags(by[("S1", "F1", 7)]))
    assert s[f"rows_fallback_reason:{PREV}"] == 12 and s["rows_fallback_reason:STALE"] == 2
    assert s[f"rows_flag:LAN_CHAY_TRUOC:{_d(1)}"] == 12 and s["previous_runs"] == f"{_d(1)}:RP1"
    # provenance: rows of the run of D-1 carry its model_version / cutoff; the AVG row (D+6) those of the reference
    # run (the same run of D-1 here)
    assert all((by[("S1", "F1", h)]["model_version"], by[("S1", "F1", h)]["data_cutoff_date"]) ==
               ("MV-RP1", _dt(D - timedelta(days=2))) for h in range(1, 8))
    assert (s["model_version"], s["data_cutoff_date"], s["stale_reason"]) == ("MV-RP1", _d(2), "NO_RUN_FOR_DAY")
    assert "NO_RUN_3_DAYS" not in (s["file_flags"] or "")


def test_failed_day_outside_the_reference_scope_is_zero(sel2_on):
    """Failed day: the newest run of D-3 .. D-1 is the reference; a SKU x FC outside its scope -> 0 + NGOAI_PHAM_VI_GAN_0
    (like a normal day), even when an older run of the window had it."""
    _run("RP2", D - timedelta(days=2), {("S1", "F1"): _series({h: 7 for h in range(1, 8)}),
                                        ("S3", "F1"): _series({h: 9 for h in range(1, 8)})})
    _run("RP1", D - timedelta(days=1), {("S1", "F1"): _series({h: 4 for h in range(1, 8)})})
    _avg(D, [("S1", "F1", "SL1", 1.0, None), ("S3", "F1", "SL1", 6.0, None), ("MEDX.B", "F1", "SL1", 2.0, None)])
    _config([(s, "F1", "LIGHTGBM", None) for s in ("S1", "S3", "MEDX.B")])
    res, by, s = _export()
    assert res["is_stale"] is True
    assert _pick(by, ("S1", "F1", 1)) == (4, 1.0, 4, PREV)                     # reference run D-1 wins over D-2
    assert all(_pick(by, ("S3", "F1", h)) == (None, 6.0, 0, "NGOAI_PHAM_VI_GAN_0") for h in range(1, 8))
    assert all(_pick(by, ("MEDX.B", "F1", h)) == (None, 2.0, 0, "NGOAI_PHAM_VI_GAN_0") for h in range(1, 8))
    assert s["rows_fallback_reason:NGOAI_PHAM_VI_GAN_0"] == 14


def test_failed_day_reference_without_the_day_takes_an_older_run_of_the_window(sel2_on):
    """Failed day, the reference run (D-1) lacks some target days of an in-scope SKU x FC: the most recent run of the
    window that has the day (D-2) gives it (same reason, flag with its own day); no run has it -> AVG + STALE."""
    _run("RP3", D - timedelta(days=3), {("S1", "F1"): _series({h: 30 + h for h in range(1, 8)})})
    _run("RP2", D - timedelta(days=2), {("S1", "F1"): _series({h: 20 + h for h in range(1, 8)})})
    _run("RP1", D - timedelta(days=1), {("S1", "F1"): _series({1: 1, 2: 2, 3: 3})})   # targets D-1 .. D+1
    _avg(D, [("S1", "F1", "SL1", 1.5, None)])
    _config([("S1", "F1", "LIGHTGBM", None)])
    _, by, s = _export()
    assert [_pick(by, ("S1", "F1", h))[0] for h in range(1, 8)] == [2, 3, 25, 26, 27, None, None]
    assert [by[("S1", "F1", h)]["fallback_reason"] for h in range(1, 8)] == [PREV] * 5 + ["STALE"] * 2
    assert [x for x in _flags(by[("S1", "F1", 1)]) if x.startswith("LAN")] == [f"LAN_CHAY_TRUOC:{_d(1)}"]
    assert [x for x in _flags(by[("S1", "F1", 3)]) if x.startswith("LAN")] == [f"LAN_CHAY_TRUOC:{_d(2)}"]
    assert _pick(by, ("S1", "F1", 6)) == (None, 1.5, 2, "STALE")              # D+5: no run of the window covers it
    assert s["previous_runs"] == f"{_d(1)}:RP1,{_d(2)}:RP2,{_d(3)}:RP3"
    # provenance: the source run of each number (D-1 or D-2); the AVG rows the reference run (D-1)
    prov = lambda h: (by[("S1", "F1", h)]["model_version"], by[("S1", "F1", h)]["data_cutoff_date"])
    assert [prov(h)[0] for h in range(1, 8)] == ["MV-RP1"] * 2 + ["MV-RP2"] * 3 + ["MV-RP1"] * 2
    assert prov(1)[1] == _dt(D - timedelta(days=2)) and prov(3)[1] == _dt(D - timedelta(days=3))
    assert prov(7)[1] == _dt(D - timedelta(days=2))


def test_no_run_within_3_days_every_lightgbm_row_from_avg(sel2_on):
    """(b) Runs failing 4 days in a row (latest run D-4): never its numbers, never 0 by R2 -> AVG + STALE for every
    LIGHTGBM row (also outside the scope of that older run). Visible: stale_reason + file flag NO_RUN_3_DAYS (TOM_TAT,
    summary, export_runs.flags); rows and file without model_version / data_cutoff_date; the old run is not counted in
    the scope / model used (keys kept, 0 / empty); refresh_run_id / run_forecast_date name it as information only."""
    import json
    from app import db
    _run("RP4", D - timedelta(days=4), {("S1", "F1"): _series({h: 50 for h in range(1, 8)}),
                                        ("S9", "F1"): _series({h: 60 for h in range(1, 8)})})
    _avg(D, [("S1", "F1", "SL1", 2.2, None), ("S7", "F1", "SL1", 1.5, None), ("MEDX.B", "F1", "SL1", None, None)])
    _config([(s, "F1", "LIGHTGBM", None) for s in ("S1", "S7", "MEDX.B")])
    res, by, s = _export()
    assert res["is_stale"] is True and s["refresh_run_id"] == "RP4" and s["run_forecast_date"] == _d(4)
    assert s["stale_reason"] == "NO_RUN_3_DAYS" == res["summary"]["stale_reason"]
    assert s["file_flags"] == "STALE,NO_RUN_3_DAYS" and res["summary"]["file_flags"] == ["STALE", "NO_RUN_3_DAYS"]
    assert all(_pick(by, ("S1", "F1", h)) == (None, 2.2, 3, "STALE") for h in range(1, 8))
    assert all(_pick(by, ("S7", "F1", h)) == (None, 1.5, 2, "STALE") for h in range(1, 8))
    assert all(_pick(by, ("MEDX.B", "F1", h)) == (None, None, 0, "KHONG_CO_SO_NAO") for h in range(1, 8))
    assert ("S9", "F1", 1) in by and len(by) == 4 * 7                       # SKU x FC of the old run kept as rows
    assert not any(r["lightgbm_forecast"] in (50, 60) for r in by.values())
    assert all(r["model_version"] is None and r["data_cutoff_date"] is None and r["model_used"] is None
               for r in by.values())
    assert "rows_fallback_reason:NGOAI_PHAM_VI_GAN_0" not in s and f"rows_fallback_reason:{PREV}" not in s
    assert s["previous_runs"] is None and s["model_version"] is None and s["data_cutoff_date"] is None
    assert s["sku_fc_in_forecast_scope"] == 0 and not any(k.startswith("sku_fc_model_used:") for k in s)
    assert res["summary"]["sku_fc"]["in_forecast_scope"] == 0 and res["summary"]["model_used_by_sku_fc"] == {}
    with db.read() as c:
        rec = db.one(c, "SELECT flags, refresh_run_id, summary_json FROM export_runs")
    assert rec["flags"].split(",")[:2] == ["STALE", "NO_RUN_3_DAYS"] and rec["refresh_run_id"] == "RP4"
    assert json.loads(rec["summary_json"])["stale_reason"] == "NO_RUN_3_DAYS"


def test_no_sel2_run_at_all_keeps_no_sel2_run(sel2_on):
    """No SEL2 run at all: stale_reason / file flag NO_SEL2_RUN (not NO_RUN_3_DAYS), rows from AVG + KHONG_CO_SO."""
    _avg(D, [("S1", "F1", "SL1", 2.2, None)])
    _config([("S1", "F1", "LIGHTGBM", None)])
    res, by, s = _export()
    assert s["stale_reason"] == "NO_SEL2_RUN" and s["file_flags"] == "NO_SEL2_RUN"
    assert _pick(by, ("S1", "F1", 1)) == (None, 2.2, 3, "KHONG_CO_SO") and by[("S1", "F1", 1)]["model_version"] is None


def test_run_of_exactly_d_minus_3_is_used_d_minus_4_is_not(sel2_on):
    """Window D-3 .. D-1: a failed day with runs of D-4 and D-3 -> the run of exactly D-3 is the reference and supplies
    its numbers (targets D .. D+3); the run of D-4 never."""
    _run("RP4", D - timedelta(days=4), {("S1", "F1"): _series({h: 40 + h for h in range(1, 8)})})
    _run("RP3", D - timedelta(days=3), {("S1", "F1"): _series({h: 30 + h for h in range(1, 8)})})
    _avg(D, [("S1", "F1", "SL1", 1.0, None)])
    _config([("S1", "F1", "LIGHTGBM", None)])
    res, by, _ = _export()
    assert res["summary"]["refresh_run_id"] == "RP3"
    assert [_pick(by, ("S1", "F1", h))[2] for h in range(1, 8)] == [34, 35, 36, 37, 1, 1, 1]
    assert [by[("S1", "F1", h)]["fallback_reason"] for h in range(1, 8)] == [PREV] * 4 + ["STALE"] * 3
    assert f"LAN_CHAY_TRUOC:{_d(3)}" in _flags(by[("S1", "F1", 1)])


def test_today_run_in_scope_without_a_number_takes_the_newest_previous_run(sel2_on):
    """(c) Today's run exists, an in-scope SKU x FC lacks a number for some days: the newest run of D-3 .. D-1 with the
    number gives it (D-1 before D-2); a day no run of the window has -> AVG + KHONG_CO_SO (the run of D-4 never);
    (d) previous runs without that SKU x FC -> AVG + KHONG_CO_SO; outside today's scope R2 (0) is unchanged."""
    _run("RP4", D - timedelta(days=4), {("S1", "F1"): _series({h: 400 for h in range(1, 8)})})
    _run("RP3", D - timedelta(days=3), {("S1", "F1"): _series({h: 300 for h in range(1, 8)})})
    _run("RP2", D - timedelta(days=2), {("S1", "F1"): _series({h: 200 for h in range(1, 8)}),
                                        ("S4", "F1"): _series({h: 8 for h in range(1, 8)})})
    _run("RP1", D - timedelta(days=1), {("S1", "F1"): _series({h: 100 for h in range(1, 4)})})   # targets D-1 .. D+1
    _run("R0", D, {("S1", "F1"): _series({1: 5}), ("S2", "F1"): _series({1: 6})},
         created="2026-11-02T00:30:00+00:00")
    _avg(D, [("S1", "F1", "SL1", 1.2, None), ("S2", "F1", "SL1", 2.5, None), ("S4", "F1", "SL1", 3.0, None)])
    _config([(s, "F1", "LIGHTGBM", None) for s in ("S1", "S2", "S4")])
    res, by, s = _export()
    assert res["is_stale"] is False and res["summary"]["refresh_run_id"] == "R0"
    assert _pick(by, ("S1", "F1", 1)) == (5, 1.2, 5, None)                    # today's number
    assert _pick(by, ("S1", "F1", 2)) == (100, 1.2, 100, PREV)                # D+1: run of D-1
    assert f"LAN_CHAY_TRUOC:{_d(1)}" in _flags(by[("S1", "F1", 2)])
    assert [_pick(by, ("S1", "F1", h))[0] for h in (3, 4, 5)] == [200, 200, 200]   # D+2 .. D+4: run of D-2
    assert f"LAN_CHAY_TRUOC:{_d(2)}" in _flags(by[("S1", "F1", 3)])
    assert _pick(by, ("S1", "F1", 6)) == (None, 1.2, 2, "KHONG_CO_SO")         # D+5: no run of the window has it
    assert all(_pick(by, ("S2", "F1", h)) == (None, 2.5, 3, "KHONG_CO_SO") for h in range(2, 8))   # (d)
    assert all(_pick(by, ("S4", "F1", h)) == (None, 3.0, 0, "NGOAI_PHAM_VI_GAN_0") for h in range(1, 8))  # R2 kept
    assert not any(r["lightgbm_forecast"] in (300, 400) for r in by.values())
    # provenance: today's rows (and the AVG / R2 rows) of today's run, previous-run rows of their own run
    prov = lambda k: (by[k]["model_version"], by[k]["data_cutoff_date"])
    assert prov(("S1", "F1", 1)) == ("MV-R0", _dt(D - timedelta(days=1)))
    assert prov(("S1", "F1", 2)) == ("MV-RP1", _dt(D - timedelta(days=2)))
    assert prov(("S1", "F1", 3)) == ("MV-RP2", _dt(D - timedelta(days=3)))
    assert prov(("S1", "F1", 6)) == prov(("S4", "F1", 1)) == ("MV-R0", _dt(D - timedelta(days=1)))
    assert (s["model_version"], s["stale_reason"]) == ("MV-R0", None)


def test_today_run_only_d_minus_3_has_the_day(sel2_on):
    """Today's run lacks D+1 .. for an in-scope SKU x FC, only the run of D-3 has them -> D-3's numbers; D-4 never."""
    _run("RP4", D - timedelta(days=4), {("S1", "F1"): _series({h: 44 for h in range(1, 8)})})
    _run("RP3", D - timedelta(days=3), {("S1", "F1"): _series({h: 33 for h in range(1, 8)})})
    _run("R0", D, {("S1", "F1"): _series({1: 1})}, created="2026-11-02T00:30:00+00:00")
    _avg(D, [("S1", "F1", "SL1", 0.1, None)])
    _config([("S1", "F1", "LIGHTGBM", None)])
    _, by, _ = _export()
    assert [_pick(by, ("S1", "F1", h))[2] for h in range(1, 8)] == [1, 33, 33, 33, 0, 0, 0]
    assert [by[("S1", "F1", h)]["fallback_reason"] for h in range(1, 8)] == [None] + [PREV] * 3 + ["KHONG_CO_SO"] * 3


def test_avg_source_without_avg_takes_the_previous_run_number(sel2_on):
    """R4 on a failed day: AVG_DEMAND (default) without an AVG value -> the R3' number, KHONG_CO_AVG_DUNG_LIGHTGBM +
    flag; with an AVG value the AVG value is used and lightgbm_forecast shows the previous-run number."""
    _run("RP1", D - timedelta(days=1), {("A1", "F1"): _series({h: 3 for h in range(1, 8)}),
                                        ("A2", "F1"): _series({h: 4 for h in range(1, 8)})})
    _avg(D, [("A1", "F1", "SL1", None, None), ("A2", "F1", "SL1", 1.1, None)])
    _, by, _ = _export()
    assert _pick(by, ("A1", "F1", 1)) == (3, None, 3, "KHONG_CO_AVG_DUNG_LIGHTGBM")
    assert f"LAN_CHAY_TRUOC:{_d(1)}" in _flags(by[("A1", "F1", 1)])
    assert (by[("A1", "F1", 1)]["model_version"], by[("A1", "F1", 1)]["data_cutoff_date"]) == \
        ("MV-RP1", _dt(D - timedelta(days=2)))                                  # R4 row: provenance of the source run
    assert _pick(by, ("A1", "F1", 7)) == (None, None, 0, "KHONG_CO_SO_NAO")
    assert _pick(by, ("A2", "F1", 1)) == (4, 1.1, 2, None)


def test_previous_numbers_are_rounded_and_counts_match_the_rows(sel2_on):
    """R5 on previous-run numbers (unit, fractional values) and TOM_TAT / summary counts = the DU_BAO rows."""
    k = ("S1", "F1")
    c1, c2 = D - timedelta(days=2), D - timedelta(days=3)
    prev = {k: [(0.15, 0.1, "M", None, _d(1), "MV-P1", c1), (2.0000001, 2.0, "M", None, _d(1), "MV-P1", c1),
                (0.5, 0.5, "M", None, _d(2), "MV-P2", c2)] + [None] * (export.HORIZON - 3)}
    stats = _stats()
    rows = list(export._rows(D, [k], RUN, {k: ("A", "M")}, {}, {k: {"value": 9.0, "reason": None}},
                             {k: "LIGHTGBM"}, {}, True, stats, prev, True))
    used = [r[COL["forecast_used"]] for r in rows]
    assert used[:3] == [0, 2, 1] and all(type(x) is int for x in used)
    assert [r[COL["lightgbm_forecast"]] for r in rows][:3] == [0.15, 2.0000001, 0.5]
    assert [r[COL["fallback_reason"]] for r in rows] == [PREV] * 3 + ["STALE"] * 4
    assert stats["rows_by_fallback_reason"] == {PREV: 3, "STALE": 4}
    assert stats["flag_rows"] == {f"LAN_CHAY_TRUOC:{_d(1)}": 2, f"LAN_CHAY_TRUOC:{_d(2)}": 1}
    assert [(r[COL["model_version"]], r[COL["data_cutoff_date"]]) for r in rows] == \
        [("MV-P1", c1)] * 2 + [("MV-P2", c2)] + [("MV-R1", export._day("2026-11-01"))] * 4   # AVG rows: reference run
    # workbook: counts of TOM_TAT / summary = the rows (S2 in the reference run, no AVG row, no number for D ..)
    _run("RP1", D - timedelta(days=1), {k: _series({h: h for h in range(1, 5)}), ("S2", "F1"): _series({1: 1})})
    _avg(D, [(k[0], k[1], "SL1", 2.0, None), ("S3", "F1", "SL1", 1.0, None)])
    _config([(k[0], k[1], "LIGHTGBM", None), ("S3", "F1", "LIGHTGBM", None)])
    res, by, s = _export()
    counts: dict = {}
    for r in by.values():
        counts[r["fallback_reason"] or ""] = counts.get(r["fallback_reason"] or "", 0) + 1
    assert counts == {PREV: 3, "STALE": 4, "KHONG_CO_SO_NAO": 7, "NGOAI_PHAM_VI_GAN_0": 7}
    assert res["summary"]["rows_by_fallback_reason"] == counts
    assert {k2: v for k2, v in s.items() if k2.startswith("rows_fallback_reason:")} == \
        {f"rows_fallback_reason:{x or '(none)'}": v for x, v in counts.items()}


# ------------------------------------------------------------------ tester additions (143-T1c-test)
def _counts(by) -> dict:
    out: dict = {}
    for r in by.values():
        out[r["fallback_reason"] or ""] = out.get(r["fallback_reason"] or "", 0) + 1
    return out


def _flag_counts(by) -> dict:
    out: dict = {}
    for r in by.values():
        for x in (r["flags"] or "").split(","):
            if x:
                out[x] = out.get(x, 0) + 1
    return out


def test_several_runs_of_a_previous_day_only_the_latest_of_each_day_counts(sel2_on):
    """Failed day, two runs of D-1: the later one is the reference and the only D-1 source (the earlier one of D-1 never
    gives numbers or scope, even for a day the later one lacks); missing days fall to the run of D-2. An in-scope SKU x FC
    whose reference series covers only target D-1 (horizon 1) is still in the scope: AVG + STALE, never 0. TOM_TAT
    previous_runs names one run per day; flag / reason counts of TOM_TAT = the DU_BAO rows; run flags kept."""
    _run("RP2", D - timedelta(days=2), {("S1", "F1"): _series({h: 20 + h for h in range(1, 8)})},
         created="2026-10-30T23:00:00+00:00", flags="OPEN_HOURS_LAG")
    _run("RP1a", D - timedelta(days=1), {("S1", "F1"): _series({h: 11 for h in range(1, 8)}),
                                         ("S5", "F1"): _series({h: 55 for h in range(1, 8)})},
         created="2026-10-31T22:00:00+00:00")
    _run("RP1b", D - timedelta(days=1), {("S1", "F1"): _series({1: 1}), ("S2", "F1"): _series({h: 5 for h in range(1, 8)}),
                                         ("S3", "F1"): _series({1: 9})},
         created="2026-10-31T23:00:00+00:00")
    _avg(D, [("S1", "F1", "SL1", 1.5, None), ("S3", "F1", "SL1", 2.5, None), ("S5", "F1", "SL1", 4.0, None)])
    _config([(s, "F1", "LIGHTGBM", None) for s in ("S1", "S2", "S3", "S5")])
    res, by, s = _export()
    assert res["is_stale"] is True and s["refresh_run_id"] == "RP1b"
    assert s["previous_runs"] == f"{_d(1)}:RP1b,{_d(2)}:RP2"
    # S1: RP1b has no target day of the file -> RP2 (targets D-2 .. D+4), never RP1a's 11
    assert [_pick(by, ("S1", "F1", h))[2] for h in range(1, 8)] == [23, 24, 25, 26, 27, 2, 2]
    assert [by[("S1", "F1", h)]["fallback_reason"] for h in range(1, 8)] == [PREV] * 5 + ["STALE"] * 2
    assert _flags(by[("S1", "F1", 1)])[:2] == ["OPEN_HOURS_LAG", f"LAN_CHAY_TRUOC:{_d(2)}"]   # run flags kept
    assert all(_pick(by, ("S2", "F1", h)) == (5, None, 5, PREV) for h in range(1, 7))
    assert _pick(by, ("S2", "F1", 7)) == (None, None, 0, "KHONG_CO_SO_NAO")
    # S3 in the reference scope (only target D-1): no number of the window -> AVG + STALE (never R2)
    assert all(_pick(by, ("S3", "F1", h)) == (None, 2.5, 3, "STALE") for h in range(1, 8))
    # S5 only in the earlier run of D-1: outside the reference scope -> 0
    assert all(_pick(by, ("S5", "F1", h)) == (None, 4.0, 0, "NGOAI_PHAM_VI_GAN_0") for h in range(1, 8))
    assert not any(r["lightgbm_forecast"] in (11, 55) for r in by.values())
    counts = _counts(by)
    assert sum(counts.values()) == s["rows_total"] == 4 * 7 and res["n_rows"] == 4 * 20
    assert {k: v for k, v in s.items() if k.startswith("rows_fallback_reason:")} == \
        {f"rows_fallback_reason:{x or '(none)'}": v for x, v in counts.items()}
    assert {k: v for k, v in s.items() if k.startswith("rows_flag:")} == \
        {f"rows_flag:{x}": v for x, v in _flag_counts(by).items()}
    assert s[f"rows_flag:LAN_CHAY_TRUOC:{_d(1)}"] == 6 and s[f"rows_flag:LAN_CHAY_TRUOC:{_d(2)}"] == 5


def test_previous_day_runs_with_the_same_created_at_use_the_last_inserted(sel2_on):
    """Tie on created_at (one-second resolution) between two runs of D-1: the run inserted last is both the reference
    and the R3' source (rowid DESC in both queries)."""
    _run("RPx", D - timedelta(days=1), {("S1", "F1"): _series({h: 7 for h in range(1, 8)}),
                                        ("S2", "F1"): _series({h: 7 for h in range(1, 8)})})
    _run("RPy", D - timedelta(days=1), {("S1", "F1"): _series({h: 8 for h in range(1, 8)})})
    _avg(D, [("S1", "F1", "SL1", 1.0, None), ("S2", "F1", "SL1", 1.0, None)])
    _config([("S1", "F1", "LIGHTGBM", None), ("S2", "F1", "LIGHTGBM", None)])
    res, by, s = _export()
    assert s["refresh_run_id"] == "RPy" and s["previous_runs"] == f"{_d(1)}:RPy"
    assert _pick(by, ("S1", "F1", 1)) == (8, 1.0, 8, PREV)
    assert _pick(by, ("S2", "F1", 1)) == (None, 1.0, 0, "NGOAI_PHAM_VI_GAN_0")


def test_runs_of_another_scope_or_not_sel2_never_supply_numbers(sel2_on):
    """Runs of another scope_key (today and D-1) and a non-SEL2 run of D-1 are ignored: the reference is searched in
    SCOPE only; its latest SEL2 run is of D-5 -> every LIGHTGBM row AVG + STALE, previous_runs empty."""
    from app import db
    from test_v140_t5t6_edges import _run as _run_cv
    _run("RP5", D - timedelta(days=5), {("S1", "F1"): _series({h: 50 for h in range(1, 8)})})
    _run("RX0", D, {("S1", "F1"): _series({h: 60 for h in range(1, 8)})}, scope="SC-OTHER")
    _run("RX1", D - timedelta(days=1), {("S1", "F1"): _series({h: 61 for h in range(1, 8)})}, scope="SC-OTHER")
    _run_cv("RV1", D - timedelta(days=1), {("S1", "F1"): {h: 62 for h in range(1, 8)}}, "2026-11-01T23:00:00+00:00",
            config_version="V33:xyz", scope=SCOPE)
    _avg(D, [("S1", "F1", "SL1", 2.2, None), ("S2", "F1", "SL1", 0.7, None)])
    _config([("S1", "F1", "LIGHTGBM", None), ("S2", "F1", "LIGHTGBM", None)])
    res, by, s = _export()
    assert res["is_stale"] is True and s["refresh_run_id"] == "RP5" and s["previous_runs"] is None
    assert all(_pick(by, ("S1", "F1", h)) == (None, 2.2, 3, "STALE") for h in range(1, 8))
    assert all(_pick(by, ("S2", "F1", h)) == (None, 0.7, 1, "STALE") for h in range(1, 8))   # never 0 by R2
    assert not any(r["lightgbm_forecast"] for r in by.values())
    with db.read() as c:
        assert [(r["id"], r["forecast_date"]) for r in export._previous_runs(c, "SC-OTHER", D)] == [("RX1", _d(1))]


def test_vietnam_day_comes_from_forecast_date_not_the_utc_creation_time(sel2_on):
    """Today's run created at 2026-11-01T17:30Z (00:30 of D in Vietnam) and a run of D-1 created later in UTC
    (2026-11-01T18:00Z): today's run is the reference (not stale), the run of D-1 only fills its missing days (R3')."""
    _run("R0", D, {("S1", "F1"): _series({1: 4, 2: 4})}, created="2026-11-01T17:30:00+00:00")
    _run("RP1", D - timedelta(days=1), {("S1", "F1"): _series({h: 9 for h in range(1, 8)}),
                                        ("S2", "F1"): _series({h: 9 for h in range(1, 8)})},
         created="2026-11-01T18:00:00+00:00")
    _avg(D, [("S1", "F1", "SL1", 1.0, None), ("S2", "F1", "SL1", 1.0, None)])
    _config([("S1", "F1", "LIGHTGBM", None), ("S2", "F1", "LIGHTGBM", None)])
    res, by, s = _export()
    assert res["is_stale"] is False and s["refresh_run_id"] == "R0" and s["previous_runs"] == f"{_d(1)}:RP1"
    assert [_pick(by, ("S1", "F1", h))[2:] for h in range(1, 8)] == \
        [(4, None), (4, None)] + [(9, PREV)] * 4 + [(1, "KHONG_CO_SO")]
    assert all(_pick(by, ("S2", "F1", h)) == (None, 1.0, 0, "NGOAI_PHAM_VI_GAN_0") for h in range(1, 8))


def test_run_of_a_later_day_never_fills_an_earlier_export(sel2_on):
    """Re-export of D with runs of D and D+1: a day today's run lacks takes the run of D-1 (window D-3 .. D-1), never
    the run of D+1."""
    _run("RP1", D - timedelta(days=1), {("S1", "F1"): _series({h: 3 for h in range(1, 8)})})
    _run("R0", D, {("S1", "F1"): _series({1: 1})}, created="2026-11-02T00:30:00+00:00")
    _run("RN1", D + timedelta(days=1), {("S1", "F1"): _series({h: 70 for h in range(1, 8)})},
         created="2026-11-03T00:30:00+00:00")
    _avg(D, [("S1", "F1", "SL1", 1.0, None)])
    _config([("S1", "F1", "LIGHTGBM", None)])
    res, by, s = _export()
    assert s["refresh_run_id"] == "R0" and s["previous_runs"] == f"{_d(1)}:RP1"
    assert [_pick(by, ("S1", "F1", h))[2] for h in range(1, 8)] == [1, 3, 3, 3, 3, 3, 1]
    assert not any(r["lightgbm_forecast"] == 70 for r in by.values())


def test_avg_source_outside_the_reference_scope_never_takes_an_older_window_number(sel2_on):
    """R4 + R3' scope: an AVG_DEMAND SKU x FC without AVG that is only in the run of D-2 (not in the reference run of
    D-1) gets no previous number (R3' looks up the reference scope only) -> 0 + KHONG_CO_SO_NAO; inside the reference
    scope it gets the number of D-2 for a day D-1 lacks (KHONG_CO_AVG_DUNG_LIGHTGBM + flag)."""
    _run("RP2", D - timedelta(days=2), {("A1", "F1"): _series({h: 6 for h in range(1, 8)}),
                                        ("A9", "F1"): _series({h: 6 for h in range(1, 8)})},
         created="2026-10-30T23:00:00+00:00")
    _run("RP1", D - timedelta(days=1), {("A1", "F1"): _series({1: 1})})
    _avg(D, [("A1", "F1", "SL1", None, None), ("A9", "F1", "SL1", None, None)])
    _, by, _ = _export()
    assert _pick(by, ("A1", "F1", 1)) == (6, None, 6, "KHONG_CO_AVG_DUNG_LIGHTGBM")
    assert f"LAN_CHAY_TRUOC:{_d(2)}" in _flags(by[("A1", "F1", 1)])
    assert _pick(by, ("A1", "F1", 6)) == (None, None, 0, "KHONG_CO_SO_NAO")       # D+5 beyond the run of D-2
    assert all(_pick(by, ("A9", "F1", h)) == (None, None, 0, "KHONG_CO_SO_NAO") for h in range(1, 8))


def test_previous_run_query_is_bounded_to_three_days(sel2_on):
    """Performance sanity: with runs on 12 days (two per day, other scope too) _previous_runs returns at most the 3
    latest runs of D-3 .. D-1 (newest day first) and _previous_values reads forecast_refresh_values of those 3 runs
    only, never when no SKU x FC needs a lookup."""
    from app import db
    for n in range(-1, 11):                                    # D+1 .. D-10
        day = D - timedelta(days=n)
        for j, t in enumerate(("22:00", "23:00")):
            _run(f"R{n}_{j}", day, {("S1", "F1"): _series({h: n + 1 for h in range(1, 8)})},
                 created=f"{(day - timedelta(days=1)).isoformat()}T{t}:00+00:00")
        _run(f"X{n}", day, {("S1", "F1"): _series({1: 1})}, scope="SC-OTHER")
    days = [(D + timedelta(days=i)).isoformat() for i in range(export.HORIZON)]
    with db.read() as c:
        prev = export._previous_runs(c, SCOPE, D)
        assert prev == [{"id": f"R{n}_1", "forecast_date": _d(n), "model_version": f"MV-R{n}_1",   # + provenance
                         "data_cutoff": D - timedelta(days=n + 1)} for n in (1, 2, 3)]
        assert export._previous_runs(c, None, D) == []
        sql: list[str] = []
        c.set_trace_callback(sql.append)
        assert export._previous_values(c, prev, days, set()) == {}
        assert not sql
        vals = export._previous_values(c, prev, days, None)
        c.set_trace_callback(None)
    reads = [q for q in sql if "forecast_refresh_values" in q]
    assert len(reads) == 3 and all(f"'R{n}_1'" in q for n, q in zip((1, 2, 3), reads))
    assert [v[0] if v else None for v in vals[("S1", "F1")]] == [2, 2, 2, 2, 2, 2, None]
    assert [v[4] for v in vals[("S1", "F1")][:6]] == [_d(1)] * 6
