"""Settings, DEMO data, Excel templates, import batches and data quality."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import db
from .. import settings_service as ss
from ..data import demo, excel_io, importer, quality
from ..data.demand import resolve_scope
from ..data.schema import FIELDS
from ..messages import AppError

router = APIRouter(prefix="/api")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(content: bytes, name: str) -> Response:
    return Response(content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------ settings
@router.get("/settings")
def get_settings():
    out = {k: ss.get(k).model_dump() for k in ss.SECTIONS}
    return out


@router.put("/settings/{section}")
def put_settings(section: str, body: dict):
    if section not in ss.SECTIONS or section in ("general", "sql_sources"):   # SQL feeds: only via /api/sql-sources
        raise AppError("BATCH_NOT_FOUND", 404, detail=f"unknown or read-only section {section}")
    if section == "bigquery":
        cur = ss.get("bigquery")
        # connection fields changed -> production mode must be re-verified
        keys = ("project_id", "dataset_id", "location", "source_table", "field_mapping", "auth_method",
                "service_account_file", "created_at_is_utc", "partition_column", "reference_mapping",
                "history_start_date", "exact_duplicate_policy", "oauth_enabled", "oauth_client_id")
        # production_enabled / schema_snapshot are only changed by the activate / mapping endpoints
        body = {k: v for k, v in body.items() if k not in ("production_enabled", "schema_snapshot", "oauth_enabled")}
        new = ss.BigQuerySettings.model_validate({**cur.model_dump(), **body})
        if cur.production_enabled and any(getattr(new, k) != getattr(cur, k) for k in keys):
            new.production_enabled = False
        return ss.save("bigquery", new, note="updated via UI").model_dump()
    if section == "schedule":
        # flow switches (and their switch-on time) change only through /api/schedules, where readiness is checked
        cur = ss.get("schedule").model_dump()
        changed = [k for k in SCHEDULE_SWITCHES if k in body and body[k] != cur[k]]
        if changed:
            raise AppError("SCHEDULE_SWITCH_VIA_FLOW_API", 409, detail=", ".join(changed))
        body = {**body, **{k: cur[k] for k in SCHEDULE_SWITCHES}}
    return ss.save(section, body, note="updated via UI").model_dump()


SCHEDULE_SWITCHES = ("d1_enabled", "d0_enabled", "train_enabled", "d1_enabled_at", "d0_enabled_at", "train_enabled_at",
                     "eod_enabled", "close_enabled", "eod_enabled_at", "close_enabled_at")


@router.post("/settings/{section}/reset")
def reset_settings(section: str):
    if section not in ss.SECTIONS or section in ("general", "sql_sources"):
        raise AppError("BATCH_NOT_FOUND", 404, detail=section)
    if section == "schedule":       # reset times/policies only: never switch a flow on or off
        cur = ss.get("schedule").model_dump()
        keep = {k: cur[k] for k in SCHEDULE_SWITCHES}
        return ss.save("schedule", {**ss.ScheduleSettings().model_dump(), **keep}, note="reset (switches kept)").model_dump()
    return ss.reset(section).model_dump()


@router.get("/settings/{section}/history")
def settings_history(section: str):
    if section not in ss.SECTIONS:
        raise AppError("BATCH_NOT_FOUND", 404, detail=section)
    return ss.history(section)


class SourceBody(BaseModel):
    source: str


@router.put("/active-source")
def set_active_source(body: SourceBody):
    if body.source not in ("DEMO", "MANUAL_IMPORT", "BIGQUERY"):
        raise AppError("NO_ACTIVE_DATASET", 422, detail=body.source)
    if body.source == "BIGQUERY" and not ss.get("bigquery").production_enabled:
        raise AppError("SOURCE_NOT_READY", 409)
    with db.tx() as c:
        ss.update("general", {"active_source": body.source}, note=f"active source -> {body.source}", conn=c)
        db.audit(c, "ACTIVE_SOURCE_CHANGED", "settings", "general", {"source": body.source})
    return ss.get("general").model_dump()


# ------------------------------------------------------------------ demo + templates
class DemoBody(BaseModel):
    days: int = 730
    n_skus: int = 30
    seed: int = 42


@router.post("/demo/generate")
def generate_demo(body: DemoBody | None = None):
    b = body or DemoBody()
    if not (60 <= b.days <= 1100 and 3 <= b.n_skus <= 200):
        raise AppError("TOO_MANY_ROWS", 422, detail="days 60..1100, n_skus 3..200")
    return demo.create_demo_batch(b.days, b.n_skus, b.seed)


@router.get("/templates/import-template.xlsx")
def template():
    return _xlsx(excel_io.build_template(), "mau-nhap-du-lieu-lich-su.xlsx")


@router.get("/templates/sample-history.xlsx")
def sample_history():
    return _xlsx(demo.sample_history_xlsx(), "du-lieu-mau-hop-le.xlsx")


@router.get("/templates/sample-with-errors.xlsx")
def sample_errors():
    return _xlsx(demo.sample_errors_xlsx(), "du-lieu-mau-co-loi.xlsx")


@router.get("/schema/fields")
def schema_fields():
    return FIELDS


# ------------------------------------------------------------------ imports
@router.post("/imports/upload")
def upload(file: UploadFile = File(...), replace_batch_id: str | None = Form(None)):
    return importer.save_upload(file.file, file.filename or "upload", replace_batch_id or None)


@router.get("/imports/uploads/{upload_id}/sheets/{sheet}")
def sheet_mapping(upload_id: str, sheet: str):
    return importer.suggest_for_sheet(upload_id, sheet)


class ValidateBody(BaseModel):
    sheet: str | None = None
    mapping: dict[str, str | None]


@router.post("/imports/uploads/{upload_id}/validate")
def validate(upload_id: str, body: ValidateBody):
    return importer.validate_upload(upload_id, body.sheet, body.mapping)


@router.get("/imports")
def list_imports(include_demo: bool = False):
    return importer.list_batches(include_demo)


@router.get("/imports/{batch_id}")
def get_import(batch_id: str):
    return importer.batch_detail(batch_id)


@router.get("/imports/{batch_id}/errors.xlsx")
def import_errors(batch_id: str, lang: str = "vi"):
    lang = lang if lang in ("vi", "en") else "vi"
    name = f"bao-cao-loi-{batch_id}.xlsx" if lang == "vi" else f"error-report-{batch_id}.xlsx"
    return _xlsx(importer.error_report(batch_id, lang), name)


class ConfirmBody(BaseModel):
    accept_row_errors: bool = False
    set_active: bool = True


@router.post("/imports/{batch_id}/confirm")
def confirm(batch_id: str, body: ConfirmBody):
    return importer.confirm(batch_id, body.accept_row_errors, body.set_active)


@router.post("/imports/{batch_id}/cancel")
def cancel(batch_id: str):
    return importer.cancel(batch_id)


class DeleteBody(BaseModel):
    confirm_text: str


@router.post("/imports/{batch_id}/delete")
def delete(batch_id: str, body: DeleteBody):
    return importer.delete_batch(batch_id, body.confirm_text)


@router.post("/imports/{batch_id}/set-active")
def set_active(batch_id: str):
    return importer.set_active_dataset(batch_id)


# ------------------------------------------------------------------ data quality
@router.get("/data-quality")
def data_quality(refresh: bool = False):
    scope = resolve_scope()
    rep = None if refresh else quality.latest_report(scope["scope_key"])
    if rep is None:
        with db.tx() as c:
            rep = quality.build_report(scope, c)
    return rep


@router.get("/data-quality/history")
def data_quality_history(limit: int = 30):
    scope = resolve_scope()
    with db.read() as c:
        return db.rows(c, "SELECT id, scope_key, data_source, created_at, can_train FROM validation_reports "
                          "WHERE scope_key=? ORDER BY created_at DESC, rowid DESC LIMIT ?", (scope["scope_key"], limit))
