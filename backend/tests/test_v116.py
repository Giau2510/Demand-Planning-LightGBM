"""v1.1.6: in-app Google sign-in (OAuth + PKCE, Windows Credential Manager), runtime identity diagnostics, read-only
SQL editor (history / D0) with versions, D0 from the user's SQL, independent sync jobs, key gate, backfill.
No real Google / BigQuery access: OAuth endpoints and BigQuery are fakes; the loopback callback is a real local HTTP."""
import json
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from app import db
from app import settings_service as ss
from app import timeutil
from app.bq import connector, oauth, secret_store, sql_guard, sql_sources
from app.messages import AppError
from fake_bq import FakeBQ

D0_FILE = Path(__file__).resolve().parents[1] / "app" / "bq" / "d0_user_sql_20261015.sql"
LAYOUT = [("fc_code", "STRING"), ("created_date", "DATE"), ("product_id", "INT64"), ("sku_code", "STRING"),
          ("item_code", "STRING"), ("demand_quantity", "FLOAT64"), ("outbound_quantity", "FLOAT64"),
          ("order_status", "STRING"), ("sales_price", "FLOAT64"), ("price_after_discount", "FLOAT64"),
          ("seller_code", "STRING"), ("sku_system_status", "STRING"), ("open_date", "DATE"),
          ("total_open_hours", "FLOAT64"), ("total_open_days", "INT64"), ("so_code", "STRING"), ("refresh_time", "TIMESTAMP")]
D0_OUT = [("fc_code", "STRING"), ("created_date", "DATE"), ("so_code", "STRING"), ("order_status", "STRING"),
          ("product_id", "INT64"), ("sku_code", "STRING"), ("item_code", "STRING"), ("seller_code", "STRING"),
          ("sku_system_status", "STRING"), ("demand_quantity", "FLOAT64"), ("sales_price", "FLOAT64")]


@pytest.fixture(autouse=True)
def _oauth_isolation():
    store = secret_store.MemoryStore()
    secret_store.set_store(store)
    oauth.set_browser(lambda url: None)
    yield store
    oauth.set_http(None)
    oauth.set_browser(None)
    secret_store.set_store(None)
    with oauth._lock:
        srv = oauth._flow.get("server")
        oauth._flow.clear()
    if srv is not None:
        srv.server_close()


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._b = body
        self.content = json.dumps(body).encode()

    def json(self):
        return self._b


class FakeGoogle:
    def __init__(self, token=None, userinfo=None, fail=None):
        self.token = token or {"access_token": "AT-1", "refresh_token": "RT-SECRET-123", "expires_in": 3600,
                               "scope": "openid https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/bigquery"}
        self.userinfo = userinfo or {"email": "planner@buymed.example", "email_verified": True}
        self.fail = fail
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append(("POST", url, dict(data or {})))
        if self.fail == "network":
            raise requests.ConnectionError("down")
        if url == oauth.TOKEN_URI:
            if self.fail == "invalid_client":
                return _Resp(401, {"error": "invalid_client"})
            return _Resp(200, self.token)
        return _Resp(200, {})

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None))
        return _Resp(200, self.userinfo)


def _configure_client():
    oauth.save_client("123-abc.apps.googleusercontent.com", "CLIENT-SECRET-XYZ")


def _callback(redirect_uri, **q):
    return requests.get(redirect_uri + "?" + urllib.parse.urlencode(q), timeout=10)


def _wait_status(want, timeout=5):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = oauth.status()
        if st["status"] == want:
            return st
        time.sleep(0.05)
    return oauth.status()


# ------------------------------------------------------------------ OAuth
def test_oauth_requires_an_administrator_client():
    with pytest.raises(AppError) as e:
        oauth.start(open_browser=False)
    assert e.value.code == "OAUTH_NOT_CONFIGURED"
    with pytest.raises(Exception):
        oauth.save_client("not-a-client-id", "x")


def test_oauth_success_pkce_state_and_no_secret_leaks(client, _oauth_isolation):
    _configure_client()
    g = FakeGoogle()
    oauth.set_http(g)
    st = oauth.start(open_browser=False)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(st["auth_url"]).query))
    assert q["code_challenge_method"] == "S256" and len(q["state"]) >= 32 and q["redirect_uri"].startswith("http://127.0.0.1:")
    assert "client_secret" not in st["auth_url"] and q["access_type"] == "offline"
    assert oauth.status()["status"] == "IN_PROGRESS"
    r = _callback(st["redirect_uri"], code="AUTH-CODE", state=q["state"])
    assert r.status_code == 200 and "planner@buymed.example" in r.text
    s2 = _wait_status("SIGNED_IN")
    assert s2["status"] == "SIGNED_IN" and s2["email"] == "planner@buymed.example"
    tok_call = next(c for c in g.calls if c[1] == oauth.TOKEN_URI)
    assert tok_call[2]["code_verifier"] and tok_call[2]["code"] == "AUTH-CODE"
    import base64, hashlib
    assert base64.urlsafe_b64encode(hashlib.sha256(tok_call[2]["code_verifier"].encode()).digest()).rstrip(b"=").decode() == q["code_challenge"]
    assert json.loads(_oauth_isolation.get(oauth.TOKEN_ITEM))["refresh_token"] == "RT-SECRET-123"
    assert ss.get("bigquery").oauth_enabled is True
    # no secret anywhere outside Credential Manager: DB, API answers
    with db.read() as c:
        dump = "\n".join(str(tuple(r)) for t in ("app_settings", "settings_history", "sync_state", "audit_log")
                         for r in c.execute(f"SELECT * FROM {t}"))
    for secret in ("RT-SECRET-123", "CLIENT-SECRET-XYZ", "AT-1", "AUTH-CODE"):
        assert secret not in dump
        assert secret not in json.dumps(client.get("/api/bigquery/identity").json())
        assert secret not in json.dumps(client.get("/api/bigquery/status").json())
        assert secret not in json.dumps(client.get("/api/settings").json())
    creds = oauth.credentials()
    assert creds.refresh_token == "RT-SECRET-123" and creds.client_id.endswith(".apps.googleusercontent.com")
    # the callback cannot be replayed: the session is over (or the one-shot listener is already closed)
    try:
        replay = _callback(st["redirect_uri"], code="AUTH-CODE", state=q["state"])
        assert "kết thúc" in replay.text
    except requests.exceptions.ConnectionError:
        pass
    assert sum(1 for c in g.calls if c[1] == oauth.TOKEN_URI) == 1


@pytest.mark.parametrize("err,status,code", [("access_denied", "CANCELLED", "OAUTH_CANCELLED"),
                                             ("admin_policy_enforced", "BLOCKED", "OAUTH_BLOCKED"),
                                             ("org_internal", "BLOCKED", "OAUTH_BLOCKED"),
                                             ("server_error", "ERROR", "OAUTH_ERROR")])
def test_oauth_cancel_blocked_and_errors(err, status, code, _oauth_isolation):
    _configure_client()
    oauth.set_http(FakeGoogle())
    st = oauth.start(open_browser=False)
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(st["auth_url"]).query))["state"]
    _callback(st["redirect_uri"], error=err, state=state)
    s2 = _wait_status(status)
    assert s2["status"] == status and s2["error"]["code"] == code
    assert _oauth_isolation.get(oauth.TOKEN_ITEM) is None and ss.get("bigquery").oauth_enabled is False


def test_oauth_wrong_state_never_exchanges_the_code():
    _configure_client()
    g = FakeGoogle()
    oauth.set_http(g)
    st = oauth.start(open_browser=False)
    _callback(st["redirect_uri"], code="AUTH-CODE", state="forged")
    s2 = _wait_status("ERROR")
    assert s2["error"]["code"] == "OAUTH_STATE_MISMATCH" and not any(c[1] == oauth.TOKEN_URI for c in g.calls)


def test_oauth_timeout_network_and_invalid_client():
    _configure_client()
    oauth.set_http(FakeGoogle())
    oauth.start(open_browser=False, timeout_s=1)
    assert _wait_status("TIMEOUT", 6)["error"]["code"] == "OAUTH_TIMEOUT"
    for fail, status, code in (("network", "ERROR", "OAUTH_NETWORK"), ("invalid_client", "BLOCKED", "OAUTH_BLOCKED")):
        oauth.set_http(FakeGoogle(fail=fail))
        st = oauth.start(open_browser=False)
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(st["auth_url"]).query))["state"]
        _callback(st["redirect_uri"], code="C", state=state)
        s2 = _wait_status(status)
        assert s2["error"]["code"] == code, (fail, s2)


def test_oauth_refresh_success_failure_and_logout(_oauth_isolation):
    _configure_client()
    _oauth_isolation.set(oauth.TOKEN_ITEM, json.dumps({"refresh_token": "RT-1", "client_id": "123-abc.apps.googleusercontent.com",
                                                       "email": "a@b.c", "scopes": oauth.SCOPES, "obtained_at": "x"}))
    from google.auth.exceptions import RefreshError
    creds = oauth.credentials()

    class Tr:
        def __init__(self, status, body):
            self.status, self.body = status, body

        def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kw):
            return SimpleNamespace(status=self.status, headers={}, data=json.dumps(self.body).encode())
    creds.refresh(Tr(200, {"access_token": "NEW-AT", "expires_in": 3600}))          # refresh succeeds
    assert creds.token == "NEW-AT" and creds.valid
    with pytest.raises(RefreshError):                                                  # revoked / expired grant
        oauth.credentials().refresh(Tr(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}))
    # the connector reports it as BQ_AUTH_EXPIRED and marks the sign-in as revoked
    ss.update("bigquery", {"dataset_id": "d", "source_table": "t", "oauth_enabled": True})
    connector.set_client_factory(FakeBQ(errors={"profile": type("RefreshError", (Exception,), {})("invalid_grant")}))
    with pytest.raises(AppError) as e:
        connector.profile(7)
    assert e.value.code == "BQ_AUTH_EXPIRED" and oauth.status()["status"] == "REVOKED"
    g = FakeGoogle()
    oauth.set_http(g)
    out = oauth.logout()
    assert out["revoked_at_google"] is True and any(c[1] == oauth.REVOKE_URI and c[2]["token"] == "RT-1" for c in g.calls)
    assert _oauth_isolation.get(oauth.TOKEN_ITEM) is None and ss.get("bigquery").oauth_enabled is False
    assert out["status"] == "NOT_SIGNED_IN"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager only")
def test_windows_credential_manager_roundtrip():
    st = secret_store.WindowsCredentialStore()
    name = "selftest-" + str(time.time_ns())
    try:
        assert st.get(name) is None
        st.set(name, "value-ÄÖ-123")
        assert st.get(name) == "value-ÄÖ-123"
    finally:
        st.delete(name)
    assert st.get(name) is None


def test_runtime_identity_explains_where_adc_is_looked_up(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    r = oauth.runtime_identity()
    assert r["adc_path_checked"] == str(tmp_path / "gcloud" / "application_default_credentials.json") and r["adc_exists"] is False
    assert r["windows_user"] and "Administrator" in r["note"]["vi"]
    (tmp_path / "gcloud").mkdir()
    (tmp_path / "gcloud" / "application_default_credentials.json").write_text("{}")
    assert oauth.runtime_identity()["adc_exists"] is True


def test_adc_valid_and_missing_paths(monkeypatch):
    import google.auth
    from google.auth.credentials import AnonymousCredentials
    from google.auth.exceptions import DefaultCredentialsError
    ss.update("bigquery", {"dataset_id": "d", "source_table": "t", "location": "asia-southeast1"})
    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (AnonymousCredentials(), "p"))
    cl = connector._client(ss.get("bigquery"))                 # a valid ADC keeps working (old flow unchanged)
    assert type(cl).__name__ == "Client" and cl.project == "lakehouse-prod-394907"

    def no_adc(scopes=None):
        raise DefaultCredentialsError("no ADC")
    monkeypatch.setattr(google.auth, "default", no_adc)
    with pytest.raises(AppError) as e:
        connector._client(ss.get("bigquery"))
    assert e.value.code == "BQ_AUTH_MISSING"


# ------------------------------------------------------------------ SQL guard + editor
def test_user_d0_sql_is_stored_verbatim_and_not_active():
    d0 = sql_sources.source("d0")
    text = D0_FILE.read_text(encoding="utf-8").rstrip("\n")
    assert d0.mode == "SQL" and d0.active_version_id is None and d0.versions[0].sql == text
    assert "b.sales_price,\nFROM" in d0.versions[0].sql                      # the trailing comma is kept as given
    chk = sql_guard.check(text)
    codes = {n["code"] for n in chk["notes"]}
    assert chk["ok"] and {"TRAILING_COMMA_BEFORE_FROM", "LEFT_JOIN_WITH_WHERE", "DATE_OF_TIMESTAMP_WITHOUT_TIMEZONE"} <= codes
    with pytest.raises(AppError) as e:          # the scheduler never runs an unvalidated SQL
        sql_sources.snapshot("d0")
    assert e.value.code == "SQL_NOT_VALIDATED"


@pytest.mark.parametrize("sql,code", [
    ("DELETE FROM `p.d.t` WHERE TRUE", "SQL_NOT_A_QUERY"),
    ("SELECT 1; DROP TABLE `p.d.t`", "SQL_MULTIPLE_STATEMENTS"),
    ("CREATE OR REPLACE TABLE x AS SELECT 1", "SQL_NOT_A_QUERY"),
    ("WITH a AS (SELECT 1) INSERT INTO t SELECT * FROM a", "SQL_FORBIDDEN_KEYWORD"),
    ("SELECT 1 /* ok */; SELECT 2", "SQL_MULTIPLE_STATEMENTS"),
    ("EXECUTE IMMEDIATE 'DELETE FROM t'", "SQL_NOT_A_QUERY"),
    ("", "SQL_EMPTY"),
])
def test_sql_guard_rejects_non_queries(sql, code):
    chk = sql_guard.check(sql)
    assert not chk["ok"] and code in {e["code"] for e in chk["errors"]}


def test_sql_guard_ignores_words_inside_strings_comments_identifiers():
    sql = "SELECT 'delete me' AS a, `update` AS b -- drop table x\n# insert\n FROM `p.d.t` /* merge */ WHERE x = \"set\";"
    chk = sql_guard.check(sql)
    assert chk["ok"], chk
    sub = sql_guard.as_subquery(sql)
    assert sub.startswith("(\n") and sub.endswith("\n)") and not sub.rstrip(")\n").rstrip().endswith(";")
    assert sql_guard.as_subquery("SELECT 1 -- trailing comment").endswith("-- trailing comment\n)")


def _bq_ready(fake=None):
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm",
                           "location": "asia-southeast1", "partition_column": "created_date"})
    fake = fake or FakeBQ(schema=LAYOUT)
    connector.set_client_factory(fake)
    sug = connector.suggest_mapping(connector.read_schema()["columns"])
    ss.update("bigquery", {"field_mapping": sug["field_mapping"], "reference_mapping": sug["reference_mapping"]})
    return fake


def test_sql_versions_validate_activate_invalid_keeps_previous_and_restore(client):
    fake = _bq_ready()
    fake.dry_schema = D0_OUT
    r = client.post("/api/sql-sources/d0/versions/1/validate").json()
    assert r["validation"]["status"] == "VALID" and r["active_version_id"] == 1
    assert r["effective_key_columns"] == ["so_code", "sku_code", "fc_code", "created_date"]
    # a new version with a BigQuery syntax error: saved, INVALID, never active
    v2 = client.post("/api/sql-sources/d0/versions", json={"sql": "SELECT sku_code FROM `p.d.t` WHERE", "note": "x"}).json()
    assert v2["saved_version_id"] == 3 and v2["active_version_id"] == 1       # v2 = seeded proposal
    fake.errors["sql_dry_run"] = type("BadRequest", (Exception,), {})("Syntax error: Unexpected end of script at [1:35]")
    r = client.post("/api/sql-sources/d0/versions/3/validate").json()
    assert r["validation"]["status"] == "INVALID" and r["validation"]["error"]["code"] == "BQ_SQL_ERROR"
    assert r["active_version_id"] == 1                                   # the validated version stays in use
    del fake.errors["sql_dry_run"]
    # output lacking a required column -> INVALID
    fake.dry_schema = [c for c in D0_OUT if c[0] != "demand_quantity"]
    v3 = client.post("/api/sql-sources/d0/versions", json={"sql": "SELECT sku_code, fc_code FROM `p.d.t`"}).json()
    r = client.post(f"/api/sql-sources/d0/versions/{v3['saved_version_id']}/validate").json()
    assert r["validation"]["error"]["code"] == "SQL_OUTPUT_MISSING_COLUMNS" and r["active_version_id"] == 1
    # a statement BigQuery classifies as not SELECT -> INVALID
    fake.dry_schema, fake.statement_type = D0_OUT, "SCRIPT"
    r = client.post(f"/api/sql-sources/d0/versions/{v3['saved_version_id']}/validate").json()
    assert r["validation"]["error"]["code"] in ("SQL_NOT_A_QUERY", "SQL_OUTPUT_MISSING_COLUMNS")
    fake.statement_type = "SELECT"
    # write statements are refused before saving
    r = client.post("/api/sql-sources/d0/versions", json={"sql": "UPDATE `p.d.t` SET a = 1 WHERE TRUE"})
    assert r.status_code == 422 and r.json()["code"] == "SQL_REJECTED"
    assert max(v["id"] for v in client.get("/api/sql-sources").json()["d0"]["versions"]) == 4
    # restore: an INVALID version comes back as a NEW version needing validation; a VALID one is re-activated
    r = client.post("/api/sql-sources/d0/versions/3/restore").json()
    assert r["needs_validation"] and r["active_version_id"] == 1 and r["saved_version_id"] == 5
    r = client.post("/api/sql-sources/d0/versions/1/restore").json()
    assert not r["needs_validation"] and r["active_version_id"] == 1
    assert client.put("/api/settings/sql_sources", json={}).status_code == 404       # only through the SQL endpoints


def test_sql_preview_is_limited_and_read_only(client):
    fake = _bq_ready()
    fake.responses["sql_preview"] = [{"sku_code": "S1", "fc_code": "F1", "demand_quantity": 2.0}]
    ss.update("bigquery", {"preview_rows": 30})
    r = client.post("/api/sql-sources/d0/versions/1/preview", json={"limit": 10000}).json()
    sql = fake.queries[-1][0]
    assert r["limit"] == 30 and "LIMIT 30" in sql and "SELECT * FROM (\nSELECT" in sql
    assert all(q[1].get("maximum_bytes_billed") or q[1].get("dry_run") for q in fake.queries)
    assert fake.queries[-2][1]["dry_run"] is True                         # dry run before the real (limited) run


def _d0_rows(today, key_dups="0", exact="0", other_date=None):
    """Result rows of the D-0 aggregate (1.2.1 layout): a row of another day is EXCLUDED as OTHER_DAY by the query."""
    n, q = (6, 10.0) if other_date else (5, 9.0)
    rows = [{"_kind": "VALID", "_reason": None, "sku_id": "S1", "fc_id": "F1", "qty": 6.0, "n_rows": 3},
            {"_kind": "VALID", "_reason": None, "sku_id": "S2", "fc_id": "F1", "qty": 1.0, "n_rows": 1},
            {"_kind": "EXCLUDED", "_reason": "NULL_FC", "qty": 2.0, "n_rows": 1},
            {"_kind": "TOTAL_READ", "_reason": exact, "qty": q, "n_rows": n},
            {"_kind": "TOTAL_KEPT", "_reason": key_dups, "qty": q, "n_rows": n},
            {"_kind": "DATE", "_reason": str(today), "qty": 9.0, "n_rows": 5}]
    if other_date:
        rows += [{"_kind": "EXCLUDED", "_reason": "OTHER_DAY", "qty": 1.0, "n_rows": 1},
                 {"_kind": "DATE", "_reason": other_date, "qty": 1.0, "n_rows": 1}]
    return rows


def _d0_production(client):
    fake = _bq_ready()
    fake.dry_schema = D0_OUT
    assert client.post("/api/sql-sources/d0/versions/1/validate").json()["validation"]["status"] == "VALID"
    ss.update("bigquery", {"production_enabled": True})
    ss.update("general", {"active_source": "BIGQUERY"})
    assert client.put("/api/sql-sources/d0/options", json={"schedule_enabled": True}).json()["schedule_enabled"] is True
    return fake


def test_d0_snapshot_from_user_sql_key_gate_dates_and_idempotent_retry(client):
    from app.sync import run_d0_snapshot
    fake = _d0_production(client)
    today = timeutil.today_vn()
    fake.responses["d0"] = _d0_rows(today, other_date=str(today - timedelta(days=1)))
    res = run_d0_snapshot("JOB-A", "slot", False)
    sql = [q for q in fake.queries if q[0].startswith("-- df:d0") and not q[1]["dry_run"]][-1][0]
    assert "FROM (\nSELECT\n  a.fc_code," in sql and "TO_JSON_STRING(STRUCT(t.`so_code`" in sql   # user SQL verbatim, sub-query
    # 1.2.1: only TODAY's rows (Vietnam day, query parameter) are counted; rows of another day are excluded and counted
    params = [q for q in fake.queries if q[0].startswith("-- df:d0") and not q[1]["dry_run"]][-1][1]["params"]
    assert "WHEN _d != @day THEN 'OTHER_DAY'" in sql and ("day", "DATE", today) in params
    assert res["series"] == 2 and res["rows_error"] == 1 and res["source_batch_id"].startswith("D0SQL-v1-")
    assert res["rows_other_day"] == 1 and res["warnings"][0]["code"] == "D0_ROWS_OTHER_THAN_TODAY"
    again = run_d0_snapshot("JOB-A", "slot", False)                     # retry of the same job -> no duplicate
    assert again["already_written"] and again["snapshot_id"] == res["snapshot_id"]
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM d0_snapshots WHERE job_id='JOB-A'").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM demand_daily").fetchone()[0] == 0          # D0 never feeds training data
    fake.responses["d0"] = _d0_rows(today, key_dups="2")
    with pytest.raises(AppError) as e:
        run_d0_snapshot("JOB-B", "slot2", False)
    assert e.value.code == "BQ_KEY_NOT_UNIQUE"
    sql_sources.set_options("d0", key_duplicate_policy="SUM_ALL")      # explicit user decision
    assert run_d0_snapshot("JOB-C", "slot3", False)["series"] == 2
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM d0_snapshots WHERE job_id='JOB-B'").fetchone()[0] == 0


def test_job_keeps_the_sql_snapshot_taken_at_start(client, monkeypatch):
    from app import sync
    fake = _d0_production(client)
    fake.responses["d0"] = _d0_rows(timeutil.today_vn())
    v2 = sql_sources.save_version("d0", sql_sources.version(sql_sources.source("d0"), 1).sql + "\n  AND TRUE")
    seen = {}
    real = connector.fetch_d0

    def mid_run(day, cutoff, snap=None):
        seen["used"] = snap["version_id"]
        connector.validate_sql_version("d0", v2["saved_version_id"])   # the user activates v2 while the job runs
        return real(day, cutoff, snap)
    monkeypatch.setattr(connector, "fetch_d0", mid_run)
    res = sync.run_d0_snapshot("JOB-SNAP", "slot", False)
    assert seen["used"] == 1 and res["sql_source"]["version_id"] == 1
    assert sql_sources.source("d0").active_version_id == v2["saved_version_id"]


def test_unvalidated_sql_skips_jobs_instead_of_failing(client):
    from app.jobs import runner
    _bq_ready()
    ss.update("bigquery", {"production_enabled": True})
    ss.update("general", {"active_source": "BIGQUERY"})
    assert {"SQL_NOT_VALIDATED", "D0_SCHEDULE_DISABLED"} <= set(runner.NEEDS_CONFIG_CODES)
    j = runner.execute("D0_SYNC", "D0_SYNC:test", "MANUAL", None, {})
    assert j["status"] == "SKIPPED" and j["reason_code"] == "SQL_NOT_VALIDATED"
    j = runner.execute("D0_SYNC", "D0_SYNC:test2", "SCHEDULE", None, {"scheduled_slot": "x"})
    assert j["status"] == "SKIPPED" and j["reason_code"] == "D0_SCHEDULE_DISABLED"


def _hist_production(fake):
    from app.bq import connector as C
    fake.responses.update({"validate_summary": [{"n_rows": 10, "rows_valid": 10, "qty_read": 50.0, "qty_valid": 50.0,
                                                 "exact_duplicate_rows": 0, "duplicate_key_rows": 0,
                                                 "min_date": date(2026, 1, 1), "max_date": date.today() - timedelta(days=1)}],
                           "validate_days": [], "validate_null_date": [{"n": 0}], "profile": [{"n_rows": 10}],
                           "completion": [{"n": 1}]})
    C.test_connection()
    ss.update("bigquery", {"schema_snapshot": C.read_schema()["columns"]})
    C.profile(7)
    assert C.validate_source()["passed"]
    ss.update("bigquery", {"production_enabled": True, "completion_table": "done", "completion_date_column": "d"})
    ss.update("general", {"active_source": "BIGQUERY"})


def _daily(day, qty):
    return [{"_kind": "VALID", "order_date": day, "sku_id": "S1", "fc_id": "F1", "qty": qty, "n_orders": 1, "n_rows": 1},
            {"_kind": "TOTAL_READ", "_reason": "0", "qty": qty, "n_rows": 1},
            {"_kind": "TOTAL_KEPT", "_reason": "0", "qty": qty, "n_rows": 1}]


def test_d1_is_independent_backfill_is_bounded_and_counts_new_updated(client, monkeypatch):
    from app import sync
    fake = _bq_ready()
    _hist_production(fake)
    y = timeutil.today_vn() - timedelta(days=1)
    fake.responses["daily"] = _daily(y, 4.0)
    r1 = sync.run_d1_sync("J1", fallback_mode=True)
    assert r1["full_reload"] and r1["series_days_new"] == 1 and r1["sql_source"]["mode"] == "TABLE"
    fake.responses["daily"] = _daily(y, 5.0)
    r2 = sync.run_d1_sync("J2", fallback_mode=True)
    assert not r2["full_reload"] and r2["series_days_updated"] == 1 and r2["series_days_new"] == 0
    with pytest.raises(AppError) as e:                                  # bounds: never before the read range
        sync.run_d1_sync("J3", backfill_start="2025-01-01", backfill_end="2025-01-02")
    assert e.value.code == "VALIDATION_ERROR"
    assert client.post("/api/sync/backfill", json={"start": str(y), "end": str(timeutil.today_vn())}).status_code == 422
    b = sync.run_d1_sync("J4", backfill_start=str(y), backfill_end=str(y))
    assert b["backfill"] and b["mode"] == "BACKFILL" and b["series_days_unchanged"] == 1
    # D0 never calls the history query, and syncing never starts a training
    monkeypatch.setattr(connector, "fetch_daily", lambda *a, **k: (_ for _ in ()).throw(AssertionError("history called")))
    from app.bq import source_tables                    # 1.2.0: the D-0 table must pass its check before D-0 can be on
    sql_sources.set_options("d0", mode="TABLE")
    assert source_tables.check("d0")["status"] == "PASSED"
    sql_sources.set_options("d0", schedule_enabled=True)
    fake.responses["d0"] = _d0_rows(timeutil.today_vn())
    sync.run_d0_snapshot("J5", "slot", False)
    with db.read() as c:
        assert c.execute("SELECT COUNT(*) FROM job_runs WHERE job_type='TRAIN_PUBLISH'").fetchone()[0] == 0
    st = client.get("/api/sync/status").json()
    assert st["timezone"] == "Asia/Ho_Chi_Minh" and st["jobs"]["D0_SYNC"]["schedule"]["times"]
    assert st["jobs"]["D1_SYNC"]["feed"]["mode"] == "TABLE" and st["jobs"]["D0_SYNC"]["feed"]["mode"] == "TABLE"


def test_history_key_repeats_are_summed_by_default_and_block_only_when_chosen(client):
    """Business rule confirmed 16/10/2026: several order lines of one order x SKU x FC x day are summed (history default
    SUM_ALL, reported as a warning). BLOCK, when the user explicitly chooses it, still blocks validation and load."""
    fake = _bq_ready()
    fake.responses.update({"validate_summary": [{"n_rows": 10, "rows_valid": 10, "qty_read": 50.0, "qty_valid": 50.0,
                                                 "exact_duplicate_rows": 0, "duplicate_key_rows": 3,
                                                 "min_date": date(2026, 1, 1), "max_date": date.today()}],
                           "validate_days": [], "validate_null_date": [{"n": 0}]})
    assert sql_sources.view("history")["key_duplicate_policy"] == "SUM_ALL"
    assert sql_sources.view("d0")["key_duplicate_policy"] == "BLOCK"             # D0 feed unchanged
    v = connector.validate_source()
    assert v["passed"] and "KEY_NOT_UNIQUE" in {w["code"] for w in v["warnings"]}
    assert v["key_check"]["key_columns"] == ["so_code", "sku_code", "fc_code", "created_date"]
    sql_sources.set_options("history", key_duplicate_policy="BLOCK")
    v = connector.validate_source()
    assert not v["passed"] and "KEY_NOT_UNIQUE" in {b["code"] for b in v["blocking_issues"]}
    fake.responses["daily"] = [{"_kind": "TOTAL_READ", "_reason": "0", "qty": 0, "n_rows": 0},
                               {"_kind": "TOTAL_KEPT", "_reason": "4", "qty": 0, "n_rows": 0}]
    with pytest.raises(AppError) as e:
        connector.fetch_daily(date(2026, 1, 1), date(2026, 1, 2))
    assert e.value.code == "BQ_KEY_NOT_UNIQUE"


def test_history_sql_mode_runs_the_user_sql_as_subquery_and_gates_production(client):
    fake = _bq_ready()
    hist_sql = "SELECT * FROM `lakehouse-prod-394907.gold_buymed_vn2.demand_planing_lightgbm`"
    v = client.post("/api/sql-sources/history/versions", json={"sql": hist_sql}).json()
    client.put("/api/sql-sources/history/options", json={"mode": "SQL"})
    act = client.get("/api/bigquery/status").json()["activation"]
    assert act["requirements"]["history_sql_validated"] is False and not act["ready"]
    fake.dry_schema = LAYOUT
    r = client.post(f"/api/sql-sources/history/versions/{v['saved_version_id']}/validate").json()
    assert r["validation"]["status"] == "VALID"
    fake.responses["daily"] = []
    connector.fetch_daily(date(2026, 1, 1), date(2026, 1, 2))
    sql = [q for q in fake.queries if q[0].startswith("-- df:daily")][-1][0]
    assert f"FROM (\n{hist_sql}\n) AS _user_sql" in sql and "DATE(`created_date`) BETWEEN @start AND @end" in sql
    assert "DATE_SUB(@start" not in sql                                  # no table partition filter on a user SQL


def test_d0_sql_does_not_change_features_or_training_data(client):
    from app.ml import feature_registry
    _d0_production(client)
    with db.read() as c:
        before = feature_registry.view(c, "BIGQUERY")["next_training"]
    client.post("/api/sql-sources/d0/versions", json={"sql": "SELECT sku_code, fc_code, demand_quantity, sales_price, seller_code FROM `p.d.t`"})
    with db.read() as c:
        after = feature_registry.view(c, "BIGQUERY")["next_training"]
    assert before == after


# ------------------------------------------------------------------ production-readiness additions
def test_seeded_proposal_is_not_active_and_schedule_is_off_by_default(client):
    d0 = client.get("/api/sql-sources").json()["d0"]
    v = {x["id"]: x for x in d0["versions"]}
    assert d0["active_version_id"] is None and d0["schedule_enabled"] is False
    assert v[1]["sha256"].startswith("b9d6d9f56a091d86") and "ĐỀ XUẤT" in v[2]["note"]
    assert "JOIN master c" in v[2]["sql"] and "b.sales_price\nFROM" in v[2]["sql"] and v[2]["static_check"]["ok"]
    r = client.put("/api/sql-sources/d0/options", json={"schedule_enabled": True})
    assert r.status_code == 409 and r.json()["code"] == "SQL_NOT_VALIDATED"          # cannot enable before validation


def test_scheduled_d0_skipped_while_schedule_off_manual_still_possible(client):
    from app import sync
    from app.jobs import runner
    fake = _bq_ready()
    fake.dry_schema = D0_OUT
    client.post("/api/sql-sources/d0/versions/1/validate")
    ss.update("bigquery", {"production_enabled": True})
    ss.update("general", {"active_source": "BIGQUERY"})
    fake.responses["d0"] = _d0_rows(timeutil.today_vn())
    j = runner.execute("D0_SYNC", "D0_SYNC:sched", "SCHEDULE", None, {"scheduled_slot": "2026-10-15T10:00:00+07:00"})
    assert j["status"] == "SKIPPED" and j["reason_code"] == "D0_SCHEDULE_DISABLED"
    assert sync.run_d0_snapshot("JOB-MANUAL", None, False)["series"] == 2      # manual run is allowed
    client.put("/api/sql-sources/d0/options", json={"schedule_enabled": True})
    assert sync.run_d0_snapshot("JOB-SCHED", "2026-10-15T12:00:00+07:00", False)["series"] == 2
    st = client.get("/api/sync/status").json()
    assert st["jobs"]["D0_SYNC"]["feed"]["schedule_enabled"] is True


def _access_fake(**kw):
    f = FakeBQ(schema=LAYOUT, responses={"access_select1": [{"ok": 1}]}, **kw)
    return f


@pytest.mark.parametrize("errors,gate,code", [
    ({"auth": type("DefaultCredentialsError", (Exception,), {})("no adc")}, "auth", "BQ_AUTH_MISSING"),
    ({"dataset": type("Forbidden", (Exception,), {})("BigQuery API has not been used in project 1 before or it is disabled")},
     "api_and_dataset", "BQ_API_DISABLED"),
    ({"dataset": type("Forbidden", (Exception,), {})("Access Denied: Dataset p:d: Permission bigquery.datasets.get denied")},
     "api_and_dataset", "BQ_PERMISSION_DENIED"),
    ({"table": type("NotFound", (Exception,), {})("Not found: Table p:d.t")}, "table_metadata", "BQ_NOT_FOUND"),
    ({"access_dry_run": type("Forbidden", (Exception,), {})("Access Denied: Project p: User does not have bigquery.jobs.create permission")},
     "query_job", "BQ_PERMISSION_DENIED"),
    ({"access_select1": type("TimeoutError", (Exception,), {})("")}, "query_job", "BQ_TIMEOUT"),
])
def test_access_gates_stop_at_the_first_failure(errors, gate, code):
    fake = _bq_ready(_access_fake())          # setup (schema read, mapping) without errors, then inject them
    if "auth" in errors:
        connector.set_client_factory(_access_fake(errors=errors))
    else:
        fake.errors.update(errors)
    r = connector.access_check()
    g = {x["gate"]: x for x in r["gates"]}
    assert not r["passed"] and g[gate]["status"] == "FAIL" and g[gate]["code"] == code, g[gate]
    order = list(connector.ACCESS_GATES)
    assert all(g[x]["status"] == "PASS" for x in order[:order.index(gate)])
    assert all(g[x]["status"] == "NOT_RUN" for x in order[order.index(gate) + 1:])
    assert connector.status()["access"]["ok"] is False


def test_access_gates_all_pass_location_and_schema_failures():
    fake = _bq_ready(_access_fake())
    r = connector.access_check()
    assert r["passed"] and [g["status"] for g in r["gates"]] == ["PASS"] * 6, r["gates"]
    assert [q[0].split("\n")[0] for q in fake.queries if not q[1]["dry_run"]] == ["-- df:access_select1"]   # only SELECT 1 really ran
    fake.location = "US"
    r = connector.access_check()
    assert {g["gate"]: g["status"] for g in r["gates"]}["location"] == "FAIL"
    fake.location = "asia-southeast1"
    fake.schema = [(n, "STRING" if n == "demand_quantity" else t) for n, t in LAYOUT]
    r = connector.access_check()
    assert r["first_failure"]["gate"] == "schema_mapping" and r["first_failure"]["code"] == "BQ_MAPPING_INVALID"


def test_backup_zip_never_contains_oauth_secrets(client, _oauth_isolation):
    import zipfile
    from app import backup
    _configure_client()
    oauth.set_http(FakeGoogle())
    st = oauth.start(open_browser=False)
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(st["auth_url"]).query))["state"]
    _callback(st["redirect_uri"], code="AUTH-CODE", state=state)
    assert _wait_status("SIGNED_IN")["status"] == "SIGNED_IN"
    zp = backup.backup_database("test")
    with zipfile.ZipFile(zp) as z:
        blob = b"".join(z.read(n) for n in z.namelist())
    for secret in (b"RT-SECRET-123", b"CLIENT-SECRET-XYZ", b"AT-1"):
        assert secret not in blob
