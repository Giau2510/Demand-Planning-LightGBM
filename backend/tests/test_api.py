from fastapi.testclient import TestClient

from app import db
from app import settings_service as ss


def test_health_and_status(client):
    assert client.get("/api/health").json()["ok"]
    st = client.get("/api/system/status").json()
    assert st["active_source"] == "DEMO" and st["scope_error"]["code"] == "NO_ACTIVE_DATASET"


def test_csrf_and_host_protection():
    from app.main import create_app
    with TestClient(create_app()) as c:
        r = c.post("/api/demo/generate", json={})
        assert r.status_code == 403 and r.json()["code"] == "CSRF_BLOCKED"
        r = c.post("/api/demo/generate", json={}, headers={"X-DF-Client": "web", "Origin": "https://evil.example"})
        assert r.status_code == 403
        r = c.get("/api/health", headers={"Host": "evil.example"})
        assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN_HOST"
        assert c.get("/api/health").status_code == 200


def test_horizon_settings_validation_and_history(client):
    r = client.put("/api/settings/horizons", json={**ss.get("horizons").model_dump(), "enabled": [7, 0]})
    assert r.status_code == 422
    r = client.put("/api/settings/horizons", json={**ss.get("horizons").model_dump(), "enabled": [9]})
    assert r.status_code == 422          # 9 is not in the choice list
    body = ss.get("horizons").model_dump()
    body["choices"] = body["choices"] + [10]
    body["enabled"] = [7, 10]
    r = client.put("/api/settings/horizons", json=body)
    assert r.status_code == 200 and r.json()["enabled"] == [7, 10]
    r = client.put("/api/settings/horizons", json={**body, "choices": body["choices"] + [5000]})
    assert r.status_code == 422          # beyond safety limit
    hist = client.get("/api/settings/horizons/history").json()
    assert hist and hist[0]["value"]["enabled"] == [7, 10]
    r = client.post("/api/settings/horizons/reset")
    assert r.json()["enabled"] == [7, 15, 30]


def test_schedule_and_quality_validation(client):
    r = client.put("/api/settings/schedule", json={**ss.get("schedule").model_dump(), "d0_times": ["25:00"]})
    assert r.status_code == 422
    r = client.put("/api/settings/quality", json={**ss.get("quality").model_dump(), "wape_max": -1})
    assert r.status_code == 422
    q = client.get("/api/settings").json()["quality"]
    assert q["approved_by_business"] is False


def test_full_demo_flow_dashboard_results_snapshots(client, fast_model):
    r = client.post("/api/demo/generate", json={"days": 150, "n_skus": 8, "seed": 3})
    assert r.status_code == 200
    j = client.post("/api/training/run", json={}).json()
    assert j["status"] == "SUCCEEDED" and j["reason_code"] == "FORECAST_PUBLISHED", j
    d = client.get("/api/dashboard?horizon=15").json()
    f = d["forecast"]
    assert f["data_source"] == "DEMO" and f["horizon"] == 15 and len(f["daily"]) == 15
    assert abs(f["grand_total"] - sum(x["total"] for x in f["daily"])) < 1e-6
    run_id = d["system"]["latest_forecast_run"]["id"]
    vals = client.get(f"/api/forecast-runs/{run_id}/values?horizon=7&limit=10").json()
    assert vals["total"] == d["system"]["latest_forecast_run"]["n_series"] * 7
    s = client.get(f"/api/forecast-runs/{run_id}/summary?horizon=30").json()
    assert s["end_date"] > s["start_date"]
    r = client.get(f"/api/forecast-runs/{run_id}/summary?horizon=31")
    assert r.status_code == 422
    assert client.get(f"/api/forecast-runs/{run_id}/export.xlsx?horizon=7").status_code == 200
    tr = client.get("/api/training-runs").json()[0]
    det = client.get(f"/api/training-runs/{tr['id']}").json()
    assert det["backtest"]["folds"] and det["quality_gate"]["passed"]
    j = client.post("/api/jobs/run", json={"job_type": "D0_SYNC"}).json()
    assert j["status"] == "SUCCEEDED"
    snaps = client.get("/api/snapshots").json()
    assert len(snaps) == 1 and snaps[0]["data_source"] == "DEMO"
    det = client.get(f"/api/snapshots/{snaps[0]['id']}").json()
    assert det["measurement_note"]["vi"].startswith("Thực tế lũy kế")
    assert client.get(f"/api/snapshots/{snaps[0]['id']}/export.xlsx").status_code == 200
    dq = client.get("/api/data-quality?refresh=true").json()
    assert dq["can_train"] and dq["stats"]["batch_id"].startswith("DEMO")
    jobs = client.get("/api/jobs").json()
    assert {x["job_type"] for x in jobs} >= {"TRAIN_PUBLISH", "D0_SYNC"}
    assert client.get("/api/forecast-runs/" + run_id + "/accuracy").json()["available"] is False


def test_published_forecast_survives_batch_replacement(client, fast_model):
    """Replacing the dataset a forecast was built on must not change that stored forecast."""
    sample = client.get("/api/templates/sample-history.xlsx").content
    up = client.post("/api/imports/upload", files={"file": ("s.xlsx", sample, "application/octet-stream")}).json()
    b = client.post(f"/api/imports/uploads/{up['upload_id']}/validate",
                    json={"sheet": "Data", "mapping": up["suggested_mapping"]}).json()
    client.post(f"/api/imports/{b['id']}/confirm", json={})
    client.put("/api/active-source", json={"source": "MANUAL_IMPORT"})
    j = client.post("/api/training/run", json={}).json()
    assert j["reason_code"] == "FORECAST_PUBLISHED", j
    with db.read() as c:
        before = c.execute("SELECT COUNT(*), SUM(yhat) FROM forecast_values").fetchone()
    up = client.post("/api/imports/upload", files={"file": ("s.xlsx", sample, "application/octet-stream")},
                     data={"replace_batch_id": b["id"]}).json()
    nb = client.post(f"/api/imports/uploads/{up['upload_id']}/validate",
                     json={"sheet": "Data", "mapping": up["suggested_mapping"]}).json()
    client.post(f"/api/imports/{nb['id']}/confirm", json={})
    with db.read() as c:
        after = c.execute("SELECT COUNT(*), SUM(yhat) FROM forecast_values").fetchone()
    assert tuple(before) == tuple(after)
    assert ss.get("general").active_import_batch_id == nb["id"]


def test_backup_endpoint(client):
    r = client.post("/api/system/backups")
    assert r.status_code == 200 and r.json()["file"].endswith(".zip")
    assert client.get("/api/system/backups").json()["files"]


def test_data_persists_across_app_restart(client):
    client.post("/api/demo/generate", json={"days": 90, "n_skus": 4})
    ss.update("quality", {"wape_max": 0.33})
    from app.main import create_app
    with TestClient(create_app(), headers={"X-DF-Client": "web"}) as c2:
        st = c2.get("/api/system/status").json()
        assert st["scope"]["data_source"] == "DEMO"
        assert c2.get("/api/settings").json()["quality"]["wape_max"] == 0.33
