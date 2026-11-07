"""Daily Excel in the 20-day layout (owner decision 05/11/2026 evening, effective from the 06/11 morning file).
One pass, run every 5 minutes by the Scheduled Task "DemandForecastExcel20" (register-excel20.ps1). The app keeps
writing its daily SEL2 Excel (du_bao_YYYYMMDD_vN.xlsx, recorded in export_runs, never touched here) and its LATEST COPY
du_bao_YYYYMMDD.xlsx; this script rewrites ONLY that latest copy, from the newest recorded version vN, into:
  DU_BAO_<fc_code>  one sheet per warehouse (DU_BAO_BD, DU_BAO_HN): every SKU x FC of that warehouse x horizon 1..20
                    (target_date D .. D+19), the app's columns in their order + cach_tinh (last column).
                    h 1..7: the app's rows unchanged, cach_tinh SEL2.
                    h 8..20: cach_tinh UOC_TINH_THEO_TUAN; template = the row of the same SKU x FC with horizon
                    ((h - 1) % 7) + 1 (same weekday); target_date D + h - 1, horizon h, lightgbm_forecast = the
                    template's raw_value (unrounded, empty without one), every other column copied from the template,
                    forecast_used re-derived with the owner's fixed rule (derive_used).
  TOM_TAT           the app's rows + layout, note, rows / SKU x FC per sheet, source file + sha256, generated_at (VN).
  CONFIG            the app's rows (seller_code / product_code derived from sku_code when the file predates 1.4.3).
Detection: state file <work dir>\\state.json = what was written per forecast day (export_runs id + sha256 of the
source, sha256 / size / mtime of the written file). Each pass looks at the newest version of today's and yesterday's
forecast_date (not before --since) and rewrites the latest copy when that version is new or when the latest copy is no
longer the file written here (the app copied it again). A failed version (input invalid, warehouse too large,
verification failed) is not retried until a newer version is recorded (or --force).
Writing: temporary file .x20_du_bao_YYYYMMDD.tmp in the day folder (the app's own temp files are .du_bao_*), streamed
with xlsx_stream of the INSTALLED app (loaded read-only by file path, no bytecode written; openpyxl write_only when it
is unavailable), verified by reading it back (sheets, header order, rows = SKU x FC x 20 per sheet, forecast_used int
>= 0, target_date = D + h - 1, weekday of h 8..20 = weekday of the template), then os.replace onto the latest copy.
Latest copy open in Excel (PermissionError): the temporary file is kept and replaced at the next pass (notified once).
Read-only on the DB (sqlite3 mode=ro + PRAGMA query_only); never writes the version files, export_runs or the DB; the
operations lock (run\\OPS_LOCK) only gives a warning in the log (this script writes one Excel file, not the DB).
usage: excel20.py [--data-dir DIR] [--db FILE] [--work-dir DIR] [--app-backend DIR] [--since YYYY-MM-DD]
                  [--forecast-date YYYY-MM-DD] [--now "YYYY-MM-DD HH:MM"] [--force] [--dry-run]
       --dry-run: build + verify the temporary file only (kept, path printed); no replace, no state, no notification"""
import argparse
import codecs
import ctypes
import hashlib
import html
import importlib.util
import json
import math
import os
import re
import sqlite3
import sys
import time
import traceback
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

sys.dont_write_bytecode = True  # xlsx_stream is loaded from the installed app folder: never write __pycache__ there
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "runner"))
import notify  # noqa: E402
from common import alive, append_log, mem, ops_lock_block, proc_created, read_json, write_json  # noqa: E402
import ops_config  # noqa: E402

VN = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh, no daylight saving
RUN_NAME = "EXCEL20"
TITLE = "[EXCEL20]"
ROOT = ops_config.PROJECT_ROOT
STORAGE = ops_config.STORAGE_JSON
PROGRAMS = ops_config.PROGS
EFFECTIVE_FROM = "2026-11-06"           # owner 05/11: from the 06/11 morning file
H_APP, H_ALL = 7, 20
MAX_SKU_FC = 50_000                     # per warehouse: 50,000 x 20 rows stays below Excel's 1,048,576
USED_THRESHOLD = 0.2                    # owner rule 05/11: round 6 decimals, < 0.2 -> 0, else rounded up
SETTLE_SECONDS = 60                     # a version recorded less than a minute ago: the app may still copy it
MIN_FREE_RAM_MB, MIN_FREE_COMMIT_MB = 1500, 2500
STALE_LOCK_SECONDS = 35 * 60          # task limit 60 min; a lock whose process is gone is stale at once
STALE_TMP_SECONDS = 3600              # .x20_*.tmp left by a killed pass (not the pending file of a locked copy)
KEEP_DAYS = 14                          # state entries older than this are dropped
CACH_SEL2, CACH_WEEK = "SEL2", "UOC_TINH_THEO_TUAN"
LIGHTGBM = "LIGHTGBM"
R_OUT_ZERO, R_PREVIOUS = "NGOAI_PHAM_VI_GAN_0", "DUNG_SO_LAN_CHAY_TRUOC"
R_AVG_MISSING_LGBM, R_NO_NUMBER = "KHONG_CO_AVG_DUNG_LIGHTGBM", "KHONG_CO_SO_NAO"
SHEET_MAIN, SHEET_SUMMARY, SHEET_CONFIG = "DU_BAO", "TOM_TAT", "CONFIG"
REQUIRED = ("sku_code", "fc_code", "forecast_date", "target_date", "horizon", "lightgbm_forecast", "forecast_source",
            "forecast_used", "fallback_reason", "raw_value")
NOTE_8_20 = ("UOC_TINH_THEO_TUAN: lightgbm_forecast = raw_value cung thu trong tuan o horizon 1-7 cua lan chay hom nay "
             "(khong phai SEL2)")
LOG = None
O = None


class X20Error(Exception):
    def __init__(self, code, text):
        super().__init__(f"{code}: {text}")
        self.code, self.text = code, text


def log(msg):
    append_log(LOG, msg)


def say(title, text, high=False):
    if O.dry_run:
        log(f"(dry run, not sent) {title}: {text}")
        return
    notify.send(f"{TITLE} {title}", text, "high" if high else "default", log=LOG)


def now_vn():
    return datetime.strptime(O.now, "%Y-%m-%d %H:%M").replace(tzinfo=VN) if O.now else datetime.now(VN)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class _PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


def peak_mb():
    """peak working set of this process (MB), None when unavailable"""
    try:
        f = ctypes.windll.psapi.GetProcessMemoryInfo
        f.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PMC), ctypes.c_ulong]
        p = _PMC()
        p.cb = ctypes.sizeof(_PMC)
        if f(ctypes.c_void_p(-1), ctypes.byref(p), p.cb):
            return round(p.PeakWorkingSetSize / 2 ** 20)
    except Exception:  # noqa: BLE001
        pass
    return None


# ------------------------------------------------------------------ fixed rule (owner 05/11)
def num(v):
    """finite float of a cell value, None when missing / not a number"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def roundup(x):
    x = round(float(x), 6)
    return 0 if x < USED_THRESHOLD else math.ceil(x)


def derive_used(src, t_used, t_reason, raw):
    """(forecast_used, fallback_reason) of an h 8..20 row from its template (forecast_source, forecast_used,
    fallback_reason) and the template's raw_value; always an int >= 0"""
    if t_reason == R_OUT_ZERO:
        return 0, R_OUT_ZERO
    if src == LIGHTGBM:
        if raw is not None:
            return roundup(raw), (R_PREVIOUS if t_reason == R_PREVIOUS else None)
        used, reason = t_used, t_reason                     # Avg / 0 of the template
    elif t_reason == R_AVG_MISSING_LGBM and raw is not None:
        return roundup(raw), R_AVG_MISSING_LGBM
    else:
        used, reason = t_used, t_reason                     # AVG_DEMAND: the template's value
    u = num(used)
    if reason == R_NO_NUMBER or u is None:
        return 0, R_NO_NUMBER
    return roundup(u), reason


def split_sku(sku):
    """(seller_code, product_code): sku_code split at its FIRST dot (same rule as the app's export.split_sku)"""
    if not sku:
        return None, None
    seller, dot, product = str(sku).partition(".")
    if not dot:
        return None, sku
    return seller or None, product or None


# ------------------------------------------------------------------ reading .xlsx (stdlib, streamed)
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_T = _NS + "t"
_ROW_RE = re.compile(r"<row\b[^>]*?(?<!/)>(.*?)</row>", re.S)
_CELL_RE = re.compile(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", re.S)
_ATTR_RE = re.compile(r'([\w:]+)="([^"]*)"')
_T_RE = re.compile(r"<t(?:\s[^>]*)?(?<!/)>(.*?)</t>", re.S)
_V_RE = re.compile(r"<v>(.*?)</v>", re.S)
_EPOCH = datetime(1899, 12, 30)
_DATE_FMT_IDS = set(range(14, 23)) | set(range(27, 37)) | {45, 46, 47} | set(range(50, 59))


def _col(ref):
    n = 0
    for ch in ref:
        o = ord(ch)
        if 65 <= o <= 90:
            n = n * 26 + o - 64
        else:
            break
    return n - 1


class Book:
    """read-only workbook: sheet names, rows as lists (str / int / float / bool / date / datetime / None)"""
    def __init__(self, path):
        self.zf = zipfile.ZipFile(path)
        self._open = []
        self._dcache = {}
        names = set(self.zf.namelist())
        wb = ET.fromstring(self.zf.read("xl/workbook.xml"))
        rels = ET.fromstring(self.zf.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        self.parts = {}
        for s in wb.iter(_NS + "sheet"):
            t = target[s.get(_NS_R + "id")]
            self.parts[s.get("name")] = t.lstrip("/") if t.startswith("/") else "xl/" + t
        self.shared = []
        if "xl/sharedStrings.xml" in names:
            sst = ET.fromstring(self.zf.read("xl/sharedStrings.xml"))
            self.shared = ["".join(t.text or "" for t in si.iter(_T)) for si in sst]
        self.dstyles = {}
        if "xl/styles.xml" in names:
            st = ET.fromstring(self.zf.read("xl/styles.xml"))
            fmts = {int(f.get("numFmtId")): f.get("formatCode") or "" for f in st.iter(_NS + "numFmt")}
            xfs = st.find(_NS + "cellXfs")
            for i, xf in enumerate(xfs if xfs is not None else []):
                fid = int(xf.get("numFmtId") or 0)
                code = re.sub(r'"[^"]*"|\[[^\]]*\]', "", fmts.get(fid, "")).lower()
                if fid in _DATE_FMT_IDS or (fid >= 164 and re.search(r"[dy]|h|s", code)):
                    self.dstyles[i] = "datetime" if (re.search(r"h|s", code) or fid in (22, 45, 46, 47)) else "date"

    def close(self):
        for g in self._open:                # an iterator left mid-sheet (error) holds the zip entry, i.e. the file
            g.close()
        self.zf.close()

    def sheetnames(self):
        return list(self.parts)

    def _cell(self, a, inner):
        if inner is None:
            return None
        t = a.get("t")
        if t == "inlineStr":
            parts = _T_RE.findall(inner)
            if not parts:
                return None
            v = "".join(parts)
            return html.unescape(v) if "&" in v else v
        m = _V_RE.search(inner)
        if m is None:
            return None
        v = m.group(1)
        if t == "s":
            return self.shared[int(v)]
        if t == "str":
            return html.unescape(v) if "&" in v else v
        if t == "b":
            return v.strip() == "1"
        if t == "e":
            return None
        st = a.get("s")
        kind = self.dstyles.get(int(st)) if st is not None and self.dstyles else None
        if kind:
            d = self._dcache.get((kind, v))
            if d is None:
                d = _EPOCH + timedelta(days=float(v))
                d = self._dcache[(kind, v)] = d.date() if kind == "date" else d
            return d
        return float(v) if ("." in v or "e" in v or "E" in v) else int(v)

    def rows(self, name):
        g = self._rows(name)
        self._open.append(g)
        return g

    def _rows(self, name):
        """rows of a sheet, streamed: the sheet XML is decoded in 4 MB chunks and cut at the last </row> (regex parse:
        about 5x faster than ElementTree on 1.2M rows; any attribute order, empty / self-closing cells and rows)"""
        dec = codecs.getincrementaldecoder("utf-8")()
        with self.zf.open(self.parts[name]) as f:
            buf = ""
            while True:
                chunk = f.read(1 << 22)
                buf += dec.decode(chunk, final=not chunk)
                end = buf.rfind("</row>")
                if end >= 0:
                    for m in _ROW_RE.finditer(buf, 0, end + 6):
                        yield self._row(m.group(1))
                    buf = buf[end + 6:]
                if not chunk:
                    break

    def _row(self, inner):
        out, nxt = [], 0
        for m in _CELL_RE.finditer(inner):
            a = dict(_ATTR_RE.findall(m.group(1)))
            ref = a.get("r")
            i = _col(ref) if ref else nxt
            nxt = i + 1
            v = self._cell(a, m.group(2))
            n = len(out)
            if i == n:
                out.append(v)
            elif i > n:
                out.extend([None] * (i - n))
                out.append(v)
            else:
                out[i] = v
        return out


# ------------------------------------------------------------------ writing
@dataclass
class _OSheet:
    name: str
    header: Sequence[str]
    rows: Iterable
    n_rows: int | None = None
    freeze_header: bool = False
    autofilter: bool = False


def _openpyxl_write(target, sheets):
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    wb = Workbook(write_only=True)
    bold = Font(bold=True)
    for sh in sheets:
        ws = wb.create_sheet(sh.name)
        if sh.freeze_header:
            ws.freeze_panes = "A2"
        head = []
        for h in sh.header:
            c = WriteOnlyCell(ws, value=h)
            c.font = bold
            head.append(c)
        ws.append(head)
        n = 0
        for r in sh.rows:
            ws.append(list(r))
            n += 1
        if sh.autofilter:
            ws.auto_filter.ref = f"A1:{get_column_letter(max(len(sh.header), 1))}{n + 1}"
    wb.save(target)


def load_writer(backend):
    """(Sheet, write_xlsx, label): xlsx_stream of the installed app (or --app-backend), else openpyxl write_only"""
    try:
        if backend:
            b, label = Path(backend), f"xlsx_stream ({backend})"
        else:
            ver = (PROGRAMS / "current.txt").read_text(encoding="utf-8").split()[0]
            b, label = PROGRAMS / ver / "backend", f"xlsx_stream (app {ver})"
        p = b / "app" / "ml" / "sel2" / "xlsx_stream.py"
        spec = importlib.util.spec_from_file_location("x20_xlsx_stream", p)
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m          # dataclasses look the module up while the class is built
        spec.loader.exec_module(m)
        return m.Sheet, m.write_xlsx, label
    except Exception as e:  # noqa: BLE001
        log(f"xlsx_stream unavailable ({type(e).__name__}: {str(e)[:200]}): openpyxl write_only")
        return _OSheet, _openpyxl_write, "openpyxl write_only"


# ------------------------------------------------------------------ build
def sheet_name(fc):
    s = re.sub(r"[\[\]:*?/\\']", "_", str(fc if fc not in (None, "") else "KHONG_FC"))
    return ("DU_BAO_" + s)[:31]


def read_source(path, d):
    """parsed app file: cols (output order without cach_tinh), groups {(sku, fc): [7 row tuples]}, keys by fc (first
    appearance order), summary rows, config (header, rows), n input rows, layout label"""
    bk = Book(path)
    try:
        for s in (SHEET_MAIN, SHEET_SUMMARY, SHEET_CONFIG):
            if s not in bk.parts:
                raise X20Error("INPUT_INVALID", f"sheet {s} missing")
        it = bk.rows(SHEET_MAIN)
        in_cols = [c for c in next(it, [])]
        while in_cols and in_cols[-1] is None:
            in_cols.pop()
        if any(not isinstance(c, str) for c in in_cols) or len(set(in_cols)) != len(in_cols):
            raise X20Error("INPUT_INVALID", "DU_BAO header invalid")
        miss = [c for c in REQUIRED if c not in in_cols]
        if miss or "cach_tinh" in in_cols:
            raise X20Error("INPUT_INVALID", f"DU_BAO header: missing {miss}" if miss else "cach_tinh already there")
        cols, derived = insert_seller_product(in_cols)
        w = len(in_cols)
        src_of = [in_cols.index(c) if c in in_cols else None for c in cols]
        ix = {c: i for i, c in enumerate(cols)}
        i_sku, i_fc, i_fd, i_td, i_h = ix["sku_code"], ix["fc_code"], ix["forecast_date"], ix["target_date"], ix["horizon"]
        cache, groups, keys_by_fc, n = {}, {}, {}, 0
        for raw in it:
            if not any(v is not None for v in raw):
                continue
            n += 1
            raw = (raw + [None] * w)[:w] if len(raw) != w else raw
            if derived:
                sp = split_sku(raw[src_of[ix["sku_code"]]])
                row = [raw[j] if j is not None else sp[0 if c == "seller_code" else 1] for c, j in zip(cols, src_of)]
            else:
                row = raw
            row = tuple(cache.setdefault(v, v) if type(v) in (str, date) else v for v in row)
            h = row[i_h]
            if isinstance(h, float) and h.is_integer():
                h = int(h)
            if type(h) is not int or not 1 <= h <= H_APP:
                raise X20Error("INPUT_INVALID", f"DU_BAO row {n + 1}: horizon {h!r}")
            if row[i_fd] != d or row[i_td] != d + timedelta(days=h - 1):
                raise X20Error("INPUT_INVALID", f"DU_BAO row {n + 1}: forecast_date / target_date not D / D+h-1")
            k = (row[i_sku], row[i_fc])
            g = groups.get(k)
            if g is None:
                g = groups[k] = [None] * H_APP
                keys_by_fc.setdefault(row[i_fc], []).append(k)
            if g[h - 1] is not None:
                raise X20Error("INPUT_INVALID", f"DU_BAO row {n + 1}: SKU x FC x horizon twice")
            g[h - 1] = row
        incomplete = sum(1 for g in groups.values() if any(r is None for r in g))
        if incomplete:
            raise X20Error("INPUT_INVALID", f"{incomplete} SKU x FC without all horizons 1..{H_APP}")
        summary = list(bk.rows(SHEET_SUMMARY))
        conf = list(bk.rows(SHEET_CONFIG))
    finally:
        bk.close()
    s_head = summary[0] if summary else ["muc", "gia_tri"]
    c_head = [c for c in (conf[0] if conf else [])]
    while c_head and c_head[-1] is None:
        c_head.pop()
    c_cols, c_derived = insert_seller_product(c_head)
    c_rows = []
    for r in conf[1:]:
        if not any(v is not None for v in r):
            continue
        r = (r + [None] * len(c_head))[:len(c_head)]
        if c_derived and "sku_code" in c_head:
            sp = split_sku(r[c_head.index("sku_code")])
            r = [r[c_head.index(c)] if c in c_head else sp[0 if c == "seller_code" else 1] for c in c_cols]
        c_rows.append(r)
    return {"cols": cols, "groups": groups, "keys_by_fc": keys_by_fc, "summary_head": s_head[:2] or ["muc", "gia_tri"],
            "summary": [r for r in summary[1:] if any(v is not None for v in r)],
            "config_head": c_cols if c_derived else c_head, "config": c_rows, "n_rows": n,
            "layout": "1.4.2 (seller/product derived)" if derived else "1.4.3"}


def insert_seller_product(cols):
    """(columns with seller_code, product_code after ten_san_pham (or sku_code) when missing, derived?)"""
    cols = list(cols)
    if "seller_code" in cols and "product_code" in cols:
        return cols, False
    if "sku_code" not in cols:
        return cols, False
    at = cols.index("ten_san_pham") + 1 if "ten_san_pham" in cols else cols.index("sku_code") + 1
    add = [c for c in ("seller_code", "product_code") if c not in cols]
    return cols[:at] + add + cols[at:], True


def make_rows(src, keys, d):
    cols, groups = src["cols"], src["groups"]
    ix = {c: i for i, c in enumerate(cols)}
    i_td, i_h, i_lg, i_raw = ix["target_date"], ix["horizon"], ix["lightgbm_forecast"], ix["raw_value"]
    i_src, i_used, i_reason = ix["forecast_source"], ix["forecast_used"], ix["fallback_reason"]
    targets = [d + timedelta(days=h - 1) for h in range(H_ALL + 1)]
    for k in keys:
        g = groups[k]
        for r in g:
            yield (*r, CACH_SEL2)
        for h in range(H_APP + 1, H_ALL + 1):
            t = g[(h - 1) % H_APP]
            r = list(t)
            raw = num(t[i_raw])
            r[i_td], r[i_h], r[i_lg] = targets[h], h, raw
            r[i_used], r[i_reason] = derive_used(t[i_src], t[i_used], t[i_reason], raw)
            r.append(CACH_WEEK)
            yield r


def build(src, d, tmp, writer, source_name, source_sha):
    Sheet, write_xlsx, _ = writer
    fcs = sorted(src["keys_by_fc"], key=lambda x: (x is None, str(x)))
    big = {str(fc): len(src["keys_by_fc"][fc]) for fc in fcs if len(src["keys_by_fc"][fc]) > MAX_SKU_FC}
    if big:
        raise X20Error("TOO_MANY_SKU_FC", f"SKU x FC per warehouse > {MAX_SKU_FC}: {big}")
    names = [sheet_name(fc) for fc in fcs]
    if len(set(names)) != len(names) or SHEET_SUMMARY in names or SHEET_CONFIG in names:
        raise X20Error("INPUT_INVALID", f"sheet names clash: {names}")
    header = list(src["cols"]) + ["cach_tinh"]
    plan = [(nm, fc, len(src["keys_by_fc"][fc])) for nm, fc in zip(names, fcs)]
    summary = [list(r[:2]) for r in src["summary"]]
    summary += [["layout", "20 ngay, tach sheet theo kho"], ["horizon_8_20", NOTE_8_20]]
    summary += [[f"rows:{nm}", nk * H_ALL] for nm, _, nk in plan]
    summary += [[f"sku_fc:{nm}", nk] for nm, _, nk in plan]
    summary += [["source_file", source_name], ["source_sha256", source_sha],
                ["generated_at", now_vn().strftime("%Y-%m-%d %H:%M:%S") + " (VN)"]]
    sheets = [Sheet(nm, header, make_rows(src, src["keys_by_fc"][fc], d), nk * H_ALL, freeze_header=True,
                    autofilter=True) for nm, fc, nk in plan]
    sheets.append(Sheet(SHEET_SUMMARY, list(src["summary_head"]), summary, len(summary), freeze_header=True,
                        autofilter=True))
    sheets.append(Sheet(SHEET_CONFIG, list(src["config_head"]), src["config"], len(src["config"]), freeze_header=True,
                        autofilter=True))
    with open(tmp, "wb") as f:
        write_xlsx(f, sheets)
        f.flush()
        os.fsync(f.fileno())
    return header, plan, len(summary)


def verify(tmp, d, src, header, plan, n_summary):
    """read the written file back; raises X20Error VERIFY_FAILED"""
    def bad(msg):
        raise X20Error("VERIFY_FAILED", msg)
    bk = Book(tmp)
    try:
        want = [nm for nm, _, _ in plan] + [SHEET_SUMMARY, SHEET_CONFIG]
        if bk.sheetnames() != want:
            bad(f"sheets {bk.sheetnames()} != {want}")
        ix = {c: i for i, c in enumerate(header)}
        i_sku, i_fc, i_td, i_h = ix["sku_code"], ix["fc_code"], ix["target_date"], ix["horizon"]
        i_used, i_cach = ix["forecast_used"], ix["cach_tinh"]
        for nm, fc, nk in plan:
            it = bk.rows(nm)
            if next(it, None) != header:
                bad(f"{nm}: header order")
            keys, n, block, prev_key = set(src["keys_by_fc"][fc]), 0, [None] * (H_ALL + 1), None
            seen = set()
            for r in it:
                n += 1
                r = (r + [None] * len(header))[:len(header)]
                h = r[i_h]
                if type(h) is not int or h != (n - 1) % H_ALL + 1:
                    bad(f"{nm} row {n + 1}: horizon {h!r}")
                k = (r[i_sku], r[i_fc])
                if h == 1:
                    if k not in keys or k in seen:
                        bad(f"{nm} row {n + 1}: SKU x FC not expected / twice")
                    seen.add(k)
                    prev_key = k
                elif k != prev_key:
                    bad(f"{nm} row {n + 1}: SKU x FC changes inside its 20 rows")
                u = r[i_used]
                if type(u) is not int or u < 0:
                    bad(f"{nm} row {n + 1}: forecast_used {u!r}")
                td = r[i_td]
                if td != d + timedelta(days=h - 1):
                    bad(f"{nm} row {n + 1}: target_date {td!r}")
                block[h] = td
                if h > H_APP and td.weekday() != block[(h - 1) % H_APP + 1].weekday():
                    bad(f"{nm} row {n + 1}: weekday differs from the template")
                if r[i_cach] != (CACH_SEL2 if h <= H_APP else CACH_WEEK):
                    bad(f"{nm} row {n + 1}: cach_tinh {r[i_cach]!r}")
            if n != nk * H_ALL or len(seen) != nk:
                bad(f"{nm}: {n} rows / {len(seen)} SKU x FC, expected {nk * H_ALL} / {nk}")
        if sum(1 for _ in bk.rows(SHEET_SUMMARY)) != n_summary + 1:
            bad("TOM_TAT rows")
        if sum(1 for _ in bk.rows(SHEET_CONFIG)) != len(src["config"]) + 1:
            bad("CONFIG rows")
    finally:
        bk.close()
    try:                                    # the consumers open it with openpyxl / Excel: metadata must load
        from openpyxl import load_workbook
        with open(tmp, "rb") as f:          # a file object: openpyxl refuses the .tmp extension of a path
            wb = load_workbook(f, read_only=True)
            names = wb.sheetnames
            wb.close()
        if names != want:
            bad(f"openpyxl sheets {names}")
    except ImportError:
        log("openpyxl not installed: open check skipped")
    except X20Error:
        raise
    except Exception as e:  # noqa: BLE001
        bad(f"openpyxl cannot open it: {type(e).__name__}")


# ------------------------------------------------------------------ one forecast day
def newest_version(conn, d):
    return conn.execute("SELECT id, forecast_date, version, path, sha256, n_rows, created_at FROM export_runs "
                        "WHERE forecast_date = ? ORDER BY version DESC, created_at DESC, rowid DESC LIMIT 1",
                        (d.isoformat(),)).fetchone()


def latest_is_ours(latest, st):
    """the latest copy is still the file this script wrote (size + mtime, else sha256)"""
    if not st.get("written_sha") or not latest.exists():
        return False
    s = latest.stat()
    if [s.st_size, s.st_mtime_ns] == st.get("written_sig"):
        return True
    if sha256(latest) == st["written_sha"]:
        st["written_sig"] = [s.st_size, s.st_mtime_ns]
        return True
    return False


def try_replace(tmp, latest, st, key, ymd):
    """True when replaced; PermissionError (open in Excel): temp kept, notified once per version"""
    for i in range(3):
        try:
            os.replace(tmp, latest)
            return True
        except PermissionError:
            time.sleep(1 + i)
    if st.get("locked_notified") != key:
        say("File dang mo", f"du_bao_{ymd}.xlsx dang mo (Excel?): ban 20 ngay da san sang, se thay khi file duoc dong.")
        st["locked_notified"] = key
    log(f"{ymd}: latest copy locked, temp kept for the next pass: {tmp}")
    return False


def process_day(conn, data_dir, d, state, writer):
    ymd = d.strftime("%Y%m%d")
    days = state.setdefault("days", {})
    st = dict(days.get(ymd) or {})
    row = newest_version(conn, d)
    if not row:
        return "no export"
    rid, _, version, rel, src_sha, n_rows, created_at = row
    key = [rid, src_sha]
    base = data_dir.resolve()
    vpath = base.joinpath(*[x for x in str(rel).replace("\\", "/").split("/") if x]).resolve()
    if not vpath.is_relative_to(base) or not re.fullmatch(rf"du_bao_{ymd}_v\d+\.xlsx", vpath.name):
        raise X20Error("SOURCE_PATH_INVALID", f"export_runs path {rel!r}")
    if not vpath.exists() and vpath.with_name(vpath.stem + "_bo.xlsx").is_file():
        vpath = vpath.with_name(vpath.stem + "_bo.xlsx")    # 1.4.5 app: renamed by a newer export (read-only)
    latest = vpath.with_name(f"du_bao_{ymd}.xlsx")
    tmp = vpath.with_name(f".x20_du_bao_{ymd}.tmp")
    shown = "/".join([x for x in str(rel).replace("\\", "/").split("/") if x][:-1] + [latest.name])
    pend = st.get("pending")
    for p in vpath.parent.glob(".x20_*.tmp"):           # left by a killed pass
        try:
            if time.time() - p.stat().st_mtime > STALE_TMP_SECONDS and not (pend and p == tmp):
                p.unlink()
                log(f"{ymd}: stale temp removed: {p.name}")
        except OSError:
            pass
    if not O.force and st.get("key") == key and latest_is_ours(latest, st):
        days[ymd] = st
        return f"up to date (v{version})"
    if not O.force and (st.get("failed") or {}).get("key") == key:
        return f"v{version} failed before ({st['failed'].get('code')}): waiting for a newer version"
    if pend and pend.get("key") == key and tmp.exists() and not O.dry_run:
        if sha256(tmp) == pend.get("tmp_sha"):
            if try_replace(tmp, latest, st, key, ymd):
                finish(st, key, latest, version, pend)
                days[ymd] = st
                say("Da thay file", f"{shown}: ban 20 ngay (v{version}) da thay "
                    "sau khi file duoc dong.")
                return f"pending file replaced (v{version})"
            days[ymd] = st
            return "latest copy still locked"
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        age = SETTLE_SECONDS
    if age < SETTLE_SECONDS and not O.force:
        return f"v{version} recorded {age:.0f} s ago: next pass"
    ram, commit = mem()
    if ram < MIN_FREE_RAM_MB or commit < MIN_FREE_COMMIT_MB:
        return f"low memory (RAM {ram} MB, commit {commit} MB): next pass"
    t0 = time.time()
    if not vpath.exists():
        raise X20Error("SOURCE_MISSING", f"{vpath.name} missing")
    got = sha256(vpath)
    if src_sha and got != src_sha:
        raise X20Error("SOURCE_SHA_MISMATCH", f"{vpath.name}: sha256 differs from export_runs")
    log(f"{ymd}: source {vpath.name} (v{version}, export {rid}) -> {latest.name}")
    src = read_source(vpath, d)
    if n_rows is not None and src["n_rows"] != n_rows:
        raise X20Error("INPUT_INVALID", f"{src['n_rows']} DU_BAO rows, export_runs says {n_rows}")
    t1 = time.time()
    tmp.unlink(missing_ok=True)
    header, plan, n_summary = build(src, d, tmp, writer, vpath.name, got)
    t2 = time.time()
    try:
        verify(tmp, d, src, header, plan, n_summary)
    except Exception:
        if not O.dry_run:
            tmp.unlink(missing_ok=True)
        raise
    t3 = time.time()
    size = tmp.stat().st_size
    info = {"rows": {nm: nk * H_ALL for nm, _, nk in plan}, "sku_fc": {nm: nk for nm, _, nk in plan},
            "size": size, "layout_in": src["layout"], "writer": writer[2],
            "seconds": {"read": round(t1 - t0, 1), "write": round(t2 - t1, 1), "verify": round(t3 - t2, 1)},
            "peak_mb": peak_mb()}
    del src
    log(f"{ymd}: built + verified {json.dumps(info)}")
    if O.dry_run:
        print(json.dumps({"day": ymd, "tmp": str(tmp), **info}))
        return f"dry run: {tmp}"
    # race: the app's own latest copy of a newer version can still land after this replace; the next pass sees the
    # newer export_runs id (or a latest copy that is not ours) and writes again
    again = newest_version(conn, d)
    if again and again[0] != rid:
        tmp.unlink(missing_ok=True)
        return f"v{again[2]} recorded meanwhile: next pass"
    pend = {"key": key, "tmp_sha": sha256(tmp), **info}
    st.pop("failed", None)
    if not try_replace(tmp, latest, st, key, ymd):
        st["pending"] = pend
        days[ymd] = st
        return "latest copy locked: temp kept"
    finish(st, key, latest, version, pend)
    days[ymd] = st
    secs = round(time.time() - t0)
    say("Da tao file 20 ngay", f"{shown} (v{version}): {size / 2 ** 20:.1f} MB, "
        + ", ".join(f"{nm} {n:,} dong" for nm, n in info["rows"].items()) + f", {secs} s.")
    return f"written (v{version}, {secs} s)"


def finish(st, key, latest, version, pend):
    s = latest.stat()
    st.update(key=key, version=version, written_sha=pend["tmp_sha"], written_sig=[s.st_size, s.st_mtime_ns],
              written_at=now_vn().isoformat(timespec="seconds"),
              info={k: pend[k] for k in ("rows", "sku_fc", "size", "layout_in", "writer", "seconds", "peak_mb")})
    st.pop("pending", None)
    st.pop("locked_notified", None)


# ------------------------------------------------------------------ pass
def data_dir_default():
    if ops_config.get("data_dir", None):          # DF_OPS_DATA_DIR / ops_config.json "data_dir"
        return ops_config.get("data_dir", None)
    obj = read_json(STORAGE)
    dd = obj.get("data_dir") if isinstance(obj, dict) else None
    if not dd:
        raise X20Error("DATA_DIR_UNKNOWN", "storage.json has no data_dir")
    return Path(dd)


def run_pass(work):
    state_p = work / "state.json"
    state = read_json(state_p)
    blk = ops_lock_block(RUN_NAME)
    if blk:
        log(f"warning: {blk} (this script writes only the Excel latest copy, not the DB: it goes on)")
    data_dir = Path(O.data_dir) if O.data_dir else data_dir_default()
    db = Path(O.db) if O.db else data_dir / "db" / "app.db"
    if O.forecast_date:
        days = [date.fromisoformat(O.forecast_date)]
    else:
        today = now_vn().date()
        since = date.fromisoformat(O.since)
        days = [x for x in (today, today - timedelta(days=1)) if x >= since]
    if not days:
        return 0
    writer = None
    rc = 0
    conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    try:
        conn.execute("PRAGMA query_only = ON")
        for d in days:
            ymd = d.strftime("%Y%m%d")
            st = state.setdefault("days", {}).setdefault(ymd, {})
            try:
                if writer is None:
                    row = newest_version(conn, d)
                    if not row:
                        log(f"{ymd}: no export")
                        continue
                    writer = load_writer(O.app_backend)
                res = process_day(conn, data_dir, d, state, writer)
                log(f"{ymd}: {res}")
            except Exception as e:  # noqa: BLE001 - one day's failure never hides the other day's result
                rc = 1
                if isinstance(e, X20Error):
                    code, text = e.code, e.text
                else:
                    code, text = f"CRASH_{type(e).__name__}", str(e)[:200]
                    log(traceback.format_exc())
                try:
                    row = newest_version(conn, d)
                except Exception:  # noqa: BLE001
                    row = None
                key = [row[0], row[4]] if row else None
                st = state["days"].setdefault(ymd, {})
                log(f"{ymd}: ERROR {code}: {text}")
                if not O.dry_run:
                    # once per source version (+ code): that version is not retried until a newer one (or --force)
                    if (st.get("failed") or {}).get("key") != key or st["failed"].get("code") != code:
                        say("Loi file 20 ngay", f"du_bao_{ymd}.xlsx v{row[2] if row else '?'}: {code} "
                            f"({text[:150]}). File cua app giu nguyen.", high=True)
                    st["failed"] = {"key": key, "code": code, "at": now_vn().isoformat(timespec="seconds")}
            save_state(state_p, state)              # after EACH day: a later crash never loses this day's result
    finally:
        conn.close()
    return rc


def save_state(state_p, state):
    if O.dry_run:
        return
    cut = (now_vn().date() - timedelta(days=KEEP_DAYS)).strftime("%Y%m%d")
    state["days"] = {k: v for k, v in state.get("days", {}).items() if k >= cut and v}
    write_json(state_p, state)


def lock_stale(lock):
    """None while the pass holding the lock may still run, else why it is stale: its process is gone (pid + creation
    time: a reused pid is not taken for it) or the lock is older than STALE_LOCK_SECONDS (the task limit killed it)"""
    age = time.time() - lock.stat().st_mtime
    if age > STALE_LOCK_SECONDS:
        return f"older than {STALE_LOCK_SECONDS // 60} min"
    lk = read_json(lock)
    if not lk.get("pid"):
        return None if age < 30 else "unreadable"   # a pass that has just created it writes it next
    if not alive(lk.get("pid"), lk.get("created")):
        return f"process {lk.get('pid')} gone"
    return None


def main():
    global O, LOG
    a = argparse.ArgumentParser(description="daily Excel in the 20-day layout (latest copy only)")
    a.add_argument("--data-dir")
    a.add_argument("--db")
    a.add_argument("--work-dir", default=str(ops_config.REPORTS / "excel20"))
    a.add_argument("--app-backend")
    a.add_argument("--since", default=EFFECTIVE_FROM)
    a.add_argument("--forecast-date")
    a.add_argument("--now")
    a.add_argument("--force", action="store_true")
    a.add_argument("--dry-run", action="store_true")
    O = a.parse_args()
    work = Path(O.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    LOG = work / "excel20.log"
    lock = work / "excel20.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            why = lock_stale(lock)
            if not why:
                return 0                    # another pass runs
            lock.unlink(missing_ok=True)
            log(f"stale lock removed ({why})")
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return 0
    try:
        os.write(fd, json.dumps({"pid": os.getpid(), "created": proc_created(os.getpid())}).encode())
        os.close(fd)
        return run_pass(work)
    except Exception as e:  # noqa: BLE001
        log(f"CRASH {type(e).__name__}: {e}\n{traceback.format_exc()}")
        day = now_vn().strftime("%Y%m%d")
        st = read_json(work / "crash.json")
        if not O.dry_run and st.get(day) != type(e).__name__:
            say("Loi script", f"excel20.py: {type(e).__name__}", high=True)
            write_json(work / "crash.json", {day: type(e).__name__})
        return 1
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
