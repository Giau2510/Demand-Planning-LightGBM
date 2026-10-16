from datetime import date, datetime, timezone

import pandas as pd

from app.data.schema import suggest_mapping
from app.data.validation import normalize_and_validate, parse_datetime_series


def _codes(issues):
    return set(issues["code"])


def test_datetime_formats_and_vietnam_date_derivation():
    s = pd.Series(["2026-03-01 23:30", "01/03/2026 08:15", "2026-03-01T20:00:00Z",
                   datetime(2026, 3, 1, 9, 0), "not a date", None], dtype=object)
    out = parse_datetime_series(s)
    assert str(out[0].date()) == "2026-03-01"
    assert out[1].hour == 8 and out[1].day == 1 and out[1].month == 3      # DD/MM/YYYY
    assert str(out[2].date()) == "2026-03-02"                              # 20:00 UTC = 03:00 next day VN
    assert out[3].hour == 9
    assert pd.isna(out[4]) and pd.isna(out[5])


def test_row_errors_are_reported_not_silently_dropped():
    raw = pd.DataFrame({
        "order_id": ["A", "B", "C", "D", "E", "F", "G"],
        "created_at": ["2026-01-01 10:00", "2026-01-01 10:00", "bad", "2026-01-01 10:00", "2026-01-01 10:00",
                       "2099-01-01 10:00", "2026-01-02 10:00"],
        "sku_id": ["S1", None, "S1", "S1", "S1", "S1", "S1"],
        "fc_id": ["F1", "F1", "F1", "F1", "F1", "F1", "F1"],
        "order_qty": [3, 1, 1, -2, "abc", 1, 0],
        "unit_price": [100, 100, 100, 100, 100, 100, "x"],
    })
    valid, issues, summary = normalize_and_validate(raw, today=date(2026, 6, 1))
    codes = _codes(issues)
    assert {"MISSING_SKU", "INVALID_DATETIME", "NEGATIVE_QTY", "INVALID_QTY", "FUTURE_DATE", "ZERO_QTY",
            "INVALID_NUMBER_BLANKED"} <= codes
    assert summary["total_rows"] == 7
    assert summary["valid_rows"] == 2             # A and G (zero qty is valid)
    assert summary["error_rows"] == 5
    g = valid[valid["order_id"] == "G"].iloc[0]
    assert g["order_qty"] == 0 and pd.isna(g["unit_price"])


def test_exact_duplicates_counted_once_and_grain_conflict_policy():
    base = {"created_at": "2026-01-01 10:00", "sku_id": "S1", "fc_id": "F1"}
    raw = pd.DataFrame([{**base, "order_id": "O1", "order_qty": 2}, {**base, "order_id": "O1", "order_qty": 2},
                        {**base, "order_id": "O2", "order_qty": 1}, {**base, "order_id": "O2", "order_qty": 5}])
    valid, issues, s = normalize_and_validate(raw, today=date(2026, 6, 1), grain_conflict_policy="ERROR")
    assert s["duplicate_rows"] == 1
    assert "GRAIN_CONFLICT" in _codes(issues)
    assert list(valid["order_id"]) == ["O1"] and valid["order_qty"].sum() == 2
    valid2, issues2, s2 = normalize_and_validate(raw, today=date(2026, 6, 1), grain_conflict_policy="SUM")
    assert valid2["order_qty"].sum() == 8          # 2 (dup counted once) + 1 + 5
    assert "GRAIN_MULTI_LINE_SUMMED" in _codes(issues2)


def test_order_date_only_and_missing_dates():
    raw = pd.DataFrame({"order_date": ["2026-01-01", "2026-01-03"], "sku_id": ["S", "S"], "fc_id": ["F", "F"],
                        "order_qty": [1, 1]})
    valid, issues, s = normalize_and_validate(raw, today=date(2026, 6, 1))
    assert s["valid_rows"] == 2
    assert s["missing_dates"] == ["2026-01-02"]


def test_min_date_out_of_range():
    raw = pd.DataFrame({"order_date": ["2020-01-01", "2026-01-03"], "sku_id": ["S", "S"], "fc_id": ["F", "F"],
                        "order_qty": [1, 1]})
    _, issues, s = normalize_and_validate(raw, today=date(2026, 6, 1), min_date="2025-01-01")
    assert "OUT_OF_RANGE_DATE" in _codes(issues) and s["valid_rows"] == 1


def test_leading_zero_sku_kept_and_numeric_sku_normalised():
    raw = pd.DataFrame({"order_date": ["2026-01-01"] * 2, "sku_id": ["00123", 456.0], "fc_id": ["F", "F"],
                        "order_qty": [1, 1]})
    valid, _, _ = normalize_and_validate(raw, today=date(2026, 6, 1))
    assert list(valid["sku_id"]) == ["00123", "456"]


def test_mapping_suggestion_is_exact_only():
    m = suggest_mapping(["Created At", "SKU", "warehouse", "qty", "order_quantity_x"],
                        {"sku_id": ["sku"], "fc_id": ["warehouse"], "order_qty": ["qty"]})
    assert m["created_at"] == "Created At" and m["sku_id"] == "SKU" and m["fc_id"] == "warehouse"
    assert m["order_qty"] == "qty"
    m2 = suggest_mapping(["order_quantity_x"], {})
    assert m2["order_qty"] is None   # no fuzzy matching on "similar" names
