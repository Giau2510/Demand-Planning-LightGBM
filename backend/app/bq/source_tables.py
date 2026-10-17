"""1.2.0: the BigQuery table of each feed, configured and checked separately (full id project.dataset.table).

  D-1 (closed days, history load)  bigquery.project_id / dataset_id / source_table  (scope key + mapping hash)
  D-0 (today, intraday snapshots)  bigquery.d0_table_id                             (TABLE mode of the D-0 feed)

A check reads table METADATA only (no query, no cost): the table exists and is readable with the credentials of the
Windows account that runs the app, its location equals the configured one, and its schema has every column the feed
reads with a compatible type (D-1: every mapped column, internal + reference fields; D-0 (1.2.1): the D-0 feed's OWN
mapping only - SKU, FC, quantity, the day and the key columns, see d0_feed.py; the D-0 table does not need the D-1
columns). A D-0 check records the D-0 mapping hash and column types it proved: a later change of the D-0 mapping needs
a new check. A table is saved only after a PASSED check of that exact id. Nothing is created or renamed, and a failing table never falls back to another one. The D-1 table
cannot be changed while production mode is on (that would silently switch the data scope of the forecasts)."""
from __future__ import annotations

import json

from .. import db
from .. import settings_service as ss
from ..messages import AppError
from ..timeutil import now_iso
from . import connector

KINDS = ("d1", "d0")


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise AppError("VALIDATION_ERROR", 422, detail=f"unknown feed {kind!r} (d1 | d0)")
    return kind


def parse(table_id: str) -> tuple[str, str, str]:
    m = ss.TABLE_ID_RE.match((table_id or "").strip())
    if not m:
        raise AppError("BQ_TABLE_ID_INVALID", 422, detail=f"{table_id!r}: expected project.dataset.table")
    return m.group(1), m.group(2), m.group(3)


def current_id(kind: str, bq=None) -> str:
    bq = bq or ss.get("bigquery")
    if _kind(kind) == "d1":
        return f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}" if bq.dataset_id and bq.source_table else ""
    return bq.d0_table_id


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
    ok = bool(lc and lc.get("status") == "PASSED" and lc.get("table_id") == current_id(kind, bq))
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
    res = check(kind, tid)
    if res["status"] != "PASSED":
        raise AppError("BQ_TABLE_CHECK_FAILED", 409, detail="; ".join(e["code"] for e in res["errors"]),
                       errors=res["errors"])
    if kind == "d0":
        if tid != bq.d0_table_id:
            ss.update("bigquery", {"d0_table_id": tid}, note=f"D-0 table {tid} (checked)")
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
            out[kind] = {"table_id": current_id(kind, bq), "last_check": lc,
                         "ok": bool(lc and lc.get("status") == "PASSED" and lc.get("table_id") == current_id(kind, bq))}
    out["d1"].update(used_by="D1_SYNC, validation, ingest check", production_enabled=bq.production_enabled)
    from . import d0_feed
    lc0 = out["d0"]["last_check"] or {}
    out["d0"]["ok"] = out["d0"]["ok"] and lc0.get("d0_mapping_hash") == d0_feed.mapping_hash(bq)
    out["d0"].update(used_by="D0_SYNC when the D-0 feed is in TABLE mode", mode=ss.get("sql_sources").d0.mode)
    return out
