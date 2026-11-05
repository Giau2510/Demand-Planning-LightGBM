"""1.4.3 owner decision 05/11/2026: the daily SEL2 Excel (ml/sel2/export.py) shows seller_code and product_code right
after ten_san_pham on DU_BAO and CONFIG: sku_code split at its FIRST dot (no dot -> seller_code empty, product_code =
sku_code). Unit (split_sku, _rows with synthetic inputs) and integration with fakes (isolated temporary database, rows
inserted directly, write_daily_export / write_temp_export workbooks read back)."""
from datetime import timedelta

import pytest
from openpyxl import load_workbook

from app import paths
from app.ml.sel2 import export
from test_v140_b6_bootstrap import _store_candidates
from test_v140_t6_export import COLS, D, SCOPE, _avg, _config, _main_rows, _run  # tests/ on path

SKUS = ("MEDX.ABC-ABC-010", "BML_E.0a1b2c3d4e5f", "A.B.C", "NODOT")
MAIN_HEADER = ["sku_code", "ten_san_pham", "seller_code", "product_code", "fc_code", "nhom", "forecast_date",
               "target_date", "horizon", "lightgbm_forecast", "avg_demand", "forecast_source", "forecast_used",
               "fallback_reason", "model_used", "raw_value", "model_version", "data_cutoff_date", "is_stale", "flags"]
CONFIG_HEADER = ["sku_code", "fc_code", "ten_san_pham", "seller_code", "product_code", "ghi_chu", "updated_by",
                 "updated_at"]


@pytest.mark.parametrize("sku, expected", [
    ("MEDX.ABC-ABC-010", ("MEDX", "ABC-ABC-010")),
    ("BML_E.0a1b2c3d4e5f", ("BML_E", "0a1b2c3d4e5f")),
    ("A.B.C", ("A", "B.C")),                                    # only the first dot splits
    ("NODOT", (None, "NODOT")),
    ("00123", (None, "00123")),                                 # leading zeros kept (text)
    (".X", (None, "X")),                                        # empty seller part -> empty
    ("X.", ("X", None)),                                        # empty product part -> empty
    (".", (None, None)),
    ("", (None, None)),
    (None, (None, None)),
])
def test_split_sku(sku, expected):
    assert export.split_sku(sku) == expected


def _check_split(rows):
    """seller_code + '.' + product_code == sku_code with a seller, product_code == sku_code without one."""
    assert rows
    for r in rows:
        sku, seller, product = r["sku_code"], r["seller_code"], r["product_code"]
        if seller:
            assert f"{seller}.{product}" == sku
        else:
            assert seller is None and product == sku


def test_columns_order_unchanged_apart_from_the_two_new_ones():
    assert list(export.COLUMNS) == MAIN_HEADER == COLS
    assert list(export.CONFIG_COLUMNS) == CONFIG_HEADER


def test_rows_carry_the_split_after_the_product_name():
    keys = [(s, "F1") for s in SKUS]
    stats = {"rows_by_fallback_reason": {}, "flag_rows": {}}
    rows = list(export._rows(D, keys, None, {}, {}, {}, {}, {"A.B.C": "Thuoc C"}, False, stats))
    assert len(rows) == len(keys) * export.HORIZON
    assert all(len(r) == len(export.COLUMNS) for r in rows)
    by = [dict(zip(export.COLUMNS, r)) for r in rows]
    _check_split(by)
    abc = next(r for r in by if r["sku_code"] == "A.B.C")
    assert (abc["ten_san_pham"], abc["seller_code"], abc["product_code"], abc["fc_code"]) == ("Thuoc C", "A", "B.C", "F1")


def _check_config(wb, expected_skus):
    cfg = list(wb["CONFIG"].iter_rows(values_only=True))
    assert list(cfg[0]) == CONFIG_HEADER
    rows = [dict(zip(CONFIG_HEADER, r)) for r in cfg[1:]]
    assert [r["sku_code"] for r in rows] == sorted(expected_skus)
    _check_split(rows)
    return {r["sku_code"]: r for r in rows}


def test_daily_export_du_bao_and_config(sel2_on):
    full = {h: (h, h - 0.4) for h in range(1, 8)}
    _run("R1", D, {(s, "F1"): ("A", "MOC+DOW4", full) for s in SKUS})
    _avg(D, [(s, "F1", "SL1", 2.0, f"Ten {s}") for s in SKUS])
    _config([(s, "F1", "LIGHTGBM", "ghi chu" if s == "NODOT" else None) for s in SKUS])
    res = export.write_daily_export(D, scope_key=SCOPE)
    wb = load_workbook(paths.data_dir() / res["path"])
    assert [c.value for c in wb["DU_BAO"][1]] == MAIN_HEADER
    rows = _main_rows(wb)
    assert len(rows) == res["n_rows"] == len(SKUS) * 7
    _check_split(rows)
    medx = next(r for r in rows if r["sku_code"] == "MEDX.ABC-ABC-010")
    assert (medx["ten_san_pham"], medx["seller_code"], medx["product_code"], medx["fc_code"], medx["forecast_used"]) \
        == ("Ten MEDX.ABC-ABC-010", "MEDX", "ABC-ABC-010", "F1", 1)
    assert wb["DU_BAO"].auto_filter.ref == f"A1:T{len(rows) + 1}"
    cfg = _check_config(wb, SKUS)
    assert (cfg["BML_E.0a1b2c3d4e5f"]["seller_code"], cfg["BML_E.0a1b2c3d4e5f"]["product_code"]) == \
        ("BML_E", "0a1b2c3d4e5f")
    assert (cfg["NODOT"]["ten_san_pham"], cfg["NODOT"]["seller_code"], cfg["NODOT"]["product_code"],
            cfg["NODOT"]["ghi_chu"], cfg["NODOT"]["updated_by"]) == ("Ten NODOT", None, "NODOT", "ghi chu", "tester")


def test_temp_export_du_bao_and_config(sel2_on):
    _store_candidates(v33={(s, "F1"): [1.0] * 7 for s in SKUS[:3]}, scope=SCOPE)
    _avg(D, [(s, "F1", "SL1", 2.0, f"Ten {s}") for s in SKUS])
    _config([(s, "F1", "LIGHTGBM", None) for s in SKUS])
    res = export.write_temp_export(D, groups={(s, "F1"): "A" for s in SKUS[:3]}, scope_key=SCOPE)
    wb = load_workbook(paths.data_dir() / res["path"])
    rows = _main_rows(wb)                                       # header checked against COLS
    assert len(rows) == res["n_rows"] == len(SKUS) * 7
    _check_split(rows)
    nodot = [r for r in rows if r["sku_code"] == "NODOT"]
    assert {(r["seller_code"], r["product_code"], r["fallback_reason"]) for r in nodot} == \
        {(None, "NODOT", "NGOAI_PHAM_VI_GAN_0")}
    abc = [r for r in rows if r["sku_code"] == "A.B.C"]
    assert {(r["seller_code"], r["product_code"], r["target_date"].date() - D) for r in abc} == \
        {("A", "B.C", timedelta(days=i)) for i in range(7)}
    _check_config(wb, SKUS)
