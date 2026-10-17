"""Product names for the forecast results (1.2.4): SKU -> product name, display and search only.

Source: the BigQuery table `<project>.<dataset>.<bigquery.product_names_table>` (default dim_sku: one row per sku_code,
checked 17/10/2026: 298,517 rows = 298,517 distinct sku_code, no empty name), read-only, dry-run first, byte cap.
Only the SKUs present in the local BIGQUERY data are kept. A SKU with more than one distinct name in the source is
AMBIGUOUS and gets no name (never one of them picked at random); a SKU missing in the source has none. The mapping is a
dict (one name per SKU), so joining it can never duplicate a forecast row, and forecast quantities are never touched.
Stored as one sync_state entry ('product_names'), refreshed after each successful D-1 sync or by hand; no schema change.
"""
from __future__ import annotations

import json
import logging
import threading
import unicodedata

from .. import db
from .. import settings_service as ss
from ..timeutil import now_iso

log = logging.getLogger("df.bq")
STATE = "product_names"
_cache: dict = {"updated_at": None, "names": {}}
_lock = threading.Lock()


def source_table(bq) -> str:
    t = bq.product_names_table
    return t if t.count(".") == 2 else f"{bq.project_id}.{bq.dataset_id}.{t}"


def refresh() -> dict:
    """Read the name table, keep the SKUs of the local BIGQUERY data, store the mapping. Read-only on BigQuery."""
    from . import connector
    bq = ss.get("bigquery")
    connector._require_config(bq, table=False)
    key, name = bq.product_names_key_column, bq.product_names_name_column
    sql = (f"SELECT CAST(`{key}` AS STRING) AS sku, `{name}` AS name FROM `{source_table(bq)}` "
           f"WHERE `{key}` IS NOT NULL")
    res = connector._run(connector._client(bq), bq, "product_names", sql, None)
    with db.read() as c:
        local = {r[0] for r in c.execute("SELECT DISTINCT sku_id FROM demand_daily WHERE data_source='BIGQUERY'")}
        local |= {r[0] for r in c.execute("SELECT DISTINCT v.sku_id FROM forecast_values v JOIN forecast_runs r "
                                          "ON r.id = v.run_id WHERE r.data_source='BIGQUERY'")}
    seen: dict[str, set] = {}
    for r in res["rows"]:
        sku = r.get("sku")
        if sku in local:
            nm = (r.get("name") or "").strip()
            if nm:
                seen.setdefault(sku, set()).add(nm)
    names = {s: next(iter(v)) for s, v in seen.items() if len(v) == 1}
    ambiguous = sorted(s for s, v in seen.items() if len(v) > 1)
    out = {"source": source_table(bq), "key_column": key, "name_column": name, "fetched_at": now_iso(),
           "rows_read": len(res["rows"]), "estimated_bytes": res.get("estimated_bytes"), "skus_local": len(local),
           "skus_named": len(names), "skus_without_name": len(local) - len(names), "skus_ambiguous": len(ambiguous),
           "ambiguous_sample": ambiguous[:20], "names": names}
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE "
                  "SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                  (STATE, json.dumps(out, ensure_ascii=False), now_iso()))
        db.audit(c, "PRODUCT_NAMES_REFRESHED", "bigquery", out["source"],
                 {k: out[k] for k in ("rows_read", "skus_local", "skus_named", "skus_ambiguous")})
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
