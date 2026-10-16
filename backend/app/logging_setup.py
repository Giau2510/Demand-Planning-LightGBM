"""Structured JSON logging with size-based rotation. Never pass secrets or full order data as context."""
from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys

from . import paths
from .timeutil import now_iso

_SECRET_RE = re.compile(r'("?(?:private_key|password|secret|token|access_token|client_secret)"?\s*[:=]\s*)'
                        r'("[^"]*"|\S+)', re.I)


def redact(text: str) -> str:
    return _SECRET_RE.sub(r"\1***", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": now_iso(), "level": record.levelname, "logger": record.name,
                   "msg": redact(record.getMessage())}
        ctx = getattr(record, "ctx", None)
        if isinstance(ctx, dict):
            payload["ctx"] = {k: (redact(v) if isinstance(v, str) else v) for k, v in ctx.items()}
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def setup_logging(level: str = "INFO", max_bytes: int = 10 * 1024 * 1024, backups: int = 5) -> None:
    global _configured
    if _configured:
        return
    root = logging.getLogger("df")
    root.setLevel(level)
    file_error = None
    try:
        fh = logging.handlers.RotatingFileHandler(paths.logs_dir() / "app.log", maxBytes=max_bytes,
                                                  backupCount=backups, encoding="utf-8")
        fh.setFormatter(JsonFormatter())
        root.addHandler(fh)
    except (OSError, paths.StorageError) as e:  # e.g. configured drive unplugged: console only, say so
        file_error = f"{type(e).__name__}: {e}"
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(JsonFormatter())
    root.addHandler(sh)
    root.propagate = False
    _configured = True
    if file_error:
        root.warning("file logging unavailable - console only", extra={"ctx": {"error": file_error}})


def log_file() -> str | None:
    for h in logging.getLogger("df").handlers:
        if isinstance(h, logging.handlers.RotatingFileHandler):
            return h.baseFilename
    return None


def reset_logging() -> None:
    """Close file handlers (tests / storage switches) so the next setup_logging() re-resolves the log folder."""
    global _configured
    root = logging.getLogger("df")
    for h in list(root.handlers):
        h.close()
        root.removeHandler(h)
    _configured = False
