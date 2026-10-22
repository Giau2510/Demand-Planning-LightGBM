"""1.2.13: read-only line-level reads of the D-1 source for the history sync (app/data/history_sync.py).

The D-1 load stores one aggregated row per day x SKU x FC. When the source later returns less for a key, only its order
lines tell why (owner rule of 22/10/2026: a cancelled or otherwise dropped order line must not reduce the stored
demand; a line re-attributed to another SKU / FC / day is a move). These reads give that evidence:

  table_version()      the source table version (its modified time, UTC) - read before and after a run: a run whose
                       source changed while it read is retried, never written
  lines()              the order lines of some days x SKUs, now or AS OF a past version (BigQuery time travel keeps the
                       versions of the last 7 days of the dataset; older versions cannot be read)
  order_lines()        every line of some order codes, now (where did a missing line go?)
  day_totals()         per day: keys, units and a fingerprint of (SKU, FC, units) of the app's own aggregation (the D-1
                       SQL) - the daily check of the history outside the D-1 window

Same mapping, day expression and valid-line rule (SKU, FC, target present, target >= 0) as the D-1 aggregation. Only
the TABLE history source supports time travel (a user SQL is not a table version); DROP_EXACT is not supported either
(duplicate lines would not match the aggregate) - available() says so and the caller then keeps every decrease (cause
NO_EVIDENCE). Every query is a dry run first and capped (connector._run). No customer column is read.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from .. import settings_service as ss
from . import connector

ORDER_CHUNK = 5000


def available(snap: dict | None) -> tuple[bool, str | None]:
    """Can line evidence be read for this history source? (reason when not)."""
    bq = ss.get("bigquery")
    if connector._is_sql(snap):
        return False, "SQL_SOURCE"            # time travel reads a table version, not the result of a user SQL
    if not connector._col(bq, "order_id"):
        return False, "ORDER_ID_NOT_MAPPED"
    if bq.exact_duplicate_policy == "DROP_EXACT":
        return False, "DROP_EXACT_POLICY"
    return True, None


def table_version() -> str | None:
    """Modified time (UTC ISO) of the source table = its current version; None when the client does not say."""
    bq = ss.get("bigquery")
    try:
        t = connector._client(bq).get_table(f"{bq.project_id}.{bq.dataset_id}.{bq.source_table}")
    except Exception as e:  # noqa: BLE001 - classified like every BigQuery error
        raise connector._map_error(e) from e
    m = getattr(t, "modified", None)
    if not isinstance(m, datetime):
        return None
    return (m if m.tzinfo else m.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def _s(expr: str | None) -> str:
    return f"CAST({expr} AS STRING)" if expr else "CAST(NULL AS STRING)"


def _select(bq) -> str:
    od = connector._order_date_expr(bq)
    return (f"{od} AS order_date, {_s(connector._col(bq, 'order_id'))} AS order_id, "
            f"CAST({connector._col(bq, 'sku_id')} AS STRING) AS sku_id, CAST({connector._col(bq, 'fc_id')} AS STRING) AS fc_id, "
            f"{connector._col(bq, 'order_qty')} AS qty, {_s(connector._ref_col(bq, 'product_id'))} AS product_id, "
            f"{_s(connector._ref_col(bq, 'item_code'))} AS item_code, {_s(connector._ref_col(bq, 'order_status'))} AS order_status")


def _valid(bq) -> str:
    sku, fc, qty = connector._col(bq, "sku_id"), connector._col(bq, "fc_id"), connector._col(bq, "order_qty")
    return f"{sku} IS NOT NULL AND {fc} IS NOT NULL AND {qty} IS NOT NULL AND {qty} >= 0"


def _from(bq, asof: str | None) -> tuple[str, list]:
    if not asof:
        return f"{connector._table_ref(bq)} AS _t", []
    return f"{connector._table_ref(bq)} AS _t FOR SYSTEM_TIME AS OF @asof", [("asof", "TIMESTAMP", _ts(asof))]


def _ts(v: str) -> datetime:
    t = datetime.fromisoformat(v)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _clean(r: dict) -> dict:
    d = r.get("order_date")
    return {"order_date": str(d)[:10] if d is not None else None, "order_id": r.get("order_id"),
            "sku_id": r.get("sku_id"), "fc_id": r.get("fc_id"), "qty": float(r.get("qty") or 0),
            "product_id": r.get("product_id"), "item_code": r.get("item_code"), "order_status": r.get("order_status")}


KEY_CHUNK = 20000


def lines(keys: set[tuple[str, str, str]], asof: str | None = None) -> list[dict]:
    """Order lines of exactly the given day x SKU x FC keys (filtered in BigQuery: "day|SKU|FC" IN the key list, at
    most KEY_CHUNK keys per query), in the current version or AS OF `asof` (UTC ISO)."""
    if not keys:
        return []
    bq = ss.get("bigquery")
    od = connector._order_date_expr(bq)
    kexpr = (f"CONCAT(CAST({od} AS STRING), '|', CAST({connector._col(bq, 'sku_id')} AS STRING), '|', "
             f"CAST({connector._col(bq, 'fc_id')} AS STRING))")
    part = connector._partition_filter(bq, "dmin", "dmax")
    ks = sorted("|".join(k) for k in keys)
    out: list[dict] = []
    for i in range(0, len(ks), KEY_CHUNK):
        chunk = ks[i:i + KEY_CHUNK]
        rel, params = _from(bq, asof)
        sql = f"SELECT {_select(bq)} FROM {rel} WHERE {kexpr} IN UNNEST(@keys) AND {_valid(bq)}{part}"
        params += [("keys", "STRING", chunk)]
        if part:
            days = sorted({x.split("|", 1)[0] for x in chunk})
            params += [("dmin", "DATE", date.fromisoformat(days[0])), ("dmax", "DATE", date.fromisoformat(days[-1]))]
        res = connector._run(connector._client(bq), bq, "hr_lines", sql, params)
        out += [_clean(r) for r in res["rows"]]
    return [r for r in out if (r["order_date"], r["sku_id"], r["fc_id"]) in keys]


def order_lines(order_ids: set[str], asof: str | None = None) -> list[dict]:
    """Every valid line of the given order codes (any day, SKU, FC), now or AS OF `asof`."""
    ids = sorted(x for x in order_ids if x)
    if not ids:
        return []
    bq = ss.get("bigquery")
    out: list[dict] = []
    for i in range(0, len(ids), ORDER_CHUNK):
        rel, params = _from(bq, asof)
        sql = (f"SELECT {_select(bq)} FROM {rel} WHERE CAST({connector._col(bq, 'order_id')} AS STRING) IN UNNEST(@ids) "
               f"AND {_valid(bq)}")
        res = connector._run(connector._client(bq), bq, "hr_order_lines", sql, params + [("ids", "STRING", ids[i:i + ORDER_CHUNK])])
        out += [_clean(r) for r in res["rows"]]
    return out


def fp_one(sku, fc, qty) -> int:
    """The fingerprint of one (SKU, FC, units) key - the term day_totals XORs per day (same formula as the SQL)."""
    import hashlib
    return int(hashlib.md5(f"{sku}|{fc}|{float(qty):.6f}".encode()).hexdigest()[:15], 16)


def day_fp_python(rows) -> int:
    """The day fingerprint of day_totals computed on (sku, fc, qty) tuples in Python (same formula as the SQL)."""
    x = 0
    for sku, fc, qty in rows:
        x ^= fp_one(sku, fc, qty)
    return x


def day_totals(start: date, end: date, snap: dict | None = None) -> dict[str, dict]:
    """{day: {keys, qty, fp}} of the app's own D-1 aggregation of [start, end] (one query, nothing written)."""
    bq = ss.get("bigquery")
    snap = connector._snap(snap)
    inner, params = connector._daily_sql(bq, start, end, snap)
    sql = ("SELECT CAST(order_date AS STRING) AS d, COUNT(*) AS keys, SUM(qty) AS qty, "
           "BIT_XOR(CAST(CONCAT('0x', SUBSTR(TO_HEX(MD5(CONCAT(sku_id, '|', fc_id, '|', "
           "FORMAT('%.6f', CAST(qty AS FLOAT64))))), 1, 15)) AS INT64)) AS fp "
           f"FROM (\n{inner}\n) AS _agg WHERE _kind = 'VALID' GROUP BY 1")
    res = connector._run(connector._client(bq), bq, "hr_day_totals", sql, params)
    return {str(r["d"])[:10]: {"keys": int(r["keys"] or 0), "qty": float(r["qty"] or 0), "fp": int(r["fp"] or 0)}
            for r in res["rows"]}
