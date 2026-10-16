"""Actual demand of the current Vietnam day up to the last successful D0 read ("actual so far today").

Definitions (docs/MO-HINH-VA-CHI-SO.md):
  demand_actual_today_as_of  sum(order_qty) of the latest SUCCEEDED D0 snapshot of the SAME dataset (scope_key) for
                             today's VN date; cancellations are not subtracted (order_qty = quantity at order time)
  actual_as_of_timestamp     d0_snapshots.snapshot_at = the moment the source was really read (never "now")
  status                     NOT_APPLICABLE  source has no intraday feed (MANUAL_IMPORT = static history)
                             NO_DATA_TODAY   no successful read today for this dataset
                             PARTIAL_DAY     read recently; the day is still running (never "complete")
                             STALE           last read older than the longest gap between scheduled D0 slots
A SKU x FC absent from a successful snapshot had no order up to that read -> 0 (the read covers the whole dataset).
Without a successful snapshot nothing is assumed: the value is None ("no data"), never 0.
"""
from __future__ import annotations

from datetime import date, datetime

from .. import db
from .. import settings_service as ss
from ..timeutil import now_utc, parse_iso, today_vn


def stale_after_minutes(sched) -> int:
    times = sorted(sched.d0_times)
    if len(times) < 2:
        return 24 * 60
    mins = [int(t[:2]) * 60 + int(t[3:]) for t in times]
    gap = max(b - a for a, b in zip(mins, mins[1:]))
    return gap + sched.slot_grace_minutes


def actual_today(scope_key: str, data_source: str, conn=None, today: date | None = None,
                 now: datetime | None = None) -> dict:
    today = today or today_vn()
    now = now or now_utc()
    base = {"date": str(today), "status": "NO_DATA_TODAY", "as_of": None, "source_updated_max": None,
            "snapshot_id": None, "is_demo": data_source == "DEMO", "is_catch_up": False, "values": {}}
    if data_source == "MANUAL_IMPORT":
        return {**base, "status": "NOT_APPLICABLE"}

    def _q(c):
        snap = db.one(c, "SELECT * FROM d0_snapshots WHERE scope_key=? AND order_date=? AND sync_status='SUCCEEDED' "
                         "ORDER BY snapshot_at DESC, rowid DESC LIMIT 1", (scope_key, str(today)))
        if not snap:
            return base
        vals = {(r["sku_id"], r["fc_id"]): float(r["cumulative_qty"]) for r in db.rows(
            c, "SELECT sku_id, fc_id, cumulative_qty FROM d0_snapshot_values WHERE snapshot_id=?", (snap["id"],))}
        sched = ss.get("schedule", c)
        age_min = (now - parse_iso(snap["snapshot_at"])).total_seconds() / 60
        status = "STALE" if age_min > stale_after_minutes(sched) else "PARTIAL_DAY"
        return {**base, "status": status, "as_of": snap["snapshot_at"], "source_updated_max": snap["source_updated_max"],
                "snapshot_id": snap["id"], "is_catch_up": bool(snap["is_catch_up"]), "rows_read": snap["rows_read"],
                "age_minutes": round(age_min, 1), "values": vals}
    if conn is not None:
        return _q(conn)
    with db.read() as c:
        return _q(c)


def has_values(actual: dict) -> bool:
    return actual["status"] in ("PARTIAL_DAY", "STALE")


def value_for(actual: dict, sku: str, fc: str, target_date: str):
    """Actual so far for that row, or None when it does not apply (other days) / is unknown."""
    if target_date != actual["date"] or not has_values(actual):
        return None
    return actual["values"].get((sku, fc), 0.0)


def public(actual: dict) -> dict:
    return {k: v for k, v in actual.items() if k != "values"}
