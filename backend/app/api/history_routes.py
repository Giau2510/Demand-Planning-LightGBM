"""Forecast & actual history (1.2.5): read-only views of the stored D+1 forecasts (see forecast_history.py).

GET only. Opening the page never starts a job, a training or a forecast and never writes: the history is recorded
when a forecast is published, the actual is read from the D-1 / D0 data at request time."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from .. import db
from .. import forecast_history as fh
from .. import settings_service as ss
from ..data.demand import resolve_scope
from ..messages import AppError

router = APIRouter(prefix="/api/history")


def _scope(c, scope_key: str | None) -> tuple[str | None, str | None, list[dict], dict | None]:
    """(scope, data source, scopes with history, active scope). Default = the ACTIVE source's scope, even when it has
    no history yet (another source's history is never shown silently in its place)."""
    scopes = fh.scopes(c)
    try:
        active = resolve_scope(c)
    except AppError:
        active = None
    if scope_key:
        sc = next((s for s in scopes if s["scope_key"] == scope_key), None)
        if sc:
            return scope_key, sc["data_source"], scopes, active
        if active and active["scope_key"] == scope_key:
            return scope_key, active["data_source"], scopes, active
        raise AppError("VALIDATION_ERROR", 422, detail="unknown scope_key")
    if active:
        return active["scope_key"], active["data_source"], scopes, active
    return (scopes[0]["scope_key"], scopes[0]["data_source"], scopes, None) if scopes else (None, None, scopes, None)


@router.get("/overview")
def overview(scope_key: str | None = None):
    """Scopes with history, the run dates of the chosen scope with their official session, FC list, today's state."""
    with db.read() as c:
        sk, src, scopes, active = _scope(c, scope_key)
        dl = fh.days(c, sk) if sk else []
        fcs = fh.Query(c, sk).fcs() if dl else []
        bq = ss.get("bigquery", c)
        today = str(fh.today_vn())
    return {"scope_key": sk, "data_source": src, "active_scope_key": (active or {}).get("scope_key"),
            "scopes": [{**s, "active": s["scope_key"] == (active or {}).get("scope_key")} for s in scopes],
            "days": dl, "fcs": fcs, "today": today,
            "today_session": next((d for d in dl if d["run_date"] == today), None),
            "completion_signal_configured": bool(bq.completion_table and bq.completion_date_column)
            if src == "BIGQUERY" else False}


def _query(c, scope_key, run_from, run_to, fc_id, q, actual_status):
    sk, _src, _s, _a = _scope(c, scope_key)
    return fh.Query(c, sk, run_from, run_to, fc_id, q, actual_status) if sk else None


@router.get("/summary")
def summary(scope_key: str | None = None, run_from: str | None = None, run_to: str | None = None,
            fc_id: str | None = None, q: str | None = None, actual_status: str | None = None):
    """KPI, one chart point per run date of the range (gaps stay gaps) and the sessions of those run dates."""
    with db.read() as c:
        qy = _query(c, scope_key, run_from, run_to, fc_id, q, actual_status)
        if qy is None:
            return {"scope_key": None, "kpi": None, "daily": [], "sessions": [], "actual_context": [], "filters": {}}
        daily = qy.daily()
        return {"scope_key": qy.scope_key, "data_source": qy.data_source, "filters": qy.filters, "today": str(qy.today),
                "kpi": qy.kpi(daily), "daily": daily, "sessions": fh.sessions(c, qy.scope_key, qy.run_from, qy.run_to),
                "actual_context": list(qy.ctx.values()),
                "matching_skus": len(qy.skus) if qy.skus is not None else None}


@router.get("/rows")
def rows(scope_key: str | None = None, run_from: str | None = None, run_to: str | None = None,
         fc_id: str | None = None, q: str | None = None, actual_status: str | None = None, sort: str = "date",
         limit: int = 100, offset: int = 0):
    """SKU x FC detail of the same filter, one page (limit <= 1000)."""
    with db.read() as c:
        qy = _query(c, scope_key, run_from, run_to, fc_id, q, actual_status)
        if qy is None:
            return {"total": 0, "rows": [], "filters": {}}
        return {"total": qy.count(), "rows": list(qy.rows(sort, max(1, min(int(limit), 1000)), max(0, int(offset)))),
                "filters": qy.filters, "sort": sort}


@router.get("/export.xlsx")
def export(scope_key: str | None = None, run_from: str | None = None, run_to: str | None = None,
           fc_id: str | None = None, q: str | None = None, actual_status: str | None = None, sort: str = "date",
           lang: str = "vi"):
    """Excel of ALL rows of the current filter (Info, sessions, per day, SKU x FC detail) in the UI language."""
    from ..export_i18n import history_labels
    lang, L = history_labels(lang)
    with db.read() as c:
        qy = _query(c, scope_key, run_from, run_to, fc_id, q, actual_status)
        if qy is None:
            raise AppError("NO_ACTIVE_DATASET", 409)
        content = fh.export_xlsx(qy, L, sort)
    name = f"forecast-history-{qy.data_source or 'NA'}-{qy.run_from}-{qy.run_to}-{lang}.xlsx"
    return Response(content, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
