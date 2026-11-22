"""Settings, DEMO data, Excel templates, import batches and data quality."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from .. import db
from .. import settings_registry as reg
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
        # production_enabled / schema_snapshot are only changed by the activate / mapping endpoints
        body = {k: v for k, v in body.items() if k not in ("production_enabled", "schema_snapshot", "oauth_enabled")}
        with db.tx() as c:          # 1.4.15 lot 2: read, registry guard and save in one transaction
            cur = ss.get("bigquery", c)
            new = ss.BigQuerySettings.model_validate({**cur.model_dump(), **body})
            _registry_guard("bigquery", cur, new)
            # connection fields changed -> production mode must be re-verified
            if cur.production_enabled and any(getattr(new, k) != getattr(cur, k) for k in BQ_CONNECTION_KEYS):
                new.production_enabled = False
            return ss.save("bigquery", new, note="updated via UI", conn=c).model_dump()
    if section == "model":
        # 1.2.9: open hours are a MANDATORY input of the BIGQUERY source and the dow encoding belongs to each training
        # run: both are decided by the training, never saved as user settings (a switch-off is refused, not ignored)
        if body.get("feature_open_hours") is not None:
            raise AppError("OPEN_HOURS_MANDATORY", 422, detail=f"feature_open_hours={body.get('feature_open_hours')!r}")
        # 1.3.1 (B11): the feature-table snapshot is set only by a training run (on the copy stored with the run)
        if body.get("feature_table") is not None:
            raise AppError("FEATURE_TABLE_SET_BY_TRAINING", 409)
        body = {**body, "feature_open_hours": None, "weekday_encoding": None}
    if section == "feature_table":
        # 1.3.1 (B11): only through PUT /api/feature-table (confirmation, history + audit)
        raise AppError("FEATURE_TABLE_VIA_OWN_API", 409)
    if section == "data_policy":
        # 1.4.15: the guarded fields change only through /api/data-policy/guarded (expected value, confirmation, audit);
        # a value sent here is ignored, read and save in one transaction so a concurrent guarded change is never undone
        with db.tx() as c:
            cur = ss.get("data_policy", c).model_dump()
            new = ss.DataPolicySettings.model_validate({**body, **{k: cur[k] for k in DATA_POLICY_GUARDED}}).model_dump()
            diff = "; ".join(f"{k} {cur.get(k)} -> {v}" for k, v in new.items() if cur.get(k) != v)
            note = (f"updated via UI: {diff}" if diff else "updated via UI")[:400]
            return ss.save(section, new, note=note, conn=c).model_dump()
    with db.tx() as c:              # 1.4.15 lot 2: read, registry guard and save in one transaction
        cur = ss.get(section, c)
        ctx = None
        if section == "daily_forecast":
            # 1.3.1 (B12): the trial mode changes only through its own confirmed endpoint, never with the other settings
            if "trial_mode" in body and body["trial_mode"] != cur.trial_mode:
                raise AppError("TRIAL_MODE_CONFIRM_REQUIRED", 409, detail=f"{cur.trial_mode} -> {body['trial_mode']}")
            body = {**body, "trial_mode": cur.trial_mode}
        if section == "schedule":
            # flow switches (and their switch-on time) change only through /api/schedules, where readiness is checked
            sched = cur.model_dump()
            changed = [k for k in SCHEDULE_SWITCHES if k in body and body[k] != sched[k]]
            if changed:
                raise AppError("SCHEDULE_SWITCH_VIA_FLOW_API", 409, detail=", ".join(changed))
            body = {**body, **{k: sched[k] for k in SCHEDULE_SWITCHES}, **{k: sched[k] for k in D0_PAUSE_FIELDS}}
            ctx = {"stored": True}      # d0_paused_until is the stored value (= ss.save's own rule)
        new = ss.SECTIONS[section].model_validate(body, context=ctx)
        _registry_guard(section, cur, new)
        return ss.save(section, new, note="updated via UI", conn=c).model_dump()


def _registry_guard(section: str, cur, new) -> None:
    """1.4.15 lot 2: a registry field (settings_registry) changes only through /api/settings-advanced: a value that
    differs from the current one (a key left out counts as its default) is refused, nothing is saved; an equal value
    (an old tab sending the whole section) passes."""
    c, n = cur.model_dump(), new.model_dump()
    keys = [k for k in reg.put_guarded_keys(section) if not reg.same(c[k], n[k])]
    if keys:
        raise AppError("SETTINGS_FIELD_GUARDED", 409, detail=f"{section}: {', '.join(keys)}", section=section,
                       fields=keys, current={k: c[k] for k in keys})


# connection fields: a change turns BigQuery production mode off (it must be re-verified)
BQ_CONNECTION_KEYS = ("project_id", "dataset_id", "location", "source_table", "field_mapping", "auth_method",
                      "service_account_file", "created_at_is_utc", "partition_column", "reference_mapping",
                      "history_start_date", "exact_duplicate_policy", "oauth_enabled", "oauth_client_id")


SCHEDULE_SWITCHES = ("d1_enabled", "d0_enabled", "train_enabled", "d1_enabled_at", "d0_enabled_at", "train_enabled_at",
                     "eod_enabled", "close_enabled", "eod_enabled_at", "close_enabled_at",
                     "refresh_enabled", "refresh_enabled_at", "report_enabled", "report_enabled_at")     # 1.3.1


D0_PAUSE_FIELDS = ("d0_paused_until", "d0_paused_by", "d0_pause_windows")     # 1.4.13: set only through /api/d0/pause, never by this editor


# 1.4.15: set only through /api/data-policy/guarded (api/data_policy_routes.py), never by this editor or its reset
DATA_POLICY_GUARDED = ("window_start_date", "history_change_policy", "history_day_check", "source_time_travel_hours",
                       "training_start_rule")


@router.post("/settings/{section}/reset")
def reset_settings(section: str):
    if section not in ss.SECTIONS or section in ("general", "sql_sources"):
        raise AppError("BATCH_NOT_FOUND", 404, detail=section)
    if section == "feature_table":      # 1.3.1: only through PUT /api/feature-table
        raise AppError("FEATURE_TABLE_VIA_OWN_API", 409)
    # 1.4.15 lot 2: a reset keeps every registry field (settings_registry: changed only through /api/settings-advanced
    # or its own path); schedule: never switches a flow on or off (1.1.8); daily_forecast: never the trial mode (1.3.1)
    keep_keys = set(reg.keys_of(section))
    if section == "schedule":
        keep_keys |= set(SCHEDULE_SWITCHES + D0_PAUSE_FIELDS)
    if section == "daily_forecast":
        keep_keys.add("trial_mode")
    if section == "bigquery":
        # 1.4.15 (owner 23/11/2026): a reset never touches the connection / mapping / sign-in (EXCLUDED + OWN_PATH of
        # settings_registry): only the remaining keys go back to their defaults
        keep_keys |= {k for (s, k) in reg.EXCLUDED if s == "bigquery"}
        keep_keys.add("maximum_bytes_billed")      # REV-B: the cost cap is never raised by a reset (default may be higher)
    if keep_keys:
        with db.tx() as c:
            cur = ss.get(section, c).model_dump()
            if section == "model" and cur["horizon_weight_short"] is not None:
                keep_keys.add("forecast_strategy")     # kept horizon weights are valid only with DIRECT
            new = {**ss.SECTIONS[section]().model_dump(), **{k: cur[k] for k in keep_keys}}
            if section == "bigquery" and cur["production_enabled"] and any(
                    not reg.same(new[k], cur[k]) for k in BQ_CONNECTION_KEYS):
                new["production_enabled"] = False      # same rule as PUT: a changed connection must be re-verified
            note = {"schedule": "reset (switches and registry fields kept)",
                    "daily_forecast": "reset (trial mode and registry fields kept)"}.get(section,
                                                                                        "reset (registry fields kept)")
            saved = ss.save(section, new, note=note, conn=c).model_dump()
            return {**saved, "kept_keys": sorted(keep_keys)} if section == "bigquery" else saved
    if section == "data_policy":       # 1.4.15: a reset never changes the guarded fields
        with db.tx() as c:
            cur = ss.get("data_policy", c).model_dump()
            keep = {k: cur[k] for k in DATA_POLICY_GUARDED}
            return ss.save("data_policy", {**ss.DataPolicySettings().model_dump(), **keep},
                           note="reset (guarded fields kept)", conn=c).model_dump()
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
