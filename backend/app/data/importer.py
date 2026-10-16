"""Excel import lifecycle: upload -> inspect -> map/validate (PENDING_REVIEW) -> confirm | cancel.

Every import is an independent batch. Replacing batch A swaps A's data for the new file atomically and
never touches other batches, DEMO data, BigQuery data or already-published forecast runs.
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from pathlib import Path

import pandas as pd

from .. import db, paths
from .. import settings_service as ss
from ..messages import AppError
from ..timeutil import now_iso
from . import excel_io
from .demand import aggregate_batch
from .schema import FIELD_NAMES, suggest_mapping
from .validation import normalize_and_validate

log = logging.getLogger("df.import")
_UPLOAD_ID_CHARS = set("0123456789abcdef")


def _upload_paths(upload_id: str) -> tuple[Path, Path]:
    if len(upload_id) != 32 or not set(upload_id) <= _UPLOAD_ID_CHARS:  # path traversal guard
        raise AppError("BATCH_NOT_FOUND", 404, detail="invalid upload id")
    d = paths.uploads_dir()
    return d / f"{upload_id}.xlsx", d / f"{upload_id}.json"


def save_upload(fileobj, original_name: str, replace_batch_id: str | None = None) -> dict:
    cfg = ss.get("import")
    upload_id = secrets.token_hex(16)
    fpath, mpath = _upload_paths(upload_id)
    h = hashlib.sha256()
    size = 0
    limit = cfg.max_file_mb * 1024 * 1024
    with open(fpath, "wb") as out:
        while chunk := fileobj.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                out.close()
                fpath.unlink(missing_ok=True)
                raise AppError("FILE_TOO_LARGE", 413, detail=f"> {cfg.max_file_mb} MB")
            h.update(chunk)
            out.write(chunk)
    try:
        excel_io.check_xlsx(fpath, original_name, cfg.max_file_mb)
        info = excel_io.inspect_workbook(fpath)
    except AppError:
        fpath.unlink(missing_ok=True)
        raise
    if replace_batch_id:
        with db.read() as c:
            t = db.one(c, "SELECT id, status, data_source FROM import_batches WHERE id=?", (replace_batch_id,))
        if not t or t["status"] != "ACTIVE" or t["data_source"] != "MANUAL_IMPORT":
            fpath.unlink(missing_ok=True)
            raise AppError("REPLACE_TARGET_INVALID", 409, detail=replace_batch_id)
    safe_name = Path(original_name).name[:200]
    meta = {"upload_id": upload_id, "file_name": safe_name, "sha256": h.hexdigest(), "size": size,
            "replace_batch_id": replace_batch_id, "uploaded_at": now_iso()}
    mpath.write_text(json.dumps(meta), encoding="utf-8")
    sheet = info["suggested_sheet"]
    headers = next((s["headers"] for s in info["sheets"] if s["name"] == sheet), [])
    log.info("upload saved", extra={"ctx": {"upload_id": upload_id, "size": size}})
    return {**meta, **info, "suggested_mapping": suggest_mapping(headers, cfg.column_aliases) if sheet else None}


def suggest_for_sheet(upload_id: str, sheet: str) -> dict:
    fpath, _ = _upload_paths(upload_id)
    if not fpath.exists():
        raise AppError("BATCH_NOT_FOUND", 404, detail="upload expired")
    info = excel_io.inspect_workbook(fpath)
    s = next((s for s in info["sheets"] if s["name"] == sheet), None)
    if not s:
        raise AppError("SHEET_NOT_FOUND", 404, detail=sheet)
    return {"headers": s["headers"], "suggested_mapping": suggest_mapping(s["headers"], ss.get("import").column_aliases)}


def _df_records(df: pd.DataFrame, cols: list[str]):
    sub = df[cols].astype(object)
    sub = sub.where(pd.notna(sub), None)
    return list(sub.itertuples(index=False, name=None))


def validate_upload(upload_id: str, sheet: str | None, mapping: dict[str, str | None]) -> dict:
    fpath, mpath = _upload_paths(upload_id)
    if not fpath.exists():
        raise AppError("BATCH_NOT_FOUND", 404, detail="upload expired")
    meta = json.loads(mpath.read_text(encoding="utf-8"))
    cfg = ss.get("import")
    pol = ss.get("data_policy")
    if not sheet:
        info = excel_io.inspect_workbook(fpath)
        sheet = info["suggested_sheet"]
        if not sheet:
            raise AppError("SHEET_NOT_FOUND", 400, detail="several sheets — choose one")
    mapping = {k: (v or None) for k, v in mapping.items() if k in FIELD_NAMES}
    used = [v for v in mapping.values() if v]
    if len(used) != len(set(used)):
        raise AppError("DUPLICATE_COLUMN_MAPPING")
    missing = [f for f in ("sku_id", "fc_id", "order_qty") if not mapping.get(f)]
    if not mapping.get("created_at") and not mapping.get("order_date"):
        missing.append("created_at|order_date")
    if missing:
        raise AppError("MISSING_REQUIRED_COLUMNS", 422, detail=", ".join(missing), fields=missing)
    raw = excel_io.read_sheet(fpath, sheet, mapping, cfg.max_rows)
    if raw.empty:
        raise AppError("EMPTY_FILE", detail=sheet)
    valid, issues, summary = normalize_and_validate(raw, grain_conflict_policy=cfg.grain_conflict_policy,
                                                    min_date=pol.min_date, price_outlier_factor=pol.price_outlier_factor)
    batch_id = db.new_id("IMP")
    with db.tx() as c:
        # a re-validation of the same upload supersedes the earlier pending batch
        for old in db.rows(c, "SELECT id FROM import_batches WHERE status='PENDING_REVIEW' AND note=?", (upload_id,)):
            _purge_lines(c, old["id"])
            c.execute("UPDATE import_batches SET status='CANCELLED', closed_at=? WHERE id=?", (now_iso(), old["id"]))
        c.execute(
            """INSERT INTO import_batches(id, data_source, status, file_name, file_sha256, sheet_name, column_mapping_json,
                   replaces_batch_id, total_rows, valid_rows, error_rows, duplicate_rows, min_order_date, max_order_date,
                   validation_json, created_at, note)
               VALUES (?, 'MANUAL_IMPORT', 'PENDING_REVIEW', ?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (batch_id, meta["file_name"], meta["sha256"], sheet, json.dumps(mapping), meta.get("replace_batch_id"),
             summary["total_rows"], summary["valid_rows"], summary["error_rows"], summary["duplicate_rows"],
             summary["min_order_date"], summary["max_order_date"], json.dumps(summary), now_iso(), upload_id))
        _insert_lines(c, batch_id, valid)
        if len(issues):
            c.executemany("INSERT INTO import_row_errors(batch_id, row_number, field, code, severity, raw_value) "
                          "VALUES (?,?,?,?,?,?)",
                          [(batch_id, int(r[0]) if r[0] is not None else None, r[1], r[2], r[3], r[4])
                           for r in _df_records(issues, ["row_number", "field", "code", "severity", "raw_value"])])
        db.audit(c, "IMPORT_VALIDATED", "import_batch", batch_id,
                 {"file": meta["file_name"], "valid": summary["valid_rows"], "errors": summary["error_rows"]})
    log.info("import validated", extra={"ctx": {"batch_id": batch_id, **{k: summary[k] for k in
                                                ("total_rows", "valid_rows", "error_rows", "duplicate_rows")}}})
    return batch_detail(batch_id)


def _insert_lines(c, batch_id: str, valid: pd.DataFrame) -> None:
    cols = ["row_number", "order_id", "created_at", "order_date", "sku_id", "fc_id", "order_qty", "unit_price",
            "discount_amount", "promotion_flag", "promotion_id", "voucher_flag", "voucher_amount",
            "source_updated_at", "source_batch_id"]
    recs = _df_records(valid, cols)
    c.executemany(f"INSERT INTO order_lines(batch_id, {', '.join(cols)}) VALUES (?, {', '.join('?' * len(cols))})",
                  [(batch_id, *r) for r in recs])


def _purge_lines(c, batch_id: str) -> None:
    c.execute("DELETE FROM order_lines WHERE batch_id=?", (batch_id,))
    c.execute("DELETE FROM import_row_errors WHERE batch_id=?", (batch_id,))
    c.execute("DELETE FROM demand_daily WHERE scope_key=?", (batch_id,))


def batch_detail(batch_id: str, preview_rows: int = 50) -> dict:
    with db.read() as c:
        b = db.one(c, "SELECT * FROM import_batches WHERE id=?", (batch_id,))
        if not b:
            raise AppError("BATCH_NOT_FOUND", 404, detail=batch_id)
        b["validation"] = json.loads(b.pop("validation_json") or "{}")
        b["column_mapping"] = json.loads(b.pop("column_mapping_json") or "{}")
        b["preview"] = db.rows(c, "SELECT row_number, order_id, created_at, order_date, sku_id, fc_id, order_qty, "
                                  "unit_price, discount_amount, promotion_flag, voucher_flag FROM order_lines "
                                  "WHERE batch_id=? ORDER BY id LIMIT ?", (batch_id, preview_rows))
        b["issues_sample"] = db.rows(c, "SELECT row_number, field, code, severity, raw_value FROM import_row_errors "
                                        "WHERE batch_id=? ORDER BY CASE severity WHEN 'ERROR' THEN 0 WHEN 'DUPLICATE' "
                                        "THEN 1 WHEN 'WARNING' THEN 2 ELSE 3 END, row_number LIMIT 200", (batch_id,))
        b["issue_count"] = c.execute("SELECT COUNT(*) FROM import_row_errors WHERE batch_id=?", (batch_id,)).fetchone()[0]
        b["demand_rows"] = c.execute("SELECT COUNT(*) FROM demand_daily WHERE scope_key=?", (batch_id,)).fetchone()[0]
        g = ss.get("general", c)
        b["is_active_dataset"] = g.active_import_batch_id == batch_id
    b["can_confirm"] = b["status"] == "PENDING_REVIEW" and b["valid_rows"] > 0
    b["requires_error_ack"] = b["error_rows"] > 0
    return b


def error_report(batch_id: str, lang: str = "vi") -> bytes:
    with db.read() as c:
        b = db.one(c, "SELECT * FROM import_batches WHERE id=?", (batch_id,))
        if not b:
            raise AppError("BATCH_NOT_FOUND", 404, detail=batch_id)
        issues = db.rows(c, "SELECT row_number, field, code, severity, raw_value FROM import_row_errors "
                            "WHERE batch_id=? ORDER BY row_number", (batch_id,))
    return excel_io.build_error_report(b, issues, lang)


def confirm(batch_id: str, accept_row_errors: bool = False, set_active: bool = True) -> dict:
    with db.tx() as c:
        b = db.one(c, "SELECT * FROM import_batches WHERE id=?", (batch_id,))
        if not b:
            raise AppError("BATCH_NOT_FOUND", 404, detail=batch_id)
        if b["status"] != "PENDING_REVIEW":
            raise AppError("BATCH_NOT_PENDING", 409, detail=b["status"])
        if b["valid_rows"] <= 0:
            raise AppError("NO_VALID_ROWS", 422)
        if b["error_rows"] > 0 and not accept_row_errors:
            raise AppError("ROW_ERRORS_NOT_ACKNOWLEDGED", 422, detail=str(b["error_rows"]))
        target = b["replaces_batch_id"]
        g = ss.get("general", c)
        if target:
            t = db.one(c, "SELECT * FROM import_batches WHERE id=?", (target,))
            if not t or t["status"] != "ACTIVE" or t["data_source"] != "MANUAL_IMPORT":
                raise AppError("REPLACE_TARGET_INVALID", 409, detail=target)
            _purge_lines(c, target)
            c.execute("UPDATE import_batches SET status='REPLACED', replaced_by_batch_id=?, closed_at=? WHERE id=?",
                      (batch_id, now_iso(), target))
            db.audit(c, "IMPORT_BATCH_REPLACED", "import_batch", target, {"replaced_by": batch_id})
        c.execute("UPDATE import_batches SET status='ACTIVE', confirmed_at=? WHERE id=?", (now_iso(), batch_id))
        n = aggregate_batch(c, batch_id, "MANUAL_IMPORT")
        if set_active or (target and g.active_import_batch_id == target):
            ss.update("general", {"active_import_batch_id": batch_id}, note=f"dataset -> {batch_id}", conn=c)
        db.audit(c, "IMPORT_CONFIRMED", "import_batch", batch_id, {"replaces": target, "demand_rows": n})
    _cleanup_upload(b["note"])
    log.info("import confirmed", extra={"ctx": {"batch_id": batch_id, "replaces": target}})
    return batch_detail(batch_id)


def cancel(batch_id: str) -> dict:
    with db.tx() as c:
        b = db.one(c, "SELECT * FROM import_batches WHERE id=?", (batch_id,))
        if not b:
            raise AppError("BATCH_NOT_FOUND", 404, detail=batch_id)
        if b["status"] != "PENDING_REVIEW":
            raise AppError("BATCH_NOT_PENDING", 409, detail=b["status"])
        _purge_lines(c, batch_id)
        c.execute("UPDATE import_batches SET status='CANCELLED', closed_at=? WHERE id=?", (now_iso(), batch_id))
        db.audit(c, "IMPORT_CANCELLED", "import_batch", batch_id)
    _cleanup_upload(b["note"])
    return batch_detail(batch_id)


def delete_batch(batch_id: str, confirm_text: str) -> dict:
    if confirm_text != batch_id:
        raise AppError("CONFIRMATION_MISMATCH", 422)
    with db.tx() as c:
        b = db.one(c, "SELECT * FROM import_batches WHERE id=?", (batch_id,))
        if not b:
            raise AppError("BATCH_NOT_FOUND", 404, detail=batch_id)
        if b["status"] != "ACTIVE" or b["data_source"] != "MANUAL_IMPORT":
            raise AppError("REPLACE_TARGET_INVALID", 409, detail=b["status"])
        _purge_lines(c, batch_id)
        c.execute("UPDATE import_batches SET status='DELETED', closed_at=? WHERE id=?", (now_iso(), batch_id))
        g = ss.get("general", c)
        if g.active_import_batch_id == batch_id:
            ss.update("general", {"active_import_batch_id": None}, note=f"dataset {batch_id} deleted", conn=c)
        db.audit(c, "IMPORT_BATCH_DELETED", "import_batch", batch_id,
                 {"note": "order lines purged; batch metadata, audit and published forecasts kept"})
    return batch_detail(batch_id)


def set_active_dataset(batch_id: str) -> dict:
    with db.tx() as c:
        b = db.one(c, "SELECT * FROM import_batches WHERE id=? AND status='ACTIVE' AND data_source='MANUAL_IMPORT'",
                   (batch_id,))
        if not b:
            raise AppError("REPLACE_TARGET_INVALID", 409, detail=batch_id)
        ss.update("general", {"active_import_batch_id": batch_id}, note=f"dataset -> {batch_id}", conn=c)
    return batch_detail(batch_id)


def list_batches(include_demo: bool = False) -> list[dict]:
    with db.read() as c:
        g = ss.get("general", c)
        sql = ("SELECT id, data_source, status, file_name, sheet_name, total_rows, valid_rows, error_rows, duplicate_rows, "
               "min_order_date, max_order_date, created_at, confirmed_at, closed_at, replaces_batch_id, "
               "replaced_by_batch_id FROM import_batches")
        if not include_demo:
            sql += " WHERE data_source='MANUAL_IMPORT'"
        out = db.rows(c, sql + " ORDER BY created_at DESC, rowid DESC")
    for r in out:
        r["is_active_dataset"] = r["id"] == g.active_import_batch_id
    return out


def _cleanup_upload(upload_id: str | None) -> None:
    if not upload_id:
        return
    try:
        for p in _upload_paths(upload_id):
            p.unlink(missing_ok=True)
    except AppError:
        pass


def cleanup_stale_uploads(max_age_hours: int = 24) -> int:
    """Remove temporary uploads that were never validated/confirmed (they are not batches)."""
    import time
    n = 0
    cutoff = time.time() - max_age_hours * 3600
    for p in paths.uploads_dir().glob("*"):
        if p.is_file() and p.stat().st_mtime < cutoff and p.suffix in (".xlsx", ".json"):
            p.unlink(missing_ok=True)
            n += 1
    return n
