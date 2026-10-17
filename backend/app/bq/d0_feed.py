"""1.2.1: the D-0 feed (today, intraday) - its own mapping, BigQuery validation, query and readiness.

D-0 has ONE purpose: compare today's actual demand per SKU x FC (cumulative up to the read) with the published
forecast. It is never history: nothing is written to demand_daily, it never enters a backtest or a training, and its
output does NOT have to look like the D-1 table. The feed reads only the fields of `bigquery.d0_mapping`:
  sku_id, fc_id, order_qty   essential
  order_date | created_at    the day of the line (DATE / DATETIME, or a TIMESTAMP converted to the Vietnam day)
  order_id                   optional, part of the default unique key
  source_updated_at          optional, freshness of the source
Any other output column is ignored: a D-0 SQL / table may have fewer, more or differently named columns than D-1.

Validating a SQL version is a real BigQuery round trip: dry run (syntax, permission, referenced tables, statement type,
cost), output schema against the D-0 mapping (column present with a compatible type, key columns present), then the
real aggregate query of TODAY (Vietnam) with nothing written. The validation records the SQL sha256 and the D-0
mapping hash; when the mapping or the key columns change, the version is stale (D0_REVALIDATE_REQUIRED) - a validated
status is never carried over to content that changed. TABLE mode applies the same rules to the D-0 table's metadata.
Rows of another day are never counted for today (OTHER_DAY, reported); a failing D-0 never falls back to the D-1 table.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

from .. import settings_service as ss
from ..messages import AppError, msg
from ..timeutil import now_iso, today_vn
from . import sql_guard

TEXTISH = {"STRING", "INT64", "INTEGER"}
NUMERIC = {"INT64", "INTEGER", "FLOAT64", "FLOAT", "NUMERIC", "BIGNUMERIC"}
COMPATIBLE = {"sku_id": TEXTISH, "fc_id": TEXTISH, "order_qty": NUMERIC, "order_date": {"DATE", "DATETIME"},
              "created_at": {"TIMESTAMP", "DATETIME"}, "order_id": TEXTISH, "source_updated_at": {"TIMESTAMP", "DATETIME"}}
VN = "Asia/Ho_Chi_Minh"
_REASON = ("CASE WHEN _d IS NULL THEN 'NULL_DATE' WHEN _d != @day THEN 'OTHER_DAY' WHEN sku_id IS NULL THEN 'NULL_SKU' "
           "WHEN fc_id IS NULL THEN 'NULL_FC' WHEN order_qty IS NULL THEN 'NULL_TARGET' "
           "WHEN order_qty < 0 THEN 'NEGATIVE_TARGET' END")


# ------------------------------------------------------------------ mapping
def used(bq) -> dict[str, str]:
    """D-0 field -> output column, for the mapped fields only."""
    return {f: m.column for f, m in bq.d0_mapping.items() if m.column and m.usage != "UNUSED"}


def date_field(mapping: dict[str, str]) -> str | None:
    return "order_date" if "order_date" in mapping else ("created_at" if "created_at" in mapping else None)


def missing_fields(bq) -> list[str]:
    u = used(bq)
    out = [f for f in ss.D0_ESSENTIAL if f not in u]
    if date_field(u) is None:
        out.append("order_date|created_at")
    return out


def key_columns(src, bq) -> list[str]:
    """Candidate unique key of the D-0 output: the user's list, else order / SKU / FC / day of the D-0 mapping."""
    if src.key_columns:
        return list(src.key_columns)
    u = used(bq)
    out: list[str] = []
    for f in ("order_id", "sku_id", "fc_id", date_field(u)):
        if f and u.get(f) and u[f] not in out:
            out.append(u[f])
    return out


def mapping_hash(bq=None, src=None, conn=None) -> str:
    """Identity of what a D-0 validation proved: the mapped columns and the key columns (not the policies)."""
    bq = bq or ss.get("bigquery", conn)
    src = src or ss.get("sql_sources", conn).d0
    key = {"mapping": used(bq), "key_columns": key_columns(src, bq)}
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def check_columns(columns: list[dict], bq, keys: list[str]) -> dict:
    """D-0 output (or table) schema against the D-0 mapping. Columns the mapping does not name are ignored."""
    types = {c["name"]: str(c["type"]).upper() for c in columns}
    u = used(bq)
    errors: list[dict] = [{"field": f, "code": "D0_FIELD_NOT_MAPPED"} for f in missing_fields(bq)]
    for f, col in u.items():
        if col not in types:
            errors.append({"field": f, "code": "COLUMN_NOT_FOUND", "column": col})
        elif types[col] not in COMPATIBLE[f]:
            errors.append({"field": f, "code": "TYPE_INCOMPATIBLE", "column": col, "type": types[col],
                           "expected": sorted(COMPATIBLE[f])})
    for k in keys:
        if k not in types:
            errors.append({"field": "key_columns", "code": "KEY_COLUMN_NOT_FOUND", "column": k})
    roles: dict[str, list[str]] = {}
    for f, col in u.items():
        roles.setdefault(col, []).append(f)
    for col, fs in roles.items():
        if len(fs) > 1:
            errors.append({"field": fs[0], "code": "SAME_COLUMN_FOR_SEVERAL_FIELDS", "column": col, "fields": fs})
    return {"ok": not errors, "errors": errors, "mapped_types": {col: types.get(col) for col in u.values()},
            "ignored_columns": sorted(set(types) - set(u.values()) - set(keys))}


def _check_error(chk: dict) -> AppError:
    missing = [e for e in chk["errors"] if e["code"] in ("COLUMN_NOT_FOUND", "KEY_COLUMN_NOT_FOUND")]
    code = "D0_MAPPING_INCOMPLETE" if any(e["code"] == "D0_FIELD_NOT_MAPPED" for e in chk["errors"]) \
        else "SQL_OUTPUT_MISSING_COLUMNS" if missing else "D0_MAPPING_TYPE_INCOMPATIBLE"
    return AppError(code, 422, detail=json.dumps(chk["errors"], ensure_ascii=False)[:1500])


def suggest(columns: list[dict]) -> dict:
    """Pre-fill of the D-0 mapping from a REAL output schema (nothing saved): exact known names first, then common
    patterns; only columns that exist with a compatible type are proposed."""
    types = {c["name"]: str(c["type"]).upper() for c in columns}
    known = {"sku_id": ["sku_code", "sku_id", "sku"], "fc_id": ["fc_code", "fc_id", "fc", "warehouse_code", "warehouse"],
             "order_qty": ["demand_quantity", "order_qty", "quantity", "qty"],
             "order_date": ["created_date", "order_date", "date"], "created_at": ["created_at", "order_time"],
             "order_id": ["so_code", "order_id", "order_code"], "source_updated_at": ["refresh_time", "updated_at"]}
    out, notes = {}, []
    for f in ss.D0_FIELDS:
        col = next((c for c in known[f] if c in types and types[c] in COMPATIBLE[f]), None)
        out[f] = {"column": col, "usage": "REQUIRED" if f in ss.D0_ESSENTIAL else "OPTIONAL"}
        if col is None and f in (*ss.D0_ESSENTIAL, "order_date"):
            notes.append({"field": f, "code": "NO_COMPATIBLE_COLUMN_FOUND"})
    if out["order_date"]["column"]:
        out["created_at"] = {"column": None, "usage": "UNUSED"}
    elif out["created_at"]["column"]:
        out["order_date"] = {"column": None, "usage": "UNUSED"}
    return {"mapping": out, "notes": notes, "columns": columns}


# ------------------------------------------------------------------ query
def _q(col: str) -> str:
    return f"t.`{col}`"


def _day_expr(snap: dict) -> str:
    m, types = snap["mapping"], snap.get("types") or {}
    f = date_field(m)
    if f is None:
        raise AppError("D0_MAPPING_INCOMPLETE", 409, detail="order_date|created_at")
    col = m[f]
    t = types.get(col)
    if t is None:        # a validation recorded before 1.2.1 has no output types: never guess a time zone
        raise AppError("D0_REVALIDATE_REQUIRED", 409, detail=f"type of {col} unknown")
    if f == "order_date":
        return _q(col) if t == "DATE" else f"DATE({_q(col)})"
    return f"DATE({_q(col)}, '{VN}')" if t == "TIMESTAMP" else f"DATE({_q(col)})"


def build_sql(snap: dict, exact_policy: str) -> str:
    """Per SKU x FC sum of TODAY's rows (@day, Vietnam) of the D-0 relation (user SQL as a sub-query, or the D-0
    table), plus control rows: excluded rows by reason (incl. OTHER_DAY), totals, key / exact duplicates of today's
    rows and the days present. Nothing is written anywhere."""
    m = snap["mapping"]
    rel = sql_guard.as_subquery(snap["sql"]) if snap["mode"] == "SQL" else f"`{snap['table']}`"
    keys = snap.get("key_columns") or []
    key = f"TO_JSON_STRING(STRUCT({', '.join(_q(k) for k in keys)}))" if keys else "CAST(NULL AS STRING)"
    keydup = ("CAST(COUNTIF(_d = @day) - COUNT(DISTINCT IF(_d = @day, _key, NULL)) AS STRING)" if keys else "'NO_KEY'")
    upd = f"CAST({_q(m['source_updated_at'])} AS STRING)" if m.get("source_updated_at") else "CAST(NULL AS STRING)"
    kept = ("SELECT * EXCEPT(_rn) FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY _row) AS _rn FROM src) WHERE _rn = 1"
            if exact_policy == "DROP_EXACT" else "SELECT * FROM src")
    return f"""WITH src AS (
  SELECT CAST({_q(m['sku_id'])} AS STRING) AS sku_id, CAST({_q(m['fc_id'])} AS STRING) AS fc_id,
    {_q(m['order_qty'])} AS order_qty, {_day_expr(snap)} AS _d, {key} AS _key, {upd} AS _upd, TO_JSON_STRING(t) AS _row
  FROM {rel} AS t
), kept AS (
  {kept}
), checked AS (
  SELECT *, {_REASON} AS _reason FROM kept
)
SELECT 'VALID' AS _kind, CAST(NULL AS STRING) AS _reason, sku_id, fc_id, SUM(order_qty) AS qty, COUNT(*) AS n_rows,
  MAX(_upd) AS source_updated_at FROM checked WHERE _reason IS NULL GROUP BY sku_id, fc_id
UNION ALL
SELECT 'EXCLUDED', _reason, NULL, NULL, SUM(order_qty), COUNT(*), NULL FROM checked WHERE _reason IS NOT NULL GROUP BY _reason
UNION ALL
SELECT 'TOTAL_READ', CAST(COUNTIF(_d = @day) - COUNT(DISTINCT IF(_d = @day, _row, NULL)) AS STRING), NULL, NULL,
  SUM(order_qty), COUNT(*), NULL FROM src
UNION ALL
SELECT 'TOTAL_KEPT', {keydup}, NULL, NULL, SUM(order_qty), COUNT(*), NULL FROM kept
UNION ALL
SELECT 'DATE', CAST(_d AS STRING), NULL, NULL, SUM(order_qty), COUNT(*), NULL FROM kept GROUP BY _d"""


def _num(v) -> float:
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def parse_rows(snap: dict, rows: list[dict], day: date, exact_policy: str, enforce: bool = True) -> dict:
    good = [r for r in rows if r.get("_kind") == "VALID"]
    excluded = {r.get("_reason") or "UNKNOWN": {"rows": int(r.get("n_rows") or 0), "qty": _num(r.get("qty"))}
                for r in rows if r.get("_kind") == "EXCLUDED"}
    tot = next((r for r in rows if r.get("_kind") == "TOTAL_READ"), {}) or {}
    kept = next((r for r in rows if r.get("_kind") == "TOTAL_KEPT"), {}) or {}
    dates = {str(r.get("_reason")): {"rows": int(r.get("n_rows") or 0), "qty": _num(r.get("qty"))}
             for r in rows if r.get("_kind") == "DATE"}
    exact = int(tot.get("_reason") or 0)
    v_rows = sum(int(r.get("n_rows") or 0) for r in good)
    v_qty = sum(_num(r.get("qty")) for r in good)
    e_rows = sum(v["rows"] for v in excluded.values())
    e_qty = sum(v["qty"] for v in excluded.values())
    k_rows, k_qty = int(kept.get("n_rows") or 0), _num(kept.get("qty"))
    other = excluded.get("OTHER_DAY", {"rows": 0, "qty": 0.0})
    rec_ok = k_rows == v_rows + e_rows and abs(k_qty - (v_qty + e_qty)) <= 1e-6 * max(1.0, abs(k_qty))
    issues = []
    if exact and exact_policy == "BLOCK":
        issues.append({"code": "EXACT_DUPLICATES", "detail": {"rows": exact}})
    key_dups = kept.get("_reason")
    if (key_dups in (None, "NO_KEY") or int(key_dups or 0)) and snap.get("key_duplicate_policy", "BLOCK") == "BLOCK":
        issues.append({"code": "KEY_NOT_UNIQUE", "detail": {"rows": key_dups, "key": snap.get("key_columns")}})
    if not rec_ok:
        issues.append({"code": "RECONCILIATION_FAILED", "detail": {"kept": [k_rows, k_qty], "valid": [v_rows, v_qty],
                                                                   "excluded": [e_rows, e_qty]}})
    warnings = []
    if other["rows"]:
        warnings.append({"code": "D0_ROWS_OTHER_THAN_TODAY", "detail": {"rows": other["rows"], "qty": other["qty"],
                                                                         "dates": sorted(d for d in dates if d != str(day))}})
    if not v_rows:
        warnings.append({"code": "D0_NO_ROWS_TODAY", "detail": str(day)})
    out = {"day": str(day),
           "rows": [{"sku_id": r["sku_id"], "fc_id": r["fc_id"], "cumulative_qty": _num(r.get("qty")),
                     "source_updated_at": r.get("source_updated_at"), "n_rows": int(r.get("n_rows") or 0)} for r in good],
           "rows_read": int(tot.get("n_rows") or 0), "rows_valid": v_rows, "rows_error": e_rows - other["rows"],
           "rows_other_day": other["rows"], "rows_dropped_duplicates": int(tot.get("n_rows") or 0) - k_rows,
           "qty_valid": v_qty, "excluded_by_reason": excluded, "exact_duplicate_rows": exact,
           "key_duplicate_rows": key_dups, "dates_in_output": dates, "blocking_issues": issues, "warnings": warnings}
    if enforce and issues:
        code = {"EXACT_DUPLICATES": "BQ_DATA_DUPLICATES", "KEY_NOT_UNIQUE": "BQ_KEY_NOT_UNIQUE",
                "RECONCILIATION_FAILED": "BQ_SYNC_RECONCILIATION_FAILED"}[issues[0]["code"]]
        raise AppError(code, 409, detail=json.dumps(issues, default=str)[:500])
    return out


def public(snap: dict) -> dict:
    return {k: v for k, v in snap.items() if k != "sql"}


# ------------------------------------------------------------------ state of the feed
def _versions_summary(src) -> str:
    if not src.versions:
        return "d0: no SQL version saved"
    parts = []
    for v in sorted(src.versions, key=lambda x: -x.id)[:4]:
        val = v.validation or {}
        st = val.get("status") or "UNCHECKED"
        err = (val.get("error") or {}).get("code")
        parts.append(f"v{v.id} {st}{' ' + err if err else ''}")
    return "d0: " + ", ".join(parts)


def snapshot(conn=None) -> dict:
    """What a D-0 job uses from start to end: mapping, key rules, SQL text (SQL mode) or table (TABLE mode), and the
    output column types proven by BigQuery. Refused when the feed is not validated for the CURRENT mapping."""
    bq = ss.get("bigquery", conn)
    src = ss.get("sql_sources", conn).d0
    miss = missing_fields(bq)
    if miss:
        raise AppError("D0_MAPPING_INCOMPLETE", 409, detail=", ".join(miss))
    h = mapping_hash(bq, src)
    base = {"kind": "d0", "mapping": used(bq), "key_columns": key_columns(src, bq),
            "key_duplicate_policy": src.key_duplicate_policy, "d0_mapping_hash": h, "taken_at": now_iso()}
    if src.mode == "TABLE":
        from . import source_tables
        lc = source_tables.last_check("d0", conn)
        if not (lc and lc.get("status") == "PASSED" and lc.get("table_id") == bq.d0_table_id):
            raise AppError("D0_TABLE_NOT_CHECKED", 409, detail=bq.d0_table_id or "-")
        if lc.get("d0_mapping_hash") != h:
            raise AppError("D0_REVALIDATE_REQUIRED", 409, detail=f"table {bq.d0_table_id}: checked for another D-0 mapping")
        return {**base, "mode": "TABLE", "table": bq.d0_table_id, "types": lc.get("mapped_types") or {}}
    act = next((v for v in src.versions if v.id == src.active_version_id), None)
    if act is None or (act.validation or {}).get("status") != "VALID":
        raise AppError("SQL_NOT_VALIDATED", 409, detail=_versions_summary(src))
    if act.validation.get("d0_mapping_hash") != h:
        raise AppError("D0_REVALIDATE_REQUIRED", 409,
                       detail=f"v{act.id}: validated for another D-0 mapping / key (or before 1.2.1)")
    types = {c["name"]: str(c["type"]).upper() for c in act.validation.get("columns") or []}
    return {**base, "mode": "SQL", "version_id": act.id, "sha256": act.sha256, "sql": act.sql, "types": types}


def readiness(conn=None) -> tuple[list[dict], list[dict]]:
    """Blocking reasons + notes of the BigQuery D-0 feed (local state only, no call to Google)."""
    try:
        snap = snapshot(conn)
    except AppError as e:
        return [{**msg(e.code), "detail": e.detail}], []
    notes = []
    if snap["mode"] == "SQL":
        src = ss.get("sql_sources", conn).d0
        act = next(v for v in src.versions if v.id == src.active_version_id)
        ex = (act.validation or {}).get("execution") or {}
        issues = [i["code"] for i in ex.get("blocking_issues") or []]
        if issues:
            notes.append({**msg("D0_LAST_CHECK_DATA_ISSUES"),
                          "detail": f"v{act.id} {ex.get('day')}: {', '.join(issues)} (key policy {src.key_duplicate_policy})"})
    return [], notes


def view(conn=None) -> dict:
    bq = ss.get("bigquery", conn)
    src = ss.get("sql_sources", conn).d0
    reasons, notes = readiness(conn)
    return {"mapping": {f: m.model_dump() for f, m in bq.d0_mapping.items()}, "used": used(bq),
            "fields": [{"field": f, "essential": f in ss.D0_ESSENTIAL or f in ("order_date", "created_at"),
                        "types": sorted(COMPATIBLE[f])} for f in ss.D0_FIELDS],
            "missing": missing_fields(bq), "key_columns": key_columns(src, bq), "mapping_hash": mapping_hash(bq, src),
            "mode": src.mode, "table_id": bq.d0_table_id, "ready": not reasons, "reasons": reasons, "notes": notes}


def save_mapping(mapping: dict) -> dict:
    """Save the D-0 mapping only (never the D-1 mapping, never production mode). A changed mapping makes the current
    D-0 validation / table check stale until it is validated again."""
    bq = ss.get("bigquery")
    cur = {f: m.model_dump() for f, m in bq.d0_mapping.items()}
    unknown = set(mapping) - set(ss.D0_FIELDS)
    if unknown:
        raise AppError("VALIDATION_ERROR", 422, detail=f"unknown D-0 fields {sorted(unknown)}")
    for f, m in mapping.items():
        col = (m or {}).get("column")
        cur[f] = {"column": (col or "").strip() or None, "usage": (m or {}).get("usage") or cur[f]["usage"]}
    ss.update("bigquery", {"d0_mapping": cur}, note="D-0 mapping (UI)")
    return view()


# ------------------------------------------------------------------ BigQuery: validate / test / fetch
def _check_text(sql_text: str, day: date) -> dict:
    """Dry run + mapping check + REAL execution of today's aggregate (nothing written). Raises the first blocking
    problem as an AppError; returns every part of the result otherwise."""
    from . import connector
    bq = ss.get("bigquery")
    src = ss.get("sql_sources").d0
    miss = missing_fields(bq)
    if miss:
        raise AppError("D0_MAPPING_INCOMPLETE", 422, detail=", ".join(miss))
    dr = connector.sql_dry_run(sql_text)
    out: dict = {k: dr[k] for k in ("statement_type", "estimated_bytes", "columns", "referenced_tables")}
    if dr["statement_type"] != "SELECT":
        raise AppError("SQL_NOT_A_QUERY", 422, detail=str(dr["statement_type"]))
    keys = key_columns(src, bq)
    chk = check_columns(dr["columns"], bq, keys)
    out["mapping_check"] = chk
    if not chk["ok"]:
        err = _check_error(chk)
        err.params["partial"] = out
        raise err
    if dr["estimated_bytes"] > bq.maximum_bytes_billed:
        raise AppError("BQ_QUERY_TOO_EXPENSIVE", 413, detail=f"{dr['estimated_bytes']} > {bq.maximum_bytes_billed}")
    snap = {"mode": "SQL", "sql": sql_text, "mapping": used(bq), "key_columns": keys,
            "key_duplicate_policy": src.key_duplicate_policy, "types": chk["mapped_types"]}
    res = connector._run(connector._client(bq), bq, "d0_check", build_sql(snap, bq.exact_duplicate_policy),
                         [("day", "DATE", day)])
    parsed = parse_rows(snap, res["rows"], day, bq.exact_duplicate_policy, enforce=False)
    out["execution"] = {**{k: v for k, v in parsed.items() if k != "rows"}, "n_series": len(parsed["rows"]),
                        "estimated_bytes": res["estimated_bytes"], "executed_at": now_iso()}
    out["_rows"] = parsed["rows"]
    out["d0_mapping_hash"] = mapping_hash(bq, src)
    out["key_columns"] = keys
    out["mapping"] = used(bq)
    return out


def validate_version(vid: int) -> dict:
    """Real BigQuery validation of one D-0 SQL version. VALID activates it; INVALID keeps the active one."""
    from . import sql_sources
    src = sql_sources.source("d0")
    v = sql_sources.version(src, vid)
    day = today_vn()
    result: dict = {"checked_at": now_iso(), "static_check": sql_guard.check(v.sql), "sql_sha256": v.sha256, "day": str(day)}
    try:
        out = _check_text(v.sql, day)
        out.pop("_rows", None)
        result.update(out)
        result["status"] = "VALID"
    except AppError as e:
        result.update(e.params.pop("partial", None) or {})
        result.update(status="INVALID", error=e.to_dict())
    return {**sql_sources.record_validation("d0", vid, result), "validation": result}


def test_version(vid: int) -> dict:
    """The same checks on real data WITHOUT recording anything (no activation, nothing written)."""
    from . import sql_sources
    v = sql_sources.version(sql_sources.source("d0"), vid)
    out = _check_text(v.sql, today_vn())
    rows = out.pop("_rows")
    ex = out["execution"]
    return {**ex, "rows": rows[:50], "columns": out["columns"], "mapping_check": out["mapping_check"],
            "passed": not ex["blocking_issues"], "checked_at": now_iso(), "version_id": vid}


def fetch(day: date, snap: dict) -> dict:
    """Cumulative quantity per SKU x FC for `day` from the snapshot's SQL or table - never the D-1 table."""
    from . import connector
    bq = ss.get("bigquery")
    if snap["mode"] == "TABLE":
        from .source_tables import parse
        parse(snap["table"])
    res = connector._run(connector._client(bq), bq, "d0", build_sql(snap, bq.exact_duplicate_policy),
                         [("day", "DATE", day)])
    out = parse_rows(snap, res["rows"], day, bq.exact_duplicate_policy)
    return {**out, "estimated_bytes": res["estimated_bytes"], "source": public(snap)}
