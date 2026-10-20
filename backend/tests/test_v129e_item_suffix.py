"""1.2.9 (fifth batch, 20/10/2026): the owner's rule on item codes. The suffix of `<sku_code>.<n>` is the order in which
the SKU was opened for sale in the regions - NOT a region code. Nothing (FC, region, open hours) may be inferred from it:
the D-1 query only COUNTS distinct item codes and distinct (item, value) pairs (data/open_hours.cell gets counts only),
so renaming or swapping the suffixes cannot change a status. The real-BigQuery check of the same rule on inline rows is
test_v129e_real_bq_item_suffix.py (opt-in).

Temporary databases (conftest), no BigQuery call."""
from __future__ import annotations

import re
from datetime import date

from app import settings_service as ss
from app.bq import connector
from app.data import open_hours
from app.ml import feature_registry as registry

FM = {"order_id": {"column": "so_code", "usage": "OPTIONAL"}, "order_date": {"column": "created_date", "usage": "REQUIRED"},
      "created_at": {"column": None, "usage": "UNUSED"},
      "sku_id": {"column": "sku_code", "usage": "REQUIRED"}, "fc_id": {"column": "fc_code", "usage": "REQUIRED"},
      "order_qty": {"column": "demand_quantity", "usage": "REQUIRED"},
      "unit_price": {"column": "sales_price", "usage": "OPTIONAL"}}
REF_ITEM = {"open_hours": {"column": "total_open_hours", "usage": "OPTIONAL"},
            "item_code": {"column": "item_code", "usage": "OPTIONAL"}}
STRING_FUNCTIONS = ("SPLIT(", "REGEXP", "SUBSTR(", "SUBSTRING(", "ENDS_WITH(", "STARTS_WITH(", "STRPOS(", "RIGHT(",
                    "LEFT(", "REPLACE(", "INSTR(", "LIKE ")


def test_the_d1_query_only_counts_item_codes_and_never_parses_them():
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders", "location": "asia-southeast1",
                           "partition_column": "", "field_mapping": FM, "reference_mapping": REF_ITEM})
    sql, _ = connector._daily_sql(ss.get("bigquery"), date(2026, 10, 1), date(2026, 10, 2))
    up = sql.upper()
    assert not [f for f in STRING_FUNCTIONS if f in up], "a string function could read the item suffix"
    uses = [m.start() for m in re.finditer(r"ref_item_code", sql)]
    assert uses, "item_code is mapped: the query must count items"
    # every use after the select list is inside one of the three counts (no item code value leaves BigQuery)
    counted = ("COUNT(DISTINCT IF(ref_open_hours IS NULL, NULL, CAST(ref_item_code AS STRING))) AS open_hours_items",
               "CONCAT(CAST(ref_item_code AS STRING), '|', CAST(ref_open_hours AS STRING)))) AS open_hours_item_values",
               "COUNTIF(ref_open_hours IS NOT NULL AND ref_item_code IS NULL) AS open_hours_no_item_rows")
    assert all(c in sql for c in counted)
    valid = sql.split("FROM checked WHERE _reason IS NULL GROUP BY")[0].rsplit("SELECT 'VALID'", 1)[1]
    assert valid.count("ref_item_code") == 4      # items (1), item / value pairs (2: null test + concat), no-item rows (1)


def test_the_status_of_a_key_depends_on_counts_only_whatever_the_item_codes_are_called():
    # the same two-item key read with suffixes .1/.2, swapped, other numbers or codes without suffix gives the same
    # counts, hence the same status; the function has no parameter that could carry an item name
    assert open_hours.cell.__code__.co_varnames[:6] == ("null_rows", "lo", "hi", "items", "item_values", "no_item_rows")
    for _names in (("S.1", "S.2"), ("S.2", "S.1"), ("S.7", "S.3"), ("ITEM-A", "ITEM-B")):
        assert open_hours.cell(0, 5.0, 24.0, 2, 2, 0) == (None, "MULTI_ITEM")
        assert open_hours.cell(0, 24.0, 24.0, 2, 2, 0) == (24.0, "OK")


def test_the_feature_explanation_does_not_call_an_item_a_region():
    text = registry._AGGREGATION["open_hours"]      # the "how it is computed" text of the feature catalog / UI
    assert "miền bán)" not in text and "listing theo miền" not in text
    assert "không phải mã miền" in text
