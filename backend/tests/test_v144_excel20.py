"""1.4.4: 20-day layout of the daily Excel written by the app (ml/sel2/export.py, owner decision 05/11/2026 evening).
Acceptance: for the same input, the app's file equals CELL BY CELL (and byte by byte per DU_BAO_* sheet) the file the ops
script scripts/ops/excel20.py (read-only reference, its functions imported) makes from the 1.4.3 layout of the same
export; plus rule cases of horizon 8..20, weekday mapping, row counts, header order, cach_tinh, TOM_TAT, export_runs and
the refusal of a too large warehouse. Integration with fakes (isolated temporary database, rows inserted directly)."""
import hashlib
import importlib.util
import json
import logging
import os
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from app import __version__, db, paths
from app.messages import AppError
from app.ml.sel2 import export
from app.ml.sel2.xlsx_stream import Sheet, write_xlsx
from test_v140_t6_export import COLS, D, SCOPE, _avg, _config, _dt, _run  # tests/ on path

# the ops script of this source tree (scripts/ops/excel20.py, versioned with the app)
SCRIPT = Path(os.environ.get("DF_EXCEL20_SCRIPT") or Path(__file__).resolve().parents[2] / "scripts" / "ops" / "excel20.py")
COLS20 = COLS + ["cach_tinh"]
NAME_S1 = "Thuoc <A> & B "                   # escaped + trailing space: kept through the round trip
PREV, OUT0, NONE, NONUM, AVGL = ("DUNG_SO_LAN_CHAY_TRUOC", "NGOAI_PHAM_VI_GAN_0", "KHONG_CO_SO", "KHONG_CO_SO_NAO",
                                 "KHONG_CO_AVG_DUNG_LIGHTGBM")


@pytest.fixture(scope="module")
def x20():
    """The ops script, loaded read-only (no bytecode written next to it; sys.path / sys.modules restored)."""
    assert SCRIPT.is_file(), f"reference script not found: {SCRIPT}"
    path0, dont0 = list(sys.path), sys.dont_write_bytecode
    saved = {m: sys.modules.pop(m) for m in ("notify", "common") if m in sys.modules}
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("x20_reference", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = path0
        sys.dont_write_bytecode = dont0
        for m in ("notify", "common"):                  # the runner folder's modules: kept by the script only
            sys.modules.pop(m, None)
        sys.modules.update(saved)
    mod.O = SimpleNamespace(now="2026-11-02 07:00", dry_run=True, force=False)
    return mod


@pytest.fixture
def scenario(sel2_on):
    """Two warehouses (HN given first, BD sorted first). Run R1 of D (flag OPEN_HOURS_LAG), run RP of D-1.
    BD: S1 LIGHTGBM full (h1 = 0 with raw 0.1), S2 LIGHTGBM h1..4 today + RP for the rest (R3'), S6 LIGHTGBM h1..2 no AVG
        (KHONG_CO_SO_NAO), S8 LIGHTGBM outside the scope (R2), S10 AVG_DEMAND 0.15 (rounded to 0).
    HN: S3 AVG_DEMAND 2.5 with numbers, S4 AVG_DEMAND without AVG (KHONG_CO_AVG_DUNG_LIGHTGBM), S5 LIGHTGBM h1..3 AVG 1.3
        (KHONG_CO_SO), S7 LIGHTGBM numbers without raw_value, S9 AVG seller rule pending, MEDX.X LIGHTGBM outside."""
    full = {h: (h, h - 0.4) for h in range(1, 8)}
    _run("RP", D - timedelta(days=1), {("S2", "BD"): ("B", "OLD", {h: (50 + h, 50.25 + h) for h in range(1, 8)})},
         created="2026-11-01T00:30:00+00:00")
    _run("R1", D, {("S1", "BD"): ("A", "MOC+DOW4", {**full, 1: (0, 0.1)}),
                   ("S2", "BD"): ("B", "MOC+DOW4", {h: (h + 10, h + 9.7) for h in range(1, 5)}),
                   ("S6", "BD"): ("C", "MOC+DOW4", {1: (1, 1.0), 2: (2, 2.0)}),
                   ("S3", "HN"): ("A", "FALLBACK:V33_L112", full),
                   ("S4", "HN"): ("A", "MOC+DOW4", {h: (h, h + 0.05) for h in range(1, 8)}),
                   ("S5", "HN"): ("B", "MOC+DOW4", {h: (h, h - 0.5) for h in range(1, 4)}),
                   ("S7", "HN"): ("C", "MOC+DOW4", {h: (4, None) for h in range(1, 8)})},
         created="2026-11-01T23:30:00+00:00", flags="OPEN_HOURS_LAG")
    _avg(D, [("S1", "BD", "SL1", 2.0, NAME_S1), ("S3", "HN", "SL1", 2.5, "Thuoc C"), ("S5", "HN", "SL1", 1.3, None),
             ("S8", "BD", "SL1", 5.0, None), ("S10", "BD", "SL1", 0.15, None), ("S9", "HN", "SL1", 1.0, None),
             ("S9", "HN", "SL2", 2.0, None), ("MEDX.X", "HN", "SL1", 3.0, "Medx X")])
    _config([(s, f, "LIGHTGBM", None) for s, f in (("S1", "BD"), ("S2", "BD"), ("S6", "BD"), ("S8", "BD"),
                                                    ("S5", "HN"), ("S7", "HN"), ("MEDX.X", "HN"))])


def _sheet_xml(p: Path) -> dict:
    """{sheet name: worksheet XML bytes}."""
    import re
    with zipfile.ZipFile(p) as z:
        wb = z.read("xl/workbook.xml").decode()
        names = re.findall(r'<sheet name="([^"]*)" sheetId="(\d+)"', wb)
        return {n: z.read(f"xl/worksheets/sheet{i}.xml") for n, i in names}


def _cells(p: Path) -> dict:
    wb = load_workbook(p, read_only=True)
    out = {n: [[(type(v).__name__, v) for v in r] for r in wb[n].iter_rows(values_only=True)] for n in wb.sheetnames}
    wb.close()
    return out


def _rows(p: Path) -> dict:
    """{sheet: [row dicts]} of the DU_BAO_* sheets (header checked)."""
    wb = load_workbook(p, read_only=True)
    out = {}
    for n in wb.sheetnames:
        if n.startswith("DU_BAO_"):
            rows = list(wb[n].iter_rows(values_only=True))
            assert list(rows[0]) == COLS20
            out[n] = [dict(zip(COLS20, r)) for r in rows[1:]]
    wb.close()
    return out


def _export_with_old_layout(monkeypatch, tmp_path) -> tuple[dict, Path]:
    """write_daily_export; its _write_book also writes the 1.4.3 layout (sheet DU_BAO, _rows of every SKU x FC in
    order) of the same input to tmp_path / old.xlsx before the 20-day file (the counts are reset in between)."""
    orig = export._write_book
    old = tmp_path / "old.xlsx"

    def both(target, d, plan, rows_for, summary_rows, config_rows):
        keys = sorted(k for _, ks in plan for k in ks)
        rows7 = list(rows_for(keys))
        summary = [r for r in summary_rows]
        summary = summary[:[r[0] for r in summary].index("layout")]   # the 1.4.3 TOM_TAT
        write_xlsx(old, [Sheet(export.SHEET_MAIN, export.COLUMNS, rows7, len(rows7), freeze_header=True,
                               autofilter=True),
                         Sheet(export.SHEET_SUMMARY, export.SUMMARY_COLUMNS, summary),
                         Sheet(export.SHEET_CONFIG, export.CONFIG_COLUMNS, config_rows, len(config_rows),
                               freeze_header=True, autofilter=True)])
        summary_rows.summary["rows_by_fallback_reason"].clear()
        summary_rows.summary["flag_rows"].clear()
        return orig(target, d, plan, rows_for, summary_rows, config_rows)

    monkeypatch.setattr(export, "_write_book", both)
    return export.write_daily_export(D, scope_key=SCOPE), old


def test_app_file_equals_the_ops_script_cell_by_cell(scenario, x20, monkeypatch, tmp_path):
    res, old = _export_with_old_layout(monkeypatch, tmp_path)
    app = paths.data_dir() / res["path"]
    ref = tmp_path / "x20.xlsx"
    src = x20.read_source(old, D)
    assert src["layout"] == "1.4.3" and src["n_rows"] == 11 * 7
    header, plan, n_summary = x20.build(src, D, ref, (Sheet, write_xlsx, "app xlsx_stream"), old.name,
                                        hashlib.sha256(old.read_bytes()).hexdigest())
    x20.verify(ref, D, src, header, plan, n_summary)
    x20.verify(app, D, src, header, plan, n_summary - 1)    # the script's own checks pass on the app's file
    plan_names = [p[0] for p in plan]
    assert header == COLS20 and plan_names == ["DU_BAO_BD", "DU_BAO_HN"]
    a, b = _cells(app), _cells(ref)
    assert list(a) == list(b) == ["DU_BAO_BD", "DU_BAO_HN", "TOM_TAT", "CONFIG"]
    diffs = [(n, i, j) for n in a if n.startswith("DU_BAO_") for i, (ra, rb) in enumerate(zip(a[n], b[n]))
             for j in range(max(len(ra), len(rb))) if (ra + [None] * 30)[j] != (rb + [None] * 30)[j]]
    assert diffs == [] and [len(a[n]) for n in plan_names] == [len(b[n]) for n in plan_names] == [101, 121]
    xa, xb = _sheet_xml(app), _sheet_xml(ref)
    assert all(xa[n] == xb[n] for n in ("DU_BAO_BD", "DU_BAO_HN", "CONFIG"))       # same bytes per sheet
    # TOM_TAT differs only in the source rows (the app names itself; the script names its source file + sha256)
    ta = [r for r in a["TOM_TAT"] if r[0][1] not in ("source", "generated_at")]
    tb = [r for r in b["TOM_TAT"] if r[0][1] not in ("source_file", "source_sha256", "generated_at")]
    assert ta == tb
    s = {r[0][1]: r[1][1] for r in a["TOM_TAT"][1:]}
    assert s["source"] == f"Demand Forecast {__version__} (ghi truc tiep)" and s["generated_at"].endswith(" (VN)")
    assert s["generated_at"] == res["summary"]["created_at_vn"] + " (VN)"


def test_rule_cases_of_horizon_8_to_20(scenario):
    res = export.write_daily_export(D, scope_key=SCOPE)
    sheets = _rows(paths.data_dir() / res["path"])
    by = {(r["sku_code"], r["fc_code"], r["horizon"]): r for rows in sheets.values() for r in rows}
    pick = lambda k: (by[k]["lightgbm_forecast"], by[k]["forecast_used"], by[k]["fallback_reason"], by[k]["cach_tinh"])
    # keep 0: h1 is 0 (R1); h8 = template h1, raw 0.1 rounds to 0, no reason
    assert pick(("S1", "BD", 1)) == (0, 0, None, "SEL2") and pick(("S1", "BD", 8)) == (0.1, 0, None, "UOC_TINH_THEO_TUAN")
    assert pick(("S1", "BD", 9)) == (pytest.approx(1.6), 2, None, "UOC_TINH_THEO_TUAN")
    assert by[("S1", "BD", 9)]["ten_san_pham"] == NAME_S1 and by[("S1", "BD", 9)]["avg_demand"] == 2.0
    # previous run (R3'): h5..7 from RP, h12..14 = raw of RP rounded up, reason kept
    assert pick(("S2", "BD", 5)) == (56, 56, PREV, "SEL2") and pick(("S2", "BD", 12)) == (56.25, 57, PREV,
                                                                                            "UOC_TINH_THEO_TUAN")
    assert by[("S2", "BD", 12)]["flags"] == by[("S2", "BD", 5)]["flags"] == "LAN_CHAY_TRUOC:2026-11-01,AVG_NO_ROW"
    assert by[("S2", "BD", 12)]["model_version"] == "MV-RP" and pick(("S2", "BD", 8)) == (10.7, 11, None,
                                                                                          "UOC_TINH_THEO_TUAN")
    # LIGHTGBM in the scope without any number -> 0 KHONG_CO_SO_NAO, kept at h8..20
    assert pick(("S6", "BD", 3)) == (None, 0, NONUM, "SEL2") and pick(("S6", "BD", 10)) == (None, 0, NONUM,
                                                                                             "UOC_TINH_THEO_TUAN")
    # outside the scope -> 0 (R2), never the AVG value, at every horizon
    assert all(pick(("S8", "BD", h))[1:3] == (0, OUT0) for h in range(1, 21))
    # AVG_DEMAND 0.15 -> 0; AVG_DEMAND 2.5 -> 3 at every horizon although LightGBM numbers exist
    assert all(by[("S10", "BD", h)]["forecast_used"] == 0 for h in range(1, 21))
    assert all(by[("S3", "HN", h)]["forecast_used"] == 3 and by[("S3", "HN", h)]["fallback_reason"] is None
               for h in range(1, 21))
    assert by[("S3", "HN", 15)]["lightgbm_forecast"] == pytest.approx(0.6)            # raw of h1 (1 - 0.4)
    # AVG_DEMAND without AVG -> the LightGBM number; h8..20 the raw rounded up
    assert pick(("S4", "HN", 2)) == (2, 2, AVGL, "SEL2") and pick(("S4", "HN", 9)) == (2.05, 3, AVGL,
                                                                                      "UOC_TINH_THEO_TUAN")
    # Avg fallback in the scope (KHONG_CO_SO): no raw at the template -> the template's value and reason
    assert pick(("S5", "HN", 4)) == (None, 2, NONE, "SEL2") and pick(("S5", "HN", 11)) == (None, 2, NONE,
                                                                                          "UOC_TINH_THEO_TUAN")
    assert pick(("S5", "HN", 8)) == (0.5, 1, None, "UOC_TINH_THEO_TUAN")
    # numbers without raw_value: h8..20 keep the template's number
    assert all(pick(("S7", "HN", h))[:3] == (None, 4, None) for h in range(8, 21))
    assert pick(("S9", "HN", 20)) == (None, 0, NONUM, "UOC_TINH_THEO_TUAN")
    assert all(pick(("MEDX.X", "HN", h))[1:3] == (0, OUT0) for h in range(1, 21))
    assert (by[("MEDX.X", "HN", 13)]["seller_code"], by[("MEDX.X", "HN", 13)]["product_code"]) == ("MEDX", "X")
    assert all(type(r["forecast_used"]) is int and r["forecast_used"] >= 0 for r in by.values())


def test_weekday_mapping_counts_header_and_cach_tinh(scenario):
    res = export.write_daily_export(D, scope_key=SCOPE)
    p = paths.data_dir() / res["path"]
    sheets = _rows(p)
    assert list(sheets) == ["DU_BAO_BD", "DU_BAO_HN"]
    n_keys = {"DU_BAO_BD": 5, "DU_BAO_HN": 6}
    for name, rows in sheets.items():
        assert len(rows) == n_keys[name] * 20
        fc = name.removeprefix("DU_BAO_")
        assert {r["fc_code"] for r in rows} == {fc}
        skus = [r["sku_code"] for r in rows[::20]]
        assert skus == sorted(skus)
        for i in range(0, len(rows), 20):
            block = rows[i:i + 20]
            assert len({(r["sku_code"], r["fc_code"]) for r in block}) == 1
            assert [r["horizon"] for r in block] == list(range(1, 21))
            assert [r["target_date"] for r in block] == [_dt(D + timedelta(days=h)) for h in range(20)]
            assert all(r["forecast_date"] == _dt(D) for r in block)
            assert [r["cach_tinh"] for r in block] == ["SEL2"] * 7 + ["UOC_TINH_THEO_TUAN"] * 13
            for r in block[7:]:
                t = block[(r["horizon"] - 1) % 7]
                assert r["target_date"].weekday() == t["target_date"].weekday()
                same = [c for c in COLS if c not in ("target_date", "horizon", "lightgbm_forecast", "forecast_used",
                                                     "fallback_reason")]
                assert [r[c] for c in same] == [t[c] for c in same]
    assert res["n_rows"] == 11 * 20 == res["summary"]["n_rows"] and res["summary"]["n_rows_h1_7"] == 11 * 7
    with db.read() as c:
        assert c.execute("SELECT n_rows FROM export_runs").fetchone()[0] == 220
    wb = load_workbook(p)
    assert wb.sheetnames == ["DU_BAO_BD", "DU_BAO_HN", "TOM_TAT", "CONFIG"]
    for n in wb.sheetnames:
        ws = wb[n]
        assert ws.freeze_panes == "A2" and ws.auto_filter.ref and all(c.font.b for c in ws[1])
    assert wb["DU_BAO_BD"].auto_filter.ref == "A1:U101" and wb["DU_BAO_HN"].auto_filter.ref == "A1:U121"
    s = {r[0]: r[1] for r in wb["TOM_TAT"].iter_rows(min_row=2, values_only=True)}
    assert s["rows_total"] == 77 and s["layout"] == "20 ngay, tach sheet theo kho"
    assert s["horizon_8_20"] == export.NOTE_8_20
    assert (s["rows:DU_BAO_BD"], s["rows:DU_BAO_HN"], s["sku_fc:DU_BAO_BD"], s["sku_fc:DU_BAO_HN"]) == (100, 120, 5, 6)
    assert sum(v for k, v in s.items() if k.startswith("rows_fallback_reason:")) == 77   # counts of horizon 1..7
    assert res["summary"]["layout"] == {"sheets": {"DU_BAO_BD": 100, "DU_BAO_HN": 120},
                                        "sku_fc": {"DU_BAO_BD": 5, "DU_BAO_HN": 6}}


def test_derive_used_truth_table():
    du = export.derive_used
    assert du("LIGHTGBM", 0, OUT0, 5.0) == (0, OUT0) and du("AVG_DEMAND", 0, OUT0, None) == (0, OUT0)
    assert du("LIGHTGBM", 3, None, 0.19) == (0, None) and du("LIGHTGBM", 3, None, 0.2) == (1, None)
    assert du("LIGHTGBM", 3, None, 2.0000004) == (2, None) and du("LIGHTGBM", 3, PREV, 2.1) == (3, PREV)
    assert du("LIGHTGBM", 3, NONE, 4.5) == (5, None)                # a raw value wins over the template's Avg
    assert du("LIGHTGBM", 2, NONE, None) == (2, NONE) and du("LIGHTGBM", 0, NONUM, None) == (0, NONUM)
    assert du("LIGHTGBM", None, "STALE", None) == (0, NONUM) and du("LIGHTGBM", -1.0, None, None) == (0, None)
    assert du("AVG_DEMAND", 3, None, 9.0) == (3, None) and du("AVG_DEMAND", 3, AVGL, 4.2) == (5, AVGL)
    assert du("AVG_DEMAND", 3, AVGL, None) == (3, AVGL) and du("AVG_DEMAND", 0, NONUM, 7.0) == (0, NONUM)
    assert export._num(float("nan")) is None and export._num(True) is None and export._num("x") is None


def test_sheet_names_and_plan():
    assert export.sheet_name("BD") == "DU_BAO_BD" and export.sheet_name(None) == "DU_BAO_KHONG_FC"
    assert export.sheet_name("a/b:c*?[x]'") == "DU_BAO_a_b_c___x__" and len(export.sheet_name("F" * 40)) == 31
    keys = [("A", "HN"), ("B", "BD"), ("C", "HN")]
    assert export._sheet_plan(keys) == [("DU_BAO_BD", [("B", "BD")]), ("DU_BAO_HN", [("A", "HN"), ("C", "HN")])]
    with pytest.raises(ValueError, match="SHEET_NAME_CLASH"):
        export._sheet_plan([("A", "X/Y"), ("A", "X:Y")])
    assert export._sheet_plan([]) == []


def test_too_many_sku_fc_in_a_warehouse_writes_nothing(scenario, monkeypatch, caplog):
    monkeypatch.setattr(export, "MAX_SKU_FC", 5)                  # HN has 6 SKU x FC
    with caplog.at_level(logging.ERROR, logger="df.sel2.export"), pytest.raises(AppError) as e:
        export.write_daily_export(D, scope_key=SCOPE)
    assert e.value.code == "SEL2_EXPORT_WRITE_FAILED" and "TOO_MANY_SKU_FC" in str(e.value.detail)
    assert "DU_BAO_BD" not in str(e.value.detail) and "'HN': 6" in str(e.value.detail)
    assert any(getattr(r, "ctx", {}).get("flag") == "TOO_MANY_SKU_FC" for r in caplog.records)
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM export_runs").fetchone()[0] == 0
    folder = paths.data_dir() / "exports" / "du_bao" / D.strftime("%Y%m%d")
    assert not folder.exists() or not any(folder.iterdir())
    monkeypatch.setattr(export, "MAX_SKU_FC", 6)                  # at the limit: written
    assert export.write_daily_export(D, scope_key=SCOPE)["n_rows"] == 220


def test_temp_export_uses_the_20_day_layout(sel2_on):
    from test_v140_b6_bootstrap import SCOPE as B6_SCOPE, _store_candidates
    _store_candidates(v33={("S1", "HN"): [2.3] * 7, ("S2", "BD"): [0.5] * 7}, scope=B6_SCOPE)
    _config([("S1", "HN", "LIGHTGBM", None)])
    res = export.write_temp_export(D, groups={}, scope_key=B6_SCOPE)
    sheets = _rows(paths.data_dir() / res["path"])
    assert list(sheets) == ["DU_BAO_BD", "DU_BAO_HN"] and res["n_rows"] == 40
    s1 = sheets["DU_BAO_HN"]
    assert [r["forecast_used"] for r in s1] == [3] * 20 and s1[19]["lightgbm_forecast"] == pytest.approx(2.3)
    assert [r["cach_tinh"] for r in s1].count("UOC_TINH_THEO_TUAN") == 13
    wb = load_workbook(paths.data_dir() / res["path"], read_only=True)
    s = {r[0]: r[1] for r in wb["TOM_TAT"].iter_rows(min_row=2, values_only=True)}
    wb.close()
    assert s["ghi_chu"] == export.TEMP_NOTE and s["rows_total"] == 14 and s["rows:DU_BAO_HN"] == 20


# ------------------------------------------------------------------ 144-T1-test (tester): stale days, Avg templates,
# warehouse codes, empty input, n_rows, TOM_TAT order, latest copy, size sanity. Integration with fakes.
def _compare_with_script(x20, monkeypatch, tmp_path) -> tuple[dict, Path]:
    """write_daily_export + the ops script on the 1.4.3 layout of the same input: every DU_BAO_* sheet equal cell by
    cell and byte by byte; returns (result, app file)."""
    res, old = _export_with_old_layout(monkeypatch, tmp_path)
    app = paths.data_dir() / res["path"]
    ref = tmp_path / "x20.xlsx"
    src = x20.read_source(old, D)
    header, plan, n_summary = x20.build(src, D, ref, (Sheet, write_xlsx, "app xlsx_stream"), old.name,
                                        hashlib.sha256(old.read_bytes()).hexdigest())
    x20.verify(app, D, src, header, plan, n_summary - 1)
    a, b = _cells(app), _cells(ref)
    assert list(a) == list(b)
    for n in a:
        if n.startswith("DU_BAO_"):
            assert a[n] == b[n], n
    xa, xb = _sheet_xml(app), _sheet_xml(ref)
    assert all(xa[n] == xb[n] for n in xa if n.startswith("DU_BAO_"))
    return res, app


def _summary_of(p: Path) -> list:
    wb = load_workbook(p, read_only=True)
    rows = [tuple(r) for r in wb["TOM_TAT"].iter_rows(values_only=True)]
    wb.close()
    return rows


@pytest.fixture
def stale_day(sel2_on):
    """No run for D; RP of D-1 (reference run, R3'). BD: S1 LIGHTGBM AVG 2.4 (h1..6 from RP h2..7, h7 AVG + STALE),
    S2 AVG_DEMAND without an AVG row (R4 with the R3' number), S3 LIGHTGBM outside RP's scope (R2)."""
    _run("RP", D - timedelta(days=1), {("S1", "BD"): ("A", "MOC+DOW4", {h: (h * 10, h * 10 - 0.3) for h in range(1, 8)}),
                                       ("S2", "BD"): ("B", "MOC+DOW4", {h: (h, h + 0.25) for h in range(1, 8)})},
         created="2026-11-01T00:30:00+00:00", flags="OPEN_HOURS_LAG")
    _avg(D, [("S1", "BD", "SL1", 2.4, None), ("S3", "BD", "SL1", 1.0, None)])
    _config([("S1", "BD", "LIGHTGBM", None), ("S3", "BD", "LIGHTGBM", None)])


def test_stale_day_previous_run_rows_keep_flag_and_reason_at_h8_20(stale_day):
    res = export.write_daily_export(D, scope_key=SCOPE)
    p = paths.data_dir() / res["path"]
    rows = _rows(p)["DU_BAO_BD"]
    by = {(r["sku_code"], r["horizon"]): r for r in rows}
    pick = lambda k: (by[k]["lightgbm_forecast"], by[k]["forecast_used"], by[k]["fallback_reason"], by[k]["cach_tinh"])
    lan = "LAN_CHAY_TRUOC:2026-11-01"
    assert res["is_stale"] is True and len(rows) == 3 * 20 and all(r["is_stale"] == 1 for r in rows)
    # S1: h1 = RP h2 (R3'); h8 = template h1: raw of RP h2 rounded up, reason + run-day flag + provenance kept
    assert pick(("S1", 1)) == (20, 20, PREV, "SEL2") and pick(("S1", 8)) == (19.7, 20, PREV, "UOC_TINH_THEO_TUAN")
    assert pick(("S1", 13)) == (69.7, 70, PREV, "UOC_TINH_THEO_TUAN")
    for h in (1, 8, 15):
        assert by[("S1", h)]["flags"] == f"OPEN_HOURS_LAG,{lan}" and by[("S1", h)]["model_version"] == "MV-RP"
        assert by[("S1", h)]["data_cutoff_date"] == _dt(D - timedelta(days=2))
    # D+6 is RP's horizon 8: AVG + STALE, copied to h14 / h20 (no raw at the template)
    assert pick(("S1", 7)) == (None, 3, "STALE", "SEL2") and pick(("S1", 14)) == (None, 3, "STALE", "UOC_TINH_THEO_TUAN")
    assert by[("S1", 14)]["flags"] is None and by[("S1", 14)]["target_date"] == _dt(D + timedelta(days=13))
    # S2 AVG_DEMAND without AVG: the R3' number (KHONG_CO_AVG_DUNG_LIGHTGBM), h8..20 its raw rounded up
    assert pick(("S2", 1)) == (2, 2, AVGL, "SEL2") and pick(("S2", 8)) == (2.25, 3, AVGL, "UOC_TINH_THEO_TUAN")
    assert by[("S2", 8)]["flags"] == f"OPEN_HOURS_LAG,{lan},AVG_NO_ROW"
    assert pick(("S2", 7)) == (None, 0, NONUM, "SEL2") and pick(("S2", 14)) == (None, 0, NONUM, "UOC_TINH_THEO_TUAN")
    assert pick(("S2", 20)) == (7.25, 8, AVGL, "UOC_TINH_THEO_TUAN")                 # template h6 = RP h7
    # S3 outside the scope of the reference run: 0 at every horizon although AVG = 1
    assert all(pick(("S3", h))[1:3] == (0, OUT0) for h in range(1, 21))
    s = {r[0]: r[1] for r in _summary_of(p)[1:]}
    assert s["stale_reason"] == "NO_RUN_FOR_DAY" and s["file_flags"] == "STALE" and s["rows_total"] == 21
    assert (s["rows_fallback_reason:DUNG_SO_LAN_CHAY_TRUOC"], s[f"rows_flag:{lan}"], s["rows_fallback_reason:STALE"],
            s["rows_fallback_reason:NGOAI_PHAM_VI_GAN_0"]) == (6, 12, 1, 7)          # counts of horizon 1..7 only
    with db.read() as c:
        rec = db.one(c, "SELECT n_rows, is_stale, refresh_run_id, summary_json FROM export_runs")
    summ = json.loads(rec["summary_json"])
    assert (rec["n_rows"], rec["is_stale"], rec["refresh_run_id"]) == (60, 1, "RP")
    assert (summ["n_rows"], summ["n_rows_h1_7"], summ["layout"]) == (60, 21, {"sheets": {"DU_BAO_BD": 60},
                                                                               "sku_fc": {"DU_BAO_BD": 3}})


def test_stale_day_equals_the_ops_script(stale_day, x20, monkeypatch, tmp_path):
    res, _ = _compare_with_script(x20, monkeypatch, tmp_path)
    assert res["n_rows"] == 60


@pytest.fixture
def no_run_3_days(sel2_on):
    """Latest run 5 days before D (information only): every LIGHTGBM row from AVG (STALE); AVG 0 is a zero, not missing."""
    _run("ROLD", D - timedelta(days=5), {("S1", "BD"): ("A", "MOC+DOW4", {h: (9, 9.0) for h in range(1, 8)}),
                                         ("S4", "HN"): ("A", "MOC+DOW4", {h: (9, 9.0) for h in range(1, 8)})})
    _avg(D, [("S1", "BD", "SL1", 2.4, None), ("S9", "HN", "SL1", 0.0, None), ("S8", "HN", "SL1", 0.2, None)])
    _config([("S1", "BD", "LIGHTGBM", None), ("S4", "HN", "LIGHTGBM", None)])


def test_no_run_3_days_file_is_all_avg_at_20_days(no_run_3_days):
    res = export.write_daily_export(D, scope_key=SCOPE)
    sheets = _rows(paths.data_dir() / res["path"])
    assert list(sheets) == ["DU_BAO_BD", "DU_BAO_HN"] and res["n_rows"] == 4 * 20
    by = {(r["sku_code"], r["horizon"]): r for rows in sheets.values() for r in rows}
    trio = lambda k: (by[k]["lightgbm_forecast"], by[k]["forecast_used"], by[k]["fallback_reason"])
    for h in range(1, 21):
        assert trio(("S1", h)) == (None, 3, "STALE")                 # LIGHTGBM -> AVG 2.4 rounded up
        assert trio(("S4", h)) == (None, 0, NONUM)                   # LIGHTGBM, no AVG row, old run never used
        assert trio(("S9", h)) == (None, 0, None)                    # AVG 0 = zero demand, no KHONG_CO_SO_NAO
        assert trio(("S8", h)) == (None, 1, None)                    # AVG 0.2 (threshold) -> 1
    assert all(r["model_version"] is None and r["data_cutoff_date"] is None and r["is_stale"] == 1
               for r in by.values())
    assert res["summary"]["stale_reason"] == "NO_RUN_3_DAYS" and res["flags"][:2] == ["STALE", "NO_RUN_3_DAYS"]


def test_no_run_3_days_equals_the_ops_script(no_run_3_days, x20, monkeypatch, tmp_path):
    _compare_with_script(x20, monkeypatch, tmp_path)


@pytest.fixture
def odd_warehouses(sel2_on):
    """Warehouse codes beyond BD / HN: a code with characters Excel refuses in a sheet name, a Unicode code with a space;
    sparse horizons (h1, h3 only) for a LIGHTGBM SKU x FC, an AVG_DEMAND 0 with LightGBM numbers."""
    _run("R1", D, {("S1", "K/1:A"): ("A", "MOC+DOW4", {1: (1, 0.6), 3: (3, 2.7)}),
                   ("S2", "Kho Hà Nội"): ("B", "MOC+DOW4", {h: (5, 4.5) for h in range(1, 8)}),
                   ("S3", "BD"): ("C", "MOC+DOW4", {h: (2, 1.5) for h in range(1, 8)})})
    _avg(D, [("S1", "K/1:A", "SL1", 1.1, None), ("S2", "Kho Hà Nội", "SL1", 0.0, None)])
    _config([("S1", "K/1:A", "LIGHTGBM", None)])


def test_odd_warehouse_codes_sparse_horizons_and_avg_zero(odd_warehouses):
    kho = "DU_BAO_Kho Hà Nội"
    res = export.write_daily_export(D, scope_key=SCOPE)
    p = paths.data_dir() / res["path"]
    sheets = _rows(p)
    assert list(sheets) == ["DU_BAO_BD", "DU_BAO_K_1_A", kho] and res["n_rows"] == 60
    assert {r["fc_code"] for r in sheets["DU_BAO_K_1_A"]} == {"K/1:A"}          # cell keeps the real code
    k1 = {r["horizon"]: r for r in sheets["DU_BAO_K_1_A"]}
    assert sorted(k1) == list(range(1, 21))                                     # 20 rows despite missing horizons
    trio = lambda r: (r["lightgbm_forecast"], r["forecast_used"], r["fallback_reason"])
    assert trio(k1[2]) == (None, 2, NONE) and trio(k1[9]) == (None, 2, NONE)    # template h2: Avg 1.1 -> 2
    assert trio(k1[10]) == (2.7, 3, None) and trio(k1[17]) == (2.7, 3, None)  # template h3: raw 2.7
    assert trio(k1[8]) == (0.6, 1, None) and trio(k1[15]) == (0.6, 1, None)
    # AVG_DEMAND 0 with LightGBM numbers: 0 everywhere (zero is a value, the LightGBM number is not used)
    kh = sheets[kho]
    assert all(r["forecast_used"] == 0 and r["fallback_reason"] is None for r in kh)
    assert kh[10]["lightgbm_forecast"] == 4.5
    # BD: AVG_DEMAND without AVG row and full numbers -> KHONG_CO_AVG_DUNG_LIGHTGBM, raw 1.5 -> 2 at h8..20
    assert all(trio(r)[1:] == (2, AVGL) for r in sheets["DU_BAO_BD"])
    s = {r[0]: r[1] for r in _summary_of(p)[1:]}
    assert (s["rows:DU_BAO_K_1_A"], s[f"sku_fc:{kho}"]) == (20, 1)


def test_odd_warehouse_codes_equal_the_ops_script(odd_warehouses, x20, monkeypatch, tmp_path):
    _compare_with_script(x20, monkeypatch, tmp_path)


def test_sheet_names_that_clash_after_truncation_write_nothing(sel2_on, caplog):
    long1, long2 = "X" * 30 + "1", "X" * 30 + "2"                  # both -> DU_BAO_ + 24 X (31 characters)
    _avg(D, [("S1", long1, "SL1", 1.0, None), ("S1", long2, "SL1", 1.0, None)])
    with caplog.at_level(logging.ERROR, logger="df.sel2.export"), pytest.raises(AppError) as e:
        export.write_daily_export(D, scope_key=SCOPE)
    assert e.value.code == "SEL2_EXPORT_WRITE_FAILED" and "SHEET_NAME_CLASH" in str(e.value.detail)
    assert any(getattr(r, "ctx", {}).get("flag") == "SHEET_NAME_CLASH" for r in caplog.records)
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM export_runs").fetchone()[0] == 0
    folder = paths.data_dir() / "exports" / "du_bao" / D.strftime("%Y%m%d")
    assert not folder.exists() or not any(folder.iterdir())


def test_sheet_names_differing_only_in_case_clash():
    """Excel sheet names are unique WITHOUT regard to case: DU_BAO_HN and DU_BAO_hn in one book is a corrupt file
    (Excel repairs it and drops a sheet). Expected: refused like any other clash."""
    with pytest.raises(ValueError, match="SHEET_NAME_CLASH"):
        export._sheet_plan([("A", "HN"), ("A", "hn")])


def test_empty_input_n_rows_zero_and_summary(sel2_on):
    res = export.write_daily_export(D, scope_key=SCOPE)
    p = paths.data_dir() / res["path"]
    wb = load_workbook(p, read_only=True)
    assert wb.sheetnames == ["TOM_TAT", "CONFIG"]
    wb.close()
    s = {r[0]: r[1] for r in _summary_of(p)[1:]}
    assert s["rows_total"] == 0 and s["layout"] == export.LAYOUT_20 and not any(k.startswith("rows:") for k in s)
    assert res["n_rows"] == 0 and res["summary"]["layout"] == {"sheets": {}, "sku_fc": {}}
    with db.read() as c:
        assert c.execute("SELECT n_rows FROM export_runs").fetchone()[0] == 0


def test_summary_key_order_versions_and_latest_copy(scenario):
    r1 = export.write_daily_export(D, scope_key=SCOPE)
    r2 = export.write_daily_export(D, scope_key=SCOPE, trigger="MANUAL")
    p1, p2 = paths.data_dir() / r1["path"], paths.data_dir() / r2["path"]
    latest = paths.data_dir() / r2["latest_path"]
    assert latest.read_bytes() == p2.read_bytes() and r2["version"] == 2
    keys = [r[0] for r in _summary_of(latest)]
    assert keys[0] == "muc" and len(keys) == len(set(keys))                    # no duplicate key (rows_total once)
    tail = ["avg_source_kind", "avg_source_table", "avg_source_modified", "avg_read_completed_at", "avg_seller_rule",
            "layout", "horizon_8_20", "rows:DU_BAO_BD", "rows:DU_BAO_HN", "sku_fc:DU_BAO_BD", "sku_fc:DU_BAO_HN",
            "source", "generated_at"]
    assert keys[-len(tail):] == tail
    head = ["forecast_date", "data_cutoff_date", "export_version", "export_time_utc", "export_time_vn", "trigger",
            "is_stale", "stale_reason", "file_flags", "refresh_run_id", "run_forecast_date", "previous_runs",
            "model_version", "sku_fc_total", "sku_fc_in_forecast_scope", "sku_fc_configured_lightgbm",
            "sku_fc_configured_lightgbm_not_in_file", "rows_total"]
    assert keys[1:1 + len(head)] == head
    # both versions: the 20-day layout with the same DU_BAO_* / CONFIG cells (same input), only TOM_TAT differs
    c1, c2 = _cells(p1), _cells(p2)
    assert [n for n in c1 if n.startswith("DU_BAO_")] == ["DU_BAO_BD", "DU_BAO_HN"]
    assert all(c1[n] == c2[n] for n in c1 if n != "TOM_TAT")
    with db.read() as c:
        recs = db.rows(c, "SELECT version, n_rows, summary_json FROM export_runs ORDER BY version")
    assert [(r["version"], r["n_rows"]) for r in recs] == [(1, 220), (2, 220)]
    for r in recs:
        sj = json.loads(r["summary_json"])
        assert (sj["n_rows"], sj["n_rows_h1_7"]) == (220, 77)
        assert sum(sj["rows_by_fallback_reason"].values()) == 77                # counts of horizon 1..7 only


def test_rows20_dates_across_year_end_and_bad_groups():
    d = date(2026, 12, 28)

    def grp(sku, hs):
        return [[sku, None, None, sku, "BD", None, d, d + timedelta(days=h - 1), h, h, None, "LIGHTGBM", h, None,
                 "M", h + 0.5, "MV", None, 0, None] for h in hs]

    out = list(export._rows20(grp("S1", range(1, 8)) + grp("S2", range(1, 8)), d))
    i_td = export._I["target_date"]
    assert len(out) == 40 and all(len(r) == len(export.COLUMNS20) for r in out)
    td = [r[i_td] for r in out[:20]]
    assert td == [d + timedelta(days=i) for i in range(20)] and td[19] == date(2027, 1, 16)
    assert all(out[i][i_td].weekday() == out[i % 7][i_td].weekday() for i in range(7, 20))
    assert out[7][export._I["lightgbm_forecast"]] == 1.5 and out[7][export._I["forecast_used"]] == 2
    assert list(export._rows20([], d)) == []
    with pytest.raises(RuntimeError):
        list(export._rows20(grp("S1", range(1, 7)), d))                        # an incomplete last group
    with pytest.raises(RuntimeError):
        list(export._rows20(grp("S1", [1, 2, 3, 5, 4, 6, 7]), d))             # horizons out of order


def test_larger_synthetic_set_time_and_memory(sel2_on):
    """5,000 SKU x FC (2 warehouses) -> 100,000 rows: written in bounded time / Python memory, counts consistent."""
    import re
    import time
    import tracemalloc
    n = 2500
    series = {(f"SKU{i:05d}", fc): ("A", "MOC+DOW4", {h: (h % 3, h % 3 + 0.25) for h in range(1, 8)})
              for i in range(n) for fc in ("BD", "HN")}
    _run("R1", D, series)
    _avg(D, [(f"SKU{i:05d}", "BD", "SL1", 1.5, None) for i in range(n)])
    _config([(f"SKU{i:05d}", "HN", "LIGHTGBM", None) for i in range(n)])
    tracemalloc.start()
    t0 = time.perf_counter()
    try:
        res = export.write_daily_export(D, scope_key=SCOPE)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    elapsed = time.perf_counter() - t0
    print(f"5000 SKU x FC: {elapsed:.1f} s (tracemalloc on), Python peak {peak / 2**20:.1f} MB")
    assert res["n_rows"] == 100_000 and res["summary"]["layout"]["sheets"] == {"DU_BAO_BD": 50_000, "DU_BAO_HN": 50_000}
    assert peak < 200 * 2**20 and elapsed < 300
    xml = _sheet_xml(paths.data_dir() / res["path"])
    assert {n: len(re.findall(rb"<row ", x)) for n, x in xml.items() if n.startswith("DU_BAO_")} == \
        {"DU_BAO_BD": 50_001, "DU_BAO_HN": 50_001}
