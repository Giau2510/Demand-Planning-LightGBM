"""'Sign in with Google' for BigQuery, directly from the app (no Google Cloud CLI needed).

OAuth 2.0 for installed applications: the browser of the logged-in Windows user opens Google's consent page, Google
redirects to a one-shot loopback listener on 127.0.0.1 (random port), the app checks `state`, exchanges the code with
the PKCE verifier (S256) and stores ONLY the refresh token, in Windows Credential Manager of that Windows account.

Requires an OAuth client of type "Desktop app" created by the Google Cloud administrator (the app never creates
or borrows one). Nothing secret is ever logged, stored in the DB, returned to the frontend or written in reports.
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import http.server
import json
import logging
import os
import secrets
import shutil
import threading
import time
import urllib.parse
from pathlib import Path

from .. import db
from .. import settings_service as ss
from ..messages import AppError
from ..timeutil import now_iso
from . import secret_store

log = logging.getLogger("df.oauth")

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
REVOKE_URI = "https://oauth2.googleapis.com/revoke"
USERINFO_URI = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPES = ["openid", "email", "https://www.googleapis.com/auth/bigquery"]
TOKEN_ITEM = "google-oauth-token"
CLIENT_SECRET_ITEM = "google-oauth-client-secret"
FLOW_TIMEOUT_S = 300
HTTP_TIMEOUT_S = 20
# error codes Google returns when the organisation / app policy blocks the sign-in
BLOCKED_ERRORS = {"admin_policy_enforced", "org_internal", "disallowed_useragent", "unauthorized_client",
                  "invalid_client", "access_blocked", "restricted_client", "policy_enforced"}

_http = None
_open_browser = None
_lock = threading.Lock()
_flow: dict = {}


def set_http(obj) -> None:
    """Tests inject an object with .post(url, data=..., timeout=...) and .get(url, headers=..., timeout=...)."""
    global _http
    _http = obj


def set_browser(fn) -> None:
    global _open_browser
    _open_browser = fn


def _client_http():
    if _http is not None:
        return _http
    import requests
    return requests


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


# ------------------------------------------------------------------ persisted status (no secrets)
def _save_status(st: dict) -> None:
    safe = {k: v for k, v in st.items() if k in ("status", "email", "at", "error", "client_id", "verified_at")}
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES ('oauth_status', ?, ?) "
                  "ON CONFLICT(name) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                  (json.dumps(safe), now_iso()))


def _load_status() -> dict:
    with db.read() as c:
        r = db.one(c, "SELECT value_json FROM sync_state WHERE name='oauth_status'")
    return json.loads(r["value_json"]) if r else {}


def _token() -> dict | None:
    raw = secret_store.store().get(TOKEN_ITEM)
    return json.loads(raw) if raw else None


def client_secret_set() -> bool:
    try:
        return bool(secret_store.store().get(CLIENT_SECRET_ITEM))
    except secret_store.SecretStoreError:
        return False


def status() -> dict:
    bq = ss.get("bigquery")
    with _lock:
        live = dict(_flow) if _flow else None
    st = _load_status()
    try:
        tok = _token()
    except secret_store.SecretStoreError as e:
        tok, st = None, {**st, "status": "ERROR", "error": {"code": "OAUTH_STORE_ERROR", "detail": str(e)}}
    if live and live.get("status") == "IN_PROGRESS":
        s = "IN_PROGRESS"
    elif tok and tok.get("client_id") != bq.oauth_client_id:
        s = "CLIENT_CHANGED"         # token of another OAuth client: unusable, sign in again
    elif tok and st.get("status") not in ("REVOKED",):
        s = "SIGNED_IN"
    else:
        s = st.get("status") or "NOT_SIGNED_IN"
        if s == "SIGNED_IN":         # token removed outside the app
            s = "NOT_SIGNED_IN"
    return {"configured": bool(bq.oauth_client_id) and client_secret_set(), "client_id": bq.oauth_client_id,
            "client_secret_set": client_secret_set(), "enabled": bq.oauth_enabled, "status": s,
            "email": (tok or {}).get("email") if s == "SIGNED_IN" else st.get("email"),
            "signed_in_at": (tok or {}).get("obtained_at"), "last_event_at": st.get("at"), "error": st.get("error"),
            # last time Google really issued an access token for the stored sign-in (None = never verified since)
            "verified_at": st.get("verified_at") if s == "SIGNED_IN" else None,
            "auth_url": live.get("auth_url") if live and s == "IN_PROGRESS" else None,
            "flow_expires_at": live.get("expires_at") if live and s == "IN_PROGRESS" else None,
            "scopes": SCOPES}


def save_client(client_id: str, client_secret: str | None) -> dict:
    """Administrator-provided OAuth client ('Desktop app'). The secret goes to Credential Manager, never to the DB.
    A sign-in made with ANOTHER client cannot work with this one: it is revoked (best effort) and removed."""
    ss.update("bigquery", {"oauth_client_id": client_id}, note="OAuth client id saved")
    if client_secret:
        secret_store.store().set(CLIENT_SECRET_ITEM, client_secret.strip())
    tok = _token()
    if tok and tok.get("client_id") != client_id:
        _revoke(tok)
        secret_store.store().delete(TOKEN_ITEM)
        ss.update("bigquery", {"oauth_enabled": False}, note="OAuth client changed: previous sign-in removed")
        _save_status({"status": "NOT_SIGNED_IN", "at": now_iso(), "email": None,
                      "error": {"code": "OAUTH_CLIENT_CHANGED", "detail": None}})
    return status()


def save_client_file(text: str) -> dict:
    """Import the OAuth client JSON downloaded from the Google Cloud Console (works the same on every PC). Only a
    'Desktop app' client ("installed") fits the loopback sign-in; a 'Web application' client is refused with a clear
    reason. The file content is parsed in memory only: never written to disk, logged or returned."""
    if not text or len(text) > 16384:
        raise AppError("OAUTH_CLIENT_FILE_INVALID", 422, detail="empty or larger than 16 KB")
    try:
        obj = json.loads(text)
    except ValueError:
        raise AppError("OAUTH_CLIENT_FILE_INVALID", 422, detail="not JSON") from None
    if not isinstance(obj, dict):
        raise AppError("OAUTH_CLIENT_FILE_INVALID", 422, detail="not a JSON object")
    if "installed" not in obj and "web" in obj:
        raise AppError("OAUTH_CLIENT_WRONG_TYPE", 422, detail="web")
    inst = obj.get("installed")
    if not isinstance(inst, dict) or not inst.get("client_id") or not inst.get("client_secret"):
        raise AppError("OAUTH_CLIENT_FILE_INVALID", 422, detail="installed.client_id / client_secret missing")
    try:
        return save_client(str(inst["client_id"]).strip(), str(inst["client_secret"]))
    except ValueError as e:     # settings validation (client id format)
        raise AppError("OAUTH_CLIENT_FILE_INVALID", 422, detail=str(e).splitlines()[0][:200]) from None


# ------------------------------------------------------------------ sign-in flow
def _finish(result: dict) -> None:
    with _lock:
        _flow.update(result)           # the loopback loop sees the final status and closes the listener itself
    st = {"status": result["status"], "at": now_iso(), "error": result.get("error"), "email": result.get("email")}
    if result["status"] == "SIGNED_IN":      # Google has just issued tokens for this account
        st["verified_at"] = st["at"]
    _save_status(st)
    log.info("oauth sign-in finished", extra={"ctx": {"status": result["status"],
                                                      "code": (result.get("error") or {}).get("code")}})


def _classify_google_error(err: str, desc: str | None) -> tuple[str, str]:
    if err == "access_denied":
        return "CANCELLED", "OAUTH_CANCELLED"
    if err in BLOCKED_ERRORS:
        return "BLOCKED", "OAUTH_BLOCKED"
    return "ERROR", "OAUTH_ERROR"


def _exchange(code: str, verifier: str, redirect_uri: str, client_id: str, client_secret: str) -> dict:
    http = _client_http()
    try:
        r = http.post(TOKEN_URI, data={"code": code, "client_id": client_id, "client_secret": client_secret,
                                       "redirect_uri": redirect_uri, "grant_type": "authorization_code",
                                       "code_verifier": verifier}, timeout=HTTP_TIMEOUT_S)
    except Exception as e:   # noqa: BLE001 - network problems are reported, not raised to the browser
        return {"status": "ERROR", "error": {"code": "OAUTH_NETWORK", "detail": type(e).__name__}}
    body = r.json() if r.content else {}
    if r.status_code != 200 or "error" in body:
        s, code_ = _classify_google_error(body.get("error", ""), body.get("error_description"))
        return {"status": s, "error": {"code": code_, "detail": body.get("error") or f"HTTP {r.status_code}"}}
    if not body.get("refresh_token"):
        return {"status": "ERROR", "error": {"code": "OAUTH_NO_REFRESH_TOKEN", "detail": "no refresh token returned"}}
    try:
        u = http.get(USERINFO_URI, headers={"Authorization": f"Bearer {body['access_token']}"}, timeout=HTTP_TIMEOUT_S)
        info = u.json() if u.status_code == 200 else {}
    except Exception:   # noqa: BLE001
        info = {}
    if not info.get("email") or info.get("email_verified") is False:
        return {"status": "ERROR", "error": {"code": "OAUTH_IDENTITY_UNVERIFIED", "detail": "email not verified"}}
    granted = set((body.get("scope") or "").split())
    tok = {"refresh_token": body["refresh_token"], "client_id": client_id, "email": info["email"],
           "scopes": sorted(granted) or SCOPES, "obtained_at": now_iso()}
    secret_store.store().set(TOKEN_ITEM, json.dumps(tok))
    if "https://www.googleapis.com/auth/bigquery" not in granted and granted:
        return {"status": "SIGNED_IN", "email": info["email"],
                "error": {"code": "OAUTH_SCOPE_NOT_GRANTED", "detail": "bigquery scope not granted"}}
    return {"status": "SIGNED_IN", "email": info["email"]}


def _handler_factory():
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):        # the default handler would log the full URL (contains the code)
            return

        def _page(self, ok: bool, text: str):
            body = (f"<!doctype html><meta charset='utf-8'><title>Demand Forecasting</title>"
                    f"<body style='font-family:sans-serif;padding:32px'><h2>{'✔' if ok else '✘'} {text}</h2>"
                    f"<p>Có thể đóng thẻ này và quay lại ứng dụng. / You can close this tab.</p></body>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            if u.path != "/":
                self.send_response(404)
                self.end_headers()
                return
            q = dict(urllib.parse.parse_qsl(u.query))
            with _lock:
                fl = dict(_flow)
            if fl.get("status") != "IN_PROGRESS":
                self._page(False, "Phiên đăng nhập đã kết thúc / sign-in session is over")
                return
            if q.get("state") != fl.get("state"):
                _finish({"status": "ERROR", "error": {"code": "OAUTH_STATE_MISMATCH", "detail": "state mismatch"}})
                self._page(False, "Yêu cầu không hợp lệ (state) / invalid request")
                return
            if "error" in q:
                s, code_ = _classify_google_error(q.get("error", ""), q.get("error_description"))
                _finish({"status": s, "error": {"code": code_, "detail": q.get("error")}})
                self._page(False, "Đăng nhập không thành công / sign-in not completed")
                return
            if not q.get("code"):
                _finish({"status": "ERROR", "error": {"code": "OAUTH_ERROR", "detail": "no code"}})
                self._page(False, "Thiếu mã xác thực / missing code")
                return
            res = _exchange(q["code"], fl["verifier"], fl["redirect_uri"], fl["client_id"], fl["client_secret"])
            if res["status"] == "SIGNED_IN":
                ss.update("bigquery", {"oauth_enabled": True}, note="signed in with Google (OAuth)")
            _finish(res)
            self._page(res["status"] == "SIGNED_IN",
                       f"Đã đăng nhập {res.get('email')}" if res["status"] == "SIGNED_IN" else "Đăng nhập không thành công")
    return Handler


def start(open_browser: bool = True, timeout_s: int = FLOW_TIMEOUT_S) -> dict:
    bq = ss.get("bigquery")
    secret = None
    try:
        secret = secret_store.store().get(CLIENT_SECRET_ITEM)
    except secret_store.SecretStoreError as e:
        raise AppError("OAUTH_NOT_CONFIGURED", 409, detail=str(e)) from e
    if not bq.oauth_client_id or not secret:
        raise AppError("OAUTH_NOT_CONFIGURED", 409)
    with _lock:
        if _flow.get("status") == "IN_PROGRESS" and _flow.get("deadline", 0) > time.monotonic():
            return {"status": "IN_PROGRESS", "auth_url": _flow["auth_url"], "redirect_uri": _flow["redirect_uri"]}
    srv = http.server.HTTPServer(("127.0.0.1", 0), _handler_factory())
    srv.timeout = 1
    redirect_uri = f"http://127.0.0.1:{srv.server_address[1]}/"
    state = secrets.token_urlsafe(32)
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    url = AUTH_URI + "?" + urllib.parse.urlencode({
        "client_id": bq.oauth_client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "access_type": "offline", "prompt": "consent"})
    deadline = time.monotonic() + timeout_s
    with _lock:
        _flow.clear()
        _flow.update(status="IN_PROGRESS", state=state, verifier=verifier, redirect_uri=redirect_uri,
                     client_id=bq.oauth_client_id, client_secret=secret, server=srv, deadline=deadline,
                     auth_url=url, expires_at=time.time() + timeout_s)

    def serve():
        while True:
            with _lock:
                done = _flow.get("status") != "IN_PROGRESS" or _flow.get("server") is not srv
            if done:
                break
            if time.monotonic() > deadline:
                _finish({"status": "TIMEOUT", "error": {"code": "OAUTH_TIMEOUT", "detail": f"{timeout_s}s"}})
                break
            srv.handle_request()
        srv.server_close()
        with _lock:                     # never keep the verifier / secret in memory after the flow
            for k in ("verifier", "client_secret", "state"):
                _flow.pop(k, None)
    threading.Thread(target=serve, name="df-oauth-loopback", daemon=True).start()
    _save_status({"status": "IN_PROGRESS", "at": now_iso()})
    if open_browser:
        try:
            (_open_browser or __import__("webbrowser").open)(url)
        except Exception:   # noqa: BLE001 - the UI also shows the link
            pass
    return {"status": "IN_PROGRESS", "auth_url": url, "redirect_uri": redirect_uri, "timeout_s": timeout_s}


def cancel() -> dict:
    with _lock:
        active = _flow.get("status") == "IN_PROGRESS"
    if active:
        _finish({"status": "CANCELLED", "error": {"code": "OAUTH_CANCELLED", "detail": "cancelled in the app"}})
    return status()


def _revoke(tok: dict) -> bool:
    try:
        r = _client_http().post(REVOKE_URI, data={"token": tok["refresh_token"]}, timeout=HTTP_TIMEOUT_S)
        return r.status_code == 200
    except Exception:   # noqa: BLE001 - best effort; the local copy is removed anyway
        return False


def logout() -> dict:
    """Revoke the refresh token at Google (best effort) and remove it from Credential Manager."""
    tok = _token()
    revoked = _revoke(tok) if tok else None
    secret_store.store().delete(TOKEN_ITEM)
    ss.update("bigquery", {"oauth_enabled": False}, note="signed out (OAuth)")
    _save_status({"status": "NOT_SIGNED_IN", "at": now_iso(), "email": None})
    return {**status(), "revoked_at_google": revoked}


def mark_revoked(detail: str | None = None) -> None:
    _save_status({"status": "REVOKED", "at": now_iso(), "email": (_token() or {}).get("email"),
                  "error": {"code": "BQ_AUTH_EXPIRED", "detail": detail}})


def mark_verified(email: str | None) -> None:
    """Google just issued an access token for the stored sign-in (real round trip)."""
    _save_status({"status": "SIGNED_IN", "at": now_iso(), "verified_at": now_iso(),
                  "email": email or (_token() or {}).get("email")})


def credentials():
    """google.oauth2 user credentials built from the stored refresh token (refreshed lazily by the client)."""
    from google.oauth2.credentials import Credentials
    tok = _token()
    if not tok:
        raise AppError("BQ_AUTH_MISSING", 401, detail="OAuth: chưa đăng nhập Google trong ứng dụng")
    if tok.get("client_id") != ss.get("bigquery").oauth_client_id:
        raise AppError("OAUTH_CLIENT_CHANGED", 409)
    secret = secret_store.store().get(CLIENT_SECRET_ITEM)
    if not secret:
        raise AppError("OAUTH_NOT_CONFIGURED", 409)
    return Credentials(token=None, refresh_token=tok["refresh_token"], token_uri=TOKEN_URI,
                       client_id=tok["client_id"], client_secret=secret, scopes=tok.get("scopes") or SCOPES)


# ------------------------------------------------------------------ diagnostics
def runtime_identity() -> dict:
    """Which Windows account runs the backend and where google.auth looks for ADC (paths only, no file content)."""
    appdata = os.environ.get("APPDATA", "")
    adc = Path(appdata) / "gcloud" / "application_default_credentials.json" if appdata else None
    gac = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    try:
        user = getpass.getuser()
    except Exception:   # noqa: BLE001
        user = None
    bq = ss.get("bigquery")
    method = "OAUTH_USER" if bq.oauth_enabled else bq.auth_method
    return {"windows_user": user, "computer": os.environ.get("COMPUTERNAME"), "appdata": appdata,
            "adc_path_checked": str(adc) if adc else None, "adc_exists": bool(adc and adc.is_file()),
            "google_application_credentials_set": bool(gac),
            "google_application_credentials_exists": bool(gac and Path(gac).is_file()),
            "gcloud_on_path": shutil.which("gcloud") is not None, "effective_method": method,
            "note": {"vi": "ADC chỉ được tìm trong hồ sơ của tài khoản Windows đang chạy ứng dụng. ADC tạo bằng tài khoản "
                           "Windows khác (ví dụ Administrator) không dùng được.",
                     "en": "ADC is only looked up in the profile of the Windows account that runs the app. ADC created "
                           "under another Windows account (e.g. Administrator) cannot be used."}}
