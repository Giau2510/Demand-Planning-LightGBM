"""1.3.1 daily forecast refresh, B6: the read-only BigQuery open-hours source copied into its own SQLite table
(docs/ke_hoach_lgbm_chot.md 1, 3). Never part of load_demand / build_panel / the data fingerprint / the D-1 SQL.

  open_hours_daily  <- daily_forecast.openhours_table: per fc x sku x open_date the MAX of total_open_hours over the
                       items and COUNT(DISTINCT item_code)

Filter: seller_code = daily_forecast.seller_code only (sku_system_status is never read). Every query goes through
connector._run (dry run + maximum_bytes_billed) with query parameters; the table id comes from the validated settings.
Read-only: SELECT only, no DML/DDL on BigQuery. Every stored row carries the source table and the seller filter of its
read (part of the key): reads and writes always filter by them, so another table / seller never mixes in.
  Upserted (a stored day is never deleted); a re-read never replaces a stored non-NULL value with NULL (kept, counted as
  kept_on_conflict). A COMPLETED read is recorded in aux_source_reads only after its last chunk committed (the
  incremental watermark), with the last-modified time of the source table seen before the read (source_modified); a
  read that failed midway records nothing, so the next attempt reads its whole range again.
source_modified() reads the table metadata only (no query, no byte billed): the refresh reads the source again only when
it changed since the last completed read.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from .. import db
from .. import settings_service as ss
from ..timeutil import iso, now_iso
from . import connector

log = logging.getLogger("df.bq.aux")
UPSERT_CHUNK_ROWS = 200_000                       # open_hours_daily rows per write transaction
KIND_OPEN_HOURS = "OPEN_HOURS"                    # aux_source_reads.kind


class NotReady(Exception):
    """An input of the refresh is not there yet (the refresh is retried later; nothing was stored)."""

    def __init__(self, code: str, detail: str | None = None, **params):
        super().__init__(f"{code}: {detail or ''}")
        self.code = code
        self.detail = detail
        self.params = params


def _day(d) -> date:
    return d if isinstance(d, date) and not isinstance(d, datetime) else date.fromisoformat(str(d)[:10])


def _ctx(cfg=None, bq=None):
    cfg = cfg or ss.get("daily_forecast")
    bq = bq or ss.get("bigquery")
    return cfg, bq, connector._client(bq)


def open_hours_source(cfg=None) -> tuple[str, str]:
    """(source_table, seller_code) of the configured open-hours read: the key of the stored open_hours_daily rows."""
    cfg = cfg or ss.get("daily_forecast")
    return cfg.openhours_table, cfg.seller_code


def last_completed_read(conn, kind: str, source_table: str, seller_code: str) -> dict | None:
    """Latest COMPLETED read of `kind` from this table / seller (None = never completed)."""
    return db.one(conn, "SELECT * FROM aux_source_reads WHERE source_table=? AND seller_code=? AND kind=? "
                        "ORDER BY completed_at DESC, rowid DESC LIMIT 1", (source_table, seller_code, kind))


def _record_read(c, kind, source_table, seller_code, start, end, n_rows, last_day, source_modified=None) -> None:
    c.execute("INSERT INTO aux_source_reads(source_table, seller_code, kind, range_start, range_end, n_rows, last_day, "
              "source_modified, completed_at) VALUES (?,?,?,?,?,?,?,?,?)",
              (source_table, seller_code, kind, str(start), str(end), int(n_rows), last_day, source_modified, now_iso()))


def source_modified(cfg=None, bq=None) -> str | None:
    """Last-modified time (UTC ISO) of the configured open-hours table from its metadata (get_table: no query, no byte
    billed). None when it is not available; a metadata error is logged, never raised (the caller then reads)."""
    try:
        cfg, bq, client = _ctx(cfg, bq)
        t = client.get_table(open_hours_source(cfg)[0])
        m = getattr(t, "modified", None)
        return iso(m) if isinstance(m, datetime) else None
    except Exception as e:  # noqa: BLE001 - unknown = read the source (never blocks the refresh)
        log.warning("open hours source metadata unavailable", extra={"ctx": {"error": f"{type(e).__name__}: {e}"[:300]}})
        return None


def fetch_open_hours(start, end, cfg=None, bq=None, source_modified: str | None = None,
                     last_day: str | None = None) -> dict:
    """Upsert open_hours_daily for [start, end] (Vietnam dates, open_date of the source); the read is recorded as
    completed (aux_source_reads, with `source_modified` = the table's last-modified time seen before the read) only
    after its last chunk committed. last_day: the last day read by the earlier sub-ranges of the same read (the
    recorded last_day is never earlier, also when this range has no row)."""
    cfg, bq, client = _ctx(cfg, bq)
    table, seller = open_hours_source(cfg)
    start, end = _day(start), _day(end)
    sql = (f"SELECT fc_code, sku_code, CAST(open_date AS STRING) AS open_date, MAX(total_open_hours) AS total_open_hours, "
           f"COUNT(DISTINCT item_code) AS n_items FROM `{table}` "
           f"WHERE open_date BETWEEN @start AND @end AND seller_code = @seller "
           f"AND fc_code IS NOT NULL AND sku_code IS NOT NULL GROUP BY fc_code, sku_code, open_date "
           f"ORDER BY open_date, fc_code, sku_code")
    res = connector._run(client, bq, "daily_open_hours", sql,
                         [("start", "DATE", start), ("end", "DATE", end), ("seller", "STRING", seller)])
    at = now_iso()
    rows, kept = res["rows"], 0
    # upserted in chunks (in open_date order), each in its own short write transaction (a full window is millions of
    # rows: the write lock is never held for the whole read); no watermark unless every chunk committed
    for i in range(0, len(rows), UPSERT_CHUNK_ROWS):
        vals = [(table, seller, str(r["fc_code"]), str(r["sku_code"]), str(r["open_date"])[:10],
                 None if r.get("total_open_hours") is None else float(r["total_open_hours"]),
                 None if r.get("n_items") is None else int(r["n_items"]), at) for r in rows[i:i + UPSERT_CHUNK_ROWS]]
        last_day = max([v[4] for v in vals] + ([last_day] if last_day else []))
        with db.tx() as c:
            # a NULL read never replaces stored hours: the WHERE skips that row (no change counted -> kept_on_conflict)
            cur = c.executemany("INSERT INTO open_hours_daily(source_table, seller_code, fc_code, sku_code, open_date, "
                                "total_open_hours, n_items, loaded_at) VALUES (?,?,?,?,?,?,?,?) "
                                "ON CONFLICT(source_table, seller_code, fc_code, sku_code, open_date) DO UPDATE SET "
                                "total_open_hours=excluded.total_open_hours, n_items=excluded.n_items, "
                                "loaded_at=excluded.loaded_at WHERE excluded.total_open_hours IS NOT NULL "
                                "OR open_hours_daily.total_open_hours IS NULL", vals)
            kept += len(vals) - cur.rowcount
        del vals
    with db.tx() as c:
        _record_read(c, KIND_OPEN_HOURS, table, seller, start, end, len(rows), last_day, source_modified)
    out = {"start": str(start), "end": str(end), "rows": len(rows), "estimated_bytes": res["estimated_bytes"],
           "last_day": last_day, "kept_on_conflict": kept, "source_modified": source_modified}
    log.info("daily forecast open hours read", extra={"ctx": out})
    return out
