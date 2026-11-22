"""1.4.15 (lot 1): the four guarded data_policy fields change only through /api/data-policy/guarded.

Integration with fakes (TestClient on the isolated temporary database, no real data, no network).
Covers: the generic editor (PUT /api/settings/data_policy and its reset) keeps the four fields; GET / preview / apply of
the guarded endpoint (expected value, confirmation text of the Vietnam day, reason length, acknowledged, validation,
history, audit, undo, sequential "concurrent" requests); other sections are not affected.
"""
import json
from datetime import datetime

import pytest

from app import db
from app import settings_service as ss
from app import timeutil
from app.timeutil import VN_TZ

GUARDED = ("window_start_date", "history_change_policy", "history_day_check", "source_time_travel_hours")
TODAY = "2026-11-22"
CONFIRM = f"DOI-CHINH-SACH-DU-LIEU-{TODAY}"
REASON = "chu du an duyet doi chinh sach"       # >= 10 characters


@pytest.fixture(autouse=True)
def _frozen_day():
    timeutil.set_now_override(lambda: datetime(2026, 11, 22, 12, 0, tzinfo=VN_TZ))
    yield


# ------------------------------------------------------------------ helpers
def _hist_count(section="data_policy") -> int:
    with db.read() as c:
        return c.execute("SELECT COUNT(*) FROM settings_history WHERE section=?", (section,)).fetchone()[0]


def _stored(section="data_policy"):
    with db.read() as c:
        r = c.execute("SELECT value_json FROM app_settings WHERE section=?", (section,)).fetchone()
    return json.loads(r[0]) if r else None


def _audit_count(action) -> int:
    with db.read() as c:
        return c.execute("SELECT COUNT(*) FROM audit_log WHERE action=?", (action,)).fetchone()[0]


def _policy() -> dict:
    return ss.get("data_policy").model_dump()


def _guarded() -> dict:
    p = _policy()
    return {k: p[k] for k in GUARDED}


def _set(**kw):
    """Put values straight in the store (setup only, bypassing the API)."""
    ss.update("data_policy", kw, note="test setup")


def _apply(client, patch, expected=None, **kw):
    cur = _guarded()
    body = {"patch": patch, "expected": {k: cur[k] for k in patch} if expected is None else expected}
    body.update(kw)
    return client.post("/api/data-policy/guarded", json=body)


def _high(**kw):
    return {"confirm_text": CONFIRM, "reason": REASON, **kw}


def _code(r):
    return r.json()["code"]


# ------------------------------------------------------------------ generic editor keeps the four fields
def test_put_keeps_four_guarded_fields_and_saves_others(client):
    before = _guarded()
    body = {**_policy(), "window_start_date": "2025-06-01", "history_change_policy": "FOLLOW_SOURCE",
            "history_day_check": False, "source_time_travel_hours": 100, "max_data_lag_days": 5,
            "late_data_lookback_days": 7}
    r = client.put("/api/settings/data_policy", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert {k: out[k] for k in GUARDED} == before
    assert out["max_data_lag_days"] == 5 and out["late_data_lookback_days"] == 7
    stored = _stored()
    assert {k: stored[k] for k in GUARDED} == before
    assert stored["max_data_lag_days"] == 5


def test_put_old_tab_sends_defaults_follow_source_stays(client):
    _set(history_change_policy="FOLLOW_SOURCE")
    old_tab = {**_policy(), "history_change_policy": "KEEP_OBSERVED_LINES", "max_data_lag_days": 4}  # stale full payload
    r = client.put("/api/settings/data_policy", json=old_tab)
    assert r.status_code == 200, r.text
    assert r.json()["history_change_policy"] == "FOLLOW_SOURCE"
    assert _stored()["history_change_policy"] == "FOLLOW_SOURCE"
    assert _stored()["max_data_lag_days"] == 4


def test_put_partial_body_without_guarded_fields_keeps_them(client):
    _set(source_time_travel_hours=120, history_day_check=False)
    r = client.put("/api/settings/data_policy", json={"max_data_lag_days": 3})
    assert r.status_code == 200, r.text
    assert _guarded()["source_time_travel_hours"] == 120 and _guarded()["history_day_check"] is False
    assert _policy()["max_data_lag_days"] == 3


def test_put_writes_one_history_row(client):
    n = _hist_count()
    assert client.put("/api/settings/data_policy", json={**_policy(), "max_data_lag_days": 9}).status_code == 200
    assert _hist_count() == n + 1


def test_reset_keeps_guarded_and_resets_others(client):
    _set(window_start_date="2025-03-01", history_change_policy="FOLLOW_SOURCE", history_day_check=False,
         source_time_travel_hours=77, max_data_lag_days=11, price_outlier_factor=25.0)
    kept = _guarded()
    r = client.post("/api/settings/data_policy/reset")
    assert r.status_code == 200, r.text
    out = r.json()
    assert {k: out[k] for k in GUARDED} == kept
    assert out["max_data_lag_days"] == 2 and out["price_outlier_factor"] == 10.0
    assert _guarded() == kept
    assert _stored()["max_data_lag_days"] == 2


def test_reset_on_fresh_db_keeps_defaults(client):
    r = client.post("/api/settings/data_policy/reset")
    assert r.status_code == 200
    d = ss.DataPolicySettings().model_dump()
    assert {k: r.json()[k] for k in GUARDED} == {k: d[k] for k in GUARDED}


def test_put_other_sections_not_affected(client):
    sched = client.get("/api/settings/schedule").json()
    daily = client.get("/api/settings/daily_forecast").json()
    n_dp = _hist_count("data_policy")
    r = client.put("/api/settings/daily_forecast", json=daily)       # old behaviour of the generic editor is kept
    assert r.status_code == 200, r.text
    assert r.json() == ss.get("daily_forecast").model_dump()
    r = client.put("/api/settings/schedule", json=sched)
    assert r.status_code == 200, r.text
    assert r.json() == ss.get("schedule").model_dump()
    # the data_policy section is untouched by the other sections
    assert _hist_count("data_policy") == n_dp
    assert _guarded() == {k: ss.DataPolicySettings().model_dump()[k] for k in GUARDED}


# ------------------------------------------------------------------ GET
def test_get_fresh_version_zero_and_contract(client):
    r = client.get("/api/data-policy/guarded")
    assert r.status_code == 200, r.text
    j = r.json()
    d = ss.DataPolicySettings().model_dump()
    assert j["fields"] == {k: d[k] for k in GUARDED}
    assert j["defaults"] == j["fields"]
    assert j["version"] == 0
    assert j["confirm_text"] == CONFIRM
    assert j["high_risk_fields"] == ["history_change_policy", "window_start_date"]
    assert j["reason_min_length"] == 10
    assert j["history"] == []


def test_get_confirm_text_uses_vietnam_date_not_utc(client):
    # 23/11 02:00 Vietnam = 22/11 19:00 UTC
    timeutil.set_now_override(lambda: datetime(2026, 11, 23, 2, 0, tzinfo=VN_TZ))
    assert client.get("/api/data-policy/guarded").json()["confirm_text"] == "DOI-CHINH-SACH-DU-LIEU-2026-11-23"
    # 22/11 23:30 Vietnam = 22/11 16:30 UTC
    timeutil.set_now_override(lambda: datetime(2026, 11, 22, 23, 30, tzinfo=VN_TZ))
    assert client.get("/api/data-policy/guarded").json()["confirm_text"] == CONFIRM


def test_get_version_is_latest_history_id_and_history_max_five(client):
    for i in range(7):
        r = _apply(client, {"source_time_travel_hours": 100 + i}, acknowledged=True)
        assert r.status_code == 200, r.text
    j = client.get("/api/data-policy/guarded").json()
    with db.read() as c:
        last = c.execute("SELECT MAX(id) FROM settings_history WHERE section='data_policy'").fetchone()[0]
    assert j["version"] == last
    assert len(j["history"]) == 5
    ids = [h["id"] for h in j["history"]]
    assert ids == sorted(ids, reverse=True)                    # newest first
    assert [h["values"]["source_time_travel_hours"] for h in j["history"]] == [106, 105, 104, 103, 102]
    assert set(j["history"][0]) == {"id", "changed_at", "note", "values", "previous_values"}
    assert set(j["history"][0]["values"]) == set(GUARDED)


def test_get_history_skips_rows_that_do_not_change_guarded_fields(client):
    assert _apply(client, {"source_time_travel_hours": 90}, acknowledged=True).status_code == 200
    assert client.put("/api/settings/data_policy", json={**_policy(), "max_data_lag_days": 6}).status_code == 200
    h = client.get("/api/data-policy/guarded").json()["history"]
    assert len(h) == 1 and h[0]["values"]["source_time_travel_hours"] == 90
    assert "OWNER_CONFIRMED" in h[0]["note"]


# ------------------------------------------------------------------ preview
def test_preview_writes_nothing(client):
    n_hist, n_audit, stored = _hist_count(), _audit_count("DATA_POLICY_GUARDED_APPLIED"), _stored()
    r = client.post("/api/data-policy/guarded/preview",
                    json={"patch": {"history_change_policy": "FOLLOW_SOURCE", "source_time_travel_hours": 50}})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["before"]["history_change_policy"] == "KEEP_OBSERVED_LINES"
    assert j["after"]["history_change_policy"] == "FOLLOW_SOURCE" and j["after"]["source_time_travel_hours"] == 50
    assert j["changed"] == ["history_change_policy", "source_time_travel_hours"]
    assert j["high_risk"] is True and j["needs_confirm_text"] is True and j["needs_acknowledged"] is True
    assert _hist_count() == n_hist and _audit_count("DATA_POLICY_GUARDED_APPLIED") == n_audit
    assert _stored() == stored
    assert _policy()["history_change_policy"] == "KEEP_OBSERVED_LINES"


def test_preview_low_risk_only(client):
    j = client.post("/api/data-policy/guarded/preview", json={"patch": {"history_day_check": False}}).json()
    assert j["changed"] == ["history_day_check"]
    assert j["high_risk"] is False and j["needs_confirm_text"] is False and j["needs_acknowledged"] is True


def test_preview_window_start_is_locked(client):
    for v in ("2025-12-22", "2026-02-01"):
        r = client.post("/api/data-policy/guarded/preview", json={"patch": {"window_start_date": v}})
        assert r.status_code == 422 and _code(r) == "DATA_POLICY_FIELD_LOCKED", r.text
        assert r.json()["params"]["reason_code"] == "WINDOW_START_CHANGES_RELOAD"


def test_preview_no_change_warns(client):
    j = client.post("/api/data-policy/guarded/preview", json={"patch": {"source_time_travel_hours": 160}}).json()
    assert j["changed"] == [] and "NO_CHANGE" in j["warnings"] and j["high_risk"] is False


def test_preview_type_is_part_of_change(client):
    # 160.0 is not 160, True is not 1: the validated value is compared with its type
    j = client.post("/api/data-policy/guarded/preview", json={"patch": {"history_day_check": True}}).json()
    assert j["changed"] == []


def test_preview_unknown_field_422(client):
    r = client.post("/api/data-policy/guarded/preview", json={"patch": {"max_data_lag_days": 3}})
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_UNKNOWN_FIELD"


def test_preview_empty_patch_422(client):
    r = client.post("/api/data-policy/guarded/preview", json={"patch": {}})
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_UNKNOWN_FIELD"


def test_preview_wrong_type_422(client):
    r = client.post("/api/data-policy/guarded/preview", json={"patch": {"source_time_travel_hours": "abc"}})
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_INVALID_VALUE"
    r = client.post("/api/data-policy/guarded/preview", json={"patch": {"history_change_policy": "OTHER"}})
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_INVALID_VALUE"


def test_preview_missing_patch_422(client):
    assert client.post("/api/data-policy/guarded/preview", json={}).status_code == 422


# ------------------------------------------------------------------ validation (apply)
@pytest.mark.parametrize("bad", [0, 169, "abc", -1])
def test_apply_rejects_bad_source_time_travel_hours(client, bad):
    n = _hist_count()
    r = _apply(client, {"source_time_travel_hours": bad}, expected={"source_time_travel_hours": 160}, acknowledged=True)
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_INVALID_VALUE", r.text
    assert _hist_count() == n and _guarded()["source_time_travel_hours"] == 160


@pytest.mark.parametrize("ok", [1, 168])
def test_apply_accepts_time_travel_bounds(client, ok):
    r = _apply(client, {"source_time_travel_hours": ok}, acknowledged=True)
    assert r.status_code == 200, r.text
    assert _guarded()["source_time_travel_hours"] == ok


@pytest.mark.parametrize("value", ["2025/01/01", "01-01-2025", "abc", "2025-13-40", "", "20250101",
                                   "2026-11-23", "2027-01-01", TODAY, "2025-06-01", "2026-01-01"])
def test_window_start_is_locked_in_apply_and_preview_for_any_value(client, value):
    """Locked whatever the value (bad format, future, today, valid, even the current one): nothing is written."""
    n, stored = _hist_count(), _stored()
    r = _apply(client, {"window_start_date": value}, expected={"window_start_date": "2026-01-01"}, **_high())
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_FIELD_LOCKED", r.text
    assert r.json()["params"]["reason_code"] == "WINDOW_START_CHANGES_RELOAD"
    r = client.post("/api/data-policy/guarded/preview", json={"patch": {"window_start_date": value}})
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_FIELD_LOCKED", r.text
    assert _hist_count() == n and _stored() == stored


def test_apply_rejects_unknown_and_too_many_fields(client):
    r = _apply(client, {"max_data_lag_days": 3}, expected={"max_data_lag_days": 2}, acknowledged=True)
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_UNKNOWN_FIELD"
    r = _apply(client, {"history_day_check": False, "oops": 1}, expected={"history_day_check": True, "oops": 1},
               acknowledged=True)
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_UNKNOWN_FIELD"
    r = _apply(client, {}, expected={}, acknowledged=True)
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_UNKNOWN_FIELD"


# ------------------------------------------------------------------ expected
def test_apply_expected_missing_422_and_no_write(client):
    n = _hist_count()
    r = client.post("/api/data-policy/guarded", json={"patch": {"source_time_travel_hours": 100}, "acknowledged": True})
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_EXPECTED_REQUIRED"
    r = client.post("/api/data-policy/guarded", json={"patch": {"source_time_travel_hours": 100}, "expected": {},
                                                      "acknowledged": True})
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_EXPECTED_REQUIRED"
    assert _hist_count() == n and _guarded()["source_time_travel_hours"] == 160


def test_apply_expected_mismatch_409_with_current_and_no_write(client):
    n, n_audit = _hist_count(), _audit_count("DATA_POLICY_GUARDED_APPLIED")
    _set(source_time_travel_hours=120)                    # changed elsewhere after the screen was opened
    r = _apply(client, {"source_time_travel_hours": 100}, expected={"source_time_travel_hours": 160}, acknowledged=True)
    assert r.status_code == 409 and _code(r) == "SETTINGS_CHANGED_ELSEWHERE", r.text
    p = r.json()["params"]
    assert p["current"]["source_time_travel_hours"] == 120
    with db.read() as c:
        assert p["version"] == c.execute("SELECT MAX(id) FROM settings_history WHERE section='data_policy'").fetchone()[0]
    assert _guarded()["source_time_travel_hours"] == 120
    assert _hist_count() == n + 1 and _audit_count("DATA_POLICY_GUARDED_APPLIED") == n_audit   # only the setup row


def test_apply_expected_compares_type_not_only_value(client):
    # stored 160 (int): 160.0 (float) is a different value for the guard; stored True (bool): 1 is different
    r = _apply(client, {"source_time_travel_hours": 100}, expected={"source_time_travel_hours": 160.0}, acknowledged=True)
    assert r.status_code == 409 and _code(r) == "SETTINGS_CHANGED_ELSEWHERE"
    r = _apply(client, {"history_day_check": False}, expected={"history_day_check": 1}, acknowledged=True)
    assert r.status_code == 409 and _code(r) == "SETTINGS_CHANGED_ELSEWHERE"
    r = _apply(client, {"history_day_check": False}, expected={"history_day_check": "true"}, acknowledged=True)
    assert r.status_code == 409 and _code(r) == "SETTINGS_CHANGED_ELSEWHERE"
    assert _guarded() == {k: ss.DataPolicySettings().model_dump()[k] for k in GUARDED}


def test_apply_expected_only_for_patched_fields(client):
    # a stale value of a field that is not in the patch does not matter
    r = _apply(client, {"source_time_travel_hours": 100}, expected={"source_time_travel_hours": 160, "history_day_check": False},
               acknowledged=True)
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ confirmation
def test_apply_high_risk_requires_confirm_text(client):
    n = _hist_count()
    for kw in ({"reason": REASON},                                        # missing text
               {"reason": REASON, "confirm_text": "DOI-CHINH-SACH-DU-LIEU-2026-11-21"},    # yesterday
               {"reason": REASON, "confirm_text": "doi-chinh-sach-du-lieu-2026-11-22"},    # case matters
               {"reason": REASON, "confirm_text": "DOI-CHINH-SACH-DU-LIEU-"}):
        r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, **kw)
        assert r.status_code == 409 and _code(r) == "DATA_POLICY_CONFIRM_REQUIRED", (kw, r.text)
    assert _hist_count() == n and _guarded()["history_change_policy"] == "KEEP_OBSERVED_LINES"


def test_apply_confirm_text_wrong_vietnam_day_near_midnight(client):
    # 23/11 00:30 Vietnam (still 22/11 in UTC): the text of 22/11 is already yesterday
    timeutil.set_now_override(lambda: datetime(2026, 11, 23, 0, 30, tzinfo=VN_TZ))
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, confirm_text=CONFIRM, reason=REASON)
    assert r.status_code == 409 and _code(r) == "DATA_POLICY_CONFIRM_REQUIRED"
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, confirm_text="DOI-CHINH-SACH-DU-LIEU-2026-11-23",
               reason=REASON)
    assert r.status_code == 200, r.text


def test_apply_confirm_text_surrounding_spaces_trimmed(client):
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, confirm_text=f"  {CONFIRM} ", reason=REASON)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("reason", [None, "", "123456789", "   short   ", "a" * 9])
def test_apply_high_risk_reason_too_short(client, reason):
    n = _hist_count()
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, confirm_text=CONFIRM, reason=reason)
    assert r.status_code == 409 and _code(r) == "DATA_POLICY_CONFIRM_REQUIRED", r.text
    assert _hist_count() == n


def test_apply_reason_exactly_10_ok(client):
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, confirm_text=CONFIRM, reason="1234567890")
    assert r.status_code == 200, r.text


def test_apply_reason_501_rejected_500_ok(client):
    n = _hist_count()
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, confirm_text=CONFIRM, reason="a" * 501)
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_INVALID_VALUE", r.text
    assert _hist_count() == n
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, confirm_text=CONFIRM, reason="a" * 500)
    assert r.status_code == 200, r.text


def test_apply_low_risk_requires_acknowledged(client):
    n = _hist_count()
    r = _apply(client, {"history_day_check": False})
    assert r.status_code == 409 and _code(r) == "DATA_POLICY_CONFIRM_REQUIRED"
    r = _apply(client, {"source_time_travel_hours": 100}, acknowledged=False)
    assert r.status_code == 409 and _code(r) == "DATA_POLICY_CONFIRM_REQUIRED"
    assert _hist_count() == n


def test_apply_low_risk_needs_no_confirm_text_nor_reason(client):
    r = _apply(client, {"history_day_check": False}, acknowledged=True)
    assert r.status_code == 200, r.text
    assert _guarded()["history_day_check"] is False


def test_apply_mixed_needs_both_confirmations(client):
    patch = {"history_change_policy": "FOLLOW_SOURCE", "source_time_travel_hours": 100}
    n = _hist_count()
    assert _code(_apply(client, patch, confirm_text=CONFIRM, reason=REASON)) == "DATA_POLICY_CONFIRM_REQUIRED"   # no ack
    assert _code(_apply(client, patch, acknowledged=True)) == "DATA_POLICY_CONFIRM_REQUIRED"            # no text
    assert _hist_count() == n
    r = _apply(client, patch, acknowledged=True, **_high())
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == patch


def test_apply_high_risk_only_does_not_need_acknowledged(client):
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, **_high())
    assert r.status_code == 200, r.text


def test_apply_no_change_400(client):
    n = _hist_count()
    r = _apply(client, {"source_time_travel_hours": 160}, acknowledged=True)
    assert r.status_code == 400 and _code(r) == "NO_CHANGE"
    r = _apply(client, {"history_change_policy": "KEEP_OBSERVED_LINES"}, **_high())
    assert r.status_code == 400 and _code(r) == "NO_CHANGE"
    assert _hist_count() == n


# ------------------------------------------------------------------ success, history, audit, undo
def test_apply_success_changes_one_field_one_history_one_audit(client):
    before = _policy()
    v0 = client.get("/api/data-policy/guarded").json()["version"]
    n_hist, n_audit = _hist_count(), _audit_count("DATA_POLICY_GUARDED_APPLIED")
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, **_high())
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["applied"] == {"history_change_policy": "FOLLOW_SOURCE"}
    after = _policy()
    assert after["history_change_policy"] == "FOLLOW_SOURCE"
    assert {k: v for k, v in after.items() if k != "history_change_policy"} == \
           {k: v for k, v in before.items() if k != "history_change_policy"}
    assert _hist_count() == n_hist + 1
    assert _audit_count("DATA_POLICY_GUARDED_APPLIED") == n_audit + 1
    assert j["version"] > v0 and client.get("/api/data-policy/guarded").json()["version"] == j["version"]
    with db.read() as c:
        row = c.execute("SELECT id, note, value_json FROM settings_history WHERE section='data_policy' "
                        "ORDER BY id DESC LIMIT 1").fetchone()
    assert row["id"] == j["version"]
    assert row["note"].startswith("OWNER_CONFIRMED data_policy")
    assert "history_change_policy KEEP_OBSERVED_LINES -> FOLLOW_SOURCE" in row["note"]
    assert REASON in row["note"]
    assert json.loads(row["value_json"])["history_change_policy"] == "FOLLOW_SOURCE"
    with db.read() as c:
        a = c.execute("SELECT details_json, entity_id FROM audit_log WHERE action='DATA_POLICY_GUARDED_APPLIED'").fetchone()
    d = json.loads(a["details_json"])
    assert a["entity_id"] == "data_policy"
    assert d["changes"] == {"history_change_policy": {"from": "KEEP_OBSERVED_LINES", "to": "FOLLOW_SOURCE"}}
    assert d["reason"] == REASON and d["version"] == j["version"]


def test_apply_keeps_other_guarded_and_other_data_policy_fields(client):
    _set(window_start_date="2025-05-05", history_day_check=False, source_time_travel_hours=77, max_data_lag_days=6)
    r = _apply(client, {"source_time_travel_hours": 80}, acknowledged=True)
    assert r.status_code == 200, r.text
    p = _policy()
    assert p["source_time_travel_hours"] == 80
    assert p["window_start_date"] == "2025-05-05" and p["history_day_check"] is False and p["max_data_lag_days"] == 6


def test_apply_reason_normalised_whitespace_in_note(client):
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, confirm_text=CONFIRM,
               reason="  doi   chinh\n sach  window ")
    assert r.status_code == 200, r.text
    with db.read() as c:
        note = c.execute("SELECT note FROM settings_history WHERE section='data_policy' ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert note.endswith(": doi chinh sach window")
    assert "history_change_policy KEEP_OBSERVED_LINES -> FOLLOW_SOURCE" in note


def test_apply_low_risk_without_reason_note_has_no_trailing_reason(client):
    assert _apply(client, {"history_day_check": False}, acknowledged=True).status_code == 200
    with db.read() as c:
        note = c.execute("SELECT note FROM settings_history WHERE section='data_policy' ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert note == "OWNER_CONFIRMED data_policy history_day_check true -> false"


def test_undo_through_same_endpoint(client):
    first = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, **_high())
    assert first.status_code == 200
    # undo = apply the previous value, expected = the value now stored
    undo = client.post("/api/data-policy/guarded",
                       json={"patch": {"history_change_policy": "KEEP_OBSERVED_LINES"},
                             "expected": {"history_change_policy": "FOLLOW_SOURCE"}, **_high(reason="hoan tac thay doi")})
    assert undo.status_code == 200, undo.text
    assert undo.json()["version"] > first.json()["version"]
    assert _guarded()["history_change_policy"] == "KEEP_OBSERVED_LINES"
    assert _audit_count("DATA_POLICY_GUARDED_APPLIED") == 2
    h = client.get("/api/data-policy/guarded").json()["history"]
    assert [x["values"]["history_change_policy"] for x in h] == ["KEEP_OBSERVED_LINES", "FOLLOW_SOURCE"]


def test_sequential_requests_with_same_expected_only_first_wins(client):
    exp = {"source_time_travel_hours": 160}
    r1 = _apply(client, {"source_time_travel_hours": 100}, expected=exp, acknowledged=True)
    r2 = _apply(client, {"source_time_travel_hours": 90}, expected=exp, acknowledged=True)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 409 and _code(r2) == "SETTINGS_CHANGED_ELSEWHERE"
    assert r2.json()["params"]["current"]["source_time_travel_hours"] == 100
    assert _guarded()["source_time_travel_hours"] == 100
    assert _audit_count("DATA_POLICY_GUARDED_APPLIED") == 1


def test_generic_put_after_guarded_apply_does_not_undo_it(client):
    assert _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, **_high()).status_code == 200
    stale = {**_policy(), "history_change_policy": "KEEP_OBSERVED_LINES", "max_data_lag_days": 8}
    assert client.put("/api/settings/data_policy", json=stale).status_code == 200
    assert _policy()["history_change_policy"] == "FOLLOW_SOURCE" and _policy()["max_data_lag_days"] == 8


# ------------------------------------------------------------------ round 2: previous_values, confirm_text in preview / errors
def _defaults_guarded() -> dict:
    d = ss.DataPolicySettings().model_dump()
    return {k: d[k] for k in GUARDED}


def test_history_first_row_previous_values_are_defaults(client):
    assert _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, **_high()).status_code == 200
    h = client.get("/api/data-policy/guarded").json()
    assert len(h["history"]) == 1
    row = h["history"][0]
    assert row["values"]["history_change_policy"] == "FOLLOW_SOURCE"
    assert row["previous_values"] == _defaults_guarded()
    assert row["previous_values"]["history_change_policy"] == "KEEP_OBSERVED_LINES"
    assert row["previous_values"] == h["defaults"]


def test_history_previous_values_chain_to_the_row_before(client):
    assert _apply(client, {"source_time_travel_hours": 100}, acknowledged=True).status_code == 200
    assert _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, **_high()).status_code == 200
    assert _apply(client, {"history_day_check": False}, acknowledged=True).status_code == 200
    h = client.get("/api/data-policy/guarded").json()["history"]
    assert len(h) == 3
    assert h[0]["previous_values"] == h[1]["values"]
    assert h[1]["previous_values"] == h[2]["values"]
    assert h[2]["previous_values"] == _defaults_guarded()
    assert h[0]["values"]["history_day_check"] is False and h[0]["previous_values"]["history_day_check"] is True


def test_history_previous_values_skip_rows_that_do_not_change_guarded_fields(client):
    assert _apply(client, {"source_time_travel_hours": 90}, acknowledged=True).status_code == 200
    assert client.put("/api/settings/data_policy", json={**_policy(), "max_data_lag_days": 6}).status_code == 200
    assert _apply(client, {"source_time_travel_hours": 80}, acknowledged=True).status_code == 200
    assert client.put("/api/settings/data_policy", json={**_policy(), "max_data_lag_days": 7}).status_code == 200
    h = client.get("/api/data-policy/guarded").json()["history"]
    assert [x["values"]["source_time_travel_hours"] for x in h] == [80, 90]
    assert [x["previous_values"]["source_time_travel_hours"] for x in h] == [90, 160]
    assert h[0]["previous_values"] == h[1]["values"] and h[1]["previous_values"] == _defaults_guarded()


def test_history_previous_values_when_only_other_fields_were_saved_first(client):
    # a generic save before the first guarded change: the first guarded row still has the defaults as previous
    assert client.put("/api/settings/data_policy", json={**_policy(), "max_data_lag_days": 6}).status_code == 200
    assert _apply(client, {"source_time_travel_hours": 120}, acknowledged=True).status_code == 200
    h = client.get("/api/data-policy/guarded").json()["history"]
    assert len(h) == 1 and h[0]["previous_values"] == _defaults_guarded()


def test_undo_with_previous_values_through_guarded_endpoint(client):
    assert _apply(client, {"history_change_policy": "FOLLOW_SOURCE", "source_time_travel_hours": 100},
                  acknowledged=True, **_high()).status_code == 200
    row = client.get("/api/data-policy/guarded").json()["history"][0]
    cur = _guarded()
    patch = {k: v for k, v in row["previous_values"].items() if not _same_val(cur[k], v)}
    assert set(patch) == {"history_change_policy", "source_time_travel_hours"}
    r = client.post("/api/data-policy/guarded",
                    json={"patch": patch, "expected": {k: cur[k] for k in patch}, "acknowledged": True,
                          **_high(reason="hoan tac theo previous_values")})
    assert r.status_code == 200, r.text
    assert _guarded() == row["previous_values"] == _defaults_guarded()
    h = client.get("/api/data-policy/guarded").json()["history"]
    assert h[0]["values"] == row["previous_values"] and h[0]["previous_values"] == row["values"]


def _same_val(a, b) -> bool:
    return type(a) is type(b) and a == b


def test_preview_confirm_text_matches_get_and_vietnam_day(client):
    patch = {"patch": {"history_change_policy": "FOLLOW_SOURCE"}}
    for now, text in ((datetime(2026, 11, 22, 23, 30, tzinfo=VN_TZ), "DOI-CHINH-SACH-DU-LIEU-2026-11-22"),
                      (datetime(2026, 11, 23, 2, 0, tzinfo=VN_TZ), "DOI-CHINH-SACH-DU-LIEU-2026-11-23")):
        timeutil.set_now_override(lambda now=now: now)
        pv = client.post("/api/data-policy/guarded/preview", json=patch).json()
        assert pv["confirm_text"] == text
        assert pv["confirm_text"] == client.get("/api/data-policy/guarded").json()["confirm_text"]


def test_preview_confirm_text_present_even_without_change(client):
    j = client.post("/api/data-policy/guarded/preview", json={"patch": {"source_time_travel_hours": 160}}).json()
    assert j["confirm_text"] == CONFIRM


def test_confirm_required_errors_carry_params_confirm_text(client):
    cases = [
        dict(confirm_text=None, reason=REASON),                                       # missing text
        dict(confirm_text="DOI-CHINH-SACH-DU-LIEU-2026-11-21", reason=REASON),        # yesterday's text
        dict(confirm_text=CONFIRM, reason=None),                                      # missing reason
        dict(confirm_text=CONFIRM, reason="short"),                                   # reason too short
    ]
    for kw in cases:
        r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, **kw)
        assert r.status_code == 409 and _code(r) == "DATA_POLICY_CONFIRM_REQUIRED", (kw, r.text)
        assert r.json()["params"]["confirm_text"] == CONFIRM, kw
    # low-risk field without acknowledged: the text is given too
    r = _apply(client, {"history_day_check": False})
    assert _code(r) == "DATA_POLICY_CONFIRM_REQUIRED" and r.json()["params"]["confirm_text"] == CONFIRM


def test_confirm_required_params_text_follows_vietnam_day(client):
    timeutil.set_now_override(lambda: datetime(2026, 11, 23, 0, 30, tzinfo=VN_TZ))
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, confirm_text=CONFIRM, reason=REASON)
    assert r.status_code == 409
    assert r.json()["params"]["confirm_text"] == "DOI-CHINH-SACH-DU-LIEU-2026-11-23"


# ------------------------------------------------------------------ round 3: window locked, BUSY, impact / notes, reset
def _at(h, m, day=22):
    timeutil.set_now_override(lambda: datetime(2026, 11, day, h, m, tzinfo=VN_TZ))


_JOB_SEQ = [0]


def _job(job_type, status):
    _JOB_SEQ[0] += 1
    n = _JOB_SEQ[0]
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) VALUES (?,?,?,?,?,?)",
                  (f"J-{n}-{job_type}", job_type, f"idem-{n}-{job_type}-{status}", "MANUAL", status,
                   "2026-11-22T05:00:00+00:00"))


def _held(scope, status, n_lines):
    with db.tx() as c:
        for i in range(n_lines):
            c.execute("INSERT INTO demand_held_lines(id, scope_key, order_date, sku_id, fc_id, order_id, qty, cause, status,"
                      " detected_run, detected_at, released_at, released_run, release_reason) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (f"H-{scope}-{status}-{i}", scope, "2026-11-01", f"S{i}", "FC1", f"O{i}", 1.0, "ORDER_GONE", status,
                       "run-1", "2026-11-02T00:00:00+00:00",
                       None if status == "ACTIVE" else "2026-11-03T00:00:00+00:00",
                       None if status == "ACTIVE" else "run-2", None if status == "ACTIVE" else "REAPPEARED"))


def test_get_locked_fields(client):
    j = client.get("/api/data-policy/guarded").json()
    assert j["locked_fields"] == ["window_start_date"]
    assert j["locked_reason_code"] == "WINDOW_START_CHANGES_RELOAD"


def test_window_lock_applies_to_mixed_patch_and_writes_nothing(client):
    n, stored, n_audit = _hist_count(), _stored(), _audit_count("DATA_POLICY_GUARDED_APPLIED")
    patch = {"window_start_date": "2025-06-01", "source_time_travel_hours": 100}
    exp = {"window_start_date": "2026-01-01", "source_time_travel_hours": 160}
    r = _apply(client, patch, expected=exp, acknowledged=True, **_high())
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_FIELD_LOCKED", r.text
    assert r.json()["params"]["reason_code"] == "WINDOW_START_CHANGES_RELOAD"
    r = client.post("/api/data-policy/guarded/preview", json={"patch": patch})
    assert r.status_code == 422 and _code(r) == "DATA_POLICY_FIELD_LOCKED"
    assert _hist_count() == n and _stored() == stored and _audit_count("DATA_POLICY_GUARDED_APPLIED") == n_audit
    assert _guarded()["source_time_travel_hours"] == 160


# ---- BUSY by time (Vietnam clock)
@pytest.mark.parametrize("h,m,day", [(23, 50, 22), (0, 10, 23), (1, 0, 23), (3, 44, 23), (23, 45, 22), (0, 0, 23),
                                     (0, 45, 23), (2, 0, 23)])
def test_apply_busy_in_production_windows(client, h, m, day):
    _at(h, m, day)
    n, stored = _hist_count(), _stored()
    r = _apply(client, {"source_time_travel_hours": 100}, acknowledged=True)
    assert r.status_code == 409 and _code(r) == "DATA_POLICY_BUSY", r.text
    assert r.json()["params"]["window"] in ("23:45-00:15", "00:45-03:45")
    assert _hist_count() == n and _stored() == stored and _guarded()["source_time_travel_hours"] == 160


@pytest.mark.parametrize("h,m,day", [(3, 45, 23), (12, 0, 22), (0, 15, 23), (0, 30, 23), (23, 44, 22), (0, 44, 23)])
def test_apply_not_busy_outside_production_windows(client, h, m, day):
    _at(h, m, day)
    r = _apply(client, {"source_time_travel_hours": 100}, acknowledged=True)
    assert r.status_code == 200, r.text


def test_busy_window_params_name_the_window(client):
    _at(23, 50)
    assert _apply(client, {"source_time_travel_hours": 100}, acknowledged=True).json()["params"]["window"] == "23:45-00:15"
    _at(1, 0, 23)
    assert _apply(client, {"source_time_travel_hours": 100}, acknowledged=True).json()["params"]["window"] == "00:45-03:45"


def test_busy_uses_vietnam_clock_not_utc(client):
    # 23/11 05:00 Vietnam = 22/11 22:00 UTC (not blocked)
    _at(5, 0, 23)
    assert _apply(client, {"source_time_travel_hours": 100}, acknowledged=True).status_code == 200


# ---- BUSY by job
@pytest.mark.parametrize("job_type,status", [("D1_SYNC", "RUNNING"), ("FORECAST_REFRESH", "PENDING"),
                                             ("CANDIDATE_TRAIN", "RETRY_WAIT"), ("TRAIN_PUBLISH", "RUNNING")])
def test_apply_busy_with_active_job(client, job_type, status):
    _job(job_type, status)
    n, stored = _hist_count(), _stored()
    r = _apply(client, {"source_time_travel_hours": 100}, acknowledged=True)
    assert r.status_code == 409 and _code(r) == "DATA_POLICY_BUSY", r.text
    jobs = r.json()["params"]["jobs"]
    assert [(j["job_type"], j["status"]) for j in jobs] == [(job_type, status)]
    assert _hist_count() == n and _stored() == stored and _guarded()["source_time_travel_hours"] == 160


@pytest.mark.parametrize("job_type,status", [("D1_SYNC", "SUCCEEDED"), ("FORECAST_REFRESH", "FAILED"),
                                             ("CANDIDATE_TRAIN", "SKIPPED"), ("D0_SYNC", "RUNNING")])
def test_apply_not_busy_with_finished_or_other_job(client, job_type, status):
    _job(job_type, status)
    r = _apply(client, {"source_time_travel_hours": 100}, acknowledged=True)
    assert r.status_code == 200, r.text


def test_preview_and_get_are_not_blocked_by_busy(client):
    _at(1, 0, 23)
    _job("D1_SYNC", "RUNNING")
    n = _hist_count()
    r = client.post("/api/data-policy/guarded/preview", json={"patch": {"source_time_travel_hours": 100}})
    assert r.status_code == 200 and r.json()["changed"] == ["source_time_travel_hours"]
    assert client.get("/api/data-policy/guarded").status_code == 200
    assert _hist_count() == n


def test_busy_blocks_before_confirmation_writes_no_audit_and_clears_when_job_ends(client):
    _job("D1_SYNC", "RUNNING")
    n_audit = _audit_count("DATA_POLICY_GUARDED_APPLIED")
    r = _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, **_high())
    assert r.status_code == 409 and _code(r) == "DATA_POLICY_BUSY"
    assert _guarded()["history_change_policy"] == "KEEP_OBSERVED_LINES"
    assert _audit_count("DATA_POLICY_GUARDED_APPLIED") == n_audit
    with db.tx() as c:
        c.execute("UPDATE job_runs SET status='SUCCEEDED' WHERE job_type='D1_SYNC'")
    assert _apply(client, {"history_change_policy": "FOLLOW_SOURCE"}, **_high()).status_code == 200


# ---- impact / notes
def test_preview_impact_null_when_history_change_policy_not_changed(client):
    j = client.post("/api/data-policy/guarded/preview", json={"patch": {"source_time_travel_hours": 100}}).json()
    assert j["impact"] is None
    assert j["notes"] == ["UNDO_SETTINGS_ONLY"]
    j = client.post("/api/data-policy/guarded/preview", json={"patch": {"history_change_policy": "KEEP_OBSERVED_LINES"}}).json()
    assert j["changed"] == [] and j["impact"] is None and j["notes"] == ["UNDO_SETTINGS_ONLY"]


def test_preview_impact_structure_and_notes_follow_source(client):
    j = client.post("/api/data-policy/guarded/preview", json={"patch": {"history_change_policy": "FOLLOW_SOURCE"}}).json()
    assert set(j["impact"]) == {"kind", "active_held_lines", "capped", "applies_from"}
    assert j["impact"]["kind"] == "HELD_LINES" and j["impact"]["applies_from"] == "NEXT_D1"
    assert j["impact"]["capped"] is False
    assert j["notes"] == ["APPLIES_AT_NEXT_D1", "FOLLOW_SOURCE_DROPS_REMOVED_LINES", "UNDO_SETTINGS_ONLY"]


def test_preview_notes_keep_observed_lines(client):
    _set(history_change_policy="FOLLOW_SOURCE")
    j = client.post("/api/data-policy/guarded/preview", json={"patch": {"history_change_policy": "KEEP_OBSERVED_LINES"}}).json()
    assert j["impact"]["kind"] == "HELD_LINES"
    assert j["notes"] == ["APPLIES_AT_NEXT_D1", "KEEP_OBSERVED_LINES_HOLDS_REMOVED_LINES", "UNDO_SETTINGS_ONLY"]


def test_preview_impact_mixed_patch_keeps_held_lines_impact(client):
    j = client.post("/api/data-policy/guarded/preview",
                    json={"patch": {"history_change_policy": "FOLLOW_SOURCE", "history_day_check": False}}).json()
    assert j["impact"]["kind"] == "HELD_LINES"
    assert j["notes"][0] == "APPLIES_AT_NEXT_D1" and j["notes"][-1] == "UNDO_SETTINGS_ONLY"
    assert j["needs_confirm_text"] is True and j["needs_acknowledged"] is True


def test_preview_impact_counts_only_active_held_lines_of_the_bigquery_scope(client):
    ss.update("bigquery", {"project_id": "proj-x", "dataset_id": "ds_x", "source_table": "tbl_x"}, note="test")
    scope = "BIGQUERY:proj-x.ds_x.tbl_x"
    _held(scope, "ACTIVE", 3)
    _held(scope, "RELEASED", 2)
    _held("BIGQUERY:other.ds.tbl", "ACTIVE", 4)
    j = client.post("/api/data-policy/guarded/preview", json={"patch": {"history_change_policy": "FOLLOW_SOURCE"}}).json()
    assert j["impact"] == {"kind": "HELD_LINES", "active_held_lines": 3, "capped": False, "applies_from": "NEXT_D1"}


def test_preview_impact_without_bigquery_settings_has_unknown_count(client):
    j = client.post("/api/data-policy/guarded/preview", json={"patch": {"history_change_policy": "FOLLOW_SOURCE"}}).json()
    assert j["impact"]["active_held_lines"] is None and j["impact"]["capped"] is False


def test_preview_other_fields_only_have_no_impact_but_a_warning(client):
    j = client.post("/api/data-policy/guarded/preview", json={"patch": {"history_day_check": False}}).json()
    assert j["impact"] is None
    assert any("history_day_check" in w for w in j["warnings"])


# ---- reset / PUT and training_start_rule
def test_reset_keeps_training_start_rule_and_guarded_fields(client):
    _set(training_start_rule="OPEN_HOURS_COVERAGE", history_change_policy="FOLLOW_SOURCE", history_day_check=False,
         source_time_travel_hours=77, window_start_date="2025-03-01", max_data_lag_days=11)
    kept = _guarded()
    r = client.post("/api/settings/data_policy/reset")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["training_start_rule"] == "OPEN_HOURS_COVERAGE"
    assert {k: out[k] for k in GUARDED} == kept
    assert out["max_data_lag_days"] == 2
    st = _stored()
    assert st["training_start_rule"] == "OPEN_HOURS_COVERAGE" and {k: st[k] for k in GUARDED} == kept


def test_put_can_still_change_training_start_rule(client):
    r = client.put("/api/settings/data_policy", json={**_policy(), "training_start_rule": "OPEN_HOURS_COVERAGE"})
    assert r.status_code == 200, r.text
    assert r.json()["training_start_rule"] == "OPEN_HOURS_COVERAGE"
    assert _policy()["training_start_rule"] == "OPEN_HOURS_COVERAGE"
    r = client.put("/api/settings/data_policy", json={**_policy(), "training_start_rule": "WINDOW_START"})
    assert r.json()["training_start_rule"] == "WINDOW_START"
