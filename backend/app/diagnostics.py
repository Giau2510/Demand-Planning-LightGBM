"""Diagnostic report: versions, effective paths, DB health, active dataset, scheduler, recent errors.

Never includes: app.env content, credentials/key files, tokens (runtime.json), raw business data.
Free text taken from logs/errors passes through logging_setup.redact and is truncated.
"""
from __future__ import annotations

import json
import platform
import sys
from collections import deque

from . import __version__, db, paths
from .logging_setup import redact
from .timeutil import now_iso, now_vn


def _safe(text, n: int = 300):
    return None if text is None else redact(str(text))[:n]


def build() -> dict:
    rep: dict = {"generated_at": now_iso(), "app_version": __version__, "python": sys.version.split()[0],
                 "platform": platform.platform(), "paths": paths.describe()}
    rep["paths"].pop("runtime_file", None)  # holds the shutdown token; its location is irrelevant here
    try:
        with db.read() as c:
            rep["database"] = {"connected": True,
                               "schema_version": c.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                               **db.health_check(c, quick=True),
                               "row_counts": {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in (
                                   "import_batches", "order_lines", "demand_daily", "training_runs",
                                   "forecast_runs", "forecast_values", "d0_snapshots", "job_runs")}}
            from . import settings_service as ss
            from .data.demand import resolve_scope
            from .messages import AppError
            g = ss.get("general", c)
            rep["source_mode"] = g.active_source
            try:
                scope = resolve_scope(c)
                rep["active_dataset"] = {"ok": True, **scope}
            except AppError as e:
                rep["active_dataset"] = {"ok": False, "code": e.code, "detail": _safe(e.detail)}
            rep["batches"] = db.rows(c, "SELECT data_source, status, COUNT(*) AS n FROM import_batches "
                                        "GROUP BY data_source, status")
            hb = db.one(c, "SELECT value_json FROM sync_state WHERE name='scheduler_heartbeat'")
            rep["scheduler"] = {"last_heartbeat": json.loads(hb["value_json"]) if hb else None}
            rep["recent_jobs"] = db.rows(c, "SELECT job_type, status, reason_code, trigger, created_at FROM job_runs "
                                            "ORDER BY created_at DESC, rowid DESC LIMIT 15")
            rep["recent_failures"] = [
                {**r, "error": _safe(r["error"])} for r in db.rows(
                    c, "SELECT job_type, reason_code, error, finished_at FROM job_runs WHERE status='FAILED' "
                       "ORDER BY created_at DESC, rowid DESC LIMIT 10")]
            rep["recent_alerts"] = db.rows(c, "SELECT level, code, created_at FROM alerts ORDER BY id DESC LIMIT 15")
            bq = ss.get("bigquery", c)
            rep["bigquery"] = {"project_id": bq.project_id, "dataset_id": bq.dataset_id or None,
                               "table": bq.source_table or None, "auth_method": bq.auth_method,
                               "service_account_file_set": bool(bq.service_account_file),
                               "production_enabled": bq.production_enabled}
    except Exception as e:  # noqa: BLE001 - the report must still be produced
        rep["database"] = {"connected": False, "error": f"{type(e).__name__}: {_safe(e)}"}
    rep["recent_log_errors"] = _recent_log_errors()
    return rep


def _recent_log_errors(limit: int = 20) -> list[dict]:
    try:
        f = paths.resolve_all()["logs_dir"] / "app.log"
        if not f.exists():
            return []
        tail: deque = deque(maxlen=2000)
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                tail.append(line)
        out = []
        for line in tail:
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if j.get("level") in ("ERROR", "CRITICAL"):
                ctx = j.get("ctx") or {}
                out.append({"ts": j.get("ts"), "logger": j.get("logger"), "msg": _safe(j.get("msg"), 200),
                            "code": ctx.get("code"), "request_id": ctx.get("request_id"), "job_id": ctx.get("job_id"),
                            "exception": _safe((j.get("exc") or "").strip().splitlines()[-1] if j.get("exc") else None)})
        return out[-limit:]
    except Exception:  # noqa: BLE001
        return []


def to_markdown(rep: dict) -> str:
    L = [f"# DemandForecasting diagnostic report", "", f"- Generated: {rep['generated_at']} (UTC)",
         f"- App version: {rep['app_version']} · Python {rep['python']} · {rep['platform']}",
         f"- Source mode: {rep.get('source_mode')}", ""]
    L += ["## Paths", "", "| Item | Path | Source |", "|---|---|---|"]
    p = rep["paths"]
    for k in ("data_dir", "db_path", "logs_dir", "backups_dir", "reports_dir", "models_dir", "uploads_dir",
              "storage_config"):
        L.append(f"| {k} | `{p.get(k)}` | {p.get('sources', {}).get(k, '')} |")
    L += [f"", f"DB exists: {p.get('db_exists')} · size: {p.get('db_size_bytes')} · WAL/SHM: {p.get('wal_files')}", ""]
    d = rep.get("database", {})
    L += ["## Database", "", "```json", json.dumps(d, indent=2, default=str), "```", ""]
    L += ["## Active dataset", "", "```json", json.dumps(rep.get("active_dataset"), indent=2, default=str), "```", ""]
    for k in ("batches", "scheduler", "recent_jobs", "recent_failures", "recent_alerts", "bigquery", "recent_log_errors"):
        L += [f"## {k}", "", "```json", json.dumps(rep.get(k), indent=2, default=str), "```", ""]
    return "\n".join(L)


def save(out_dir=None) -> str:
    rep = build()
    out_dir = out_dir or paths.reports_dir()
    f = out_dir / f"demandforecast_diagnostic_{now_vn():%Y%m%d_%H%M%S}.md"
    f.write_text(to_markdown(rep), encoding="utf-8")
    return str(f)
