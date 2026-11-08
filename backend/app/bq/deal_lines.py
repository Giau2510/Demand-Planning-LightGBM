"""1.3.2: order-line deal codes of the D-1 source -> demand_deal_daily (docs/hoc_lai_2025_deal_20261030.md 1.2, 1.3).

When bigquery.deal_code_column is set, the D-1 load, a backfill and the CLI (deal-lines-load) read, for their own
window, the quantity of the order lines that carry a deal code, per Vietnam day x SKU x FC x deal code. The read uses
the same source relation (table or validated user SQL), day expression, valid-line rule (SKU, FC, quantity present and
>= 0: connector._REASON) and exact-duplicate rule (DROP_EXACT keeps one row per group like the demand read; BLOCK /
KEEP keep every row) as the demand aggregation (connector._daily_sql); the deal code is TRIMmed, empty = no deal.
Read-only BigQuery through connector._run (dry run first + maximum_bytes_billed).

A load replaces exactly its own window of the scope in one transaction and records one deal_line_loads row. It is
refused (nothing written) when the deal-code quantity of a day x SKU x FC is above the stored demand of that key or a
key has no stored demand (DEAL_LINES_EXCEED_DEMAND), or when the source table version changed since the given version.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from .. import db
from .. import settings_service as ss
from ..messages import AppError
from ..timeutil import now_iso
from . import connector, source_lines

log = logging.getLogger("df.bq.deal_lines")
KIND = "deal_lines"                  # -- df:deal_lines (query kind of connector._run)
TRIGGERS = ("D1_SYNC", "BACKFILL", "MANUAL")
TOL = 1e-6


def months(s: date, e: date) -> list[tuple[date, date]]:
    """[s, e] split into calendar-month chunks, oldest first (the unit of a load: one query, one transaction)."""
    out = []
    while s <= e:
        ce = min(e, (s.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1))
        out.append((s, ce))
        s = ce + timedelta(days=1)
    return out


def _deal_expr(bq) -> str:
    return f"NULLIF(TRIM(CAST(`{bq.deal_code_column}` AS STRING)), '') AS _deal"


def deal_sql(bq, start: date, end: date, snap: dict | None = None) -> tuple[str, list]:
    """Per order_date x sku_id x fc_id x deal_code: SUM(qty), COUNT(*) of the valid lines with a deal code ('DEAL'),
    plus one 'TOTAL' row (valid lines / quantity of the whole window). Same CTE chain as connector._daily_sql."""
    al = connector._aliases(bq, with_refs=True)
    cols = ", ".join(al) + ", _order_date, _key"
    kcols = cols + ", _deal"
    kept = f"SELECT {kcols} FROM src"
    if bq.exact_duplicate_policy == "DROP_EXACT":
        # the row the demand read keeps (first by its full value), then the deal code: one deterministic row per group
        cmp = ", ".join(c["alias"] for c in connector.dup_columns(bq))
        kept = (f"SELECT {kcols} FROM src WHERE _pend UNION ALL SELECT {kcols} FROM (SELECT {kcols}, ROW_NUMBER() OVER ("
                f"PARTITION BY TO_JSON_STRING(STRUCT({cmp})) ORDER BY TO_JSON_STRING(STRUCT({cols})), _deal) AS _rn "
                f"FROM src WHERE NOT _pend) WHERE _rn = 1")
    sql = f"""WITH src AS (
  {connector._src_cte(bq, True, snap=snap, extra=(_deal_expr(bq),))}
), kept AS (
  {kept}
), checked AS (
  SELECT {kcols}, {connector._REASON} AS _reason FROM kept
)
SELECT 'DEAL' AS _kind, _order_date AS order_date, CAST(sku_id AS STRING) AS sku_id, CAST(fc_id AS STRING) AS fc_id,
  _deal AS deal_code, SUM(order_qty) AS qty, COUNT(*) AS n_rows
FROM checked WHERE _reason IS NULL AND _deal IS NOT NULL GROUP BY 2, 3, 4, 5
UNION ALL
SELECT 'TOTAL', CAST(NULL AS DATE), CAST(NULL AS STRING), CAST(NULL AS STRING), CAST(NULL AS STRING), SUM(order_qty),
  COUNT(*)
FROM checked WHERE _reason IS NULL"""
    return sql, [("start", "DATE", start), ("end", "DATE", end)]


def _prepare(bq, start: date, end: date, snap: dict | None):
    if not bq.deal_code_column:
        raise AppError("VALIDATION_ERROR", 422, detail="bigquery.deal_code_column is not set")
    connector._require_config(bq)
    if end < start:
        raise AppError("VALIDATION_ERROR", 422, detail=f"deal lines window {start}..{end}")
    snap = connector._snap(snap)
    return snap, deal_sql(bq, start, end, snap)


def estimate(start: date, end: date, snap: dict | None = None) -> int:
    """Dry run only (nothing is read or written): bytes the read of [start, end] would scan."""
    bq = ss.get("bigquery")
    snap, (sql, params) = _prepare(bq, start, end, snap)
    return connector._run(connector._client(bq), bq, KIND, sql, params, dry_run_only=True)["estimated_bytes"]


def _parse(rows: list[dict]) -> tuple[dict, dict]:
    """({(day, sku, fc, code): [qty, n_rows]}, total {qty, n_rows}). A blank code is no deal (also when the source
    returns one); keys equal after TRIM are summed."""
    out: dict[tuple, list] = {}
    total = {"qty": 0.0, "n_rows": 0}
    for r in rows:
        if r.get("_kind") == "TOTAL":
            total = {"qty": float(r.get("qty") or 0.0), "n_rows": int(r.get("n_rows") or 0)}
            continue
        code = r.get("deal_code")
        code = str(code).strip() if code is not None else ""
        if not code or r.get("sku_id") is None or r.get("fc_id") is None or r.get("order_date") is None:
            continue
        if r.get("qty") is None:
            raise AppError("DEAL_LINES_LOAD_FAILED", 409, detail=f"NULL quantity for {r.get('order_date')} "
                                                               f"{r.get('sku_id')} {r.get('fc_id')} {code}")
        k = (str(r["order_date"])[:10], str(r["sku_id"]), str(r["fc_id"]), code)
        cur = out.setdefault(k, [0.0, 0])
        cur[0] += float(r["qty"])
        cur[1] += int(r.get("n_rows") or 0)
    return out, total


def write(scope_key: str, start: date, end: date, rows: dict, *, trigger: str, total: dict, deal_code_column: str,
          job_id: str | None = None, version: str | None = None, estimated_bytes: int | None = None,
          started: str | None = None, allow_empty: bool = False) -> dict:
    """One transaction: delete the scope's lines of [start, end], insert `rows` ({(day, sku, fc, code): [qty, n]}),
    record one deal_line_loads row. Refused, nothing written: the source table version changed since `version`
    (DEAL_LINES_LOAD_FAILED), a key's deal quantity above its stored demand or without stored demand
    (DEAL_LINES_EXCEED_DEMAND), an empty read where lines are stored (DEAL_LINES_LOAD_FAILED EMPTY_READ), a read
    without any deal-code line where lines are stored (DEAL_LINES_LOAD_FAILED EMPTY_DEAL_READ) unless `allow_empty`
    (an explicit decision: the window really has no deal any more)."""
    if trigger not in TRIGGERS:
        raise AppError("VALIDATION_ERROR", 422, detail=f"trigger {trigger}")
    if version is not None and source_lines.table_version() != version:
        raise AppError("DEAL_LINES_LOAD_FAILED", 409, detail=json.dumps(
            {"reason": "SOURCE_CHANGED_DURING_READ", "version_before": version}))
    s, e = str(start), str(end)
    per_key: dict[tuple, float] = {}
    for (d, sku, fc, _code), (q, _n) in rows.items():
        per_key[(d, sku, fc)] = per_key.get((d, sku, fc), 0.0) + q
    load_id = db.new_id("DLL")
    qty = float(sum(v[0] for v in rows.values()))
    with db.tx() as c:
        demand = {(r[0], r[1], r[2]): r[3] for r in c.execute(
            "SELECT order_date, sku_id, fc_id, qty FROM demand_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?",
            (scope_key, s, e))}
        bad = []
        for k, q in sorted(per_key.items()):
            dq = demand.get(k)
            if dq is None or q > float(dq) + TOL:
                bad.append({"key": list(k), "deal_qty": q, "demand_qty": dq})
        if bad:
            raise AppError("DEAL_LINES_EXCEED_DEMAND", 409, detail=json.dumps(bad[:20], default=str), keys=len(bad),
                           window=[s, e])
        # after the per-key check (its code is the one reported): the deal lines are part of the valid lines read
        tq = float(total.get("qty") or 0.0)
        if qty > tq + TOL * max(1.0, abs(tq)):
            raise AppError("DEAL_LINES_LOAD_FAILED", 409, detail=f"deal-code quantity {qty} above the valid quantity "
                                                               f"{tq} of {s}..{e}")
        n_old = c.execute("SELECT COUNT(*) FROM demand_deal_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?",
                          (scope_key, s, e)).fetchone()[0]
        if not total.get("n_rows") and n_old:
            # an empty read (table being rebuilt, lost permission) never replaces stored lines with nothing
            raise AppError("DEAL_LINES_LOAD_FAILED", 409, detail=json.dumps(
                {"reason": "EMPTY_READ", "window": [s, e], "rows_stored": n_old}))
        if not rows and n_old and not allow_empty:
            # order lines read but none with a deal code (e.g. the deal column emptied by a rebuild): the stored lines
            # are kept unless the caller says the window has no deal any more (CLI deal-lines-load --allow-empty)
            raise AppError("DEAL_LINES_LOAD_FAILED", 409, detail=json.dumps(
                {"reason": "EMPTY_DEAL_READ", "window": [s, e], "rows_stored": n_old,
                 "lines_read": int(total.get("n_rows") or 0)}))
        c.execute("DELETE FROM demand_deal_daily WHERE scope_key=? AND order_date BETWEEN ? AND ?", (scope_key, s, e))
        at = now_iso()
        c.executemany("INSERT INTO demand_deal_daily(scope_key, order_date, sku_id, fc_id, deal_code, qty, n_rows, "
                      "load_id, loaded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                      [(scope_key, k[0], k[1], k[2], k[3], v[0], v[1], load_id, at) for k, v in sorted(rows.items())])
        w = c.execute("SELECT COUNT(*), TOTAL(qty) FROM demand_deal_daily WHERE scope_key=? AND order_date BETWEEN ? "
                      "AND ?", (scope_key, s, e)).fetchone()
        if w[0] != len(rows) or abs(float(w[1]) - qty) > TOL * max(1.0, abs(qty)):
            raise AppError("DEAL_LINES_LOAD_FAILED", 409, detail=f"written {w[0]} rows / {w[1]} qty != read "
                                                               f"{len(rows)} / {qty}")
        c.execute("INSERT INTO deal_line_loads(load_id, scope_key, range_start, range_end, trigger, deal_code_column, "
                  "source_version, rows_written, rows_removed, qty, lines, estimated_bytes, job_id, started_at, "
                  "completed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (load_id, scope_key, s, e, trigger, deal_code_column, version, len(rows), n_old, qty,
                   int(total.get("n_rows") or 0), estimated_bytes, job_id, started or at, now_iso()))
        db.audit(c, "DEAL_LINES_LOADED", "scope", scope_key, {"load_id": load_id, "window": [s, e], "trigger": trigger,
                                                               "rows_written": len(rows), "rows_removed": n_old})
    return {"load_id": load_id, "scope_key": scope_key, "window": {"start": s, "end": e}, "trigger": trigger,
            "rows_written": len(rows), "rows_removed": n_old, "qty": qty,
            "deal_lines": sum(v[1] for v in rows.values()), "lines_read": int(total.get("n_rows") or 0),
            "qty_read": float(total.get("qty") or 0.0), "estimated_bytes": estimated_bytes, "source_version": version}


def load_window(scope_key: str, start: date, end: date, trigger: str, job_id: str | None = None,
                snap: dict | None = None, version: str | None = None, max_bytes: int | None = None,
                allow_empty: bool = False) -> dict:
    """Read the deal lines of [start, end] (Vietnam days) and replace the scope's stored lines of that window (write).
    max_bytes: refused before the query runs when the dry run is above it (BQ_QUERY_TOO_EXPENSIVE). allow_empty: see
    write (EMPTY_DEAL_READ)."""
    bq = ss.get("bigquery")
    snap, (sql, params) = _prepare(bq, start, end, snap)
    client = connector._client(bq)
    started = now_iso()
    if max_bytes is not None:
        est = connector._run(client, bq, KIND, sql, params, dry_run_only=True)["estimated_bytes"]
        if est > max_bytes:
            raise AppError("BQ_QUERY_TOO_EXPENSIVE", 413, detail=f"{est} bytes > --max-bytes {max_bytes}",
                           estimated_bytes=est)
    res = connector._run(client, bq, KIND, sql, params)
    rows, total = _parse(res["rows"])
    out = write(scope_key, start, end, rows, trigger=trigger, total=total, deal_code_column=bq.deal_code_column,
                job_id=job_id, version=version, estimated_bytes=res["estimated_bytes"], started=started,
                allow_empty=allow_empty)
    log.info("deal lines loaded", extra={"ctx": {k: out[k] for k in ("load_id", "window", "trigger", "rows_written")}})
    return out
