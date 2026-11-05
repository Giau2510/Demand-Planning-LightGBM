"""1.4.0 SEL2: the daily Excel the purchasing team uses (<data folder>\\<sel2_pipeline.export_subdir>\\YYYYMMDD\\).

Every call writes a NEW version: du_bao_YYYYMMDD_vN.xlsx (never overwritten, never changed later) and the copy of the
latest version du_bao_YYYYMMDD.xlsx (written to a temporary file, then replaced). export_runs keeps one record per
version (path relative to the data folder, sha256, row count, stale flag, summary).

Versions across processes (the scheduled export runs in the server, sel2-export in a CLI process): a version number is
reserved by creating .du_bao_YYYYMMDD_vN.reserved exclusively (O_EXCL) in the day folder; a number whose file, record or
reservation exists is skipped (a reservation left by a crashed process leaves a gap, never a clash; .reserved / .tmp
files older than 1 hour are removed before reserving). Temporary files have a unique name (pid + random) created
exclusively. The version file and its export_runs record are written first;
the latest copy comes after: when it cannot be replaced (du_bao_YYYYMMDD.xlsx open in Excel) the version is kept and
flagged LATEST_COPY_LOCKED (export_runs.flags and the result), never failed. A day without a completed AVG_DEMAND read
is flagged AVG_NO_READ (file level: TOM_TAT and export_runs.flags).

  DU_BAO   one row per SKU x FC x target day (D .. D+6): the union of the SKU x FC of the SEL2 run used and of the
           SKU x FC with an AVG_DEMAND row of day D. forecast_used
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
           lightgbm_forecast and avg_demand keep the original values (unrounded, empty when missing); lightgbm_forecast,
           raw_value and model_used come from today's run, else from the R3' run (flag LAN_CHAY_TRUOC, every source).
           Row provenance (model_version, data_cutoff_date): a row whose LightGBM number comes from a previous run
           (flag LAN_CHAY_TRUOC: R3', R4 with the R3' number, or shown next to an AVG_DEMAND value) carries the values of
           THAT run; every other row carries those of the reference run (today's run; on a failed day the newest run
           of D-3 .. D-1); without a reference run (no run within D-3 .. D-1, or no SEL2 run at all) both are empty.
           With a reference run of D-1 the target day D+6 is its horizon 8 (beyond H = 7) and older runs cover even
           less: on a failed day D+6 never has a previous-run number -> AVG + STALE (in the scope) or 0 by R2.
  TOM_TAT  counts of the file (scope, fallback reasons, flags, model used, AVG_DEMAND read used).
  CONFIG   the SKU x FC configured LIGHTGBM at export time.
  seller_code / product_code (DU_BAO and CONFIG, right after ten_san_pham; owner decision 05/11/2026): sku_code split
           at its FIRST dot (MEDX.ABC-ABC-010 -> MEDX / ABC-ABC-010, A.B.C -> A / B.C). No dot: seller_code empty,
           product_code = sku_code; an empty part before the dot (".X") gives seller_code empty, an empty part after
           it ("X.") product_code empty (split_sku).

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
version, not the latest copy, not in export_runs; replaced by the next bootstrap of the same day.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path, PureWindowsPath

from ... import db, paths
from ... import settings_service as ss
from ...messages import AppError
from ...timeutil import VN_TZ, now_utc, iso
from . import avg_demand
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
_lock = threading.Lock()                  # one export at a time in this process (version numbers, file names)


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


def resolve_file(rel_path: str, cfg=None) -> Path:
    """Absolute path of a stored relative export path; refused when it leaves the export folder."""
    root = export_root(cfg)
    p = paths.data_dir().resolve().joinpath(*[x for x in str(rel_path).replace("\\", "/").split("/") if x]).resolve()
    if not p.is_relative_to(root):
        raise AppError("SEL2_EXPORT_PATH_INVALID", 500, detail=str(rel_path))
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
    out.update({k: v for k, v in (product_names.names(conn) or {}).items() if v})
    return out


def _config_rows(conn) -> list[dict]:
    return db.rows(conn, "SELECT sku_code, fc_code, ghi_chu, updated_by, updated_at FROM forecast_source_config "
                         "WHERE forecast_source=? ORDER BY sku_code, fc_code", (LIGHTGBM,))


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
            yield [sku, name, seller, product, fc, grp, d, td, i + 1, qty, av, src, used, reason, v[2] if v else None,
                   v[1] if v else None, v[5] if from_prev else mv, v[6] if from_prev else cutoff, st, flags]


def _write_book(target: Path, rows, n_rows: int, summary_rows, config_rows: list) -> None:
    """Bold header on every sheet; DU_BAO and CONFIG: header frozen + autofilter. Streamed (xlsx_stream: openpyxl's
    writer took about 380 s for 420k rows); summary_rows is read after DU_BAO is written."""
    write_xlsx(target, [Sheet(SHEET_MAIN, COLUMNS, rows, n_rows, freeze_header=True, autofilter=True),
                        Sheet(SHEET_SUMMARY, SUMMARY_COLUMNS, summary_rows),
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
           ["rows_total", s["n_rows"]]]
    out += [[f"rows_fallback_reason:{k or '(none)'}", v] for k, v in sorted(s["rows_by_fallback_reason"].items())]
    out += [[f"rows_flag:{k}", v] for k, v in sorted(s["flag_rows"].items())]
    out += [[f"sku_fc_avg_reason:{k}", v] for k, v in sorted(s["avg"]["no_value_by_reason"].items())]
    out += [[f"sku_fc_model_used:{k}", v] for k, v in sorted(s["model_used_by_sku_fc"].items())]
    a = s["avg"]
    out += [["avg_source_kind", a["source_kind"]], ["avg_source_table", a["source_table"]],
            ["avg_source_modified", a["source_modified"]], ["avg_read_completed_at", a["completed_at"]],
            ["avg_seller_rule", a["rule"]]]
    return out


# ------------------------------------------------------------------ export
def write_daily_export(forecast_date, trigger: str = "SCHEDULE", job_id=None, scope_key: str | None = None) -> dict:
    """Write a new version of the daily Excel of forecast day D (Vietnam day). Returns path (relative to the data
    folder), version, n_rows, is_stale, summary. Earlier version files are never touched."""
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
    n_rows = len(keys) * HORIZON
    file_flags = ([STALE_NO_RUN if run is None else "STALE"] if is_stale else []) + \
        ([STALE_NO_RUN_3_DAYS] if no_run_3_days else []) + ([FLAG_AVG_NO_READ] if av["read_id"] is None else [])
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
                       "n_rows": n_rows,
                       "sku_fc": {"total": len(keys), "in_forecast_scope": len(run_keys) if ref else 0,
                                  "configured_lightgbm": len(lgbm_keys),
                                  "configured_lightgbm_not_in_file": len(lgbm_keys - set(keys))},
                       "rows_by_fallback_reason": stats["rows_by_fallback_reason"], "flag_rows": stats["flag_rows"],
                       "model_used_by_sku_fc": model_used,
                       "avg": {"source_kind": av["source_kind"], "source_table": av["source_table"],
                               "source_modified": av["source_modified"], "completed_at": av["completed_at"],
                               "rule": av["rule"], "sku_fc_with_value": sum(1 for k in keys if not avg[k]["reason"]),
                               "no_value_by_reason": no_value}}
            rows = _rows(d, keys, run, run_keys, vals, avg, conf, names, is_stale, stats, prev, scoped)
            tmp = _tmp_name(folder, vpath.stem)
            config_rows = _config_book_rows(cfg_rows, names)
            try:
                # TOM_TAT is written after DU_BAO: its counts are complete once the rows generator is consumed
                with os.fdopen(_excl(tmp), "wb") as f:
                    _write_book(f, rows, n_rows, _LazySummary(summary), config_rows)
                os.rename(tmp, vpath)                       # fails (never replaces) when the version file exists
            finally:
                tmp.unlink(missing_ok=True)
            sha = _sha256(vpath)
            rel = vpath.relative_to(base).as_posix()
            flags = file_flags + sorted(stats["flag_rows"])
            rid = db.new_id("EXP")
            with db.tx() as c:
                c.execute("INSERT INTO export_runs(id, forecast_date, version, path, sha256, n_rows, is_stale, flags, "
                          "refresh_run_id, trigger, job_id, created_at, summary_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (rid, d.isoformat(), version, rel, sha, n_rows, int(is_stale), ",".join(flags) or None,
                           run["id"] if run else None, trigger, job_id, created_at,
                           json.dumps(summary, ensure_ascii=False, default=str)))
                db.audit(c, "SEL2_EXPORT_WRITTEN", "export_run", rid,
                         {"forecast_date": d.isoformat(), "version": version, "rows": n_rows, "is_stale": is_stale,
                          "trigger": trigger})
            recorded = True
        except (OSError, sqlite3.IntegrityError) as e:
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
            "summary": summary}


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
    n_rows = len(keys) * HORIZON
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
               "sku_fc": {"total": len(keys), "in_forecast_scope": len(run_keys), "configured_lightgbm": len(lgbm_keys),
                          "configured_lightgbm_not_in_file": len(lgbm_keys - set(keys))},
               "rows_by_fallback_reason": stats["rows_by_fallback_reason"], "flag_rows": stats["flag_rows"],
               "model_used_by_sku_fc": {TEMP_MODEL: len(run_keys)} if run_keys else {},
               "avg": {"source_kind": av["source_kind"], "source_table": av["source_table"],
                       "source_modified": av["source_modified"], "completed_at": av["completed_at"], "rule": av["rule"],
                       "sku_fc_with_value": sum(1 for k in keys if not avg[k]["reason"]), "no_value_by_reason": no_value}}
    rows = _rows(d, keys, run, run_keys, vals, avg, conf, names, False, stats)
    config_rows = _config_book_rows(cfg_rows, names)
    with _lock:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            _remove_stale_temp(folder)
            tmp = _tmp_name(folder, target.stem)
            try:
                with os.fdopen(_excl(tmp), "wb") as f:
                    _write_book(f, rows, n_rows, _LazyTempSummary(summary), config_rows)
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
