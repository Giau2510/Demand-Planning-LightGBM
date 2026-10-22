"""Read-only BigQuery connector. Never creates datasets/tables/views and never writes to BigQuery.

The source table (e.g. `gold_buymed_vn2.demand_planing_lightgbm`) is built by the user's own SQL. That SQL and the
table are NOT modified here: every query below is an independent read-only query on top of the table. The app-side
rules (column mapping, date range, row checks, aggregation to SKU × FC × day) are listed in docs/BIGQUERY.md.

Cost control: only mapped columns are selected (never SELECT * on the source table), every query is dry-run first
and refused when it would scan more than `maximum_bytes_billed`, the partition column (if configured) is always
filtered, and daily loads are incremental (watermark + small late-data look-back) and never start before
`history_start_date`.
Each query starts with a `-- df:<kind>` marker (used in logs and by the fake client in tests).
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .. import db, paths
from .. import settings_service as ss
from ..data import open_hours
from ..messages import AppError
from ..timeutil import VN_TZ, now_iso, now_vn, today_vn
from . import dup_report, oauth, sql_guard

log = logging.getLogger("df.bq")

NUMERIC = {"INT64", "INTEGER", "FLOAT64", "FLOAT", "NUMERIC", "BIGNUMERIC"}
TEXTISH = {"STRING", "INT64", "INTEGER"}
FLAG = {"BOOL", "BOOLEAN", "INT64", "INTEGER", "STRING"}
COMPATIBLE = {
    "order_id": TEXTISH, "created_at": {"TIMESTAMP", "DATETIME"},
    # a TIMESTAMP has no calendar day without a time zone: map it to created_at (explicit UTC/VN setting) instead
    "order_date": {"DATE", "DATETIME"},
    "sku_id": TEXTISH, "fc_id": TEXTISH, "order_qty": NUMERIC, "unit_price": NUMERIC, "discount_amount": NUMERIC,
    "promotion_flag": FLAG, "promotion_id": TEXTISH, "voucher_flag": FLAG, "voucher_amount": NUMERIC,
    "source_updated_at": {"TIMESTAMP", "DATETIME"}, "batch_id": TEXTISH,
}
REF_COMPATIBLE = {
    "product_id": TEXTISH, "item_code": TEXTISH, "outbound_qty": NUMERIC, "order_status": TEXTISH,
    "sales_price": NUMERIC, "price_after_discount": NUMERIC, "seller_code": TEXTISH,
    "sku_status": TEXTISH | {"BOOL", "BOOLEAN"}, "open_date": {"DATE", "DATETIME", "TIMESTAMP"},
    "open_hours": NUMERIC, "open_days": NUMERIC,
}
REF_NUMERIC = {"outbound_qty", "sales_price", "price_after_discount", "open_hours", "open_days"}
REF_CATEGORY = {"order_status", "sku_status"}
EXCLUSION_REASONS = ["NULL_SKU", "NULL_FC", "NULL_TARGET", "NEGATIVE_TARGET"]

# Column names of the confirmed source table `demand_planing_lightgbm` (as given by the user). Used ONLY to pre-fill a
# suggestion on the mapping page; nothing is saved until the user reviews it and the live schema confirms the types.
SUGGESTED = {
    "order_id": "so_code", "order_date": "created_date", "sku_id": "sku_code", "fc_id": "fc_code",
    "order_qty": "demand_quantity", "source_updated_at": "refresh_time",
}
SUGGESTED_REF = {
    "product_id": "product_id", "item_code": "item_code", "outbound_qty": "outbound_quantity",
    "order_status": "order_status", "sales_price": "sales_price", "price_after_discount": "price_after_discount",
    "seller_code": "seller_code", "sku_status": "sku_system_status", "open_date": "open_date",
    "open_hours": "total_open_hours", "open_days": "total_open_days",
}

_client_factory = None
_sleep = time.sleep


def set_client_factory(fn) -> None:
    """Tests inject a fake client factory: fn(settings) -> client."""
    global _client_factory
    _client_factory = fn


def set_sleep(fn) -> None:
    global _sleep
    _sleep = fn


def _client(bq):
    if _client_factory is not None:
        return _client_factory(bq)
    try:
        from google.cloud import bigquery
    except ImportError as e:
        raise AppError("BQ_LIBRARY_MISSING", 500) from e
    return bigquery.Client(project=bq.project_id, credentials=_credentials(bq), location=bq.location or None)


def _credentials(bq):
    """Credentials of the Windows account running the app for the configured method. Building them does NOT contact
    Google: verify_auth() does the real check."""
    try:
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError, RefreshError
    except ImportError as e:
        raise AppError("BQ_LIBRARY_MISSING", 500) from e
    scopes = ["https://www.googleapis.com/auth/bigquery"]
    if bq.oauth_enabled:          # 'Sign in with Google' done in the app (Windows Credential Manager)
        return oauth.credentials()
    try:
        if bq.auth_method == "SERVICE_ACCOUNT_FILE":
            from google.oauth2 import service_account
            p = Path(bq.service_account_file)
            if not p.is_file():
                raise AppError("BQ_AUTH_MISSING", 400, detail="service account file not found")
            if paths.REPO_DIR in p.resolve().parents:
                raise AppError("BQ_AUTH_MISSING", 400, detail="key file must be stored outside the application folder")
            creds = service_account.Credentials.from_service_account_file(str(p), scopes=scopes)
        else:
            creds, _ = google.auth.default(scopes=scopes)
    except DefaultCredentialsError as e:
        raise AppError("BQ_AUTH_MISSING", 401) from e
    except RefreshError as e:
        raise AppError("BQ_AUTH_EXPIRED", 401) from e
    return creds


_auth_probe = None


def set_auth_probe(fn) -> None:
    """Tests inject fn(bq) -> identity dict (or raise) instead of a real token request to Google."""
    global _auth_probe
    _auth_probe = fn


def verify_auth(bq) -> dict:
    """Real round trip to Google: obtain an access token NOW with the stored credentials and read the account e-mail.
    Separates 'cannot sign in' (revoked/expired token, invalid client, network) from later permission problems."""
    if _auth_probe is not None:
        return _auth_probe(bq)
    if _client_factory is not None:          # fake BigQuery client in tests: no Google round trip possible
        return {"verified": False, "note": "test client"}
    from google.auth.transport.requests import Request
    creds = _credentials(bq)
    try:
        creds.refresh(Request())
    except Exception as e:  # noqa: BLE001 - classified below
        raise _map_error(e) from e
    email = getattr(creds, "service_account_email", None)
    if not email and getattr(creds, "token", None):
        try:
            import requests
            r = requests.get(oauth.USERINFO_URI, headers={"Authorization": f"Bearer {creds.token}"}, timeout=20)
            email = (r.json() or {}).get("email") if r.status_code == 200 else None
        except Exception:  # noqa: BLE001 - the e-mail is informative; the token itself was obtained
            email = None
    return {"verified": True, "account": email}


def _reasons(e: Exception) -> set[str]:
    out = set()
    for x in getattr(e, "errors", None) or []:
        if isinstance(x, dict) and x.get("reason"):
            out.add(str(x["reason"]))
    return out


def _map_error(e: Exception) -> AppError:
    """Classify a client/library error. Never includes credentials; the message is cut to its first line."""
    if isinstance(e, AppError):
        return e
    name = type(e).__name__
    msg = str(e).split("\n")[0][:300]
    low = msg.lower()
    reasons = _reasons(e)
    if name == "DefaultCredentialsError":
        return AppError("BQ_AUTH_MISSING", 401, detail=msg)
    # the OAuth client itself is wrong / deleted / not allowed (administrator action), not an expired sign-in
    if "invalid_client" in low or "unauthorized_client" in low or "deleted_client" in low:
        return AppError("OAUTH_CLIENT_INVALID", 401, detail=msg)
    # the token works but lacks the BigQuery scope (the user unticked it on the consent page)
    if "insufficient authentication scopes" in low or "access_token_scope_insufficient" in low \
            or "invalid_scope" in low:
        return AppError("OAUTH_SCOPE_NOT_GRANTED", 403, detail=msg)
    if name in ("RefreshError", "Unauthorized") or "invalid_grant" in low or "reauthentication" in low:
        return AppError("BQ_AUTH_EXPIRED", 401, detail=msg)
    if "bytesbilledlimitexceeded" in {r.lower() for r in reasons} or "bytes billed" in low:
        return AppError("BQ_QUERY_TOO_EXPENSIVE", 413, detail=msg)
    if name == "TooManyRequests" or reasons & {"quotaExceeded", "rateLimitExceeded"} or "quota exceeded" in low \
            or "rate limit" in low:
        return AppError("BQ_QUOTA", 429, detail=msg)
    if name in ("TimeoutError", "DeadlineExceeded", "Timeout", "ReadTimeout", "ConnectTimeout") or "timed out" in low \
            or "timeout" in low:
        return AppError("BQ_TIMEOUT", 504, detail=msg)
    if name in ("ServiceUnavailable", "InternalServerError", "BadGateway", "GatewayTimeout", "ConnectionError",
                "TransportError") or reasons & {"backendError", "internalError"}:
        return AppError("BQ_UNAVAILABLE", 503, detail=msg)
    if reasons & {"accessNotConfigured"} or "has not been used in project" in low or ("api" in low and "is disabled" in low):
        return AppError("BQ_API_DISABLED", 403, detail=msg)
    if name in ("Forbidden", "PermissionDenied") or "access denied" in low or "permission" in low:
        return AppError("BQ_PERMISSION_DENIED", 403, detail=msg)
    # "Not found: Table x was not found in location L" = the table does not exist; a dataset not found in a location
    # is the classic wrong-location case (real BigQuery messages, checked 17/10/2026)
    if name == "NotFound" and "location" in low and "not found: table" not in low:
        return AppError("BQ_LOCATION_MISMATCH", 409, detail=msg)
    if name == "NotFound":
        return AppError("BQ_NOT_FOUND", 404, detail=msg)
    if name == "BadRequest" and ("unrecognized name" in low or "no matching signature" in low
                                 or "cannot be" in low and "type" in low or "not found inside" in low):
        return AppError("BQ_SCHEMA_CHANGED", 409, detail=msg)
    if name == "BadRequest" and ("syntax error" in low or "unexpected" in low or "parse" in low):
        return AppError("BQ_SQL_ERROR", 400, detail=msg)
    if name == "BadRequest":
        return AppError("BQ_QUERY_INVALID", 400, detail=msg)
    return AppError("BQ_ERROR", 502, detail=f"{name}: {msg}")


def _require_config(bq, table: bool = True):
    if not bq.project_id or not bq.dataset_id or (table and not bq.source_table):
        raise AppError("BQ_NOT_CONFIGURED", 409)


def _table_ref(bq, table: str | None = None) -> str:
    return f"`{bq.project_id}.{bq.dataset_id}.{table or bq.source_table}`"


RETRYABLE = {"BQ_UNAVAILABLE", "BQ_QUOTA"}


def _run(client, bq, kind: str, sql: str, params: list | None = None, dry_run_only: bool = False) -> dict:
    """Dry run (cost check) then the query. Transient errors are retried at most `max_retries` times; a timeout is
    never retried (the job is cancelled) so a slow query cannot multiply its cost."""
    from_lib = _client_factory is None
    sql = f"-- df:{kind}\n{sql}"
    if from_lib:
        from google.cloud import bigquery
        # 1.2.13: a list value is an ARRAY parameter (line evidence of the history sync: days, SKUs, order codes)
        qp = [bigquery.ArrayQueryParameter(n, t, list(v)) if isinstance(v, (list, tuple))
              else bigquery.ScalarQueryParameter(n, t, v) for n, t, v in (params or [])]
        dry = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False, query_parameters=qp)
        cfg = bigquery.QueryJobConfig(maximum_bytes_billed=bq.maximum_bytes_billed, query_parameters=qp)
    else:
        dry = {"dry_run": True, "params": params}
        cfg = {"dry_run": False, "params": params, "maximum_bytes_billed": bq.maximum_bytes_billed}
    try:
        dj = client.query(sql, job_config=dry)
        est = int(dj.total_bytes_processed or 0)
    except Exception as e:
        err = _map_error(e)
        if err.code == "BQ_AUTH_EXPIRED" and bq.oauth_enabled:
            oauth.mark_revoked(err.detail)
        raise err from e
    if est > bq.maximum_bytes_billed:
        raise AppError("BQ_QUERY_TOO_EXPENSIVE", 413, detail=f"{est} bytes > {bq.maximum_bytes_billed}", estimated_bytes=est)
    if dry_run_only:
        return {"estimated_bytes": est, "rows": [], "attempts": 0}
    attempt = 0
    t0 = time.monotonic()
    while True:
        attempt += 1
        job = None
        try:
            job = client.query(sql, job_config=cfg)
            rows = [dict(r.items()) if hasattr(r, "items") else dict(r) for r in job.result(timeout=bq.query_timeout_seconds)]
            log.info("bq query", extra={"ctx": {"kind": kind, "estimated_bytes": est, "rows": len(rows),
                                                "attempts": attempt, "seconds": round(time.monotonic() - t0, 2)}})
            return {"estimated_bytes": est, "rows": rows, "attempts": attempt}
        except Exception as e:
            err = _map_error(e)
            if err.code == "BQ_TIMEOUT" and job is not None and hasattr(job, "cancel"):
                try:
                    job.cancel()
                except Exception:   # noqa: BLE001 - best effort, the timeout is what is reported
                    pass
            log.warning("bq query failed", extra={"ctx": {"kind": kind, "code": err.code, "attempt": attempt}})
            if err.code == "BQ_AUTH_EXPIRED" and bq.oauth_enabled:
                oauth.mark_revoked(err.detail)
            if err.code in RETRYABLE and attempt <= bq.max_retries:
                _sleep(min(30, 2 ** attempt))
                continue
            if attempt > 1:
                err.params["attempts"] = attempt
            raise err from e


def _set_status(part: str, ok: bool, **info) -> dict:
    with db.tx() as c:
        r = db.one(c, "SELECT value_json FROM sync_state WHERE name='bq_status'")
        st = json.loads(r["value_json"]) if r else {}
        st[part] = {"ok": ok, "checked_at": now_iso(), **info}
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES ('bq_status', ?, ?) "
                  "ON CONFLICT(name) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                  (json.dumps(st, default=str), now_iso()))
    return st[part]


def status() -> dict:
    with db.read() as c:
        r = db.one(c, "SELECT value_json FROM sync_state WHERE name='bq_status'")
        d1 = db.rows(c, "SELECT name, value_json FROM sync_state WHERE name LIKE 'last_d1_sync:BIGQUERY:%'")
    st = json.loads(r["value_json"]) if r else {}
    st["last_sync"] = {x["name"].split(":", 1)[1]: json.loads(x["value_json"]) for x in d1}
    return st


def _checked(fn_name: str, part: str):
    def deco(fn):
        def wrapper(*a, **kw):
            try:
                res = fn(*a, **kw)
                _set_status(part, bool(res.get("passed", True)), **{k: v for k, v in res.items() if k in (
                    "location", "principal", "num_rows", "estimated_bytes", "n_columns", "mapping_hash", "blocking_issues")})
                return res
            except AppError as e:
                _set_status(part, False, error=e.to_dict())
                raise
        wrapper.__name__ = fn_name
        return wrapper
    return deco


@_checked("test_connection", "connection")
def test_connection() -> dict:
    """Metadata only (dataset + table): no table data is read and no query cost is incurred."""
    bq = ss.get("bigquery")
    _require_config(bq, table=False)
    client = _client(bq)
    try:
        ds = client.get_dataset(f"{bq.project_id}.{bq.dataset_id}")
        actual_loc = getattr(ds, "location", None)
        out = {"project": bq.project_id, "dataset": f"{bq.project_id}.{bq.dataset_id}", "location": actual_loc}
        if bq.location and actual_loc and bq.location.lower() != actual_loc.lower():
            raise AppError("BQ_LOCATION_MISMATCH", 409, detail=f"configured {bq.location}, actual {actual_loc}")
        if bq.source_table:
            t = client.get_table(f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}")
            out.update(table=bq.source_table, num_rows=getattr(t, "num_rows", None),
                       table_type=str(getattr(t, "table_type", "") or ""),
                       partitioning=str(getattr(t, "time_partitioning", None) or ""))
        return out
    except Exception as e:
        raise _map_error(e) from e


@_checked("read_schema", "schema")
def read_schema() -> dict:
    """Schema from table metadata (no query, no cost)."""
    bq = ss.get("bigquery")
    _require_config(bq)
    client = _client(bq)
    try:
        t = client.get_table(f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}")
    except Exception as e:
        raise _map_error(e) from e
    cols = [{"name": f.name, "type": f.field_type.upper(), "mode": getattr(f, "mode", "NULLABLE")} for f in t.schema]
    drift = schema_drift(bq.schema_snapshot, cols) if bq.schema_snapshot else None
    return {"columns": cols, "n_columns": len(cols), "drift": drift,
            "table_type": str(getattr(t, "table_type", "") or ""), "num_rows": getattr(t, "num_rows", None),
            "partitioning": str(getattr(t, "time_partitioning", None) or "")}


def schema_drift(saved: list[dict], current: list[dict]) -> dict:
    s = {c["name"]: c["type"] for c in saved}
    cur = {c["name"]: c["type"] for c in current}
    return {"removed": sorted(set(s) - set(cur)), "added": sorted(set(cur) - set(s)),
            "type_changed": sorted(k for k in set(s) & set(cur) if s[k] != cur[k])}


def _fm(m):
    return m if isinstance(m, ss.FieldMapping) else ss.FieldMapping.model_validate(m)


def validate_mapping(columns: list[dict], mapping=None, reference_mapping=None, extra_reference_columns=None) -> dict:
    bq = ss.get("bigquery")
    extra = list(bq.extra_reference_columns if extra_reference_columns is None else extra_reference_columns)
    mapping = {k: _fm(v) for k, v in (mapping or bq.field_mapping).items()}
    for f in ss.INTERNAL_FIELDS:            # a partial mapping (e.g. posted by a client) = the other fields unmapped
        mapping.setdefault(f, ss.FieldMapping(column=None, usage="UNUSED"))
    reference_mapping = {k: _fm(v) for k, v in (reference_mapping if reference_mapping is not None
                                                  else bq.reference_mapping).items()}
    types = {c["name"]: c["type"] for c in columns}
    errors, warnings = [], []
    for field, m in mapping.items():
        if m.usage == "UNUSED":
            continue
        if not m.column:
            if m.usage == "REQUIRED":
                errors.append({"field": field, "code": "REQUIRED_NOT_MAPPED"})
            continue
        if m.column not in types:
            errors.append({"field": field, "code": "COLUMN_NOT_FOUND", "column": m.column})
            continue
        if types[m.column] not in COMPATIBLE[field]:
            code = "ORDER_DATE_TIMESTAMP_NEEDS_TIMEZONE" if field == "order_date" and types[m.column] == "TIMESTAMP" \
                else "TYPE_INCOMPATIBLE"
            errors.append({"field": field, "code": code, "column": m.column, "type": types[m.column],
                           "expected": sorted(COMPATIBLE[field])})
    for field, m in reference_mapping.items():
        if m.usage == "UNUSED" or not m.column:
            continue
        if m.column not in types:
            errors.append({"field": field, "code": "COLUMN_NOT_FOUND", "column": m.column, "reference": True})
        elif types[m.column] not in REF_COMPATIBLE[field]:
            errors.append({"field": field, "code": "TYPE_INCOMPATIBLE", "column": m.column, "type": types[m.column],
                           "expected": sorted(REF_COMPATIBLE[field]), "reference": True})
    # 1.2.9: a REQUIRED_FEATURE (SKU open hours) must be mapped: the model input cannot exist without its column
    for field in ss.MANDATORY_REFERENCE_FIELDS:
        m = reference_mapping.get(field)
        if not m or m.usage == "UNUSED" or not m.column:
            errors.append({"field": field, "code": "REQUIRED_NOT_MAPPED", "reference": True, "role": "REQUIRED_FEATURE"})
    used = lambda f: mapping[f].usage != "UNUSED" and mapping[f].column  # noqa: E731
    if not used("created_at") and not used("order_date"):
        errors.append({"field": "created_at", "code": "NEED_CREATED_AT_OR_ORDER_DATE"})
    for f in ("sku_id", "fc_id", "order_qty"):
        if not used(f) and not any(e["field"] == f for e in errors):
            errors.append({"field": f, "code": "REQUIRED_NOT_MAPPED"})
    if not used("order_id"):
        warnings.append({"field": "order_id", "code": "NO_ORDER_ID_DUPLICATES_BY_FULL_ROW"})
    roles = {}
    for f, m in list(mapping.items()) + list(reference_mapping.items()):
        if m.usage != "UNUSED" and m.column:
            roles.setdefault(m.column, []).append(f)
    for col, fs in roles.items():
        key_fs = [f for f in fs if f in ("sku_id", "fc_id", "order_qty", "order_date", "created_at", "order_id")]
        # 1.2.9: one column feeds at most ONE of key / target / model input (a key or the target as a model input would
        # break the grain or leak the target); a REFERENCE field may read the same column (shown, never an input)
        model_fs = [f for f in fs if ss.FIELD_ROLES.get(f) != "REFERENCE"]
        if len(key_fs) > 1:
            errors.append({"field": key_fs[0], "code": "SAME_COLUMN_FOR_SEVERAL_KEYS", "column": col, "fields": key_fs})
        elif len(model_fs) > 1:
            errors.append({"field": model_fs[0], "code": "COLUMN_ROLE_CONFLICT", "column": col, "fields": model_fs,
                           "roles": [ss.FIELD_ROLES[f] for f in model_fs]})
        elif len(fs) > 1:
            warnings.append({"field": fs[0], "code": "COLUMN_USED_TWICE", "column": col, "fields": fs})
    for col in extra:                # columns classified as REFERENCE without a field: never read, so only checked here
        if col in roles:
            errors.append({"field": "extra_reference_columns", "code": "EXTRA_REFERENCE_ALREADY_MAPPED", "column": col,
                           "fields": roles[col]})
        elif col not in types:
            warnings.append({"field": "extra_reference_columns", "code": "EXTRA_REFERENCE_NOT_IN_SOURCE", "column": col})
    if bq.partition_column and bq.partition_column not in types:
        errors.append({"field": "partition_column", "code": "COLUMN_NOT_FOUND", "column": bq.partition_column})
    return {"ok": not errors, "errors": errors, "warnings": warnings}


_ROLE_ORDER = {r: i for i, r in enumerate(ss.ROLES)}


def column_roles(columns: list[dict], bq=None) -> list[dict]:
    """1.2.9: every column of the D-1 source (schema snapshot / live schema) with the field(s) and role reading it.
    A column no field uses is UNCLASSIFIED (waiting for a decision) or an extra REFERENCE column; nothing is ever turned
    into a key, the target or a model input because it exists. Columns mapped but absent from the source are listed
    with status MISSING_IN_SOURCE."""
    bq = bq or ss.get("bigquery")
    used: dict[str, list[dict]] = {}
    for ref, fm in ((False, bq.field_mapping), (True, bq.reference_mapping)):
        for f, m in fm.items():
            if m.usage != "UNUSED" and m.column:
                used.setdefault(m.column, []).append({"field": f, "role": ss.FIELD_ROLES[f], "reference": ref})
    extra = set(bq.extra_reference_columns)
    out, names = [], set()
    for c in columns:
        n = c["name"]
        names.add(n)
        fs = used.get(n, [])
        if fs:
            role = min((x["role"] for x in fs), key=_ROLE_ORDER.get)
            status = "CLASSIFIED"
        elif n in extra:
            role, status = "REFERENCE", "EXTRA_REFERENCE"
        else:
            role, status = None, "UNCLASSIFIED"
        out.append({"name": n, "type": c.get("type"), "role": role, "status": status, "fields": fs,
                    "model_input": role in ("REQUIRED_FEATURE", "OPTIONAL_FEATURE")})
    for n, fs in used.items():
        if n not in names:
            out.append({"name": n, "type": None, "role": min((x["role"] for x in fs), key=_ROLE_ORDER.get),
                        "status": "MISSING_IN_SOURCE", "fields": fs, "model_input": False})
    return out


def suggest_mapping(columns: list[dict]) -> dict:
    """Pre-fill for the confirmed table layout. Only columns that exist in the LIVE schema with a compatible type are
    proposed; everything else is left unmapped with a note. Nothing is saved here."""
    types = {c["name"]: c["type"] for c in columns}
    fm = {f: {"column": None, "usage": "UNUSED" if f in ("order_date", "created_at") else "OPTIONAL"}
          for f in ss.INTERNAL_FIELDS}
    for f in ("sku_id", "fc_id", "order_qty"):
        fm[f]["usage"] = "REQUIRED"
    notes = []
    for f, col in SUGGESTED.items():
        t = types.get(col)
        if t is None:
            notes.append({"field": f, "code": "SUGGESTED_COLUMN_MISSING", "column": col})
            continue
        if f == "order_date" and t == "TIMESTAMP":
            fm["created_at"] = {"column": col, "usage": "REQUIRED"}
            notes.append({"field": "created_at", "code": "DATE_COLUMN_IS_TIMESTAMP_SET_TIMEZONE", "column": col})
            continue
        if t not in COMPATIBLE[f]:
            notes.append({"field": f, "code": "SUGGESTED_TYPE_INCOMPATIBLE", "column": col, "type": t})
            continue
        fm[f] = {"column": col, "usage": "REQUIRED" if f in ("sku_id", "fc_id", "order_qty", "order_date") else "OPTIONAL"}
    ref = {f: {"column": None, "usage": "OPTIONAL"} for f in ss.REFERENCE_FIELDS}
    for f, col in SUGGESTED_REF.items():
        t = types.get(col)
        if t is None:
            notes.append({"field": f, "code": "SUGGESTED_COLUMN_MISSING", "column": col, "reference": True})
        elif t not in REF_COMPATIBLE[f]:
            notes.append({"field": f, "code": "SUGGESTED_TYPE_INCOMPATIBLE", "column": col, "type": t, "reference": True})
        else:
            ref[f] = {"column": col, "usage": "OPTIONAL"}
    for f in ("unit_price", "discount_amount", "promotion_flag", "voucher_flag", "voucher_amount"):
        notes.append({"field": f, "code": "LEFT_UNMAPPED_NEEDS_BUSINESS_RULE"})
    return {"field_mapping": fm, "reference_mapping": ref, "notes": notes,
            "target": {"field": "order_qty", "column": fm["order_qty"]["column"]}}


def _hist_identity(conn=None) -> dict:
    """Which history feed the validation belongs to: TABLE, or the exact active SQL text (sha256) + key rules."""
    src = ss.get("sql_sources", conn).history
    act = next((v for v in src.versions if v.id == src.active_version_id), None)
    keys = src.key_columns or [m.column for f, m in sorted(bq_map(conn).items())
                               if f in ("order_id", "sku_id", "fc_id", "order_date", "created_at") and m.column]
    return {"mode": src.mode, "sql_sha256": act.sha256 if (src.mode == "SQL" and act) else None,
            "key_columns": keys, "key_duplicate_policy": src.key_duplicate_policy}


def bq_map(conn=None) -> dict:
    return ss.get("bigquery", conn).field_mapping


def mapping_hash(bq, conn=None) -> str:
    """Identity of everything that decides WHICH rows are read and HOW they are turned into demand."""
    key = {"table": f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}",
           "field_mapping": {k: v.model_dump() for k, v in sorted(bq.field_mapping.items())},
           "reference_mapping": {k: v.model_dump() for k, v in sorted(bq.reference_mapping.items())},
           "created_at_is_utc": bq.created_at_is_utc, "partition_column": bq.partition_column,
           "history_start_date": bq.history_start_date, "exact_duplicate_policy": bq.exact_duplicate_policy,
           "history_source": _hist_identity(conn),
           "window_start_date": ss.get("data_policy", conn).window_start_date}
    if bq.customer_id_column:       # 1.2.9b: only when mapped - an unmapped installation keeps its hash
        from ..data import customers
        key["customer_id"] = {"column": bq.customer_id_column, "repeat_lookback_days": customers.REPEAT_LOOKBACK_DAYS}
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def _col(bq, field):
    m = bq.field_mapping.get(field)
    if not m or m.usage == "UNUSED" or not m.column:
        return None
    return f"`{m.column}`"


def _ref_col(bq, field):
    m = bq.reference_mapping.get(field)
    if not m or m.usage == "UNUSED" or not m.column:
        return None
    return f"`{m.column}`"


def _order_date_expr(bq) -> str:
    od = _col(bq, "order_date")
    if od:
        return f"DATE({od})"
    ca = _col(bq, "created_at")
    if bq.created_at_is_utc:
        return f"DATE(TIMESTAMP({ca}), 'Asia/Ho_Chi_Minh')"
    return f"DATE({ca})"


def _raw_date_col(bq) -> str:
    return _col(bq, "order_date") or _col(bq, "created_at")


def _created_ts_expr(bq) -> str | None:
    ca = _col(bq, "created_at")
    if not ca:
        return None
    return f"TIMESTAMP({ca})" if bq.created_at_is_utc else f"TIMESTAMP({ca}, 'Asia/Ho_Chi_Minh')"


# ------------------------------------------------------------------ source relation: table or validated user SQL
def _snap(snap: dict | None, kind: str = "history") -> dict:
    from . import sql_sources
    return snap if snap is not None else sql_sources.snapshot(kind)


def _is_sql(snap: dict | None) -> bool:
    return bool(snap) and snap.get("mode") == "SQL"


def _rel(bq, snap: dict | None) -> str:
    """FROM target: the configured table, or the user's SQL text unchanged as a sub-query."""
    return f"{sql_guard.as_subquery(snap['sql'])} AS _user_sql" if _is_sql(snap) else _table_ref(bq)


def _key_expr(snap: dict | None) -> str | None:
    cols = (snap or {}).get("key_columns") or []
    return f"TO_JSON_STRING(STRUCT({', '.join(f'`{c}`' for c in cols)}))" if cols else None


def _partition_filter(bq, start_param: str, end_param: str, snap: dict | None = None) -> str:
    if not bq.partition_column or _is_sql(snap):
        return ""        # the partition column belongs to the table; a user SQL filters its own sources
    # widen by one day on each side to cover the UTC/UTC+7 shift; exact filtering uses order_date
    return (f" AND DATE(`{bq.partition_column}`) BETWEEN DATE_SUB(@{start_param}, INTERVAL 1 DAY) "
            f"AND DATE_ADD(@{end_param}, INTERVAL 1 DAY)")


def _mapped_internal(bq) -> list[str]:
    return [f for f in ss.INTERNAL_FIELDS if _col(bq, f)]


def _mapped_refs(bq) -> list[str]:
    return [f for f in ss.REFERENCE_FIELDS if _ref_col(bq, f)]


def _select_list(bq, with_refs: bool = False) -> str:
    parts = [f"{_col(bq, f)} AS {f}" for f in _mapped_internal(bq)]
    if with_refs:
        parts += [f"{_ref_col(bq, f)} AS ref_{f}" for f in _mapped_refs(bq)]
    return ", ".join(parts)


def _aliases(bq, with_refs: bool = False) -> list[str]:
    a = _mapped_internal(bq)
    if with_refs:
        a += [f"ref_{f}" for f in _mapped_refs(bq)]
    return a


_REASON = ("CASE WHEN sku_id IS NULL THEN 'NULL_SKU' WHEN fc_id IS NULL THEN 'NULL_FC' "
           "WHEN order_qty IS NULL THEN 'NULL_TARGET' WHEN order_qty < 0 THEN 'NEGATIVE_TARGET' END")


def read_range(bq, end: date | None = None, conn=None) -> tuple[date, date]:
    """[start, end] read from BigQuery. start = data_policy.window_start_date (2026-01-01 by default) or a LATER
    bigquery.history_start_date; the old two-year look-back (initial_history_days) is no longer used, so no history
    before the data window is downloaded."""
    end = end or today_vn()
    floor = date.fromisoformat(ss.get("data_policy", conn).window_start_date)
    start = max(floor, date.fromisoformat(bq.history_start_date)) if bq.history_start_date else floor
    return start, end


def _src_cte(bq, with_refs: bool, start_param="start", end_param="end", distinct: bool = False,
             snap: dict | None = None, praw: bool = False) -> str:
    od = _order_date_expr(bq)
    key = _key_expr(snap) or "CAST(NULL AS STRING)"
    # _pend: the row is a pending order (PENDING_STATUSES), exempt from the exact-duplicate rule. praw (duplicate check
    # only): the WHOLE source row of a pending order as JSON, to count pending rows identical in every source column
    # (informative, never blocking); the source row has an alias for it
    rel, row = (_rel(bq, snap), "_user_sql") if _is_sql(snap) else (f"{_table_ref(bq)} AS _src_row", "_src_row")
    raw = f", {_pending_raw_expr(bq, row)} AS _praw" if praw else ""
    return (f"SELECT {'DISTINCT ' if distinct else ''}{_select_list(bq, with_refs)}, {od} AS _order_date, {key} AS _key, "
            f"{_pending_src_expr(bq)} AS _pend{raw} FROM {rel} WHERE {od} BETWEEN @{start_param} AND @{end_param}"
            f"{_partition_filter(bq, start_param, end_param, snap)}")


# ------------------------------------------------------------------ exact-duplicate gate (raw rows, BEFORE aggregation)
DUP_MAX_GROUPS = 100_000        # groups listed in the report; the counts are always complete
# Owner rules on the exact-duplicate gate:
# * 21/10/2026 (consolidated release 1.2.11, supersedes fix 7.1): a row of a PENDING order (order status
#   WAIT_TO_CONFIRM, with or without so_code) is EXEMPT from the duplicate rule - never blocking, never dropped by
#   DROP_EXACT, every row and its quantity kept; no order code is required or invented, rows are never merged, and a
#   repeated customer_id or other matching columns are no reason to reject them. They are counted apart (pending_orders
#   of the duplicate check), including the pending rows identical in the compared columns and those identical in EVERY
#   source column (a possible join fan-out, reported, not blocking). Read-only audits of 21/10/2026: 46 groups / 136
#   pending rows without so_code identical in the mapped columns, each row a different customer (separate orders).
# * Rows of every other status keep the exact-duplicate protection: identical in every COMPARED column = a duplicate.
#   The compared columns are the mapped columns except item_code (DUP_NOT_COMPARED_FIELDS): an item code (the SKU's
#   listing) is never a uniqueness criterion - two otherwise identical order lines that differ only in their item code
#   are duplicates (e.g. an order line fanned out over the SKU's listings by a join). No column is used as an order key.
# The status rule applies only when the order status (reference order_status) is mapped; otherwise every row is compared.
PENDING_STATUSES = ("WAIT_TO_CONFIRM",)
DUP_NOT_COMPARED_FIELDS = ("item_code",)


def _pending_cond(status: str) -> str:
    vals = ", ".join(f"'{s}'" for s in PENDING_STATUSES)
    return f"COALESCE(UPPER(TRIM(CAST({status} AS STRING))) IN ({vals}), FALSE)"


def _pending_expr(bq) -> str:
    """SQL boolean (never NULL) on the source aliases: the row is a pending order. FALSE when the order status is not
    mapped (then nothing changes)."""
    return _pending_cond("ref_order_status") if _ref_col(bq, "order_status") else "FALSE"


def _pending_src_expr(bq) -> str:
    """The same condition on the SOURCE column (inside the source relation of _src_cte)."""
    st = _ref_col(bq, "order_status")
    return _pending_cond(st) if st else "FALSE"


def _pending_raw_expr(bq, row: str) -> str:
    """SQL STRING in the source relation (`row` = its alias): the whole source row as JSON for a pending order, NULL
    for every other row; a constant NULL when the rule does not apply. The row never leaves BigQuery: it is only
    grouped / counted (pending rows identical in every source column, informative)."""
    st = _ref_col(bq, "order_status")
    if not st:
        return "CAST(NULL AS STRING)"
    return f"IF({_pending_cond(st)}, TO_JSON_STRING({row}), NULL)"


def _exact_dup_rows_expr(bq) -> str:
    """Extra exact-duplicate rows among the rows of the current FROM (columns: the source aliases + _pend): rows that
    are not pending orders and are identical in every compared column (dup_columns), NULL = NULL. The same rule as the
    gate (_dup_sql) and DROP_EXACT (_daily_sql)."""
    st = ", ".join(c["alias"] for c in dup_columns(bq))
    return f"COUNTIF(NOT _pend) - COUNT(DISTINCT IF(_pend, NULL, TO_JSON_STRING(STRUCT({st}))))"


def dup_columns(bq) -> list[dict]:
    """The columns the gate compares: every column read through the mapping (internal + reference fields) except
    DUP_NOT_COMPARED_FIELDS (item_code: never a uniqueness criterion). A mapped column that is missing from the source
    stops the run (require_mapping); it is never left out of the comparison silently (not_compared lists the rest)."""
    out = [{"field": f, "alias": f, "column": bq.field_mapping[f].column} for f in _mapped_internal(bq)]
    return out + [{"field": f, "alias": f"ref_{f}", "column": bq.reference_mapping[f].column} for f in _mapped_refs(bq)
                  if f not in DUP_NOT_COMPARED_FIELDS]


def require_mapping(bq, snap: dict | None) -> dict:
    """The saved mapping must match the LIVE source (table metadata, or the dry-run schema of the user SQL; no data is
    read): required fields mapped, every mapped column present with a compatible type. Otherwise BQ_MAPPING_INVALID
    with the list of fields."""
    sch = _output_columns(bq, snap)
    mc = validate_mapping(sch["columns"])
    if bq.customer_id_column:       # 1.2.9b: a mapped customer column must exist in the live source too
        from ..data import customers
        cerr = customers.check_column(sch["columns"], bq.customer_id_column)
        if cerr:
            mc = {**mc, "ok": False, "errors": mc["errors"] + cerr}
    if not mc["ok"]:
        raise AppError("BQ_MAPPING_INVALID", 422, detail=json.dumps(mc["errors"]))
    return {**sch, "mapping_check": mc}


def _dup_sql(bq, snap: dict | None, limit: int = DUP_MAX_GROUPS) -> str:
    """Exact duplicates = source rows equal in EVERY compared column (dup_columns: the mapped columns except item_code),
    found by GROUP BY on the native values (rule: dup_report.RULE_EN): NULL = NULL, numbers by value in their type,
    dates/times without time-zone conversion, strings exactly. No row is filtered out: a NULL so_code takes part like
    any value. Rows of a pending order (PENDING_STATUSES; the status is a compared column, so a group is all pending or
    all not) are exempt: never a duplicate group; pending_identical_* counts the pending rows identical in the compared
    columns and pending_whole_row_* those identical in every SOURCE column (informative). Groups are listed ordered by
    every compared column, so their numbering in the report is stable for the same data."""
    cols = ", ".join(c["alias"] for c in dup_columns(bq))
    nocode = "COUNTIF(_pend AND order_id IS NULL)" if _col(bq, "order_id") else "0"
    return f"""WITH src AS (
  {_src_cte(bq, True, snap=snap, praw=True)}
), g AS (
  SELECT {cols}, LOGICAL_OR(_pend) AS _pending, {nocode} AS _nocode, COUNT(*) AS _n,
    SUM(order_qty) AS _q FROM src GROUP BY {cols}
), pw AS (
  SELECT COUNTIF(_m > 1) AS pending_whole_row_groups, SUM(IF(_m > 1, _m, 0)) AS pending_whole_row_rows
  FROM (SELECT COUNT(*) AS _m FROM src WHERE _praw IS NOT NULL GROUP BY _praw)
)
SELECT SUM(_n) AS rows_checked, SUM(_q) AS qty_checked, COUNTIF(_n > 1 AND NOT _pending) AS duplicate_groups,
  SUM(IF(_n > 1 AND NOT _pending, _n, 0)) AS duplicate_rows, SUM(IF(_n > 1 AND NOT _pending, _n - 1, 0)) AS extra_duplicate_rows,
  SUM(IF(_pending, _n, 0)) AS pending_rows, SUM(IF(_pending, _q, 0)) AS pending_qty, SUM(_nocode) AS pending_without_code_rows,
  COUNTIF(_n > 1 AND _pending) AS pending_identical_groups, SUM(IF(_n > 1 AND _pending, _n, 0)) AS pending_identical_rows,
  ANY_VALUE(pw.pending_whole_row_groups) AS pending_whole_row_groups, ANY_VALUE(pw.pending_whole_row_rows) AS pending_whole_row_rows,
  ARRAY_AGG(IF(_n > 1 AND NOT _pending, STRUCT({cols}, _n AS _occurrences), NULL) IGNORE NULLS ORDER BY {cols} LIMIT {int(limit)}) AS _groups
FROM g CROSS JOIN pw"""


def _dup_finish(bq, snap: dict | None, start: date, end: date, rows: list[dict], columns: list[dict],
                context: str, est: int | None) -> dict:
    """Result of the duplicate query: counts, the groups, the report file when there are duplicates. The result
    (without the rows) is kept in sync_state 'bq_duplicate_check' for the BigQuery page."""
    r = rows[0] if rows else {}
    cols = dup_columns(bq)
    groups = [{"values": {c["alias"]: g.get(c["alias"]) for c in cols}, "occurrences": int(g.get("_occurrences") or 0)}
              for g in (r.get("_groups") or [])]
    used = {c["column"] for c in cols}
    n_groups = int(r.get("duplicate_groups") or 0)
    blocked = bool(n_groups) and bq.exact_duplicate_policy == "BLOCK"
    chk = {"rows_checked": int(r.get("rows_checked") or 0), "qty_checked": _num(r.get("qty_checked")),
           "duplicate_groups": n_groups, "duplicate_rows": int(r.get("duplicate_rows") or 0),
           "extra_duplicate_rows": int(r.get("extra_duplicate_rows") or 0), "groups": groups,
           "truncated": n_groups > len(groups), "columns": cols,
           "not_compared": [c["name"] for c in columns if c["name"] not in used],
           "range": {"start": str(start), "end": str(end)}, "context": context, "policy": bq.exact_duplicate_policy,
           "ingest_status": "BLOCKED" if blocked else ("PASSED" if not n_groups else bq.exact_duplicate_policy),
           "table": f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}",
           "source_label": (f"SQL v{snap.get('version_id')} ({(snap.get('sha256') or '')[:12]})" if _is_sql(snap)
                            else "TABLE"),
           "checked_at": now_iso(), "checked_at_vn": now_vn().strftime("%d/%m/%Y %H:%M:%S"), "estimated_bytes": est,
           # pending orders (PENDING_STATUSES), exempt from the rule: kept and counted apart, never in duplicate_groups.
           # identical_* = pending rows identical in the compared columns, whole_row_* = identical in EVERY source
           # column (a join fan-out would look like this: reported, not blocking - owner rule 21/10/2026)
           "pending_orders": {"applies": _pending_expr(bq) != "FALSE", "statuses": list(PENDING_STATUSES),
                              "exempt": True, "rows": int(r.get("pending_rows") or 0),
                              "qty": _num(r.get("pending_qty")) or 0.0,
                              "without_order_code_rows": int(r.get("pending_without_code_rows") or 0),
                              "identical_groups": int(r.get("pending_identical_groups") or 0),
                              "identical_rows": int(r.get("pending_identical_rows") or 0),
                              "whole_row_groups": int(r.get("pending_whole_row_groups") or 0),
                              "whole_row_rows": int(r.get("pending_whole_row_rows") or 0)}}
    if n_groups:
        chk["report"] = dup_report.write(chk)
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES ('bq_duplicate_check', ?, ?) "
                  "ON CONFLICT(name) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                  (json.dumps(dup_public(chk), default=str), now_iso()))
    return chk


def dup_public(chk: dict) -> dict:
    return {k: v for k, v in chk.items() if k != "groups"}


def dup_state() -> dict | None:
    with db.read() as c:
        r = db.one(c, "SELECT value_json FROM sync_state WHERE name='bq_duplicate_check'")
    return json.loads(r["value_json"]) if r else None


def duplicate_check(start: date, end: date, snap: dict | None = None, context: str = "",
                    columns: list[dict] | None = None) -> dict:
    """Exact duplicates of the raw source rows of [start, end] (one read-only query, dry-run first). Never blocks by
    itself; see duplicate_gate."""
    bq = ss.get("bigquery")
    _require_config(bq)
    snap = _snap(snap)
    if columns is None:
        columns = require_mapping(bq, snap)["columns"]
    res = _run(_client(bq), bq, "dup_check", _dup_sql(bq, snap), [("start", "DATE", start), ("end", "DATE", end)])
    return _dup_finish(bq, snap, start, end, res["rows"], columns, context, res["estimated_bytes"])


def _dup_detail(chk: dict) -> str:
    rep = chk.get("report") or {}
    where = rep.get("file") or ", ".join(rep.get("files") or []) or f"REPORT FAILED: {rep.get('error')}"
    if rep.get("format") == "csv":
        where = f"xlsx failed ({rep.get('xlsx_error')}); CSV: {where}"
    return (f"groups={chk['duplicate_groups']} rows={chk['duplicate_rows']} extra={chk['extra_duplicate_rows']} "
            f"range={chk['range']['start']}..{chk['range']['end']} report={where}")


def duplicate_gate(start: date, end: date, snap: dict | None = None, context: str = "",
                   columns: list[dict] | None = None) -> dict | None:
    """BLOCK policy (default): checked on the raw rows BEFORE any aggregation; duplicates -> report file +
    BQ_DATA_DUPLICATES, nothing else is read or written. KEEP / DROP_EXACT (explicit user choice) keep their 1.1.5
    behaviour and are not checked here."""
    bq = ss.get("bigquery")
    if bq.exact_duplicate_policy != "BLOCK":
        return None
    chk = duplicate_check(start, end, snap, context, columns)
    if chk["duplicate_groups"]:
        raise AppError("BQ_DATA_DUPLICATES", 409, detail=_dup_detail(chk), duplicate_check=dup_public(chk))
    return dup_public(chk)


def preview() -> dict:
    """Small sample (mapped + reference columns only, LIMIT preview_rows) + validation of that sample."""
    import pandas as pd
    from ..data.validation import normalize_and_validate
    bq = ss.get("bigquery")
    _require_config(bq)
    snap = _snap(None)
    client = _client(bq)
    end = today_vn()
    start = end - timedelta(days=7)
    od = _order_date_expr(bq)
    sql = (f"SELECT {_select_list(bq, with_refs=True)} FROM {_rel(bq, snap)} WHERE {od} BETWEEN @start AND @end"
           f"{_partition_filter(bq, 'start', 'end', snap)} LIMIT {int(min(bq.preview_rows, 500))}")
    res = _run(client, bq, "preview", sql, [("start", "DATE", start), ("end", "DATE", end)])
    df = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("ref_")} for r in res["rows"]])
    validation = None
    if len(df):
        _, _, validation = normalize_and_validate(df, naive_tz=timezone.utc if bq.created_at_is_utc else VN_TZ)
    return {"sql": sql, "estimated_bytes": res["estimated_bytes"], "limit": int(min(bq.preview_rows, 500)),
            "window": {"start": str(start), "end": str(end)}, "source": _public(snap),
            "rows": [_jsonable(r) for r in res["rows"]], "validation": validation}


def _jsonable(r: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in r.items()}


def _public(snap: dict | None) -> dict | None:
    return {k: v for k, v in snap.items() if k != "sql"} if snap else None


def estimate_daily_query(start: date, end: date) -> dict:
    bq = ss.get("bigquery")
    _require_config(bq)
    sql, params = _daily_sql(bq, start, end, _snap(None))
    res = _run(_client(bq), bq, "daily_estimate", sql, params, dry_run_only=True)
    return {"sql": sql, "estimated_bytes": res["estimated_bytes"], "start": str(start), "end": str(end)}


@_checked("profile", "profile")
def profile(days: int = 30) -> dict:
    """Quick data checks on the last `days` days: nulls, negatives, duplicates by grain, date range, freshness."""
    bq = ss.get("bigquery")
    _require_config(bq)
    snap = _snap(None)
    end = today_vn()
    start = end - timedelta(days=days)
    od = _order_date_expr(bq)
    sku, fc, qty, oid = _col(bq, "sku_id"), _col(bq, "fc_id"), _col(bq, "order_qty"), _col(bq, "order_id")
    grain = (f"CONCAT(CAST({oid} AS STRING),'|',CAST({sku} AS STRING),'|',CAST({fc} AS STRING),'|',CAST({od} AS STRING))"
             if oid else None)
    upd = _col(bq, "source_updated_at")
    sql = (f"SELECT COUNT(*) AS n_rows, COUNTIF({sku} IS NULL) AS null_sku, COUNTIF({fc} IS NULL) AS null_fc, "
           f"COUNTIF({qty} IS NULL) AS null_qty, COUNTIF({qty} < 0) AS negative_qty, "
           f"MIN({od}) AS min_date, MAX({od}) AS max_date, COUNT(DISTINCT {od}) AS n_days, "
           + (f"COUNT(*) - COUNT(DISTINCT {grain}) AS duplicate_grain_rows, " if grain else "NULL AS duplicate_grain_rows, ")
           + (f"MAX({upd}) AS max_source_updated_at " if upd else "NULL AS max_source_updated_at ")
           + f"FROM {_rel(bq, snap)} WHERE {od} BETWEEN @start AND @end{_partition_filter(bq, 'start', 'end', snap)}")
    res = _run(_client(bq), bq, "profile", sql, [("start", "DATE", start), ("end", "DATE", end)])
    row = res["rows"][0] if res["rows"] else {}
    row = _jsonable(row)
    blocking = []
    n = row.get("n_rows") or 0
    if n == 0:
        blocking.append("NO_DATA")
    for k in ("null_sku", "null_fc", "null_qty", "negative_qty"):
        if n and (row.get(k) or 0) / n > bq.max_null_share:
            blocking.append(k.upper())
    return {"window_days": days, "stats": row, "blocking_issues": blocking, "passed": not blocking,
            "estimated_bytes": res["estimated_bytes"], "source": _public(snap),
            "grain": "order_id × sku_id × fc_id × ngày" if grain else "full row"}


# ------------------------------------------------------------------ full-period validation
def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _validation_sqls(bq, start: date, end: date, snap: dict | None = None) -> dict[str, str]:
    refs = _mapped_refs(bq)
    al = _aliases(bq, with_refs=True)
    checked = (f"WITH src AS ({_src_cte(bq, True, snap=snap)}), checked AS (SELECT {', '.join(al)}, _order_date, _key, "
               f"_pend, {_REASON} AS _reason FROM src)")
    upd = "source_updated_at" if _col(bq, "source_updated_at") else None
    excl = "".join(f"COUNTIF(_reason = '{r}') AS excl_rows_{r.lower()}, "
                   f"SUM(IF(_reason = '{r}', order_qty, 0)) AS excl_qty_{r.lower()}, " for r in EXCLUSION_REASONS)
    ref_parts = ""
    for f in refs:
        ref_parts += f", COUNTIF(ref_{f} IS NOT NULL) AS ref_{f}_non_null"
        if f in REF_NUMERIC:
            ref_parts += (f", SUM(ref_{f}) AS ref_{f}_sum, SUM(IF(_reason IS NULL, ref_{f}, NULL)) AS ref_{f}_sum_valid, "
                          f"COUNTIF(ref_{f} < 0) AS ref_{f}_negative")
            if f == "open_hours":       # 1.2.9: hours of one day: 0..24 (data/open_hours.py)
                ref_parts += (f", COUNTIF(ref_{f} > {open_hours.MAX_HOURS:g}) AS ref_{f}_above_max, "
                              f"MIN(ref_{f}) AS ref_{f}_min, MAX(ref_{f}) AS ref_{f}_max")
        else:
            ref_parts += f", COUNT(DISTINCT CAST(ref_{f} AS STRING)) AS ref_{f}_distinct"
    dup_key = ("COUNT(*) - COUNT(DISTINCT _key) AS duplicate_key_rows" if _key_expr(snap)
               else "NULL AS duplicate_key_rows")
    summary = (f"{checked}\nSELECT COUNT(*) AS n_rows, COUNTIF(_reason IS NULL) AS rows_valid, {excl}"
               f"SUM(order_qty) AS qty_read, SUM(IF(_reason IS NULL, order_qty, 0)) AS qty_valid, "
               f"COUNTIF(order_qty = 0) AS zero_target_rows, MAX(order_qty) AS max_qty, "
               f"APPROX_QUANTILES(order_qty, 100)[SAFE_OFFSET(99)] AS p99_qty, "
               f"MIN(_order_date) AS min_date, MAX(_order_date) AS max_date, COUNT(DISTINCT _order_date) AS n_days, "
               f"COUNT(DISTINCT sku_id) AS n_sku, COUNT(DISTINCT fc_id) AS n_fc, "
               f"COUNT(DISTINCT CONCAT(CAST(sku_id AS STRING), '|', CAST(fc_id AS STRING))) AS n_series, "
               f"{_exact_dup_rows_expr(bq)} AS exact_duplicate_rows, {dup_key}, "
               + (f"MAX(source_updated_at) AS max_source_updated_at" if upd else "NULL AS max_source_updated_at")
               + f"{ref_parts}\nFROM checked AS c0")
    days = (f"{checked}\nSELECT _order_date AS d, CAST(fc_id AS STRING) AS fc_id, COUNT(*) AS n_rows, "
            f"COUNTIF(_reason IS NULL) AS rows_valid, SUM(IF(_reason IS NULL, order_qty, 0)) AS qty_valid "
            f"FROM checked GROUP BY 1, 2")
    out = {"validate_summary": summary, "validate_days": days, "validate_duplicates": _dup_sql(bq, snap)}
    cats = [f for f in refs if f in REF_CATEGORY]
    if cats:
        parts = [f"SELECT '{f}' AS field, CAST(ref_{f} AS STRING) AS value, COUNT(*) AS n_rows, "
                 f"SUM(IF(_reason IS NULL, order_qty, 0)) AS qty_valid FROM checked GROUP BY 1, 2" for f in cats]
        out["validate_categories"] = f"{checked}\n" + "\nUNION ALL\n".join(parts) + "\nORDER BY field, n_rows DESC LIMIT 200"
    raw = _raw_date_col(bq)
    out["validate_null_date"] = f"SELECT COUNT(*) AS n FROM {_rel(bq, snap)} WHERE {raw} IS NULL"
    return out


def _analyse(bq, start: date, end: date, s: dict, days: list[dict], cats: list[dict], null_date: int,
             drift: dict | None, mapping_check: dict, snap: dict | None = None, dup: dict | None = None) -> dict:
    n = int(s.get("n_rows") or 0)
    blocking, warnings = [], []
    if not mapping_check.get("ok", True):
        blocking.append({"code": "MAPPING_INVALID", "detail": mapping_check.get("errors")})
    if drift:
        mapped_cols = {m.column for m in list(bq.field_mapping.values()) + list(bq.reference_mapping.values())
                       if m.column and m.usage != "UNUSED"}
        hit = sorted((set(drift.get("removed", [])) | set(drift.get("type_changed", []))) & mapped_cols)
        if hit:
            blocking.append({"code": "SCHEMA_CHANGED", "detail": hit})
    if n == 0:
        blocking.append({"code": "NO_DATA", "detail": f"{start}..{end}"})
    excl = {r: {"rows": int(s.get(f"excl_rows_{r.lower()}") or 0), "qty": _num(s.get(f"excl_qty_{r.lower()}")) or 0.0}
            for r in EXCLUSION_REASONS}
    for r, v in excl.items():
        if n and v["rows"] / n > bq.max_null_share:
            blocking.append({"code": r, "detail": {"rows": v["rows"], "share": v["rows"] / n, "max": bq.max_null_share}})
        elif v["rows"]:
            warnings.append({"code": f"EXCLUDED_{r}", "detail": v})
    total_with_null_date = n + null_date
    if null_date:
        share = null_date / total_with_null_date
        (blocking if share > bq.max_null_share else warnings).append(
            {"code": "NULL_DATE", "detail": {"rows": null_date, "share": share}})
    # exact duplicates: groups / rows / extra rows of the duplicate query (identical in every mapped column)
    extra = dup["extra_duplicate_rows"] if dup and dup.get("rows_checked") else int(s.get("exact_duplicate_rows") or 0)
    if extra:
        detail = {"rows": extra, "policy": bq.exact_duplicate_policy}
        if dup and dup.get("rows_checked"):
            detail.update(groups=dup["duplicate_groups"], rows_in_groups=dup["duplicate_rows"],
                          report=dup.get("report"))
        item = {"code": "EXACT_DUPLICATES", "detail": detail}
        (blocking if bq.exact_duplicate_policy == "BLOCK" else warnings).append(item)
    # candidate unique key (configured on the SQL page): duplicates mean the grain is not proven -> block writes
    keys = (snap or {}).get("key_columns") or []
    kpol = (snap or {}).get("key_duplicate_policy", "BLOCK")
    dk = s.get("duplicate_key_rows")
    if not keys:
        (blocking if kpol == "BLOCK" else warnings).append({"code": "KEY_NOT_CONFIGURED", "detail": None})
    elif dk:
        (blocking if kpol == "BLOCK" else warnings).append(
            {"code": "KEY_NOT_UNIQUE", "detail": {"rows": int(dk), "key": keys, "policy": kpol}})
    rows_valid = int(s.get("rows_valid") or 0)
    qty_read = _num(s.get("qty_read")) or 0.0
    qty_valid = _num(s.get("qty_valid")) or 0.0
    rows_excl = sum(v["rows"] for v in excl.values())
    qty_excl = sum(v["qty"] for v in excl.values())
    rec_rows_ok = n == rows_valid + rows_excl
    rec_qty_ok = abs(qty_read - (qty_valid + qty_excl)) <= 1e-6 * max(1.0, abs(qty_read))
    if not (rec_rows_ok and rec_qty_ok):
        blocking.append({"code": "RECONCILIATION_FAILED", "detail": {"rows": [n, rows_valid, rows_excl],
                                                                     "qty": [qty_read, qty_valid, qty_excl]}})
    # calendar coverage: a day without ANY row is "missing data" (unknown), never "zero demand"
    by_day: dict[str, int] = {}
    by_day_qty: dict[str, float] = {}
    fc_days: dict[str, set] = {}
    for r in days:
        d = str(r["d"])[:10]
        by_day[d] = by_day.get(d, 0) + int(r.get("n_rows") or 0)
        by_day_qty[d] = by_day_qty.get(d, 0.0) + (_num(r.get("qty_valid")) or 0.0)
        if r.get("fc_id") is not None:
            fc_days.setdefault(str(r["fc_id"]), set()).add(d)
    last = min(end, today_vn())
    cal = [str(start + timedelta(days=i)) for i in range((last - start).days + 1)]
    missing = [d for d in cal if d not in by_day]
    if missing:
        warnings.append({"code": "MISSING_DAYS", "detail": {"count": len(missing), "first": missing[:31]}})
    fc_gaps = []
    for fc, ds in fc_days.items():
        lo, hi = min(ds), max(ds)
        gaps = [d for d in cal if lo <= d <= hi and d not in ds and d in by_day]
        if gaps:
            fc_gaps.append({"fc_id": fc, "days_without_rows": len(gaps), "first": gaps[:10]})
    fc_gaps.sort(key=lambda x: -x["days_without_rows"])
    if fc_gaps:
        warnings.append({"code": "FC_DAYS_WITHOUT_ROWS", "detail": {"fcs": len(fc_gaps)}})
    mx, p99 = _num(s.get("max_qty")), _num(s.get("p99_qty"))
    if mx is not None and p99 is not None and mx > 100 * max(p99, 1.0):
        warnings.append({"code": "TARGET_OUTLIER", "detail": {"max": mx, "p99": p99}})
    max_date = s.get("max_date")
    max_date = str(max_date)[:10] if max_date else None
    pol = ss.get("data_policy")
    if max_date:
        lag = (today_vn() - date.fromisoformat(max_date)).days
        if lag > pol.max_data_lag_days:
            warnings.append({"code": "STALE_SOURCE", "detail": {"max_date": max_date, "lag_days": lag}})
    min_date = str(s.get("min_date"))[:10] if s.get("min_date") else None
    if min_date and date.fromisoformat(min_date) > start + timedelta(days=7):
        warnings.append({"code": "STARTS_AFTER_HISTORY_START", "detail": {"min_date": min_date, "history_start": str(start)}})
    refs = {}
    for f in _mapped_refs(bq):
        nn = int(s.get(f"ref_{f}_non_null") or 0)
        refs[f] = {"column": bq.reference_mapping[f].column, "non_null": nn, "share": (nn / n) if n else None,
                   "sum": _num(s.get(f"ref_{f}_sum")), "sum_valid": _num(s.get(f"ref_{f}_sum_valid")),
                   "negative": s.get(f"ref_{f}_negative"), "distinct": s.get(f"ref_{f}_distinct")}
        if f in ("sales_price", "price_after_discount") and (s.get(f"ref_{f}_negative") or 0) > 0:
            warnings.append({"code": "NEGATIVE_PRICE", "detail": {"field": f, "rows": s.get(f"ref_{f}_negative")}})
    oh = refs.get("open_hours")
    if oh is not None:
        # 1.2.9: mandatory model input. Reported here (counts only); the training of the BIGQUERY source stops while a
        # demand row of its window has no valid value (OPEN_HOURS_INVALID) - the D-1 load of the demand is not blocked
        oh.update(min=_num(s.get("ref_open_hours_min")), max=_num(s.get("ref_open_hours_max")),
                  above_max=s.get("ref_open_hours_above_max"))
        if n and oh["non_null"] < n:
            warnings.append({"code": "OPEN_HOURS_MISSING", "detail": {"rows": n - oh["non_null"],
                                                                       "share": (n - oh["non_null"]) / n}})
        out_of_range = int(oh.get("negative") or 0) + int(oh.get("above_max") or 0)
        if out_of_range:
            warnings.append({"code": "OPEN_HOURS_OUT_OF_RANGE", "detail": {"rows": out_of_range, "min": oh["min"],
                                                                            "max": oh["max"]}})
    outbound = None
    if "outbound_qty" in refs:
        ob = refs["outbound_qty"]["sum_valid"]
        outbound = {"sum_demand_valid": qty_valid, "sum_outbound_valid": ob,
                    "ratio_outbound_to_demand": (ob / qty_valid) if ob is not None and qty_valid else None,
                    "note": "Chỉ để đối chiếu; target vẫn là cột đã ánh xạ cho order_qty."}
    categories: dict[str, list] = {}
    for r in cats:
        categories.setdefault(r["field"], []).append({"value": r.get("value"), "rows": int(r.get("n_rows") or 0),
                                                      "qty_valid": _num(r.get("qty_valid"))})
    stats = {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in s.items()
             if not k.startswith(("excl_", "ref_"))}
    return {
        "range": {"start": str(start), "end": str(end)}, "stats": stats,
        "reconciliation": {"rows_read": n, "rows_valid": rows_valid, "rows_excluded": rows_excl,
                           "rows_null_date_outside_range": null_date, "qty_read": qty_read, "qty_valid": qty_valid,
                           "qty_excluded": qty_excl, "rows_ok": rec_rows_ok, "qty_ok": rec_qty_ok},
        "exclusions": excl, "missing_days": {"count": len(missing), "days": missing[:120]},
        "per_day": [{"date": d, "rows": by_day[d], "qty_valid": by_day_qty[d]} for d in sorted(by_day)],
        "fc_gaps": fc_gaps[:30], "categories": categories, "reference_completeness": refs, "outbound_vs_demand": outbound,
        "key_check": {"key_columns": keys, "duplicate_key_rows": dk, "policy": kpol},
        "duplicate_check": dup_public(dup) if dup else None,
        "blocking_issues": blocking, "warnings": warnings, "passed": not blocking,
        "grain": {"source_rows": "1 dòng nguồn = 1 dòng của bảng/SQL (không đổi)",
                  "target": "SKU × FC × ngày; qty = Σ order_qty của các dòng hợp lệ",
                  "duplicate_policy": bq.exact_duplicate_policy},
    }


def _output_columns(bq, snap: dict) -> dict:
    """Columns available to the app: table schema (metadata, no cost) or the dry-run schema of the user SQL."""
    if _is_sql(snap):
        dr = sql_dry_run(snap["sql"])
        return {"columns": dr["columns"], "drift": None, "dry_run": dr}
    return read_schema()


def _run_validation(bq, snap: dict, start: date, end: date) -> dict:
    sch = require_mapping(bq, snap)
    mcheck = sch["mapping_check"]
    names = {c["name"] for c in sch["columns"]}
    miss = [k for k in snap.get("key_columns") or [] if k not in names]
    if miss:
        raise AppError("BQ_MAPPING_INVALID", 422, detail=json.dumps([{"code": "KEY_COLUMN_NOT_FOUND", "columns": miss}]))
    client = _client(bq)
    sqls = _validation_sqls(bq, start, end, snap)
    params = [("start", "DATE", start), ("end", "DATE", end)]
    # every query is dry-run first; refuse the whole validation if the total would exceed the limit
    est = {k: _run(client, bq, k, q, params if "@start" in q else None, dry_run_only=True)["estimated_bytes"]
           for k, q in sqls.items()}
    if sum(est.values()) > bq.maximum_bytes_billed:
        raise AppError("BQ_QUERY_TOO_EXPENSIVE", 413, detail=f"{sum(est.values())} bytes > {bq.maximum_bytes_billed}",
                       estimated_bytes=sum(est.values()))
    t0 = time.monotonic()
    res = {k: _run(client, bq, k, q, params if "@start" in q else None) for k, q in sqls.items()}
    summary = res["validate_summary"]["rows"][0] if res["validate_summary"]["rows"] else {}
    null_date = int((res["validate_null_date"]["rows"] or [{}])[0].get("n") or 0)
    dup = _dup_finish(bq, snap, start, end, res["validate_duplicates"]["rows"], sch["columns"],
                      "validate_source", est["validate_duplicates"])
    out = _analyse(bq, start, end, summary, res["validate_days"]["rows"],
                   res.get("validate_categories", {}).get("rows", []), null_date, sch.get("drift"), mcheck, snap, dup)
    out.update(checked_at=now_iso(), estimated_bytes=sum(est.values()), estimated_bytes_by_query=est,
               seconds=round(time.monotonic() - t0, 2), table=f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}",
               mapping_warnings=mcheck["warnings"], source=_public(snap), output_columns=sch["columns"],
               target={"field": "order_qty", "column": bq.field_mapping["order_qty"].column})
    return out


def validate_source() -> dict:
    """Full-period, read-only validation of the mapped history feed (history_start_date .. today). Stores the result
    for the current mapping hash; production mode, D-1 sync and training require a passing result for that hash."""
    bq = ss.get("bigquery")
    _require_config(bq)
    try:
        snap = _snap(None)
        start, end = read_range(bq)
        out = _run_validation(bq, snap, start, end)
        out["mapping_hash"] = mapping_hash(bq)
    except AppError as e:
        _store_validation({"passed": False, "checked_at": now_iso(), "mapping_hash": mapping_hash(bq), "error": e.to_dict()})
        _set_status("validation", False, error=e.to_dict())
        raise
    _store_validation(out)
    _set_status("validation", out["passed"], mapping_hash=out["mapping_hash"],
                blocking_issues=[b["code"] for b in out["blocking_issues"]])
    return out


def _store_validation(v: dict) -> None:
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES ('bq_validation', ?, ?) "
                  "ON CONFLICT(name) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                  (json.dumps(v, default=str), now_iso()))
        db.audit(c, "BQ_VALIDATION", "settings", "bigquery",
                 {"passed": v.get("passed"), "mapping_hash": v.get("mapping_hash"),
                  "blocking": [b["code"] for b in v.get("blocking_issues", [])] or (v.get("error") or {}).get("code")})


def validation_state(conn=None) -> dict | None:
    def _q(c):
        r = c.execute("SELECT value_json FROM sync_state WHERE name='bq_validation'").fetchone()
        return json.loads(r[0]) if r else None
    if conn is not None:
        return _q(conn)
    with db.read() as c:
        return _q(c)


def validation_ok_for_current(conn=None) -> bool:
    v = validation_state(conn)
    bq = ss.get("bigquery", conn)
    return bool(v and v.get("passed") and v.get("mapping_hash") == mapping_hash(bq, conn))


# ------------------------------------------------------------------ daily load
def _daily_sql(bq, start: date, end: date, snap: dict | None = None) -> tuple[str, list]:
    # reference columns are read too, so "exact duplicate" means the same thing as in validate_source and the gate:
    # identical in EVERY compared column (dup_columns: key + reference, except item_code), not only in the key columns;
    # a pending order (PENDING_STATUSES, _pend) is exempt: never counted as a duplicate, never dropped by DROP_EXACT
    al = _aliases(bq, with_refs=True)
    drop = bq.exact_duplicate_policy == "DROP_EXACT"
    fnull = "CAST(NULL AS FLOAT64)"   # typed NULLs keep the UNION ALL column types unambiguous
    up = "unit_price" if _col(bq, "unit_price") else fnull
    disc = "discount_amount" if _col(bq, "discount_amount") else fnull
    pf = "CAST(promotion_flag AS INT64)" if _col(bq, "promotion_flag") else fnull
    vf = "CAST(voucher_flag AS INT64)" if _col(bq, "voucher_flag") else fnull
    oid = "order_id" if _col(bq, "order_id") else "CAST(NULL AS STRING)"
    upd = "source_updated_at" if _col(bq, "source_updated_at") else "CAST(NULL AS TIMESTAMP)"
    bid = "batch_id" if _col(bq, "batch_id") else "CAST(NULL AS STRING)"
    # 1.2.9: SKU open hours (mandatory REQUIRED_FEATURE): lines without a value + MIN / MAX per day x SKU x FC. Python
    # turns them into a value or a status (data/open_hours.cell); no aggregation rule is invented for differing lines
    oh = ("COUNTIF(ref_open_hours IS NULL) AS open_hours_null_rows, MIN(ref_open_hours) AS open_hours_min, "
          "MAX(ref_open_hours) AS open_hours_max") if _ref_col(bq, "open_hours") else (
        "CAST(NULL AS INT64) AS open_hours_null_rows, CAST(NULL AS FLOAT64) AS open_hours_min, "
        "CAST(NULL AS FLOAT64) AS open_hours_max")
    # 1.2.9b: open hours are measured per item (listing of the SKU) and day: distinct items with a value, distinct
    # (item, value) pairs and lines with a value but no item code tell "one value per item" (MULTI_ITEM) from a real
    # disagreement (CONFLICT); only counts leave BigQuery
    oh += (", COUNT(DISTINCT IF(ref_open_hours IS NULL, NULL, CAST(ref_item_code AS STRING))) AS open_hours_items, "
           "COUNT(DISTINCT IF(ref_open_hours IS NULL OR ref_item_code IS NULL, NULL, CONCAT(CAST(ref_item_code AS STRING), "
           "'|', CAST(ref_open_hours AS STRING)))) AS open_hours_item_values, "
           "COUNTIF(ref_open_hours IS NOT NULL AND ref_item_code IS NULL) AS open_hours_no_item_rows"
           ) if _ref_col(bq, "open_hours") and _ref_col(bq, "item_code") else (
        ", CAST(NULL AS INT64) AS open_hours_items, CAST(NULL AS INT64) AS open_hours_item_values, "
        "CAST(NULL AS INT64) AS open_hours_no_item_rows")
    cols = ", ".join(al) + ", _order_date, _key"
    kept = f"SELECT {cols} FROM src"
    if drop:
        # one row per group of identical compared columns among the non-pending rows (the first by its full value, so
        # the result is deterministic); every pending row is kept. PARTITION BY a STRING (FLOAT64 is not allowed there)
        cmp = ", ".join(c["alias"] for c in dup_columns(bq))
        kept = (f"SELECT {cols} FROM src WHERE _pend UNION ALL SELECT {cols} FROM (SELECT {cols}, ROW_NUMBER() OVER ("
                f"PARTITION BY TO_JSON_STRING(STRUCT({cmp})) ORDER BY TO_JSON_STRING(STRUCT({cols}))) AS _rn "
                f"FROM src WHERE NOT _pend) WHERE _rn = 1")
    nulls = "CAST(NULL AS DATE), CAST(NULL AS STRING), CAST(NULL AS STRING)"
    keydup = "CAST(COUNT(*) - COUNT(DISTINCT _key) AS STRING)" if _key_expr(snap) else "'NO_KEY'"
    valid = f"""SELECT 'VALID' AS _kind, CAST(NULL AS STRING) AS _reason, _order_date AS order_date, CAST(sku_id AS STRING) AS sku_id,
  CAST(fc_id AS STRING) AS fc_id, SUM(order_qty) AS qty, COUNT(DISTINCT CAST({oid} AS STRING)) AS n_orders,
  SAFE_DIVIDE(SUM({up} * order_qty), SUM(IF({up} IS NULL, NULL, order_qty))) AS avg_unit_price,
  SAFE_DIVIDE(SUM({disc}), SUM({up} * order_qty)) AS avg_discount_rate,
  AVG({pf}) AS promo_share, AVG({vf}) AS voucher_share,
  MAX({upd}) AS max_source_updated_at, MAX(CAST({bid} AS STRING)) AS max_batch_id, COUNT(*) AS n_rows,
  {oh}
FROM checked WHERE _reason IS NULL GROUP BY 3, 4, 5"""
    params = [("start", "DATE", start), ("end", "DATE", end)]
    extra_ctes, more_nulls = "", ""
    if bq.customer_id_column:
        # 1.2.9b: customer counts per day x SKU x FC (data/customers.py), joined to the valid aggregate; the identifier
        # stays inside BigQuery. Only when the owner mapped a customer column
        from ..data import customers
        extra_ctes = f""",
{_customer_ctes(bq, snap)},
valid AS (
{valid}
)"""
        valid = ("SELECT valid.*, cust.customer_count, cust.repeat_customer_count, cust.repeat_interval_days_sum "
                 "FROM valid LEFT JOIN cust ON cust.d = valid.order_date AND cust.sku_id = valid.sku_id "
                 "AND cust.fc_id = valid.fc_id")
        more_nulls = ", NULL, NULL, NULL"
        params.append(("cust_start", "DATE", start - timedelta(days=customers.REPEAT_LOOKBACK_DAYS)))
    sql = f"""WITH src AS (
  {_src_cte(bq, True, snap=snap)}
), kept AS (
  {kept}
), checked AS (
  SELECT {cols}, {_REASON} AS _reason FROM kept
){extra_ctes}
{valid}
UNION ALL
SELECT 'EXCLUDED', _reason, {nulls}, SUM(order_qty), NULL, NULL, NULL, NULL, NULL, NULL, NULL, COUNT(*), NULL, NULL, NULL,
  NULL, NULL, NULL{more_nulls}
FROM checked WHERE _reason IS NOT NULL GROUP BY 2
UNION ALL
SELECT 'TOTAL_READ', CAST({_exact_dup_rows_expr(bq)} AS STRING), {nulls}, SUM(order_qty),
  NULL, NULL, NULL, NULL, NULL, NULL, NULL, COUNT(*), NULL, NULL, NULL, NULL, NULL, NULL{more_nulls} FROM src AS s
UNION ALL
SELECT 'TOTAL_KEPT', {keydup}, {nulls}, SUM(order_qty), NULL, NULL, NULL, NULL, NULL, NULL, NULL, COUNT(*),
  NULL, NULL, NULL, NULL, NULL, NULL{more_nulls} FROM kept"""
    return sql, params


def _customer_ctes(bq, snap: dict | None) -> str:
    """1.2.9b: per day x SKU x FC of [@start, @end] - distinct customers, repeat customers (an earlier order day of the
    same SKU x FC within REPEAT_LOOKBACK_DAYS) and the sum of their days since that order (data/customers.py). Same
    source relation, day expression and valid-line rule as the demand; empty / blank identifiers are no customer. Only
    the counts (cte `cust`) are joined to the output: no identifier is selected out of BigQuery."""
    from ..data import customers
    od = _order_date_expr(bq)
    sku, fc, qty = _col(bq, "sku_id"), _col(bq, "fc_id"), _col(bq, "order_qty")
    lb = customers.REPEAT_LOOKBACK_DAYS
    return f"""cust_src AS (
  SELECT DISTINCT {od} AS d, CAST({sku} AS STRING) AS sku_id, CAST({fc} AS STRING) AS fc_id,
    NULLIF(TRIM(CAST(`{bq.customer_id_column}` AS STRING)), '') AS cid
  FROM {_rel(bq, snap)} WHERE {od} BETWEEN @cust_start AND @end{_partition_filter(bq, "cust_start", "end", snap)}
    AND {sku} IS NOT NULL AND {fc} IS NOT NULL AND {qty} IS NOT NULL AND {qty} >= 0
), cust_seq AS (
  SELECT d, sku_id, fc_id, LAG(d) OVER (PARTITION BY cid, sku_id, fc_id ORDER BY d) AS prev_d
  FROM cust_src WHERE cid IS NOT NULL
), cust AS (
  SELECT d, sku_id, fc_id, COUNT(*) AS customer_count,
    COUNTIF(prev_d >= DATE_SUB(d, INTERVAL {lb} DAY)) AS repeat_customer_count,
    SUM(IF(prev_d >= DATE_SUB(d, INTERVAL {lb} DAY), DATE_DIFF(d, prev_d, DAY), 0)) AS repeat_interval_days_sum
  FROM cust_seq WHERE d BETWEEN @start AND @end GROUP BY 1, 2, 3
)"""


def _key_gate(snap: dict | None, key_dups: str | None, where: str) -> int | None:
    """Writes are blocked while the candidate key is not proven unique, unless the user chose SUM_ALL."""
    pol = (snap or {}).get("key_duplicate_policy", "BLOCK")
    if key_dups in (None, "NO_KEY"):
        if pol == "BLOCK":
            raise AppError("BQ_KEY_NOT_UNIQUE", 409, detail=f"{where}: no candidate key configured")
        return None
    n = int(key_dups or 0)
    if n and pol == "BLOCK":
        raise AppError("BQ_KEY_NOT_UNIQUE", 409, detail=f"{where}: {n} rows share a key {snap.get('key_columns')}")
    return n


def fetch_daily(start: date, end: date, snap: dict | None = None, context: str = "", prechecked: bool = False) -> dict:
    """Aggregated SKU × FC × day rows + a full reconciliation of what was read, kept, excluded (by reason).
    Order: mapping vs live source, exact-duplicate gate on the RAW rows (BLOCK: report + stop), then the aggregation
    (`prechecked`: the caller already ran the first two steps on the same window and snapshot)."""
    bq = ss.get("bigquery")
    _require_config(bq)
    snap = _snap(snap)
    floor, _ = read_range(bq, end)
    start = max(start, floor)
    if not prechecked:
        cols = require_mapping(bq, snap)["columns"]
        duplicate_gate(start, end, snap, context, cols)
    sql, params = _daily_sql(bq, start, end, snap)
    res = _run(_client(bq), bq, "daily", sql, params)
    rows = res["rows"]
    kind = lambda r: r.get("_kind") or ("VALID" if r.get("sku_id") is not None else "EXCLUDED")  # noqa: E731
    good = [r for r in rows if kind(r) == "VALID"]
    excluded = {}
    for r in rows:
        if kind(r) == "EXCLUDED":
            k = r.get("_reason") or "UNKNOWN"
            excluded[k] = {"rows": int(r.get("n_rows") or 0), "qty": _num(r.get("qty")) or 0.0}
    tot = next((r for r in rows if kind(r) == "TOTAL_READ"), None)
    kept = next((r for r in rows if kind(r) == "TOTAL_KEPT"), None)
    valid_rows = sum(int(r.get("n_rows") or 0) for r in good)
    valid_qty = sum(_num(r.get("qty")) or 0.0 for r in good)
    excl_rows = sum(v["rows"] for v in excluded.values())
    excl_qty = sum(v["qty"] for v in excluded.values())
    rows_read = int(tot["n_rows"]) if tot else valid_rows + excl_rows
    qty_read = (_num(tot.get("qty")) or 0.0) if tot else valid_qty + excl_qty
    dup_rows = int(tot.get("_reason") or 0) if tot else 0
    rows_kept = int(kept["n_rows"]) if kept else rows_read
    qty_kept = (_num(kept.get("qty")) or 0.0) if kept else qty_read
    if dup_rows and bq.exact_duplicate_policy == "BLOCK":
        raise AppError("BQ_DATA_DUPLICATES", 409, detail=f"{dup_rows} exact duplicate rows in {start}..{end}")
    key_dups = _key_gate(snap, kept.get("_reason") if kept else "0", f"history {start}..{end}")
    ok = rows_kept == valid_rows + excl_rows and abs(qty_kept - (valid_qty + excl_qty)) <= 1e-6 * max(1.0, abs(qty_kept))
    if not ok:
        raise AppError("BQ_SYNC_RECONCILIATION_FAILED", 409,
                       detail=f"kept {rows_kept}/{qty_kept} != valid {valid_rows}/{valid_qty} + excluded {excl_rows}/{excl_qty}")
    ups = [r["max_source_updated_at"] for r in good if r.get("max_source_updated_at")]
    bids = [r["max_batch_id"] for r in good if r.get("max_batch_id")]
    return {"rows": good, "rows_read": rows_read, "rows_valid": valid_rows, "rows_error": excl_rows,
            "rows_dropped_duplicates": rows_read - rows_kept, "qty_read": qty_read, "qty_valid": valid_qty,
            "qty_excluded": excl_qty, "qty_dropped_duplicates": qty_read - qty_kept, "exact_duplicate_rows": dup_rows,
            "key_duplicate_rows": key_dups, "excluded_by_reason": excluded, "window": {"start": str(start), "end": str(end)},
            "source": _public(snap), "max_source_updated_at": str(max(ups)) if ups else None,
            "source_batch_id": max(bids) if bids else None, "estimated_bytes": res["estimated_bytes"]}


# ------------------------------------------------------------------ D0 (today)
def fetch_d0(day: date, cutoff=None, snap: dict | None = None) -> dict:
    """Cumulative quantity per SKU x FC for `day` (1.2.1: the D-0 feed's own mapping, see d0_feed). `cutoff` is kept
    for callers of the 1.2.0 signature; the Vietnam day filter decides which rows count."""
    from . import d0_feed
    bq = ss.get("bigquery")
    _require_config(bq, table=False)
    return d0_feed.fetch(day, snap if snap is not None else d0_feed.snapshot())


# ------------------------------------------------------------------ SQL editor: dry run, validation, preview, test
def sql_dry_run(sql: str) -> dict:
    """BigQuery dry run of the user text as written (a dry run never executes anything). Returns the statement type,
    the bytes it would scan, the output schema and the tables it reads."""
    bq = ss.get("bigquery")
    _require_config(bq, table=False)
    chk = sql_guard.check(sql)
    if not chk["ok"]:
        raise AppError("SQL_REJECTED", 422, detail=json.dumps(chk["errors"]))
    client = _client(bq)
    text = f"-- df:sql_dry_run\n{sql}"
    try:
        if _client_factory is None:
            from google.cloud import bigquery
            dj = client.query(text, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
        else:
            dj = client.query(text, job_config={"dry_run": True, "params": None})
    except Exception as e:
        err = _map_error(e)
        if err.code == "BQ_AUTH_EXPIRED" and bq.oauth_enabled:
            oauth.mark_revoked(err.detail)
        raise err from e
    schema = getattr(dj, "schema", None) or []
    return {"statement_type": getattr(dj, "statement_type", None), "estimated_bytes": int(dj.total_bytes_processed or 0),
            "columns": [{"name": f.name, "type": str(f.field_type).upper()} for f in schema],
            "referenced_tables": [str(getattr(t, "path", None) or t) for t in (getattr(dj, "referenced_tables", None) or [])]}


def _version_snap(kind: str, vid: int) -> dict:
    from . import sql_sources
    src = sql_sources.source(kind)
    v = sql_sources.version(src, vid)
    return {"mode": "SQL", "kind": kind, "version_id": v.id, "sha256": v.sha256, "sql": v.sql,
            "key_columns": sql_sources.effective_keys(src, kind), "key_duplicate_policy": src.key_duplicate_policy}


def validate_sql_version(kind: str, vid: int) -> dict:
    """Dry run + output checks. VALID activates the version; INVALID keeps the previously active one.
    1.2.1: a D-0 version is checked against the D-0 mapping and executed for today (d0_feed.validate_version)."""
    from . import sql_sources
    if kind == "d0":
        from . import d0_feed
        return d0_feed.validate_version(vid)
    bq = ss.get("bigquery")
    snap = _version_snap(kind, vid)
    result: dict = {"checked_at": now_iso(), "static_check": sql_guard.check(snap["sql"])}
    try:
        dr = sql_dry_run(snap["sql"])
        result.update({k: dr[k] for k in ("statement_type", "estimated_bytes", "columns", "referenced_tables")})
        if dr["statement_type"] != "SELECT":
            raise AppError("SQL_NOT_A_QUERY", 422, detail=str(dr["statement_type"]))
        names = {c["name"] for c in dr["columns"]}
        need = [c for c in sql_sources.required_columns(kind) if c not in names]
        keys = [k for k in snap["key_columns"] if k not in names]
        if need or keys:
            raise AppError("SQL_OUTPUT_MISSING_COLUMNS", 422,
                           detail=json.dumps({"required_missing": need, "key_columns_missing": keys}))
        if kind == "history":
            mc = validate_mapping(dr["columns"])
            if not mc["ok"]:
                raise AppError("BQ_MAPPING_INVALID", 422, detail=json.dumps(mc["errors"]))
        if dr["estimated_bytes"] > bq.maximum_bytes_billed:
            raise AppError("BQ_QUERY_TOO_EXPENSIVE", 413, detail=f"{dr['estimated_bytes']} > {bq.maximum_bytes_billed}")
        result["status"] = "VALID"
    except AppError as e:
        result.update(status="INVALID", error=e.to_dict())
    return {**sql_sources.record_validation(kind, vid, result), "validation": result}


def preview_sql(kind: str, vid: int, limit: int = 20) -> dict:
    bq = ss.get("bigquery")
    _require_config(bq, table=False)
    snap = _version_snap(kind, vid)
    n = max(1, min(int(limit), int(bq.preview_rows), 500))
    sql = f"SELECT * FROM {sql_guard.as_subquery(snap['sql'])} AS t LIMIT {n}"
    res = _run(_client(bq), bq, "sql_preview", sql, None)
    return {"kind": kind, "version_id": vid, "limit": n, "estimated_bytes": res["estimated_bytes"],
            "rows": [_jsonable(r) for r in res["rows"]]}


def test_sql_version(kind: str, vid: int) -> dict:
    """Data checks of a saved version on real data, WITHOUT writing anything (D0: today's output; history: the
    configured read range)."""
    bq = ss.get("bigquery")
    if kind == "d0":
        from . import d0_feed
        _require_config(bq, table=False)
        return d0_feed.test_version(vid)
    snap = _version_snap(kind, vid)
    _require_config(bq)
    start, end = read_range(bq)
    return _run_validation(bq, snap, start, end)


def completion_signal(day: date) -> bool | None:
    """True/False if a completion table is configured, None when no signal source is configured."""
    bq = ss.get("bigquery")
    if not (bq.completion_table and bq.completion_date_column):
        return None
    where = f"DATE(`{bq.completion_date_column}`) = @day"
    params = [("day", "DATE", day)]
    if bq.completion_status_column:
        where += f" AND CAST(`{bq.completion_status_column}` AS STRING) = @status"
        params.append(("status", "STRING", bq.completion_status_value))
    sql = f"SELECT COUNT(*) AS n FROM {_table_ref(bq, bq.completion_table)} WHERE {where}"
    res = _run(_client(bq), bq, "completion", sql, params)
    return bool(res["rows"] and (res["rows"][0].get("n") or 0) > 0)


def sufficiency_check(day: date) -> dict:
    """Fallback path: is there plausibly a complete day of data? rows(day) >= ratio × avg(previous 7 days)."""
    bq = ss.get("bigquery")
    snap = _snap(None)
    od = _order_date_expr(bq)
    sql = (f"SELECT {od} AS d, COUNT(*) AS n FROM {_rel(bq, snap)} WHERE {od} BETWEEN @start AND @day"
           f"{_partition_filter(bq, 'start', 'day', snap)} GROUP BY 1")
    res = _run(_client(bq), bq, "sufficiency", sql, [("start", "DATE", day - timedelta(days=7)), ("day", "DATE", day)])
    counts = {str(r["d"]): int(r["n"]) for r in res["rows"]}
    today_n = counts.get(str(day), 0)
    prev = [v for k, v in counts.items() if k != str(day)]
    avg = sum(prev) / len(prev) if prev else 0
    ok = today_n > 0 and (avg == 0 or today_n >= bq.fallback_min_rows_ratio * avg)
    return {"ok": ok, "rows_for_day": today_n, "avg_previous_7d": avg, "ratio_required": bq.fallback_min_rows_ratio}


def activation_check() -> dict:
    """Production mode may be enabled only when auth, connection, schema, mapping, quick profile and the full-period
    validation (for the CURRENT mapping) all pass."""
    st = status()
    bq = ss.get("bigquery")
    reqs = {}
    for part in ("connection", "schema", "profile"):
        reqs[part] = bool(st.get(part, {}).get("ok"))
    cols = bq.schema_snapshot
    reqs["mapping"] = bool(cols) and validate_mapping(cols)["ok"]
    reqs["validation"] = validation_ok_for_current()
    reqs["location_set"] = bool(bq.location)
    hist = ss.get("sql_sources").history
    if hist.mode == "SQL":           # a SQL feed must have a validated active version
        act = next((v for v in hist.versions if v.id == hist.active_version_id), None)
        reqs["history_sql_validated"] = bool(act and (act.validation or {}).get("status") == "VALID")
    return {"requirements": reqs, "ready": all(reqs.values()), "mapping_hash": mapping_hash(bq)}


# ------------------------------------------------------------------ access gates (separate, in order)
ACCESS_GATES = ("auth", "api_and_dataset", "location", "table_metadata", "query_job", "schema_mapping")


def access_check() -> dict:
    """Separate gates, run in order and stopped at the first failure (later gates = NOT_RUN):
      auth            credentials of THIS Windows account can be obtained (in-app OAuth / ADC / service account)
      api_and_dataset BigQuery API reachable + dataset metadata readable (dataViewer); API disabled is reported apart
      location        dataset location equals the configured one
      table_metadata  source table metadata readable
      query_job       a query job can be created: dry run on the table (jobs.create + read) and a real
                      `SELECT 1` job (0 bytes scanned)
      schema_mapping  the live table schema satisfies the saved mapping
    The data gate is the full-period validation (validate_source). Nothing is written to BigQuery."""
    bq = ss.get("bigquery")
    _require_config(bq)
    gates = [{"gate": g, "status": "NOT_RUN"} for g in ACCESS_GATES]
    by = {g["gate"]: g for g in gates}
    ident = {"method": "OAUTH_USER" if bq.oauth_enabled else bq.auth_method}

    def fail(gate, e):
        err = e if isinstance(e, AppError) else _map_error(e)
        by[gate].update(status="FAIL", code=err.code, detail=err.detail)
        if err.code == "BQ_AUTH_EXPIRED" and bq.oauth_enabled:
            oauth.mark_revoked(err.detail)
        return finish()

    def finish():
        ok = all(g["status"] == "PASS" for g in gates)
        out = {"passed": ok, "gates": gates, "identity": ident, "checked_at": now_iso(),
               "first_failure": next((g for g in gates if g["status"] == "FAIL"), None)}
        _set_status("access", ok, gates=[{k: g.get(k) for k in ("gate", "status", "code")} for g in gates])
        return out

    try:
        client = _client(bq)
        v = verify_auth(bq)      # a real access token is obtained here; building the client alone proves nothing
        ident.update(verified=bool(v.get("verified")), account=v.get("account"))
        if bq.oauth_enabled:
            ident["account"] = ident["account"] or oauth.status().get("email")
            if v.get("verified"):
                oauth.mark_verified(ident["account"])
        by["auth"].update(status="PASS", account=ident.get("account"), verified=ident["verified"])
    except Exception as e:      # noqa: BLE001
        return fail("auth", e)
    try:
        ds = client.get_dataset(f"{bq.project_id}.{bq.dataset_id}")
        by["api_and_dataset"]["status"] = "PASS"
    except Exception as e:      # noqa: BLE001
        return fail("api_and_dataset", e)
    actual = getattr(ds, "location", None)
    by["location"].update(actual=actual, configured=bq.location)
    if bq.location and actual and bq.location.lower() != actual.lower():
        return fail("location", AppError("BQ_LOCATION_MISMATCH", 409, detail=f"configured {bq.location}, actual {actual}"))
    by["location"]["status"] = "PASS"
    try:
        t = client.get_table(f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}")
        by["table_metadata"].update(status="PASS", num_rows=getattr(t, "num_rows", None))
    except Exception as e:      # noqa: BLE001
        return fail("table_metadata", e)
    try:
        est = _run(client, bq, "access_dry_run", f"SELECT 1 AS ok FROM {_table_ref(bq)} LIMIT 1", None,
                   dry_run_only=True)["estimated_bytes"]
        real = _run(client, bq, "access_select1", "SELECT 1 AS ok", None)
        ok = bool(real["rows"]) and list(real["rows"][0].values())[0] == 1
        if not ok:
            raise AppError("BQ_ERROR", 502, detail="SELECT 1 returned no row")
        by["query_job"].update(status="PASS", dry_run_bytes=est)
    except Exception as e:      # noqa: BLE001
        return fail("query_job", e)
    cols = [{"name": f.name, "type": f.field_type.upper()} for f in t.schema]
    mc = validate_mapping(cols)
    if not mc["ok"]:
        by["schema_mapping"].update(status="FAIL", code="BQ_MAPPING_INVALID", detail=mc["errors"])
        return finish()
    by["schema_mapping"]["status"] = "PASS"
    return finish()
