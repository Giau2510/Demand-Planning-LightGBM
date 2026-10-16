"""System status, jobs/scheduler, D0 snapshots, BigQuery connection, alerts, backups, audit."""
from __future__ import annotations

import json
import os
import threading

import pandas as pd
from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel

from .. import __version__, backup, db, paths
from .. import settings_service as ss
from .. import sync
from ..bq import connector, dup_report, oauth
from ..data.demand import data_window, resolve_scope
from ..data.excel_io import dataframe_to_xlsx
from ..jobs import scheduler as sched_mod
from ..messages import AppError
from ..security import read_runtime
from ..timeutil import now_iso, today_vn
from . import background

router = APIRouter(prefix="/api")


@router.get("/messages")
def messages():
    """Bilingual catalogue for every code the backend emits (validation, jobs, alerts, errors)."""
    from ..messages import CATALOG
    return {k: {"vi": v[0], "en": v[1]} for k, v in CATALOG.items()}


@router.get("/health")
def health():
    return {"ok": True, "version": __version__, "time": now_iso()}


def system_status() -> dict:
    g = ss.get("general")
    pol = ss.get("data_policy")
    out: dict = {"version": __version__, "data_dir": str(paths.data_dir()), "active_source": g.active_source,
                 "scope": None, "scope_error": None, "today_vn": str(today_vn())}
    with db.read() as c:
        out["db_version"] = c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        win = data_window(c)
        out["data_window"] = {"start": win["start"], "end": win["end"]}
        try:
            scope = resolve_scope(c)
            out["scope"] = scope
        except AppError as e:
            out["scope_error"] = e.to_dict()
            scope = None
        if scope:
            r = db.one(c, "SELECT MAX(order_date) AS max_date, MIN(order_date) AS min_date, COUNT(*) AS n, "
                          "MAX(loaded_at) AS loaded_at FROM demand_daily WHERE scope_key=?", (scope["scope_key"],))
            fresh = {"max_date": r["max_date"], "min_date": r["min_date"], "rows": r["n"], "loaded_at": r["loaded_at"]}
            w = c.execute("SELECT COUNT(*), MIN(order_date), MAX(order_date) FROM demand_daily WHERE scope_key=? AND "
                          "order_date BETWEEN ? AND ?", (scope["scope_key"], win["start"], win["end"])).fetchone()
            fresh["window_rows"], fresh["window_min_date"], fresh["window_max_date"] = w[0], w[1], w[2]
            if r["max_date"]:
                from datetime import date
                lag = (today_vn() - date.fromisoformat(r["max_date"])).days
                fresh["lag_days"] = lag
                fresh["stale"] = lag > pol.max_data_lag_days
                fresh["stale_enforced"] = fresh["stale"] and scope["data_source"] in pol.stale_check_sources
            if scope["data_source"] == "BIGQUERY":
                st = db.one(c, "SELECT value_json FROM sync_state WHERE name=?", (f"last_d1_sync:{scope['scope_key']}",))
                fresh["last_successful_sync"] = json.loads(st["value_json"]) if st else None
            out["freshness"] = fresh
            out["latest_forecast_run"] = _dec(db.one(
                c, "SELECT * FROM forecast_runs WHERE scope_key=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (scope["scope_key"],)))
            out["latest_accepted_training"] = _dec(db.one(
                c, "SELECT id, model_version, status, finished_at, metrics_json, quality_gate_json FROM training_runs "
                   "WHERE scope_key=? AND status='ACCEPTED' ORDER BY started_at DESC, rowid DESC LIMIT 1", (scope["scope_key"],)))
            out["latest_training_attempt"] = _dec(db.one(
                c, "SELECT id, model_version, status, started_at, finished_at, reject_reason, error, metrics_json, "
                   "quality_gate_json FROM training_runs WHERE scope_key=? ORDER BY started_at DESC, rowid DESC LIMIT 1",
                (scope["scope_key"],)))
        out["latest_jobs"] = {jt: db.one(c, "SELECT id, job_type, status, trigger, reason_code, created_at, finished_at, "
                                            "next_attempt_at, attempt, max_attempts, stage, stage_updated_at "
                                            "FROM job_runs WHERE job_type=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (jt,))
                              for jt in ("D1_SYNC", "D0_SYNC", "TRAIN_PUBLISH", "FORECAST_EXTEND")}
        out["alerts"] = [_dec(a) for a in db.rows(c, "SELECT * FROM alerts WHERE acknowledged_at IS NULL "
                                                     "ORDER BY id DESC LIMIT 20")]
    out["scheduler"] = sched_mod.SCHEDULER.status() if sched_mod.SCHEDULER else {"running": False}
    sc = ss.get("schedule")
    out["scheduler"]["flows"] = {"d1": sc.d1_enabled, "d0": sc.d0_enabled, "train": sc.train_enabled}
    out["bigquery_production_enabled"] = ss.get("bigquery").production_enabled
    return out


def _dec(r):
    if not r:
        return r
    for k in list(r):
        if k.endswith("_json"):
            r[k[:-5]] = json.loads(r.pop(k) or "null")
    return r


@router.get("/system/status")
def get_status():
    return system_status()


@router.post("/system/shutdown")
def shutdown(request: Request):
    rt = read_runtime() or {}
    if not rt.get("shutdown_token") or request.headers.get("x-df-shutdown-token") != rt["shutdown_token"]:
        raise AppError("CSRF_BLOCKED", 403)
    def _later():
        import time
        time.sleep(0.5)
        if sched_mod.SCHEDULER:
            sched_mod.SCHEDULER.stop()
        os._exit(0)
    threading.Thread(target=_later, daemon=True).start()
    return {"ok": True}


# ------------------------------------------------------------------ alerts / audit / backups
@router.get("/alerts")
def alerts(limit: int = 100, include_ack: bool = False):
    with db.read() as c:
        sql = "SELECT * FROM alerts" + ("" if include_ack else " WHERE acknowledged_at IS NULL")
        return [_dec(a) for a in db.rows(c, sql + " ORDER BY id DESC LIMIT ?", (limit,))]


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int):
    with db.tx() as c:
        c.execute("UPDATE alerts SET acknowledged_at=? WHERE id=?", (now_iso(), alert_id))
    return {"ok": True}


@router.post("/alerts/ack-all")
def ack_all():
    with db.tx() as c:
        c.execute("UPDATE alerts SET acknowledged_at=? WHERE acknowledged_at IS NULL", (now_iso(),))
    return {"ok": True}


@router.get("/audit")
def audit(limit: int = 200):
    with db.read() as c:
        return [_dec(a) for a in db.rows(c, "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))]


@router.get("/system/backups")
def backups():
    return {"dir": str(paths.backups_dir()), "files": backup.list_backups()}


@router.post("/system/backups")
def make_backup():
    f = backup.backup_database("manual")
    with db.tx() as c:
        db.audit(c, "BACKUP_CREATED", "backup", f.name)
    return {"file": f.name, "dir": str(paths.backups_dir())}


# ------------------------------------------------------------------ jobs / scheduler
@router.get("/jobs")
def jobs(job_type: str | None = None, status: str | None = None, limit: int = 200):
    sql = "SELECT * FROM job_runs WHERE 1=1"
    params: list = []
    if job_type:
        sql += " AND job_type=?"
        params.append(job_type)
    if status:
        sql += " AND status=?"
        params.append(status)
    with db.read() as c:
        return [_job_view(r) for r in db.rows(c, sql + " ORDER BY created_at DESC, rowid DESC LIMIT ?", (*params, limit))]


def _job_view(r: dict | None) -> dict | None:
    """Job row + derived facts: elapsed seconds and `stale` = RUNNING but no stage update for longer than the
    job timeout (progress unknown - e.g. the process hung). Interrupted jobs are already FAILED/RETRY_WAIT
    after a restart (runner.recover_interrupted)."""
    if not r:
        return r
    from ..timeutil import now_utc, parse_iso
    r = _dec(r)                                   # stage_history_json -> stage_history
    r["stage_history"] = r.get("stage_history") or []
    start, end = parse_iso(r.get("started_at")), parse_iso(r.get("finished_at"))
    r["elapsed_seconds"] = round(((end or now_utc()) - start).total_seconds(), 1) if start else None
    upd = parse_iso(r.get("stage_updated_at"))
    timeout = ss.get("schedule").timeout_seconds
    r["stale"] = bool(r["status"] == "RUNNING" and upd and (now_utc() - upd).total_seconds() > timeout + 60)
    return r


@router.get("/jobs/active")
def active_job(job_type: str):
    """The most recent queued/running job of a type (lets the UI resume tracking after a reload)."""
    with db.read() as c:
        return _job_view(db.one(c, "SELECT * FROM job_runs WHERE job_type=? AND status IN ('PENDING','RUNNING') "
                                   "ORDER BY created_at DESC, rowid DESC LIMIT 1", (job_type,)))


@router.get("/jobs/latest")
def latest_job(job_type: str):
    with db.read() as c:
        return _job_view(db.one(c, "SELECT * FROM job_runs WHERE job_type=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                                (job_type,)))


@router.get("/jobs/{job_id}")
def job_detail(job_id: str):
    with db.read() as c:
        r = db.one(c, "SELECT * FROM job_runs WHERE id=?", (job_id,))
    if not r:
        raise AppError("BATCH_NOT_FOUND", 404, detail=job_id)
    return _job_view(r)


class RunJobBody(BaseModel):
    job_type: str
    force: bool = False


@router.post("/jobs/run")
def run_job(body: RunJobBody):
    if body.job_type == "FORECAST_EXTEND":       # needs a run id: POST /api/forecast-runs/{id}/extend
        raise AppError("VALIDATION_ERROR", 422, detail="use /api/forecast-runs/{run_id}/extend")
    params = {"force": body.force} if body.job_type == "TRAIN_PUBLISH" else {}
    return background.submit(body.job_type, params)


@router.get("/scheduler/status")
def scheduler_status():
    s = sched_mod.SCHEDULER.status() if sched_mod.SCHEDULER else {"running": False}
    with db.read() as c:
        hb = db.one(c, "SELECT value_json FROM sync_state WHERE name='scheduler_heartbeat'")
    s["heartbeat"] = json.loads(hb["value_json"]) if hb else None
    s["config"] = ss.get("schedule").model_dump()
    return s


@router.post("/scheduler/tick")
def scheduler_tick():
    """Evaluate the schedule now (useful after changing the configuration)."""
    if not sched_mod.SCHEDULER:
        raise AppError("SCHEDULER_DISABLED", 409)
    return {"actions": sched_mod.SCHEDULER.tick()}


# ------------------------------------------------------------------ snapshots
@router.get("/snapshots")
def snapshots(order_date: str | None = None, date_from: str | None = None, date_to: str | None = None,
              sku_id: str | None = None, fc_id: str | None = None, data_source: str | None = None, limit: int = 200):
    return sync.list_snapshots({"order_date": order_date, "date_from": date_from, "date_to": date_to,
                                "sku_id": sku_id, "fc_id": fc_id, "data_source": data_source}, limit)


@router.get("/snapshots/{sid}")
def snapshot(sid: str, sku_id: str | None = None, fc_id: str | None = None):
    return sync.snapshot_detail(sid, sku_id, fc_id)


@router.get("/snapshots/{sid}/export.xlsx")
def snapshot_export(sid: str, lang: str = "vi"):
    """Snapshot export in the UI language; dates DD/MM/YYYY, times in Vietnam time, numbers unchanged."""
    from ..export_i18n import OTHER, fmt_date, fmt_dateish, labels
    lang, L = labels(lang)
    O = OTHER[lang]
    d = sync.snapshot_detail(sid)
    snap = d["snapshot"]
    rows = []
    for k, v in snap.items():
        if k == "order_date":
            v = fmt_date(v, L)
        elif k == "is_catch_up":
            v = L["yes"] if v else L["no"]
        else:
            v = fmt_dateish(v, L)
        rows.append((O["snap_info"].get(k, k), v))
    info = pd.DataFrame(rows, columns=[L["field"], L["value"]])
    vals = pd.DataFrame(d["values"])
    if not vals.empty:
        if "source_updated_at" in vals:
            vals["source_updated_at"] = vals["source_updated_at"].map(lambda v: fmt_dateish(v, L))
        vals = vals[[c for c in O["snap_cols"] if c in vals]].rename(columns=O["snap_cols"])
    content = dataframe_to_xlsx({O["snap_sheet_info"]: info, O["snap_sheet_values"]: vals})
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="snapshot-{sid}-{lang}.xlsx"'})


# ------------------------------------------------------------------ BigQuery
@router.get("/bigquery/status")
def bq_status():
    bq = ss.get("bigquery")
    v = connector.validation_state()
    start, end = connector.read_range(bq)
    return {"settings": bq.model_dump(), "checks": connector.status(), "activation": connector.activation_check(),
            "mapping_hash": connector.mapping_hash(bq), "read_range": {"start": str(start), "end": str(end)},
            "validation": v, "validation_current": bool(v and v.get("mapping_hash") == connector.mapping_hash(bq)),
            "identity": oauth.runtime_identity(), "oauth": oauth.status(),
            "duplicate_check": connector.dup_state(), "duplicate_reports": dup_report.list_reports(10),
            "ingest_check": sync.ingest_check_state(),
            "adc_env_set": bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")),
            "adc_default_file_exists": os.path.exists(os.path.join(os.environ.get("APPDATA", ""), "gcloud",
                                                                   "application_default_credentials.json"))}


@router.post("/bigquery/check-auth")
def bq_check_auth():
    bq = ss.get("bigquery")
    try:
        connector._client(bq)
        connector._set_status("auth", True, method=bq.auth_method)
        return {"ok": True, "method": bq.auth_method}
    except AppError as e:
        connector._set_status("auth", False, error=e.to_dict())
        raise


@router.post("/bigquery/test-connection")
def bq_test():
    return connector.test_connection()


@router.post("/bigquery/schema")
def bq_schema():
    res = connector.read_schema()
    res["mapping_check"] = connector.validate_mapping(res["columns"])
    return res


@router.post("/bigquery/preview")
def bq_preview():
    return connector.preview()


class ProfileBody(BaseModel):
    days: int = 30


@router.post("/bigquery/profile")
def bq_profile(body: ProfileBody | None = None):
    days = body.days if body else 30
    if not 1 <= days <= 400:
        raise AppError("TOO_MANY_ROWS", 422, detail="days 1..400")
    return connector.profile(days)


@router.post("/bigquery/validate")
def bq_validate():
    """Full-period read-only validation (dry-run cost check first). Never changes the source or the forecast."""
    return connector.validate_source()


@router.post("/bigquery/ingest-check")
def bq_ingest_check():
    """Next D-1 load step by step WITHOUT writing demand: sign-in, window, mapping, exact-duplicate gate (report on
    duplicates), aggregation, output checks, reconciliation, comparison with the stored days (read-only)."""
    return sync.d1_dry_run()


@router.get("/bigquery/duplicate-reports")
def bq_duplicate_reports():
    return dup_report.list_reports()


@router.get("/bigquery/duplicate-reports/{name}")
def bq_duplicate_report_file(name: str):
    """Download one duplicate report (.xlsx, or a .csv fallback) from the reports folder; nothing else is served."""
    p = dup_report.path_of(name)
    if p is None:
        raise AppError("BATCH_NOT_FOUND", 404, detail=name)
    media = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if p.suffix == ".xlsx"
             else "text/csv; charset=utf-8")
    return Response(p.read_bytes(), media_type=media, headers={"Content-Disposition": f'attachment; filename="{p.name}"'})


@router.post("/bigquery/suggest-mapping")
def bq_suggest_mapping():
    """Suggestion for the confirmed table layout, checked against the LIVE schema. Not saved."""
    res = connector.read_schema()
    sug = connector.suggest_mapping(res["columns"])
    sug["check"] = connector.validate_mapping(res["columns"], sug["field_mapping"], sug["reference_mapping"])
    sug["columns"] = res["columns"]
    return sug


class EstimateBody(BaseModel):
    start: str
    end: str


@router.post("/bigquery/estimate")
def bq_estimate(body: EstimateBody):
    from datetime import date
    return connector.estimate_daily_query(date.fromisoformat(body.start), date.fromisoformat(body.end))


class MappingBody(BaseModel):
    field_mapping: dict[str, ss.FieldMapping]
    reference_mapping: dict[str, ss.FieldMapping] | None = None
    created_at_is_utc: bool | None = None
    partition_column: str | None = None


@router.post("/bigquery/mapping")
def bq_mapping(body: MappingBody):
    """Validate the mapping against the live schema, then save mapping + schema snapshot (for drift checks)."""
    res = connector.read_schema()
    check = connector.validate_mapping(res["columns"], body.field_mapping, body.reference_mapping)
    if not check["ok"]:
        raise AppError("BQ_MAPPING_INVALID", 422, detail=json.dumps(check["errors"]))
    cur = ss.get("bigquery")
    patch = {"field_mapping": {k: v.model_dump() for k, v in body.field_mapping.items()},
             "schema_snapshot": res["columns"], "production_enabled": False}
    if body.reference_mapping is not None:
        patch["reference_mapping"] = {k: v.model_dump() for k, v in body.reference_mapping.items()}
    if body.created_at_is_utc is not None:
        patch["created_at_is_utc"] = body.created_at_is_utc
    if body.partition_column is not None:
        patch["partition_column"] = body.partition_column
    saved = ss.save("bigquery", {**cur.model_dump(), **patch}, note="field mapping saved")
    connector._set_status("mapping", True)
    return {"settings": saved.model_dump(), "check": check}


@router.post("/bigquery/activate")
def bq_activate():
    act = connector.activation_check()
    if not act["ready"]:
        raise AppError("SOURCE_NOT_READY", 409, detail=json.dumps(act["requirements"]))
    ss.update("bigquery", {"production_enabled": True}, note="production mode enabled")
    with db.tx() as c:
        db.audit(c, "BIGQUERY_ACTIVATED", "settings", "bigquery", act)
    return {"ok": True, **act}


@router.post("/bigquery/deactivate")
def bq_deactivate():
    ss.update("bigquery", {"production_enabled": False}, note="production mode disabled")
    g = ss.get("general")
    if g.active_source == "BIGQUERY":
        ss.update("general", {"active_source": "DEMO"}, note="BigQuery deactivated -> DEMO")
    return {"ok": True}


# ------------------------------------------------------------------ storage paths & diagnostics
@router.get("/system/paths")
def system_paths():
    """Effective storage locations (decided by the backend only) and where each setting came from."""
    from ..logging_setup import log_file
    d = paths.describe()
    d.pop("runtime_file", None)
    d["active_log_file"] = log_file()
    return d


@router.get("/system/health-check")
def system_health_check(full: bool = False):
    """Read-only SQLite integrity + foreign-key check of the live database."""
    with db.read() as c:
        return db.health_check(c, quick=not full)


@router.get("/system/diagnostics")
def system_diagnostics():
    from .. import diagnostics
    return diagnostics.build()


@router.get("/system/diagnostics.md")
def system_diagnostics_md():
    from .. import diagnostics
    from ..timeutil import now_vn
    content = diagnostics.to_markdown(diagnostics.build())
    return Response(content, media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="demandforecast_diagnostic_{now_vn():%Y%m%d_%H%M%S}.md"'})


@router.post("/system/diagnostics/save")
def system_diagnostics_save():
    from .. import diagnostics
    f = diagnostics.save()
    return {"file": os.path.basename(f), "dir": str(paths.reports_dir())}
