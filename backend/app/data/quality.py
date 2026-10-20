"""Dataset-level data-quality report for one scope (shared by DEMO, MANUAL_IMPORT, BIGQUERY)."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd

from .. import db
from .. import settings_service as ss
from ..timeutil import now_iso, today_vn
from .demand import data_window, load_demand


def build_report(scope: dict, conn=None, persist: bool = True) -> dict:
    own = conn is None
    c = conn or db.connect()
    try:
        mcfg = ss.get("model", c)
        pol = ss.get("data_policy", c)
        win = data_window(c, scope=scope)      # 1.2.9b: same start rule as the training
        # the report judges the MODEL INPUT (the data window); stored rows outside it are counted, never used
        outside = c.execute("SELECT COALESCE(SUM(order_date < ?), 0), COALESCE(SUM(order_date > ?), 0) FROM demand_daily "
                            "WHERE scope_key=?", (win["start"], win["end"], scope["scope_key"])).fetchone()
        d = load_demand(scope["scope_key"], c, start=win["start"], end=win["end"])
        checks: list[dict] = []
        stats: dict = {"rows_read": 0, "rows_valid": 0, "rows_rejected": 0, "duplicate_rows": 0,
                       "data_window": {"start": win["start"], "end": win["end"], "start_rule": win["start_rule"],
                                       "configured_start": win["configured_start"], "excluded": win.get("excluded")},
                       "demand_rows_before_window": int(outside[0]), "demand_rows_after_window_end": int(outside[1])}
        batch = None
        if scope["data_source"] in ("DEMO", "MANUAL_IMPORT"):
            batch = db.one(c, "SELECT * FROM import_batches WHERE id=?", (scope["scope_key"],))
        if batch:
            v = json.loads(batch.get("validation_json") or "{}")
            stats.update(rows_read=batch["total_rows"], rows_valid=batch["valid_rows"],
                         rows_rejected=batch["error_rows"], duplicate_rows=batch["duplicate_rows"],
                         issues_by_code=v.get("issues_by_code", []), batch_id=batch["id"])
        else:
            st = db.one(c, "SELECT value_json FROM sync_state WHERE name=?", (f"last_d1_sync:{scope['scope_key']}",))
            if st:
                v = json.loads(st["value_json"])
                stats.update(rows_read=v.get("rows_read", 0), rows_valid=v.get("rows_valid", 0),
                             rows_rejected=v.get("rows_error", 0), batch_id=v.get("source_batch_id"),
                             last_sync_at=v.get("synced_at"))
        if d.empty:
            checks.append({"code": "NO_DATA", "severity": "ERROR", "window": [win["start"], win["end"]]})
            rep = {"scope": scope, "checked_at": now_iso(), "stats": stats, "checks": checks,
                   "can_train": False, "can_publish": False}
            if persist:
                _persist(c, scope, rep)
            return rep
        dates = sorted(d["order_date"].unique())
        first, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
        span = (last - first).days + 1
        missing = span - len(dates)
        g = d.groupby(["sku_id", "fc_id"])
        series_first = g["order_date"].min()
        series_last = g["order_date"].max()
        n_series = len(series_first)
        stats.update(min_date=dates[0], max_date=dates[-1], history_days=span, n_days_with_data=len(dates),
                     n_skus=int(d["sku_id"].nunique()), n_fcs=int(d["fc_id"].nunique()), n_series=n_series,
                     total_qty=float(d["qty"].sum()))
        if missing:
            all_days = {str(first + timedelta(days=i)) for i in range(span)}
            checks.append({"code": "MISSING_CALENDAR_DAYS", "severity": "WARNING", "count": missing,
                           "examples": sorted(all_days - set(dates))[:20]})
        if span < mcfg.min_total_history_days:
            checks.append({"code": "INSUFFICIENT_HISTORY", "severity": "ERROR", "count": span,
                           "required": mcfg.min_total_history_days})
        else:
            target = (date.fromisoformat(win["end"]) - date.fromisoformat(win["start"])).days + 1
            if span < target:     # the data covers only part of the window (e.g. starts later than window_start_date)
                checks.append({"code": "SHORT_HISTORY", "severity": "INFO", "count": span, "target": target})
        cutoff = str(last - timedelta(days=13))
        new_skus = d.groupby("sku_id")["order_date"].min()
        new_skus = new_skus[new_skus >= cutoff]
        if len(new_skus) and span > 14:
            checks.append({"code": "NEW_SKUS", "severity": "INFO", "count": int(len(new_skus)),
                           "examples": list(new_skus.index[:20])})
        new_fcs = d.groupby("fc_id")["order_date"].min()
        new_fcs = new_fcs[new_fcs >= cutoff]
        if len(new_fcs) and span > 14:
            checks.append({"code": "NEW_FCS", "severity": "INFO", "count": int(len(new_fcs)),
                           "examples": list(new_fcs.index[:20])})
        last_ts = pd.Timestamp(dates[-1])
        age = ((last_ts - pd.to_datetime(series_first)).dt.days + 1).to_numpy()
        short = int((age < mcfg.min_series_history_days).sum())
        if short:
            checks.append({"code": "SHORT_SERIES", "severity": "INFO", "count": short})
        inactive = int(((last_ts - pd.to_datetime(series_last)).dt.days >= mcfg.inactive_days).sum())
        if inactive:
            checks.append({"code": "INACTIVE_SERIES", "severity": "INFO", "count": inactive})
        # zero-demand share across series-days since each series started
        expected = int(age.sum())
        zero_days = expected - len(d[d["qty"] > 0])
        stats["zero_demand_share"] = round(zero_days / expected, 4) if expected else None
        recent = d[d["order_date"] >= str(last - timedelta(days=mcfg.fallback_window_days * 2 - 1))]
        nz = recent.groupby(["sku_id", "fc_id"]).size()
        window = mcfg.fallback_window_days * 2
        intermittent = int(((1 - nz / window) >= mcfg.intermittent_zero_share).sum())
        if intermittent:
            checks.append({"code": "INTERMITTENT_SERIES", "severity": "INFO", "count": intermittent})
        if stats.get("zero_demand_share") and stats["zero_demand_share"] > 0.5:
            checks.append({"code": "ZERO_DEMAND_DAYS", "severity": "INFO", "count": zero_days})
        lag_days = (today_vn() - last).days
        stats["data_lag_days"] = lag_days
        stale = lag_days > pol.max_data_lag_days
        stale_blocks = stale and scope["data_source"] in pol.stale_check_sources
        if stale:
            checks.append({"code": "STALE_DATA", "severity": "ERROR" if stale_blocks else "INFO",
                           "count": lag_days, "max_allowed": pol.max_data_lag_days,
                           "enforced": stale_blocks})
        for it in stats.get("issues_by_code", []):
            if it["severity"] in ("ERROR", "DUPLICATE", "WARNING"):
                checks.append({"code": it["code"], "severity": "INFO" if it["severity"] != "WARNING" else "WARNING",
                               "count": it["count"], "row_level": True})
        can_train = not any(ch["severity"] == "ERROR" and ch["code"] in ("NO_DATA", "INSUFFICIENT_HISTORY")
                            for ch in checks)
        rep = {"scope": scope, "checked_at": now_iso(), "stats": stats, "checks": checks,
               "can_train": bool(can_train), "can_publish": bool(can_train and not stale_blocks),
               "stale": bool(stale), "stale_enforced": bool(stale_blocks)}
        if persist:
            _persist(c, scope, rep)
        return rep
    finally:
        if own:
            c.close()


def _persist(c, scope, rep):
    rid = db.new_id("DQ")
    rep["id"] = rid
    c.execute("INSERT INTO validation_reports(id, scope_key, data_source, created_at, can_train, report_json) "
              "VALUES (?,?,?,?,?,?)", (rid, scope["scope_key"], scope["data_source"], rep["checked_at"],
                                       int(rep["can_train"]), json.dumps(rep, default=str)))


def latest_report(scope_key: str) -> dict | None:
    with db.read() as c:
        r = db.one(c, "SELECT report_json FROM validation_reports WHERE scope_key=? ORDER BY created_at DESC, rowid DESC "
                      "LIMIT 1", (scope_key,))
    return json.loads(r["report_json"]) if r else None
