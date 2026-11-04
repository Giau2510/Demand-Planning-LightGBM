"""1.4.0 S5: POST /api/sel2/export runs as a FORECAST_EXPORT job (mode MANUAL, trigger MANUAL) instead of synchronously:
the response is the job row, the job result carries version / n_rows / sha256, a second click while one is queued or
running returns that job (already_active), each click after it has finished is a new job (a new version), and the
confirm / switch checks still refuse before any job is created. Integration with fakes (isolated temporary database,
TestClient with background.SYNC_MODE, export.write_daily_export faked except in the last test)."""
import json

import pytest

from app import db
from app import settings_service as ss
from app.ml.sel2 import export
from app.timeutil import now_iso

D = "2026-11-02"


@pytest.fixture
def fake_write(monkeypatch):
    calls = []

    def write(d, trigger="SCHEDULE", job_id=None, scope_key=None):
        calls.append({"d": str(d), "trigger": trigger, "job_id": job_id})
        return {"id": f"EXP{len(calls)}", "path": "exports/du_bao/x.xlsx", "version": len(calls), "sha256": "ab" * 32,
                "n_rows": 14, "is_stale": False, "flags": ["OPEN_HOURS_LAG"], "summary": {}}
    monkeypatch.setattr(export, "write_daily_export", write)
    return calls


def _jobs() -> list[dict]:
    with db.read() as c:
        return db.rows(c, "SELECT * FROM job_runs WHERE job_type='FORECAST_EXPORT' ORDER BY created_at, rowid")


def _post(client, **body):
    return client.post("/api/sel2/export", json={"date": D, "confirm": True, **body})


def test_post_returns_a_job_whose_result_has_the_version(sel2_on, client, fake_write):
    r = _post(client)
    job = r.json()
    assert r.status_code == 200 and job["job_type"] == "FORECAST_EXPORT" and job["trigger"] == "MANUAL"
    assert job["status"] == "SUCCEEDED" and job["already_active"] is False
    res = json.loads(job["result_json"])
    assert res["params"] == {"business_date": D, "mode": "MANUAL"}
    assert res["result"] == {"status": "DONE", "mode": "MANUAL", "business_date": D, "version": 1, "n_rows": 14,
                             "is_stale": False, "sha256": "ab" * 32, "path": "exports/du_bao/x.xlsx",
                             "flags": ["OPEN_HOURS_LAG"]}
    assert fake_write == [{"d": D, "trigger": "MANUAL", "job_id": job["id"]}]


def test_each_finished_click_is_a_new_job_and_version(sel2_on, client, fake_write):
    a, b = _post(client).json(), _post(client).json()
    assert a["id"] != b["id"] and a["idempotency_key"] != b["idempotency_key"]
    assert [json.loads(j["result_json"])["result"]["version"] for j in (a, b)] == [1, 2]
    assert len(_jobs()) == 2 and len(fake_write) == 2


@pytest.mark.parametrize("status", ["PENDING", "RUNNING"])
def test_second_post_while_one_is_active_returns_it(sel2_on, client, fake_write, status):
    at = now_iso()
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, "
                  "created_at, result_json) VALUES ('JOB-ACTIVE', 'FORECAST_EXPORT', 'FORECAST_EXPORT:MANUAL:x', "
                  "'MANUAL', ?, 0, 1, ?, ?)", (status, at, json.dumps({"params": {"business_date": D, "mode": "MANUAL"}})))
    r = _post(client)
    assert r.status_code == 200 and r.json()["id"] == "JOB-ACTIVE" and r.json()["already_active"] is True
    assert len(_jobs()) == 1 and fake_write == []


def test_switch_off_refuses_before_any_job(sel2_off, client, fake_write):
    r = _post(client)
    assert r.status_code == 409 and r.json()["code"] == "SEL2_PIPELINE_DISABLED"
    assert _jobs() == [] and fake_write == []


def test_no_confirm_and_bad_date_refuse_before_any_job(sel2_on, client, fake_write):
    r = client.post("/api/sel2/export", json={"date": D})
    assert r.status_code == 409 and r.json()["code"] == "SEL2_EXPORT_CONFIRM_REQUIRED"
    r = _post(client, confirm=False)
    assert r.status_code == 409 and r.json()["code"] == "SEL2_EXPORT_CONFIRM_REQUIRED"
    assert _post(client, date="02/11/2026").status_code == 422
    assert _jobs() == [] and fake_write == []


def test_manual_export_runs_even_with_the_refresh_schedule_off(sel2_on, client, fake_write):
    """FORECAST_EXPORT shares the refresh flow's switch; like every manual job it is not stopped by it."""
    ss.update("schedule", {"refresh_enabled": False}, note="tests: refresh schedule off")
    job = _post(client).json()
    assert job["status"] == "SUCCEEDED" and json.loads(job["result_json"])["result"]["version"] == 1


def test_export_error_fails_the_job_with_its_code(sel2_on, client, monkeypatch):
    from app.messages import AppError

    def boom(*a, **k):
        raise AppError("SEL2_PIPELINE_DISABLED", 409)
    monkeypatch.setattr(export, "write_daily_export", boom)
    job = _post(client).json()
    assert job["status"] == "FAILED" and job["reason_code"] == "SEL2_PIPELINE_DISABLED"
