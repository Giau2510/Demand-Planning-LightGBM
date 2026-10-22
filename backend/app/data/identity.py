"""Content identity of the model-input data (1.2.4).

`demand.fingerprint` (rows, sum, first/last day, MAX(loaded_at)) changes whenever rows are rewritten, even with the same
values: a D-1 full reload of identical data (17/10/2026 19:58) made every explanation of the published forecast say
"data changed". The identity here hashes the VALUES the model reads (CONTENT_COLUMNS), never loaded_at:

  day hash     sha256 of the rows of one order_date, ordered by sku_id, fc_id (repr of each row tuple, one per line)
  window hash  sha256 of "date:dayhash" lines for the days in [start, end] (the training run's train_start..train_end)

A training run stores the identity of its own window (feature_config_json.data_identity). A run trained before 1.2.4
can get one only by ATTESTATION from a backup that provably holds its training data (the backup's fingerprint equals
the run's data_fingerprint): sync_state 'training_data_identity:<run id>'. Nothing is ever estimated: without a stored
identity, a changed fingerprint stays "data changed". Days added after the window (the next D-1) do not change it;
a restated day inside the window does, and is named.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict

from .. import db
from ..timeutil import now_iso
from .demand import fingerprint

ALGORITHM = "content-v1"
CONTENT_COLUMNS = ("order_date", "sku_id", "fc_id", "qty", "n_orders", "avg_unit_price", "avg_discount_rate",
                   "promo_share", "voucher_share")
# 1.2.9: a run that used the SKU open hours also hashes them. Each identity stores its own column list and is always
# compared with exactly that list, so runs recorded before (CONTENT_COLUMNS) keep their identity when a D-1 reload adds
# open hours to their days.
OPEN_HOURS_COLUMNS = CONTENT_COLUMNS + ("open_hours",)
# 1.2.9b: a run that used the customer features also hashes the customer counts (same per-identity column list rule)
CUSTOMER_COLUMNS = ("customer_count", "repeat_customer_count", "repeat_interval_days_sum")
_ALLOWED = (CONTENT_COLUMNS, OPEN_HOURS_COLUMNS, CONTENT_COLUMNS + CUSTOMER_COLUMNS, OPEN_HOURS_COLUMNS + CUSTOMER_COLUMNS)


def columns_for(cfg) -> tuple[str, ...]:
    from ..ml.features import customer_on, open_hours_on
    base = OPEN_HOURS_COLUMNS if open_hours_on(cfg) else CONTENT_COLUMNS
    return base + CUSTOMER_COLUMNS if customer_on(cfg) else base


def _columns(cols) -> tuple[str, ...]:
    c = tuple(cols or CONTENT_COLUMNS)
    if c not in _ALLOWED:        # stored JSON never reaches the SQL text unchecked
        raise ValueError(f"unknown identity columns {c}")
    return c
def _log_marker(conn, scope_key: str):
    """Newest demand_change_log id of the scope (None before migration 0010)."""
    try:
        return conn.execute("SELECT MAX(id) FROM demand_change_log WHERE scope_key=?", (scope_key,)).fetchone()[0]
    except Exception:  # noqa: BLE001 - a database before 1.2.13 has no change log
        return None


_cache: "OrderedDict[tuple, dict]" = OrderedDict()     # (scope_key, fingerprint, columns, log id) -> {date: (sha256, rows)}
_CACHE_MAX = 4
_lock = threading.Lock()


def day_hashes(scope_key: str, conn, cache: bool = True, fp: str | None = None,
               columns=None) -> dict[str, tuple[str, int]]:
    """{order_date: (sha256, rows)} of the whole scope. One ordered scan (~11 s for 1.35 M rows), cached per data
    version of the live database (the fingerprint): computed again only after the data was written. cache=False for
    another database (a backup copy). fp: the fingerprint when the caller has it (one full-scope aggregate less).
    columns: the identity's own column list (CONTENT_COLUMNS for every run before 1.2.9)."""
    cols = _columns(columns)
    # 1.2.13: + the newest change-log entry of the scope - a rollback can restore the count, sum and newest loaded_at
    # of the fingerprint while the content differs (history_sync logs every changed row)
    key = (scope_key, fp or fingerprint(scope_key, conn), cols, _log_marker(conn, scope_key))
    with _lock:
        if cache and key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    out: dict[str, tuple[str, int]] = {}
    day, h, n = None, None, 0
    for row in conn.execute(f"SELECT {', '.join(cols)} FROM demand_daily WHERE scope_key=? "
                            "ORDER BY order_date, sku_id, fc_id", (scope_key,)):
        t = tuple(row)
        if t[0] != day:
            if h is not None:
                out[day] = (h.hexdigest(), n)
            day, h, n = t[0], hashlib.sha256(), 0
        h.update(repr(t).encode())
        h.update(b"\n")
        n += 1
    if h is not None:
        out[day] = (h.hexdigest(), n)
    if cache:
        with _lock:
            _cache[key] = out
            while len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
    return out


def window_identity(scope_key: str, start: str, end: str, conn, days: dict | None = None, fp: str | None = None,
                    columns=None) -> dict:
    """Identity of the data window [start, end] of a scope (both Vietnam calendar dates, inclusive)."""
    cols = _columns(columns)
    days = days if days is not None else day_hashes(scope_key, conn, fp=fp, columns=cols)
    sel = {d: v for d, v in days.items() if start <= d <= end}
    sha = hashlib.sha256("\n".join(f"{d}:{sel[d][0]}" for d in sorted(sel)).encode()).hexdigest()
    return {"algorithm": ALGORITHM, "columns": list(cols), "start": start, "end": end, "days": len(sel),
            "rows": sum(v[1] for v in sel.values()), "sha256": sha, "day_sha": {d: v[0][:16] for d, v in sel.items()},
            "computed_at": now_iso()}


def stored_identity(tr: dict | None, conn) -> dict | None:
    """The identity recorded for a training run: at training time (1.2.4+) or by attestation (older runs)."""
    if not tr:
        return None
    fc = json.loads(tr.get("feature_config_json") or "{}") or {}
    if fc.get("data_identity"):
        return {**fc["data_identity"], "origin": "TRAINING"}
    r = conn.execute("SELECT value_json FROM sync_state WHERE name=?", (f"training_data_identity:{tr['id']}",)).fetchone()
    return {**json.loads(r[0]), "origin": "ATTESTED"} if r else None


def data_state(tr: dict | None, scope_key: str, conn) -> dict:
    """Is the data a training run used still exactly the data in the database?
      SAME_LOAD     fingerprint unchanged (nothing rewritten since training)
      SAME_CONTENT  rows rewritten (loaded_at moved) but the values of the run's window are identical
      CHANGED       values inside the window differ (changed / added / removed days listed)
      UNVERIFIABLE  fingerprint changed and no identity was recorded for this run: treated as changed
    `key` identifies the data version (for caches)."""
    cur = fingerprint(scope_key, conn)
    if tr and tr.get("data_fingerprint") == cur:
        return {"status": "SAME_LOAD", "key": cur}
    ident = stored_identity(tr, conn)
    if not ident or ident.get("algorithm") != ALGORITHM:
        return {"status": "UNVERIFIABLE", "key": cur}
    try:
        now = window_identity(scope_key, ident["start"], ident["end"], conn, fp=cur, columns=ident.get("columns"))
    except ValueError:
        return {"status": "UNVERIFIABLE", "key": cur}
    base = {"key": cur, "origin": ident["origin"], "window": [ident["start"], ident["end"]], "rows": ident.get("rows"),
            "sha256": ident["sha256"]}
    if now["sha256"] == ident["sha256"]:
        return {"status": "SAME_CONTENT", **base}
    old, new = ident.get("day_sha") or {}, now["day_sha"]
    changed = sorted(d for d in set(old) | set(new) if old.get(d) != new.get(d))
    return {"status": "CHANGED", **base, "current_sha256": now["sha256"], "changed_days": changed[:60],
            "n_changed_days": len(changed)}


def record_for_training(run_id: str, scope_key: str, start: str, end: str, columns=None) -> dict:
    """Stored with a training run at training time (feature_config_json.data_identity)."""
    with db.read() as c:
        ident = window_identity(scope_key, start, end, c, columns=columns)
    with db.tx() as c:
        c.execute("UPDATE training_runs SET feature_config_json=json_set(COALESCE(feature_config_json, '{}'), "
                  "'$.data_identity', json(?)) WHERE id=?", (json.dumps(ident), run_id))
    return ident


def attest_from_backup(training_run_id: str, backup_zip) -> dict:
    """Identity of an OLDER run's training data, computed from a backup that provably holds it: the training run is in
    the backup with the same data_fingerprint and the backup's scope fingerprint equals it. Stored once (never
    overwritten) in sync_state; the live data itself is never changed."""
    import shutil
    import sqlite3
    import tempfile
    import zipfile
    from pathlib import Path

    from ..messages import AppError
    backup_zip = Path(backup_zip)
    with db.read() as c:
        tr = db.one(c, "SELECT * FROM training_runs WHERE id=?", (training_run_id,))
        if not tr:
            raise AppError("BATCH_NOT_FOUND", 404, detail=training_run_id)
        if stored_identity(tr, c):
            raise AppError("VALIDATION_ERROR", 409, detail=f"{training_run_id} already has a data identity")
    if not tr.get("train_start") or not tr.get("train_end"):
        raise AppError("VALIDATION_ERROR", 409, detail=f"{training_run_id} has no training window")
    tmp = Path(tempfile.mkdtemp(prefix="df-attest-"))
    try:
        with zipfile.ZipFile(backup_zip) as z:
            z.extract("db/app.db", tmp)
        b = sqlite3.connect(f"file:{(tmp / 'db' / 'app.db').as_posix()}?mode=ro", uri=True)
        try:
            btr = b.execute("SELECT data_fingerprint FROM training_runs WHERE id=?", (training_run_id,)).fetchone()
            bfp = fingerprint(tr["scope_key"], b)
            if not btr or btr[0] != tr["data_fingerprint"] or bfp != tr["data_fingerprint"]:
                raise AppError("VALIDATION_ERROR", 409, detail=f"backup {backup_zip.name} does not hold the training data "
                                                               f"of {training_run_id} (fingerprint {bfp})")
            ident = window_identity(tr["scope_key"], tr["train_start"], tr["train_end"], b,
                                    days=day_hashes(tr["scope_key"], b, cache=False))
        finally:
            b.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    sha_zip = hashlib.sha256(backup_zip.read_bytes()).hexdigest()
    ident["attestation"] = {"backup": backup_zip.name, "backup_sha256": sha_zip, "backup_fingerprint": bfp,
                            "rule": "backup training run + scope fingerprint == training data_fingerprint",
                            "attested_at": now_iso()}
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?,?,?)",
                  (f"training_data_identity:{training_run_id}", json.dumps(ident), now_iso()))
        db.audit(c, "TRAINING_DATA_ATTESTED", "training_run", training_run_id,
                 {"backup": backup_zip.name, "sha256": ident["sha256"], "rows": ident["rows"], "days": ident["days"]})
    with db.read() as c:
        state = data_state(tr, tr["scope_key"], c)
    return {"training_run_id": training_run_id, "identity": {k: v for k, v in ident.items() if k != "day_sha"},
            "current_state": {k: v for k, v in state.items() if k != "key"}}
