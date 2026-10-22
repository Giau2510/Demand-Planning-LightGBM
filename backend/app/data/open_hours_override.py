"""1.2.12: owner-approved ADHOC open-hours rule for SIX exact day x SKU x FC keys (owner decision, 21/10/2026).

The six keys are the only rows of the BIGQUERY source that stopped the training with OPEN_HOURS_INVALID (status
MULTI_ITEM, data/open_hours.py): two listings (item codes) of the SKU sold through the same FC that day carry different
total_open_hours and the source has no SKU x FC value. The owner approved, for exactly these keys and no other:

    representative total_open_hours = MAXIMUM of the valid listing-level values of that SKU x FC x day

Scope and safety:
* key = scope x business date x SKU x FC (the model grain). item_code is never part of the key: the listing codes below
  only label the evidence values;
* the stored data is never changed: demand_daily keeps the D-1 result as loaded (MULTI_ITEM, no value) and the D-1
  classification is unchanged, so any OTHER multi-listing, conflicting or missing key still stops the training (a new
  case needs its own owner decision; this is not a general rule);
* the value is applied when the training reads its window (ml/pipeline.train_and_publish) and recorded with the run
  (feature_decisions.open_hours.override: listing values, selected maximum, rule, version, reason, time) and in the
  audit log (OPEN_HOURS_OVERRIDE_APPLIED). A rebuilt panel of that run (promotion, explanations) applies the values
  recorded with the run, never the current list (data/demand.panel_for_run);
* checked at every use, never guessed: every listing value present, numeric, finite and within 0..24, at least two
  listings, the maximum computed here (not typed in); the stored row must still be MULTI_ITEM without a value, with the
  approved quantity and number of orders AND from the very D-1 load the evidence was verified against (APPROVED_LOADED_AT:
  the load that read the 07:10:38 snapshot; the listing values are not stored, so a reload of the day could carry other
  values - it needs a new read-only verification and approval). Otherwise the key is NOT overridden: its row keeps
  blocking with its reason in the OPEN_HOURS_INVALID detail. An approved key without a stored row (ROW_NOT_FOUND) gets
  nothing - there is no row to give a value, so nothing is guessed and nothing blocks - and is reported with the run
  (not_applied); the loaded frame is checked again when the value is applied (fill);
* reversible: removing a key (or emptying APPROVED_KEYS) in a later version restores the block; nothing stored needs a
  repair, and a version without this module (1.2.11) blocks the six keys again.
* 1.2.13 (owner rule restated 22/10/2026: the MAX applies to the six keys only "if the source values still match the
  recorded evidence"): a LATER load of a key is accepted when that load verified the source against the evidence before
  writing (verify_load, run on every D-1 load / backfill and stored with its run record in demand_sync_runs) - the same
  quantity and orders, every line with a value and an item code, as many items and distinct (item, value) pairs as
  approved listings and the same minimum and maximum (two listings: the pair of values is fully determined). A reload
  without such a record (e.g. written by an older version) or with different values keeps blocking. So a reload that
  changes nothing in the evidence (e.g. a full reload after a new column mapping) no longer needs a new approval.

Evidence: read-only BigQuery queries of 21/10/2026 on the table snapshot modified 2026-10-21 00:10:38 UTC (07:10:38
Vietnam time), the snapshot the stored rows were loaded from; reports/release-1.2.12-20261021/
OPEN_HOURS_OVERRIDE_EVIDENCE.xlsx.
"""
from __future__ import annotations

import json
import math
import sqlite3

from ..timeutil import now_iso
from .open_hours import MAX_HOURS, MIN_HOURS

RULE_ID = "OWNER_ADHOC_MAX_LISTING_OPEN_HOURS"
RULE_VERSION = "1.2.12"
VERIFY_VERSION = "1.2.13"           # per-load verification of the evidence (verify_load / verified_for)
APPROVED_ON = "2026-10-21"
REASON = ("MULTI_ITEM: the listings of the SKU sold through this FC that day have different open hours; owner-approved "
          "adhoc rule for this key only: maximum of the valid listing-level values")
SCOPE_KEY = "BIGQUERY:lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm"
SOURCE_SNAPSHOT = "2026-10-21T00:10:38.658000+00:00"
# demand_daily.loaded_at of the six rows = backfill JOB-20261021052939-2D9CCE, which read that same source snapshot
APPROVED_LOADED_AT = "2026-10-21T05:36:47+00:00"
STATUS = "MULTI_ITEM"              # the stored status the approval was made for

# (business date, sku_code, fc_code, approved qty, approved orders, {listing item_code: listing total_open_hours})
APPROVED_KEYS = (
    ("2026-02-09", "MEDX.DMTS-HOA-BAO-002", "HN", 8.0, 4,
     {"MEDX.DMTS-HOA-BAO-002.1": 23.92, "MEDX.DMTS-HOA-BAO-002.2": 24.0}),
    ("2026-02-10", "MEDX.2LJ61PGE", "HN", 11.0, 2, {"MEDX.2LJ61PGE.1": 21.16, "MEDX.2LJ61PGE.3": 24.0}),
    ("2026-03-02", "MEDX.DMTS-STA-LOS-002", "BD", 88.0, 18,
     {"MEDX.DMTS-STA-LOS-002.1": 5.0, "MEDX.DMTS-STA-LOS-002.2": 24.0}),
    ("2026-03-02", "MEDX.SOP-NEO-001", "BD", 3.0, 3, {"MEDX.SOP-NEO-001.1": 1.7, "MEDX.SOP-NEO-001.2": 24.0}),
    ("2026-08-26", "MEDX.COU-STR-001", "BD", 42.0, 8, {"MEDX.COU-STR-001.1": 23.72, "MEDX.COU-STR-001.2": 24.0}),
    ("2026-08-26", "MEDX.D6TABCV8", "BD", 4.0, 4, {"MEDX.D6TABCV8.1": 22.85, "MEDX.D6TABCV8.2": 18.22}),
)


def listing_max(values) -> tuple[float | None, str | None]:
    """(maximum, None) when every listing-level value is present, numeric, finite and within MIN_HOURS..MAX_HOURS and
    there are at least two listings (the case the rule was approved for); (None, reason) otherwise - never a guess."""
    vals = list(values.values()) if isinstance(values, dict) else list(values or [])
    if len(vals) < 2:
        return None, "FEWER_THAN_TWO_LISTINGS"
    out = []
    for v in vals:
        if v is None:
            return None, "LISTING_VALUE_MISSING"
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None, "LISTING_VALUE_NOT_NUMERIC"
        v = float(v)
        if not math.isfinite(v):
            return None, "LISTING_VALUE_NOT_FINITE"
        if v < MIN_HOURS or v > MAX_HOURS:
            return None, "LISTING_VALUE_OUT_OF_RANGE"
        out.append(v)
    return max(out), None


def approved() -> list[dict]:
    """The approved keys with their listing values, the computed maximum and the validation of the values."""
    recs = []
    for d, sku, fc, qty, orders, listings in APPROVED_KEYS:
        mx, why = listing_max(listings)
        recs.append({"business_date": d, "sku_id": sku, "fc_id": fc, "approved_qty": qty, "approved_orders": orders,
                     "listings": [{"item_code": k, "total_open_hours": v} for k, v in listings.items()],
                     "selected_hours": mx, "invalid_reason": why})
    return recs


def resolve(conn, scope_key: str, start: str, end: str) -> dict:
    """Which approved keys apply to the stored rows of [start, end] of a scope (read-only, one primary-key read per key).
    applied: the stored row exists, is still MULTI_ITEM without a value, has the approved quantity, number of orders and
    load, and its listing values are valid. Every other approved key is listed in not_applied with its reason:
    NOT_IN_WINDOW / ROW_NOT_FOUND (no such row in the model input: nothing to give a value) and STORED_STATUS_OK (the
    source now gives one value: nothing to replace) do not block; every other reason leaves the stored row blocking
    (it is still MULTI_ITEM or another not-OK status, counted by window_check)."""
    out = {"rule": RULE_ID, "version": RULE_VERSION, "approved_on": APPROVED_ON, "reason": REASON,
           "source_snapshot": SOURCE_SNAPSHOT, "approved_loaded_at": APPROVED_LOADED_AT, "scope_key": scope_key,
           "applies_to_scope": scope_key == SCOPE_KEY, "window": [start, end], "checked_at": now_iso(),
           "applied": [], "not_applied": []}
    if scope_key != SCOPE_KEY:
        return out
    for rec in approved():
        rec = dict(rec)
        why = None
        if not (start <= rec["business_date"] <= end):
            why = "NOT_IN_WINDOW"
        else:
            r = conn.execute("SELECT open_hours, open_hours_status, qty, n_orders, loaded_at FROM demand_daily "
                             "WHERE scope_key=? AND order_date=? AND sku_id=? AND fc_id=?",
                             (scope_key, rec["business_date"], rec["sku_id"], rec["fc_id"])).fetchone()
            if r is not None:
                rec["stored"] = {"open_hours": r[0], "open_hours_status": r[1], "qty": r[2], "n_orders": r[3],
                                 "loaded_at": r[4]}
            if r is None:
                why = "ROW_NOT_FOUND"
            elif rec["invalid_reason"]:
                why = rec["invalid_reason"]
            elif r[1] != STATUS:
                why = "STORED_STATUS_" + str(r[1] or "NOT_LOADED")      # e.g. OK: the source now gives one value
            elif r[0] is not None:
                why = "VALUE_ALREADY_STORED"
            elif r[2] is None or abs(float(r[2]) - rec["approved_qty"]) > 1e-9 or int(r[3] or 0) != rec["approved_orders"]:
                why = "CONTENT_CHANGED"
            elif r[4] != APPROVED_LOADED_AT:
                # 1.2.13: a later load counts only through the verification it recorded before writing the row
                v = verified_for(conn, scope_key, r[4], rec)
                if v is None:
                    why = "RELOADED_SINCE_APPROVAL"     # no verification of the evidence for the load that wrote the row
                elif not v["match"]:
                    why = v.get("reason") or "LISTING_VALUES_CHANGED"
                else:
                    rec["verified_by_load"] = {"run_id": v["run_id"], "loaded_at": r[4],
                                               "source_version": v.get("source_version")}
        if why:
            out["not_applied"].append({**rec, "not_applied_reason": why})
        else:
            out["applied"].append(rec)
    return out


def _expected(rec: dict) -> dict:
    """What the source aggregate of a load (connector._daily_sql) must show for an approved key: the approved quantity
    and orders, every line with a value and an item code, one distinct (item, value) pair per approved listing and the
    approved minimum / maximum."""
    vals = [float(x["total_open_hours"]) for x in rec["listings"]]
    return {"qty": float(rec["approved_qty"]), "n_orders": int(rec["approved_orders"]), "hours_null_rows": 0,
            "hours_no_item_rows": 0, "hours_items": len(vals), "hours_item_values": len(vals),
            "hours_min": min(vals), "hours_max": max(vals)}


def _num(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def verify_load(scope_key: str, rows, start: str, end: str) -> dict | None:
    """1.2.13: compare, BEFORE a load / backfill writes, the source aggregate of every approved key inside [start, end]
    with the recorded evidence. Returns the record stored with the run (None for any other scope): per key `match`, the
    reason (ROW_NOT_FOUND / CONTENT_CHANGED / LISTING_VALUES_CHANGED) and the observed values. Read-only; no query."""
    if scope_key != SCOPE_KEY:
        return None
    want = {(r["business_date"], r["sku_id"], r["fc_id"]): r for r in approved() if start <= r["business_date"] <= end}
    out = {"rule": RULE_ID, "verify_version": VERIFY_VERSION, "checked_at": now_iso(), "window": [start, end], "keys": []}
    if not want:
        return out
    found = {}
    for r in rows:
        k = (str(r.get("order_date"))[:10], str(r.get("sku_id")), str(r.get("fc_id")))
        if k in want:
            found[k] = r
    for k, rec in want.items():
        exp, r = _expected(rec), found.get(k)
        if r is None:
            out["keys"].append({"key": list(k), "match": False, "reason": "ROW_NOT_FOUND", "expected": exp})
            continue
        got = {"qty": _num(r.get("qty")), "n_orders": _num(r.get("n_orders")),
               "hours_null_rows": _num(r.get("open_hours_null_rows")), "hours_no_item_rows": _num(r.get("open_hours_no_item_rows")),
               "hours_items": _num(r.get("open_hours_items")), "hours_item_values": _num(r.get("open_hours_item_values")),
               "hours_min": _num(r.get("open_hours_min")), "hours_max": _num(r.get("open_hours_max"))}
        diff = sorted(n for n in exp if got[n] is None or abs(got[n] - float(exp[n])) > 1e-9)
        reason = None if not diff else ("CONTENT_CHANGED" if set(diff) <= {"qty", "n_orders"} else "LISTING_VALUES_CHANGED")
        out["keys"].append({"key": list(k), "match": not diff, "reason": reason, "differs": diff, "observed": got})
    return out


def verified_for(conn, scope_key: str, loaded_at: str | None, rec: dict) -> dict | None:
    """1.2.13: the verification recorded by the load that wrote the stored row (its loaded_at = the run's finished_at);
    None when there is none (a row written by an older version, a schema without run records). A load that was rolled
    back still counts for a row that carries its loaded_at: the rollback restored every row it changed, so such a row
    has the content it had before and that load verified the evidence against it."""
    if not loaded_at:
        return None
    try:
        runs = conn.execute("SELECT id, source_version, summary_json FROM demand_sync_runs WHERE scope_key=? AND "
                            "finished_at=? AND status IN ('COMMITTED', 'ROLLED_BACK') AND kind IN ('D1_SYNC', 'BACKFILL') "
                            "ORDER BY rowid DESC", (scope_key, loaded_at)).fetchall()
    except sqlite3.OperationalError:
        return None
    key = [rec["business_date"], rec["sku_id"], rec["fc_id"]]
    for run_id, version, sj in runs:
        try:
            ver = (json.loads(sj or "{}") or {}).get("open_hours_override") or {}
        except (TypeError, ValueError):
            continue
        for k in ver.get("keys") or []:
            if k.get("key") == key:
                return {"run_id": run_id, "source_version": version, "match": bool(k.get("match")), "reason": k.get("reason")}
    return None


def summary(res: dict | None) -> dict | None:
    """What a blocking detail / status page shows: rule, counts and the keys not applied with their reason."""
    if not res:
        return None
    return {"rule": res["rule"], "version": res["version"], "applies_to_scope": res["applies_to_scope"],
            "applied": len(res["applied"]),
            "applied_keys": [[a["business_date"], a["sku_id"], a["fc_id"], a["selected_hours"]] for a in res["applied"]],
            "not_applied": [[a["business_date"], a["sku_id"], a["fc_id"], a["not_applied_reason"]]
                            for a in res["not_applied"]]}


def fill(demand, applied: list[dict]):
    """(demand with the approved value on exactly the row of each applied key, problems). The frame is the one the
    training loaded (pipeline) or rebuilds (panel_for_run); stored data is never written. Checked again on the frame
    itself (a load may have run since resolve): the row is found exactly once, has no value, the approved quantity and
    number of orders, and the value is the valid maximum of the recorded listing values. Otherwise the key is a problem
    and gets nothing (the training then stops)."""
    problems = []
    if not applied or demand is None or demand.empty:
        return demand, ([] if not applied else [{"key": "ALL", "reason": "NO_DEMAND_ROWS"}])
    od = demand["order_date"]
    if od.dtype != object:                      # load_demand gives the stored TEXT 'YYYY-MM-DD' (compared as is)
        od = od.astype(str).str[:10]
    for a in applied:
        key = [a["business_date"], a["sku_id"], a["fc_id"]]
        m = (od == a["business_date"]) & (demand["sku_id"] == a["sku_id"]) & (demand["fc_id"] == a["fc_id"])
        n = int(m.sum())
        mx, why = listing_max({x["item_code"]: x["total_open_hours"] for x in a.get("listings") or []})
        if n != 1:
            problems.append({"key": key, "reason": f"ROWS_FOUND_{n}"})
        elif why or mx != a.get("selected_hours"):
            problems.append({"key": key, "reason": why or "SELECTED_VALUE_NOT_THE_MAXIMUM"})
        elif demand.loc[m, "open_hours"].notna().any():
            problems.append({"key": key, "reason": "VALUE_ALREADY_PRESENT"})
        elif (abs(float(demand.loc[m, "qty"].iloc[0]) - float(a["approved_qty"])) > 1e-9
              or int(demand.loc[m, "n_orders"].iloc[0] or 0) != int(a["approved_orders"])):
            problems.append({"key": key, "reason": "CONTENT_CHANGED_AT_LOAD"})
        else:
            demand.loc[m, "open_hours"] = float(mx)
    return demand, problems


def recorded(tr: dict | None) -> list[dict]:
    """The keys an override gave a value in a stored training run (feature_config_json), [] for every other run."""
    try:
        fc = json.loads((tr or {}).get("feature_config_json") or "{}")
        ov = ((fc.get("feature_decisions") or {}).get("open_hours") or {}).get("override") or {}
        return list(ov.get("applied") or [])
    except (TypeError, ValueError, AttributeError):
        return []


def audit_details(res: dict) -> dict:
    """Audit record of one application: rule, version, reason, time, and per key the listing values and the maximum."""
    return {"rule": res["rule"], "version": res["version"], "approved_on": res["approved_on"], "reason": res["reason"],
            "source_snapshot": res["source_snapshot"], "applied_at": res["checked_at"], "scope_key": res["scope_key"],
            "keys": [{"business_date": a["business_date"], "sku_id": a["sku_id"], "fc_id": a["fc_id"],
                      "listings": a["listings"], "selected_hours": a["selected_hours"]} for a in res["applied"]],
            "not_applied": [[a["business_date"], a["sku_id"], a["fc_id"], a["not_applied_reason"]]
                            for a in res["not_applied"]]}
