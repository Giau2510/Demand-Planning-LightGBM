"""1.4.4: the published SEL2 numbers kept for the forecast history page, in sidecar files of the daily Excel (no
database table: owner decision 06/11/2026, the database size).

One sidecar per recorded export version (export_runs): <export root>\\.published\\YYYYMMDD\\du_bao_YYYYMMDD_vN.h2.json.gz
(outside the day folder: its listing, which the purchasing team browses, stays the Excel files only), gzip JSON
{"export_run_id", "forecast_date", "horizons": [1], "sha256_of_xlsx", "rows": [[sku, fc, target_date, forecast_used,
forecast_source, fallback_reason], ...], "flags": {...}}: the rows of HISTORY_HORIZONS exactly as written in the file.
1.4.5 (owner decision 06/11/2026): horizon 1 = target day = forecast day (the run of day D for target D); up to 1.4.4
horizon 2 (target D + 1). A sidecar of other horizons is stale (its "horizons" differ) and is rebuilt from the xlsx at
the same path (the name keeps ".h2" for every horizon: a 1.4.4 sidecar is replaced, never left beside a new one). The
sidecar of a version renamed to du_bao_YYYYMMDD_vN_bo.xlsx (1.4.5, export.py) keeps the name of du_bao_YYYYMMDD_vN. export.write_daily_export writes it right after the
version file and its record, from the rows it already built (keep() wraps the rows generator); a failure is a warning
(flag SIDECAR_WRITE_FAILED), never a failed export; the temporary _TAM file writes none. Written atomically (temporary
file + os.replace).

The sidecar is derived data: when it is missing, unreadable or its sha256_of_xlsx differs from export_runs.sha256,
load() rebuilds it from the recorded version file (1.4.2 / 1.4.3 sheet DU_BAO, 1.4.4 sheets DU_BAO_<fc_code>; columns
found by their header name; only the xlsx whose sha256 equals the record is read; a row without forecast_used is counted,
never stored as 0; fractional numbers of 1.4.2 files are kept as they are and counted). Sidecars are not in the database
backups and can always be regenerated from the Excel files (`python -m app.cli sel2-published-backfill`). The parsed rows
of the last days read are kept in a small in-process LRU (MAX_CACHED_ROWS, compact interned tuples). A rebuild runs once
per export at a time (a lock per export_run id, at most MAX_BUILD_LOCKS kept): a second request for the same day waits
and reuses its result.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import sys
import threading
import uuid
import zlib
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path

from ... import db, paths

log = logging.getLogger("df.sel2.published")
HISTORY_HORIZONS = (1,)                   # horizons kept per SKU x FC (1.4.5 history: target = forecast day)
SIDECAR_DIR = ".published"
FORMAT = 1
COLS = ("sku_code", "fc_code", "target_date", "forecast_used", "forecast_source", "fallback_reason")
SHEET_7, SHEET_PREFIX = "DU_BAO", "DU_BAO_"
MAX_CACHED_ROWS = 600_000                 # about 10 days of 58k SKU x FC
FLAG_WRITE_FAILED = "SIDECAR_WRITE_FAILED"
RETIRED_SUFFIX = "_bo"                    # = export.RETIRED_SUFFIX (earlier versions of a day, 1.4.5)
_lock = threading.Lock()
_lru: OrderedDict = OrderedDict()         # (export_run_id, sha256) -> tuple of rows
_lru_rows = 0
MAX_BUILD_LOCKS = 64
_build_locks: OrderedDict = OrderedDict()  # export_run_id -> threading.Lock (one load / rebuild per export at a time)


def _iso(v) -> str:
    return v.isoformat()[:10] if hasattr(v, "isoformat") else str(v)[:10]


def sidecar_path(version_file: Path) -> Path:
    """<export root>/.published/YYYYMMDD/<version stem>.h2.json.gz for <export root>/YYYYMMDD/du_bao_YYYYMMDD_vN.xlsx
    (also for its renamed du_bao_YYYYMMDD_vN_bo.xlsx: the _bo suffix is not part of the sidecar name)."""
    stem = version_file.stem
    if stem.endswith(RETIRED_SUFFIX):
        stem = stem[:-len(RETIRED_SUFFIX)]
    return version_file.parent.parent / SIDECAR_DIR / version_file.parent.name / f"{stem}.h2.json.gz"


def keep(rows, into: dict, columns):
    """Pass the export rows through unchanged; the rows of HISTORY_HORIZONS go into `into` keyed by (sku, fc, horizon)
    (rows read twice - e.g. a second layout written from the same rows - are kept once)."""
    i = {c: n for n, c in enumerate(columns)}
    isku, ifc, itd, ih = i["sku_code"], i["fc_code"], i["target_date"], i["horizon"]
    iu, isrc, ir = i["forecast_used"], i["forecast_source"], i["fallback_reason"]
    for r in rows:
        if r[ih] in HISTORY_HORIZONS:
            into[(r[isku], r[ifc], r[ih])] = (r[isku], r[ifc], _iso(r[itd]), r[iu], r[isrc], r[ir])
        yield r


def write(version_file: Path, export_run_id: str, forecast_date, sha256: str, rows, flags: dict | None = None) -> Path:
    """Write the sidecar of one version file atomically (temporary file in the same folder + os.replace)."""
    p = sidecar_path(version_file)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"format": FORMAT, "export_run_id": export_run_id, "forecast_date": _iso(forecast_date),
           "horizons": list(HISTORY_HORIZONS), "sha256_of_xlsx": sha256, "columns": list(COLS),
           "rows": [list(r) for r in rows], "flags": flags or {}}
    tmp = p.parent / f".{p.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, p)
    finally:
        tmp.unlink(missing_ok=True)
    return p


def write_safe(version_file: Path, export_run_id: str, forecast_date, sha256: str, kept: dict) -> str | None:
    """write() for the export: never raises; returns FLAG_WRITE_FAILED (and logs a warning) on failure."""
    try:
        write(version_file, export_run_id, forecast_date, sha256, kept.values())
        return None
    except Exception as e:  # noqa: BLE001 - the export is recorded; the sidecar can be rebuilt from the file
        log.warning("sel2 published sidecar not written", extra={"ctx": {"export_run_id": export_run_id,
                                                                         "error": f"{type(e).__name__}: {e}"[:300]}})
        return FLAG_WRITE_FAILED


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _rows_of_file(p: Path) -> tuple[list[tuple], str, dict]:
    """(rows of HISTORY_HORIZONS, layout, flags) of one daily Excel; ValueError when no known layout."""
    from openpyxl import load_workbook
    wb = load_workbook(p, read_only=True, data_only=True)
    try:
        names = [n for n in wb.sheetnames if n == SHEET_7 or n.startswith(SHEET_PREFIX)]
        if not names:
            raise ValueError("NO_DU_BAO_SHEET")
        layout = SHEET_7 if SHEET_7 in names else "DU_BAO_<fc>"
        need = ("sku_code", "fc_code", "target_date", "horizon", "forecast_used", "forecast_source", "fallback_reason")
        out, empty, fractional = [], 0, 0
        for n in names:
            it = wb[n].iter_rows(values_only=True)
            head = [str(x) if x is not None else "" for x in next(it, [])]
            missing = [c for c in need if c not in head]
            if missing:
                raise ValueError(f"MISSING_COLUMNS:{n}:{','.join(missing)}")
            isku, ifc, itd, ih, iu, isrc, ir = (head.index(c) for c in need)
            for r in it:
                h = r[ih]
                if h is None or int(h) not in HISTORY_HORIZONS:
                    continue
                if r[iu] is None or r[isku] is None or r[ifc] is None:
                    empty += 1                      # counted, never stored as 0
                    continue
                u = r[iu]
                if isinstance(u, float) and not u.is_integer():
                    fractional += 1                 # 1.4.2: kept as written
                elif isinstance(u, float):
                    u = int(u)
                out.append((str(r[isku]), str(r[ifc]), _iso(r[itd]), u, r[isrc], r[ir]))
        return out, layout, {"rows_without_number": empty, "rows_fractional": fractional}
    finally:
        wb.close()


def _read_sidecar(p: Path, export_run: dict) -> list[tuple] | None:
    """None when the sidecar is unreadable (damaged gzip / deflate body, bad JSON, unexpected shape) or stale: the
    caller rebuilds it from the xlsx; one damaged day never breaks the other days."""
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            doc = json.load(f)
        if (not isinstance(doc, dict) or doc.get("export_run_id") != export_run["id"]
                or doc.get("sha256_of_xlsx") != export_run["sha256"] or doc.get("horizons") != list(HISTORY_HORIZONS)):
            return None
        return _compact(doc.get("rows") or [])
    except (OSError, ValueError, EOFError, zlib.error, TypeError, AttributeError):
        return None


def _compact(rows) -> list[tuple]:
    """Rows as tuples with shared strings (SKU / FC interned: the same objects across days; dates, sources and
    reasons shared within the list)."""
    intern, shared = sys.intern, {}
    sh = shared.setdefault
    return [(intern(str(a)), intern(str(b)), sh(c, c), d, sh(e, e), sh(f, f)) for a, b, c, d, e, f in rows]


def ensure(export_run: dict, create: bool = True) -> dict:
    """State of the sidecar of one export_runs record (id, forecast_date, path, sha256); create=True rebuilds a
    missing / stale one from the recorded file. Returns {status, rows?, layout?, flags?, error?}; status PRESENT,
    CREATED, WOULD_CREATE, FILE_MISSING, SHA256_MISMATCH or UNREADABLE. The xlsx is only read."""
    base = paths.data_dir().resolve()
    vf = (base / export_run["path"]).resolve()
    if base not in vf.parents:
        return {"status": "FILE_MISSING"}
    if not vf.exists() and not vf.stem.endswith(RETIRED_SUFFIX):
        bo = vf.with_name(f"{vf.stem}{RETIRED_SUFFIX}{vf.suffix}")
        if bo.is_file():                             # 1.4.5: renamed by a newer export killed before its record (read)
            vf = bo
    sc = sidecar_path(vf)
    if sc.is_file() and (rows := _read_sidecar(sc, export_run)) is not None:
        return {"status": "PRESENT", "rows": len(rows), "_rows": rows}
    if not vf.is_file():
        return {"status": "FILE_MISSING"}
    if not export_run.get("sha256") or _sha256(vf) != export_run["sha256"]:
        return {"status": "SHA256_MISMATCH"}
    try:
        rows, layout, flags = _rows_of_file(vf)
    except (ValueError, OSError, KeyError, TypeError) as e:
        return {"status": "UNREADABLE", "error": str(e)[:200]}
    out = {"status": "WOULD_CREATE", "rows": len(rows), "layout": layout, "flags": flags,
           "_rows": _compact(rows)}
    if create:
        try:
            write(vf, export_run["id"], export_run["forecast_date"], export_run["sha256"], rows,
                  {**flags, "rebuilt_from_xlsx": layout})
            out["status"] = "CREATED"
        except OSError as e:                         # the rows are still usable for this request
            out.update(status="CREATED_IN_MEMORY_ONLY", error=f"{type(e).__name__}: {e}"[:200])
    return out


def _build_lock(export_run_id: str) -> threading.Lock:
    """The lock of one export (created on first use; the oldest unused locks are dropped above MAX_BUILD_LOCKS)."""
    with _lock:
        lk = _build_locks.get(export_run_id)
        if lk is None:
            lk = _build_locks[export_run_id] = threading.Lock()
            for k in [k for k, v in _build_locks.items() if not v.locked() and k != export_run_id]:
                if len(_build_locks) <= MAX_BUILD_LOCKS:
                    break
                del _build_locks[k]
        else:
            _build_locks.move_to_end(export_run_id)
        return lk


def load(export_run: dict) -> tuple | None:
    """Rows ((sku, fc, target_date, forecast_used, forecast_source, fallback_reason), ...) of one export (LRU, else the
    sidecar, else rebuilt from the xlsx); None when the file cannot be used (missing / changed / unreadable). Two
    requests for the same export: the second waits for the first (lock per export) and takes its rows from the LRU."""
    key = (export_run["id"], export_run.get("sha256"))
    with _lock:
        if key in _lru:
            _lru.move_to_end(key)
            return _lru[key]
    with _build_lock(export_run["id"]):
        return _load(export_run, key)


def _load(export_run: dict, key: tuple) -> tuple | None:
    global _lru_rows
    with _lock:
        if key in _lru:                         # built by the request this one waited for
            _lru.move_to_end(key)
            return _lru[key]
    res = ensure(export_run, create=True)
    rows = res.get("_rows")
    if rows is None:
        log.warning("sel2 published rows unavailable", extra={"ctx": {"export_run_id": export_run["id"],
                                                                      "status": res["status"]}})
        return None
    rows = tuple(rows)
    with _lock:
        _lru[key] = rows
        _lru_rows += len(rows)
        while _lru_rows > MAX_CACHED_ROWS and len(_lru) > 1:
            _, old = _lru.popitem(last=False)
            _lru_rows -= len(old)
    return rows


def clear_cache() -> None:
    global _lru_rows
    with _lock:
        _lru.clear()
        _lru_rows = 0


def latest_exports(c, scope_key: str, run_from: str, run_to: str) -> list[dict]:
    """Newest export (created_at, rowid) of each forecast day of [run_from, run_to] of the scope, newest day first."""
    out, seen = [], set()
    for r in db.rows(c, "SELECT id, forecast_date, path, sha256, created_at, refresh_run_id, "
                        "json_extract(summary_json, '$.model_version') AS model_version FROM export_runs "
                        "WHERE forecast_date BETWEEN ? AND ? AND json_extract(summary_json, '$.scope_key') = ? "
                        "ORDER BY forecast_date DESC, created_at DESC, rowid DESC", (run_from, run_to, scope_key)):
        d = str(r["forecast_date"])[:10]
        if d not in seen:
            seen.add(d)
            out.append({**r, "forecast_date": d})
    return out


def backfill(start, end, apply: bool = False) -> dict:
    """Per forecast day of [start, end]: the sidecar of the newest export_runs record; a missing / stale one is
    rebuilt from the recorded xlsx (apply=True; else WOULD_CREATE with the counts). Idempotent; xlsx only read."""
    s, e = date.fromisoformat(_iso(start)), date.fromisoformat(_iso(end))
    days, d = [], s
    while d <= e:
        with db.read() as c:
            r = db.one(c, "SELECT id, forecast_date, path, sha256 FROM export_runs WHERE forecast_date=? "
                          "ORDER BY created_at DESC, rowid DESC LIMIT 1", (d.isoformat(),))
        item = {"forecast_date": d.isoformat(), "export_run_id": r["id"] if r else None}
        if r is None:
            item["status"] = "NO_EXPORT"
        else:
            with _build_lock(r["id"]):
                res = ensure(r, create=apply)
            res.pop("_rows", None)
            item.update(res)
        days.append(item)
        d += timedelta(days=1)
    log.info("sel2 published backfill", extra={"ctx": {"start": s.isoformat(), "end": e.isoformat(), "apply": apply,
                                                      "days": len(days)}})
    return {"start": s.isoformat(), "end": e.isoformat(), "apply": apply, "days": days}
