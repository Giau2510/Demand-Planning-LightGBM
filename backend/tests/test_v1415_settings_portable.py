"""1.4.15 (lot 2B): settings export / import (app/settings_portable.py, /api/settings-export, /api/settings-import/*,
`app.cli settings-export` / `settings-import`).

Integration with fakes (TestClient and the CLI on isolated temporary databases, no real data, no network).
Covers: export whitelist (no excluded key, nothing that looks like a secret / token / path), round trip export -> import
on a SECOND temporary database gives identical sections, whole-file refusals (format, newer version, sha256, unknown /
excluded key, wrong type, read-only differing, window_start_date), apply in one transaction (expected hash, typed text,
reason, busy, retention decrease), audit SETTINGS_IMPORTED, undo (match / moved), CLI dry run writes nothing.
"""
import copy
import json
import re
from datetime import datetime

import pytest

from app import cli, db
from app import settings_portable as sp
from app import settings_registry as reg
from app import settings_service as ss
from app import timeutil
from app.messages import CATALOG
from app.timeutil import VN_TZ

TODAY = "2026-11-22"
CONFIRM = f"NHAP-CAI-DAT-{TODAY}"
PURCHASE = f"DOI-CAI-DAT-ANH-HUONG-MUA-HANG-{TODAY}"
HIGH = f"DOI-CAI-DAT-AN-{TODAY}"
REASON = "chu du an nhap cai dat may moi"
NEVER = ("project_id", "dataset_id", "location", "source_table", "service_account_file", "auth_method",
         "field_mapping", "reference_mapping", "oauth_enabled", "oauth_client_id", "production_enabled",
         "schema_snapshot", "trial_mode", "feature_table", "d0_paused_until", "d0_paused_by", "d0_pause_windows",
         "d1_enabled", "d0_enabled", "train_enabled", "refresh_enabled", "report_enabled", "eod_enabled",
         "close_enabled", "d1_enabled_at", "report_enabled_at", "partition_column", "customer_id_column")


@pytest.fixture(autouse=True)
def _frozen_day():
    timeutil.set_now_override(lambda: datetime(2026, 11, 22, 12, 0, tzinfo=VN_TZ))
    yield


def _export() -> dict:
    with db.read() as c:
        return sp.export_doc(c)


def _resign(doc: dict) -> dict:
    doc["sha256"] = sp.sha256(doc["sections"])
    return doc


def _counts() -> tuple:
    with db.read() as c:
        return (c.execute("SELECT COUNT(*) FROM settings_history").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0],
                tuple(c.execute("SELECT section, value_json FROM app_settings ORDER BY section").fetchall()))


def _preview(client, doc):
    return client.post("/api/settings-import/preview", json={"document": doc})


def _apply(client, doc, sections, expected=None, **kw):
    if expected is None:
        pv = _preview(client, doc).json()
        expected = {p["section"]: p["expected"] for p in pv["sections"]}
    body = {"document": doc, "sections": sections, "expected": expected, "confirm_text": CONFIRM, "reason": REASON,
            "confirm_purchase": PURCHASE, "confirm_high": HIGH}
    body.update(kw)
    return client.post("/api/settings-import/apply", json=body)


def _code(r):
    return r.json()["code"]


def _changed_doc(**sections) -> dict:
    doc = _export()
    for s, patch in sections.items():
        doc["sections"][s].update(patch)
    return _resign(doc)


# ------------------------------------------------------------------ export
def test_export_format_and_whitelist(client):
    r = client.get("/api/settings-export")
    assert r.status_code == 200
    assert re.match(r'attachment; filename="cai_dat_\d{8}_\d{4}\.json"', r.headers["content-disposition"])
    doc = r.json()
    assert doc["format"] == "df-settings" and doc["format_version"] == 1 and doc["app_version"]
    assert doc["schema_version"] >= 13 and doc["sha256"] == sp.sha256(doc["sections"])
    assert set(doc["sections"]) == set(sp.EXPORT_SECTIONS)
    for s, keys in doc["sections"].items():
        for k in keys:
            assert k not in NEVER, (s, k)
            assert (s, k) not in reg.EXCLUDED
    assert {"general.*", "sql_sources.*", "feature_table.*", "bigquery.project_id", "bigquery.oauth_client_id",
            "daily_forecast.trial_mode", "schedule.d1_enabled"} <= set(doc["excluded"])
    assert set(doc["sections"]["data_policy"]) == set(ss.DataPolicySettings.model_fields)


def test_export_contains_nothing_that_looks_like_a_secret(client):
    ss.update("bigquery", {"oauth_client_id": "123-abc.apps.googleusercontent.com", "service_account_file":
                           "C:\\keys\\bq.json", "dataset_id": "ds_private", "project_id": "my-project-123"}, note="setup")
    text = client.get("/api/settings-export").text
    for needle in ("googleusercontent", "C:\\\\keys", "bq.json", "ds_private", "my-project-123", "client_secret",
                   "refresh_token", "access_token", "private_key", "password"):
        assert needle not in text, needle
    assert not re.search(r"ya29\.|1//0[A-Za-z0-9_-]{20,}|-----BEGIN", text)


def test_export_is_read_only(client):
    before = _counts()
    assert client.get("/api/settings-export").status_code == 200
    assert _counts() == before


# ------------------------------------------------------------------ round trip on a second database
def test_round_trip_to_a_second_database_is_identical(client, tmp_path, monkeypatch):
    for s, patch in {"model": {"num_threads": 4, "num_boost_round": 120},
                     "sel2_pipeline": {"retention_days": 200, "tsb_alpha": 0.2},
                     "bigquery": {"max_retries": 4, "maximum_bytes_billed": 11 * 1024 ** 2},
                     "schedule": {"report_time": "08:00", "slot_grace_minutes": 30},
                     "data_policy": {"history_change_policy": "FOLLOW_SOURCE", "max_data_lag_days": 5},
                     "import": {"column_aliases": {"sku_id": ["ma_sku"]}}}.items():
        ss.update(s, patch, note="setup")
    doc = json.loads(client.get("/api/settings-export").text)
    monkeypatch.setenv("DF_DATA_DIR", str(tmp_path / "second"))
    db.migrate()
    ss.update("sel2_pipeline", {"enabled": False}, note="tests: 1.3.1 mode")      # same as the first DB (conftest)
    with db.read() as c:
        pv = sp.preview(c, doc)
    sections = [p["section"] for p in pv["sections"] if p["changed"]]
    expected = {p["section"]: p["expected"] for p in pv["sections"]}
    with db.tx() as c:
        res = sp.apply(c, doc, sections, expected, CONFIRM, REASON, PURCHASE, HIGH)
    assert res["import_id"].startswith("IMP-")
    again = _export()
    assert again["sections"] == doc["sections"] and again["sha256"] == doc["sha256"]


# ------------------------------------------------------------------ whole-file refusals
@pytest.mark.parametrize("mutate,code", [
    (lambda d: d.update(format="other"), "SETTINGS_IMPORT_INVALID_FILE"),
    (lambda d: d.update(format_version=2), "SETTINGS_IMPORT_VERSION_NEWER"),
    (lambda d: d["sections"]["model"].update(num_threads=4), "SETTINGS_IMPORT_HASH_MISMATCH"),
])
def test_file_level_refusals(client, mutate, code):
    doc = _export()
    mutate(doc)
    before = _counts()
    r = _preview(client, doc)
    assert r.status_code == 422 and _code(r) == code, r.text
    assert r.json()["vi"] != r.json()["en"]
    assert _apply(client, doc, ["model"], expected={"model": "x"}).status_code == 422
    assert _counts() == before


@pytest.mark.parametrize("section,key,value,code", [
    ("bigquery", "project_id", "other-project-1", "SETTINGS_IMPORT_EXCLUDED_KEY"),
    ("bigquery", "oauth_client_id", "", "SETTINGS_IMPORT_EXCLUDED_KEY"),
    ("schedule", "d1_enabled", True, "SETTINGS_IMPORT_EXCLUDED_KEY"),
    ("daily_forecast", "trial_mode", False, "SETTINGS_IMPORT_EXCLUDED_KEY"),
    ("model", "feature_table", None, "SETTINGS_IMPORT_EXCLUDED_KEY"),
    ("general", "active_source", "DEMO", "SETTINGS_IMPORT_EXCLUDED_KEY"),
    ("model", "no_such_key", 1, "SETTINGS_IMPORT_UNKNOWN_KEY"),
    ("no_such_section", "x", 1, "SETTINGS_IMPORT_UNKNOWN_KEY"),
    ("model", "num_threads", "4", "SETTINGS_IMPORT_INVALID_VALUE"),
    ("model", "num_threads", 999, "SETTINGS_IMPORT_INVALID_VALUE"),
    ("daily_forecast", "rounding_threshold", 0.3, "SETTINGS_IMPORT_READONLY_DIFFERS"),
    ("data_policy", "window_start_date", "2025-01-01", "SETTINGS_IMPORT_WINDOW_START_DIFFERS")])
def test_key_level_refusals_reject_the_whole_file(client, section, key, value, code):
    doc = _export()
    doc["sections"]["bigquery"]["max_retries"] = 4          # a valid change elsewhere is refused with the file
    doc["sections"].setdefault(section, {})[key] = value
    _resign(doc)
    before = _counts()
    r = _preview(client, doc)
    if code == "SETTINGS_IMPORT_INVALID_VALUE" and r.status_code == 200:
        # an out-of-range value makes its section invalid (not selectable) instead of a type error
        p = next(x for x in r.json()["sections"] if x["section"] == section)
        assert p["errors"] and not p["selectable"]
        r = _apply(client, doc, [section])
        assert r.status_code == 422 and _code(r) == "SETTINGS_IMPORT_SECTION_INVALID"
    else:
        assert r.status_code == 422 and _code(r) == code, r.text
    assert _counts() == before and ss.get("bigquery").max_retries == 2


def test_readonly_equal_value_is_accepted(client):
    doc = _changed_doc(bigquery={"max_retries": 4})
    assert "rounding_threshold" in doc["sections"]["daily_forecast"]
    assert _preview(client, doc).status_code == 200


# ------------------------------------------------------------------ preview
def test_preview_writes_nothing_and_marks_risky_sections(client):
    doc = _changed_doc(bigquery={"max_retries": 4}, model={"num_threads": 4})
    before = _counts()
    j = _preview(client, doc).json()
    assert _counts() == before
    by = {p["section"]: p for p in j["sections"]}
    assert by["bigquery"]["changed"] == ["max_retries"] and by["bigquery"]["default_selected"] is True
    assert by["model"]["max_risk"] == "PURCHASE" and by["model"]["default_selected"] is False
    assert by["quality"]["changed"] == [] and by["quality"]["selectable"] is False
    assert j["confirm_text"] == CONFIRM and j["warnings"] == []


def test_preview_warns_on_other_versions(client):
    doc = _export()
    doc["app_version"], doc["schema_version"] = "1.4.14", 12
    j = _preview(client, doc).json()
    assert {"SETTINGS_IMPORT_APP_VERSION_DIFFERS", "SETTINGS_IMPORT_SCHEMA_VERSION_DIFFERS", "NO_CHANGE"} <= set(j["warnings"])


# ------------------------------------------------------------------ apply
def test_apply_needs_text_and_reason(client):
    doc = _changed_doc(bigquery={"max_retries": 4})
    before = _counts()
    for kw in ({"confirm_text": "NHAP-CAI-DAT-2026-11-21"}, {"reason": "short"}, {"confirm_text": None}):
        r = _apply(client, doc, ["bigquery"], **kw)
        assert r.status_code == 409 and _code(r) == "SETTINGS_IMPORT_CONFIRM_REQUIRED", kw
    assert _counts() == before


def test_apply_all_or_nothing_and_audit(client):
    doc = _changed_doc(bigquery={"max_retries": 4}, model={"num_threads": 4},
                       data_policy={"history_change_policy": "FOLLOW_SOURCE"})
    with db.read() as c:
        hb = c.execute("SELECT MAX(id) FROM settings_history WHERE section='bigquery'").fetchone()[0] or 0
    r = _apply(client, doc, ["bigquery", "model", "data_policy"])
    assert r.status_code == 200, r.text
    assert ss.get("bigquery").max_retries == 4 and ss.get("model").num_threads == 4
    assert ss.get("data_policy").history_change_policy == "FOLLOW_SOURCE"      # guarded field imported here
    with db.read() as c:
        d = json.loads(c.execute("SELECT details_json FROM audit_log WHERE action='SETTINGS_IMPORTED'").fetchone()[0])
        note = c.execute("SELECT note FROM settings_history WHERE section='model' ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert d["import_id"] == r.json()["import_id"] and d["sha256"] == doc["sha256"]
    bq = next(e for e in d["entries"] if e["section"] == "bigquery")
    assert bq["history_id_before"] == hb and bq["keys"] == {"max_retries": {"from": 2, "to": 4}}
    assert f"nhap tu tep {doc['sha256'][:12]}" in note and REASON in note


def test_apply_unselected_section_is_not_written(client):
    doc = _changed_doc(bigquery={"max_retries": 4}, model={"num_threads": 4})
    assert _apply(client, doc, ["bigquery"]).status_code == 200
    assert ss.get("model").num_threads == 0 and ss.get("bigquery").max_retries == 4


def test_apply_expected_hash_mismatch_409(client):
    doc = _changed_doc(bigquery={"max_retries": 4})
    pv = _preview(client, doc).json()
    expected = {p["section"]: p["expected"] for p in pv["sections"]}
    ss.update("bigquery", {"preview_rows": 60}, note="elsewhere")
    before = _counts()
    r = _apply(client, doc, ["bigquery"], expected=expected)
    assert r.status_code == 409 and _code(r) == "SETTINGS_CHANGED_ELSEWHERE"
    assert _counts() == before


def test_apply_one_bad_section_writes_nothing(client):
    doc = _changed_doc(bigquery={"max_retries": 4}, sel2_pipeline={"retention_days": 60})      # decrease 120 -> 60
    before = _counts()
    r = _apply(client, doc, ["bigquery", "sel2_pipeline"])
    assert r.status_code == 422 and _code(r) == "SETTINGS_IMPORT_SECTION_INVALID"
    assert "RETENTION_DECREASE_NOT_ALLOWED" in r.json()["detail"]
    assert _counts() == before and ss.get("bigquery").max_retries == 2


def test_apply_cross_validation_of_the_whole_section(client):
    doc = _changed_doc(sel2_pipeline={"min_days": 40})        # > window_days 28
    p = next(x for x in _preview(client, doc).json()["sections"] if x["section"] == "sel2_pipeline")
    assert p["errors"] and not p["selectable"]


def test_apply_no_section_and_no_change(client):
    doc = _changed_doc(bigquery={"max_retries": 4})
    assert _code(_apply(client, doc, [])) == "SETTINGS_IMPORT_NO_SECTION"
    assert _code(_apply(client, doc, ["quality"])) == "NO_CHANGE"


@pytest.mark.parametrize("h,m,day", [(23, 50, 22), (1, 0, 23)])
def test_apply_busy_in_production_window(client, h, m, day):
    doc = _changed_doc(bigquery={"max_retries": 4})
    pv = _preview(client, doc).json()
    timeutil.set_now_override(lambda: datetime(2026, 11, day, h, m, tzinfo=VN_TZ))
    r = _apply(client, doc, ["bigquery"], expected={p["section"]: p["expected"] for p in pv["sections"]})
    assert r.status_code == 409 and _code(r) == "SETTINGS_ADVANCED_BUSY"
    assert ss.get("bigquery").max_retries == 2


def test_apply_busy_with_active_job(client):
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) VALUES (?,?,?,?,?,?)",
                  ("J-1", "SPIKE_LINES", "idem-1", "SCHEDULE", "RUNNING", "2026-11-22T04:00:00+00:00"))
    r = _apply(client, _changed_doc(bigquery={"max_retries": 4}), ["bigquery"])
    assert r.status_code == 409 and _code(r) == "SETTINGS_ADVANCED_BUSY"


# ------------------------------------------------------------------ undo
def test_undo_restores_and_is_audited(client):
    doc = _changed_doc(bigquery={"max_retries": 4}, model={"num_threads": 4})
    iid = _apply(client, doc, ["bigquery", "model"]).json()["import_id"]
    r = client.post("/api/settings-import/undo", json={"import_id": iid, "confirm_text": CONFIRM, "reason": "x",
                                                            "confirm_purchase": PURCHASE})
    assert r.status_code == 409 and _code(r) == "SETTINGS_IMPORT_CONFIRM_REQUIRED"
    r = client.post("/api/settings-import/undo", json={"import_id": iid, "confirm_text": CONFIRM, "reason": REASON,
                                                                "confirm_purchase": PURCHASE})
    assert r.status_code == 200, r.text
    assert ss.get("bigquery").max_retries == 2 and ss.get("model").num_threads == 0
    again = client.post("/api/settings-import/undo", json={"import_id": iid, "confirm_text": CONFIRM, "reason": REASON,
                                                                "confirm_purchase": PURCHASE})
    assert again.status_code == 409 and _code(again) == "SETTINGS_ADVANCED_ALREADY_UNDONE"
    h = client.get("/api/settings-import/history").json()
    assert [x["action"] for x in h] == ["SETTINGS_IMPORT_UNDONE", "SETTINGS_IMPORTED"] and h[1]["undone"] is True
    assert client.post("/api/settings-import/undo", json={"import_id": "IMP-none", "confirm_text": CONFIRM,
                                                          "reason": REASON}).status_code == 404


def test_undo_refused_when_a_value_moved(client):
    iid = _apply(client, _changed_doc(bigquery={"max_retries": 4}, model={"num_threads": 4}),
                 ["bigquery", "model"]).json()["import_id"]
    ss.update("model", {"num_threads": 6}, note="elsewhere")
    before = _counts()
    r = client.post("/api/settings-import/undo", json={"import_id": iid, "confirm_text": CONFIRM, "reason": REASON,
                                                                "confirm_purchase": PURCHASE})
    assert r.status_code == 409 and _code(r) == "SETTINGS_CHANGED_ELSEWHERE" and r.json()["params"]["keys"] == [
        "model.num_threads"]
    assert _counts() == before and ss.get("bigquery").max_retries == 4


def test_undo_skips_a_retention_the_import_raised_and_undoes_the_rest(client):
    iid = _apply(client, _changed_doc(sel2_pipeline={"retention_days": 200, "tsb_alpha": 0.2}),
                 ["sel2_pipeline"]).json()["import_id"]
    r = client.post("/api/settings-import/undo", json={"import_id": iid, "confirm_text": CONFIRM, "reason": REASON,
                                                       "confirm_purchase": PURCHASE})
    assert r.status_code == 200, r.text
    assert r.json()["skipped"] == [{"section": "sel2_pipeline", "key": "retention_days",
                                    "reason": "UNDO_SKIPPED_RETENTION_DECREASE", "value": 200}]
    s = ss.get("sel2_pipeline")
    assert s.retention_days == 200 and s.tsb_alpha == 0.1
    with db.read() as c:
        d = json.loads(c.execute("SELECT details_json FROM audit_log WHERE action='SETTINGS_IMPORT_UNDONE'").fetchone()[0])
    assert d["skipped"][0]["key"] == "retention_days"
    assert d["entries"][0]["keys"] == {"tsb_alpha": {"from": 0.2, "to": 0.1}}
    vi, en = CATALOG["UNDO_SKIPPED_RETENTION_DECREASE"]
    assert vi and en and vi != en


def test_undo_with_only_a_raised_retention_changes_nothing_but_is_recorded(client):
    iid = _apply(client, _changed_doc(sel2_pipeline={"retention_days": 200}), ["sel2_pipeline"]).json()["import_id"]
    n = _counts()[0]
    r = client.post("/api/settings-import/undo", json={"import_id": iid, "confirm_text": CONFIRM, "reason": REASON})
    assert r.status_code == 200 and r.json()["entries"] == [] and len(r.json()["skipped"]) == 1
    assert _counts()[0] == n and ss.get("sel2_pipeline").retention_days == 200


# ------------------------------------------------------------------ CLI
def test_cli_export_then_dry_run_import_writes_nothing(tmp_path, capsys):
    out = tmp_path / "out"
    out.mkdir()
    assert cli.main(["settings-export", "--out", str(out)]) == 0
    res = json.loads(capsys.readouterr().out)
    f = res["file"]
    assert re.search(r"cai_dat_\d{8}_\d{4}\.json$", f)
    doc = json.loads(open(f, encoding="utf-8").read())
    doc["sections"]["bigquery"]["max_retries"] = 4
    _resign(doc)
    g = tmp_path / "out" / "changed.json"
    g.write_text(json.dumps(doc), encoding="utf-8")
    before = _counts()
    assert cli.main(["settings-import", "--file", str(g)]) == 0
    pv = json.loads(capsys.readouterr().out)
    assert pv["dry_run"] is True and pv["selected"] == ["bigquery"]
    assert _counts() == before
    assert cli.main(["settings-import", "--file", str(g), "--apply", "--confirm", CONFIRM, "--reason", "x"]) == 1
    assert _counts() == before
    assert cli.main(["settings-import", "--file", str(g), "--apply", "--confirm", CONFIRM, "--reason", REASON]) == 0
    assert ss.get("bigquery").max_retries == 4


def test_cli_export_refuses_the_data_folder(data_dir, capsys):
    assert cli.main(["settings-export", "--out", str(data_dir / "x.json")]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "SETTINGS_EXPORT_PATH_REFUSED"
    assert not (data_dir / "x.json").exists()


def test_new_codes_have_both_languages():
    for code in [k for k in CATALOG if k.startswith("SETTINGS_IMPORT_")] + ["SETTINGS_EXPORT_PATH_REFUSED"]:
        vi, en = CATALOG[code]
        assert vi and en and vi != en, code


def test_excluded_list_covers_every_non_exported_field():
    doc = _export()
    listed = set(doc["excluded"])
    for s in sp.EXPORT_SECTIONS:
        for k in ss.SECTIONS[s].model_fields:
            assert (k in doc["sections"][s]) != (f"{s}.{k}" in listed), (s, k)
    assert copy.deepcopy(doc)["sha256"] == sp.sha256(doc["sections"])


# ------------------------------------------------------------------ review L2-REV fixes
def test_purchase_key_needs_the_purchase_text(client):
    doc = _changed_doc(model={"num_threads": 4}, bigquery={"max_retries": 4})
    pv = _preview(client, doc).json()
    assert pv["needs_purchase_confirm"] is True and pv["purchase_keys"] == ["model.num_threads"]
    assert pv["confirm_purchase"] == PURCHASE
    before = _counts()
    for bad in (None, f"DOI-CAI-DAT-AN-{TODAY}", "DOI-CAI-DAT-ANH-HUONG-MUA-HANG-2026-11-21"):
        r = _apply(client, doc, ["model", "bigquery"], confirm_purchase=bad)
        assert r.status_code == 409 and _code(r) == "SETTINGS_IMPORT_PURCHASE_CONFIRM_REQUIRED", bad
        assert r.json()["vi"] != r.json()["en"]
    assert _counts() == before
    assert _apply(client, doc, ["bigquery"], confirm_purchase=None).status_code == 200      # no PURCHASE key selected
    assert ss.get("model").num_threads == 0


def test_visible_keys_risk_and_not_selected_by_default(client):
    doc = _changed_doc(model={"num_boost_round": 120}, quality={"wape_max": 0.5}, schedule={"train_time": "07:30"},
                       bigquery={"maximum_bytes_billed": 11 * 1024 ** 2}, horizons={"max_allowed_days": 400},
                       data_policy={"training_start_rule": "OPEN_HOURS_COVERAGE", "max_data_lag_days": 5},
                       daily_forecast={"report_subdir": "bao-cao"})
    by = {p["section"]: p for p in _preview(client, doc).json()["sections"]}
    assert by["model"]["max_risk"] == "PURCHASE" and by["model"]["purchase_keys"] == ["model.num_boost_round"]
    assert by["horizons"]["max_risk"] == "PURCHASE"
    assert by["data_policy"]["max_risk"] == "PURCHASE" and by["data_policy"]["purchase_keys"] == [
        "data_policy.training_start_rule"]
    for s in ("quality", "schedule", "bigquery"):
        assert by[s]["max_risk"] == "HIGH", s
    for s in ("model", "horizons", "data_policy", "quality", "schedule", "bigquery"):
        assert by[s]["default_selected"] is False, s
    assert by["daily_forecast"]["max_risk"] == "LOW" and by["daily_forecast"]["default_selected"] is True


def test_undo_refused_when_a_key_is_no_longer_importable(client, monkeypatch):
    iid = _apply(client, _changed_doc(sel2_pipeline={"spike_e4_n": 6}), ["sel2_pipeline"]).json()["import_id"]
    kind = sp._kind
    monkeypatch.setattr(sp, "_kind", lambda s, k: "READONLY" if k == "spike_e4_n" else kind(s, k))  # made read-only since
    before = _counts()
    r = client.post("/api/settings-import/undo", json={"import_id": iid, "confirm_text": CONFIRM, "reason": REASON,
                                                       "confirm_purchase": PURCHASE})
    assert r.status_code == 422 and _code(r) == "SETTINGS_ADVANCED_NOT_EDITABLE"
    assert _counts() == before and ss.get("sel2_pipeline").spike_e4_n == 6


def test_undo_of_a_purchase_key_needs_the_purchase_text(client):
    iid = _apply(client, _changed_doc(model={"num_threads": 4}), ["model"]).json()["import_id"]
    r = client.post("/api/settings-import/undo", json={"import_id": iid, "confirm_text": CONFIRM, "reason": REASON})
    assert r.status_code == 409 and _code(r) == "SETTINGS_IMPORT_PURCHASE_CONFIRM_REQUIRED"
    assert ss.get("model").num_threads == 4


def test_body_too_large_413(client):
    doc = _export()
    doc["padding"] = "x" * (2 * 1024 * 1024 + 10)
    before = _counts()
    for url in ("/api/settings-import/preview", "/api/settings-import/apply"):
        r = client.post(url, json={"document": doc, "sections": ["bigquery"], "expected": {}})
        assert r.status_code == 413 and _code(r) == "SETTINGS_IMPORT_TOO_LARGE", url
    assert _counts() == before


def test_cli_without_sections_imports_only_low_sections(tmp_path, capsys):
    doc = _changed_doc(model={"num_boost_round": 120}, bigquery={"max_retries": 4})
    f = tmp_path / "f.json"
    f.write_text(json.dumps(doc), encoding="utf-8")
    assert cli.main(["settings-import", "--file", str(f), "--apply", "--confirm", CONFIRM, "--reason", REASON]) == 0
    capsys.readouterr()
    assert ss.get("bigquery").max_retries == 4 and ss.get("model").num_boost_round == 300
    doc2 = _changed_doc(model={"num_threads": 4})
    g = tmp_path / "g.json"
    g.write_text(json.dumps(doc2), encoding="utf-8")
    args = ["settings-import", "--file", str(g), "--sections", "model", "--apply", "--confirm", CONFIRM, "--reason",
            REASON]
    assert cli.main(args) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "SETTINGS_IMPORT_PURCHASE_CONFIRM_REQUIRED"
    assert cli.main(args + ["--confirm-purchase", PURCHASE]) == 0
    assert ss.get("model").num_threads == 4


def test_cli_export_refuses_the_reports_folder(data_dir, capsys):
    from app import paths
    target = paths.reports_dir() / "x.json"
    assert cli.main(["settings-export", "--out", str(target)]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "SETTINGS_EXPORT_PATH_REFUSED"
    assert not target.exists()


# ------------------------------------------------------------------ data-reviewer L2-DREV fixes
def test_spike_keys_are_exported(client):
    ss.update("sel2_pipeline", {"spike_cleaning": True, "spike_e4_n": 5}, note="setup")
    doc = _export()
    assert doc["sections"]["sel2_pipeline"]["spike_cleaning"] is True
    assert doc["sections"]["sel2_pipeline"]["spike_e4_n"] == 5
    assert "sel2_pipeline.spike_e4_n" not in doc["excluded"]


def test_spike_keys_import_and_undo_at_purchase_level(client):
    doc = _changed_doc(sel2_pipeline={"spike_cleaning": True, "spike_e4_n": 5})
    pv = _preview(client, doc).json()
    assert sorted(pv["purchase_keys"]) == ["sel2_pipeline.spike_cleaning", "sel2_pipeline.spike_e4_n"]
    p = next(x for x in pv["sections"] if x["section"] == "sel2_pipeline")
    assert p["default_selected"] is False and "SPIKE_NOT_TRANSFERRED" not in pv["warnings"]
    before = _counts()
    r = _apply(client, doc, ["sel2_pipeline"], confirm_purchase=None)
    assert r.status_code == 409 and _code(r) == "SETTINGS_IMPORT_PURCHASE_CONFIRM_REQUIRED"
    assert _counts() == before
    iid = _apply(client, doc, ["sel2_pipeline"]).json()["import_id"]
    s = ss.get("sel2_pipeline")
    assert s.spike_cleaning is True and s.spike_e4_n == 5
    u = client.post("/api/settings-import/undo", json={"import_id": iid, "confirm_text": CONFIRM, "reason": REASON,
                                                       "confirm_purchase": PURCHASE})
    assert u.status_code == 200, u.text
    s = ss.get("sel2_pipeline")
    assert s.spike_cleaning is False and s.spike_e4_n == 4


def test_cli_apply_warns_and_respects_the_ops_lock(tmp_path, capsys, monkeypatch):
    doc = _changed_doc(bigquery={"max_retries": 4})
    f = tmp_path / "f.json"
    f.write_text(json.dumps(doc), encoding="utf-8")
    lock = tmp_path / "OPS_LOCK"
    lock.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DF_OPS_LOCK", str(lock))
    args = ["settings-import", "--file", str(f), "--apply", "--confirm", CONFIRM, "--reason", REASON]
    before = _counts()
    assert cli.main(args) == 2
    out = capsys.readouterr()
    assert json.loads(out.out)["code"] == "SETTINGS_IMPORT_OPS_LOCKED" and "only the project owner" in out.err
    assert _counts() == before
    vi, en = CATALOG["SETTINGS_IMPORT_OPS_LOCKED"]
    assert vi != en
    monkeypatch.setenv("DF_OPS_LOCK", str(tmp_path / "no-such-lock"))
    assert cli.main(args) == 0
    assert "only the project owner" in json.loads(capsys.readouterr().out)["warning"]
    assert ss.get("bigquery").max_retries == 4


# ------------------------------------------------------------------ co-van-opus CV-L23
def test_high_key_needs_the_high_text(client):
    doc = _changed_doc(schedule={"slot_grace_minutes": 30}, bigquery={"max_retries": 4})
    pv = _preview(client, doc).json()
    assert pv["needs_high_confirm"] is True and pv["high_keys"] == ["schedule.slot_grace_minutes"]
    assert pv["confirm_high"] == HIGH and pv["needs_purchase_confirm"] is False
    before = _counts()
    for bad in (None, PURCHASE, "DOI-CAI-DAT-AN-2026-11-21"):
        r = _apply(client, doc, ["schedule", "bigquery"], confirm_high=bad)
        assert r.status_code == 409 and _code(r) == "SETTINGS_IMPORT_HIGH_CONFIRM_REQUIRED", bad
        assert r.json()["vi"] != r.json()["en"]
    assert _counts() == before
    assert _apply(client, doc, ["schedule", "bigquery"]).status_code == 200
    assert ss.get("schedule").slot_grace_minutes == 30


def test_purchase_only_import_does_not_need_the_high_text(client):
    doc = _changed_doc(model={"num_threads": 4})
    r = _apply(client, doc, ["model"], confirm_high=None)
    assert r.status_code == 200, r.text


def test_undo_of_a_high_key_needs_the_high_text(client):
    iid = _apply(client, _changed_doc(schedule={"slot_grace_minutes": 30}), ["schedule"]).json()["import_id"]
    r = client.post("/api/settings-import/undo", json={"import_id": iid, "confirm_text": CONFIRM, "reason": REASON})
    assert r.status_code == 409 and _code(r) == "SETTINGS_IMPORT_HIGH_CONFIRM_REQUIRED"
    r = client.post("/api/settings-import/undo", json={"import_id": iid, "confirm_text": CONFIRM, "reason": REASON,
                                                       "confirm_high": HIGH})
    assert r.status_code == 200 and ss.get("schedule").slot_grace_minutes == 20


def test_preview_warns_only_for_an_older_file_without_spike_keys(client):
    ss.update("sel2_pipeline", {"spike_cleaning": True, "spike_e4_n": 5}, note="setup")
    assert "SPIKE_NOT_TRANSFERRED" not in _preview(client, _export()).json()["warnings"]
    doc = _export()
    for k in ("spike_cleaning", "spike_e4_n"):
        doc["sections"]["sel2_pipeline"].pop(k)
    j = _preview(client, _resign(doc)).json()
    assert "SPIKE_NOT_TRANSFERRED" in j["warnings"]
    assert j["spike_current"] == {"spike_cleaning": True, "spike_e4_n": 5}
    vi, en = CATALOG["SPIKE_NOT_TRANSFERRED"]
    assert vi and en and vi != en


def test_cli_apply_refuses_under_the_heavy_lock(tmp_path, capsys, monkeypatch):
    f = tmp_path / "f.json"
    f.write_text(json.dumps(_changed_doc(bigquery={"max_retries": 4})), encoding="utf-8")
    lock = tmp_path / "HEAVY_LOCK"
    lock.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("DF_OPS_LOCK", raising=False)
    monkeypatch.setenv("DF_HEAVY_LOCK", str(lock))
    before = _counts()
    args = ["settings-import", "--file", str(f), "--apply", "--confirm", CONFIRM, "--reason", REASON]
    assert cli.main(args) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "SETTINGS_IMPORT_HEAVY_LOCKED"
    assert _counts() == before and ss.get("bigquery").max_retries == 2
    lock.unlink()
    assert cli.main(args) == 0 and ss.get("bigquery").max_retries == 4
