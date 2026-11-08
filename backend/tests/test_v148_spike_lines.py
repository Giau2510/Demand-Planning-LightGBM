"""1.4.8 C-2: the nightly SO-line step (app/spike_lines.py, bq/connector.fetch_so_lines, cli spike-lines) on the
isolated test DB with a fake BigQuery client (unit / integration with fakes; no BigQuery, no live data)."""
import json
from datetime import date, timedelta

import pytest

from app import cli, db, spike_lines
from app import settings_service as ss
from app.bq import connector
from app.bq.aux_sources import open_hours_source
from app.data.demand import bigquery_scope_key
from app.messages import AppError
from fake_bq import FakeBQ

D = date(2026, 11, 1)
KEYS = [("S00", "FC1"), ("S01", "FC1"), ("S02", "FC2"), ("S03", "FC2")]
SPIKE = (D - timedelta(days=5), "S01", "FC1")
MAPPING = {"order_id": {"column": "order_id", "usage": "OPTIONAL"},
           "created_at": {"column": "created_at", "usage": "REQUIRED"},
           "sku_id": {"column": "sku", "usage": "REQUIRED"}, "fc_id": {"column": "warehouse", "usage": "REQUIRED"},
           "order_qty": {"column": "qty", "usage": "REQUIRED"}}


def _configure(**extra):
    ss.update("bigquery", {"dataset_id": "sales", "source_table": "orders", "location": "asia-southeast1",
                           "field_mapping": MAPPING, "customer_id_column": "customer", **extra})
    ss.update("general", {"active_source": "BIGQUERY"})
    ss.update("data_policy", {"window_start_date": "2026-01-01"})
    return bigquery_scope_key(ss.get("bigquery"))


def _lines(start: date, end: date) -> list[dict]:
    """3 customers x 2 units per key and day; customer C1 orders 60 of S01 x FC1 on SPIKE day."""
    out = []
    d = start
    while d <= end:
        for sku, fc in KEYS:
            for c in ("C1", "C2", "C3"):
                q = 60 if (d, sku, fc) == SPIKE and c == "C1" else 2
                out.append({"order_date": d, "fc_code": fc, "sku_code": sku, "so_code": f"SO{d:%m%d}{sku}{c}",
                            "customer_id": c, "qty": q, "n_rows": 1})
        d += timedelta(days=1)
    return out


def _fake(**kw):
    def resp(cfg):
        p = {n: v for n, _t, v in cfg["params"]}
        return _lines(p["start"], p["end"])
    f = FakeBQ(responses={"so_lines": resp}, **kw)
    connector.set_client_factory(f)
    return f


def _seed_db(scope, start=date(2026, 1, 1), end=D - timedelta(days=1)):
    """demand_daily = the sum of the fake lines per day x SKU x FC; open hours 10 every day."""
    tbl, seller = open_hours_source()
    dem, oh = [], []
    d = start
    while d <= end:
        for sku, fc in KEYS:
            q = 6 + (58 if (d, sku, fc) == SPIKE else 0)
            dem.append((scope, "BIGQUERY", str(d), sku, fc, float(q), 3, "x", 10.0, "OK"))
            oh.append((tbl, seller, fc, sku, str(d), 10.0, 1, "x"))
        d += timedelta(days=1)
    with db.tx() as c:
        c.executemany("INSERT INTO demand_daily(scope_key, data_source, order_date, sku_id, fc_id, qty, n_orders, "
                      "loaded_at, open_hours, open_hours_status) VALUES (?,?,?,?,?,?,?,?,?,?)", dem)
        c.executemany("INSERT INTO open_hours_daily(source_table, seller_code, fc_code, sku_code, open_date, "
                      "total_open_hours, n_items, loaded_at) VALUES (?,?,?,?,?,?,?,?)", oh)


def _count(sql, p=()):
    with db.read() as c:
        return c.execute(sql, p).fetchone()[0]


# ------------------------------------------------------------------ the line query
@pytest.mark.parametrize("policy, dedupe", [("BLOCK", True), ("DROP_EXACT", True), ("KEEP", False)])
def test_line_sql_same_filters_as_d1_customer_inside_and_read_only(policy, dedupe):
    _configure(exact_duplicate_policy=policy)
    sql = connector._lines_sql(ss.get("bigquery"))
    assert "`customer`" in sql and "order_qty >= 0" in sql and "sku_id IS NOT NULL" in sql
    assert ("ROW_NUMBER() OVER" in sql) is dedupe
    assert "_pend" in sql and "GROUP BY 1, 2, 3, 4, 5" in sql
    import re
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|MERGE|CREATE|DROP|ALTER|TRUNCATE)\s", sql.upper())


def test_dry_run_refused_above_5_gb_and_capped_by_the_smaller_limit():
    _configure()
    f = _fake(bytes_=5_000_000_001)
    with pytest.raises(AppError) as e:
        connector.fetch_so_lines(D - timedelta(days=3), D - timedelta(days=1), lambda b: None)
    assert e.value.code == "BQ_QUERY_TOO_EXPENSIVE"
    assert len(f.queries) == 1 and f.queries[0][1]["dry_run"]           # only the dry run went out
    ss.update("bigquery", {"maximum_bytes_billed": 1_000_000_000})
    f = _fake(bytes_=2_000_000_000)
    with pytest.raises(AppError):
        connector.fetch_so_lines(D - timedelta(days=3), D - timedelta(days=1), lambda b: None)
    f = _fake(bytes_=1000)
    got = []
    r = connector.fetch_so_lines(D - timedelta(days=3), D - timedelta(days=1), got.extend)
    assert f.queries[1][1]["maximum_bytes_billed"] == 1_000_000_000 and r["rows"] == len(got) == 3 * 4 * 3


def test_dry_run_cli_writes_nothing(sel2_on, capsys):
    _configure()
    _fake(bytes_=3_141_612_152)
    assert cli.main(["spike-lines", "--date", str(D), "--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["result"]["estimated_bytes"] == 3_141_612_152
    assert out["result"]["read_start"] == str(D - timedelta(days=210))
    assert _count("SELECT COUNT(*) FROM so_lines_cache") == 0


def test_cli_without_yes_plans_only(capsys):
    _configure()
    f = _fake()
    assert cli.main(["spike-lines", "--date", str(D)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["code"] == "SEL2_CONFIRM_REQUIRED" and out["plan"]["read_end"] == str(D - timedelta(days=1))
    assert f.queries == [] and _count("SELECT COUNT(*) FROM so_lines_cache") == 0


# ------------------------------------------------------------------ run: cache, prune, flags, excess
def test_first_run_210_days_then_incremental_and_prune(sel2_on):
    scope = _configure()
    _seed_db(scope, end=D)
    f = _fake()
    r = spike_lines.run(D)
    assert r["status"] == "DONE" and r["read_start"] == str(D - timedelta(days=210))
    assert _count("SELECT MIN(order_date) FROM so_lines_cache") == str(D - timedelta(days=210))
    assert _count("SELECT MAX(order_date) FROM so_lines_cache") == str(D - timedelta(days=1))
    assert _count("SELECT COUNT(*) FROM so_lines_cache") == 210 * 12
    # flags: the 60-unit line of the regular customer C1 is flagged (T1), its excess as of D written at level 1
    with db.read() as c:
        fl = db.rows(c, "SELECT d, sku_code, fc_code, T1, computed_for FROM spike_flag_lines")
        ex = db.rows(c, "SELECT d, sku_code, fc_code, excess, asof, level, e4_n FROM demand_excess_daily")
    assert {(x["d"], x["sku_code"], x["T1"], x["computed_for"]) for x in fl} >= {(str(SPIKE[0]), "S01", 1, str(D))}
    assert ex == [{"d": str(SPIKE[0]), "sku_code": "S01", "fc_code": "FC1", "excess": 58.0, "asof": str(D),
                   "level": 1, "e4_n": 4}]
    assert r["flags"]["excess_total"] == 58.0
    # incremental: from the last cached day - late_data_lookback_days (3); the day before D+1-210 pruned
    d2 = D + timedelta(days=1)
    r2 = spike_lines.run(d2)
    assert r2["read_start"] == str(D - timedelta(days=4)) and r2["lines"]["window"]["end"] == str(D)
    assert r2["lines"]["cache_rows_pruned"] == 12
    assert _count("SELECT MIN(order_date) FROM so_lines_cache") == str(d2 - timedelta(days=210))
    assert _count("SELECT COUNT(*) FROM so_lines_cache") == 210 * 12
    assert f.queries[-1][1]["params"][0][2] == D - timedelta(days=4)


def test_a_line_returned_twice_is_summed_with_its_rows(sel2_on):
    scope = _configure()
    one = {"order_date": D - timedelta(days=1), "fc_code": "FC1", "sku_code": "S00", "so_code": "", "customer_id": "",
           "qty": 2, "n_rows": 2}
    connector.set_client_factory(FakeBQ(responses={"so_lines": [one, {**one, "qty": 3, "n_rows": 1}]}))
    res = spike_lines.load_lines(scope, D - timedelta(days=1), D - timedelta(days=1), D - timedelta(days=210))
    with db.read() as c:
        rows = db.rows(c, "SELECT qty, n_rows, so_code, customer_id FROM so_lines_cache")
    assert rows == [{"qty": 5.0, "n_rows": 3, "so_code": "", "customer_id": ""}] and res["cache_rows_written"] == 1


def test_no_customer_column_is_refused():
    _configure(customer_id_column="")
    ss.update("sel2_pipeline", {"enabled": True})
    with pytest.raises(AppError) as e:
        spike_lines.run(D)
    assert e.value.code == "SPIKE_LINES_NO_CUSTOMER"


# ------------------------------------------------------------------ the job: failure only flags
def _run_job():
    from app.jobs import runner
    return runner.execute("SPIKE_LINES", spike_lines.job_key(D), "MANUAL", None, {"business_date": str(D)})


def _job(monkeypatch, child):
    from app.jobs import resources
    real = resources.snapshot
    monkeypatch.setattr(resources, "snapshot", lambda: {**real(), "commit_avail": 1 << 50})
    spike_lines.set_child_runner(child)
    try:
        return _run_job()
    finally:
        spike_lines.set_child_runner(None)


def _boom(args, timeout):
    raise RuntimeError("child crashed")


@pytest.mark.parametrize("child", [_boom, lambda a, t: {"ok": False, "code": "BQ_QUERY_TOO_EXPENSIVE", "exit_code": 1}])
def test_job_failure_is_a_warning_alert_only(sel2_on, monkeypatch, child):
    with db.read() as c:
        before = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("demand_daily", "forecast_refresh_runs", "so_lines_cache", "spike_flag_lines")}
    row = _job(monkeypatch, child)
    assert row["status"] == "FAILED" and row["reason_code"] == "SPIKE_LINES_FAILED" and row["job_type"] == "SPIKE_LINES"
    assert row["next_attempt_at"] is None                            # never retried
    with db.read() as c:
        al = db.rows(c, "SELECT level, code, params_json FROM alerts")
        after = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
    assert [(a["level"], a["code"]) for a in al] == [("WARNING", "SPIKE_LINES_FAILED")]
    assert after == before
    # one attempt: a second call does not run it again
    assert _job(monkeypatch, _boom)["note"] == "RETRIES_EXHAUSTED"


def test_job_success_records_the_result_and_child_args(sel2_on, monkeypatch):
    seen = {}

    def child(args, timeout):
        seen.update(args=args, timeout=timeout)
        return {"ok": True, "exit_code": 0, "result": {"status": "DONE", "flags": {"excess_total": 1.0}}}
    row = _job(monkeypatch, child)
    assert row["status"] == "SUCCEEDED"
    assert seen == {"args": ["spike-lines", "--date", str(D), "--yes"], "timeout": 45 * 60}
    assert _count("SELECT COUNT(*) FROM alerts") == 0


def test_job_low_memory_is_not_started(sel2_on, monkeypatch):
    from app.jobs import resources
    real = resources.snapshot
    monkeypatch.setattr(resources, "snapshot", lambda: {**real(), "commit_avail": 100 * resources.MB})
    spike_lines.set_child_runner(lambda a, t: pytest.fail("child started"))
    try:
        row = _run_job()
    finally:
        spike_lines.set_child_runner(None)
    assert row["status"] == "FAILED" and json.loads(row["result_json"])["result"]["cause"] == "SEL2_LOW_MEMORY"


def test_job_skipped_with_sel2_off(monkeypatch):
    spike_lines.set_child_runner(lambda a, t: pytest.fail("child started"))
    try:
        row = _run_job()
    finally:
        spike_lines.set_child_runner(None)
    assert row["status"] == "SKIPPED" and row["reason_code"] == "SEL2_DISABLED"


def _stored_flag(scope, day, sku, customer, next_day=None, computed_for=None):
    with db.tx() as c:
        c.execute("INSERT INTO spike_flag_lines(scope_key, logic, history_days, d, fc_code, sku_code, so_code, "
                  "customer_id, qty, group_code, min_qty, n_prev, cust_med, gap_med, n_gaps, next_day, kept, T1, T2, T4, "
                  "T7, n_signals_raw, exc_wholesale, exc_periodic, exc_demand, is_regular, computed_for, computed_at) "
                  "VALUES (?, 'v3', 180, ?, 'FC1', ?, 'SOX', ?, 50, 'B', 5, ?, 2, 7, 3, ?, 2, ?, ?, 0, 0, 1, 0, 0, 0, ?, "
                  "?, 'x')", (scope, str(day), sku, customer, 5 if customer else 0, next_day, int(bool(customer)),
                              int(not customer), int(bool(customer)), str(computed_for or day + timedelta(days=1))))


def test_later_nights_rewrite_only_the_last_30_days_and_refresh_next_day(sel2_on):
    scope = _configure()
    _seed_db(scope, end=D)
    _fake()
    r1 = spike_lines.run(D)
    assert r1["flags"]["full"] and r1["flags"]["written_from"] == str(D - timedelta(days=210))
    d2 = D + timedelta(days=1)
    old = d2 - timedelta(days=40)
    _stored_flag(scope, old, "S00", "C1")                                        # next purchase not seen yet
    _stored_flag(scope, old, "S02", "")                     # unknown customer (new, T2 only): never updated
    _stored_flag(scope, old - timedelta(days=1), "S03", "C2", next_day=str(old), computed_for=old)   # already seen
    r2 = spike_lines.run(d2)
    assert not r2["flags"]["full"] and r2["flags"]["written_from"] == str(d2 - timedelta(days=30))
    assert r2["flags"]["next_day_refreshed"] == 1
    with db.read() as c:
        rows = {(x["sku_code"], x["customer_id"]): x for x in db.rows(
            c, "SELECT sku_code, customer_id, next_day, computed_for, qty, kept, n_prev FROM spike_flag_lines WHERE d < ?",
            (str(d2 - timedelta(days=30)),))}
        recent = db.rows(c, "SELECT d, computed_for FROM spike_flag_lines WHERE d = ?", (str(SPIKE[0]),))
    assert rows[("S00", "C1")]["next_day"] == str(old + timedelta(days=1))
    assert rows[("S00", "C1")]["computed_for"] == str(d2) and rows[("S00", "C1")]["qty"] == 50.0
    assert rows[("S02", "")]["next_day"] is None and rows[("S02", "")]["computed_for"] == str(old + timedelta(days=1))
    assert rows[("S03", "C2")]["next_day"] == str(old) and rows[("S03", "C2")]["computed_for"] == str(old)
    assert recent == [{"d": str(SPIKE[0]), "computed_for": str(d2)}]               # recomputed in the last 30 days


def test_data_check_warns_per_day_series_when_cache_and_demand_differ(sel2_on):
    from app import data_checks, paths
    scope = _configure()
    _seed_db(scope, end=D)
    _fake()
    spike_lines.run(D)

    def chk():
        res = data_checks.run(paths.db_path())
        return next(x for x in res["checks"] if x["check"] == "so_lines_cache_matches_demand")
    assert chk()["status"] == "OK"
    with db.tx() as c:
        c.execute("UPDATE demand_daily SET qty = qty + 1 WHERE order_date=? AND sku_id='S00'", (str(D - timedelta(days=3)),))
        c.execute("DELETE FROM so_lines_cache WHERE order_date=? AND sku_code='S02'", (str(D - timedelta(days=2)),))
    r = chk()
    assert r["status"] == "WARN" and r["count"] == 2 and r["days"] == 2
    assert r["examples"][0] == [scope, str(D - timedelta(days=3)), "S00", "FC1", 6.0, 7.0]
    assert all(len(x) == 6 and not {"C1", "C2", "C3"} & set(map(str, x)) for x in r["examples"])   # no customer id


# ------------------------------------------------------------------ fix loop 1 (R1, DR3, R3/DR4, R7, R9)
def test_full_reflag_is_decided_from_the_flag_state_and_heals_a_failed_night(sel2_on, monkeypatch):
    from app.ml.sel2 import spike
    scope = _configure()
    _seed_db(scope, end=D + timedelta(days=2))
    _fake()
    real = spike.flag_lines
    monkeypatch.setattr(spike, "flag_lines", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("flags failed")))
    with pytest.raises(RuntimeError):
        spike_lines.run(D)                                     # cache loaded, flags failed
    assert _count("SELECT COUNT(*) FROM so_lines_cache") == 210 * 12
    with db.read() as c:
        assert spike_lines.full_done(c, scope) is None
    monkeypatch.setattr(spike, "flag_lines", real)
    r2 = spike_lines.run(D + timedelta(days=1))               # incremental read, but the flags are derived in full
    assert r2["read_start"] != r2["cache_first_day"] and r2["flags"]["full"]
    assert r2["flags"]["written_from"] == r2["cache_first_day"]
    r3 = spike_lines.run(D + timedelta(days=2))
    assert not r3["flags"]["full"]


def test_initial_refused_once_flags_exist_unless_reflag(sel2_on, capsys):
    scope = _configure()
    _seed_db(scope, end=D + timedelta(days=1))
    _fake()
    spike_lines.run(D)
    with pytest.raises(AppError) as e:
        spike_lines.run(D + timedelta(days=1), initial=True)
    assert e.value.code == "SPIKE_LINES_REFLAG_REQUIRED"
    r = spike_lines.run(D + timedelta(days=1), initial=True, reflag=True)
    assert r["flags"]["full"] and r["read_start"] == r["cache_first_day"]
    assert cli.main(["spike-lines", "--date", str(D + timedelta(days=1)), "--initial", "--yes"]) == 1
    assert json.loads(capsys.readouterr().out)["code"] == "SPIKE_LINES_REFLAG_REQUIRED"


def test_writes_are_short_transactions_another_connection_writes_between(sel2_on, monkeypatch):
    import sqlite3
    from app import paths
    scope = _configure()
    _seed_db(scope, end=D)
    _fake()
    done = []

    def other_writer():
        c = sqlite3.connect(str(paths.db_path()), timeout=0.2)
        try:
            c.execute("INSERT INTO sync_state(name, value_json, updated_at) VALUES (?, '{}', 'x')", (f"t{len(done)}",))
            c.commit()
        finally:
            c.close()
        done.append(1)
    monkeypatch.setattr(spike_lines, "_on_chunk", other_writer)
    spike_lines.run(D)
    assert len(done) == 30 + 30                                # 210 cache days and 210 flag days in 7-day chunks
    assert _count("SELECT COUNT(*) FROM so_lines_cache") == 210 * 12


def test_runner_timeout_is_failed_with_a_warning_never_retried(sel2_on, monkeypatch):
    import time
    from app.jobs import resources, runner
    real = resources.snapshot
    monkeypatch.setattr(resources, "snapshot", lambda: {**real(), "commit_avail": 1 << 50})
    monkeypatch.setattr(runner, "job_timeout", lambda jt, sched: 0.2)
    spike_lines.set_child_runner(lambda a, t: (time.sleep(1), {"ok": True, "exit_code": 0,
                                                               "result": {"status": "DONE"}})[1])
    try:
        row = runner.execute("SPIKE_LINES", spike_lines.job_key(D), "MANUAL", None, {"business_date": str(D)})
    finally:
        time.sleep(1.2)
        spike_lines.set_child_runner(None)
    assert row["status"] == "FAILED" and row["next_attempt_at"] is None and "TIMEOUT" in row["error"]
    with db.read() as c:
        al = db.rows(c, "SELECT level, code FROM alerts")
    assert al == [{"level": "WARNING", "code": "SPIKE_LINES_FAILED"}]
    assert "SPIKE_LINES" in runner.HEAVY_TYPES


def test_next_day_refresh_never_takes_next_day_from_the_cache_for_lines_before_it(sel2_on):
    scope = _configure()
    _seed_db(scope, end=D + timedelta(days=1))
    _fake()
    spike_lines.run(D)
    before = D - timedelta(days=300)
    _stored_flag(scope, before, "S00", "C9")                  # customer without a purchase in the cache
    _stored_flag(scope, before, "S01", "C1", next_day=str(before + timedelta(days=3)))
    spike_lines.run(D + timedelta(days=1))
    with db.read() as c:
        r = {x["sku_code"]: x for x in db.rows(c, "SELECT sku_code, next_day, computed_for FROM spike_flag_lines "
                                                  "WHERE d=?", (str(before),))}
    # no next_day taken from the cache; the T7 data end moves (no later purchase), so Excess stays decidable
    assert r["S00"]["next_day"] is None and r["S00"]["computed_for"] == str(D + timedelta(days=1))
    assert r["S01"]["next_day"] == str(before + timedelta(days=3))
    assert r["S01"]["computed_for"] == str(before + timedelta(days=1))


def test_cli_initial_with_reflag_rederives_every_flag(sel2_on, capsys):
    """fix loop 1: --reflag reaches spike_lines.run through the CLI (exit 0, flags derived in full from the first
    cached day) once the scope has flags."""
    scope = _configure()
    _seed_db(scope, end=D + timedelta(days=1))
    _fake()
    spike_lines.run(D)
    capsys.readouterr()
    assert cli.main(["spike-lines", "--date", str(D + timedelta(days=1)), "--initial", "--reflag", "--yes"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["args"]["reflag"] is True and out["result"]["reflag"] is True
    res = out["result"]
    assert res["flags"]["full"] and res["read_start"] == res["cache_first_day"]
    assert res["flags"]["written_from"] == res["cache_first_day"]


def test_a_night_after_a_gap_of_more_than_30_days_flags_every_line_since_the_last_run(sel2_on, monkeypatch):
    """review R-148b: no flag run for 40 nights -> the next night writes flags from the day of the last flag run (not
    only the last 30 days), so a spike in the gap is flagged; the marker keeps the day of the last run."""
    scope = _configure()
    _seed_db(scope, end=D)
    _fake()
    spike_lines.run(D)
    d2 = D + timedelta(days=41)
    monkeypatch.setitem(globals(), "SPIKE", (D + timedelta(days=5), "S01", "FC1"))     # a spike inside the gap
    _seed_db(scope, start=D + timedelta(days=1), end=d2)
    r2 = spike_lines.run(d2)
    assert not r2["flags"]["full"] and r2["flags"]["written_from"] == str(D)
    with db.read() as c:
        gap = db.rows(c, "SELECT computed_for FROM spike_flag_lines WHERE d=? AND sku_code='S01' AND customer_id='C1'",
                      (str(D + timedelta(days=5)),))
        mark = spike_lines.full_done(c, scope)
    assert gap == [{"computed_for": str(d2)}]
    assert mark["last_computed_for"] == str(d2) and mark["computed_for"] == str(D)
    d3 = d2 + timedelta(days=1)
    _seed_db(scope, start=d3, end=d3)
    r3 = spike_lines.run(d3)                                                          # next night: back to 30 days
    assert r3["flags"]["written_from"] == str(d3 - timedelta(days=30))
