"""Day of week: ONE convention for the whole application (1.2.9) - Monday = 1 ... Sunday = 7 (ISO 8601).

Always computed from the calendar date itself: a Vietnam business date (order_date of a demand row, target_date of a
forecast day), never from a UTC timestamp, so no time-zone shift can move a day to its neighbour.
  history   order_date of the demand row = the mapped D-1 column (BigQuery created_date) or, for a timestamp source,
            its Vietnam calendar day (connector._order_date_expr)
  forecast  the TARGET date of each forecast day (never the date of a historical order)
"""
from __future__ import annotations

from datetime import date, datetime

LABELS = {"vi": ("Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"),
          "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")}


def iso_weekday(d) -> int:
    """1 = Monday ... 7 = Sunday of a date, a datetime / pandas Timestamp (its own calendar day) or 'YYYY-MM-DD'."""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    elif isinstance(d, datetime):          # also pandas Timestamp
        d = d.date()
    elif not isinstance(d, date):
        import pandas as pd
        d = pd.Timestamp(d).date()
    return d.isoweekday()


def is_weekend(d) -> bool:
    return iso_weekday(d) >= 6


def label(n, lang: str = "vi") -> str | None:
    """'Thứ 2' ... 'Chủ nhật' (en: Monday ... Sunday) for 1..7; None for a missing or invalid value (never guessed)."""
    if n is None or isinstance(n, bool):
        return None
    try:
        i = int(n)
    except (TypeError, ValueError):
        return None
    if i != n and not (isinstance(n, str) and n.strip() == str(i)):
        return None
    if not 1 <= i <= 7:
        return None
    return LABELS["en" if lang == "en" else "vi"][i - 1]
