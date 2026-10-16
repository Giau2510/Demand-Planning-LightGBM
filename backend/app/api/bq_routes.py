"""1.1.6: Google sign-in (OAuth), runtime identity diagnostics, SQL feeds (history / D0) and sync job status."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .. import db
from .. import settings_service as ss
from ..bq import connector, oauth, sql_sources
from ..messages import AppError
from ..timeutil import now_vn, today_vn, vn_slot
from . import background

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ identity + OAuth
@router.get("/bigquery/identity")
def bq_identity():
    """Which Windows account runs the backend, where ADC is looked up, the in-app Google sign-in status and the
    BigQuery target the access check uses (for the administrator checklist; no secrets)."""
    bq = ss.get("bigquery")
    return {"runtime": oauth.runtime_identity(), "oauth": oauth.status(),
            "target": {"project": bq.project_id, "location": bq.location, "dataset": bq.dataset_id,
                       "table": bq.source_table}}


class OAuthClientBody(BaseModel):
    client_id: str
    client_secret: str | None = Field(default=None, max_length=512)


@router.post("/bigquery/oauth/client")
def bq_oauth_client(body: OAuthClientBody):
    return oauth.save_client(body.client_id.strip(), body.client_secret)


class OAuthClientFileBody(BaseModel):
    content: str = Field(max_length=16384)


@router.post("/bigquery/oauth/client-file")
def bq_oauth_client_file(body: OAuthClientFileBody):
    """The client JSON file from the Google Cloud Console, read by the browser and sent once; parsed in memory only."""
    return oauth.save_client_file(body.content)


@router.post("/bigquery/oauth/start")
def bq_oauth_start():
    return oauth.start(open_browser=True)


@router.post("/bigquery/oauth/cancel")
def bq_oauth_cancel():
    return oauth.cancel()


@router.post("/bigquery/oauth/logout")
def bq_oauth_logout():
    return oauth.logout()


@router.post("/bigquery/access-check")
def bq_access_check():
    """Separate gates: auth -> API + dataset -> location -> table metadata -> query job -> schema/mapping."""
    return connector.access_check()


@router.get("/bigquery/oauth/status")
def bq_oauth_status():
    return oauth.status()


# ------------------------------------------------------------------ SQL feeds
def _kind(kind: str) -> str:
    if kind not in sql_sources.KINDS:
        raise AppError("BATCH_NOT_FOUND", 404, detail=kind)
    return kind


@router.get("/sql-sources")
def sql_sources_view():
    return {k: sql_sources.view(k) for k in sql_sources.KINDS}


class SqlBody(BaseModel):
    sql: str = Field(max_length=100_000)
    note: str | None = Field(default=None, max_length=300)


@router.post("/sql-sources/{kind}/versions")
def sql_save(kind: str, body: SqlBody):
    """Save a new version. It is NOT used by any job until BigQuery validates it."""
    return sql_sources.save_version(_kind(kind), body.sql, body.note)


def _invalidate_history(kind: str, note: str) -> None:
    if kind == "history" and ss.get("bigquery").production_enabled:
        ss.update("bigquery", {"production_enabled": False}, note=note)


@router.post("/sql-sources/{kind}/versions/{vid}/validate")
def sql_validate(kind: str, vid: int):
    before = sql_sources.source(_kind(kind)).active_version_id
    res = connector.validate_sql_version(kind, vid)
    if res["active_version_id"] != before:
        _invalidate_history(kind, f"history SQL changed to version {vid} -> production must be re-verified")
    return res


class PreviewBody(BaseModel):
    limit: int = 20


@router.post("/sql-sources/{kind}/versions/{vid}/preview")
def sql_preview(kind: str, vid: int, body: PreviewBody | None = None):
    return connector.preview_sql(_kind(kind), vid, (body.limit if body else 20))


@router.post("/sql-sources/{kind}/versions/{vid}/test")
def sql_test(kind: str, vid: int):
    return connector.test_sql_version(_kind(kind), vid)


@router.post("/sql-sources/{kind}/versions/{vid}/restore")
def sql_restore(kind: str, vid: int):
    before = sql_sources.source(_kind(kind)).active_version_id
    res = sql_sources.restore(kind, vid)
    if res["active_version_id"] != before:
        _invalidate_history(kind, f"history SQL restored to version {vid} -> production must be re-verified")
    return res


class OptionsBody(BaseModel):
    mode: str | None = None
    key_columns: list[str] | None = None
    key_duplicate_policy: str | None = None
    schedule_enabled: bool | None = None


@router.put("/sql-sources/{kind}/options")
def sql_options(kind: str, body: OptionsBody):
    res = sql_sources.set_options(_kind(kind), body.mode, body.key_columns, body.key_duplicate_policy, body.schedule_enabled)
    if body.mode is not None or body.key_columns is not None or body.key_duplicate_policy is not None:
        _invalidate_history(kind, "history feed options changed -> production must be re-verified")
    return res


# ------------------------------------------------------------------ sync jobs status + backfill
def _next_runs(times: list[str], now: datetime, n: int = 3) -> list[str]:
    out = []
    d = now.date()
    while len(out) < n and d <= now.date() + timedelta(days=2):
        for t in sorted(times):
            slot = vn_slot(d, t)
            if slot > now:
                out.append(slot.isoformat())
                if len(out) >= n:
                    break
        d += timedelta(days=1)
    return out


def _last(c, job_type: str) -> dict | None:
    r = db.one(c, "SELECT id, idempotency_key, trigger, scheduled_for, status, attempt, max_attempts, next_attempt_at, "
                  "created_at, started_at, finished_at, reason_code, error, result_json FROM job_runs WHERE job_type=? "
                  "AND status != 'SKIPPED' ORDER BY created_at DESC, rowid DESC LIMIT 1", (job_type,))
    if not r:
        return None
    res = (json.loads(r.pop("result_json") or "{}") or {}).get("result") or {}
    keep = ("rows_read", "rows_valid", "rows_error", "excluded_by_reason", "series_days_written", "series_days_new",
            "series_days_updated", "series_days_removed", "series_rows_new", "snapshot_id", "series", "window_start",
            "window_end", "mode", "backfill", "sql_source", "key_duplicate_rows", "exact_duplicate_rows",
            "source_batch_id", "already_written", "dates_in_output", "warnings", "qty_valid", "full_reload")
    r["result"] = {k: res.get(k) for k in keep if k in res}
    return r


@router.get("/sync/status")
def sync_status():
    sched = ss.get("schedule")
    g = ss.get("general")
    now = now_vn()
    with db.read() as c:
        last = {jt: _last(c, jt) for jt in ("D1_SYNC", "D0_SYNC")}
        skipped = {jt: db.one(c, "SELECT id, scheduled_for, reason_code, created_at FROM job_runs WHERE job_type=? AND "
                                 "status='SKIPPED' ORDER BY created_at DESC, rowid DESC LIMIT 1", (jt,)) for jt in ("D1_SYNC", "D0_SYNC")}
    feeds = {k: sql_sources.view(k) for k in sql_sources.KINDS}

    def feed(k):
        v = feeds[k]
        return {"mode": v["mode"], "active_version_id": v["active_version_id"],
                "active_sha256": (v["active"] or {}).get("sha256"), "key_columns": v["key_columns"],
                "key_duplicate_policy": v["key_duplicate_policy"], "schedule_enabled": v["schedule_enabled"]}
    return {
        "timezone": g.timezone, "active_source": g.active_source,
        "flows_enabled": {"D1_SYNC": sched.d1_enabled, "D0_SYNC": sched.d0_enabled},
        "bigquery_production_enabled": ss.get("bigquery").production_enabled,
        "jobs": {
            "D1_SYNC": {"kind": "history", "schedule": {"times": [sched.d1_signal_poll_start], "fallback": sched.d1_fallback_time,
                                                        "poll_minutes": sched.d1_poll_interval_minutes},
                        "enabled": sched.d1_enabled,
                        "next_runs": _next_runs([sched.d1_signal_poll_start], now, 2) if sched.d1_enabled else [],
                        "applies": g.active_source == "BIGQUERY", "last_run": last["D1_SYNC"],
                        "last_skipped": skipped["D1_SYNC"], "feed": feed("history")},
            "D0_SYNC": {"kind": "d0", "schedule": {"times": sched.d0_times}, "enabled": sched.d0_enabled,
                        "next_runs": _next_runs(sched.d0_times, now, 3) if sched.d0_enabled else [],
                        "applies": g.active_source in ("BIGQUERY", "DEMO"), "last_run": last["D0_SYNC"],
                        "last_skipped": skipped["D0_SYNC"], "feed": feed("d0")},
        },
        "retry": {"max_attempts": sched.max_attempts, "base_seconds": sched.retry_base_seconds,
                  "max_seconds": sched.retry_max_seconds, "timeout_seconds": sched.timeout_seconds},
        "notes": {"vi": "D-1 chạy một lần/ngày, D0 chạy theo các giờ đã cấu hình; hai luồng có công tắc riêng (trang "
                        "Lịch chạy dữ liệu), không chạy chồng (khóa theo loại job), không tự kích hoạt huấn luyện.",
                  "en": "D-1 runs once a day, D0 at the configured times; each flow has its own switch (Data schedules "
                        "page), never overlapping (lock per job type), never trigger training."},
    }


class BackfillBody(BaseModel):
    start: str
    end: str


@router.post("/sync/backfill")
def sync_backfill(body: BackfillBody):
    """Re-read an explicit history window (user request only; bounded; requires production + validation)."""
    try:
        s, e = date.fromisoformat(body.start), date.fromisoformat(body.end)
    except ValueError as ex:
        raise AppError("VALIDATION_ERROR", 422, detail=str(ex)) from ex
    if e < s or e >= today_vn():
        raise AppError("VALIDATION_ERROR", 422, detail="end must be >= start and before today (D-1 or older)")
    return background.submit("D1_SYNC", {"backfill_start": str(s), "backfill_end": str(e)})
