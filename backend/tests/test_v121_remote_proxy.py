"""1.2.1 remote dashboard: the read-only proxy in front of the public HTTPS tunnel (scripts/remote/readonly_proxy.py).
Kind of evidence: unit + local integration (real sockets, a FAKE upstream app on 127.0.0.1; no tunnel, no Internet).
The real tunnel run is recorded in the 1.2.1 report."""
import http.client
import http.server
import importlib.util
import json
import re
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("readonly_proxy", ROOT / "scripts" / "remote" / "readonly_proxy.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


@pytest.mark.parametrize("method,path,expect", [
    ("GET", "/", None), ("GET", "/results", None), ("GET", "/assets/index-abc.js", None),
    ("GET", "/api/health", None), ("GET", "/api/dashboard?horizon=7", None), ("GET", "/api/system/status", None),
    ("GET", "/api/forecast-runs/FCR-20261017-1/values?limit=50", None),
    ("GET", "/api/forecast-runs/FCR-1/export.xlsx?lang=vi", None), ("GET", "/api/snapshots/SNP-1", None),
    ("GET", "/api/schedules", None), ("GET", "/api/data-quality", None), ("GET", "/api/data-quality?refresh=false", None),
    ("HEAD", "/api/health", None),
    ("POST", "/api/training/run", (405, "REMOTE_READ_ONLY")), ("PUT", "/api/settings/model", (405, "REMOTE_READ_ONLY")),
    ("DELETE", "/api/imports/X", (405, "REMOTE_READ_ONLY")), ("POST", "/api/system/shutdown", (405, "REMOTE_READ_ONLY")),
    ("OPTIONS", "/api/health", (405, "REMOTE_READ_ONLY")),
    ("GET", "/api/system/paths", (403, "REMOTE_FORBIDDEN")), ("GET", "/api/system/diagnostics.md", (403, "REMOTE_FORBIDDEN")),
    ("GET", "/api/system/backups", (403, "REMOTE_FORBIDDEN")), ("GET", "/api/audit", (403, "REMOTE_FORBIDDEN")),
    ("GET", "/api/bigquery/identity", (403, "REMOTE_FORBIDDEN")), ("GET", "/api/bigquery/status", (403, "REMOTE_FORBIDDEN")),
    ("GET", "/api/bigquery/oauth/status", (403, "REMOTE_FORBIDDEN")), ("GET", "/api/settings/bigquery/history", (403, "REMOTE_FORBIDDEN")),
    ("GET", "/api/docs", (403, "REMOTE_FORBIDDEN")), ("GET", "/api/openapi.json", (403, "REMOTE_FORBIDDEN")),
    ("GET", "/api/bigquery/duplicate-reports/x.xlsx", (403, "REMOTE_FORBIDDEN")),
    ("GET", "/api/imports/uploads/U1/sheets/S", (403, "REMOTE_FORBIDDEN")),
    ("GET", "/api/data-quality?refresh=true", (403, "REMOTE_FORBIDDEN")), ("GET", "/api/data-quality?refresh=1", (403, "REMOTE_FORBIDDEN")),
    ("GET", "/api/system/health-check?full=true", (403, "REMOTE_FORBIDDEN")),
    ("GET", "/assets/../../db/app.db", (400, "REMOTE_BAD_PATH")), ("GET", "/%2e%2e/x", (400, "REMOTE_BAD_PATH")),
    ("GET", "/assets\\..\\x", (400, "REMOTE_BAD_PATH")), ("GET", "//etc/passwd", (400, "REMOTE_BAD_PATH")),
    ("GET", "/api/jobs/..%2fsystem", (400, "REMOTE_BAD_PATH")),
])
def test_only_reads_of_the_dashboard_are_allowed(method, path, expect):
    assert rp.classify(method, path) == expect


def _paths_used_by(files):
    out = set()
    for f in files:
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"""get(?:<[^>]*>)?\(\s*[`"'](/api/[^`"']*)""", text):
            p = re.sub(r"/\$\{[^}]*\}", "/X1", m.group(1))     # path parameters
            p = p.split("${")[0].split("?")[0]                    # query templates (qs(...), optional flags)
            out.add(p)
    return out


def test_every_read_of_the_viewing_pages_passes():
    src = ROOT / "frontend" / "src"
    pages = ["Dashboard", "Results", "Performance", "Snapshots", "Schedules", "Jobs", "DataQuality", "Features",
             "TrainingExplain", "Methodology", "ShapTrace", "ExplainPanel", "Config", "SqlSources", "Batches"]
    files = [src / "pages" / f"{p}.tsx" for p in pages] + [src / "App.tsx", src / "components" / "ui.tsx"]
    used = _paths_used_by(files)
    # 1.2.7: the dashboard reads the shell's status and /api/forecast-runs/{id}/summary (no longer /api/dashboard)
    assert "/api/forecast-runs/X1/summary" in used and "/api/system/status" in used
    by_design = {"/api/settings/X1/history",                     # administration history: not remote
                 "/api/schedules/X1/preview"}                    # 1.2.6 operator dry run: local only (proxy unchanged)
    blocked = sorted(p for p in used - by_design if rp.classify("GET", p) is not None)
    assert blocked == [], blocked
    assert all(rp.classify("GET", p) for p in by_design)


class _Upstream(http.server.BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.seen.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
        if self.path.startswith("/api/"):
            body = json.dumps({"ok": True, "version": "1.2.0", "data_dir": "D:\\Buymed\\data\\runtime",
                               "nested": {"model_path": "C:\\Users\\x\\m.txt", "error": "failed at D:\\a\\b.log now",
                                          "qty": 5, "sku_id": "S1"}}).encode()
            ctype = "application/json"
        else:
            body = b"<html><head><title>DF</title></head><body><div id=\"root\"></div></body></html>"
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_HEAD = do_GET

    def do_POST(self):
        self.seen.append({"method": "POST", "path": self.path})
        self.send_response(200)
        self.end_headers()


@pytest.fixture
def stack():
    _Upstream.seen = []
    up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    px = rp.make_server(up.server_address[1], 0, per_minute=1000)
    threading.Thread(target=px.serve_forever, daemon=True).start()
    yield up, px
    px.shutdown()
    up.shutdown()


def _req(px, method, path, headers=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", px.server_address[1], timeout=10)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    out = (r.status, dict(r.getheaders()), data)
    c.close()
    return out


def test_reads_are_forwarded_with_the_local_host_and_scrubbed(stack):
    up, px = stack
    st, h, data = _req(px, "GET", "/api/dashboard?horizon=7", headers={
        "Host": "random-words.trycloudflare.com", "Cookie": "a=b", "Authorization": "Bearer x", "Origin": "https://evil",
        "X-DF-Client": "web", "Accept": "application/json", "CF-Connecting-IP": "203.0.113.9"})
    assert st == 200 and h["X-DF-Remote"] == "read-only" and h["Cache-Control"] == "no-store"
    assert h["X-Robots-Tag"] == "noindex, nofollow" and h["X-Frame-Options"] == "DENY"
    d = json.loads(data)
    assert d["data_dir"] == "<hidden>" and d["nested"]["model_path"] == "<hidden>"
    assert d["nested"]["error"] == "failed at <hidden> now" and d["nested"]["qty"] == 5 and d["ok"] is True
    seen = {k.lower(): v for k, v in _Upstream.seen[-1]["headers"].items()}
    assert seen["host"] == f"127.0.0.1:{up.server_address[1]}" and seen["accept"] == "application/json"
    assert not {"cookie", "authorization", "origin", "x-df-client", "cf-connecting-ip"} & set(seen)


def test_writes_never_reach_the_app_and_get_a_clear_message(stack):
    up, px = stack
    for m, p in (("POST", "/api/training/run"), ("PUT", "/api/settings/model"), ("POST", "/api/system/shutdown"),
                 ("DELETE", "/api/imports/B1")):
        st, h, data = _req(px, m, p, headers={"X-DF-Client": "web", "Content-Type": "application/json"}, body=b"{}")
        body = json.loads(data)
        assert st == 405 and body["code"] == "REMOTE_READ_ONLY" and "chỉ cho phép XEM" in body["vi"] and h["Allow"] == "GET, HEAD"
    st, _, data = _req(px, "GET", "/api/system/paths")
    assert st == 403 and json.loads(data)["code"] == "REMOTE_FORBIDDEN"
    assert all(s["method"] == "GET" for s in _Upstream.seen) and not any("/system/paths" in s["path"] for s in _Upstream.seen)


def test_html_gets_the_read_only_banner_and_noindex(stack):
    _, px = stack
    st, h, data = _req(px, "GET", "/")
    html = data.decode("utf-8")
    assert st == 200 and 'id="df-remote-banner"' in html and "CHỈ ĐỌC" in html and 'name="robots"' in html
    assert int(h["Content-Length"]) == len(data)
    st, h, data = _req(px, "HEAD", "/api/health")
    assert st == 200 and data == b""


def test_rate_limit_app_down_and_local_bind_only():
    px = rp.make_server(1, 0, per_minute=2)          # nothing listens on port 1: the app is "down"
    threading.Thread(target=px.serve_forever, daemon=True).start()
    try:
        assert px.server_address[0] == "127.0.0.1"
        st, _, data = _req(px, "GET", "/api/health")
        assert st == 502 and json.loads(data)["code"] == "REMOTE_APP_DOWN" and json.loads(data)["vi"]
        st, _, data = _req(px, "GET", "/__remote/health")
        assert st == 200 and json.loads(data)["upstream"] is False
        st, _, data = _req(px, "GET", "/api/health")
        assert st == 429 and json.loads(data)["code"] == "REMOTE_RATE_LIMIT"
    finally:
        px.shutdown()
