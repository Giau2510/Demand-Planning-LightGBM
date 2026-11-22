"""1.4.15 lot 3: release of held lines from the UI (api/held_lines_routes.py around history_sync.release_holds).

Integration with fakes: TestClient on the isolated temporary database (conftest), synthetic demand rows and held lines
inserted directly, the real release_holds / backup_database / rollback on that temporary database, or a fake
release_holds where a test needs to block or fail the background thread. No real data, no BigQuery, no network.
Covers: read-only summary and paging; the preview writes nothing; the 450 lines / 6,000 units limits; signature
mismatch; confirmation text and reason; busy (job rows, production windows, the margin before them); short disk space;
one release at a time; a release cut by an app stop never blocks the next one; worker failure; undo via rollback().
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
from app.data import history_sync
from app.jobs import runner
from app.messages import CATALOG, AppError
from app.timeutil import VN_TZ

SCOPE = "BIGQUERY:proj-x.ds_x.tbl_x"
OTHER = "BIGQUERY:other.ds.tbl"
TODAY = "2026-11-22"
CONFIRM = f"NHA-DONG-GIU-{TODAY}"
REASON = "chu du an duyet nha dong giu"      # >= 10 characters
D1 = "2026-11-10"
D2 = "2026-11-12"
NOW_UTC = "2026-11-22T08:00:00+00:00"        # 15:00 Vietnam, the frozen time (no default schedule time near it)


@pytest.fixture(autouse=True)
def _frozen_day():
    timeutil.set_now_override(lambda: datetime(2026, 11, 22, 15, 0, tzinfo=VN_TZ))
    yield


@pytest.fixture
def bq(client, monkeypatch):
    """The BigQuery scope configured (no connection needed) and plenty of free space for the backup."""
    ss.update("bigquery", {"project_id": "proj-x", "dataset_id": "ds_x", "source_table": "tbl_x"}, note="test")
    monkeypatch.setattr(hl, "_free_bytes", lambda p: 10 ** 15)
    for k in (*hl.LOCK_ENV, hl.RUN_DIR_ENV):     # no operations lock variable unless a test sets one
        monkeypatch.delenv(k, raising=False)
    return SCOPE


# ------------------------------------------------------------------ helpers
_SEQ = [0]


def _at(h, m, day=22):
    timeutil.set_now_override(lambda: datetime(2026, 11, day, h, m, tzinfo=VN_TZ))


def _row(d, sku, qty, fc="F1", n_orders=1, scope=SCOPE):
    with db.tx() as c:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
                  "VALUES (?, 'BIGQUERY', ?,?,?,?,?, '2026-11-13T00:00:00+00:00')", (scope, d, sku, fc, qty, n_orders))


def _hold(d, sku, qty, fc="F1", cause="ORDER_GONE", order_id=None, scope=SCOPE, status="ACTIVE", n=1):
    ids = []
    with db.tx() as c:
        for _ in range(n):
            _SEQ[0] += 1
            hid = f"H{_SEQ[0]:07d}"
            rel = status != "ACTIVE"
            c.execute("INSERT INTO demand_held_lines(id, scope_key, order_date, sku_id, fc_id, order_id, qty, cause, status, "
                      "detected_run, detected_at, released_at, released_run, release_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (hid, scope, d, sku, fc, order_id, qty, cause, status, "D1L-T", "2026-11-13T00:00:00+00:00",
                       "2026-11-14T00:00:00+00:00" if rel else None, "D1L-T2" if rel else None,
                       "REAPPEARED" if rel else None))
            ids.append(hid)
    return ids[0] if n == 1 else ids


def _values(scope=SCOPE) -> dict:
    with db.read() as c:
        return {(r[0], r[1], r[2]): (r[3], r[4]) for r in c.execute(
            "SELECT order_date, sku_id, fc_id, qty, n_orders FROM demand_daily WHERE scope_key=?", (scope,))}


def _count(sql, p=()) -> int:
    with db.read() as c:
        return c.execute(sql, p).fetchone()[0]


def _audit(action) -> int:
    return _count("SELECT COUNT(*) FROM audit_log WHERE action=?", (action,))


def _raw_state():
    with db.read() as c:
        r = c.execute("SELECT value_json FROM sync_state WHERE name=?", (hl.STATE,)).fetchone()
    return json.loads(r[0]) if r else None


def _put_state(st):
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET "
                  "value_json=excluded.value_json, updated_at=excluded.updated_at", (hl.STATE, json.dumps(st), NOW_UTC))


def _backups() -> list[str]:
    return sorted(x.name for x in paths.backups_dir().iterdir())


def _snapshot() -> dict:
    """Everything a release (or a stray write) could touch."""
    return {"daily": _values(), "held": _count("SELECT COUNT(*) FROM demand_held_lines WHERE status='ACTIVE'"),
            "runs": _count("SELECT COUNT(*) FROM demand_sync_runs"), "log": _count("SELECT COUNT(*) FROM demand_change_log"),
            "audit": _count("SELECT COUNT(*) FROM audit_log"), "state": _count("SELECT COUNT(*) FROM sync_state"),
            "state_value": _raw_state(), "backups": _backups()}


def _job(job_type, status, created_at="2026-11-22T07:30:00+00:00"):
    _SEQ[0] += 1
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) VALUES (?,?,?,?,?,?)",
                  (f"J-{_SEQ[0]}", job_type, f"idem-{_SEQ[0]}", "MANUAL", status, created_at))


def _code(r):
    return r.json()["code"]


def _preview(client, **flt):
    r = client.post("/api/held-lines/release-preview", json=flt)
    assert r.status_code == 200, r.json()
    return r.json()


def _release(client, pv, **kw):
    body = {**{k: v for k, v in pv["filter"].items() if v is not None}, "signature": pv["signature"],
            "confirm_text": CONFIRM, "reason": REASON}
    body.update(kw)
    return client.post("/api/held-lines/release", json=body)


def _wait_done(client, timeout=10.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = client.get("/api/held-lines/release-status").json()
        if not st["running"]:
            return st
        time.sleep(0.02)
    raise AssertionError("release still running")


# ------------------------------------------------------------------ GET: read-only summary
def test_summary_counts_only_active_lines_of_the_bigquery_scope_groups_and_pages(bq, client):
    _hold(D1, "A", 2.0, order_id="O1")
    _hold(D1, "A", 1.0, cause="QTY_REDUCED", order_id="O2")
    _hold(D2, "B", 4.0, fc="F2", cause="LINE_GONE", order_id="O3")
    _hold(D2, "C", 0.5, order_id="O4")
    _hold(D1, "A", 9.0, status="RELEASED")
    _hold(D1, "A", 7.0, scope=OTHER)
    before = _snapshot()
    j = client.get("/api/held-lines").json()
    s = j["summary"]
    assert j["configured"] and j["scope_key"] == SCOPE and s["status"] == "COMPLETE"
    assert (s["active_lines"], s["units"], s["keys"], s["days"]) == (4, 7.5, 3, 2)
    assert s["by_cause"]["ORDER_GONE"] == {"lines": 2, "units": 2.5}
    assert [(r["sku_id"], r["fc_id"], r["units"]) for r in j["rows"]] == [("B", "F2", 4.0), ("A", "F1", 3.0),
                                                                          ("C", "F1", 0.5)]
    assert j["total_groups"] == 3 and j["limits"]["max_lines"] == 450 and j["confirm_text"] == CONFIRM
    days = client.get("/api/held-lines", params={"view": "day"}).json()["rows"]
    assert [r["order_date"] for r in days] == [D2, D1]           # newest day first
    p1 = client.get("/api/held-lines", params={"view": "lines", "limit": 2}).json()["rows"]
    p2 = client.get("/api/held-lines", params={"view": "lines", "limit": 2, "offset": 2}).json()["rows"]
    assert len(p1) == 2 and len(p2) == 2 and not {r["id"] for r in p1} & {r["id"] for r in p2}
    only = client.get("/api/held-lines", params={"fc_id": "F2"}).json()["summary"]
    assert only["active_lines"] == 1 and only["units"] == 4.0
    assert client.get("/api/held-lines", params={"limit": 201}).status_code == 422
    r = client.get("/api/held-lines", params={"view": "everything"})
    assert r.status_code == 422 and _code(r) == "HELD_RELEASE_INVALID_FILTER"
    assert _snapshot() == before                                  # GET never writes


def test_summary_stops_at_the_scan_cap(bq, client, monkeypatch):
    _hold(D1, "A", 1.0, n=5)
    monkeypatch.setattr(hl, "SCAN_CAP", 3)
    s = client.get("/api/held-lines").json()["summary"]
    assert s["status"] == "CAPPED" and s["active_lines"] == 3


def test_summary_without_bigquery_settings_is_not_configured(client):
    j = client.get("/api/held-lines").json()
    assert j["configured"] is False and j["summary"] is None and j["rows"] == []
    r = client.post("/api/held-lines/release-preview", json={})
    assert r.status_code == 409 and _code(r) == "HELD_LINES_NO_SCOPE"


# ------------------------------------------------------------------ preview: dry run
def test_preview_is_a_dry_run_and_writes_nothing(bq, client):
    _row(D1, "A", 8.0, n_orders=2)
    _hold(D1, "A", 3.0, order_id="O2")
    _row(D1, "B", 2.0)
    _hold(D1, "B", 2.0, order_id="O5")
    before = _snapshot()
    pv = _preview(client)
    assert (pv["holds"], pv["units"], pv["keys"]) == (2, 5.0, 2) and pv["releasable"] and len(pv["signature"]) == 64
    k = {x["sku_id"]: x for x in pv["keys_detail"]}
    assert k["A"]["qty_after"] == 5.0 and not k["A"]["row_removed"]
    assert k["B"]["qty_after"] is None and k["B"]["row_removed"]
    assert pv["confirm_text"] == CONFIRM and pv["backup_before"] and pv["runs_in_background"] and pv["disk"]["ok"]
    assert _preview(client)["signature"] == pv["signature"]      # same lines -> same signature
    assert _snapshot() == before                                  # nothing written, no backup made


def test_preview_with_nothing_to_release_is_not_releasable(bq, client):
    pv = _preview(client, sku_id="NONE")
    assert pv["holds"] == 0 and pv["signature"] is None and pv["warnings"] == ["HELD_RELEASE_NOTHING"]


def test_filters_are_validated_and_there_is_no_fc_filter(bq, client):
    for body in ({"fc_id": "F1"}, {"cause": "BOGUS"}, {"start": "2026-11-1"}, {"start": D2, "end": D1}):
        r = client.post("/api/held-lines/release-preview", json=body)
        assert r.status_code == 422, body
    r = client.post("/api/held-lines/release-preview", json={"start": D2, "end": D1})
    assert _code(r) == "HELD_RELEASE_INVALID_FILTER"


def test_a_key_without_stored_row_or_with_fewer_stored_units_is_refused(bq, client):
    _hold(D1, "A", 3.0)                                           # no demand_daily row
    r = client.post("/api/held-lines/release-preview", json={})
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_ROW_INCONSISTENT"
    _row(D1, "A", 1.0)                                            # stored 1 < held 3
    r = client.post("/api/held-lines/release-preview", json={})
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_ROW_INCONSISTENT"


# ------------------------------------------------------------------ limits 450 lines / 6,000 units per release
def test_more_than_450_lines_is_refused_with_the_largest_groups(bq, client):
    _row(D1, "A", 500.0)
    _hold(D1, "A", 1.0, n=450)
    _row(D1, "B", 5.0)
    _hold(D1, "B", 1.0)
    r = client.post("/api/held-lines/release-preview", json={})
    assert r.status_code == 422 and _code(r) == "HELD_RELEASE_TOO_LARGE"
    p = r.json()["params"]
    assert p["holds"] == 451 and p["by_sku_fc"][0] == {"sku_id": "A", "fc_id": "F1", "lines": 450, "units": 450.0}
    assert p["by_day"][0]["order_date"] == D1
    pv = _preview(client, sku_id="A")                             # exactly 450: accepted
    assert pv["holds"] == 450
    r = _release(client, {"filter": {}, "signature": pv["signature"]})     # the whole selection again: refused
    assert r.status_code == 422 and _code(r) == "HELD_RELEASE_TOO_LARGE"
    assert _count("SELECT COUNT(*) FROM demand_sync_runs") == 0 and _backups() == []


def test_more_than_6000_units_is_refused(bq, client):
    _row(D1, "A", 7000.0)
    _hold(D1, "A", 3000.0)
    _hold(D1, "A", 3000.5, cause="QTY_REDUCED")
    r = client.post("/api/held-lines/release-preview", json={})
    assert r.status_code == 422 and _code(r) == "HELD_RELEASE_TOO_LARGE" and r.json()["params"]["units"] == 6000.5
    assert _preview(client, cause="ORDER_GONE")["units"] == 3000.0
    _row(D2, "C", 6000.0)
    _hold(D2, "C", 3000.0, n=2)
    assert _preview(client, sku_id="C")["units"] == 6000.0      # exactly 6,000: accepted


# ------------------------------------------------------------------ release gates
def test_a_signature_that_does_not_match_writes_nothing(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client, sku_id="A")
    _hold(D1, "A", 1.0)                                           # a D-1 added a held line after the preview
    before = _snapshot()
    r = _release(client, pv)
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_PREVIEW_STALE" and r.json()["params"]["holds"] == 2
    r = _release(client, pv, signature="0" * 64)
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_PREVIEW_STALE"
    assert _snapshot() == before


def test_wrong_confirmation_text_or_short_reason_writes_nothing(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client)
    before = _snapshot()
    for kw in ({"confirm_text": "NHA-DONG-GIU-2026-11-21"}, {"confirm_text": None}, {"reason": "ngan qua"},
               {"reason": "  a   b  c  d  "}):
        r = _release(client, pv, **kw)
        assert r.status_code == 409 and _code(r) == "HELD_RELEASE_CONFIRM_REQUIRED", kw
        assert r.json()["params"]["confirm_text"] == CONFIRM
    r = _release(client, pv, reason="x" * 501)
    assert r.status_code == 422
    assert _snapshot() == before
    assert _release(client, pv).status_code == 202               # the lock was never taken by the refused calls


@pytest.mark.parametrize("job_type,status", [("D1_SYNC", "RUNNING"), ("FORECAST_REFRESH", "RETRY_WAIT"),
                                             ("SPIKE_LINES", "PENDING"), ("FORECAST_EXPORT", "RUNNING"),
                                             ("ACTUAL_CLOSE", "PENDING")])
def test_an_active_job_blocks_preview_and_release(bq, client, job_type, status):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client)
    _job(job_type, status)
    before = _snapshot()
    r = client.post("/api/held-lines/release-preview", json={})
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_BUSY"
    r = _release(client, pv)
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_BUSY" and r.json()["params"]["jobs"][0]["job_type"] == job_type
    assert _snapshot() == before


def test_production_windows_and_the_hour_before_them_block(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    _at(2, 0)                                                     # inside 00:45-03:45
    r = client.post("/api/held-lines/release-preview", json={})
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_BUSY" and r.json()["params"]["window"] == "00:45-03:45"
    _at(23, 0)                                                    # 45 min before 23:45
    r = client.post("/api/held-lines/release-preview", json={})
    assert r.status_code == 409 and r.json()["params"]["window_soon"] == "23:45"
    _at(0, 20, day=23)                                            # between the windows, 25 min before 00:45
    r = client.post("/api/held-lines/release-preview", json={})
    assert r.status_code == 409 and r.json()["params"]["window_soon"] == "00:45"
    _at(22, 0)                                                    # 105 min before 23:45, 115 before eod_time: free
    assert _preview(client)["holds"] == 1


def test_short_disk_space_is_refused_with_the_figures(bq, client, monkeypatch):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    monkeypatch.setattr(hl, "_free_bytes", lambda p: 1000)
    pv = _preview(client)
    assert pv["disk"]["ok"] is False and pv["disk"]["need_bytes"] > 1000
    before = _snapshot()
    r = _release(client, pv)
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_DISK_SPACE"
    p = r.json()["params"]
    assert p["free_bytes"] == 1000 and p["missing_bytes"] == p["need_bytes"] - 1000
    assert f"need {p['need_bytes']} B, free 1000 B, missing {p['missing_bytes']} B" in r.json()["detail"]
    assert _snapshot() == before                                  # no backup started, no task state


# ------------------------------------------------------------------ the release itself
def test_a_release_backs_up_writes_one_run_and_rollback_restores_it(bq, client):
    _row(D1, "A", 8.0, n_orders=2)
    _hold(D1, "A", 3.0, order_id="O2")
    _row(D1, "B", 2.0)
    _hold(D1, "B", 2.0, order_id="O5")
    _row(D2, "Z", 4.0)                                            # not held: untouched
    before = _values()
    pv = _preview(client)
    r = _release(client, pv)
    assert r.status_code == 202 and r.json()["accepted"]
    t = r.json()["task"]
    assert t["status"] == "SUCCEEDED" and t["error"] is None and t["reason"] == REASON
    res = t["result"]
    run_id = res["sync_run_id"]
    assert run_id.startswith("HRL-") and (res["holds"], res["units"], res["keys"]) == (2, 5.0, 2)
    assert res["rollback"]["sync_run_id"] == run_id
    assert res["backup_file"].endswith("-pre-hold-release.zip") and Path(res["backup_path"]).exists()
    assert res["backup_bytes"] > 0 and res["backup_file"] in _backups()
    v = _values()
    assert v[(D1, "A", "F1")] == (5.0, 1) and (D1, "B", "F1") not in v and v[(D2, "Z", "F1")] == (4.0, 1)
    with db.read() as c:
        run = db.one(c, "SELECT * FROM demand_sync_runs WHERE id=?", (run_id,))
    assert run["kind"] == "HOLD_RELEASE" and run["status"] == "COMMITTED"
    assert json.loads(run["summary_json"])["by"] == f"API {t['task_id']}: {REASON}"
    assert _audit("HELD_LINES_RELEASE_REQUESTED") == 1 and _audit("HELD_LINES_RELEASED") == 1
    assert _count("SELECT COUNT(*) FROM demand_held_lines WHERE status='ACTIVE'") == 0
    st = client.get("/api/held-lines/release-status").json()
    assert st["recent_releases"][0]["sync_run_id"] == run_id and st["recent_releases"][0]["rollback"]
    assert st["backups"]["release_backups"] == 1 and st["backups"]["temporary_files"] == []
    history_sync.rollback(run_id, apply=True)                     # the undo path of a later lot
    assert _values() == before and _count("SELECT COUNT(*) FROM demand_held_lines WHERE status='ACTIVE'") == 2
    assert client.get("/api/held-lines/release-status").json()["recent_releases"][0]["status"] == "ROLLED_BACK"


def _fake_release(gate=None, entered=None, error=None, calls=None):
    def fake(scope_key, cause=None, sku_id=None, start=None, end=None, apply=False, by="CLI", expected_ids=None,
             before_write=None):
        if calls is not None:
            calls.append({"scope_key": scope_key, "sku_id": sku_id, "apply": apply, "by": by,
                          "expected_ids": expected_ids, "before_write": before_write})
        if entered is not None:
            entered.set()
        if gate is not None:
            assert gate.wait(10)
        if error is not None:
            raise error
        return {"applied": True, "run_id": "HRL-FAKE", "backup": None, "holds": 1, "units": 3.0, "keys": 1,
                "by_cause": {"ORDER_GONE": 1}}
    return fake


def test_only_one_release_runs_at_a_time(bq, client, monkeypatch):
    _row(D1, "A", 9.0)
    hid = _hold(D1, "A", 3.0)
    pv = _preview(client)
    gate, entered, calls = threading.Event(), threading.Event(), []
    monkeypatch.setattr(history_sync, "release_holds", _fake_release(gate, entered, calls=calls))
    monkeypatch.setattr(background, "SYNC_MODE", False)
    r1 = _release(client, pv)
    assert r1.status_code == 202 and r1.json()["task"]["status"] == "RUNNING"
    assert entered.wait(10)
    th = hl._current["thread"]
    r2 = _release(client, pv)
    assert r2.status_code == 409 and _code(r2) == "HELD_RELEASE_RUNNING"
    st = client.get("/api/held-lines/release-status").json()
    assert st["running"] and st["task"]["status"] == "RUNNING"    # its own live thread: never shown INTERRUPTED
    gate.set()
    th.join(10)
    st = _wait_done(client)
    assert st["task"]["status"] == "SUCCEEDED" and st["task"]["result"]["sync_run_id"] == "HRL-FAKE"
    assert len(calls) == 1 and calls[0]["apply"] is True and calls[0]["sku_id"] is None
    assert calls[0]["expected_ids"] == {hid}                     # the previewed lines, passed to release_holds
    assert calls[0]["before_write"] is hl._guard                 # the gate checked again inside the write
    r3 = _release(client, pv)                                     # the lock is free again
    assert r3.status_code == 202
    assert _wait_done(client)["task"]["task_id"] == r3.json()["task"]["task_id"]


def test_a_failure_in_the_background_is_recorded_and_frees_the_lock(bq, client, monkeypatch):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client)
    monkeypatch.setattr(history_sync, "release_holds",
                        _fake_release(error=AppError("VALIDATION_ERROR", 409, detail="1 held lines changed")))
    r = _release(client, pv)
    assert r.status_code == 202
    t = r.json()["task"]
    assert t["status"] == "FAILED" and t["error"]["code"] == "VALIDATION_ERROR" and t["result"] is None
    assert _audit("HELD_LINES_RELEASE_FAILED") == 1
    monkeypatch.setattr(history_sync, "release_holds", _fake_release(error=RuntimeError("disk full")))
    t = _release(client, pv).json()["task"]
    assert t["status"] == "FAILED" and t["error"]["code"] == "HELD_RELEASE_FAILED"
    assert not hl._proc_lock.locked() and hl._current["task_id"] is None


# ------------------------------------------------------------------ the app stops during a release
def _old_task(owner="pid1-dead00", heartbeat="2026-11-22T03:00:00+00:00", task_id="HLT-OLD"):
    return {"task_id": task_id, "status": "RUNNING", "owner": owner, "scope_key": SCOPE,
            "filter": {"cause": None, "sku_id": None, "start": None, "end": None},
            "started_at": "2026-11-22T03:00:00+00:00", "heartbeat_at": heartbeat, "result": None, "error": None}


def test_a_release_cut_by_an_app_stop_is_interrupted_and_never_blocks(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    _put_state(_old_task())                                       # another process, no heartbeat for 2 hours
    raw = _raw_state()
    st = client.get("/api/held-lines/release-status").json()
    assert not st["running"] and st["task"]["status"] == "INTERRUPTED" and st["task"]["committed"] is False
    assert st["task"]["error"]["code"] == "HELD_RELEASE_INTERRUPTED"
    assert _raw_state() == raw                                    # shown, not written by a GET
    r = _release(client, _preview(client))
    assert r.status_code == 202 and r.json()["task"]["status"] == "SUCCEEDED"
    assert _audit("HELD_LINES_RELEASE_INTERRUPTED") == 1


def test_a_task_of_this_process_whose_thread_is_gone_is_interrupted(bq, client):
    _put_state(_old_task(owner=runner.OWNER, heartbeat=NOW_UTC))
    assert client.get("/api/held-lines/release-status").json()["task"]["status"] == "INTERRUPTED"


def test_a_release_cut_after_its_commit_shows_the_run_to_undo(bq, client):
    _put_state(_old_task())
    with db.tx() as c:
        c.execute("INSERT INTO demand_sync_runs(id, kind, status, scope_key, policy, started_at, finished_at, summary_json, "
                  "backup) VALUES ('HRL-CUT', 'HOLD_RELEASE', 'COMMITTED', ?, 'KEEP_OBSERVED_LINES', ?, ?, ?, ?)",
                  (SCOPE, "2026-11-22T03:20:00+00:00", "2026-11-22T03:20:00+00:00",
                   json.dumps({"holds": 1, "by": f"API HLT-OLD: {REASON}"}), json.dumps({"file": "backup-x.zip"})))
    t = client.get("/api/held-lines/release-status").json()["task"]
    assert t["status"] == "INTERRUPTED" and t["committed"] is True and t["result"]["sync_run_id"] == "HRL-CUT"


def test_a_live_release_of_another_process_blocks(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client)
    _put_state(_old_task(heartbeat="2026-11-22T07:59:00+00:00"))     # heartbeat 1 minute ago
    assert client.get("/api/held-lines/release-status").json()["running"] is True
    before = _snapshot()
    r = _release(client, pv)
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_RUNNING"
    assert _snapshot() == before
    assert not hl._proc_lock.locked() and hl._current["task_id"] is None      # the refusal gave the lock back


def test_files_left_by_a_cut_backup_are_listed_never_deleted(bq, client):
    left = paths.backups_dir() / "app-20261122-100000-pre-hold-release.db"
    left.write_bytes(b"x" * 10)
    b = client.get("/api/held-lines/release-status").json()["backups"]
    assert b["temporary_files"] == [{"file": left.name, "size_bytes": 10, "note": "LEFT_BY_A_CUT_BACKUP"}]
    assert left.exists()


# ------------------------------------------------------------------ catalogue
def test_every_code_of_the_module_is_in_the_catalogue():
    src = Path(hl.__file__).read_text(encoding="utf-8")
    codes = set(re.findall(r'AppError\(\s*"([A-Z_]+)"', src)) | set(re.findall(r'"code": "([A-Z_]+)"', src)) \
        | set(re.findall(r'"(HELD_RELEASE_[A-Z_]+|HELD_LINES_NO_SCOPE)"', src))     # not the audit actions
    assert {"HELD_RELEASE_TOO_LARGE", "HELD_RELEASE_INTERRUPTED", "HELD_RELEASE_PREVIEW_STALE"} <= codes
    assert not sorted(c for c in codes if c not in CATALOG)


# ------------------------------------------------------------------ L3-FIX: schedule times, expected ids, heartbeat, timeout, disk
def test_a_saved_schedule_time_near_now_blocks_and_is_named(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    ss.update("schedule", {"report_time": "16:00"}, note="test")          # in 60 minutes
    r = client.post("/api/held-lines/release-preview", json={})
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_BUSY"
    assert r.json()["params"]["schedule_times"] == [{"setting": "schedule.report_time", "time": "16:00"}]
    assert "schedule.report_time 16:00" in r.json()["detail"]
    ss.update("schedule", {"report_time": "14:50"}, note="test")          # 10 minutes ago
    assert client.post("/api/held-lines/release-preview", json={}).status_code == 409
    ss.update("schedule", {"report_time": "14:40"}, note="test")          # 20 minutes ago: free
    assert _preview(client)["holds"] == 1
    ss.update("sel2_pipeline", {"avg_reexport_time": "16:25"}, note="test")   # in 85 minutes (other section)
    r = client.post("/api/held-lines/release-preview", json={})
    assert r.json()["params"]["schedule_times"] == [{"setting": "sel2_pipeline.avg_reexport_time", "time": "16:25"}]


def test_release_holds_with_expected_ids_refuses_a_changed_selection_before_the_backup(bq):
    _row(D1, "A", 9.0)
    h1 = _hold(D1, "A", 3.0)
    _hold(D1, "A", 1.0)                                           # held after the preview of {h1}
    before = _snapshot()
    with pytest.raises(AppError) as e:
        history_sync.release_holds(SCOPE, apply=True, expected_ids={h1})
    assert e.value.code == "HELD_RELEASE_PREVIEW_STALE" and e.value.status == 409
    assert _snapshot() == before                                  # no backup, nothing written


def test_release_holds_with_expected_ids_refuses_a_line_added_during_the_backup(bq, monkeypatch):
    from app import backup
    _row(D1, "A", 9.0)
    h1 = _hold(D1, "A", 3.0)

    def fake_backup(reason="manual", dest_dir=None):
        _hold(D1, "A", 1.0)                                       # a D-1 holds a line while the backup runs
        f = paths.backups_dir() / f"backup-fake-{reason}.zip"
        f.write_bytes(b"z")
        return f
    monkeypatch.setattr(backup, "backup_database", fake_backup)
    values = _values()
    with pytest.raises(AppError) as e:
        history_sync.release_holds(SCOPE, apply=True, expected_ids={h1})
    assert e.value.code == "HELD_RELEASE_PREVIEW_STALE"
    assert _values() == values and _count("SELECT COUNT(*) FROM demand_held_lines WHERE status='ACTIVE'") == 2
    assert _count("SELECT COUNT(*) FROM demand_sync_runs") == 0 and _count("SELECT COUNT(*) FROM demand_change_log") == 0


def test_release_holds_without_expected_ids_keeps_the_cli_behaviour(bq):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    _hold(D1, "A", 1.0)
    out = history_sync.release_holds(SCOPE, apply=True)
    assert out["applied"] and out["holds"] == 2 and _values()[(D1, "A", "F1")] == (5.0, 1)


def test_a_line_held_between_the_route_check_and_the_write_fails_the_task_and_writes_nothing(bq, client, monkeypatch):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client)
    real = history_sync.release_holds

    def late(*a, **k):
        _hold(D1, "A", 1.0)                                       # after the route's signature check
        return real(*a, **k)
    monkeypatch.setattr(history_sync, "release_holds", late)
    values = _values()
    t = _release(client, pv).json()["task"]
    assert t["status"] == "FAILED" and t["error"]["code"] == "HELD_RELEASE_PREVIEW_STALE" and t["result"] is None
    assert _values() == values and _backups() == [] and _count("SELECT COUNT(*) FROM demand_sync_runs") == 0
    assert not hl._proc_lock.locked()


def test_the_heartbeat_is_written_while_the_release_runs(bq, client, monkeypatch):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client)
    gate, entered = threading.Event(), threading.Event()
    monkeypatch.setattr(history_sync, "release_holds", _fake_release(gate, entered))
    monkeypatch.setattr(background, "SYNC_MODE", False)
    monkeypatch.setattr(hl, "HEARTBEAT_S", 0.02)
    assert _release(client, pv).status_code == 202
    assert entered.wait(10)
    first = _raw_state()["heartbeat_at"]
    _at(15, 5)
    end = time.monotonic() + 10
    while _raw_state()["heartbeat_at"] == first and time.monotonic() < end:
        time.sleep(0.02)
    assert timeutil.parse_iso(_raw_state()["heartbeat_at"]) == timeutil.parse_iso("2026-11-22T08:05:00+00:00")
    gate.set()
    assert _wait_done(client)["task"]["status"] == "SUCCEEDED"


def test_a_slow_summary_stops_with_status_timeout(bq, client, monkeypatch):
    _hold(D1, "A", 1.0, n=300)
    monkeypatch.setattr(hl, "SUMMARY_TIMEOUT_S", -1)              # the deadline has passed before the first row
    j = client.get("/api/held-lines").json()
    assert j["summary"]["status"] == "TIMEOUT" and j["summary"]["active_lines"] < 300


def _fake_storage(m, d, db=10_000, wal=1_000):
    (d / "bk").mkdir(parents=True, exist_ok=True)
    (d / "app.db").write_bytes(b"x" * db)
    if wal:
        (d / "app.db-wal").write_bytes(b"x" * wal)
    m.setattr(hl.paths, "db_path", lambda: d / "app.db")
    m.setattr(hl.paths, "backups_dir", lambda: d / "bk")


def test_the_disk_gate_without_a_backup_zip_uses_15_percent_of_the_database(tmp_path, monkeypatch):
    d = tmp_path / "fake"
    with monkeypatch.context() as m:        # only around _disk(): the database itself is never opened here
        _fake_storage(m, d)
        m.setattr(hl, "_free_bytes", lambda p: 18_750)
        x = hl._disk()
        assert (x["db_bytes"], x["wal_bytes"], x["zip_estimate_bytes"]) == (10_000, 1_000, 1_500)
        assert (x["need_bytes"], x["floor_bytes"], x["missing_bytes"], x["ok"]) == (18_750, 16_500, 0, True)   # just enough
        m.setattr(hl, "_free_bytes", lambda p: 18_749)
        x = hl._disk()
        assert x["ok"] is False and x["missing_bytes"] == 1
        with pytest.raises(AppError) as e:
            hl._check_disk()
        assert e.value.code == "HELD_RELEASE_DISK_SPACE" and "need 18750 B, free 18749 B, missing 1 B" in e.value.detail


def test_the_disk_gate_uses_the_newest_backup_zip(tmp_path, monkeypatch):
    import os
    d = tmp_path / "fake"
    with monkeypatch.context() as m:
        _fake_storage(m, d, wal=0)
        old, new = d / "bk" / "backup-20261101-000000-manual.zip", d / "bk" / "backup-20261117-000000-manual.zip"
        old.write_bytes(b"z" * 5_000)
        new.write_bytes(b"z" * 920)
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(new, (2_000_000, 2_000_000))
        m.setattr(hl, "_free_bytes", lambda p: 10 ** 9)
        x = hl._disk()
        assert x["zip_estimate_bytes"] == 920 and new.name in x["zip_estimate_from"] and x["need_bytes"] == 16_380
        new.write_bytes(b"")                                       # an empty zip: never below the floor
        os.utime(new, (2_000_000, 2_000_000))
        assert hl._disk()["need_bytes"] == hl._disk()["floor_bytes"] == 15_000


# ------------------------------------------------------------------ no switch: the buttons work at once, gates stay
def test_the_release_works_at_once_and_says_whether_locks_are_checked(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    j = client.get("/api/held-lines").json()
    pv = _preview(client)
    assert "enabled" not in j and "enabled" not in pv
    assert j["ops_lock_checked"] is False and pv["ops_lock_checked"] is False and pv["ops_locks"] == []
    t = _release(client, pv).json()["task"]
    assert t["status"] == "SUCCEEDED"


@pytest.mark.parametrize("change,code", [("job", "HELD_RELEASE_BUSY"), ("window", "HELD_RELEASE_BUSY"),
                                         ("schedule", "HELD_RELEASE_BUSY"), ("lock", "OPERATIONS_LOCK_HELD")])
def test_a_gate_that_fails_after_the_backup_writes_nothing(bq, client, monkeypatch, tmp_path, change, code):
    from app import backup
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client)
    real = backup.backup_database
    lock = tmp_path / "OPS_LOCK"
    monkeypatch.setenv("DF_OPS_LOCK", str(lock))           # set, file absent: no lock yet

    def backup_then_change(reason="manual", dest_dir=None):
        f = real(reason=reason, dest_dir=dest_dir)
        if change == "job":
            _job("D1_SYNC", "RUNNING")
        elif change == "window":
            _at(2, 0)
        elif change == "schedule":
            ss.update("schedule", {"report_time": "15:30"}, note="test")       # now within 90 minutes
        else:
            lock.write_text("{}")
        return f
    monkeypatch.setattr(backup, "backup_database", backup_then_change)
    values = _values()
    t = _release(client, pv).json()["task"]
    assert t["status"] == "FAILED" and t["error"]["code"] == code
    assert _values() == values and _count("SELECT COUNT(*) FROM demand_held_lines WHERE status='ACTIVE'") == 1
    assert _count("SELECT COUNT(*) FROM demand_sync_runs") == 0 and _count("SELECT COUNT(*) FROM demand_change_log") == 0
    assert [x for x in _backups() if x.endswith("-pre-hold-release.zip")]     # the backup is kept


def test_the_cli_path_ignores_the_api_gates(bq):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    _job("D1_SYNC", "RUNNING")
    out = history_sync.release_holds(SCOPE, apply=True)
    assert out["applied"] and _values()[(D1, "A", "F1")] == (6.0, 1)


@pytest.mark.parametrize("env,file", [("DF_OPS_LOCK", "LOCK"), ("DF_HEAVY_LOCK", "LOCK"), ("DF_RUN_DIR", "OPS_LOCK"),
                                      ("DF_RUN_DIR", "HEAVY_LOCK")])
def test_an_operations_lock_file_refuses_the_release(bq, client, monkeypatch, tmp_path, env, file):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    pv = _preview(client)
    lock = tmp_path / file
    monkeypatch.setenv(env, str(tmp_path if env == "DF_RUN_DIR" else lock))
    assert _preview(client)["ops_lock_checked"] is True
    lock.write_text("{}")
    before = _snapshot()
    r = _release(client, pv)
    assert r.status_code == 409 and _code(r) == "OPERATIONS_LOCK_HELD" and r.json()["params"]["locks"][0]["env"] == env
    assert _snapshot() == before and not hl._proc_lock.locked()
    lock.unlink()                                           # variable set, file gone: no lock
    assert _release(client, pv).status_code == 202


# ------------------------------------------------------------------ CV-NOSWITCH: one background write, daily cap, derived locks
def _other_task(state, heartbeat):
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET "
                  "value_json=excluded.value_json", (state, json.dumps({
                      "task_id": "X-1", "status": "RUNNING", "owner": "pid1-other", "started_at": heartbeat,
                      "heartbeat_at": heartbeat}), NOW_UTC))


def test_another_background_write_button_blocks_the_release(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    _other_task("sync_rollback", "2026-11-22T07:59:00+00:00")         # alive in another process (fresh heartbeat)
    pv = _preview(client)
    assert pv["busy_other_task"]["button"] == "SYNC_ROLLBACK"
    before = _snapshot()
    r = _release(client, pv)
    assert r.status_code == 409 and _code(r) == "HEAVY_WRITE_ANOTHER_RUNNING" and r.json()["params"]["task_id"] == "X-1"
    assert _snapshot() == before and not hl._proc_lock.locked()
    _other_task("sync_rollback", "2026-11-22T03:00:00+00:00")         # interrupted (no heartbeat for 5 h): never blocks
    assert _preview(client)["busy_other_task"] is None
    assert _release(client, pv).json()["task"]["status"] == "SUCCEEDED"


def _committed_release(holds):
    _SEQ[0] += 1
    with db.tx() as c:
        c.execute("INSERT INTO demand_sync_runs(id, kind, status, scope_key, policy, started_at, finished_at, "
                  "summary_json) VALUES (?, 'HOLD_RELEASE', 'COMMITTED', ?, 'KEEP_OBSERVED_LINES', ?, ?, ?)",
                  (f"HRL-T{_SEQ[0]}", SCOPE, "2026-11-22T06:00:00+00:00", "2026-11-22T06:00:00+00:00",
                   json.dumps({"holds": holds})))


def test_the_daily_cap_of_releases_and_lines(bq, client):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 1.0)
    _hold(D1, "A", 1.0)
    _committed_release(1349)
    pv = _preview(client)
    assert pv["daily"] == {"releases_used": 1, "releases_left": 2, "lines_used": 1349, "lines_left": 1,
                           "max_releases": 3, "max_lines": 1350}
    r = _release(client, pv)                                       # 2 lines > 1 left
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_DAILY_LIMIT" and r.json()["params"]["lines_left"] == 1
    _committed_release(0)
    _committed_release(0)                                           # 3 releases today
    r = _release(client, _preview(client))
    assert r.status_code == 409 and _code(r) == "HELD_RELEASE_DAILY_LIMIT" and r.json()["params"]["releases_left"] == 0
    assert not hl._proc_lock.locked()


def test_the_operations_locks_use_the_run_folder_derived_from_the_data_folder(bq, client, monkeypatch, tmp_path):
    _row(D1, "A", 9.0)
    _hold(D1, "A", 3.0)
    data = tmp_path / "root" / "data" / "runtime"
    data.mkdir(parents=True)
    monkeypatch.setattr(hl, "_app_data_dir", lambda: data)
    pv = _preview(client)
    assert pv["ops_lock_checked"] is False and pv["ops_lock_source"] is None      # no run folder: not checked
    (tmp_path / "root" / "run").mkdir()
    pv = _preview(client)
    assert pv["ops_lock_checked"] is True and pv["ops_lock_source"] == "derived" and pv["ops_locks"] == []
    (tmp_path / "root" / "run" / "HEAVY_LOCK").write_text("{}")
    r = _release(client, pv)
    assert r.status_code == 409 and _code(r) == "OPERATIONS_LOCK_HELD" and r.json()["params"]["locks"][0]["env"] == "DERIVED"
    monkeypatch.setenv("DF_OPS_LOCK", str(tmp_path / "none"))                    # a variable set: the derived folder is not used
    assert _preview(client)["ops_lock_source"] == "env"
