"""1.3.2 review fix round (task G3-T3): the behaviour added after the reviews of the deal data layer and the extra
features. Temporary data only (conftest); BigQuery is the DealFake of test_v132_deal_data.py, nothing real is read.

A. data layer: EMPTY_DEAL_READ refusal and --allow-empty; the D-1 / backfill hook loads month by month and stops at the
   first failing month; a refresh with the same content keeps the stored deals; the five deal data checks; the CLI
   --apply refusal while the app runs or a job is active.
B. model layer: the coverage gates of check_sources (history months / committed sync runs, deal-line loads), the
   training refusal and the recorded coverage, the daily refresh NotReady; the chunked DB reader (DealLines / Rows) gives
   the same features as the frame path.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app import cli, data_checks, db, paths, timeutil
from app import settings_service as ss
from app.messages import AppError
from test_v132_deal_data import (DEAL_TABLE, DEALS, EXT, SCOPE, WINDOW, _alerts, _backfill, _d, _deal, _lines,
                                 _month_chunks, _n, _production, _q, _snaps)

UTC = timezone.utc
NOW = datetime(2026, 10, 30, 1, 0, tzinfo=UTC)          # 08:00 on 30/10/2026 in Vietnam: yesterday = 29/10
Y = date(2026, 10, 29)


@pytest.fixture
def frozen():
    timeutil.set_now_override(lambda: NOW)


def _cli(capsys, *argv) -> tuple[int, dict]:
    """The command's JSON object (printed with indent=2: it starts at a line that is exactly '{'); log lines a stdout
    handler may print around it are skipped."""
    capsys.readouterr()
    rc = cli.main(list(argv))
    lines = capsys.readouterr().out.splitlines()
    start = max(i for i, x in enumerate(lines) if x == "{")
    end = next(i for i in range(start, len(lines)) if lines[i] == "}")
    return rc, json.loads("\n".join(lines[start:end + 1]))


def _loads() -> list[tuple]:
    return _q("SELECT trigger, range_start, range_end, rows_written, rows_removed FROM deal_line_loads ORDER BY rowid")


# ================================================================== A1. EMPTY_DEAL_READ
def test_empty_deal_read_keeps_the_stored_lines_unless_allowed(frozen):
    from app.bq import deal_lines
    from app import sync
    fake = _production(_d(WINDOW), deal_col="deal_code")
    assert sync.run_d1_sync("J1")["deal_lines"]["status"] == "SUCCEEDED"
    m0 = Y.replace(day=1)
    stored = _lines(str(m0), str(Y))
    assert stored and _n("deal_line_loads") == len(_month_chunks(_d(WINDOW), Y))
    n_loads = _n("deal_line_loads")
    # the order lines of October are still read (TOTAL > 0) but none carries a deal code any more
    fake.lines = [r for r in fake.lines if r["order_date"] < m0]
    with pytest.raises(AppError) as e:
        deal_lines.load_window(SCOPE, m0, Y, "MANUAL")
    assert e.value.code == "DEAL_LINES_LOAD_FAILED"
    det = json.loads(e.value.detail)
    assert det["reason"] == "EMPTY_DEAL_READ" and det["window"] == [str(m0), str(Y)]
    assert det["rows_stored"] == len(stored) and det["lines_read"] > 0
    assert _lines(str(m0), str(Y)) == stored and _n("deal_line_loads") == n_loads      # nothing deleted / recorded
    # an explicit decision: the window really has no deal any more -> replaced by nothing, one load recorded
    res = deal_lines.load_window(SCOPE, m0, Y, "MANUAL", allow_empty=True)
    assert (res["rows_written"], res["rows_removed"]) == (0, len(stored))
    assert _lines(str(m0), str(Y)) == [] and _n("deal_line_loads") == n_loads + 1
    assert _loads()[-1] == ("MANUAL", str(m0), str(Y), 0, len(stored))
    assert _lines(WINDOW, str(m0 - timedelta(days=1)))                                  # other months untouched
    # a window without stored lines: an empty deal read is a normal load (nothing to protect)
    res = deal_lines.load_window(SCOPE, m0, Y, "MANUAL")
    assert (res["rows_written"], res["rows_removed"]) == (0, 0)


def test_empty_read_without_any_order_line_is_refused_even_with_allow_empty(frozen):
    from app.bq import deal_lines
    from app import sync
    fake = _production(_d(WINDOW), deal_col="deal_code")
    sync.run_d1_sync("J1")
    m0 = Y.replace(day=1)
    stored = _lines(str(m0), str(Y))
    fake.lines = [r for r in fake.lines if r["order_date"] < m0]
    fake.src = [r for r in fake.src if r["order_date"] < m0]            # TOTAL n_rows 0: the table is being rebuilt
    for allow in (False, True):
        with pytest.raises(AppError) as e:
            deal_lines.load_window(SCOPE, m0, Y, "MANUAL", allow_empty=allow)
        assert e.value.code == "DEAL_LINES_LOAD_FAILED" and json.loads(e.value.detail)["reason"] == "EMPTY_READ"
    assert _lines(str(m0), str(Y)) == stored


def test_the_d1_hook_never_replaces_stored_lines_by_an_empty_deal_read(frozen):
    from app import sync
    fake = _production(_d(WINDOW), deal_col="deal_code")
    sync.run_d1_sync("J1")
    before = _lines()
    n_loads = _n("deal_line_loads")
    fake.lines = []
    out = sync.run_d1_sync("J2")                                        # incremental: its window has stored lines
    assert out["status"] == "SUCCEEDED" and out["deal_lines"]["status"] == "FAILED"
    assert out["deal_lines"]["error"]["code"] == "DEAL_LINES_LOAD_FAILED"
    assert "EMPTY_DEAL_READ" in out["deal_lines"]["error"]["detail"]
    assert _lines() == before and _n("deal_line_loads") == n_loads
    al = _alerts("DEAL_LINES_LOAD_FAILED")
    assert len(al) == 1 and al[0][0] == "WARNING"


def test_cli_deal_lines_load_allow_empty(frozen, capsys):
    from app import sync
    fake = _production(_d(WINDOW), deal_col="deal_code")
    sync.run_d1_sync("J1")
    m0 = Y.replace(day=1)
    stored = _lines(str(m0), str(Y))
    fake.lines = [r for r in fake.lines if r["order_date"] < m0]
    rc, out = _cli(capsys, "deal-lines-load", "--start", str(m0), "--end", str(Y), "--apply")
    assert rc == 1 and out["ok"] is False and out["stopped_at"] == str(m0)
    ch = out["chunks"][-1]
    assert ch["status"] == "FAILED" and ch["error"]["code"] == "DEAL_LINES_LOAD_FAILED"
    assert "EMPTY_DEAL_READ" in ch["error"]["detail"]
    assert _lines(str(m0), str(Y)) == stored
    rc, out = _cli(capsys, "deal-lines-load", "--start", str(m0), "--end", str(Y), "--apply", "--allow-empty")
    assert rc == 0 and out["chunks"][-1]["status"] == "SUCCEEDED" and out["chunks"][-1]["rows_removed"] == len(stored)
    assert _lines(str(m0), str(Y)) == []


# ================================================================== A2. month chunks of the hook
def test_full_reload_hook_stops_at_the_first_failing_month_and_keeps_the_earlier_ones(frozen):
    from app import sync
    fake = _production(_d(WINDOW), deal_col="deal_code")
    bad_day = date(2026, 3, 15)                                         # A has 5 units: 7 of a deal cannot be
    fake.lines = [{**r, "qty": 7.0} if (r["order_date"] == bad_day and r["sku_id"] == "A") else r for r in fake.lines]
    out = sync.run_d1_sync("J1")
    assert out["status"] == "SUCCEEDED" and out["full_reload"]
    dl = out["deal_lines"]
    assert dl["status"] == "FAILED" and dl["failed_chunk"] == {"start": "2026-03-01", "end": "2026-03-31"}
    assert [(c["window"]["start"], c["window"]["end"]) for c in dl["chunks"]] == [
        ("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28")]
    # one query per month up to the failing one, then the loop stops (no read of April .. October)
    assert [(_d(c["params"][0][2]), _d(c["params"][1][2])) for _, c in fake.deal_sent("deal_lines")] == [
        (date(2026, 1, 1), date(2026, 1, 31)), (date(2026, 2, 1), date(2026, 2, 28)), (date(2026, 3, 1), date(2026, 3, 31))]
    assert [x[:3] for x in _loads()] == [("D1_SYNC", "2026-01-01", "2026-01-31"), ("D1_SYNC", "2026-02-01", "2026-02-28")]
    assert len(_lines("2026-01-01", "2026-02-28")) == len([r for r in fake.lines if date(2026, 1, 1) <= r["order_date"]
                                                           <= date(2026, 2, 28)])
    assert _lines("2026-03-01", str(Y)) == []
    al = _alerts("DEAL_LINES_EXCEED_DEMAND")
    assert len(al) == 1 and al[0][0] == "WARNING"
    p = json.loads(al[0][1])
    assert p["window"] == [WINDOW, str(Y)] and p["failed_chunk"] == {"start": "2026-03-01", "end": "2026-03-31"}
    assert p["chunks_done"] == [{"start": "2026-01-01", "end": "2026-01-31"}, {"start": "2026-02-01", "end": "2026-02-28"}]
    assert p["trigger"] == "D1_SYNC" and p["job_id"] == "J1"
    assert _demand_days() == (_d(WINDOW), Y)                            # the demand of the whole window is written


def _demand_days():
    r = _q("SELECT MIN(order_date), MAX(order_date) FROM demand_daily WHERE scope_key=?", SCOPE)[0]
    return _d(r[0]), _d(r[1])


def test_a_failing_first_month_writes_no_deal_line(frozen):
    from app import sync
    fake = _production(_d(WINDOW), deal_col="deal_code")
    fake.lines = fake.lines + [{"order_date": date(2026, 1, 2), "sku_id": "ZZ", "fc_id": "F1", "deal_code": "D1",
                                "qty": 1.0, "n_rows": 1}]               # a key without stored demand in January
    out = sync.run_d1_sync("J1")
    assert out["deal_lines"]["status"] == "FAILED" and out["deal_lines"]["chunks"] == []
    assert out["deal_lines"]["failed_chunk"] == {"start": "2026-01-01", "end": "2026-01-31"}
    assert (_n("demand_deal_daily"), _n("deal_line_loads")) == (0, 0) and len(fake.deal_sent("deal_lines")) == 1
    assert json.loads(_alerts("DEAL_LINES_EXCEED_DEMAND")[0][1])["chunks_done"] == []


def test_a_backfill_over_two_months_loads_one_backfill_row_per_month(frozen):
    _production(deal_col="deal_code", ext=EXT)
    from app import sync
    sync.run_d1_sync("J1")
    n0 = _n("deal_line_loads")
    out = _backfill("2025-11-25", "2025-12-05")
    assert out["deal_lines"]["status"] == "SUCCEEDED"
    assert _q("SELECT trigger, range_start, range_end, job_id FROM deal_line_loads ORDER BY rowid")[n0:] == [
        ("BACKFILL", "2025-11-25", "2025-11-30", "JB"), ("BACKFILL", "2025-12-01", "2025-12-05", "JB")]
    assert out["backfill_floor"] == EXT


def test_months_splits_at_calendar_month_ends_including_leap_february():
    from app.bq import deal_lines
    for s, e in [(date(2024, 1, 31), date(2024, 3, 1)), (date(2025, 12, 31), date(2026, 1, 1)),
                 (date(2026, 2, 1), date(2026, 2, 28)), (date(2025, 11, 1), date(2026, 10, 29)), (date(2026, 5, 5),
                                                                                                    date(2026, 5, 5))]:
        assert deal_lines.months(s, e) == _month_chunks(s, e)
    assert deal_lines.months(date(2024, 2, 10), date(2024, 3, 2)) == [(date(2024, 2, 10), date(2024, 2, 29)),
                                                                     (date(2024, 3, 1), date(2024, 3, 2))]
    assert deal_lines.months(date(2026, 3, 2), date(2026, 3, 1)) == []


# ================================================================== A3. same-content refresh
def _deal_rows() -> list[tuple]:
    return _q("SELECT rowid, row_no, deal_code, sku_code, fc_code, snapshot_id FROM deals ORDER BY rowid")


def test_same_content_keeps_the_stored_deals_and_changed_content_rewrites_them(frozen):
    from app.bq import deal_source
    fake = _production(_d(WINDOW), deal_table=DEAL_TABLE)
    fake.deal_rows = DEALS
    r1 = deal_source.refresh("MANUAL")
    assert r1["deals_rewritten"] is True and r1["same_as"] is None and r1["deals_snapshot_id"] == r1["snapshot_id"]
    rows1 = _deal_rows()
    assert {r[5] for r in rows1} == {r1["snapshot_id"]}
    fake.deal_rows = list(reversed(DEALS))                              # same content, other order
    r2 = deal_source.refresh("MANUAL")
    assert (r2["same_as"], r2["rows_stored"], r2["deals_rewritten"], r2["replaced_deals"]) == (
        r1["snapshot_id"], False, False, 0)
    assert r2["deals_snapshot_id"] == r1["snapshot_id"]
    assert _deal_rows() == rows1                                        # same rowids: not deleted / inserted again
    # changed content: rewritten, pointing at the new snapshot (which holds the rows)
    fake.deal_rows = DEALS[:2] + [_deal("D4", "A")]
    r3 = deal_source.refresh("MANUAL")
    assert r3["deals_rewritten"] is True and r3["same_as"] is None and r3["replaced_deals"] == 4
    assert {r[5] for r in _deal_rows()} == {r3["snapshot_id"]} and _n("deals") == 3
    rows3 = _deal_rows()
    # the same as r3 again: kept, the new snapshot points at r3
    r4 = deal_source.refresh("MANUAL")
    assert r4["same_as"] == r3["snapshot_id"] and r4["deals_rewritten"] is False and _deal_rows() == rows3
    # back to the first content: compared with the LATEST snapshot only (r4 = r3's content) -> a new snapshot with
    # its own rows, the deals rewritten
    fake.deal_rows = DEALS
    r5 = deal_source.refresh("MANUAL")
    assert r5["same_as"] is None and r5["deals_rewritten"] is True
    assert {r[5] for r in _deal_rows()} == {r5["snapshot_id"]}
    st = {x["check"]: x["status"] for x in data_checks.run(paths.db_path())["checks"]}
    assert st["deal_snapshot_same_as"] == "OK" and st["deals_latest_snapshot"] == "OK"


def test_same_content_but_stored_deals_not_of_that_snapshot_are_rewritten_with_the_holder(frozen):
    from app.bq import deal_source
    fake = _production(_d(WINDOW), deal_table=DEAL_TABLE)
    fake.deal_rows = DEALS
    r1 = deal_source.refresh("MANUAL")
    with db.tx() as c:                                                  # one stored deal lost (e.g. a restore)
        c.execute("DELETE FROM deals WHERE source_table=? AND row_no=1", (DEAL_TABLE,))
    r2 = deal_source.refresh("MANUAL")
    assert r2["same_as"] == r1["snapshot_id"] and r2["deals_rewritten"] is True and r2["replaced_deals"] == 3
    assert _n("deals") == 4 and {r[5] for r in _deal_rows()} == {r1["snapshot_id"]}   # the snapshot holding rows_gz
    assert _snaps()[1][4] == 1                                          # r2 holds no rows itself


# ================================================================== A4. the five deal data checks
def _st(name: str) -> str:
    return next(x["status"] for x in data_checks.run(paths.db_path())["checks"] if x["check"] == name)


def _deal_fixture():
    """A clean deal state: demand 5 on 2026-02-01, a deal line of 2 written by a load covering the day, snapshot S1
    (rows) and S2 (same content, same_as S1, newer), deals pointing at S1, one refresh run with deal_active 0 / 1."""
    with db.tx() as c:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
                  "VALUES (?, 'BIGQUERY', '2026-02-01', 'A', 'F1', 5, 1, 'x')", (SCOPE,))
        c.execute("INSERT INTO deal_line_loads(load_id, scope_key, range_start, range_end, trigger, deal_code_column, "
                  "rows_written, rows_removed, qty, lines, started_at, completed_at) VALUES ('DLL-1', ?, '2026-02-01', "
                  "'2026-02-28', 'MANUAL', 'deal_code', 1, 0, 2, 1, 'x', 'x')", (SCOPE,))
        c.execute("INSERT INTO demand_deal_daily VALUES (?, '2026-02-01', 'A', 'F1', 'D1', 2, 1, 'DLL-1', 'x')", (SCOPE,))
        c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, rows_gz) VALUES "
                  "('S1', ?, '2026-10-29T01:00:00+00:00', 1, 'h1', x'00')", (DEAL_TABLE,))
        c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, same_as) VALUES "
                  "('S2', ?, '2026-10-30T01:00:00+00:00', 1, 'h1', 'S1')", (DEAL_TABLE,))
        c.execute("INSERT INTO deals(source_table, row_no, deal_code, sku_code, fc_code, snapshot_id) VALUES "
                  "(?, 1, 'D1', 'A', 'F1', 'S1')", (DEAL_TABLE,))
        _refresh_run(c, "FRR-1", timeutil.today_vn(), [0, 1, None])


def _refresh_run(c, rid, fdate, values):
    c.execute("INSERT INTO forecast_refresh_runs(id, scope_key, forecast_date, data_as_of, status, config_version, "
              "trial_mode, horizon, n_series, n_lightgbm, n_fallback, created_at) VALUES (?,?,?,?, 'PUBLISHED', 'cv', 1, "
              "?, 1, 1, 0, ?)", (rid, SCOPE, str(fdate), str(fdate - timedelta(days=1)), len(values), timeutil.now_iso()))
    c.executemany("INSERT INTO forecast_refresh_values(run_id, horizon, target_date, fc_code, sku_code, lgb_raw, final_qty, "
                  "method, deal_active) VALUES (?,?,?,?,?,?,?,?,?)",
                  [(rid, h + 1, str(fdate + timedelta(days=h)), "F1", "A", 1.0, 1, "LIGHTGBM", v)
                   for h, v in enumerate(values)])


DEAL_CHECKS = ("deal_lines_within_demand", "deal_lines_load_window", "deal_snapshot_same_as", "deals_latest_snapshot",
               "refresh_values_deal_active")


def test_deal_checks_are_ok_on_clean_data_and_on_an_empty_deal_state(frozen):
    st = {x["check"]: x["status"] for x in data_checks.run(paths.db_path())["checks"]}
    assert {k: st[k] for k in DEAL_CHECKS} == {k: "OK" for k in DEAL_CHECKS}     # nothing configured yet
    _deal_fixture()
    st = {x["check"]: x["status"] for x in data_checks.run(paths.db_path())["checks"]}
    assert {k: st[k] for k in DEAL_CHECKS} == {k: "OK" for k in DEAL_CHECKS}


def _v_above(c):        # 6 deal units on a day with 5 demand units (two codes summed)
    c.execute("INSERT INTO demand_deal_daily VALUES (?, '2026-02-01', 'A', 'F1', 'D2', 4, 1, 'DLL-1', 'x')", (SCOPE,))


def _v_no_demand(c):    # a line of a key without any demand row
    c.execute("INSERT INTO demand_deal_daily VALUES (?, '2026-02-02', 'B', 'F1', 'D1', 1, 1, 'DLL-1', 'x')", (SCOPE,))
    c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
              "VALUES (?, 'BIGQUERY', '2026-02-02', 'A', 'F1', 1, 1, 'x')", (SCOPE,))


def _v_unknown_load(c):  # a line whose load is not recorded
    c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
              "VALUES (?, 'BIGQUERY', '2026-02-03', 'A', 'F1', 3, 1, 'x')", (SCOPE,))
    c.execute("INSERT INTO demand_deal_daily VALUES (?, '2026-02-03', 'A', 'F1', 'D1', 1, 1, 'DLL-NOPE', 'x')", (SCOPE,))


def _v_outside_load(c):  # a line outside the window of the load that wrote it
    c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
              "VALUES (?, 'BIGQUERY', '2026-03-01', 'A', 'F1', 3, 1, 'x')", (SCOPE,))
    c.execute("INSERT INTO demand_deal_daily VALUES (?, '2026-03-01', 'A', 'F1', 'D1', 1, 1, 'DLL-1', 'x')", (SCOPE,))


def _v_other_scope_load(c):  # a line written by a load of another scope
    c.execute("INSERT INTO deal_line_loads(load_id, scope_key, range_start, range_end, trigger, deal_code_column, "
              "rows_written, rows_removed, qty, lines, started_at, completed_at) VALUES ('DLL-2', 'OTHER', '2026-02-01', "
              "'2026-02-28', 'MANUAL', 'deal_code', 1, 0, 1, 1, 'x', 'x')")
    c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
              "VALUES (?, 'BIGQUERY', '2026-02-04', 'A', 'F1', 3, 1, 'x')", (SCOPE,))
    c.execute("INSERT INTO demand_deal_daily VALUES (?, '2026-02-04', 'A', 'F1', 'D1', 1, 1, 'DLL-2', 'x')", (SCOPE,))


def _v_same_as_other_content(c):   # same_as points at a snapshot with another content hash
    c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, same_as) VALUES "
              "('S0', ?, '2026-10-28T01:00:00+00:00', 1, 'h-other', 'S1')", (DEAL_TABLE,))


def _v_same_as_no_rows(c):         # same_as points at a snapshot that holds no rows itself
    c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, same_as) VALUES "
              "('S0', ?, '2026-10-28T01:00:00+00:00', 1, 'h1', 'S2')", (DEAL_TABLE,))


def _v_same_as_other_table(c):     # same_as points at a snapshot of another source table
    c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, rows_gz) VALUES "
              "('T1', 'p.d.other', '2026-10-28T01:00:00+00:00', 1, 'h9', x'00')")
    c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, same_as) VALUES "
              "('S0', ?, '2026-10-28T02:00:00+00:00', 1, 'h9', 'T1')", (DEAL_TABLE,))


def _v_not_latest(c):              # a newer snapshot with other rows, the deals not rewritten
    c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, rows_gz) VALUES "
              "('S3', ?, '2026-10-30T02:00:00+00:00', 1, 'h3', x'00')", (DEAL_TABLE,))


def _v_same_second_tie(c):         # same taken_at as S2 (one-second resolution): the later rowid is the latest
    c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, rows_gz) VALUES "
              "('S3', ?, '2026-10-30T01:00:00+00:00', 1, 'h3', x'00')", (DEAL_TABLE,))


def _v_deal_active_2(c):
    _refresh_run(c, "FRR-2", timeutil.today_vn(), [2])


@pytest.mark.parametrize("violate, check, level", [
    (_v_above, "deal_lines_within_demand", "WARN"),
    (_v_no_demand, "deal_lines_within_demand", "WARN"),
    (_v_unknown_load, "deal_lines_load_window", "WARN"),
    (_v_outside_load, "deal_lines_load_window", "WARN"),
    (_v_other_scope_load, "deal_lines_load_window", "WARN"),
    (_v_same_as_other_content, "deal_snapshot_same_as", "FAIL"),
    (_v_same_as_no_rows, "deal_snapshot_same_as", "FAIL"),
    (_v_same_as_other_table, "deal_snapshot_same_as", "FAIL"),
    (_v_not_latest, "deals_latest_snapshot", "WARN"),
    (_v_same_second_tie, "deals_latest_snapshot", "WARN"),
    (_v_deal_active_2, "refresh_values_deal_active", "FAIL"),
])
def test_each_deal_check_reports_its_level_on_a_crafted_violation(frozen, violate, check, level):
    _deal_fixture()
    with db.tx() as c:
        violate(c)
    res = data_checks.run(paths.db_path())
    st = {x["check"]: x for x in res["checks"]}
    assert st[check]["status"] == level and st[check]["count"] >= 1, st[check]
    others = {k: st[k]["status"] for k in DEAL_CHECKS if k != check}
    if violate is not _v_no_demand:                                     # the extra demand row of A touches no other
        assert others == {k: "OK" for k in others}, others


def test_deal_active_of_an_old_run_is_outside_the_checked_days(frozen):
    _deal_fixture()
    with db.tx() as c:
        _refresh_run(c, "FRR-OLD", timeutil.today_vn() - timedelta(days=30), [5])
    assert _st("refresh_values_deal_active") == "OK"


def test_deal_checks_are_read_only(frozen):
    import hashlib
    _deal_fixture()
    with db.tx() as c:
        _v_above(c)
        _v_deal_active_2(c)
    before = hashlib.sha256(paths.db_path().read_bytes()).hexdigest()
    data_checks.run(paths.db_path())
    assert hashlib.sha256(paths.db_path().read_bytes()).hexdigest() == before


# ================================================================== A5. CLI --apply refused while busy
def _job(status: str, job_type: str = "D1_SYNC") -> str:
    jid = db.new_id("JOB")
    with db.tx() as c:
        c.execute("INSERT INTO job_runs(id, job_type, idempotency_key, trigger, status, attempt, max_attempts, created_at) "
                  "VALUES (?, ?, ?, 'MANUAL', ?, 1, 4, ?)", (jid, job_type, f"K:{jid}", status, timeutil.now_iso()))
    return jid


def _apply_cmds(m0):
    return [("deal-lines-load", "--start", str(m0), "--end", str(Y), "--apply"),
            ("deal-refresh", "--apply"),
            ("open-hours-load", "--start", str(m0), "--end", str(Y), "--apply")]


def _write_counts():
    return [_n(t) for t in ("demand_deal_daily", "deal_line_loads", "deal_snapshots", "deals", "open_hours_daily",
                            "aux_source_reads")]


@pytest.mark.parametrize("status", ["PENDING", "RUNNING", "RETRY_WAIT"])
def test_cli_apply_is_refused_while_a_job_is_active(frozen, capsys, status):
    fake = _production(_d(WINDOW), deal_col="deal_code", deal_table=DEAL_TABLE)
    fake.deal_rows = DEALS
    jid = _job(status)
    w0, q0 = _write_counts(), len(fake.queries)
    for argv in _apply_cmds(Y.replace(day=1)):
        rc, out = _cli(capsys, *argv)
        assert rc == 2 and out["ok"] is False and jid in out["refused"] and status in out["refused"], (argv, out)
    assert _write_counts() == w0 and len(fake.queries) == q0             # nothing read, nothing written
    # a dry run is still allowed (no write)
    rc, out = _cli(capsys, "deal-refresh")
    assert rc == 0 and out["dry_run"] is True


def test_cli_apply_runs_once_the_job_is_finished(frozen, capsys):
    from app import sync
    fake = _production(_d(WINDOW), deal_col="deal_code", deal_table=DEAL_TABLE)
    fake.deal_rows = DEALS
    sync.run_d1_sync("J1")
    for st in ("SUCCEEDED", "FAILED", "CANCELLED"):
        try:
            _job(st)
        except Exception:  # noqa: BLE001 - a status the schema does not know is simply not inserted
            pass
    rc, out = _cli(capsys, "deal-refresh", "--apply")
    assert rc == 0 and out["dry_run"] is False


def test_cli_apply_is_refused_while_the_app_is_running(frozen, capsys, monkeypatch):
    from app import storage_migrate
    fake = _production(_d(WINDOW), deal_col="deal_code", deal_table=DEAL_TABLE)
    fake.deal_rows = DEALS
    monkeypatch.setattr(storage_migrate, "app_running", lambda: {"pid": 4242, "port": 8765})
    w0, q0 = _write_counts(), len(fake.queries)
    for argv in _apply_cmds(Y.replace(day=1)):
        rc, out = _cli(capsys, *argv)
        assert rc == 2 and "4242" in out["refused"], (argv, out)
    assert _write_counts() == w0 and len(fake.queries) == q0
    rc, out = _cli(capsys, "deal-check")                               # read-only: allowed
    assert rc == 0


# ================================================================== B1. coverage gates of check_sources
def _cfg(fs="CHOT_LY", start=EXT):
    return SimpleNamespace(feature_set=fs, ly_history_start=start)


def _hist_rows(c, months, scope=SCOPE):
    for m in months:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
                  "VALUES (?, 'BIGQUERY', ?, 'A', 'F1', 1, 1, 'x')", (scope, f"{m}-15"))


def _sync_run(c, kind, status, start, end, scope=SCOPE):
    c.execute("INSERT INTO demand_sync_runs(id, kind, status, scope_key, window_start, window_end, started_at, "
              "summary_json) VALUES (?,?,?,?,?,?,?, '{}')", (db.new_id("DSR"), kind, status, scope, start, end, "x"))


def _check(cfg=None, last=None, first_origin=None):
    from app.ml import extra_features as xf
    with db.read() as c:
        return xf.check_sources(c, cfg or _cfg(), SCOPE, last, window_start=WINDOW, first_origin=first_origin)


def test_ly_history_gate_lists_the_months_without_rows_and_the_days_not_loaded():
    with pytest.raises(AppError) as e:                                  # nothing at all
        _check()
    assert e.value.code == "LY_HISTORY_NOT_CONFIGURED"
    assert "2025-11" in e.value.detail and "2025-12" in e.value.detail
    with db.tx() as c:
        _hist_rows(c, ["2025-11"])
        _sync_run(c, "BACKFILL", "COMMITTED", "2025-11-01", "2025-11-30")
        _hist_rows(c, ["2025-12"], scope="OTHER")                      # another scope never counts
        _sync_run(c, "BACKFILL", "COMMITTED", "2025-12-01", "2025-12-31", scope="OTHER")
        _sync_run(c, "BACKFILL", "ROLLED_BACK", "2025-12-01", "2025-12-31")   # rolled back: not loaded
        _sync_run(c, "PREVIEW", "PREVIEW", "2025-12-01", "2025-12-31")        # a preview wrote nothing
    with pytest.raises(AppError) as e:
        _check()
    assert e.value.code == "LY_HISTORY_NOT_CONFIGURED"
    assert "demand rows [2025-12]" in e.value.detail and "run [2025-12-01..2025-12-31]" in e.value.detail
    # December has rows but only half of it is inside a committed run: the uncovered days are listed
    with db.tx() as c:
        _hist_rows(c, ["2025-12"])
        _sync_run(c, "D1_SYNC", "COMMITTED", "2025-12-01", "2025-12-20")
    with pytest.raises(AppError) as e:
        _check()
    assert "2025-12-21..2025-12-31" in e.value.detail and "months without demand rows []" in e.value.detail
    with db.tx() as c:
        _sync_run(c, "BACKFILL", "COMMITTED", "2025-12-15", "2026-01-10")     # overlapping windows
    out = _check()
    assert out["history"] == {"start": EXT, "end": "2025-12-31", "months_without_rows": [], "days_not_loaded": [],
                              "runs": 3}


def test_ly_history_gate_is_not_applied_when_the_history_start_is_the_window_start():
    out = _check(_cfg(start=WINDOW))
    assert out is not None and "history" not in out
    from app.ml import extra_features as xf
    with db.read() as c:
        assert xf.check_sources(c, SimpleNamespace(feature_set="CHOT", ly_history_start=None), SCOPE, None,
                                window_start=WINDOW) is None
        with pytest.raises(AppError) as e:                              # a CHOT_LY run without its DAY0
            xf.check_sources(c, _cfg(start=None), SCOPE, None, window_start=WINDOW)
        assert e.value.code == "LY_HISTORY_NOT_CONFIGURED"


def _history_ok():
    with db.tx() as c:
        _hist_rows(c, ["2025-11", "2025-12"])
        _sync_run(c, "BACKFILL", "COMMITTED", "2025-11-01", "2025-12-31")


def _deal_settings(deals=True, dup=False):
    ss.update("bigquery", {"deal_code_column": "deal_code", "deal_table_id": DEAL_TABLE})
    if not deals:
        return
    with db.tx() as c:
        c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, rows_gz) VALUES "
                  "('S1', ?, 'x', 2, 'h', x'00')", (DEAL_TABLE,))
        rows = [("D1", "A", "F1"), ("D2", "B", "F1")] + ([("D1", "A", "F1"), ("D1", "A", "F1")] if dup else [])
        c.executemany("INSERT INTO deals(source_table, row_no, deal_code, sku_code, fc_code, ready_time, end_time, "
                      "snapshot_id) VALUES (?,?,?,?,?, '2026-02-01 00:00:00', '2026-02-03 23:59:59', 'S1')",
                      [(DEAL_TABLE, i, *r) for i, r in enumerate(rows)])


def _deal_load(c, start, end, scope=SCOPE):
    c.execute("INSERT INTO deal_line_loads(load_id, scope_key, range_start, range_end, trigger, deal_code_column, "
              "rows_written, rows_removed, qty, lines, started_at, completed_at) VALUES (?, ?, ?, ?, 'MANUAL', "
              "'deal_code', 0, 0, 0, 0, 'x', 'x')", (db.new_id("DLL"), scope, start, end))


def test_deal_lines_gate_lists_the_days_without_a_load_and_records_the_coverage():
    _history_ok()
    with pytest.raises(AppError) as e:                                  # deal source not configured
        _check(_cfg("CHOT_LY_DEAL"), last=date(2026, 3, 31))
    assert e.value.code == "DEAL_SOURCE_NOT_CONFIGURED"
    _deal_settings(dup=True)
    with db.tx() as c:
        _deal_load(c, "2025-11-01", "2025-12-31")
        _deal_load(c, "2026-01-01", "2026-01-31")
        _deal_load(c, "2026-02-01", "2026-03-31", scope="OTHER")      # another scope never counts
        _deal_load(c, "2026-03-01", "2026-03-20")
    with pytest.raises(AppError) as e:
        _check(_cfg("CHOT_LY_DEAL"), last=date(2026, 3, 31))
    assert e.value.code == "DEAL_SOURCE_NOT_CONFIGURED"
    assert "2026-02-01..2026-02-28" in e.value.detail and "2026-03-21..2026-03-31" in e.value.detail
    with db.tx() as c:
        _deal_load(c, "2026-02-01", "2026-02-28")
        _deal_load(c, "2026-03-15", "2026-04-30")
    out = _check(_cfg("CHOT_LY_DEAL"), last=date(2026, 3, 31), first_origin=date(2026, 3, 1))
    assert out["deal_lines_loaded"] == {"start": EXT, "end": "2026-03-31", "loads": 5, "days_not_loaded": []}
    assert out["duplicate_deal_keys"] == {"keys": 1, "rows": 3, "rows_dropped": 2, "rule": "LATEST_END_TIME_THEN_LAST_ROW"}
    assert out["history"]["days_not_loaded"] == [] and out["n_deals"] == 4 and out["deal_table"] == DEAL_TABLE
    # the open hours of the group window of each origin month (March, April = the month of last_day + 1)
    assert [g["month"] for g in out["group_open_hours"]] == ["2026-03-01", "2026-04-01"]
    assert out["group_open_hours"][0]["window"] == ["2025-12-01", "2026-02-28"]
    assert all(g["days_with_open_hours"] == 0 for g in out["group_open_hours"])
    # CHOT_LY never needs deal lines
    assert "deal_lines_loaded" not in _check(_cfg("CHOT_LY"), last=date(2026, 3, 31))


def test_training_with_chot_ly_is_refused_until_the_history_is_loaded_then_records_the_coverage(small_demo):
    from app.ml import pipeline
    ss.update("data_policy", {"extended_history_start_date": EXT})
    ss.update("model", {"feature_set": "CHOT_LY", "forecast_strategy": "DIRECT", "direct_origins": 4,
                        "direct_origin_step_days": 7})
    ss.update("horizons", {"enabled": [7]})
    scope = small_demo["batch_id"]
    n0 = _n("training_runs")
    with pytest.raises(AppError) as e:
        pipeline.train_and_publish(force=True)
    assert e.value.code == "LY_HISTORY_NOT_CONFIGURED"
    assert "2025-11" in e.value.detail and "2025-12" in e.value.detail
    assert _n("training_runs") == n0                                    # refused before any training_runs row
    with db.tx() as c:
        for m in ("2025-11", "2025-12"):
            c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                      "loaded_at) SELECT scope_key, data_source, ?, sku_id, fc_id, 2, 1, 'x' FROM demand_daily WHERE "
                      "scope_key=? GROUP BY sku_id, fc_id", (f"{m}-10", scope))
        _sync_run(c, "BACKFILL", "COMMITTED", "2025-11-01", "2025-12-31", scope=scope)
    pipeline.train_and_publish(force=True)
    with db.read() as c:
        tr = db.one(c, "SELECT feature_config_json FROM training_runs ORDER BY started_at DESC, rowid DESC LIMIT 1")
    fcj = json.loads(tr["feature_config_json"])
    xf = fcj["feature_decisions"]["extra_features"]
    assert xf["feature_set"] == "CHOT_LY" and xf["ly_history_start"] == EXT
    assert xf["history"] == {"start": EXT, "end": "2025-12-31", "months_without_rows": [], "days_not_loaded": [],
                             "runs": 1}
    assert fcj["config"]["ly_history_start"] == EXT


def test_daily_refresh_panel_is_not_ready_until_the_history_is_loaded(small_demo):
    from app.bq.aux_sources import NotReady
    from app.data.demand import resolve_scope
    from app.ml import daily_refresh as dr
    ss.update("data_policy", {"extended_history_start_date": EXT})
    mcfg = ss.ModelSettings(feature_set="CHOT_LY", forecast_strategy="DIRECT").model_copy(
        update={"ly_history_start": EXT})
    with db.read() as c:
        scope = resolve_scope(c)
    d = timeutil.today_vn()
    w0 = [_n(t) for t in ("forecast_refresh_runs", "forecast_refresh_values")]
    with pytest.raises(NotReady) as e:
        dr.build_refresh_panel(scope, d, mcfg)
    assert e.value.code == "LY_HISTORY_NOT_CONFIGURED" and "2025-11" in e.value.detail
    assert [_n(t) for t in ("forecast_refresh_runs", "forecast_refresh_values")] == w0
    with db.tx() as c:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
                  "SELECT scope_key, data_source, '2025-11-10', sku_id, fc_id, 2, 1, 'x' FROM demand_daily WHERE "
                  "scope_key=? GROUP BY sku_id, fc_id", (scope["scope_key"],))
        _sync_run(c, "BACKFILL", "COMMITTED", "2025-11-01", "2025-11-30", scope=scope["scope_key"])
    with pytest.raises(NotReady) as e:                                  # December still missing
        dr.build_refresh_panel(scope, d, mcfg)
    assert "demand rows [2025-12]" in e.value.detail and "run [2025-12-01..2025-12-31]" in e.value.detail
    with db.tx() as c:
        c.execute("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, loaded_at) "
                  "SELECT scope_key, data_source, '2025-12-10', sku_id, fc_id, 2, 1, 'x' FROM demand_daily WHERE "
                  "scope_key=? AND order_date='2025-11-10'", (scope["scope_key"],))
        _sync_run(c, "D1_SYNC", "COMMITTED", "2025-12-01", "2025-12-31", scope=scope["scope_key"])
    panel, _ = dr.build_refresh_panel(scope, d, mcfg)
    assert panel.extra is not None and panel.extra.sources["history"]["days_not_loaded"] == []
    assert panel.extra.info["sources"]["history"]["runs"] == 2


# ================================================================== B2. chunked DB reader == frame path
def _random_case(seed: int):
    rng = np.random.default_rng(seed)
    day0, last = date(2025, 11, 1), date(2026, 3, 31)
    n = (last - day0).days + 1
    days = [day0 + timedelta(days=i) for i in range(-10, n + 5)]       # a few rows outside [day0, last]
    series = [(f"S{i}", f"F{i % 2 + 1}") for i in range(6)]
    demand = [(str(d), s, f, float(rng.integers(0, 12)) / 4) for d in days for s, f in series if rng.random() < 0.7]
    deals = []
    for i in range(14):
        s, f = series[rng.integers(0, len(series))] if i != 13 else ("S9", "F1")   # S9: a series without demand
        a = day0 + timedelta(days=int(rng.integers(0, n - 5)))
        b = a + timedelta(days=int(rng.integers(0, 20)))
        ready = f"{a} {int(rng.integers(0, 24)):02d}:00:00"
        end = f"{b} 23:59:59" if i != 5 else None                       # one deal without end: never used
        code = f"K{i if i not in (7, 8) else 7}"                         # deals 7 and 8: a duplicate key when same series
        mx = None if i % 4 == 0 else float(rng.integers(10, 60))
        deals.append((code, s, f, ready, end, mx, None if i % 3 == 0 else float(rng.integers(0, 40))))
    if deals[7][1:3] != deals[8][1:3]:
        deals[8] = (deals[8][0], *deals[7][1:3], *deals[8][3:])
    lines = {}
    for code, s, f, ready, end, *_ in deals + [("NOPE", "S0", "F1", f"{day0} 00:00:00", f"{last} 00:00:00", 0, 0)]:
        a = date.fromisoformat(ready[:10])
        for k in range(int(rng.integers(1, 15))):
            d = a + timedelta(days=int(rng.integers(-3, 25)))
            lines[(str(d), s, f, code)] = float(rng.integers(1, 9)) / 2
    lines = [(d, s, f, code, q) for (d, s, f, code), q in sorted(lines.items())]
    hours = [(str(d), s, f, float(rng.choice([0.0, 4.0, 10.0]))) for d in days for s, f in series if rng.random() < 0.8]
    return day0, last, series, demand, deals, lines, hours


def _store_case(demand, deals, lines, hours):
    from app.bq.aux_sources import open_hours_source
    ss.update("bigquery", {"deal_code_column": "deal_code", "deal_table_id": DEAL_TABLE})
    tbl, seller = open_hours_source()
    with db.tx() as c:
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                      "loaded_at) VALUES (?, 'BIGQUERY', ?, ?, ?, ?, 1, 'x')", [(SCOPE, *r) for r in demand])
        c.execute("INSERT INTO deal_snapshots(id, source_table, taken_at, n_rows, content_sha256, rows_gz) VALUES "
                  "('S1', ?, 'x', ?, 'h', x'00')", (DEAL_TABLE, len(deals)))
        c.executemany("INSERT INTO deals(source_table, row_no, deal_code, sku_code, fc_code, ready_time, end_time, "
                      "max_quantity, quantity_used, snapshot_id) VALUES (?,?,?,?,?,?,?,?,?, 'S1')",
                      [(DEAL_TABLE, i, *r) for i, r in enumerate(deals, start=1)])
        c.executemany("INSERT INTO demand_deal_daily VALUES (?,?,?,?,?,?, 1, 'L', 'x')", [(SCOPE, *r) for r in lines])
        c.executemany("INSERT INTO open_hours_daily VALUES (?,?,?,?,?,?, 1, 'x')",
                      [(tbl, seller, f, s, d, h) for d, s, f, h in hours])


@pytest.mark.parametrize("chunk", [3, 17, 200_000])
@pytest.mark.parametrize("seed", [21, 22])
def test_chunked_db_reader_gives_the_features_of_the_frame_path(monkeypatch, chunk, seed):
    from app.ml import extra_features as xf
    day0, last, series, demand, deals, lines, hours = _random_case(seed)
    _store_case(demand, deals, lines, hours)
    monkeypatch.setattr(xf, "_READ_CHUNK", chunk)
    keys = series[::-1] + [("S7", "F2")]                                 # S7: a key without any row
    cfg = _cfg("CHOT_LY_DEAL", str(day0))
    with db.read() as c:
        db_ctx = xf.load_context(c, SCOPE, keys, cfg, last)
    cols = ["deal_code", "sku_code", "fc_code", "ready_time", "end_time", "max_quantity", "quantity_used"]
    fr = xf.ExtraContext(
        keys, day0, last, pd.DataFrame(demand, columns=["order_date", "sku_id", "fc_id", "qty"]),
        deals=pd.DataFrame(deals, columns=cols),
        deal_lines=pd.DataFrame(lines, columns=["order_date", "sku_id", "fc_id", "deal_code", "qty"]),
        open_days=pd.DataFrame(hours, columns=["date", "sku_id", "fc_id", "hours"]), open_days_from=day0)
    assert (db_ctx.n_deals, db_ctx.n_deal_lines_matched, db_ctx.n_deal_rows_dropped) == (
        fr.n_deals, fr.n_deal_lines_matched, fr.n_deal_rows_dropped)
    assert db_ctx.n_deal_lines == fr.n_deal_lines and db_ctx.n_deal_lines > 0 and db_ctx.n_deal_lines_matched > 0
    assert db_ctx.n_deal_rows_dropped >= 1
    origins = [day0 + timedelta(days=k) for k in (0, 1, 30, 61, 90, 121, 140)] + [last, last + timedelta(days=1)]
    for D in origins:
        np.testing.assert_array_equal(db_ctx.block(D, xf.ALL_NAMES), fr.block(D, xf.ALL_NAMES), err_msg=str(D))
        np.testing.assert_array_equal(db_ctx.active_on(D), fr.active_on(D), err_msg=str(D))
    for k in keys:
        assert db_ctx.daily(k, day0 - timedelta(days=2), last) == fr.daily(k, day0 - timedelta(days=2), last)
    # the comparison is not vacuous: deals are active and their used quantities are non-zero on some origin
    blocks = np.concatenate([fr.block(D, xf.DEAL_NAMES) for D in origins])
    assert (blocks[:, xf.DEAL_NAMES.index("deal_active")] == 1).any()
    assert (np.nan_to_num(blocks[:, xf.DEAL_NAMES.index("deal_used_to_date")]) > 0).any()


def test_deal_line_reader_maps_lines_to_the_deal_keys_across_chunk_boundaries(monkeypatch):
    from app.ml import extra_features as xf
    day0, last, series, demand, deals, lines, hours = _random_case(5)
    _store_case(demand, deals, lines, hours)
    df = pd.DataFrame(deals, columns=["deal_code", "sku_code", "fc_code", "ready_time", "end_time", "max_quantity",
                                      "quantity_used"])
    out = {}
    for chunk in (1, 4, 10_000):
        monkeypatch.setattr(xf, "_READ_CHUNK", chunk)
        with db.read() as c:
            dl = xf._read_deal_lines(c, SCOPE, df, day0, last)
        got = sorted((dl.keys[k], int(d), float(q)) for k, d, q in zip(dl.ki, dl.di, dl.qty))
        out[chunk] = (got, dl.n_lines, len(dl.keys))
    assert out[1] == out[4] == out[10_000]
    inside = [r for r in lines if str(day0) <= r[0] <= str(last)]
    known = {(r[0], r[1], r[2]) for r in deals}
    want = sorted(((code, s, f), (date.fromisoformat(d) - day0).days, q) for d, s, f, code, q in inside
                  if (code, s, f) in known)
    assert out[1][0] == want and out[1][1] == len(inside)
