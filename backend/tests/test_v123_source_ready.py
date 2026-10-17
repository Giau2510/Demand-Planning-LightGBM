"""1.2.3 (P0 2026-10-17 evening): manual trainings JOB-20261017121820-57FB9B / JOB-20261017122150-90EEDA were skipped
with SOURCE_NOT_READY. Cause on production: saving the BigQuery field mapping at 17:32 (unit_price OPTIONAL ->
REQUIRED) switched production mode off (by design: a new mapping needs a new full-period validation + activation); the
job reported a bare code after ~35 s of data fingerprint, and the Jobs page showed "On - loaded by the scheduler" for the
training flow from its switch alone. 1.2.3 says since when / which change / how to fix, refuses a manual training at
once (no skipped job), never blocks a manual training on schedule-only conditions, shows the effective flow state and
never switches the source to DEMO when production is turned off.

Kind of evidence: integration on an isolated database (conftest: temporary DF_DATA_DIR) with a FAKE BigQuery client."""
import pytest

from app import db
from app import settings_service as ss
from app.bq import connector
from app.jobs import flows
from app.messages import AppError
from app.ml import pipeline

from test_v118 import _bq_ready_production
from test_v122_bigquery_policy import _bq_history


def _codes(r):
    return [x["code"] for x in r["reasons"]]


def _jobs():
    with db.read() as c:
        return c.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0]


def _mapping_with(unit_price):
    fm = {k: v.model_dump() for k, v in ss.get("bigquery").field_mapping.items()}
    fm["unit_price"] = unit_price
    return fm


def _save_mapping_like_on_17_10(client):
    """The production change of 17/10 17:32: unit_price <- sales_price, OPTIONAL -> REQUIRED, saved on the mapping page."""
    r = client.post("/api/bigquery/mapping", json={"field_mapping": _mapping_with({"column": "sales_price", "usage": "REQUIRED"})})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ 0: test isolation (incident of 17/10/2026 19:49)
def test_paths_never_reach_the_installation_even_after_monkeypatch_undo(monkeypatch):
    """A test that called monkeypatch.undo() removed conftest's DF_DATA_DIR and one settings write reached the live
    database. The process-wide fallback of conftest keeps every path in a throw-away folder. Resolves paths only."""
    from app import paths
    monkeypatch.undo()
    for p in (paths.db_path(), paths.storage_config_path()):
        assert "df-tests-" in str(p) and "Lightgbm AI" not in str(p) and "DemandForecast" not in str(p), p


# ------------------------------------------------------------------ 1, 5, 7: ready source; D-0 and schedules play no part
def test_ready_production_source_trains_by_hand_whatever_the_schedules_and_d0(client, fast_model):
    _bq_ready_production()
    _bq_history()
    ss.update("horizons", {"enabled": [7]})
    ss.update("schedule", {"train_enabled": False, "d1_enabled": False, "d0_enabled": False})
    assert flows.readiness("d1")["ready"] and flows.source_blockers() == []
    # D-0 is not ready (no validated D-0 SQL) - that never concerns D-1 or the training
    assert "SQL_NOT_VALIDATED" in _codes(flows.readiness("d0"))
    # the SCHEDULED training waits for today's D-1 (D-1 flow off); a MANUAL run is not refused for that
    assert "TRAIN_WAITS_FOR_D1" in _codes(flows.readiness("train"))
    v = client.get("/api/schedules/train").json()
    assert v["manual_readiness"]["ready"] is True and not v["readiness"]["ready"]
    r = client.post("/api/schedules/train/run")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["status"] == "SUCCEEDED" and j["reason_code"] == "FORECAST_PUBLISHED_WITH_WARNING", j
    j2 = client.post("/api/training/run", json={"force": True}).json()      # the dashboard / performance button
    assert j2["status"] == "SUCCEEDED" and j2["reason_code"] == "PROMOTION_REVIEW_REQUIRED", j2
    s = ss.get("schedule")
    assert (s.train_enabled, s.d1_enabled, s.d0_enabled) == (False, False, False)   # a manual run switches nothing


# ------------------------------------------------------------------ 2, 3: production off after a mapping save; official recovery
def test_mapping_save_switches_production_off_and_every_reason_says_since_when_why_and_how(client, monkeypatch):
    _bq_ready_production()
    out = _save_mapping_like_on_17_10(client)
    assert out["production_switched_off"] is True and out["check"]["ok"] is True
    bq = ss.get("bigquery")
    assert bq.production_enabled is False and bq.field_mapping["unit_price"].usage == "REQUIRED"
    assert ss.get("general").active_source == "BIGQUERY"                      # the source is never changed
    for flow in ("d1", "d0", "train"):
        r = flows.readiness(flow)
        why = next(x for x in r["reasons"] if x["code"] == "SOURCE_NOT_READY")
        assert "since" in why["detail"] and "field mapping saved" in why["detail"], why
        assert "enable production" in why["detail"] and why["vi"] and why["en"]
    # a manual training is refused AT ONCE, with the reason, and no job row is created
    n = _jobs()
    r = client.post("/api/training/run", json={"force": True})
    assert r.status_code == 409 and r.json()["code"] == "SOURCE_NOT_READY"
    assert "field mapping saved" in r.json()["detail"] and _jobs() == n
    r = client.post("/api/jobs/run", json={"job_type": "TRAIN_PUBLISH"})
    assert r.status_code == 409 and r.json()["code"] == "SOURCE_NOT_READY" and _jobs() == n
    # the pipeline itself (scheduled run) stops before the data fingerprint (~35 s on the real table). NB: a nested
    # context, never monkeypatch.undo() - that would also remove conftest's DF_DATA_DIR isolation
    with monkeypatch.context() as m:
        m.setattr(pipeline, "fingerprint", lambda *a, **k: pytest.fail("fingerprint computed before readiness"))
        with pytest.raises(AppError) as e:
            pipeline.train_and_publish(force=True)
    assert e.value.code == "SOURCE_NOT_READY" and "field mapping saved" in e.value.detail
    # 3: production ON without a validation for the NEW mapping -> the exact reason, not 'ready'
    ss.update("bigquery", {"production_enabled": True})
    assert _codes(flows.readiness("train"))[:1] == ["BQ_VALIDATION_REQUIRED"]
    assert "full-period validation" in flows.readiness("d1")["reasons"][0]["detail"]
    ss.update("bigquery", {"production_enabled": False})
    # the supported recovery: activation refused until the full-period validation of the new mapping passes
    r = client.post("/api/bigquery/activate")
    assert r.status_code == 409 and r.json()["code"] == "SOURCE_NOT_READY"
    assert connector.validate_source()["passed"]
    r = client.post("/api/bigquery/activate")
    assert r.status_code == 200 and r.json()["requirements"]["validation"] is True
    assert ss.get("bigquery").production_enabled is True
    assert flows.source_blockers() == [] and flows.readiness("d1")["ready"]


def test_a_mapping_save_with_production_off_reports_no_switch_off(client):
    _bq_ready_production()
    ss.update("bigquery", {"production_enabled": False}, note="production mode disabled")
    out = _save_mapping_like_on_17_10(client)
    assert out["production_switched_off"] is False
    # the change that SWITCHED it off is named (the oldest 'off' entry after the last 'on'), not the later mapping save
    detail = flows.readiness("d1")["reasons"][0]["detail"]
    assert "switched off by: production mode disabled" in detail and "field mapping saved" not in detail


# ------------------------------------------------------------------ 4: unit_price that does not fit the schema
def test_unit_price_mapping_errors_name_the_field_and_the_column(client):
    _bq_ready_production()
    before = ss.get("bigquery").model_dump()
    r = client.post("/api/bigquery/mapping", json={"field_mapping": _mapping_with({"column": "sale_prise", "usage": "REQUIRED"})})
    assert r.status_code == 422 and r.json()["code"] == "BQ_MAPPING_INVALID"
    assert '"field": "unit_price"' in r.json()["detail"] and "COLUMN_NOT_FOUND" in r.json()["detail"]
    assert "sale_prise" in r.json()["detail"]
    r = client.post("/api/bigquery/mapping", json={"field_mapping": _mapping_with({"column": None, "usage": "REQUIRED"})})
    assert r.status_code == 422 and "REQUIRED_NOT_MAPPED" in r.json()["detail"] and "unit_price" in r.json()["detail"]
    r = client.post("/api/bigquery/mapping", json={"field_mapping": _mapping_with({"column": "sku_code", "usage": "REQUIRED"})})
    assert r.status_code == 422 and "TYPE_INCOMPATIBLE" in r.json()["detail"]                  # a STRING is no price
    assert ss.get("bigquery").model_dump() == before                         # nothing saved, production untouched
    # REQUIRED means 'must be mapped'; a row without a price is never excluded from the demand
    assert "unit_price" not in connector._REASON and "price" not in connector._REASON.lower()


# ------------------------------------------------------------------ 10: turning production off never falls back to DEMO
def test_deactivate_keeps_the_active_source_and_the_reason_is_explicit(client):
    _bq_ready_production()
    r = client.post("/api/bigquery/deactivate")
    assert r.status_code == 200 and r.json()["active_source"] == "BIGQUERY"
    assert ss.get("general").active_source == "BIGQUERY" and ss.get("bigquery").production_enabled is False
    why = flows.readiness("train")["reasons"][0]
    assert why["code"] == "SOURCE_NOT_READY" and "production mode disabled" in why["detail"]


# ------------------------------------------------------------------ Jobs page: effective state, not the switch alone
def test_scheduler_status_gives_the_effective_state_of_each_flow(client):
    _bq_ready_production()
    ss.update("schedule", {"train_enabled": True, "d1_enabled": False})
    _save_mapping_like_on_17_10(client)
    st = client.get("/api/scheduler/status").json()
    t = st["flow_states"]["train"]
    assert t["enabled"] is True and t["state"] != "ON" and not t["readiness"]["ready"]
    assert _codes(t["readiness"])[0] == "SOURCE_NOT_READY"
    assert st["flow_states"]["d1"]["state"] == "OFF"
    # with a running scheduler that loaded the switch, the state is ON_NOT_READY (never 'On - loaded')
    v = flows.flow_view("train", sched_view={"running": True, "loaded": {"flows": {"train": True}}})
    assert v["state"] == "ON_NOT_READY"
    ss.update("bigquery", {"production_enabled": True})
    connector.validate_source()
    ss.update("schedule", {"d1_enabled": True})
    v = flows.flow_view("train", sched_view={"running": True, "loaded": {"flows": {"train": True}}})
    assert v["state"] == "ON" and v["readiness"]["ready"]
