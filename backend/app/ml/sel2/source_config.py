"""1.4.0 SEL2: forecast source per SKU x FC (forecast_source_config; a missing row = AVG_DEMAND, the default) with its
append-only history (forecast_source_config_history).

  set_one          one change, explicit confirmation required; history channel UI (or API)
  preview_upload   .xlsx with the columns sku_code, fc_code, forecast_source (+ optional ghi_chu): parsed and validated,
                   nothing written; the planned changes are kept in this process only (PREVIEW_TTL_SECONDS) under a
                   preview_id
  apply_upload     the changes of a preview without any error row, ONE transaction, ONE batch_id, history channel
                   UPLOAD; refused when the configuration of ANY SKU x FC of the file (changed or unchanged rows)
                   changed since the preview (stale)
  download_xlsx    the configured rows (a note row says that a missing row = AVG_DEMAND); the file uploads back with
                   0 changes. The SKU x FC without a row are not listed (their source is the default). Written with
                   xlsx_stream (inline strings): a note starting with "=" stays text (openpyxl would write a formula)
                   and a note longer than 32,767 characters is not truncated.

A row is "changed" when its source differs from the effective source, or when the file has a ghi_chu column and the
note differs from the stored one (an empty cell = no note). 1.4.5: an explicit AVG_DEMAND for a SKU x FC WITHOUT a row
(UI / API set_one, or an upload row) is a change too: it writes the row + a history row, so a code a user set to
AVG_DEMAND is told apart from a default code (export.auto_switch_new_codes switches default codes only). Writing is refused while sel2_pipeline.enabled = False.
An upload passes the safety checks of the Excel import (data/excel_io.check_xlsx: .xlsx only, workbook parts, no
macro, bounded uncompressed size) before openpyxl reads it.
"""
from __future__ import annotations

import getpass
import io
import os
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

from openpyxl import load_workbook

from ... import db
from ... import settings_service as ss
from ...messages import AppError
from ...timeutil import iso, now_iso, now_utc
from .xlsx_stream import Sheet, write_xlsx

SOURCES = ("AVG_DEMAND", "LIGHTGBM")
DEFAULT_SOURCE = "AVG_DEMAND"
CHANNELS = ("UI", "UPLOAD", "API")
REQUIRED_COLS = ("sku_code", "fc_code", "forecast_source")
HEADER_SCAN_ROWS = 10                 # the header row is searched in the first rows (the download has a note row)
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_ROWS = 200_000
MAX_LISTED = 1000                     # error rows / changes returned by a preview
PREVIEW_TTL_SECONDS = 30 * 60
MAX_PREVIEWS = 5
NOTE_VI = "Cặp SKU x FC không có trong bảng = AVG_DEMAND (mặc định)."
NOTE_EN = "A SKU x FC missing from this table = AVG_DEMAND (default)."
HISTORY_COLS = "id, sku_code, fc_code, old_source, new_source, ghi_chu, changed_by, changed_at, channel, batch_id"

_previews: dict[str, dict] = {}
_lock = threading.Lock()


def actor() -> str:
    """Who changes the configuration: the Windows account running the app (single-user, local-only writes)."""
    try:
        return getpass.getuser() or "local"
    except Exception:  # noqa: BLE001
        return "local"


def _require_enabled(conn=None) -> None:
    if not ss.get("sel2_pipeline", conn).enabled:
        raise AppError("SEL2_PIPELINE_DISABLED", 409)


def _text(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s or None


def normalise_source(v) -> str | None:
    s = _text(v)
    return s.upper() if s else None


def get_effective(conn, sku_code: str, fc_code: str) -> dict:
    r = db.one(conn, "SELECT sku_code, fc_code, forecast_source, ghi_chu, updated_by, updated_at "
                     "FROM forecast_source_config WHERE sku_code=? AND fc_code=?", (sku_code, fc_code))
    if r:
        return {**r, "configured": True}
    return {"sku_code": sku_code, "fc_code": fc_code, "forecast_source": DEFAULT_SOURCE, "ghi_chu": None,
            "updated_by": None, "updated_at": None, "configured": False}


def configured_map(conn) -> dict[tuple[str, str], str]:
    """(sku_code, fc_code) -> source of every configured row (a key not in it = AVG_DEMAND)."""
    return {(r[0], r[1]): r[2] for r in conn.execute("SELECT sku_code, fc_code, forecast_source FROM forecast_source_config")}


def list_config(conn, sku_code: str | None = None, fc_code: str | None = None, source: str | None = None,
                limit: int = 100, offset: int = 0) -> dict:
    """Configured rows (substring search on sku_code / fc_code, filter by source), newest change first."""
    where, params = [], []
    if sku_code:
        where.append("instr(lower(sku_code), lower(?)) > 0")
        params.append(sku_code.strip())
    if fc_code:
        where.append("instr(lower(fc_code), lower(?)) > 0")
        params.append(fc_code.strip())
    if source:
        src = normalise_source(source)
        if src not in SOURCES:
            raise AppError("SOURCE_CONFIG_INVALID_SOURCE", 422, detail=str(source))
        where.append("forecast_source=?")
        params.append(src)
    w = f" WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM forecast_source_config{w}", params).fetchone()[0]
    items = db.rows(conn, f"SELECT sku_code, fc_code, forecast_source, ghi_chu, updated_by, updated_at "
                          f"FROM forecast_source_config{w} ORDER BY updated_at DESC, rowid DESC LIMIT ? OFFSET ?",
                    (*params, int(limit), int(offset)))
    counts = dict(conn.execute("SELECT forecast_source, COUNT(*) FROM forecast_source_config GROUP BY forecast_source"))
    return {"total": total, "limit": limit, "offset": offset, "items": items, "default_source": DEFAULT_SOURCE,
            "configured_by_source": {s: counts.get(s, 0) for s in SOURCES}}


def _write(c, sku: str, fc: str, old: dict, new_source: str, ghi_chu: str | None, by: str, at: str, channel: str,
           batch_id: str | None) -> None:
    c.execute("INSERT INTO forecast_source_config(sku_code, fc_code, forecast_source, ghi_chu, updated_by, updated_at) "
              "VALUES (?,?,?,?,?,?) ON CONFLICT(sku_code, fc_code) DO UPDATE SET forecast_source=excluded.forecast_source, "
              "ghi_chu=excluded.ghi_chu, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
              (sku, fc, new_source, ghi_chu, by, at))
    c.execute("INSERT INTO forecast_source_config_history(sku_code, fc_code, old_source, new_source, ghi_chu, changed_by, "
              "changed_at, channel, batch_id) VALUES (?,?,?,?,?,?,?,?,?)",
              (sku, fc, old["forecast_source"] if old["configured"] else None, new_source, ghi_chu, by, at, channel,
               batch_id))


def set_one(sku_code: str, fc_code: str, forecast_source: str, ghi_chu: str | None = None, confirm: bool = False,
            changed_by: str | None = None, channel: str = "UI") -> dict:
    """One change (confirm=True required). No change (same source and note of a CONFIGURED row) writes nothing; an
    explicit set of a SKU x FC without a row is always recorded (1.4.5, even AVG_DEMAND = the default)."""
    if confirm is not True:
        raise AppError("SOURCE_CONFIG_CONFIRM_REQUIRED", 409)
    sku, fc = _text(sku_code), _text(fc_code)
    if not sku or not fc:
        raise AppError("SOURCE_CONFIG_INVALID_KEY", 422)
    src = normalise_source(forecast_source)
    if src not in SOURCES:
        raise AppError("SOURCE_CONFIG_INVALID_SOURCE", 422, detail=str(forecast_source))
    if channel not in CHANNELS:
        raise AppError("VALIDATION_ERROR", 422, detail=f"channel {channel!r}")
    note = _text(ghi_chu)
    with db.tx() as c:
        _require_enabled(c)
        old = get_effective(c, sku, fc)
        if old["configured"] and old["forecast_source"] == src and old["ghi_chu"] == note:
            return {"changed": False, "before": old, "after": old}
        by, at = changed_by or actor(), now_iso()
        _write(c, sku, fc, old, src, note, by, at, channel, None)
        db.audit(c, "FORECAST_SOURCE_SET", "forecast_source_config", f"{sku}|{fc}",
                 {"from": old["forecast_source"], "to": src, "channel": channel})
        after = get_effective(c, sku, fc)
    return {"changed": True, "before": old, "after": after}


# ------------------------------------------------------------------ upload: preview, apply
_NOT_CONFIGURED = (None, None)          # state of a SKU x FC without a row (a configured row always has a source)


def _config_state(conn) -> dict[tuple[str, str], tuple[str, str | None]]:
    return {(r[0], r[1]): (r[2], r[3]) for r in
            conn.execute("SELECT sku_code, fc_code, forecast_source, ghi_chu FROM forecast_source_config")}


def _purge(now: float) -> None:
    for k in [k for k, v in _previews.items() if v["expires"] <= now]:
        del _previews[k]


def _check_container(data: bytes, filename: str | None) -> None:
    """The checks of the Excel import (excel_io.check_xlsx) on the uploaded bytes (a temporary copy: the check reads a
    path). A container that cannot be read keeps SOURCE_CONFIG_FILE_INVALID, a too large content
    SOURCE_CONFIG_FILE_TOO_LARGE; NOT_XLSX / MACRO_NOT_ALLOWED are the import's codes."""
    from ...data import excel_io
    fd, name = tempfile.mkstemp(prefix="df-source-config-", suffix=".xlsx")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            excel_io.check_xlsx(Path(name), filename or "upload.xlsx", MAX_UPLOAD_BYTES // (1024 * 1024) + 1)
        except AppError as e:
            if e.code in ("CORRUPT_FILE", "EMPTY_FILE"):
                raise AppError("SOURCE_CONFIG_FILE_INVALID", 422, detail=e.detail) from None
            if e.code == "FILE_TOO_LARGE":
                raise AppError("SOURCE_CONFIG_FILE_TOO_LARGE", 413, detail=e.detail) from None
            raise
    finally:
        try:
            os.unlink(name)
        except OSError:
            pass


def _read_rows(fileobj, filename: str | None = None) -> tuple[list[str], list[tuple[int, list]]]:
    data = fileobj.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise AppError("SOURCE_CONFIG_FILE_TOO_LARGE", 413, detail=f"> {MAX_UPLOAD_BYTES} bytes")
    _check_container(data, filename)
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001 - not a readable .xlsx
        raise AppError("SOURCE_CONFIG_FILE_INVALID", 422, detail=type(e).__name__) from None
    try:
        it = wb.worksheets[0].iter_rows(values_only=True)
        header, n = None, 0
        for n, row in enumerate(it, start=1):
            names = [(_text(v) or "").lower() for v in row]
            if all(c in names for c in REQUIRED_COLS):
                header = names
                break
            if n >= HEADER_SCAN_ROWS:
                break
        if header is None:
            raise AppError("SOURCE_CONFIG_BAD_HEADER", 422, detail=", ".join(REQUIRED_COLS))
        rows = []
        for i, row in enumerate(it, start=n + 1):
            vals = list(row)
            if all(_text(v) is None for v in vals):
                continue
            rows.append((i, vals))
            if len(rows) > MAX_UPLOAD_ROWS:
                raise AppError("SOURCE_CONFIG_FILE_TOO_LARGE", 413, detail=f"> {MAX_UPLOAD_ROWS} rows")
        return header, rows
    finally:
        wb.close()


def preview_upload(fileobj, filename: str | None = None) -> dict:
    """Parse and validate the file against the current configuration; nothing is written."""
    header, rows = _read_rows(fileobj, filename)
    col = {c: header.index(c) for c in REQUIRED_COLS}
    has_note = "ghi_chu" in header
    if has_note:
        col["ghi_chu"] = header.index("ghi_chu")

    def cell(vals, name):
        i = col[name]
        return vals[i] if i < len(vals) else None

    parsed, errors, seen = [], [], {}
    for rownum, vals in rows:
        sku, fc = _text(cell(vals, "sku_code")), _text(cell(vals, "fc_code"))
        raw = cell(vals, "forecast_source")
        src = normalise_source(raw)
        reason = ("MISSING_SKU_CODE" if not sku else "MISSING_FC_CODE" if not fc else
                  "MISSING_SOURCE" if not src else "UNKNOWN_SOURCE" if src not in SOURCES else None)
        rec = {"row": rownum, "sku_code": sku, "fc_code": fc, "forecast_source": _text(raw),
               "ghi_chu": _text(cell(vals, "ghi_chu")) if has_note else None, "reason": reason}
        if reason is None:
            rec["forecast_source"] = src
            seen.setdefault((sku, fc), []).append(rec)
        parsed.append(rec)
    for recs in seen.values():          # every occurrence of a key repeated in the file is an error
        if len(recs) > 1:
            for r in recs:
                r["reason"] = "DUPLICATE_IN_FILE"
    errors = [r for r in parsed if r["reason"]]
    changes, unchanged = [], 0
    with db.read() as c:
        current = _config_state(c)
    snapshot = {}                       # every SKU x FC of the file as seen now (checked again by apply_upload)
    for r in parsed:
        if r["reason"]:
            continue
        snapshot[(r["sku_code"], r["fc_code"])] = current.get((r["sku_code"], r["fc_code"]), _NOT_CONFIGURED)
        cur = current.get((r["sku_code"], r["fc_code"]))
        old_src = cur[0] if cur else DEFAULT_SOURCE
        old_note = cur[1] if cur else None
        new_note = r["ghi_chu"] if has_note else old_note
        if cur is not None and old_src == r["forecast_source"] and old_note == new_note:
            unchanged += 1                  # 1.4.5: a row for an unconfigured key is recorded (user-set)
            continue
        changes.append({"row": r["row"], "sku_code": r["sku_code"], "fc_code": r["fc_code"],
                        "old_source": cur[0] if cur else None, "effective_old_source": old_src,
                        "new_source": r["forecast_source"], "old_ghi_chu": old_note, "ghi_chu": new_note})
    counts = {"rows": len(parsed), "changed": len(changes), "unchanged": unchanged, "errors": len(errors)}
    now = time.monotonic()
    pid = db.new_id("SCP")
    with _lock:
        _purge(now)
        while len(_previews) >= MAX_PREVIEWS:
            del _previews[min(_previews, key=lambda k: _previews[k]["expires"])]
        _previews[pid] = {"expires": now + PREVIEW_TTL_SECONDS, "changes": changes, "counts": counts,
                          "filename": filename, "has_errors": bool(errors), "snapshot": snapshot}
    return {"preview_id": pid, "filename": filename, "counts": counts, "has_ghi_chu": has_note,
            "expires_at": iso(now_utc() + timedelta(seconds=PREVIEW_TTL_SECONDS)),
            "errors": errors[:MAX_LISTED], "errors_truncated": len(errors) > MAX_LISTED,
            "changes": changes[:MAX_LISTED], "changes_truncated": len(changes) > MAX_LISTED,
            "can_apply": not errors and bool(changes)}


def apply_upload(preview_id: str, confirm: bool = False, changed_by: str | None = None) -> dict:
    """Write every change of the preview in ONE transaction with ONE batch_id (history channel UPLOAD). Refused when
    the preview is unknown / expired, has error rows, or the configuration changed since the preview."""
    if confirm is not True:
        raise AppError("SOURCE_CONFIG_CONFIRM_REQUIRED", 409)
    with _lock:
        _purge(time.monotonic())
        pv = _previews.get(preview_id)
    if pv is None:
        raise AppError("SOURCE_CONFIG_PREVIEW_NOT_FOUND", 404)
    if pv["has_errors"]:
        raise AppError("SOURCE_CONFIG_UPLOAD_HAS_ERRORS", 422, detail=f"{pv['counts']['errors']} rows")
    batch_id = db.new_id("SCU") if pv["changes"] else None
    by, at = changed_by or actor(), now_iso()
    with db.tx() as c:
        _require_enabled(c)
        # every SKU x FC of the file, changed or not: the preview showed them as they were then
        state = _config_state(c)
        for k, seen in pv["snapshot"].items():
            if state.get(k, _NOT_CONFIGURED) != seen:
                raise AppError("SOURCE_CONFIG_PREVIEW_STALE", 409, detail=f"{k[0]} x {k[1]}")
        for ch in pv["changes"]:
            old = get_effective(c, ch["sku_code"], ch["fc_code"])
            _write(c, ch["sku_code"], ch["fc_code"], old, ch["new_source"], ch["ghi_chu"], by, at, "UPLOAD", batch_id)
        if pv["changes"]:
            db.audit(c, "FORECAST_SOURCE_UPLOAD_APPLIED", "forecast_source_config", batch_id,
                     {"changed": len(pv["changes"]), "filename": pv["filename"]})
    with _lock:
        _previews.pop(preview_id, None)
    return {"batch_id": batch_id, "applied": len(pv["changes"]), "counts": pv["counts"]}


# ------------------------------------------------------------------ download, history
def _book_bytes(sheet: Sheet) -> bytes:
    buf = io.BytesIO()
    write_xlsx(buf, [sheet])
    return buf.getvalue()


def download_xlsx() -> bytes:
    """Row 1 = the note (header row of the writer, one cell), row 2 = the column names, then the configured rows."""
    cols = ["sku_code", "fc_code", "forecast_source", "ghi_chu", "updated_by", "updated_at"]
    with db.read() as c:
        rows = [cols] + [list(r) for r in c.execute(
            "SELECT sku_code, fc_code, forecast_source, ghi_chu, updated_by, updated_at "
            "FROM forecast_source_config ORDER BY sku_code, fc_code")]
    return _book_bytes(Sheet("forecast_source", [f"{NOTE_VI} / {NOTE_EN}"] + [None] * (len(cols) - 1), rows))


def history(conn, sku_code: str | None = None, fc_code: str | None = None, batch_id: str | None = None,
            limit: int = 100, offset: int = 0) -> dict:
    """History rows, newest first (exact sku_code / fc_code / batch_id filters)."""
    where, params = [], []
    for name, v in (("sku_code", sku_code), ("fc_code", fc_code), ("batch_id", batch_id)):
        if v:
            where.append(f"{name}=?")
            params.append(v.strip())
    w = f" WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) FROM forecast_source_config_history{w}", params).fetchone()[0]
    items = db.rows(conn, f"SELECT {HISTORY_COLS} FROM forecast_source_config_history{w} "
                          f"ORDER BY changed_at DESC, rowid DESC LIMIT ? OFFSET ?", (*params, int(limit), int(offset)))
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def history_xlsx(conn, sku_code: str | None = None, fc_code: str | None = None, batch_id: str | None = None) -> bytes:
    cols = [c.strip() for c in HISTORY_COLS.split(",")]
    rows = []
    total = history(conn, sku_code, fc_code, batch_id, limit=1)["total"]
    step = 5000
    for off in range(0, total, step):
        for r in history(conn, sku_code, fc_code, batch_id, limit=step, offset=off)["items"]:
            rows.append([r[k] for k in cols])
    return _book_bytes(Sheet("history", cols, rows))
