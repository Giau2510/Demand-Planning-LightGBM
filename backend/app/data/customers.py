"""1.2.9b: optional customer_id of the D-1 BigQuery source -> AGGREGATE repeat-purchase signals of a SKU x FC series.

OFF by default on both sides, and never switched on by itself:
* the source column is used only when the owner maps it (BigQuerySettings.customer_id_column, "" = none; the mapping
  hash changes only when it is set, so an installation without it keeps its validated state);
* the three model features are used only when the model switch feature_customer is ON *and* the stored rows carry the
  aggregates (feature_registry.resolve, coverage >= feature_min_coverage); otherwise the training runs without them.

Privacy: the identifier never leaves BigQuery. The D-1 query reduces it to counts per day x SKU x FC (connector.
_customer_ctes); no identifier is fetched, stored, logged or exported, and the output grain stays day x SKU x FC (the
forecast is never per customer). A count is not anonymisation of the source - it only keeps identifiers out of this app.

Per day d x SKU x FC (valid D-1 lines - SKU, FC, target present and target >= 0 - with a non-empty identifier):
  customer_count            distinct customers that ordered on d
  repeat_customer_count     of those, customers that had ordered the same SKU x FC on an EARLIER day within
                            REPEAT_LOOKBACK_DAYS before d (d - 90 .. d - 1)
  repeat_interval_days_sum  sum over the repeat customers of the days since their previous order day
Each value of day d uses orders up to d only. A day x SKU x FC without a line with an identifier has NULL (unknown,
never 0); lines without an identifier still count fully in the demand (qty). The features at a forecast origin T read the
days before T only (features.features_at), so no order on or after T is used.
"""
from __future__ import annotations

REPEAT_LOOKBACK_DAYS = 90
COLUMNS = ("customer_count", "repeat_customer_count", "repeat_interval_days_sum")
ID_TYPES = ("STRING", "INTEGER", "INT64")


def check_column(columns: list[dict], name: str) -> list[dict]:
    """Errors of a customer_id column choice against the LIVE source schema ([] = usable; "" = not mapped)."""
    if not name:
        return []
    types = {c["name"]: str(c.get("type") or "").upper() for c in columns}
    if name not in types:
        return [{"field": "customer_id", "code": "COLUMN_NOT_FOUND", "column": name}]
    if types[name] not in ID_TYPES:
        return [{"field": "customer_id", "code": "TYPE_NOT_ALLOWED", "column": name, "type": types[name]}]
    return []


def stored(r: dict) -> tuple:
    """(customer_count, repeat_customer_count, repeat_interval_days_sum) of one aggregated D-1 row (None = unknown)."""
    def i(v):
        return None if v is None else int(v)
    s = r.get("repeat_interval_days_sum")
    return i(r.get("customer_count")), i(r.get("repeat_customer_count")), None if s is None else float(s)
