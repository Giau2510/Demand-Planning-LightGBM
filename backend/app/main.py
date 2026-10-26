"""FastAPI application: API under /api, the built React UI served from /."""
from __future__ import annotations

import logging
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from . import __version__, db, paths
from .api import bq_routes, data_routes, explainer_routes, forecast_routes, history_routes, ops_routes, schedule_routes
from .jobs import scheduler as sched_mod
from .logging_setup import setup_logging
from .messages import AppError
from .security import LocalGuardMiddleware

log = logging.getLogger("df.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage = paths.ensure_storage()   # raises StorageError -> server refuses to start (no silent empty DB)
    setup_logging(os.environ.get("DF_LOG_LEVEL", "INFO"))
    res = db.migrate()
    d = paths.describe()
    log.info("app starting", extra={"ctx": {
        "version": __version__, "migrations": res,
        "paths": {k: d[k] for k in ("data_dir", "db_path", "logs_dir", "backups_dir", "reports_dir", "models_dir",
                                    "storage_config")},
        "path_sources": d["sources"], "db_created_now": not storage["db_exists"]}})
    from .data.importer import cleanup_stale_uploads
    cleanup_stale_uploads()
    # 1.2.5: published runs not yet in the forecast history (published before 1.2.5, or a failed recording) are recorded
    # from the immutable forecast runs; never blocks the start
    try:
        from . import forecast_history
        rec = forecast_history.reconcile()
        if rec["missing"]:
            log.info("forecast history reconciled", extra={"ctx": {"recorded": rec["recorded"], "errors": rec["errors"]}})
    except Exception:  # noqa: BLE001
        log.warning("forecast history not reconciled at start", exc_info=True)
    if os.environ.get("DF_DISABLE_SCHEDULER") != "1":
        sched_mod.SCHEDULER = sched_mod.Scheduler(int(os.environ.get("DF_TICK_SECONDS", "30")))
        sched_mod.SCHEDULER.start()
    yield
    if sched_mod.SCHEDULER:
        sched_mod.SCHEDULER.stop()
        sched_mod.SCHEDULER = None
    log.info("app stopped")


def create_app() -> FastAPI:
    app = FastAPI(title="Demand Forecasting", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(LocalGuardMiddleware)

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or secrets.token_hex(6)
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    def _err(request: Request, code: str, status: int, detail: str | None = None, **extra) -> JSONResponse:
        body = AppError(code, status, detail=detail).to_dict()
        body.update(extra)
        body["request_id"] = getattr(request.state, "request_id", None)
        return JSONResponse(body, status_code=status)

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        body = exc.to_dict()
        body["request_id"] = getattr(request.state, "request_id", None)
        return JSONResponse(body, status_code=exc.status)

    def _fmt(errors) -> str:
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in errors)

    @app.exception_handler(RequestValidationError)
    async def _req_validation(request: Request, exc: RequestValidationError):
        return _err(request, "VALIDATION_ERROR", 422, _fmt(exc.errors()))

    @app.exception_handler(ValidationError)
    async def _validation(request: Request, exc: ValidationError):
        return _err(request, "VALIDATION_ERROR", 422, _fmt(exc.errors()))

    @app.exception_handler(paths.StorageError)
    async def _storage(request: Request, exc: paths.StorageError):
        log.error("storage error", extra={"ctx": {"code": exc.code, "detail": exc.detail,
                                                  "request_id": getattr(request.state, "request_id", None)}})
        return _err(request, exc.code, 503, exc.detail)

    @app.exception_handler(db.ConsistencyError)
    async def _consistency(request: Request, exc: db.ConsistencyError):
        log.error("consistency check failed (rolled back)", exc_info=exc,
                  extra={"ctx": {"path": request.url.path, "request_id": getattr(request.state, "request_id", None)}})
        return _err(request, "DATA_CONSISTENCY", 409)

    @app.exception_handler(sqlite3.Error)
    async def _sqlite(request: Request, exc: sqlite3.Error):
        # full traceback in the log; the user gets a stable code + safe next step, never the raw exception
        log.error("database error", exc_info=exc,
                  extra={"ctx": {"path": request.url.path, "request_id": getattr(request.state, "request_id", None),
                                 "type": type(exc).__name__}})
        if isinstance(exc, sqlite3.IntegrityError):
            return _err(request, "DATABASE_CONSTRAINT", 409)
        if isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower():
            return _err(request, "DATABASE_LOCKED", 503)
        return _err(request, "DATABASE_ERROR", 500)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.error("unhandled error", exc_info=exc,
                  extra={"ctx": {"path": request.url.path, "request_id": getattr(request.state, "request_id", None)}})
        return _err(request, "INTERNAL_ERROR", 500)

    app.include_router(ops_routes.router)
    app.include_router(bq_routes.router)
    app.include_router(schedule_routes.router)
    app.include_router(data_routes.router)
    app.include_router(forecast_routes.router)
    app.include_router(history_routes.router)
    app.include_router(explainer_routes.router)

    dist = paths.frontend_dist()
    if (dist / "index.html").exists():
        if (dist / "assets").exists():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse({"code": "NOT_FOUND"}, status_code=404)
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def no_ui():
            return JSONResponse({"message": "UI not built. Run scripts\\build-frontend.ps1", "api_docs": "/api/docs"})
    return app


app = create_app()
