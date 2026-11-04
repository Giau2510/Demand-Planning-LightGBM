"""1.4.0 SEL2: the AVG_DEMAND source, read read-only from BigQuery and stored per business day (avg_demand_daily).

  current     sel2_pipeline.avg_demand_table: a snapshot without a date column (one row per fc x sku x seller, rebuilt
              about 10:15 Vietnam time every day). read_current(D) stores it as the rows of day D.
  historical  sel2_pipeline.avg_demand_hist_table: the same columns + transformed_at (partitioned by DAY; one snapshot
              per day, the TIMESTAMP holds the Vietnam wall clock, so DATE(transformed_at) is the Vietnam day).
              read_historical(start, end) stores each day DATE(transformed_at) as the rows of that day.

Read-only: SELECT only through connector._run (dry run first, maximum_bytes_billed capped at MAX_BYTES), the needed
columns only, the dates as query parameters; the table ids come from the validated settings. Rows are stored raw (one
per seller, avg_demand NULL kept as NULL); a read replaces the rows of its day x source table and records itself in
avg_demand_reads in ONE transaction (a read that failed midway records nothing and leaves the earlier rows of that day
untouched). Only days with a completed read are used by avg_value(). The current snapshot is the table of TODAY
(Vietnam): read_current(D) refuses D != today (AVG_CURRENT_ONLY_TODAY); a past day comes from the historical table.

avg_value() applies sel2_pipeline.avg_seller_rule (owner approval pending): one seller row -> its value whatever the
rule; several rows -> SUM / MAX / SELLER:<CODE>; PENDING -> no value (reason SELLER_RULE_PENDING). A NULL avg_demand
among the rows the rule needs gives no value (reason AVG_DEMAND_NULL): a missing value is never read as 0.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from ... import db
from ... import settings_service as ss
from ...bq import connector
from ...messages import AppError
from ...timeutil import iso, now_iso, today_vn

log = logging.getLogger("df.sel2.avg")
MAX_BYTES = 5 * 1024 ** 3                         # cap of every AVG_DEMAND query (lower of this and the settings)
KIND_CURRENT, KIND_HISTORICAL = "CURRENT", "HISTORICAL"
MAX_HIST_DAYS = 120                               # longest historical range of one read
REASON_PENDING = "SELLER_RULE_PENDING"
REASON_NULL = "AVG_DEMAND_NULL"
REASON_SELLER = "SELLER_NOT_FOUND"
REASON_NO_ROW = "NO_ROW"
_COLS = "fc_code, sku_code, seller_code, avg_demand, product_name, ingest_time"


def _day(d) -> date:
    return d if isinstance(d, date) and not isinstance(d, datetime) else date.fromisoformat(str(d)[:10])


def _ctx(cfg=None, bq=None):
    cfg = cfg or ss.get("sel2_pipeline")
    bq = bq or ss.get("bigquery")
    bq = bq.model_copy(update={"maximum_bytes_billed": min(int(bq.maximum_bytes_billed), MAX_BYTES)})
    return cfg, bq, connector._client(bq)


def _require_enabled(cfg) -> None:
    # sel2_pipeline.enabled = False is the exact 1.3.1 behaviour: nothing is written into the SEL2 tables
    if not cfg.enabled:
        raise AppError("SEL2_PIPELINE_DISABLED", 409)


def source_modified_now(table: str | None = None, cfg=None, bq=None) -> str | None:
    """Last-modified time (UTC ISO) of the AVG_DEMAND table (default: the current one) from its metadata (get_table: no
    query, no byte billed). None when not available; a metadata error is logged, never raised. Used to decide a
    re-read / re-export when the source changed after the last completed read."""
    try:
        cfg, bq, client = _ctx(cfg, bq)
        t = client.get_table(table or cfg.avg_demand_table)
        m = getattr(t, "modified", None)
        return iso(m) if isinstance(m, datetime) else None
    except Exception as e:  # noqa: BLE001 - unknown = None (the caller decides)
        log.warning("avg demand source metadata unavailable", extra={"ctx": {"error": f"{type(e).__name__}: {e}"[:300]}})
        return None


def _num(v):
    return None if v is None else float(v)


def _prepare(rows: list[dict]) -> tuple[list[dict], dict]:
    """Rows of ONE day: rows with a NULL key are skipped (counted); an exact repeat of a key is kept once (counted);
    the same key with different values refuses the whole read (nothing stored)."""
    out: dict[tuple, dict] = {}
    stats = {"skipped_null_keys": 0, "exact_duplicates": 0}
    conflicts = 0
    for r in rows:
        if r.get("sku_code") is None or r.get("fc_code") is None or r.get("seller_code") is None:
            stats["skipped_null_keys"] += 1
            continue
        k = (str(r["sku_code"]), str(r["fc_code"]), str(r["seller_code"]))
        v = (_num(r.get("avg_demand")), r.get("product_name"))
        if k in out:
            if (out[k]["avg_demand"], out[k]["product_name"]) == v:
                stats["exact_duplicates"] += 1
            else:
                conflicts += 1
            continue
        out[k] = {"sku_code": k[0], "fc_code": k[1], "seller_code": k[2], "avg_demand": v[0], "product_name": v[1]}
    if conflicts:
        raise AppError("AVG_DEMAND_CONFLICTING_ROWS", 409, detail=f"{conflicts} rows")
    return list(out.values()), stats


def _store_day(c, day: str, table: str, rows: list[dict], source_modified: str | None, at: str) -> None:
    c.execute("DELETE FROM avg_demand_daily WHERE business_date=? AND source_table=?", (day, table))
    c.executemany("INSERT INTO avg_demand_daily(business_date, sku_code, fc_code, seller_code, avg_demand, product_name, "
                  "source_table, source_modified, loaded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  [(day, r["sku_code"], r["fc_code"], r["seller_code"], r["avg_demand"], r["product_name"], table,
                    source_modified, at) for r in rows])


def _record_read(c, table: str, day: str, kind: str, n_rows: int, source_modified: str | None) -> str:
    rid = db.new_id("ADR")
    c.execute("INSERT INTO avg_demand_reads(id, source_table, business_date, kind, n_rows, source_modified, completed_at) "
              "VALUES (?,?,?,?,?,?,?)", (rid, table, day, kind, int(n_rows), source_modified, now_iso()))
    return rid


def _multi_seller(rows: list[dict]) -> dict:
    """SKU x FC with more than one seller row (owner 03/11: one seller_code per SKU x FC is expected; none is chosen
    automatically - such keys get no value and are reported)."""
    n: dict[tuple, int] = {}
    for r in rows:
        n[(r["sku_code"], r["fc_code"])] = n.get((r["sku_code"], r["fc_code"]), 0) + 1
    multi = sorted(k for k, v in n.items() if v > 1)
    return {"keys": len(multi), "examples": [f"{s} x {f}" for s, f in multi[:10]]}


def _save(table: str, day: str, kind: str, rows: list[dict], source_modified: str | None, seller_rule: str) -> dict:
    prepared, stats = _prepare(rows)
    multi = _multi_seller(prepared)
    if multi["keys"]:
        multi["seller_rule"] = seller_rule          # the rule in force when the alert was raised (avg_value applies it)
    with db.tx() as c:                  # rows + read record together: a failure stores and records nothing
        _store_day(c, day, table, prepared, source_modified, now_iso())
        rid = _record_read(c, table, day, kind, len(prepared), source_modified)
        if multi["keys"]:
            db.alert(c, "WARNING", "AVG_DEMAND_MULTI_SELLER", {"business_date": day, "source_table": table, **multi},
                     "avg_demand_reads", rid)
    if multi["keys"]:
        log.warning("avg demand: several seller rows for one SKU x FC", extra={"ctx": {"business_date": day, **multi}})
    return {"business_date": day, "read_id": rid, "rows": len(prepared), "multi_seller_keys": multi["keys"], **stats}


def require_today(business_date) -> None:
    """The current snapshot is today's table: refused for another day (a past day: the historical table)."""
    if _day(business_date) != today_vn():
        raise AppError("AVG_CURRENT_ONLY_TODAY", 422,
                       detail=f"{_day(business_date).isoformat()} != today {today_vn().isoformat()}: use --hist-from/--hist-to")


def read_current(business_date, cfg=None, bq=None) -> dict:
    """Store the current AVG_DEMAND snapshot as the rows of `business_date` (Vietnam day, must be today), replacing
    that day's rows of the current table; avg_demand_reads kind CURRENT in the same transaction."""
    cfg = cfg or ss.get("sel2_pipeline")
    _require_enabled(cfg)                                   # before any BigQuery client
    require_today(business_date)
    cfg, bq, client = _ctx(cfg, bq)
    day = _day(business_date).isoformat()
    table = cfg.avg_demand_table
    modified = source_modified_now(table, cfg, bq)          # seen BEFORE the read
    res = connector._run(client, bq, "sel2_avg_demand_current", f"SELECT {_COLS} FROM `{table}`")
    out = _save(table, day, KIND_CURRENT, res["rows"], modified, cfg.avg_seller_rule)
    ingest = sorted({str(r["ingest_time"]) for r in res["rows"] if r.get("ingest_time") is not None})
    out.update(kind=KIND_CURRENT, source_table=table, source_modified=modified, estimated_bytes=res["estimated_bytes"],
               ingest_time=ingest[:3])
    log.info("avg demand current read", extra={"ctx": {k: v for k, v in out.items() if k != "ingest_time"}})
    return out


def read_historical(start, end, cfg=None, bq=None) -> dict:
    """Store each day DATE(transformed_at) in [start, end] of the historical table (partition filter on transformed_at),
    one transaction + one avg_demand_reads row (kind HISTORICAL) per day that has rows. When a day holds several
    snapshots, the latest transformed_at of the day is kept (counted as superseded_rows)."""
    cfg = cfg or ss.get("sel2_pipeline")
    _require_enabled(cfg)                                   # before any BigQuery client
    cfg, bq, client = _ctx(cfg, bq)
    start, end = _day(start), _day(end)
    if end < start or (end - start).days + 1 > MAX_HIST_DAYS:
        raise AppError("VALIDATION_ERROR", 422, detail=f"historical range: start <= end, at most {MAX_HIST_DAYS} days")
    table = cfg.avg_demand_hist_table
    modified = source_modified_now(table, cfg, bq)
    sql = (f"SELECT {_COLS}, CAST(DATE(transformed_at) AS STRING) AS business_date, "
           f"CAST(transformed_at AS STRING) AS transformed_at FROM `{table}` "
           f"WHERE transformed_at >= TIMESTAMP(@start) AND transformed_at < TIMESTAMP(DATE_ADD(@end, INTERVAL 1 DAY))")
    res = connector._run(client, bq, "sel2_avg_demand_hist", sql, [("start", "DATE", start), ("end", "DATE", end)])
    by_day: dict[str, list[dict]] = {}
    for r in res["rows"]:
        by_day.setdefault(str(r["business_date"])[:10], []).append(r)
    days, superseded = [], 0
    for day in sorted(by_day):
        if not (start.isoformat() <= day <= end.isoformat()):
            continue
        rows = by_day[day]
        last = max(str(r.get("transformed_at") or "") for r in rows)
        keep = [r for r in rows if str(r.get("transformed_at") or "") == last]
        superseded += len(rows) - len(keep)
        days.append(_save(table, day, KIND_HISTORICAL, keep, modified, cfg.avg_seller_rule))
    out = {"kind": KIND_HISTORICAL, "source_table": table, "start": start.isoformat(), "end": end.isoformat(),
           "source_modified": modified, "estimated_bytes": res["estimated_bytes"], "rows": sum(d["rows"] for d in days),
           "superseded_rows": superseded, "days": days,
           "days_without_rows": [(start + timedelta(i)).isoformat() for i in range((end - start).days + 1)
                                 if (start + timedelta(i)).isoformat() not in by_day]}
    log.info("avg demand historical read", extra={"ctx": {k: v for k, v in out.items() if k != "days"}})
    return out


def latest_read(conn, business_date, cfg=None) -> dict | None:
    """The completed read used for day D: the latest CURRENT read of D from the current table, else the latest
    HISTORICAL read of D from the historical table (None = no completed read)."""
    cfg = cfg or ss.get("sel2_pipeline", conn)
    day = _day(business_date).isoformat()
    for kind, table in ((KIND_CURRENT, cfg.avg_demand_table), (KIND_HISTORICAL, cfg.avg_demand_hist_table)):
        r = db.one(conn, "SELECT * FROM avg_demand_reads WHERE business_date=? AND kind=? AND source_table=? "
                         "ORDER BY completed_at DESC, rowid DESC LIMIT 1", (day, kind, table))
        if r:
            return r
    return None


def apply_rule(sellers: list[tuple[str, float | None]], rule: str) -> tuple[float | None, str | None]:
    """(value, reason) of one SKU x FC from its (seller_code, avg_demand) rows; reason None = a value."""
    if not sellers:
        return None, REASON_NO_ROW
    if len(sellers) == 1:
        v = sellers[0][1]
        return (v, None) if v is not None else (None, REASON_NULL)
    if rule == "PENDING":
        return None, REASON_PENDING
    if rule.startswith("SELLER:"):
        code = rule.split(":", 1)[1]
        hit = [v for s, v in sellers if s == code]
        if not hit:
            return None, REASON_SELLER
        return (hit[0], None) if hit[0] is not None else (None, REASON_NULL)
    vals = [v for _, v in sellers]
    if any(v is None for v in vals):
        return None, REASON_NULL
    if rule == "SUM":
        return float(sum(vals)), None
    if rule == "MAX":
        return float(max(vals)), None
    raise AppError("VALIDATION_ERROR", 422, detail=f"avg_seller_rule {rule!r}")


def avg_value(business_date, keys=None, rule: str | None = None, conn=None, cfg=None) -> dict:
    """AVG_DEMAND value per (sku_code, fc_code) of day D with the seller rule (default: the settings). keys: iterable of
    (sku_code, fc_code) (None = every stored SKU x FC of the day; a requested key without a row -> reason NO_ROW).
    Returns the read used (source_kind / source_table / source_modified; all None when the day has no completed read)
    and values {(sku_code, fc_code): {"value", "reason", "n_sellers"}}."""
    def _run(c):
        cf = cfg or ss.get("sel2_pipeline", c)
        rl = rule or cf.avg_seller_rule
        day = _day(business_date).isoformat()
        rd = latest_read(c, day, cf)
        groups: dict[tuple, list] = {}
        if rd:
            for r in c.execute("SELECT sku_code, fc_code, seller_code, avg_demand FROM avg_demand_daily "
                               "WHERE business_date=? AND source_table=? ORDER BY sku_code, fc_code, seller_code",
                               (day, rd["source_table"])):
                groups.setdefault((r[0], r[1]), []).append((r[2], r[3]))
        wanted = list(groups) if keys is None else [(str(s), str(f)) for s, f in keys]
        values = {}
        for k in wanted:
            v, reason = apply_rule(groups.get(k, []), rl)
            values[k] = {"value": v, "reason": reason, "n_sellers": len(groups.get(k, []))}
        return {"business_date": day, "rule": rl, "read_id": rd["id"] if rd else None,
                "source_kind": rd["kind"] if rd else None, "source_table": rd["source_table"] if rd else None,
                "source_modified": rd["source_modified"] if rd else None,
                "completed_at": rd["completed_at"] if rd else None, "values": values}
    if conn is not None:
        return _run(conn)
    with db.read() as c:
        return _run(c)
