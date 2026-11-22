"""1.4.15 lot 4: read the open hours again (api/open_hours_routes.py).

Integration with fakes: TestClient on the isolated temporary database (conftest) and a FAKE BigQuery client
(tests/fake_bq.FakeBQ through connector.set_client_factory) - no real BigQuery, no real data, no network.
Covers: read-only plan (stored / missing days, reads, dry-run bytes); day limit and data window; confirmation text and
reason; busy; FILL_MISSING_DAYS_ONLY (a stored day is never read, a row stored meanwhile is never overwritten); a
source NULL stays NULL and a day without source rows gets no row (MISSING, never 0); no refresh watermark written;
background state and audit; two clicks; plan changed; interrupted task; failure; the SELECT is the one of
aux_sources.fetch_open_hours.
"""
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from app import db, timeutil
from app.api import background
from app.api import held_lines_routes as hl
from app.api import open_hours_routes as oh
from app.bq import aux_sources, connector
from app.jobs import runner
from app.messages import CATALOG
from app.timeutil import VN_TZ
from fake_bq import FakeBQ

TODAY = "2026-11-22"
CONFIRM = f"DOC-LAI-GIO-MO-BAN-{TODAY}"
REASON = "chu du an duyet doc lai gio mo ban"
D1, D2, D3, D4, D5 = "2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"


@pytest.fixture(autouse=True)
def _frozen_day():
    timeutil.set_now_override(lambda: datetime(2026, 11, 22, 15, 0, tzinfo=VN_TZ))   # no default schedule time near
    yield


class Source(FakeBQ):
    """Open-hours source: {(day, fc, sku): hours or None}; `on_read` runs before a (non dry run) read returns."""

    def __init__(self, data=None, on_read=None):
        super().__init__(responses={})
        self.data = dict(data or {})
        self.on_read = on_read
        self.responses["open_hours_reread"] = self._rows

    def _rows(self, cfg):
        p = {n: v for n, _t, v in cfg["params"]}
        if self.on_read:
            self.on_read(p)
        return [{"fc_code": fc, "sku_code": sku, "open_date": d, "total_open_hours": h, "n_items": 1}
                for (d, fc, sku), h in sorted(self.data.items()) if str(p["start"]) <= d <= str(p["end"])]

    def reads(self):
        """(start, end) of every real (not dry run) read."""
        out = []
        for _sql, cfg in self.queries:
            if not cfg.get("dry_run"):
                p = {n: v for n, _t, v in cfg["params"]}
                out.append((str(p["start"]), str(p["end"])))
        return out


@pytest.fixture
def src(client, monkeypatch):
    s = Source()
    connector.set_client_factory(s)
    for k in (*hl.LOCK_ENV, hl.RUN_DIR_ENV):     # no operations lock variable unless a test sets one
        monkeypatch.delenv(k, raising=False)
    return s


def _store(d, fc="F1", sku="A", hours=5.0, loaded="2026-11-10T00:00:00+00:00"):
    table, seller = aux_sources.open_hours_source()
    with db.tx() as c:
        c.execute("INSERT INTO open_hours_daily(source_table, seller_code, fc_code, sku_code, open_date, total_open_hours, "
                  "n_items, loaded_at) VALUES (?,?,?,?,?,?,1,?)", (table, seller, fc, sku, d, hours, loaded))


def _stored() -> dict:
    with db.read() as c:
        return {(r[0], r[1], r[2]): r[3] for r in c.execute(
            "SELECT open_date, fc_code, sku_code, total_open_hours FROM open_hours_daily")}


def _count(sql, p=()) -> int:
    with db.read() as c:
        return c.execute(sql, p).fetchone()[0]


def _audit(action) -> int:
    return _count("SELECT COUNT(*) FROM audit_log WHERE action=?", (action,))


def _snapshot() -> dict:
    return {"oh": _stored(), "reads": _count("SELECT COUNT(*) FROM aux_source_reads"),
            "audit": _count("SELECT COUNT(*) FROM audit_log"), "state": _count("SELECT COUNT(*) FROM sync_state")}


def _plan(client, start=D1, end=D5, estimate=False):
    r = client.get("/api/open-hours-reread/plan", params={"start": start, "end": end, "estimate": estimate})
    assert r.status_code == 200, r.json()
    return r.json()


def _run(client, p, **kw):
    body = {"start": p["start"], "end": p["end"], "signature": p["signature"], "confirm_text": CONFIRM, "reason": REASON}
    body.update(kw)
    return client.post("/api/open-hours-reread", json=body)


def _code(r):
    return r.json()["code"]


def _wait_done(client, timeout=10.0) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        st = client.get("/api/open-hours-reread/status").json()
        if not st["running"]:
            return st
        time.sleep(0.02)
    raise AssertionError("re-read still running")


# ------------------------------------------------------------------ plan (read-only)
def test_the_plan_lists_stored_and_missing_days_and_dry_run_bytes_and_writes_nothing(src, client):
    _store(D1)
    _store(D1, sku="B")
    _store(D3)
    before = _snapshot()
    p = _plan(client, estimate=True)
    assert (p["days"], p["days_stored"], p["days_missing"], p["stored_rows"]) == (5, 2, 3, 3)
    assert p["missing_days"] == [D2, D4, D5] and p["reads"][0]["start"] == D2 and p["reads"][1]["end"] == D5
    assert p["estimated_bytes"] == 2 * src.bytes and p["mode"] == "FILL_MISSING_DAYS_ONLY" and len(p["signature"]) == 64
    assert src.queries and all(cfg.get("dry_run") for _sql, cfg in src.queries)     # dry runs only
    assert p["confirm_text"] == CONFIRM and p["max_days"] == 60
    assert _snapshot() == before


def test_the_plan_without_estimate_does_not_query_bigquery(src, client):
    p = _plan(client)
    assert p["estimated_bytes"] is None and src.queries == []


def test_the_range_is_limited_to_60_days_inside_the_data_window(src, client):
    ok = _plan(client, start="2026-09-23", end="2026-11-21")                         # exactly 60 days
    assert ok["days"] == 60
    for start, end, code in (("2026-09-22", "2026-11-21", "OPEN_HOURS_REREAD_TOO_MANY_DAYS"),
                             (D1, TODAY, "OPEN_HOURS_REREAD_INVALID_RANGE"),          # today is not complete
                             ("2025-12-31", "2026-01-05", "OPEN_HOURS_REREAD_INVALID_RANGE"),   # before the window
                             (D2, D1, "OPEN_HOURS_REREAD_INVALID_RANGE"), ("2026-11-1", D2, "OPEN_HOURS_REREAD_INVALID_RANGE")):
        r = client.get("/api/open-hours-reread/plan", params={"start": start, "end": end})
        assert r.status_code == 422 and _code(r) == code, (start, end)


# ------------------------------------------------------------------ gates
def test_wrong_confirmation_text_or_short_reason_writes_nothing(src, client):
    p = _plan(client)
    before = _snapshot()
    for kw in ({"confirm_text": "DOC-LAI-GIO-MO-BAN-2026-11-21"}, {"confirm_text": None}, {"reason": "ngan"}):
        r = _run(client, p, **kw)
        assert r.status_code == 409 and _code(r) == "OPEN_HOURS_REREAD_CONFIRM_REQUIRED", kw
    assert _snapshot() == before and src.queries == [] and not oh._proc_lock.locked()


def test_busy_jobs_and_production_windows_refuse(src, client):
    p = _plan(client)
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, created_at) VALUES "
                  "('J-1', 'FORECAST_REFRESH', 'k1', 'MANUAL', 'RUNNING', '2026-11-22T07:30:00+00:00')")
    r = _run(client, p)
    assert r.status_code == 409 and _code(r) == "OPEN_HOURS_REREAD_BUSY"
    with db.tx() as c:
        c.execute("UPDATE job_runs SET status='SUCCEEDED' WHERE id='J-1'")
    timeutil.set_now_override(lambda: datetime(2026, 11, 22, 23, 0, tzinfo=VN_TZ))   # before 23:45 / eod_time
    r = _run(client, p)
    assert r.status_code == 409 and _code(r) == "OPEN_HOURS_REREAD_BUSY" and r.json()["params"]["window_soon"] == "23:45"
    assert src.queries == [] and _count("SELECT COUNT(*) FROM open_hours_daily") == 0 and not oh._proc_lock.locked()


def test_a_plan_whose_missing_days_changed_is_refused(src, client):
    p = _plan(client)
    _store(D4)
    r = _run(client, p)
    assert r.status_code == 409 and _code(r) == "OPEN_HOURS_REREAD_PLAN_STALE" and src.queries == []
    _store(D1), _store(D2), _store(D3), _store(D5)
    r = _run(client, _plan(client) | {"signature": "x"})
    assert r.status_code == 409 and _code(r) == "OPEN_HOURS_REREAD_NOTHING"


# ------------------------------------------------------------------ the re-read itself
def test_only_missing_days_are_read_and_stored_values_are_never_overwritten(src, client):
    _store(D1, hours=5.0)
    src.data = {(D1, "F1", "A"): 9.0, (D2, "F1", "A"): 8.0, (D2, "F1", "B"): 7.5, (D3, "F1", "A"): 6.0}

    def meanwhile(p):           # the refresh stores D2 / A while the re-read of D2..D5 runs
        if str(p["start"]) <= D2 <= str(p["end"]) and (D2, "F1", "A") not in _stored():
            _store(D2, hours=3.0)
    src.on_read = meanwhile
    reads_before = _count("SELECT COUNT(*) FROM aux_source_reads")
    r = _run(client, _plan(client))
    assert r.status_code == 202
    t = r.json()["task"]
    assert t["status"] == "SUCCEEDED" and t["error"] is None
    s = _stored()
    assert s[(D1, "F1", "A")] == 5.0                    # a stored day is not read again
    assert s[(D2, "F1", "A")] == 3.0                    # stored meanwhile: never overwritten
    assert (D2, "F1", "B") not in s                     # ... and that day is skipped whole: never completed halfway
    assert s[(D3, "F1", "A")] == 6.0
    assert src.reads() == [(D2, D5)]                    # D1 never read
    res = t["result"]
    assert (res["rows_read"], res["inserted"], res["skipped_existing"]) == (3, 1, 2)
    assert res["reads"][0]["skipped_days_stored_meanwhile"] == [D2]
    assert res["undo"]["loaded_at"] == t["loaded_at"]
    assert _count("SELECT COUNT(*) FROM aux_source_reads") == reads_before        # the refresh watermark is untouched
    assert _audit("OPEN_HOURS_REREAD_REQUESTED") == 1 and _audit("OPEN_HOURS_REREAD_DONE") == 1
    with db.read() as c:
        a = json.loads(c.execute("SELECT details_json FROM audit_log WHERE action='OPEN_HOURS_REREAD_DONE'").fetchone()[0])
    assert a["result"]["reads"][0]["rows_read"] == 3 and a["result"]["estimated_bytes"] == src.bytes


def test_a_source_null_stays_null_and_a_day_without_source_rows_stays_missing(src, client):
    src.data = {(D2, "F1", "A"): None, (D3, "F1", "A"): 0.0}
    t = _run(client, _plan(client, start=D2, end=D4)).json()["task"]
    assert t["status"] == "SUCCEEDED"
    s = _stored()
    assert (D2, "F1", "A") in s and s[(D2, "F1", "A")] is None      # MISSING, never 0
    assert s[(D3, "F1", "A")] == 0.0                                   # a real 0 of the source is kept as 0
    assert not [k for k in s if k[0] == D4]                            # no source row: no row (MISSING)


def test_two_clicks_start_one_re_read(src, client, monkeypatch):
    gate, entered = threading.Event(), threading.Event()
    src.data = {(D2, "F1", "A"): 4.0}

    def slow(p):
        entered.set()
        assert gate.wait(10)
    src.on_read = slow
    monkeypatch.setattr(background, "SYNC_MODE", False)
    p = _plan(client)
    r1 = _run(client, p)
    assert r1.status_code == 202 and r1.json()["task"]["status"] == "RUNNING"
    assert entered.wait(10)
    r2 = _run(client, p)
    assert r2.status_code == 409 and _code(r2) == "OPEN_HOURS_REREAD_RUNNING"
    assert client.get("/api/open-hours-reread/status").json()["task"]["status"] == "RUNNING"
    gate.set()
    st = _wait_done(client)
    assert st["task"]["status"] == "SUCCEEDED" and len(src.reads()) == 1
    assert not oh._proc_lock.locked() and oh._current["task_id"] is None


def test_a_bigquery_failure_is_recorded_and_frees_the_lock(src, client):
    src.errors["open_hours_reread"] = RuntimeError("boom")
    t = _run(client, _plan(client)).json()["task"]
    assert t["status"] == "FAILED" and t["error"]["code"].startswith("BQ_")
    assert _audit("OPEN_HOURS_REREAD_FAILED") == 1 and _count("SELECT COUNT(*) FROM open_hours_daily") == 0
    assert not oh._proc_lock.locked()


def test_a_re_read_cut_by_an_app_stop_is_interrupted_and_never_blocks(src, client):
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?,?,?)",
                  (oh.STATE, json.dumps({"task_id": "OHR-OLD", "status": "RUNNING", "owner": "pid1-dead00",
                                         "started_at": "2026-11-22T03:00:00+00:00",
                                         "heartbeat_at": "2026-11-22T03:00:00+00:00"}), "x"))
    assert client.get("/api/open-hours-reread/status").json()["task"]["status"] == "INTERRUPTED"
    src.data = {(D2, "F1", "A"): 4.0}
    assert _run(client, _plan(client)).json()["task"]["status"] == "SUCCEEDED"
    assert _audit("OPEN_HOURS_REREAD_INTERRUPTED") == 1
    with db.tx() as c:          # this process's own task whose thread is gone
        c.execute("UPDATE sync_state SET value_json=? WHERE name=?",
                  (json.dumps({"task_id": "OHR-X", "status": "RUNNING", "owner": runner.OWNER,
                               "heartbeat_at": "2026-11-22T08:00:00+00:00"}), oh.STATE))
    assert client.get("/api/open-hours-reread/status").json()["task"]["status"] == "INTERRUPTED"


# ------------------------------------------------------------------ the SELECT and the catalogue
def test_the_select_is_the_one_of_aux_sources_fetch_open_hours(src):
    aux_sources.fetch_open_hours(D1, D1)
    sql = next(s for s, cfg in src.queries if not cfg.get("dry_run"))
    assert sql.split("\n", 1)[1] == oh._sql(aux_sources.open_hours_source()[0])


def test_every_code_of_the_module_is_in_the_catalogue():
    s = Path(oh.__file__).read_text(encoding="utf-8")
    codes = set(re.findall(r'AppError\(\s*"([A-Z_]+)"', s)) | set(re.findall(r'"code": "([A-Z_]+)"', s))
    assert {"OPEN_HOURS_REREAD_BUSY", "OPEN_HOURS_REREAD_INTERRUPTED"} <= codes
    assert not sorted(c for c in codes if c not in CATALOG)


# ------------------------------------------------------------------ no switch: works at once; locks; description
def test_the_re_read_works_at_once_and_the_plan_describes_the_button(src, client):
    src.data = {(D2, "F1", "A"): 4.0}
    p = _plan(client)
    assert "enabled" not in p and p["ops_lock_checked"] is False
    assert p["description_codes"] == list(oh.DESCRIPTION_CODES)
    assert [x["code"] for x in p["description"]] == list(oh.DESCRIPTION_CODES)
    assert all(x["vi"] != x["en"] and x["vi"] != x["code"] for x in p["description"])
    assert client.get("/api/open-hours-reread/status").json()["description_codes"] == list(oh.DESCRIPTION_CODES)
    assert _run(client, p).json()["task"]["status"] == "SUCCEEDED"


def test_an_operations_lock_file_refuses_the_re_read(src, client, monkeypatch, tmp_path):
    monkeypatch.setenv("DF_RUN_DIR", str(tmp_path))
    (tmp_path / "HEAVY_LOCK").write_text("{}")
    p = _plan(client)
    assert p["ops_lock_checked"] is True and p["ops_locks"][0]["env"] == "DF_RUN_DIR"
    r = _run(client, p)
    assert r.status_code == 409 and _code(r) == "OPERATIONS_LOCK_HELD" and src.queries == []


def test_a_lock_taken_during_the_read_writes_nothing_more(src, client, monkeypatch, tmp_path):
    lock = tmp_path / "OPS_LOCK"
    monkeypatch.setenv("DF_OPS_LOCK", str(lock))
    src.data = {(D2, "F1", "A"): 4.0}
    src.on_read = lambda p: lock.write_text("{}")
    t = _run(client, _plan(client)).json()["task"]
    assert t["status"] == "FAILED" and t["error"]["code"] == "OPERATIONS_LOCK_HELD"
    assert _count("SELECT COUNT(*) FROM open_hours_daily") == 0


def test_a_schedule_time_near_now_refuses_the_re_read(src, client):
    from app import settings_service as ss
    ss.update("schedule", {"report_time": "16:00"}, note="test")
    r = _run(client, _plan(client))
    assert r.status_code == 409 and _code(r) == "OPEN_HOURS_REREAD_BUSY"
    assert r.json()["params"]["schedule_times"] == [{"setting": "schedule.report_time", "time": "16:00"}]


# ------------------------------------------------------------------ REV-A: the task's own source; never an override
def test_the_task_reads_its_own_source_and_stops_when_the_setting_changes(src, client):
    from app import settings_service as ss
    _store(D3)                                           # D2 and D4 missing: two separate reads
    table, seller = aux_sources.open_hours_source()
    src.data = {(D2, "F1", "A"): 4.0, (D4, "F1", "A"): 5.0}
    changed = []

    def change_seller(p):
        if not changed:
            changed.append(1)
            ss.update("daily_forecast", {"seller_code": "OTHER"}, note="test: changed during the re-read")
    src.on_read = change_seller
    t = _run(client, _plan(client, start=D2, end=D4)).json()["task"]
    assert t["status"] == "FAILED" and t["error"]["code"] == "OPEN_HOURS_REREAD_CONFIG_CHANGED"
    with db.read() as c:
        rows = c.execute("SELECT source_table, seller_code, open_date FROM open_hours_daily WHERE open_date=?",
                         (D2,)).fetchall()
    assert [tuple(r) for r in rows] == [(table, seller, D2)]          # the first read wrote under the task's source
    sellers = {v for _sql, cfg in src.queries if not cfg.get("dry_run") for n, _t, v in cfg["params"] if n == "seller"}
    assert sellers == {seller} and src.reads() == [(D2, D2)]


def test_the_re_read_never_calls_the_open_hours_override(src, client, monkeypatch):
    import inspect
    from app.data import open_hours_override as oho
    called = []
    for name, fn in inspect.getmembers(oho, inspect.isfunction):
        if fn.__module__ == oho.__name__:
            monkeypatch.setattr(oho, name, lambda *a, _n=name, **k: called.append(_n))
    src.data = {(D2, "F1", "A"): None, (D3, "F1", "A"): 4.0}
    assert _run(client, _plan(client, start=D2, end=D3)).json()["task"]["status"] == "SUCCEEDED"
    assert called == [] and _stored()[(D2, "F1", "A")] is None


# ------------------------------------------------------------------ CV-NOSWITCH: one background write across the buttons
def test_a_running_release_blocks_the_re_read(src, client):
    with db.tx() as c:
        c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?,?,?)",
                  ("held_lines_release", json.dumps({"task_id": "HLT-X", "status": "RUNNING", "owner": "pid1-other",
                                                     "started_at": "2026-11-22T07:59:00+00:00",
                                                     "heartbeat_at": "2026-11-22T07:59:00+00:00"}), "x"))
    p = _plan(client)
    assert p["busy_other_task"]["button"] == "HELD_LINES_RELEASE"
    r = _run(client, p)
    assert r.status_code == 409 and _code(r) == "HEAVY_WRITE_ANOTHER_RUNNING" and src.queries == []
    assert "OH_REREAD_CHANGES_SEL2_NUMBERS" in p["description_codes"]
