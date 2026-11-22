"""1.4.15 lot 6: presets behind the UI gates and the spike-lines estimate (api/ops_tools_routes.py).

Integration with fakes: TestClient on the isolated temporary database (conftest); the flow readiness / switch
(jobs/flows) and spike_lines.run are replaced by fakes where the test needs them. No BigQuery, no real data.
Covers: list; preview writes nothing; typed text; expected hash; busy; a flow not ready refuses before any write; apply
(settings history, PRESET_APPLIED + SETTINGS_ADVANCED_APPLIED, flows switched after the commit); idempotence (NO_CHANGE);
undo through the existing Advanced settings Undo; spike estimate = dry run only, initial needs reflag, bad date.
"""
import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from app import db, timeutil
from app import settings_service as ss
from app.api import ops_tools_routes as ot
from app.jobs import flows
from app.messages import CATALOG
from app.timeutil import VN_TZ

TODAY = "2026-11-22"
CONFIRM = f"AP-DUNG-PRESET-LGBM-CHOT-{TODAY}"
PURCHASE = f"DOI-CAI-DAT-ANH-HUONG-MUA-HANG-{TODAY}"
REASON = "chu du an duyet ap dung preset"


@pytest.fixture(autouse=True)
def _frozen_day():
    timeutil.set_now_override(lambda: datetime(2026, 11, 22, 15, 0, tzinfo=VN_TZ))
    yield


@pytest.fixture(autouse=True)
def _direct_strategy():
    """The preset sets horizon weights, valid only with forecast_strategy DIRECT (HORIZON_WEIGHT_DIRECT_ONLY): as in
    test_v131_api, the installation the preset is for runs DIRECT; with RECURSIVE the preset is refused (PRESET_INVALID)."""
    ss.update("model", {"forecast_strategy": "DIRECT"}, note="tests: preset needs DIRECT")


@pytest.fixture
def ready(client, monkeypatch):
    """Every flow ready; switching a flow ON stores its flag (as flows.update_flow would) and is recorded."""
    calls = []
    monkeypatch.setattr(flows, "readiness", lambda f, conn=None: {"ready": True, "reasons": []})

    def update(f, body):
        calls.append((f, body))
        ss.update("schedule", {flows.FLOWS[f]["flag"]: True}, note="test: flow on")
        return {"flow": f, "enabled": True}
    monkeypatch.setattr(flows, "update_flow", update)
    return calls


def _count(sql, p=()) -> int:
    with db.read() as c:
        return c.execute(sql, p).fetchone()[0]


def _snapshot() -> dict:
    return {"hist": _count("SELECT COUNT(*) FROM settings_history"), "audit": _count("SELECT COUNT(*) FROM audit_log"),
            "model": ss.get("model").model_dump(), "daily": ss.get("daily_forecast").model_dump(),
            "schedule": ss.get("schedule").model_dump()}


def _preview(client):
    r = client.post("/api/presets/lgbm-chot/preview")
    assert r.status_code == 200, r.json()
    return r.json()


def _apply(client, pv, **kw):
    body = {"expected_hash": pv["expected_hash"], "confirm_text": CONFIRM, "confirm_purchase": PURCHASE, "reason": REASON}
    body.update(kw)
    return client.post("/api/presets/lgbm-chot/apply", json=body)


def _code(r):
    return r.json()["code"]


# ------------------------------------------------------------------ presets
def test_the_presets_are_listed_with_their_description(client):
    p = client.get("/api/presets").json()["presets"]
    assert [x["name"] for x in p] == ["lgbm-chot"] and p[0]["confirm_text"] == CONFIRM
    assert "log_retention_days" not in p[0]["sections"]["daily_forecast"]
    assert [d["code"] for d in p[0]["description"]] == list(ot.PRESET_DESCRIPTIONS["lgbm-chot"])
    r = client.post("/api/presets/nope/preview")
    assert r.status_code == 404 and _code(r) == "PRESET_UNKNOWN"


def test_the_preview_lists_every_change_and_writes_nothing(ready, client):
    before = _snapshot()
    pv = _preview(client)
    keys = {(x["section"], x["key"]): x for x in pv["changes"]}
    assert keys[("model", "feature_sku_code")]["to"] is False and keys[("daily_forecast", "enabled")]["to"] is True
    assert all(x["undoable"] for x in pv["changes"])                       # rounding 0.2 is already the stored value
    assert {x["flow"] for x in pv["flows"]} == {"refresh", "report"} and pv["ready"] is True
    assert "flow refresh" in pv["not_undoable"] and len(pv["expected_hash"]) == 64
    assert pv["needs_purchase_confirm"] is True and "daily_forecast.enabled" in pv["purchase_keys"]
    assert pv["confirm_purchase"] == PURCHASE and pv["undo_warning"]["code"] == "PRESET_UNDO_SETTINGS_ONLY"
    assert _snapshot() == before and ready == []


def test_wrong_text_short_reason_or_a_changed_value_saves_nothing(ready, client):
    pv = _preview(client)
    before = _snapshot()
    for kw in ({"confirm_text": "AP-DUNG-PRESET-LGBM-CHOT-2026-11-21"}, {"confirm_text": None}, {"reason": "ngan"}):
        r = _apply(client, pv, **kw)
        assert r.status_code == 409 and _code(r) == "PRESET_CONFIRM_REQUIRED", kw
    assert _snapshot() == before
    ss.update("model", {"horizon_weight_short": 2.0, "horizon_weight_cutoff": 5}, note="test: changed elsewhere")
    r = _apply(client, pv)
    assert r.status_code == 409 and _code(r) == "SETTINGS_CHANGED_ELSEWHERE"
    assert ss.get("daily_forecast").enabled is False and ready == []


def test_a_busy_job_refuses_the_apply(ready, client):
    pv = _preview(client)
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) VALUES "
                  "('J-1', 'D0_SYNC', 'k1', 'MANUAL', 'RUNNING', '2026-11-22T07:30:00+00:00')")
    before = _snapshot()
    r = _apply(client, pv)
    assert r.status_code == 409 and _code(r) == "PRESET_BUSY" and _snapshot() == before and ready == []


def test_a_flow_not_ready_refuses_before_any_write(client, monkeypatch):
    monkeypatch.setattr(flows, "readiness", lambda f, conn=None: {"ready": False, "reasons": [
        {"code": "DATA_NOT_UP_TO_DATE", "detail": "x"}, {"code": "DAILY_FORECAST_DISABLED", "detail": "y"}]})
    pv = _preview(client)
    assert pv["ready"] is False and pv["flows"][0]["reasons"] == [{"code": "DATA_NOT_UP_TO_DATE", "detail": "x"}]
    before = _snapshot()
    r = _apply(client, pv)
    assert r.status_code == 409 and _code(r) == "PRESET_FLOW_NOT_READY" and _snapshot() == before


def test_apply_saves_audits_switches_flows_and_the_advanced_undo_puts_the_keys_back(ready, client):
    model_before = ss.get("model").model_dump()
    pv = _preview(client)
    r = _apply(client, pv)
    assert r.status_code == 200, r.json()
    j = r.json()
    assert ss.get("model").feature_sku_code is False and ss.get("daily_forecast").enabled is True
    assert [f for f, _b in ready] == ["refresh", "report"] and all(x["to"] for x in j["flows"])
    assert j["partial"] is False and j["flow_errors"] == [] and j["undo_warning"]["code"] == "PRESET_UNDO_SETTINGS_ONLY"
    assert _count("SELECT COUNT(*) FROM audit_log WHERE action='PRESET_FLOWS_RESULT'") == 1
    assert _count("SELECT COUNT(*) FROM audit_log WHERE action='PRESET_APPLIED'") == 1
    with db.read() as c:
        adv = json.loads(c.execute("SELECT details_json FROM audit_log WHERE id=?", (j["undo_audit_id"],)).fetchone()[0])
        notes = [x[0] for x in c.execute("SELECT note FROM settings_history WHERE section IN ('model', 'daily_forecast') "
                                         "ORDER BY id DESC LIMIT 2")]
    assert adv["source"] == "preset lgbm-chot" and {x["key"] for x in adv["changes"]} >= {"feature_sku_code", "enabled"}
    assert all(REASON in n and "PRESET lgbm-chot" in n for n in notes)
    r = _apply(client, _preview(client))                                    # idempotent
    assert r.status_code == 400 and _code(r) == "NO_CHANGE"
    texts = client.get("/api/settings-advanced").json()["confirm_texts"]
    u = client.post("/api/settings-advanced/undo", json={"audit_id": j["undo_audit_id"], "confirm_text": texts["PURCHASE"],
                                                         "reason": REASON, "acknowledged": True})
    assert u.status_code == 200, u.json()
    assert ss.get("model").model_dump() == model_before and ss.get("daily_forecast").enabled is False


# ------------------------------------------------------------------ spike lines: estimate only
def test_the_spike_estimate_is_a_dry_run_only(client, monkeypatch):
    from app import spike_lines
    calls = []

    def fake(d=None, initial=False, dry_run=False, reflag=False):
        calls.append({"d": str(d), "initial": initial, "dry_run": dry_run, "reflag": reflag})
        return {"status": "DRY_RUN", "estimated_bytes": 123, "cap_bytes": 1000, "read_start": "2026-10-23"}
    monkeypatch.setattr(spike_lines, "run", fake)
    r = client.post("/api/spike-lines/estimate", json={"date": "2026-11-21"})
    assert r.status_code == 200 and r.json()["estimated_bytes"] == 123 and r.json()["rows_estimated"] is None
    assert calls == [{"d": "2026-11-21", "initial": False, "dry_run": True, "reflag": False}]
    assert r.json()["description"][0]["code"] == "SPIKE_ESTIMATE_ONLY"
    assert client.post("/api/spike-lines/estimate", json={}).json()["estimated_bytes"] == 123   # today
    assert calls[-1]["d"] == TODAY
    r = client.post("/api/spike-lines/estimate", json={"date": "21/11/2026"})
    assert r.status_code == 422 and _code(r) == "SPIKE_ESTIMATE_INVALID_DATE"


def test_an_initial_estimate_on_a_flagged_scope_needs_reflag(client, monkeypatch):
    from app import spike_lines
    monkeypatch.setattr(spike_lines, "_scope_key", lambda: "BIGQUERY:p.d.t")
    monkeypatch.setattr(ot, "_has_flags", lambda sk: True)
    monkeypatch.setattr(spike_lines, "run", lambda d=None, initial=False, dry_run=False, reflag=False:
                        {"status": "DRY_RUN", "estimated_bytes": 5, "initial": initial, "reflag": reflag})
    r = client.post("/api/spike-lines/estimate", json={"initial": True})
    assert r.status_code == 409 and _code(r) == "SPIKE_LINES_REFLAG_REQUIRED"
    r = client.post("/api/spike-lines/estimate", json={"initial": True, "reflag": True})
    assert r.status_code == 200 and r.json()["reflag"] is True


def test_every_code_of_the_module_is_in_the_catalogue():
    s = Path(ot.__file__).read_text(encoding="utf-8")
    codes = set(re.findall(r'AppError\(\s*"([A-Z_]+)"', s)) | set(ot.SPIKE_DESCRIPTION) \
        | {c for v in ot.PRESET_DESCRIPTIONS.values() for c in v}
    assert {"PRESET_CONFIRM_REQUIRED", "PRESET_LGBM_CHOT_DESC"} <= codes
    assert not sorted(c for c in codes if c not in CATALOG)


# ------------------------------------------------------------------ REV-B: purchase text, readiness under the lock, flow errors
def test_a_purchase_key_needs_the_purchase_text_too(ready, client):
    pv = _preview(client)
    before = _snapshot()
    for v in (None, "DOI-CAI-DAT-ANH-HUONG-MUA-HANG-2026-11-21"):
        r = _apply(client, pv, confirm_purchase=v)
        assert r.status_code == 409 and _code(r) == "PRESET_PURCHASE_CONFIRM_REQUIRED"
        assert "model.feature_sku_code" in r.json()["params"]["purchase_keys"]
    assert _snapshot() == before and ready == []


def test_a_flow_that_stops_being_ready_before_the_write_refuses(client, monkeypatch):
    calls = []

    def readiness(f, conn=None):
        calls.append(f)
        ok = len(calls) <= 4                    # preview (2 flows) + the check before the transaction (2): ready
        return {"ready": ok, "reasons": [] if ok else [{"code": "DATA_NOT_UP_TO_DATE", "detail": "x"}]}
    monkeypatch.setattr(flows, "readiness", readiness)
    pv = _preview(client)
    before = _snapshot()
    r = _apply(client, pv)
    assert r.status_code == 409 and _code(r) == "PRESET_FLOW_NOT_READY" and _snapshot() == before


def test_a_flow_switch_error_after_the_commit_is_reported_not_a_500(client, monkeypatch):
    monkeypatch.setattr(flows, "readiness", lambda f, conn=None: {"ready": True, "reasons": []})

    def boom(f, body):
        raise RuntimeError("scheduler file locked")
    monkeypatch.setattr(flows, "update_flow", boom)
    r = _apply(client, _preview(client))
    assert r.status_code == 200, r.json()
    j = r.json()
    assert j["partial"] is True and {e["flow"] for e in j["flow_errors"]} == {"refresh", "report"}
    assert {e["code"] for e in j["flow_errors"]} == {"PRESET_FLOW_SWITCH_FAILED"} and j["warnings"] == ["PRESET_FLOWS_NOT_ALL_ON"]
    assert ss.get("daily_forecast").enabled is True                      # the settings stay committed
    with db.read() as c:
        a = json.loads(c.execute("SELECT details_json FROM audit_log WHERE action='PRESET_FLOWS_RESULT'").fetchone()[0])
    assert len(a["errors"]) == 2 and all(x["to"] is False for x in a["flows"])


# ------------------------------------------------------------------ DREV: operations locks and schedule times
def test_a_preset_is_refused_near_a_schedule_time_or_with_an_operations_lock(ready, client, monkeypatch, tmp_path):
    for k in ("DF_OPS_LOCK", "DF_HEAVY_LOCK", "DF_RUN_DIR"):
        monkeypatch.delenv(k, raising=False)
    pv = _preview(client)
    assert pv["ops_lock_checked"] is False and pv["schedule_times"] == []
    ss.update("schedule", {"report_time": "16:00"}, note="test: in 60 minutes")
    pv2 = _preview(client)
    assert pv2["schedule_times"] == [{"setting": "schedule.report_time", "time": "16:00"}]
    before = _snapshot()
    r = _apply(client, pv2)
    assert r.status_code == 409 and _code(r) == "PRESET_BUSY" and "schedule.report_time 16:00" in r.json()["detail"]
    ss.update("schedule", {"report_time": "09:30"}, note="test: back")
    monkeypatch.setenv("DF_OPS_LOCK", str(tmp_path / "OPS_LOCK"))
    (tmp_path / "OPS_LOCK").write_text("{}")
    pv3 = _preview(client)
    assert pv3["ops_lock_checked"] is True and pv3["ops_locks"][0]["env"] == "DF_OPS_LOCK"
    r = _apply(client, pv3)
    assert r.status_code == 409 and _code(r) == "OPERATIONS_LOCK_HELD" and ready == []
    assert ss.get("daily_forecast").enabled is False


def test_with_the_recursive_strategy_the_preset_is_refused_as_invalid(ready, client):
    ss.update("model", {"forecast_strategy": "RECURSIVE"}, note="test")
    r = client.post("/api/presets/lgbm-chot/preview")
    assert r.status_code == 422 and _code(r) == "PRESET_INVALID" and "HORIZON_WEIGHT_DIRECT_ONLY" in r.json()["detail"]
