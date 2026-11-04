"""1.3.1 daily forecast refresh, B9: the accuracy report (docs/ke_hoach_lgbm_chot.md 1, 6.4).

A cell = one SKU x FC x target day x horizon h of the LATEST published refresh run of each forecast day (created_at
DESC, rowid DESC) of the ACTIVE data scope, with the actual of the SAME day (actual_daily). Only open days count
(actual_daily.total_open_hours > 0; a closed day or unknown hours is not evaluated) and only closed target days
(target_date <= business day - 1). demand NULL of an open day is 0 (actual_daily stores 0 for an open day without an
order). Views: D1 = horizon 1, D7 = horizons 1..7 pooled (h > 7 ignored); period = month of the target day + TOTAL.

Category (classify_cells): dev = final_qty - demand; tolerance 1 for group C, 3 otherwise (no group = B);
  DUNG when |dev| <= tolerance or (demand > 0 and |dev| / demand <= 0.20);
  otherwise ratio = |dev| / demand (infinite when demand = 0): IT when <= 0.50, NHIEU above; DU when dev > 0, THIEU
  when dev < 0.
Tables (per view and period, columns A / B / C / TOTAL): slots = distinct (target day, h) pairs with a cell;
sku_per_day = cells / slots; sku_share = cells / cells of the column; qty_dev = sum |dev|; demand = sum demand of the
column; qty_dev_share = sum |dev| / demand of the column. An empty group / category is 0 (never NaN).
aggregate() / combine() / tables_from_aggregates() work chunk by chunk (one forecast day at a time in run()): the
cells are never all in memory; build_tables(cells) = tables_from_aggregates(*aggregate(cells)).

run() writes ONE accuracy_report_runs row and the workbook <reports_dir>/<daily_forecast.report_subdir>/
bao-cao-do-chinh-xac-<YYYYMMDD-HHMMSS Vietnam>.xlsx (never overwritten: -2, -3, ...). A file error leaves the run DONE
with report_path NULL, the error and ONE WARNING alert ACCURACY_REPORT_NOT_WRITTEN (the computed summary is kept).
Every other table is only read.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .. import db, paths
from .. import settings_service as ss
from ..data.demand import resolve_scope
from ..messages import AppError
from ..timeutil import now_iso, now_vn, today_vn

log = logging.getLogger("df.accuracy")

CATEGORIES = ("DUNG", "DU_NHIEU", "DU_IT", "THIEU_NHIEU", "THIEU_IT")
CATEGORY_LABEL = {"DUNG": "Đúng với demand", "DU_NHIEU": "Dư nhiều", "DU_IT": "Dư ít", "THIEU_NHIEU": "Thiếu nhiều",
                  "THIEU_IT": "Thiếu ít"}
GROUPS = ("A", "B", "C")
COLUMNS = GROUPS + ("TOTAL",)
VIEWS = ("D1", "D7")
TOTAL = "TOTAL"
TOLERANCE_C = 1                 # units, group C
TOLERANCE = 3                   # units, groups A / B (and no group)
OK_RATIO = 0.20                 # DUNG up to this |dev| / demand
SMALL_RATIO = 0.50              # IT up to this |dev| / demand, NHIEU above
MAX_HORIZON = 7                 # D7 = horizons 1..7
TRIAL_LABEL = "Chạy thử – chưa dùng để mua hàng"
FILE_PREFIX = "bao-cao-do-chinh-xac-"
SCHEDULED_TRIGGERS = ("SCHEDULE", "CATCH_UP", "RETRY")
SCHEDULED, MANUAL = "SCHEDULED", "MANUAL"
FAILED_CODE = "ACCURACY_REPORT_FAILED"
NOT_WRITTEN = "ACCURACY_REPORT_NOT_WRITTEN"

_CAT_OBJ = np.array(CATEGORIES, dtype=object)
_AGG_COLS = ["view", "period", "group_code", "category", "cells", "qty_dev", "demand"]
_SLOT_COLS = ["view", "period", "slots"]


def _day(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


# ------------------------------------------------------------------ pure part
def _group_index(group) -> np.ndarray:
    """0 / 1 / 2 for A / B / C; anything else (no group) is B (rule B7: B = the rest)."""
    g = np.asarray(group, dtype=object)
    return np.where(g == "A", 0, np.where(g == "C", 2, 1)).astype(np.int8)


def _category_index(final_qty, demand, gidx: np.ndarray) -> np.ndarray:
    f = np.asarray(final_qty, dtype=float)
    d = np.asarray(demand, dtype=float)
    if not (np.isfinite(f).all() and np.isfinite(d).all()):
        raise ValueError("final_qty and demand must be finite numbers (a missing value is never classified)")
    dev = f - d
    a = np.abs(dev)
    tol = np.where(gidx == 2, TOLERANCE_C, TOLERANCE)
    pos = d > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(pos, a / np.where(pos, d, 1.0), np.inf)
    ok = (a <= tol) | (pos & (ratio <= OK_RATIO))
    small = ratio <= SMALL_RATIO
    code = np.where(dev > 0, np.where(small, 2, 1), np.where(small, 4, 3))
    return np.where(ok, 0, code).astype(np.int8)


def classify_cells(final_qty, demand, group) -> np.ndarray:
    """Category of every cell (object array of CATEGORIES); rule in the module docstring."""
    gidx = _group_index(group)
    return _CAT_OBJ[_category_index(final_qty, demand, gidx)]


def _empty() -> tuple[pd.DataFrame, pd.DataFrame]:
    return pd.DataFrame(columns=_AGG_COLS), pd.DataFrame(columns=_SLOT_COLS)


def aggregate(cells: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sums of one chunk of cells (columns target_date, horizon, group_code, final_qty, demand; others ignored).

    agg: view ("D1" / "D7"), period ("YYYY-MM" of target_date), group_code ("A" / "B" / "C"; a missing or unknown
    group is counted in "B", rule B7: B = the rest), category, cells, qty_dev (sum |dev|), demand (sum); only
    non-empty combinations. slots: view, period, slots (distinct (target_date, horizon) pairs). Rows with a horizon
    outside 1..7 are ignored. Vectorised; the input frame is not kept."""
    if cells is None or len(cells) == 0:
        return _empty()
    h = cells["horizon"].to_numpy(dtype=np.int64)
    keep = (h >= 1) & (h <= MAX_HORIZON)
    if not keep.any():
        return _empty()
    h = h[keep]
    tcode, tuniq = pd.factorize(cells["target_date"].to_numpy()[keep])
    if (tcode < 0).any():
        raise ValueError("target_date must be set for every cell")
    tper = np.array([str(t)[:7] for t in tuniq], dtype=object)
    pcode_of_t, periods = pd.factorize(tper)
    pcode = pcode_of_t[tcode]
    gidx = _group_index(cells["group_code"].to_numpy()[keep])
    final = cells["final_qty"].to_numpy(dtype=float)[keep]
    demand = cells["demand"].to_numpy(dtype=float)[keep]
    cat = _category_index(final, demand, gidx)
    absdev = np.abs(final - demand)
    n_per = len(periods)
    key = (pcode.astype(np.int64) * len(GROUPS) + gidx) * len(CATEGORIES) + cat
    size = n_per * len(GROUPS) * len(CATEGORIES)
    # slot key (target_date, horizon): one per distinct pair; its period follows the target date
    skey = np.unique(tcode.astype(np.int64) * (MAX_HORIZON + 1) + h)
    s_t, s_h = skey // (MAX_HORIZON + 1), skey % (MAX_HORIZON + 1)
    s_per = pcode_of_t[s_t]
    agg_parts, slot_parts = [], []
    for view, m, sm in (("D1", h == 1, s_h == 1), ("D7", None, None)):
        k = key if m is None else key[m]
        n = np.bincount(k, minlength=size)
        dv = np.bincount(k, weights=absdev if m is None else absdev[m], minlength=size)
        dm = np.bincount(k, weights=demand if m is None else demand[m], minlength=size)
        nz = np.nonzero(n)[0]
        if len(nz):
            agg_parts.append(pd.DataFrame({
                "view": view, "period": periods[nz // (len(GROUPS) * len(CATEGORIES))],
                "group_code": np.array(GROUPS, dtype=object)[(nz // len(CATEGORIES)) % len(GROUPS)],
                "category": _CAT_OBJ[nz % len(CATEGORIES)], "cells": n[nz].astype(np.int64),
                "qty_dev": dv[nz], "demand": dm[nz]}))
        sc = np.bincount(s_per if sm is None else s_per[sm], minlength=n_per)
        snz = np.nonzero(sc)[0]
        if len(snz):
            slot_parts.append(pd.DataFrame({"view": view, "period": periods[snz], "slots": sc[snz].astype(np.int64)}))
    agg = pd.concat(agg_parts, ignore_index=True) if agg_parts else _empty()[0]
    slots = pd.concat(slot_parts, ignore_index=True) if slot_parts else _empty()[1]
    return agg, slots


def combine(pairs) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sum of several (agg, slots) pairs. A slot (target_date, h) belongs to one forecast day only, so chunks cut by
    forecast day add up."""
    pairs = list(pairs)
    aggs = [a for a, _ in pairs if a is not None and len(a)]
    sls = [s for _, s in pairs if s is not None and len(s)]
    agg = (pd.concat(aggs, ignore_index=True).groupby(["view", "period", "group_code", "category"], as_index=False)
           [["cells", "qty_dev", "demand"]].sum()) if aggs else _empty()[0]
    slots = (pd.concat(sls, ignore_index=True).groupby(["view", "period"], as_index=False)[["slots"]].sum()
             ) if sls else _empty()[1]
    return agg, slots


def _entry(period: str, n_slots: int, sub: pd.DataFrame) -> dict:
    ci = {c: i for i, c in enumerate(CATEGORIES)}
    gi = {g: i for i, g in enumerate(GROUPS)}
    n = np.zeros((len(CATEGORIES), len(COLUMNS)))
    dev = np.zeros((len(CATEGORIES), len(COLUMNS)))
    dem = np.zeros(len(COLUMNS))
    for r in sub.itertuples(index=False):
        i, j = ci[r.category], gi[r.group_code]
        n[i, j] += r.cells
        dev[i, j] += r.qty_dev
        dem[j] += r.demand
    n[:, 3], dev[:, 3], dem[3] = n[:, :3].sum(axis=1), dev[:, :3].sum(axis=1), dem[:3].sum()
    n_col, dev_col = n.sum(axis=0), dev.sum(axis=0)

    def ratio(x, y):
        return float(x / y) if y > 0 else 0.0

    per_day = {c: {col: ratio(n[i, j], n_slots) for j, col in enumerate(COLUMNS)} for c, i in ci.items()}
    share = {c: {col: ratio(n[i, j], n_col[j]) for j, col in enumerate(COLUMNS)} for c, i in ci.items()}
    qdev = {c: {col: float(dev[i, j]) for j, col in enumerate(COLUMNS)} for c, i in ci.items()}
    qdev[TOTAL] = {col: float(dev_col[j]) for j, col in enumerate(COLUMNS)}
    qshare = {c: {col: ratio(dev[i, j], dem[j]) for j, col in enumerate(COLUMNS)} for c, i in ci.items()}
    qshare[TOTAL] = {col: ratio(dev_col[j], dem[j]) for j, col in enumerate(COLUMNS)}
    return {"period": period, "slots": int(n_slots), "sku_per_day": per_day, "sku_share": share, "qty_dev": qdev,
            "demand": {col: float(dem[j]) for j, col in enumerate(COLUMNS)}, "qty_dev_share": qshare}


def tables_from_aggregates(agg: pd.DataFrame, slots: pd.DataFrame) -> dict:
    """{"D1": [...], "D7": [...]}: one entry per month (ascending) then "TOTAL" (all months pooled; TOTAL slots = sum
    of the month slots). Without any cell a view has only its (zero) TOTAL entry."""
    out = {}
    for view in VIEWS:
        a = agg[agg["view"] == view] if len(agg) else agg
        s = slots[slots["view"] == view] if len(slots) else slots
        periods = sorted(set(a["period"]) | set(s["period"]))
        entries = []
        for p in periods:
            entries.append(_entry(p, int(s.loc[s["period"] == p, "slots"].sum()), a[a["period"] == p]))
        entries.append(_entry(TOTAL, int(s["slots"].sum()) if len(s) else 0, a))
        out[view] = entries
    return out


def build_tables(cells: pd.DataFrame) -> dict:
    return tables_from_aggregates(*aggregate(cells))


# ------------------------------------------------------------------ workbook
SHEET_INFO, SHEET_D1, SHEET_D7 = "Thông tin", "Ngày thứ 1", "7 ngày"
_HEADER = ("Loại", "A", "B", "C", "Tổng 3 nhóm")
_FMT_DAY, _FMT_PCT, _FMT_QTY = "#,##0.0", "0.0%", "#,##0"

DEFINITIONS = [
    ("Ô (dòng được đánh giá)", "Một SKU × FC × ngày đích × ngày thứ h, lấy từ lần làm mới PUBLISHED mới nhất của "
                               "mỗi ngày dự báo (phạm vi dữ liệu đang dùng)."),
    ("Chỉ ngày mở bán", "Chỉ tính ngày đích có tổng giờ mở bán > 0; ngày đóng hoặc chưa biết giờ mở bán không tính. "
                        "Chỉ tính ngày đích đã đóng (trước ngày chạy)."),
    ("Demand thực", "Demand thực của đúng ngày đích đó; ngày mở bán không có đơn = 0."),
    ("Lệch", "Lệch = số dự báo công bố (số nguyên) − demand thực."),
    ("Dung sai", f"{TOLERANCE_C} đơn vị với nhóm C; {TOLERANCE} đơn vị với nhóm A, B."),
    ("Đúng với demand", "|lệch| ≤ dung sai, hoặc demand > 0 và |lệch| / demand ≤ 20 %."),
    ("Ít / Nhiều", "Còn lại: tỷ lệ = |lệch| / demand (vô cùng khi demand = 0); Ít khi ≤ 50 %, Nhiều khi > 50 %."),
    ("Dư / Thiếu", "Dư khi lệch > 0 (dự báo cao hơn), Thiếu khi lệch < 0 (dự báo thấp hơn)."),
    ("Nhóm A / B / C", "Nhóm của chuỗi ghi cùng lần làm mới (90 ngày tới D-1, chỉ ngày mở bán): A khi bình quân/ngày "
                       "mở bán > 20 và tỷ lệ ngày demand 0 ≤ 20 %; C khi bình quân ≤ 5 và tỷ lệ ngày demand 0 > 20 %; "
                       "còn lại (và chuỗi không có nhóm) là B."),
    ("Ngày thứ 1", "h = 1: dự báo cho chính ngày dự báo."),
    ("7 ngày", "h = 1..7 gộp lại."),
    ("Slot", "Một cặp (ngày đích, h) có ít nhất một ô trong kỳ. Số SKU bình quân/ngày = số ô / số slot."),
    ("Tỷ trọng SKU", "Số ô của loại / tổng số ô của cột (mỗi cột cộng 100 %)."),
    ("Qty lệch", "Σ|lệch| của loại; Qty lệch / tổng demand = Σ|lệch| / Σ demand thực của cột."),
    ("Kỳ", "Tháng theo ngày đích; 'Cả kỳ' = mọi tháng gộp lại."),
]


def _trial(meta: dict) -> bool:
    if "trial_mode" in meta:
        return bool(meta["trial_mode"])
    try:
        return bool(ss.get("daily_forecast").trial_mode)
    except Exception:  # noqa: BLE001 - no database (e.g. a reproduction): show the label rather than hide it
        return True


def write_workbook(tables: dict, path, meta: dict | None = None) -> Path:
    """Write the report to `path` (exclusive create: an existing file is never overwritten, FileExistsError).
    Plain values only (no formula). meta: trial_mode, title, scope, run_date, generated_at, period_start,
    period_end, n_runs, n_cells_d1, n_cells_d7, report_run_id (all optional)."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font

    meta = dict(meta or {})
    wb = Workbook(write_only=True)
    bold = Font(bold=True)

    def cell(ws, value, fmt=None, strong=False):
        c = WriteOnlyCell(ws, value=value)
        if fmt:
            c.number_format = fmt
        if strong:
            c.font = bold
        return c

    info = wb.create_sheet(SHEET_INFO)
    info.column_dimensions["A"].width = 34
    info.column_dimensions["B"].width = 110
    if _trial(meta):
        info.append([cell(info, TRIAL_LABEL, strong=True)])
    ps, pe = meta.get("period_start"), meta.get("period_end")
    rows = [("Báo cáo", meta.get("title") or "Báo cáo độ chính xác dự báo làm mới (LightGBM)"),
            ("Phạm vi dữ liệu", meta.get("scope") or ""),
            ("Ngày chạy", str(meta.get("run_date") or "")),
            ("Thời điểm lập (giờ Việt Nam)", str(meta.get("generated_at") or "")),
            ("Kỳ báo cáo (ngày đích)", f"{ps} → {pe}" if ps else "(chưa có ngày đích nào đánh giá được)"),
            ("Số lần làm mới đã dùng", meta.get("n_runs", 0)),
            ("Số ô ngày thứ 1", meta.get("n_cells_d1", 0)),
            ("Số ô 7 ngày", meta.get("n_cells_d7", 0)),
            ("Mã lần chạy báo cáo", meta.get("report_run_id") or "")]
    for k, v in rows:
        info.append([cell(info, k, strong=True), cell(info, v)])
    info.append([])
    info.append([cell(info, "Định nghĩa", strong=True)])
    for k, v in DEFINITIONS:
        info.append([cell(info, k, strong=True), cell(info, v)])

    for sheet, view in ((SHEET_D1, "D1"), (SHEET_D7, "D7")):
        ws = wb.create_sheet(sheet)
        ws.column_dimensions["A"].width = 26
        for col in "BCDE":
            ws.column_dimensions[col].width = 16
        for e in tables.get(view) or []:
            label = "Cả kỳ" if e["period"] == TOTAL else f"Tháng {e['period']}"
            ws.append([cell(ws, f"Kỳ: {label} — {e['slots']} slot (ngày đích × h)", strong=True)])

            def block(title, table, fmt, extra=()):
                ws.append([cell(ws, title, strong=True)])
                ws.append([cell(ws, h, strong=True) for h in _HEADER])
                for c in CATEGORIES:
                    ws.append([cell(ws, CATEGORY_LABEL[c])] + [cell(ws, table[c][col], fmt) for col in COLUMNS])
                for name, values, f in extra:
                    ws.append([cell(ws, name, strong=True)] + [cell(ws, values[col], f, True) for col in COLUMNS])
                ws.append([])

            block("(1) Số SKU bình quân/ngày", e["sku_per_day"], _FMT_DAY)
            block("(2) Tỷ trọng SKU", e["sku_share"], _FMT_PCT)
            block("(3) Qty lệch", e["qty_dev"], _FMT_QTY,
                  (("Tổng", e["qty_dev"][TOTAL], _FMT_QTY), ("Tổng demand thực", e["demand"], _FMT_QTY)))
            block("(4) Qty lệch / tổng demand", e["qty_dev_share"], _FMT_PCT,
                  (("Tổng", e["qty_dev_share"][TOTAL], _FMT_PCT),))
            ws.append([])
    buf = io.BytesIO()
    wb.save(buf)
    p = Path(path)
    with open(p, "xb") as f:
        f.write(buf.getvalue())
    return p


def report_dir(cfg) -> Path:
    return paths.reports_dir() / cfg.report_subdir


def write_report(folder: Path, stem: str, tables: dict, meta: dict) -> Path:
    """<folder>/<stem>.xlsx; an existing file is never overwritten (-2, -3, ... added)."""
    folder.mkdir(parents=True, exist_ok=True)
    k = 1
    while True:
        p = folder / (f"{stem}.xlsx" if k == 1 else f"{stem}-{k}.xlsx")
        try:
            return write_workbook(tables, p, meta)
        except FileExistsError:
            k += 1


# ------------------------------------------------------------------ loading
_LATEST = ("SELECT id FROM forecast_refresh_runs WHERE scope_key=? AND status='PUBLISHED' AND forecast_date=? "
           "ORDER BY created_at DESC, rowid DESC LIMIT 1")
# values of one run with the actual of the same day; open days only (hours > 0), closed target days only
_CELLS = ("SELECT v.target_date, v.horizon, v.group_code, v.final_qty, COALESCE(a.demand, 0) AS demand "
          "FROM forecast_refresh_values v JOIN actual_daily a ON a.scope_key = ? AND a.date = v.target_date "
          "AND a.fc_code = v.fc_code AND a.sku_code = v.sku_code "
          "WHERE v.run_id = ? AND v.horizon BETWEEN 1 AND ? AND v.target_date <= ? AND a.total_open_hours > 0")


def evaluate(conn, scope_key: str, last_day: date, since: date | None = None) -> dict:
    """Aggregates of every forecast day of the scope from `since` (None = the first) up to last_day (its latest
    published run), one day at a time."""
    days = [r[0] for r in conn.execute(
        "SELECT DISTINCT forecast_date FROM forecast_refresh_runs WHERE scope_key=? AND status='PUBLISHED' "
        "AND forecast_date <= ? AND forecast_date >= ? ORDER BY forecast_date",
        (scope_key, str(last_day), str(since or ""))).fetchall()]
    total = _empty()
    n_runs, ps, pe = 0, None, None
    for fd in days:
        rid = conn.execute(_LATEST, (scope_key, fd)).fetchone()[0]
        cells = pd.read_sql_query(_CELLS, conn, params=(scope_key, rid, MAX_HORIZON, str(last_day)))
        if cells.empty:
            continue
        n_runs += 1
        lo, hi = str(cells["target_date"].min()), str(cells["target_date"].max())
        ps = lo if ps is None or lo < ps else ps
        pe = hi if pe is None or hi > pe else pe
        total = combine([total, aggregate(cells)])
        del cells
    agg = total[0]
    n = {v: int(agg.loc[agg["view"] == v, "cells"].sum()) if len(agg) else 0 for v in VIEWS}
    return {"agg": agg, "slots": total[1], "n_runs": n_runs, "period_start": ps, "period_end": pe,
            "n_cells_d1": n["D1"], "n_cells_d7": n["D7"]}


# ------------------------------------------------------------------ the job
def run(business_date=None, job_id: str | None = None, trigger: str = "SCHEDULE", progress=None) -> dict:
    """status DONE (reason ACCURACY_REPORT_WRITTEN / ACCURACY_REPORT_NOT_WRITTEN / ACCURACY_REPORT_NO_DATA) | SKIPPED
    (DAILY_FORECAST_DISABLED, or the code of a missing active data scope) | FAILED."""
    d = _day(business_date) if business_date else today_vn()
    stage = progress or (lambda *a, **k: None)
    cfg = ss.get("daily_forecast")
    if not cfg.enabled:
        return {"status": "SKIPPED", "reason_code": "DAILY_FORECAST_DISABLED", "business_date": str(d)}
    kind = SCHEDULED if trigger in SCHEDULED_TRIGGERS else MANUAL
    stage("VALIDATING_DATA")
    try:
        scope = resolve_scope()
    except AppError as e:
        return {"status": "SKIPPED", "reason_code": e.code, "detail": e.detail, "business_date": str(d)}
    run_id = db.new_id("ARR")
    try:
        return _report(d, cfg, scope, run_id, job_id, kind, stage)
    except Exception as e:  # noqa: BLE001 - reported as a failed run (one FAILED row, best effort)
        code = e.code if isinstance(e, AppError) else FAILED_CODE
        detail = ((e.detail if isinstance(e, AppError) else None) or f"{type(e).__name__}: {e}")[:2000]
        log.exception("accuracy report failed", extra={"ctx": {"business_date": str(d), "code": code}})
        rid = None
        try:
            with db.tx() as c:
                if db.one(c, "SELECT id FROM accuracy_report_runs WHERE id=?", (run_id,)) is None:
                    c.execute("INSERT INTO accuracy_report_runs(id, scope_key, run_kind, run_date, status, error, "
                              "job_id, created_at) VALUES (?,?,?,?, 'FAILED', ?,?,?)",
                              (run_id, scope["scope_key"], kind, str(d), detail, job_id, now_iso()))
            rid = run_id
        except Exception:  # noqa: BLE001 - the log line above stays
            log.exception("accuracy report failure not recorded")
        return {"status": "FAILED", "reason_code": code, "error": detail, "business_date": str(d),
                "report_run_id": rid, "report_path": None, "run_kind": kind}


def _report(d: date, cfg, scope: dict, run_id: str, job_id, kind: str, stage) -> dict:
    sk = scope["scope_key"]
    stage("EVALUATING")
    with db.read() as c:        # forecast days older than the log retention have no values left: not evaluated
        ev = evaluate(c, sk, d - timedelta(days=1), since=d - timedelta(days=int(cfg.log_retention_days)))
    tables = tables_from_aggregates(ev["agg"], ev["slots"])
    summary = {v: tables[v][-1] for v in VIEWS}          # the TOTAL entries
    no_data = ev["n_cells_d7"] == 0

    stage("REPORTING")
    with db.tx() as c:
        c.execute("INSERT INTO accuracy_report_runs(id, scope_key, run_kind, run_date, period_start, period_end, "
                  "n_cells, status, summary_json, report_path, error, job_id, created_at) "
                  "VALUES (?,?,?,?,?,?,?, 'DONE', ?, NULL, NULL, ?, ?)",
                  (run_id, sk, kind, str(d), ev["period_start"], ev["period_end"], ev["n_cells_d7"],
                   json.dumps(summary), job_id, now_iso()))

    # the run is committed above: a failure while building or writing the file leaves it DONE with report_path NULL,
    # the error and one WARNING alert, never FAILED
    now = now_vn()
    meta = {"trial_mode": cfg.trial_mode, "scope": scope.get("label") or sk, "run_date": str(d),
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"), "period_start": ev["period_start"],
            "period_end": ev["period_end"], "n_runs": ev["n_runs"], "n_cells_d1": ev["n_cells_d1"],
            "n_cells_d7": ev["n_cells_d7"], "report_run_id": run_id}
    report_path, error = None, None
    try:
        path = str(write_report(report_dir(cfg), f"{FILE_PREFIX}{now.strftime('%Y%m%d-%H%M%S')}", tables, meta))
        with db.tx() as c:
            c.execute("UPDATE accuracy_report_runs SET report_path=? WHERE id=?", (path, run_id))
        report_path = path
    except Exception as e:  # noqa: BLE001 - see above
        error = f"{type(e).__name__}: {e}"[:500]
        log.warning("accuracy report not written", extra={"ctx": {"report_run_id": run_id, "error": error}})
        try:
            with db.tx() as c:
                c.execute("UPDATE accuracy_report_runs SET error=? WHERE id=?", (error, run_id))
                db.alert(c, "WARNING", NOT_WRITTEN, {"report_run_id": run_id, "error": error},
                         "accuracy_report_run", run_id)
        except Exception:  # noqa: BLE001 - the alert is best effort; the log line above stays
            log.exception("accuracy report alert not written")
    reason = "ACCURACY_REPORT_NO_DATA" if no_data else (NOT_WRITTEN if error else "ACCURACY_REPORT_WRITTEN")
    log.info("accuracy report done", extra={"ctx": {"report_run_id": run_id, "business_date": str(d),
                                                    "n_cells": ev["n_cells_d7"], "written": report_path is not None}})
    out = {"status": "DONE", "reason_code": reason, "report_run_id": run_id, "report_path": report_path,
           "period_start": ev["period_start"], "period_end": ev["period_end"], "n_cells_d1": ev["n_cells_d1"],
           "n_cells_d7": ev["n_cells_d7"], "summary": summary, "business_date": str(d), "run_kind": kind}
    if error:
        out["error"] = error
    return out
