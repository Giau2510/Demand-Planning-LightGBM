"""1.4.9 review R-149: an auxiliary table is not changed while a job that reads it is waiting / running / waiting to
retry; the data check keeps working when the stored bigquery settings fail validation."""
import json

import pytest

from app import data_checks, db, paths
from app import settings_service as ss
from app.bq import source_tables
from app.timeutil import now_iso

from test_v116 import _bq_ready
from test_v149_source_tables import AUX, REAL, SETTING, _fake

NEW = "company-prod-01.sales_dw.new_table"


def _job(job_type, status):
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) VALUES (?,?,?,?,?,?)",
                  (f"JOB-{job_type}-{status}", job_type, f"K-{job_type}-{status}", "MANUAL", status, now_iso()))


@pytest.mark.parametrize("job_type", source_tables.READER_JOBS)
@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "RETRY_WAIT"])
def test_a_new_aux_table_is_refused_while_a_reader_job_is_active(client, job_type, status):
    _bq_ready(_fake({NEW: REAL[AUX["openhours"]]}))
    _job(job_type, status)
    r = client.put("/api/bigquery/source-tables/openhours", json={"table_id": NEW})
    assert r.status_code == 409 and r.json()["code"] == "BQ_TABLE_CHANGE_JOB_ACTIVE", r.text
    assert job_type in r.json()["detail"]
    assert ss.get("daily_forecast").openhours_table == AUX["openhours"]        # unchanged
    assert source_tables.last_check("openhours") is None                       # refused before the check


@pytest.mark.parametrize("kind", list(AUX))
def test_every_aux_kind_is_guarded_and_saves_once_the_job_ended(client, kind):
    _bq_ready(_fake({NEW: REAL[AUX[kind]]}))
    _job("FORECAST_REFRESH", "RUNNING")
    assert client.put(f"/api/bigquery/source-tables/{kind}", json={"table_id": NEW}).status_code == 409
    with db.tx() as c:
        c.execute("UPDATE job_runs SET status='SUCCEEDED'")
    r = client.put(f"/api/bigquery/source-tables/{kind}", json={"table_id": NEW})
    assert r.status_code == 200, r.text
    section, key = SETTING[kind]
    assert getattr(ss.get(section), key) == NEW


def test_other_jobs_the_same_table_and_d0_are_not_blocked(client):
    _bq_ready(_fake({NEW: REAL[AUX["avg_demand"]]}))
    _job("D0_SYNC", "RUNNING")                                                  # does not read the aux tables
    _job("TRAIN_PUBLISH", "PENDING")
    assert client.put("/api/bigquery/source-tables/avg_demand", json={"table_id": NEW}).status_code == 200
    _job("FORECAST_REFRESH", "RUNNING")
    # re-saving the table already configured changes nothing: allowed
    assert client.put("/api/bigquery/source-tables/avg_demand", json={"table_id": NEW}).status_code == 200
    # the D-0 table keeps its own rules (not guarded by the aux reader jobs)
    assert client.put("/api/bigquery/source-tables/d0", json={"table_id": ss.get("bigquery").d0_table_id}).status_code == 200


def test_the_data_check_falls_back_to_the_evidence_scope_when_bigquery_settings_are_invalid(client):
    ss.update("bigquery", {"dataset_id": "gold_buymed_vn2", "source_table": "demand_planing_lightgbm"})
    with db.tx() as c:
        v = json.loads(c.execute("SELECT value_json FROM app_settings WHERE section='bigquery'").fetchone()[0])
        v["project_id"] = "NOT A PROJECT"                                       # fails the settings validation
        c.execute("UPDATE app_settings SET value_json=? WHERE section='bigquery'", (json.dumps(v),))
    chk = {x["check"]: x for x in data_checks.run(paths.db_path())["checks"]}
    assert chk["open_hours_owner_override"]["status"] == "OK"                 # no approved row: nothing uncovered
