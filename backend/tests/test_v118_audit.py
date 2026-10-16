"""Audit of 16/10/2026 (source after 1.1.8): regressions for the fixes made during the audit.
1. A D-1 read that returns no rows never deletes stored days: nothing is written, the job retries (SOURCE_INCOMPLETE).
2. The schedules view reports the RESULT status of each job: a training job can SUCCEED as a job while its result is
   REJECTED / FAILED, and the page must be able to show that."""
import json
from datetime import timedelta

import pytest

from app import db, sync, timeutil
from app import settings_service as ss
from app.data.demand import bigquery_scope_key


def _demand(sk):
    with db.read() as c:
        return tuple(c.execute("SELECT COUNT(*), COALESCE(SUM(qty), 0) FROM demand_daily WHERE scope_key=?",
                               (sk,)).fetchone())


def _empty_read():
    """What the fake BigQuery returns for a source that is momentarily empty (rebuild, view returning nothing)."""
    return [{"_kind": "TOTAL_READ", "_reason": "0", "qty": 0.0, "n_rows": 0},
            {"_kind": "TOTAL_KEPT", "_reason": "0", "qty": 0.0, "n_rows": 0}]


@pytest.mark.parametrize("second_run_full", [False, True])
def test_d1_empty_source_read_never_deletes_stored_days(client, second_run_full):
    from test_v116 import _bq_ready, _daily, _hist_production      # tests/ is on sys.path
    fake = _bq_ready()
    _hist_production(fake)
    sk = bigquery_scope_key(ss.get("bigquery"))
    y = timeutil.today_vn() - timedelta(days=1)
    fake.responses["daily"] = _daily(y, 4.0)
    first = sync.run_d1_sync("J1", fallback_mode=True)
    assert first["full_reload"] and _demand(sk) == (1, 4.0)
    if second_run_full:             # forget the watermark: the next run is a full reload of the whole window
        with db.tx() as c:
            c.execute("DELETE FROM sync_state WHERE name=?", (f"last_d1_sync:{sk}",))
    fake.responses["daily"] = _empty_read()
    with pytest.raises(sync.Retryable) as e:
        sync.run_d1_sync("J2", fallback_mode=True)
    assert e.value.code == "SOURCE_INCOMPLETE"
    detail = json.loads(str(e.value).split(": ", 1)[1])            # "SOURCE_INCOMPLETE: {...}"
    assert detail["reason"] == "EMPTY_READ" and detail["rows_stored"] == 1
    assert _demand(sk) == (1, 4.0)                                  # nothing deleted, nothing written


def test_d1_empty_read_on_an_empty_scope_is_not_an_error(client):
    from test_v116 import _bq_ready, _hist_production
    fake = _bq_ready()
    _hist_production(fake)
    fake.responses["daily"] = _empty_read()
    res = sync.run_d1_sync("J1", fallback_mode=True)               # nothing stored, nothing to protect
    assert res["series_days_written"] == 0


def test_schedule_history_reports_the_result_status_of_each_job(client):
    now = timeutil.now_iso()
    with db.tx() as c:
        for jid, key, res in (("J-REJ", "TRAIN_PUBLISH:MANUAL:a", {"status": "REJECTED", "reason_code": "QUALITY_GATE_FAILED"}),
                              ("J-PUB", "TRAIN_PUBLISH:MANUAL:b", {"status": "PUBLISHED", "reason_code": "FORECAST_PUBLISHED"})):
            c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, "
                      "created_at, finished_at, reason_code, result_json) VALUES (?, 'TRAIN_PUBLISH', ?, 'MANUAL', "
                      "'SUCCEEDED', 1, 1, ?, ?, ?, ?)",
                      (jid, key, now, now, res["reason_code"], json.dumps({"params": {}, "result": res})))
    train = client.get("/api/schedules").json()["flows"]["train"]
    by_id = {h["id"]: h for h in train["history"]}
    assert by_id["J-REJ"]["status"] == "SUCCEEDED" and by_id["J-REJ"]["result_status"] == "REJECTED"
    assert by_id["J-PUB"]["result_status"] == "PUBLISHED"
    assert train["last_run"]["result_status"] in ("REJECTED", "PUBLISHED")
