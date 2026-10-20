"""Finalized (frozen) actual of a business day (1.2.9, seventh batch; owner rule 20/10/2026). Full description in
docs/LICH-SU-FORECAST.md section 15; storage: migration 0009.

  rule         the actual of a completed Vietnam business day T is FINALIZED from the successful D-1 load that wrote T's
               rows, and never changes afterwards. A D-1 load writes the whole days of its window in one transaction
               with one `loaded_at` (= its `synced_at`) and its audit `D1_SYNC` in the same transaction, so the stored
               rows of T name exactly one load. T is finalized only when:
                 - T is before today (Vietnam): the day is over (today and future days are never finalized);
                 - every stored row of T carries the same loaded_at, and an audit D1_SYNC of this scope has exactly that
                   synced_at (a committed, verified load: completion signal, fallback time + row-count sufficiency check,
                   or a backfill with its READY preview - the existing D-1 rules; a failed D-1 commits nothing);
                 - that load's window covers T and the load ran after T ended (its Vietnam date is after T);
                 - every row has a SKU, an FC and a quantity >= 0.
               Otherwise the day is BLOCKED with the reason (kept until a later load makes it eligible; a BLOCKED day
               shows the live actual as before, never as final). A day without any stored row is not a candidate (the
               history shows "no actual data", never 0).
  frozen       FINALIZED copies the day's SKU x FC rows (quantity, order count) with the load's provenance, the row
               count, total and sha256, in ONE immediate transaction per day: the values are checked against the header
               (and against demand_daily) before the header is sealed, else the whole day rolls back. Sealed = immutable
               (triggers): a later reload, correction, cancellation, missing key or reimport never changes it, and it
               never goes back to provisional. A correction of a finalized day is out of scope (it would need its own
               explicit, audited workflow).
  idempotent   a FINALIZED day is never evaluated again; re-running with the same data writes nothing (a BLOCKED day is
               rewritten only when its reason or load changed); a failed day is retried at the next run (after the next
               D-1 load, or `python -m app.cli actual-finalize --apply`).
  scope        BIGQUERY only (the D-1 source). DEMO / Excel data have no D-1 load and keep their existing status.
Finalization never writes demand_daily, a forecast, the D+1 history or the 23:59 close, and never calls BigQuery.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date

from . import db
from .timeutil import VN_TZ, now_iso, parse_iso, today_vn

log = logging.getLogger("df.final")

FINALIZED, BLOCKED = "FINALIZED", "BLOCKED"
TIMEZONE = "Asia/Ho_Chi_Minh"
ELIGIBLE_MODES = ("SIGNAL", "FALLBACK_TIME_VERIFIED", "BACKFILL")
PROVENANCE = ("load_id", "job_id", "synced_at", "mode", "backfill", "full_reload", "window_start", "window_end",
              "watermark", "mapping_hash", "preview_id")


def _sha(rows: list[tuple]) -> str:
    """sha256 of the sorted 'sku|fc|qty' lines (same form as actual_close._sha)."""
    return hashlib.sha256("\n".join(sorted(f"{s}|{f}|{float(q)!r}" for s, f, q, _n in rows)).encode()).hexdigest()


def _vn_date(ts: str) -> date:
    return parse_iso(ts).astimezone(VN_TZ).date()


def d1_loads(c, scope_key: str) -> dict[str, dict]:
    """Committed D-1 loads of the scope by synced_at (audit D1_SYNC, written in the load's own transaction). Entries
    without synced_at (older test fixtures, other writers) cannot be matched and are ignored; two entries with the same
    synced_at but different load ids are ambiguous and marked so."""
    out: dict[str, dict] = {}
    for (dj,) in c.execute("SELECT details_json FROM audit_log WHERE action='D1_SYNC' AND entity_id=? ORDER BY id",
                           (scope_key,)):
        try:
            d = json.loads(dj or "{}")
        except ValueError:
            continue
        at = d.get("synced_at")
        if not at:
            continue
        if at in out and out[at].get("load_id") != d.get("load_id"):
            out[at]["ambiguous"] = True
            continue
        out[at] = {k: d.get(k) for k in PROVENANCE}
    return out


def _eligibility(day: str, groups: list[tuple], loads: dict) -> tuple[str, dict | None]:
    """(reason, load) for one day; reason 'OK' = can be finalized."""
    if len(groups) != 1:
        return "MIXED_LOADS", None
    loaded_at, _n, _tot, bad, _orders = groups[0]
    ld = loads.get(loaded_at)
    if not ld:
        return "NO_VERIFIED_D1_LOAD", None
    if ld.get("ambiguous"):
        return "AMBIGUOUS_D1_LOAD", ld
    if ld.get("mode") not in ELIGIBLE_MODES:
        return "D1_MODE_NOT_ELIGIBLE", ld
    if not (ld.get("window_start") and ld.get("window_end") and ld["window_start"] <= day <= ld["window_end"]):
        return "LOAD_WINDOW_DOES_NOT_COVER_DAY", ld
    if _vn_date(loaded_at) <= date.fromisoformat(day):
        return "LOADED_BEFORE_DAY_ENDED", ld
    if bad:
        return "INVALID_ROWS", ld
    return "OK", ld


def plan(c, scope_key: str, data_source: str | None, today: date | None = None) -> dict:
    """Read-only: every stored business day of the scope that is not FINALIZED yet, with the decision a run would take
    now (FINALIZE + the load, or BLOCK + reason). Days of today or later are not listed (never finalized)."""
    today = today or today_vn()
    if data_source != "BIGQUERY":
        return {"applicable": False, "reason": "NOT_A_D1_SOURCE", "scope_key": scope_key, "items": []}
    has_table = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='actual_finals'").fetchone()
    # a database before migration 0009 (dry run of the upgrade impact) has nothing finalized yet
    done = {d: (st, r) for d, st, r in c.execute("SELECT business_date, status, reason FROM actual_finals "
                                                 "WHERE scope_key=?", (scope_key,))} if has_table else {}
    # the stored days from the key index (cheap), then the aggregates of the days NOT finalized yet only - once the
    # history is finalized, a run after each D-1 looks at the few new days instead of every row of the scope
    days = [d for (d,) in c.execute("SELECT DISTINCT order_date FROM demand_daily WHERE scope_key=? AND order_date < ?",
                                    (scope_key, str(today)))]
    by_day: dict[str, list[tuple]] = {}
    for d in days:
        if done.get(d, ("",))[0] == FINALIZED:
            continue
        by_day[d] = [tuple(r) for r in c.execute(
            "SELECT loaded_at, COUNT(*), TOTAL(qty), SUM(qty IS NULL OR qty < 0 OR sku_id IS NULL OR fc_id IS NULL), "
            "SUM(n_orders) FROM demand_daily WHERE scope_key=? AND order_date=? GROUP BY loaded_at", (scope_key, d))]
    loads = d1_loads(c, scope_key)
    items = []
    for day in sorted(by_day):
        g = by_day[day]
        reason, ld = _eligibility(day, g, loads)
        items.append({"business_date": day, "decision": "FINALIZE" if reason == "OK" else "BLOCK",
                      "reason": "D1_LOAD" if reason == "OK" else reason, "loaded_at": g[0][0] if len(g) == 1 else None,
                      "rows": sum(x[1] for x in g), "total_qty": sum(x[2] for x in g), "load": ld,
                      "previous": {"status": done[day][0], "reason": done[day][1]} if day in done else None})
    return {"applicable": True, "scope_key": scope_key, "today": str(today),
            "finalized_days": sum(1 for v in done.values() if v[0] == FINALIZED),
            "to_finalize": sum(1 for i in items if i["decision"] == "FINALIZE"),
            "to_block": sum(1 for i in items if i["decision"] == "BLOCK"),
            "blocked_by_reason": _count(i["reason"] for i in items if i["decision"] == "BLOCK"), "items": items}


def _count(xs) -> dict:
    out: dict = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def _header(c, scope_key: str, day: str) -> dict | None:
    return db.one(c, "SELECT * FROM actual_finals WHERE scope_key=? AND business_date=?", (scope_key, day))


def _prov(ld: dict | None) -> dict:
    ld = ld or {}
    return {"d1_load_id": ld.get("load_id"), "d1_job_id": ld.get("job_id"), "d1_synced_at": ld.get("synced_at"),
            "d1_mode": ld.get("mode"), "d1_backfill": None if ld.get("backfill") is None else int(bool(ld["backfill"])),
            "d1_full_reload": None if ld.get("full_reload") is None else int(bool(ld["full_reload"])),
            "d1_window_start": ld.get("window_start"), "d1_window_end": ld.get("window_end"),
            "d1_watermark": ld.get("watermark"), "d1_mapping_hash": ld.get("mapping_hash"),
            "d1_preview_id": ld.get("preview_id")}


def _finalize_day(c, scope_key: str, data_source: str, item: dict, today: date, by: str, job_id: str | None) -> dict:
    """Inside ONE immediate transaction: re-check under the write lock, write header + values, check, seal."""
    day = item["business_date"]
    have = _header(c, scope_key, day)
    if have and have["status"] == FINALIZED:
        return {"business_date": day, "result": "ALREADY_FINALIZED", "id": have["id"]}
    groups = [tuple(r) for r in c.execute(
        "SELECT loaded_at, COUNT(*), TOTAL(qty), SUM(qty IS NULL OR qty < 0 OR sku_id IS NULL OR fc_id IS NULL), "
        "SUM(n_orders) FROM demand_daily WHERE scope_key=? AND order_date=? GROUP BY loaded_at", (scope_key, day))]
    reason, ld = _eligibility(day, groups, d1_loads(c, scope_key))
    if reason != "OK" or groups[0][0] != item["loaded_at"] or day >= str(today):
        return {"business_date": day, "result": "CHANGED_SINCE_PLAN", "reason": reason}     # the next run decides
    rows = [tuple(r) for r in c.execute("SELECT sku_id, fc_id, qty, n_orders FROM demand_daily WHERE scope_key=? AND "
                                        "order_date=? ORDER BY sku_id, fc_id", (scope_key, day))]
    total = float(sum(r[2] for r in rows))
    orders = sum(int(r[3] or 0) for r in rows)
    at = now_iso()
    head = {"status": FINALIZED, "reason": "D1_LOAD", **_prov(ld), "n_rows": len(rows), "total_qty": total,
            "total_orders": orders, "values_sha256": _sha(rows), "timezone": TIMEZONE, "finalized_by": by,
            "job_id": job_id, "last_attempt_at": at, "finalized_at": at}
    if have:                    # a BLOCKED day becomes FINALIZED (the only transition the triggers allow)
        fid = have["id"]
        c.execute(f"UPDATE actual_finals SET {', '.join(f'{k}=?' for k in head)}, attempts = attempts + 1 WHERE id=?",
                  (*head.values(), fid))
    else:
        fid = db.new_id("AFN")
        row = {"id": fid, "scope_key": scope_key, "data_source": data_source, "business_date": day, **head,
               "attempts": 1, "first_attempt_at": at}
        c.execute(f"INSERT INTO actual_finals({', '.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
    c.executemany("INSERT INTO actual_final_values(final_id, sku_id, fc_id, qty, n_orders) VALUES (?,?,?,?,?)",
                  [(fid, s, f, float(q), None if n is None else int(n)) for s, f, q, n in rows])
    chk = c.execute("SELECT COUNT(*), TOTAL(qty) FROM actual_final_values WHERE final_id=?", (fid,)).fetchone()
    if chk[0] != len(rows) or abs(chk[1] - total) > 1e-6 * max(1.0, abs(total)) or chk[0] != groups[0][1]:
        raise RuntimeError(f"ACTUAL_FINAL_VERIFY_FAILED {day}: {chk[0]} rows / {chk[1]} vs {len(rows)} / {total}")
    c.execute("UPDATE actual_finals SET sealed = 1 WHERE id=?", (fid,))       # trigger re-checks count and total
    db.audit(c, "ACTUAL_FINALIZED", "actual_final", fid,
             {"scope_key": scope_key, "business_date": day, "n_rows": len(rows), "total_qty": total,
              "d1_load_id": head["d1_load_id"], "d1_synced_at": head["d1_synced_at"], "d1_mode": head["d1_mode"],
              "finalized_by": by, "was_blocked": bool(have)})
    return {"business_date": day, "result": FINALIZED, "id": fid, "n_rows": len(rows), "total_qty": total}


def _block_day(c, scope_key: str, data_source: str, item: dict, by: str, job_id: str | None) -> dict:
    """Record why the day is not finalized. Unchanged reason and load -> nothing written (idempotent)."""
    day = item["business_date"]
    have = _header(c, scope_key, day)
    if have and have["status"] == FINALIZED:
        return {"business_date": day, "result": "ALREADY_FINALIZED", "id": have["id"]}
    prov = _prov(item.get("load"))
    if have and have["reason"] == item["reason"] and have["d1_synced_at"] == (item.get("loaded_at") or prov["d1_synced_at"]):
        return {"business_date": day, "result": "UNCHANGED", "id": have["id"], "reason": item["reason"]}
    at = now_iso()
    head = {"status": BLOCKED, "reason": item["reason"], **prov,
            "d1_synced_at": item.get("loaded_at") or prov["d1_synced_at"], "n_rows": item["rows"],
            "total_qty": item["total_qty"], "timezone": TIMEZONE, "finalized_by": by, "job_id": job_id,
            "last_attempt_at": at}
    if have:
        fid = have["id"]
        c.execute(f"UPDATE actual_finals SET {', '.join(f'{k}=?' for k in head)}, attempts = attempts + 1 WHERE id=?",
                  (*head.values(), fid))
    else:
        fid = db.new_id("AFN")
        row = {"id": fid, "scope_key": scope_key, "data_source": data_source, "business_date": day, **head,
               "attempts": 1, "first_attempt_at": at}
        c.execute(f"INSERT INTO actual_finals({', '.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
    db.audit(c, "ACTUAL_FINALIZATION_BLOCKED", "actual_final", fid,
             {"scope_key": scope_key, "business_date": day, "reason": item["reason"], "rows": item["rows"]})
    return {"business_date": day, "result": BLOCKED, "id": fid, "reason": item["reason"]}


def finalize(scope_key: str, data_source: str | None, today: date | None = None, by: str = "AFTER_D1",
             job_id: str | None = None) -> dict:
    """Finalize every eligible day (one transaction per day) and record the blocked ones. A day that fails is rolled
    back alone, reported and retried at the next run; the others go on."""
    today = today or today_vn()
    with db.read() as c:
        p = plan(c, scope_key, data_source, today)
    out = {"applicable": p["applicable"], "scope_key": scope_key, "finalized": [], "blocked": [], "unchanged": 0,
           "skipped": [], "errors": []}
    for item in p["items"]:
        try:
            with db.tx() as c:
                res = (_finalize_day(c, scope_key, data_source, item, today, by, job_id) if item["decision"] == "FINALIZE"
                       else _block_day(c, scope_key, data_source, item, by, job_id))
        except Exception as e:  # noqa: BLE001 - one day never stops the others; it rolled back and is retried later
            log.warning("actual not finalized", exc_info=True, extra={"ctx": {"business_date": item["business_date"]}})
            out["errors"].append({"business_date": item["business_date"], "error": f"{type(e).__name__}: {e}"[:300]})
            continue
        if res["result"] == FINALIZED:
            out["finalized"].append({k: res[k] for k in ("business_date", "id", "n_rows", "total_qty")})
        elif res["result"] == BLOCKED:
            out["blocked"].append({k: res[k] for k in ("business_date", "reason")})
        elif res["result"] == "UNCHANGED":
            out["unchanged"] += 1
        else:
            out["skipped"].append(res)
    if out["errors"]:
        with db.tx() as c:
            db.alert(c, "ERROR", "ACTUAL_FINALIZE_FAILED", {"scope_key": scope_key, "days": out["errors"][:20],
                                                            "count": len(out["errors"])}, "scope", scope_key)
    log.info("actual finalization", extra={"ctx": {"scope_key": scope_key, "finalized": len(out["finalized"]),
                                                   "blocked": len(out["blocked"]), "errors": len(out["errors"])}})
    return out


def finalize_quietly(scope_key: str, data_source: str, context: str, job_id: str | None = None) -> dict | None:
    """After a successful D-1 load (after its commit): never fails the load; a failure is logged, alerted and retried
    by the next run."""
    try:
        return finalize(scope_key, data_source, by="AFTER_D1", job_id=job_id)
    except Exception as e:  # noqa: BLE001
        log.warning("actual finalization failed", exc_info=True, extra={"ctx": {"context": context}})
        try:
            with db.tx() as c:
                db.alert(c, "ERROR", "ACTUAL_FINALIZE_FAILED", {"scope_key": scope_key, "context": context,
                                                                "error": f"{type(e).__name__}: {e}"[:500]},
                         "scope", scope_key)
        except Exception:  # noqa: BLE001
            log.exception("finalization alert not written")
        return None


def d1_scopes(c) -> list[str]:
    return [r[0] for r in c.execute("SELECT DISTINCT scope_key FROM demand_daily WHERE data_source='BIGQUERY' "
                                    "ORDER BY scope_key")]


def dry_run(db_path, today: date | None = None, items: bool = True) -> dict:
    """Read-only plan of every BIGQUERY scope of a database file (opened mode=ro; works before migration 0009 too,
    to measure the upgrade impact). Nothing is written."""
    import sqlite3
    from pathlib import Path
    c = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        out = {"db": str(db_path), "scopes": []}
        for sk in d1_scopes(c):
            p = plan(c, sk, "BIGQUERY", today)
            if not items:
                p = {k: v for k, v in p.items() if k != "items"}
            else:
                p["items"] = [{k: i[k] for k in ("business_date", "decision", "reason", "rows", "total_qty")}
                              | {"d1_load_id": (i["load"] or {}).get("load_id"), "d1_mode": (i["load"] or {}).get("mode"),
                                 "d1_synced_at": i["loaded_at"]} for i in p["items"]]
            out["scopes"].append(p)
        return out
    finally:
        c.close()


def finals(c, scope_key: str, days: list[str]) -> dict[str, dict]:
    """Headers (FINALIZED and BLOCKED) of the given days."""
    if not days:
        return {}
    return {r["business_date"]: r for r in db.rows(
        c, f"SELECT * FROM actual_finals WHERE scope_key=? AND business_date IN ({','.join('?' * len(days))})",
        (scope_key, *days))}


def summary(c, scope_key: str | None) -> dict:
    """Counts for the history overview: finalized / blocked days, the newest finalized day."""
    if not scope_key:
        return {"finalized_days": 0, "blocked_days": 0, "last_finalized_date": None}
    r = c.execute("SELECT SUM(status='FINALIZED' AND sealed=1), SUM(status='BLOCKED'), "
                  "MAX(CASE WHEN status='FINALIZED' AND sealed=1 THEN business_date END) FROM actual_finals "
                  "WHERE scope_key=?", (scope_key,)).fetchone()
    return {"finalized_days": r[0] or 0, "blocked_days": r[1] or 0, "last_finalized_date": r[2]}
