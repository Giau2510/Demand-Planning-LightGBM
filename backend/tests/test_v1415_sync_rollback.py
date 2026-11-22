"""1.4.15 lot 5: undo of one history-sync run from the UI (api/sync_rollback_routes.py around history_sync.rollback).

Integration with fakes: TestClient on the isolated temporary database (conftest), synthetic demand rows and held lines,
runs made by the real release_holds (HOLD_RELEASE) and undone by the real rollback / backup_database on that temporary
database, or a fake rollback where a test needs to block the background thread. No real data, no BigQuery.
Covers: list + rollbackable (later write, kind, already rolled back); the preview writes nothing; a run changed by a
later write is refused; confirmation text; signature; busy / window / schedule time / disk / lock; a gate failing after
the backup writes nothing; two clicks; the release -> rollback loop through both APIs; the CLI path unchanged.
"""
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from app import db, paths, timeutil
from app import settings_service as ss
from app.api import background
from app.api import held_lines_routes as hl
from app.api import sync_rollback_routes as sr
from app.data import history_sync
from app.messages import CATALOG
from app.timeutil import VN_TZ

SCOPE = "BIGQUERY:proj-x.ds_x.tbl_x"
TODAY = "2026-11-22"
CONFIRM = f"QUAY-LAI-DONG-BO-{TODAY}"
REASON = "chu du an duyet quay lai lan dong bo"
D1, D2 = "2026-11-10", "2026-11-12"


@pytest.fixture(autouse=True)
def _frozen_day():
    timeutil.set_now_override(lambda: datetime(2026, 11, 22, 15, 0, tzinfo=VN_TZ))   # no default schedule time near
    yield


@pytest.fixture
def bq(client, monkeypatch):
    ss.update("bigquery", {"project_id": "proj-x", "dataset_id": "ds_x", "source_table": "tbl_x"}, note="test")
    monkeypatch.setattr(hl, "_free_bytes", lambda p: 10 ** 15)
    for k in (*hl.LOCK_ENV, hl.RUN_DIR_ENV):
        monkeypatch.delenv(k, raising=False)
    return SCOPE


_SEQ = [0]


def _row(d, sku, qty, fc="F1", n_orders=1):
    with db.tx() as c:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
                  "VALUES (?, 'BIGQUERY', ?,?,?,?,?, '2026-11-13T00:00:00+00:00')", (SCOPE, d, sku, fc, qty, n_orders))


def _hold(d, sku, qty, fc="F1", cause="ORDER_GONE"):
    _SEQ[0] += 1
    with db.tx() as c:
        c.execute("INSERT INTO demand_held_lines(id, scope_key, order_date, sku_id, fc_id, qty, cause, status, "
                  "detected_run, detected_at) VALUES (?,?,?,?,?,?,?, 'ACTIVE', 'D1L-T', '2026-11-13T00:00:00+00:00')",
                  (f"H{_SEQ[0]:07d}", SCOPE, d, sku, fc, qty, cause))


def _release(sku, cause=None) -> str:
    return history_sync.release_holds(SCOPE, cause=cause, sku_id=sku, apply=True)["run_id"]


def _values() -> dict:
    with db.read() as c:
        return {(r[0], r[1], r[2]): r[3] for r in c.execute(
            "SELECT order_date, sku_id, fc_id, qty FROM demand_daily WHERE scope_key=?", (SCOPE,))}


def _count(sql, p=()) -> int:
    with db.read() as c:
        return c.execute(sql, p).fetchone()[0]


def _backups() -> list[str]:
    return sorted(x.name for x in paths.backups_dir().iterdir())


def _snapshot() -> dict:
    with db.read() as c:
        runs = [tuple(r) for r in c.execute("SELECT id, status FROM demand_sync_runs ORDER BY id")]
    return {"daily": _values(), "held": _count("SELECT COUNT(*) FROM demand_held_lines WHERE status='ACTIVE'"),
            "runs": runs, "log": _count("SELECT COUNT(*) FROM demand_change_log"),
            "audit": _count("SELECT COUNT(*) FROM audit_log"), "state": _count("SELECT COUNT(*) FROM sync_state"),
            "backups": _backups()}


def _job(job_type, status):
    _SEQ[0] += 1
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) VALUES (?,?,?,?,?,?)",
                  (f"J-{_SEQ[0]}", job_type, f"idem-{_SEQ[0]}", "MANUAL", status, "2026-11-22T07:30:00+00:00"))


def _code(r):
    return r.json()["code"]


def _preview(client, run_id):
    r = client.post("/api/sync-rollback/preview", json={"sync_run_id": run_id})
    assert r.status_code == 200, r.json()
    return r.json()


def _rollback(client, pv, **kw):
    body = {"sync_run_id": pv["sync_run_id"], "signature": pv["signature"], "confirm_text": CONFIRM, "reason": REASON}
    body.update(kw)
    return client.post("/api/sync-rollback", json=body)


def _runs(client) -> dict:
    return {r["id"]: r for r in client.get("/api/sync-runs").json()["runs"]}


def _two_runs_same_key():
    """R1 releases A's ORDER_GONE hold, R2 releases B, R3 releases A's LINE_GONE hold (same key as R1: R1 is then
    changed by a later write)."""
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    _hold(D1, "A", 2.0, cause="LINE_GONE")
    _row(D2, "B", 5.0)
    _hold(D2, "B", 1.0)
    return _release("A", "ORDER_GONE"), _release("B"), _release("A", "LINE_GONE")


# ------------------------------------------------------------------ list
def test_the_list_tells_which_runs_can_be_rolled_back(bq, client):
    r1, r2, r3 = _two_runs_same_key()
    before = _snapshot()
    runs = _runs(client)
    assert _snapshot() == before                                  # the list never writes
    assert runs[r1]["rollbackable"] is False and runs[r1]["reason"] == "CHANGED_BY_A_LATER_WRITE"
    assert runs[r2]["rollbackable"] is True and runs[r3]["rollbackable"] is True
    assert list(runs)[:3] == [r3, r2, r1]                         # newest first
    history_sync.rollback(r3, apply=True)
    runs = _runs(client)
    assert runs[r3]["rollbackable"] is False and runs[r3]["reason"] == "ALREADY_ROLLED_BACK"
    rbk = [x for x in runs.values() if x["kind"] == "ROLLBACK"][0]
    assert rbk["rollbackable"] is False and rbk["reason"] == "KIND_NOT_ROLLBACKABLE"
    j = client.get("/api/sync-runs").json()
    assert j["description_codes"] == list(sr.DESCRIPTION_CODES) and j["description"][1]["code"] == "SYNC_ROLLBACK_NOT_MODELS"


def test_the_list_without_bigquery_settings_is_empty(client):
    j = client.get("/api/sync-runs").json()
    assert j["configured"] is False and j["runs"] == []


# ------------------------------------------------------------------ preview
def test_the_preview_is_a_dry_run_and_writes_nothing(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    run = _release("A")
    before = _snapshot()
    pv = _preview(client, run)
    assert (pv["entries"], pv["rows_updated_by_run"], pv["units_now"], pv["units_after_rollback"]) == (1, 1, 6.0, 9.0)
    assert (pv["first_day"], pv["last_day"], pv["holds_to_restore"]) == (D1, D1, 1) and len(pv["signature"]) == 64
    assert pv["confirm_text"] == CONFIRM and pv["backup_before"] and pv["ops_lock_checked"] is False
    assert [x["code"] for x in pv["description"]] == list(sr.DESCRIPTION_CODES)
    assert _preview(client, run)["signature"] == pv["signature"]
    assert _snapshot() == before


def test_a_run_changed_by_a_later_write_is_refused_with_its_keys(bq, client):
    r1, _r2, _r3 = _two_runs_same_key()
    r = client.post("/api/sync-rollback/preview", json={"sync_run_id": r1})
    assert r.status_code == 409 and _code(r) == "SYNC_ROLLBACK_REFUSED" and r.json()["params"]["n_conflicts"] == 1
    assert r.json()["params"]["conflicts"][0]["key"] == [D1, "A", "F1"]
    r = client.post("/api/sync-rollback/preview", json={"sync_run_id": "NOPE"})
    assert r.status_code == 404 and _code(r) == "SYNC_RUN_NOT_FOUND"


def test_a_run_above_the_entry_cap_is_refused(bq, client, monkeypatch):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    run = _release("A")
    monkeypatch.setattr(sr, "MAX_ENTRIES", 0)
    r = client.post("/api/sync-rollback/preview", json={"sync_run_id": run})
    assert r.status_code == 422 and _code(r) == "SYNC_ROLLBACK_TOO_LARGE"
    assert _runs(client)[run]["reason"] == "TOO_LARGE_FOR_THE_UI"


# ------------------------------------------------------------------ gates
def test_wrong_text_short_reason_or_signature_writes_nothing(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client, _release("A"))
    before = _snapshot()
    for kw in ({"confirm_text": "QUAY-LAI-DONG-BO-2026-11-21"}, {"confirm_text": None}, {"reason": "ngan"}):
        r = _rollback(client, pv, **kw)
        assert r.status_code == 409 and _code(r) == "SYNC_ROLLBACK_CONFIRM_REQUIRED", kw
    r = _rollback(client, pv, signature="0" * 64)
    assert r.status_code == 409 and _code(r) == "SYNC_ROLLBACK_PREVIEW_STALE"
    assert _snapshot() == before and not sr._proc_lock.locked()


@pytest.mark.parametrize("setup,code", [("job", "SYNC_ROLLBACK_BUSY"), ("window", "SYNC_ROLLBACK_BUSY"),
                                        ("schedule", "SYNC_ROLLBACK_BUSY"), ("disk", "SYNC_ROLLBACK_DISK_SPACE"),
                                        ("lock", "OPERATIONS_LOCK_HELD")])
def test_busy_window_schedule_disk_and_lock_refuse(bq, client, monkeypatch, tmp_path, setup, code):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client, _release("A"))
    if setup == "job":
        _job("D1_SYNC", "RUNNING")
    elif setup == "window":
        timeutil.set_now_override(lambda: datetime(2026, 11, 22, 23, 0, tzinfo=VN_TZ))
    elif setup == "schedule":
        ss.update("schedule", {"report_time": "16:00"}, note="test")
    elif setup == "disk":
        monkeypatch.setattr(hl, "_free_bytes", lambda p: 1000)
    else:
        monkeypatch.setenv("DF_OPS_LOCK", str(tmp_path / "OPS_LOCK"))
        (tmp_path / "OPS_LOCK").write_text("{}")
    before = _snapshot()
    r = _rollback(client, pv)
    assert r.status_code == 409 and _code(r) == code
    if setup == "disk":
        p = r.json()["params"]
        assert p["free_bytes"] == 1000 and p["missing_bytes"] == p["need_bytes"] - 1000
    assert _snapshot() == before and not sr._proc_lock.locked()


def test_a_gate_that_fails_after_the_backup_writes_nothing(bq, client, monkeypatch):
    from app import backup
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    run = _release("A")
    pv = _preview(client, run)
    real = backup.backup_database

    def backup_then_job(reason="manual", dest_dir=None):
        f = real(reason=reason, dest_dir=dest_dir)
        _job("FORECAST_REFRESH", "RUNNING")
        return f
    monkeypatch.setattr(backup, "backup_database", backup_then_job)
    values = _values()
    t = _rollback(client, pv).json()["task"]
    assert t["status"] == "FAILED" and t["error"]["code"] == "SYNC_ROLLBACK_BUSY"
    assert _values() == values and _count("SELECT COUNT(*) FROM demand_sync_runs WHERE kind='ROLLBACK'") == 0
    assert _count("SELECT COUNT(*) FROM demand_sync_runs WHERE id=? AND status='COMMITTED'", (run,)) == 1
    assert [x for x in _backups() if x.endswith("-pre-rollback.zip")]       # the backup is kept


def test_the_cli_rollback_is_unchanged(bq):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    run = _release("A")
    _job("D1_SYNC", "RUNNING")                                    # the API gates play no part in the CLI path
    out = history_sync.rollback(run, apply=True)
    assert out["applied"] and _values()[(D1, "A", "F1")] == 9.0


# ------------------------------------------------------------------ background, two clicks, the full loop
def test_two_clicks_start_one_rollback(bq, client, monkeypatch):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client, _release("A"))
    gate, entered, calls = threading.Event(), threading.Event(), []

    def fake(run_id, apply=False, by="CLI", before_write=None):
        calls.append(run_id)
        assert apply is True and callable(before_write)          # the gate checked again inside the write
        entered.set()
        assert gate.wait(10)
        return {"applied": True, "rollback_run": "RBK-FAKE", "backup": None, "entries": 1}
    monkeypatch.setattr(history_sync, "rollback", fake)
    monkeypatch.setattr(background, "SYNC_MODE", False)
    r1 = _rollback(client, pv)
    assert r1.status_code == 202 and r1.json()["task"]["status"] == "RUNNING"
    assert entered.wait(10)
    r2 = _rollback(client, pv)
    assert r2.status_code == 409 and _code(r2) == "SYNC_ROLLBACK_RUNNING"
    gate.set()
    end = time.monotonic() + 10
    while client.get("/api/sync-rollback/status").json()["running"] and time.monotonic() < end:
        time.sleep(0.02)
    st = client.get("/api/sync-rollback/status").json()
    assert st["task"]["status"] == "SUCCEEDED" and st["task"]["result"]["rollback_run"] == "RBK-FAKE" and calls == [pv["sync_run_id"]]
    assert not sr._proc_lock.locked()


def test_release_through_the_api_then_roll_it_back_by_its_sync_run_id(bq, client):
    _row(D1, "A", 8.0, n_orders=2)
    _hold(D1, "A", 3.0)
    _row(D1, "B", 2.0)
    _hold(D1, "B", 2.0)
    before = _values()
    hp = client.post("/api/held-lines/release-preview", json={}).json()
    rel = client.post("/api/held-lines/release", json={"signature": hp["signature"],
                                                       "confirm_text": f"NHA-DONG-GIU-{TODAY}", "reason": REASON}).json()
    run_id = rel["task"]["result"]["sync_run_id"]
    assert _values() != before
    pv = _preview(client, run_id)
    assert pv["kind"] == "HOLD_RELEASE" and pv["rows_deleted_by_run"] == 1 and pv["rows_updated_by_run"] == 1
    r = _rollback(client, pv)
    assert r.status_code == 202
    t = r.json()["task"]
    assert t["status"] == "SUCCEEDED" and t["result"]["rollback_run"].startswith("RBK-")
    assert Path(t["result"]["backup_path"]).exists() and t["result"]["backup_file"].endswith("-pre-rollback.zip")
    assert _values() == before and _count("SELECT COUNT(*) FROM demand_held_lines WHERE status='ACTIVE'") == 2
    with db.read() as c:
        assert c.execute("SELECT status FROM demand_sync_runs WHERE id=?", (run_id,)).fetchone()[0] == "ROLLED_BACK"
        rb = json.loads(c.execute("SELECT summary_json FROM demand_sync_runs WHERE kind='ROLLBACK'").fetchone()[0])
        audits = {r[0] for r in c.execute("SELECT action FROM audit_log")}
    assert rb["by"] == f"API {t['task_id']}: {REASON}"
    assert {"SYNC_ROLLBACK_REQUESTED", "DEMAND_SYNC_ROLLBACK"} <= audits
    assert _runs(client)[run_id]["reason"] == "ALREADY_ROLLED_BACK"


def test_a_rollback_cut_by_an_app_stop_is_interrupted_and_never_blocks(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client, _release("A"))
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?,?,?)",
                  (sr.STATE, json.dumps({"task_id": "SRB-OLD", "status": "RUNNING", "owner": "pid1-dead00",
                                         "sync_run_id": "X", "started_at": "2026-11-22T03:00:00+00:00",
                                         "heartbeat_at": "2026-11-22T03:00:00+00:00"}), "x"))
    assert client.get("/api/sync-rollback/status").json()["task"]["status"] == "INTERRUPTED"
    assert _rollback(client, pv).json()["task"]["status"] == "SUCCEEDED"
    assert _count("SELECT COUNT(*) FROM audit_log WHERE action='SYNC_ROLLBACK_INTERRUPTED'") == 1


def test_every_code_of_the_module_is_in_the_catalogue():
    s = Path(sr.__file__).read_text(encoding="utf-8")
    codes = set(re.findall(r'AppError\(\s*"([A-Z_]+)"', s)) | set(re.findall(r'"code": "([A-Z_]+)"', s)) \
        | set(sr.DESCRIPTION_CODES)
    assert {"SYNC_ROLLBACK_BUSY", "SYNC_ROLLBACK_INTERRUPTED", "SYNC_ROLLBACK_NOT_MODELS"} <= codes
    assert not sorted(c for c in codes if c not in CATALOG)


# ------------------------------------------------------------------ REV-B: a slow check never answers 500
def test_a_check_over_the_time_limit_is_refused_as_too_large(bq, client, monkeypatch):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client, _release("A"))
    monkeypatch.setattr(sr, "_deadline", lambda c, seconds: c.set_progress_handler(lambda: 1, 1))   # time is up at once
    for r in (client.post("/api/sync-rollback/preview", json={"sync_run_id": pv["sync_run_id"]}), _rollback(client, pv)):
        assert r.status_code == 422 and _code(r) == "SYNC_ROLLBACK_TOO_LARGE"
    assert not sr._proc_lock.locked()


def test_before_write_receives_the_check_made_under_the_write_lock(bq, client, monkeypatch):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client, _release("A"))
    real, seen = history_sync.rollback, []

    def spy(run_id, apply=False, by="CLI", before_write=None):
        def bw(c, check):
            seen.append((check[0]["id"], len(check[1])))
            return before_write(c, check)
        return real(run_id, apply=apply, by=by, before_write=bw)
    monkeypatch.setattr(history_sync, "rollback", spy)
    assert _rollback(client, pv).json()["task"]["status"] == "SUCCEEDED"
    assert seen == [(pv["sync_run_id"], 1)]


# ------------------------------------------------------------------ CV-NOSWITCH: one background write across the buttons
def test_a_running_re_read_blocks_the_rollback(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client, _release("A"))
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?,?,?)",
                  ("open_hours_reread", json.dumps({"task_id": "OHR-X", "status": "RUNNING", "owner": "pid1-other",
                                                    "started_at": "2026-11-22T07:59:00+00:00",
                                                    "heartbeat_at": "2026-11-22T07:59:00+00:00"}), "x"))
    assert _preview(client, pv["sync_run_id"])["busy_other_task"]["button"] == "OPEN_HOURS_REREAD"
    before = _snapshot()
    r = _rollback(client, pv)
    assert r.status_code == 409 and _code(r) == "HEAVY_WRITE_ANOTHER_RUNNING" and _snapshot() == before
    assert "ROLLBACK_ONLY_BEFORE_NEXT_WRITE" in pv["description_codes"]
