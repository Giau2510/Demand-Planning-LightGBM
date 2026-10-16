"""Local-only hardening: Host allow-list (DNS-rebinding guard) and CSRF protection for state-changing calls.

Browsers cannot attach the custom `X-DF-Client` header to a cross-site request without a CORS preflight,
and CORS is not enabled, so another website cannot trigger jobs or change settings.
"""
from __future__ import annotations

import json
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from . import paths
from .messages import msg

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "testserver"}
CLIENT_HEADER = "x-df-client"


def _host_only(h: str) -> str:
    h = h.strip().lower()
    if h.startswith("["):
        return h.split("]")[0] + "]"
    return h.split(":")[0]


class LocalGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        extra = {x.strip().lower() for x in os.environ.get("DF_ALLOWED_HOSTS", "").split(",") if x.strip()}
        host = _host_only(request.headers.get("host", ""))
        if host not in ALLOWED_HOSTS | extra:
            return JSONResponse({"code": "FORBIDDEN_HOST", "vi": "Host không được phép.", "en": "Host not allowed."},
                                status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/"):
            if request.headers.get(CLIENT_HEADER) != "web":
                return JSONResponse({"code": "CSRF_BLOCKED", "vi": "Thiếu header bảo vệ X-DF-Client.",
                                     "en": "Missing X-DF-Client protection header."}, status_code=403)
            origin = request.headers.get("origin")
            if origin:
                o = _host_only(origin.split("://", 1)[-1])
                if o not in ALLOWED_HOSTS | extra:
                    return JSONResponse({"code": "CSRF_BLOCKED", **{k: v for k, v in msg("CSRF_BLOCKED").items()
                                                                    if k != "code"}}, status_code=403)
        return await call_next(request)


def runtime_file():
    return paths.runtime_file()


def write_runtime(port: int) -> str:
    token = secrets.token_urlsafe(24)
    runtime_file().write_text(json.dumps({"pid": os.getpid(), "port": port, "shutdown_token": token}),
                              encoding="utf-8")
    return token


def read_runtime() -> dict | None:
    try:
        return json.loads(runtime_file().read_text(encoding="utf-8"))
    except Exception:
        return None
