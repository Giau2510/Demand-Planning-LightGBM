"""1.4.0 SEL2: forecast source per SKU x FC (AVG_DEMAND | LIGHTGBM; ml/sel2/source_config.py) and the stored AVG_DEMAND
values per day (ml/sel2/avg_demand.py).

Every GET is read-only. The state changes (PUT one row, upload preview, apply) are guarded by the X-DF-Client header like
every other state change (security.LocalGuardMiddleware) and need confirm=true; writing is refused while
sel2_pipeline.enabled = False (the exact 1.3.1 mode). The AVG_DEMAND read from BigQuery is started from the pipeline or
the CLI (sel2-avg-read), never from here.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import db
from ..messages import AppError
from ..ml.sel2 import avg_demand, source_config
from ..timeutil import today_vn

router = APIRouter(prefix="/api/sel2")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(content: bytes, name: str) -> Response:
    return Response(content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _date(v: str | None, name: str) -> str | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise AppError("VALIDATION_ERROR", 422, detail=f"{name}: YYYY-MM-DD expected") from None


# ------------------------------------------------------------------ forecast source configuration
@router.get("/source-config")
def source_config_list(sku_code: str | None = None, fc_code: str | None = None, source: str | None = None,
                       limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    with db.read() as c:
        return source_config.list_config(c, sku_code, fc_code, source, limit, offset)


@router.get("/source-config/history")
def source_config_history(sku_code: str | None = None, fc_code: str | None = None, batch_id: str | None = None,
                          limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                          format: str = Query("json", pattern="^(json|xlsx)$")):
    with db.read() as c:
        if format == "xlsx":
            return _xlsx(source_config.history_xlsx(c, sku_code, fc_code, batch_id),
                         f"lich-su-nguon-du-bao-{today_vn().isoformat()}.xlsx")
        return source_config.history(c, sku_code, fc_code, batch_id, limit, offset)


@router.get("/source-config/download")
def source_config_download():
    return _xlsx(source_config.download_xlsx(), f"nguon-du-bao-{today_vn().isoformat()}.xlsx")


@router.get("/source-config/{sku_code}/{fc_code}")
def source_config_get(sku_code: str, fc_code: str):
    with db.read() as c:
        return source_config.get_effective(c, sku_code.strip(), fc_code.strip())


class SourceBody(BaseModel):
    forecast_source: str
    ghi_chu: str | None = None
    confirm: bool = False


@router.put("/source-config/{sku_code}/{fc_code}")
def source_config_put(sku_code: str, fc_code: str, body: SourceBody):
    return source_config.set_one(sku_code, fc_code, body.forecast_source, body.ghi_chu, body.confirm, channel="UI")


@router.post("/source-config/upload")
def source_config_upload(file: UploadFile = File(...)):
    return source_config.preview_upload(file.file, file.filename or "upload.xlsx")


class ApplyBody(BaseModel):
    preview_id: str
    confirm: bool = False


@router.post("/source-config/apply")
def source_config_apply(body: ApplyBody):
    return source_config.apply_upload(body.preview_id, body.confirm)


# ------------------------------------------------------------------ AVG_DEMAND values
@router.get("/avg-demand")
def avg_demand_values(date: str | None = None, sku_code: str | None = None, fc_code: str | None = None,
                      limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Values of the day (default: today, Vietnam) with the seller rule of the settings; sku_code / fc_code are
    substring filters. The read used (CURRENT, else HISTORICAL) is reported with its source_modified."""
    day = _date(date, "date") or today_vn().isoformat()
    res = avg_demand.avg_value(day)
    s, f = (sku_code or "").strip().lower(), (fc_code or "").strip().lower()
    items = [{"sku_code": k[0], "fc_code": k[1], **v} for k, v in sorted(res.pop("values").items())
             if (not s or s in k[0].lower()) and (not f or f in k[1].lower())]
    reasons: dict[str, int] = {}
    for it in items:
        if it["reason"]:
            reasons[it["reason"]] = reasons.get(it["reason"], 0) + 1
    return {**res, "total": len(items), "limit": limit, "offset": offset, "no_value_by_reason": reasons,
            "items": items[offset:offset + limit]}


# ------------------------------------------------------------------ daily Excel (ml/sel2/export.py)
@router.get("/export/{day}")
def export_download(day: str):
    """The latest version of the daily Excel of the day (SEL2_EXPORT_NOT_FOUND when none)."""
    from fastapi.responses import FileResponse
    from ..ml.sel2 import export
    p, r = export.latest_file(_date(day, "date"))
    return FileResponse(p, media_type=XLSX, filename=export.file_names(r["forecast_date"])[1],
                        headers={"X-DF-Export-Version": str(r["version"]), "X-DF-Export-Sha256": r["sha256"] or ""})


@router.get("/export/{day}/runs")
def export_versions(day: str):
    from ..ml.sel2 import export
    d = _date(day, "date")
    return {"forecast_date": d, "items": export.runs(d)}


class ExportBody(BaseModel):
    date: str
    confirm: bool = False


@router.post("/export")
def export_write(body: ExportBody):
    """Write a new version of the daily Excel: a FORECAST_EXPORT job (mode MANUAL, trigger MANUAL) tracked like every
    manual job; its result (version, n_rows, sha256) is in the job row. confirm=true required; refused while
    sel2_pipeline.enabled = False. An export already queued / running is returned (already_active) instead of a second
    one; each click after it has finished writes a new version."""
    from ..ml.sel2 import jobs as sel2_jobs
    from . import background
    d = _date(body.date, "date")
    if not d:
        raise AppError("VALIDATION_ERROR", 422, detail="date: YYYY-MM-DD expected")
    if body.confirm is not True:
        raise AppError("SEL2_EXPORT_CONFIRM_REQUIRED", 409)
    if not sel2_jobs.enabled():
        raise AppError("SEL2_PIPELINE_DISABLED", 409)
    return background.submit("FORECAST_EXPORT", {"business_date": d, "mode": "MANUAL"})
