"""1.3.2: the deal table (bigquery.deal_table_id) -> deal_snapshots + deals (docs/hoc_lai_2025_deal_20261030.md 1.2,
1.3), and the read-only deal checks.

refresh() reads the table metadata (get_table: modified time, no byte billed), then the deal rows (one read-only query,
dry run first + maximum_bytes_billed through connector._run). ready_time / end_time are TIMESTAMPs whose UTC components
are the Vietnam wall clock (owner-verified): they are kept as the naive text 'YYYY-MM-DD HH:MM:SS' of those components,
never shifted by 7 hours. The rows are put in a canonical order (deal_code, sku_code, fc_code, ready_time, end_time, then
the other columns); content_sha256 is the SHA-256 of their canonical CSV (stdlib csv, header, '' for NULL). One
snapshot per refresh: the gzip of that CSV, or - same content as the latest snapshot of the table - same_as pointing to
the snapshot that holds the rows. A changed content replaces the `deals` rows of the table in the same transaction;
the same content leaves them as they are. deals.snapshot_id is always the snapshot that HOLDS the rows (rows_gz). Duplicate keys (deal_code, sku_code, fc_code) are stored and reported (WARNING DEAL_DUPLICATE_KEYS).
refresh_quietly() is the D-1 hook (after a successful regular load): it never fails the load.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import logging
from collections import Counter
from datetime import datetime, timezone

from .. import db
from .. import settings_service as ss
from ..messages import AppError
from ..timeutil import iso, now_iso
from . import connector

log = logging.getLogger("df.bq.deal_source")
KIND = "deal_source"                 # -- df:deal_source (query kind of connector._run)
COLUMNS = ("deal_code", "sku_code", "fc_code", "ready_time", "end_time", "status", "quantity_used", "max_quantity",
           "reason")
TEXT = ("deal_code", "sku_code", "fc_code", "status", "reason")
TIMES = ("ready_time", "end_time")
NUMBERS = ("quantity_used", "max_quantity")


def _table(bq) -> str:
    if not bq.deal_table_id:
        raise AppError("DEAL_SOURCE_NOT_CONFIGURED", 409, detail="bigquery.deal_table_id is not set")
    return bq.deal_table_id


def _sql(table: str) -> str:
    return f"SELECT {', '.join(COLUMNS)} FROM `{table}`"


def _wall_clock(v) -> str | None:
    """The UTC components of the TIMESTAMP as naive text (they ARE the Vietnam wall clock): never +7 h."""
    if v is None:
        return None
    if not isinstance(v, datetime):
        v = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if v.tzinfo is not None:
        v = v.astimezone(timezone.utc)
    return v.strftime("%Y-%m-%d %H:%M:%S")


def _norm(r: dict) -> dict:
    out = {}
    for k in COLUMNS:
        v = r.get(k)
        if k in TIMES:
            out[k] = _wall_clock(v)
        elif k in NUMBERS:
            out[k] = None if v is None else float(v)
        else:
            out[k] = None if v is None else str(v)
    return out


def _order_key(r: dict) -> tuple:
    # NULL first in every column; two non-NULL values of a column have the same type
    return tuple((False, "") if r[k] is None else (True, r[k]) for k in COLUMNS)


def _csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in rows:
        w.writerow(["" if r[k] is None else r[k] for k in COLUMNS])
    return buf.getvalue().encode("utf-8")


def _checks(rows: list[dict]) -> dict:
    keys = Counter((r["deal_code"], r["sku_code"], r["fc_code"]) for r in rows)
    ready = [r["ready_time"] for r in rows if r["ready_time"] is not None]
    end = [r["end_time"] for r in rows if r["end_time"] is not None]
    return {"n_rows": len(rows), "n_deal_codes": len({r["deal_code"] for r in rows if r["deal_code"] is not None}),
            "duplicate_keys": sum(n - 1 for n in keys.values() if n > 1),
            "ready_after_end": sum(1 for r in rows if r["ready_time"] is not None and r["end_time"] is not None
                                   and r["ready_time"] > r["end_time"]),
            "max_null": sum(1 for r in rows if r["max_quantity"] is None),
            "used_above_max": sum(1 for r in rows if r["quantity_used"] is not None and r["max_quantity"] is not None
                                  and r["quantity_used"] > r["max_quantity"]),
            "by_status": dict(sorted(Counter("" if r["status"] is None else r["status"] for r in rows).items())),
            "min_ready": min(ready, default=None), "max_ready": max(ready, default=None),
            "min_end": min(end, default=None), "max_end": max(end, default=None)}


def _modified(client, table: str) -> str | None:
    """Last-modified time (UTC ISO) of the deal table from its metadata (no query, no byte billed)."""
    try:
        t = client.get_table(table)
    except Exception as e:  # noqa: BLE001 - classified like every BigQuery error
        raise connector._map_error(e) from e
    m = getattr(t, "modified", None)
    return iso(m) if isinstance(m, datetime) else None


def estimate(max_bytes: int | None = None) -> dict:
    """Dry run only (nothing read or written): metadata time and the bytes the refresh would scan."""
    bq = ss.get("bigquery")
    table = _table(bq)
    client = connector._client(bq)
    modified = _modified(client, table)
    est = connector._run(client, bq, KIND, _sql(table), None, dry_run_only=True)["estimated_bytes"]
    return {"source_table": table, "source_modified": modified, "estimated_bytes": est,
            "above_max_bytes": max_bytes is not None and est > max_bytes}


def refresh(trigger: str, job_id: str | None = None, max_bytes: int | None = None) -> dict:
    """Read the deal table, store one snapshot and replace the table's `deals` rows (one transaction). max_bytes:
    refused before the query runs when the dry run is above it (BQ_QUERY_TOO_EXPENSIVE)."""
    bq = ss.get("bigquery")
    table = _table(bq)
    client = connector._client(bq)
    modified = _modified(client, table)
    sql = _sql(table)
    if max_bytes is not None:
        est = connector._run(client, bq, KIND, sql, None, dry_run_only=True)["estimated_bytes"]
        if est > max_bytes:
            raise AppError("BQ_QUERY_TOO_EXPENSIVE", 413, detail=f"{est} bytes > --max-bytes {max_bytes}",
                           estimated_bytes=est)
    res = connector._run(client, bq, KIND, sql, None)
    rows = sorted((_norm(r) for r in res["rows"]), key=_order_key)
    body = _csv(rows)
    sha = hashlib.sha256(body).hexdigest()
    chk = {**_checks(rows), "source_modified": modified, "estimated_bytes": res["estimated_bytes"]}
    sid = db.new_id("DSN")
    with db.tx() as c:
        n_stored = c.execute("SELECT COUNT(*) FROM deals WHERE source_table=?", (table,)).fetchone()[0]
        if not rows and n_stored:
            # an empty read (table being rebuilt, lost permission) never replaces the stored deals with nothing
            raise AppError("DEAL_REFRESH_FAILED", 409, detail=json.dumps({"reason": "EMPTY_READ", "rows_stored": n_stored}))
        last = db.one(c, "SELECT id, content_sha256, same_as FROM deal_snapshots WHERE source_table=? "
                         "ORDER BY taken_at DESC, rowid DESC LIMIT 1", (table,))
        same_as = (last["same_as"] or last["id"]) if last and last["content_sha256"] == sha else None
        c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, source_modified, n_rows, content_sha256, "
                  "rows_gz, same_as, checks_json, estimated_bytes, trigger, job_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (sid, table, now_iso(), modified, len(rows), sha, None if same_as else gzip.compress(body, mtime=0),
                   same_as, json.dumps(chk, default=str), res["estimated_bytes"], trigger, job_id))
        # same content as the latest snapshot: the stored deals already are these rows and keep pointing to the
        # snapshot that holds them (same_as); they are rewritten only when the content changed (or the stored rows are
        # not that snapshot's any more), always with the id of the snapshot that holds the rows
        holder = same_as or sid
        keep = same_as is not None and n_stored == len(rows) and c.execute(
            "SELECT COUNT(*) FROM deals WHERE source_table=? AND snapshot_id=?", (table, same_as)).fetchone()[0] == n_stored
        if not keep:
            c.execute("DELETE FROM deals WHERE source_table=?", (table,))
            c.executemany("INSERT INTO deals(source_table, row_no, deal_code, sku_code, fc_code, ready_time, end_time, "
                          "status, quantity_used, max_quantity, reason, snapshot_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          [(table, i, *(r[k] for k in COLUMNS), holder) for i, r in enumerate(rows, start=1)])
        if chk["duplicate_keys"]:
            db.alert(c, "WARNING", "DEAL_DUPLICATE_KEYS", {"snapshot_id": sid, "source_table": table,
                                                            "duplicate_keys": chk["duplicate_keys"]},
                     "deal_snapshot", sid)
        db.audit(c, "DEAL_SNAPSHOT", "deal_snapshot", sid, {"source_table": table, "n_rows": len(rows),
                                                            "same_as": same_as, "trigger": trigger})
    out = {"snapshot_id": sid, "source_table": table, "n_rows": len(rows), "content_sha256": sha, "same_as": same_as,
           "rows_stored": same_as is None, "deals_rewritten": not keep, "replaced_deals": 0 if keep else n_stored,
           "deals_snapshot_id": holder, "checks": chk,
           "estimated_bytes": res["estimated_bytes"], "source_modified": modified, "trigger": trigger}
    log.info("deal table refreshed", extra={"ctx": {k: out[k] for k in ("snapshot_id", "n_rows", "same_as")}})
    return out


def refresh_quietly(trigger: str, job_id: str | None = None) -> dict | None:
    """The D-1 hook: refresh() when bigquery.deal_table_id is set (None otherwise); an error never fails the caller:
    WARNING alert DEAL_REFRESH_FAILED, {status: FAILED} returned, the stored deals and snapshots unchanged."""
    if not ss.get("bigquery").deal_table_id:
        return None
    try:
        return {"status": "SUCCEEDED", **refresh(trigger, job_id)}
    except Exception as ex:  # noqa: BLE001 - informative data of the deal features; the D-1 load is written
        log.warning("deal table not refreshed", exc_info=True, extra={"ctx": {"job_id": job_id}})
        err = ex.to_dict() if isinstance(ex, AppError) else {"code": type(ex).__name__, "detail": str(ex)[:300]}
        try:
            with db.tx() as c:
                db.alert(c, "WARNING", "DEAL_REFRESH_FAILED", {"trigger": trigger, "job_id": job_id, "error": err},
                         "settings", "bigquery")
        except Exception:  # noqa: BLE001 - a locked database never fails the D-1 load (the result still says FAILED)
            log.warning("deal refresh alert not written", exc_info=True, extra={"ctx": {"job_id": job_id}})
        return {"status": "FAILED", "trigger": trigger, "error": err}


def _share(part, whole):
    return None if not whole else part / whole


def checks(scope_key: str, start: str | None = None, end: str | None = None) -> dict:
    """Read-only (database only, no BigQuery): the stored deals of the configured deal table (or of the latest snapshot
    when none is configured) and the order-line deal codes of the scope in [start, end] (None = no bound)."""
    with db.read() as c:
        table = ss.get("bigquery", c).deal_table_id
        if not table:
            r = db.one(c, "SELECT source_table FROM deal_snapshots ORDER BY taken_at DESC, rowid DESC LIMIT 1")
            table = r["source_table"] if r else ""
        d = c.execute("SELECT COUNT(*), SUM(ready_time > end_time) FROM deals WHERE source_table=?", (table,)).fetchone()
        n_keys = c.execute("SELECT COUNT(*) FROM (SELECT 1 FROM deals WHERE source_table=? "
                           "GROUP BY deal_code, sku_code, fc_code)", (table,)).fetchone()[0]
        w, p = "l.scope_key=?", [scope_key]
        if start:
            w += " AND l.order_date >= ?"
            p.append(str(start))
        if end:
            w += " AND l.order_date <= ?"
            p.append(str(end))
        li = c.execute(
            f"SELECT COUNT(*), TOTAL(l.qty), "
            f"SUM(EXISTS (SELECT 1 FROM deals d WHERE d.source_table=? AND d.deal_code=l.deal_code AND "
            f"d.sku_code=l.sku_id AND d.fc_code=l.fc_id)), "
            f"TOTAL(CASE WHEN EXISTS (SELECT 1 FROM deals d WHERE d.source_table=? AND d.deal_code=l.deal_code AND "
            f"d.sku_code=l.sku_id AND d.fc_code=l.fc_id) THEN l.qty END), "
            f"SUM(EXISTS (SELECT 1 FROM deals d WHERE d.source_table=? AND d.deal_code=l.deal_code)), "
            f"TOTAL(CASE WHEN EXISTS (SELECT 1 FROM deals d WHERE d.source_table=? AND d.deal_code=l.deal_code) "
            f"THEN l.qty END) FROM demand_deal_daily l WHERE {w}", [table] * 4 + p).fetchone()
        # per deal key with lines in the window: its line quantity vs quantity_used (duplicate keys summed)
        per = c.execute(
            f"SELECT k.used, x.q FROM (SELECT deal_code, sku_code, fc_code, SUM(quantity_used) AS used FROM deals "
            f"WHERE source_table=? GROUP BY 1, 2, 3) k JOIN (SELECT l.deal_code, l.sku_id, l.fc_id, TOTAL(l.qty) AS q "
            f"FROM demand_deal_daily l WHERE {w} GROUP BY 1, 2, 3) x ON x.deal_code=k.deal_code AND x.sku_id=k.sku_code "
            f"AND x.fc_id=k.fc_code WHERE k.used IS NOT NULL", [table] + p).fetchall()
        snap = db.one(c, "SELECT id, taken_at FROM deal_snapshots WHERE source_table=? ORDER BY taken_at DESC, "
                         "rowid DESC LIMIT 1", (table,))
    rows, qty = int(li[0] or 0), float(li[1] or 0.0)
    n = len(per)
    used, lq = sum(float(u) for u, _ in per), sum(float(q) for _, q in per)
    equal = sum(1 for u, q in per if abs(float(q) - float(u)) <= 1e-6)
    near = sum(1 for u, q in per if abs(float(q) - float(u)) <= 0.05 * abs(float(u)) + 1e-6)
    return {"scope_key": scope_key, "source_table": table or None, "window": {"start": start, "end": end},
            "deals": {"n_rows": int(d[0] or 0), "duplicate_keys": int(d[0] or 0) - int(n_keys or 0),
                      "ready_after_end": int(d[1] or 0)},
            "lines": {"rows": rows, "qty": qty,
                      "match_key": {"rows": int(li[2] or 0), "qty": float(li[3] or 0.0),
                                    "rows_share": _share(int(li[2] or 0), rows), "qty_share": _share(float(li[3] or 0.0), qty)},
                      "match_code": {"rows": int(li[4] or 0), "qty": float(li[5] or 0.0),
                                     "rows_share": _share(int(li[4] or 0), rows), "qty_share": _share(float(li[5] or 0.0), qty)}},
            "per_deal": {"deals_compared": n, "share_equal": _share(equal, n), "share_within_5pct": _share(near, n),
                         "line_qty": lq, "quantity_used": used, "ratio": _share(lq, used)},
            "snapshot": {"id": snap["id"], "taken_at": snap["taken_at"]} if snap else {"id": None, "taken_at": None}}
