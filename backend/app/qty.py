"""1.2.8: the forecast quantity shown and exported is a whole number of units.

Rule (one place, used by the API, the Excel export and the explanation): round half up of the stored forecast (yhat),
never below 0 - stored forecasts are already clipped at 0, so the floor only guards against a bad value. The stored
yhat is never changed and stays the input of every accuracy figure (WAPE / bias, quality gate). Totals are sums of the
rounded daily values, so a table, a chart, a total and an export of the same rows always agree.
"""
from __future__ import annotations

import math

RULE = "ROUND_HALF_UP_NON_NEGATIVE"
# SQL form of business_qty() over a column `yhat`; CAST truncates toward zero, which is floor() for MAX(yhat, 0) + 0.5
SQL = "CAST(MAX(yhat, 0) + 0.5 AS INTEGER)"


def business_qty(yhat: float | None) -> int | None:
    if yhat is None or (isinstance(yhat, float) and math.isnan(yhat)):
        return None
    return int(math.floor(max(float(yhat), 0.0) + 0.5))
