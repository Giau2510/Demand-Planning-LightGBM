"""90-day retention of the end-of-day forecast backup (1.2.6, migration 0006; owner decision 18/10/2026). Full
description in docs/LICH-SU-FORECAST.md section 14.

  age        the snapshot's BUSINESS DATE (the Vietnam day it stands for), never a file time or a UTC timestamp.
  expired    business_date < cutoff = today (Vietnam) - 90 days. A snapshot exactly 90 days old is kept: with today
             18/10/2026 the cutoff is 20/07/2026, so 19/07 is deleted and 20/07 kept. The database enforces the same
             floor itself (triggers 0006): a snapshot younger than 90 days cannot be deleted whatever this module says.
  held       an expired COMPLETE snapshot that is still the backup shown for a run date INSIDE the 90 days (no newer
             snapshot in between, forecast_history.fallback_days) is kept until that run date leaves the window. A
             snapshot whose stored values do not match its header (or an incomplete one with values) is held as well
             (data-check reports it). A table other than its values that references the snapshot table refuses the run.
  dry run    the default (CLI eod-retention): read-only connection, prints the plan and its plan_id, writes nothing.
  apply      explicit (--apply) and only for the plan that was reviewed (--plan <plan_id>; the id changes when the set
             of snapshots to delete changes). A verified backup is taken first. Then ONE immediate transaction per
             snapshot: permit row (forecast_eod_snapshot_retention, DELETING) -> values -> header -> DELETED, checked
             before commit. A failure rolls that snapshot back, stops the run and is recorded (audit + alert); the
             snapshots deleted before it stay deleted and recorded. Running again continues; nothing is deleted twice.
  never      forecast_values, the D+1 history, actual closes or any other table; never started by the scheduler.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from . import db
from .messages import AppError
from .timeutil import now_iso, today_vn

log = logging.getLogger("df.eod_retention")

POLICY_DAYS = 90                  # owner decision; migration 0006 refuses any deletion younger than 90 days
TIMEZONE = "Asia/Ho_Chi_Minh"
SCHEMA = 6                        # forecast_eod_snapshot_retention + the retention-only delete triggers
RULE = ("delete when business_date < cutoff_date = today (Vietnam) - 90 days; a snapshot exactly 90 days old "
        "(business_date = cutoff_date) is kept")


def cutoff(today: date | None = None) -> date:
    return (today or today_vn()) - timedelta(days=POLICY_DAYS)


def _schema(c) -> int:
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone():
        return 0
    return c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] or 0


def _unknown_references(c) -> list[str]:
    """Columns of other tables that reference the snapshot table (only its values are known to)."""
    return [f"{t}.{col}" for t, col in c.execute(
        "SELECT m.name, f.\"from\" FROM sqlite_master m JOIN pragma_foreign_key_list(m.name) f "
        "WHERE m.type = 'table' AND f.\"table\" = 'forecast_eod_snapshots' AND m.name != 'forecast_eod_snapshot_values'")]


def _serving(c, scope_key: str, today: date, cut: date) -> dict[str, list[str]]:
    """Snapshot id -> run dates inside the window (>= cutoff) for which it is the backup shown today."""
    from .forecast_history import fallback_days
    out: dict[str, list[str]] = {}
    for d in fallback_days(c, scope_key, today):
        if d["run_date"] >= str(cut):
            out.setdefault(d["snapshot_id"], []).append(d["run_date"])
    return out


def _hold(c, s: dict, today: date, cut: date, serving: dict | None = None) -> dict | None:
    want = s["n_rows"] if s["status"] == "COMPLETE" else 0
    if s["n_values"] != want:
        return {"code": "VALUES_DO_NOT_MATCH_HEADER", "detail": f"{s['n_values']} values stored, header says {want}"}
    if s["status"] == "COMPLETE":
        days = (serving if serving is not None else _serving(c, s["scope_key"], today, cut)).get(s["id"])
        if days:
            return {"code": "SERVES_BACKUP_INSIDE_WINDOW", "detail": f"backup shown for run date(s) {', '.join(sorted(days))}",
                    "run_dates": sorted(days)}
    return None


_EXPIRED = ("SELECT s.id, s.scope_key, s.data_source, s.business_date, s.first_target_date, s.last_target_date, s.status, "
            "s.n_rows, s.created_at, s.source_run_id, (SELECT COUNT(*) FROM forecast_eod_snapshot_values v "
            "WHERE v.snapshot_id = s.id) AS n_values FROM forecast_eod_snapshots s WHERE s.business_date < ?")


def plan(c, today: date | None = None) -> dict:
    """The retention plan on connection c (reads only)."""
    today = today or today_vn()
    cut = cutoff(today)
    schema = _schema(c)
    out = {"policy_days": POLICY_DAYS, "timezone": TIMEZONE, "today": str(today), "cutoff_date": str(cut), "rule": RULE,
           "schema_version": schema, "refused": None, "plan_id": None,
           "delete": {"snapshots": 0, "rows": 0, "first_business_date": None, "last_business_date": None,
                      "by_status": {}, "items": []},
           "held": [], "kept": {"snapshots": 0, "rows": 0, "first_business_date": None}}
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='forecast_eod_snapshots'").fetchone():
        out["apply_ready"] = False
        out["note"] = "no end-of-day backup tables (schema < 5): nothing to do"
        return out
    unknown = _unknown_references(c)
    if unknown:
        out["refused"] = {"code": "EOD_RETENTION_UNKNOWN_REFERENCE",
                          "detail": f"other table(s) reference forecast_eod_snapshots: {', '.join(unknown)}"}
    expired = db.rows(c, _EXPIRED + " ORDER BY s.business_date, s.scope_key, s.id", (str(cut),))
    serving: dict[str, list[str]] = {}
    for scope in sorted({s["scope_key"] for s in expired if s["status"] == "COMPLETE"}):
        serving.update(_serving(c, scope, today, cut))
    items = []
    for s in expired:
        h = _hold(c, s, today, cut, serving)
        if h:
            out["held"].append({"id": s["id"], "scope_key": s["scope_key"], "business_date": s["business_date"],
                                "status": s["status"], "n_rows": s["n_rows"], **h})
        else:
            items.append({k: s[k] for k in ("id", "scope_key", "data_source", "business_date", "first_target_date",
                                            "last_target_date", "status", "n_rows", "created_at")})
    d = out["delete"]
    d.update({"snapshots": len(items), "rows": sum(i["n_rows"] for i in items), "items": items,
              "first_business_date": items[0]["business_date"] if items else None,
              "last_business_date": items[-1]["business_date"] if items else None})
    for i in items:
        d["by_status"][i["status"]] = d["by_status"].get(i["status"], 0) + 1
    k = c.execute("SELECT COUNT(*), COALESCE(SUM(n_rows), 0), MIN(business_date) FROM forecast_eod_snapshots "
                  "WHERE business_date >= ?", (str(cut),)).fetchone()
    out["kept"] = {"snapshots": k[0], "rows": k[1], "first_business_date": k[2]}
    key = ",".join(sorted(f"{i['id']}:{i['status']}:{i['n_rows']}" for i in items))
    out["plan_id"] = hashlib.sha256(f"{cut}|{key}".encode()).hexdigest()[:16]
    out["apply_ready"] = schema >= SCHEMA and not out["refused"]
    return out


def dry_run(db_path: Path, today: date | None = None) -> dict:
    """Plan on a read-only connection (safe on the live database while the app runs, and on copies)."""
    c = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        return {"mode": "DRY_RUN", "database": str(db_path), **plan(c, today), "written": False}
    finally:
        c.close()


def _delete_one(item: dict, today: date, cut: date, run_id: str, backup_file: str, requested_by: str) -> dict:
    """One snapshot in ONE immediate transaction; every condition is checked again inside it."""
    sid = item["id"]
    with db.tx() as c:
        s = db.one(c, _EXPIRED + " AND s.id = ?", (str(cut), sid))
        if not s:
            done = db.one(c, "SELECT state FROM forecast_eod_snapshot_retention WHERE snapshot_id=?", (sid,))
            if done and done["state"] == "DELETED":
                return {"id": sid, "business_date": item["business_date"], "result": "ALREADY_DELETED", "rows": 0}
            raise db.ConsistencyError(f"{sid}: no longer an expired snapshot (business date >= {cut} or missing)")
        unknown = _unknown_references(c)
        if unknown:
            raise db.ConsistencyError(f"other table(s) reference forecast_eod_snapshots: {', '.join(unknown)}")
        h = _hold(c, s, today, cut)
        if h:
            raise db.ConsistencyError(f"{sid}: {h['code']} ({h['detail']})")
        hdr = db.one(c, "SELECT values_sha256, total_yhat, source_run_date FROM forecast_eod_snapshots WHERE id=?", (sid,))
        # the permit must be the LAST insert of this connection before the deletes (triggers: seq = last_insert_rowid());
        # a random 62-bit seq cannot be matched by an insert into another table
        seq = secrets.randbits(62) | (1 << 61)
        c.execute("INSERT INTO forecast_eod_snapshot_retention(seq, run_id, snapshot_id, scope_key, data_source, "
                  "business_date, first_target_date, last_target_date, snapshot_status, source_run_id, source_run_date, "
                  "n_rows, values_sha256, total_yhat, snapshot_created_at, policy_days, cutoff_date, state, requested_by, "
                  "backup_file, started_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'DELETING', ?,?,?)",
                  (seq, run_id, sid, s["scope_key"], s["data_source"], s["business_date"], s["first_target_date"],
                   s["last_target_date"], s["status"], s["source_run_id"], hdr["source_run_date"], s["n_rows"],
                   hdr["values_sha256"], hdr["total_yhat"], s["created_at"], POLICY_DAYS, str(cut), requested_by,
                   backup_file, now_iso()))
        nv = c.execute("DELETE FROM forecast_eod_snapshot_values WHERE snapshot_id=?", (sid,)).rowcount
        nh = c.execute("DELETE FROM forecast_eod_snapshots WHERE id=?", (sid,)).rowcount
        if nv != s["n_values"] or nh != 1:
            raise db.ConsistencyError(f"{sid}: deleted {nv} values / {nh} header, expected {s['n_values']} / 1")
        c.execute("UPDATE forecast_eod_snapshot_retention SET state='DELETED', rows_deleted=?, finished_at=? "
                  "WHERE snapshot_id=?", (nv, now_iso(), sid))
        left = c.execute("SELECT (SELECT COUNT(*) FROM forecast_eod_snapshot_values WHERE snapshot_id=?) + "
                         "(SELECT COUNT(*) FROM forecast_eod_snapshots WHERE id=?)", (sid, sid)).fetchone()[0]
        if left:
            raise db.ConsistencyError(f"{sid}: {left} row(s) still present after the deletion")
    return {"id": sid, "scope_key": s["scope_key"], "business_date": s["business_date"], "status": s["status"],
            "result": "DELETED", "rows": nv}


def apply(plan_id: str, today: date | None = None, requested_by: str = "CLI") -> dict:
    """Delete exactly the reviewed plan (see the module docstring). Raises AppError when refused (nothing written)."""
    today = today or today_vn()
    with db.read() as c:
        p = plan(c, today)
    if p["schema_version"] < SCHEMA:
        raise AppError("EOD_RETENTION_SCHEMA", 409, detail=f"database schema {p['schema_version']}, retention needs {SCHEMA}")
    if p["refused"]:
        raise AppError(p["refused"]["code"], 409, detail=p["refused"]["detail"])
    if not plan_id or plan_id != p["plan_id"]:
        raise AppError("EOD_RETENTION_PLAN_CHANGED", 409,
                       detail=f"reviewed plan {plan_id!r}, current plan {p['plan_id']!r}: run the dry run again")
    items = p["delete"]["items"]
    out = {"mode": "APPLY", **p, "run_id": None, "backup_file": None, "deleted": [], "error": None}
    if not items:
        return out
    from .backup import backup_database
    backup_file = str(backup_database(reason="pre-eod-retention"))      # verified (integrity_check) or it raises
    run_id = db.new_id("RET")
    started = now_iso()
    cut = date.fromisoformat(p["cutoff_date"])
    with db.tx() as c:      # recorded before the first deletion (a killed process still leaves this trace)
        db.audit(c, "EOD_SNAPSHOT_RETENTION_STARTED", "forecast_eod_snapshot_retention", run_id,
                 {"plan_id": plan_id, "cutoff_date": p["cutoff_date"], "planned_snapshots": len(items),
                  "planned_rows": p["delete"]["rows"], "backup_file": backup_file, "requested_by": requested_by})
    for it in items:
        try:
            out["deleted"].append(_delete_one(it, today, cut, run_id, backup_file, requested_by))
        except Exception as e:  # noqa: BLE001 - that snapshot was rolled back; recorded below, the run stops here
            out["error"] = {"snapshot_id": it["id"], "business_date": it["business_date"],
                            "error": f"{type(e).__name__}: {e}"[:500]}
            break
    done = [x for x in out["deleted"] if x["result"] == "DELETED"]
    summary = {"plan_id": plan_id, "cutoff_date": p["cutoff_date"], "policy_days": POLICY_DAYS,
               "planned_snapshots": len(items), "planned_rows": p["delete"]["rows"],
               "deleted_snapshots": len(done), "deleted_rows": sum(x["rows"] for x in done),
               "first_business_date": done[0]["business_date"] if done else None,
               "last_business_date": done[-1]["business_date"] if done else None,
               "backup_file": backup_file, "started_at": started, "finished_at": now_iso(), "error": out["error"],
               "requested_by": requested_by}
    with db.tx() as c:
        db.audit(c, "EOD_SNAPSHOT_RETENTION", "forecast_eod_snapshot_retention", run_id, summary)
        if out["error"]:
            db.alert(c, "ERROR", "EOD_RETENTION_FAILED", summary, "forecast_eod_snapshot_retention", run_id)
    log.info("eod snapshot retention", extra={"ctx": {k: summary[k] for k in (
        "plan_id", "planned_snapshots", "deleted_snapshots", "deleted_rows", "error")}})
    return {**out, "run_id": run_id, "backup_file": backup_file, "summary": summary}
