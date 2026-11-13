"""1.4.0 SEL2: the daily Excel the purchasing team uses (<data folder>\\<sel2_pipeline.export_subdir>\\YYYYMMDD\\).

Every call writes a NEW version: du_bao_YYYYMMDD_vN.xlsx (never overwritten, never changed later) and the copy of the
latest version du_bao_YYYYMMDD.xlsx (written to a temporary file, then replaced). export_runs keeps one record per
version (path relative to the data folder, sha256, row count, stale flag, summary).
1.4.5 (owner decision 06/11/2026, one final file per day): once the new version file is written, the earlier version
files of the same day (recorded versions below it) are renamed du_bao_YYYYMMDD_vK_bo.xlsx (never deleted, content and
sha256 unchanged) and their export_runs.path is updated in the SAME transaction as the record of the new version (a
failed record renames them back). A file that cannot be renamed (open in Excel) keeps its name and record: logged, the
new version is flagged OLD_VERSION_RENAME_FAILED, never failed. A record whose file is gone but whose _bo file exists
(rename done, record not updated: crash in between) gets its path repaired by the next export of the day.

Versions across processes (the scheduled export runs in the server, sel2-export in a CLI process): a version number is
reserved by creating .du_bao_YYYYMMDD_vN.reserved exclusively (O_EXCL) in the day folder; a number whose file, record or
reservation exists is skipped (a reservation left by a crashed process leaves a gap, never a clash; .reserved / .tmp
files older than 1 hour are removed before reserving). Temporary files have a unique name (pid + random) created
exclusively. The version file and its export_runs record are written first;
the latest copy comes after: when it cannot be replaced (du_bao_YYYYMMDD.xlsx open in Excel) the version is kept and
flagged LATEST_COPY_LOCKED (export_runs.flags and the result), never failed. A day without a completed AVG_DEMAND read
is flagged AVG_NO_READ (file level: TOM_TAT and export_runs.flags).

  DU_BAO_<fc_code>  (1.4.4, 20-day layout below) one sheet per warehouse; the rows of horizon 1..7 are the rows
           described here (cach_tinh SEL2).
  DU_BAO   (up to 1.4.3) one row per SKU x FC x target day (D .. D+6): the union of the SKU x FC of the SEL2 run used
           and of the SKU x FC with an AVG_DEMAND row of day D. forecast_used
           follows the owner's fixed rule 05/11/2026 (with its supplement of the same day):
           Reference run: today's run (the SEL2 run of D); without it (failed / missing) the most recent SEL2 run of
           D-3 .. D-1 (same scope_key); runs older than D-3 are never a reference and never supply numbers.
           R1 configured LIGHTGBM and today's run has a number for that day (0 included) -> that number (a 0 is never
              replaced by the AVG_DEMAND value);
           R2 configured LIGHTGBM, SKU x FC outside the scope of the reference run -> 0 for every sku_code prefix,
              fallback_reason NGOAI_PHAM_VI_GAN_0 (without a reference run R2 never applies);
           R3' configured LIGHTGBM, in the scope of the reference run without a number of today's run for that day (no
              run of D, or today's run lacks that day) -> the number (0 included) of the most recent SEL2 run of
              D-3 .. D-1 that has one for exactly that SKU x FC x target day, fallback_reason DUNG_SO_LAN_CHAY_TRUOC,
              row flag LAN_CHAY_TRUOC:YYYY-MM-DD (forecast day of that run);
           R3'' no such number (or no reference run at all) -> the AVG_DEMAND value of day D, fallback_reason STALE
              (stale file with an earlier run) or KHONG_CO_SO (today's run, or no SEL2 run at all);
           R4 configured AVG_DEMAND (new SKU x FC included, the default source) -> the AVG_DEMAND value; without it ->
              the LightGBM number of that day (today's run, else the R3' number with its flag), fallback_reason
              KHONG_CO_AVG_DUNG_LIGHTGBM;
           R5 every source is rounded (below 0.2 -> 0, else rounded up; negative -> 0) and the column is never empty:
              without any number it is 0 with fallback_reason KHONG_CO_SO_NAO (in place of STALE / KHONG_CO_SO).
           avg_demand keeps the original value (unrounded, empty when missing); lightgbm_forecast (1.4.5, owner
           decision 06/11/2026) is written rounded like R5 at every horizon (the SEL2 published quantity; empty when
           missing) and raw_value keeps the original number; forecast_used is derived from the numbers exactly as
           before (R1 .. R5 unchanged); lightgbm_forecast,
           raw_value and model_used come from today's run, else from the R3' run (flag LAN_CHAY_TRUOC, every source).
           Row provenance (model_version, data_cutoff_date): a row whose LightGBM number comes from a previous run
           (flag LAN_CHAY_TRUOC: R3', R4 with the R3' number, or shown next to an AVG_DEMAND value) carries the values of
           THAT run; every other row carries those of the reference run (today's run; on a failed day the newest run
           of D-3 .. D-1); without a reference run (no run within D-3 .. D-1, or no SEL2 run at all) both are empty.
           With a reference run of D-1 the target day D+6 is its horizon 8 (beyond H = 7) and older runs cover even
           less: on a failed day D+6 never has a previous-run number -> AVG + STALE (in the scope) or 0 by R2.
  TOM_TAT  counts of the file (scope, fallback reasons, flags, model used, AVG_DEMAND read used). 1.4.5: after the
           model-used counts, the FALLBACK share of the reference run with two denominators (every SKU x FC in its
           scope / only those with an open day - open hours > 0 - in the selection window D-W .. D-1 of the run,
           W = sel2_pipeline.window_days) and the FALLBACK SKU x FC split into "no open day in the W days"
           (khong_mo_ban_W_ngay) and the rest (co_mo_ban_thieu_ngay: fewer than min_days days with cells, or the
           second candidate without a forecast); with the flag OPEN_HOURS_LAG one line open_hours_lag_note: the
           newest open-hours day stored and the build (last-modified) times of the open-hours and demand source
           tables as last read by the app (aux_source_reads.source_modified, demand_sync_runs.source_version of the
           newest D-1 load; no new BigQuery call), with which was built first ("khong ro" when a time is unknown).
  CONFIG   the SKU x FC configured LIGHTGBM at export time.
  GIAI_THICH (1.4.6, C3) after the DU_BAO_* sheets, only when a run used by the file has an explanation sidecar
           (giai_thich.py, written by the pipeline): one row per SKU x FC whose horizon-1 lightgbm_forecast is not empty;
           its TOM_TAT lines (how to read it, counts) come last. Without a sidecar the file is the 1.4.5 file. No
           number of the other sheets depends on it.
  seller_code / product_code (DU_BAO and CONFIG, right after ten_san_pham; owner decision 05/11/2026): sku_code split
           at its FIRST dot (MEDX.ABC-ABC-010 -> MEDX / ABC-ABC-010, A.B.C -> A / B.C). No dot: seller_code empty,
           product_code = sku_code; an empty part before the dot (".X") gives seller_code empty, an empty part after
           it ("X.") product_code empty (split_sku).

20-day layout (owner decision 05/11/2026 evening; 1.4.4 writes it directly, same values cell by cell as the ops script
scripts/ops/excel20.py that rewrote the latest copy of 1.4.3 from 06/11):
  DU_BAO_<fc_code>  one sheet per warehouse, sorted by fc_code (sheet_name: DU_BAO_BD, DU_BAO_HN), then TOM_TAT,
           CONFIG. Every SKU x FC of that warehouse (sorted by sku_code) x horizon 1..20 (target_date D .. D+19), the
           columns of DU_BAO + cach_tinh (last column). h 1..7: the rows above, cach_tinh SEL2. h 8..20: cach_tinh
           UOC_TINH_THEO_TUAN; template = the row of the same SKU x FC with horizon ((h - 1) % 7) + 1 (same weekday);
           target_date D + h - 1, horizon h, lightgbm_forecast = the template's raw_value rounded like R5 (1.4.5;
           empty without one), every other column copied from the template (raw_value: the template's original), forecast_used re-derived with the owner's fixed rule
           (derive_used: outside the scope stays 0; LIGHTGBM with a raw_value -> that value rounded (R5); otherwise the
           template's forecast_used / reason; AVG_DEMAND without Avg -> the raw_value rounded).
  TOM_TAT  the rows of the 7-day file (rows_total and the rows_fallback_reason / rows_flag counts are those of horizon
           1..7), then layout, horizon_8_20 (note), rows:<sheet> / sku_fc:<sheet>, source (the app version),
           generated_at (VN). Every sheet: bold header, frozen, autofilter.
  export_runs.n_rows (and n_rows of the result / summary) = the rows of every DU_BAO_* sheet (SKU x FC x 20).
  A warehouse with more than MAX_SKU_FC SKU x FC (50,000 x 20 rows stays below Excel's 1,048,576) or sheet names that
  clash: no file is written (no version, no record): error log with the flag TOO_MANY_SKU_FC / SHEET_NAME_CLASH and
  SEL2_EXPORT_WRITE_FAILED (detail = the flag).

Stale mode: without a SEL2 run published for D the file is marked is_stale = 1 and its numbers come only from R3'
(runs of D-3 .. D-1, horizon recomputed from D). The latest SEL2 run of an earlier day (whatever its age) stays the
file's run for refresh_run_id / run_forecast_date (export_runs.refresh_run_id), column nhom and the SKU x FC of the
file. When it is not older than D-3 it is the reference run: stale_reason NO_RUN_FOR_DAY, file flag STALE, file-level
model_version / data_cutoff_date and the scope counts are its own. When it is older (no run within D-3 .. D-1): it
supplies neither numbers nor R2 nor provenance, only the information refresh_run_id / run_forecast_date: stale_reason
NO_RUN_3_DAYS, file flags STALE + NO_RUN_3_DAYS, file-level model_version / data_cutoff_date empty,
sku_fc_in_forecast_scope 0, model_used_by_sku_fc empty, every LIGHTGBM row from AVG_DEMAND (STALE). Without any SEL2
run: stale_reason NO_SEL2_RUN (SCOPE_UNRESOLVED:<code> without a data scope), file flag NO_SEL2_RUN, rows from
AVG_DEMAND. Writing is refused while sel2_pipeline.enabled = False.

Temporary file of the first start (write_temp_export, pipeline.bootstrap): du_bao_YYYYMMDD_TAM.xlsx = the V33_L112
candidate of D for every SKU x FC in place of the SEL2 run (same DU_BAO / CONFIG logic, TOM_TAT note "bản tạm"); not a
version, not the latest copy, not in export_runs; replaced by the next bootstrap of the same day. Same 20-day layout.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from itertools import islice
from pathlib import Path, PureWindowsPath

from ... import __version__, db, paths
from ... import settings_service as ss
from ...messages import AppError
from ...timeutil import VN_TZ, now_utc, iso, parse_iso
from . import avg_demand, published
from .source_config import DEFAULT_SOURCE
from .xlsx_stream import Sheet, write_xlsx

log = logging.getLogger("df.sel2.export")
HORIZON = 7
SHEET_MAIN, SHEET_SUMMARY, SHEET_CONFIG = "DU_BAO", "TOM_TAT", "CONFIG"
COLUMNS = ("sku_code", "ten_san_pham", "seller_code", "product_code", "fc_code", "nhom", "forecast_date", "target_date",
           "horizon", "lightgbm_forecast", "avg_demand", "forecast_source", "forecast_used", "fallback_reason",
           "model_used", "raw_value", "model_version", "data_cutoff_date", "is_stale", "flags")
CONFIG_COLUMNS = ("sku_code", "fc_code", "ten_san_pham", "seller_code", "product_code", "ghi_chu", "updated_by",
                  "updated_at")
SUMMARY_COLUMNS = ("muc", "gia_tri")
LIGHTGBM = "LIGHTGBM"
REASON_STALE, REASON_NONE = "STALE", "KHONG_CO_SO"
REASON_OUT_ZERO = "NGOAI_PHAM_VI_GAN_0"   # owner final rule 05/11/2026: LIGHTGBM outside the run scope -> 0
REASON_AVG_MISSING_LGBM = "KHONG_CO_AVG_DUNG_LIGHTGBM"   # AVG_DEMAND without a value -> the LightGBM number
REASON_NO_NUMBER = "KHONG_CO_SO_NAO"      # owner decision 05/11/2026: no number at all -> forecast_used 0
REASON_PREVIOUS = "DUNG_SO_LAN_CHAY_TRUOC"   # owner rule 05/11/2026 (R3'): number of a previous SEL2 run
FLAG_PREVIOUS = "LAN_CHAY_TRUOC"          # row flag LAN_CHAY_TRUOC:YYYY-MM-DD = forecast day of the run used (R3')
PREVIOUS_RUN_DAYS = 3                     # R3' looks at the SEL2 runs of D-3 .. D-1 only (older runs: never)
USED_THRESHOLD = 0.2                      # owner decision 05/11/2026: forecast_used below 0.2 -> 0, else rounded up
                                          # (same rule and 6-decimal rounding as the SEL2 publication, select.THRESHOLD)
STALE_NO_RUN_FOR_DAY, STALE_NO_RUN, STALE_NO_SCOPE = "NO_RUN_FOR_DAY", "NO_SEL2_RUN", "SCOPE_UNRESOLVED"
STALE_NO_RUN_3_DAYS = "NO_RUN_3_DAYS"     # stale_reason + file flag: no SEL2 run within D-3 .. D-1 (all LIGHTGBM on AVG)
FLAG_AVG_NO_READ = "AVG_NO_READ"                    # file level: day D has no completed AVG_DEMAND read
FLAG_LATEST_LOCKED, FLAG_LATEST_FAILED = "LATEST_COPY_LOCKED", "LATEST_COPY_FAILED"
MAX_VERSION_TRIES = 1000
STALE_TEMP_SECONDS = 3600                 # .reserved / .tmp files older than this are left by a crashed process
MAX_LATEST_COPIES = 10                    # latest copy re-done while a newer version was recorded meanwhile
# 1.4.4 20-day layout (owner decision 05/11/2026 evening, values as scripts/ops/excel20.py)
H_ALL = 20                                # horizons per SKU x FC in the file (1..7 SEL2, 8..20 weekly estimate)
SHEET_PREFIX = "DU_BAO_"                  # one sheet per warehouse: DU_BAO_<fc_code>
COLUMNS20 = COLUMNS + ("cach_tinh",)
CACH_SEL2, CACH_WEEK = "SEL2", "UOC_TINH_THEO_TUAN"
LAYOUT_20 = "20 ngay, tach sheet theo kho"
NOTE_8_20 = ("UOC_TINH_THEO_TUAN: lightgbm_forecast = raw_value cung thu trong tuan o horizon 1-7 cua lan chay hom nay, "
             "lam tron (< 0,2 -> 0, con lai lam tron len) (khong phai SEL2)")
MAX_SKU_FC = 50_000                       # per warehouse: 50,000 x 20 rows stays below Excel's 1,048,576
WARN_SKU_FC = 45_000                      # per warehouse: warning in the log from here on (05/11: BD 31,955 / HN 26,636)
FLAG_TOO_MANY_SKU_FC, FLAG_SHEET_CLASH = "TOO_MANY_SKU_FC", "SHEET_NAME_CLASH"
# 1.4.5 (owner decisions 06/11/2026)
RETIRED_SUFFIX = "_bo"                    # earlier version files of the day: du_bao_YYYYMMDD_vK_bo.xlsx
FLAG_RENAME_FAILED = "OLD_VERSION_RENAME_FAILED"   # an earlier version file could not be renamed (open in Excel)
FLAG_OPEN_HOURS_LAG = "OPEN_HOURS_LAG"    # = sel2.data.FLAG_OPEN_HOURS_LAG (run flag carried by the rows)
FALLBACK_PREFIX = "FALLBACK"              # model_used of a series without the two best candidates (select.py)
UNKNOWN = "khong ro"
FLAG_INFO_FAILED = "SUMMARY_INFO_FAILED"     # FALLBACK shares / source build times not read (file still written)
FLAG_GIAI_THICH_SKIPPED = "GIAI_THICH_SKIPPED"   # 1.4.6 = giai_thich.FLAG_SKIPPED (status file, no sidecar)
_I = {c: i for i, c in enumerate(COLUMNS)}
_lock = threading.Lock()                 # one export at a time in this process (version numbers, file names)


def _day(d) -> date:
    return d if isinstance(d, date) and not isinstance(d, datetime) else date.fromisoformat(str(d)[:10])


# ------------------------------------------------------------------ files
def export_root(cfg=None) -> Path:
    """<data folder>\\<export_subdir> (validated: always inside the data folder)."""
    cfg = cfg or ss.get("sel2_pipeline")
    base = paths.data_dir().resolve()
    parts = [p for p in str(cfg.export_subdir).replace("/", "\\").split("\\") if p]
    root = base.joinpath(*parts).resolve()
    if not parts or PureWindowsPath(cfg.export_subdir).is_absolute() or ".." in parts or not root.is_relative_to(base):
        raise AppError("SEL2_EXPORT_PATH_INVALID", 500, detail=str(cfg.export_subdir))
    return root


def file_names(d) -> tuple[str, str]:
    """(day folder name, latest file name) of forecast day d."""
    ymd = _day(d).strftime("%Y%m%d")
    return ymd, f"du_bao_{ymd}.xlsx"


def resolve_file(rel_path: str, cfg=None, retired_fallback: bool = True) -> Path:
    """Absolute path of a stored relative export path; refused when it leaves the export folder. 1.4.5: when the file
    is gone but its _bo file exists (renamed by a newer export that was killed before its record committed), the _bo
    file (same content; read-only fallback, the record is repaired by the next export of the day)."""
    root = export_root(cfg)
    p = paths.data_dir().resolve().joinpath(*[x for x in str(rel_path).replace("\\", "/").split("/") if x]).resolve()
    if not p.is_relative_to(root):
        raise AppError("SEL2_EXPORT_PATH_INVALID", 500, detail=str(rel_path))
    if retired_fallback and not p.exists() and not p.stem.endswith(RETIRED_SUFFIX) and retired_path(p).is_file():
        return retired_path(p)
    return p


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _excl(p: Path) -> int:
    """File descriptor of a NEW file p (fails when p exists: never shared with another process)."""
    return os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))


def _tmp_name(folder: Path, stem: str) -> Path:
    return folder / f".{stem}.{os.getpid()}.{uuid.uuid4().hex[:12]}.tmp"


def _max_version(d: date) -> int:
    with db.read() as c:
        return c.execute("SELECT MAX(version) FROM export_runs WHERE forecast_date=?", (d.isoformat(),)).fetchone()[0] or 0


def _remove_stale_temp(folder: Path) -> int:
    """Remove the .du_bao_*.reserved / .du_bao_*.tmp files of the day folder older than STALE_TEMP_SECONDS (left by a
    crashed process); version files and younger files are never touched. Returns the number removed."""
    limit = time.time() - STALE_TEMP_SECONDS
    removed = 0
    for p in folder.glob(".du_bao_*"):
        if p.suffix not in (".reserved", ".tmp"):
            continue
        try:
            if p.is_file() and p.stat().st_mtime < limit:
                p.unlink()
                removed += 1
        except OSError:                         # in use (a live process holds it) or already gone
            pass
    if removed:
        log.info("sel2 export stale temporary files removed", extra={"ctx": {"folder": folder.name, "removed": removed}})
    return removed


def _reserve_version(folder: Path, ymd: str, d: date) -> tuple[int, Path]:
    """(version, reservation file): the next number without a record, a file or another reservation, reserved by
    creating its reservation file exclusively (shared by every process writing into the folder)."""
    version = _max_version(d) + 1
    for _ in range(MAX_VERSION_TRIES):
        vpath = folder / f"du_bao_{ymd}_v{version}.xlsx"
        res = folder / f".du_bao_{ymd}_v{version}.reserved"
        if not vpath.exists():
            try:
                os.close(_excl(res))
            except (FileExistsError, PermissionError):  # reserved by another process (or being removed)
                pass
            else:
                # checked again once reserved: a process may have written this version meanwhile
                with db.read() as c:
                    recorded = c.execute("SELECT 1 FROM export_runs WHERE forecast_date=? AND version=?",
                                         (d.isoformat(), version)).fetchone()
                if not recorded and not vpath.exists():
                    return version, res
                res.unlink(missing_ok=True)
        version += 1
    raise AppError("SEL2_EXPORT_WRITE_FAILED", 500, detail=f"no free version after {MAX_VERSION_TRIES} tries")


def _latest_copy(folder: Path, vpath: Path, latest: Path, d: date, version: int) -> str | None:
    """Copy version `version` to the latest file (temporary file, then replace). None = copied (or a newer version
    owns the latest file); otherwise the flag: LATEST_COPY_LOCKED (the latest file is open, e.g. in Excel) or
    LATEST_COPY_FAILED. Never raises: the version is already recorded.
    Two processes exporting at once: the replace of an older version can land after the one of a newer version, so
    the highest recorded version is checked again after each replace and copied again when it is newer (the last
    replace is always followed by that check: the latest file never ends on an older version)."""
    if _max_version(d) > version:
        return None
    src_path, src_version = vpath, version
    for _ in range(MAX_LATEST_COPIES):
        ltmp = _tmp_name(folder, latest.name)
        if not src_path.exists() and retired_path(src_path).exists():
            src_path = retired_path(src_path)           # 1.4.5: renamed _bo by a newer export meanwhile (same content)
        try:
            with open(src_path, "rb") as src, os.fdopen(_excl(ltmp), "wb") as dst:
                for chunk in iter(lambda: src.read(1 << 20), b""):
                    dst.write(chunk)
            os.replace(ltmp, latest)
            newest = _max_version(d)
            if newest <= src_version:
                return None
            src_version = newest                        # a newer version was recorded meanwhile: copied again
            src_path = folder / f"{latest.stem}_v{newest}.xlsx"
            continue
        except PermissionError as e:
            flag = FLAG_LATEST_LOCKED
            err = e
        except OSError as e:
            flag = FLAG_LATEST_FAILED
            err = e
        finally:
            try:
                ltmp.unlink(missing_ok=True)
            except OSError:
                pass
        break
    else:
        return None                                     # still newer versions: their own exports copy them
    log.warning("sel2 export latest copy not replaced", extra={"ctx": {
        "forecast_date": d.isoformat(), "version": version, "flag": flag, "error": f"{type(err).__name__}: {err}"[:300]}})
    return flag


def retired_path(p: Path) -> Path:
    """du_bao_YYYYMMDD_vK_bo.xlsx of a version file du_bao_YYYYMMDD_vK.xlsx (1.4.5)."""
    return p.with_name(f"{p.stem}{RETIRED_SUFFIX}{p.suffix}")


def _retire_earlier(d: date, version: int, base: Path, cfg) -> tuple[list[tuple], list[int]]:
    """1.4.5: rename the files of the recorded versions of day d below `version` to their _bo name. Returns (moves
    [(export_run id, old path, new path, new relative path)] whose record must take the new path, versions whose
    file could not be renamed). A record already on a _bo name is left; a record whose file is gone while its _bo
    file exists (renamed, record not updated) is repaired; a record whose file and _bo file are both gone is left
    (data-check export_files_exist reports it). Never raises."""
    moves, failed = [], []
    with db.read() as c:
        recs = db.rows(c, "SELECT id, version, path FROM export_runs WHERE forecast_date=? AND version<? "
                          "ORDER BY version", (d.isoformat(), version))
    for r in recs:
        try:
            p = resolve_file(r["path"], cfg, retired_fallback=False)   # the recorded name (repair below)
        except AppError:
            failed.append(r["version"])
            continue
        if p.stem.endswith(RETIRED_SUFFIX):
            continue
        bo = retired_path(p)
        try:
            if p.is_file():
                if bo.exists():                         # never replaced (os.rename replaces on POSIX)
                    raise FileExistsError(f"{bo.name} exists")
                os.rename(p, bo)
            elif not bo.is_file():
                continue
        except OSError as e:                            # PermissionError: open in Excel - the old name stays
            log.warning("sel2 export: earlier version not renamed", extra={"ctx": {
                "forecast_date": d.isoformat(), "version": r["version"], "error": f"{type(e).__name__}: {e}"[:300]}})
            failed.append(r["version"])
            continue
        moves.append((r["id"], p, bo, bo.relative_to(base).as_posix()))
    return moves, failed


def _undo_retire(moves: list[tuple]) -> None:
    """Rename the files of _retire_earlier back (the new version was not recorded). Never raises."""
    for _rid, p, bo, _rel in reversed(moves):
        try:
            if bo.is_file() and not p.exists():
                os.rename(bo, p)
        except OSError as e:
            log.warning("sel2 export: earlier version not renamed back", extra={"ctx": {
                "file": bo.name, "error": f"{type(e).__name__}: {e}"[:300]}})


# ------------------------------------------------------------------ inputs
def _scope_key(conn) -> tuple[str | None, str | None]:
    from ...data.demand import resolve_scope
    try:
        return resolve_scope(conn)["scope_key"], None
    except AppError as e:
        return None, e.code


def _run_for(conn, scope_key: str | None, d: date, scope_error: str | None) -> tuple[dict | None, str | None]:
    """(SEL2 run used, stale reason): the run published for d, else the latest SEL2 run of an earlier day (file-level
    metadata only in that case: its numbers come through _previous_values, D-3 .. D-1)."""
    if scope_key is None:
        return None, f"{STALE_NO_SCOPE}:{scope_error}"
    run = db.one(conn, "SELECT * FROM forecast_refresh_runs WHERE scope_key=? AND forecast_date=? AND "
                       "config_version LIKE 'SEL2:%' ORDER BY created_at DESC, rowid DESC LIMIT 1", (scope_key, d.isoformat()))
    if run:
        return run, None
    run = db.one(conn, "SELECT * FROM forecast_refresh_runs WHERE scope_key=? AND forecast_date<? AND "
                       "config_version LIKE 'SEL2:%' ORDER BY forecast_date DESC, created_at DESC, rowid DESC LIMIT 1",
                 (scope_key, d.isoformat()))
    return run, (STALE_NO_RUN_FOR_DAY if run else STALE_NO_RUN)


def _run_values(conn, run: dict | None, days: list[str]) -> tuple[dict, dict]:
    """keys {(sku, fc): (group, model_used)} of the whole run, values {(sku, fc): [7 x (qty, raw, method, flags) | None]}
    of the target days D .. D+6. Strings of methods / flags are shared (about 410k values)."""
    keys: dict[tuple, list] = {}
    vals: dict[tuple, list] = {}
    if run is None:
        return keys, vals
    idx = {t: i for i, t in enumerate(days)}
    shared: dict = {}
    for sku, fc, td, h, qty, raw, method, grp, fl in conn.execute(
            "SELECT sku_code, fc_code, target_date, horizon, final_qty, lgb_raw, method, group_code, flags "
            "FROM forecast_refresh_values WHERE run_id=?", (run["id"],)):
        k = (sku, fc)
        method, fl = shared.setdefault(method, method), shared.setdefault(fl, fl)
        info = keys.get(k)
        if info is None:
            keys[k] = info = [grp, method, h]
        elif h < info[2]:                       # model used of the series = the method of its first horizon
            info[1], info[2] = method, h
        if grp and not info[0]:
            info[0] = grp
        i = idx.get(str(td)[:10])
        if i is not None:
            vals.setdefault(k, [None] * HORIZON)[i] = (int(qty), raw, method, fl)
    return {k: (v[0], v[1]) for k, v in keys.items()}, vals


def _previous_runs(conn, scope_key: str | None, d: date) -> list[dict]:
    """Latest SEL2 run of each forecast day D-3 .. D-1 (newest day first): the runs R3' may take numbers from.
    forecast_refresh_runs holds published (successful) runs only."""
    if scope_key is None:
        return []
    out, seen = [], set()
    for r in db.rows(conn, "SELECT id, forecast_date, model_version, data_as_of FROM forecast_refresh_runs "
                           "WHERE scope_key=? AND forecast_date>=? "
                           "AND forecast_date<? AND config_version LIKE 'SEL2:%' "
                           "ORDER BY forecast_date DESC, created_at DESC, rowid DESC",
                     (scope_key, (d - timedelta(days=PREVIOUS_RUN_DAYS)).isoformat(), d.isoformat())):
        day = str(r["forecast_date"])[:10]
        if day not in seen:
            seen.add(day)
            out.append({"id": r["id"], "forecast_date": day, "model_version": r["model_version"],
                        "data_cutoff": _day(r["data_as_of"]) if r["data_as_of"] else None})
    return out


def _previous_values(conn, prev_runs: list[dict], days: list[str], need: set | None) -> dict:
    """{(sku, fc): [7 x (qty, raw, method, flags, run day, model_version, data cutoff) | None]} of the target days
    D .. D+6: per day the number of the newest run of prev_runs (newest first) that has one (R3'), with the
    model_version / data cutoff of that run (row provenance). need = the SKU x FC to look up (None = every one)."""
    out: dict[tuple, list] = {}
    if not prev_runs or (need is not None and not need):
        return out
    idx = {t: i for i, t in enumerate(days)}
    d0 = date.fromisoformat(days[0])
    shared: dict = {}
    for run in prev_runs:
        lo = (d0 - date.fromisoformat(run["forecast_date"])).days + 1     # horizon of target day D in that run
        for sku, fc, td, qty, raw, method, fl in conn.execute(
                "SELECT sku_code, fc_code, target_date, final_qty, lgb_raw, method, flags FROM forecast_refresh_values "
                "WHERE run_id=? AND horizon BETWEEN ? AND ?", (run["id"], lo, lo + HORIZON - 1)):
            k = (sku, fc)
            if need is not None and k not in need:
                continue
            i = idx.get(str(td)[:10])
            if i is None:
                continue
            series = out.get(k)
            if series is None:
                out[k] = series = [None] * HORIZON
            if series[i] is None:                   # a newer run already gave this day: kept
                series[i] = (int(qty), raw, shared.setdefault(method, method), shared.setdefault(fl, fl),
                             run["forecast_date"], run["model_version"], run["data_cutoff"])
    return out


def _names(conn, d: str, avg_table: str | None) -> dict[str, str]:
    from ...bq import product_names
    out = {}
    if avg_table:
        out = {r[0]: r[1] for r in conn.execute("SELECT sku_code, MAX(product_name) FROM avg_demand_daily WHERE "
                                                "business_date=? AND source_table=? AND product_name IS NOT NULL "
                                                "GROUP BY sku_code", (d, avg_table))}
    out = {k: v for k, v in out.items() if v and v.strip()}                    # 1.4.10: an empty text is no name
    for k, v in (product_names.names(conn) or {}).items():                      # the stored mapping only FILLS gaps
        if v and v.strip() and k not in out:
            out[k] = v                                  # names are written exactly as read (as in 1.4.9)
    return out


def _config_rows(conn) -> list[dict]:
    return db.rows(conn, "SELECT sku_code, fc_code, ghi_chu, updated_by, updated_at FROM forecast_source_config "
                         "WHERE forecast_source=? ORDER BY sku_code, fc_code", (LIGHTGBM,))


def _ts(ts):
    """datetime of a stored UTC ISO time; None when missing / unreadable (never raises)."""
    try:
        return parse_iso(str(ts)) if ts else None
    except (TypeError, ValueError, OverflowError):
        return None


def _vn(ts: str | None) -> str | None:
    """'YYYY-MM-DD HH:MM:SS' (Vietnam time) of a stored UTC ISO time; None when missing / unreadable."""
    dt = _ts(ts)
    try:
        return dt.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S") if dt else None
    except (ValueError, OverflowError, OSError):
        return None


def _source_build(conn, scope_key: str | None, d: date) -> dict:
    """1.4.5 (C5): what the app last recorded about the two BigQuery source tables of day d - read from the database
    only (no BigQuery call): newest open-hours day stored up to D-1 (open_hours_daily of the configured source), the
    last-modified (build) time of the open-hours table seen by its newest completed read (aux_source_reads) and of the
    demand table seen by the newest D-1 load (demand_sync_runs.source_version), which was built first, and the line
    of TOM_TAT (text). A time not recorded -> None, and "khong ro" in the text."""
    from ...bq import aux_sources
    tbl, seller = aux_sources.open_hours_source()
    last_day = conn.execute("SELECT MAX(open_date) FROM open_hours_daily WHERE source_table=? AND seller_code=? AND "
                            "open_date <= ?", (tbl, seller, (d - timedelta(days=1)).isoformat())).fetchone()[0]
    rd = aux_sources.last_completed_read(conn, aux_sources.KIND_OPEN_HOURS, tbl, seller)
    oh_built = rd["source_modified"] if rd else None
    dm = db.one(conn, "SELECT source_version FROM demand_sync_runs WHERE scope_key=? AND kind='D1_SYNC' AND "
                      "source_version IS NOT NULL ORDER BY started_at DESC, rowid DESC LIMIT 1",
                (scope_key,)) if scope_key else None
    dm_built = dm["source_version"] if dm else None
    dm_table = ss.get("bigquery").source_table or None
    a, b = _ts(oh_built), _ts(dm_built)
    first = (UNKNOWN if a is None or b is None else "cung luc" if a == b else tbl if a < b else (dm_table or "demand"))
    out = {"open_hours_table": tbl, "open_hours_last_day": str(last_day)[:10] if last_day else None,
           "open_hours_built_at": oh_built, "demand_table": dm_table, "demand_built_at": dm_built, "built_first": first}
    out["text"] = (f"{FLAG_OPEN_HOURS_LAG}: gio mo ban moi nhat {out['open_hours_last_day'] or UNKNOWN}; "
                   f"{tbl} build {_vn(oh_built) or UNKNOWN}, {dm_table or 'bang demand'} build {_vn(dm_built) or UNKNOWN} "
                   f"(gio VN); build truoc: {first}")
    return out


def _fallback_info(conn, ref: dict | None, run_keys: dict, cfg) -> dict:
    """1.4.5 (C7): FALLBACK SKU x FC of the reference run (model_used FALLBACK:<model>, select.py) with two denominators:
    every SKU x FC in its scope and only those with an open day (open hours > 0, open_hours_daily of the configured
    source) in the selection window D-W .. D-1 of the run (W = sel2_pipeline.window_days); the FALLBACK split into
    no open day in the window / the rest. Without a reference run: counts 0, shares None."""
    from ...bq import aux_sources
    W = int(cfg.window_days)
    out = {"window_days": W, "window": None, "sku_fc_in_scope": 0, "sku_fc_open_in_window": 0, "sku_fc_fallback": 0,
           "fallback_no_open_day": 0, "fallback_with_open_day": 0, "pct_all": None, "pct_open": None}
    if ref is None or not run_keys:
        return out
    rd = _day(ref["forecast_date"])
    lo, hi = (rd - timedelta(days=W)).isoformat(), (rd - timedelta(days=1)).isoformat()
    tbl, seller = aux_sources.open_hours_source()
    open_keys = {(r[0], r[1]) for r in conn.execute(
        "SELECT DISTINCT sku_code, fc_code FROM open_hours_daily WHERE source_table=? AND seller_code=? AND "
        "open_date BETWEEN ? AND ? AND total_open_hours > 0", (tbl, seller, lo, hi))}
    fb = [k for k, (_g, m) in run_keys.items() if str(m or "").startswith(FALLBACK_PREFIX)]
    n, n_open = len(run_keys), sum(1 for k in run_keys if k in open_keys)
    fb_closed = sum(1 for k in fb if k not in open_keys)
    out.update(window=f"{lo}..{hi}", sku_fc_in_scope=n, sku_fc_open_in_window=n_open, sku_fc_fallback=len(fb),
               fallback_no_open_day=fb_closed, fallback_with_open_day=len(fb) - fb_closed,
               pct_all=round(100.0 * len(fb) / n, 2),
               pct_open=round(100.0 * (len(fb) - fb_closed) / n_open, 2) if n_open else None)
    return out


AUTO_BY, AUTO_REASON, AUTO_CHANNEL = "system", "AUTO_LIGHTGBM_KHI_CO_SO", "API"


def _set_keys(conn) -> set:
    """SKU x FC ever set (a configuration row or any history row): never switched automatically."""
    return ({(r[0], r[1]) for r in conn.execute("SELECT sku_code, fc_code FROM forecast_source_config")}
            | {(r[0], r[1]) for r in conn.execute("SELECT DISTINCT sku_code, fc_code FROM forecast_source_config_history")})


def auto_switch_new_codes(d: date, scope_key: str | None) -> dict:
    """1.4.5 C8 (owner decision 07/11/2026 01:10): a SKU x FC whose forecast source is AVG_DEMAND BY DEFAULT - no row in
    forecast_source_config and no row in its append-only history, i.e. never set by a user - is switched to LIGHTGBM
    when today's SEL2 run of D (forecast_refresh_runs, scope_key) has a number for it. Written like a user change
    (source_config._write: config row + history row, old_source NULL) with changed_by "system", ghi_chu / reason
    AUTO_LIGHTGBM_KHI_CO_SO, channel API (the history CHECK allows UI / UPLOAD / API only) and one batch_id per call,
    plus one audit record. A code set by a user (AVG_DEMAND or LIGHTGBM, any history row) is never touched. Called by
    the pipeline right after the publication of the day's run, before its export hook writes the Excel (pipeline
    _export_hook), so the day's Excel already uses LIGHTGBM; never by write_daily_export itself (a manual / AVG
    re-export does not change the configuration). scope_key None = the active scope. Idempotent."""
    from . import source_config
    if scope_key is None:
        with db.read() as c:
            scope_key = _scope_key(c)[0]
    if scope_key is None:
        return {"switched": 0, "batch_id": None}
    with db.read() as c:
        run = db.one(c, "SELECT id FROM forecast_refresh_runs WHERE scope_key=? AND forecast_date=? AND "
                        "config_version LIKE 'SEL2:%' ORDER BY created_at DESC, rowid DESC LIMIT 1",
                     (scope_key, d.isoformat()))
    if run is None:
        return {"switched": 0, "batch_id": None}
    batch_id, by, at = db.new_id("SCA"), AUTO_BY, iso(now_utc())
    # the keys of the run and the configured / history keys read once each (no per-row subquery: the history has no
    # index on the key); the write transaction re-reads only the two small key sets (lock kept short)
    with db.read() as c:
        run_keys = {(r[0], r[1]) for r in c.execute("SELECT DISTINCT sku_code, fc_code FROM forecast_refresh_values "
                                                    "WHERE run_id=? AND final_qty IS NOT NULL", (run["id"],))}
        cand = run_keys - _set_keys(c)
    if not cand:
        return {"switched": 0, "batch_id": None}
    with db.tx() as c:
        keys = sorted(cand - _set_keys(c))
        for sku, fc in keys:
            source_config._write(c, sku, fc, source_config.get_effective(c, sku, fc), LIGHTGBM, AUTO_REASON, by, at,
                                 AUTO_CHANNEL, batch_id)
        if keys:
            db.audit(c, "FORECAST_SOURCE_AUTO_LIGHTGBM", "forecast_source_config", batch_id,
                     {"forecast_date": d.isoformat(), "run_id": run["id"], "switched": len(keys),
                      "reason": AUTO_REASON})
    if keys:
        log.info("sel2 forecast source: default codes switched to LIGHTGBM", extra={"ctx": {
            "forecast_date": d.isoformat(), "run_id": run["id"], "switched": len(keys), "batch_id": batch_id}})
    return {"switched": len(keys), "batch_id": batch_id if keys else None}


def split_sku(sku: str | None) -> tuple[str | None, str | None]:
    """(seller_code, product_code) of a sku_code, split at the FIRST dot (owner decision 05/11/2026). No dot ->
    (None, sku); an empty part on either side of the dot -> None for that part; None / '' -> (None, None)."""
    if not sku:
        return None, None
    seller, dot, product = sku.partition(".")
    if not dot:
        return None, sku
    return seller or None, product or None


def _config_book_rows(cfg_rows: list[dict], names: dict) -> list[list]:
    """Rows of CONFIG in CONFIG_COLUMNS order."""
    return [[r["sku_code"], r["fc_code"], names.get(r["sku_code"]), *split_sku(r["sku_code"]), r["ghi_chu"],
             r["updated_by"], r["updated_at"]] for r in cfg_rows]


# ------------------------------------------------------------------ rows
def _rows(d: date, keys: list, run: dict | None, run_keys: dict, vals: dict, avg: dict, conf: dict, names: dict,
          stale: bool, stats: dict, prev: dict | None = None, scoped: bool | None = None):
    """Rows of DU_BAO in COLUMNS order; counts into stats. vals = the numbers of today's run (the caller passes none in
    stale mode), prev = the previous-run numbers of _previous_values (R3', SKU x FC of the reference run only),
    scoped = run is the reference run (default: today's run, run is not None and not stale). model_version /
    data_cutoff_date: of the previous run for a previous-run number, else of the reference run (empty without one)."""
    days = [d + timedelta(days=i) for i in range(HORIZON)]
    if scoped is None:
        scoped = run is not None and not stale              # R2 applies only with a reference run
    ref = run if scoped else None                           # an older stale run gives no provenance
    mv = ref["model_version"] if ref else None
    cutoff = _day(ref["data_as_of"]) if ref and ref.get("data_as_of") else None
    st = 1 if stale else 0
    by_reason, flag_rows = stats["rows_by_fallback_reason"], stats["flag_rows"]
    prev_flags: dict[str, str] = {}
    for k in keys:
        sku, fc = k
        src = conf.get(k, DEFAULT_SOURCE)
        a = avg.get(k) or {"value": None, "reason": avg_demand.REASON_NO_ROW}
        av, a_reason = a["value"], a["reason"]
        info = run_keys.get(k)
        grp = info[0] if info else None
        series = vals.get(k)
        # R3': in the scope of the reference run only (outside it R2 applies, never a previous number)
        pseries = prev.get(k) if prev and scoped and info is not None else None
        name = names.get(sku)
        seller, product = split_sku(sku)                    # once per SKU x FC (7 rows share the strings)
        for i, td in enumerate(days):
            v = series[i] if series else None
            from_prev = v is None and pseries is not None and pseries[i] is not None
            if from_prev:
                v = pseries[i]
            qty = v[0] if v else None
            reason = None
            # owner's fixed rule 05/11/2026 (R1, R2, R3', R3'', R4, R5 in the module docstring)
            if src == LIGHTGBM and qty is not None:
                used = qty                                          # R1 / R3', a 0 included
                if from_prev:
                    reason = REASON_PREVIOUS
            elif src == LIGHTGBM and scoped and info is None:
                used, reason = 0, REASON_OUT_ZERO                   # R2: outside the scope of the reference run
            elif src == LIGHTGBM:
                used, reason = av, (REASON_STALE if run is not None and stale else REASON_NONE)   # R3''
            elif (av is None or not math.isfinite(av)) and qty is not None:
                used, reason = qty, REASON_AVG_MISSING_LGBM         # R4: AVG_DEMAND without a value (R3' number too)
            else:
                used = av                                           # R4
            # owner decision 05/11/2026: forecast_used never empty, below 0.2 -> 0, else rounded up (6 decimals first)
            if used is None or not math.isfinite(used):
                used, reason = 0, REASON_NO_NUMBER
            else:
                x = round(float(used), 6)
                used = 0 if x < USED_THRESHOLD else math.ceil(x)
            fl = [x for x in (v[3] or "").split(",") if x] if v else []
            if from_prev:
                fl.append(prev_flags.get(v[4]) or prev_flags.setdefault(v[4], f"{FLAG_PREVIOUS}:{v[4]}"))
            if a_reason:
                fl.append(f"AVG_{a_reason}")
            flags = ",".join(fl) or None
            by_reason[reason or ""] = by_reason.get(reason or "", 0) + 1
            for x in fl:
                flag_rows[x] = flag_rows.get(x, 0) + 1
            # 1.4.5: lightgbm_forecast written rounded (R5); forecast_used above is derived from qty as before
            yield [sku, name, seller, product, fc, grp, d, td, i + 1, round_lgbm(qty), av, src, used, reason,
                   v[2] if v else None,
                   v[1] if v else None, v[5] if from_prev else mv, v[6] if from_prev else cutoff, st, flags]


# ------------------------------------------------------------------ 20-day layout (1.4.4)
def _num(v) -> float | None:
    """Finite float of a value, None when missing / not a number."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _roundup(x) -> int:
    x = round(float(x), 6)
    return 0 if x < USED_THRESHOLD else math.ceil(x)


def round_lgbm(x) -> int | None:
    """1.4.5 (owner decision 06/11/2026): the lightgbm_forecast column at every horizon = the number rounded like
    forecast_used (6 decimals, below 0.2 -> 0, else rounded up; = the SEL2 published quantity); None (or a value that
    is not a finite number) stays empty. raw_value keeps the original."""
    f = _num(x)
    return None if f is None else _roundup(f)


def derive_used(src, t_used, t_reason, raw) -> tuple[int, str | None]:
    """(forecast_used, fallback_reason) of a horizon 8..20 row from its template (forecast_source, forecast_used,
    fallback_reason) and the template's raw_value (_num); always an int >= 0 (owner's fixed rule, R5)."""
    if t_reason == REASON_OUT_ZERO:
        return 0, REASON_OUT_ZERO
    if src == LIGHTGBM:
        if raw is not None:
            return _roundup(raw), (REASON_PREVIOUS if t_reason == REASON_PREVIOUS else None)
        used, reason = t_used, t_reason                     # Avg / 0 of the template
    elif t_reason == REASON_AVG_MISSING_LGBM and raw is not None:
        return _roundup(raw), REASON_AVG_MISSING_LGBM
    else:
        used, reason = t_used, t_reason                     # AVG_DEMAND: the template's value
    u = _num(used)
    if reason == REASON_NO_NUMBER or u is None:
        return 0, REASON_NO_NUMBER
    return _roundup(u), reason


def sheet_name(fc) -> str:
    """DU_BAO_<fc_code> (characters Excel refuses in a sheet name -> _, at most 31 characters)."""
    s = re.sub(r"[\[\]:*?/\\']", "_", str(fc if fc not in (None, "") else "KHONG_FC"))
    return (SHEET_PREFIX + s)[:31]


def _sheet_plan(keys: list) -> list[tuple[str, list]]:
    """[(sheet name, SKU x FC of that warehouse in the order of keys)], sorted by fc_code. ValueError (flag first)
    when a warehouse has more than MAX_SKU_FC SKU x FC or two sheet names clash."""
    by_fc: dict = {}
    for k in keys:
        by_fc.setdefault(k[1], []).append(k)
    fcs = sorted(by_fc, key=lambda x: (x is None, str(x)))
    big = {str(fc): len(by_fc[fc]) for fc in fcs if len(by_fc[fc]) > MAX_SKU_FC}
    if big:
        raise ValueError(f"{FLAG_TOO_MANY_SKU_FC}: SKU x FC per warehouse > {MAX_SKU_FC}: {big}")
    near = {str(fc): len(by_fc[fc]) for fc in fcs if len(by_fc[fc]) > WARN_SKU_FC}
    if near:                                          # early warning before the hard limit refuses the daily file
        log.warning("sel2 export: warehouse near the 20-day sheet limit",
                    extra={"ctx": {"limit": MAX_SKU_FC, "warn_from": WARN_SKU_FC, "sku_fc": near}})
    names = [sheet_name(fc) for fc in fcs]
    folded = [n.casefold() for n in names]            # Excel sheet names are unique regardless of case
    if len(set(folded)) != len(folded) or SHEET_SUMMARY.casefold() in folded or SHEET_CONFIG.casefold() in folded:
        raise ValueError(f"{FLAG_SHEET_CLASH}: {names}")
    return [(nm, by_fc[fc]) for nm, fc in zip(names, fcs)]


def _plan_or_fail(keys: list, d: date) -> list[tuple[str, list]]:
    """_sheet_plan; a refused plan is logged (error) and raised as SEL2_EXPORT_WRITE_FAILED before any file is written."""
    try:
        return _sheet_plan(keys)
    except ValueError as e:
        flag = str(e).split(":", 1)[0]
        log.error("sel2 export refused: 20-day layout", extra={"ctx": {"forecast_date": d.isoformat(), "flag": flag,
                                                                       "error": str(e)[:300]}})
        raise AppError("SEL2_EXPORT_WRITE_FAILED", 500, detail=str(e)[:300]) from None


def _rows20(rows7, d: date):
    """20 rows per SKU x FC (COLUMNS20) from the rows of _rows (7 consecutive rows per SKU x FC, horizon 1..7):
    horizon 1..7 unchanged + SEL2; horizon 8..20 from the template of the same weekday + UOC_TINH_THEO_TUAN."""
    i_td, i_h, i_lg, i_raw = _I["target_date"], _I["horizon"], _I["lightgbm_forecast"], _I["raw_value"]
    i_src, i_used, i_reason = _I["forecast_source"], _I["forecast_used"], _I["fallback_reason"]
    targets = [d + timedelta(days=h - 1) for h in range(H_ALL + 1)]
    it = iter(rows7)
    for first in it:
        g = [first, *islice(it, HORIZON - 1)]
        if [r[i_h] for r in g] != list(range(1, HORIZON + 1)):
            raise RuntimeError("DU_BAO rows: 7 consecutive horizons expected per SKU x FC")
        for r in g:
            yield [*r, CACH_SEL2]
        for h in range(HORIZON + 1, H_ALL + 1):
            t = g[(h - 1) % HORIZON]
            r = list(t)
            raw = _num(t[i_raw])
            r[i_td], r[i_h], r[i_lg] = targets[h], h, round_lgbm(raw)   # 1.4.5: rounded; derive_used takes the raw
            r[i_used], r[i_reason] = derive_used(t[i_src], t[i_used], t[i_reason], raw)
            r.append(CACH_WEEK)
            yield r


def _layout_summary(plan: list) -> dict:
    return {"sheets": {nm: len(ks) * H_ALL for nm, ks in plan}, "sku_fc": {nm: len(ks) for nm, ks in plan}}


def _write_book(target: Path, d: date, plan: list, rows_for, summary_rows, config_rows: list, extra=()) -> None:
    """Sheets DU_BAO_<fc> (plan order), the extra sheets (1.4.6: GIAI_THICH), TOM_TAT, CONFIG; bold header, frozen,
    autofilter on every sheet. rows_for(keys) = the _rows generator of those SKU x FC. Streamed (xlsx_stream: openpyxl's
    writer took about 380 s for 420k rows); the extra sheets and summary_rows are read after every DU_BAO_* sheet is
    written."""
    sheets = [Sheet(nm, COLUMNS20, _rows20(rows_for(ks), d), len(ks) * H_ALL, freeze_header=True, autofilter=True)
              for nm, ks in plan]
    write_xlsx(target, sheets + list(extra) + [
                                 Sheet(SHEET_SUMMARY, SUMMARY_COLUMNS, summary_rows, freeze_header=True, autofilter=True),
                                 Sheet(SHEET_CONFIG, CONFIG_COLUMNS, config_rows, len(config_rows), freeze_header=True,
                                       autofilter=True)])


def _summary_rows(s: dict) -> list:
    out = [["forecast_date", s["forecast_date"]], ["data_cutoff_date", s["data_cutoff_date"]],
           ["export_version", s["version"]], ["export_time_utc", s["created_at"]],
           ["export_time_vn", s["created_at_vn"]], ["trigger", s["trigger"]],
           ["is_stale", 1 if s["is_stale"] else 0], ["stale_reason", s["stale_reason"]],
           ["file_flags", ",".join(s["file_flags"]) or None],
           ["refresh_run_id", s["refresh_run_id"]], ["run_forecast_date", s["run_forecast_date"]]]
    if "previous_runs" in s:                                # daily file: SEL2 runs of D-3 .. D-1 R3' may use
        out.append(["previous_runs", ",".join(s["previous_runs"]) or None])
    out += [["model_version", s["model_version"]],
           ["sku_fc_total", s["sku_fc"]["total"]], ["sku_fc_in_forecast_scope", s["sku_fc"]["in_forecast_scope"]],
           ["sku_fc_configured_lightgbm", s["sku_fc"]["configured_lightgbm"]],
           ["sku_fc_configured_lightgbm_not_in_file", s["sku_fc"]["configured_lightgbm_not_in_file"]],
           ["rows_total", s["n_rows_h1_7"]]]                # horizon 1..7 (the counts below are of these rows)
    out += [[f"rows_fallback_reason:{k or '(none)'}", v] for k, v in sorted(s["rows_by_fallback_reason"].items())]
    out += [[f"rows_flag:{k}", v] for k, v in sorted(s["flag_rows"].items())]
    out += [[f"sku_fc_avg_reason:{k}", v] for k, v in sorted(s["avg"]["no_value_by_reason"].items())]
    out += [[f"sku_fc_model_used:{k}", v] for k, v in sorted(s["model_used_by_sku_fc"].items())]
    fb = s.get("fallback")                                  # 1.4.5 (C7): daily file only
    if fb is not None:
        w = fb["window_days"]
        out += [["fallback_window", fb["window"]], ["sku_fc_fallback", fb["sku_fc_fallback"]],
                ["fallback_pct_all_sku_fc", fb["pct_all"]],
                ["sku_fc_open_in_window", fb["sku_fc_open_in_window"]],
                ["fallback_pct_open_sku_fc", fb["pct_open"]],
                [f"sku_fc_fallback:khong_mo_ban_{w}_ngay", fb["fallback_no_open_day"]],
                ["sku_fc_fallback:co_mo_ban_thieu_ngay", fb["fallback_with_open_day"]]]
    sb = s.get("source_build")                              # 1.4.5 (C5): one line with the flag OPEN_HOURS_LAG
    if sb is not None and FLAG_OPEN_HOURS_LAG in s["flag_rows"]:
        out.append(["open_hours_lag_note", sb["text"]])
    a = s["avg"]
    out += [["avg_source_kind", a["source_kind"]], ["avg_source_table", a["source_table"]],
            ["avg_source_modified", a["source_modified"]], ["avg_read_completed_at", a["completed_at"]],
            ["avg_seller_rule", a["rule"]]]
    lay = s["layout"]                                       # 1.4.4 20-day layout (rows as scripts/ops/excel20.py)
    out += [["layout", LAYOUT_20], ["horizon_8_20", NOTE_8_20]]
    out += [[f"rows:{nm}", n] for nm, n in lay["sheets"].items()]
    out += [[f"sku_fc:{nm}", n] for nm, n in lay["sku_fc"].items()]
    out += [["source", f"Demand Forecast {__version__} (ghi truc tiep)"], ["generated_at", s["created_at_vn"] + " (VN)"]]
    gt = s.get("giai_thich")                                # 1.4.6 (C3): only when the sheet GIAI_THICH is written
    if gt and gt.get("sheet"):
        try:
            from . import giai_thich
            out += giai_thich.summary_rows(gt, giai_thich.labels())
        except Exception as e:  # noqa: BLE001 - explanation only, never fails the file
            out.append(["giai_thich", f"loi doc thong tin: {type(e).__name__}"])
    return out


class _GiaiThich:
    """1.4.6 (C3) sheet GIAI_THICH (giai_thich.py): the horizon-1 rows of the DU_BAO_* sheets are captured while they
    are written (capture), the sheet rows are built when it is written (after every DU_BAO_* sheet)."""
    def __init__(self, d: date, plan: list, run, is_stale: bool, prev_runs: list, scope_key, names: dict, info: dict):
        from . import giai_thich
        self.gt, self.d, self.names, self.info = giai_thich, d, names, info
        self.keys = [k for _, ks in plan for k in ks]
        self.today = (str(run["forecast_date"])[:10], run["id"]) if run is not None and not is_stale else (None, None)
        self.prev = {r["forecast_date"]: r["id"] for r in prev_runs}
        self.scope_key = scope_key
        self.day_of = {rid: day for day, rid in ([self.today] if self.today[1] else [])
                       + [(r["forecast_date"], r["id"]) for r in prev_runs]}
        # sidecars are loaded on first use (doc); only their existence is checked here
        have = [rid for rid, day in self.day_of.items() if giai_thich.exists(scope_key, day, rid)]
        self.docs: dict = {}
        self.enabled = bool(have)
        info.update(sheet=self.enabled, runs=[f"{self.day_of[rid]}:{rid}" for rid in have])
        if self.today[1] and self.today[1] not in have:     # today's run without a sidecar: why (status file)
            st = giai_thich.read_status(scope_key, self.today[0], self.today[1])
            if st and st.get("status") != giai_thich.STATUS_OK:
                info.update(skipped=True, status=st.get("status"), reason=st.get("reason"))
        self.h1: dict = {}

    def doc(self, rid):
        if rid not in self.docs:
            try:
                self.docs[rid] = self.gt.load(self.scope_key, self.day_of.get(rid), rid) if rid in self.day_of else None
            except Exception as e:  # noqa: BLE001 - explanation only, never fails the file
                log.warning("sel2 export: giai_thich sidecar not read", extra={"ctx": {"run_id": rid, "error": str(e)[:300]}})
                self.docs[rid] = None
            d = self.docs[rid]
            if d and "window_days" not in self.info:
                self.info.update(window_days=d.get("window_days"), min_days=d.get("min_days"))
        return self.docs[rid]

    def capture(self, rows):
        h1 = self.h1
        ih, isku, ifc = _I["horizon"], _I["sku_code"], _I["fc_code"]
        sel = [_I[c] for c in ("lightgbm_forecast", "forecast_used", "fallback_reason", "forecast_source", "raw_value",
                               "model_used", "flags", "avg_demand")]
        for r in rows:
            if r[ih] == 1:
                h1[(r[isku], r[ifc])] = tuple(r[i] for i in sel)
            yield r

    def run_of(self, flags) -> tuple:
        for x in (flags or "").split(","):
            if x.startswith(FLAG_PREVIOUS + ":"):
                day = x.split(":", 1)[1]
                return day, self.prev.get(day)
        return self.today

    def sheet(self) -> Sheet:
        gt = self.gt
        outer = self

        class _Rows:
            def __iter__(self):
                return gt.sheet_rows(outer.d, outer.keys, outer.h1, outer.doc, outer.run_of, outer.names, gt.labels(),
                                     outer.info)
        return Sheet(gt.SHEET, gt.columns(gt.select.CANDIDATES), _Rows(), freeze_header=True, autofilter=True)


# ------------------------------------------------------------------ export
def write_daily_export(forecast_date, trigger: str = "SCHEDULE", job_id=None, scope_key: str | None = None) -> dict:
    """Write a new version of the daily Excel of forecast day D (Vietnam day). Returns path (relative to the data
    folder), version, n_rows, is_stale, summary, retired (1.4.5: new relative paths of the earlier versions renamed
    to _bo). Earlier version files are never changed or deleted (only renamed, module text)."""
    d = _day(forecast_date)
    cfg = ss.get("sel2_pipeline")
    if not cfg.enabled:
        raise AppError("SEL2_PIPELINE_DISABLED", 409)
    root = export_root(cfg)
    days = [(d + timedelta(days=i)).isoformat() for i in range(HORIZON)]
    with db.read() as c:
        scope_error = None
        if scope_key is None:
            scope_key, scope_error = _scope_key(c)
        run, stale_reason = _run_for(c, scope_key, d, scope_error)
        is_stale = stale_reason is not None
        # numbers of today's run only (an earlier run gives its numbers through R3', D-3 .. D-1)
        run_keys, vals = _run_values(c, run, [] if is_stale else days)
        prev_runs = _previous_runs(c, scope_key, d)
        # reference run: today's run, else the stale run when it is the newest run of D-3 .. D-1 (same ordering)
        scoped = run is not None and (not is_stale or (bool(prev_runs) and prev_runs[0]["id"] == run["id"]))
        no_run_3_days = is_stale and run is not None and not scoped   # latest run older than D-3: information only
        if no_run_3_days:
            stale_reason = STALE_NO_RUN_3_DAYS
        ref = run if scoped else None
        need = {k for k in run_keys if vals.get(k) is None or None in vals[k]} if scoped else set()
        prev = _previous_values(c, prev_runs, days, need)
        av = avg_demand.avg_value(d, conn=c, cfg=cfg)
        conf = {(r[0], r[1]): r[2] for r in c.execute("SELECT sku_code, fc_code, forecast_source FROM forecast_source_config")}
        cfg_rows = _config_rows(c)
        names = _names(c, d.isoformat(), av["source_table"])
        # 1.4.5 (C7 / C5): information only - an error never fails the file (flag SUMMARY_INFO_FAILED, "khong ro")
        info_failed = []
        try:
            fallback = _fallback_info(c, ref, run_keys, cfg)
        except Exception as e:  # noqa: BLE001
            fallback = None
            info_failed.append(("fallback", e))
        try:
            source_build = _source_build(c, scope_key, d)
        except Exception as e:  # noqa: BLE001
            source_build = {"text": f"{FLAG_OPEN_HOURS_LAG}: {UNKNOWN} (loi doc thong tin)", "built_first": UNKNOWN,
                            "error": f"{type(e).__name__}"}
            info_failed.append(("source_build", e))
    for part, e in info_failed:
        log.warning("sel2 export summary information not read", extra={"ctx": {
            "forecast_date": d.isoformat(), "part": part, "error": f"{type(e).__name__}: {e}"[:300]}})
    avg_keys = set(av["values"])
    keys = sorted(set(run_keys) | avg_keys)
    avg = av["values"]
    for k in keys:                                          # SKU x FC of the run without an AVG_DEMAND row
        if k not in avg:
            avg[k] = {"value": None, "reason": avg_demand.REASON_NO_ROW, "n_sellers": 0}
    lgbm_keys = {k for k, s in conf.items() if s == LIGHTGBM}
    model_used: dict[str, int] = {}
    for g, m in (run_keys.values() if ref else ()):         # the scope of the reference run only
        model_used[m] = model_used.get(m, 0) + 1
    no_value: dict[str, int] = {}
    for k in keys:
        if avg[k]["reason"]:
            no_value[avg[k]["reason"]] = no_value.get(avg[k]["reason"], 0) + 1
    stats = {"rows_by_fallback_reason": {}, "flag_rows": {}}
    plan = _plan_or_fail(keys, d)                           # before any version is reserved
    n_rows = len(keys) * H_ALL
    gt_info: dict = {"sheet": False}                        # 1.4.6 (C3): sheet GIAI_THICH when a run has a sidecar
    try:
        gt = _GiaiThich(d, plan, run, is_stale, prev_runs, scope_key, names, gt_info)
    except Exception as e:  # noqa: BLE001 - explanation only, never fails the file
        log.warning("sel2 export: giai_thich not prepared", extra={"ctx": {"forecast_date": d.isoformat(),
                                                                          "error": f"{type(e).__name__}: {e}"[:300]}})
        gt, gt_info = None, {"sheet": False, "error": f"{type(e).__name__}"}
    if gt is not None and not gt.enabled:
        gt = None
    file_flags = ([STALE_NO_RUN if run is None else "STALE"] if is_stale else []) + \
        ([STALE_NO_RUN_3_DAYS] if no_run_3_days else []) + ([FLAG_AVG_NO_READ] if av["read_id"] is None else []) +         ([FLAG_INFO_FAILED] if info_failed else [])
    if gt_info.get("skipped"):                              # today's run: the sidecar step was skipped / failed
        file_flags.append(FLAG_GIAI_THICH_SKIPPED)
    ymd, latest_name = file_names(d)
    folder = root / ymd
    base = paths.data_dir().resolve()
    with _lock:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            _remove_stale_temp(folder)
            version, reservation = _reserve_version(folder, ymd, d)
        except OSError as e:
            raise AppError("SEL2_EXPORT_WRITE_FAILED", 500, detail=f"{type(e).__name__}: {e}"[:300]) from None
        vpath = folder / f"du_bao_{ymd}_v{version}.xlsx"
        recorded = False
        try:
            now = now_utc()
            created_at = iso(now)
            summary = {"forecast_date": d.isoformat(), "version": version, "created_at": created_at,
                       "created_at_vn": now.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S"), "trigger": trigger,
                       "is_stale": is_stale, "stale_reason": stale_reason, "file_flags": file_flags,
                       "refresh_run_id": run["id"] if run else None,
                       "run_forecast_date": run["forecast_date"] if run else None,
                       "previous_runs": [f"{r['forecast_date']}:{r['id']}" for r in prev_runs],
                       "model_version": ref["model_version"] if ref else None,
                       "data_cutoff_date": ref["data_as_of"] if ref else None, "scope_key": scope_key,
                       "n_rows": n_rows, "n_rows_h1_7": len(keys) * HORIZON, "layout": _layout_summary(plan),
                       "sku_fc": {"total": len(keys), "in_forecast_scope": len(run_keys) if ref else 0,
                                  "configured_lightgbm": len(lgbm_keys),
                                  "configured_lightgbm_not_in_file": len(lgbm_keys - set(keys))},
                       "rows_by_fallback_reason": stats["rows_by_fallback_reason"], "flag_rows": stats["flag_rows"],
                       "model_used_by_sku_fc": model_used, "fallback": fallback, "source_build": source_build,
                       "avg": {"source_kind": av["source_kind"], "source_table": av["source_table"],
                               "source_modified": av["source_modified"], "completed_at": av["completed_at"],
                               "rule": av["rule"], "sku_fc_with_value": sum(1 for k in keys if not avg[k]["reason"]),
                               "no_value_by_reason": no_value}, "giai_thich": gt_info}
            kept: dict = {}                         # 1.4.4: rows of published.HISTORY_HORIZONS (history page)

            def rows_for(ks):
                rows = _rows(d, ks, run, run_keys, vals, avg, conf, names, is_stale, stats, prev, scoped)
                return published.keep(gt.capture(rows) if gt else rows, kept, COLUMNS)
            tmp = _tmp_name(folder, vpath.stem)
            config_rows = _config_book_rows(cfg_rows, names)
            try:
                # TOM_TAT is written after DU_BAO_*: its counts are complete once the rows generators are consumed
                with os.fdopen(_excl(tmp), "wb") as f:
                    _write_book(f, d, plan, rows_for, _LazySummary(summary), config_rows,
                                **({"extra": [gt.sheet()]} if gt else {}))   # call unchanged without the sheet
                os.rename(tmp, vpath)                       # fails (never replaces) when the version file exists
            finally:
                tmp.unlink(missing_ok=True)
            sha = _sha256(vpath)
            rel = vpath.relative_to(base).as_posix()
            flags = file_flags + sorted(stats["flag_rows"])
            rid = db.new_id("EXP")
            # 1.4.5: earlier versions of the day -> _bo files, their paths updated with the new record (one transaction)
            moves, rename_failed = _retire_earlier(d, version, base, cfg)
            if rename_failed:
                flags.append(FLAG_RENAME_FAILED)
                summary["rename_failed_versions"] = rename_failed
            try:
                with db.tx() as c:
                    c.execute("INSERT INTO export_runs(id, forecast_date, version, path, sha256, n_rows, is_stale, "
                              "flags, refresh_run_id, trigger, job_id, created_at, summary_json) "
                              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (rid, d.isoformat(), version, rel, sha, n_rows, int(is_stale), ",".join(flags) or None,
                               run["id"] if run else None, trigger, job_id, created_at,
                               json.dumps(summary, ensure_ascii=False, default=str)))
                    for old_id, _p, _bo, old_rel in moves:
                        c.execute("UPDATE export_runs SET path=? WHERE id=?", (old_rel, old_id))
                    db.audit(c, "SEL2_EXPORT_WRITTEN", "export_run", rid,
                             {"forecast_date": d.isoformat(), "version": version, "rows": n_rows, "is_stale": is_stale,
                              "trigger": trigger, "retired": [m[3] for m in moves],
                              "rename_failed_versions": rename_failed})
            except BaseException:
                _undo_retire(moves)
                raise
            recorded = True
            # 1.4.4: sidecar of the history page (published.py) from the rows written; a failure is only a flag
            sflag = published.write_safe(vpath, rid, d, sha, kept)
            if sflag:
                flags.append(sflag)
                try:
                    with db.tx() as c:
                        c.execute("UPDATE export_runs SET flags=? WHERE id=?", (",".join(flags), rid))
                except sqlite3.Error:                   # the flag stays in the result and the log only
                    pass
        except (OSError, sqlite3.IntegrityError, RuntimeError, ValueError) as e:   # _rows20 / xlsx_stream refusals too
            raise AppError("SEL2_EXPORT_WRITE_FAILED", 500, detail=f"{type(e).__name__}: {e}"[:300]) from None
        finally:
            if not recorded and vpath.exists():         # this call's own file without a record: removed
                try:
                    vpath.unlink()
                except OSError:
                    pass
            try:
                reservation.unlink(missing_ok=True)
            except OSError:
                pass
        # the version is recorded: the latest copy can only add a flag, never fail the export
        lflag = _latest_copy(folder, vpath, folder / latest_name, d, version)
        if lflag:
            flags.append(lflag)
            with db.tx() as c:
                c.execute("UPDATE export_runs SET flags=? WHERE id=?", (",".join(flags), rid))
    log.info("sel2 export written", extra={"ctx": {"forecast_date": d.isoformat(), "version": version, "rows": n_rows,
                                                   "is_stale": is_stale, "sha256": sha, "latest_copy": lflag or "OK"}})
    return {"id": rid, "path": rel, "latest_path": (folder / latest_name).relative_to(base).as_posix(),
            "version": version, "sha256": sha, "n_rows": n_rows, "is_stale": is_stale, "flags": flags,
            "summary": summary, "retired": [m[3] for m in moves]}


class _LazySummary:
    """TOM_TAT rows built when the sheet is written (after DU_BAO filled the row counts)."""
    def __init__(self, summary: dict):
        self.summary = summary

    def __iter__(self):
        return iter(_summary_rows(self.summary))


# ------------------------------------------------------------------ temporary file of the first start
TEMP_TRIGGER, TEMP_MODEL = "BOOTSTRAP_TEMP", "V33_L112"
TEMP_NOTE = "bản tạm – chưa chọn mô hình theo SKU"


def temp_file_name(d) -> str:
    return f"du_bao_{_day(d).strftime('%Y%m%d')}_TAM.xlsx"


def _candidate_values(conn, scope_key: str, d: date, days: list[str], groups: dict,
                      model: str = TEMP_MODEL) -> tuple[dict, dict, dict]:
    """(pseudo run, keys, values) of the stored candidate `model` of forecast day d in the shapes of _run_for /
    _run_values: quantity = the publication rule of SEL2 (daily_refresh.published_qty with select.THRESHOLD: 0 below
    0.2, else rounded up), model used = model, flags = the candidate run's flags. No candidate run of d ->
    SEL2_MISSING_FORECAST (no other number is put in its place)."""
    from ..daily_refresh import published_qty
    from .errors import MISSING_FORECAST, Sel2Error
    from .select import THRESHOLD
    cr = db.one(conn, "SELECT * FROM candidate_runs WHERE scope_key=? AND forecast_date=? AND model=? AND "
                      "status='SUCCEEDED' ORDER BY created_at DESC, rowid DESC LIMIT 1", (scope_key, d.isoformat(), model))
    if cr is None:
        raise Sel2Error(MISSING_FORECAST, detail=f"{d.isoformat()}: no stored {model} candidate")
    rows = conn.execute("SELECT sku_code, fc_code, target_date, value FROM candidate_forecasts WHERE forecast_date=? "
                        "AND model=?", (d.isoformat(), model)).fetchall()
    qty = published_qty([r[3] for r in rows], THRESHOLD).tolist()
    idx = {t: i for i, t in enumerate(days)}
    keys: dict[tuple, tuple] = {}
    vals: dict[tuple, list] = {}
    fl = cr["flags"]
    for (sku, fc, td, raw), q in zip(rows, qty):
        k = (sku, fc)
        if k not in keys:
            g = groups.get(k)
            keys[k] = (None if g is None or g != g else g, model)  # NaN -> None, as store.publish
        i = idx.get(str(td)[:10])
        if i is not None:
            vals.setdefault(k, [None] * HORIZON)[i] = (int(q), raw, model, fl)
    run = {"id": None, "forecast_date": d.isoformat(), "model_version": f"TAM {model}={cr['train_run_id']}",
           "data_as_of": cr["data_as_of"]}
    return run, keys, vals


def write_temp_export(forecast_date, groups: dict | None = None, job_id=None, scope_key: str | None = None) -> dict:
    """Temporary Excel of the first start (pipeline.bootstrap, before the past days and SEL2 are computed):
    du_bao_YYYYMMDD_TAM.xlsx in the day folder with the V33_L112 candidate of D (models of D's week) in place of the SEL2
    run; same rows, sources and AVG_DEMAND as the daily file (_rows); TOM_TAT starts with TEMP_NOTE and the trigger
    BOOTSTRAP_TEMP. Never a version, never the latest copy, never published, never in export_runs (data-check
    export_files_exist reads export_runs only): an audit record SEL2_EXPORT_TEMP_WRITTEN. A second call of the same day
    replaces the file (temporary file, then replace; open in Excel -> SEL2_EXPORT_WRITE_FAILED, the old file stays).
    groups: {(sku, fc): A / B / C} of D (column nhom)."""
    d = _day(forecast_date)
    cfg = ss.get("sel2_pipeline")
    if not cfg.enabled:
        raise AppError("SEL2_PIPELINE_DISABLED", 409)
    root = export_root(cfg)
    days = [(d + timedelta(days=i)).isoformat() for i in range(HORIZON)]
    with db.read() as c:
        if scope_key is None:
            from ...data.demand import resolve_scope
            scope_key = resolve_scope(c)["scope_key"]
        run, run_keys, vals = _candidate_values(c, scope_key, d, days, groups or {})
        av = avg_demand.avg_value(d, conn=c, cfg=cfg)
        conf = {(r[0], r[1]): r[2] for r in c.execute("SELECT sku_code, fc_code, forecast_source FROM forecast_source_config")}
        cfg_rows = _config_rows(c)
        names = _names(c, d.isoformat(), av["source_table"])
    keys = sorted(set(run_keys) | set(av["values"]))
    avg = av["values"]
    for k in keys:                                          # SKU x FC of the candidate without an AVG_DEMAND row
        if k not in avg:
            avg[k] = {"value": None, "reason": avg_demand.REASON_NO_ROW, "n_sellers": 0}
    lgbm_keys = {k for k, s in conf.items() if s == LIGHTGBM}
    no_value: dict[str, int] = {}
    for k in keys:
        if avg[k]["reason"]:
            no_value[avg[k]["reason"]] = no_value.get(avg[k]["reason"], 0) + 1
    stats = {"rows_by_fallback_reason": {}, "flag_rows": {}}
    plan = _plan_or_fail(keys, d)
    n_rows = len(keys) * H_ALL
    file_flags = [FLAG_AVG_NO_READ] if av["read_id"] is None else []
    ymd, _ = file_names(d)
    folder = root / ymd
    target = folder / temp_file_name(d)
    base = paths.data_dir().resolve()
    now = now_utc()
    summary = {"forecast_date": d.isoformat(), "version": "TAM", "created_at": iso(now),
               "created_at_vn": now.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S"), "trigger": TEMP_TRIGGER,
               "note": TEMP_NOTE, "is_stale": False, "stale_reason": None, "file_flags": file_flags,
               "refresh_run_id": None, "run_forecast_date": d.isoformat(), "model_version": run["model_version"],
               "data_cutoff_date": run["data_as_of"], "scope_key": scope_key, "n_rows": n_rows,
               "n_rows_h1_7": len(keys) * HORIZON, "layout": _layout_summary(plan),
               "sku_fc": {"total": len(keys), "in_forecast_scope": len(run_keys), "configured_lightgbm": len(lgbm_keys),
                          "configured_lightgbm_not_in_file": len(lgbm_keys - set(keys))},
               "rows_by_fallback_reason": stats["rows_by_fallback_reason"], "flag_rows": stats["flag_rows"],
               "model_used_by_sku_fc": {TEMP_MODEL: len(run_keys)} if run_keys else {},
               "avg": {"source_kind": av["source_kind"], "source_table": av["source_table"],
                       "source_modified": av["source_modified"], "completed_at": av["completed_at"], "rule": av["rule"],
                       "sku_fc_with_value": sum(1 for k in keys if not avg[k]["reason"]), "no_value_by_reason": no_value}}
    def rows_for(ks):
        return _rows(d, ks, run, run_keys, vals, avg, conf, names, False, stats)
    config_rows = _config_book_rows(cfg_rows, names)
    with _lock:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            _remove_stale_temp(folder)
            tmp = _tmp_name(folder, target.stem)
            try:
                with os.fdopen(_excl(tmp), "wb") as f:
                    _write_book(f, d, plan, rows_for, _LazyTempSummary(summary), config_rows)
                os.replace(tmp, target)                     # an earlier temporary file of the day is replaced
            finally:
                tmp.unlink(missing_ok=True)
            sha = _sha256(target)
        except OSError as e:
            raise AppError("SEL2_EXPORT_WRITE_FAILED", 500, detail=f"{type(e).__name__}: {e}"[:300]) from None
    rel = target.relative_to(base).as_posix()
    flags = file_flags + sorted(stats["flag_rows"])
    with db.tx() as c:
        db.audit(c, "SEL2_EXPORT_TEMP_WRITTEN", "export_file", rel,
                 {"forecast_date": d.isoformat(), "rows": n_rows, "sha256": sha, "model": TEMP_MODEL,
                  "trigger": TEMP_TRIGGER, "job_id": job_id})
    log.info("sel2 temporary export written", extra={"ctx": {"forecast_date": d.isoformat(), "rows": n_rows,
                                                             "sha256": sha, "path": rel}})
    return {"path": rel, "sha256": sha, "n_rows": n_rows, "trigger": TEMP_TRIGGER, "model_used": TEMP_MODEL,
            "temporary": True, "flags": flags, "sku_fc": summary["sku_fc"]}


class _LazyTempSummary(_LazySummary):
    """TOM_TAT of the temporary file: the note and the trigger first, then the rows of the daily file."""
    def __iter__(self):
        return iter([["ghi_chu", TEMP_NOTE], ["trigger", TEMP_TRIGGER]]
                    + [r for r in _summary_rows(self.summary) if r[0] != "trigger"])


# ------------------------------------------------------------------ reading
def runs(forecast_date) -> list[dict]:
    """Versions of forecast day D, newest first."""
    d = _day(forecast_date).isoformat()
    with db.read() as c:
        items = db.rows(c, "SELECT id, forecast_date, version, path, sha256, n_rows, is_stale, flags, refresh_run_id, "
                           "trigger, job_id, created_at, summary_json FROM export_runs WHERE forecast_date=? "
                           "ORDER BY version DESC, rowid DESC", (d,))
    for it in items:
        it["summary"] = json.loads(it.pop("summary_json") or "null")
    return items


def latest_file(forecast_date) -> tuple[Path, dict]:
    """(file of the latest version of D, its record); SEL2_EXPORT_NOT_FOUND when D has no export or the file is gone."""
    d = _day(forecast_date)
    with db.read() as c:
        r = db.one(c, "SELECT * FROM export_runs WHERE forecast_date=? ORDER BY version DESC, rowid DESC LIMIT 1",
                   (d.isoformat(),))
    if r is None:
        raise AppError("SEL2_EXPORT_NOT_FOUND", 404, detail=d.isoformat())
    p = resolve_file(r["path"])
    if not p.is_file():
        raise AppError("SEL2_EXPORT_NOT_FOUND", 404, detail=f"{d.isoformat()} v{r['version']}: file missing")
    return p, r
