"""1.1.7: 2026 data window, Vietnam day boundaries, backtest span, incumbent protection, OAuth/BigQuery hardening,
deterministic newest-first ordering."""
import json
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app import cli, db, paths, timeutil
from app import settings_service as ss
from app.bq import connector, oauth, secret_store
from app.data import quality
from app.data.demand import bigquery_scope_key, data_window, load_demand
from app.messages import CATALOG, AppError
from app.ml import model, pipeline, training_explain
from app.ml.features import build_panel

from test_import import _import, _xlsx   # tests/ is on sys.path (pytest rootdir-less "prepend" import mode)

VN = timezone(timedelta(hours=7))


def _freeze(y, m, d, hh=12, mm=0, ss_=0, tz=VN):
    t = datetime(y, m, d, hh, mm, ss_, tzinfo=tz)
    timeutil.set_now_override(lambda: t)


def _rows(start: date, end: date, skus=("S1", "S2", "S3"), fcs=("F1", "F2")):
    out, n, d = [], 0, start
    while d <= end:
        for i, s in enumerate(skus):
            for j, f in enumerate(fcs):
                n += 1
                out.append((f"O{n}", datetime(d.year, d.month, d.day, 10, 0), s, f, 10 + d.weekday() + i + 2 * j))
        d += timedelta(days=1)
    return out


def _dataset(client, start, end, **kw):
    b, conf = _import(client, _xlsx(_rows(start, end, **kw)))
    assert conf.status_code == 200, conf.text
    ss.update("general", {"active_source": "MANUAL_IMPORT"})
    return b["id"]


def _insert_demand(scope, day, qty=5.0, sku="S1", fc="F1", source="MANUAL_IMPORT"):
    with db.tx() as c:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
                  "VALUES (?,?,?,?,?,?,1,?)", (scope, source, day, sku, fc, qty, timeutil.now_iso()))


def _tr(run_id):
    with db.read() as c:
        return db.one(c, "SELECT * FROM training_runs WHERE id=?", (run_id,))


# ------------------------------------------------------------------ data window
def test_window_is_2026_01_01_to_yesterday_and_stored_history_is_kept(client, fast_model):
    _freeze(2026, 3, 15)
    bid = _dataset(client, date(2025, 11, 1), date(2026, 3, 15))       # today (15/03) is accepted by the import
    _insert_demand(bid, "2026-03-20")                                   # a future row must never be used
    with db.read() as c:
        before = c.execute("SELECT COUNT(*), SUM(qty) FROM demand_daily WHERE scope_key=?", (bid,)).fetchone()
    assert data_window()["start"] == "2026-01-01" and data_window()["end"] == "2026-03-14"
    res = pipeline.train_and_publish(force=True)
    tr = _tr(res["training_run_id"])
    assert (tr["train_start"], tr["train_end"]) == ("2026-01-01", "2026-03-14"), res
    assert json.loads(tr["feature_config_json"])["data_window"]["start"] == "2026-01-01"
    rep = quality.latest_report(bid)
    assert rep["stats"]["data_window"] == {"start": "2026-01-01", "end": "2026-03-14"}
    assert rep["stats"]["demand_rows_before_window"] == 61 * 6           # Nov + Dec 2025, 6 series
    assert rep["stats"]["demand_rows_after_window_end"] == 6 + 1         # today's partial day + the future row
    assert rep["stats"]["min_date"] == "2026-01-01" and rep["stats"]["max_date"] == "2026-03-14"
    if res["status"] == "PUBLISHED":
        with db.read() as c:
            fr = db.one(c, "SELECT * FROM forecast_runs WHERE id=?", (res["forecast_run_id"],))
        assert fr["data_as_of"] == "2026-03-14" and fr["forecast_origin"] == "2026-03-15"
    with db.read() as c:                                                 # nothing outside the window was deleted
        assert tuple(c.execute("SELECT COUNT(*), SUM(qty) FROM demand_daily WHERE scope_key=?", (bid,)).fetchone()) \
            == tuple(before)


def test_vietnam_day_boundary_decides_window_membership(client):
    _freeze(2026, 1, 5)
    rows = [("O1", "2025-12-31 23:30:00", "S1", "F1", 1),       # naive = Vietnam time -> 31/12 -> outside
            ("O2", "2025-12-31T17:30:00+00:00", "S1", "F1", 2),  # 17:30 UTC = 00:30 VN on 01/01 -> inside
            ("O3", "2026-01-01 00:00:00", "S1", "F1", 4)]        # first second of the window -> inside
    b, conf = _import(client, _xlsx(rows))
    assert conf.status_code == 200, conf.text
    with db.read() as c:
        dates = dict(c.execute("SELECT order_id, order_date FROM order_lines WHERE batch_id=?", (b["id"],)).fetchall())
    assert dates == {"O1": "2025-12-31", "O2": "2026-01-01", "O3": "2026-01-01"}
    w = data_window()
    d = load_demand(b["id"], start=w["start"], end=w["end"])
    assert d["qty"].sum() == 6 and set(d["order_date"]) == {"2026-01-01"}


def test_today_closes_at_midnight_vietnam_time():
    _freeze(2026, 3, 14, 16, 59, 59, tz=timezone.utc)      # 23:59:59 VN on 14/03 -> today is 14/03
    assert data_window()["end"] == "2026-03-13"
    _freeze(2026, 3, 14, 17, 0, 0, tz=timezone.utc)        # 00:00:00 VN on 15/03 -> 14/03 is now complete
    assert data_window()["end"] == "2026-03-14"


def test_window_setting_is_validated():
    with pytest.raises(Exception):
        ss.update("data_policy", {"window_start_date": "01/01/2026"})
    with pytest.raises(Exception):
        ss.update("data_policy", {"window_start_date": ""})
    assert ss.get("data_policy").window_start_date == "2026-01-01"


def test_bigquery_reads_from_the_window_not_two_years():
    bq = ss.get("bigquery").model_copy(update={"history_start_date": ""})
    assert connector.read_range(bq, date(2026, 10, 15))[0] == date(2026, 1, 1)       # was 730 days back
    bq = bq.model_copy(update={"history_start_date": "2025-06-01"})
    assert connector.read_range(bq, date(2026, 10, 15))[0] == date(2026, 1, 1)       # never before the window
    bq = bq.model_copy(update={"history_start_date": "2026-03-01"})
    assert connector.read_range(bq, date(2026, 10, 15))[0] == date(2026, 3, 1)       # a later start is kept
    h1 = connector.mapping_hash(ss.get("bigquery"))
    ss.update("data_policy", {"window_start_date": "2026-02-01"})
    assert connector.mapping_hash(ss.get("bigquery")) != h1          # changing the window forces re-validation


def test_d1_rerun_is_idempotent_and_full_reload_keeps_rows_before_the_window(client):
    from app import sync
    from test_v116 import _bq_ready, _daily, _hist_production
    fake = _bq_ready()
    _hist_production(fake)
    sk = bigquery_scope_key(ss.get("bigquery"))
    _insert_demand(sk, "2025-06-01", 9.0, "S0", "F0", source="BIGQUERY")   # stored by an older version: not used
    y = timeutil.today_vn() - timedelta(days=1)
    fake.responses["daily"] = _daily(y, 4.0)
    r1 = sync.run_d1_sync("J1", fallback_mode=True)
    assert r1["full_reload"] and r1["rows_kept_before_window"] == 1 and r1["read_floor"] == "2026-01-01"
    with db.read() as c:
        n1 = c.execute("SELECT COUNT(*), SUM(qty) FROM demand_daily WHERE scope_key=?", (sk,)).fetchone()
    r2 = sync.run_d1_sync("J2", fallback_mode=True)
    assert r2["series_days_new"] == 0 and r2["series_days_unchanged"] == 1 and r2["series_days_updated"] == 0
    with db.read() as c:
        assert tuple(c.execute("SELECT COUNT(*), SUM(qty) FROM demand_daily WHERE scope_key=?", (sk,)).fetchone()) \
            == tuple(n1) == (2, 13.0)
        assert c.execute("SELECT COUNT(*) FROM demand_daily WHERE scope_key=? AND order_date='2025-06-01'",
                         (sk,)).fetchone()[0] == 1


def test_runs_trained_before_a_window_change_stay_explainable_and_extendable(client, fast_model):
    _freeze(2026, 3, 15)
    ss.update("data_policy", {"window_start_date": "2025-11-01"})
    ss.update("horizons", {"enabled": [7]})
    _dataset(client, date(2025, 11, 1), date(2026, 3, 14))
    res = pipeline.train_and_publish(force=True)
    assert res["status"] == "PUBLISHED", res
    tr = _tr(res["training_run_id"])
    assert tr["train_start"] == "2025-11-01"
    ss.update("data_policy", {"window_start_date": "2026-01-01"})       # later change of the rule
    with db.read() as c:
        fr = db.one(c, "SELECT * FROM forecast_runs WHERE id=?", (res["forecast_run_id"],))
    e = client.get(f"/api/forecast-runs/{fr['id']}/explain",
                   params={"sku_id": "S1", "fc_id": "F1", "target_date": fr["forecast_origin"]}).json()
    assert e["reproduction"]["status"] == "OK", e.get("reproduction")
    pts = training_explain.backtest_points(tr["id"])                     # stored metrics reproduced exactly
    assert pts["points"]
    ss.update("horizons", {"enabled": [7, 15]})
    x = pipeline.extend_forecast(fr["id"])
    assert x["status"] == "PUBLISHED" and x["reproduced_values"] == fr["n_series"] * 7


# ------------------------------------------------------------------ backtest span, leakage, determinism
def _panel(days, n=3):
    start = date(2026, 1, 1)
    rows = [{"order_date": str(start + timedelta(days=t)), "sku_id": f"S{s}", "fc_id": "F1",
             "qty": float(10 + (t % 7) + s)} for t in range(days) for s in range(n)]
    return build_panel(pd.DataFrame(rows))


def test_backtest_span_is_the_longest_valid_one_and_never_sees_its_own_window(monkeypatch):
    cfg = ss.ModelSettings(num_boost_round=10)          # defaults: up to 12 folds x 30 days, min 56 training days
    seen = []
    real = model.train

    def spy(p, c, cancel=None):
        seen.append(p.dates[-1])
        return real(p, c, cancel)
    monkeypatch.setattr(model, "train", spy)
    bt = model.backtest(_panel(288), cfg, collect=True)          # 01/01 -> 15/10/2026 = 288 days
    assert bt["config"]["folds_evaluated"] == 7 and bt["config"]["span_days"] == 210
    assert not any(n["code"] == "BACKTEST_SPAN_BELOW_6_MONTHS" for n in bt["notes"])
    for f, last in zip(bt["folds"], seen):
        assert (pd.Timestamp(f["origin"]) - last).days == 1        # trained strictly before the evaluated window
    assert all(pt["date"] >= pt["origin"] for pt in bt["points"])
    short = model.backtest(_panel(150), cfg)
    assert short["config"]["folds_evaluated"] == 3 and short["config"]["span_days"] == 90
    assert any(n["code"] == "BACKTEST_SPAN_BELOW_6_MONTHS" for n in short["notes"])


def test_same_input_gives_the_same_panel_and_metrics():
    p1, p2 = _panel(120), _panel(120)
    assert np.array_equal(p1.Y, p2.Y, equal_nan=True) and list(p1.dates) == list(p2.dates)
    cfg = ss.ModelSettings(num_boost_round=20, backtest_folds=2, backtest_horizon_days=14, backtest_step_days=14)
    assert model.backtest(p1, cfg)["metrics"] == model.backtest(p2, cfg)["metrics"]


# ------------------------------------------------------------------ incumbent protection
def _m(wape, n):
    return {"wape": wape, "bias": 0.01, "mae": 1.0, "mape": 0.2, "n_points": n, "sum_actual": 100.0,
            "sum_forecast": 100.0, "mape_points": n, "mape_excluded_points": 0, "notes": []}


def _inc(cfg_json=None):
    return {"id": "TRN-I", "model_version": "MV-I", "metrics_json": None,
            "feature_config_json": cfg_json if cfg_json is not None else json.dumps({"config": ss.ModelSettings().model_dump()})}


@pytest.mark.parametrize("cand,inc,verdict", [(0.20, 0.30, "BETTER"), (0.30, 0.20, "WORSE"), (0.25, 0.25, "EQUAL")])
def test_comparison_verdicts(monkeypatch, cand, inc, verdict):
    q = ss.QualitySettings(min_backtest_points=10)
    monkeypatch.setattr(model, "backtest", lambda *a, **k: {"metrics": _m(inc, 100), "folds": [{}]})
    out = pipeline.compare_with_incumbent(None, {"metrics": _m(cand, 100), "folds": [{}], "config": {}},
                                          ss.ModelSettings(), _inc(), q)
    assert out["verdict"] == verdict and out["method"] == "WALK_FORWARD_SAME_FOLDS"
    assert out["delta"]["wape"] == pytest.approx(cand - inc)


def test_comparison_without_enough_evaluation_data(monkeypatch):
    q = ss.QualitySettings(min_backtest_points=10)
    monkeypatch.setattr(model, "backtest", lambda *a, **k: {"metrics": _m(0.1, 5), "folds": [{}]})
    out = pipeline.compare_with_incumbent(None, {"metrics": _m(0.2, 5), "folds": [{}], "config": {}},
                                          ss.ModelSettings(), _inc(), q)
    assert out["verdict"] == "INSUFFICIENT_DATA" and out["reason"] == "TOO_FEW_EVALUATION_POINTS"
    out = pipeline.compare_with_incumbent(None, {"metrics": _m(0.2, 100), "folds": [], "config": {}},
                                          ss.ModelSettings(), _inc(), q)
    assert out["verdict"] == "INSUFFICIENT_DATA"
    out = pipeline.compare_with_incumbent(None, {"metrics": _m(0.2, 100), "folds": [{}], "config": {}},
                                          ss.ModelSettings(), _inc("{}"), q)
    assert out["verdict"] == "INSUFFICIENT_DATA" and out["reason"] == "INCUMBENT_CONFIG_UNAVAILABLE"


def test_a_model_in_use_is_never_replaced_automatically(client, fast_model):
    _freeze(2026, 3, 15)
    _dataset(client, date(2026, 1, 1), date(2026, 3, 14))
    r1 = pipeline.train_and_publish(force=True)
    assert r1["status"] == "PUBLISHED", r1
    assert json.loads(_tr(r1["training_run_id"])["quality_gate_json"])["promotion"]["decision"] == "INITIAL_MODEL"
    r2 = pipeline.train_and_publish(force=True)                       # same data + same configuration
    assert r2["status"] == "CANDIDATE" and r2["reason_code"] == "PROMOTION_REVIEW_REQUIRED", r2
    assert r2["verdict"] == "EQUAL"                                   # identical method on identical folds
    t2 = _tr(r2["training_run_id"])
    assert (t2["status"], t2["reject_reason"]) == ("REJECTED", "PROMOTION_REVIEW_REQUIRED")
    assert (paths.models_dir() / t2["model_path"]).is_file()
    with db.read() as c:
        assert pipeline.latest_published(conn=c)["id"] == r1["forecast_run_id"]        # forecast in use unchanged
        assert c.execute("SELECT COUNT(*) FROM forecast_runs").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM alerts WHERE code='CANDIDATE_READY_FOR_REVIEW'").fetchone()[0] == 1
    # the scheduled run does not retrain the same data while the candidate waits
    r3 = pipeline.train_and_publish(force=False)
    assert r3["status"] == "SKIPPED" and r3["training_run_id"] == r2["training_run_id"]
    d = client.get(f"/api/training-runs/{r2['training_run_id']}").json()
    assert d["can_promote"] and not d["in_use"] and d["incumbent_training_run_id"] == r1["training_run_id"]
    assert client.post(f"/api/training-runs/{r2['training_run_id']}/promote", json={}).status_code == 422
    p = client.post(f"/api/training-runs/{r2['training_run_id']}/promote", json={"confirm": True})
    assert p.status_code == 200, p.text
    new_fr = p.json()["forecast_run_id"]
    with db.read() as c:
        assert pipeline.latest_published(conn=c)["id"] == new_fr
        assert db.one(c, "SELECT training_run_id FROM forecast_runs WHERE id=?", (new_fr,))["training_run_id"] == r2["training_run_id"]
        assert db.one(c, "SELECT status FROM training_runs WHERE id=?", (r1["training_run_id"],))["status"] == "ACCEPTED"
        assert db.one(c, "SELECT id FROM forecast_runs WHERE id=?", (r1["forecast_run_id"],))       # old run kept
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE action='MODEL_PROMOTED'").fetchone()[0] == 1
    d = client.get(f"/api/training-runs/{r2['training_run_id']}").json()
    assert d["in_use"] and not d["can_promote"]
    again = client.post(f"/api/training-runs/{r2['training_run_id']}/promote", json={"confirm": True})
    assert again.status_code == 409 and again.json()["code"] == "PROMOTION_NOT_ALLOWED"


def test_promotion_is_refused_when_the_data_changed(client, fast_model):
    _freeze(2026, 3, 15)
    bid = _dataset(client, date(2026, 1, 1), date(2026, 3, 14))
    assert pipeline.train_and_publish(force=True)["status"] == "PUBLISHED"
    r2 = pipeline.train_and_publish(force=True)
    assert r2["status"] == "CANDIDATE"
    _insert_demand(bid, "2026-03-14", 99.0, "S9", "F9")
    r = client.post(f"/api/training-runs/{r2['training_run_id']}/promote", json={"confirm": True})
    assert r.status_code == 409 and r.json()["code"] == "DATA_CHANGED_SINCE_TRAINING"
    assert _tr(r2["training_run_id"])["status"] == "REJECTED"


# ------------------------------------------------------------------ OAuth / BigQuery
def _ready():
    from test_v116 import _access_fake, _bq_ready
    return _bq_ready(_access_fake())


def _gates(r):
    return {g["gate"]: (g["status"], g.get("code")) for g in r["gates"]}


def _token(store, client_id="123-abc.apps.googleusercontent.com"):
    store.set(oauth.TOKEN_ITEM, json.dumps({"refresh_token": "RT-9", "client_id": client_id, "email": "a@b.c",
                                            "scopes": oauth.SCOPES, "obtained_at": "x"}))


def test_auth_gate_really_asks_google_and_separates_sign_in_from_permissions():
    from google.auth.exceptions import RefreshError, TransportError
    _ready()
    oauth.save_client("123-abc.apps.googleusercontent.com", "CS-1")
    _token(secret_store.store())
    ss.update("bigquery", {"oauth_enabled": True})
    connector.set_auth_probe(lambda bq: (_ for _ in ()).throw(RefreshError("invalid_grant: Token has been expired or revoked.")))
    g = _gates(connector.access_check())
    assert g["auth"] == ("FAIL", "BQ_AUTH_EXPIRED") and g["api_and_dataset"][0] == "NOT_RUN"
    assert oauth.status()["status"] == "REVOKED"
    connector.set_auth_probe(lambda bq: (_ for _ in ()).throw(RefreshError("invalid_client: The OAuth client was deleted.")))
    assert _gates(connector.access_check())["auth"] == ("FAIL", "OAUTH_CLIENT_INVALID")
    connector.set_auth_probe(lambda bq: (_ for _ in ()).throw(TransportError("Failed to resolve oauth2.googleapis.com")))
    assert _gates(connector.access_check())["auth"] == ("FAIL", "BQ_UNAVAILABLE")      # network, not the login
    _token(secret_store.store())
    connector.set_auth_probe(lambda bq: {"verified": True, "account": "planner@buymed.example"})
    r = connector.access_check()
    assert r["passed"] and r["identity"]["verified"] and r["identity"]["account"] == "planner@buymed.example"
    st = oauth.status()
    assert st["status"] == "SIGNED_IN" and st["verified_at"]


def test_missing_scope_is_not_reported_as_missing_iam_permission():
    fake = _ready()
    connector.set_auth_probe(lambda bq: {"verified": True, "account": "x@y.z"})
    fake.errors["dataset"] = type("Forbidden", (Exception,), {})("403 Request had insufficient authentication scopes.")
    assert _gates(connector.access_check())["api_and_dataset"] == ("FAIL", "OAUTH_SCOPE_NOT_GRANTED")
    fake.errors["dataset"] = type("Forbidden", (Exception,), {})("Access Denied: Dataset p:d: Permission bigquery.datasets.get denied")
    assert _gates(connector.access_check())["api_and_dataset"] == ("FAIL", "BQ_PERMISSION_DENIED")


def _client_json(kind="installed", cid="555-xyz.apps.googleusercontent.com", secret="GOCSPX-FAKE-SECRET-0001"):
    return json.dumps({kind: {"client_id": cid, "project_id": "p", "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                              "token_uri": "https://oauth2.googleapis.com/token", "client_secret": secret,
                              "redirect_uris": ["http://localhost"]}})


def test_client_json_import_desktop_only_and_secret_never_stored_in_db(client):
    r = client.post("/api/bigquery/oauth/client-file", json={"content": _client_json("web")})
    assert r.status_code == 422 and r.json()["code"] == "OAUTH_CLIENT_WRONG_TYPE"
    r = client.post("/api/bigquery/oauth/client-file", json={"content": "not json"})
    assert r.status_code == 422 and r.json()["code"] == "OAUTH_CLIENT_FILE_INVALID"
    r = client.post("/api/bigquery/oauth/client-file", json={"content": _client_json(cid="bad id")})
    assert r.status_code == 422 and r.json()["code"] == "OAUTH_CLIENT_FILE_INVALID"
    r = client.post("/api/bigquery/oauth/client-file", json={"content": _client_json()})
    assert r.status_code == 200 and r.json()["configured"] and r.json()["client_id"].startswith("555-")
    assert secret_store.store().get(oauth.CLIENT_SECRET_ITEM) == "GOCSPX-FAKE-SECRET-0001"
    with db.read() as c:
        dump = "\n".join(str(tuple(x)) for t in ("app_settings", "settings_history", "sync_state", "audit_log")
                         for x in c.execute(f"SELECT * FROM {t}"))
    assert "GOCSPX-FAKE-SECRET-0001" not in dump
    assert "GOCSPX-FAKE-SECRET-0001" not in json.dumps(client.get("/api/bigquery/identity").json())


def test_changing_the_client_removes_the_old_sign_in():
    class G:
        calls = []

        def post(self, url, data=None, timeout=None):
            G.calls.append(url)
            return type("R", (), {"status_code": 200})()
    oauth.set_http(G())
    try:
        oauth.save_client("123-abc.apps.googleusercontent.com", "CS-1")
        _token(secret_store.store())
        assert oauth.status()["status"] == "SIGNED_IN"
        out = oauth.save_client("999-new.apps.googleusercontent.com", "CS-2")
        assert out["status"] == "NOT_SIGNED_IN" and out["error"]["code"] == "OAUTH_CLIENT_CHANGED"
        assert secret_store.store().get(oauth.TOKEN_ITEM) is None and oauth.REVOKE_URI in G.calls
        _token(secret_store.store(), "123-abc.apps.googleusercontent.com")      # a stale token of the old client
        assert oauth.status()["status"] == "CLIENT_CHANGED"
        with pytest.raises(AppError) as e:
            oauth.credentials()
        assert e.value.code == "OAUTH_CLIENT_CHANGED"
    finally:
        oauth.set_http(None)


def test_bq_check_cli_reports_the_first_failure_without_secrets(capsys):
    oauth.save_client("123-abc.apps.googleusercontent.com", "CS-TOP-SECRET")
    _token(secret_store.store())
    assert cli.main(["bq-check"]) == 1                     # dataset/table not configured on a fresh database
    out = capsys.readouterr().out
    res = json.loads(out)
    assert res["access"]["first_failure"]["code"] == "BQ_NOT_CONFIGURED" and res["next_action"]["vi"]
    assert res["identity"]["windows_user"] is not None and res["oauth"]["status"] == "SIGNED_IN"
    assert "CS-TOP-SECRET" not in out and "RT-9" not in out


def test_every_oauth_and_bigquery_code_has_an_actionable_message():
    import pathlib
    import re
    src = "\n".join(p.read_text(encoding="utf-8") for p in (pathlib.Path(connector.__file__).parent).glob("*.py"))
    # codes really emitted: AppError("X"), {"code": "X"} and the (status, code) pairs of the OAuth classifier
    pat = r'(?:AppError\(\s*|"code":\s*|return "[A-Z]+", )"((?:OAUTH|BQ)_[A-Z_]+)"'
    codes = set(re.findall(pat, src))
    assert {"BQ_AUTH_MISSING", "OAUTH_CLIENT_CHANGED", "OAUTH_BLOCKED"} <= codes      # the scan itself works
    missing = sorted(c for c in codes if c not in CATALOG)
    assert not missing, missing


# ------------------------------------------------------------------ deterministic newest-first
def test_rows_with_the_same_timestamp_resolve_to_the_last_insert(client):
    same = "2099-01-01T00:00:00+00:00"
    with db.tx() as c:
        for tid in ("TRN-A", "TRN-B"):
            c.execute("INSERT INTO training_runs(id, model_version, scope_key, data_source, status, started_at) "
                      "VALUES (?, ?, 'SC', 'DEMO', 'ACCEPTED', ?)", (tid, "MV-" + tid, same))
        for fid in ("FCR-A", "FCR-B"):
            c.execute("INSERT INTO forecast_runs(id, training_run_id, model_version, scope_key, data_source, "
                      "forecast_origin, data_as_of, horizons_json, max_horizon, n_series, status, created_at) "
                      "VALUES (?, 'TRN-A', 'MV-TRN-A', 'SC', 'DEMO', '2099-01-02', '2099-01-01', '[7]', 7, 0, "
                      "'PUBLISHED', ?)", (fid, same))
        for rid in ("DQ-A", "DQ-B"):
            c.execute("INSERT INTO validation_reports(id, scope_key, data_source, created_at, can_train, report_json) "
                      "VALUES (?, 'SC', 'DEMO', ?, 1, ?)", (rid, same, json.dumps({"id": rid})))
    assert [r["id"] for r in client.get("/api/training-runs", params={"scope_key": "SC"}).json()][:2] == ["TRN-B", "TRN-A"]
    with db.read() as c:
        assert pipeline.latest_published("SC", c)["id"] == "FCR-B"
        assert pipeline.incumbent("SC", c)["forecast_run"]["id"] == "FCR-B"
    assert quality.latest_report("SC")["id"] == "DQ-B"
