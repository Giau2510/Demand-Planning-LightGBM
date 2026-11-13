"""Product names for the forecast results (1.2.4): SKU -> product name, display and search only.

1.4.10: the names come from the Avg Demand tables first; the dim_sku table is an OPTIONAL last fallback. Per SKU, in
this order (the first non-empty, trimmed name wins; ONE stored mapping, so joining it can never duplicate a forecast row
and forecast quantities are never touched):
  1. the newest non-empty product_name of the SKU in the local avg_demand_daily (the stored copy of today's
     fact_avg_demand_sku, written by ml/sel2/avg_demand.read_current);
  2. only for SKUs still without a name: the latest non-empty name of the historical Avg Demand table
     (sel2_pipeline.avg_demand_hist_table), last 60 days of transformed_at, read-only (dry run first, byte cap); a
     failure of this read is logged and never fails the refresh;
  3. the name stored by the previous refresh (a SKU that had a name is never blanked);
  4. only when `bigquery.product_names_table` is NOT empty and SKUs are still without a name: that table (1.4.9: a full
     id project.dataset.table, checked on the BigQuery page; a short name stored by an older version is joined with
     project / dataset of the D-1 table as before). A SKU with more than one distinct name there is AMBIGUOUS and gets
     no name from it (never one of them picked at random). An empty setting = this table is never read.
The SKU universe is the local BIGQUERY data (demand_daily, forecast_values) plus the SKUs of the newest business_date
of avg_demand_daily. Stored as one sync_state entry ('product_names'), refreshed after each successful D-1 sync or by
hand; no schema change.
"""
from __future__ import annotations

import json
import logging
import threading
import unicodedata
from datetime import timedelta

from .. import db
from .. import settings_service as ss
from ..timeutil import now_iso, today_vn

log = logging.getLogger("df.bq")
STATE = "product_names"
HIST_DAYS = 60                  # window of the historical Avg Demand read (transformed_at, the partition column)
HIST_CHUNK = 50000              # SKUs per historical query (list parameter)
_cache: dict = {"updated_at": None, "names": {}}
_lock = threading.Lock()


def source_table(bq) -> str:
    """Effective full id of the optional dim_sku table ('' = not used)."""
    t = (bq.product_names_table or "").strip()
    if not t:
        return ""
    return t if t.count(".") == 2 else f"{bq.project_id}.{bq.dataset_id}.{t}"


def _local(c) -> tuple[set, dict, dict]:
    """(SKU universe, newest non-empty Avg Demand name per SKU, names stored by the previous refresh)."""
    local = {r[0] for r in c.execute("SELECT DISTINCT sku_id FROM demand_daily WHERE data_source='BIGQUERY'")}
    local |= {r[0] for r in c.execute("SELECT DISTINCT v.sku_id FROM forecast_values v JOIN forecast_runs r "
                                      "ON r.id = v.run_id WHERE r.data_source='BIGQUERY'")}
    local |= {r[0] for r in c.execute("SELECT DISTINCT sku_code FROM avg_demand_daily WHERE business_date = "
                                      "(SELECT MAX(business_date) FROM avg_demand_daily)")}
    avg = {}
    for sku, nm in c.execute("SELECT sku_code, product_name FROM (SELECT sku_code, product_name, ROW_NUMBER() OVER "
                             "(PARTITION BY sku_code ORDER BY business_date DESC, loaded_at DESC, rowid DESC) AS rn "
                             "FROM avg_demand_daily WHERE product_name IS NOT NULL AND TRIM(product_name) <> '' AND business_date >= "
                             "date((SELECT MAX(business_date) FROM avg_demand_daily), '-60 days')) "
                             "WHERE rn = 1"):
        if sku in local:
            avg[sku] = nm.strip()
    r = c.execute("SELECT value_json FROM sync_state WHERE name=?", (STATE,)).fetchone()
    prev = {k: v for k, v in (json.loads(r[0]).get("names") or {}).items() if k in local and v} if r else {}
    return local, avg, prev


def _hist_names(skus: list[str]) -> tuple[dict, int, int]:
    """Latest non-empty name per SKU of the historical Avg Demand table (last HIST_DAYS days), read-only. Returns
    (names, rows read, estimated bytes); a failure is logged (error code only) and keeps what was read so far."""
    from ..ml.sel2 import avg_demand
    from . import connector
    out, rows, est = {}, 0, 0
    try:
        cfg, bq = ss.get("sel2_pipeline"), ss.get("bigquery")
        connector._require_config(bq, table=False)
        bq = bq.model_copy(update={"maximum_bytes_billed": min(int(bq.maximum_bytes_billed), avg_demand.MAX_BYTES)})
        client = connector._client(bq)
        since = today_vn() - timedelta(days=HIST_DAYS)
        sql = (f"SELECT CAST(sku_code AS STRING) AS sku, product_name AS name FROM `{cfg.avg_demand_hist_table}` "
               "WHERE transformed_at >= TIMESTAMP(@since) AND CAST(sku_code AS STRING) IN UNNEST(@skus) "
               "AND product_name IS NOT NULL AND TRIM(product_name) <> '' "
               "QUALIFY ROW_NUMBER() OVER (PARTITION BY sku_code ORDER BY transformed_at DESC, product_name DESC) = 1")
        for i in range(0, len(skus), HIST_CHUNK):
            res = connector._run(client, bq, "product_names_hist", sql,
                                 [("since", "DATE", since), ("skus", "STRING", skus[i:i + HIST_CHUNK])])
            rows += len(res["rows"])
            est += int(res.get("estimated_bytes") or 0)
            for r in res["rows"]:
                nm = (r.get("name") or "").strip()
                if nm and r.get("sku"):
                    out.setdefault(r["sku"], nm)
    except Exception as e:  # noqa: BLE001 - names are display data: the refresh goes on without the historical names
        log.warning("product names: historical Avg Demand read failed",
                    extra={"ctx": {"error": getattr(e, "code", type(e).__name__)}})
    return out, rows, est


def _dim_names(bq, want: set) -> tuple[dict, list, int, int]:
    """Names of the optional dim_sku table for the SKUs in `want`: (names, ambiguous SKUs, rows read, estimated bytes).
    Read-only on BigQuery; an error is raised here and caught by refresh() (recorded as dim_error, the other names are
    still saved)."""
    from . import connector
    connector._require_config(bq, table=False)
    key, name = bq.product_names_key_column, bq.product_names_name_column
    sql = (f"SELECT CAST(`{key}` AS STRING) AS sku, `{name}` AS name FROM `{source_table(bq)}` "
           f"WHERE `{key}` IS NOT NULL")
    res = connector._run(connector._client(bq), bq, "product_names", sql, None)
    seen: dict[str, set] = {}
    for r in res["rows"]:
        sku = r.get("sku")
        if sku in want:
            nm = (r.get("name") or "").strip()
            if nm:
                seen.setdefault(sku, set()).add(nm)
    names = {s: next(iter(v)) for s, v in seen.items() if len(v) == 1}
    return names, sorted(s for s, v in seen.items() if len(v) > 1), len(res["rows"]), int(res.get("estimated_bytes") or 0)


def refresh() -> dict:
    """Resolve the names (Avg Demand first, dim_sku optional last) and store the mapping. Read-only on BigQuery."""
    bq = ss.get("bigquery")
    with db.read() as c:
        local, avg, prev = _local(c)
    names = dict(avg)
    by_source = {"avg": len(names), "hist": 0, "stored": 0, "dim": 0}
    rows_read = est = 0
    ambiguous: list[str] = []
    dim_error = None
    todo = sorted(local - names.keys())
    if todo:                                                # 2. historical Avg Demand (bounded read)
        h, n, b = _hist_names(todo)
        names.update(h)
        by_source["hist"] = len(h)
        rows_read, est = rows_read + n, est + b
    kept = {s: v for s, v in prev.items() if s not in names}   # 3. a SKU that had a name is never blanked
    names.update(kept)
    by_source["stored"] = len(kept)
    todo = local - names.keys()
    if todo and source_table(bq):                           # 4. optional dim_sku (empty setting = never read)
        try:
            d, ambiguous, n, b = _dim_names(bq, todo)
        except Exception as e:  # noqa: BLE001 - review 13/11: a failing OPTIONAL table must not lose the Avg / historical names
            dim_error = getattr(e, "code", type(e).__name__)
            log.warning("product names: optional dim table read failed", extra={"ctx": {"error": dim_error}})
        else:
            names.update(d)
            by_source["dim"] = len(d)
            rows_read, est = rows_read + n, est + b
    used = ss.get("sel2_pipeline").avg_demand_table.split(".")[-1] + " (stored)"
    if by_source["hist"]:
        used += " + historical"
    if by_source["dim"]:
        used += f" + {source_table(bq).split('.')[-1]}"
    out = {"source": used, "key_column": bq.product_names_key_column, "name_column": bq.product_names_name_column,
           "fetched_at": now_iso(), "rows_read": rows_read, "estimated_bytes": est, "skus_local": len(local),
           "skus_named": len(names), "skus_without_name": len(local) - len(names), "skus_by_source": by_source,
           "skus_ambiguous": len(ambiguous), "ambiguous_sample": ambiguous[:20], "names": names}
    if dim_error:
        out["dim_error"] = dim_error
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE "
                  "SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                  (STATE, json.dumps(out, ensure_ascii=False), now_iso()))
        db.audit(c, "PRODUCT_NAMES_REFRESHED", "bigquery", out["source"],
                 {**{k: out[k] for k in ("rows_read", "skus_local", "skus_named", "skus_ambiguous")},
                  "skus_by_source": by_source})
    return {k: v for k, v in out.items() if k != "names"}


def refresh_quietly(context: str) -> None:
    """After a D-1 sync: names are display data, a failure here never fails the sync (it is logged)."""
    try:
        r = refresh()
        log.info("product names refreshed", extra={"ctx": {"context": context, "named": r["skus_named"],
                                                           "local": r["skus_local"]}})
    except Exception:  # noqa: BLE001
        log.warning("product names not refreshed", exc_info=True, extra={"ctx": {"context": context}})


def status(conn) -> dict | None:
    r = conn.execute("SELECT value_json FROM sync_state WHERE name=?", (STATE,)).fetchone()
    if not r:
        return None
    v = json.loads(r[0])
    return {k: x for k, x in v.items() if k != "names"}


def names(conn) -> dict[str, str]:
    """SKU -> name (cached until the stored mapping changes)."""
    r = conn.execute("SELECT updated_at FROM sync_state WHERE name=?", (STATE,)).fetchone()
    upd = r[0] if r else None
    with _lock:
        if _cache["updated_at"] == upd:
            return _cache["names"]
    v = {}
    if upd:
        v = json.loads(conn.execute("SELECT value_json FROM sync_state WHERE name=?", (STATE,)).fetchone()[0]).get("names") or {}
    with _lock:
        _cache.update(updated_at=upd, names=v)
    return v


def for_run(run: dict, conn) -> dict[str, str]:
    """Names apply to BIGQUERY runs only (DEMO / Excel SKUs are not the source's SKUs)."""
    return names(conn) if run.get("data_source") == "BIGQUERY" else {}


def normalize(text: str | None) -> str:
    """Lower case, Vietnamese accents removed (đ -> d), spaces collapsed: 'Hỗ trợ GAN' -> 'ho tro gan'."""
    t = unicodedata.normalize("NFD", (text or "").replace("đ", "d").replace("Đ", "D"))
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return " ".join(t.lower().split())


def matching_skus(skus, q: str, mapping: dict[str, str]) -> list[str]:
    """SKUs whose 'SKU + name' contains EVERY word of q (partial, case- and accent-insensitive)."""
    words = normalize(q).split()
    if not words:
        return list(skus)
    out = []
    for s in skus:
        hay = normalize(f"{s} {mapping.get(s, '')}")
        if all(w in hay for w in words):
            out.append(s)
    return out
