"""1.2.0: the BigQuery table of each feed, configured and checked separately (full id project.dataset.table).

  D-1 (closed days, history load)  bigquery.project_id / dataset_id / source_table  (scope key + mapping hash)
  D-0 (today, intraday snapshots)  bigquery.d0_table_id                             (TABLE mode of the D-0 feed)

A check reads table METADATA only (no query, no cost): the table exists and is readable with the credentials of the
Windows account that runs the app, its location equals the configured one, and its schema has every column the feed
reads with a compatible type (D-1: every mapped column, internal + reference fields; D-0 (1.2.1): the D-0 feed's OWN
mapping only - SKU, FC, quantity, the day and the key columns, see d0_feed.py; the D-0 table does not need the D-1
columns). A D-0 check records the D-0 mapping hash and column types it proved: a later change of the D-0 mapping needs
a new check. A table is saved only after a PASSED check of that exact id. Nothing is created or renamed, and a failing table never falls back to another one. The D-1 table
cannot be changed while production mode is on (that would silently switch the data scope of the forecasts).

1.4.9: the auxiliary tables are configured and checked the same way (full id, metadata-only check, saved only after a
PASSED check of that exact id, settings history kept by settings_service); the check requires every column the code
reads from the table with a compatible type (AUX_COLUMNS = the SELECTs of the modules below):

  openhours        daily_forecast.openhours_table       bq/aux_sources.fetch_open_hours (daily refresh, SEL2)
  avg_demand       sel2_pipeline.avg_demand_table       ml/sel2/avg_demand.read_current (_COLS)
  avg_demand_hist  sel2_pipeline.avg_demand_hist_table  ml/sel2/avg_demand.read_historical (_COLS + transformed_at)
  product_names    bigquery.product_names_table         bq/product_names.refresh (the configured key / name columns;
                                                        a stored short name shows as its effective full id)"""
from __future__ import annotations

import json

from .. import db
from .. import settings_service as ss
from ..messages import AppError
from ..timeutil import now_iso
from . import connector

KINDS = ("d1", "d0", "openhours", "avg_demand", "avg_demand_hist", "product_names")
# 1.4.9: settings section and key of each auxiliary table
AUX = {"openhours": ("daily_forecast", "openhours_table"), "avg_demand": ("sel2_pipeline", "avg_demand_table"),
       "avg_demand_hist": ("sel2_pipeline", "avg_demand_hist_table"),
       "product_names": ("bigquery", "product_names_table")}
# columns read by the code -> compatible BigQuery types (None = any type: the value is only turned into text)
_AVG = {"fc_code": connector.TEXTISH, "sku_code": connector.TEXTISH, "seller_code": connector.TEXTISH,
        "avg_demand": connector.NUMERIC, "product_name": {"STRING"}, "ingest_time": None}
AUX_COLUMNS = {
    # seller_code is compared with a STRING parameter, open_date with DATE parameters (BETWEEN @start AND @end)
    "openhours": {"fc_code": connector.TEXTISH, "sku_code": connector.TEXTISH, "item_code": connector.TEXTISH,
                  "seller_code": {"STRING"}, "open_date": {"DATE"}, "total_open_hours": connector.NUMERIC},
    "avg_demand": _AVG,
    # transformed_at is compared with TIMESTAMP(@start) and gives the day (DATE(transformed_at))
    "avg_demand_hist": {**_AVG, "transformed_at": {"TIMESTAMP"}},
}
USED_BY = {"openhours": "daily forecast refresh + SEL2 (open hours per SKU x FC x day)",
           "avg_demand": "SEL2 AVG_DEMAND of today (forecast_used when the source is AVG_DEMAND or a fallback)",
           "avg_demand_hist": "SEL2 AVG_DEMAND of past days (history, backtest, re-export)",
           "product_names": "product names next to the SKU (display and search only)"}


# jobs that read an auxiliary table (directly or through its stored copy keyed by the table id): the daily refresh
# (open hours, AVG_DEMAND), the exports (AVG re-export), the SEL2 candidates, D-1 (product names after the sync) and the
# SO lines; the AVG / open-hours reads have no job type of their own (they run inside these jobs or the CLI)
READER_JOBS = ("FORECAST_REFRESH", "CANDIDATE_TRAIN", "FORECAST_EXPORT", "D1_SYNC", "SPIKE_LINES")


def _require_no_reader_job(kind: str) -> None:
    """A new auxiliary table is refused while a job that reads it is PENDING / RUNNING / RETRY_WAIT (the job would mix
    the old and the new table)."""
    from ..jobs.flows import ACTIVE_STATUSES
    with db.read() as c:
        r = c.execute(f"SELECT id, job_type, status FROM job_runs WHERE job_type IN ({','.join('?' * len(READER_JOBS))}) "
                      f"AND status IN ({','.join('?' * len(ACTIVE_STATUSES))}) ORDER BY created_at DESC, rowid DESC "
                      "LIMIT 1", (*READER_JOBS, *ACTIVE_STATUSES)).fetchone()
    if r:
        raise AppError("BQ_TABLE_CHANGE_JOB_ACTIVE", 409, detail=f"{kind}: {r[1]} {r[0]} {r[2]}")


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise AppError("VALIDATION_ERROR", 422, detail=f"unknown table {kind!r} ({' | '.join(KINDS)})")
    return kind


def required_columns(kind: str, bq=None) -> dict:
    """Columns the code reads from the table of an auxiliary kind -> compatible types (None = any)."""
    if _kind(kind) == "product_names":
        bq = bq or ss.get("bigquery")
        # the key is CAST AS STRING in the query; the name is read as text (stripped)
        return {bq.product_names_key_column: connector.TEXTISH, bq.product_names_name_column: {"STRING"}}
    return dict(AUX_COLUMNS[kind])


def check_columns(columns: list[dict], kind: str, bq=None) -> dict:
    """The schema of an auxiliary table against the columns the code reads (missing / incompatible type = error)."""
    types = {c["name"]: str(c["type"]).upper() for c in columns}
    errors = []
    for col, ok in required_columns(kind, bq).items():
        if col not in types:
            errors.append({"field": kind, "code": "COLUMN_NOT_FOUND", "column": col})
        elif ok is not None and types[col] not in ok:
            errors.append({"field": kind, "code": "TYPE_INCOMPATIBLE", "column": col, "type": types[col],
                           "expected": sorted(ok)})
    return {"ok": not errors, "errors": errors, "warnings": []}


def parse(table_id: str) -> tuple[str, str, str]:
    m = ss.TABLE_ID_RE.match((table_id or "").strip())
    if not m:
        raise AppError("BQ_TABLE_ID_INVALID", 422, detail=f"{table_id!r}: expected project.dataset.table")
    return m.group(1), m.group(2), m.group(3)


def current_id(kind: str, bq=None, conn=None) -> str:
    bq = bq or ss.get("bigquery", conn)
    if _kind(kind) == "d1":
        return f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}" if bq.dataset_id and bq.source_table else ""
    if kind == "d0":
        return bq.d0_table_id
    if kind == "product_names":
        from . import product_names
        return product_names.source_table(bq)           # the effective full id (a stored short name joined as read)
    section, key = AUX[kind]
    return getattr(ss.get(section, conn), key)


def last_check(kind: str, conn=None) -> dict | None:
    def q(c):
        r = c.execute("SELECT value_json FROM sync_state WHERE name=?", (f"bq_table_check:{_kind(kind)}",)).fetchone()
        return json.loads(r[0]) if r else None
    if conn is not None:
        return q(conn)
    with db.read() as c:
        return q(c)


def is_ok(kind: str, conn=None) -> bool:
    """The configured table of this feed passed its last check (and that check was for this exact table id; for D-0
    also for the current D-0 mapping)."""
    lc = last_check(kind, conn)
    bq = ss.get("bigquery", conn)
    ok = bool(lc and lc.get("status") == "PASSED" and lc.get("table_id") == current_id(kind, bq, conn))
    if ok and kind == "d0":
        from . import d0_feed
        ok = lc.get("d0_mapping_hash") == d0_feed.mapping_hash(bq, conn=conn)
    return ok


def check(kind: str, table_id: str | None = None) -> dict:
    kind = _kind(kind)
    bq = ss.get("bigquery")
    tid = (table_id if table_id is not None else current_id(kind, bq)).strip()
    out: dict = {"kind": kind, "table_id": tid, "checked_at": now_iso(), "status": "FAILED", "errors": [],
                 "warnings": []}
    try:
        parse(tid)
        client = connector._client(bq)
        try:
            t = client.get_table(tid)
        except Exception as e:  # noqa: BLE001 - classified into a catalogue code (no credential in the message)
            raise connector._map_error(e) from e
        cols = [{"name": f.name, "type": f.field_type.upper(), "mode": getattr(f, "mode", "NULLABLE")} for f in t.schema]
        loc = str(getattr(t, "location", "") or "")
        out.update(columns=cols, n_columns=len(cols), num_rows=getattr(t, "num_rows", None), location=loc,
                   modified=str(getattr(t, "modified", "") or ""), table_type=str(getattr(t, "table_type", "") or ""))
        if bq.location and loc and loc.lower() != bq.location.lower():
            out["errors"].append({"code": "BQ_LOCATION_MISMATCH", "detail": f"{loc} != {bq.location}"})
        if kind == "d1":
            chk = connector.validate_mapping(cols, bq.field_mapping, None)
        elif kind in AUX:
            chk = check_columns(cols, kind, bq)
            out.update(required_columns=sorted(required_columns(kind, bq)))
        else:
            from . import d0_feed
            src = ss.get("sql_sources").d0
            chk = d0_feed.check_columns(cols, bq, d0_feed.key_columns(src, bq))
            out.update(d0_mapping_hash=d0_feed.mapping_hash(bq, src), mapped_types=chk["mapped_types"],
                       ignored_columns=chk["ignored_columns"])
        out["errors"] += [{"code": "BQ_MAPPING_INVALID", **e} for e in chk["errors"]]
        out["warnings"] += chk.get("warnings", [])
        out["status"] = "FAILED" if out["errors"] else "PASSED"
    except AppError as e:
        out["errors"].append({"code": e.code, "detail": e.detail})
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET "
                  "value_json=excluded.value_json, updated_at=excluded.updated_at",
                  (f"bq_table_check:{kind}", json.dumps({k: v for k, v in out.items() if k != "columns"}), now_iso()))
        db.audit(c, "BQ_TABLE_CHECKED", "bigquery", kind, {"table_id": tid, "status": out["status"],
                                                           "errors": [e["code"] for e in out["errors"]]})
    return out


def save(kind: str, table_id: str) -> dict:
    kind = _kind(kind)
    tid = (table_id or "").strip()
    proj, ds, tbl = parse(tid)
    bq = ss.get("bigquery")
    if kind == "d1" and tid != current_id("d1", bq) and bq.production_enabled:
        raise AppError("BQ_TABLE_CHANGE_NEEDS_PRODUCTION_OFF", 409, detail=f"{current_id('d1', bq)} -> {tid}")
    if kind in AUX and tid != current_id(kind, bq):
        _require_no_reader_job(kind)
    res = check(kind, tid)
    if res["status"] != "PASSED":
        raise AppError("BQ_TABLE_CHECK_FAILED", 409, detail="; ".join(e["code"] for e in res["errors"]),
                       errors=res["errors"])
    if kind == "d0":
        if tid != bq.d0_table_id:
            ss.update("bigquery", {"d0_table_id": tid}, note=f"D-0 table {tid} (checked)")
    elif kind in AUX:
        section, key = AUX[kind]
        if tid != current_id(kind, bq):
            ss.update(section, {key: tid}, note=f"{section}.{key} = {tid} (checked)")
    elif tid != current_id("d1", bq):
        ss.update("bigquery", {"project_id": proj, "dataset_id": ds, "source_table": tbl,
                               "schema_snapshot": res["columns"]}, note=f"D-1 table {tid} (checked)")
    return status()


def status() -> dict:
    bq = ss.get("bigquery")
    with db.read() as c:
        out = {}
        for kind in KINDS:
            lc = last_check(kind, c)
            tid = current_id(kind, bq, c)
            out[kind] = {"table_id": tid, "last_check": lc,
                         "ok": bool(lc and lc.get("status") == "PASSED" and lc.get("table_id") == tid)}
            if kind in AUX:
                out[kind].update(setting=".".join(AUX[kind]), used_by=USED_BY[kind],
                                 required_columns=sorted(required_columns(kind, bq)))
    out["d1"].update(used_by="D1_SYNC, validation, ingest check", production_enabled=bq.production_enabled)
    from . import d0_feed
    lc0 = out["d0"]["last_check"] or {}
    out["d0"]["ok"] = out["d0"]["ok"] and lc0.get("d0_mapping_hash") == d0_feed.mapping_hash(bq)
    out["d0"].update(used_by="D0_SYNC when the D-0 feed is in TABLE mode", mode=ss.get("sql_sources").d0.mode)
    return out
