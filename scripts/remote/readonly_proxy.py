"""Read-only front of the Demand Forecasting dashboard for a public HTTPS tunnel (Python standard library only).

The tunnel (cloudflared Quick Tunnel) points HERE - http://127.0.0.1:<listen port> - never at the app itself:
  * only GET / HEAD; any other method -> 405 REMOTE_READ_ONLY (no training, import, settings, sync, backup, shutdown);
  * /api: an allow-list of the read endpoints the dashboard pages use; everything else -> 403 REMOTE_FORBIDDEN
    (system paths, diagnostics, backups, audit, settings history, Google identity / OAuth, BigQuery status, uploads,
    duplicate-report files, OpenAPI docs) and no read that can write: 1.2.11 audit - GET /api/data-quality stores a
    report when none is cached, so only /api/data-quality/history is open; HEAD is refused on /api (UI only);
  * JSON answers are scrubbed: local paths and path / identity fields are replaced, so no folder, account or
    credential location leaves the PC (the app never returns secrets; this removes the locations too);
  * the UI (index.html, /assets, SPA routes) is forwarded; '..', backslashes and encoded separators are refused;
  * the upstream request carries the LOCAL Host header and none of the visitor's headers except Accept*,
    If-None-Match / If-Modified-Since and Range; the app's own Host guard still refuses direct tunnel traffic;
  * per-visitor rate limit and a cap on concurrent upstream calls; listens on 127.0.0.1 only.
Usage: python -I readonly_proxy.py --upstream-port 8765 --listen-port 8766 [--log <file>]
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import http.server
import json
import re
import socketserver
import sys
import threading
import time
import urllib.parse
from collections import defaultdict, deque

VERSION = "1.2.11"
ID = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}"
FR = r"/api/forecast-runs/" + ID
ALLOWED_API = [re.compile(p + r"\Z") for p in (
    r"/api/health", r"/api/messages", r"/api/methods", r"/api/dashboard", r"/api/alerts",
    r"/api/system/status", r"/api/settings", r"/api/schema/fields",
    r"/api/schedules", r"/api/schedules/(d1|d0|train)", r"/api/scheduler/status", r"/api/sync/status",
    r"/api/jobs", r"/api/jobs/(active|latest)", r"/api/jobs/" + ID,
    r"/api/snapshots", r"/api/snapshots/" + ID, r"/api/snapshots/" + ID + r"/export\.xlsx",
    r"/api/forecast-runs", FR,
    FR + r"/(values|summary|accuracy|explain|export\.xlsx|explain/history\.xlsx|shap-trace|shap-trace/tree)",
    FR + r"/shap-trace\.(xlsx|csv|json)",
    r"/api/training-runs", r"/api/training-runs/" + ID, r"/api/training-runs/" + ID + r"/backtest-points\.xlsx",
    r"/api/model/training-explain", r"/api/features/(catalog|registry)",
    r"/api/data-quality/history",                 # 1.2.11: /api/data-quality can INSERT a report (cache miss)
    r"/api/sql-sources", r"/api/bigquery/source-tables", r"/api/bigquery/d0-mapping",
    r"/api/imports", r"/api/imports/" + ID,
    r"/api/history/(overview|summary|rows|export\.xlsx)",       # 1.2.5: Forecast & actual history (GET, read-only)
)]
# query parameters that would start heavy work on a read endpoint
DENIED_QUERY = {"/api/system/health-check": {"full"}}
FORWARD_HEADERS = ("accept", "accept-language", "accept-encoding", "if-none-match", "if-modified-since", "range")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding",
       "upgrade", "content-length", "server", "date"}
SCRUB_KEYS = {"data_dir", "db_path", "logs_dir", "backups_dir", "reports_dir", "models_dir", "storage_config",
              "runtime_file", "active_log_file", "model_path", "service_account_file", "oauth_client_id", "adc_path",
              "windows_user", "user", "account", "principal", "path", "dir", "file_path"}
WIN_PATH = re.compile(r"(?:[A-Za-z]:\\|\\\\)[^\s\"'<>|]*")
HIDDEN = "<hidden>"
BANNER = ('<div id="df-remote-banner" style="position:fixed;left:0;right:0;bottom:0;z-index:99999;padding:6px 12px;'
          'background:#1f3a5f;color:#fff;font:13px/1.4 system-ui,sans-serif;text-align:center">'
          'Chế độ xem từ xa — CHỈ ĐỌC. Các nút chạy / lưu / nhập dữ liệu bị từ chối. '
          '· Remote view — READ ONLY.</div>')
MSG = {
    "REMOTE_READ_ONLY": ("Link xem từ xa chỉ cho phép XEM. Thao tác chạy, lưu, nhập dữ liệu hay đổi cấu hình chỉ làm "
                         "được trên máy chạy ứng dụng.", "The remote link is read-only. Running, saving, importing or "
                         "changing settings is only possible on the PC that runs the app."),
    "REMOTE_FORBIDDEN": ("Trang/thông tin này không mở qua link từ xa (thông tin quản trị của máy chạy ứng dụng).",
                         "This page/information is not available through the remote link (administration data)."),
    "REMOTE_BAD_PATH": ("Đường dẫn không hợp lệ.", "Invalid path."),
    "REMOTE_RATE_LIMIT": ("Quá nhiều yêu cầu trong thời gian ngắn — vui lòng thử lại sau ít giây.",
                          "Too many requests in a short time — please retry in a few seconds."),
    "REMOTE_BUSY": ("Máy chủ đang bận — vui lòng thử lại.", "The server is busy — please retry."),
    "REMOTE_APP_DOWN": ("Ứng dụng trên máy chạy đang tắt hoặc chưa sẵn sàng.", "The app on the host PC is not running."),
}


def scrub(o):
    """Replace path / identity fields and any Windows path inside strings (recursive)."""
    if isinstance(o, dict):
        return {k: (HIDDEN if (k in SCRUB_KEYS and isinstance(v, (str, int, float)) and v not in ("", None))
                    else scrub(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    if isinstance(o, str) and ("\\" in o):
        return WIN_PATH.sub(HIDDEN, o)
    return o


def classify(method: str, raw_path: str) -> tuple[int, str] | None:
    """None = forward; else (status, code). Pure function (unit-tested)."""
    if method not in ("GET", "HEAD"):
        return 405, "REMOTE_READ_ONLY"
    raw = raw_path.split("?", 1)[0]
    if not raw.startswith("/") or raw.startswith("//"):      # '//host/x' would be read as another host
        return 400, "REMOTE_BAD_PATH"
    parts = urllib.parse.urlsplit(raw_path)
    path = parts.path
    low = path.lower()
    if (not path.startswith("/") or "\\" in path or ".." in path or "%2e" in low or "%2f" in low or "%5c" in low
            or "//" in path or len(raw_path) > 4096 or "\x00" in raw_path):
        return 400, "REMOTE_BAD_PATH"
    if path == "/__remote/health":
        return None
    if path.startswith("/api/") or path == "/api":
        if method == "HEAD":                                # 1.2.11: never run an /api handler for a HEAD
            return 405, "REMOTE_READ_ONLY"
        if not any(p.match(path) for p in ALLOWED_API):
            return 403, "REMOTE_FORBIDDEN"
        q = urllib.parse.parse_qs(parts.query)
        for k in DENIED_QUERY.get(path, ()):
            if any(v.lower() not in ("", "0", "false") for v in q.get(k, [])):
                return 403, "REMOTE_FORBIDDEN"
        return None
    return None      # UI: index.html, /assets/*, SPA routes (served by the app from its web folder only)


class Limiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            if len(self.hits) > 10000:      # bounded memory
                self.hits.clear()
            return True


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "df-remote"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    cfg: dict = {}

    def log_message(self, fmt, *args):      # access log handled in _log
        pass

    def _client(self) -> str:
        ip = self.headers.get("cf-connecting-ip") or self.client_address[0]
        return hashlib.sha256(ip.encode()).hexdigest()[:10]

    def _log(self, status: int, t0: float, note: str = "") -> None:
        line = (f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {self._client()} {self.command} "
                f"{urllib.parse.urlsplit(self.path).path[:200]} {status} {int((time.monotonic() - t0) * 1000)}ms {note}")
        with self.cfg["log_lock"]:
            f = self.cfg.get("log")
            if f:
                f.write(line + "\n")
                f.flush()

    def _send(self, status: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in self._security_headers().items():
            self.send_header(k, v)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _security_headers(self) -> dict:
        h = {"X-DF-Remote": "read-only", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer",
             "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY"}
        if self.path.startswith("/api/"):
            h["Cache-Control"] = "no-store"
        return h

    def _error(self, status: int, code: str, t0: float) -> None:
        vi, en = MSG[code]
        body = json.dumps({"code": code, "vi": vi, "en": en, "detail": f"{self.command} {urllib.parse.urlsplit(self.path).path}"[:300],
                           "category": "INPUT"}, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", {"Allow": "GET, HEAD"} if status == 405 else None)
        self._log(status, t0, code)

    def _handle(self) -> None:
        t0 = time.monotonic()
        verdict = classify(self.command, self.path)
        if verdict:
            self._error(verdict[0], verdict[1], t0)
            return
        if not self.cfg["limiter"].allow(self._client()):
            self._error(429, "REMOTE_RATE_LIMIT", t0)
            return
        if self.path == "/__remote/health":
            up = _upstream_ok(self.cfg)
            self._send(200, json.dumps({"ok": True, "upstream": up, "proxy": VERSION}).encode(), "application/json")
            self._log(200, t0)
            return
        if not self.cfg["sem"].acquire(timeout=20):
            self._error(503, "REMOTE_BUSY", t0)
            return
        try:
            self._forward(t0)
        finally:
            self.cfg["sem"].release()

    def _forward(self, t0: float) -> None:
        headers = {k: v for k, v in ((h, self.headers.get(h)) for h in FORWARD_HEADERS) if v}
        headers["Host"] = f"127.0.0.1:{self.cfg['upstream_port']}"
        headers["X-DF-Remote"] = "read-only"
        try:
            conn = http.client.HTTPConnection("127.0.0.1", self.cfg["upstream_port"], timeout=self.cfg["timeout"])
            conn.request(self.command, self.path, headers=headers)
            resp = conn.getresponse()
        except OSError:
            self._error(502, "REMOTE_APP_DOWN", t0)
            return
        try:
            ctype = resp.getheader("Content-Type", "application/octet-stream")
            enc = (resp.getheader("Content-Encoding") or "").lower()
            out_headers = {k: v for k, v in resp.getheaders() if k.lower() not in HOP and k.lower() != "content-type"}
            body = resp.read() if self.command != "HEAD" else b""
            if not enc and body and "application/json" in ctype and len(body) < 50 * 1024 * 1024:
                try:
                    body = json.dumps(scrub(json.loads(body)), ensure_ascii=False).encode("utf-8")
                except ValueError:
                    pass
            elif not enc and body and "text/html" in ctype:
                html = body.decode("utf-8", "replace")
                if "</body>" in html and "df-remote-banner" not in html:
                    html = html.replace("</body>", BANNER + "</body>", 1)
                html = html.replace("<head>", '<head><meta name="robots" content="noindex,nofollow">', 1)
                body = html.encode("utf-8")
            self.send_response(resp.status)
            self.send_header("Content-Type", ctype)
            for k, v in out_headers.items():
                self.send_header(k, v)
            for k, v in self._security_headers().items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body) if self.command != "HEAD" else resp.getheader("Content-Length") or 0))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            self._log(resp.status, t0)
        finally:
            conn.close()

    def do_GET(self):
        self._handle()

    def do_HEAD(self):
        self._handle()

    def _refuse(self):
        t0 = time.monotonic()
        n = int(self.headers.get("content-length") or 0)
        if 0 < n <= 1024 * 1024:     # drain a small body so the connection stays usable; never forwarded
            self.rfile.read(n)
        self.close_connection = True
        self._error(405, "REMOTE_READ_ONLY", t0)

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = do_CONNECT = _refuse


def _upstream_ok(cfg) -> bool:
    try:
        c = http.client.HTTPConnection("127.0.0.1", cfg["upstream_port"], timeout=3)
        c.request("GET", "/api/health", headers={"Host": f"127.0.0.1:{cfg['upstream_port']}"})
        ok = c.getresponse().status == 200
        c.close()
        return ok
    except OSError:
        return False


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = False


def make_server(upstream_port: int, listen_port: int, log_path: str | None = None, per_minute: int = 300,
                max_concurrent: int = 6, timeout: int = 180) -> Server:
    cfg = {"upstream_port": upstream_port, "limiter": Limiter(per_minute), "sem": threading.BoundedSemaphore(max_concurrent),
           "timeout": timeout, "log_lock": threading.Lock(),
           "log": open(log_path, "a", encoding="utf-8") if log_path else None}
    handler = type("BoundHandler", (Handler,), {"cfg": cfg})
    return Server(("127.0.0.1", listen_port), handler)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--upstream-port", type=int, default=8765)
    ap.add_argument("--listen-port", type=int, default=8766)
    ap.add_argument("--log")
    ap.add_argument("--per-minute", type=int, default=300)
    a = ap.parse_args(argv)
    srv = make_server(a.upstream_port, a.listen_port, a.log, a.per_minute)
    print(f"df-remote {VERSION}: http://127.0.0.1:{a.listen_port} -> app 127.0.0.1:{a.upstream_port} (read-only)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
