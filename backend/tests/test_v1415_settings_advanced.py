"""1.4.15 (lot 2): settings registry + /api/settings-advanced + the registry guard of the generic editor.

Integration with fakes (TestClient on the isolated temporary database, no real data, no network).
Covers: every field of every section is classified exactly once; GET / preview / apply / undo (risk levels, typed texts
of the Vietnam day, reason, acknowledged, expected value, busy gate incl. stale jobs, READONLY / OWN_PATH / unknown,
only_increase, max 10 keys, whole-section validation, audit from -> to); PUT /api/settings/{section} refuses a changed
registry key and its reset keeps every registry key; error texts in both languages.
"""
import json
from datetime import datetime

import pytest

from app import db
from app import settings_registry as reg
from app import settings_service as ss
from app import timeutil
from app.messages import CATALOG
from app.timeutil import VN_TZ

TODAY = "2026-11-22"
HIGH = f"DOI-CAI-DAT-AN-{TODAY}"
PURCHASE = f"DOI-CAI-DAT-ANH-HUONG-MUA-HANG-{TODAY}"
REASON = "chu du an duyet doi cai dat"
OLD = "2026-11-21T20:00:00+00:00"       # 9 h before now
RECENT = "2026-11-22T03:00:00+00:00"    # 2 h before now
NEW_CODES = ("SETTINGS_FIELD_GUARDED", "SETTINGS_ADVANCED_BUSY", "SETTINGS_ADVANCED_UNKNOWN_KEY",
             "SETTINGS_ADVANCED_NOT_EDITABLE", "SETTINGS_ADVANCED_KEY_COUNT", "SETTINGS_ADVANCED_DUPLICATE_KEY",
             "SETTINGS_ADVANCED_INVALID_VALUE", "SETTINGS_ADVANCED_EXPECTED_REQUIRED",
             "SETTINGS_ADVANCED_CONFIRM_REQUIRED", "RETENTION_DECREASE_NOT_ALLOWED", "SETTINGS_PATH_INVALID",
             "SETTINGS_ADVANCED_AUDIT_NOT_FOUND", "SETTINGS_ADVANCED_ALREADY_UNDONE", "PURCHASE_NUMBERS_CHANGE",
             "SPIKE_OWNER_DECISION", "APPLIES_FROM_NEXT_RUN", "RETENTION_DATA_NOT_RESTORED")


@pytest.fixture(autouse=True)
def _frozen_day():
    timeutil.set_now_override(lambda: datetime(2026, 11, 22, 12, 0, tzinfo=VN_TZ))
    yield


# ------------------------------------------------------------------ helpers
def _at(h, m, day=22):
    timeutil.set_now_override(lambda: datetime(2026, 11, day, h, m, tzinfo=VN_TZ))


def _hist(section) -> int:
    with db.read() as c:
        return c.execute("SELECT COUNT(*) FROM settings_history WHERE section=?", (section,)).fetchone()[0]


def _audits(action) -> list[dict]:
    with db.read() as c:
        return [json.loads(r[0]) for r in c.execute("SELECT details_json FROM audit_log WHERE action=? ORDER BY id",
                                                    (action,))]


def _val(section, key):
    return ss.get(section).model_dump()[key]


def _changes(*items):
    return [{"section": s, "key": k, "value": v} for s, k, v in items]


def _apply(client, *items, expected=None, **kw):
    if expected is None:
        expected = {}
        for s, k, _ in items:
            expected.setdefault(s, {})[k] = _val(s, k)
    return client.post("/api/settings-advanced/apply", json={"changes": _changes(*items), "expected": expected, **kw})


def _code(r):
    return r.json()["code"]


def _job(jid, job_type, status, created_at=RECENT, started_at=None, stage_updated_at=None):
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at, started_at, "
                  "stage_updated_at) VALUES (?,?,?,?,?,?,?,?)",
                  (jid, job_type, f"idem-{jid}", "SCHEDULE", status, created_at, started_at, stage_updated_at))


# ------------------------------------------------------------------ registry completeness
def test_every_field_of_every_section_is_classified_exactly_once():
    assert set(reg.SECTIONS_CHECKED) == {"horizons", "quality", "model", "import", "data_policy", "schedule",
                                         "bigquery", "daily_forecast", "sel2_pipeline", "general"}
    cl = reg.classification()
    for s in reg.SECTIONS_CHECKED:
        fields = set(ss.SECTIONS[s].model_fields)
        got = cl.get(s, {})
        assert fields - set(got) == set(), f"{s}: not classified"
        assert set(got) - fields == set(), f"{s}: classified key not in the model"
        assert [k for k, v in got.items() if v == "DUPLICATE"] == [], s
    assert set(cl) <= set(reg.SECTIONS_CHECKED)
    assert set(reg.DATA_POLICY) == set(ss.DataPolicySettings.model_fields) and len(reg.DATA_POLICY) == 10


def test_registry_entries_are_well_formed():
    for e in reg.ENTRIES:
        assert e.risk in reg.RISKS, e
        assert e.label_vi and e.label_en and e.desc_vi and e.desc_en, e
        if e.risk in ("READONLY", "OWN_PATH"):
            assert e.reason_code in CATALOG, e
        assert e.only_increase is False or e.key in ("retention_days", "log_retention_days"), e
        reg.constraints(e.section, e.key)


def test_fixed_rules_and_own_paths_are_not_editable():
    for s, k in (("daily_forecast", "rounding_threshold"), ("sel2_pipeline", "p_threshold"), ("model", "feature_table"),
                 ("daily_forecast", "trial_mode"), ("schedule", "d0_paused_until"), ("bigquery", "production_enabled"),
                 ("bigquery", "oauth_client_id"), ("general", "active_import_batch_id"), ("schedule", "refresh_enabled")):
        assert not reg.editable(reg.entry(s, k)), (s, k)
    assert reg.entry("daily_forecast", "log_retention_days").only_increase
    assert reg.entry("sel2_pipeline", "retention_days").only_increase
    assert reg.risk(reg.entry("sel2_pipeline", "enabled")) == "PURCHASE"
    assert reg.risk(reg.entry("daily_forecast", "enabled")) == "PURCHASE"      # orchestrator decision 23/11 (#9)


def test_daily_forecast_enabled_needs_purchase_text(client):
    r = _apply(client, ("daily_forecast", "enabled", True), confirm_text=HIGH, reason=REASON)
    assert r.status_code == 409 and r.json()["params"]["confirm_text"] == PURCHASE
    r = _apply(client, ("daily_forecast", "enabled", True), confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 200, r.text
    assert ss.get("daily_forecast").enabled is True and ss.get("daily_forecast").trial_mode is True
    for k in ("project_id", "dataset_id", "location", "source_table", "service_account_file", "auth_method", "field_mapping"):
        assert ("bigquery", k) in reg.EXCLUDED


def test_spike_keys_are_purchase_and_describe_the_training_impact():
    assert not hasattr(reg, "SPIKE_OWNER_EDIT")         # owner decision 23/11/2026: no lock flag
    for k in reg.SPIKE_KEYS:
        e = reg.entry("sel2_pipeline", k)
        assert reg.risk(e) == "PURCHASE" and reg.editable(e) and reg.exportable(e) and reg.reason_code(e) is None
        assert "dữ liệu học" in e.desc_vi and "lượt học kế tiếp" in e.desc_vi and "không trả lại" in e.desc_vi
        assert "training data" in e.desc_en and "next training" in e.desc_en and "setting only" in e.desc_en


@pytest.mark.parametrize("rule,value,ok", [("NAME", "theo-doi", True), ("NAME", "a\\b", False), ("NAME", "..", False),
                                           ("NAME", "C:\\x", False), ("NAME", "\\x", False), ("NAME", "", False),
                                           ("SUBDIR", "exports\\du_bao", True), ("SUBDIR", "a/../..", False),
                                           ("SUBDIR", "D:x", False), ("SUBDIR", "/abs", False)])
def test_path_rule(rule, value, ok):
    e = reg.Entry("x", "y", "LOW", "a", "a", "a", "a", path_rule=rule)
    assert reg.path_ok(e, value) is ok


def test_messages_have_both_languages():
    for code in NEW_CODES + tuple({e.reason_code for e in reg.ENTRIES if e.reason_code}) :
        vi, en = CATALOG[code]
        assert vi and en and vi != en, code


# ------------------------------------------------------------------ GET / preview
def test_get_contract(client):
    j = client.get("/api/settings-advanced").json()
    assert len(j["entries"]) == len(reg.ENTRIES)
    e = next(x for x in j["entries"] if (x["section"], x["key"]) == ("sel2_pipeline", "retention_days"))
    assert e["risk"] == "HIGH" and e["only_increase"] is True and e["value"] == 120 and e["default"] == 120
    assert e["constraints"]["ge"] == 35 and e["editable"] is True
    assert j["confirm_texts"] == {"HIGH": HIGH, "PURCHASE": PURCHASE}
    assert j["max_keys"] == 10 and j["reason_min_length"] == 10 and j["history"] == []
    assert set(j["versions"]) >= {"model", "sel2_pipeline", "bigquery"}


def test_preview_writes_nothing_and_reports_highest_risk(client):
    n = (_hist("model"), _hist("bigquery"))
    r = client.post("/api/settings-advanced/preview", json={"changes": _changes(
        ("model", "num_threads", 4), ("bigquery", "max_retries", 3))})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["max_risk"] == "PURCHASE" and j["confirm_text"] == PURCHASE and j["needs_acknowledged"] is True
    assert set(j["changed"]) == {"model.num_threads", "bigquery.max_retries"}
    assert "PURCHASE_NUMBERS_CHANGE" in j["warnings"] and "APPLIES_FROM_NEXT_RUN" in j["notes"]
    assert j["busy"]["busy"] is False
    assert (_hist("model"), _hist("bigquery")) == n and _val("model", "num_threads") == 0


def test_preview_no_change_and_retention_note(client):
    j = client.post("/api/settings-advanced/preview", json={"changes": _changes(("bigquery", "max_retries", 2))}).json()
    assert j["changed"] == [] and "NO_CHANGE" in j["warnings"]
    j = client.post("/api/settings-advanced/preview",
                    json={"changes": _changes(("sel2_pipeline", "retention_days", 150))}).json()
    assert "RETENTION_DATA_NOT_RESTORED" in j["notes"] and j["max_risk"] == "HIGH"


# ------------------------------------------------------------------ apply: risk levels
def test_low_needs_acknowledged(client):
    r = _apply(client, ("bigquery", "max_retries", 3))
    assert r.status_code == 409 and _code(r) == "SETTINGS_ADVANCED_CONFIRM_REQUIRED"
    assert _val("bigquery", "max_retries") == 2
    n = _hist("bigquery")
    r = _apply(client, ("bigquery", "max_retries", 3), acknowledged=True)
    assert r.status_code == 200, r.text
    assert _val("bigquery", "max_retries") == 3 and _hist("bigquery") == n + 1
    a = _audits("SETTINGS_ADVANCED_APPLIED")[-1]
    assert a["changes"] == [{"section": "bigquery", "key": "max_retries", "risk": "LOW", "from": 2, "to": 3}]
    assert a["risk"] == "LOW" and a["versions"]["bigquery"] > a["versions_before"]["bigquery"]


def test_high_needs_text_and_reason(client):
    item = ("schedule", "max_catchup_jobs_per_tick", 2)
    assert _code(_apply(client, item)) == "SETTINGS_ADVANCED_CONFIRM_REQUIRED"
    assert _code(_apply(client, item, confirm_text=HIGH, reason="short")) == "SETTINGS_ADVANCED_CONFIRM_REQUIRED"
    assert _code(_apply(client, item, confirm_text=PURCHASE, reason=REASON)) == "SETTINGS_ADVANCED_CONFIRM_REQUIRED"
    assert _val("schedule", "max_catchup_jobs_per_tick") == 1
    r = _apply(client, item, confirm_text=f"  {HIGH} ", reason=REASON)
    assert r.status_code == 200, r.text
    assert _val("schedule", "max_catchup_jobs_per_tick") == 2


def test_purchase_needs_purchase_text(client):
    item = ("model", "num_threads", 4)
    r = _apply(client, item, confirm_text=HIGH, reason=REASON)
    assert r.status_code == 409 and r.json()["params"]["confirm_text"] == PURCHASE
    r = _apply(client, item, confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 200, r.text
    assert _val("model", "num_threads") == 4
    with db.read() as c:
        note = c.execute("SELECT note FROM settings_history WHERE section='model' ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert "num_threads 0 -> 4" in note and REASON in note


def test_confirm_text_follows_vietnam_day(client):
    _at(5, 0, 23)        # 23/11 05:00 Vietnam = 22/11 22:00 UTC
    r = _apply(client, ("model", "num_threads", 4), confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 409 and r.json()["params"]["confirm_text"].endswith("2026-11-23")


def test_mixed_purchase_and_low_need_both(client):
    items = (("model", "num_threads", 4), ("bigquery", "max_retries", 3))
    assert _code(_apply(client, *items, confirm_text=PURCHASE, reason=REASON)) == "SETTINGS_ADVANCED_CONFIRM_REQUIRED"
    n = (_hist("model"), _hist("bigquery"))
    r = _apply(client, *items, confirm_text=PURCHASE, reason=REASON, acknowledged=True)
    assert r.status_code == 200, r.text
    assert (_hist("model"), _hist("bigquery")) == (n[0] + 1, n[1] + 1)


def test_no_change_400(client):
    r = _apply(client, ("bigquery", "max_retries", 2), acknowledged=True)
    assert r.status_code == 400 and _code(r) == "NO_CHANGE"


# ------------------------------------------------------------------ apply: refusals
def test_expected_missing_422_and_mismatch_409(client):
    r = client.post("/api/settings-advanced/apply", json={"changes": _changes(("bigquery", "max_retries", 3)),
                                                          "acknowledged": True})
    assert r.status_code == 422 and _code(r) == "SETTINGS_ADVANCED_EXPECTED_REQUIRED"
    ss.update("bigquery", {"max_retries": 4}, note="elsewhere")
    n = _hist("bigquery")
    r = _apply(client, ("bigquery", "max_retries", 3), expected={"bigquery": {"max_retries": 2}}, acknowledged=True)
    assert r.status_code == 409 and _code(r) == "SETTINGS_CHANGED_ELSEWHERE"
    assert r.json()["params"]["current"] == {"bigquery": {"max_retries": 4}}
    assert _hist("bigquery") == n and _val("bigquery", "max_retries") == 4


def test_expected_bool_is_not_a_number(client):
    r = _apply(client, ("model", "fallback_enabled", False), expected={"model": {"fallback_enabled": 1}},
               confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 409 and _code(r) == "SETTINGS_CHANGED_ELSEWHERE"


@pytest.mark.parametrize("section,key,value,code", [
    ("daily_forecast", "rounding_threshold", 0.3, "SETTINGS_ADVANCED_NOT_EDITABLE"),
    ("sel2_pipeline", "p_threshold", 0.6, "SETTINGS_ADVANCED_NOT_EDITABLE"),
    ("daily_forecast", "trial_mode", False, "SETTINGS_ADVANCED_NOT_EDITABLE"),
    ("schedule", "d1_enabled", True, "SETTINGS_ADVANCED_NOT_EDITABLE"),
    ("bigquery", "production_enabled", True, "SETTINGS_ADVANCED_NOT_EDITABLE"),
    ("bigquery", "project_id", "other-project-1", "SETTINGS_ADVANCED_UNKNOWN_KEY"),
    ("quality", "wape_max", 0.5, "SETTINGS_ADVANCED_UNKNOWN_KEY"),
    ("data_policy", "window_start_date", "2025-01-01", "SETTINGS_ADVANCED_UNKNOWN_KEY"),
    ("nope", "x", 1, "SETTINGS_ADVANCED_UNKNOWN_KEY")])
def test_readonly_own_path_unknown_422(client, section, key, value, code):
    for url in ("/api/settings-advanced/preview", "/api/settings-advanced/apply"):
        r = client.post(url, json={"changes": _changes((section, key, value)), "expected": {section: {key: value}},
                                   "confirm_text": PURCHASE, "reason": REASON, "acknowledged": True})
        assert r.status_code == 422 and _code(r) == code, (url, r.text)
        assert r.json()["vi"] != r.json()["en"]


def test_spike_preview_needs_purchase_and_warns(client):
    n = _hist("sel2_pipeline")
    j = client.post("/api/settings-advanced/preview", json={"changes": _changes(("sel2_pipeline", "spike_e4_n", 6))}).json()
    assert j["max_risk"] == "PURCHASE" and j["confirm_text"] == PURCHASE and "SPIKE_OWNER_DECISION" in j["warnings"]
    assert _hist("sel2_pipeline") == n


def test_spike_apply_and_undo_at_purchase_level(client):
    items = (("sel2_pipeline", "spike_cleaning", True), ("sel2_pipeline", "spike_e4_n", 5))
    assert _code(_apply(client, *items, confirm_text=HIGH, reason=REASON)) == "SETTINGS_ADVANCED_CONFIRM_REQUIRED"
    assert _code(_apply(client, *items, confirm_text=PURCHASE, reason="short")) == "SETTINGS_ADVANCED_CONFIRM_REQUIRED"
    r = _apply(client, *items, expected={"sel2_pipeline": {"spike_cleaning": True, "spike_e4_n": 4}},
               confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 409 and _code(r) == "SETTINGS_CHANGED_ELSEWHERE"
    r = _apply(client, *items, confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 200, r.text
    s = ss.get("sel2_pipeline")
    assert s.spike_cleaning is True and s.spike_e4_n == 5
    u = client.post("/api/settings-advanced/undo", json={"audit_id": r.json()["audit_id"], "confirm_text": PURCHASE,
                                                         "reason": REASON})
    assert u.status_code == 200, u.text
    s = ss.get("sel2_pipeline")
    assert s.spike_cleaning is False and s.spike_e4_n == 4


def test_spike_apply_busy(client):
    _job("JB-9", "CANDIDATE_TRAIN", "RUNNING", started_at=RECENT)
    r = _apply(client, ("sel2_pipeline", "spike_cleaning", True), confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 409 and _code(r) == "SETTINGS_ADVANCED_BUSY"
    assert ss.get("sel2_pipeline").spike_cleaning is False


@pytest.mark.parametrize("section,key", [("sel2_pipeline", "retention_days"), ("daily_forecast", "log_retention_days")])
def test_retention_decrease_422_increase_ok(client, section, key):
    cur = _val(section, key)
    n = _hist(section)
    r = _apply(client, (section, key, cur - 1), confirm_text=HIGH, reason=REASON)
    assert r.status_code == 422 and _code(r) == "RETENTION_DECREASE_NOT_ALLOWED"
    assert _hist(section) == n and _val(section, key) == cur
    r = _apply(client, (section, key, cur + 30), confirm_text=HIGH, reason=REASON)
    assert r.status_code == 200, r.text
    assert _val(section, key) == cur + 30


def test_key_count_limits(client):
    assert _code(client.post("/api/settings-advanced/preview", json={"changes": []})) == "SETTINGS_ADVANCED_KEY_COUNT"
    keys = ["window_days", "min_days", "fallback_model", "group_mode", "retention_days", "export_deadline",
            "prev_week_deadline", "retrain_weekday", "train_timeout_seconds", "tsb_alpha", "tsb_beta"]
    cur = ss.get("sel2_pipeline").model_dump()
    items = [("sel2_pipeline", k, cur[k]) for k in keys]
    r = _apply(client, *items, confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 422 and _code(r) == "SETTINGS_ADVANCED_KEY_COUNT"
    r = _apply(client, *items[:10], confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 400 and _code(r) == "NO_CHANGE"           # 10 keys accepted (all equal here)
    r = _apply(client, ("sel2_pipeline", "tsb_alpha", 0.2), ("sel2_pipeline", "tsb_alpha", 0.3),
               confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 422 and _code(r) == "SETTINGS_ADVANCED_DUPLICATE_KEY"


def test_whole_section_cross_validation_sel2(client):
    n = _hist("sel2_pipeline")
    r = _apply(client, ("sel2_pipeline", "min_days", 40), confirm_text=PURCHASE, reason=REASON)     # > window_days 28
    assert r.status_code == 422 and _code(r) == "SETTINGS_ADVANCED_INVALID_VALUE"
    r = _apply(client, ("sel2_pipeline", "window_days", 200), confirm_text=PURCHASE, reason=REASON)  # retention 120 < 207
    assert r.status_code == 422 and _code(r) == "SETTINGS_ADVANCED_INVALID_VALUE"
    r = _apply(client, ("sel2_pipeline", "prev_week_deadline", "07:00"), confirm_text=HIGH, reason=REASON)
    assert r.status_code == 422 and _code(r) == "SETTINGS_ADVANCED_INVALID_VALUE"
    assert _hist("sel2_pipeline") == n
    r = _apply(client, ("sel2_pipeline", "window_days", 200), ("sel2_pipeline", "retention_days", 210),
               confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 200, r.text
    assert _hist("sel2_pipeline") == n + 1


def test_model_horizon_weight_needs_both_and_direct(client):
    r = _apply(client, ("model", "horizon_weight_short", 3.0), confirm_text=PURCHASE, reason=REASON)
    assert r.status_code == 422 and _code(r) == "SETTINGS_ADVANCED_INVALID_VALUE"


def test_report_subdir_path_refused(client):
    r = _apply(client, ("daily_forecast", "report_subdir", "..\\x"), acknowledged=True)
    assert r.status_code == 422 and _code(r) in ("SETTINGS_ADVANCED_INVALID_VALUE", "SETTINGS_PATH_INVALID")
    assert _val("daily_forecast", "report_subdir") == "theo-doi"


# ------------------------------------------------------------------ busy
@pytest.mark.parametrize("h,m,day", [(23, 50, 22), (1, 0, 23)])
def test_busy_in_production_window(client, h, m, day):
    _at(h, m, day)
    r = _apply(client, ("bigquery", "max_retries", 3), acknowledged=True)
    assert r.status_code == 409 and _code(r) == "SETTINGS_ADVANCED_BUSY" and r.json()["params"]["window"]
    assert _val("bigquery", "max_retries") == 2


@pytest.mark.parametrize("job_type", ["D1_SYNC", "D0_SYNC", "FORECAST_EXPORT", "SPIKE_LINES", "CANDIDATE_TRAIN",
                                      "EOD_FORECAST_SNAPSHOT"])
def test_busy_with_any_active_job(client, job_type):
    _job("JB-1", job_type, "RUNNING", started_at=RECENT)
    r = _apply(client, ("bigquery", "max_retries", 3), acknowledged=True)
    assert r.status_code == 409 and _code(r) == "SETTINGS_ADVANCED_BUSY", r.text
    assert [j["id"] for j in r.json()["params"]["jobs"]] == ["JB-1"]
    pv = client.post("/api/settings-advanced/preview", json={"changes": _changes(("bigquery", "max_retries", 3))})
    assert pv.status_code == 200 and pv.json()["busy"]["busy"] is True


def test_stale_job_ignored_and_audited(client):
    _job("JB-2", "D1_SYNC", "RUNNING", created_at=OLD, started_at=OLD, stage_updated_at=OLD)
    r = _apply(client, ("bigquery", "max_retries", 3), acknowledged=True)
    assert r.status_code == 200, r.text
    a = _audits("SETTINGS_ADVANCED_APPLIED")[-1]
    assert a["stale_ignored"] == [{"id": "JB-2", "job_type": "D1_SYNC", "status": "RUNNING"}]
    assert a["stale_ignored_total"] == 1


def test_finished_job_does_not_block(client):
    _job("JB-3", "D1_SYNC", "SUCCEEDED")
    assert _apply(client, ("bigquery", "max_retries", 3), acknowledged=True).status_code == 200


# ------------------------------------------------------------------ undo
def test_undo_restores_from_and_is_audited(client):
    r = _apply(client, ("model", "num_threads", 4), ("bigquery", "max_retries", 3),
               confirm_text=PURCHASE, reason=REASON, acknowledged=True)
    aid = r.json()["audit_id"]
    assert _code(client.post("/api/settings-advanced/undo", json={"audit_id": aid})) == "SETTINGS_ADVANCED_CONFIRM_REQUIRED"
    u = client.post("/api/settings-advanced/undo", json={"audit_id": aid, "confirm_text": PURCHASE, "reason": REASON,
                                                         "acknowledged": True})
    assert u.status_code == 200, u.text
    assert _val("model", "num_threads") == 0 and _val("bigquery", "max_retries") == 2
    d = _audits("SETTINGS_ADVANCED_UNDONE")[-1]
    assert d["undo_of"] == aid and {(c["key"], c["from"], c["to"]) for c in d["changes"]} == {
        ("num_threads", 4, 0), ("max_retries", 3, 2)}
    again = client.post("/api/settings-advanced/undo", json={"audit_id": aid, "confirm_text": PURCHASE,
                                                             "reason": REASON, "acknowledged": True})
    assert again.status_code == 409 and _code(again) == "SETTINGS_ADVANCED_ALREADY_UNDONE"
    h = client.get("/api/settings-advanced").json()["history"]
    assert [x["action"] for x in h] == ["SETTINGS_ADVANCED_UNDONE", "SETTINGS_ADVANCED_APPLIED"] and h[1]["undone"]


def test_undo_refused_when_value_moved(client):
    aid = _apply(client, ("model", "num_threads", 4), confirm_text=PURCHASE, reason=REASON).json()["audit_id"]
    ss.update("model", {"num_threads": 6}, note="elsewhere")
    n = _hist("model")
    u = client.post("/api/settings-advanced/undo", json={"audit_id": aid, "confirm_text": PURCHASE, "reason": REASON})
    assert u.status_code == 409 and _code(u) == "SETTINGS_CHANGED_ELSEWHERE" and "model.num_threads" in u.json()["detail"]
    assert _hist("model") == n and _val("model", "num_threads") == 6


def test_undo_of_a_retention_increase_is_refused(client):
    aid = _apply(client, ("sel2_pipeline", "retention_days", 150), confirm_text=HIGH, reason=REASON).json()["audit_id"]
    u = client.post("/api/settings-advanced/undo", json={"audit_id": aid, "confirm_text": HIGH, "reason": REASON})
    assert u.status_code == 422 and _code(u) == "RETENTION_DECREASE_NOT_ALLOWED"
    assert _val("sel2_pipeline", "retention_days") == 150


def test_undo_busy_and_unknown(client):
    aid = _apply(client, ("bigquery", "max_retries", 3), acknowledged=True).json()["audit_id"]
    _job("JB-4", "D1_SYNC", "PENDING")
    u = client.post("/api/settings-advanced/undo", json={"audit_id": aid, "acknowledged": True})
    assert u.status_code == 409 and _code(u) == "SETTINGS_ADVANCED_BUSY"
    with db.tx() as c:
        c.execute("UPDATE job_runs SET status='SUCCEEDED'")
    assert client.post("/api/settings-advanced/undo", json={"audit_id": 999999}).status_code == 404


# ------------------------------------------------------------------ PUT guard + reset of the generic editor
GUARD_CASES = [("model", "num_threads", 4), ("sel2_pipeline", "spike_e4_n", 6), ("bigquery", "max_retries", 3),
               ("daily_forecast", "rounding_threshold", 0.3), ("daily_forecast", "log_retention_days", 60),
               ("schedule", "report_time", "08:00"), ("import", "column_aliases", {"sku_id": ["x"]}),
               ("horizons", "max_forecast_rows", 2000)]


@pytest.mark.parametrize("section,key,value", GUARD_CASES)
def test_put_refuses_a_changed_registry_key(client, section, key, value):
    body = client.get("/api/settings").json()[section]
    n = _hist(section)
    r = client.put(f"/api/settings/{section}", json={**body, key: value})
    assert r.status_code == 409 and _code(r) == "SETTINGS_FIELD_GUARDED", r.text
    assert r.json()["params"]["fields"] == [key] and r.json()["vi"] != r.json()["en"]
    assert _hist(section) == n and not reg.same(_val(section, key), value)


@pytest.mark.parametrize("section", ["model", "sel2_pipeline", "bigquery", "daily_forecast", "schedule", "import",
                                     "horizons"])
def test_put_whole_section_unchanged_registry_passes(client, section):
    body = client.get("/api/settings").json()[section]
    r = client.put(f"/api/settings/{section}", json=body)
    assert r.status_code == 200, r.text


def test_put_old_tab_cannot_undo_an_advanced_change(client):
    old_tab = client.get("/api/settings").json()["model"]
    assert _apply(client, ("model", "num_threads", 4), confirm_text=PURCHASE, reason=REASON).status_code == 200
    r = client.put("/api/settings/model", json={**old_tab, "num_boost_round": 100})
    assert r.status_code == 409 and _code(r) == "SETTINGS_FIELD_GUARDED"
    assert _val("model", "num_threads") == 4 and _val("model", "num_boost_round") == 300
    fresh = client.get("/api/settings").json()["model"]
    assert client.put("/api/settings/model", json={**fresh, "num_boost_round": 100}).status_code == 200


def test_put_partial_body_counts_left_out_key_as_default(client):
    ss.update("model", {"num_threads": 4}, note="setup")
    r = client.put("/api/settings/model", json={"num_boost_round": 100})
    assert r.status_code == 409 and _code(r) == "SETTINGS_FIELD_GUARDED"
    assert _val("model", "num_threads") == 4


def test_put_bigquery_connection_still_saved(client):
    r = client.put("/api/settings/bigquery", json={"source_table": "orders_v2"})
    assert r.status_code == 200 and r.json()["source_table"] == "orders_v2"


def test_put_existing_rules_keep_their_codes(client):
    cur = client.get("/api/settings").json()
    r = client.put("/api/settings/daily_forecast", json={**cur["daily_forecast"], "trial_mode": False})
    assert _code(r) == "TRIAL_MODE_CONFIRM_REQUIRED"
    r = client.put("/api/settings/schedule", json={**cur["schedule"], "d1_enabled": True})
    assert _code(r) == "SCHEDULE_SWITCH_VIA_FLOW_API"
    r = client.put("/api/settings/model", json={**cur["model"], "feature_open_hours": False})
    assert _code(r) == "OPEN_HOURS_MANDATORY"


@pytest.mark.parametrize("section,patch", [
    ("model", {"num_threads": 4, "fallback_enabled": False, "num_boost_round": 99}),
    ("sel2_pipeline", {"spike_e4_n": 6, "retention_days": 200, "tsb_alpha": 0.3}),
    ("bigquery", {"max_retries": 4, "max_null_share": 0.1, "maximum_bytes_billed": 11 * 1024 ** 2,
                  "initial_history_days": 400}),
    ("daily_forecast", {"rounding_threshold": 0.3, "log_retention_days": 200, "seller_code": "ABC"}),
    ("schedule", {"report_time": "08:00", "refresh_deadline": "11:00", "slot_grace_minutes": 30}),
    ("import", {"column_aliases": {"sku_id": ["x"]}, "max_rows": 99}),
    ("horizons", {"max_forecast_rows": 2000, "max_allowed_days": 400})])
def test_reset_keeps_every_registry_key(client, section, patch):
    ss.update(section, patch, note="setup")
    r = client.post(f"/api/settings/{section}/reset")
    assert r.status_code == 200, r.text
    out = ss.get(section).model_dump()
    default = ss.SECTIONS[section]().model_dump()
    for k, v in patch.items():
        # REV-B: the BigQuery cost cap is kept by a reset too (a default may be higher), though it is a VISIBLE key
        if reg.entry(section, k) or (section, k) == ("bigquery", "maximum_bytes_billed"):
            assert reg.same(out[k], v), (section, k)
        else:
            assert reg.same(out[k], default[k]), (section, k)


def test_bigquery_reset_keeps_connection_mapping_and_sign_in(client):
    conn = {"project_id": "my-project-123", "dataset_id": "ds1", "location": "US", "source_table": "t1",
            "partition_column": "p", "service_account_file": "C:\\k.json", "auth_method": "SERVICE_ACCOUNT_FILE",
            "history_start_date": "2025-06-01", "customer_id_column": "customer_id",
            "oauth_client_id": "1-a.apps.googleusercontent.com", "production_enabled": True,
            "d0_table_id": "my-project-123.ds.d0", "product_names_table": "dim_sku"}
    ss.update("bigquery", {**conn, "max_retries": 4, "maximum_bytes_billed": 11 * 1024 ** 2, "preview_rows": 60},
              note="setup")
    mapping = ss.get("bigquery").model_dump()["field_mapping"]
    r = client.post("/api/settings/bigquery/reset")
    assert r.status_code == 200, r.text
    out = r.json()
    b = ss.get("bigquery").model_dump()
    for k, v in conn.items():
        assert b[k] == v and out[k] == v, k
    assert b["field_mapping"] == mapping
    assert b["max_retries"] == 4 and b["preview_rows"] == 60                     # registry keys kept
    assert b["maximum_bytes_billed"] == 11 * 1024 ** 2 and out["maximum_bytes_billed"] == 11 * 1024 ** 2   # cost cap kept
    assert {"project_id", "dataset_id", "field_mapping", "reference_mapping", "oauth_client_id", "production_enabled",
            "d0_mapping", "service_account_file", "auth_method", "maximum_bytes_billed"} <= set(out["kept_keys"])
    expected = {k for (s, k) in reg.EXCLUDED if s == "bigquery"} | set(reg.keys_of("bigquery")) | {"maximum_bytes_billed"}
    assert set(out["kept_keys"]) == expected


# ------------------------------------------------------------------ apply-preset never lowers a retention (B5a)
def test_preset_no_longer_sets_log_retention_days():
    from app import cli
    assert "log_retention_days" not in cli.PRESETS["lgbm-chot"]["sections"]["daily_forecast"]


def test_preset_values_never_lower_an_only_increase_key():
    from app import cli
    cur = {"sel2_pipeline": ss.Sel2PipelineSettings(retention_days=200),
           "daily_forecast": ss.DailyForecastSettings(log_retention_days=300)}
    preset = {"sections": {"sel2_pipeline": {"retention_days": 120, "tsb_alpha": 0.2},
                           "daily_forecast": {"log_retention_days": 400}}}
    vals, kept = cli._preset_values(preset, cur)
    assert vals == {"sel2_pipeline": {"tsb_alpha": 0.2}, "daily_forecast": {"log_retention_days": 400}}
    assert kept == [{"section": "sel2_pipeline", "key": "retention_days", "current": 200, "preset": 120}]


def test_preset_dry_run_leaves_a_longer_log_retention(capsys):
    from app import cli
    ss.update("model", {"forecast_strategy": "DIRECT"}, note="setup: the preset's horizon weights need DIRECT")
    ss.update("daily_forecast", {"log_retention_days": 365}, note="setup")
    ss.update("model", {"forecast_strategy": "DIRECT"}, note="setup")      # the preset's horizon weights need DIRECT
    n = _hist("daily_forecast")
    assert cli.main(["apply-preset", "lgbm-chot"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert not any(c["key"] == "log_retention_days" for c in dry["changes"]) and dry["kept_higher"] == []
    assert _hist("daily_forecast") == n and ss.get("daily_forecast").log_retention_days == 365


def test_reset_model_keeps_direct_strategy_with_horizon_weights(client):
    ss.update("model", {"forecast_strategy": "DIRECT", "horizon_weight_short": 3.0, "horizon_weight_cutoff": 7,
                        "num_boost_round": 99}, note="setup")
    r = client.post("/api/settings/model/reset")
    assert r.status_code == 200, r.text
    m = ss.get("model")
    assert (m.forecast_strategy, m.horizon_weight_short, m.horizon_weight_cutoff) == ("DIRECT", 3.0, 7)
    assert m.num_boost_round == 300                     # a VISIBLE key is reset


def test_reset_model_without_weights_resets_the_strategy(client):
    ss.update("model", {"forecast_strategy": "DIRECT"}, note="setup")
    assert client.post("/api/settings/model/reset").status_code == 200
    assert ss.get("model").forecast_strategy == "RECURSIVE"


def test_export_subdir_is_purchase():
    assert reg.risk(reg.entry("sel2_pipeline", "export_subdir")) == "PURCHASE"
