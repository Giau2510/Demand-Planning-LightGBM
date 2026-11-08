"""1.3.1 "LightGBM chốt" (docs/ke_hoach_lgbm_chot.md): the daily forecast refresh (status, runs, values, export, manual
refresh, confirmed trial-mode switch), the accuracy reports (B9), the feature table (B11) and the feature importance of a
training run (B10).

Every GET is read-only and shows the active data scope only (no usable scope: nothing, never another scope's rows). The
state changes are the POST / PUT below, guarded by the X-DF-Client header like every other state change
(security.LocalGuardMiddleware). The trial mode and the feature table change only here: the generic
PUT /api/settings/{section} refuses both (api/data_routes.py).
"""
from __future__ import annotations

import io
import json
import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response
from openpyxl import Workbook
from pydantic import BaseModel, ValidationError

from .. import db, paths
from .. import settings_service as ss
from ..bq import product_names
from ..data import intraday, open_hours
from ..data.demand import resolve_scope
from ..messages import AppError
from ..ml import accuracy_report, feature_registry, feature_report, features
from ..ml.pipeline import feature_table_snapshot
from ..ml.sel2 import export
from ..timeutil import VN_TZ, iso, now_iso, now_vn, parse_iso, today_vn, vn_slot
from . import background, sel2_view

router = APIRouter(prefix="/api")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PAGE = 100
EXPORT_CHUNK = 5000     # rows fetched from the cursor per step of the export
GROUPS = ("A", "B", "C")
TRIAL_LABEL = {"vi": accuracy_report.TRIAL_LABEL, "en": "Trial run – not yet used for purchasing"}
FINGERPRINT_NOTE = {"vi": "Thay đổi làm đổi fingerprint và chỉ có hiệu lực ở lần huấn luyện sau",
                    "en": "A change alters the configuration fingerprint and takes effect only at the next training"}
PUBLISH_RULE = "0 nếu giá trị LightGBM (6 chữ số) < ngưỡng, ngược lại làm tròn lên"
RUN_COLS = ("id, forecast_date, data_as_of, created_at, model_version, training_run_id, n_series, n_lightgbm, "
            "n_fallback, horizon, config_version, trial_mode, trigger")
VALUE_COLS = ("target_date", "horizon", "fc_code", "sku_code", "group_code", "lgb_raw", "final_qty", "method", "flags")
REPORT_COLS = "id, run_kind, run_date, period_start, period_end, n_cells, status, report_path, error, created_at"


def _trial_label(dcfg) -> dict | None:
    """The trial label is shown only while the daily forecast is on and in trial mode."""
    return TRIAL_LABEL if dcfg.enabled and dcfg.trial_mode else None


def _date(v: str | None, name: str) -> str | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise AppError("VALIDATION_ERROR", 422, detail=f"{name}: YYYY-MM-DD expected") from None


def _scope(c) -> dict | None:
    """Active data scope (None = no usable scope: nothing is shown)."""
    try:
        return resolve_scope(c)
    except AppError:
        return None


def _vn(ts: str | None) -> str | None:
    """UTC timestamp -> Vietnam time 'YYYY-MM-DD HH:MM:SS'."""
    dt = parse_iso(ts)
    return dt.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M:%S") if dt else None


def _dmy(d: str | None) -> str:
    return date.fromisoformat(d).strftime("%d/%m/%Y") if d else ""


def _run_row(r: dict | None) -> dict | None:
    if r is not None:
        r["trial_mode"] = bool(r["trial_mode"])
    return r


def _find_run(c, scope_key: str | None, run_id: str | None = None, forecast_date: str | None = None) -> dict | None:
    """PUBLISHED refresh run of the scope: the given id, else the latest of forecast_date, else the latest of all."""
    if scope_key is None:
        return None
    base = f"SELECT {RUN_COLS} FROM forecast_refresh_runs WHERE scope_key=? AND status='PUBLISHED'"
    if run_id:
        return _run_row(db.one(c, base + " AND id=?", (scope_key, run_id)))
    if forecast_date:
        return _run_row(db.one(c, base + " AND forecast_date=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                               (scope_key, forecast_date)))
    return _run_row(db.one(c, base + " ORDER BY forecast_date DESC, created_at DESC, rowid DESC LIMIT 1",
                           (scope_key,)))


def _report_row(r: dict | None, with_error: bool = True) -> dict | None:
    """Accuracy report run as shown: the file name only, never the full path."""
    if r is None:
        return None
    p = r.pop("report_path", None)
    r["report_path_name"] = Path(p).name if p else None
    if not with_error:
        r.pop("error", None)
    return r


def _names(c, scope: dict | None) -> dict[str, str]:
    """SKU -> product name (dim_sku, read from BigQuery); BIGQUERY scopes only (DEMO / Excel SKUs are not its SKUs)."""
    return product_names.names(c) if scope and scope["data_source"] == "BIGQUERY" else {}


# ------------------------------------------------------------------ daily forecast refresh
@router.get("/daily-forecast/status")
def daily_status():
    dcfg = ss.get("daily_forecast")
    sched = ss.get("schedule")
    today = today_vn()
    now = now_vn()
    deadline = vn_slot(today, sched.refresh_deadline)
    since = parse_iso(sched.refresh_enabled_at)
    with db.read() as c:
        scope = _scope(c)
        sk = scope["scope_key"] if scope else None
        source = ss.get("general", c).active_source
        last = _find_run(c, sk)
        today_run = sk is not None and db.one(
            c, "SELECT id FROM forecast_refresh_runs WHERE scope_key=? AND forecast_date=? AND status='PUBLISHED' "
               "LIMIT 1", (sk, today.isoformat())) is not None
        report = None
        if sk is not None:
            report = _report_row(db.one(c, f"SELECT {REPORT_COLS} FROM accuracy_report_runs WHERE scope_key=? "
                                           "ORDER BY created_at DESC, rowid DESC LIMIT 1", (sk,)), with_error=False)
        # the same rule as the scheduler's STALE_FORECAST verdict (scheduler._plan_refresh): daily forecast ON, refresh
        # ON (and on before today's deadline), BIGQUERY with a usable scope, past the deadline, no PUBLISHED refresh of
        # that scope today and no attempt of today still PENDING / RUNNING (the verdict waits for its end)
        stale = bool(dcfg.enabled and sched.refresh_enabled and (since is None or since <= deadline)
                     and source == "BIGQUERY" and sk is not None and now > deadline and not today_run)
        if stale:
            from ..jobs.flows import _vn_day_start_utc
            stale = db.one(c, "SELECT id FROM job_runs WHERE job_type='FORECAST_REFRESH' AND created_at>=? "
                              "AND status IN ('PENDING', 'RUNNING') LIMIT 1", (_vn_day_start_utc(now),)) is None
    made_on = parse_iso(last["created_at"]).astimezone(VN_TZ).date().isoformat() if last else None
    data_to = last["data_as_of"] if last else None
    message = None
    if last:
        message = {"vi": f"Số dự báo lập ngày {_dmy(made_on)}, dữ liệu đến ngày {_dmy(data_to)}",
                   "en": f"Forecast made on {_dmy(made_on)}, data up to {_dmy(data_to)}"}
    return {"enabled": dcfg.enabled, "trial_mode": dcfg.trial_mode, "trial_label": _trial_label(dcfg),
            "refresh_enabled": sched.refresh_enabled, "refresh_deadline": sched.refresh_deadline,
            "today": today.isoformat(), "last_run": last, "made_on": made_on, "data_to": data_to, "message": message,
            "stale": stale, "stale_code": "STALE_FORECAST" if stale else None,
            "stale_since": iso(deadline) if stale else None,
            # an existing run of an earlier day (no run at all is not "outdated": there is nothing yet)
            "outdated": bool(last and last["forecast_date"] != today.isoformat()),
            "last_report": report, "trial_confirm_text": f"TAT-CHAY-THU-{today.isoformat()}"}


@router.get("/daily-forecast/runs")
def daily_runs(limit: int = Query(30, ge=1, le=200)):
    with db.read() as c:
        scope = _scope(c)
        if scope is None:
            return []
        return [_run_row(r) for r in db.rows(
            c, f"SELECT {RUN_COLS} FROM forecast_refresh_runs WHERE scope_key=? AND status='PUBLISHED' "
               "ORDER BY forecast_date DESC, created_at DESC, rowid DESC LIMIT ?", (scope["scope_key"], limit))]


def _filters(run_id: str, horizon: int | None, group: str | None, q: str | None, date_from: str | None = None,
             date_to: str | None = None) -> tuple[str, list]:
    where, params = ["run_id=?"], [run_id]
    if horizon is not None:
        where.append("horizon=?")
        params.append(horizon)
    if date_from:
        where.append("target_date>=?")
        params.append(date_from)
    if date_to:
        where.append("target_date<=?")
        params.append(date_to)
    if group:
        where.append("group_code=?")
        params.append(group)
    q = (q or "").strip()
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(sku_code LIKE ? ESCAPE '\\' OR fc_code LIKE ? ESCAPE '\\')")
        params += [like, like]
    return " AND ".join(where), params


def _value_row(run: dict, r, names: dict) -> dict:
    return {"forecast_date": run["forecast_date"], "target_date": r["target_date"], "horizon": r["horizon"],
            "fc_code": r["fc_code"], "sku_code": r["sku_code"], "product_name": names.get(r["sku_code"]),
            "group_code": r["group_code"], "lgb_raw": r["lgb_raw"], "final_qty": r["final_qty"], "method": r["method"],
            "flags": r["flags"]}


def _sel2_value_row(r: dict) -> dict:
    """An export row with the field names of the page (final_qty = forecast_used, lgb_raw = raw_value, method =
    model_used, group_code = nhom) and the columns of the Excel."""
    return {**r, "product_name": r["ten_san_pham"], "group_code": r["nhom"], "lgb_raw": r["raw_value"],
            "final_qty": r["forecast_used"], "method": r["model_used"]}


@router.get("/daily-forecast/values")
def daily_values(run_id: str | None = None, forecast_date: str | None = None, horizon: int | None = Query(None, ge=1),
                 group: str | None = None, q: str | None = None, page: int = Query(0, ge=0),
                 date_from: str | None = None, date_to: str | None = None):
    """Rows of one refresh run. 1.4.6: a SEL2 run shows the 20 days of the daily Excel (horizon 8..20 = weekly estimate,
    column cach_tinh); date_from / date_to = target date range (both kinds of run)."""
    fd = _date(forecast_date, "forecast_date")
    df, dt = _date(date_from, "date_from"), _date(date_to, "date_to")
    if group and group not in GROUPS:
        raise AppError("VALIDATION_ERROR", 422, detail=f"group: one of {', '.join(GROUPS)}")
    with db.read() as c:
        scope = _scope(c)
        run = _find_run(c, scope["scope_key"] if scope else None, run_id, fd)
        if run is None:
            return {"run": None, "rows": [], "total": 0, "page": page, "page_size": PAGE, "horizons": []}
        v = sel2_view.view(c, run["id"])
        if v is not None:      # 1.4.4: a SEL2 run shows the rows of the daily Excel (1.4.6: export._rows20, 1..20)
            total, rows = sel2_view.page(v, v.filter(q=q, group=group), horizon, page * PAGE, PAGE, df, dt)
            return {"run": run, "rows": [_sel2_value_row(r) for r in rows], "total": total, "page": page,
                    "page_size": PAGE, "horizons": list(range(1, sel2_view.H_ALL + 1)), "sel2": True,
                    "estimate_from": sel2_view.HORIZON + 1}
        where, params = _filters(run["id"], horizon, group, q, df, dt)
        total = c.execute(f"SELECT COUNT(*) FROM forecast_refresh_values WHERE {where}", params).fetchone()[0]
        names = _names(c, scope)
        rows = [_value_row(run, r, names) for r in c.execute(
            f"SELECT {', '.join(VALUE_COLS)} FROM forecast_refresh_values WHERE {where} "
            "ORDER BY fc_code, sku_code, horizon LIMIT ? OFFSET ?", (*params, PAGE, page * PAGE)).fetchall()]
        horizons = [r[0] for r in c.execute("SELECT DISTINCT horizon FROM forecast_refresh_values WHERE run_id=? "
                                            "ORDER BY horizon", (run["id"],)).fetchall()]
    return {"run": run, "rows": rows, "total": total, "page": page, "page_size": PAGE, "horizons": horizons}


@router.get("/forecast-info")
def forecast_info():
    """1.4.4: the info line of the forecast pages (sel2_view.info): newest SEL2 run of the active scope, else the
    newest 1.3.x run (LIGHTGBM_CU), else the newest AVG_DEMAND read."""
    with db.read() as c:
        scope = _scope(c)
        return sel2_view.info(c, scope["scope_key"] if scope else None)


def _sel2_run(c, run_id: str | None) -> tuple[dict | None, sel2_view.View | None]:
    """(run as shown on the Results page, view) of the given SEL2 run of the active scope, else its newest one."""
    scope = _scope(c)
    sk = scope["scope_key"] if scope else None
    run = _find_run(c, sk, run_id) if run_id else sel2_view.latest_run(c, sk)
    v = sel2_view.view(c, run["id"]) if run else None
    if v is None:
        return None, None
    r = v.run
    hs = list(range(1, sel2_view.H_ALL + 1))
    # the blocks of the 1.3.x run on the page, SEL2-true: the horizons the page offers vs the configured ones (1.4.6: the
    # 20 days of the daily Excel, 8..20 = weekly estimate; nothing to extend), the data used as recorded with the run,
    # the product-name source
    cov = {"run_horizons": hs, "max_horizon": sel2_view.H_ALL,
           "configured": sorted(set(ss.get("horizons", c).enabled)), "configured_missing_in_run": [], "can_extend_without_retraining": False, "cannot_extend_reason": None}
    return {"id": r["id"], "model_version": r["model_version"], "data_source": scope["data_source"],
            "scope_key": sk, "forecast_origin": r["forecast_date"], "forecast_date": r["forecast_date"],
            "data_as_of": r["data_as_of"], "created_at": r["created_at"], "max_horizon": sel2_view.H_ALL,
            "horizons": hs, "estimate_from": sel2_view.HORIZON + 1, "fcs": v.fcs, "sel2": True, "horizon_coverage": cov,
            "lineage": _sel2_lineage(r, scope["data_source"]),
            "product_names": product_names.status(c) if scope["data_source"] == "BIGQUERY" else None}, v


def _sel2_lineage(run: dict, data_source: str) -> dict:
    """Data used by a SEL2 run as recorded with it: the scope (source; BigQuery: the table of the scope key) and the
    input window of the selection (detail_json.inputs window_start .. end, None when not recorded). The sync time is
    not recorded with a SEL2 run: last_sync None (the page omits it)."""
    try:
        inp = (json.loads(run.get("detail_json") or "{}") or {}).get("inputs")
    except (ValueError, AttributeError):
        inp = None
    inp = inp if isinstance(inp, dict) else {}
    sk = run["scope_key"]
    table = sk.split(":", 1)[1] if data_source == "BIGQUERY" and sk.startswith("BIGQUERY:") else None
    return {"data_source": data_source, "scope_key": sk, "table": table, "batch_id": None if table else sk,
            "train_start": inp.get("window_start"), "train_end": inp.get("end"), "last_sync": None}


def _sel2_actual(c, run: dict) -> dict:
    """Actual so far today of the run's scope (the same read-only D0 snapshot as the 1.3.x Results page)."""
    return intraday.actual_today(run["scope_key"], run["data_source"], c)


@router.get("/daily-forecast/sel2-runs")
def sel2_runs(limit: int = Query(30, ge=1, le=200)):
    """Published SEL2 runs of the active scope, newest first (the run list of the Results page in SEL2 mode)."""
    with db.read() as c:
        scope = _scope(c)
        if scope is None:
            return []
        return [_run_row(r) for r in db.rows(
            c, f"SELECT {RUN_COLS} FROM forecast_refresh_runs WHERE scope_key=? AND status='PUBLISHED' "
               "AND config_version LIKE ? ORDER BY forecast_date DESC, created_at DESC, rowid DESC LIMIT ?",
            (scope["scope_key"], sel2_view.SEL2_PREFIX + "%", limit))]


@router.get("/daily-forecast/sel2-summary")
def sel2_summary(run_id: str | None = None, horizon: int = Query(7, ge=1, le=sel2_view.H_ALL),
                 sku_id: str | None = None, fc_id: str | None = None, q: str | None = None,
                 date_from: str | None = None, date_to: str | None = None, limit: int = Query(100, ge=1, le=1000),
                 offset: int = Query(0, ge=0)):
    """Results page (SEL2 mode): per SKU x FC the total of forecast_used over horizon 1..horizon (1.4.6: up to 20, the
    days of the daily Excel; 8..20 = weekly estimate) within the target dates date_from .. date_to, and the daily totals
    of the filtered SKU x FC - the numbers of the daily Excel of the run's day. Order as the 1.3.x summary: total
    DESC, sku, fc. actual: the actual so far today as the 1.3.x summary (D0 snapshot, read only)."""
    df, dt = _date(date_from, "date_from"), _date(date_to, "date_to")
    with db.read() as c:
        run, v = _sel2_run(c, run_id)
        if v is None:
            return {"run": None, "series": [], "daily": [], "n_series": 0, "grand_total": 0}
        keys = v.filter(sku=sku_id, fc=fc_id, q=q)
        act = _sel2_actual(c, run)
    idx = [i for i in range(horizon) if (not df or v.days[i] >= df) and (not dt or v.days[i] <= dt)]
    tot = {k: sum(v.used[k][i] for i in idx) for k in keys}
    keys = sorted(keys, key=lambda k: (-tot[k], k[0], k[1]))
    start, end = (v.days[idx[0]], v.days[idx[-1]]) if idx else (None, None)
    in_range = bool(idx) and start <= act["date"] <= end
    actual = intraday.public(act)
    actual["in_horizon"] = in_range
    # each SKU x FC counted once, only the series that pass the current filter (as the 1.3.x summary)
    actual["total"] = (sum(act["values"].get(k, 0.0) for k in keys)
                       if in_range and intraday.has_values(act) else None)
    actual["n_series"] = len(keys)
    daily = [{"target_date": v.days[i], "total": sum(v.used[k][i] for k in keys),
              "cach_tinh": export.CACH_SEL2 if i < sel2_view.HORIZON else export.CACH_WEEK} for i in idx]
    for d in daily:
        d["actual_today"] = actual["total"] if d["target_date"] == act["date"] else None
    series = [{"sku_id": k[0], "fc_id": k[1], "product_name": v.names.get(k[0]), "total": tot[k],
               "method": v.model[k], "model_used": v.model[k], "forecast_source": v.source[k],
               "actual_today": intraday.value_for(act, k[0], k[1], act["date"]) if in_range else None}
              for k in keys[offset:offset + limit]]
    return {"run": run, "start_date": start, "end_date": end, "horizon": horizon,
            "grand_total": sum(d["total"] for d in daily), "daily": daily, "n_series": len(keys), "series": series,
            "actual": actual}


@router.get("/daily-forecast/sel2-values")
def sel2_values(run_id: str | None = None, horizon: int = Query(7, ge=1, le=sel2_view.H_ALL),
                sku_id: str | None = None, fc_id: str | None = None, q: str | None = None,
                date_from: str | None = None, date_to: str | None = None, limit: int = Query(100, ge=1, le=1000),
                offset: int = Query(0, ge=0)):
    """Results page (SEL2 mode), daily detail: the rows of the daily Excel (horizon 1..horizon; 1.4.6: up to 20, column
    cach_tinh SEL2 / UOC_TINH_THEO_TUAN) with the field names of the page (sku_id, fc_id, horizon_day, forecast_qty =
    forecast_used, method = model_used). Order as the 1.3.x detail: sku, fc, target date; actual_today as the 1.3.x
    detail (D0 snapshot, read only)."""
    df, dt = _date(date_from, "date_from"), _date(date_to, "date_to")
    with db.read() as c:
        run, v = _sel2_run(c, run_id)
        if v is None:
            return {"run": None, "rows": [], "total": 0}
        keys = sorted(v.filter(sku=sku_id, fc=fc_id, q=q))
        total, rows = sel2_view.page(v, keys, None, offset, limit, df, dt, horizon)
        act = _sel2_actual(c, run)
    return {"run": run, "total": total, "actual": intraday.public(act), "rows": [
        {**r, "sku_id": r["sku_code"], "fc_id": r["fc_code"], "product_name": r["ten_san_pham"],
         "horizon_day": r["horizon"], "weekday": date.fromisoformat(r["target_date"]).isoweekday(),
         "forecast_qty": r["forecast_used"], "method": r["model_used"],
         "actual_today": intraday.value_for(act, r["sku_code"], r["fc_code"], r["target_date"])} for r in rows]}


@router.get("/daily-forecast/export.xlsx")
def daily_export(run_id: str | None = None, forecast_date: str | None = None):
    """Every value of one refresh run + a sheet with the trial label, the run, the model and the publishing rule."""
    fd = _date(forecast_date, "forecast_date")
    dcfg = ss.get("daily_forecast")
    with db.read() as c:
        scope = _scope(c)
        run = _find_run(c, scope["scope_key"] if scope else None, run_id, fd)
        if run is None:
            raise AppError("BATCH_NOT_FOUND", 404, detail=f"no refreshed forecast for {run_id or fd or 'any day'}")
        extra = db.one(c, "SELECT model_fingerprint, detail_json FROM forecast_refresh_runs WHERE id=?", (run["id"],))
        content = _export_workbook(c, run, extra or {}, dcfg, _names(c, scope))
    return Response(content, media_type=XLSX, headers={
        "Content-Disposition": f'attachment; filename="daily-forecast-{run["forecast_date"]}-{run["id"]}.xlsx"'})


def _export_workbook(c, run: dict, extra: dict, dcfg, names: dict) -> bytes:
    """openpyxl write-only workbook: the values of the run are streamed from the cursor in chunks (no DataFrame, no
    workbook of cell objects held in memory)."""
    try:
        detail = json.loads(extra.get("detail_json") or "{}")
    except ValueError:
        detail = {}
    info = []
    if run["trial_mode"] or dcfg.trial_mode:
        info.append(("Lưu ý", TRIAL_LABEL["vi"]))
    info += [("Mã lần làm mới", run["id"]), ("Ngày lập dự báo", run["forecast_date"]),
             ("Lập lúc (giờ VN)", _vn(run["created_at"])), ("Dữ liệu đến ngày", run["data_as_of"]),
             ("Mô hình (model id)", run["model_version"]), ("Mã lần huấn luyện", run["training_run_id"]),
             ("Fingerprint cấu hình model", extra.get("model_fingerprint")),
             ("Phiên bản cấu hình (config_version)", run["config_version"]),
             # the threshold the run used (stored with it), never today's setting
             ("Ngưỡng làm tròn (rounding_threshold)", detail.get("rounding_threshold")),
             ("Quy tắc số công bố", PUBLISH_RULE), ("Số chuỗi", run["n_series"]),
             ("Số chuỗi LightGBM", run["n_lightgbm"]), ("Số chuỗi dự phòng", run["n_fallback"]),
             ("Số ngày dự báo", run["horizon"])]
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Thông tin")
    for k, v in info:
        ws.append([k, v])
    ws = wb.create_sheet("Dự báo")
    ws.append(["Ngày lập dự báo", "Ngày", "Ngày thứ", "FC/kho", "SKU", "Tên sản phẩm", "Nhóm", "LightGBM gốc",
               "Số công bố", "Phương pháp", "Cờ"])
    cur = c.execute(f"SELECT {', '.join(VALUE_COLS)} FROM forecast_refresh_values WHERE run_id=? "
                    "ORDER BY fc_code, sku_code, horizon", (run["id"],))
    fd = run["forecast_date"]
    while chunk := cur.fetchmany(EXPORT_CHUNK):
        for r in chunk:
            ws.append([fd, r["target_date"], r["horizon"], r["fc_code"], r["sku_code"], names.get(r["sku_code"]),
                       r["group_code"], r["lgb_raw"], r["final_qty"], r["method"], r["flags"]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@router.post("/daily-forecast/refresh")
def daily_refresh_run():
    """Manual refresh of today (a FORECAST_REFRESH job, trigger MANUAL, tracked like every manual job)."""
    if not ss.get("daily_forecast").enabled:
        raise AppError("DAILY_FORECAST_DISABLED", 409)
    return background.submit("FORECAST_REFRESH", {"business_date": today_vn().isoformat()})


class TrialModeBody(BaseModel):
    trial_mode: bool
    confirm_text: str | None = None


@router.post("/daily-forecast/trial-mode")
def daily_trial_mode(body: TrialModeBody):
    """The ONLY way to change the trial mode (the generic settings PUT refuses it). Switching it OFF needs the typed
    text TAT-CHAY-THU-<today, Vietnam>; back ON (the safe side) needs none. History note OWNER_CONFIRMED."""
    expected = f"TAT-CHAY-THU-{today_vn().isoformat()}"
    if not body.trial_mode and (body.confirm_text or "").strip() != expected:
        raise AppError("TRIAL_MODE_CONFIRMATION_MISMATCH", 400, detail=f"type {expected}")
    with db.tx() as c:
        cur = ss.get("daily_forecast", c)
        before = cur.trial_mode
        if before == body.trial_mode:
            return {"changed": False, "trial_mode": before, "trial_label": _trial_label(cur)}
        new = ss.save("daily_forecast", {**cur.model_dump(), "trial_mode": body.trial_mode},
                      note=f"OWNER_CONFIRMED trial_mode={'true' if body.trial_mode else 'false'}", conn=c)
        params = {"from": before, "to": body.trial_mode}
        db.audit(c, "TRIAL_MODE_CHANGED", "settings", "daily_forecast", params)
        db.alert(c, "INFO" if body.trial_mode else "WARNING", "TRIAL_MODE_CHANGED", params, "settings",
                 "daily_forecast")
    return {"changed": True, "trial_mode": body.trial_mode, "trial_label": _trial_label(new)}


# ------------------------------------------------------------------ accuracy reports (B9)
@router.get("/accuracy-reports")
def accuracy_reports(limit: int = Query(50, ge=1, le=200)):
    with db.read() as c:
        scope = _scope(c)
        if scope is None:
            return []
        return [_report_row(r) for r in db.rows(
            c, f"SELECT {REPORT_COLS} FROM accuracy_report_runs WHERE scope_key=? "
               "ORDER BY created_at DESC, rowid DESC LIMIT ?", (scope["scope_key"], limit))]


@router.post("/accuracy-reports/run")
def accuracy_report_run():
    """Manual accuracy report (an ACCURACY_REPORT job, trigger MANUAL)."""
    if not ss.get("daily_forecast").enabled:
        raise AppError("DAILY_FORECAST_DISABLED", 409)
    return background.submit("ACCURACY_REPORT", {"business_date": today_vn().isoformat()})


def _report_file(path: str | None, dcfg) -> Path | None:
    """The stored report file, only when it resolves INSIDE <reports_dir>/<report_subdir> (else None)."""
    if not path:
        return None
    try:
        base = accuracy_report.report_dir(dcfg).resolve()
        p = Path(path).resolve()
    except (OSError, ValueError):
        return None
    if base not in p.parents or p.suffix.lower() != ".xlsx" or not p.is_file():
        return None
    return p


@router.get("/accuracy-reports/{report_id}/download")
def accuracy_report_download(report_id: str):
    dcfg = ss.get("daily_forecast")
    with db.read() as c:
        scope = _scope(c)
        r = db.one(c, "SELECT report_path FROM accuracy_report_runs WHERE id=? AND scope_key=?",
                   (report_id, scope["scope_key"])) if scope else None
    p = _report_file(r["report_path"] if r else None, dcfg)
    if p is None:
        raise AppError("BATCH_NOT_FOUND", 404, detail=f"report {report_id}: no file")
    return FileResponse(p, media_type=XLSX, filename=p.name)


# ------------------------------------------------------------------ feature table (B11)
def _feature_names(c) -> list[str]:
    """The features a NEW training would use before the table is applied (resolved like train_and_publish: optional
    groups by the scope's coverage, open hours when mandatory for the source, ISO weekday, no table), then any other
    feature of the stored table (model order)."""
    scope = _scope(c)
    cov = feature_registry.coverage(c, scope["scope_key"]) if scope else {"rows": 0}
    mcfg, _ = feature_registry.resolve(ss.get("model", c), cov)
    mcfg = mcfg.model_copy(update={"feature_open_hours": bool(scope and open_hours.mandatory(scope["data_source"])),
                                   "weekday_encoding": "ISO", "feature_table": None})
    names = list(features.feature_names(mcfg))
    order = {n: i for i, n in enumerate(feature_registry.all_model_features())}
    stored = ss.get("feature_table", c).features
    names += sorted((n for n in stored if n not in names), key=lambda n: (order.get(n, len(order)), n))
    return names


def _feature_payload(c) -> dict:
    table = ss.get("feature_table", c).features
    rows = []
    for n in _feature_names(c):
        rule = table.get(n) or ss.FeatureRule()
        rows.append({"feature": n, "feature_group": feature_report.feature_group(n), "enabled": rule.enabled,
                     "contri": rule.contri, "is_default": bool(rule.enabled and rule.contri == 1.0)})
    upd = db.one(c, "SELECT updated_at FROM app_settings WHERE section='feature_table'")
    history = db.rows(c, "SELECT changed_at, note, value_json FROM settings_history WHERE section='feature_table' "
                         "ORDER BY changed_at DESC, id DESC LIMIT 20")
    return {"rows": rows, "updated_at": upd["updated_at"] if upd else None, "effective": "NEXT_TRAINING",
            "history": history, "fingerprint_note": FINGERPRINT_NOTE}


@router.get("/feature-table")
def get_feature_table():
    with db.read() as c:
        return _feature_payload(c)


class FeatureTableBody(BaseModel):
    features: dict[str, dict] = {}
    confirm: bool = False
    note: str | None = None


@router.put("/feature-table")
def put_feature_table(body: FeatureTableBody):
    """The whole table as it should be (a missing name = the default row); only the rows away from the default
    (enabled, 1.0) are stored. Takes effect at the next training (copied into model.feature_table of its run)."""
    if body.confirm is not True:
        raise AppError("FEATURE_TABLE_CONFIRM_REQUIRED", 409)
    if "sku_code" in body.features:
        raise AppError("FEATURE_NOT_IN_TABLE", 422, detail="sku_code")
    with db.read() as c:
        known = set(_feature_names(c))
    unknown = sorted(set(body.features) - known)
    if unknown:
        raise AppError("FEATURE_UNKNOWN", 422, detail=", ".join(unknown[:20]))
    try:
        table = ss.FeatureTableSettings.model_validate({"features": body.features})
    except ValidationError as e:
        text = "; ".join(str(x.get("msg", "")) for x in e.errors())
        for code in ("FEATURE_UNKNOWN", "FEATURE_NOT_IN_TABLE", "FEATURE_REQUIRED"):
            if code in text:
                raise AppError(code, 422, detail=text[:300]) from None
        raise
    new = {n: r.model_dump() for n, r in (feature_table_snapshot(table) or {}).items()}
    note = f"OWNER_CONFIRMED {(body.note or '').strip()}".strip()
    with db.tx() as c:
        before = {n: r.model_dump() for n, r in ss.get("feature_table", c).features.items()}
        saved = before != new
        if saved:       # an identical table is not saved again (no history row, no audit)
            ss.save("feature_table", {"features": new}, note=note, conn=c)
            db.audit(c, "FEATURE_TABLE_CHANGED", "settings", "feature_table",
                     {"from": before, "to": new, "note": body.note})
    with db.read() as c:
        return {**_feature_payload(c), "saved": saved}


# ------------------------------------------------------------------ feature importance of a training run (B10)
def _legacy_rows(raw: str | None) -> list[dict]:
    """Gain only (training_runs.feature_importance_json, the 30 largest before 1.3.1): shares of the listed gains,
    no split count (null, never 0)."""
    try:
        items = json.loads(raw or "[]")
    except ValueError:
        items = []
    items = [x for x in items if isinstance(x, dict) and x.get("feature") and isinstance(x.get("gain"), (int, float))]
    total = float(sum(float(x["gain"]) for x in items))
    rows = [{"feature": x["feature"], "feature_group": feature_report.feature_group(x["feature"]),
             "gain": float(x["gain"]), "split": None, "gain_share": float(x["gain"]) / total if total > 0 else 0.0,
             "split_share": None} for x in items]
    rows.sort(key=lambda r: -r["gain"])
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


def _legacy_groups(rows: list[dict]) -> list[dict]:
    by: dict[str, dict] = {}
    for r in rows:
        d = by.setdefault(r["feature_group"], {"feature_group": r["feature_group"], "n_features": 0, "gain": 0.0,
                                                "split": None})
        d["n_features"] += 1
        d["gain"] += r["gain"]
    total = float(sum(d["gain"] for d in by.values()))
    out = [{**d, "gain_share": d["gain"] / total if total > 0 else 0.0, "split_share": None} for d in by.values()]
    return sorted(out, key=lambda d: -d["gain"])


def _importance(c, run_id: str) -> tuple[dict, dict]:
    tr = db.one(c, "SELECT id, model_version, feature_importance_json FROM training_runs WHERE id=?", (run_id,))
    if tr is None:
        raise AppError("BATCH_NOT_FOUND", 404, detail=f"training run {run_id}")
    rows = db.rows(c, "SELECT feature, feature_group, gain, split, gain_share, split_share, rank "
                      "FROM training_feature_importance WHERE training_run_id=? ORDER BY rank, feature", (run_id,))
    if rows:
        return {"training_run_id": run_id, "source": "TABLE", "rows": rows,
                "groups": feature_report.group_rows(rows)}, tr
    rows = _legacy_rows(tr["feature_importance_json"])
    return {"training_run_id": run_id, "source": "LEGACY_GAIN", "rows": rows, "groups": _legacy_groups(rows)}, tr


@router.get("/training-runs/{run_id}/feature-importance")
def feature_importance(run_id: str):
    with db.read() as c:
        return _importance(c, run_id)[0]


@router.get("/training-runs/{run_id}/feature-importance.xlsx")
def feature_importance_xlsx(run_id: str):
    with db.read() as c:
        out, tr = _importance(c, run_id)
    if out["source"] != "TABLE":      # the workbook needs the split counts stored since 1.3.1
        raise AppError("BATCH_NOT_FOUND", 404, detail=f"training run {run_id}: no feature importance rows")
    dcfg = ss.get("daily_forecast")
    with tempfile.TemporaryDirectory(dir=paths.uploads_dir(), prefix="fi-") as tmp:
        p = feature_report.write_workbook(Path(tmp) / "feature-importance.xlsx", run_id, out["rows"],
                                          {"trial_mode": bool(dcfg.trial_mode), "model_version": tr["model_version"],
                                           "created_at": now_iso()})
        content = p.read_bytes()
    return Response(content, media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="ty-trong-bien-{run_id}.xlsx"'})
